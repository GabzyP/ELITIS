"""Enrichment foto dan URL toko Steam untuk daftar game D-4 (ETL-06)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import requests

CDN_HEADER_URL_TEMPLATE = "https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg"
APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
STORE_URL_TEMPLATE = "https://store.steampowered.com/app/{app_id}/"
DEFAULT_TIMEOUT_SECONDS = 10
MAX_429_RETRIES = 3


class RateLimiter:
    """Pengatur jeda minimum antar permintaan HTTP ke Steam."""

    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = max(delay_seconds, 0.0)
        self._last_call: float | None = None

    def wait(self) -> None:
        if self._last_call is not None and self.delay_seconds > 0:
            elapsed = time.monotonic() - self._last_call
            remaining = self.delay_seconds - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_call = time.monotonic()


def _request_with_backoff(
    session: requests.Session,
    method: str,
    url: str,
    limiter: RateLimiter,
    *,
    params: dict[str, Any] | None = None,
    stream: bool = False,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> requests.Response | None:
    """Kirim permintaan HTTP dengan jeda rate-limit dan backoff saat HTTP 429."""
    for attempt in range(MAX_429_RETRIES + 1):
        limiter.wait()
        try:
            resp = session.request(
                method,
                url,
                params=params,
                stream=stream,
                timeout=timeout,
                allow_redirects=True,
            )
        except requests.RequestException:
            return None

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            resp.close()
            if attempt >= MAX_429_RETRIES:
                return None
            if retry_after and retry_after.isdigit():
                backoff = max(float(retry_after), limiter.delay_seconds)
            else:
                backoff = max(limiter.delay_seconds, 1.5) * (2 ** (attempt + 1))
            time.sleep(min(backoff, 30.0))
            continue

        return resp
    return None


def _check_cdn_header(
    session: requests.Session,
    app_id: int,
    limiter: RateLimiter,
) -> str | None:
    """Verifikasi ketersediaan header.jpg di CDN Steam (HEAD, lalu GET ringan bila ditolak)."""
    cdn_url = CDN_HEADER_URL_TEMPLATE.format(app_id=app_id)
    head_resp = _request_with_backoff(session, "HEAD", cdn_url, limiter)
    if head_resp is not None:
        status = head_resp.status_code
        head_resp.close()
        if status == 200:
            return cdn_url
        if status == 404:
            return None

    # Fallback GET ringan (stream=True) bila HEAD ditolak (403/405/501) atau gagal jaringan
    get_resp = _request_with_backoff(session, "GET", cdn_url, limiter, stream=True)
    if get_resp is not None:
        status = get_resp.status_code
        get_resp.close()
        if status == 200:
            return cdn_url
    return None


def fetch_appdetails_data(
    session: requests.Session,
    app_id: int,
    limiter: RateLimiter,
) -> dict[str, Any] | None:
    """Ambil objek `data` dari Steam Store API appdetails untuk satu `app_id`, atau None."""
    resp = _request_with_backoff(
        session,
        "GET",
        APPDETAILS_URL,
        limiter,
        params={"appids": str(app_id), "cc": "us", "l": "english"},
    )
    if resp is None:
        return None

    try:
        if resp.status_code != 200:
            return None
        payload = resp.json()
    except ValueError:
        return None
    finally:
        resp.close()

    if not isinstance(payload, dict):
        return None
    entry = payload.get(str(app_id))
    if not isinstance(entry, dict) or entry.get("success") is not True:
        return None

    data = entry.get("data")
    return data if isinstance(data, dict) else None


def _fetch_appdetails_media(
    session: requests.Session,
    app_id: int,
    limiter: RateLimiter,
) -> tuple[str, str, list[str]] | None:
    """Ambil metadata media dari Steam Store API appdetails untuk satu app_id."""
    data = fetch_appdetails_data(session, app_id, limiter)
    if data is None:
        return None

    header_url = str(data.get("header_image") or "").strip()
    if not header_url:
        return None

    capsule_url = str(
        data.get("capsule_image") or data.get("capsule_imagev5") or ""
    ).strip()

    screenshots: list[str] = []
    raw_shots = data.get("screenshots")
    if isinstance(raw_shots, list):
        for shot in raw_shots:
            if not isinstance(shot, dict):
                continue
            shot_url = str(shot.get("path_full") or shot.get("path_thumbnail") or "").strip()
            if shot_url:
                screenshots.append(shot_url)

    return header_url, capsule_url, screenshots


def enrich_single_game(
    session: requests.Session,
    app_id: int,
    limiter: RateLimiter,
) -> tuple[dict[str, Any], str]:
    """Proses enrichment media satu game dan kembalikan `(game_media_doc, source_outcome)`.

    `source_outcome` bernilai salah satu dari: `'ok_cdn'`, `'ok_appdetails'`, `'missing'`.
    """
    store_url = STORE_URL_TEMPLATE.format(app_id=app_id)
    cdn_url = _check_cdn_header(session, app_id, limiter)
    if cdn_url is not None:
        return (
            {
                "app_id": app_id,
                "header_image_url": cdn_url,
                "capsule_image_url": "",
                "screenshots": [],
                "store_url": store_url,
                "fetched_at": datetime.now(timezone.utc),
                "status": "ok",
            },
            "ok_cdn",
        )

    appdetails_media = _fetch_appdetails_media(session, app_id, limiter)
    if appdetails_media is not None:
        header_url, capsule_url, screenshots = appdetails_media
        return (
            {
                "app_id": app_id,
                "header_image_url": header_url,
                "capsule_image_url": capsule_url,
                "screenshots": screenshots,
                "store_url": store_url,
                "fetched_at": datetime.now(timezone.utc),
                "status": "ok",
            },
            "ok_appdetails",
        )

    return (
        {
            "app_id": app_id,
            "header_image_url": "",
            "capsule_image_url": "",
            "screenshots": [],
            "store_url": store_url,
            "fetched_at": datetime.now(timezone.utc),
            "status": "missing",
        },
        "missing",
    )


def create_steam_session() -> requests.Session:
    """Buat HTTP session standar untuk permintaan ke CDN Steam dan Store API."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "ELITIS-ETL/1.0 (+https://store.steampowered.com/)",
            "Accept": "application/json,image/*,*/*;q=0.8",
        }
    )
    return session
