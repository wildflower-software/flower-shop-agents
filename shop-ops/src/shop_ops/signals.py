"""Import stockouts / turned-away requests that the POS never sees.

Staff (or a future SMS intake) append rows to inbox/demand_signals.csv:

    occurred_at,kind,raw_text,variety,product,quantity,note
    2026-10-10 14:05,turned_away,"wanted 2 dozen white roses",ROSE,,24,

`variety` / `product` accept a code (ROSE), a SKU (BUNDLE_ROSE12) or the full name, and may
be blank - raw_text is always kept so nothing is lost when matching fails.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from .config import read_csv
from .db import PROJECT_ROOT

INBOX = PROJECT_ROOT / "inbox" / "demand_signals.csv"
KINDS = {"stockout", "turned_away", "special_request"}


def _lookup(conn, table: str, key: str, value: str) -> int | None:
    if not value:
        return None
    row = conn.execute(f"SELECT id FROM {table} WHERE upper({key}) = upper(?) OR lower(name) = lower(?)",
                       (value, value)).fetchone()
    return row[0] if row else None


def import_signals(conn: sqlite3.Connection, path: Path = INBOX, source: str = "csv") -> dict:
    rows = read_csv(path)
    imported, unmatched = 0, []
    for r in rows:
        kind = r["kind"].lower().replace(" ", "_").replace("-", "_")
        if kind not in KINDS:
            raise ValueError(f"Row {r}: kind must be one of {sorted(KINDS)}")
        variety_id = _lookup(conn, "variety", "code", r.get("variety", ""))
        product_id = _lookup(conn, "product", "sku", r.get("product", ""))
        if (r.get("variety") and not variety_id) or (r.get("product") and not product_id):
            unmatched.append(r["raw_text"])
        conn.execute(
            """INSERT INTO demand_signal(occurred_at, kind, raw_text, variety_id, product_id,
                 quantity, source, note) VALUES (?,?,?,?,?,?,?,?)""",
            (r["occurred_at"], kind, r["raw_text"], variety_id, product_id,
             int(r["quantity"]) if r.get("quantity") else None, source, r.get("note") or None))
        imported += 1
    conn.commit()
    if imported and path == INBOX:
        archive = path.parent / "archive"
        archive.mkdir(exist_ok=True)
        shutil.copy(path, archive / f"demand_signals_{datetime.now():%Y%m%d_%H%M%S}.csv")
        header = path.read_text(encoding="utf-8").splitlines()[0]
        path.write_text(header + "\n", encoding="utf-8")
    return {"imported": imported, "unmatched": unmatched}
