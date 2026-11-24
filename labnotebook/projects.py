"""Projects: experiments linked by material into a route that can branch and converge.

A link is a starting material taken from the product of another experiment (``source_reagent_id``). The route of a
project is the graph of those links between its experiments: one product can feed several experiments (branches,
small-scale trials), and an experiment can take products of several (convergent routes).

Starting materials that do not come from another experiment are grouped into *batches*: the same compound (and
the same lot, when one is entered) used by several first experiments is one batch, drawn once with an arrow to each
experiment and the amount each took. A project can record how much of a batch is on hand, to show what is left.

The route map lays the graph out left to right: an experiment's column is the length of the longest chain of links
leading to it; rows follow a tree of "main parents" (the deepest parent of each experiment), so branches fan out from
the experiment they start from. Extra parents (convergence) get their own connectors.
"""
from __future__ import annotations

import html
from typing import Any, Callable, Optional

from . import scheme

CARD_W, CARD_H, GAP_X, GAP_Y, PAD = 212, 178, 92, 22, 14
STATUS_COLORS = {"planned": "#8a94a3", "in_progress": "#d68a00", "completed": "#1f9d55"}


def taken_g(r: dict, c: dict) -> Optional[float]:
    """Mass of a starting material taken from a product: measured if recorded, else planned."""
    for k in ("act_mass_g", "mass_g"):
        if c.get(k) is not None:
            return c[k]
    return None


def product_of(bundle: dict) -> Optional[dict]:
    prods = [r for r in bundle["reagents"] if r.get("role") == "product"]
    return prods[0] if prods else None


def _ident(r: dict) -> str:
    return str(r.get("cid") or (r.get("smiles") or "").strip() or (r.get("name") or "").strip().lower() or r["id"])


def material_key(r: dict) -> str:
    """Identity of a starting-material batch: the compound, plus the lot when one is entered."""
    return f"{_ident(r)}|{(r.get('lot') or '').strip().lower()}"


