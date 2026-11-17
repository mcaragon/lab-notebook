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


def _scheme_html(sch: dict, img_src: Callable[[dict, int, int], Optional[str]]) -> str:
    return _env.get_template("scheme.html").render(sch=sch, img_src=img_src)


def scheme_html(bundle: dict, calc: dict, img_src: Callable[[dict, int, int], Optional[str]]) -> str:
    """The reaction scheme as an HTML fragment (``img_src(reagent, w, h)`` gives each structure's image URL)."""
    return _scheme_html(scheme.build(bundle, calc), img_src)


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
    statements = unique_h(r.get("hazard_statements"))
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


def _assign_entries(bundle: dict) -> dict[int, Any]:
    """Step of each log entry: its own, its procedure row's, or that of the entry before it."""
    steps = bundle["steps"]
    if not steps:
        return {}
    proc_step = {p["id"]: p.get("step_id") for p in bundle["procedure"]}
    timer_proc = {t["id"]: t.get("procedure_id") for t in bundle.get("timers", [])}
    valid = {s["id"] for s in steps}
    out, last = {}, steps[0]["id"]
    for e in bundle["entries"]:
        sid = e.get("step_id")
        if sid not in valid:
            pid = e.get("procedure_id") or timer_proc.get(e.get("timer_id"))
            sid = proc_step.get(pid)
        if sid not in valid:
            sid = last
        out[e["id"]] = sid
        last = sid
    return out


def build_context(bundle: dict, calc: dict, settings: Any = None,
                  client: Optional[PubChemClient] = None, images: Optional[tuple[dict, dict]] = None,
                  numbers: Optional[dict] = None, step_offset: int = 0) -> dict:
    """Everything the report templates need. With ``client``, structures and pictograms are embedded.

    ``numbers`` and ``step_offset`` let a chapter of a sequence report use the route's compound numbers and arrow
    letters."""
    exp = bundle["experiment"]
    rows = calc["rows"]
    reagents = bundle["reagents"]
    use = actions.usage(bundle["entries"])
    ref_no = {r["id"]: i for i, r in enumerate(bundle["refs"], 1)}
    structures_by_id, ghs = images or embedded_images(reagents, client)
    img = lambda r, w, h: structures_by_id.get(r["id"])  # noqa: E731
    multi = len(bundle["steps"]) > 1

    overall = scheme.build(bundle, calc, numbers=numbers, first_index=step_offset)
    entry_step = _assign_entries(bundle)
    first_step = bundle["steps"][0]["id"] if bundle["steps"] else None
    exp_date = exp.get("date") or ""

    steps = []
    for i, s in enumerate(bundle["steps"]):
        rs = [_row(r, rows.get(r["id"], {}), use.get(r["id"], {}), ref_no)
              for r in reagents if r.get("step_id") == s["id"]]
        inputs = [x for x in rs if x["r"]["role"] != "product"]
        legend: dict[str, str] = {}
        for x in rs:
            for code, text in zip(x["haz"]["codes"], x["haz"]["statements"]):
                legend.setdefault(code, text)
        proc_rows = [p for p in bundle["procedure"]
                     if p.get("step_id") == s["id"] or (p.get("step_id") is None and s["id"] == first_step)
                     or (not multi)]
        procedure = [{**p, "n": n, "rendered": scheme.render_mentions(p.get("text") or "", reagents, rows),
                      "html": scheme.render_mentions(p.get("text") or "", reagents, rows, mode="html")}
                     for n, p in enumerate(proc_rows, 1)]
        proc_no = {p["id"]: p["n"] for p in procedure}
        log = [{**e, "time": fmt_ts(e["ts"], with_date=not exp_date or not (e["ts"] or "").startswith(exp_date)),
                "tplus": fmt_elapsed(e.get("elapsed_s")), "proc_no": proc_no.get(e.get("procedure_id"))}
               for e in bundle["entries"] if entry_step.get(e["id"]) == s["id"]]
        step_scheme = scheme.build_step(bundle, calc, i, overall["numbers"], step_offset) if multi else None
        steps.append({
            "s": s, "n": i + 1, "letter": chr(ord("a") + i), "inputs": inputs,
            "products": [x for x in rs if x["r"]["role"] == "product"],
            "legend": sorted(legend.items(), key=lambda kv: kv[0]),
            "planned_only": any(x["planned_only"] for x in inputs),
            "conditions": scheme.conditions_text(s), "procedure": procedure, "log": log,
            "scheme_html": _scheme_html(step_scheme, img) if step_scheme and not step_scheme["empty"] else "",
            "yield": calc["steps"].get(s["id"], {}).get("step_yield"),
        })

    sections = {k: (exp.get(k) or "").strip() for k in db.SECTION_KEYS}
    refs = [{"n": i, "text": format_ref(r)} for i, r in enumerate(bundle["refs"], 1) if format_ref(r)]
    cited, cids = [], set()
    for r in reagents:
        if r.get("cid") and r["cid"] not in cids:
            cids.add(r["cid"])
            cited.append(r)
    return {
        "exp": exp, "steps": steps, "multi": multi, "overall_yield": calc.get("overall_yield"),
        "sections": sections, "headings": dict(db.SECTIONS), "refs": refs, "cited": cited, "n_refs": len(refs),
        "scheme": overall, "scheme_html": _scheme_html(overall, img),
        "status_label": (exp.get("status") or "").replace("_", " ").capitalize(),
        "lab_name": getattr(settings, "lab_name", "") if settings else "",
        "generated": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
        "ghs": ghs, "ghs_names": GHS_NAMES,
        "duration": fmt_elapsed(db.elapsed_between(exp.get("started_at"), exp.get("ended_at")))
        if exp.get("ended_at") else "",
    }


