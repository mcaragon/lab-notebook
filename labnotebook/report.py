"""Lab report generation: Markdown, HTML (print view) and PDF (HTML rendered by WeasyPrint).

Also renders the reaction scheme fragment that the app shows at the top of an experiment.
"""
from __future__ import annotations

import base64
import html
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import markdown as md
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import actions, costs as costs_mod, db, hazards, projects, scheme
from .pubchem import PubChemClient, PubChemUnavailable
from .structures import structure

TEMPLATES = Path(__file__).parent / "templates"
ROLE_LABELS = {"reactant": "Reactant", "reagent": "Reagent", "catalyst": "Catalyst", "solvent": "Solvent",
               "workup": "Workup", "product": "Product"}
GHS_NAMES = {
    "GHS01": "Explosive", "GHS02": "Flammable", "GHS03": "Oxidizer", "GHS04": "Compressed gas",
    "GHS05": "Corrosive", "GHS06": "Acute toxicity", "GHS07": "Harmful / irritant", "GHS08": "Health hazard",
    "GHS09": "Environmental hazard",
}


# ------------------------------------------------------------------------------------------- formatting
def fmt(v: Any, sig: int = 3) -> str:
    """Format a number with ``sig`` significant figures, without scientific notation."""
    if v is None or v == "":
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f == 0:
        return "0"
    decimals = max(0, sig - 1 - int(math.floor(math.log10(abs(f)))))
    return f"{f:.{decimals}f}"


def fmt_fixed(v: Any, decimals: int) -> str:
    if v is None or v == "":
        return ""
    return f"{float(v):.{decimals}f}"


def fmt_ts(ts: Optional[str], with_date: bool = True) -> str:
    d = db.parse_ts(ts)
    if not d:
        return ts or ""
    return d.strftime("%Y-%m-%d %H:%M" if with_date else "%H:%M")


def fmt_elapsed(s: Optional[float]) -> str:
    """T+ as h:mm:ss."""
    if s is None:
        return ""
    sign = "−" if s < 0 else ""
    s = abs(int(round(s)))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{sign}{h}:{m:02d}:{sec:02d}"


def h_code(statement: str) -> str:
    """'H225: Highly flammable ...' -> 'H225'."""
    m = re.match(r"\s*((?:EU)?H\d{3}[A-Za-z+H\d]*)", statement or "")
    return m.group(1) if m else (statement or "")


def h_text(statement: str) -> str:
    """Strip the bracketed GHS classification PubChem appends: 'H225: ... vapor [Danger ...]' -> 'H225: ... vapor'."""
    return re.sub(r"\s*\[[^\]]*\]\s*$", "", statement or "").strip()


H_RE = re.compile(r"^\s*(?:EU)?H\d{3}")


def ghs_statements(statements: list[str]) -> tuple[list[str], bool]:
    """Real H-statements (unique by code) and whether PubChem reports the substance as not classified.

    PubChem's GHS list also carries entries such as "Not Classified" and "Reported as not meeting GHS hazard
    criteria by 1866 of 1876 companies ..."; those are not hazard statements."""
    real = [s for s in statements or [] if H_RE.match(s or "")]
    not_classified = any(not H_RE.match(s or "") and ("not classified" in (s or "").lower()
                                                       or "not meeting ghs" in (s or "").lower())
                         for s in statements or [])
    return unique_h(real), not_classified


def unique_h(statements: list[str]) -> list[str]:
    seen, out = set(), []
    for s in statements or []:
        t = h_text(s)
        code = h_code(t)
        if code not in seen:
            seen.add(code)
            out.append(t)
    return out


def amount_text(r: dict, mass: Optional[float], vol: Optional[float]) -> str:
    """'1.06 g', '15.0 mL', '0.189 g' — volume for liquids, solutions and solvents, mass otherwise."""
    liquid = r.get("form") != "neat" or r.get("role") in ("solvent", "workup") \
        or r.get("basis") == "volume" or r.get("actual_basis") == "volume"
    if liquid and vol is not None:
        return f"{fmt(vol)} mL"
    if mass is not None:
        return f"{fmt(mass)} g"
    if vol is not None:
        return f"{fmt(vol)} mL"
    return ""


def form_text(r: dict) -> str:
    form = r.get("form") or "neat"
    if form == "solution" and r.get("concentration_m"):
        return f"{fmt(r['concentration_m'])} M solution"
    if form == "wt" and r.get("wt_percent"):
        return f"{fmt(r['wt_percent'])} wt% solution"
    if r.get("purity") and float(r["purity"]) < 100:
        return f"{fmt(r['purity'])}% purity"
    return ""


