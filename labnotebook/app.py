"""FastAPI application: JSON API, report downloads and the single-page frontend."""
from __future__ import annotations

import re
import zlib
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, actions, db, hazards, projects, report, scheme, stoich, structures
from .config import Settings, load_settings
from .pubchem import PubChemClient, PubChemUnavailable, summary_to_reagent

STATIC = Path(__file__).parent / "static"


# ------------------------------------------------------------------------------------------- request models
class PhaseIn(BaseModel):
    key: str
    label: Optional[str] = None


class ExperimentIn(BaseModel):
    title: Optional[str] = None
    date: Optional[str] = None
    author: Optional[str] = None
    course: Optional[str] = None
    status: Optional[Literal["planned", "in_progress", "completed"]] = None
    scheme_style: Optional[Literal["auto", "inline", "lettered"]] = None
    objective: Optional[str] = None
    results: Optional[str] = None
    discussion: Optional[str] = None
    conclusion: Optional[str] = None
    phases: Optional[list[PhaseIn]] = None  # the experiment's phases in order (defaults and its own)


class StepIn(BaseModel):
    title: Optional[str] = None
    notes: Optional[str] = None
    atmosphere: Optional[str] = None


class ConditionIn(BaseModel):
    temperature: Optional[str] = None
    duration: Optional[str] = None
    note: Optional[str] = None


class ReagentIn(BaseModel):
    query: Optional[str] = None  # create only: identifier to resolve with PubChem Local
    step_id: Optional[int] = None
    cid: Optional[int] = None
    name: Optional[str] = None
    label: Optional[str] = None
    iupac_name: Optional[str] = None
    cas: Optional[str] = None
    formula: Optional[str] = None
    smiles: Optional[str] = None
    mw: Optional[float] = None
    density: Optional[float] = None
    bp: Optional[float] = None
    mp: Optional[float] = None
    flash_point: Optional[float] = None
    refractive_index: Optional[float] = None
    signal_word: Optional[str] = None
    pictograms: Optional[list[str]] = None
    hazard_statements: Optional[list[str]] = None
    extra_hazards: Optional[dict[str, Any]] = None
    hazard_notes: Optional[str] = None
    role: Optional[Literal[stoich.ROLES]] = None  # type: ignore[valid-type]
    form: Optional[Literal[stoich.FORMS]] = None  # type: ignore[valid-type]
    purity: Optional[float] = None
    concentration_m: Optional[float] = None
    wt_percent: Optional[float] = None
    solution_density: Optional[float] = None
    coefficient: Optional[float] = None
    basis: Optional[Literal[stoich.BASES]] = None  # type: ignore[valid-type]
    basis_value: Optional[float] = None
    is_reference: Optional[bool] = None
    actual_basis: Optional[Literal["mass", "volume"]] = None
    actual_value: Optional[float] = None
    actual_mass_g: Optional[float] = None
    crude_mass_g: Optional[float] = None
    expected_yield_pct: Optional[float] = None
    expected_ref_id: Optional[int] = None
    source_reagent_id: Optional[int] = None
    scheme_pos: Optional[Literal["auto", "above", "below", "structure", "hidden"]] = None
    grade: Optional[str] = None
    supplier: Optional[str] = None
    lot: Optional[str] = None
    notes: Optional[str] = None


class ProcedureIn(BaseModel):
    text: Optional[str] = None
    notes: Optional[str] = None
    phase: Optional[str] = None
    step_id: Optional[int] = None
    done: Optional[bool] = None


class TimerStart(BaseModel):
    label: str
    kind: Literal["stopwatch", "countdown"] = "stopwatch"
    duration_s: Optional[float] = None
    reagent_id: Optional[int] = None
    procedure_id: Optional[int] = None


class EntryIn(BaseModel):
    ts: Optional[str] = None
    action: Optional[str] = None
    data: Optional[dict[str, Any]] = None
    text: Optional[str] = None  # overrides the generated sentence
    value: Optional[str] = None
    unit: Optional[str] = None
    step_id: Optional[int] = None
    procedure_id: Optional[int] = None
    start_timer: Optional[TimerStart] = None


class RefIn(BaseModel):
    authors: Optional[str] = None
    title: Optional[str] = None
    source: Optional[str] = None
    year: Optional[str] = None
    volume: Optional[str] = None
    pages: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    text: Optional[str] = None


class ProjectIn(BaseModel):
    title: Optional[str] = None
    notes: Optional[str] = None
    scheme_style: Optional[Literal["auto", "inline", "lettered"]] = None
    experiment_ids: Optional[list[int]] = None  # create only


class ProjectAdd(BaseModel):
    experiment_id: int


class BranchIn(BaseModel):
    title: Optional[str] = None
    mass_g: Optional[float] = None       # portion of the product to take (default: what is left)
    project_id: Optional[int] = None     # project to add the new experiment to (default: the product's projects)


class RefreshIn(BaseModel):
    fields: Optional[list[str]] = None  # None = every PubChem field


