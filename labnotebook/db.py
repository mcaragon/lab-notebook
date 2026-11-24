"""SQLite storage.

An experiment is one reaction: one arrow in a scheme, with one or more one-pot *stages* (table ``steps``; each has
condition rows and its own reagents), procedure rows grouped into *phases* (setup, reaction, workup, purification,
analysis and the experiment's own), a log of entries, timers and reference rows.

A *project* groups experiments into a route. Experiments are linked by material: a starting material whose
``source_reagent_id`` is the product of another experiment is a portion of that product. Links make the route a
graph, so routes can branch (one product used in several experiments) and converge.

Accounts (schema version 4): every experiment and project has an owner (``owner_id``); users only see their own.
Users, sessions, invites and sign-in attempts are stored here too (see ``auth.py``).

Schema version 5 (the stockroom: see ``stockroom.py``); older databases are migrated on open (v2 multi-step experiments are split into one experiment per
step, linked through their intermediates and grouped into a project).
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

SCHEMA_VERSION = 5

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
# Procedure phases every experiment has (shown only when they have rows); experiments can add their own
PHASES = [("setup", "Setup"), ("reaction", "Reaction"), ("workup", "Workup"), ("purification", "Purification"),
          ("analysis", "Analysis")]
DEFAULT_PHASE = "reaction"

# Chemical data columns that can come from PubChem Local (and be overridden by the user)
CHEM_FIELDS = ["name", "iupac_name", "cas", "formula", "smiles", "mw", "density", "bp", "mp", "flash_point",
               "refractive_index", "signal_word"]
JSON_FIELDS = {"pictograms": list, "hazard_statements": list, "sources": dict, "data": dict, "extra_hazards": dict,
               "phases": list}

# Writable columns per table
FIELDS = {
    "experiments": ["title", "date", "author", "course", "status", "scheme_style", "started_at", "ended_at",
                    "phases", "owner_id", *SECTION_KEYS],
    "steps": ["title", "notes", "atmosphere", "position"],
    "conditions": ["step_id", "temperature", "duration", "note", "position"],
    "reagents": ["step_id", "position", "cid", "pubchem_url", *CHEM_FIELDS, "pictograms", "hazard_statements",
                 "sources", "extra_hazards", "hazard_notes", "label", "role", "form", "purity", "concentration_m", "wt_percent", "solution_density",
                 "coefficient", "basis", "basis_value", "is_reference", "actual_basis", "actual_value",
                 "actual_mass_g", "crude_mass_g", "expected_yield_pct", "expected_ref_id", "source_reagent_id",
                 "scheme_pos", "grade", "supplier", "lot", "notes", "stock_item_id"],
    "procedure": ["step_id", "phase", "position", "text", "notes", "done_at"],
    "entries": ["ts", "elapsed_s", "kind", "action", "text", "value", "unit", "data", "custom_text", "step_id",
                "procedure_id", "timer_id"],
    "timers": ["label", "kind", "started_at", "duration_s", "stopped_at", "elapsed_s", "start_entry_id",
               "stop_entry_id", "procedure_id", "reagent_id"],
    "refs": ["position", "authors", "title", "source", "year", "volume", "pages", "doi", "url", "text"],
    "projects": ["title", "notes", "scheme_style", "owner_id"],
    "stock_items": ["cid", "pubchem_url", *CHEM_FIELDS, "label", "pictograms", "hazard_statements", "sources",
                    "extra_hazards", "hazard_notes", "form", "purity", "concentration_m", "wt_percent",
                    "solution_density", "supplier", "catalog_no", "grade", "lot", "quantity", "unit", "price",
                    "location", "received_at", "opened_at", "expires_at", "low_threshold", "status", "notes",
                    "updated_at"],
    "project_items": ["position"],
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


_V3 = """
ALTER TABLE procedure ADD COLUMN phase TEXT NOT NULL DEFAULT 'reaction';
ALTER TABLE experiments ADD COLUMN phases TEXT;
"""

_V4 = """
CREATE INDEX IF NOT EXISTS experiments_owner ON experiments(owner_id);
CREATE INDEX IF NOT EXISTS projects_owner ON projects(owner_id);
"""

# Created on every start if missing
_ALWAYS = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    active INTEGER NOT NULL DEFAULT 1,
    demo INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT,
    max_experiments INTEGER,
    created_at TEXT NOT NULL,
    last_login_at TEXT,
    last_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT,
    ip TEXT, user_agent TEXT
);
CREATE TABLE IF NOT EXISTS invites (
    id INTEGER PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    note TEXT,
    role TEXT NOT NULL DEFAULT 'user',
    demo INTEGER NOT NULL DEFAULT 1,
    max_experiments INTEGER,
    account_days INTEGER,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    used_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    username TEXT,
    ip TEXT,
    ok INTEGER NOT NULL,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS login_attempts_ts ON login_attempts(ts);
CREATE TABLE IF NOT EXISTS stock_items (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    cid INTEGER, pubchem_url TEXT,
    name TEXT NOT NULL DEFAULT '', iupac_name TEXT, cas TEXT, formula TEXT, smiles TEXT, label TEXT,
    mw REAL, density REAL, bp REAL, mp REAL, flash_point REAL, refractive_index REAL,
    signal_word TEXT, pictograms TEXT, hazard_statements TEXT, sources TEXT, extra_hazards TEXT, hazard_notes TEXT,
    form TEXT NOT NULL DEFAULT 'neat', purity REAL, concentration_m REAL, wt_percent REAL, solution_density REAL,
    supplier TEXT, catalog_no TEXT, grade TEXT, lot TEXT,
    quantity REAL, unit TEXT NOT NULL DEFAULT 'g', price REAL,
    location TEXT, received_at TEXT, opened_at TEXT, expires_at TEXT, low_threshold REAL,
    status TEXT NOT NULL DEFAULT 'in_use', notes TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS stock_items_owner ON stock_items(owner_id, cid);
CREATE TABLE IF NOT EXISTS stock_adjustments (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES stock_items(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    delta REAL NOT NULL,
    reason TEXT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS stock_adjustments_item ON stock_adjustments(item_id, ts);
CREATE TABLE IF NOT EXISTS project_materials (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    on_hand_g REAL,
    PRIMARY KEY (project_id, key)
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '', notes TEXT, scheme_style TEXT NOT NULL DEFAULT 'auto',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_items (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    UNIQUE (project_id, experiment_id)
);
"""

