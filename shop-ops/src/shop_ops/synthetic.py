"""Generate realistic placeholder history: weekly supplier prices, sales, and purchases.

Every row written here is tagged data_source='synthetic'. `purge_synthetic` removes it
once real POS exports and invoices are loaded.

Shape assumptions (all tunable below, all to be replaced by real data):
  * ~28 transactions on an average day, growing ~4%/year
  * month seasonality peaking in May and December, dipping in Jan/Aug
  * Fri/Sat busier - the *presumption* the owner wants tested, baked in only so the
    checker has something to find; it is not evidence
  * holiday lifts come from calendar_event (Valentine's x6, Mother's Day x4, ...)
"""

from __future__ import annotations

import math
import random
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .calendar import demand_lift, in_window, parse_weekdays
from .db import get_setting, id_map

BASE_TXNS_PER_DAY = 28
ANNUAL_GROWTH = 0.04
MONTH_FACTOR = {1: .80, 2: 1.05, 3: 1.00, 4: 1.10, 5: 1.25, 6: 1.10,
                7: .90, 8: .85, 9: .95, 10: 1.00, 11: 1.00, 12: 1.15}
WEEKDAY_FACTOR = {0: .75, 1: .80, 2: .90, 3: 1.00, 4: 1.35, 5: 1.45, 6: .90}
PRODUCT_MIX = {"TWENTIES": .28, "FIFTEENS": .27, "ARRANGEMENT": .08,
               "STEM_ROSE": .06, "STEM_ALSTRO": .03, "STEM_SPIDER": .025, "STEM_POMPON": .02,
               "STEM_HYDRANGEA": .03, "STEM_SOLIDAGO": .015,
               "BUNDLE_ROSE12": .07, "BUNDLE_ALSTRO10": .04, "BUNDLE_POMPON10": .03,
               "BUNDLE_HYDRANGEA3": .03}
CHANNELS = {"walk_in": .80, "phone": .12, "online": .08}


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def pick(rng: random.Random, weights: dict):
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]


@dataclass
class Offer:
    sp_id: int
    supplier_id: int
    variety_id: int
    origin: str
    stems_per_pack: int
    min_packs: int
    base_price: float


def generate(conn: sqlite3.Connection, years: int = 4, seed: int = 7,
             end: date | None = None) -> dict[str, int]:
    rng = random.Random(seed)
    end = end or date.today() - timedelta(days=1)
    start = end - timedelta(days=int(365.25 * years))

    variety = id_map(conn, "variety")
    product = id_map(conn, "product", "sku")
    lifts = {start + timedelta(days=i): demand_lift(conn, start + timedelta(days=i))
             for i in range((end - start).days + 1)}
    focus = _focus_days(conn, start, end)

    prices = _generate_prices(conn, rng, start, end, focus)
    usage = _generate_sales(conn, rng, start, end, lifts, focus, prices, variety, product)
    n_po = _generate_purchases(conn, rng, start, end, usage, prices, lifts)
    conn.commit()
    return {
        "days": (end - start).days + 1,
        "transactions": conn.execute(
            "SELECT COUNT(*) FROM sales_transaction WHERE data_source='synthetic'").fetchone()[0],
        "purchase_orders": n_po,
        "price_rows": sum(len(v) for v in prices.values()),
    }


# ------------------------------------------------------------------ prices
def _offers(conn) -> list[Offer]:
    return [Offer(*r) for r in conn.execute(
        """SELECT id, supplier_id, variety_id, origin, stems_per_pack, min_packs, base_price_per_stem
           FROM supplier_product""")]


def _focus_days(conn, start: date, end: date) -> dict[date, tuple[set[str], float]]:
    """Days inside a holiday window -> (focus variety codes, lift)."""
    out: dict[date, tuple[set[str], float]] = {}
    for ev_date, before, after, lift, fv in conn.execute(
        """SELECT o.event_date, e.window_before_days, e.window_after_days, e.demand_lift,
                  COALESCE(e.focus_varieties,'')
           FROM event_occurrence o JOIN calendar_event e ON e.id = o.event_id WHERE e.active = 1"""):
        d0 = date.fromisoformat(ev_date)
        for k in range(-before - 7, after + 1):   # wholesale prices move the week before too
            d = d0 + timedelta(days=k)
            if start <= d <= end and fv:
                codes, cur = out.get(d, (set(), 1.0))
                out[d] = (codes | set(fv.split("|")), max(cur, lift))
    return out


