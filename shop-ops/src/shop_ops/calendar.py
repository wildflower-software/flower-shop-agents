"""Holiday rules, season windows, and per-day demand lift.

Holiday rule syntax (config/holidays.csv `rule` column):
    fixed:MM-DD            same date every year            fixed:02-14
    nth:M:N:DOW            Nth weekday of month M          nth:5:2:SUN  (Mother's Day)
                           N = -1 means the last one       nth:5:-1:MON (Memorial Day)
    easter:+D              Western Easter plus D days      easter:-2    (Good Friday)
    admin_professionals    Wednesday of the last full week of April
"""

from __future__ import annotations

from datetime import date, timedelta

WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def weekday_index(code: str) -> int:
    return WEEKDAYS.index(code.upper())


def parse_weekdays(spec: str) -> set[int]:
    """'MON|WED|FRI' -> {0, 2, 4} (Python weekday numbers)."""
    return {weekday_index(d) for d in spec.split("|") if d}


def easter(year: int) -> date:
    """Anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def nth_weekday(year: int, month: int, n: int, dow: int) -> date:
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(dow - first.weekday()) % 7 + 7 * (n - 1))
    nxt = date(year + month // 12, month % 12 + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - dow) % 7 + 7 * (-n - 1))


def resolve_rule(rule: str, year: int) -> date:
    kind, _, arg = rule.partition(":")
    if kind == "fixed":
        month, day = arg.split("-")
        return date(year, int(month), int(day))
    if kind == "nth":
        month, n, dow = arg.split(":")
        return nth_weekday(year, int(month), int(n), weekday_index(dow))
    if kind == "easter":
        return easter(year) + timedelta(days=int(arg or 0))
    if kind == "admin_professionals":
        # Last full Sun-Sat week of April ends on April's last Saturday.
        return nth_weekday(year, 4, -1, weekday_index("SAT")) - timedelta(days=3)
    raise ValueError(f"Unknown holiday rule: {rule!r}")


def in_window(day: date, start_mmdd: str, end_mmdd: str) -> bool:
    """True if day falls in an MM-DD window; windows may wrap the year end."""
    key = day.strftime("%m-%d")
    if start_mmdd <= end_mmdd:
        return start_mmdd <= key <= end_mmdd
    return key >= start_mmdd or key <= end_mmdd


def event_lift_on(day: date, event_day: date, lift: float, before: int, after: int) -> float:
    """Demand multiplier an event contributes to `day`.

    Ramps up linearly over the `before` window, full lift on the day and through `after`.
    """
    delta = (day - event_day).days
    if 0 <= delta <= after:
        return lift
    if -before <= delta < 0:
        share = (before + 1 + delta) / (before + 1)
        return 1 + (lift - 1) * share
    return 1.0


def demand_lift(conn, day: date) -> float:
    """Largest lift from any active event touching `day` (events don't stack)."""
    rows = conn.execute(
        """SELECT o.event_date, e.demand_lift, e.window_before_days, e.window_after_days
           FROM event_occurrence o JOIN calendar_event e ON e.id = o.event_id
           WHERE e.active = 1
             AND o.event_date BETWEEN date(?, '-40 days') AND date(?, '+40 days')""",
        (day.isoformat(), day.isoformat()),
    ).fetchall()
    best = 1.0
    for ev_date, lift, before, after in rows:
        best = max(best, event_lift_on(day, date.fromisoformat(ev_date), lift, before, after))
    return best


def event_days(conn, start: date, end: date) -> set[date]:
    """Every date inside any active event window between start and end."""
    rows = conn.execute(
        """SELECT o.event_date, e.window_before_days, e.window_after_days
           FROM event_occurrence o JOIN calendar_event e ON e.id = o.event_id
           WHERE e.active = 1"""
    ).fetchall()
    days: set[date] = set()
    for ev_date, before, after in rows:
        d0 = date.fromisoformat(ev_date)
        for k in range(-before, after + 1):
            d = d0 + timedelta(days=k)
            if start <= d <= end:
                days.add(d)
    return days
