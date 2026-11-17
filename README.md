# Lab Notebook

Self-hosted lab notebook for organic chemistry experiments. It uses [PubChem Local](https://github.com/mcaragon/local_pubchem_db)
as its chemical data source and runs as its own Docker container (built for Unraid).

- **One page per experiment**: overview, reaction scheme, reagents, procedure & log, results, references and report,
  with a section menu. A bench bar with the experiment clock stays at the top while you work.
- **Multi-step experiments.** Each step has its own reagents and condition stages (e.g. 0 °C, 15 min; then rt, 2 h).
  A new step starts from the previous step's product, carrying over the isolated amount.
- **Reaction scheme** drawn the organic chemistry way: numbered structures, reagents and catalysts above each arrow,
  solvent, atmosphere and conditions below, yields under the products. Long conditions switch to lettered arrows with
  a legend.
- **Reagent table** grouped into starting materials, reagents & catalysts, solvents, workup & purification, and
  products. Autocomplete by name, CAS, formula or SMILES; typing `2.5 M n-BuLi in hexanes` or `37% HCl` sets the
  solution type. Molar mass, density, bp, mp, flash point, GHS pictograms and H-statements, plus DOT transport class,
  NFPA 704 rating and reactivity alerts, come from PubChem Local and are shown on every row. Values can be overridden
  (marked *edited*, one click restores them), and grade, supplier, lot, notes and extra hazard notes can be added.
- **Planned and actual amounts.** Plan in g, mL, mmol or equivalents; record what you actually weighed or measured.
  The deviation is shown, the measurement is logged, and the limiting reagent and yields use the actual amounts.
- **Yields:** theoretical (from stoichiometry), expected (literature, linked to a reference), crude and isolated
  (actual), per step and overall.
- **Procedure as numbered steps** with notes, checkboxes and `@` mentions that print the chemical's amount
  (`Add @NaBH4` → "Add NaBH4 (0.189 g, 5.00 mmol, 0.500 equiv)").
- **Log next to the procedure.** Every entry records the time of day and T+ from the start of the experiment.
  Structured actions write standard sentences: add (portionwise/dropwise, over a time), quench, extract
  (4 × 25 mL DCM), wash, dry, filter, concentrate, heat/cool, stir, TLC (eluent, Rf), purify, product mass,
  measurements, observations. Solvent use from the log is totalled per chemical.
- **Timers:** stopwatches started from an action ("Addition of NaBH4") that log their duration when stopped, and
  countdowns with a sound, vibration and notification alert. Timers keep running across reloads and devices.
- **References as numbered rows** (authors, title, journal, year, volume, pages, DOI) or free text; PubChem citations
  are added automatically.
- **Lab report** as PDF, Markdown or a printable HTML page.
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
  **Percent yield** uses the isolated mass (× product purity, if set). The **overall yield** of a multi-step
  experiment is the product of the step yields.

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
| `labnotebook/db.py` | SQLite storage (schema version 2; version 1 databases are migrated on start) |
| `labnotebook/pubchem.py`, `structures.py` | PubChem Local REST client and structure images |
| `labnotebook/report.py`, `templates/report.html` | Markdown / HTML / PDF reports |
| `labnotebook/static/js/` | Frontend modules (vanilla JS, no build step) |
| `unraid/` | Unraid template and icon |

The browser talks only to this app; it proxies PubChem Local (autocomplete, structures, GHS pictograms), so
`PUBCHEM_URL` can be an address that only works inside the Docker network.

## License

MIT
