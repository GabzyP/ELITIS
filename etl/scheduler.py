"""Scheduler polling berkala (APScheduler) dan orkestrasi folder watcher (ETL-08)."""

from __future__ import annotations

import argparse
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from etl.config import Settings, get_settings
from etl.live_polling import run_polling_round
from etl.watcher import start_watcher


def run_scheduler(
    settings: Settings | None = None,
    *,
    interval_seconds: float | None = None,
    limit: int | None = None,
    max_runs: int | None = None,
    enable_watcher: bool = True,
    watch_dir: Path | None = None,
    run_immediately: bool = False,
) -> dict[str, Any]:
    """Jalankan APScheduler untuk polling berkala (dan watcher opsional).

    Secara default memakai `POLLING_INTERVAL_MINUTES` dan `TRACKED_LIMIT` dari `.env`.
    """
    cfg = settings or get_settings()
    effective_seconds = (
        float(interval_seconds)
        if interval_seconds is not None
        else float(cfg.polling_interval_minutes) * 60.0
    )

    polling_lock = threading.Lock()
    runs_completed = 0
    runs_skipped = 0
    done_event = threading.Event()

    def _scheduled_poll_job() -> None:
        nonlocal runs_completed, runs_skipped
        if not polling_lock.acquire(blocking=False):
            runs_skipped += 1
            print(
                "[scheduler] Putaran polling sebelumnya belum selesai; "
                "putaran baru dilewati."
            )
            return

        try:
            now_str = datetime.now(timezone.utc).isoformat()
            print(f"[scheduler] Memulai putaran polling terjadwal pada {now_str}")
            run_polling_round(settings=cfg, limit=limit)
            runs_completed += 1
            if max_runs is not None and runs_completed >= max_runs:
                done_event.set()
        except Exception as exc:
            print(f"[scheduler] Error pada putaran polling: {exc}")
        finally:
            polling_lock.release()

    scheduler = BackgroundScheduler(timezone="UTC")
    next_run = datetime.now(timezone.utc) if run_immediately else None
    job_kwargs: dict[str, Any] = {
        "trigger": "interval",
        "seconds": effective_seconds,
        "id": "elitis_live_polling",
        "name": "ELITIS Live Polling Steam Store API",
        "max_instances": 1,
        "coalesce": True,
    }
    if next_run is not None:
        job_kwargs["next_run_time"] = next_run

    job = scheduler.add_job(_scheduled_poll_job, **job_kwargs)
    scheduler.start()
    print(
        f"[scheduler] Pekerjaan terdaftar: id={job.id} interval={effective_seconds:.1f}s "
        f"next_run_time={job.next_run_time}"
    )

    observer = None
    handler = None
    if enable_watcher:
        observer, handler = start_watcher(watch_dir=watch_dir, settings=cfg)

    try:
        while not done_event.is_set():
            done_event.wait(timeout=0.5)
    except KeyboardInterrupt:
        print("[scheduler] Dihentikan oleh pengguna.")
    finally:
        scheduler.shutdown(wait=True)
        if handler is not None:
            handler.stop_timers()
        if observer is not None:
            observer.stop()
            observer.join(timeout=5.0)
        print(
            f"[scheduler] Berhenti. runs_completed={runs_completed} "
            f"runs_skipped={runs_skipped}"
        )

    return {"runs_completed": runs_completed, "runs_skipped": runs_skipped}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ELITIS Scheduler + Folder Watcher")
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=None,
        help="Override interval polling dalam detik untuk pengujian (default POLLING_INTERVAL_MINUTES).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Batas opsional game D-4 untuk pengujian polling.",
    )
    parser.add_argument(
        "--max-runs",
        type=int,
        default=None,
        help="Berhenti otomatis setelah N putaran polling selesai (untuk pengujian).",
    )
    parser.add_argument(
        "--no-watcher",
        action="store_true",
        help="Nonaktifkan folder watcher (jalankan scheduler polling saja).",
    )
    parser.add_argument(
        "--watch-dir",
        type=Path,
        default=None,
        help="Override direktori yang diawasi watcher.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    run_scheduler(
        interval_seconds=args.interval_seconds,
        limit=args.limit,
        max_runs=args.max_runs,
        enable_watcher=not args.no_watcher,
        watch_dir=args.watch_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
