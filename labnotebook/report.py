"""Lab report generation: Markdown, HTML (print view) and PDF (HTML rendered by WeasyPrint)."""
from __future__ import annotations

import base64
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import markdown as md
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import db
from .pubchem import PubChemClient, PubChemUnavailable

TEMPLATES = Path(__file__).parent / "templates"
ROLE_LABELS = {"reactant": "Reactant", "reagent": "Reagent", "catalyst": "Catalyst", "solvent": "Solvent",
               "product": "Product", "other": "Other"}
KIND_LABELS = {"note": "Note", "observation": "Observation", "measurement": "Measurement"}
GHS_NAMES = {
    "GHS01": "Explosive", "GHS02": "Flammable", "GHS03": "Oxidizer", "GHS04": "Compressed gas",
    "GHS05": "Corrosive", "GHS06": "Acute toxicity", "GHS07": "Harmful / irritant", "GHS08": "Health hazard",
    "GHS09": "Environmental hazard",
}


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
    if not ts:
        return ""
    try:
        d = datetime.fromisoformat(ts)
    except ValueError:
        return ts
    return d.strftime("%Y-%m-%d %H:%M" if with_date else "%H:%M")


def h_code(statement: str) -> str:
    """'H225: Highly flammable ...' -> 'H225'."""
    m = re.match(r"\s*((?:EU)?H\d{3}[A-Za-z+H\d]*)", statement or "")
    return m.group(1) if m else (statement or "")


def h_text(statement: str) -> str:
    """Strip the bracketed GHS classification PubChem appends: 'H225: ... vapor [Danger ...]' -> 'H225: ... vapor'."""
    return re.sub(r"\s*\[[^\]]*\]\s*$", "", statement or "").strip()


def _unique_h(statements: list[str]) -> list[str]:
    seen, out = set(), []
    for s in statements or []:
        t = h_text(s)
        code = h_code(t)
        if code not in seen:
            seen.add(code)
            out.append(t)
    return out


def amount_text(r: dict, c: dict) -> str:
    parts = []
    if c.get("mass_g") is not None:
        parts.append(f"{fmt(c['mass_g'])} g")
    if c.get("volume_ml") is not None and (r.get("form") != "neat" or r.get("basis") == "volume"
                                           or r.get("role") == "solvent" or c.get("mass_g") is None):
        parts.append(f"{fmt(c['volume_ml'])} mL")
    return ", ".join(parts)


def form_text(r: dict) -> str:
    form = r.get("form") or "neat"
    if form == "solution" and r.get("concentration_m"):
        return f"{fmt(r['concentration_m'])} M solution"
    if form == "wt" and r.get("wt_percent"):
        return f"{fmt(r['wt_percent'])} wt% solution"
    if r.get("purity") and float(r["purity"]) < 100:
        return f"{fmt(r['purity'])}% purity"
    return ""


def build_context(store: db.Store, exp_id: int, calc: dict, settings: Any = None) -> Optional[dict]:
    exp = store.get_experiment(exp_id)
    if not exp:
        return None
    reagents = store.list_reagents(exp_id)
    entries = store.list_entries(exp_id)
    rows = []
    for r in reagents:
        c = dict(calc["rows"].get(r["id"], {}))
        if r.get("role") == "solvent":  # amounts of solvent in mmol / equiv are noise in a report
            c["mmol"] = c["equiv"] = None
        rows.append({
            "r": r, "c": c,
            "role": ROLE_LABELS.get(r.get("role"), r.get("role") or ""),
            "amount": amount_text(r, c),
            "form": form_text(r),
            "hazards": _unique_h(r.get("hazard_statements")),
            "manual": sorted(k for k, v in (r.get("sources") or {}).items() if v == "manual"),
        })
    inputs = [x for x in rows if x["r"].get("role") != "product"]
    products = [x for x in rows if x["r"].get("role") == "product"]
    exp_date = exp.get("date") or ""
    log = [{**e, "kind_label": KIND_LABELS.get(e["kind"], e["kind"]),
            "time": fmt_ts(e["ts"], with_date=not (e["ts"] or "").startswith(exp_date) or not exp_date)}
           for e in entries]
    sections = {k: (exp.get(k) or "").strip() for k in db.SECTION_KEYS}
    cited = [x["r"] for x in rows if x["r"].get("cid")]
    return {
        "exp": exp, "rows": rows, "inputs": inputs, "products": products, "log": log,
        "sections": sections, "headings": dict(db.SECTIONS), "cited": cited,
        "status_label": exp.get("status", "").replace("_", " ").capitalize(),
        "lab_name": getattr(settings, "lab_name", "") if settings else "",
        "generated": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
        "pictograms_used": sorted({p for x in rows for p in (x["r"].get("pictograms") or [])}),
    }


# ----------------------------------------------------------------------------------------------- Markdown
def _md_escape_cell(s: Any) -> str:
    return str(s or "").replace("|", "\\|").replace("\n", " ")


