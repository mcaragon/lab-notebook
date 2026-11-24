# Stockroom: plan

A chemical inventory inside Lab Notebook: the containers a chemist has on hand, with amounts and prices. Reagent rows
in experiments can be drawn from a container, so the stockroom knows what is left and experiments know what they
cost.

## Decisions

| Question | Decision |
| --- | --- |
| Whose stockroom | Each account has its own, like its notebook. Shared stockrooms come later; the data model leaves room for them. |
| When stock goes down | **Measured** amounts (weighed, or logged as "Amount used" / "Add") count as **used**. **Planned** amounts only count as **reserved**, and only while the experiment is not completed: marking an experiment *completed* releases whatever it still had reserved. |
| Currency | One currency per account (set on the Stockroom page). |
| Costs in reports | Off by default, with a checkbox to include them. |
| Architecture | All-in-one, as its own module (`stockroom.py`, its own tables, `/api/stockroom/…` routes) so it could be split out later. |

## Data model

- **Container** (`stock_items`), one per bottle or bag, owned by an account:
  - compound data copied from PubChem Local when added, and editable (name, CAS, formula, SMILES, MW, density, bp,
    mp, flash point, GHS, DOT/NFPA)
  - source: supplier, catalogue number, grade, purity, lot, form (neat / x M solution / x wt %)
  - amount as bought: quantity and unit (g or mL)
  - price paid (total) → price per g or per mL
  - location, received / opened / expiry dates, low-stock threshold, status (in use, empty, disposed), notes
- **Corrections** (`stock_adjustments`): signed amount, reason, time, who (spill, stocktake recount, gift…).
- **Link**: `reagents.stock_item_id`, the container a reagent row was drawn from.
- **Account**: `users.currency`.

Derived, never stored:

- *used* = measured amounts of linked reagent rows (converted to the container's unit with the density when needed)
- *reserved* = planned amounts of linked rows that have no measured amount yet, in experiments that are not completed
- *left* = quantity + corrections − used; *available* = left − reserved
- *value left* = left × price per unit

## Order of work

Each step is usable on its own and ships as its own pull request.

### 1. Stockroom basics ✅ (v0.9)

- Schema v5: containers, corrections, the reagent link column, the account currency.
- Stockroom page (sidebar → 📦 Stockroom):
  - containers grouped by compound, with structure and hazards, amount-left bar, price per unit, value left, location
  - search, filters (in use, low stock, expiring, empty / disposed, all) and summary tiles (containers, total value,
    low stock, expiring)
- Add a container with PubChem Local autocomplete, which fills the compound data; then supplier, amount, price etc.
  "Duplicate" makes the next bottle of the same thing quick to add.
- Container details: edit everything, record corrections, mark empty / disposed, delete; history of corrections.
- Currency per account.

### 2. Plan integration ✅ (v0.10)

- Adding a reagent lists matching **containers first** (supplier, grade, lot, amount left, price), then PubChem
  results. Picking a container fills the row (compound data, supplier, grade, lot, purity) and links it.
- A chip on the reagent row shows its container and switches to another one (or unlinks it).
- Used / reserved / left computed from linked rows as described above; completing an experiment releases its
  reservations.
- Container history lists the experiments that drew from it, with amounts.

### 3. Costs ✅ (v0.11)

- Input cost = amount × container price per unit (measured amount, else planned, marked *estimated*). Solvent and
  workup use comes from the log totals (e.g. "Extracted with DCM 3 × 25 mL") when they are larger than the planned
  amount.
- Experiment cost = sum of inputs; product cost per g (and per mmol) = experiment cost ÷ isolated mass.
- Projects: a portion of another experiment's product inherits that product's cost per g, so each final product has
  a cumulative cost per g along its route; unused product keeps its value for other branches.
- Results tab: cost breakdown per input with shares; Project: cost and $/g product columns and on the route map.
- Inputs without a price make a total *incomplete* (and say which); nothing is silently treated as free.
- Reports: an "Include costs" checkbox (off by default) adds a cost section.

### 4. Later

- CSV import / export of the stockroom; reorder list from low stock.
- Stocktake mode on a phone (walk the shelf, confirm or correct each container).
- Printable labels with a QR code to the container page.
- A reagent row drawn from two containers (one bottle finished, the next opened).
- Shared stockrooms for groups of accounts.
