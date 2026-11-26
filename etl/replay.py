"""Mode replay rekomendasi dari replay_buffer ke recommendations (ETL-08)."""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from etl.config import Settings, get_mongo_db, get_pg_connection, get_settings
from etl.load import refresh_game_stats, upsert_etl_log, write_etl_log

_ORIGINAL_COUNT_RE = re.compile(r"original_count=(\d+)")


def _extract_last_prepare_original_count(mongo_db: Any) -> int | None:
    """Ambil nilai `original_count` dari log `replay --prepare` sukses terakhir."""
    doc = mongo_db["etl_logs"].find_one(
        {"stage": "replay", "source_file": "replay --prepare", "status": "success"},
        sort=[("started_at", -1)],
    )
    if not doc:
        return None
    notes = str(doc.get("notes") or "")
    match = _ORIGINAL_COUNT_RE.search(notes)
    return int(match.group(1)) if match else None


def prepare_replay(
    settings: Settings | None = None,
    *,
    fraction: float = 0.05,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Pindahkan ~`fraction` baris recommendations terbaru ke `replay_buffer` dan REFRESH game_stats."""
    if fraction <= 0.0 or fraction > 1.0:
        raise ValueError(f"fraction harus di dalam rentang (0, 1], diterima: {fraction}")

    cfg = settings or get_settings()
    active_run_id = run_id or str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    perf_start = time.perf_counter()

    mongo_client, mongo_db = get_mongo_db(cfg)
    pg_conn = None
    original_count = 0
    moved_count = 0

    try:
        pg_conn = get_pg_connection(cfg)
        with pg_conn.transaction():
            with pg_conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM replay_buffer;")
                existing_buffer = int(cur.fetchone()[0])
                if existing_buffer > 0:
                    raise RuntimeError(
                        f"replay_buffer belum kosong (sisa {existing_buffer:,} baris). "
                        "Jalankan --batch hingga habis sebelum --prepare ulang."
                    )

                cur.execute("SELECT COUNT(*) FROM recommendations;")
                original_count = int(cur.fetchone()[0])
                target_rows = int(round(original_count * fraction))
                if original_count > 0 and target_rows == 0:
                    target_rows = 1

                if target_rows > 0:
                    cur.execute(
                        """
                        WITH moved AS (
                            DELETE FROM recommendations
                            WHERE review_id IN (
                                SELECT review_id
                                FROM recommendations
                                ORDER BY review_date DESC NULLS LAST, review_id DESC
                                LIMIT %s
                            )
                            RETURNING
                                review_id, user_id, app_id, is_recommended,
                                hours_played, review_date, helpful, funny
                        )
                        INSERT INTO replay_buffer (
                            review_id, user_id, app_id, is_recommended,
                            hours_played, review_date, helpful, funny
                        )
                        SELECT
                            review_id, user_id, app_id, is_recommended,
                            hours_played, review_date, helpful, funny
                        FROM moved;
                        """,
                        (target_rows,),
                    )
                    moved_count = max(int(cur.rowcount or 0), 0)

        refresh_game_stats(pg_conn, concurrently=True)
        with pg_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM recommendations;")
            rec_after = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM replay_buffer;")
            buffer_after = int(cur.fetchone()[0])
    except Exception as exc:
        elapsed_s = max(time.perf_counter() - perf_start, 1e-6)
        write_etl_log(
            mongo_db,
            {
                "run_id": active_run_id,
                "stage": "replay",
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc),
                "source_file": "replay --prepare",
                "rows_read": original_count,
                "rows_loaded": moved_count,
                "rows_discarded": 0,
                "status": "failed",
                "notes": (
                    f"mode=prepare; fraction={fraction}; original_count={original_count}; "
                    f"elapsed_s={elapsed_s:.2f}; error={type(exc).__name__}: {exc}"
                ),
            },
        )
        if pg_conn is not None:
            pg_conn.close()
        mongo_client.close()
        raise

    elapsed_s = max(time.perf_counter() - perf_start, 1e-6)
    log_doc = {
        "run_id": active_run_id,
        "stage": "replay",
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc),
        "source_file": "replay --prepare",
        "rows_read": original_count,
        "rows_loaded": moved_count,
        "rows_discarded": 0,
        "status": "success",
        "notes": (
            f"mode=prepare; fraction={fraction}; original_count={original_count}; "
            f"moved_to_buffer={moved_count}; recommendations_after={rec_after}; "
            f"replay_buffer_after={buffer_after}; refreshed_game_stats=true; "
            f"elapsed_s={elapsed_s:.2f}"
        ),
    }
    write_etl_log(mongo_db, log_doc)

    pg_conn.close()
    mongo_client.close()

    print(
        f"[replay:prepare] run_id={active_run_id} fraction={fraction} "
        f"original_count={original_count} moved_to_buffer={moved_count} "
        f"recommendations_after={rec_after} replay_buffer_after={buffer_after} "
        f"elapsed={elapsed_s:.2f}s"
    )

    return {
        "log": log_doc,
        "original_count": original_count,
        "moved_to_buffer": moved_count,
        "recommendations_after": rec_after,
        "replay_buffer_after": buffer_after,
        "elapsed_seconds": elapsed_s,
    }


def run_replay_batches(
    settings: Settings | None = None,
    *,
    batch_size: int,
    interval_seconds: float = 5.0,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Pindahkan baris dari `replay_buffer` kembali ke `recommendations` per batch hingga habis."""
    if batch_size <= 0:
        raise ValueError(f"batch_size harus > 0, diterima: {batch_size}")
    if interval_seconds < 0.0:
        raise ValueError(f"interval_seconds harus >= 0, diterima: {interval_seconds}")

    cfg = settings or get_settings()
    active_run_id = run_id or str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    perf_start = time.perf_counter()

    mongo_client, mongo_db = get_mongo_db(cfg)
    pg_conn = None
    batches_done = 0
    total_deleted = 0
    total_inserted = 0
    remaining_buffer = 0
    rec_final = 0
    original_count = _extract_last_prepare_original_count(mongo_db)

    def _build_batch_log(status: str, elapsed_s: float, error_msg: str | None = None) -> dict[str, Any]:
        notes_parts = [
            "mode=batch",
            f"batch_size={batch_size}",
            f"interval_s={interval_seconds}",
            f"batches={batches_done}",
            f"remaining_buffer={remaining_buffer}",
            f"recommendations_final={rec_final}",
            f"elapsed_s={elapsed_s:.2f}",
        ]
        if remaining_buffer == 0 and original_count is not None:
            notes_parts.append(f"original_count={original_count}")
            notes_parts.append(f"matches_original={str(rec_final == original_count).lower()}")
        if error_msg:
            notes_parts.append(f"error={error_msg}")

        return {
            "run_id": active_run_id,
            "stage": "replay",
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc),
            "source_file": "replay --batch",
            "rows_read": total_deleted,
            "rows_loaded": total_inserted,
            "rows_discarded": max(total_deleted - total_inserted, 0),
            "status": status,
            "notes": "; ".join(notes_parts),
        }

    try:
        pg_conn = get_pg_connection(cfg)
        with pg_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM replay_buffer;")
            initial_buffer = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM recommendations;")
            rec_final = int(cur.fetchone()[0])

        if initial_buffer == 0:
            elapsed_s = max(time.perf_counter() - perf_start, 1e-6)
            log_doc = {
                "run_id": active_run_id,
                "stage": "replay",
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc),
                "source_file": "replay --batch",
                "rows_read": 0,
                "rows_loaded": 0,
                "rows_discarded": 0,
                "status": "success",
                "notes": (
                    f"mode=batch; batch_size={batch_size}; interval_s={interval_seconds}; "
                    f"buffer_initially_empty=true; recommendations_final={rec_final}; "
                    f"elapsed_s={elapsed_s:.2f}"
                ),
            }
            write_etl_log(mongo_db, log_doc)
            pg_conn.close()
            mongo_client.close()
            print(
                "[replay:batch] replay_buffer sudah kosong; tidak ada baris yang dikerjakan."
            )
            return {
                "log": log_doc,
                "batches": 0,
                "total_moved": 0,
                "remaining_buffer": 0,
                "recommendations_final": rec_final,
            }

        remaining_buffer = initial_buffer
        while remaining_buffer > 0:
            batches_done += 1
            with pg_conn.transaction():
                with pg_conn.cursor() as cur:
                    cur.execute(
                        """
                        WITH deleted AS (
                            DELETE FROM replay_buffer
                            WHERE ctid IN (
                                SELECT ctid
                                FROM replay_buffer
                                ORDER BY review_id ASC
                                LIMIT %s
                            )
                            RETURNING
                                review_id, user_id, app_id, is_recommended,
                                hours_played, review_date, helpful, funny
                        ),
                        inserted AS (
                            INSERT INTO recommendations (
                                review_id, user_id, app_id, is_recommended,
                                hours_played, review_date, helpful, funny
                            )
                            SELECT
                                review_id, user_id, app_id, is_recommended,
                                hours_played, review_date, helpful, funny
                            FROM deleted
                            ON CONFLICT (review_id) DO NOTHING
                            RETURNING review_id
                        )
                        SELECT
                            (SELECT COUNT(*) FROM deleted) AS deleted_count,
                            (SELECT COUNT(*) FROM inserted) AS inserted_count;
                        """,
                        (batch_size,),
                    )
                    deleted_count, inserted_count = cur.fetchone()
                    deleted_count = int(deleted_count or 0)
                    inserted_count = int(inserted_count or 0)

            if deleted_count == 0:
                remaining_buffer = 0
                break

            refresh_game_stats(pg_conn, concurrently=True)
            with pg_conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM replay_buffer;")
                remaining_buffer = int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM recommendations;")
                rec_final = int(cur.fetchone()[0])

            total_deleted += deleted_count
            total_inserted += inserted_count
            print(
                f"[replay:batch] batch={batches_done} moved={deleted_count} "
                f"inserted={inserted_count} remaining_buffer={remaining_buffer} "
                f"recommendations_total={rec_final}"
            )
            upsert_etl_log(
                mongo_db,
                _build_batch_log(
                    "partial" if remaining_buffer > 0 else "success",
                    time.perf_counter() - perf_start,
                ),
            )

            if remaining_buffer == 0:
                break
            if interval_seconds > 0:
                time.sleep(interval_seconds)
    except Exception as exc:
        upsert_etl_log(
            mongo_db,
            _build_batch_log(
                "failed",
                time.perf_counter() - perf_start,
                error_msg=f"{type(exc).__name__}: {exc}",
            ),
        )
        if pg_conn is not None:
            pg_conn.close()
        mongo_client.close()
        raise

    elapsed_s = max(time.perf_counter() - perf_start, 1e-6)
    log_doc = _build_batch_log("success", elapsed_s)
    upsert_etl_log(mongo_db, log_doc)

    pg_conn.close()
    mongo_client.close()

    print(
        f"[replay:batch] selesai run_id={active_run_id} batches={batches_done} "
        f"total_moved={total_deleted} total_inserted={total_inserted} "
        f"remaining_buffer={remaining_buffer} recommendations_final={rec_final} "
        f"elapsed={elapsed_s:.2f}s"
    )

    return {
        "log": log_doc,
        "batches": batches_done,
        "total_moved": total_deleted,
        "total_inserted": total_inserted,
        "remaining_buffer": remaining_buffer,
        "recommendations_final": rec_final,
        "original_count": original_count,
        "elapsed_seconds": elapsed_s,
    }
