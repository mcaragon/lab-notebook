"""Accounts: users, password hashing, sessions, invites and sign-in throttling.

Every account has its own notebook (experiments and projects carry an ``owner_id``). Admins manage accounts from the
admin dashboard; they do not open other people's experiments.

Passwords are hashed with scrypt (standard library). Sessions are random tokens kept in a cookie; only their SHA-256
is stored. Invites are one-time links that let someone create their own account. Failed sign-ins are throttled per
user name and per address.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

ROLES = ("admin", "user")
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$")
MIN_PASSWORD = 10
MAX_PASSWORD = 256
# Throttling: this many failures within the window lock the user name (or the address) until the window passes
WINDOW = timedelta(minutes=15)
MAX_FAILS_USER = 8
MAX_FAILS_IP = 25
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


class AuthError(Exception):
    """A refusal with a message for the user (and an HTTP status)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ts(d: Optional[datetime] = None) -> str:
    return (d or utcnow()).isoformat(timespec="seconds")


def parse(v: Optional[str]) -> Optional[datetime]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(v)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------------------------------------ passwords
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${b64(salt)}${b64(h)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, h = stored.split("$")
        if algo != "scrypt":
            return False
        want = base64.b64decode(h)
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), dklen=len(want),
                             n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, want)


_DUMMY = hash_password(secrets.token_hex(8))  # verified against for unknown users, so timing does not tell


