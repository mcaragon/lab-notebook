# Lab Notebook

Self-hosted lab notebook for organic chemistry experiments. It uses [PubChem Local](https://github.com/mcaragon/local_pubchem_db)
as its chemical data source and runs as its own Docker container (built for Unraid).

- **Workspace layout:** a sidebar with all experiments and projects (searchable, collapsible groups, can be hidden),
  a dashboard, and per experiment four tabs that fill the window with side-by-side panes that scroll on their own:
  **Plan** (reaction scheme and reagents, with a side rail showing *At a glance* figures, the *Route* (where the
  starting materials came from and where the product went), an experiment-wide *Hazard summary* and the details), **Bench** (reagent checklist | procedure | log), **Results** (yields and
  write-up | references) and **Report**. Every section folds; the clock and running timers stay in a strip at the top.
  Light and night themes: the switch at the bottom of the sidebar (☀ Light · ◐ Auto · ☾ Night; ☾ in the header on
  phones) overrides the device setting. Color marks chemical roles, procedure phases, kinds of log entry, status and
  hazards.
- **One experiment, one reaction.** An experiment has one arrow in its scheme and one product yield. Reagents added in
  sequence to the same flask without isolating anything (forming a Grignard reagent, then adding the aldehyde) are
  numbered **stages** of that reaction, drawn on the arrow the usual way ("1. Mg, THF, reflux; 2. PhCHO, 0 °C"); all
  stages share one reference reagent and one limiting reagent.
- **Projects and branching routes.** Experiments are linked by material: a starting material can be a portion of
  another experiment's product (type the product's name under Starting materials, or press **⑂ Branch** on a
  product). A project shows the route as a map that can branch (one intermediate used in several reactions, or in
  several small-scale trials) and converge (two intermediates combined). Each product shows how much was taken and
  how much is left; each experiment shows its yield and the overall yield along the longest chain leading to it.
  Project reports cover the whole project or the route to one final product.
- **Reaction scheme** drawn the organic chemistry way: numbered structures, reagents and catalysts above each arrow,
  solvent, atmosphere and conditions below, yields under the products. Long conditions switch to lettered arrows with
  a legend.
- **Reagent table** grouped into starting materials, reagents & catalysts, solvents, workup & purification, and
  products. Autocomplete by name, CAS, formula or SMILES; typing `2.5 M n-BuLi in hexanes` or `37% HCl` sets the
  solution type. Molar mass, density, bp, mp, flash point, GHS pictograms and H-statements, plus DOT transport class,
  NFPA 704 rating and reactivity alerts, come from PubChem Local and are shown on every row. Values can be overridden
  (marked *edited*, one click restores them), and grade, supplier, lot, notes and extra hazard notes can be added.
- **Planned and actual amounts.** Plan in g, mL, mmol or equivalents; record what you actually weighed or measured
  in the table, in the Bench checklist or in the log ("Amount used", or the amounts of "Add" entries, which add up
  over several portions). The log is the record: the deviation is shown, and the limiting reagent and yields use the
  actual amounts.
- **Yields:** theoretical (from stoichiometry), expected (literature, linked to a reference), crude and isolated
  (actual); overall yields along a project's route.
- **Procedure as numbered steps in phases:** Setup, Reaction, Workup, Purification and Analysis, plus phases of your
  own (e.g. Recrystallization). Phases without steps are hidden. Steps have notes, checkboxes and `@` mentions that
  print the chemical's amount (`Add @NaBH4` → "Add NaBH4 (0.189 g, 5.00 mmol, 0.500 equiv)").
- **Log next to the procedure,** oldest entry first, with the composer underneath. Every entry records the time of day
  and T+ from the start of the experiment and belongs to the procedure step that was current. Structured actions
  write standard sentences: add (portionwise/dropwise, over a time), amount used, quench, extract (4 × 25 mL DCM),
  wash, dry, filter, concentrate, heat/cool, stir, TLC (eluent, Rf), purify, product mass, measurements,
  observations. `@` inserts a chemical in any log text. Solvent use from the log is totalled per chemical.
- **Timers:** stopwatches ("Addition of @NaBH4") that log their duration when stopped, and countdowns with a sound,
  vibration and notification alert. Started from the composer or from an action; they keep running across reloads
  and devices.
- **References as numbered rows** (authors, title, journal, year, volume, pages, DOI) or free text; PubChem citations
  are added automatically.
