"""Pemuatan idempotent ke MongoDB dan PostgreSQL (COPY + ON CONFLICT)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pymongo import ReplaceOne
from pymongo.database import Database

if TYPE_CHECKING:
    import psycopg


def upsert_metadata_batch(
    mongo_db: Database,
    raw_docs: list[dict[str, Any]],
    clean_docs: list[dict[str, Any]],
) -> int:
    """Upsert batch dokumen ke koleksi `raw_metadata` dan `game_metadata` berdasarkan `app_id`."""
    if not clean_docs:
        return 0

    raw_ops = [
        ReplaceOne({"app_id": doc["app_id"]}, doc, upsert=True)
        for doc in raw_docs
    ]
    clean_ops = [
        ReplaceOne({"app_id": doc["app_id"]}, doc, upsert=True)
        for doc in clean_docs
    ]

    mongo_db["raw_metadata"].bulk_write(raw_ops, ordered=False)
    mongo_db["game_metadata"].bulk_write(clean_ops, ordered=False)
    return len(clean_docs)


def get_indie_cohort(mongo_db: Database) -> set[int]:
    """Ambil himpunan app_id cohort Indie (D-1) langsung dari MongoDB `game_metadata`."""
    app_ids = mongo_db["game_metadata"].distinct("app_id", {"tags": "Indie"})
    return {int(app_id) for app_id in app_ids if app_id is not None}


def write_etl_log(mongo_db: Database, log_doc: dict[str, Any]) -> None:
    """Catat satu dokumen log eksekusi tahap ETL ke koleksi `etl_logs`."""
    mongo_db["etl_logs"].insert_one(log_doc)


def upsert_etl_log(mongo_db: Database, log_doc: dict[str, Any]) -> None:
    """Perbarui atau sisipkan satu dokumen log eksekusi berdasarkan `(run_id, stage)`."""
    mongo_db["etl_logs"].update_one(
        {"run_id": log_doc["run_id"], "stage": log_doc["stage"]},
        {"$set": log_doc},
        upsert=True,
    )


def upsert_games_copy(conn: psycopg.Connection, rows: list[tuple[Any, ...]]) -> int:
    """Muat daftar game terfilter ke PostgreSQL menggunakan COPY ke temp table + ON CONFLICT."""
    if not rows:
        return 0

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TEMP TABLE tmp_games (
                    app_id          BIGINT,
                    title           TEXT,
                    release_date    DATE,
                    win             BOOLEAN,
                    mac             BOOLEAN,
                    linux           BOOLEAN,
                    rating_category TEXT,
                    positive_ratio  NUMERIC(5,4),
                    total_reviews   INTEGER,
                    price_usd       NUMERIC(10,2)
                ) ON COMMIT DROP;
                """
            )
            with cur.copy(
                """
                COPY tmp_games (
                    app_id, title, release_date, win, mac, linux,
                    rating_category, positive_ratio, total_reviews, price_usd
                ) FROM STDIN
                """
            ) as copy:
                for row in rows:
                    copy.write_row(row)

            cur.execute(
                """
                INSERT INTO games (
                    app_id, title, release_date, win, mac, linux,
                    rating_category, positive_ratio, total_reviews, price_usd, updated_at
                )
                SELECT
                    app_id, title, release_date, win, mac, linux,
                    rating_category, positive_ratio, total_reviews, price_usd, now()
                FROM tmp_games
                ON CONFLICT (app_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    release_date = EXCLUDED.release_date,
                    win = EXCLUDED.win,
                    mac = EXCLUDED.mac,
                    linux = EXCLUDED.linux,
                    rating_category = EXCLUDED.rating_category,
                    positive_ratio = EXCLUDED.positive_ratio,
                    total_reviews = EXCLUDED.total_reviews,
                    price_usd = EXCLUDED.price_usd,
                    updated_at = now();
                """
            )
    return len(rows)


