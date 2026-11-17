"""SQLite storage.

An experiment has reaction steps (each with condition stages and its own reagents), procedure rows, a log of
entries, timers and reference rows. Schema version 2; version 1 databases are migrated on open.
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

SCHEMA_VERSION = 2

# Free-text sections of an experiment (key, heading)
SECTIONS = [
    ("objective", "Objective"),
    ("results", "Results"),
    ("discussion", "Discussion"),
    ("conclusion", "Conclusion"),
]
SECTION_KEYS = [k for k, _ in SECTIONS]
STATUSES = ("planned", "in_progress", "completed")
SCHEME_STYLES = ("auto", "inline", "lettered")

# Chemical data columns that can come from PubChem Local (and be overridden by the user)
CHEM_FIELDS = ["name", "iupac_name", "cas", "formula", "smiles", "mw", "density", "bp", "mp", "flash_point",
               "refractive_index", "signal_word"]
JSON_FIELDS = {"pictograms": list, "hazard_statements": list, "sources": dict, "data": dict, "extra_hazards": dict}

# Writable columns per table
FIELDS = {
    "experiments": ["title", "date", "author", "course", "status", "scheme_style", "started_at", "ended_at",
                    *SECTION_KEYS],
    "steps": ["title", "notes", "atmosphere", "position"],
    "conditions": ["step_id", "temperature", "duration", "note", "position"],
    "reagents": ["step_id", "position", "cid", "pubchem_url", *CHEM_FIELDS, "pictograms", "hazard_statements",
                 "sources", "extra_hazards", "hazard_notes", "label", "role", "form", "purity", "concentration_m", "wt_percent", "solution_density",
                 "coefficient", "basis", "basis_value", "is_reference", "actual_basis", "actual_value",
                 "actual_mass_g", "crude_mass_g", "expected_yield_pct", "expected_ref_id", "source_reagent_id",
                 "scheme_pos", "grade", "supplier", "lot", "notes"],
    "procedure": ["step_id", "position", "text", "notes", "done_at"],
    "entries": ["ts", "elapsed_s", "kind", "action", "text", "value", "unit", "data", "custom_text", "step_id",
                "procedure_id", "timer_id"],
    "timers": ["label", "kind", "started_at", "duration_s", "stopped_at", "elapsed_s", "start_entry_id",
               "stop_entry_id", "procedure_id", "reagent_id"],
    "refs": ["position", "authors", "title", "source", "year", "volume", "pages", "doi", "url", "text"],
}
BOOL_FIELDS = {"is_reference", "custom_text"}
# Tables whose rows belong directly to an experiment (others belong to a step)
EXP_CHILDREN = ("steps", "reagents", "procedure", "entries", "timers", "refs")

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
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'note',
    text TEXT NOT NULL DEFAULT '',
    value TEXT, unit TEXT
);
"""

_V2 = """
ALTER TABLE experiments ADD COLUMN scheme_style TEXT NOT NULL DEFAULT 'auto';
ALTER TABLE experiments ADD COLUMN started_at TEXT;
ALTER TABLE experiments ADD COLUMN ended_at TEXT;
CREATE TABLE steps (
    id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    title TEXT, notes TEXT, atmosphere TEXT
);
CREATE TABLE conditions (
    id INTEGER PRIMARY KEY,
    step_id INTEGER NOT NULL REFERENCES steps(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    temperature TEXT, duration TEXT, note TEXT
);
ALTER TABLE reagents ADD COLUMN step_id INTEGER REFERENCES steps(id) ON DELETE CASCADE;
ALTER TABLE reagents ADD COLUMN label TEXT;
ALTER TABLE reagents ADD COLUMN actual_basis TEXT;
ALTER TABLE reagents ADD COLUMN actual_value REAL;
ALTER TABLE reagents ADD COLUMN crude_mass_g REAL;
ALTER TABLE reagents ADD COLUMN expected_yield_pct REAL;
ALTER TABLE reagents ADD COLUMN expected_ref_id INTEGER;
ALTER TABLE reagents ADD COLUMN source_reagent_id INTEGER;
ALTER TABLE reagents ADD COLUMN scheme_pos TEXT NOT NULL DEFAULT 'auto';
ALTER TABLE reagents ADD COLUMN grade TEXT;
ALTER TABLE reagents ADD COLUMN supplier TEXT;
ALTER TABLE reagents ADD COLUMN lot TEXT;
ALTER TABLE reagents ADD COLUMN extra_hazards TEXT;
ALTER TABLE reagents ADD COLUMN hazard_notes TEXT;
CREATE TABLE procedure (
    id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    step_id INTEGER REFERENCES steps(id) ON DELETE SET NULL,
    position INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL DEFAULT '', notes TEXT, done_at TEXT
);
ALTER TABLE entries ADD COLUMN elapsed_s REAL;
ALTER TABLE entries ADD COLUMN action TEXT;
ALTER TABLE entries ADD COLUMN data TEXT;
ALTER TABLE entries ADD COLUMN custom_text INTEGER NOT NULL DEFAULT 0;
ALTER TABLE entries ADD COLUMN step_id INTEGER;
ALTER TABLE entries ADD COLUMN procedure_id INTEGER;
ALTER TABLE entries ADD COLUMN timer_id INTEGER;
CREATE TABLE timers (
    id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    label TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'stopwatch',
    started_at TEXT NOT NULL, duration_s REAL, stopped_at TEXT, elapsed_s REAL,
    start_entry_id INTEGER, stop_entry_id INTEGER, procedure_id INTEGER, reagent_id INTEGER
);
CREATE TABLE refs (
    id INTEGER PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    authors TEXT, title TEXT, source TEXT, year TEXT, volume TEXT, pages TEXT, doi TEXT, url TEXT, text TEXT
);
CREATE INDEX IF NOT EXISTS reagents_exp_step ON reagents(experiment_id, step_id, position);
CREATE INDEX IF NOT EXISTS entries_exp ON entries(experiment_id, ts);
CREATE INDEX IF NOT EXISTS procedure_exp ON procedure(experiment_id, position);
CREATE INDEX IF NOT EXISTS steps_exp ON steps(experiment_id, position);
"""


