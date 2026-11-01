"""Load the owner-editable CSVs in config/ into the database.

Safe to re-run after the owner edits a CSV: catalog rows are upserted by their code/sku
so sales and purchase history keep pointing at the same ids.
"""

from __future__ import annotations

import csv
import sqlite3
from datetime import date
from pathlib import Path

from .calendar import resolve_rule
from .db import CONFIG_DIR, id_map


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [{k: (v.strip() if v else "") for k, v in row.items()} for row in csv.DictReader(f)]


def _blank_to_none(value: str):
    return value if value != "" else None


def load_config(conn: sqlite3.Connection, config_dir: Path = CONFIG_DIR) -> None:
    rows = lambda name: read_csv(config_dir / name)  # noqa: E731

    for r in rows("settings.csv"):
        conn.execute(
            """INSERT INTO setting(key, value, data_source, note) VALUES (?,?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                 data_source=excluded.data_source, note=excluded.note""",
            (r["key"], r["value"], r["data_source"], r["note"]),
        )

    for r in rows("varieties.csv"):
        conn.execute(
            """INSERT INTO variety(code, name, category, unit, default_vase_life_days,
                 owner_vase_life_days, default_target_on_hand, owner_target_on_hand, notes)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(code) DO UPDATE SET name=excluded.name, category=excluded.category,
                 unit=excluded.unit, default_vase_life_days=excluded.default_vase_life_days,
                 owner_vase_life_days=excluded.owner_vase_life_days,
                 default_target_on_hand=excluded.default_target_on_hand,
                 owner_target_on_hand=excluded.owner_target_on_hand, notes=excluded.notes""",
            (r["code"], r["name"], r["category"], r["unit"], int(r["default_vase_life_days"]),
             _blank_to_none(r["owner_vase_life_days"]), int(r["default_target_on_hand"]),
             _blank_to_none(r["owner_target_on_hand"]), r["notes"]),
        )
    variety = id_map(conn, "variety")

    conn.execute("DELETE FROM season_window")
    for r in rows("seasonality.csv"):
        conn.execute(
            """INSERT INTO season_window(variety_id, source, default_best_start, default_best_end,
                 owner_best_start, owner_best_end, available_off_season, in_season_price_factor,
                 off_season_price_factor, quality_note, research_basis)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (variety[r["variety"]], r["source"], r["default_best_start"], r["default_best_end"],
             _blank_to_none(r["owner_best_start"]), _blank_to_none(r["owner_best_end"]),
             int(r["available_off_season"]), float(r["in_season_price_factor"]),
             float(r["off_season_price_factor"]), r["quality_note"], r["research_basis"]),
        )

    _load_calendar(conn, rows("holidays.csv"), rows("owner_events.csv"))

    for r in rows("suppliers.csv"):
        conn.execute(
            """INSERT INTO supplier(code, name, kind, lead_time_days, holiday_lead_time_days,
                 delivery_weekdays, freight_flat_per_delivery, freight_per_pack, min_order_dollars,
                 data_source) VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(code) DO UPDATE SET name=excluded.name, kind=excluded.kind,
                 lead_time_days=excluded.lead_time_days,
                 holiday_lead_time_days=excluded.holiday_lead_time_days,
                 delivery_weekdays=excluded.delivery_weekdays,
                 freight_flat_per_delivery=excluded.freight_flat_per_delivery,
                 freight_per_pack=excluded.freight_per_pack,
                 min_order_dollars=excluded.min_order_dollars, data_source=excluded.data_source""",
            (r["code"], r["name"], r["kind"], int(r["lead_time_days"]),
             int(r["holiday_lead_time_days"]), r["delivery_weekdays"],
             float(r["freight_flat_per_delivery"]), float(r["freight_per_pack"]),
             float(r["min_order_dollars"]), r["data_source"]),
        )
    supplier = id_map(conn, "supplier")

    for r in rows("supplier_products.csv"):
        conn.execute(
            """INSERT INTO supplier_product(supplier_id, variety_id, origin, pack_unit,
                 stems_per_pack, min_packs, base_price_per_stem, data_source)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(supplier_id, variety_id, origin) DO UPDATE SET
                 pack_unit=excluded.pack_unit, stems_per_pack=excluded.stems_per_pack,
                 min_packs=excluded.min_packs, base_price_per_stem=excluded.base_price_per_stem,
                 data_source=excluded.data_source""",
            (supplier[r["supplier"]], variety[r["variety"]], r["origin"], r["pack_unit"],
             int(r["stems_per_pack"]), int(r["min_packs"]), float(r["base_price_per_stem"]),
             r["data_source"]),
        )

    for r in rows("products.csv"):
        conn.execute(
            """INSERT INTO product(sku, name, product_type, variety_id, stems_per_unit, list_price, active)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(sku) DO UPDATE SET name=excluded.name,
                 product_type=excluded.product_type, variety_id=excluded.variety_id,
                 stems_per_unit=excluded.stems_per_unit, list_price=excluded.list_price,
                 active=excluded.active""",
            (r["sku"], r["name"], r["product_type"],
             variety[r["variety"]] if r["variety"] else None,
             _blank_to_none(r["stems_per_unit"]), _blank_to_none(r["list_price"]), int(r["active"])),
        )
    product = id_map(conn, "product", "sku")

    conn.execute("DELETE FROM recipe_slot")
    for r in rows("recipes.csv"):
        conn.execute("INSERT INTO recipe_slot(product_id, role, qty) VALUES (?,?,?)",
                     (product[r["sku"]], r["role"], int(r["qty"])))

    conn.execute("DELETE FROM substitution_option")
    for r in rows("substitutions.csv"):
        conn.execute(
            "INSERT INTO substitution_option(role, variety_id, preference_rank, active) VALUES (?,?,?,?)",
            (r["role"], variety[r["variety"]], int(r["preference_rank"]), int(r["active"])),
        )

    for r in rows("hardgoods.csv"):
        conn.execute(
            """INSERT INTO hardgood(code, name, unit_cost, data_source) VALUES (?,?,?,?)
               ON CONFLICT(code) DO UPDATE SET name=excluded.name, unit_cost=excluded.unit_cost,
                 data_source=excluded.data_source""",
            (r["code"], r["name"], float(r["unit_cost"]), r["data_source"]),
        )
    hardgood = id_map(conn, "hardgood")
    conn.execute("DELETE FROM hardgood_rule")
    for r in rows("hardgood_rules.csv"):
        conn.execute(
            "INSERT INTO hardgood_rule(hardgood_id, product_type, qty_per_sale) VALUES (?,?,?)",
            (hardgood[r["hardgood"]], r["product_type"], float(r["qty_per_sale"])),
        )

    for r in rows("competitors.csv"):
        conn.execute(
            """INSERT INTO competitor(name, kind, neighborhood, notes) VALUES (?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET kind=excluded.kind,
                 neighborhood=excluded.neighborhood, notes=excluded.notes""",
            (r["name"], r["kind"], r["neighborhood"], r["notes"]),
        )
    competitor = id_map(conn, "competitor", "name")
    conn.execute("DELETE FROM competitor_observation")
    for r in rows("competitor_observations.csv"):
        conn.execute(
            """INSERT INTO competitor_observation(competitor_id, observed_on, item_desc, price,
                 stem_count, varieties, notes) VALUES (?,?,?,?,?,?,?)""",
            (competitor[r["competitor"]], r["observed_on"], r["item_desc"], float(r["price"]),
             _blank_to_none(r["stem_count"]), r["varieties"], r["notes"]),
        )

    conn.commit()


def _load_calendar(conn, holidays, owner_events, first_year: int | None = None,
                   last_year: int | None = None) -> None:
    this_year = date.today().year
    first_year = first_year or this_year - 6
    last_year = last_year or this_year + 2

    conn.execute("DELETE FROM event_occurrence")
    conn.execute("DELETE FROM calendar_event")
    for r in holidays:
        cur = conn.execute(
            """INSERT INTO calendar_event(name, kind, rule, demand_lift, window_before_days,
                 window_after_days, order_lead_weeks, focus_varieties, active, notes)
               VALUES (?,'holiday',?,?,?,?,?,?,?,?)""",
            (r["name"], r["rule"], float(r["demand_lift"]), int(r["window_before_days"]),
             int(r["window_after_days"]), int(r["order_lead_weeks"]), r["focus_varieties"],
             int(r["active"]), r["notes"]),
        )
        for year in range(first_year, last_year + 1):
            conn.execute("INSERT INTO event_occurrence VALUES (?,?)",
                         (cur.lastrowid, resolve_rule(r["rule"], year).isoformat()))
    for r in owner_events:
        cur = conn.execute(
            """INSERT INTO calendar_event(name, kind, event_date, demand_lift, window_before_days,
                 window_after_days, order_lead_weeks, focus_varieties, active, notes)
               VALUES (?,'owner_event',?,?,?,?,?,?,?,?)""",
            (r["name"], r["event_date"], float(r["demand_lift"]), int(r["window_before_days"]),
             int(r["window_after_days"]), int(r["order_lead_weeks"]), r["focus_varieties"],
             int(r["active"]), r["notes"]),
        )
        conn.execute("INSERT INTO event_occurrence VALUES (?,?)", (cur.lastrowid, r["event_date"]))
