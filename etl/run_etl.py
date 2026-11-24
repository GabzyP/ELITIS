"""CLI entry point orkestrasi pipeline ETL ELITIS."""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from etl.config import (
    PROJECT_ROOT,
    Settings,
    get_mongo_db,
    get_pg_connection,
    get_settings,
    resolve_source_path,
)
from etl.extract import iter_metadata_jsonl, iter_users_chunks, read_games_csv
from etl.load import (
    get_indie_cohort,
    upsert_games_copy,
    upsert_metadata_batch,
    upsert_users_copy,
    write_etl_log,
)
from etl.transform import (
    transform_games_df,
    transform_metadata_record,
    transform_users_chunk,
)

METADATA_BATCH_SIZE = 1000


def _relative_source_label(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.name


def _format_discard_notes(reasons: dict[str, int]) -> str:
    if not reasons:
        return "discarded_reasons=none"
    parts = [f"{key}={reasons[key]}" for key in sorted(reasons)]
    return "discarded_reasons={" + ", ".join(parts) + "}"


def run_metadata_stage(
    settings: Settings | None = None,
    sample: bool = False,
    run_id: str | None = None,
    batch_size: int = METADATA_BATCH_SIZE,
) -> dict[str, Any]:
    """Jalankan ETL-01: streaming `games_metadata.json` -> `raw_metadata` & `game_metadata`."""
    cfg = settings or get_settings()
    source_path = resolve_source_path("games_metadata.json", sample=sample, settings=cfg)
    source_label = _relative_source_label(source_path)
    active_run_id = run_id or str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)

    rows_read = 0
    rows_loaded = 0
    rows_discarded = 0
    raw_batch: list[dict[str, Any]] = []
    clean_batch: list[dict[str, Any]] = []

    client, mongo_db = get_mongo_db(cfg)
    status = "success"
    notes_parts: list[str] = [f"sample={str(sample).lower()}"]

    try:
        for _line_no, parsed_doc, parse_err in iter_metadata_jsonl(source_path):
            rows_read += 1
            if parse_err is not None or parsed_doc is None:
                rows_discarded += 1
                continue

            transformed = transform_metadata_record(parsed_doc)
            if transformed is None:
                rows_discarded += 1
                continue

            raw_entry, clean_entry = transformed
            raw_batch.append(raw_entry)
            clean_batch.append(clean_entry)

            if len(clean_batch) >= batch_size:
                rows_loaded += upsert_metadata_batch(mongo_db, raw_batch, clean_batch)
                raw_batch.clear()
                clean_batch.clear()

        if clean_batch:
            rows_loaded += upsert_metadata_batch(mongo_db, raw_batch, clean_batch)
            raw_batch.clear()
            clean_batch.clear()

        cohort = get_indie_cohort(mongo_db)
        notes_parts.append(f"cohort_indie={len(cohort)}")
    except Exception as exc:
        status = "failed"
        notes_parts.append(f"error={type(exc).__name__}: {exc}")
        write_etl_log(
            mongo_db,
            {
                "run_id": active_run_id,
                "stage": "metadata",
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc),
                "source_file": source_label,
                "rows_read": rows_read,
                "rows_loaded": rows_loaded,
                "rows_discarded": rows_discarded,
                "status": status,
                "notes": "; ".join(notes_parts),
            },
        )
        client.close()
        raise

    log_doc = {
        "run_id": active_run_id,
        "stage": "metadata",
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc),
        "source_file": source_label,
        "rows_read": rows_read,
        "rows_loaded": rows_loaded,
        "rows_discarded": rows_discarded,
        "status": status,
        "notes": "; ".join(notes_parts),
    }
    write_etl_log(mongo_db, log_doc)

    raw_count = mongo_db["raw_metadata"].count_documents({})
    game_count = mongo_db["game_metadata"].count_documents({})
    client.close()

    print(
        f"[metadata] run_id={active_run_id} source={source_label} "
        f"rows_read={rows_read} rows_loaded={rows_loaded} rows_discarded={rows_discarded} "
        f"raw_metadata={raw_count} game_metadata={game_count} cohort_indie={len(cohort)}"
    )

    return {
        "log": log_doc,
        "raw_metadata_count": raw_count,
        "game_metadata_count": game_count,
        "cohort_size": len(cohort),
    }


