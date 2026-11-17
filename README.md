# Lab Notebook

Self-hosted lab notebook for organic chemistry experiments. It uses [PubChem Local](https://github.com/mcaragon/local_pubchem_db)
as its chemical data source and runs as its own Docker container (built for Unraid).

- **Experiments** with title, date, author, course and status (planned / in progress / completed).
- **Reagent table** with autocomplete by name, CAS, formula or SMILES. Molar mass, density, bp, mp, flash point,
  refractive index and GHS hazards are filled in from PubChem Local. Any value can be overridden (marked *edited*,
  one click restores the PubChem value), and the individual source values behind bp/mp/density/flash point can be
  shown.
- **Stoichiometry**: type a mass, volume, mmol or equivalents in any row and the rest is calculated. Handles purity,
  molar solutions (e.g. 2.5 M n-BuLi) and wt% solutions (e.g. 37 % HCl), stoichiometric coefficients, a reference
  reagent for equivalents, the limiting reactant, and theoretical and percent yield.
- **Procedure**, **timestamped log** of observations, notes and measurements (value + unit), and **results /
  discussion / conclusion / references**.
- **Lab report** as PDF, Markdown or a printable HTML page, with structures, a reagent table, a safety table with GHS
  pictograms and H-statements, the observation log, yields, and PubChem citations.
- Works without PubChem Local too: all data can be entered by hand.

Single user, no login. Intended for your LAN; the layout works on tablets and phones.

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

Container names like `pubchem-local` only resolve on a custom network, never on the default `bridge` network. Avoid
setting PubChem Local's network type to *Container: lab-notebook*: that removes PubChem Local's own port mapping, so
its web UI is no longer reachable on port 55055, and it breaks whenever lab-notebook is restarted or updated.

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
- **Equivalents** are relative to the reference reagent (radio button), by default the first reactant with an amount.
- The **limiting reactant** is the *reactant* with the smallest mmol ÷ coefficient. Reagents, catalysts and solvents
  never limit the yield, so give the role *Reactant* only to the compounds that end up in the product.
- **Theoretical yield** = limiting mmol ÷ its coefficient × product coefficient × product molar mass.
  **Percent yield** uses the isolated mass (× product purity, if set).

Physical properties from PubChem Local are the median of all PubChem source values at standard conditions. Check
them, especially for salts, hydrates and solutions: for example, PubChem's "hydrochloric acid" has the density of
HCl itself, not of 37 % aqueous HCl.

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
| `labnotebook/stoich.py` | Stoichiometry calculations (pure functions) |
| `labnotebook/db.py` | SQLite storage |
| `labnotebook/pubchem.py` | PubChem Local REST client |
| `labnotebook/report.py`, `templates/report.html` | Markdown / HTML / PDF reports |
| `labnotebook/static/` | Single-page frontend (vanilla JS, no build step) |
| `unraid/` | Unraid template and icon |

The browser talks only to this app; it proxies PubChem Local (autocomplete, structures, GHS pictograms), so
`PUBCHEM_URL` can be an address that only works inside the Docker network.

## License

MIT
