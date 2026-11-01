def test_recipes_match_business_rules(conn):
    recipe = dict(conn.execute(
        """SELECT p.sku || ':' || r.role, r.qty FROM recipe_slot r
           JOIN product p ON p.id = r.product_id""").fetchall())
    assert recipe == {
        "TWENTIES:base": 1, "TWENTIES:filler": 2, "TWENTIES:statement": 1, "TWENTIES:green": 5,
        "FIFTEENS:base": 1, "FIFTEENS:filler": 4, "FIFTEENS:green": 5,
    }


def test_mass_market_and_by_stem_hydrangea_are_distinct(conn):
    statement = {c for (c,) in conn.execute(
        """SELECT v.code FROM substitution_option s JOIN variety v ON v.id = s.variety_id
           WHERE s.role = 'statement'""")}
    assert "HYDRANGEA_MM" in statement
    assert "HYDRANGEA_STEM" not in statement


def test_hardgoods_per_product_type(conn):
    rules = set(conn.execute(
        """SELECT h.code, r.product_type FROM hardgood_rule r JOIN hardgood h ON h.id = r.hardgood_id"""))
    for code in ("FOOD_PACKET", "RIBBON", "CLEAR_PAPER", "COLORED_PAPER"):
        assert (code, "bouquet_giftwrap") in rules
    assert ("VASE", "arrangement") in rules


def test_owner_override_wins(conn):
    conn.execute("UPDATE variety SET owner_vase_life_days = 10 WHERE code = 'ROSE'")
    conn.execute("UPDATE season_window SET owner_best_start = '05-15' WHERE source = 'local' "
                 "AND variety_id = (SELECT id FROM variety WHERE code = 'SOLIDAGO')")
    assert conn.execute("SELECT vase_life_days FROM variety_effective WHERE code='ROSE'").fetchone()[0] == 10
    assert conn.execute(
        """SELECT best_start, best_end FROM season_window_effective s JOIN variety v ON v.id = s.variety_id
           WHERE v.code = 'SOLIDAGO' AND s.source = 'local'""").fetchone() == ("05-15", "10-15")


def test_inactive_owner_events_are_loaded_but_inactive(conn):
    assert conn.execute(
        "SELECT COUNT(*) FROM calendar_event WHERE kind='owner_event' AND active=1").fetchone()[0] == 0
