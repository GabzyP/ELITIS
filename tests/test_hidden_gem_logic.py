"""Uji batas definisi hidden gem (D-3) terhadap 5 sampel AC-07 dan seluruh `game_stats`."""

from __future__ import annotations

from etl.config import get_pg_connection, get_settings

AC07_SAMPLE_APP_IDS = (490100, 587310, 676130, 797570, 1511140)


def test_ac07_samples_satisfy_d3_in_game_stats() -> None:
    """Kelima sampel AC-07 berstatus is_hidden_gem = TRUE dan memenuhi syarat D-3."""
    cfg = get_settings()
    conn = get_pg_connection(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY total_reviews) FROM games;"
            )
            median_reviews = float(cur.fetchone()[0])

            cur.execute(
                """
                SELECT app_id, positive_ratio::float, total_reviews, is_hidden_gem
                FROM game_stats
                WHERE app_id = ANY(%s)
                ORDER BY app_id;
                """,
                (list(AC07_SAMPLE_APP_IDS),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    assert len(rows) == len(AC07_SAMPLE_APP_IDS)
    for app_id, ratio, total_reviews, is_hg in rows:
        assert is_hg is True, f"app_id={app_id} seharusnya is_hidden_gem=True"
        assert ratio >= 0.80
        assert total_reviews < median_reviews


def test_d3_boundary_has_no_false_positives_or_false_negatives() -> None:
    """Tidak ada pelanggaran batas D-3 di kedua arah pada `game_stats`."""
    cfg = get_settings()
    conn = get_pg_connection(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH med AS (
                    SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY total_reviews) AS m
                    FROM games
                )
                SELECT
                    COUNT(*) FILTER (
                        WHERE gs.is_hidden_gem = TRUE
                          AND (gs.positive_ratio < 0.80 OR gs.total_reviews >= med.m)
                    ) AS false_positives,
                    COUNT(*) FILTER (
                        WHERE gs.is_hidden_gem = FALSE
                          AND gs.positive_ratio >= 0.80
                          AND gs.total_reviews < med.m
                    ) AS false_negatives
                FROM game_stats gs
                CROSS JOIN med;
                """
            )
            false_positives, false_negatives = cur.fetchone()
    finally:
        conn.close()

    assert int(false_positives) == 0
    assert int(false_negatives) == 0
