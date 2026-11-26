"""Uji konsistensi data lintas database dan metrik pada produksi."""

from __future__ import annotations

from etl.config import get_mongo_db, get_pg_connection, get_settings
from etl.load import get_indie_cohort


def test_pg_games_count_equals_mongo_indie_cohort() -> None:
    """Jumlah baris PG `games` sama persis dengan jumlah distinct app_id bertag 'Indie' di MongoDB."""
    cfg = get_settings()
    conn = get_pg_connection(cfg)
    client, mongo_db = get_mongo_db(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM games;")
            pg_count = int(cur.fetchone()[0])
        mongo_cohort_count = len(get_indie_cohort(mongo_db))
    finally:
        conn.close()
        client.close()

    assert pg_count > 0
    assert pg_count == mongo_cohort_count


def test_hidden_gem_count_matches_recomputed_d3_and_ratios_valid() -> None:
    """Jumlah hidden gem di `game_stats` cocok dengan hitungan D-3 langsung dari `games` dan rasio 0..1."""
    cfg = get_settings()
    conn = get_pg_connection(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM game_stats WHERE is_hidden_gem = TRUE;")
            view_hg_count = int(cur.fetchone()[0])

            cur.execute(
                """
                WITH med AS (
                    SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY total_reviews) AS m
                    FROM games
                )
                SELECT COUNT(*)
                FROM games g, med
                WHERE g.positive_ratio >= 0.80 AND g.total_reviews < med.m;
                """
            )
            recomputed_hg_count = int(cur.fetchone()[0])

            cur.execute(
                """
                SELECT COUNT(*)
                FROM games
                WHERE positive_ratio IS NULL OR positive_ratio < 0 OR positive_ratio > 1;
                """
            )
            invalid_ratios = int(cur.fetchone()[0])
    finally:
        conn.close()

    assert view_hg_count == recomputed_hg_count
    assert invalid_ratios == 0
