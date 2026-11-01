-- Flower shop: weekly flower-order recommendation data model (SQLite).
--
-- Conventions
--   * data_source on every table that can hold generated rows:
--       'real'      – came from the shop (POS export, invoices, counts)
--       'synthetic' – generated placeholder; delete with `shop-ops purge-synthetic`
--       'estimate'  – derived by analysis from other data
--       'owner'     – entered/overridden by the owner
--   * Owner-tunable values use a default_* column plus an owner_* column.
--     The *_effective views pick owner_* when set, otherwise default_*.
--   * Dates are ISO-8601 text (YYYY-MM-DD); timestamps are YYYY-MM-DD HH:MM:SS local time.
--   * Season dates are MM-DD and may wrap the year end (e.g. 11-01 .. 03-31).

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- settings
CREATE TABLE IF NOT EXISTS setting (
    key          TEXT PRIMARY KEY,
    value        TEXT NOT NULL,
    data_source  TEXT NOT NULL DEFAULT 'owner'
                 CHECK (data_source IN ('real','synthetic','estimate','owner')),
    note         TEXT
);

-- ---------------------------------------------------------------- catalog
CREATE TABLE IF NOT EXISTS variety (
    id                       INTEGER PRIMARY KEY,
    code                     TEXT NOT NULL UNIQUE,
    name                     TEXT NOT NULL,
    -- base = the mass-market vendor bouquet used inside twenties/fifteens
    category                 TEXT NOT NULL
                             CHECK (category IN ('base','filler','statement','green','specialty')),
    unit                     TEXT NOT NULL DEFAULT 'stem' CHECK (unit IN ('stem','bouquet')),
    default_vase_life_days   INTEGER NOT NULL CHECK (default_vase_life_days > 0),
    owner_vase_life_days     INTEGER CHECK (owner_vase_life_days > 0),
    default_target_on_hand   INTEGER NOT NULL CHECK (default_target_on_hand >= 0),
    owner_target_on_hand     INTEGER CHECK (owner_target_on_hand >= 0),
    notes                    TEXT
);

CREATE VIEW IF NOT EXISTS variety_effective AS
SELECT v.*,
       COALESCE(owner_vase_life_days, default_vase_life_days) AS vase_life_days,
       COALESCE(owner_target_on_hand, default_target_on_hand) AS target_on_hand
FROM variety v;

-- One row per variety × source (local field, import, mass-market vendor).
CREATE TABLE IF NOT EXISTS season_window (
    id                       INTEGER PRIMARY KEY,
    variety_id               INTEGER NOT NULL REFERENCES variety(id),
    source                   TEXT NOT NULL CHECK (source IN ('local','import','vendor')),
    default_best_start       TEXT NOT NULL,   -- MM-DD
    default_best_end         TEXT NOT NULL,   -- MM-DD
    owner_best_start         TEXT,
    owner_best_end           TEXT,
    available_off_season     INTEGER NOT NULL DEFAULT 1 CHECK (available_off_season IN (0,1)),
    in_season_price_factor   REAL NOT NULL DEFAULT 1.0,
    off_season_price_factor  REAL NOT NULL DEFAULT 1.0,
    quality_note             TEXT,
    research_basis           TEXT,
    UNIQUE (variety_id, source)
);

CREATE VIEW IF NOT EXISTS season_window_effective AS
SELECT s.*,
       COALESCE(owner_best_start, default_best_start) AS best_start,
       COALESCE(owner_best_end,   default_best_end)   AS best_end
FROM season_window s;

-- Holidays (rule-based) and owner events (e.g. home games) in one table.
CREATE TABLE IF NOT EXISTS calendar_event (
    id                  INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    kind                TEXT NOT NULL CHECK (kind IN ('holiday','owner_event')),
    rule                TEXT,            -- holidays: see calendar.py; owner events: NULL
    event_date          TEXT,            -- owner events: the specific date
    demand_lift         REAL NOT NULL DEFAULT 1.0,   -- 2.0 = twice a normal day
    window_before_days  INTEGER NOT NULL DEFAULT 0,
    window_after_days   INTEGER NOT NULL DEFAULT 0,
    order_lead_weeks    INTEGER NOT NULL DEFAULT 2,
    focus_varieties     TEXT,            -- '|'-separated variety codes that spike
    active              INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    notes               TEXT,
    CHECK ((kind = 'holiday' AND rule IS NOT NULL) OR (kind = 'owner_event' AND event_date IS NOT NULL))
);

-- Materialised dates for each event (rebuilt on config load).
CREATE TABLE IF NOT EXISTS event_occurrence (
    event_id    INTEGER NOT NULL REFERENCES calendar_event(id) ON DELETE CASCADE,
    event_date  TEXT NOT NULL,
    PRIMARY KEY (event_id, event_date)
);