# Keywords that place a migrated procedure row in a phase (first match wins; the rest stay in "reaction")
_PHASE_WORDS = [
    ("analysis", r"\b(nmr|ir spectrum|ftir|melting point|mp\b|gc-?ms|lc-?ms|hplc|characteri[sz]|purity|uv-vis)"),
    ("purification", r"\b(column|chromatograph|recrystalli[sz]|distil|sublim|flash|prep(arative)? tlc|triturat)"),
    ("workup", r"\b(quench|extract|wash|brine|dried over|dry over|dry the|mgso4|na2so4|filter|concentrat|rotary|"
               r"rotovap|evaporat|separat|work-?up|neutrali[sz]|acidif|basif)"),
    ("setup", r"\b(flame-?dr|oven-?dr|set up|assemble|charge(d)? (a|the) flask|purge|under (n2|nitrogen|argon))"),
]


def guess_phase(text: str) -> str:
    t = (text or "").lower()
    for phase, rx in _PHASE_WORDS:
        if re.search(rx, t):
            return phase
    return DEFAULT_PHASE


def phase_list(exp: Optional[dict]) -> list[dict]:
    """An experiment's phases in order: the defaults plus its own ({key, label, custom})."""
    stored = [p for p in ((exp or {}).get("phases") or []) if isinstance(p, dict) and p.get("key")]
    defaults = dict(PHASES)
    out, seen = [], set()
    for p in stored:
        k = str(p["key"])
        if k in seen:
            continue
        seen.add(k)
        out.append({"key": k, "label": defaults.get(k) or str(p.get("label") or k), "custom": k not in defaults})
    # defaults missing from the stored order go back in their usual place
    for i, (k, label) in enumerate(PHASES):
        if k not in seen:
            after = [PHASES[j][0] for j in range(i)]
            pos = max((n + 1 for n, p in enumerate(out) if p["key"] in after), default=0)
            out.insert(pos, {"key": k, "label": label, "custom": False})
            seen.add(k)
    return out


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


def _ident(r: Any) -> Any:
    """What makes two reagent rows the same compound."""
    return r["cid"] or (r["smiles"] or "").strip() or (r["name"] or "").strip().lower() or None