def _slug(title: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", title or "").strip("-")
    return (s or "experiment")[:60]


_MOLAR = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*M\s+(.+?)(?:\s+in\s+(.+))?\s*$", re.I)
_WT = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(?:wt\s*%|%\s*(?:w/w)?)\s+(?:aq(?:ueous|\.)?\s+)?(.+?)\s*$", re.I)


def parse_reagent_query(q: str) -> dict:
    """'2.5 M n-BuLi in hexanes' -> name n-BuLi, molar solution; '37% HCl' -> name HCl, 37 wt%."""
    m = _MOLAR.match(q)
    if m:
        out = {"query": m.group(2), "form": "solution", "concentration_m": float(m.group(1).replace(",", "."))}
        if m.group(3):
            out["notes"] = f"{m.group(1)} M in {m.group(3)}"
        return out
    m = _WT.match(q)
    if m:
        return {"query": m.group(2), "form": "wt", "wt_percent": float(m.group(1).replace(",", "."))}
    return {"query": q}


def create_app(settings: Optional[Settings] = None, pubchem: Optional[PubChemClient] = None) -> FastAPI:
    settings = settings or load_settings()
    store = db.Store(settings.db_path)
    client = pubchem or PubChemClient(settings.pubchem_url, settings.pubchem_timeout)

    app = FastAPI(title="Lab Notebook", version=__version__,
                  description="Organic chemistry lab notebook backed by PubChem Local.")
    app.state.store, app.state.pubchem, app.state.settings = store, client, settings

    # -------------------------------------------------------------- helpers
    def need(table: str, rid: int, what: str) -> dict:
        row = store.get(table, rid)
        if not row:
            raise HTTPException(404, f"{what} not found")
        return row

    def need_exp(exp_id: int) -> dict:
        exp = store.get_experiment(exp_id)
        if not exp:
            raise HTTPException(404, "Experiment not found")
        return exp

    def compute(bundle: dict) -> dict:
        return stoich.compute_experiment(bundle["steps"], bundle["reagents"], db.stoich_rows)

    def names_for(exp_id: int):
        by_id = {r["id"]: scheme.label(r) for r in store.list("reagents", "experiment_id = ?", (exp_id,))}
        return lambda rid: by_id.get(int(rid)) if rid not in (None, "") else None

    def sync_actuals(exp_id: int, rids) -> None:
        """Set the actual amount of these reagents from the log (Add and Amount used entries)."""
        rids = {int(r) for r in rids if r}
        if not rids:
            return
        entries = store.list("entries", "experiment_id = ?", (exp_id,), order="ts, id")
        for rid in rids:
            r = store.get("reagents", rid)
            if not r or r["experiment_id"] != exp_id or r["role"] == "product":
                continue
            a = actions.actual_from_log(entries, rid)
            if a:
                store.update_reagent(rid, {"actual_value": round(a[0], 6),
                                           "actual_basis": "mass" if a[1] == "g" else "volume"})
            else:
                store.update_reagent(rid, {"actual_value": None, "actual_basis": None})

    def detail(exp_id: int) -> dict:
        b = store.bundle(exp_id)
        if not b:
            raise HTTPException(404, "Experiment not found")
        calc = compute(b)
        use = actions.usage(b["entries"])
        for r in b["reagents"]:
            r["calc"] = calc["rows"].get(r["id"])
            r["usage"] = use.get(r["id"], {})
        for p in b["procedure"]:
            p["html"] = scheme.render_mentions(p.get("text") or "", b["reagents"], calc["rows"], mode="html")
        b["stoich"] = {k: calc[k] for k in ("reference_id", "reference_mmol", "limiting_id", "yield")}
        b["scheme_html"] = report.scheme_html(b, calc, lambda r, w, h: _struct_url(r, w, h))
        b["server_time"] = db.now()
        b["phases"] = db.phase_list(b["experiment"])
        b["projects"] = store.projects_of(exp_id)
        b["route"] = route_links(b, calc)
        return b

    def route_links(b: dict, calc: dict) -> dict:
        """Where this experiment's starting materials came from and where its product went."""
        own = {r["id"] for r in b["reagents"]}
        sources = []
        for r in b["reagents"]:
            src = r.get("source_reagent_id")
            if src and src not in own:
                p = store.get("reagents", src)
                e = store.get_experiment(p["experiment_id"]) if p else None
                sources.append({"reagent_id": r["id"], "product_id": src, "name": scheme.label(r),
                                "experiment_id": e["id"] if e else None, "experiment": e["title"] if e else None,
                                "taken_g": projects.taken_g(r, calc["rows"].get(r["id"], {})), "missing": not p})
        prods = [r for r in b["reagents"] if r.get("role") == "product"]
        uses = []
        for u in store.uses_of([p["id"] for p in prods]):
            if u["experiment_id"] == b["experiment"]["id"]:
                continue
            amount = u.get("actual_value") if u.get("actual_basis") == "mass" else \
                u.get("basis_value") if u.get("basis") == "mass" else None
            uses.append({"experiment_id": u["experiment_id"], "experiment": u["experiment"],
                         "status": u["experiment_status"], "product_id": u["source_reagent_id"], "taken_g": amount})
        products = []
        for p in prods:
            c = calc["rows"].get(p["id"], {})
            used = [u["taken_g"] for u in uses if u["product_id"] == p["id"] and u["taken_g"] is not None]
            iso = c.get("isolated_mass_g")
            products.append({"id": p["id"], "name": scheme.label(p), "isolated_g": iso,
                             "used_g": sum(used) if used else None,
                             "remaining_g": (iso - sum(used)) if iso is not None else None})
        return {"sources": sources, "uses": uses, "products": products}

    def _struct_url(r: dict, w: int, h: int) -> Optional[str]:
        if not r.get("cid") and not r.get("smiles"):
            return None
        key = r.get("cid") or zlib.crc32((r.get("smiles") or "").encode())
        return f"/api/reagents/{r['id']}/structure.svg?width={w}&height={h}&v={key}"

    def elapsed_for(exp: dict, ts: str) -> Optional[float]:
        return db.elapsed_between(exp.get("started_at"), ts)

    def log(exp_id: int, action: str, data: Optional[dict] = None, text: Optional[str] = None,
            **extra: Any) -> int:
        """Add a log entry (sentence generated from the action unless ``text`` is given)."""
        exp = need_exp(exp_id)
        ts = extra.pop("ts", None) or db.now()
        if text is None:
            text = actions.describe(action, data or {}, names_for(exp_id))
            custom = False
        else:
            custom = action in actions.ACTIONS and action not in ("observation", "note")
        eid = store.insert("entries", {"ts": ts, "elapsed_s": elapsed_for(exp, ts), "kind": action, "action": action,
                                       "data": data or {}, "text": text, "custom_text": custom, **extra},
                           experiment_id=exp_id)
        store.touch(exp_id)
        return eid

    # -------------------------------------------------------------- meta
    @app.get("/api/health")
    def health():
        try:
            pc = client.health()
            pubchem_status = {"reachable": True, **({"datasets": pc.get("datasets")} if "datasets" in pc else {})}
        except PubChemUnavailable as e:
            pubchem_status = {"reachable": False, "error": str(e)}
        return {"status": "ok", "version": __version__, "pubchem": {"url": settings.pubchem_url, **pubchem_status}}

    @app.get("/api/config")
    def config():
        return {"version": __version__, "author": settings.author, "lab_name": settings.lab_name,
                "sections": db.SECTIONS, "roles": stoich.ROLES, "forms": stoich.FORMS, "bases": stoich.BASES,
                "actions": actions.ACTIONS, "units": actions.AMOUNT_UNITS}

    # -------------------------------------------------------------- experiments
    @app.get("/api/experiments")
    def list_experiments():
        return {"experiments": store.list_experiments()}

    @app.post("/api/experiments", status_code=201)
    def create_experiment(body: ExperimentIn):
        data = body.model_dump(exclude_unset=True)
        if not data.get("author") and settings.author:
            data["author"] = settings.author
        return detail(store.create_experiment(data))

    @app.get("/api/experiments/{exp_id}")
    def get_experiment(exp_id: int):
        return detail(exp_id)

    @app.put("/api/experiments/{exp_id}")
    def update_experiment(exp_id: int, body: ExperimentIn):
        need_exp(exp_id)
        data = body.model_dump(exclude_unset=True)
        if "phases" in data:
            data["phases"] = clean_phases(data["phases"] or [])
            keys = {p["key"] for p in data["phases"]}
            with store.conn() as c:  # rows of a removed phase go back to the reaction
                for p in c.execute("SELECT id, phase FROM procedure WHERE experiment_id = ?", (exp_id,)).fetchall():
                    if p["phase"] not in keys:
                        c.execute("UPDATE procedure SET phase = ? WHERE id = ?", (db.DEFAULT_PHASE, p["id"]))
            store.update_experiment(exp_id, data)
            return detail(exp_id)
        store.update_experiment(exp_id, data)
        return {"experiment": store.get_experiment(exp_id)}

    def clean_phases(items: list[dict]) -> list[dict]:
        """Validated phase list: the default phases keep their names and relative order; own phases need a name."""
        defaults = dict(db.PHASES)
        out, seen = [], set()
        for p in items:
            key = re.sub(r"[^a-z0-9_-]", "", str(p.get("key") or "").lower())[:40]
            if not key or key in seen:
                continue
            label = defaults.get(key) or (p.get("label") or "").strip()[:60]
            if not label:
                continue
            seen.add(key)
            out.append({"key": key, "label": label})
        order = [p["key"] for p in out if p["key"] in defaults]
        if order != [k for k, _ in db.PHASES if k in order]:
            raise HTTPException(422, "The standard phases keep their order")
        return [{"key": p["key"], "label": p["label"]} for p in db.phase_list({"phases": out})]

    @app.delete("/api/experiments/{exp_id}", status_code=204)
    def delete_experiment(exp_id: int):
        if not store.delete_experiment(exp_id):
            raise HTTPException(404, "Experiment not found")
        return Response(status_code=204)

    @app.post("/api/experiments/{exp_id}/duplicate", status_code=201)
    def duplicate_experiment(exp_id: int):
        new_id = store.duplicate_experiment(exp_id)
        if new_id is None:
            raise HTTPException(404, "Experiment not found")
        return detail(new_id)

    @app.post("/api/experiments/{exp_id}/start")
    def start_experiment(exp_id: int):
        exp = need_exp(exp_id)
        if not exp.get("started_at"):
            ts = db.now()
            store.update_experiment(exp_id, {"started_at": ts, "ended_at": None, "status": "in_progress"})
            log(exp_id, "start", text="Experiment started", ts=ts)
        return detail(exp_id)

    @app.post("/api/experiments/{exp_id}/end")
    def end_experiment(exp_id: int):
        exp = need_exp(exp_id)
        if exp.get("started_at") and not exp.get("ended_at"):
            ts = db.now()
            for t in store.list("timers", "experiment_id = ? AND stopped_at IS NULL", (exp_id,)):
                _stop_timer(t, log_it=True)
            store.update_experiment(exp_id, {"ended_at": ts})
            dur = actions.fmt_duration(db.elapsed_between(exp["started_at"], ts))
            log(exp_id, "end", text=f"Experiment ended (total {dur})", ts=ts)
        return detail(exp_id)

    @app.post("/api/experiments/{exp_id}/restart")
    def restart_clock(exp_id: int):
        """Clear the experiment clock (start and end) so it can be started again."""
        need_exp(exp_id)
        store.update_experiment(exp_id, {"started_at": None, "ended_at": None})
        return detail(exp_id)

    # -------------------------------------------------------------- stages (one-pot) and conditions
    # The table and routes are called "steps"; in the app they are the numbered stages of a one-pot reaction.
    @app.post("/api/experiments/{exp_id}/steps", status_code=201)
    def add_step(exp_id: int, body: StepIn):
        need_exp(exp_id)
        sid = store.insert("steps", body.model_dump(exclude_unset=True), experiment_id=exp_id)
        store.touch(exp_id)
        out = detail(exp_id)
        out["step_id"] = sid
        return out

    def _extra_hazards(cid: int) -> dict:
        """DOT / NFPA / reactivity data from the safety summary ({} if unavailable)."""
        try:
            extra = hazards.extract(client.safety_summary(cid))
        except PubChemUnavailable:
            return {}
        return {"extra_hazards": extra} if extra else {}

    def remaining_of(product: dict) -> Optional[float]:
        """Isolated (else crude) mass of a product minus what other experiments took (planned or measured)."""
        mass = product.get("actual_mass_g") or product.get("crude_mass_g")
        if mass is None:
            return None
        for u in store.uses_of([product["id"]]):
            amount = u.get("actual_value") if u.get("actual_basis") == "mass" else \
                u.get("basis_value") if u.get("basis") == "mass" else None
            mass -= amount or 0
        return mass

    def _carry(exp_id: int, step_id: int, product: dict, mass: Optional[float] = None) -> int:
        """Add a portion of a product (of another experiment) as a starting material of ``exp_id``.

        The amount is ``mass`` or else what is left of the product."""
        data = {k: product.get(k) for k in ["cid", "pubchem_url", *db.CHEM_FIELDS, "pictograms", "hazard_statements",
                                            "sources", "label", "extra_hazards", "hazard_notes"]}
        if mass is None:
            left = remaining_of(product)
            mass = round(left, 4) if left is not None and left > 0 else None
        has_ref = any(r.get("is_reference") for r in store.list("reagents", "experiment_id = ?", (exp_id,)))
        data.update(step_id=step_id, role="reactant", source_reagent_id=product["id"], is_reference=not has_ref,
                    basis="mass" if mass else None, basis_value=mass)
        return store.add_reagent(exp_id, data)

    @app.put("/api/steps/{sid}")
    def update_step(sid: int, body: StepIn):
        s = need("steps", sid, "Step")
        store.update("steps", sid, body.model_dump(exclude_unset=True))
        store.touch(s["experiment_id"])
        return detail(s["experiment_id"])

    @app.delete("/api/steps/{sid}")
    def delete_step(sid: int):
        s = need("steps", sid, "Step")
        if len(store.list("steps", "experiment_id = ?", (s["experiment_id"],))) <= 1:
            raise HTTPException(400, "An experiment needs at least one stage")
        store.delete("steps", sid)
        store.touch(s["experiment_id"])
        return detail(s["experiment_id"])

    @app.post("/api/steps/{sid}/conditions", status_code=201)
    def add_condition(sid: int, body: ConditionIn):
        s = need("steps", sid, "Step")
        store.insert("conditions", body.model_dump(exclude_unset=True), step_id=sid)
        store.touch(s["experiment_id"])
        return detail(s["experiment_id"])

    @app.put("/api/conditions/{cid_}")
    def update_condition(cid_: int, body: ConditionIn):
        need("conditions", cid_, "Condition")
        exp_id = store.experiment_of("conditions", cid_)
        store.update("conditions", cid_, body.model_dump(exclude_unset=True))
        store.touch(exp_id)
        return detail(exp_id)

    @app.delete("/api/conditions/{cid_}")
    def delete_condition(cid_: int):
        need("conditions", cid_, "Condition")
        exp_id = store.experiment_of("conditions", cid_)
        store.delete("conditions", cid_)
        return detail(exp_id)

    # -------------------------------------------------------------- reagents
    @app.post("/api/experiments/{exp_id}/reagents", status_code=201)
    def add_reagent(exp_id: int, body: ReagentIn):
        need_exp(exp_id)
        data = body.model_dump(exclude_unset=True)
        steps = store.list("steps", "experiment_id = ?", (exp_id,))
        if not data.get("step_id") or data["step_id"] not in {s["id"] for s in steps}:
            data["step_id"] = steps[0]["id"]
        if data.get("source_reagent_id"):
            src = need("reagents", data["source_reagent_id"], "Reagent")
            if src["experiment_id"] == exp_id or src["role"] != "product":
                raise HTTPException(400, "A starting material can only come from the product of another experiment")
            rid = _carry(exp_id, data["step_id"], src,
                         data.get("basis_value") if data.get("basis") == "mass" else None)
            if data.get("role"):
                store.update_reagent(rid, {"role": data["role"]})
            out = detail(exp_id)
            out["reagent_id"], out["warning"] = rid, None
            return out
        query = (data.pop("query", None) or "").strip()
        if query and "form" not in data:
            parsed = parse_reagent_query(query)
            query = parsed.pop("query")
            for k, v in parsed.items():
                data.setdefault(k, v)
        warning, found = None, None
        if data.get("cid") or query:
            try:
                found = client.lab(data["cid"]) if data.get("cid") else client.lookup(query)
                if not found:
                    warning = f"“{query or data.get('cid')}” was not found in PubChem Local; enter its data manually."
            except PubChemUnavailable as e:
                warning = f"PubChem Local is unavailable ({e}); enter the data manually."
        values = summary_to_reagent(found) if found else {"sources": {}}
        if found and found.get("cid"):
            values.update(_extra_hazards(found["cid"]))
        user_chem = {k: v for k, v in data.items() if k in db.CHEM_FIELDS}
        values.update(data)
        for k in user_chem:
            values["sources"][k] = "manual"
        if not values.get("name"):
            values["name"] = query or "Unnamed"
        role = values.get("role") or "reactant"
        values["role"] = role
        if role in ("solvent", "workup") and "basis" not in data:
            values["basis"] = "volume"
        rid = store.add_reagent(exp_id, values)
        out = detail(exp_id)
        out["reagent_id"], out["warning"] = rid, warning
        return out

    @app.put("/api/reagents/{rid}")
    def update_reagent(rid: int, body: ReagentIn):
        current = need("reagents", rid, "Reagent")
        data = body.model_dump(exclude_unset=True)
        data.pop("query", None)
        changed = [k for k in data if k in db.CHEM_FIELDS + ["pictograms", "hazard_statements", "extra_hazards"]
                   and data[k] != current.get(k)]
        if changed:
            sources = dict(current.get("sources") or {})
            for k in changed:
                sources[k] = "manual"
            data["sources"] = sources
        store.update_reagent(rid, data)
        # Recording an actual amount in the table logs it (as one "Amount used" entry per reagent; corrections
        # update that entry). The log is the record of what was used.
        if ("actual_value" in data or "actual_basis" in data) and current["role"] != "product":
            r = store.get("reagents", rid)
            value, basis = r.get("actual_value"), r.get("actual_basis") or "mass"
            prev = [e for e in store.list("entries", "experiment_id = ? AND action = 'weigh'",
                                          (current["experiment_id"],), order="id")
                    if actions.entry_reagent(e) == rid]
            if value is not None:
                ed = {"chem": {"reagent_id": rid}, "amount": value, "unit": "g" if basis == "mass" else "mL"}
                text = actions.describe("weigh", ed, names_for(current["experiment_id"]))
                if prev:
                    store.update("entries", prev[-1]["id"], {"data": ed, "text": text})
                else:
                    log(current["experiment_id"], "weigh", ed, step_id=current.get("step_id"))
            elif prev:
                store.delete("entries", prev[-1]["id"])
        store.touch(current["experiment_id"])
        return detail(current["experiment_id"])

    @app.post("/api/reagents/{rid}/refresh")
    def refresh_reagent(rid: int, body: RefreshIn):
        """Re-read values from PubChem Local, replacing manual overrides (all fields or the listed ones)."""
        current = need("reagents", rid, "Reagent")
        if not current.get("cid"):
            raise HTTPException(400, "This reagent is not linked to a PubChem compound")
        try:
            found = client.lab(current["cid"])
        except PubChemUnavailable as e:
            raise HTTPException(503, str(e))
        if not found:
            raise HTTPException(404, "Compound not found in PubChem Local")
        values = summary_to_reagent(found)
        if not body.fields or "extra_hazards" in body.fields:
            extra = _extra_hazards(current["cid"]).get("extra_hazards")
            values["extra_hazards"] = extra
            if extra:
                values["sources"]["extra_hazards"] = "pubchem"
        fields = body.fields or [k for k in values if k not in ("sources", "cid")]
        sources = dict(current.get("sources") or {})
        update = {}
        for k in fields:
            if k in values and k != "sources":
                update[k] = values[k]
                if k in values["sources"]:
                    sources[k] = "pubchem"
                else:
                    sources.pop(k, None)
        update["sources"] = sources
        store.update_reagent(rid, update)
        return detail(current["experiment_id"])

    @app.delete("/api/reagents/{rid}")
    def delete_reagent(rid: int):
        current = need("reagents", rid, "Reagent")
        store.delete("reagents", rid)
        store.touch(current["experiment_id"])
        return detail(current["experiment_id"])

    @app.put("/api/steps/{sid}/reagents/order")
    def reorder_reagents(sid: int, ids: list[int]):
        s = need("steps", sid, "Step")
        store.reorder("reagents", ids, "step_id", sid)
        return detail(s["experiment_id"])

    @app.get("/api/reagents/{rid}/structure.svg")
    def reagent_structure(rid: int, width: int = Query(300, ge=40, le=1200), height: int = Query(240, ge=40, le=1200),
                          theme: Literal["light", "dark"] = "light"):
        r = need("reagents", rid, "Reagent")
        img = structures.structure(client, r.get("cid"), r.get("smiles"), width, height, theme)
        if not img:
            raise HTTPException(404, "No structure available")
        return Response(img[0], media_type=img[1], headers={"Cache-Control": "public, max-age=3600"})

    # -------------------------------------------------------------- procedure
    @app.post("/api/experiments/{exp_id}/procedure", status_code=201)
    def add_procedure(exp_id: int, body: ProcedureIn):
        exp = need_exp(exp_id)
        data = body.model_dump(exclude_unset=True)
        data.pop("done", None)
        data.setdefault("text", "")
        if data.get("phase") not in {p["key"] for p in db.phase_list(exp)}:
            data["phase"] = db.DEFAULT_PHASE
        store.insert("procedure", data, experiment_id=exp_id)
        store.touch(exp_id)
        return detail(exp_id)

    @app.put("/api/procedure/{pid}")
    def update_procedure(pid: int, body: ProcedureIn):
        p = need("procedure", pid, "Procedure step")
        data = body.model_dump(exclude_unset=True)
        done = data.pop("done", None)
        exp_id = p["experiment_id"]
        if "phase" in data and data["phase"] not in {x["key"] for x in db.phase_list(need_exp(exp_id))}:
            raise HTTPException(422, f"Unknown phase {data['phase']!r}")
        if done is not None and bool(p.get("done_at")) != done:
            if done:
                ts = db.now()
                data["done_at"] = ts
                rows = store.ordered_procedure(exp_id)
                n = next(i for i, x in enumerate(rows, 1) if x["id"] == pid)
                log(exp_id, "procedure", {"procedure_id": pid}, text=f"Procedure step {n} completed", ts=ts,
                    procedure_id=pid)
            else:
                data["done_at"] = None
                for e in store.list("entries", "procedure_id = ? AND action = 'procedure'", (pid,)):
                    store.delete("entries", e["id"])
        store.update("procedure", pid, data)
        store.touch(exp_id)
        return detail(exp_id)

    @app.delete("/api/procedure/{pid}")
    def delete_procedure(pid: int):
        p = need("procedure", pid, "Procedure step")
        store.delete("procedure", pid)
        return detail(p["experiment_id"])

    @app.put("/api/experiments/{exp_id}/{table}/order")
    def reorder(exp_id: int, table: Literal["procedure", "refs", "steps"], ids: list[int]):
        need_exp(exp_id)
        store.reorder(table, ids, "experiment_id", exp_id)
        return detail(exp_id)

    # -------------------------------------------------------------- log entries and timers
    @app.post("/api/experiments/{exp_id}/entries", status_code=201)
    def add_entry(exp_id: int, body: EntryIn):
        need_exp(exp_id)
        data = body.model_dump(exclude_unset=True)
        action = data.get("action") or "note"
        if action not in actions.ACTIONS and action not in actions.SYSTEM_ACTIONS:
            raise HTTPException(422, f"Unknown action {action!r}")
        payload = data.get("data") or {}
        if action in ("note", "observation") and not payload.get("text") and data.get("text"):
            payload["text"] = data["text"]
        text = data.get("text") if action not in ("note", "observation") else None
        eid = log(exp_id, action, payload, text=text, ts=data.get("ts"), value=data.get("value"),
                  unit=data.get("unit"), step_id=data.get("step_id"), procedure_id=data.get("procedure_id"))
        if action == "isolate" and payload.get("product"):
            prod = store.get("reagents", int(payload["product"]))
            if prod and prod["experiment_id"] == exp_id:
                field = "crude_mass_g" if payload.get("stage") == "crude" else "actual_mass_g"
                try:
                    store.update_reagent(prod["id"], {field: float(payload.get("mass"))})
                except (TypeError, ValueError):
                    pass
        if action in actions.AMOUNT_ACTIONS:
            sync_actuals(exp_id, [actions.entry_reagent({"data": payload})])
        if body.start_timer:
            _start_timer(exp_id, body.start_timer, start_entry_id=eid)
        out = detail(exp_id)
        out["entry_id"] = eid
        return out

    @app.put("/api/entries/{eid}")
    def update_entry(eid: int, body: EntryIn):
        e = need("entries", eid, "Entry")
        exp = need_exp(e["experiment_id"])
        data = body.model_dump(exclude_unset=True, exclude={"start_timer"})
        if "ts" in data:
            data["elapsed_s"] = elapsed_for(exp, data["ts"])
        if "text" in data and e["action"] not in ("note", "observation"):
            data["custom_text"] = True
        if "data" in data:
            if e["action"] in ("note", "observation"):
                data["text"] = (data["data"] or {}).get("text", "")
            elif not (data.get("custom_text") or e.get("custom_text")):
                data["text"] = actions.describe(e["action"], data["data"] or {}, names_for(e["experiment_id"]))
        if "text" in data and e["action"] in ("note", "observation"):
            data["data"] = {**(e.get("data") or {}), **(data.get("data") or {}), "text": data["text"]}
        store.update("entries", eid, data)
        if e["action"] in actions.AMOUNT_ACTIONS:
            sync_actuals(e["experiment_id"], [actions.entry_reagent(e), actions.entry_reagent(store.get("entries", eid))])
        store.touch(e["experiment_id"])
        return detail(e["experiment_id"])

    @app.delete("/api/entries/{eid}")
    def delete_entry(eid: int):
        e = need("entries", eid, "Entry")
        store.delete("entries", eid)
        if e["action"] in actions.AMOUNT_ACTIONS:
            sync_actuals(e["experiment_id"], [actions.entry_reagent(e)])
        store.touch(e["experiment_id"])
        return detail(e["experiment_id"])

    def _start_timer(exp_id: int, t: TimerStart, start_entry_id: Optional[int] = None) -> int:
        return store.insert("timers", {"label": t.label, "kind": t.kind, "started_at": db.now(),
                                       "duration_s": t.duration_s, "reagent_id": t.reagent_id,
                                       "procedure_id": t.procedure_id, "start_entry_id": start_entry_id},
                            experiment_id=exp_id)

    def _stop_timer(t: dict, log_it: bool = True) -> None:
        ts = db.now()
        elapsed = db.elapsed_between(t["started_at"], ts)
        stop_eid = None
        if log_it:
            verb = "finished" if t["kind"] == "countdown" else "complete"
            stop_eid = log(t["experiment_id"], "timer", {"timer_id": t["id"], "elapsed_s": elapsed},
                           text=f"{t['label']}: {verb} ({actions.fmt_duration(elapsed)})", ts=ts,
                           timer_id=t["id"], procedure_id=t.get("procedure_id"))
        store.update("timers", t["id"], {"stopped_at": ts, "elapsed_s": elapsed, "stop_entry_id": stop_eid})

    @app.post("/api/experiments/{exp_id}/timers", status_code=201)
    def start_timer(exp_id: int, body: TimerStart):
        need_exp(exp_id)
        what = "Countdown" if body.kind == "countdown" else "Timer"
        extra = f" ({actions.fmt_duration(body.duration_s)})" if body.kind == "countdown" and body.duration_s else ""
        eid = log(exp_id, "timer", {"label": body.label}, text=f"{what} started: {body.label}{extra}",
                  procedure_id=body.procedure_id)
        tid = _start_timer(exp_id, body, start_entry_id=eid)
        store.update("entries", eid, {"timer_id": tid})
        out = detail(exp_id)
        out["timer_id"] = tid
        return out

    @app.post("/api/timers/{tid}/stop")
    def stop_timer(tid: int):
        t = need("timers", tid, "Timer")
        if not t.get("stopped_at"):
            _stop_timer(t)
        return detail(t["experiment_id"])

    @app.delete("/api/timers/{tid}")
    def cancel_timer(tid: int):
        """Discard a timer without logging its end."""
        t = need("timers", tid, "Timer")
        store.delete("timers", tid)
        return detail(t["experiment_id"])

    # -------------------------------------------------------------- references
    @app.post("/api/experiments/{exp_id}/refs", status_code=201)
    def add_ref(exp_id: int, body: RefIn):
        need_exp(exp_id)
        store.insert("refs", body.model_dump(exclude_unset=True), experiment_id=exp_id)
        store.touch(exp_id)
        return detail(exp_id)

    @app.put("/api/refs/{rid}")
    def update_ref(rid: int, body: RefIn):
        r = need("refs", rid, "Reference")
        store.update("refs", rid, body.model_dump(exclude_unset=True))
        store.touch(r["experiment_id"])
        return detail(r["experiment_id"])

    @app.delete("/api/refs/{rid}")
    def delete_ref(rid: int):
        r = need("refs", rid, "Reference")
        store.delete("refs", rid)
        with store.conn() as c:
            c.execute("UPDATE reagents SET expected_ref_id = NULL WHERE expected_ref_id = ?", (rid,))
        return detail(r["experiment_id"])

    # -------------------------------------------------------------- projects
    def need_project(project_id: int) -> dict:
        proj = store.get_project(project_id)
        if not proj:
            raise HTTPException(404, "Project not found")
        return proj

    def project_parts(proj: dict) -> tuple[list[dict], list[dict], dict]:
        bundles = [b for b in (store.bundle(eid) for eid in proj["experiment_ids"]) if b]
        calcs = [compute(b) for b in bundles]
        return bundles, calcs, projects.graph(bundles, calcs)

    def project_detail(project_id: int) -> dict:
        proj = need_project(project_id)
        bundles, calcs, g = project_parts(proj)
        numbers = report.project_numbers(g, bundles, calcs)[0]
        img = lambda r, w, h: _struct_url(r, w, h)  # noqa: E731
        rows = projects.summary_rows(g)
        final = [n for n in projects.leaves(g) if next(x for x in g["nodes"] if x["id"] == n)["parents"]]
        return {
            "project": {k: proj[k] for k in ("id", "title", "notes", "scheme_style", "created_at", "updated_at")},
            "experiments": [{**{k: b["experiment"].get(k) for k in ("id", "title", "date", "status", "author")}}
                            for b in bundles],
            "summary": [{k: r[k] for k in ("n", "id", "title", "date", "status", "col", "yield", "isolated_g", "used_g",
                                           "remaining_g", "overall_yield", "lls", "from", "children")}
                        | {"product": scheme.label(r["product"]) if r["product"] else None,
                           "product_id": r["product"]["id"] if r["product"] else None,
                           "number": numbers.get(r["product"]["id"]) if r["product"] else None} for r in rows],
            "final": [{"id": n, "title": next(x for x in g["nodes"] if x["id"] == n)["title"]} for n in final],
            "map_svg": projects.route_svg(g, img, numbers),
            "branches": any(len(x["children"]) > 1 for x in g["nodes"]),
        }

    @app.get("/api/projects")
    def list_projects():
        return {"projects": store.list_projects()}

    @app.post("/api/projects", status_code=201)
    def create_project(body: ProjectIn):
        data = body.model_dump(exclude_unset=True)
        ids = data.pop("experiment_ids", None) or []
        for eid in ids:
            need_exp(eid)
        return project_detail(store.create_project(data, ids))

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: int):
        return project_detail(project_id)

    @app.put("/api/projects/{project_id}")
    def update_project(project_id: int, body: ProjectIn):
        need_project(project_id)
        data = body.model_dump(exclude_unset=True)
        data.pop("experiment_ids", None)
        store.update_project(project_id, data)
        return project_detail(project_id)

    @app.delete("/api/projects/{project_id}", status_code=204)
    def delete_project(project_id: int):
        need_project(project_id)
        store.delete("projects", project_id)
        return Response(status_code=204)

    @app.post("/api/projects/{project_id}/experiments")
    def add_to_project(project_id: int, body: ProjectAdd):
        need_project(project_id)
        need_exp(body.experiment_id)
        store.add_to_project(project_id, body.experiment_id)
        return project_detail(project_id)

    @app.delete("/api/projects/{project_id}/experiments/{exp_id}")
    def remove_from_project(project_id: int, exp_id: int):
        need_project(project_id)
        store.remove_from_project(project_id, exp_id)
        return project_detail(project_id)

    @app.post("/api/projects/{project_id}/new", status_code=201)
    def new_in_project(project_id: int, body: ExperimentIn):
        """A new experiment in the project, not yet linked (the start of a route or a separate branch)."""
        need_project(project_id)
        data = body.model_dump(exclude_unset=True)
        data.pop("phases", None)
        if not data.get("author") and settings.author:
            data["author"] = settings.author
        eid = store.create_experiment(data)
        store.add_to_project(project_id, eid)
        out = project_detail(project_id)
        out["experiment_id"] = eid
        return out

    @app.post("/api/reagents/{rid}/branch", status_code=201)
    def branch(rid: int, body: BranchIn):
        """New experiment that starts from a portion of this product, in the product's projects (or a new one)."""
        prod = need("reagents", rid, "Reagent")
        if prod["role"] != "product":
            raise HTTPException(400, "Only a product can start a branch")
        parent = need_exp(prod["experiment_id"])
        title = body.title or f"From {scheme.label(prod)}"
        data = {"title": title}
        if settings.author:
            data["author"] = settings.author
        eid = store.create_experiment(data)
        stage = store.list("steps", "experiment_id = ?", (eid,))[0]["id"]
        _carry(eid, stage, prod, body.mass_g)
        if body.project_id:
            need_project(body.project_id)
            pids = [body.project_id]
        else:
            pids = [p["id"] for p in store.projects_of(parent["id"])]
        if not pids:
            pids = [store.create_project({"title": f"Route from {scheme.label(prod)}"}, [parent["id"]])]
        for pid in pids:
            if parent["id"] not in store.get_project(pid)["experiment_ids"]:
                store.add_to_project(pid, parent["id"])
            store.add_to_project(pid, eid)
        out = detail(eid)
        out["project_ids"] = pids
        return out

    @app.get("/api/products")
    def search_products(q: str = "", exclude: Optional[int] = None, limit: int = Query(12, ge=1, le=50)):
        """Products of experiments, to use as a starting material (a link between experiments)."""
        out = []
        for p in store.products(q, exclude, limit):
            left = remaining_of(store.get("reagents", p["id"]))
            out.append({**p, "remaining_g": left})
        return {"products": out}

    def _project_ctx(project_id: int, embed: bool, leaf: Optional[int]) -> dict:
        proj = need_project(project_id)
        bundles, calcs, g = project_parts(proj)
        if leaf is not None and leaf not in proj["experiment_ids"]:
            raise HTTPException(404, "That experiment is not in this project")
        return report.build_project_context(proj, bundles, calcs, g, settings, client if embed else None, leaf)

    def _project_name(ctx: dict) -> str:
        return _slug(ctx["title"])

    @app.get("/api/projects/{project_id}/report.md", response_class=PlainTextResponse)
    def project_md(project_id: int, download: bool = False, leaf: Optional[int] = None):
        ctx = _project_ctx(project_id, False, leaf)
        headers = ({"Content-Disposition": f'attachment; filename="{_project_name(ctx)}.md"'} if download else {})
        return PlainTextResponse(report.project_markdown(ctx), media_type="text/markdown; charset=utf-8",
                                 headers=headers)

    @app.get("/api/projects/{project_id}/report.html", response_class=HTMLResponse)
    def project_report_html(project_id: int, leaf: Optional[int] = None):
        return HTMLResponse(report.project_html(_project_ctx(project_id, True, leaf)))

    @app.get("/api/projects/{project_id}/report.pdf")
    def project_pdf(project_id: int, download: bool = True, leaf: Optional[int] = None):
        ctx = _project_ctx(project_id, True, leaf)
        try:
            pdf = report.to_pdf(report.project_html(ctx, for_pdf=True))
        except (ImportError, OSError) as e:
            raise HTTPException(501, f"PDF export is not available on this system: {e}")
        disp = "attachment" if download else "inline"
        return Response(pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'{disp}; filename="{_project_name(ctx)}.pdf"'})

    # -------------------------------------------------------------- PubChem Local proxy
    def _pc(fn, *args):
        try:
            return fn(*args)
        except PubChemUnavailable as e:
            raise HTTPException(503, str(e))

    @app.get("/api/pubchem/autocomplete")
    def pc_autocomplete(q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=50)):
        parsed = parse_reagent_query(q)
        return {"suggestions": _pc(client.autocomplete, parsed["query"], limit),
                "parsed": {k: v for k, v in parsed.items() if k != "query"}}

    @app.get("/api/pubchem/lookup")
    def pc_lookup(q: str = Query(..., min_length=1)):
        res = _pc(client.lookup, q)
        if not res:
            raise HTTPException(404, "Not found")
        return res

    @app.get("/api/pubchem/compound/{cid}/sources")
    def pc_sources(cid: int):
        return {"cid": cid, "properties": _pc(client.property_sources, cid)}

    @app.get("/api/pubchem/compound/{cid}/safety-summary")
    def pc_safety(cid: int):
        res = _pc(client.safety_summary, cid)
        if res is None:
            raise HTTPException(404, "Not found")
        return res

    def _image(item):
        if not item:
            raise HTTPException(404, "Not found")
        content, ctype = item
        return Response(content, media_type=ctype, headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/api/pubchem/compound/{cid}/structure.svg")
    def pc_structure(cid: int, width: int = Query(300, ge=40, le=1200), height: int = Query(240, ge=40, le=1200),
                     theme: Literal["light", "dark"] = "light"):
        return _image(_pc(client.structure_svg, cid, width, height, theme))

    @app.get("/api/pubchem/ghs/{code}.svg")
    def pc_ghs(code: str):
        if not re.fullmatch(r"GHS0[1-9]", code):
            raise HTTPException(404, "Unknown pictogram")
        return _image(_pc(client.ghs_svg, code))

    # -------------------------------------------------------------- reports
    def _ctx(exp_id: int, embed: bool) -> dict:
        b = store.bundle(exp_id)
        if not b:
            raise HTTPException(404, "Experiment not found")
        return report.build_context(b, compute(b), settings, client if embed else None)

    @app.get("/api/experiments/{exp_id}/report.md", response_class=PlainTextResponse)
    def report_md(exp_id: int, download: bool = False):
        ctx = _ctx(exp_id, embed=False)
        headers = ({"Content-Disposition": f'attachment; filename="{_slug(ctx["exp"]["title"])}.md"'}
                   if download else {})
        return PlainTextResponse(report.to_markdown(ctx), media_type="text/markdown; charset=utf-8",
                                 headers=headers)

    @app.get("/api/experiments/{exp_id}/report.html", response_class=HTMLResponse)
    def report_html(exp_id: int):
        return HTMLResponse(report.to_html(_ctx(exp_id, embed=True)))

    @app.get("/api/experiments/{exp_id}/report.pdf")
    def report_pdf(exp_id: int, download: bool = True):
        ctx = _ctx(exp_id, embed=True)
        try:
            pdf = report.to_pdf(report.to_html(ctx, for_pdf=True))
        except (ImportError, OSError) as e:
            raise HTTPException(501, f"PDF export is not available on this system: {e}")
        disp = "attachment" if download else "inline"
        return Response(pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'{disp}; filename="{_slug(ctx["exp"]["title"])}.pdf"'})

    # -------------------------------------------------------------- frontend
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    return app
