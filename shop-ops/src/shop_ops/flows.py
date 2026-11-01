"""Prefect flows: scheduled jobs that run the shop's agents.

    uv run shop-ops weekly-note            # run once, now
    uv run python -m shop_ops.flows serve  # stay up and run on the schedule

The weekly sales note only ever writes a draft. Sending texts is a later step, and it
will go through an approval check in code, not through this flow.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

from prefect import flow, get_run_logger, task

from . import weekly_note
from .db import DEFAULT_DB, connect, init_schema

# Monday 7:00 shop time, before the owner's weekly review. Owner-tunable via env.
WEEKLY_NOTE_CRON = os.environ.get("SHOP_OPS_WEEKLY_NOTE_CRON", "0 7 * * 1")
SHOP_TIMEZONE = os.environ.get("SHOP_OPS_TZ", "America/New_York")


def _db() -> Path:
    return weekly_note.db_path_from_env(DEFAULT_DB)


@task(retries=1)
def compute_trends(db: str, weeks: int, as_of: str | None) -> dict:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        day = date.fromisoformat(as_of) if as_of else weekly_note.last_sales_day(conn)
        if day is None:
            raise RuntimeError("No sales in the database yet.")
        return weekly_note.sales_trends(conn, as_of=day, weeks=weeks)
    finally:
        conn.close()


@task(retries=0)  # never retried: a retry after a partial write could save the note twice
def save_draft(db: str, body: str) -> int:
    conn = connect(db)
    try:
        init_schema(conn)
        return weekly_note.save_draft(conn, body)
    finally:
        conn.close()


@flow(name="weekly-sales-note")
def weekly_sales_note(weeks: int = 4, as_of: str | None = None, db: str | None = None,
                      model: str | None = None) -> int:
    """Interpret recent sales and save the owner's note as a draft text. Returns its id."""
    log = get_run_logger()
    db = db or str(_db())
    trends = compute_trends(db, weeks, as_of)
    log.info("Period %s to %s, data basis %s, %d outliers",
             trends["period"]["start"], trends["period"]["end"],
             trends["data_basis"], len(trends["outliers"]))
    note = weekly_note.write_note(trends, weekly_note.build_agent(model, durable=True))
    log.info("Draft note:\n%s", note)
    msg_id = save_draft(db, note)
    log.info("Saved draft text %d. Nothing was sent.", msg_id)
    return msg_id


def serve() -> None:
    weekly_sales_note.serve(name="weekly", cron=WEEKLY_NOTE_CRON, timezone=SHOP_TIMEZONE)


if __name__ == "__main__":
    if sys.argv[1:] == ["serve"]:
        serve()
    else:
        print(weekly_sales_note())