def now() -> str:
    """Local time with UTC offset (set TZ in the container)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return d if d.tzinfo else d.astimezone()


def elapsed_between(start: Optional[str], end: Optional[str]) -> Optional[float]:
    a, b = parse_ts(start), parse_ts(end)
    return (b - a).total_seconds() if a and b else None


def _q(col: str) -> str:
    return f'"{col}"'


_NUMBERED = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+")


def split_procedure(text: str) -> list[str]:
    """Split a v1 free-text procedure into steps: numbered/bulleted lines start a step, blank lines separate."""
    steps: list[str] = []
    cur: list[str] = []
    for line in (text or "").splitlines():
        if not line.strip():
            if cur:
                steps.append(" ".join(cur))
                cur = []
            continue
        if _NUMBERED.match(line) and cur:
            steps.append(" ".join(cur))
            cur = []
        cur.append(_NUMBERED.sub("", line).strip())
    if cur:
        steps.append(" ".join(cur))
    return [s for s in steps if s]


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            version = c.execute("PRAGMA user_version").fetchone()[0]
            fresh = not c.execute("SELECT 1 FROM sqlite_master WHERE name = 'experiments'").fetchone()
            c.executescript(_SCHEMA)
            if version < 2:
                c.executescript(_V2)
                if not fresh:
                    self._migrate_v1(c)
            c.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @staticmethod
    def _migrate_v1(c: sqlite3.Connection) -> None:
        for exp in c.execute("SELECT * FROM experiments").fetchall():
            eid = exp["id"]
            sid = c.execute("INSERT INTO steps (experiment_id, position, notes) VALUES (?, 0, ?)",
                            (eid, exp["reaction_scheme"])).lastrowid
            c.execute("UPDATE reagents SET step_id = ? WHERE experiment_id = ?", (sid, eid))
            for pos, text in enumerate(split_procedure(exp["procedure"])):
                c.execute("INSERT INTO procedure (experiment_id, step_id, position, text) VALUES (?, ?, ?, ?)",
                          (eid, sid, pos, text))
            refs = [line.strip() for line in (exp["references"] or "").splitlines() if line.strip()]
            for pos, text in enumerate(refs):
                c.execute("INSERT INTO refs (experiment_id, position, text) VALUES (?, ?, ?)",
                          (eid, pos, _NUMBERED.sub("", text)))
            # v1 stored a product's isolated mass in actual_mass_g; that is still its meaning
        c.execute("UPDATE entries SET action = kind")
        c.execute("UPDATE reagents SET role = 'workup' WHERE role = 'other'")

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

    # ------------------------------------------------------------------ generic helpers
    @staticmethod
    def _out(row: Optional[sqlite3.Row]) -> Optional[dict]:
        if row is None:
            return None
        d = dict(row)
        for k, typ in JSON_FIELDS.items():
            if k in d:
                d[k] = json.loads(d[k]) if d[k] else typ()
        for k in BOOL_FIELDS:
            if k in d:
                d[k] = bool(d[k])
        return d

    @staticmethod
    def _in(table: str, data: dict) -> dict:
        vals = {k: data[k] for k in FIELDS[table] if k in data}
        for k, typ in JSON_FIELDS.items():
            if k in vals:
                vals[k] = json.dumps(vals[k] if vals[k] is not None else typ())
        for k in BOOL_FIELDS:
            if k in vals:
                vals[k] = 1 if vals[k] else 0
        return vals

    def get(self, table: str, rid: int) -> Optional[dict]:
        with self.conn() as c:
            return self._out(c.execute(f"SELECT * FROM {table} WHERE id = ?", (rid,)).fetchone())

    def list(self, table: str, where: str, args: Iterable, order: Optional[str] = None) -> list[dict]:
        order = order or ("position, id" if "position" in FIELDS[table] else "id")
        with self.conn() as c:
            rows = c.execute(f"SELECT * FROM {table} WHERE {where} ORDER BY {order}", tuple(args)).fetchall()
        return [self._out(r) for r in rows]

    def insert(self, table: str, data: dict, **fixed: Any) -> int:
        vals = {k: v for k, v in self._in(table, data).items() if v is not None}
        vals.update(fixed)
        with self.conn() as c:
            if "position" in FIELDS[table] and "position" not in vals:
                scope = "experiment_id" if "experiment_id" in vals else "step_id"
                vals["position"] = c.execute(
                    f"SELECT COALESCE(MAX(position), -1) + 1 FROM {table} WHERE {scope} = ?",
                    (vals[scope],)).fetchone()[0]
            cols = ", ".join(_q(k) for k in vals)
            return c.execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' * len(vals))})",
                             list(vals.values())).lastrowid

    def update(self, table: str, rid: int, data: dict) -> None:
        vals = self._in(table, data)
        if not vals:
            return
        sets = ", ".join(f"{_q(k)} = ?" for k in vals)
        with self.conn() as c:
            c.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*vals.values(), rid])

    def delete(self, table: str, rid: int) -> bool:
        with self.conn() as c:
            return c.execute(f"DELETE FROM {table} WHERE id = ?", (rid,)).rowcount > 0

    def reorder(self, table: str, ids: list[int], scope_col: str, scope_id: int) -> None:
        with self.conn() as c:
            for pos, rid in enumerate(ids):
                c.execute(f"UPDATE {table} SET position = ? WHERE id = ? AND {scope_col} = ?", (pos, rid, scope_id))

    def experiment_of(self, table: str, rid: int) -> Optional[int]:
        """Experiment id that owns a row of any table."""
        with self.conn() as c:
            if table == "conditions":
                row = c.execute("SELECT s.experiment_id FROM conditions k JOIN steps s ON s.id = k.step_id "
                                "WHERE k.id = ?", (rid,)).fetchone()
            else:
                row = c.execute(f"SELECT experiment_id FROM {table} WHERE id = ?", (rid,)).fetchone()
        return row[0] if row else None

    def touch(self, exp_id: int) -> None:
        with self.conn() as c:
            c.execute("UPDATE experiments SET updated_at = ? WHERE id = ?", (now(), exp_id))

    # ------------------------------------------------------------------ experiments
    def list_experiments(self) -> list[dict]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT e.id, e.title, e.date, e.status, e.course, e.updated_at, "
                "(SELECT COUNT(*) FROM steps s WHERE s.experiment_id = e.id) AS n_steps, "
                "(SELECT COUNT(*) FROM reagents r WHERE r.experiment_id = e.id) AS n_reagents "
                "FROM experiments e ORDER BY COALESCE(e.date, '') DESC, e.id DESC").fetchall()
        return [dict(r) for r in rows]

    def create_experiment(self, data: dict) -> int:
        vals = {k: v for k, v in self._in("experiments", data).items() if v is not None}
        vals.setdefault("title", "Untitled experiment")
        vals.setdefault("date", datetime.now().date().isoformat())
        vals.setdefault("status", "planned")
        vals["created_at"] = vals["updated_at"] = now()
        cols = ", ".join(_q(k) for k in vals)
        with self.conn() as c:
            eid = c.execute(f"INSERT INTO experiments ({cols}) VALUES ({', '.join('?' * len(vals))})",
                            list(vals.values())).lastrowid
        self.insert("steps", {}, experiment_id=eid)
        return eid

    def get_experiment(self, exp_id: int) -> Optional[dict]:
        exp = self.get("experiments", exp_id)
        if exp:
            for k in ("reaction_scheme", "procedure", "references"):  # v1 columns, migrated
                exp.pop(k, None)
        return exp

    def update_experiment(self, exp_id: int, data: dict) -> None:
        self.update("experiments", exp_id, data)
        self.touch(exp_id)

    def delete_experiment(self, exp_id: int) -> bool:
        return self.delete("experiments", exp_id)

    def bundle(self, exp_id: int) -> Optional[dict]:
        """Everything belonging to an experiment."""
        exp = self.get_experiment(exp_id)
        if not exp:
            return None
        steps = self.list("steps", "experiment_id = ?", (exp_id,))
        conds = self.list("conditions", "step_id IN (SELECT id FROM steps WHERE experiment_id = ?)", (exp_id,))
        for s in steps:
            s["conditions"] = [k for k in conds if k["step_id"] == s["id"]]
        return {
            "experiment": exp,
            "steps": steps,
            "reagents": self.list("reagents", "experiment_id = ?", (exp_id,)),
            "procedure": self.list("procedure", "experiment_id = ?", (exp_id,)),
            "entries": self.list("entries", "experiment_id = ?", (exp_id,), order="ts, id"),
            "timers": self.list("timers", "experiment_id = ?", (exp_id,), order="started_at, id"),
            "refs": self.list("refs", "experiment_id = ?", (exp_id,)),
        }

    def duplicate_experiment(self, exp_id: int) -> Optional[int]:
        """Copy the plan: text, steps, conditions, reagents (planned amounts only), procedure and references."""
        b = self.bundle(exp_id)
        if not b:
            return None
        exp = b["experiment"]
        data = {k: exp.get(k) for k in FIELDS["experiments"] if k not in ("started_at", "ended_at")}
        data.update(title=f"{exp['title']} (copy)", status="planned", date=None, results=None, discussion=None,
                    conclusion=None)
        new_id = self.create_experiment(data)
        with self.conn() as c:
            c.execute("DELETE FROM steps WHERE experiment_id = ?", (new_id,))
        step_map, ref_map, reagent_map = {}, {}, {}
        for r in b["refs"]:
            ref_map[r["id"]] = self.insert("refs", r, experiment_id=new_id)
        for s in b["steps"]:
            step_map[s["id"]] = self.insert("steps", s, experiment_id=new_id)
            for k in s["conditions"]:
                self.insert("conditions", {**k, "step_id": step_map[s["id"]]})
        for r in b["reagents"]:
            r = dict(r, actual_basis=None, actual_value=None, actual_mass_g=None, crude_mass_g=None,
                     step_id=step_map.get(r["step_id"]), expected_ref_id=ref_map.get(r.get("expected_ref_id")),
                     source_reagent_id=None)
            reagent_map[r["id"]] = self.insert("reagents", r, experiment_id=new_id)
        for r in b["reagents"]:
            if r.get("source_reagent_id") in reagent_map:
                self.update("reagents", reagent_map[r["id"]],
                            {"source_reagent_id": reagent_map[r["source_reagent_id"]]})
        for p in b["procedure"]:
            self.insert("procedure", dict(p, done_at=None, step_id=step_map.get(p["step_id"])),
                        experiment_id=new_id)
        return new_id

    # ------------------------------------------------------------------ reagents
    def add_reagent(self, exp_id: int, data: dict) -> int:
        rid = self.insert("reagents", data, experiment_id=exp_id)
        if data.get("is_reference"):
            self._single_reference(rid)
        self.touch(exp_id)
        return rid

    def update_reagent(self, rid: int, data: dict) -> None:
        self.update("reagents", rid, data)
        if data.get("is_reference"):
            self._single_reference(rid)

    def _single_reference(self, rid: int) -> None:
        """Only one reference reagent per step."""
        with self.conn() as c:
            row = c.execute("SELECT experiment_id, step_id FROM reagents WHERE id = ?", (rid,)).fetchone()
            c.execute("UPDATE reagents SET is_reference = 0 WHERE experiment_id = ? AND step_id IS ? AND id != ?",
                      (row["experiment_id"], row["step_id"], rid))


def stoich_rows(reagents: list[dict]) -> list[dict]:
    keys = ("id", "role", "form", "mw", "density", "mp", "purity", "concentration_m", "wt_percent",
            "solution_density", "coefficient", "basis", "basis_value", "is_reference", "actual_basis",
            "actual_value", "actual_mass_g", "crude_mass_g", "expected_yield_pct")
    return [{k: r.get(k) for k in keys} for r in reagents]
