"""shop-ops command line."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from . import analysis, config, signals, synthetic
from .db import DEFAULT_DB, connect, init_schema


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="shop-ops")
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("SHOP_OPS_DB", DEFAULT_DB)))
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="Create the database and load config/*.csv")
    sub.add_parser("reload-config", help="Re-load config/*.csv after the owner edits them")
    g = sub.add_parser("generate", help="Generate synthetic sales, prices and purchases")
    g.add_argument("--years", type=int, default=4)
    g.add_argument("--seed", type=int, default=7)
    sub.add_parser("purge-synthetic", help="Delete all synthetic rows (keep real data)")
    s = sub.add_parser("import-signals", help="Import stockouts / turned-away requests")
    s.add_argument("path", nargs="?", type=Path, default=signals.INBOX)
    b = sub.add_parser("check-busiest-days", help="Test the Fri/Sat presumption against sales")
    b.add_argument("--include-synthetic", action="store_true")
    e = sub.add_parser("estimate", help="Estimate on-hand, waste and cooler capacity")
    e.add_argument("--write-defaults", action="store_true",
                   help="Write suggested on-hand targets into varieties.csv default column")
    sub.add_parser("status", help="Row counts by data source")
    w = sub.add_parser("weekly-note", help="Write the owner's weekly sales note as a draft text (nothing is sent)")
    w.add_argument("--weeks", type=int, default=4)
    w.add_argument("--as-of", help="Last day of the period (default: last day with sales)")
    d = sub.add_parser("drafts", help="Show draft texts waiting for review")
    d.add_argument("--limit", type=int, default=5)
    args = parser.parse_args(argv)

    conn = connect(args.db)
    init_schema(conn)
    if args.cmd in ("init", "reload-config"):
        config.load_config(conn)
        print(f"Config loaded into {args.db}")
    elif args.cmd == "generate":
        config.load_config(conn)
        synthetic.purge_synthetic(conn)
        print(json.dumps(synthetic.generate(conn, years=args.years, seed=args.seed), indent=2))
    elif args.cmd == "purge-synthetic":
        synthetic.purge_synthetic(conn)
        print("Synthetic rows removed.")
    elif args.cmd == "import-signals":
        print(json.dumps(signals.import_signals(conn, args.path), indent=2))
    elif args.cmd == "check-busiest-days":
        print(json.dumps(analysis.check_busiest_days(conn, args.include_synthetic), indent=2))
    elif args.cmd == "estimate":
        print(json.dumps(analysis.estimate(conn, args.write_defaults), indent=2))
    elif args.cmd == "weekly-note":
        from .flows import weekly_sales_note  # Prefect loads only when needed
        msg_id = weekly_sales_note(weeks=args.weeks, as_of=args.as_of, db=str(args.db))
        print(conn.execute("SELECT body FROM recommendation_message WHERE id = ?", (msg_id,)).fetchone()[0])
        print(f"\n(draft {msg_id}, not sent)")
    elif args.cmd == "drafts":
        for msg_id, run_at, body in conn.execute(
                "SELECT id, run_at, body FROM recommendation_message WHERE status = 'draft' "
                "ORDER BY id DESC LIMIT ?", (args.limit,)):
            print(f"--- draft {msg_id}, {run_at}\n{body}\n")
    elif args.cmd == "status":
        for table in ("sales_transaction", "purchase_order", "supplier_price",
                      "demand_signal", "inventory_count"):
            counts = conn.execute(
                f"SELECT data_source, COUNT(*) FROM {table} GROUP BY data_source").fetchall()
            print(f"{table:20s} {dict(counts) or '-'}")


if __name__ == "__main__":
    main()