def graph(bundles: list[dict], calcs: list[dict], on_hand: Optional[dict] = None) -> dict:
    """Nodes (experiments) and edges (material links) of a project, with layout and yields.

    Each node: ``id, title, date, status, col, row, product, number, yield, isolated_g, used_g, remaining_g,
    overall_yield, lls, parents, children, main_parent, starting, main_start``; ``starting`` lists the starting
    materials that do not come from another experiment of the project (``{reagent, name, taken_g, key}``) and
    ``main_start`` is the one the route starts from (the reference reagent, else the limiting one, else the first).
    ``materials`` are the batches the first experiments start from: ``{key, reagent, name, lot, supplier, uses:
    [{experiment_id, reagent_id, taken_g}], used_g, on_hand_g, left_g}``; ``on_hand`` gives amounts by key. Each edge: ``from, to, product_id, reagent_id, taken_g,
    main`` (main: part of the layout tree).
    """
    order = [b["experiment"]["id"] for b in bundles]
    by_id = {b["experiment"]["id"]: (b, c) for b, c in zip(bundles, calcs)}
    owner = {r["id"]: eid for eid, (b, _) in by_id.items() for r in b["reagents"] if r.get("role") == "product"}
    edges: list[dict] = []
    for eid in order:
        b, c = by_id[eid]
        for r in b["reagents"]:
            src = r.get("source_reagent_id")
            if src in owner and owner[src] != eid:
                edges.append({"from": owner[src], "to": eid, "product_id": src, "reagent_id": r["id"],
                              "taken_g": taken_g(r, c["rows"].get(r["id"], {})), "main": False})
    parents = {eid: [] for eid in order}
    children = {eid: [] for eid in order}
    for e in edges:
        if e["from"] not in parents[e["to"]]:
            parents[e["to"]].append(e["from"])
        if e["to"] not in children[e["from"]]:
            children[e["from"]].append(e["to"])

    depth: dict[int, int] = {}

    def dep(n: int, seen: frozenset = frozenset()) -> int:
        if n in depth:
            return depth[n]
        if n in seen:  # a cycle (a product feeding its own ancestor): break it
            return 0
        d = max((dep(p, seen | {n}) + 1 for p in parents[n]), default=0)
        depth[n] = d
        return d

    for n in order:
        dep(n)
    main_parent = {n: max(parents[n], key=lambda p: (depth[p], -order.index(p))) if parents[n] else None
                   for n in order}
    for n in order:  # a cycle can leave a main parent no deeper than its child: drop it
        if main_parent[n] is not None and depth[main_parent[n]] >= depth[n]:
            main_parent[n] = None
    for e in edges:
        e["main"] = main_parent[e["to"]] == e["from"]
    tree = {n: [m for m in order if main_parent[m] == n] for n in order}
    roots = [n for n in order if main_parent[n] is None]

    # starting materials of each experiment that do not come from another experiment; the main one starts the route
    starting, main_start = {}, {}
    for n in order:
        b, c = by_id[n]
        linked = {e["reagent_id"] for e in edges if e["to"] == n}
        starting[n] = [{"reagent": r, "name": scheme.label(r), "taken_g": taken_g(r, c["rows"].get(r["id"], {})),
                        "key": material_key(r)}
                       for r in b["reagents"] if r.get("role") == "reactant" and r["id"] not in linked]
        sm = starting[n]
        main_start[n] = (next((x for x in sm if x["reagent"].get("is_reference")), None)
                         or next((x for x in sm if x["reagent"]["id"] == c.get("limiting_id")), None)
                         or (sm[0] if sm else None)) if not parents[n] else None
    # batches the first experiments start from; experiments of one batch sit together on the map
    materials: dict[str, dict] = {}
    for n in roots:
        m = main_start[n]
        if not m:
            continue
        mat = materials.setdefault(m["key"], {"key": m["key"], "reagent": m["reagent"], "name": m["name"],
                                              "lot": m["reagent"].get("lot"), "supplier": m["reagent"].get("supplier"),
                                              "uses": []})
        mat["uses"].append({"experiment_id": n, "reagent_id": m["reagent"]["id"], "taken_g": m["taken_g"]})
    first_of = {k: i for i, k in enumerate(materials)}
    roots.sort(key=lambda n: first_of.get(main_start[n]["key"], len(first_of)) if main_start[n] else len(first_of))
    for mat in materials.values():
        used = [u["taken_g"] for u in mat["uses"] if u["taken_g"] is not None]
        mat["used_g"] = sum(used) if used else None
        mat["on_hand_g"] = (on_hand or {}).get(mat["key"])
        mat["left_g"] = mat["on_hand_g"] - (mat["used_g"] or 0) if mat["on_hand_g"] is not None else None

    rowpos: dict[int, float] = {}
    next_row = [0]

    def place(n: int) -> None:
        kids = tree[n]
        if not kids:
            rowpos[n] = next_row[0]
            next_row[0] += 1
            return
        for k in kids:
            place(k)
        rowpos[n] = (rowpos[kids[0]] + rowpos[kids[-1]]) / 2

    for r in roots:
        place(r)

    nodes = []
    for n in order:
        b, c = by_id[n]
        prod = product_of(b)
        pc = c["rows"].get(prod["id"], {}) if prod else {}
        isolated = pc.get("isolated_mass_g")
        used = [e["taken_g"] for e in edges if prod and e["product_id"] == prod["id"] and e["taken_g"] is not None]
        nodes.append({
            "id": n, "title": b["experiment"].get("title") or "Untitled", "date": b["experiment"].get("date"),
            "status": b["experiment"].get("status"), "col": depth[n], "row": rowpos[n],
            "product": prod, "yield": c.get("yield"), "isolated_g": isolated,
            "used_g": sum(used) if used else None,
            "remaining_g": isolated - sum(used) if isolated is not None and used else None,
            "parents": parents[n], "children": children[n], "main_parent": main_parent[n],
            "stages": len(b["steps"]), "starting": starting[n], "main_start": main_start[n],
        })
    node = {x["id"]: x for x in nodes}
    for x in nodes:  # overall yield along the main chain back to its start
        chain, cur = [], x["id"]
        while cur is not None and cur not in chain:
            chain.append(cur)
            cur = main_parent[cur]
        x["lls"] = len(chain)
        ys = [node[k]["yield"] for k in chain]
        x["overall_yield"] = None  # a first experiment's overall yield is its own yield
        if all(y is not None for y in ys):
            o = 1.0
            for y in ys:
                o *= y / 100
            x["overall_yield"] = o * 100
    return {"nodes": nodes, "edges": edges, "order": order, "materials": list(materials.values()),
            "cols": max((x["col"] for x in nodes), default=-1) + 1, "rows": next_row[0]}


