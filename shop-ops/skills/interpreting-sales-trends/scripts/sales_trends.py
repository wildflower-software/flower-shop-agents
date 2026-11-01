"""Compute the numbers behind a sales-trend note. The model interprets; this file does the math.

    uv run python skills/interpreting-sales-trends/scripts/sales_trends.py [--weeks 4] [--as-of YYYY-MM-DD] [--db PATH]

Prints JSON: totals for this period, the period before and the same weeks last year;
the product mix; and outlier days with any calendar events or demand signals that
might explain them. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from statistics import median

DEFAULT_DB = Path(__file__).resolve().parents[3] / "data" / "shop.db"
BASELINE_WEEKS = 8      # same-weekday history used to judge each day
OUTLIER_Z = 3.5         # modified z-score cut-off (Iglewicz and Hoaglin)
MIN_BASELINE_DAYS = 4


def _days(start: date, end: date) -> list[str]:
    return [(start + timedelta(d)).isoformat() for d in range((end - start).days + 1)]


def _period(conn, start: date, end: date) -> dict:
    row = conn.execute(
        "SELECT COALESCE(SUM(revenue),0), COALESCE(SUM(transactions),0), COUNT(*) "
        "FROM daily_sales WHERE day BETWEEN ? AND ?", (start.isoformat(), end.isoformat())).fetchone()
    revenue, txns, days_with_sales = row
    return {
        "start": start.isoformat(), "end": end.isoformat(),
        "revenue": round(revenue, 2), "transactions": txns, "days_with_sales": days_with_sales,
        "avg_ticket": round(revenue / txns, 2) if txns else None,
    }


def _change(now: float | None, then: float | None) -> float | None:
    if not now or not then:
        return None
    return round(100 * (now - then) / then, 1)


def _mix(conn, start: date, end: date) -> dict[str, dict]:
    rows = conn.execute(
        """SELECT p.product_type, SUM(l.quantity), SUM(l.line_total)
           FROM sales_line l JOIN sales_transaction t ON t.id = l.transaction_id
           JOIN product p ON p.id = l.product_id
           WHERE date(t.occurred_at) BETWEEN ? AND ? GROUP BY p.product_type""",
        (start.isoformat(), end.isoformat())).fetchall()
    total = sum(r[2] for r in rows) or 1
    return {r[0]: {"units": r[1], "revenue": round(r[2], 2), "share_pct": round(100 * r[2] / total, 1)} for r in rows}


def _events_by_day(conn, start: date, end: date) -> dict[str, list[str]]:
    """Each day in range -> names of holidays or owner events whose window covers it."""
    out: dict[str, list[str]] = {}
    rows = conn.execute(
        """SELECT e.name, o.event_date, e.window_before_days, e.window_after_days, e.demand_lift
           FROM event_occurrence o JOIN calendar_event e ON e.id = o.event_id WHERE e.active = 1""").fetchall()
    for name, day, before, after, lift in rows:
        d = date.fromisoformat(day)
        for covered in _days(d - timedelta(before), d + timedelta(after)):
            if start.isoformat() <= covered <= end.isoformat():
                out.setdefault(covered, []).append(f"{name} (expected lift x{lift:g})")
    return out


def _signals_by_day(conn, start: date, end: date) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for day, kind, text in conn.execute(
            "SELECT date(occurred_at), kind, raw_text FROM demand_signal WHERE date(occurred_at) BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat())):
        out.setdefault(day, []).append(f"{kind}: {text}")
    return out


def _outliers(conn, start: date, end: date) -> list[dict]:
    history_start = start - timedelta(weeks=BASELINE_WEEKS)
    revenue = dict(conn.execute(
        "SELECT day, revenue FROM daily_sales WHERE day BETWEEN ? AND ?",
        (history_start.isoformat(), end.isoformat())).fetchall())
    events = _events_by_day(conn, history_start, end)
    signals = _signals_by_day(conn, start, end)

    found = []
    for day in _days(start, end):
        d = date.fromisoformat(day)
        # Same weekday, previous BASELINE_WEEKS weeks, skipping event days so a holiday
        # doesn't make a normal day look slow.
        base = [revenue.get((d - timedelta(weeks=w)).isoformat(), 0.0) for w in range(1, BASELINE_WEEKS + 1)
                if (d - timedelta(weeks=w)).isoformat() not in events]
        if len(base) < MIN_BASELINE_DAYS:
            continue
        actual = revenue.get(day, 0.0)
        med = median(base)
        mad = median(abs(x - med) for x in base)
        if mad:
            z = 0.6745 * (actual - med) / mad
            flagged = abs(z) >= OUTLIER_Z
        else:  # a perfectly steady history: flag anything 50% away from it
            z, flagged = None, med and abs(actual - med) / med >= 0.5
        if not flagged:
            continue
        found.append({
            "day": day, "weekday": d.strftime("%A"),
            "revenue": round(actual, 2), "usual_for_weekday": round(med, 2),
            "pct_vs_usual": _change(actual, med) if med else None,
            "times_usual": round(actual / med, 1) if med else None,
            "direction": "high" if actual > med else "low",
            "modified_z": round(z, 1) if z is not None else None,
            "calendar": events.get(day, []),
            "demand_signals": signals.get(day, []),
            "no_sales_recorded": day not in revenue,
        })
    return found


def _data_basis(conn, start: date, end: date) -> str:
    kinds = {r[0] for r in conn.execute(
        "SELECT DISTINCT data_source FROM sales_transaction WHERE date(occurred_at) BETWEEN ? AND ?",
        (start.isoformat(), end.isoformat()))}
    if not kinds:
        return "none"
    return kinds.pop() if len(kinds) == 1 else "mixed"


def sales_trends(conn: sqlite3.Connection, as_of: date, weeks: int = 4) -> dict:
    end = as_of
    start = end - timedelta(weeks=weeks) + timedelta(1)
    prior = (start - timedelta(weeks=weeks), start - timedelta(1))
    last_year = (start - timedelta(weeks=52), end - timedelta(weeks=52))  # 364 days keeps weekdays aligned

    now, before, year_ago = _period(conn, start, end), _period(conn, *prior), _period(conn, *last_year)
    return {
        "data_basis": _data_basis(conn, start, end),
        "period": now,
        "prior_period": before,
        "same_weeks_last_year": year_ago,
        "change_pct": {
            "revenue_vs_prior": _change(now["revenue"], before["revenue"]),
            "revenue_vs_last_year": _change(now["revenue"], year_ago["revenue"]),
            "transactions_vs_prior": _change(now["transactions"], before["transactions"]),
            "avg_ticket_vs_prior": _change(now["avg_ticket"], before["avg_ticket"]),
        },
        "mix": _mix(conn, start, end),
        "mix_prior": _mix(conn, *prior),
        "calendar_in_period": _events_by_day(conn, start, end),
        "outliers": _outliers(conn, start, end),
        "method": {"baseline_weeks": BASELINE_WEEKS, "outlier_modified_z": OUTLIER_Z},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--weeks", type=int, default=4)
    parser.add_argument("--as-of", help="Last day of the period (default: last day with sales)")
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    as_of = args.as_of or conn.execute("SELECT MAX(day) FROM daily_sales").fetchone()[0]
    if not as_of:
        raise SystemExit("No sales in the database yet.")
    print(json.dumps(sales_trends(conn, date.fromisoformat(as_of), args.weeks), indent=2))


if __name__ == "__main__":
    main()