def provenance(r: dict) -> str:
    """'ReagentPlus 99%, Sigma-Aldrich, lot MKCB1234'."""
    parts = [p for p in (r.get("grade"), r.get("supplier")) if p]
    if r.get("lot"):
        parts.append(f"lot {r['lot']}")
    return ", ".join(parts)


def format_ref(r: dict) -> str:
    """ACS-like citation from reference fields; the free-text field is used as is."""
    if not any(r.get(k) for k in ("authors", "title", "source", "doi", "url")):
        return (r.get("text") or "").strip()
    parts = []
    if r.get("authors"):
        parts.append(r["authors"].rstrip(".") + ".")
    if r.get("title"):
        parts.append(r["title"].rstrip(".") + ".")
    src = " ".join(p for p in [r.get("source") or "", r.get("year") or ""] if p)
    tail = ", ".join(p for p in [src, r.get("volume") or "", r.get("pages") or ""] if p)
    if tail:
        parts.append(tail + ".")
    if r.get("doi"):
        parts.append(f"DOI: {r['doi']}.")
    elif r.get("url"):
        parts.append(r["url"])
    if r.get("text"):
        parts.append(r["text"])
    return " ".join(parts)


# ------------------------------------------------------------------------------------------- templates
_env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))
_env.filters.update(fmt=fmt, fmt_fixed=fmt_fixed, temp=actions.fmt_temp)
# User text is Markdown; raw HTML in it is shown as text, never rendered (reports are served from the app's origin)
_SAFE_URL = re.compile(r"^(https?:|mailto:|#|/(?!/)|[^:/?#]*$)", re.I)


def _url_ok(m: re.Match) -> str:
    url = re.sub(r"[\x00-\x20]", "", html.unescape(m.group(2)))
    return m.group(0) if _SAFE_URL.match(url) else f'{m.group(1)}="#"'


def safe_markdown(text: str) -> str:
    """Markdown to HTML without raw HTML and without script links (javascript:, data:, ...)."""
    out = md.markdown(html.escape(text or "", quote=False).replace("&gt;", ">"),
                      extensions=["extra", "sane_lists", "nl2br"])
    return re.sub(r'\b(href|src)="([^"]*)"', _url_ok, out, flags=re.I)


_env.filters["md"] = safe_markdown


def nfpa_svg(n: Optional[dict], size_mm: float = 7) -> str:
    """NFPA 704 diamond as inline SVG (renders in browsers and WeasyPrint)."""
    if not n:
        return ""

    def t(x: float, y: float, v: Any, fill: str) -> str:
        return (f'<text x="{x}" y="{y}" font-size="9" font-weight="700" text-anchor="middle" '
                f'font-family="DejaVu Sans, sans-serif" fill="{fill}">{"" if v is None else v}</text>')

    return (f'<svg class="nfpa" width="{size_mm}mm" height="{size_mm}mm" viewBox="0 0 40 40">'
            '<polygon points="20,1 29.5,10.5 20,20 10.5,10.5" fill="#d62728"/>'
            '<polygon points="10.5,10.5 20,20 10.5,29.5 1,20" fill="#1f62b0"/>'
            '<polygon points="29.5,10.5 39,20 29.5,29.5 20,20" fill="#f2c80f"/>'
            '<polygon points="20,20 29.5,29.5 20,39 10.5,29.5" fill="#fff" stroke="#999" stroke-width=".6"/>'
            + t(20, 14, n.get("fire"), "#fff") + t(10.5, 23, n.get("health"), "#fff")
            + t(29.5, 23, n.get("instability"), "#000") + t(20, 32.5, n.get("special") or "", "#000") + "</svg>")


_env.globals["nfpa_svg"] = nfpa_svg
_env.filters["money"] = lambda v, cur="USD": costs_mod.money(v, cur)


def _scheme_html(sch: dict, img_src: Callable[[dict, int, int], Optional[str]]) -> str:
    return _env.get_template("scheme.html").render(sch=sch, img_src=img_src)


def scheme_html(bundle: dict, calc: dict, img_src: Callable[[dict, int, int], Optional[str]]) -> str:
    """The reaction scheme as an HTML fragment (``img_src(reagent, w, h)`` gives each structure's image URL)."""
    return _scheme_html(scheme.build_experiment(bundle, calc), img_src)


