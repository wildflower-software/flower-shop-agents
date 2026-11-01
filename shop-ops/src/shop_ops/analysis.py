"""Derived estimates: busiest days, on-hand inventory, waste, cooler capacity.

None of these numbers are supplied by the shop today; they are inferred from sales and
purchase history and are marked data_source='estimate'.
"""

from __future__ import annotations

import csv
import math
import random
import sqlite3
import statistics
from collections import defaultdict, deque
from datetime import date, timedelta

from .calendar import WEEKDAYS, event_days, parse_weekdays
from .db import CONFIG_DIR, get_setting

# SQLite strftime('%w') is 0=Sunday; Python weekday() is 0=Monday.
SQLITE_TO_PY = {0: 6, 1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5}


# ------------------------------------------------------------------ busiest days
def check_busiest_days(conn: sqlite3.Connection, include_synthetic: bool = False,
                       min_weeks: int = 26, permutations: int = 5000) -> dict:
    """Test the owner's presumption (default Fri/Sat) against daily revenue.

    Holiday/event windows are excluded so Valentine's week doesn't decide the answer.
    The assumption is only marked 'supported' when the data is real.
    """
    presumed = parse_weekdays(get_setting(conn, "presumed_busiest_days", "FRI|SAT"))
    sources = ("real", "synthetic") if include_synthetic else ("real",)
    rows = conn.execute(
        f"""SELECT day, weekday, revenue, data_source_min, data_source_max FROM daily_sales
            WHERE data_source_min IN ({','.join('?' * len(sources))})
              AND data_source_max IN ({','.join('?' * len(sources))})""",
        sources + sources).fetchall()
    name = "Busiest days are " + "/".join(WEEKDAYS[d] for d in sorted(presumed))

    if not rows:
        return _record(conn, name, "insufficient_data", "No sales data loaded yet.", "real")

    basis = {r[3] for r in rows} | {r[4] for r in rows}
    basis = "real" if basis == {"real"} else "synthetic" if basis == {"synthetic"} else "mixed"
    days = [(date.fromisoformat(d), SQLITE_TO_PY[w], rev) for d, w, rev, _, _ in rows]
    holidays = event_days(conn, min(d for d, _, _ in days), max(d for d, _, _ in days))
    days = [x for x in days if x[0] not in holidays]

    by_wd: dict[int, list[float]] = defaultdict(list)
    for _, wd, rev in days:
        by_wd[wd].append(rev)
    means = {wd: statistics.mean(v) for wd, v in by_wd.items()}
    ranking = sorted(means, key=means.get, reverse=True)
    top = set(ranking[:len(presumed)])

    weeks = len(days) / max(1, len(by_wd))
    if weeks < min_weeks:
        return _record(conn, name, "insufficient_data",
                       f"Only ~{weeks:.0f} weeks of non-holiday sales; need {min_weeks}.", basis)

    p = _permutation_p(days, presumed, permutations)
    mean_line = ", ".join(f"{WEEKDAYS[wd]} ${means[wd]:,.0f}" for wd in ranking)
    evidence = (f"Avg non-holiday daily revenue: {mean_line}. "
                f"Presumed days rank top-{len(presumed)}: {top == presumed}. "
                f"Permutation p-value (presumed days higher than the rest): {p:.4f}.")
    holds = top == presumed and p < 0.05
    if basis != "real":
        status = "presumed"
        evidence = (f"[{basis.upper()} DATA - not evidence; status stays 'presumed'] "
                    f"Would be {'supported' if holds else 'not supported'}. " + evidence)
    else:
        status = "supported" if holds else "not_supported"
    return _record(conn, name, status, evidence, basis)


def _permutation_p(days, presumed: set[int], n: int) -> float:
    revenue = [r for _, _, r in days]
    in_group = [wd in presumed for _, wd, _ in days]

    def diff(flags):
        a = [r for r, f in zip(revenue, flags) if f]
        b = [r for r, f in zip(revenue, flags) if not f]
        return statistics.mean(a) - statistics.mean(b)

    observed = diff(in_group)
    rng = random.Random(0)
    shuffled = in_group[:]
    hits = 0
    for _ in range(n):
        rng.shuffle(shuffled)
        hits += diff(shuffled) >= observed
    return (hits + 1) / (n + 1)


def _record(conn, name, status, evidence, basis) -> dict:
    conn.execute("INSERT INTO assumption_check(name, status, evidence, data_basis) VALUES (?,?,?,?)",
                 (name, status, evidence, basis))
    conn.commit()
    return {"name": name, "status": status, "evidence": evidence, "data_basis": basis}


