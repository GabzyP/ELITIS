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