def to_markdown(ctx: dict) -> str:
    exp, s, H = ctx["exp"], ctx["sections"], ctx["headings"]
    out = [f"# {exp['title']}", ""]
    meta = [("Date", exp.get("date")), ("Author", exp.get("author")), ("Course", exp.get("course")),
            ("Lab", ctx.get("lab_name")), ("Status", ctx["status_label"])]
    out += [f"**{k}:** {v}  " for k, v in meta if v]
    out.append("")

    def section(key: str) -> None:
        if s[key]:
            out.extend([f"## {H[key]}", "", s[key], ""])

    section("objective")
    section("reaction_scheme")

    if ctx["inputs"]:
        out += ["## Reagents", "",
                "| Compound | Role | MW (g/mol) | Amount | mmol | equiv | Properties |",
                "| --- | --- | ---: | --- | ---: | ---: | --- |"]
        for x in ctx["inputs"]:
            r, c = x["r"], x["c"]
            name = r.get("name") or "?"
            if x["form"]:
                name += f" ({x['form']})"
            if c.get("is_limiting"):
                name += " (limiting)"
            props = []
            if r.get("density"):
                props.append(f"d {fmt(r['density'])} g/mL")
            if r.get("bp") is not None:
                props.append(f"bp {fmt_fixed(r['bp'], 0)} °C")
            if r.get("mp") is not None:
                props.append(f"mp {fmt_fixed(r['mp'], 0)} °C")
            out.append("| " + " | ".join(_md_escape_cell(v) for v in [
                name, x["role"], fmt_fixed(r.get("mw"), 2), x["amount"], fmt(c.get("mmol")),
                fmt_fixed(c.get("equiv"), 2), ", ".join(props)]) + " |")
        out.append("")

    hazard_rows = [x for x in ctx["rows"] if x["r"].get("signal_word") or x["hazards"] or x["r"].get("pictograms")]
    if hazard_rows:
        out += ["## Safety", ""]
        for x in hazard_rows:
            r = x["r"]
            head = f"**{r.get('name')}**"
            extra = [w for w in [r.get("signal_word"),
                                 ", ".join(f"{p} {GHS_NAMES.get(p, '')}".strip() for p in r.get("pictograms") or [])]
                     if w]
            if r.get("flash_point") is not None:
                extra.append(f"flash point {fmt_fixed(r['flash_point'], 0)} °C")
            out.append(f"- {head}: " + "; ".join(extra) if extra else f"- {head}")
            for h in x["hazards"]:
                out.append(f"  - {h}")
        out.append("")

    section("procedure")

    if ctx["log"]:
        out += ["## Observations", "", "| Time | Type | Entry | Value |", "| --- | --- | --- | --- |"]
        for e in ctx["log"]:
            val = " ".join(v for v in [e.get("value") or "", e.get("unit") or ""] if v)
            out.append("| " + " | ".join(_md_escape_cell(v) for v in [e["time"], e["kind_label"], e["text"], val])
                       + " |")
        out.append("")

    if ctx["products"] or s["results"]:
        out += ["## Results", ""]
        if ctx["products"]:
            out += ["| Product | MW (g/mol) | Theoretical yield | Isolated | Yield |",
                    "| --- | ---: | --- | --- | ---: |"]
            for x in ctx["products"]:
                r, c = x["r"], x["c"]
                theo = (f"{fmt(c['theoretical_mass_g'])} g ({fmt(c['theoretical_mmol'])} mmol)"
                        if c.get("theoretical_mass_g") is not None else "")
                iso = f"{fmt(c['mass_g'])} g" if c.get("mass_g") is not None else ""
                if iso and c.get("mmol") is not None:
                    iso += f" ({fmt(c['mmol'])} mmol)"
                yld = f"{c['percent_yield']:.1f} %" if c.get("percent_yield") is not None else ""
                out.append("| " + " | ".join(_md_escape_cell(v) for v in [
                    r.get("name"), fmt_fixed(r.get("mw"), 2), theo, iso, yld]) + " |")
            out.append("")
        if s["results"]:
            out += [s["results"], ""]

    section("discussion")
    section("conclusion")

    refs = [s["references"]] if s["references"] else []
    if ctx["cited"]:
        refs.append("\n".join(
            f"- {r['name']}: PubChem CID {r['cid']}, {r.get('pubchem_url') or ''} (data via PubChem Local)".rstrip()
            for r in ctx["cited"]))
    if refs:
        out += ["## References", "", *refs, ""]
    out += ["---", f"*Generated {ctx['generated']} by Lab Notebook.*", ""]
    return "\n".join(out)


# ----------------------------------------------------------------------------------------------- HTML / PDF
_env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))
_env.filters.update(fmt=fmt, fmt_fixed=fmt_fixed)
_env.filters["md"] = lambda text: md.markdown(text or "", extensions=["extra", "sane_lists", "nl2br"])


def _data_uri(item: Optional[tuple[bytes, str]]) -> Optional[str]:
    if not item:
        return None
    content, ctype = item
    ctype = ctype.split(";")[0].strip() or "image/svg+xml"
    return f"data:{ctype};base64,{base64.b64encode(content).decode()}"


def embed_images(ctx: dict, client: Optional[PubChemClient]) -> dict:
    """Fetch structure and GHS images as data URIs so the report is self-contained."""
    structures, ghs = {}, {}
    if client is not None:
        try:
            for x in ctx["rows"]:
                cid = x["r"].get("cid")
                if cid and cid not in structures:
                    structures[cid] = _data_uri(client.structure_svg(cid, 260, 180))
            for code in ctx["pictograms_used"]:
                ghs[code] = _data_uri(client.ghs_svg(code))
        except PubChemUnavailable:
            pass
    ctx = dict(ctx, structures=structures, ghs=ghs, ghs_names=GHS_NAMES)
    return ctx


def to_html(ctx: dict, for_pdf: bool = False) -> str:
    return _env.get_template("report.html").render(**ctx, for_pdf=for_pdf)


def to_pdf(html: str) -> bytes:
    from weasyprint import HTML  # imported lazily: needs Pango system libraries

    return HTML(string=html).write_pdf()