def _generate_prices(conn, rng, start, end, focus) -> dict[date, dict[int, tuple]]:
    """week_start -> {supplier_product_id: (price, availability, quality)}."""
    windows = {(v, s): (bs, be, off, fin, fout) for v, s, bs, be, off, fin, fout in conn.execute(
        """SELECT variety_id, source, best_start, best_end, available_off_season,
                  in_season_price_factor, off_season_price_factor FROM season_window_effective""")}
    codes = {i: c for c, i in id_map(conn, "variety").items()}
    out: dict[date, dict[int, tuple]] = {}
    rows = []
    week = monday(start)
    while week <= end:
        mid = week + timedelta(days=3)
        out[week] = {}
        for o in _offers(conn):
            w = windows.get((o.variety_id, o.origin))
            in_season = w is None or in_window(mid, w[0], w[1])
            factor = 1.0 if w is None else (w[3] if in_season else w[4])
            availability, quality = "available", "A"
            if w is not None and not in_season and not w[2]:
                availability = "unavailable"
            elif w is not None and in_season and o.origin == "local" and (
                    not in_window(mid - timedelta(days=14), w[0], w[1])
                    or not in_window(mid + timedelta(days=14), w[0], w[1])):
                availability, quality = "limited", "B"     # season edges
            elif rng.random() < 0.03:
                availability = "limited"
            if rng.random() < 0.05:
                quality = "B"
            hol = 1.0
            for d in (week + timedelta(days=k) for k in range(7)):
                if d in focus and codes[o.variety_id] in focus[d][0]:
                    hol = max(hol, 1 + 0.25 * (focus[d][1] - 1))
            price = round(o.base_price * factor * hol * rng.gauss(1, 0.05), 3)
            out[week][o.sp_id] = (price, availability, quality)
            rows.append((o.sp_id, week.isoformat(), price, availability, quality))
        week += timedelta(days=7)
    conn.executemany(
        """INSERT OR REPLACE INTO supplier_price(supplier_product_id, week_start, price_per_stem,
             availability, quality_grade, data_source) VALUES (?,?,?,?,?,'synthetic')""", rows)
    return out


def _cheapest_by_variety(conn, prices_week: dict[int, tuple]) -> dict[int, float]:
    best: dict[int, float] = {}
    for o in _offers(conn):
        p, avail, _ = prices_week[o.sp_id]
        if avail != "unavailable":
            best[o.variety_id] = min(best.get(o.variety_id, math.inf), p)
    return best