def _data_uri(item: Optional[tuple[bytes, str]]) -> Optional[str]:
    if not item:
        return None
    content, ctype = item
    ctype = ctype.split(";")[0].strip() or "image/svg+xml"
    return f"data:{ctype};base64,{base64.b64encode(content).decode()}"


def embedded_images(reagents: list[dict], client: Optional[PubChemClient]) -> tuple[dict, dict]:
    """Structure and GHS pictogram data URIs (empty when PubChem Local is unavailable)."""
    structures_by_id, ghs = {}, {}
    if client is None:
        return structures_by_id, ghs
    by_ident: dict = {}
    for r in reagents:
        key = r.get("cid") or r.get("smiles")
        if not key:
            continue
        if key not in by_ident:
            by_ident[key] = _data_uri(structure(client, r.get("cid"), r.get("smiles"), 240, 170))
        structures_by_id[r["id"]] = by_ident[key]
    try:
        for code in sorted({p for r in reagents for p in (r.get("pictograms") or [])}):
            ghs[code] = _data_uri(client.ghs_svg(code))
    except PubChemUnavailable:
        pass
    return structures_by_id, ghs


# ------------------------------------------------------------------------------------------- context
def hazard_info(r: dict) -> dict:
    """Everything the hazard cell of a reagent row shows."""
    extra = r.get("extra_hazards") or {}
    dot = extra.get("dot") or {}
    statements, not_classified = ghs_statements(r.get("hazard_statements"))
    dot_parts = list(dot.get("un") or [])
    dot_parts += [re.sub(r"^(Class|Div)\s+([\d.]+[A-Z]?).*", r"\1 \2", c)
                  for c in dot.get("classes") or [] if "forbidden" not in c.lower()][:2]
    if dot.get("packing_groups"):
        dot_parts.append("PG " + "/".join(dot["packing_groups"]))
    return {
        "pictograms": r.get("pictograms") or [], "signal": r.get("signal_word"), "fp": r.get("flash_point"),
        "codes": [h_code(h) for h in statements], "statements": statements,
        "dot": ", ".join(dot_parts), "forbidden": bool(dot.get("forbidden")), "nfpa": extra.get("nfpa"),
        "alerts": extra.get("alerts") or [], "notes": r.get("hazard_notes"),
        "not_classified": not_classified and not statements,
    }


def _row(r: dict, c: dict, usage: dict, ref_no: dict) -> dict:
    """A reagent row of the report: one amount — measured if recorded, otherwise planned (flagged)."""
    measured = c.get("act_mass_g") is not None or c.get("act_volume_ml") is not None
    if measured:
        amount = amount_text(r, c.get("act_mass_g"), c.get("act_volume_ml"))
        mmol, equiv = c.get("act_mmol"), c.get("act_equiv")
    else:
        amount = amount_text(r, c.get("mass_g"), c.get("volume_ml"))
        mmol, equiv = c.get("mmol"), c.get("equiv")
    solvent = r.get("role") in ("solvent", "workup")
    used = ", ".join(f"{fmt(v)} {k}" for k, v in usage.items()) if solvent else ""
    if solvent:
        mmol = equiv = None
        if not amount and used:
            amount, used = used, ""
    return {
        "r": r, "c": c, "role": ROLE_LABELS.get(r.get("role"), r.get("role") or ""),
        "amount": amount, "planned_only": bool(amount) and not measured and not (solvent and not r.get("basis_value")),
        "mmol": mmol, "equiv": equiv, "used": used,
        "form": form_text(r), "provenance": provenance(r), "haz": hazard_info(r),
        "expected_ref": ref_no.get(r.get("expected_ref_id")),
    }


def pair_procedure_log(procedure: list[dict], log: list[dict]) -> list[dict]:
    """Rows of procedure steps with the log entries made during each one.

    An entry belongs to its procedure step; entries without one join the step worked on at that time (that of the
    entry before them). Entries before any step form a first row without a step."""
    rows = [{"p": p, "entries": []} for p in procedure]
    by_id = {r["p"]["id"]: r for r in rows}
    before = {"p": None, "entries": []}
    current = None
    for e in log:
        row = by_id.get(e.get("procedure_id"))
        if row is not None:
            current = row
        (current or before)["entries"].append(e)
    return ([before] if before["entries"] else []) + rows