- **Lab report** as PDF, Markdown or a printable HTML page. The reagent table shows the measured amount of each
  chemical (the planned one, marked, when nothing was measured), its properties and its hazards: pictograms, signal
  word, H-codes (full statements listed once below the table), flash point, DOT, NFPA and reactivity alerts.
  Procedure and log are side by side, grouped by phase: each procedure step next to the entries logged during it.
  A project report has the route map, a table of the experiments (what each was made from, yield, what is left,
  overall yield) and one chapter per experiment, with compound numbers shared across the project.
- Works without PubChem Local too: all data can be entered by hand.

Single user, no login. Intended for your LAN or Tailscale; the layout adapts from laptop (procedure and log side by
side) to phone (log entries under each procedure step, compact log bar). Keeping the screen awake and timer
notifications need HTTPS (e.g. Tailscale Serve) or localhost; sound and vibration alerts work everywhere.

## Install on Unraid

1. Make sure PubChem Local is running (with at least the `lcss` dataset, plus `names` for better name search).
2. Install the template:
   ```bash
   wget -O /boot/config/plugins/dockerMan/templates-user/my-lab-notebook.xml https://raw.githubusercontent.com/mcaragon/lab-notebook/main/unraid/lab-notebook.xml
   ```
3. Docker → Add Container → pick **lab-notebook** from the template list.
4. Set **PubChem Local URL** to match how the two containers are networked (see below).
5. Open the Web UI (default host port 55056). The header shows whether PubChem Local is reachable; hover over it to
   see the error if it is not.

### Connecting to PubChem Local

| Network setup | PubChem Local URL |
| --- | --- |
| Both containers on Unraid's default `bridge` network (simplest) | `http://<unraid-ip>:55055` (Unraid IP + PubChem Local's **host** port) |
| Both containers on the same **custom** network, e.g. one made with `docker network create chem` | `http://pubchem-local:8080` (container **name** + **container** port) |
| PubChem Local's network type set to **Container: lab-notebook** (shares lab-notebook's network, e.g. to reach both through lab-notebook's Tailscale) | `http://localhost:8080` |

Container names like `pubchem-local` only resolve on a custom network, never on the default `bridge` network.

When PubChem Local shares lab-notebook's network (*Container: lab-notebook*):

- Both apps answer on lab-notebook's addresses, including its Tailscale MagicDNS name: the notebook on port 8000 and
  PubChem Local on port 8080 (on Tailscale, use the container ports).
- PubChem Local's own port mappings no longer apply. To reach its web UI from the LAN, add a port to
  **lab-notebook's** template: container port 8080 → host port 55055.
- When lab-notebook is restarted, updated or edited, restart PubChem Local too. It is attached to the old network
  until it is restarted, and the notebook then shows "PubChem Local offline".

To check the connection from the Unraid terminal:

```bash
docker exec lab-notebook python -c "import os, urllib.request; print(urllib.request.urlopen(os.environ['PUBCHEM_URL'] + '/api/health').read())"
```