def run_games_stage(
    settings: Settings | None = None,
    sample: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Jalankan ETL-02: baca `games.csv`, filter kohort Indie, COPY + upsert ke PostgreSQL."""
    cfg = settings or get_settings()
    source_path = resolve_source_path("games.csv", sample=sample, settings=cfg)
    source_label = _relative_source_label(source_path)
    active_run_id = run_id or str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)

    rows_read = 0
    rows_loaded = 0
    rows_discarded = 0
    discard_reasons: dict[str, int] = {}
    notes_parts: list[str] = [f"sample={str(sample).lower()}"]

    mongo_client, mongo_db = get_mongo_db(cfg)
    pg_conn = None

    try:
        cohort = get_indie_cohort(mongo_db)
        if not cohort:
            raise RuntimeError(
                "Kohort Indie di MongoDB kosong. Jalankan '--stage metadata' terlebih dahulu."
            )
        notes_parts.append(f"cohort_indie={len(cohort)}")

        games_df = read_games_csv(source_path)
        rows_to_load, rows_read, discard_reasons = transform_games_df(games_df, cohort)
        rows_discarded = sum(discard_reasons.values())
        notes_parts.append(_format_discard_notes(discard_reasons))

        pg_conn = get_pg_connection(cfg)
        rows_loaded = upsert_games_copy(pg_conn, rows_to_load)

        with pg_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM games;")
            pg_games_count = int(cur.fetchone()[0])
    except Exception as exc:
        notes_parts.append(f"error={type(exc).__name__}: {exc}")
        write_etl_log(
            mongo_db,
            {
                "run_id": active_run_id,
                "stage": "games",
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc),
                "source_file": source_label,
                "rows_read": rows_read,
                "rows_loaded": rows_loaded,
                "rows_discarded": rows_discarded,
                "status": "failed",
                "notes": "; ".join(notes_parts),
            },
        )
        if pg_conn is not None:
            pg_conn.close()
        mongo_client.close()
        raise

    log_doc = {
        "run_id": active_run_id,
        "stage": "games",
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc),
        "source_file": source_label,
        "rows_read": rows_read,
        "rows_loaded": rows_loaded,
        "rows_discarded": rows_discarded,
        "status": "success",
        "notes": "; ".join(notes_parts),
    }
    write_etl_log(mongo_db, log_doc)

    pg_conn.close()
    mongo_client.close()

    print(
        f"[games] run_id={active_run_id} source={source_label} "
        f"rows_read={rows_read} rows_loaded={rows_loaded} rows_discarded={rows_discarded} "
        f"pg_games_total={pg_games_count} {_format_discard_notes(discard_reasons)}"
    )

    return {
        "log": log_doc,
        "discard_reasons": discard_reasons,
        "pg_games_count": pg_games_count,
    }


def run_users_stage(
    settings: Settings | None = None,
    sample: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Jalankan ETL-03: baca `users.csv` per chunk, COPY + upsert ke PostgreSQL."""
    cfg = settings or get_settings()
    source_path = resolve_source_path("users.csv", sample=sample, settings=cfg)
    source_label = _relative_source_label(source_path)
    active_run_id = run_id or str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    perf_start = time.perf_counter()

    rows_read = 0
    rows_loaded = 0
    rows_discarded = 0
    chunks_processed = 0
    discard_counter: Counter[str] = Counter()
    notes_parts: list[str] = [f"sample={str(sample).lower()}", f"chunk_size={cfg.chunk_size}"]

    mongo_client, mongo_db = get_mongo_db(cfg)
    pg_conn = None

    try:
        pg_conn = get_pg_connection(cfg)
        for chunk_df in iter_users_chunks(source_path, chunk_size=cfg.chunk_size):
            chunks_processed += 1
            chunk_start = time.perf_counter()
            chunk_rows, chunk_read, chunk_reasons = transform_users_chunk(chunk_df)
            chunk_loaded = upsert_users_copy(pg_conn, chunk_rows)
            chunk_discarded = sum(chunk_reasons.values())

            rows_read += chunk_read
            rows_loaded += chunk_loaded
            rows_discarded += chunk_discarded
            discard_counter.update(chunk_reasons)

            elapsed = max(time.perf_counter() - chunk_start, 1e-6)
            rate = chunk_read / elapsed
            print(
                f"[users] chunk={chunks_processed} chunk_read={chunk_read} "
                f"chunk_loaded={chunk_loaded} chunk_discarded={chunk_discarded} "
                f"rate={rate:,.0f} rows/s"
            )

        with pg_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users;")
            pg_users_count = int(cur.fetchone()[0])
    except Exception as exc:
        notes_parts.append(f"chunks={chunks_processed}")
        notes_parts.append(_format_discard_notes(dict(discard_counter)))
        notes_parts.append(f"error={type(exc).__name__}: {exc}")
        write_etl_log(
            mongo_db,
            {
                "run_id": active_run_id,
                "stage": "users",
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc),
                "source_file": source_label,
                "rows_read": rows_read,
                "rows_loaded": rows_loaded,
                "rows_discarded": rows_discarded,
                "status": "failed",
                "notes": "; ".join(notes_parts),
            },
        )
        if pg_conn is not None:
            pg_conn.close()
        mongo_client.close()
        raise

    total_elapsed = max(time.perf_counter() - perf_start, 1e-6)
    notes_parts.append(f"chunks={chunks_processed}")
    notes_parts.append(f"elapsed_s={total_elapsed:.2f}")
    notes_parts.append(_format_discard_notes(dict(discard_counter)))

    log_doc = {
        "run_id": active_run_id,
        "stage": "users",
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc),
        "source_file": source_label,
        "rows_read": rows_read,
        "rows_loaded": rows_loaded,
        "rows_discarded": rows_discarded,
        "status": "success",
        "notes": "; ".join(notes_parts),
    }
    write_etl_log(mongo_db, log_doc)

    pg_conn.close()
    mongo_client.close()

    print(
        f"[users] run_id={active_run_id} source={source_label} "
        f"chunks={chunks_processed} rows_read={rows_read} rows_loaded={rows_loaded} "
        f"rows_discarded={rows_discarded} pg_users_total={pg_users_count} "
        f"elapsed={total_elapsed:.2f}s"
    )

    return {
        "log": log_doc,
        "discard_reasons": dict(discard_counter),
        "pg_users_count": pg_users_count,
        "elapsed_seconds": total_elapsed,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ELITIS ETL Pipeline CLI")
    parser.add_argument(
        "--stage",
        required=True,
        choices=["metadata", "games", "users", "recommendations", "enrichment", "polling", "replay", "full"],
        help="Tahap ETL yang akan dijalankan.",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Baca berkas sumber dari data/samples/ alih-alih data/incoming/.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.stage == "metadata":
        run_metadata_stage(sample=args.sample)
        return 0
    if args.stage == "games":
        run_games_stage(sample=args.sample)
        return 0
    if args.stage == "users":
        run_users_stage(sample=args.sample)
        return 0

    print(
        f"Tahap '--stage {args.stage}' belum diimplementasikan (dikerjakan pada T4-T8).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