def check_password_rules(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(f"Use a password of at least {MIN_PASSWORD} characters.")
    if len(password) > MAX_PASSWORD:
        raise AuthError("That password is too long.")


def check_username(username: str) -> str:
    u = (username or "").strip()
    if not USERNAME_RE.match(u):
        raise AuthError("User names have 3–32 characters: letters, digits, dot, dash or underscore.")
    return u


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ------------------------------------------------------------------------------------------------ store
class Auth:
    def __init__(self, store: Any, session_days: int = 30):
        self.store = store
        self.session_days = session_days
        self.setup_code: Optional[str] = None

    def conn(self):
        return self.store.conn()

    # users ------------------------------------------------------------------------------------------
    def has_users(self) -> bool:
        with self.conn() as c:
            return c.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def get_user(self, uid: int) -> Optional[dict]:
        with self.conn() as c:
            row = c.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        return dict(row) if row else None

    def find_user(self, username: str) -> Optional[dict]:
        with self.conn() as c:
            row = c.execute("SELECT * FROM users WHERE username = ?", ((username or "").strip(),)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def public(u: dict) -> dict:
        return {k: u.get(k) for k in ("id", "username", "display_name", "role", "active", "demo", "expires_at",
                                      "max_experiments", "created_at", "last_login_at", "last_seen_at")} | {
            "active": bool(u.get("active")), "demo": bool(u.get("demo")), "is_admin": u.get("role") == "admin"}

    @staticmethod
    def refusal(u: dict) -> Optional[str]:
        """Why this account cannot be used now (None if it can)."""
        if not u.get("active"):
            return "This account is disabled."
        exp = parse(u.get("expires_at"))
        if exp and exp <= utcnow():
            return "This demo account has expired."
        return None

    def create_user(self, username: str, password: str, display_name: str = "", role: str = "user",
                    demo: bool = False, expires_at: Optional[str] = None,
                    max_experiments: Optional[int] = None) -> int:
        username = check_username(username)
        check_password_rules(password)
        if role not in ROLES:
            raise AuthError("Unknown role.")
        if self.find_user(username):
            raise AuthError("That user name is taken.", 409)
        first = not self.has_users()
        with self.conn() as c:
            uid = c.execute(
                "INSERT INTO users (username, display_name, password_hash, role, demo, expires_at, max_experiments, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (username, (display_name or username).strip()[:80], hash_password(password), role, int(bool(demo)),
                 expires_at, max_experiments, ts())).lastrowid
            if first:  # the notebook as it was before accounts belongs to the first admin
                c.execute("UPDATE experiments SET owner_id = ? WHERE owner_id IS NULL", (uid,))
                c.execute("UPDATE projects SET owner_id = ? WHERE owner_id IS NULL", (uid,))
        return uid

    def update_user(self, uid: int, fields: dict) -> None:
        allowed = {k: v for k, v in fields.items()
                   if k in ("display_name", "role", "active", "demo", "expires_at", "max_experiments")}
        if "role" in allowed and allowed["role"] not in ROLES:
            raise AuthError("Unknown role.")
        for k in ("active", "demo"):
            if k in allowed:
                allowed[k] = int(bool(allowed[k]))
        if not allowed:
            return
        with self.conn() as c:
            c.execute(f"UPDATE users SET {', '.join(f'{k} = ?' for k in allowed)} WHERE id = ?",
                      [*allowed.values(), uid])
        if allowed.get("active") == 0:
            self.end_sessions(uid)

    def set_password(self, uid: int, password: str) -> None:
        check_password_rules(password)
        with self.conn() as c:
            c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), uid))

    def delete_user_data(self, uid: int) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM projects WHERE owner_id = ?", (uid,))
            c.execute("DELETE FROM experiments WHERE owner_id = ?", (uid,))

    def delete_user(self, uid: int) -> None:
        self.delete_user_data(uid)
        with self.conn() as c:
            c.execute("DELETE FROM users WHERE id = ?", (uid,))

    def admins(self) -> int:
        with self.conn() as c:
            return c.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1").fetchone()[0]

    # sign-in ----------------------------------------------------------------------------------------
    def record_attempt(self, username: str, ip: Optional[str], ok: bool, reason: str = "") -> None:
        with self.conn() as c:
            c.execute("INSERT INTO login_attempts (ts, username, ip, ok, reason) VALUES (?, ?, ?, ?, ?)",
                      (ts(), (username or "")[:64], ip, int(ok), reason))
            c.execute("DELETE FROM login_attempts WHERE id NOT IN (SELECT id FROM login_attempts ORDER BY id DESC "
                      "LIMIT 2000)")

    def lockout(self, username: str, ip: Optional[str]) -> Optional[int]:
        """Minutes until sign-in is allowed again, or None."""
        since = ts(utcnow() - WINDOW)
        with self.conn() as c:
            by_user = c.execute("SELECT ts FROM login_attempts WHERE ok = 0 AND username = ? COLLATE NOCASE "
                                "AND ts > ? ORDER BY ts", ((username or "").strip(), since)).fetchall()
            by_ip = c.execute("SELECT ts FROM login_attempts WHERE ok = 0 AND ip = ? AND ts > ? ORDER BY ts",
                              (ip, since)).fetchall() if ip else []
        for rows, limit in ((by_user, MAX_FAILS_USER), (by_ip, MAX_FAILS_IP)):
            if len(rows) >= limit:
                until = parse(rows[-limit][0]) + WINDOW
                return max(1, int((until - utcnow()).total_seconds() // 60) + 1)
        return None

    def login(self, username: str, password: str, ip: Optional[str], user_agent: str = "") -> tuple[dict, str]:
        wait = self.lockout(username, ip)
        if wait:
            self.record_attempt(username, ip, False, "throttled")
            raise AuthError(f"Too many failed sign-ins. Try again in {wait} minute{'s' if wait != 1 else ''}.", 429)
        u = self.find_user(username)
        if not verify_password(password or "", u["password_hash"] if u else _DUMMY) or not u:
            self.record_attempt(username, ip, False, "wrong password" if u else "unknown user")
            raise AuthError("Wrong user name or password.", 401)
        why = self.refusal(u)
        if why:
            self.record_attempt(username, ip, False, why)
            raise AuthError(why, 403)
        self.record_attempt(u["username"], ip, True)
        with self.conn() as c:
            c.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (ts(), u["id"]))
        return u, self.new_session(u["id"], ip, user_agent)

    # sessions ---------------------------------------------------------------------------------------
    def new_session(self, uid: int, ip: Optional[str] = None, user_agent: str = "") -> str:
        token = secrets.token_urlsafe(32)
        now = utcnow()
        with self.conn() as c:
            c.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (ts(now), uid))
            c.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_seen_at, ip, user_agent) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (token_hash(token), uid, ts(now), ts(now + timedelta(days=self.session_days)), ts(now), ip,
                       (user_agent or "")[:200]))
            c.execute("DELETE FROM sessions WHERE expires_at < ?", (ts(now),))
        return token

    def session_user(self, token: Optional[str]) -> Optional[dict]:
        """The user of a valid session (sessions slide: each use, at most hourly, extends them)."""
        if not token:
            return None
        h = token_hash(token)
        now = utcnow()
        with self.conn() as c:
            row = c.execute("SELECT user_id, expires_at, last_seen_at FROM sessions WHERE token_hash = ?",
                            (h,)).fetchone()
            if not row:
                return None
            if parse(row["expires_at"]) <= now:
                c.execute("DELETE FROM sessions WHERE token_hash = ?", (h,))
                return None
            seen = parse(row["last_seen_at"])
            if not seen or now - seen > timedelta(hours=1):
                c.execute("UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE token_hash = ?",
                          (ts(now), ts(now + timedelta(days=self.session_days)), h))
                c.execute("UPDATE users SET last_seen_at = ? WHERE id = ?", (ts(now), row["user_id"]))
        user = self.get_user(row["user_id"])
        return user if user and not self.refusal(user) else None

    def end_session(self, token: Optional[str]) -> None:
        if token:
            with self.conn() as c:
                c.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))

    def end_sessions(self, uid: int, keep: Optional[str] = None) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash IS NOT ?",
                      (uid, token_hash(keep) if keep else None))

    # first start ------------------------------------------------------------------------------------
    def new_setup_code(self) -> str:
        self.setup_code = "-".join(secrets.token_hex(3).upper() for _ in range(3))
        return self.setup_code

    def check_setup_code(self, code: str) -> bool:
        return bool(self.setup_code) and hmac.compare_digest((code or "").strip().upper(), self.setup_code)

    # invites ----------------------------------------------------------------------------------------
    def create_invite(self, created_by: int, role: str = "user", demo: bool = True,
                      max_experiments: Optional[int] = None, account_days: Optional[int] = None,
                      valid_days: int = 7, note: str = "") -> tuple[int, str]:
        if role not in ROLES:
            raise AuthError("Unknown role.")
        token = secrets.token_urlsafe(24)
        with self.conn() as c:
            iid = c.execute(
                "INSERT INTO invites (token_hash, created_by, note, role, demo, max_experiments, account_days, "
                "created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (token_hash(token), created_by, (note or "")[:120], role, int(bool(demo)), max_experiments,
                 account_days, ts(), ts(utcnow() + timedelta(days=max(1, min(valid_days, 90)))))).lastrowid
        return iid, token

    def invite(self, token: str) -> Optional[dict]:
        """An invite that can still be used."""
        with self.conn() as c:
            row = c.execute("SELECT * FROM invites WHERE token_hash = ?", (token_hash(token or ""),)).fetchone()
        if not row or row["used_at"] or parse(row["expires_at"]) <= utcnow():
            return None
        return dict(row)

    def accept_invite(self, token: str, username: str, password: str, display_name: str = "") -> int:
        inv = self.invite(token)
        if not inv:
            raise AuthError("This invite link is not valid (it may have been used or have expired).", 404)
        expires = ts(utcnow() + timedelta(days=inv["account_days"])) if inv["account_days"] else None
        uid = self.create_user(username, password, display_name, inv["role"], bool(inv["demo"]), expires,
                               inv["max_experiments"])
        with self.conn() as c:
            c.execute("UPDATE invites SET used_at = ?, used_by = ? WHERE id = ?", (ts(), uid, inv["id"]))
        return uid

    def list_invites(self) -> list[dict]:
        with self.conn() as c:
            rows = c.execute("SELECT i.id, i.note, i.role, i.demo, i.max_experiments, i.account_days, i.created_at, "
                             "i.expires_at, i.used_at, u.username AS used_by FROM invites i "
                             "LEFT JOIN users u ON u.id = i.used_by ORDER BY i.id DESC LIMIT 100").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["demo"] = bool(d["demo"])
            d["status"] = "used" if d["used_at"] else "expired" if parse(d["expires_at"]) <= utcnow() else "open"
            out.append(d)
        return out

    def revoke_invite(self, iid: int) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM invites WHERE id = ? AND used_at IS NULL", (iid,))

    # admin overview ---------------------------------------------------------------------------------
    def users_overview(self) -> list[dict]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT u.*, "
                "(SELECT COUNT(*) FROM experiments e WHERE e.owner_id = u.id) AS n_experiments, "
                "(SELECT COUNT(*) FROM projects p WHERE p.owner_id = u.id) AS n_projects, "
                "(SELECT MAX(e.updated_at) FROM experiments e WHERE e.owner_id = u.id) AS last_change, "
                "(SELECT COUNT(*) FROM sessions s WHERE s.user_id = u.id AND s.expires_at > ?) AS n_sessions "
                "FROM users u ORDER BY u.role = 'admin' DESC, u.username", (ts(),)).fetchall()
        return [self.public(dict(r)) | {k: r[k] for k in ("n_experiments", "n_projects", "last_change", "n_sessions")}
                for r in rows]

    def user_experiments(self, uid: int) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT id, title, date, status, updated_at FROM experiments WHERE owner_id = ? "
                "ORDER BY updated_at DESC LIMIT 200", (uid,))]

    def recent_attempts(self, limit: int = 60) -> list[dict]:
        with self.conn() as c:
            return [dict(r) | {"ok": bool(r["ok"])} for r in c.execute(
                "SELECT ts, username, ip, ok, reason FROM login_attempts ORDER BY id DESC LIMIT ?", (limit,))]

    def recent_changes(self, limit: int = 30) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT e.id, e.title, e.updated_at, u.username FROM experiments e LEFT JOIN users u "
                "ON u.id = e.owner_id ORDER BY e.updated_at DESC LIMIT ?", (limit,))]
