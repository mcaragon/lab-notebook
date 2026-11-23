"""Problem reports and ideas sent from inside the app.

Reports are stored in the notebook's own database (nothing is sent anywhere). Admins read them in the Feedback inbox
of the admin dashboard, set a status and can write a reply the reporter sees. A report can carry one screenshot
(PNG, JPEG or WebP, stored as a blob and served only to its author and to admins).
"""
from __future__ import annotations

import base64
import re
from typing import Any, Optional

from . import auth

KINDS = ("bug", "idea", "question")
STATUSES = ("new", "open", "resolved", "wontfix")
MAX_IMAGE = 3 * 1024 * 1024          # bytes, after decoding
MAX_PER_DAY = 25                      # reports per account per day
_IMAGE_TYPES = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    kind TEXT NOT NULL DEFAULT 'bug',
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    steps TEXT, expected TEXT,
    page TEXT, version TEXT, user_agent TEXT, screen TEXT, theme TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    reply TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    replied_at TEXT, seen_reply_at TEXT
);
CREATE INDEX IF NOT EXISTS feedback_status ON feedback(status, id);
CREATE INDEX IF NOT EXISTS feedback_user ON feedback(user_id, id);
CREATE TABLE IF NOT EXISTS feedback_files (
    feedback_id INTEGER PRIMARY KEY REFERENCES feedback(id) ON DELETE CASCADE,
    mime TEXT NOT NULL,
    data BLOB NOT NULL
);
"""


class FeedbackError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def decode_image(data_url: str) -> tuple[str, bytes]:
    """A screenshot sent as a data URL -> (mime, bytes). Only PNG, JPEG and WebP; the content is checked."""
    m = re.match(r"^data:image/(png|jpeg|webp);base64,(.+)$", data_url or "", re.S)
    if not m:
        raise FeedbackError("The screenshot must be a PNG, JPEG or WebP image.")
    try:
        raw = base64.b64decode(m.group(2), validate=True)
    except ValueError:
        raise FeedbackError("The screenshot could not be read.")
    if len(raw) > MAX_IMAGE:
        raise FeedbackError("The screenshot is too large (3 MB at most).")
    for magic, mime in _IMAGE_TYPES.items():
        if raw.startswith(magic):
            return mime, raw
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp", raw
    raise FeedbackError("The screenshot must be a PNG, JPEG or WebP image.")


def _clip(v: Optional[str], n: int) -> Optional[str]:
    v = (v or "").strip()
    return v[:n] if v else None


class Feedback:
    def __init__(self, store: Any):
        self.store = store
        with store.conn() as c:
            c.executescript(SCHEMA)

    def conn(self):
        return self.store.conn()

    def create(self, user_id: int, data: dict, screenshot: Optional[str] = None) -> int:
        kind = data.get("kind") if data.get("kind") in KINDS else "bug"
        title = _clip(data.get("title"), 140)
        body = _clip(data.get("body"), 8000)
        if not title or not body:
            raise FeedbackError("Give the report a title and describe what happened.")
        since = auth.ts(auth.utcnow().replace(hour=0, minute=0, second=0, microsecond=0))
        with self.conn() as c:
            n = c.execute("SELECT COUNT(*) FROM feedback WHERE user_id = ? AND created_at >= ?",
                          (user_id, since)).fetchone()[0]
        if n >= MAX_PER_DAY:
            raise FeedbackError("That's a lot of reports for one day. Thank you! Please send more tomorrow.", 429)
        image = decode_image(screenshot) if screenshot else None
        now = auth.ts()
        with self.conn() as c:
            fid = c.execute(
                "INSERT INTO feedback (user_id, kind, title, body, steps, expected, page, version, user_agent, screen, "
                "theme, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, kind, title, body, _clip(data.get("steps"), 8000), _clip(data.get("expected"), 4000),
                 _clip(data.get("page"), 300), _clip(data.get("version"), 40), _clip(data.get("user_agent"), 400),
                 _clip(data.get("screen"), 60), _clip(data.get("theme"), 20), now, now)).lastrowid
            if image:
                c.execute("INSERT INTO feedback_files (feedback_id, mime, data) VALUES (?, ?, ?)", (fid, *image))
        return fid

    def _rows(self, where: str, args: tuple, limit: int = 200) -> list[dict]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT f.*, u.username, u.display_name, "
                "EXISTS(SELECT 1 FROM feedback_files x WHERE x.feedback_id = f.id) AS has_image "
                f"FROM feedback f LEFT JOIN users u ON u.id = f.user_id WHERE {where} ORDER BY f.id DESC LIMIT ?",
                (*args, limit)).fetchall()
        return [dict(r) | {"has_image": bool(r["has_image"])} for r in rows]

    def get(self, fid: int) -> Optional[dict]:
        rows = self._rows("f.id = ?", (fid,), 1)
        return rows[0] if rows else None

    def mine(self, user_id: int) -> list[dict]:
        out = self._rows("f.user_id = ?", (user_id,), 100)
        with self.conn() as c:  # replies are now seen
            c.execute("UPDATE feedback SET seen_reply_at = ? WHERE user_id = ? AND replied_at IS NOT NULL "
                      "AND (seen_reply_at IS NULL OR seen_reply_at < replied_at)", (auth.ts(), user_id))
        return out

    def unseen_replies(self, user_id: int) -> int:
        with self.conn() as c:
            return c.execute("SELECT COUNT(*) FROM feedback WHERE user_id = ? AND replied_at IS NOT NULL "
                             "AND (seen_reply_at IS NULL OR seen_reply_at < replied_at)", (user_id,)).fetchone()[0]

    def inbox(self, status: Optional[str] = None) -> list[dict]:
        if status in STATUSES:
            return self._rows("f.status = ?", (status,))
        if status == "active":
            return self._rows("f.status IN ('new', 'open')", ())
        return self._rows("1 = 1", ())

    def counts(self) -> dict:
        with self.conn() as c:
            rows = c.execute("SELECT status, COUNT(*) FROM feedback GROUP BY status").fetchall()
        out = {s: 0 for s in STATUSES}
        out.update({r[0]: r[1] for r in rows})
        return out

    def update(self, fid: int, status: Optional[str] = None, reply: Optional[str] = None) -> None:
        sets, args = ["updated_at = ?"], [auth.ts()]
        if status is not None:
            if status not in STATUSES:
                raise FeedbackError("Unknown status.")
            sets.append("status = ?")
            args.append(status)
        if reply is not None:
            sets += ["reply = ?", "replied_at = ?"]
            args += [_clip(reply, 4000), auth.ts() if reply.strip() else None]
        with self.conn() as c:
            c.execute(f"UPDATE feedback SET {', '.join(sets)} WHERE id = ?", (*args, fid))

    def delete(self, fid: int) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM feedback WHERE id = ?", (fid,))

    def image(self, fid: int) -> Optional[tuple[str, bytes]]:
        with self.conn() as c:
            row = c.execute("SELECT mime, data FROM feedback_files WHERE feedback_id = ?", (fid,)).fetchone()
        return (row["mime"], bytes(row["data"])) if row else None