def _assign_entries(entries: list, procedure: list, timers: list, step_ids: list) -> dict:
    """Step of each log entry: its own, its procedure row's, or that of the entry before it."""
    proc_step = {p["id"]: p["step_id"] for p in procedure}
    timer_proc = {t["id"]: t["procedure_id"] for t in timers}
    valid = set(step_ids)
    out, last = {}, step_ids[0]
    for e in entries:
        sid = e["step_id"]
        if sid not in valid:
            sid = proc_step.get(e["procedure_id"] or timer_proc.get(e["timer_id"]))
        if sid not in valid:
            sid = last
        out[e["id"]] = sid
        last = sid
    return out


def _migrate_v3(c: sqlite3.Connection) -> None:
    """Phases for procedure rows; one experiment per reaction (v2 multi-step experiments are split); projects link
    their experiments by material."""
    for p in c.execute("SELECT id, text FROM procedure").fetchall():
        c.execute("UPDATE procedure SET phase = ? WHERE id = ?", (guess_phase(p["text"]), p["id"]))

    exp_cols = [r[1] for r in c.execute("PRAGMA table_info(experiments)")]
    copy_cols = [k for k in ("date", "author", "course", "status", "scheme_style", "objective") if k in exp_cols]
    for exp in c.execute("SELECT * FROM experiments ORDER BY id").fetchall():
        eid = exp["id"]
        steps = c.execute("SELECT * FROM steps WHERE experiment_id = ? ORDER BY position, id", (eid,)).fetchall()
        if len(steps) < 2:
            continue
        entries = c.execute("SELECT * FROM entries WHERE experiment_id = ? ORDER BY ts, id", (eid,)).fetchall()
        procedure = c.execute("SELECT * FROM procedure WHERE experiment_id = ?", (eid,)).fetchall()
        timers = c.execute("SELECT * FROM timers WHERE experiment_id = ?", (eid,)).fetchall()
        refs = c.execute("SELECT * FROM refs WHERE experiment_id = ? ORDER BY position, id", (eid,)).fetchall()
        entry_step = _assign_entries(entries, procedure, timers, [s["id"] for s in steps])
        title = exp["title"] or "Untitled experiment"
        stamp = now()
        new_ids = []
        for k, s in enumerate(steps[1:], 2):
            vals = {col: exp[col] for col in copy_cols}
            vals.update(title=f"{title} — step {k}" + (f": {s['title']}" if s["title"] else ""),
                        created_at=stamp, updated_at=stamp)
            cols = ", ".join(_q(x) for x in vals)
            nid = c.execute(f"INSERT INTO experiments ({cols}) VALUES ({', '.join('?' * len(vals))})",
                            list(vals.values())).lastrowid
            new_ids.append(nid)
            c.execute("UPDATE steps SET experiment_id = ?, position = 0 WHERE id = ?", (nid, s["id"]))
            c.execute("UPDATE reagents SET experiment_id = ? WHERE step_id = ?", (nid, s["id"]))
            c.execute("UPDATE procedure SET experiment_id = ? WHERE step_id = ?", (nid, s["id"]))
            moved = [e for e in entries if entry_step[e["id"]] == s["id"]]
            moved_ids = {e["id"] for e in moved}
            moved_procs = {p["id"] for p in procedure if p["step_id"] == s["id"]}
            for e in moved:
                c.execute("UPDATE entries SET experiment_id = ? WHERE id = ?", (nid, e["id"]))
            for t in timers:
                if t["start_entry_id"] in moved_ids or t["procedure_id"] in moved_procs:
                    c.execute("UPDATE timers SET experiment_id = ? WHERE id = ?", (nid, t["id"]))
            ref_map = {}
            for r in refs:
                rc = [x for x in r.keys() if x not in ("id", "experiment_id")]
                ref_map[r["id"]] = c.execute(
                    f"INSERT INTO refs (experiment_id, {', '.join(_q(x) for x in rc)}) VALUES (?{', ?' * len(rc)})",
                    [nid, *[r[x] for x in rc]]).lastrowid
            for old, new in ref_map.items():
                c.execute("UPDATE reagents SET expected_ref_id = ? WHERE experiment_id = ? AND expected_ref_id = ?",
                          (new, nid, old))
            if moved:  # the clock of the new experiment runs from its first entry
                start = moved[0]["ts"]
                c.execute("UPDATE experiments SET started_at = ?, ended_at = ? WHERE id = ?",
                          (start, moved[-1]["ts"] if exp["ended_at"] else None, nid))
                for e in moved:
                    c.execute("UPDATE entries SET elapsed_s = ? WHERE id = ?", (elapsed_between(start, e["ts"]), e["id"]))
        c.execute("UPDATE experiments SET title = ? WHERE id = ?",
                  (f"{title} — step 1" + (f": {steps[0]['title']}" if steps[0]["title"] else ""), eid))
        # the new experiments follow the original in its projects (or in a new project)
        memberships = c.execute("SELECT project_id, position FROM project_items WHERE experiment_id = ?",
                                (eid,)).fetchall()
        if not memberships:
            pid = c.execute("INSERT INTO projects (title, created_at, updated_at) VALUES (?, ?, ?)",
                            (title, stamp, stamp)).lastrowid
            c.execute("INSERT INTO project_items (project_id, experiment_id, position) VALUES (?, ?, 0)", (pid, eid))
            memberships = [{"project_id": pid, "position": 0}]
        for m in memberships:
            n = len(new_ids)
            c.execute("UPDATE project_items SET position = position + ? WHERE project_id = ? AND position > ?",
                      (n, m["project_id"], m["position"]))
            for i, nid in enumerate(new_ids, 1):
                c.execute("INSERT OR IGNORE INTO project_items (project_id, experiment_id, position) VALUES (?, ?, ?)",
                          (m["project_id"], nid, m["position"] + i))

    # Former sequences linked consecutive experiments by compound; make those links explicit
    for proj in c.execute("SELECT id FROM projects").fetchall():
        members = [r[0] for r in c.execute("SELECT experiment_id FROM project_items WHERE project_id = ? "
                                           "ORDER BY position, id", (proj["id"],))]
        for a, b in zip(members, members[1:]):
            prods = c.execute("SELECT * FROM reagents WHERE experiment_id = ? AND role = 'product'", (a,)).fetchall()
            if not prods:
                continue
            prod_ids = {p["id"] for p in prods}
            reactants = c.execute("SELECT * FROM reagents WHERE experiment_id = ? AND role = 'reactant'",
                                  (b,)).fetchall()
            if any(r["source_reagent_id"] in prod_ids for r in reactants):
                continue
            for r in reactants:
                if r["source_reagent_id"]:
                    continue
                match = next((p for p in prods if _ident(p) and _ident(p) == _ident(r)), None)
                if match:
                    c.execute("UPDATE reagents SET source_reagent_id = ? WHERE id = ?", (match["id"], r["id"]))
                    break


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
            if version < 3:
                c.executescript(_V3)
                tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                if "sequences" in tables and "projects" not in tables:
                    c.execute("ALTER TABLE sequences RENAME TO projects")
                    c.execute("ALTER TABLE sequence_items RENAME TO project_items")
                    c.execute("ALTER TABLE project_items RENAME COLUMN sequence_id TO project_id")
            c.executescript(_ALWAYS)
            if version < 3 and not fresh:
                _migrate_v3(c)
            if version < 4:  # existing data gets its owner when the first admin is created
                for table in ("experiments", "projects"):
                    if "owner_id" not in [r[1] for r in c.execute(f"PRAGMA table_info({table})")]:
                        c.execute(f"ALTER TABLE {table} ADD COLUMN owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE")
                c.executescript(_V4)
            # v5: the stockroom (tables in stockroom.py); a reagent row can be drawn from a container
            cols = {t: [r[1] for r in c.execute(f"PRAGMA table_info({t})")] for t in ("reagents", "users")}
            if "stock_item_id" not in cols["reagents"]:
                c.execute("ALTER TABLE reagents ADD COLUMN stock_item_id INTEGER REFERENCES stock_items(id) "
                          "ON DELETE SET NULL")
            if "currency" not in cols["users"]:
                c.execute("ALTER TABLE users ADD COLUMN currency TEXT")
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
    def owner_of(self, table: str, rid: int) -> Optional[int]:
        """Owner of an experiment, a project or a row that belongs to an experiment (None if there is none)."""
        with self.conn() as c:
            if table == "projects":
                row = c.execute("SELECT owner_id FROM projects WHERE id = ?", (rid,)).fetchone()
                return row[0] if row else None
        exp_id = rid if table == "experiments" else self.experiment_of(table, rid)
        if exp_id is None:
            return None
        with self.conn() as c:
            row = c.execute("SELECT owner_id FROM experiments WHERE id = ?", (exp_id,)).fetchone()
        return row[0] if row else None

    def count_experiments(self, owner: Optional[int]) -> int:
        with self.conn() as c:
            return c.execute("SELECT COUNT(*) FROM experiments WHERE owner_id IS ?", (owner,)).fetchone()[0]

    def list_experiments(self, owner: Optional[int] = None) -> list[dict]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT e.id, e.title, e.date, e.status, e.course, e.updated_at, "
                "(SELECT COUNT(*) FROM reagents r WHERE r.experiment_id = e.id) AS n_reagents, "
                "(SELECT COALESCE(r.label, r.name) FROM reagents r WHERE r.experiment_id = e.id AND r.role = 'product' "
                "ORDER BY r.position, r.id LIMIT 1) AS product "
                "FROM experiments e WHERE e.owner_id IS ? ORDER BY COALESCE(e.date, '') DESC, e.id DESC",
                (owner,)).fetchall()
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
            "procedure": self.ordered_procedure(exp_id, exp),
            "entries": self.list("entries", "experiment_id = ?", (exp_id,), order="ts, id"),
            "timers": self.list("timers", "experiment_id = ?", (exp_id,), order="started_at, id"),
            "refs": self.list("refs", "experiment_id = ?", (exp_id,)),
        }

    def ordered_procedure(self, exp_id: int, exp: Optional[dict] = None) -> list[dict]:
        """Procedure rows in reading order: by phase, then position."""
        exp = exp or self.get_experiment(exp_id)
        order = {p["key"]: i for i, p in enumerate(phase_list(exp))}
        rows = self.list("procedure", "experiment_id = ?", (exp_id,))
        for p in rows:
            if p.get("phase") not in order:
                p["phase"] = DEFAULT_PHASE
        return sorted(rows, key=lambda p: (order[p["phase"]], p["position"], p["id"]))

    def duplicate_experiment(self, exp_id: int) -> Optional[int]:
        """Copy the plan: text, phases, stages, conditions, reagents (planned amounts only), procedure and references."""
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
        own = {r["id"] for r in b["reagents"]}
        for r in b["reagents"]:
            # a starting material taken from another experiment's product stays linked to that product
            src = r.get("source_reagent_id")
            r = dict(r, actual_basis=None, actual_value=None, actual_mass_g=None, crude_mass_g=None,
                     step_id=step_map.get(r["step_id"]), expected_ref_id=ref_map.get(r.get("expected_ref_id")),
                     source_reagent_id=None if src in own else src)
            reagent_map[r["id"]] = self.insert("reagents", r, experiment_id=new_id)
        for r in b["reagents"]:
            if r.get("source_reagent_id") in reagent_map:
                self.update("reagents", reagent_map[r["id"]],
                            {"source_reagent_id": reagent_map[r["source_reagent_id"]]})
        for p in b["procedure"]:
            self.insert("procedure", dict(p, done_at=None, step_id=step_map.get(p["step_id"])),
                        experiment_id=new_id)
        return new_id

    def products(self, q: str = "", exclude_exp: Optional[int] = None, limit: int = 12,
                 owner: Optional[int] = None) -> list[dict]:
        """Products of experiments (newest first) whose name, label, formula or CAS contains ``q``."""
        like = f"%{q.strip().lower()}%"
        with self.conn() as c:
            rows = c.execute(
                "SELECT r.id, r.name, r.label, r.formula, r.cas, r.cid, r.actual_mass_g, r.crude_mass_g, "
                "e.id AS experiment_id, e.title AS experiment, e.date FROM reagents r "
                "JOIN experiments e ON e.id = r.experiment_id WHERE r.role = 'product' AND e.id IS NOT ? "
                "AND e.owner_id IS ? "
                "AND (LOWER(COALESCE(r.name, '')) LIKE ? OR LOWER(COALESCE(r.label, '')) LIKE ? "
                "OR LOWER(COALESCE(r.formula, '')) LIKE ? OR COALESCE(r.cas, '') LIKE ?) "
                "ORDER BY COALESCE(e.date, '') DESC, e.id DESC LIMIT ?",
                (exclude_exp, owner, like, like, like, like, limit)).fetchall()
        return [dict(r) for r in rows]

    def uses_of(self, product_ids: Iterable[int]) -> list[dict]:
        """Starting materials taken from these products (in any experiment)."""
        ids = list(product_ids)
        if not ids:
            return []
        with self.conn() as c:
            rows = c.execute(
                f"SELECT r.*, e.title AS experiment, e.status AS experiment_status FROM reagents r "
                f"JOIN experiments e ON e.id = r.experiment_id "
                f"WHERE r.source_reagent_id IN ({', '.join('?' * len(ids))}) ORDER BY e.id", ids).fetchall()
        return [self._out(r) for r in rows]

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
        """Only one reference reagent per experiment (one reaction, all stages)."""
        with self.conn() as c:
            row = c.execute("SELECT experiment_id FROM reagents WHERE id = ?", (rid,)).fetchone()
            c.execute("UPDATE reagents SET is_reference = 0 WHERE experiment_id = ? AND id != ?",
                      (row["experiment_id"], rid))


