"""SQLite storage for experiments, reagents and log entries."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

SCHEMA_VERSION = 1

# Free-text sections of an experiment, in report order (key, heading)
SECTIONS = [
    ("objective", "Objective"),
    ("reaction_scheme", "Reaction"),
    ("procedure", "Procedure"),
    ("results", "Results"),
    ("discussion", "Discussion"),
    ("conclusion", "Conclusion"),
    ("references", "References"),
]
SECTION_KEYS = [k for k, _ in SECTIONS]
EXPERIMENT_FIELDS = ["title", "date", "author", "course", "status", *SECTION_KEYS]
STATUSES = ("planned", "in_progress", "completed")

# Chemical data columns that can come from PubChem Local (and be overridden by the user)
CHEM_FIELDS = ["name", "iupac_name", "cas", "formula", "smiles", "mw", "density", "bp", "mp", "flash_point",
               "refractive_index", "signal_word"]
JSON_FIELDS = ["pictograms", "hazard_statements", "sources"]
AMOUNT_FIELDS = ["role", "form", "purity", "concentration_m", "wt_percent", "solution_density", "coefficient",
                 "basis", "basis_value", "is_reference", "actual_mass_g", "notes"]
REAGENT_FIELDS = ["cid", "pubchem_url", *CHEM_FIELDS, *JSON_FIELDS, *AMOUNT_FIELDS]
ENTRY_KINDS = ("note", "observation", "measurement")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    date TEXT, author TEXT, course TEXT,
    status TEXT NOT NULL DEFAULT 'planned',
    objective TEXT, reaction_scheme TEXT, procedure TEXT, results TEXT,
    discussion TEXT, conclusion TEXT, "references" TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reagents (
    id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    cid INTEGER, pubchem_url TEXT,
    name TEXT, iupac_name TEXT, cas TEXT, formula TEXT, smiles TEXT,
    mw REAL, density REAL, bp REAL, mp REAL, flash_point REAL, refractive_index REAL,
    signal_word TEXT, pictograms TEXT, hazard_statements TEXT, sources TEXT,
    role TEXT NOT NULL DEFAULT 'reactant', form TEXT NOT NULL DEFAULT 'neat',
    purity REAL, concentration_m REAL, wt_percent REAL, solution_density REAL,
    coefficient REAL NOT NULL DEFAULT 1,
    basis TEXT, basis_value REAL, is_reference INTEGER NOT NULL DEFAULT 0,
    actual_mass_g REAL, notes TEXT
);
CREATE INDEX IF NOT EXISTS reagents_exp ON reagents(experiment_id, position);
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'note',
    text TEXT NOT NULL DEFAULT '',
    value TEXT, unit TEXT
);
CREATE INDEX IF NOT EXISTS entries_exp ON entries(experiment_id, ts);
"""


