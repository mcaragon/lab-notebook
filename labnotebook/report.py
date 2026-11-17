"""Lab report generation: Markdown, HTML (print view) and PDF (HTML rendered by WeasyPrint).

Also renders the reaction scheme fragment that the app shows at the top of an experiment.
"""
from __future__ import annotations

import base64
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import markdown as md
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import actions, db, hazards, scheme
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
_env.filters["md"] = lambda text: md.markdown(text or "", extensions=["extra", "sane_lists", "nl2br"])


def scheme_html(bundle: dict, calc: dict, img_src: Callable[[dict, int, int], Optional[str]]) -> str:
    """The reaction scheme as an HTML fragment (``img_src(reagent, w, h)`` gives each structure's image URL)."""
    sch = scheme.build(bundle, calc)
    return _env.get_template("scheme.html").render(sch=sch, img_src=img_src)


def _data_uri(item: Optional[tuple[bytes, str]]) -> Optional[str]:
    if not item:
        return None
    content, ctype = item
    ctype = ctype.split(";")[0].strip() or "image/svg+xml"
    return f"data:{ctype};base64,{base64.b64encode(content).decode()}"


# ------------------------------------------------------------------------------------------- context
def build_context(bundle: dict, calc: dict, settings: Any = None,
                  client: Optional[PubChemClient] = None) -> dict:
    """Everything the report templates need. With ``client``, structures and pictograms are embedded."""
    exp = bundle["experiment"]
    rows = calc["rows"]
    reagents = bundle["reagents"]
    use = actions.usage(bundle["entries"])
    ref_no = {r["id"]: i for i, r in enumerate(bundle["refs"], 1)}

    def row(r: dict) -> dict:
        c = dict(rows.get(r["id"], {}))
        if r.get("role") in ("solvent", "workup"):  # mmol / equiv of solvents are noise in a report
            for k in ("mmol", "equiv", "act_mmol", "act_equiv"):
                c[k] = None
        u = use.get(r["id"], {}) if r.get("role") in ("solvent", "workup") else {}
        return {
            "r": r, "c": c, "role": ROLE_LABELS.get(r.get("role"), r.get("role") or ""),
            "planned": amount_text(r, c.get("mass_g"), c.get("volume_ml")),
            "actual": amount_text(r, c.get("act_mass_g"), c.get("act_volume_ml")),
            "form": form_text(r), "provenance": provenance(r),
            "hazards": unique_h(r.get("hazard_statements")),
            "extra": hazards.summary_lines(r.get("extra_hazards")),
            "used": ", ".join(f"{fmt(v)} {k}" for k, v in u.items()),
            "expected_ref": ref_no.get(r.get("expected_ref_id")),
        }

    steps = []
    for i, s in enumerate(bundle["steps"], 1):
        rs = [row(r) for r in reagents if r.get("step_id") == s["id"]]
        steps.append({
            "s": s, "n": i, "letter": chr(ord("a") + i - 1),
            "inputs": [x for x in rs if x["r"]["role"] not in ("product",)],
            "products": [x for x in rs if x["r"]["role"] == "product"],
            "conditions": scheme.conditions_text(s),
            "yield": calc["steps"].get(s["id"], {}).get("step_yield"),
        })
    has_actual = any(x["c"].get("act_mmol") is not None or x["actual"] for st in steps for x in st["inputs"])

    # Safety: one row per distinct chemical
    safety, seen = [], set()
    for r in reagents:
        key = r.get("cid") or (r.get("name") or "").lower()
        if key in seen:
            continue
        seen.add(key)
        extra = hazards.summary_lines(r.get("extra_hazards"))
        if (r.get("signal_word") or r.get("hazard_statements") or r.get("pictograms") or extra
                or r.get("hazard_notes") or r.get("flash_point") is not None):
            safety.append({"r": r, "hazards": unique_h(r.get("hazard_statements")), "extra": extra,
                           "forbidden": bool(((r.get("extra_hazards") or {}).get("dot") or {}).get("forbidden"))})

    procedure = [{**p, "n": i, "rendered": scheme.render_mentions(p.get("text") or "", reagents, rows),
                  "html": scheme.render_mentions(p.get("text") or "", reagents, rows, mode="html")}
                 for i, p in enumerate(bundle["procedure"], 1)]
    proc_no = {p["id"]: p["n"] for p in procedure}
    exp_date = exp.get("date") or ""
    log = [{**e, "time": fmt_ts(e["ts"], with_date=not exp_date or not (e["ts"] or "").startswith(exp_date)),
            "tplus": fmt_elapsed(e.get("elapsed_s")), "proc_no": proc_no.get(e.get("procedure_id"))}
           for e in bundle["entries"]]

    sections = {k: (exp.get(k) or "").strip() for k in db.SECTION_KEYS}
    refs = [{"n": i, "text": format_ref(r)} for i, r in enumerate(bundle["refs"], 1) if format_ref(r)]
    cited, cids = [], set()
    for r in reagents:
        if r.get("cid") and r["cid"] not in cids:
            cids.add(r["cid"])
            cited.append(r)

    structures_by_id, ghs = {}, {}
    if client is not None:
        for r in reagents:
            if r.get("cid") or r.get("smiles"):
                structures_by_id[r["id"]] = _data_uri(structure(client, r.get("cid"), r.get("smiles"), 240, 170))
        codes = sorted({p for r in reagents for p in (r.get("pictograms") or [])})
        try:
            for code in codes:
                ghs[code] = _data_uri(client.ghs_svg(code))
        except PubChemUnavailable:
            pass
    sch_html = scheme_html(bundle, calc, lambda r, w, h: structures_by_id.get(r["id"]))

    return {
        "exp": exp, "steps": steps, "multi": len(steps) > 1, "has_actual": has_actual,
        "overall_yield": calc.get("overall_yield"), "safety": safety, "procedure": procedure, "log": log,
        "sections": sections, "headings": dict(db.SECTIONS), "refs": refs, "cited": cited,
        "n_refs": len(refs), "scheme_html": sch_html, "scheme": scheme.build(bundle, calc),
        "status_label": (exp.get("status") or "").replace("_", " ").capitalize(),
        "lab_name": getattr(settings, "lab_name", "") if settings else "",
        "generated": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
        "ghs": ghs, "ghs_names": GHS_NAMES, "duration": fmt_elapsed(
            db.elapsed_between(exp.get("started_at"), exp.get("ended_at"))) if exp.get("ended_at") else "",
    }


