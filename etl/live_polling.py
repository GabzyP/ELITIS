"""Live polling harga dan metadata Steam Store API untuk daftar D-4 (ETL-07)."""

from __future__ import annotations

import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from etl.config import Settings, get_mongo_db, get_pg_connection, get_settings
from etl.enrichment import RateLimiter, create_steam_session, fetch_appdetails_data
from etl.load import (
    get_tracked_app_ids,
    record_live_poll_update,
    refresh_game_stats,
    write_etl_log,
)


def parse_appdetails_poll_fields(data: dict[str, Any]) -> tuple[Decimal | None, int | None]:
    """Ekstrak `(price_usd, steam_recommendations)` dari objek `data` respons appdetails."""
    price_usd: Decimal | None = None
    price_overview = data.get("price_overview")
    if isinstance(price_overview, dict) and price_overview.get("final") is not None:
        try:
            price_usd = (
                Decimal(str(price_overview["final"])) / Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError):
            price_usd = None
    elif data.get("is_free") is True:
        price_usd = Decimal("0.00")

    steam_recommendations: int | None = None
    recs = data.get("recommendations")
    if isinstance(recs, dict) and recs.get("total") is not None:
        try:
            parsed_recs = int(recs["total"])
            if parsed_recs >= 0:
                steam_recommendations = parsed_recs
        except (TypeError, ValueError):
            steam_recommendations = None

    return price_usd, steam_recommendations


def run_polling_round(
    settings: Settings | None = None,
    limit: int | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Jalankan satu putaran live polling (ETL-07) untuk daftar D-4 lalu REFRESH game_stats."""
    cfg = settings or get_settings()
    target_limit = cfg.tracked_limit if limit is None else limit
    active_run_id = run_id or str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    perf_start = time.perf_counter()

    rows_read = 0
    rows_loaded = 0
    rows_discarded = 0
    stats: Counter[str] = Counter()
    refreshed = False

    mongo_client, mongo_db = get_mongo_db(cfg)
    pg_conn = None
    session = create_steam_session()

    def _build_log_doc(status: str, elapsed_s: float, error_msg: str | None = None) -> dict[str, Any]:
        notes_parts = [
            f"tracked_limit={target_limit}",
            f"succeeded={rows_loaded}",
            f"failed={rows_discarded}",
            f"no_price={stats['no_price']}",
            f"no_steam_recommendations={stats['no_steam_recommendations']}",
            f"refreshed_game_stats={str(refreshed).lower()}",
            f"elapsed_s={elapsed_s:.2f}",
        ]
        if error_msg:
            notes_parts.append(f"error={error_msg}")
        return {
            "run_id": active_run_id,
            "stage": "polling",
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc),
            "source_file": "game_stats (D-4)",
            "rows_read": rows_read,
            "rows_loaded": rows_loaded,
            "rows_discarded": rows_discarded,
            "status": status,
            "notes": "; ".join(notes_parts),
        }

    try:
        pg_conn = get_pg_connection(cfg)
        app_ids = get_tracked_app_ids(pg_conn, limit=target_limit)
        limiter = RateLimiter(cfg.steam_api_delay_seconds)

        for idx, app_id in enumerate(app_ids, start=1):
            rows_read += 1
            data = fetch_appdetails_data(session, app_id, limiter)
            if data is None:
                rows_discarded += 1
                print(f"[polling] ({idx}/{len(app_ids)}) app_id={app_id} status=failed")
                continue

            price_usd, steam_recs = parse_appdetails_poll_fields(data)
            if price_usd is None:
                stats["no_price"] += 1
            if steam_recs is None:
                stats["no_steam_recommendations"] += 1

            record_live_poll_update(pg_conn, app_id, price_usd, steam_recs)
            rows_loaded += 1
            print(
                f"[polling] ({idx}/{len(app_ids)}) app_id={app_id} "
                f"price_usd={price_usd} steam_recommendations={steam_recs}"
            )

        if rows_loaded > 0:
            refresh_game_stats(pg_conn, concurrently=True)
            refreshed = True
    except Exception as exc:
        write_etl_log(
            mongo_db,
            _build_log_doc(
                "failed",
                time.perf_counter() - perf_start,
                error_msg=f"{type(exc).__name__}: {exc}",
            ),
        )
        session.close()
        if pg_conn is not None:
            pg_conn.close()
        mongo_client.close()
        raise

    total_elapsed = max(time.perf_counter() - perf_start, 1e-6)
    if rows_read > 0 and rows_loaded == 0:
        final_status = "failed"
    elif rows_discarded > 0:
        final_status = "partial"
    else:
        final_status = "success"

    log_doc = _build_log_doc(final_status, total_elapsed)
    write_etl_log(mongo_db, log_doc)

    session.close()
    pg_conn.close()
    mongo_client.close()

    print(
        f"[polling] run_id={active_run_id} tracked={rows_read} "
        f"succeeded={rows_loaded} failed={rows_discarded} "
        f"no_steam_recommendations={stats['no_steam_recommendations']} "
        f"refreshed_game_stats={refreshed} status={final_status} elapsed={total_elapsed:.2f}s"
    )

    return {
        "log": log_doc,
        "succeeded": rows_loaded,
        "failed": rows_discarded,
        "no_price": stats["no_price"],
        "no_steam_recommendations": stats["no_steam_recommendations"],
        "refreshed": refreshed,
        "elapsed_seconds": total_elapsed,
    }