-- ---------------------------------------------------------------- suppliers
CREATE TABLE IF NOT EXISTS supplier (
    id                         INTEGER PRIMARY KEY,
    code                       TEXT NOT NULL UNIQUE,
    name                       TEXT NOT NULL,
    kind                       TEXT NOT NULL
                               CHECK (kind IN ('wholesaler','importer','local_farm','mass_market')),
    lead_time_days             INTEGER NOT NULL,   -- normal weeks
    holiday_lead_time_days     INTEGER NOT NULL,   -- order this far ahead for holidays
    delivery_weekdays          TEXT NOT NULL,      -- e.g. 'MON|WED|FRI'
    freight_flat_per_delivery  REAL NOT NULL DEFAULT 0,
    freight_per_pack           REAL NOT NULL DEFAULT 0,
    min_order_dollars          REAL NOT NULL DEFAULT 0,
    data_source                TEXT NOT NULL DEFAULT 'synthetic'
                               CHECK (data_source IN ('real','synthetic','estimate','owner'))
);

CREATE TABLE IF NOT EXISTS supplier_product (
    id                   INTEGER PRIMARY KEY,
    supplier_id          INTEGER NOT NULL REFERENCES supplier(id),
    variety_id           INTEGER NOT NULL REFERENCES variety(id),
    origin               TEXT NOT NULL CHECK (origin IN ('local','import','vendor')),
    pack_unit            TEXT NOT NULL DEFAULT 'bunch' CHECK (pack_unit IN ('bunch','box','case','each')),
    stems_per_pack       INTEGER NOT NULL CHECK (stems_per_pack > 0),
    min_packs            INTEGER NOT NULL DEFAULT 1 CHECK (min_packs > 0),
    base_price_per_stem  REAL NOT NULL,
    data_source          TEXT NOT NULL DEFAULT 'synthetic'
                         CHECK (data_source IN ('real','synthetic','estimate','owner')),
    UNIQUE (supplier_id, variety_id, origin)
);

-- Weekly price / availability / quality snapshot (week_start = Monday).
CREATE TABLE IF NOT EXISTS supplier_price (
    supplier_product_id  INTEGER NOT NULL REFERENCES supplier_product(id),
    week_start           TEXT NOT NULL,
    price_per_stem       REAL NOT NULL,
    availability         TEXT NOT NULL CHECK (availability IN ('available','limited','unavailable')),
    quality_grade        TEXT NOT NULL DEFAULT 'A' CHECK (quality_grade IN ('A','B','C')),
    data_source          TEXT NOT NULL DEFAULT 'synthetic'
                         CHECK (data_source IN ('real','synthetic','estimate','owner')),
    PRIMARY KEY (supplier_product_id, week_start)
);

-- ---------------------------------------------------------------- products & recipes
CREATE TABLE IF NOT EXISTS product (
    id               INTEGER PRIMARY KEY,
    sku              TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL,
    product_type     TEXT NOT NULL
                     CHECK (product_type IN ('bouquet_giftwrap','loose_stem','bundle','arrangement')),
    variety_id       INTEGER REFERENCES variety(id),   -- loose stems & single-variety bundles
    stems_per_unit   INTEGER,                          -- loose = 1, bundle = n, recipe items NULL
    list_price       REAL,                             -- NULL for custom-priced arrangements
    active           INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    data_source      TEXT NOT NULL DEFAULT 'owner'
                     CHECK (data_source IN ('real','synthetic','estimate','owner'))
);

-- "twenties" = 1 base + 2 filler + 1 statement + 5 green, etc.
CREATE TABLE IF NOT EXISTS recipe_slot (
    product_id  INTEGER NOT NULL REFERENCES product(id),
    role        TEXT NOT NULL CHECK (role IN ('base','filler','statement','green')),
    qty         INTEGER NOT NULL CHECK (qty > 0),
    PRIMARY KEY (product_id, role)
);

-- Which varieties can fill a role. preference_rank 1 = first choice when prices tie.
CREATE TABLE IF NOT EXISTS substitution_option (
    role             TEXT NOT NULL CHECK (role IN ('base','filler','statement','green')),
    variety_id       INTEGER NOT NULL REFERENCES variety(id),
    preference_rank  INTEGER NOT NULL DEFAULT 1,
    active           INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    PRIMARY KEY (role, variety_id)
);