def phase_groups(phases: list[dict], proc_log: list[dict]) -> list[dict]:
    """Procedure-and-log rows by phase, in phase order; phases without rows are left out. Log entries made before
    the first procedure row open the first group."""
    groups = [{"key": p["key"], "label": p["label"], "rows": []} for p in phases]
    by_key = {g["key"]: g for g in groups}
    before = []
    for row in proc_log:
        if row["p"] is None:
            before.append(row)
        else:
            by_key.get(row["p"].get("phase"), by_key[db.DEFAULT_PHASE])["rows"].append(row)
    out = [g for g in groups if g["rows"]]
    if before:
        if out:
            out[0]["rows"] = before + out[0]["rows"]
        else:
            out = [{"key": "log", "label": "Log", "rows": before}]
    return out


def build_context(bundle: dict, calc: dict, settings: Any = None,
                  client: Optional[PubChemClient] = None, images: Optional[tuple[dict, dict]] = None,
                  numbers: Optional[dict] = None, step_offset: int = 0, idents: Optional[dict] = None) -> dict:
    """Everything the report templates need for one experiment. With ``client``, structures and pictograms are
    embedded.

    ``numbers`` and ``step_offset`` let a chapter of a project report use the project's compound numbers and arrow
    letters."""
    exp = bundle["experiment"]
    rows = calc["rows"]
    reagents = bundle["reagents"]
    use = actions.usage(bundle["entries"])
    ref_no = {r["id"]: i for i, r in enumerate(bundle["refs"], 1)}
    structures_by_id, ghs = images or embedded_images(reagents, client)
    img = lambda r, w, h: structures_by_id.get(r["id"])  # noqa: E731
    stages = bundle["steps"]
    multi_stage = len(stages) > 1
    stage_no = {s["id"]: i for i, s in enumerate(stages, 1)}

    sch = scheme.build_experiment(bundle, calc, numbers=numbers, first_index=step_offset, idents=idents)
    exp_date = exp.get("date") or ""
    rs = []
    for r in reagents:
        x = _row(r, rows.get(r["id"], {}), use.get(r["id"], {}), ref_no)
        x["stage"] = stage_no.get(r.get("step_id"), 1) if multi_stage else None
        rs.append(x)
    inputs = [x for x in rs if x["r"]["role"] != "product"]
    if multi_stage:
        inputs.sort(key=lambda x: x["stage"])
    legend: dict[str, str] = {}
    for x in rs:
        for code, text in zip(x["haz"]["codes"], x["haz"]["statements"]):
            legend.setdefault(code, text)
    procedure = [{**p, "n": n, "rendered": scheme.render_mentions(p.get("text") or "", reagents, rows),
                  "html": scheme.render_mentions(p.get("text") or "", reagents, rows, mode="html")}
                 for n, p in enumerate(bundle["procedure"], 1)]
    proc_no = {p["id"]: p["n"] for p in procedure}
    log = [{**e, "time": fmt_ts(e["ts"], with_date=not exp_date or not (e["ts"] or "").startswith(exp_date)),
            "tplus": fmt_elapsed(e.get("elapsed_s")), "proc_no": proc_no.get(e.get("procedure_id"))}
           for e in bundle["entries"]]
    proc_log = pair_procedure_log(procedure, log)
    groups = phase_groups(db.phase_list(exp), proc_log)

    sections = {k: (exp.get(k) or "").strip() for k in db.SECTION_KEYS}
    refs = [{"n": i, "text": format_ref(r)} for i, r in enumerate(bundle["refs"], 1) if format_ref(r)]
    cited, cids = [], set()
    for r in reagents:
        if r.get("cid") and r["cid"] not in cids:
            cids.add(r["cid"])
            cited.append(r)
    return {
        "exp": exp, "inputs": inputs, "products": [x for x in rs if x["r"]["role"] == "product"],
        "legend": sorted(legend.items(), key=lambda kv: kv[0]),
        "planned_only": any(x["planned_only"] for x in inputs),
        "multi_stage": multi_stage,
        "stages": [{"n": i, "s": s, "conditions": scheme.conditions_text(s)} for i, s in enumerate(stages, 1)],
        "procedure": procedure, "log": log, "proc_log": proc_log, "phase_groups": groups,
        "yield": calc.get("yield"),
        "sections": sections, "headings": dict(db.SECTIONS), "refs": refs, "cited": cited, "n_refs": len(refs),
        "scheme": sch, "scheme_html": _scheme_html(sch, img),
        "status_label": (exp.get("status") or "").replace("_", " ").capitalize(),
        "lab_name": getattr(settings, "lab_name", "") if settings else "",
        "generated": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
        "ghs": ghs, "ghs_names": GHS_NAMES,
        "duration": fmt_elapsed(db.elapsed_between(exp.get("started_at"), exp.get("ended_at")))
        if exp.get("ended_at") else "",
    }


