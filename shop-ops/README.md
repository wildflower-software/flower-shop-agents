# Shop ops: weekly ordering and sales notes for a flower shop

Data model and tooling for recommending what a Philadelphia flower shop should order each
week. Orders arrive **Mon/Wed/Fri** and are placed **2–4 weeks ahead** (4 for holidays).
The recommendations steer toward cheap, good-quality, in-season stems while keeping the
fixed price points (twenties $20, fifteens $15).

This repo covers the **data foundation**: schema, owner-editable config, realistic
placeholder history, and the first estimates. The recommendation engine and the text
message to the owner come next. Their output tables are already in the schema.

## Developer path

- Python is installed and managed by **uv**. The version is pinned in `.python-version` (3.14).
  Don't use the macOS system `python3` or Homebrew Python.
- One virtual environment per project, named `.venv`, created with `uv venv`.
- Install packages with `uv pip install`. uv environments have no `pip`, so
  "No module named pip" is expected. Pin dependencies in `pyproject.toml`.
- Run commands with `uv run ...` or after `source .venv/bin/activate`.

```bash
uv venv
```
```bash
uv pip install -e ".[dev]"
```
```bash
uv run shop-ops init
```
```bash
uv run shop-ops generate
```
```bash
uv run pytest
```

Runtime dependencies are PydanticAI (the note-writing agent) and Prefect (scheduling and run history), pinned in `pyproject.toml` and `uv.lock`. The data tooling itself is stdlib `sqlite3`. pytest is the only dev dependency. Tests never call a real model.

## Layout

```
schema/schema.sql      SQLite data model (the source of truth for tables/views)
config/*.csv           Owner-editable settings, catalog, seasonality, holidays, suppliers
inbox/                 Drop files here for import (stockouts / turned-away requests)
src/shop_ops/     calendar rules, config loader, synthetic data, analysis, CLI,
                       weekly_note.py (the note agent) and flows.py (Prefect schedules)
skills/                Agent Skills the shop's agents use (SKILL.md + scripts)
scripts/start-worker.sh  What the Render worker runs on start
data/shop.db  Generated database (git-ignored)
```

## Commands

| Command | What it does |
|---|---|
| `shop-ops init` | Create the DB and load `config/*.csv` |
| `shop-ops reload-config` | Re-load the CSVs after the owner edits them. History is kept. |
| `shop-ops generate [--years 4]` | Replace synthetic sales, prices and purchases |
| `shop-ops purge-synthetic` | Delete every synthetic row and keep real data |
| `shop-ops import-signals [file]` | Import stockouts and turned-away requests (default `inbox/demand_signals.csv`) |
| `shop-ops check-busiest-days [--include-synthetic]` | Test the Fri/Sat presumption |
| `shop-ops estimate [--write-defaults]` | Simulate on-hand stock, then estimate waste and cooler capacity |
| `shop-ops status` | Row counts by data source |
| `shop-ops weekly-note [--weeks 4] [--as-of DATE]` | Write the owner's weekly sales note as a **draft** text. Nothing is sent. Needs `ANTHROPIC_API_KEY`. |
| `shop-ops drafts` | Show draft texts waiting for review |

## Real vs. placeholder data

Every table that can hold generated data has a `data_source` column:
`real` · `synthetic` · `estimate` · `owner`. The current state:

| Data | Status | How it gets replaced |
|---|---|---|
| Sales by transaction (bouquets, loose stems, bundles, arrangements) | **synthetic**, 4 years | POS export → `sales_transaction` / `sales_line` |
| Stems used per sale | synthetic; recipe-estimated for bouquets, recorded for arrangements | Arrangement stems logged by staff, or estimated from recipes |
| Stockouts and turned-away requests | not tracked yet. Table and CSV template are ready. | `inbox/demand_signals.csv` → `import-signals` (SMS intake later) |
| Supplier prices, pack sizes, minimums, lead times, delivery days, freight | **synthetic**, realistic | Edit `config/suppliers.csv` and `supplier_products.csv`; weekly prices → `supplier_price` |
| Availability and quality flags | synthetic, driven by season windows | Weekly supplier availability lists |
| Hardgood costs (food packet, ribbon, clear and colored paper, vase) | synthetic | `config/hardgoods.csv` |
| On-hand stems | **estimate** from a FIFO simulation | Physical counts → `inventory_count`. They override the simulation on that day. |
| Waste | **estimate**: stems that age past their shelf life in the simulation | Derived only. Waste is never entered by hand. |
| Cooler capacity | **estimate**: peak simulated stems | Owner sets it in `settings.csv` with `data_source=owner` |

## What the owner can tune (all in `config/`, then `reload-config`)