-- Supplies consumed per sale (food packet, ribbon, papers, vase).
CREATE TABLE IF NOT EXISTS hardgood (
    id           INTEGER PRIMARY KEY,
    code         TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    unit_cost    REAL NOT NULL,
    data_source  TEXT NOT NULL DEFAULT 'synthetic'
                 CHECK (data_source IN ('real','synthetic','estimate','owner'))
);

CREATE TABLE IF NOT EXISTS hardgood_rule (
    hardgood_id   INTEGER NOT NULL REFERENCES hardgood(id),
    product_type  TEXT NOT NULL
                  CHECK (product_type IN ('bouquet_giftwrap','loose_stem','bundle','arrangement')),
    qty_per_sale  REAL NOT NULL DEFAULT 1,
    PRIMARY KEY (hardgood_id, product_type)
);

-- ---------------------------------------------------------------- sales (demand)
CREATE TABLE IF NOT EXISTS sales_transaction (
    id            INTEGER PRIMARY KEY,
    occurred_at   TEXT NOT NULL,
    channel       TEXT NOT NULL DEFAULT 'walk_in'
                  CHECK (channel IN ('walk_in','phone','online','event','other')),
    external_ref  TEXT,            -- POS transaction id, for de-duplicating imports
    data_source   TEXT NOT NULL DEFAULT 'real'
                  CHECK (data_source IN ('real','synthetic','estimate','owner'))
);
CREATE INDEX IF NOT EXISTS ix_txn_time ON sales_transaction(occurred_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_txn_ref ON sales_transaction(external_ref) WHERE external_ref IS NOT NULL;

CREATE TABLE IF NOT EXISTS sales_line (
    id              INTEGER PRIMARY KEY,
    transaction_id  INTEGER NOT NULL REFERENCES sales_transaction(id) ON DELETE CASCADE,
    product_id      INTEGER NOT NULL REFERENCES product(id),
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    unit_price      REAL NOT NULL,
    line_total      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_line_txn ON sales_line(transaction_id);

-- Stems actually used by a sale. 'recorded' when staff logged it (custom arrangements),
-- 'recipe_estimate' when inferred from the recipe + substitution options.
CREATE TABLE IF NOT EXISTS sales_line_component (
    sales_line_id  INTEGER NOT NULL REFERENCES sales_line(id) ON DELETE CASCADE,
    variety_id     INTEGER NOT NULL REFERENCES variety(id),
    stems          INTEGER NOT NULL CHECK (stems > 0),
    how_known      TEXT NOT NULL CHECK (how_known IN ('recorded','recipe_estimate')),
    PRIMARY KEY (sales_line_id, variety_id)
);

-- Demand the sales table can't see: stockouts, turned-away customers, requests.
CREATE TABLE IF NOT EXISTS demand_signal (
    id           INTEGER PRIMARY KEY,
    occurred_at  TEXT NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('stockout','turned_away','special_request')),
    raw_text     TEXT NOT NULL,             -- what was asked for, in the owner's words
    variety_id   INTEGER REFERENCES variety(id),
    product_id   INTEGER REFERENCES product(id),
    quantity     INTEGER,
    source       TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','csv','sms','pos')),
    note         TEXT,
    data_source  TEXT NOT NULL DEFAULT 'real'
                 CHECK (data_source IN ('real','synthetic','estimate','owner'))
);

-- ---------------------------------------------------------------- purchasing & inventory
CREATE TABLE IF NOT EXISTS purchase_order (
    id             INTEGER PRIMARY KEY,
    supplier_id    INTEGER NOT NULL REFERENCES supplier(id),
    ordered_on     TEXT NOT NULL,
    delivery_date  TEXT NOT NULL,   -- a processing day (MON/WED/FRI)
    freight_cost   REAL NOT NULL DEFAULT 0,
    data_source    TEXT NOT NULL DEFAULT 'real'
                   CHECK (data_source IN ('real','synthetic','estimate','owner'))
);
CREATE INDEX IF NOT EXISTS ix_po_delivery ON purchase_order(delivery_date);

CREATE TABLE IF NOT EXISTS purchase_line (
    id                   INTEGER PRIMARY KEY,
    order_id             INTEGER NOT NULL REFERENCES purchase_order(id) ON DELETE CASCADE,
    supplier_product_id  INTEGER NOT NULL REFERENCES supplier_product(id),
    packs                INTEGER NOT NULL CHECK (packs > 0),
    stems                INTEGER NOT NULL CHECK (stems > 0),
    price_per_stem       REAL NOT NULL,
    line_cost            REAL NOT NULL
);

-- Physical counts when the owner takes them. Optional; on-hand is otherwise simulated.
CREATE TABLE IF NOT EXISTS inventory_count (
    id           INTEGER PRIMARY KEY,
    counted_at   TEXT NOT NULL,
    variety_id   INTEGER NOT NULL REFERENCES variety(id),
    stems        INTEGER NOT NULL CHECK (stems >= 0),
    data_source  TEXT NOT NULL DEFAULT 'real'
                 CHECK (data_source IN ('real','synthetic','estimate','owner'))
);

-- Output of the inventory simulation (FIFO lots, discarded after shelf life).
CREATE TABLE IF NOT EXISTS inventory_estimate (
    day          TEXT NOT NULL,
    variety_id   INTEGER NOT NULL REFERENCES variety(id),
    on_hand      INTEGER NOT NULL,
    received     INTEGER NOT NULL,
    used         INTEGER NOT NULL,
    discarded    INTEGER NOT NULL,
    PRIMARY KEY (day, variety_id)
);

-- ---------------------------------------------------------------- competitors
CREATE TABLE IF NOT EXISTS competitor (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    kind          TEXT NOT NULL CHECK (kind IN ('trader_joes','grocery','local_shop','online','other')),
    neighborhood  TEXT,
    notes         TEXT
);

-- Spot checks: "TJ's mixed bouquet, $12.99, ~15 stems, alstro + mums".
CREATE TABLE IF NOT EXISTS competitor_observation (
    id             INTEGER PRIMARY KEY,
    competitor_id  INTEGER NOT NULL REFERENCES competitor(id),
    observed_on    TEXT NOT NULL,
    item_desc      TEXT NOT NULL,
    price          REAL NOT NULL,
    stem_count     INTEGER,
    varieties      TEXT,   -- '|'-separated variety codes where known
    notes          TEXT
);

-- ---------------------------------------------------------------- assumptions & outputs
-- Beliefs the system must not treat as true until real data supports them
-- (e.g. "Fri/Sat are the busiest days").
CREATE TABLE IF NOT EXISTS assumption_check (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    status       TEXT NOT NULL
                 CHECK (status IN ('presumed','supported','not_supported','insufficient_data')),
    evidence     TEXT NOT NULL,
    data_basis   TEXT NOT NULL CHECK (data_basis IN ('real','synthetic','mixed')),
    checked_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS order_recommendation (
    id                   INTEGER PRIMARY KEY,
    run_at               TEXT NOT NULL,
    delivery_date        TEXT NOT NULL,
    order_by_date        TEXT NOT NULL,
    supplier_product_id  INTEGER NOT NULL REFERENCES supplier_product(id),
    packs                INTEGER NOT NULL,
    stems                INTEGER NOT NULL,
    est_cost             REAL NOT NULL,
    reason               TEXT,
    status               TEXT NOT NULL DEFAULT 'proposed'
                         CHECK (status IN ('proposed','sent','accepted','edited','rejected'))
);

-- The owner prefers text messages; recommendations are summarised here for SMS.
CREATE TABLE IF NOT EXISTS recommendation_message (
    id        INTEGER PRIMARY KEY,
    run_at    TEXT NOT NULL,
    channel   TEXT NOT NULL DEFAULT 'sms' CHECK (channel IN ('sms','email','print')),
    body      TEXT NOT NULL,
    status    TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','sent','replied')),
    reply     TEXT
);

-- ---------------------------------------------------------------- handy views
CREATE VIEW IF NOT EXISTS daily_sales AS
SELECT date(t.occurred_at)                       AS day,
       CAST(strftime('%w', t.occurred_at) AS INT) AS weekday,   -- 0 = Sunday
       COUNT(DISTINCT t.id)                       AS transactions,
       SUM(l.line_total)                          AS revenue,
       MIN(t.data_source)                         AS data_source_min,
       MAX(t.data_source)                         AS data_source_max
FROM sales_transaction t
JOIN sales_line l ON l.transaction_id = t.id
GROUP BY date(t.occurred_at);

CREATE VIEW IF NOT EXISTS stems_used_daily AS
SELECT date(t.occurred_at) AS day, c.variety_id, SUM(c.stems) AS stems
FROM sales_line_component c
JOIN sales_line l        ON l.id = c.sales_line_id
JOIN sales_transaction t ON t.id = l.transaction_id
GROUP BY date(t.occurred_at), c.variety_id;

CREATE VIEW IF NOT EXISTS hardgoods_used_daily AS
SELECT date(t.occurred_at) AS day, h.code AS hardgood, SUM(l.quantity * r.qty_per_sale) AS qty
FROM sales_line l
JOIN sales_transaction t ON t.id = l.transaction_id
JOIN product p           ON p.id = l.product_id
JOIN hardgood_rule r     ON r.product_type = p.product_type
JOIN hardgood h          ON h.id = r.hardgood_id
GROUP BY date(t.occurred_at), h.code;