def project_numbers(g: dict, bundles: list[dict], calcs: list[dict]) -> tuple[dict, dict]:
    """Compound numbers across a project, in route order: ``(numbers by reagent id, numbers by compound)``. A product
    keeps its number where it is used, and the same compound keeps one number throughout."""
    by_id = {b["experiment"]["id"]: (b, c) for b, c in zip(bundles, calcs)}
    numbers: dict = {}
    idents: dict = {}
    for eid in projects.topo_order(g):
        b, c = by_id[eid]
        sch = scheme.build_experiment(b, c, numbers=numbers, idents=idents)
        numbers, idents = sch["numbers"], sch["idents"]
    return numbers, idents


def build_project_context(proj: dict, bundles: list[dict], calcs: list[dict], g: dict, settings: Any = None,
                          client: Optional[PubChemClient] = None, leaf: Optional[int] = None,
                          currency: Optional[str] = None) -> dict:
    """A project report: route map and summary, then one chapter per experiment in route order.

    With ``leaf``, only the route to that experiment (it and everything that feeds it), with its linear scheme."""
    by_id = {b["experiment"]["id"]: (b, c) for b, c in zip(bundles, calcs)}
    ids = projects.ancestors(g, leaf) if leaf is not None else projects.topo_order(g)
    numbers, idents = project_numbers(g, bundles, calcs)
    included = [by_id[i] for i in ids]
    images = embedded_images([r for b, _ in included for r in b["reagents"]], client)
    img = lambda r, w, h: images[0].get(r["id"])  # noqa: E731
    node = {x["id"]: x for x in g["nodes"]}
    linear = all(len(node[i]["children"]) <= 1 and len(node[i]["parents"]) <= 1 for i in ids) and \
        sum(1 for i in ids if not node[i]["parents"]) <= 1
    chain = projects.main_chain(g, leaf) if leaf is not None else (ids if linear else [])
    sch = None
    if len(chain) > 1:
        rxs = [scheme.reaction_of(by_id[i][0]) for i in chain]
        sch = scheme.build(rxs, projects.combined_calc([by_id[i][1] for i in chain])["rows"],
                           proj.get("scheme_style") or "auto", numbers, idents=idents)
    chapters = [build_context(b, c, settings, images=images, numbers=numbers, step_offset=n, idents=idents)
                for n, (b, c) in enumerate(included)]
    summary = projects.summary_rows(g, ids)
    for r in summary:
        r["number"] = numbers.get(r["product"]["id"]) if r["product"] else None
    shown = set(ids)
    materials = []
    for m in g.get("materials", []):
        uses = [dict(u, title=node[u["experiment_id"]]["title"]) for u in m["uses"] if u["experiment_id"] in shown]
        if uses:
            used = [u["taken_g"] for u in uses if u["taken_g"] is not None]
            materials.append({**m, "uses": uses, "used_g": sum(used) if used else None,
                              "number": numbers.get(m["reagent"]["id"])})
    target = node[leaf]["title"] if leaf is not None else None
    return {
        "proj": proj, "title": proj["title"] + (f" — route to {target}" if target else ""), "leaf": target,
        "chapters": chapters, "summary": summary, "materials": materials, "currency": currency,
        "map_svg": projects.route_svg(g, img, numbers, link=False, only=set(ids), inline_css=True, currency=currency)
        if len(ids) > 1 else "",
        "scheme": sch, "scheme_html": _scheme_html(sch, img) if sch and not sch["empty"] else "",
        "overall_yield": node[chain[-1]]["overall_yield"] if len(chain) > 1 else None,
        "lls": len(chain), "lab_name": getattr(settings, "lab_name", "") if settings else "",
        "generated": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"), "ghs": images[1], "ghs_names": GHS_NAMES,
    }


# ------------------------------------------------------------------------------------------- Markdown
def _cell(s: Any) -> str:
    return str(s or "").replace("|", "\\|").replace("\n", " ")


def _table(head: list[str], align: list[str], body: list[list[Any]]) -> list[str]:
    sep = {"l": "---", "r": "---:"}
    return ["| " + " | ".join(head) + " |", "| " + " | ".join(sep[a] for a in align) + " |",
            *("| " + " | ".join(_cell(v) for v in r) + " |" for r in body), ""]