Back up `/mnt/user/appdata/lab-notebook` (a single SQLite file, `notebook.sqlite`).

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `PUBCHEM_URL` | `http://localhost:55055` | Base URL of PubChem Local, as seen from this container |
| `PUBCHEM_TIMEOUT` | `8` | Seconds before a PubChem Local request is treated as unavailable |
| `AUTHOR_NAME` | | Default author for new experiments |
| `LAB_NAME` | | Lab / institution shown in the report header |
| `TZ` | | Time zone for log timestamps, e.g. `Europe/Berlin` |
| `PORT` | `8000` | Port inside the container |
| `NOTEBOOK_DATA_DIR` | `/data` | Database location |
| `PUID` / `PGID` | `99` / `100` | User and group the app runs as (Unraid's nobody:users) |

## How the calculations work

All amounts are in g, mL, mmol and °C. Each row has one **entered** value (bold); everything else is **calculated**
(blue).

| Form | Mass means | Volume means | Needed for mmol |
| --- | --- | --- | --- |
| Neat / pure | mass weighed | volume measured (needs density) | molar mass, purity (default 100 %) |
| Solution (molarity) | mass of solution (needs solution density) | volume of solution | concentration in M |
| Solution (wt %) | mass of solution | volume of solution (needs solution density) | molar mass, wt % |

- A neat compound that is solid at room temperature (mp above 25 °C) gets no calculated volume.
- Each row has a **planned** amount and, once weighed or measured, an **actual** amount (g or mL). Wherever an
  actual amount exists it is used for the limiting reagent, the theoretical yield and the percent yield.
- **Equivalents** are relative to the reference reagent ("Use as 1 equiv"), by default the first starting material
  with an amount.
- The **limiting reactant** is the *starting material* with the smallest mmol ÷ coefficient. Reagents, catalysts and
  solvents never limit the yield, so put only the compounds that end up in the product under Starting materials.
- **Theoretical yield** = limiting mmol ÷ its coefficient × product coefficient × product molar mass.
  **Percent yield** uses the isolated mass (× product purity, if set). The **overall yield** of an experiment in a
  project is the product of the yields along the longest chain of experiments leading to it.
- A one-pot reaction in several **stages** is one reaction: one reference, and a starting material added in a later
  stage can be the limiting one.
- A starting material taken from another experiment's product counts against that product: **left** = isolated mass
  − what the other experiments took (measured if recorded, else planned).

Physical properties from PubChem Local are the median of all PubChem source values at standard conditions. Check
them, especially for salts, hydrates and solutions: for example, PubChem's "hydrochloric acid" has the density of
HCl itself, not of 37 % aqueous HCl.

## Structures and hazard data

All structure drawings come from PubChem Local: by CID for every compound it knows, and for compounds entered by hand
with a SMILES string from `GET /api/depict?smiles=…&width=…&height=…&theme=light|dark` (returning SVG) if PubChem
Local provides that endpoint. Until it does, hand-entered compounds are shown without a structure.

GHS data comes from the lab summary; DOT, NFPA 704 and reactivity alerts come from PubChem Local's safety summary
(LCSS). Compounds without an LCSS record (for example silver fulminate) have no hazard data in PubChem Local; use the
"Additional hazard information" field of the reagent, which is printed in the report's safety table.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
python -m pytest
```

Tests use recorded PubChem Local responses (`tests/fixtures`), so no PubChem data is needed. To run against real data,
start a local PubChem Local:

```bash
pip install "pubchem2sqlite[server] @ git+https://github.com/mcaragon/local_pubchem_db"
PUBCHEM_DATA_DIR=./pc pubchem-local build --datasets lcss
PUBCHEM_DATA_DIR=./pc pubchem-local serve --port 8080
```

and then the notebook:

```bash
NOTEBOOK_DATA_DIR=./data PUBCHEM_URL=http://localhost:8080 lab-notebook serve --port 8000
```

PDF export uses [WeasyPrint](https://weasyprint.org), which needs Pango (`libpango-1.0-0 libpangoft2-1.0-0` on
Debian/Ubuntu). Without it, PDF export returns HTTP 501 and the other formats still work. The API is documented at
`/docs`.

### Layout

| Path | Contents |
| --- | --- |
| `labnotebook/app.py` | FastAPI app: JSON API, PubChem Local proxy, report downloads, frontend |
| `labnotebook/stoich.py` | Stoichiometry: planned/actual amounts, limiting reagent, yields (pure functions) |
| `labnotebook/actions.py` | Log actions: fields and the sentences they produce |
| `labnotebook/scheme.py`, `templates/scheme.html` | Reaction scheme layout and `@` mentions |
| `labnotebook/hazards.py` | DOT / NFPA / reactivity data from the safety summary |
| `labnotebook/projects.py` | Project routes: material links between experiments, layout, overall yields, route map (SVG) |
| `labnotebook/db.py` | SQLite storage (schema version 3; older databases are migrated on start: multi-step experiments become linked experiments in a project) |
| `labnotebook/pubchem.py`, `structures.py` | PubChem Local REST client and structure images |
| `labnotebook/report.py`, `templates/report.html` | Markdown / HTML / PDF reports |
| `labnotebook/static/js/` | Frontend modules (vanilla JS, no build step) |
| `unraid/` | Unraid template and icon |

The browser talks only to this app; it proxies PubChem Local (autocomplete, structures, GHS pictograms), so
`PUBCHEM_URL` can be an address that only works inside the Docker network.

## License

MIT. The bundled Inter font (`labnotebook/static/fonts`) is © The Inter Project Authors, under the SIL Open Font
License 1.1 (`Inter-LICENSE.txt`).