def stoich_rows(reagents: list[dict]) -> list[dict]:
    keys = ("id", "role", "form", "mw", "density", "mp", "purity", "concentration_m", "wt_percent",
            "solution_density", "coefficient", "basis", "basis_value", "is_reference", "actual_basis",
            "actual_value", "actual_mass_g", "crude_mass_g", "expected_yield_pct")
    return [{k: r.get(k) for k in keys} for r in reagents]


# ---------------------------------------------------------------------------------------------- projects
def _project_methods():
    """Project storage (attached to Store below to keep the class readable)."""

    def list_projects(self, owner: Optional[int] = None) -> list[dict]:
        with self.conn() as c:
            projs = [dict(r) for r in c.execute("SELECT * FROM projects WHERE owner_id IS ? "
                                                "ORDER BY updated_at DESC, id DESC", (owner,))]
            for q in projs:
                q["experiments"] = [dict(r) for r in c.execute(
                    "SELECT e.id, e.title, e.date, e.status FROM project_items i JOIN experiments e "
                    "ON e.id = i.experiment_id WHERE i.project_id = ? ORDER BY i.position, i.id", (q["id"],))]
        return projs

    def create_project(self, data: dict, experiment_ids: Iterable[int] = ()) -> int:
        vals = {k: v for k, v in self._in("projects", data).items() if v is not None}
        vals.setdefault("title", "Untitled project")
        vals["created_at"] = vals["updated_at"] = now()
        cols = ", ".join(_q(k) for k in vals)
        with self.conn() as c:
            pid = c.execute(f"INSERT INTO projects ({cols}) VALUES ({', '.join('?' * len(vals))})",
                            list(vals.values())).lastrowid
        for eid in experiment_ids:
            self.add_to_project(pid, eid)
        return pid

    def get_project(self, project_id: int) -> Optional[dict]:
        proj = self.get("projects", project_id)
        if proj:
            with self.conn() as c:
                proj["experiment_ids"] = [r[0] for r in c.execute(
                    "SELECT experiment_id FROM project_items WHERE project_id = ? ORDER BY position, id",
                    (project_id,))]
        return proj

    def update_project(self, project_id: int, data: dict) -> None:
        vals = self._in("projects", data)
        vals["updated_at"] = now()
        sets = ", ".join(f"{_q(k)} = ?" for k in vals)
        with self.conn() as c:
            c.execute(f"UPDATE projects SET {sets} WHERE id = ?", [*vals.values(), project_id])

    def add_to_project(self, project_id: int, exp_id: int) -> None:
        with self.conn() as c:
            pos = c.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM project_items WHERE project_id = ?",
                            (project_id,)).fetchone()[0]
            c.execute("INSERT OR IGNORE INTO project_items (project_id, experiment_id, position) VALUES (?, ?, ?)",
                      (project_id, exp_id, pos))
            c.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now(), project_id))

    def remove_from_project(self, project_id: int, exp_id: int) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM project_items WHERE project_id = ? AND experiment_id = ?", (project_id, exp_id))

    def material_amounts(self, project_id: int) -> dict:
        """Amount on hand of each starting-material batch of a project (key -> g)."""
        with self.conn() as c:
            return {r[0]: r[1] for r in c.execute(
                "SELECT key, on_hand_g FROM project_materials WHERE project_id = ? AND on_hand_g IS NOT NULL",
                (project_id,))}

    def set_material_amount(self, project_id: int, key: str, grams: Optional[float]) -> None:
        with self.conn() as c:
            if grams is None:
                c.execute("DELETE FROM project_materials WHERE project_id = ? AND key = ?", (project_id, key))
            else:
                c.execute("INSERT INTO project_materials (project_id, key, on_hand_g) VALUES (?, ?, ?) "
                          "ON CONFLICT(project_id, key) DO UPDATE SET on_hand_g = excluded.on_hand_g",
                          (project_id, key, grams))

    def projects_of(self, exp_id: int) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT p.id, p.title FROM project_items i JOIN projects p ON p.id = i.project_id "
                "WHERE i.experiment_id = ? ORDER BY p.id", (exp_id,))]

    return locals()


for _name, _fn in _project_methods().items():
    setattr(Store, _name, _fn)
