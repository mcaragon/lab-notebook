"""FastAPI application: JSON API, report downloads and the single-page frontend."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, db, report, stoich
from .config import Settings, load_settings
from .pubchem import PubChemClient, PubChemUnavailable, summary_to_reagent

STATIC = Path(__file__).parent / "static"


class ExperimentIn(BaseModel):
    title: Optional[str] = None
    date: Optional[str] = None
    author: Optional[str] = None
    course: Optional[str] = None
    status: Optional[Literal["planned", "in_progress", "completed"]] = None
    objective: Optional[str] = None
    reaction_scheme: Optional[str] = None
    procedure: Optional[str] = None
    results: Optional[str] = None
    discussion: Optional[str] = None
    conclusion: Optional[str] = None
    references: Optional[str] = None


class ReagentIn(BaseModel):
    query: Optional[str] = None  # create only: identifier to resolve with PubChem Local
    cid: Optional[int] = None
    name: Optional[str] = None
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
    actual_mass_g: Optional[float] = None
    notes: Optional[str] = None


class EntryIn(BaseModel):
    ts: Optional[str] = None
    kind: Optional[Literal["note", "observation", "measurement"]] = None
    text: Optional[str] = None
    value: Optional[str] = None
    unit: Optional[str] = None


class RefreshIn(BaseModel):
    fields: Optional[list[str]] = None  # None = every PubChem field


def _slug(title: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", title or "").strip("-")
    return (s or "experiment")[:60]


def create_app(settings: Optional[Settings] = None, pubchem: Optional[PubChemClient] = None) -> FastAPI:
    settings = settings or load_settings()
    store = db.Store(settings.db_path)
    client = pubchem or PubChemClient(settings.pubchem_url, settings.pubchem_timeout)

    app = FastAPI(title="Lab Notebook", version=__version__,
                  description="Organic chemistry lab notebook backed by PubChem Local.")
    app.state.store, app.state.pubchem, app.state.settings = store, client, settings

    def need_exp(exp_id: int) -> dict:
        exp = store.get_experiment(exp_id)
        if not exp:
            raise HTTPException(404, "Experiment not found")
        return exp

    def detail(exp_id: int) -> dict:
        exp = need_exp(exp_id)
        reagents = store.list_reagents(exp_id)
        calc = stoich.compute(db.stoich_rows(reagents))
        for r in reagents:
            r["calc"] = calc["rows"].get(r["id"])
        return {"experiment": exp, "reagents": reagents, "entries": store.list_entries(exp_id),
                "stoich": {k: v for k, v in calc.items() if k != "rows"}}

    # ------------------------------------------------------------------ meta
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
                "sections": db.SECTIONS, "roles": stoich.ROLES, "forms": stoich.FORMS, "bases": stoich.BASES}

    # ------------------------------------------------------------------ experiments
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
        store.update_experiment(exp_id, body.model_dump(exclude_unset=True))
        return {"experiment": store.get_experiment(exp_id)}

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

    # ------------------------------------------------------------------ reagents
    @app.post("/api/experiments/{exp_id}/reagents", status_code=201)
    def add_reagent(exp_id: int, body: ReagentIn):
        need_exp(exp_id)
        data = body.model_dump(exclude_unset=True)
        query = (data.pop("query", None) or "").strip()
        warning = None
        found = None
        if data.get("cid") or query:
            try:
                found = client.lab(data["cid"]) if data.get("cid") else client.lookup(query)
                if not found:
                    warning = f"“{query or data.get('cid')}” was not found in PubChem Local; enter its data manually."
            except PubChemUnavailable as e:
                warning = f"PubChem Local is unavailable ({e}); enter the data manually."
        values = summary_to_reagent(found) if found else {"sources": {}}
        user_chem = {k: v for k, v in data.items() if k in db.CHEM_FIELDS}
        values.update(data)
        for k in user_chem:
            if k in values["sources"] or not found:
                values["sources"][k] = "manual"
        if not values.get("name"):
            values["name"] = query or "Unnamed"
        if data.get("role") == "solvent" and "basis" not in data:
            values["basis"] = "volume"
        rid = store.add_reagent(exp_id, values)
        out = detail(exp_id)
        out["reagent_id"], out["warning"] = rid, warning
        return out

    @app.put("/api/reagents/{rid}")
    def update_reagent(rid: int, body: ReagentIn):
        current = store.get_reagent(rid)
        if not current:
            raise HTTPException(404, "Reagent not found")
        data = body.model_dump(exclude_unset=True)
        data.pop("query", None)
        changed = [k for k in data if k in db.CHEM_FIELDS + ["pictograms", "hazard_statements"]
                   and data[k] != current.get(k)]
        if changed:
            sources = dict(current.get("sources") or {})
            for k in changed:
                sources[k] = "manual"
            data["sources"] = sources
        store.update_reagent(rid, data)
        return detail(current["experiment_id"])

    @app.post("/api/reagents/{rid}/refresh")
    def refresh_reagent(rid: int, body: RefreshIn):
        """Re-read values from PubChem Local, replacing manual overrides (all fields or the listed ones)."""
        current = store.get_reagent(rid)
        if not current:
            raise HTTPException(404, "Reagent not found")
        if not current.get("cid"):
            raise HTTPException(400, "This reagent is not linked to a PubChem compound")
        try:
            found = client.lab(current["cid"])
        except PubChemUnavailable as e:
            raise HTTPException(503, str(e))
        if not found:
            raise HTTPException(404, "Compound not found in PubChem Local")
        values = summary_to_reagent(found)
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
        current = store.get_reagent(rid)
        if not current:
            raise HTTPException(404, "Reagent not found")
        store.delete_reagent(rid)
        return detail(current["experiment_id"])

    @app.put("/api/experiments/{exp_id}/reagents/order")
    def reorder_reagents(exp_id: int, ids: list[int]):
        need_exp(exp_id)
        store.reorder_reagents(exp_id, ids)
        return detail(exp_id)

    # ------------------------------------------------------------------ log entries
    @app.post("/api/experiments/{exp_id}/entries", status_code=201)
    def add_entry(exp_id: int, body: EntryIn):
        need_exp(exp_id)
        eid = store.add_entry(exp_id, body.model_dump(exclude_unset=True))
        return {"entry": store.get_entry(eid)}

    @app.put("/api/entries/{eid}")
    def update_entry(eid: int, body: EntryIn):
        e = store.update_entry(eid, body.model_dump(exclude_unset=True))
        if not e:
            raise HTTPException(404, "Entry not found")
        return {"entry": e}

    @app.delete("/api/entries/{eid}", status_code=204)
    def delete_entry(eid: int):
        if not store.delete_entry(eid):
            raise HTTPException(404, "Entry not found")
        return Response(status_code=204)

    # ------------------------------------------------------------------ PubChem Local proxy
    def _pc(fn, *args):
        try:
            return fn(*args)
        except PubChemUnavailable as e:
            raise HTTPException(503, str(e))

    @app.get("/api/pubchem/autocomplete")
    def pc_autocomplete(q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=50)):
        return {"suggestions": _pc(client.autocomplete, q, limit)}

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
    def pc_structure(cid: int, width: int = Query(300, ge=50, le=1200), height: int = Query(240, ge=50, le=1200),
                     theme: Literal["light", "dark"] = "light"):
        return _image(_pc(client.structure_svg, cid, width, height, theme))

    @app.get("/api/pubchem/ghs/{code}.svg")
    def pc_ghs(code: str):
        if not re.fullmatch(r"GHS0[1-9]", code):
            raise HTTPException(404, "Unknown pictogram")
        return _image(_pc(client.ghs_svg, code))

    # ------------------------------------------------------------------ reports
    def _ctx(exp_id: int) -> dict:
        reagents = store.list_reagents(need_exp(exp_id)["id"])
        calc = stoich.compute(db.stoich_rows(reagents))
        return report.build_context(store, exp_id, calc, settings)

    @app.get("/api/experiments/{exp_id}/report.md", response_class=PlainTextResponse)
    def report_md(exp_id: int, download: bool = False):
        ctx = _ctx(exp_id)
        headers = ({"Content-Disposition": f'attachment; filename="{_slug(ctx["exp"]["title"])}.md"'}
                   if download else {})
        return PlainTextResponse(report.to_markdown(ctx), media_type="text/markdown; charset=utf-8",
                                 headers=headers)

    @app.get("/api/experiments/{exp_id}/report.html", response_class=HTMLResponse)
    def report_html(exp_id: int):
        ctx = report.embed_images(_ctx(exp_id), client)
        return HTMLResponse(report.to_html(ctx))

    @app.get("/api/experiments/{exp_id}/report.pdf")
    def report_pdf(exp_id: int, download: bool = True):
        ctx = report.embed_images(_ctx(exp_id), client)
        try:
            pdf = report.to_pdf(report.to_html(ctx, for_pdf=True))
        except (ImportError, OSError) as e:
            raise HTTPException(501, f"PDF export is not available on this system: {e}")
        disp = "attachment" if download else "inline"
        return Response(pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'{disp}; filename="{_slug(ctx["exp"]["title"])}.pdf"'})

    # ------------------------------------------------------------------ frontend
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    return app