# ------------------------------------------------------------------ inventory simulation
def simulate_inventory(conn: sqlite3.Connection) -> dict[int, dict]:
    """Replay purchases and sales day by day with FIFO lots.

    A lot is discarded once it is older than its shelf life
    (vase life minus the days the customer should still get at home).
    Physical counts in inventory_count reset the simulated on-hand on that day.
    """
    min_customer = int(get_setting(conn, "min_customer_vase_days", "4"))
    shelf = {vid: max(1, life - min_customer) for vid, life in conn.execute(
        "SELECT id, vase_life_days FROM variety_effective")}
    received = defaultdict(lambda: defaultdict(int))
    for d, vid, stems in conn.execute(
            """SELECT po.delivery_date, sp.variety_id, SUM(pl.stems)
               FROM purchase_line pl JOIN purchase_order po ON po.id = pl.order_id
               JOIN supplier_product sp ON sp.id = pl.supplier_product_id
               GROUP BY po.delivery_date, sp.variety_id"""):
        received[date.fromisoformat(d)][vid] = stems
    used = defaultdict(lambda: defaultdict(int))
    for d, vid, stems in conn.execute("SELECT day, variety_id, stems FROM stems_used_daily"):
        used[date.fromisoformat(d)][vid] = stems
    counts = defaultdict(dict)
    for ts, vid, stems in conn.execute("SELECT counted_at, variety_id, stems FROM inventory_count"):
        counts[date.fromisoformat(ts[:10])][vid] = stems

    all_days = set(received) | set(used)
    if not all_days:
        return {}
    first, last = min(all_days), max(all_days)

    lots = {vid: deque() for vid in shelf}           # (received_on, stems)
    totals = {vid: defaultdict(int) for vid in shelf}
    rows = []
    day = first
    while day <= last:
        for vid in shelf:
            q = lots[vid]
            got = received[day].get(vid, 0)
            if got:
                q.append([day, got])
            if vid in counts[day]:
                q.clear()
                q.append([day, counts[day][vid]])
            peak = sum(s for _, s in q)
            want = used[day].get(vid, 0)
            take = want
            while take and q:
                n = min(take, q[0][1])
                q[0][1] -= n
                take -= n
                if q[0][1] == 0:
                    q.popleft()
            thrown = 0
            while q and (day - q[0][0]).days >= shelf[vid]:
                thrown += q.popleft()[1]
            on_hand = sum(s for _, s in q)
            t = totals[vid]
            t["received"] += got
            t["used"] += want - take
            t["short"] += take
            t["discarded"] += thrown
            t["peak"] = max(t["peak"], peak)
            rows.append((day.isoformat(), vid, on_hand, got, want - take, thrown))
        day += timedelta(days=1)

    conn.execute("DELETE FROM inventory_estimate")
    conn.executemany("INSERT INTO inventory_estimate VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    return {vid: dict(t) for vid, t in totals.items()}


def estimate(conn: sqlite3.Connection, write_defaults: bool = False) -> dict:
    """Waste rate, suggested on-hand targets and cooler capacity from the simulation."""
    totals = simulate_inventory(conn)
    if not totals:
        return {}
    delivery_days = parse_weekdays(get_setting(conn, "delivery_weekdays", "MON|WED|FRI"))
    days_between = 7 / max(1, len(delivery_days))
    n_days = conn.execute("SELECT COUNT(DISTINCT day) FROM inventory_estimate").fetchone()[0]

    varieties = {}
    for vid, code, name, target in conn.execute(
            "SELECT id, code, name, target_on_hand FROM variety_effective"):
        t = totals.get(vid, {})
        recv = t.get("received", 0)
        avg_daily_use = t.get("used", 0) / max(1, n_days)
        varieties[code] = {
            "name": name,
            "waste_rate": (t.get("discarded", 0) / recv) if recv else None,
            "short_stems": t.get("short", 0),
            "current_target_on_hand": target,
            "suggested_target_on_hand": math.ceil(avg_daily_use * days_between * 1.1),
        }

    peak_total = conn.execute(
        """SELECT MAX(total) FROM (
             SELECT day, SUM(on_hand + used + discarded) AS total
             FROM inventory_estimate GROUP BY day)""").fetchone()[0] or 0
    capacity = int(math.ceil(peak_total / 100.0) * 100)
    row = conn.execute("SELECT data_source FROM setting WHERE key='cooler_capacity_stems'").fetchone()
    if row is None or row[0] != "owner":
        conn.execute(
            """INSERT INTO setting(key, value, data_source, note) VALUES ('cooler_capacity_stems',?,
                 'estimate','Peak simulated stems in the cooler, rounded up to 100')
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, data_source='estimate',
                 note=excluded.note""", (str(capacity),))
    if write_defaults:
        _write_default_targets({c: v["suggested_target_on_hand"] for c, v in varieties.items()})
        for code, v in varieties.items():
            conn.execute("UPDATE variety SET default_target_on_hand=? WHERE code=?",
                         (v["suggested_target_on_hand"], code))
    conn.commit()
    return {"varieties": varieties, "cooler_capacity_estimate": capacity}


def _write_default_targets(targets: dict[str, int], path=CONFIG_DIR / "varieties.csv") -> None:
    """Update only the default_target_on_hand column; owner_* columns are never touched."""
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields, rows = reader.fieldnames, list(reader)
    for r in rows:
        if r["code"] in targets:
            r["default_target_on_hand"] = str(targets[r["code"]])
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
