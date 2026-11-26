"""Uji cabang fallback enrichment (CDN gagal -> appdetails, dan appdetails gagal -> missing)."""

from __future__ import annotations

from unittest.mock import MagicMock

import etl.enrichment as enrichment


def _fake_response(status_code: int, json_payload: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    if json_payload is not None:
        resp.json.return_value = json_payload
    return resp


def test_enrichment_falls_back_to_appdetails_when_cdn_fails(monkeypatch) -> None:
    """Bila CDN gagal, enrichment mengambil header_image, capsule_image_url, dan screenshots dari appdetails."""
    app_id = 999001
    responses = [
        _fake_response(404),  # CDN HEAD -> 404 (tidak ada di CDN)
        _fake_response(
            200,
            {
                str(app_id): {
                    "success": True,
                    "data": {
                        "header_image": "https://shared.akamai.steamstatic.com/app/999001/header.jpg",
                        "capsule_image": "https://shared.akamai.steamstatic.com/app/999001/capsule.jpg",
                        "screenshots": [
                            {"path_full": "https://shared.akamai.steamstatic.com/app/999001/ss1.jpg"},
                            {"path_full": "https://shared.akamai.steamstatic.com/app/999001/ss2.jpg"},
                        ],
                    },
                }
            },
        ),
    ]

    session = MagicMock()
    session.request.side_effect = responses
    limiter = enrichment.RateLimiter(delay_seconds=0.0)

    doc, outcome = enrichment.enrich_single_game(session, app_id, limiter)

    assert outcome == "ok_appdetails"
    assert doc["status"] == "ok"
    assert doc["app_id"] == app_id
    assert doc["header_image_url"] == "https://shared.akamai.steamstatic.com/app/999001/header.jpg"
    assert doc["capsule_image_url"] == "https://shared.akamai.steamstatic.com/app/999001/capsule.jpg"
    assert doc["screenshots"] == [
        "https://shared.akamai.steamstatic.com/app/999001/ss1.jpg",
        "https://shared.akamai.steamstatic.com/app/999001/ss2.jpg",
    ]
    assert doc["store_url"] == f"https://store.steampowered.com/app/{app_id}/"


def test_enrichment_marks_missing_when_cdn_and_appdetails_both_fail() -> None:
    """Bila CDN dan appdetails sama-sama gagal, status='missing' dan store_url tetap terisi."""
    app_id = 999002
    responses = [
        _fake_response(404),  # CDN HEAD -> 404
        _fake_response(200, {str(app_id): {"success": False}}),  # appdetails -> success:false
    ]

    session = MagicMock()
    session.request.side_effect = responses
    limiter = enrichment.RateLimiter(delay_seconds=0.0)

    doc, outcome = enrichment.enrich_single_game(session, app_id, limiter)

    assert outcome == "missing"
    assert doc["status"] == "missing"
    assert doc["app_id"] == app_id
    assert doc["header_image_url"] == ""
    assert doc["capsule_image_url"] == ""
    assert doc["screenshots"] == []
    assert doc["store_url"] == f"https://store.steampowered.com/app/{app_id}/"