The pattern is a `default_*` column (research or data) next to an `owner_*` column.
Fill in the owner column to override. Leave it blank to use the default.

- **`varieties.csv`**: vase life per variety (`owner_vase_life_days`) and the desired
  on-hand stems (`owner_target_on_hand`), to raise or lower.
- **`seasonality.csv`**: best dates per flower and source (local PA vs. import), as
  `owner_best_start` / `owner_best_end` (MM-DD; can wrap the year end).
- **`owner_events.csv`**: extra busy days such as home games or the Flower Show. Set `active=1`.
  The example rows are inactive.
- **`holidays.csv`**: built-in holidays, rule-based so the dates recompute every year.
- **`substitutions.csv`**: which stems can fill each recipe role, and the preference order.
- **`settings.csv`**: delivery days, lead times, presumed busiest days, and
  `min_customer_vase_days`. A stem has to leave the shop with at least this many days of
  vase life left, so shelf life = vase life − this.

## Business rules captured

- **Twenties ($20)**: 1 mass-market vendor bouquet + 2 filler + 1 statement + 5 greens.
- **Fifteens ($15)**: 1 mass-market vendor bouquet + 4 filler + 5 greens.
- Filler: Alstroemeria, Statice, Pom pons. Statement: Roses, Spider mums, mass-market hydrangea.
  Greens: leatherleaf fern, Limonium, Solidago.
- **Mass-market hydrangea** (recipe statement option) is kept separate from
  **hydrangea by the stem** (premium; loose sales, bundles and arrangements only).
- Every gift-wrap bouquet uses 1 food packet, 1 ribbon, 1 clear paper and 1 colored paper.
  Every arrangement uses 1 vase. See `hardgood_rules.csv`.
- **Fri/Sat as busiest days is a presumption, not a fact.** `assumption_check` records
  it as `presumed` until a check on real sales shows it holds. Synthetic data can never
  promote it to `supported`.
- Weather is out of scope. Flowers live in the walk-in, and shipping is the vendors' responsibility.
- Labor and staffing are out of scope. This system covers flower orders only.

## Seasonality sources (Philadelphia / Pennsylvania)

The defaults in `seasonality.csv` come from Penn State Extension cut-flower guidance
(hydrangea mid-July to August, chrysanthemums as fall short-day crops, solidago as a
strong cut crop) and USDA AMS terminal-market reports (alstroemeria and roses imported
from Colombia/Ecuador year-round; 2025 hybrid-tea roses about $0.42–0.51/stem off-peak).
The owner's experience should override these.

## The weekly sales note

Every Monday at 7:00 (shop time) a scheduled job writes the owner a short note on how
sales are going. It works in four steps, and only one of them uses a model:

1. **Code does the math.** The `interpreting-sales-trends` skill's script compares the last
   4 weeks with the 4 before and the same weeks last year, and flags outlier days.
2. **A model writes the note** from that output, following the skill's `SKILL.md`. It has
   no tools, so it can only return text.
3. **Code checks the note.** Every number must appear in the script's output, placeholder
   data must be labelled, there is at most one question, and it must fit on a phone. A
   note that fails goes back to the model with the reason; if it still fails, the run
   fails and nothing is saved.
4. **The note is saved as a draft** in `recommendation_message`. Nothing is sent. Sending
   texts comes later, behind an approval check in code.

Prefect records every run, including failed ones, and retries a failed model call up to
three times. Set `SHOP_OPS_MODEL` to use a different model
(default `anthropic:claude-sonnet-5-5`).

## Deploy on Render

`render.yaml` (at the repo root) sets up one **background worker** with a 1 GB **persistent disk** holding
the SQLite database. The worker stays up and runs `flow.serve()`, which waits for the
schedule in **Prefect Cloud** and runs the flow when it is due.

Why this shape:

- Render cron jobs can't attach a disk, so they can't reach a SQLite file.
- A Render disk belongs to one service, so the worker that writes the database is
  the one that runs the jobs.
- `flow.serve()` needs a Prefect API to schedule against. Prefect Cloud also gives
  you the run history and logs, including each draft note.

Steps:

1. Create a Prefect Cloud workspace and an API key.
2. In Render: **New > Blueprint**, pick this repo (the Blueprint builds from `shop-ops/`), and enter `ANTHROPIC_API_KEY`,
   `PREFECT_API_URL` and `PREFECT_API_KEY` when asked.
3. On first start the worker creates the database on the disk and, while
   `SHOP_OPS_SEED_SYNTHETIC=1`, fills it with placeholder history. Set it to `0`
   once real sales are loaded.
4. Read drafts in the Prefect run log, or in the Render shell with `uv run shop-ops drafts`.

When the text desk arrives (an inbound SMS web service), two services will need the
database, so it moves to Render Postgres.