# ------------------------------------------------------------------------------------------- Markdown
def _cell(s: Any) -> str:
    return str(s or "").replace("|", "\\|").replace("\n", " ")


def _table(head: list[str], align: list[str], body: list[list[Any]]) -> list[str]:
    sep = {"l": "---", "r": "---:"}
    return ["| " + " | ".join(head) + " |", "| " + " | ".join(sep[a] for a in align) + " |",
            *("| " + " | ".join(_cell(v) for v in r) + " |" for r in body), ""]


def to_markdown(ctx: dict) -> str:
    exp, s, H = ctx["exp"], ctx["sections"], ctx["headings"]
    out = [f"# {exp['title']}", ""]
    meta = [("Date", exp.get("date")), ("Author", exp.get("author")), ("Course", exp.get("course")),
            ("Lab", ctx.get("lab_name")), ("Status", ctx["status_label"]), ("Duration", ctx["duration"])]
    out += [f"**{k}:** {v}  " for k, v in meta if v]
    out.append("")

    def section(key: str) -> None:
        if s[key]:
            out.extend([f"## {H[key]}", "", s[key], ""])

    section("objective")

    sch = ctx["scheme"]
    if not sch["empty"] or any(st["conditions"] for st in ctx["steps"]):
        out += ["## Reaction", ""]
        line = []
        for seg in sch["segments"]:
            if seg["type"] == "mols":
                line.append(" + ".join(f"{scheme.label(m['reagent'])} (**{m['number']}**)"
                                       + (f", {m['yield']:.0f}%" if m.get("yield") is not None else "")
                                       for m in seg["mols"]))
            else:
                text = f"({seg['letter']})" if sch["lettered"] else "; ".join(seg["above"] + seg["below"])
                line.append(f"→[{text}]→" if text else "→")
        out += [" ".join(line), ""]
        for letter, text in sch["legend"]:
            out.append(f"- ({letter}) {text}")
        if sch["legend"]:
            out.append("")

    for st in ctx["steps"]:
        if not st["inputs"] and not st["products"]:
            continue
        title = f"## Step {st['n']}" + (f": {st['s']['title']}" if st["s"].get("title") else "") if ctx["multi"] \
            else "## Reagents"
        out += [title, ""]
        if st["s"].get("notes"):
            out += [st["s"]["notes"], ""]
        if st["inputs"]:
            head = ["Compound", "Role", "MW", "Planned", "mmol", "equiv"]
            align = ["l", "l", "r", "r", "r", "r"]
            if ctx["has_actual"]:
                head += ["Actual", "mmol", "equiv"]
                align += ["r", "r", "r"]
            head.append("Properties")
            align.append("l")
            body = []
            for x in st["inputs"]:
                r, c = x["r"], x["c"]
                name = r.get("name") or "?"
                extra = [v for v in (x["form"], x["provenance"]) if v]
                if extra:
                    name += f" ({'; '.join(extra)})"
                if c.get("is_limiting"):
                    name += " — limiting"
                props = []
                if r.get("density"):
                    props.append(f"d {fmt(r['density'])} g/mL")
                if r.get("bp") is not None:
                    props.append(f"bp {fmt_fixed(r['bp'], 0)} °C")
                if r.get("mp") is not None:
                    props.append(f"mp {fmt_fixed(r['mp'], 0)} °C")
                cells = [name, x["role"], fmt_fixed(r.get("mw"), 2), x["planned"], fmt(c.get("mmol")),
                         fmt_fixed(c.get("equiv"), 2)]
                if ctx["has_actual"]:
                    cells += [x["actual"], fmt(c.get("act_mmol")), fmt_fixed(c.get("act_equiv"), 2)]
                cells.append(", ".join(props))
                body.append(cells)
            out += _table(head, align, body)
        notes = [f"- {x['r'].get('name')}: {x['r']['notes']}" for x in st["inputs"] + st["products"]
                 if x["r"].get("notes")]
        if notes:
            out += ["Notes:", "", *notes, ""]

    if ctx["safety"]:
        out += ["## Safety", ""]
        for x in ctx["safety"]:
            r = x["r"]
            extra = [w for w in [r.get("signal_word"),
                                 ", ".join(f"{p} {GHS_NAMES.get(p, '')}".strip() for p in r.get("pictograms") or [])]
                     if w]
            if r.get("flash_point") is not None:
                extra.append(f"flash point {fmt_fixed(r['flash_point'], 0)} °C")
            out.append(f"- **{r.get('name')}**" + (": " + "; ".join(extra) if extra else ""))
            for h in x["hazards"] + x["extra"] + ([r["hazard_notes"]] if r.get("hazard_notes") else []):
                out.append(f"  - {h}")
        out.append("")

    if ctx["procedure"]:
        out += ["## Procedure", ""]
        for p in ctx["procedure"]:
            line = f"{p['n']}. {p['rendered']}"
            if p.get("done_at"):
                line += f" *(done {fmt_ts(p['done_at'], with_date=False)})*"
            out.append(line)
            if p.get("notes"):
                out.append(f"   - *Note:* {p['notes']}")
        out.append("")

    if ctx["log"]:
        out += ["## Log", ""]
        out += _table(["Time", "T+", "Step", "Entry"], ["l", "r", "r", "l"],
                      [[e["time"], e["tplus"], e["proc_no"] or "",
                        e["text"] + (f" ({e['value']} {e.get('unit') or ''})".rstrip() if e.get("value") else "")]
                       for e in ctx["log"]])

    products = [(st, x) for st in ctx["steps"] for x in st["products"]]
    if products or s["results"]:
        out += ["## Results", ""]
        if products:
            body = []
            for st, x in products:
                r, c = x["r"], x["c"]
                name = r.get("name") or "?"
                if ctx["multi"]:
                    name = f"Step {st['n']}: {name}"
                theo = f"{fmt(c['theoretical_mass_g'])} g ({fmt(c['theoretical_mmol'])} mmol)" \
                    if c.get("theoretical_mass_g") is not None else ""
                expd = ""
                if c.get("expected_yield_pct") is not None:
                    expd = f"{c['expected_yield_pct']:.0f}%"
                    if c.get("expected_mass_g") is not None:
                        expd += f" ({fmt(c['expected_mass_g'])} g)"
                    if x["expected_ref"]:
                        expd += f" [{x['expected_ref']}]"
                crude = f"{fmt(c['crude_mass_g'])} g" + (f" ({c['crude_percent']:.0f}%)" if c.get("crude_percent")
                                                          is not None else "") if c.get("crude_mass_g") else ""
                iso = f"{fmt(c['isolated_mass_g'])} g" if c.get("isolated_mass_g") is not None else ""
                if iso and c.get("isolated_mmol") is not None:
                    iso += f" ({fmt(c['isolated_mmol'])} mmol)"
                yld = f"{c['percent_yield']:.1f}%" if c.get("percent_yield") is not None else ""
                body.append([name, fmt_fixed(r.get("mw"), 2), theo, expd, crude, iso, yld])
            out += _table(["Product", "MW", "Theoretical", "Expected", "Crude", "Isolated", "Yield"],
                          ["l", "r", "r", "r", "r", "r", "r"], body)
            if ctx["overall_yield"] is not None:
                out += [f"**Overall yield:** {ctx['overall_yield']:.1f}% over {len(ctx['steps'])} steps", ""]
        if s["results"]:
            out += [s["results"], ""]

    section("discussion")
    section("conclusion")

    if ctx["refs"] or ctx["cited"]:
        out += ["## References", ""]
        for r in ctx["refs"]:
            out.append(f"{r['n']}. {r['text']}")
        start = ctx["n_refs"]
        for i, r in enumerate(ctx["cited"], start + 1):
            out.append(f"{i}. {r['name']}: PubChem CID {r['cid']}, {r.get('pubchem_url') or ''}"
                       " (data via PubChem Local).")
        out.append("")
    out += ["---", f"*Generated {ctx['generated']} by Lab Notebook.*", ""]
    return "\n".join(out)


# ------------------------------------------------------------------------------------------- HTML / PDF
def to_html(ctx: dict, for_pdf: bool = False) -> str:
    return _env.get_template("report.html").render(**ctx, for_pdf=for_pdf)


def to_pdf(html: str) -> bytes:
    from weasyprint import HTML  # imported lazily: needs Pango system libraries

    return HTML(string=html).write_pdf()