def upsert_users_copy(conn: psycopg.Connection, rows: list[tuple[int, int, int]]) -> int:
    """Muat satu chunk users ke PostgreSQL menggunakan COPY ke temp table + ON CONFLICT."""
    if not rows:
        return 0

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TEMP TABLE tmp_users (
                    user_id        BIGINT,
                    total_products INTEGER,
                    total_reviews  INTEGER
                ) ON COMMIT DROP;
                """
            )
            with cur.copy(
                "COPY tmp_users (user_id, total_products, total_reviews) FROM STDIN"
            ) as copy:
                for row in rows:
                    copy.write_row(row)

            cur.execute(
                """
                INSERT INTO users (user_id, total_products, total_reviews)
                SELECT user_id, total_products, total_reviews
                FROM tmp_users
                ON CONFLICT (user_id) DO UPDATE SET
                    total_products = EXCLUDED.total_products,
                    total_reviews = EXCLUDED.total_reviews;
                """
            )
    return len(rows)


def upsert_recommendations_copy(
    conn: psycopg.Connection,
    rows: list[tuple[Any, ...]],
) -> tuple[int, int, dict[str, int]]:
    """Muat satu chunk recommendations via COPY ke temp table + ON CONFLICT (review_id) DO NOTHING.

    Mengembalikan `(rows_valid_fk, rows_newly_inserted, fk_discard_reasons)`.
    """
    if not rows:
        return 0, 0, {}

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TEMP TABLE tmp_recommendations (
                    review_id      BIGINT,
                    user_id        BIGINT,
                    app_id         BIGINT,
                    is_recommended BOOLEAN,
                    hours_played   NUMERIC(10,2),
                    review_date    DATE,
                    helpful        INTEGER,
                    funny          INTEGER
                ) ON COMMIT DROP;
                """
            )
            with cur.copy(
                """
                COPY tmp_recommendations (
                    review_id, user_id, app_id, is_recommended,
                    hours_played, review_date, helpful, funny
                ) FROM STDIN
                """
            ) as copy:
                for row in rows:
                    copy.write_row(row)

            cur.execute("ANALYZE tmp_recommendations;")
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE u.user_id IS NULL) AS missing_user,
                    COUNT(*) FILTER (WHERE u.user_id IS NOT NULL AND g.app_id IS NULL) AS missing_game
                FROM tmp_recommendations t
                LEFT JOIN users u ON u.user_id = t.user_id
                LEFT JOIN games g ON g.app_id = t.app_id;
                """
            )
            missing_user, missing_game = cur.fetchone()
            missing_user = int(missing_user or 0)
            missing_game = int(missing_game or 0)

            cur.execute(
                """
                INSERT INTO recommendations (
                    review_id, user_id, app_id, is_recommended,
                    hours_played, review_date, helpful, funny
                )
                SELECT
                    t.review_id, t.user_id, t.app_id, t.is_recommended,
                    t.hours_played, t.review_date, t.helpful, t.funny
                FROM tmp_recommendations t
                INNER JOIN users u ON u.user_id = t.user_id
                INNER JOIN games g ON g.app_id = t.app_id
                ON CONFLICT (review_id) DO NOTHING;
                """
            )
            newly_inserted = max(int(cur.rowcount or 0), 0)

    fk_reasons: dict[str, int] = {}
    if missing_user:
        fk_reasons["missing_user"] = missing_user
    if missing_game:
        fk_reasons["missing_game"] = missing_game

    valid_loaded = len(rows) - missing_user - missing_game
    return valid_loaded, newly_inserted, fk_reasons


def get_tracked_app_ids(conn: psycopg.Connection, limit: int) -> list[int]:
    """Ambil daftar app_id teratas sesuai definisi D-4 dari `game_stats` secara stabil."""
    if limit <= 0:
        return []

    query = """
        SELECT app_id
        FROM game_stats
        ORDER BY
            COALESCE(is_hidden_gem, FALSE) DESC,
            CASE WHEN is_hidden_gem THEN positive_ratio END DESC NULLS LAST,
            CASE WHEN is_hidden_gem THEN total_reviews END DESC NULLS LAST,
            CASE WHEN NOT COALESCE(is_hidden_gem, FALSE) THEN total_recommendations END DESC NULLS LAST,
            app_id ASC
        LIMIT %s;
    """
    with conn.cursor() as cur:
        cur.execute(query, (limit,))
        return [int(row[0]) for row in cur.fetchall()]


def upsert_game_media_doc(mongo_db: Database, media_doc: dict[str, Any]) -> None:
    """Upsert satu dokumen media game ke koleksi `game_media` berdasarkan `app_id`."""
    mongo_db["game_media"].replace_one(
        {"app_id": media_doc["app_id"]},
        media_doc,
        upsert=True,
    )