def _md_scheme(sch: dict) -> list[str]:
    line = []
    for seg in sch["segments"]:
        if seg["type"] == "mols":
            line.append(" + ".join(f"{scheme.label(m['reagent'])} (**{m['number']}**)"
                                   + (f", {m['yield']:.0f}%" if m.get("yield") is not None else "")
                                   for m in seg["mols"]))
        else:
            text = f"({seg['letter']})" if sch["lettered"] else "; ".join(seg["above"] + seg["below"])
            line.append(f"→[{text}]→" if text else "→")
    out = [" ".join(line), ""]
    out += [f"- ({letter}) {text}" for letter, text in sch["legend"]]
    return out + ([""] if sch["legend"] else [])


def _md_hazard(h: dict) -> str:
    parts = []
    if h["forbidden"]:
        parts.append("**DOT: forbidden for transport**")
    if h["pictograms"]:
        parts.append(" ".join(h["pictograms"]))
    if h["signal"]:
        parts.append(h["signal"])
    if h["codes"]:
        parts.append(" ".join(h["codes"]))
    elif h.get("not_classified"):
        parts.append("Not classified (GHS)")
    if h["fp"] is not None:
        parts.append(f"fp {fmt_fixed(h['fp'], 0)} °C")
    if h["dot"]:
        parts.append(f"DOT {h['dot']}")
    if h["nfpa"]:
        n = h["nfpa"]
        parts.append(f"NFPA {n['health']}-{n['fire']}-{n['instability']}" + (f" {n['special']}" if n.get("special") else ""))
    if h["alerts"]:
        parts.append(", ".join(h["alerts"]))
    if h["notes"]:
        parts.append(h["notes"])
    return "; ".join(parts)


def _md_reagents(ctx: dict) -> list[str]:
    out: list[str] = []
    body = []
    for x in ctx["inputs"]:
        r = x["r"]
        name = r.get("name") or "?"
        extra = [v for v in (x["form"], x["provenance"], r.get("notes")) if v]
        if extra:
            name += f" ({'; '.join(extra)})"
        if x["c"].get("is_limiting"):
            name += " — limiting"
        props = [p for p in (f"d {fmt(r['density'])}" if r.get("density") else "",
                             f"bp {fmt_fixed(r['bp'], 0)}" if r.get("bp") is not None else "",
                             f"mp {fmt_fixed(r['mp'], 0)}" if r.get("mp") is not None else "") if p]
        role = (f"{x['stage']}. " if x.get("stage") else "") + x["role"]
        body.append([name, role, fmt_fixed(r.get("mw"), 2), x["amount"] + (" *" if x["planned_only"] else ""),
                     fmt(x["mmol"]), fmt_fixed(x["equiv"], 2), ", ".join(props), _md_hazard(x["haz"])])
    out += _table(["Compound", "Stage · role" if ctx["multi_stage"] else "Role", "MW", "Amount", "mmol", "equiv",
                   "Properties", "Hazards"], ["l", "l", "r", "r", "r", "r", "l", "l"], body)
    if ctx["planned_only"]:
        out += ["\\* planned amount; no measurement recorded.", ""]
    if ctx["legend"]:
        out += ["Hazard statements: " + "; ".join(text for _, text in ctx["legend"]), ""]
    return out


def _entry_line(e: dict) -> str:
    val = f" ({e['value']} {e.get('unit') or ''})".rstrip() if e.get("value") else ""
    when = e["time"] + (f", T+{e['tplus']}" if e["tplus"] else "")
    return f"{when}: {e['text']}{val}"


def _md_procedure(ctx: dict, lvl: int) -> list[str]:
    h = "#" * lvl
    out: list[str] = [f"{h} Procedure and log", ""]
    for grp in ctx["phase_groups"]:
        out += [f"{h}# {grp['label']}", ""]
        for row in grp["rows"]:
            p = row["p"]
            if p is None:
                out.append("*Before the procedure:*")
                out += [f"- {_entry_line(e)}" for e in row["entries"]]
                out.append("")
                continue
            line = f"{p['n']}. {p['rendered']}"
            if p.get("done_at"):
                line += f" *(done {fmt_ts(p['done_at'], with_date=False)})*"
            out.append(line)
            if p.get("notes"):
                out.append(f"   - *Note:* {p['notes']}")
            out += [f"   - {_entry_line(e)}" for e in row["entries"]]
        out.append("")
    return out


