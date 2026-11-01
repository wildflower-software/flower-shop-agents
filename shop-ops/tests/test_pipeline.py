from datetime import date

from shop_ops import analysis, signals, synthetic


def test_synthetic_history_and_estimates(conn):
    stats = synthetic.generate(conn, years=1, seed=1, end=date(2026, 9, 30))
    assert stats["transactions"] > 5000

    # Every twenties sale uses exactly 9 units: 1 base + 2 filler + 1 statement + 5 green.
    bad = conn.execute(
        """SELECT COUNT(*) FROM (
             SELECT l.id, SUM(c.stems) AS n FROM sales_line l
             JOIN product p ON p.id = l.product_id AND p.sku = 'TWENTIES'
             JOIN sales_line_component c ON c.sales_line_id = l.id GROUP BY l.id) WHERE n != 9""").fetchone()[0]
    assert bad == 0

    # Local-only stock is never bought out of season.
    off_season_local = conn.execute(
        """SELECT COUNT(*) FROM purchase_line pl JOIN purchase_order po ON po.id = pl.order_id
           JOIN supplier_product sp ON sp.id = pl.supplier_product_id
           JOIN variety v ON v.id = sp.variety_id
           WHERE sp.origin = 'local' AND v.code = 'SOLIDAGO'
             AND strftime('%m', po.delivery_date) IN ('01','02','03','04','05','06')""").fetchone()[0]
    assert off_season_local == 0

    result = analysis.estimate(conn)
    totals = conn.execute(
        "SELECT SUM(received), SUM(used), SUM(discarded) FROM inventory_estimate").fetchone()
    assert totals[0] >= totals[1] + totals[2]           # stems are conserved
    assert result["cooler_capacity_estimate"] > 0


def test_synthetic_data_never_proves_busiest_days(conn):
    synthetic.generate(conn, years=1, seed=1, end=date(2026, 9, 30))
    assert analysis.check_busiest_days(conn)["status"] == "insufficient_data"
    assert analysis.check_busiest_days(conn, include_synthetic=True)["status"] == "presumed"


def test_purge_synthetic_keeps_config(conn):
    synthetic.generate(conn, years=1, seed=1, end=date(2026, 9, 30))
    synthetic.purge_synthetic(conn)
    assert conn.execute("SELECT COUNT(*) FROM sales_transaction").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM variety").fetchone()[0] == 11


def test_import_demand_signals(conn, tmp_path):
    f = tmp_path / "signals.csv"
    f.write_text(
        "occurred_at,kind,raw_text,variety,product,quantity,note\n"
        "2026-10-10 14:05,turned_away,wanted 2 dozen white roses,rose,,24,\n"
        "2026-10-10 16:00,stockout,out of sunflowers,sunflower,,,not a stocked variety\n")
    result = signals.import_signals(conn, f)
    assert result == {"imported": 2, "unmatched": ["out of sunflowers"]}
    assert conn.execute("SELECT COUNT(*) FROM demand_signal WHERE variety_id IS NOT NULL").fetchone()[0] == 1