def ancestors(g: dict, leaf: int) -> list[int]:
    """The experiment and every experiment that feeds it, in route order (parents first)."""
    node = {x["id"]: x for x in g["nodes"]}
    seen: set[int] = set()
    stack = [leaf]
    while stack:
        n = stack.pop()
        if n in seen or n not in node:
            continue
        seen.add(n)
        stack.extend(node[n]["parents"])
    return topo_order(g, seen)


def main_chain(g: dict, leaf: int) -> list[int]:
    """The longest linear sequence ending at ``leaf`` (main parents), first experiment first."""
    node = {x["id"]: x for x in g["nodes"]}
    chain, cur = [], leaf
    while cur is not None and cur in node and cur not in chain:
        chain.append(cur)
        cur = node[cur]["main_parent"]
    return chain[::-1]


def topo_order(g: dict, ids: Optional[set] = None) -> list[int]:
    """Experiments by column, then row (parents before children)."""
    nodes = [x for x in g["nodes"] if ids is None or x["id"] in ids]
    return [x["id"] for x in sorted(nodes, key=lambda x: (x["col"], x["row"]))]


def leaves(g: dict) -> list[int]:
    return [n for n in topo_order(g) if not next(x for x in g["nodes"] if x["id"] == n)["children"]]


# ------------------------------------------------------------------------------------------------- route map
def _t(s: Any, n: int) -> str:
    s = str(s or "")
    return html.escape(s if len(s) <= n else s[: n - 1].rstrip() + "…")


def _fmt(v: Any, sig: int = 3) -> str:
    from .report import fmt

    return fmt(v, sig)