def _md_yield(ctx: dict) -> list[str]:
    body = []
    for x in ctx["products"]:
        r, c = x["r"], x["c"]
        theo = f"{fmt(c['theoretical_mass_g'])} g ({fmt(c['theoretical_mmol'])} mmol)" \
            if c.get("theoretical_mass_g") is not None else ""
        expd = ""
        if c.get("expected_yield_pct") is not None:
            expd = f"{c['expected_yield_pct']:.0f}%"
            if c.get("expected_mass_g") is not None:
                expd += f" ({fmt(c['expected_mass_g'])} g)"
            if x["expected_ref"]:
                expd += f" [{x['expected_ref']}]"
        crude = (f"{fmt(c['crude_mass_g'])} g" + (f" ({c['crude_percent']:.0f}%)" if c.get("crude_percent")
                                                  is not None else "")) if c.get("crude_mass_g") else ""
        iso = f"{fmt(c['isolated_mass_g'])} g" if c.get("isolated_mass_g") is not None else ""
        if iso and c.get("isolated_mmol") is not None:
            iso += f" ({fmt(c['isolated_mmol'])} mmol)"
        yld = f"{c['percent_yield']:.1f}%" if c.get("percent_yield") is not None else ""
        body.append([r.get("name"), fmt_fixed(r.get("mw"), 2), theo, expd, crude, iso, yld])
    return _table(["Product", "MW", "Theoretical", "Expected", "Crude", "Isolated", "Yield"],
                  ["l", "r", "r", "r", "r", "r", "r"], body)


def _md_cost(c: dict, cur: str) -> list[str]:
    m = lambda v: costs_mod.money(v, cur)  # noqa: E731
    body = []
    for x in c["inputs"]:
        src = ""
        if x["source"] and x["source"]["kind"] == "stock":
            src = ", ".join(v for v in (x["source"].get("supplier"), f"lot {x['source']['lot']}" if x["source"].get("lot") else "") if v)
        elif x["source"]:
            src = "from an earlier step"
        amount = f"{fmt(x['amount'])} {x['unit']}" if x["amount"] is not None else ""
        body.append([x["name"], src, amount + (" *" if x["estimated"] and x["cost"] is not None else ""),
                     f"{m(x['unit_price'])}/{x['unit']}" if x["unit_price"] is not None else "",
                     m(x["cost"]) if x["cost"] is not None else f"no price ({x.get('why', '')})",
                     f"{x['share'] * 100:.0f}%" if x["share"] is not None else ""])
    out = _table(["Input", "Source", "Amount", "Price", "Cost", "Share"], ["l", "l", "r", "r", "r", "r"], body)
    total = m(c["total"]) if c["total"] is not None else "—"
    line = f"**Total:** {total}" + ("" if c["complete"] else " (incomplete: " + ", ".join(c["unpriced"]) + " without a price)")
    p = c.get("product") or {}
    if p.get("cost_per_g") is not None:
        line += f" · **{p['name']}:** {m(p['cost_per_g'])}/g" + (" (crude)" if p.get("crude") else "")
    out += [line, ""]
    if c["estimated"]:
        out += ["\\* planned amount (no measurement): estimated.", ""]
    return out


def _md_body(ctx: dict, lvl: int = 2) -> list[str]:
    exp, s, H = ctx["exp"], ctx["sections"], ctx["headings"]
    h = "#" * lvl
    out: list[str] = []
    meta = [("Date", exp.get("date")), ("Author", exp.get("author")), ("Course", exp.get("course")),
            ("Lab", ctx.get("lab_name")), ("Status", ctx["status_label"]), ("Duration", ctx["duration"])]
    out += [f"**{k}:** {v}  " for k, v in meta if v]
    out.append("")
    if s["objective"]:
        out += [f"{h} {H['objective']}", "", s["objective"], ""]
    if not ctx["scheme"]["empty"]:
        out += [f"{h} Reaction", ""] + _md_scheme(ctx["scheme"])
    if ctx["inputs"]:
        out += [f"{h} Reagents", ""] + _md_reagents(ctx)
    if ctx["procedure"] or ctx["log"]:
        out += _md_procedure(ctx, lvl)
    if ctx["products"]:
        out += [f"{h} Yield", ""] + _md_yield(ctx)
    if ctx.get("cost"):
        out += [f"{h} Cost", ""] + _md_cost(ctx["cost"], ctx.get("currency") or "USD")
    if s["results"]:
        out += [f"{h} {H['results']}", "", s["results"], ""]
    for key in ("discussion", "conclusion"):
        if s[key]:
            out += [f"{h} {H[key]}", "", s[key], ""]
    if ctx["refs"] or ctx["cited"]:
        out += [f"{h} References", ""]
        for r in ctx["refs"]:
            out.append(f"{r['n']}. {r['text']}")
        for i, r in enumerate(ctx["cited"], ctx["n_refs"] + 1):
            out.append(f"{i}. {r['name']}: PubChem CID {r['cid']}, {r.get('pubchem_url') or ''} (data via PubChem Local).")
        out.append("")
    return out


