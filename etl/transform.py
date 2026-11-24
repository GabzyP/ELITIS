"""Transformasi dan validasi data untuk pipeline ETL ELITIS."""

from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

import pandas as pd


def parse_valid_app_id(value: Any) -> int | None:
    """Konversi nilai app_id menjadi integer positif yang valid, atau None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            parsed = int(text)
            return parsed if parsed > 0 else None
    return None


def _parse_bool(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def _parse_iso_date(value: Any) -> date | None:
    text = str(value).strip()
    if not text:
        return None
    return date.fromisoformat(text)


def _parse_non_negative_int(value: Any, default: int = 0) -> int | None:
    text = str(value).strip()
    if not text:
        return default
    try:
        parsed = int(text)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _clean_tags(raw_tags: Any) -> list[str]:
    """Normalisasi array tags menjadi list string unik dengan urutan terjaga."""
    if not isinstance(raw_tags, list):
        return []
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in raw_tags:
        if item is None:
            continue
        tag = str(item).strip()
        if tag and tag not in seen:
            seen.add(tag)
            cleaned.append(tag)
    return cleaned


def transform_metadata_record(raw_doc: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Validasi dan bentuk pasangan dokumen `(raw_metadata, game_metadata)`.

    Mengembalikan None bila dokumen tidak memiliki `app_id` yang valid.
    """
    app_id = parse_valid_app_id(raw_doc.get("app_id"))
    if app_id is None:
        return None

    description_val = raw_doc.get("description")
    description = "" if description_val is None else str(description_val)
    tags = _clean_tags(raw_doc.get("tags"))

    raw_entry = dict(raw_doc)
    raw_entry["app_id"] = app_id

    clean_entry = {
        "app_id": app_id,
        "description": description,
        "tags": tags,
    }
    return raw_entry, clean_entry


def transform_games_df(
    df: pd.DataFrame,
    cohort: set[int],
) -> tuple[list[tuple[Any, ...]], int, dict[str, int]]:
    """Transformasi dan filter DataFrame `games.csv` terhadap kohort Indie.

    Mengembalikan `(rows_siap_load, rows_read, discarded_by_reason)`.
    """
    rows: list[tuple[Any, ...]] = []
    seen_app_ids: set[int] = set()
    reasons: Counter[str] = Counter()
    rows_read = len(df)

    for record in df.itertuples(index=False):
        app_id = parse_valid_app_id(record.app_id)
        if app_id is None:
            reasons["invalid_app_id"] += 1
            continue

        title = str(record.title).strip()
        if not title:
            reasons["empty_title"] += 1
            continue

        if app_id in seen_app_ids:
            reasons["duplicate_app_id"] += 1
            continue
        seen_app_ids.add(app_id)

        if app_id not in cohort:
            reasons["not_in_cohort"] += 1
            continue

        ratio_text = str(record.positive_ratio).strip()
        try:
            ratio = (Decimal(ratio_text) / Decimal("100")).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
        except (InvalidOperation, ValueError):
            reasons["positive_ratio_out_of_range"] += 1
            continue

        if ratio < Decimal("0") or ratio > Decimal("1"):
            reasons["positive_ratio_out_of_range"] += 1
            continue

        try:
            release_date = _parse_iso_date(record.date_release)
        except ValueError:
            reasons["invalid_release_date"] += 1
            continue

        total_reviews = _parse_non_negative_int(record.user_reviews, default=0)
        if total_reviews is None:
            reasons["invalid_total_reviews"] += 1
            continue

        price_text = str(record.price_final).strip()
        try:
            price_usd = Decimal(price_text or "0").quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        except (InvalidOperation, ValueError):
            reasons["invalid_price"] += 1
            continue

        if price_usd < Decimal("0"):
            reasons["invalid_price"] += 1
            continue

        rating_text = str(record.rating).strip()
        rating_category = rating_text if rating_text else None

        rows.append(
            (
                app_id,
                title,
                release_date,
                _parse_bool(record.win),
                _parse_bool(record.mac),
                _parse_bool(record.linux),
                rating_category,
                ratio,
                total_reviews,
                price_usd,
            )
        )

    return rows, rows_read, dict(reasons)


def transform_users_chunk(
    df: pd.DataFrame,
) -> tuple[list[tuple[int, int, int]], int, dict[str, int]]:
    """Transformasi satu chunk DataFrame `users.csv` sesuai pemetaan PRD §2.2."""
    rows: list[tuple[int, int, int]] = []
    seen_user_ids: set[int] = set()
    reasons: Counter[str] = Counter()
    rows_read = len(df)

    for record in df.itertuples(index=False):
        user_id = parse_valid_app_id(record.user_id)
        if user_id is None:
            reasons["invalid_user_id"] += 1
            continue

        if user_id in seen_user_ids:
            reasons["duplicate_user_id_in_chunk"] += 1
            continue
        seen_user_ids.add(user_id)

        total_products = _parse_non_negative_int(record.products, default=0)
        total_reviews = _parse_non_negative_int(record.reviews, default=0)
        if total_products is None or total_reviews is None:
            reasons["invalid_numeric_count"] += 1
            continue

        rows.append((user_id, total_products, total_reviews))

    return rows, rows_read, dict(reasons)
