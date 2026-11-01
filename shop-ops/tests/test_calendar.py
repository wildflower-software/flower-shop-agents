from datetime import date

from shop_ops.calendar import event_lift_on, in_window, resolve_rule


def test_holiday_rules_2026():
    assert resolve_rule("fixed:02-14", 2026) == date(2026, 2, 14)
    assert resolve_rule("nth:5:2:SUN", 2026) == date(2026, 5, 10)    # Mother's Day
    assert resolve_rule("nth:11:4:THU", 2026) == date(2026, 11, 26)  # Thanksgiving
    assert resolve_rule("nth:5:-1:MON", 2026) == date(2026, 5, 25)   # Memorial Day
    assert resolve_rule("easter:+0", 2026) == date(2026, 4, 5)
    assert resolve_rule("easter:+0", 2027) == date(2027, 3, 28)
    assert resolve_rule("admin_professionals", 2026) == date(2026, 4, 22)


def test_season_window_wraps_year_end():
    assert in_window(date(2026, 1, 15), "11-01", "03-31")
    assert not in_window(date(2026, 6, 15), "11-01", "03-31")
    assert in_window(date(2026, 8, 1), "07-01", "09-15")


def test_event_lift_ramps_up_to_the_day():
    day = date(2026, 2, 14)
    assert event_lift_on(day, day, 6.0, 3, 0) == 6.0
    assert 1.0 < event_lift_on(date(2026, 2, 12), day, 6.0, 3, 0) < 6.0
    assert event_lift_on(date(2026, 2, 15), day, 6.0, 3, 0) == 1.0