def now() -> str:
    """Local time with UTC offset (set TZ in the container)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _q(col: str) -> str:
    return f'"{col}"'


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript(_SCHEMA)
            c.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("PRAGMA journal_mode = WAL")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ----- experiments -----
    def list_experiments(self) -> list[dict]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT e.id, e.title, e.date, e.status, e.course, e.updated_at, "
                "(SELECT COUNT(*) FROM reagents r WHERE r.experiment_id = e.id) AS n_reagents "
                "FROM experiments e ORDER BY COALESCE(e.date, '') DESC, e.id DESC").fetchall()
        return [dict(r) for r in rows]

    def create_experiment(self, data: dict) -> int:
        vals = {k: data.get(k) for k in EXPERIMENT_FIELDS if data.get(k) is not None}
        vals.setdefault("title", "Untitled experiment")
        vals.setdefault("date", datetime.now().date().isoformat())
        vals.setdefault("status", "planned")
        vals["created_at"] = vals["updated_at"] = now()
        cols = ", ".join(_q(k) for k in vals)
        with self.conn() as c:
            cur = c.execute(f"INSERT INTO experiments ({cols}) VALUES ({', '.join('?' * len(vals))})",
                            list(vals.values()))
            return cur.lastrowid

    def get_experiment(self, exp_id: int) -> Optional[dict]:
        with self.conn() as c:
            row = c.execute("SELECT * FROM experiments WHERE id = ?", (exp_id,)).fetchone()
        return dict(row) if row else None

    def update_experiment(self, exp_id: int, data: dict) -> bool:
        vals = {k: data[k] for k in EXPERIMENT_FIELDS if k in data}
        vals["updated_at"] = now()
        sets = ", ".join(f"{_q(k)} = ?" for k in vals)
        with self.conn() as c:
            cur = c.execute(f"UPDATE experiments SET {sets} WHERE id = ?", [*vals.values(), exp_id])
            return cur.rowcount > 0

    def touch(self, exp_id: int) -> None:
        with self.conn() as c:
            c.execute("UPDATE experiments SET updated_at = ? WHERE id = ?", (now(), exp_id))

    def delete_experiment(self, exp_id: int) -> bool:
        with self.conn() as c:
            return c.execute("DELETE FROM experiments WHERE id = ?", (exp_id,)).rowcount > 0

    def duplicate_experiment(self, exp_id: int) -> Optional[int]:
        """Copy an experiment's plan (text and reagents, without amounts isolated or log entries)."""
        exp = self.get_experiment(exp_id)
        if not exp:
            return None
        data = {k: exp[k] for k in EXPERIMENT_FIELDS}
        data.update(title=f"{exp['title']} (copy)", status="planned", date=None, results=None,
                    discussion=None, conclusion=None)
        new_id = self.create_experiment(data)
        for r in self.list_reagents(exp_id):
            r = dict(r)
            r["actual_mass_g"] = None
            self.add_reagent(new_id, r)
        return new_id

    # ----- reagents -----
    @staticmethod
    def _reagent_out(row: sqlite3.Row) -> dict:
        d = dict(row)
        for k in JSON_FIELDS:
            d[k] = json.loads(d[k]) if d[k] else ({} if k == "sources" else [])
        d["is_reference"] = bool(d["is_reference"])
        return d

    @staticmethod
    def _reagent_in(data: dict) -> dict:
        vals = {k: data[k] for k in REAGENT_FIELDS if k in data}
        for k in JSON_FIELDS:
            if k in vals:
                vals[k] = json.dumps(vals[k] or ({} if k == "sources" else []))
        if "is_reference" in vals:
            vals["is_reference"] = 1 if vals["is_reference"] else 0
        return vals

    def list_reagents(self, exp_id: int) -> list[dict]:
        with self.conn() as c:
            rows = c.execute("SELECT * FROM reagents WHERE experiment_id = ? ORDER BY position, id",
                             (exp_id,)).fetchall()
        return [self._reagent_out(r) for r in rows]

    def get_reagent(self, rid: int) -> Optional[dict]:
        with self.conn() as c:
            row = c.execute("SELECT * FROM reagents WHERE id = ?", (rid,)).fetchone()
        return self._reagent_out(row) if row else None

    def add_reagent(self, exp_id: int, data: dict) -> int:
        vals = self._reagent_in(data)
        vals = {k: v for k, v in vals.items() if v is not None}
        with self.conn() as c:
            pos = c.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM reagents WHERE experiment_id = ?",
                            (exp_id,)).fetchone()[0]
            vals.update(experiment_id=exp_id, position=pos)
            cols = ", ".join(_q(k) for k in vals)
            cur = c.execute(f"INSERT INTO reagents ({cols}) VALUES ({', '.join('?' * len(vals))})",
                            list(vals.values()))
            rid = cur.lastrowid
            if data.get("is_reference"):
                c.execute("UPDATE reagents SET is_reference = 0 WHERE experiment_id = ? AND id != ?", (exp_id, rid))
        self.touch(exp_id)
        return rid

    def update_reagent(self, rid: int, data: dict) -> Optional[dict]:
        cur_row = self.get_reagent(rid)
        if not cur_row:
            return None
        vals = self._reagent_in(data)
        if vals:
            sets = ", ".join(f"{_q(k)} = ?" for k in vals)
            with self.conn() as c:
                c.execute(f"UPDATE reagents SET {sets} WHERE id = ?", [*vals.values(), rid])
                if data.get("is_reference"):
                    c.execute("UPDATE reagents SET is_reference = 0 WHERE experiment_id = ? AND id != ?",
                              (cur_row["experiment_id"], rid))
            self.touch(cur_row["experiment_id"])
        return self.get_reagent(rid)

    def delete_reagent(self, rid: int) -> bool:
        r = self.get_reagent(rid)
        if not r:
            return False
        with self.conn() as c:
            c.execute("DELETE FROM reagents WHERE id = ?", (rid,))
        self.touch(r["experiment_id"])
        return True

    def reorder_reagents(self, exp_id: int, ids: list[int]) -> None:
        with self.conn() as c:
            for pos, rid in enumerate(ids):
                c.execute("UPDATE reagents SET position = ? WHERE id = ? AND experiment_id = ?", (pos, rid, exp_id))

    # ----- log entries -----
    def list_entries(self, exp_id: int) -> list[dict]:
        with self.conn() as c:
            rows = c.execute("SELECT * FROM entries WHERE experiment_id = ? ORDER BY ts, id", (exp_id,)).fetchall()
        return [dict(r) for r in rows]

    def add_entry(self, exp_id: int, data: dict) -> int:
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO entries (experiment_id, ts, kind, text, value, unit) VALUES (?, ?, ?, ?, ?, ?)",
                (exp_id, data.get("ts") or now(), data.get("kind") or "note", data.get("text") or "",
                 data.get("value"), data.get("unit")))
        self.touch(exp_id)
        return cur.lastrowid

    def get_entry(self, eid: int) -> Optional[dict]:
        with self.conn() as c:
            row = c.execute("SELECT * FROM entries WHERE id = ?", (eid,)).fetchone()
        return dict(row) if row else None

    def update_entry(self, eid: int, data: dict) -> Optional[dict]:
        e = self.get_entry(eid)
        if not e:
            return None
        vals = {k: data[k] for k in ("ts", "kind", "text", "value", "unit") if k in data}
        if vals:
            sets = ", ".join(f"{k} = ?" for k in vals)
            with self.conn() as c:
                c.execute(f"UPDATE entries SET {sets} WHERE id = ?", [*vals.values(), eid])
            self.touch(e["experiment_id"])
        return self.get_entry(eid)

    def delete_entry(self, eid: int) -> bool:
        e = self.get_entry(eid)
        if not e:
            return False
        with self.conn() as c:
            c.execute("DELETE FROM entries WHERE id = ?", (eid,))
        self.touch(e["experiment_id"])
        return True


def stoich_rows(reagents: list[dict]) -> list[dict]:
    return [{k: r.get(k) for k in ("id", "role", "form", "mw", "density", "mp", "purity", "concentration_m", "wt_percent",
                                   "solution_density", "coefficient", "basis", "basis_value", "is_reference",
                                   "actual_mass_g")} for r in reagents]

