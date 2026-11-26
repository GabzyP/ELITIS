"""Uji integritas referensial lintas PostgreSQL dan MongoDB pada database produksi."""

from __future__ import annotations

from etl.config import get_mongo_db, get_pg_connection, get_settings
from etl.load import get_indie_cohort


def test_no_orphan_recommendations() -> None:
    """Tidak ada baris recommendations yang user_id atau app_id-nya hilang di users/games."""
    cfg = get_settings()
    conn = get_pg_connection(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM recommendations r
                LEFT JOIN users u ON u.user_id = r.user_id
                WHERE u.user_id IS NULL;
                """
            )
            orphan_users = int(cur.fetchone()[0])

            cur.execute(
                """
                SELECT COUNT(*)
                FROM recommendations r
                LEFT JOIN games g ON g.app_id = r.app_id
                WHERE g.app_id IS NULL;
                """
            )
            orphan_games = int(cur.fetchone()[0])
    finally:
        conn.close()

    assert orphan_users == 0
    assert orphan_games == 0


def test_games_and_mongo_cohort_match_exactly() -> None:
    """Tidak ada selisih app_id antara tabel PG `games` dan kohort Indie MongoDB."""
    cfg = get_settings()
    conn = get_pg_connection(cfg)
    client, mongo_db = get_mongo_db(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT app_id FROM games;")
            pg_app_ids = {int(row[0]) for row in cur.fetchall()}

        mongo_cohort_ids = get_indie_cohort(mongo_db)
    finally:
        conn.close()
        client.close()

    assert pg_app_ids - mongo_cohort_ids == set()
    assert mongo_cohort_ids - pg_app_ids == set()