def to_markdown(ctx: dict) -> str:
    out = [f"# {ctx['exp']['title']}", ""] + _md_body(ctx, 2)
    out += ["---", f"*Generated {ctx['generated']} by Lab Notebook.*", ""]
    return "\n".join(out)


def _route_table(summary: list[dict], currency: Optional[str] = None) -> list[str]:
    body = []
    for r in summary:
        frm = "; ".join(f"{f['title']}" + (f" ({fmt(f['taken_g'])} g)" if f["taken_g"] is not None else "")
                        for f in r["from"])
        prod = (f"**{r['number']}** " if r.get("number") else "") + (scheme.label(r["product"]) if r["product"] else "")
        body.append([r["n"], r["title"], frm, prod, f"{fmt(r['isolated_g'])} g" if r["isolated_g"] is not None else "",
                     f"{r['yield']:.1f}%" if r["yield"] is not None else "",
                     f"{fmt(r['remaining_g'])} g" if r["remaining_g"] is not None else "",
                     f"{r['overall_yield']:.1f}% ({r['lls']} step{'s' if r['lls'] != 1 else ''})" if r["overall_yield"] is not None else ""]
                    + ([_md_per_g(r, currency)] if currency else []))
    return _table(["#", "Experiment", "From", "Product", "Isolated", "Yield", "Left", "Overall"] + (["Cost/g"] if currency else []),
                  ["r", "l", "l", "l", "r", "r", "r", "r"] + (["r"] if currency else []), body)


def _md_per_g(r: dict, currency: str) -> str:
    c = r.get("cost") or {}
    per_g = (c.get("product") or {}).get("cost_per_g")
    if per_g is None:
        return ""
    return ("≥" if not c.get("complete") else "") + costs_mod.money(per_g, currency)


def project_markdown(ctx: dict) -> str:
    proj = ctx["proj"]
    out = [f"# {ctx['title']}", ""]
    if proj.get("notes"):
        out += [proj["notes"], ""]
    if ctx["scheme"] and not ctx["scheme"]["empty"]:
        out += ["## Route", ""] + _md_scheme(ctx["scheme"])
    if ctx["materials"]:
        out += ["## Starting materials", ""]
        body = []
        for m in ctx["materials"]:
            name = (f"**{m['number']}** " if m.get("number") else "") + m["name"]
            src = ", ".join(x for x in (m.get("supplier"), f"lot {m['lot']}" if m.get("lot") else "") if x)
            body.append([name, src, "; ".join(f"{u['title']}" + (f" ({fmt(u['taken_g'])} g)" if u["taken_g"] is not None
                                                                else "") for u in m["uses"]),
                         f"{fmt(m['used_g'])} g" if m["used_g"] is not None else "",
                         f"{fmt(m['on_hand_g'])} g" if m.get("on_hand_g") is not None else "",
                         f"{fmt(m['on_hand_g'] - (m['used_g'] or 0))} g" if m.get("on_hand_g") is not None else ""])
        out += _table(["Compound", "Source", "Used in", "Used", "On hand", "Left"], ["l", "l", "l", "r", "r", "r"], body)
    if ctx["summary"]:
        out += ["## Experiments", ""] + _route_table(ctx["summary"], ctx.get("currency"))
    if ctx["overall_yield"] is not None:
        out += [f"**Overall yield:** {ctx['overall_yield']:.1f}% over {ctx['lls']} steps", ""]
    for i, ch in enumerate(ctx["chapters"], 1):
        out += [f"## {i}. {ch['exp']['title']}", ""] + _md_body(ch, 3)
    out += ["---", f"*Generated {ctx['generated']} by Lab Notebook.*", ""]
    return "\n".join(out)


# ------------------------------------------------------------------------------------------- HTML / PDF
def to_html(ctx: dict, for_pdf: bool = False) -> str:
    return _env.get_template("report.html").render(**ctx, self_ctx=ctx, for_pdf=for_pdf)


def project_html(ctx: dict, for_pdf: bool = False) -> str:
    return _env.get_template("project_report.html").render(**ctx, for_pdf=for_pdf)


def to_pdf(html: str) -> bytes:
    from weasyprint import HTML  # imported lazily: needs Pango system libraries

    return HTML(string=html).write_pdf()