def route_svg(g: dict, img_src: Callable[[dict, int, int], Optional[str]], numbers: Optional[dict] = None,
              link: bool = True, only: Optional[set] = None, inline_css: bool = False,
              currency: Optional[str] = None) -> str:
    """The route map as inline SVG (the app and the reports share it). ``only`` limits it to some experiments;
    ``inline_css`` puts the styles inside the SVG (for the reports; the app styles it with its theme)."""
    nodes = [x for x in g["nodes"] if only is None or x["id"] in only]
    if not nodes:
        return ""
    # compact rows and columns when showing part of the map; the first experiments of the route get a card with
    # their starting materials in front of them
    shown = {x["id"] for x in nodes}
    batches = [dict(m, uses=[u for u in m["uses"] if u["experiment_id"] in shown]) for m in g.get("materials", [])]
    batches = [m for m in batches if m["uses"]]
    shift = 1 if batches else 0
    cols = sorted({x["col"] for x in nodes})
    rows = sorted({x["row"] for x in nodes})
    col_i = {c: i + shift for i, c in enumerate(cols)}
    row_i = {r: i for i, r in enumerate(rows)}
    pos = {x["id"]: (PAD + col_i[x["col"]] * (CARD_W + GAP_X), PAD + row_i[x["row"]] * (CARD_H + GAP_Y)) for x in nodes}
    width = PAD * 2 + (len(cols) + shift) * CARD_W + (len(cols) + shift - 1) * GAP_X
    height = PAD * 2 + len(rows) * CARD_H + (len(rows) - 1) * GAP_Y
    out = [f'<svg class="route-map" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
           f'width="{width}" height="{height}" role="img" aria-label="Route map">',
           '<defs><marker id="rm-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
           'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="rm-head"/></marker></defs>']
    if inline_css:
        out.append(f"<style>{ROUTE_CSS}</style>")
    for e in g["edges"]:
        if e["from"] not in pos or e["to"] not in pos:
            continue
        x1, y1 = pos[e["from"]][0] + CARD_W, pos[e["from"]][1] + CARD_H / 2
        x2, y2 = pos[e["to"]][0] - 2, pos[e["to"]][1] + CARD_H / 2
        mx = (x1 + x2) / 2
        cls = "rm-edge" if e["main"] else "rm-edge extra"
        out.append(f'<path class="{cls}" d="M{x1},{y1} C{mx},{y1} {mx},{y2} {x2},{y2}" marker-end="url(#rm-arrow)"/>')
        if e["taken_g"] is not None:
            lx, ly = x2 - 8, y2 - 6
            out.append(f'<text class="rm-label" x="{lx}" y="{ly}" text-anchor="end">{_fmt(e["taken_g"])} g</text>')
    node_of = {x["id"]: x for x in nodes}
    for m in batches:  # one card per batch, with an arrow and the amount taken to each experiment that uses it
        ys = [pos[u["experiment_id"]][1] for u in m["uses"]]
        px, py = PAD, (min(ys) + max(ys)) / 2
        r = m["reagent"]
        x1, y1 = px + CARD_W, py + CARD_H / 2
        for u in m["uses"]:
            tx, ty = pos[u["experiment_id"]]
            x2, y2 = tx - 2, ty + CARD_H / 2
            mx = (x1 + x2) / 2
            out.append(f'<path class="rm-edge" d="M{x1},{y1} C{mx},{y1} {mx},{y2} {x2},{y2}" marker-end="url(#rm-arrow)"/>')
            if u["taken_g"] is not None:
                out.append(f'<text class="rm-label" x="{x2 - 8}" y="{y2 - 6}" text-anchor="end">{_fmt(u["taken_g"])} g</text>')
        extra = node_of[m["uses"][0]["experiment_id"]]["starting"] if len(m["uses"]) == 1 else []
        extra = [s for s in extra if s["reagent"]["id"] != m["uses"][0]["reagent_id"]]
        title = "Starting material" + (f" · lot {m['lot']}" if m.get("lot") else "")
        card = [f'<g class="rm-node rm-start" data-material="{html.escape(m["key"])}" transform="translate({px},{py})">',
                f'<rect class="rm-card rm-start-card" width="{CARD_W}" height="{CARD_H}" rx="9"/>',
                f'<text class="rm-title rm-start-title" x="14" y="20">{_t(title, 31)}</text>',
                f'<rect class="rm-paper" x="12" y="28" width="{CARD_W - 22}" height="84" rx="5"/>']
        src = img_src(r, 380, 170)
        if src:
            card.append(f'<image href="{html.escape(src)}" x="14" y="30" width="{CARD_W - 26}" height="80" '
                        'preserveAspectRatio="xMidYMid meet"/>')
        else:
            card.append(f'<text class="rm-none" x="{CARD_W / 2 + 3}" y="74" text-anchor="middle">no structure</text>')
        no = (numbers or {}).get(r["id"])
        num = f'<tspan class="rm-no">{no}</tspan> ' if no else ""
        card.append(f'<text class="rm-prod" x="14" y="130">{num}{_t(m["name"], 28 if no else 31)}</text>')
        n_uses = len(m["uses"])
        used = sum(u["taken_g"] for u in m["uses"] if u["taken_g"] is not None) if any(
            u["taken_g"] is not None for u in m["uses"]) else None
        stat = (f"{_fmt(used)} g used" if used is not None else "amount not set") + \
            (f" in {n_uses} experiments" if n_uses > 1 else "")
        card.append(f'<text class="rm-stat" x="14" y="148">{stat}</text>')
        if m.get("on_hand_g") is not None:
            left = m["on_hand_g"] - (used or 0)
            cls = "rm-low" if left < 0 else "rm-left"
            card.append(f'<text class="rm-sub" x="14" y="166">of {_fmt(m["on_hand_g"])} g · '
                        f'<tspan class="{cls}">{_fmt(left)} g left</tspan></text>')
        elif extra:
            more = ", ".join(f'{s["name"]}' + (f' ({_fmt(s["taken_g"])} g)' if s["taken_g"] is not None else "")
                             for s in extra)
            card.append(f'<text class="rm-sub" x="14" y="166">+ {_t(more, 30)}</text>')
        card.append("</g>")
        out.append("".join(card))
    for x in nodes:
        px, py = pos[x["id"]]
        prod = x["product"]
        color = STATUS_COLORS.get(x["status"] or "", "#8a94a3")
        card = [f'<g class="rm-node" data-eid="{x["id"]}" transform="translate({px},{py})">',
                f'<rect class="rm-card" width="{CARD_W}" height="{CARD_H}" rx="9"/>',
                f'<rect x="0" y="0" width="5" height="{CARD_H}" rx="2" fill="{color}"/>',
                f'<text class="rm-title" x="14" y="20">{_t(x["title"], 30)}</text>']
        src = img_src(prod, 380, 170) if prod else None
        card.append(f'<rect class="rm-paper" x="12" y="28" width="{CARD_W - 22}" height="84" rx="5"/>')
        if src:
            card.append(f'<image href="{html.escape(src)}" x="14" y="30" width="{CARD_W - 26}" height="80" '
                        'preserveAspectRatio="xMidYMid meet"/>')
        else:
            card.append(f'<text class="rm-none" x="{CARD_W / 2 + 3}" y="74" text-anchor="middle">'
                        f'{"no structure" if prod else "no product yet"}</text>')
        if prod:
            no = (numbers or {}).get(prod["id"])
            name = scheme.label(prod)
            num = f'<tspan class="rm-no">{no}</tspan> ' if no else ""
            card.append(f'<text class="rm-prod" x="14" y="130">{num}{_t(name, 28 if no else 31)}</text>')
        stats = []
        if x["yield"] is not None:
            stats.append(f'<tspan class="rm-yield">{x["yield"]:.0f}%</tspan>')
        if x["isolated_g"] is not None:
            stats.append(f'{_fmt(x["isolated_g"])} g')
        if x["remaining_g"] is not None:
            low = "rm-low" if x["remaining_g"] < 0 else "rm-left"
            stats.append(f'<tspan class="{low}">{_fmt(x["remaining_g"])} g left</tspan>')
        stat = " · ".join(stats) or '<tspan class="rm-muted">no yield yet</tspan>'
        card.append(f'<text class="rm-stat" x="14" y="148">{stat}</text>')
        sub = []
        if x["overall_yield"] is not None and x["lls"] > 1:
            sub.append(f'overall {x["overall_yield"]:.0f}% ({x["lls"]} steps)')
        elif x["stages"] > 1:
            sub.append(f'one-pot, {x["stages"]} stages')
        per_g = ((x.get("cost") or {}).get("product") or {}).get("cost_per_g") if currency else None
        if per_g is not None:
            from .costs import money
            mark = "" if x["cost"]["complete"] else "≥"
            sub.append(f'<tspan class="rm-cost">{mark}{html.escape(money(per_g, currency))}/g</tspan>')
        if sub:
            card.append(f'<text class="rm-sub" x="14" y="166">{" · ".join(sub)}</text>')
        card.append("</g>")
        out.append((f'<a href="#/exp/{x["id"]}/plan">' + "".join(card) + "</a>") if link else "".join(card))
    out.append("</svg>")
    return "".join(out)


