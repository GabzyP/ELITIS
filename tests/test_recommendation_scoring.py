"""Uji fungsi murni rekomendasi (D-6 / REC-03, REC-05, REC-06) dari `dashboard/app.py`."""

from __future__ import annotations

import pandas as pd
import pytest

from dashboard.app import (
    build_recommendation_reason,
    compute_recommendation_score,
    filter_and_rank_recommendations,
)
from etl.config import get_mongo_db, get_pg_connection, get_settings


def test_monaco_scoring_and_reason_with_and_without_tags() -> None:
    """Skor Monaco (113020) = 77.6 dengan tag [Stealth, Co-op, Heist] dan 27.6 tanpa tag."""
    cfg = get_settings()
    conn = get_pg_connection(cfg)
    client, mongo_db = get_mongo_db(cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT app_id, title, win, mac, linux, positive_ratio::float,
                       total_reviews, price_usd::float, is_hidden_gem
                FROM game_stats
                WHERE app_id = 113020;
                """
            )
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()
        doc = mongo_db["game_metadata"].find_one({"app_id": 113020}, {"_id": 0, "tags": 1})
    finally:
        conn.close()
        client.close()

    assert row is not None and doc is not None
    monaco_df = pd.DataFrame([row], columns=cols)
    tags_by_app = {113020: list(doc["tags"])}

    with_tags = filter_and_rank_recommendations(
        monaco_df,
        tags_by_app,
        selected_tags=["Stealth", "Co-op", "Heist"],
        max_price=20.0,
        selected_platforms=["Windows"],
    )
    assert len(with_tags) == 1
    assert with_tags[0]["score"] == pytest.approx(77.6, abs=1e-4)
    assert "Stealth" in with_tags[0]["reason"]

    without_tags = filter_and_rank_recommendations(
        monaco_df,
        tags_by_app,
        selected_tags=[],
        max_price=None,
        selected_platforms=["Windows"],
    )
    assert len(without_tags) == 1
    assert without_tags[0]["score"] == pytest.approx(27.6, abs=1e-4)
    assert "tags favoritmu" not in without_tags[0]["reason"]

    # Verifikasi fungsi skor & alasan langsung
    assert compute_recommendation_score(3, 3, 0.92, False) == pytest.approx(77.6, abs=1e-4)
    assert compute_recommendation_score(0, 0, 0.92, False) == pytest.approx(27.6, abs=1e-4)
    reason_no_tag = build_recommendation_reason(
        matched_tags=[],
        selected_tags=[],
        positive_ratio=0.92,
        total_reviews=3722,
        is_hidden_gem=False,
        price_usd=14.99,
        max_price=None,
        supported_selected_platforms=["Windows"],
    )
    assert "tags favoritmu" not in reason_no_tag


def test_impossible_filter_returns_empty_list_rec06() -> None:
    """Kombinasi filter yang tidak mungkin terpenuhi mengembalikan daftar kosong tanpa error."""
    sample_df = pd.DataFrame(
        [
            {
                "app_id": 113020,
                "title": "Monaco: What's Yours Is Mine",
                "win": True,
                "mac": True,
                "linux": True,
                "positive_ratio": 0.92,
                "total_reviews": 3722,
                "price_usd": 14.99,
                "is_hidden_gem": False,
            }
        ]
    )
    res = filter_and_rank_recommendations(
        sample_df,
        {113020: ["Stealth", "Co-op", "Heist"]},
        selected_tags=["NonExistentRareTagXYZ"],
        max_price=0.01,
        selected_platforms=["Windows", "Mac", "Linux"],
    )
    assert res == []
