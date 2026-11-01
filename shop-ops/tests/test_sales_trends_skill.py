"""The interpreting-sales-trends skill: valid Agent Skill, and its script finds the right days."""

import importlib.util
import re
from datetime import date
from pathlib import Path

from shop_ops import synthetic

SKILL = Path(__file__).resolve().parents[1] / "skills" / "interpreting-sales-trends"
spec = importlib.util.spec_from_file_location("sales_trends", SKILL / "scripts" / "sales_trends.py")
sales_trends = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sales_trends)


def test_skill_front_matter_follows_the_spec():
    text = (SKILL / "SKILL.md").read_text()
    front = re.match(r"^---\n(.*?)\n---\n", text, re.S).group(1)
    name = re.search(r"^name: (.+)$", front, re.M).group(1)
    description = re.search(r"^description: (.+)$", front, re.M).group(1)
    assert name == SKILL.name and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) and len(name) <= 64
    assert 0 < len(description) <= 1024
    assert len(text.splitlines()) < 500


def test_valentines_week_is_flagged_and_explained(conn):
    synthetic.generate(conn, years=1, seed=1, end=date(2026, 2, 28))
    result = sales_trends.sales_trends(conn, as_of=date(2026, 2, 20), weeks=4)
    assert result["data_basis"] == "synthetic"
    feb_13 = next(o for o in result["outliers"] if o["day"] == "2026-02-13")
    assert feb_13["direction"] == "high"
    assert any("Valentine" in c for c in feb_13["calendar"])


def test_a_missing_day_is_reported_as_no_sales(conn):
    synthetic.generate(conn, years=1, seed=1, end=date(2026, 9, 30))
    conn.execute("DELETE FROM sales_transaction WHERE date(occurred_at) = '2026-09-26'")  # a Saturday
    result = sales_trends.sales_trends(conn, as_of=date(2026, 9, 30), weeks=4)
    missing = next(o for o in result["outliers"] if o["day"] == "2026-09-26")
    assert missing["no_sales_recorded"] and missing["direction"] == "low"


def test_periods_line_up_on_weekdays(conn):
    synthetic.generate(conn, years=2, seed=1, end=date(2026, 9, 30))
    result = sales_trends.sales_trends(conn, as_of=date(2026, 9, 30), weeks=4)
    now = date.fromisoformat(result["period"]["start"])
    year_ago = date.fromisoformat(result["same_weeks_last_year"]["start"])
    assert now.weekday() == year_ago.weekday()