ROUTE_CSS = """
.route-map { font-family: inherit; max-width: 100%; height: auto; }
.route-map .rm-card { fill: #fff; stroke: #cfd5dc; stroke-width: 1; }
.route-map .rm-start-card { fill: #f6f7f9; stroke-dasharray: 4 3; }
.route-map .rm-start-title { fill: #6b7480; }
.route-map .rm-paper { fill: #fff; }
.route-map .rm-title { font-size: 12px; font-weight: 650; fill: #1b1f24; }
.route-map .rm-prod { font-size: 11.5px; fill: #1b1f24; }
.route-map .rm-no { font-weight: 700; }
.route-map .rm-stat { font-size: 11px; fill: #3a434e; }
.route-map .rm-yield { font-weight: 700; fill: #1d7a46; }
.route-map .rm-low { fill: #b42323; font-weight: 600; }
.route-map .rm-sub, .route-map .rm-muted, .route-map .rm-none { font-size: 10.5px; fill: #6b7480; }
.route-map .rm-edge { fill: none; stroke: #6b7480; stroke-width: 1.6; }
.route-map .rm-edge.extra { stroke-dasharray: 5 4; }
.route-map .rm-head { fill: #6b7480; }
.route-map .rm-label { font-size: 10.5px; fill: #3a434e; font-weight: 600; }
.route-map .rm-cost { fill: #8a5a00; font-weight: 650; }
"""


def summary_rows(g: dict, ids: Optional[list[int]] = None) -> list[dict]:
    """Table rows in route order: experiment, what it was made from, product, yields, what is left."""
    node = {x["id"]: x for x in g["nodes"]}
    out = []
    for n, eid in enumerate(ids or topo_order(g), 1):
        x = node[eid]
        froms = [e for e in g["edges"] if e["to"] == eid]
        out.append({**x, "n": n, "from": [{"id": e["from"], "title": node[e["from"]]["title"], "taken_g": e["taken_g"]}
                                          for e in froms]
                    + [{"id": None, "title": sm["name"], "taken_g": sm["taken_g"]} for sm in x["starting"]]})
    return out


def combined_calc(calcs: list[dict]) -> dict:
    rows: dict = {}
    for c in calcs:
        rows.update(c["rows"])
    return {"rows": rows}

