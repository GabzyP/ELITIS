"""Folder watcher untuk memantau berkas masuk di data/incoming (ETL-08)."""

from __future__ import annotations

import argparse
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from etl.config import Settings, get_pg_connection, get_settings
from etl.load import refresh_game_stats
from etl.run_etl import (
    run_games_stage,
    run_metadata_stage,
    run_recommendations_stage,
    run_users_stage,
)

FILE_STAGE_MAP: dict[str, str] = {
    "games_metadata.json": "metadata",
    "games.csv": "games",
    "users.csv": "users",
    "recommendations.csv": "recommendations",
}


class IncomingFileHandler(FileSystemEventHandler):
    """Handler watchdog dengan debounce kestabilan ukuran berkas sebelum memicu ETL."""

    def __init__(
        self,
        watch_dir: Path,
        settings: Settings | None = None,
        *,
        debounce_seconds: float = 2.0,
        stability_checks: int = 2,
        stability_interval_seconds: float = 0.5,
        on_triggered: Callable[[str, Path, dict[str, Any]], None] | None = None,
    ) -> None:
        super().__init__()
        self.watch_dir = watch_dir
        self.base_settings = settings or get_settings()
        self.scoped_settings = replace(self.base_settings, data_incoming_dir=watch_dir)
        self.debounce_seconds = max(debounce_seconds, 0.1)
        self.stability_checks = max(stability_checks, 1)
        self.stability_interval_seconds = max(stability_interval_seconds, 0.1)
        self.on_triggered = on_triggered

        self._lock = threading.Lock()
        self._etl_lock = threading.Lock()
        self._timers: dict[Path, threading.Timer] = {}
        self._last_event_at: dict[Path, float] = {}
        self._active_paths: set[Path] = set()

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle_event("created", event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._handle_event("modified", event)

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        dest_path = getattr(event, "dest_path", None)
        if dest_path:
            self._schedule_if_tracked("moved", Path(dest_path))

    def _handle_event(self, event_type: str, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._schedule_if_tracked(event_type, Path(event.src_path))

    def _schedule_if_tracked(self, event_type: str, file_path: Path) -> None:
        stage = FILE_STAGE_MAP.get(file_path.name)
        if stage is None:
            return

        resolved = file_path.resolve()
        with self._lock:
            existing = self._timers.pop(resolved, None)
            if existing is not None:
                existing.cancel()
            self._last_event_at[resolved] = time.monotonic()
            timer = threading.Timer(
                self.debounce_seconds,
                self._process_when_stable,
                args=(resolved, stage),
            )
            timer.daemon = True
            self._timers[resolved] = timer
            timer.start()

        print(
            f"[watcher] Event terdeteksi ({event_type}): file={file_path.name} "
            f"stage={stage} debounce={self.debounce_seconds:.2f}s"
        )

    def _wait_until_size_stable(self, file_path: Path) -> int | None:
        """Tunggu hingga ukuran berkas > 0 dan stabil berturut-turut."""
        stable_streak = 0
        last_size: int | None = None

        while True:
            if not file_path.exists():
                return None
            current_size = file_path.stat().st_size
            with self._lock:
                quiet_elapsed = time.monotonic() - self._last_event_at.get(file_path, 0.0)

            if current_size > 0 and last_size == current_size and quiet_elapsed >= self.debounce_seconds:
                stable_streak += 1
                if stable_streak >= self.stability_checks:
                    return current_size
            else:
                stable_streak = 0

            last_size = current_size
            time.sleep(self.stability_interval_seconds)

    def _process_when_stable(self, file_path: Path, stage: str) -> None:
        with self._lock:
            self._timers.pop(file_path, None)
            if file_path in self._active_paths:
                return
            self._active_paths.add(file_path)

        try:
            print(f"[watcher] Menunggu ukuran berkas stabil: {file_path.name} ...")
            stable_size = self._wait_until_size_stable(file_path)
            if stable_size is None:
                print(f"[watcher] Berkas hilang sebelum stabil, dilewati: {file_path.name}")
                return

            print(
                f"[watcher] Ukuran stabil ({stable_size} bytes); "
                f"memicu stage={stage} untuk {file_path.name}"
            )
            with self._etl_lock:
                result = self._run_stage(stage)

            if self.on_triggered is not None:
                self.on_triggered(stage, file_path, result)
        except Exception as exc:
            print(f"[watcher] Gagal memproses {file_path.name} (stage={stage}): {exc}")
        finally:
            with self._lock:
                self._active_paths.discard(file_path)

    def _run_stage(self, stage: str) -> dict[str, Any]:
        if stage == "metadata":
            return run_metadata_stage(settings=self.scoped_settings, sample=False)
        if stage == "games":
            result = run_games_stage(settings=self.scoped_settings, sample=False)
            self._refresh_view_after_pg_load()
            return result
        if stage == "users":
            return run_users_stage(settings=self.scoped_settings, sample=False)
        if stage == "recommendations":
            result = run_recommendations_stage(settings=self.scoped_settings, sample=False)
            self._refresh_view_after_pg_load()
            return result
        raise ValueError(f"Tahap watcher tidak dikenal: {stage}")

    def _refresh_view_after_pg_load(self) -> None:
        conn = get_pg_connection(self.scoped_settings)
        try:
            refresh_game_stats(conn, concurrently=True)
        finally:
            conn.close()

    def stop_timers(self) -> None:
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()


def start_watcher(
    watch_dir: Path | None = None,
    settings: Settings | None = None,
    *,
    debounce_seconds: float = 2.0,
    stability_checks: int = 2,
    stability_interval_seconds: float = 0.5,
    on_triggered: Callable[[str, Path, dict[str, Any]], None] | None = None,
) -> tuple[Observer, IncomingFileHandler]:
    """Mulai watchdog Observer pada `watch_dir` (default `DATA_INCOMING_DIR`)."""
    cfg = settings or get_settings()
    target_dir = (watch_dir or cfg.data_incoming_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    handler = IncomingFileHandler(
        watch_dir=target_dir,
        settings=cfg,
        debounce_seconds=debounce_seconds,
        stability_checks=stability_checks,
        stability_interval_seconds=stability_interval_seconds,
        on_triggered=on_triggered,
    )
    observer = Observer()
    observer.schedule(handler, str(target_dir), recursive=False)
    observer.start()
    print(f"[watcher] Mengawasi direktori: {target_dir}")
    return observer, handler


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ELITIS Folder Watcher (watchdog)")
    parser.add_argument("--dir", type=Path, default=None, help="Direktori yang diawasi (default DATA_INCOMING_DIR).")
    parser.add_argument("--debounce", type=float, default=2.0, help="Debounce detik sebelum cek ukuran stabil.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    observer, handler = start_watcher(watch_dir=args.dir, debounce_seconds=args.debounce)
    try:
        while observer.is_alive():
            observer.join(timeout=1.0)
    except KeyboardInterrupt:
        print("[watcher] Dihentikan oleh pengguna.")
    finally:
        handler.stop_timers()
        observer.stop()
        observer.join(timeout=5.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
