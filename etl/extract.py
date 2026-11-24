"""Ekstraksi streaming flat file sumber ELITIS."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd

GAMES_USECOLS = [
    "app_id",
    "title",
    "date_release",
    "win",
    "mac",
    "linux",
    "rating",
    "positive_ratio",
    "user_reviews",
    "price_final",
]

USERS_USECOLS = ["user_id", "products", "reviews"]

RECOMMENDATIONS_USECOLS = [
    "app_id",
    "helpful",
    "funny",
    "date",
    "is_recommended",
    "hours",
    "user_id",
    "review_id",
]


def iter_metadata_jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any] | None, str | None]]:
    """Baca games_metadata.json secara streaming per baris (JSON Lines, UTF-8).

    Menghasilkan tuple `(nomor_baris, objek_json_atau_None, pesan_error_atau_None)`
    untuk setiap baris non-kosong tanpa memuat seluruh berkas ke memori.
    """
    if not path.exists():
        raise FileNotFoundError(f"Berkas metadata tidak ditemukan: {path}")

    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as exc:
                yield line_no, None, f"json_decode_error: {exc.msg}"
                continue

            if not isinstance(parsed, dict):
                yield line_no, None, "not_a_json_object"
                continue

            yield line_no, parsed, None


def read_games_csv(path: Path) -> pd.DataFrame:
    """Baca berkas games.csv secara utuh sebagai UTF-8 dengan kolom target PRD §2.1–2.2."""
    if not path.exists():
        raise FileNotFoundError(f"Berkas games.csv tidak ditemukan: {path}")

    return pd.read_csv(
        path,
        usecols=GAMES_USECOLS,
        dtype={col: "string" for col in GAMES_USECOLS},
        encoding="utf-8",
        na_filter=False,
    )


def iter_users_chunks(path: Path, chunk_size: int) -> Iterator[pd.DataFrame]:
    """Baca berkas users.csv per chunk (UTF-8) tanpa memuat seluruh berkas ke memori."""
    if not path.exists():
        raise FileNotFoundError(f"Berkas users.csv tidak ditemukan: {path}")

    reader = pd.read_csv(
        path,
        chunksize=chunk_size,
        usecols=USERS_USECOLS,
        dtype={col: "string" for col in USERS_USECOLS},
        encoding="utf-8",
        na_filter=False,
    )
    yield from reader


def iter_recommendations_chunks(path: Path, chunk_size: int) -> Iterator[pd.DataFrame]:
    """Baca berkas recommendations.csv per chunk (UTF-8) tanpa memuat seluruh berkas ke memori."""
    if not path.exists():
        raise FileNotFoundError(f"Berkas recommendations.csv tidak ditemukan: {path}")

    reader = pd.read_csv(
        path,
        chunksize=chunk_size,
        usecols=RECOMMENDATIONS_USECOLS,
        dtype={col: "string" for col in RECOMMENDATIONS_USECOLS},
        encoding="utf-8",
        na_filter=False,
    )
    yield from reader