# ------------------------------------------------------------------ sales
def _generate_sales(conn, rng, start, end, lifts, focus, prices, variety, product):
    open_days = parse_weekdays(get_setting(conn, "open_weekdays", "MON|TUE|WED|THU|FRI|SAT|SUN"))
    recipes = defaultdict(dict)
    for sku, role, qty in conn.execute(
            "SELECT p.sku, r.role, r.qty FROM recipe_slot r JOIN product p ON p.id = r.product_id"):
        recipes[sku][role] = qty
    options = defaultdict(list)
    for role, vid, rank in conn.execute(
            "SELECT role, variety_id, preference_rank FROM substitution_option WHERE active = 1"):
        options[role].append((vid, rank))
    prod_info = {sku: (pid, price, vid, spu) for pid, sku, price, vid, spu in conn.execute(
        "SELECT id, sku, list_price, variety_id, stems_per_unit FROM product")}
    rose_codes = {"STEM_ROSE", "BUNDLE_ROSE12"}

    usage: dict[date, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    cheapest_cache: dict[date, dict[int, float]] = {}
    day = start
    while day <= end:
        if day.weekday() not in open_days:
            day += timedelta(days=1)
            continue
        wk = monday(day)
        if wk not in cheapest_cache:
            cheapest_cache[wk] = _cheapest_by_variety(conn, prices[wk])
        cheapest = cheapest_cache[wk]
        years_in = (day - start).days / 365.25
        expected = (BASE_TXNS_PER_DAY * (1 + ANNUAL_GROWTH) ** years_in
                    * MONTH_FACTOR[day.month] * WEEKDAY_FACTOR[day.weekday()] * lifts[day])
        n = max(0, round(rng.gauss(expected, math.sqrt(expected))))
        mix = dict(PRODUCT_MIX)
        if day in focus and "ROSE" in focus[day][0]:
            for sku in rose_codes:
                mix[sku] *= 3

        for _ in range(n):
            ts = datetime.combine(day, datetime.min.time()) + timedelta(
                minutes=rng.randint(10 * 60, 19 * 60))
            txn = conn.execute(
                "INSERT INTO sales_transaction(occurred_at, channel, data_source) VALUES (?,?,'synthetic')",
                (ts.strftime("%Y-%m-%d %H:%M:%S"), pick(rng, CHANNELS))).lastrowid
            for _ in range(1 if rng.random() < .85 else 2):
                sku = pick(rng, mix)
                pid, list_price, vid, spu = prod_info[sku]
                components: dict[int, int] = defaultdict(int)
                how = "recipe_estimate"
                qty = 1
                if sku in recipes:
                    for role, rq in recipes[sku].items():
                        for _ in range(rq):
                            components[_choose_option(rng, options[role], cheapest)] += 1
                    price = list_price
                elif sku == "ARRANGEMENT":
                    price = float(rng.choice(range(45, 155, 5)))
                    stems = max(10, round(price / 3.2))
                    how = "recorded"
                    for role, share in (("statement", .3), ("filler", .3), ("green", .4)):
                        pool = options[role] + ([(variety["HYDRANGEA_STEM"], 2)] if role == "statement" else [])
                        for _ in range(round(stems * share)):
                            components[_choose_option(rng, pool, cheapest)] += 1
                else:
                    qty = rng.choice([1, 1, 1, 2, 3, 6, 12]) if spu == 1 else 1
                    price = list_price
                    components[vid] += spu * qty
                line = conn.execute(
                    """INSERT INTO sales_line(transaction_id, product_id, quantity, unit_price, line_total)
                       VALUES (?,?,?,?,?)""", (txn, pid, qty, price, round(price * qty, 2))).lastrowid
                conn.executemany(
                    "INSERT INTO sales_line_component VALUES (?,?,?,?)",
                    [(line, v, s, how) for v, s in components.items()])
                for v, s in components.items():
                    usage[day][v] += s
        day += timedelta(days=1)
    return usage


def _choose_option(rng, options: list[tuple[int, int]], cheapest: dict[int, float]) -> int:
    """Cheaper and higher-preference stems are used more often; unavailable ones never."""
    weights = {v: 1 / (cheapest[v] ** 2 * math.sqrt(rank)) for v, rank in options if v in cheapest}
    return pick(rng, weights) if weights else options[0][0]


# ------------------------------------------------------------------ purchases
def _generate_purchases(conn, rng, start, end, usage, prices, lifts) -> int:
    offers = _offers(conn)
    suppliers = {sid: (parse_weekdays(days), lead, hlead, flat, per_pack)
                 for sid, days, lead, hlead, flat, per_pack in conn.execute(
                     """SELECT id, delivery_weekdays, lead_time_days, holiday_lead_time_days,
                               freight_flat_per_delivery, freight_per_pack FROM supplier""")}
    shelf = {vid: life for vid, life in conn.execute(
        "SELECT id, vase_life_days FROM variety_effective")}
    delivery_days = parse_weekdays(get_setting(conn, "delivery_weekdays", "MON|WED|FRI"))

    deliveries = [start + timedelta(days=i) for i in range((end - start).days + 1)
                  if (start + timedelta(days=i)).weekday() in delivery_days]
    on_hand: dict[int, float] = defaultdict(float)
    n_po = 0
    for i, d in enumerate(deliveries):
        nxt = deliveries[i + 1] if i + 1 < len(deliveries) else d + timedelta(days=2)
        need: dict[int, int] = defaultdict(int)
        k = d
        while k < nxt:
            for v, s in usage.get(k, {}).items():
                need[v] += s
            k += timedelta(days=1)
        holiday = max(lifts.get(d + timedelta(days=j), 1.0) for j in range(7)) > 1.5
        week_prices = prices[monday(d)]

        lines_by_supplier: dict[int, list] = defaultdict(list)
        for vid, stems_needed in need.items():
            target = stems_needed * rng.uniform(1.05, 1.20) - 0.5 * on_hand[vid]
            if target <= 0:
                continue
            candidates = [o for o in offers if o.variety_id == vid
                          and d.weekday() in suppliers[o.supplier_id][0]
                          and week_prices[o.sp_id][1] != "unavailable"]
            if not candidates:
                continue
            o = min(candidates, key=lambda o: week_prices[o.sp_id][0]
                    + suppliers[o.supplier_id][4] / o.stems_per_pack)
            packs = max(o.min_packs, math.ceil(target / o.stems_per_pack))
            lines_by_supplier[o.supplier_id].append((o, packs))
            on_hand[vid] += packs * o.stems_per_pack

        for sid, lines in lines_by_supplier.items():
            _, lead, hlead, flat, per_pack = suppliers[sid]
            ordered_on = d - timedelta(days=hlead if holiday else lead)
            freight = flat + per_pack * sum(p for _, p in lines)
            po = conn.execute(
                """INSERT INTO purchase_order(supplier_id, ordered_on, delivery_date, freight_cost, data_source)
                   VALUES (?,?,?,?,'synthetic')""",
                (sid, ordered_on.isoformat(), d.isoformat(), round(freight, 2))).lastrowid
            n_po += 1
            for o, packs in lines:
                stems = packs * o.stems_per_pack
                price = week_prices[o.sp_id][0]
                conn.execute(
                    """INSERT INTO purchase_line(order_id, supplier_product_id, packs, stems,
                         price_per_stem, line_cost) VALUES (?,?,?,?,?,?)""",
                    (po, o.sp_id, packs, stems, price, round(stems * price, 2)))

        # Rough carry-over between deliveries: subtract use, age out a share by vase life.
        for vid in list(on_hand):
            on_hand[vid] = max(0.0, on_hand[vid] - need.get(vid, 0)) * (1 - 2 / shelf[vid])
    return n_po


def purge_synthetic(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM sales_transaction WHERE data_source = 'synthetic'")
    conn.execute("DELETE FROM purchase_order WHERE data_source = 'synthetic'")
    conn.execute("DELETE FROM supplier_price WHERE data_source = 'synthetic'")
    conn.execute("DELETE FROM demand_signal WHERE data_source = 'synthetic'")
    conn.execute("DELETE FROM inventory_count WHERE data_source = 'synthetic'")
    conn.execute("DELETE FROM inventory_estimate")
    conn.execute("DELETE FROM assumption_check WHERE data_basis != 'real'")
    conn.commit()