def build_sequence_context(seq: dict, bundles: list[dict], calcs: list[dict], settings: Any = None,
                           client: Optional[PubChemClient] = None) -> dict:
    """A sequence report: overall scheme and yields, then one chapter per experiment."""
    from . import sequences

    combined, ccalc = sequences.compute(bundles)
    images = embedded_images(combined["reagents"], client)
    img = lambda r, w, h: images[0].get(r["id"])  # noqa: E731
    sch = scheme.build(dict(combined, experiment={"scheme_style": seq.get("scheme_style")}), ccalc)
    summary = sequences.summary(bundles, ccalc)
    chapters, offset = [], 0
    for b, c in zip(bundles, calcs):
        chapters.append(build_context(b, c, settings, images=images, numbers=sch["numbers"], step_offset=offset))
        offset += len(b["steps"])
    return {
        "seq": seq, "chapters": chapters, "scheme": sch, "scheme_html": _scheme_html(sch, img), "summary": summary,
        "overall_yield": sequences.overall_yield(summary), "lab_name": getattr(settings, "lab_name", "") if settings else "",
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


def _md_step(ctx: dict, st: dict, lvl: int) -> list[str]:
    h = "#" * lvl
    out: list[str] = []
    if st["inputs"]:
        body = []
        for x in st["inputs"]:
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
            body.append([name, x["role"], fmt_fixed(r.get("mw"), 2), x["amount"] + (" *" if x["planned_only"] else ""),
                         fmt(x["mmol"]), fmt_fixed(x["equiv"], 2), ", ".join(props), _md_hazard(x["haz"])])
        out += _table(["Compound", "Role", "MW", "Amount", "mmol", "equiv", "Properties", "Hazards"],
                      ["l", "l", "r", "r", "r", "r", "l", "l"], body)
        if st["planned_only"]:
            out += ["\\* planned amount; no measurement recorded.", ""]
        if st["legend"]:
            out += ["Hazard statements: " + "; ".join(text for _, text in st["legend"]), ""]
    if st["procedure"]:
        out += [f"{h} Procedure", ""]
        for p in st["procedure"]:
            line = f"{p['n']}. {p['rendered']}"
            if p.get("done_at"):
                line += f" *(done {fmt_ts(p['done_at'], with_date=False)})*"
            out.append(line)
            if p.get("notes"):
                out.append(f"   - *Note:* {p['notes']}")
        out.append("")
    if st["log"]:
        out += [f"{h} Log", ""]
        out += _table(["Time", "T+", "Step", "Entry"], ["l", "r", "r", "l"],
                      [[e["time"], e["tplus"], e["proc_no"] or "",
                        e["text"] + (f" ({e['value']} {e.get('unit') or ''})".rstrip() if e.get("value") else "")]
                       for e in st["log"]])
    if st["products"]:
        out += [f"{h} Yield", ""]
        body = []
        for x in st["products"]:
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
        out += _table(["Product", "MW", "Theoretical", "Expected", "Crude", "Isolated", "Yield"],
                      ["l", "r", "r", "r", "r", "r", "r"], body)
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
        out += [f"{h} {'Overall reaction' if ctx['multi'] else 'Reaction'}", ""] + _md_scheme(ctx["scheme"])
    for st in ctx["steps"]:
        if ctx["multi"]:
            out += [f"{h} Step {st['n']}" + (f": {st['s']['title']}" if st["s"].get("title") else ""), ""]
            if st["s"].get("notes"):
                out += [st["s"]["notes"], ""]
            if st["conditions"] or st["s"].get("atmosphere"):
                out += ["Conditions: " + ", ".join(x for x in (st["s"].get("atmosphere"), st["conditions"]) if x), ""]
            out += _md_step(ctx, st, lvl + 1)
        else:
            if st["inputs"]:
                out += [f"{h} Reagents", ""]
            out += _md_step(ctx, st, lvl)
    if ctx["overall_yield"] is not None:
        out += [f"**Overall yield:** {ctx['overall_yield']:.1f}% over {len(ctx['steps'])} steps", ""]
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


def sequence_markdown(ctx: dict) -> str:
    seq = ctx["seq"]
    out = [f"# {seq['title']}", ""]
    if seq.get("notes"):
        out += [seq["notes"], ""]
    if not ctx["scheme"]["empty"]:
        out += ["## Route", ""] + _md_scheme(ctx["scheme"])
    if ctx["summary"]:
        out += _table(["Step", "Experiment", "Date", "Product", "Isolated", "Yield"], ["r", "l", "l", "l", "r", "r"],
                      [[r["n"], r["experiment"]["title"], r["experiment"].get("date") or "",
                        r["product"]["name"] if r["product"] else "",
                        f"{fmt(r['isolated_mass_g'])} g" if r["isolated_mass_g"] is not None else "",
                        f"{r['yield']:.1f}%" if r["yield"] is not None else ""] for r in ctx["summary"]])
    if ctx["overall_yield"] is not None:
        out += [f"**Overall yield:** {ctx['overall_yield']:.1f}% over {len(ctx['summary'])} steps", ""]
    for i, ch in enumerate(ctx["chapters"], 1):
        out += [f"## {i}. {ch['exp']['title']}", ""] + _md_body(ch, 3)
    out += ["---", f"*Generated {ctx['generated']} by Lab Notebook.*", ""]
    return "\n".join(out)


# ------------------------------------------------------------------------------------------- HTML / PDF
def to_html(ctx: dict, for_pdf: bool = False) -> str:
    return _env.get_template("report.html").render(**ctx, self_ctx=ctx, for_pdf=for_pdf)


def sequence_html(ctx: dict, for_pdf: bool = False) -> str:
    return _env.get_template("sequence_report.html").render(**ctx, for_pdf=for_pdf)


def to_pdf(html: str) -> bytes:
    from weasyprint import HTML  # imported lazily: needs Pango system libraries

    return HTML(string=html).write_pdf()
