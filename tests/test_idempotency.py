"""Uji idempotensi ETL (metadata, games, users) pada sampel di database uji terisolasi."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import psycopg
from psycopg import sql
import pytest

from etl.config import PROJECT_ROOT, get_mongo_client, get_pg_connection, get_settings
from etl.load import get_indie_cohort
from etl.run_etl import run_games_stage, run_metadata_stage, run_users_stage

TEST_DB_NAME = "elitis_pytest_idempotency"


@pytest.fixture(scope="module")
def isolated_test_settings():
    """Buat database uji terisolasi di PostgreSQL dan MongoDB agar data produksi aman."""
    base_cfg = get_settings()
    test_cfg = replace(base_cfg, pg_db=TEST_DB_NAME, mongo_db=TEST_DB_NAME)

    admin_conn = get_pg_connection(base_cfg)
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE);").format(
                    sql.Identifier(TEST_DB_NAME)
                )
            )
            cur.execute(
                sql.SQL("CREATE DATABASE {};").format(sql.Identifier(TEST_DB_NAME))
            )
    finally:
        admin_conn.close()

    schema_sql = (PROJECT_ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    test_conn = get_pg_connection(test_cfg)
    test_conn.autocommit = True
    try:
        with test_conn.cursor() as cur:
            cur.execute(schema_sql)
    finally:
        test_conn.close()

    mongo_client = get_mongo_client(base_cfg)
    mongo_client.drop_database(TEST_DB_NAME)
    mongo_db = mongo_client[TEST_DB_NAME]
    mongo_db["game_metadata"].create_index([("app_id", 1)], unique=True)
    mongo_db["game_metadata"].create_index([("tags", 1)])
    mongo_db["raw_metadata"].create_index([("app_id", 1)])

    try:
        yield test_cfg
    finally:
        mongo_client.drop_database(TEST_DB_NAME)
        mongo_client.close()

        cleanup_conn = get_pg_connection(base_cfg)
        cleanup_conn.autocommit = True
        try:
            with cleanup_conn.cursor() as cur:
                cur.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE);").format(
                        sql.Identifier(TEST_DB_NAME)
                    )
                )
        finally:
            cleanup_conn.close()


def test_sample_pipeline_idempotency(isolated_test_settings) -> None:
    """Run dua kali tahap metadata, games, dan users pada sampel menghasilkan jumlah identik."""
    cfg = isolated_test_settings

    # 1. Metadata (2 kali)
    meta_1 = run_metadata_stage(settings=cfg, sample=True)
    meta_2 = run_metadata_stage(settings=cfg, sample=True)
    assert meta_1["raw_metadata_count"] == 1000
    assert meta_1["game_metadata_count"] == 1000
    assert meta_2["raw_metadata_count"] == meta_1["raw_metadata_count"]
    assert meta_2["game_metadata_count"] == meta_1["game_metadata_count"]
    assert meta_2["cohort_size"] == meta_1["cohort_size"] == 507

    mongo_client = get_mongo_client(cfg)
    try:
        assert len(get_indie_cohort(mongo_client[cfg.mongo_db])) == 507
    finally:
        mongo_client.close()

    # 2. Games (2 kali)
    games_1 = run_games_stage(settings=cfg, sample=True)
    games_2 = run_games_stage(settings=cfg, sample=True)
    assert games_1["pg_games_count"] == 507
    assert games_2["pg_games_count"] == games_1["pg_games_count"]

    # 3. Users (2 kali)
    users_1 = run_users_stage(settings=cfg, sample=True)
    users_2 = run_users_stage(settings=cfg, sample=True)
    assert users_1["pg_users_count"] == 1000
    assert users_2["pg_users_count"] == users_1["pg_users_count"]
