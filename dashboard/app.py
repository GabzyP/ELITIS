"""Dasbor satu halaman ELITIS — Engine for Locating Indie Treasures in Steam."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from etl.config import Settings, get_mongo_db, get_pg_connection, get_settings

PLACEHOLDER_IMAGE_SVG = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' width='460' height='215' viewBox='0 0 460 215'>"
    "<rect width='460' height='215' fill='%231e2430'/>"
    "<text x='50%' y='50%' dominant-baseline='middle' text-anchor='middle' "
    "fill='%238b98a5' font-family='sans-serif' font-size='18'>Media Tidak Tersedia</text>"
    "</svg>"
)

PLATFORM_COL_MAP = {
    "Windows": "win",
    "Mac": "mac",
    "Linux": "linux",
}


# ---------------------------------------------------------------------------
# Logika murni rekomendasi (D-6, REC-01..REC-06) — dapat diuji unit secara terpisah
# ---------------------------------------------------------------------------


def compute_recommendation_score(
    matched_tag_count: int,
    selected_tag_count: int,
    positive_ratio: float,
    is_hidden_gem: bool,
) -> float:
    """Hitung skor rekomendasi rule-based persis sesuai rumus D-6 / REC-03."""
    tag_component = (
        matched_tag_count / selected_tag_count if selected_tag_count > 0 else 0.0
    )
    hg_component = 1.0 if is_hidden_gem else 0.0
    score = 100.0 * (
        0.50 * tag_component + 0.30 * float(positive_ratio) + 0.20 * hg_component
    )
    return round(score, 4)


def _join_indonesian_clauses(clauses: list[str]) -> str:
    if not clauses:
        return ""
    if len(clauses) == 1:
        return clauses[0]
    if len(clauses) == 2:
        return f"{clauses[0]} dan {clauses[1]}"
    return ", ".join(clauses[:-1]) + f", dan {clauses[-1]}"


def build_recommendation_reason(
    *,
    matched_tags: list[str],
    selected_tags: list[str],
    positive_ratio: float,
    total_reviews: int,
    is_hidden_gem: bool,
    price_usd: float,
    max_price: float | None,
    supported_selected_platforms: list[str],
) -> str:
    """Bangun satu kalimat alasan REC-05 yang hanya mengklaim komponen terpenuhi."""
    clauses: list[str] = []

    if selected_tags and matched_tags:
        tag_list = ", ".join(matched_tags[:5])
        if len(matched_tags) > 5:
            tag_list += f" (+{len(matched_tags) - 5} lainnya)"
        clauses.append(f"cocok dengan tags favoritmu ({tag_list})")

    pct = float(positive_ratio) * 100.0
    if float(positive_ratio) >= 0.80:
        clauses.append(
            f"kualitasnya tinggi (positive ratio {pct:.1f}% dari {int(total_reviews):,} review)"
        )
    else:
        clauses.append(
            f"memiliki positive ratio {pct:.1f}% dari {int(total_reviews):,} review"
        )

    if is_hidden_gem:
        clauses.append("termasuk hidden gem")

    if max_price is not None and float(price_usd) <= float(max_price):
        if float(price_usd) == 0.0:
            clauses.append("gratis dan sesuai budgetmu")
        else:
            clauses.append("harganya di bawah budgetmu")

    if supported_selected_platforms:
        clauses.append(f"tersedia di {', '.join(supported_selected_platforms)}")

    return f"Direkomendasikan karena {_join_indonesian_clauses(clauses)}."


def filter_and_rank_recommendations(
    games_df: pd.DataFrame,
    tags_by_app: dict[int, list[str]],
    *,
    selected_tags: list[str],
    max_price: float | None,
    selected_platforms: list[str],
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Terapkan filter keras REC-02, skor D-6 / REC-03, dan kembalikan maksimal 20 kandidat."""
    if games_df.empty:
        return []

    selected_tag_set = set(selected_tags)
    candidates: list[dict[str, Any]] = []

    for row in games_df.itertuples(index=False):
        app_id = int(row.app_id)
        price = float(row.price_usd)

        # REC-02: batas harga maksimal (game gratis selalu lolos bila max_price >= 0 atau None)
        if max_price is not None and price > 0.0 and price > float(max_price):
            continue

        # REC-02: platform terpilih harus didukung
        supported_selected: list[str] = []
        platform_ok = True
        for plat_label in selected_platforms:
            col_name = PLATFORM_COL_MAP.get(plat_label)
            if col_name and bool(getattr(row, col_name, False)):
                supported_selected.append(plat_label)
            else:
                platform_ok = False
                break
        if not platform_ok:
            continue

        game_tags = tags_by_app.get(app_id, [])
        if selected_tags:
            matched_tags = [tag for tag in selected_tags if tag in game_tags]
            if not matched_tags:
                continue
        else:
            matched_tags = []

        ratio = float(row.positive_ratio or 0.0)
        total_reviews = int(row.total_reviews or 0)
        is_hidden_gem = bool(row.is_hidden_gem)

        score = compute_recommendation_score(
            matched_tag_count=len(matched_tags),
            selected_tag_count=len(selected_tag_set),
            positive_ratio=ratio,
            is_hidden_gem=is_hidden_gem,
        )
        reason = build_recommendation_reason(
            matched_tags=matched_tags,
            selected_tags=selected_tags,
            positive_ratio=ratio,
            total_reviews=total_reviews,
            is_hidden_gem=is_hidden_gem,
            price_usd=price,
            max_price=max_price,
            supported_selected_platforms=supported_selected,
        )

        candidates.append(
            {
                "app_id": app_id,
                "title": str(row.title),
                "positive_ratio": ratio,
                "total_reviews": total_reviews,
                "price_usd": price,
                "is_hidden_gem": is_hidden_gem,
                "win": bool(row.win),
                "mac": bool(row.mac),
                "linux": bool(row.linux),
                "tags": game_tags,
                "matched_tags": matched_tags,
                "score": score,
                "reason": reason,
            }
        )

    candidates.sort(
        key=lambda item: (
            -item["score"],
            -item["positive_ratio"],
            -item["total_reviews"],
            item["app_id"],
        )
    )
    return candidates[:limit]


# ---------------------------------------------------------------------------
# Query layer (PostgreSQL & MongoDB terpisah agar gagal satu DB tidak crash total)
# ---------------------------------------------------------------------------


def fetch_pg_game_stats(cfg: Settings) -> tuple[pd.DataFrame | None, str | None]:
    """Ambil seluruh baris `game_stats` dari PostgreSQL."""
    conn = None
    try:
        conn = get_pg_connection(cfg)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    app_id, title, release_date, win, mac, linux,
                    rating_category, positive_ratio, total_reviews, price_usd,
                    total_recommendations, recommended_share, avg_hours_played, is_hidden_gem
                FROM game_stats;
                """
            )
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
        df = pd.DataFrame(rows, columns=cols)
        if not df.empty:
            df["positive_ratio"] = df["positive_ratio"].astype(float)
            df["price_usd"] = df["price_usd"].astype(float)
            df["total_reviews"] = df["total_reviews"].astype(int)
            df["total_recommendations"] = df["total_recommendations"].astype(int)
            df["is_hidden_gem"] = df["is_hidden_gem"].astype(bool)
        return df, None
    except Exception as exc:
        return None, f"PostgreSQL tidak dapat diakses ({type(exc).__name__}: {exc})"
    finally:
        if conn is not None:
            conn.close()


def fetch_pg_kpis(cfg: Settings) -> tuple[dict[str, Any] | None, str | None]:
    """Hitung 4 KPI utama dari PostgreSQL (`games` dan `game_stats`)."""
    conn = None
    try:
        conn = get_pg_connection(cfg)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)::bigint AS total_games,
                    AVG(positive_ratio)::float AS avg_positive_ratio,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY total_reviews)::float AS median_total_reviews
                FROM games;
                """
            )
            total_games, avg_ratio, median_reviews = cur.fetchone()

            cur.execute(
                "SELECT COUNT(*)::bigint FROM game_stats WHERE is_hidden_gem = TRUE;"
            )
            hidden_gems = int(cur.fetchone()[0])

        return (
            {
                "total_games": int(total_games or 0),
                "avg_positive_ratio": float(avg_ratio or 0.0),
                "median_total_reviews": float(median_reviews or 0.0),
                "hidden_gem_count": hidden_gems,
            },
            None,
        )
    except Exception as exc:
        return None, f"PostgreSQL KPI gagal dimuat ({type(exc).__name__}: {exc})"
    finally:
        if conn is not None:
            conn.close()


def fetch_pg_monthly_trend(cfg: Settings) -> tuple[pd.DataFrame | None, str | None]:
    """Ambil jumlah rekomendasi per bulan dari `recommendations.review_date`."""
    conn = None
    try:
        conn = get_pg_connection(cfg)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    date_trunc('month', review_date)::date AS month,
                    COUNT(*)::bigint AS total_recommendations
                FROM recommendations
                WHERE review_date IS NOT NULL
                GROUP BY 1
                ORDER BY 1;
                """
            )
            rows = cur.fetchall()
        df = pd.DataFrame(rows, columns=["month", "total_recommendations"])
        return df, None
    except Exception as exc:
        return None, f"PostgreSQL Tren Rekomendasi gagal dimuat ({type(exc).__name__}: {exc})"
    finally:
        if conn is not None:
            conn.close()


def fetch_pg_top10(cfg: Settings) -> tuple[pd.DataFrame | None, str | None]:
    """Ambil 10 game dengan `total_recommendations` terbesar dari `game_stats`."""
    conn = None
    try:
        conn = get_pg_connection(cfg)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    app_id, title, total_recommendations, positive_ratio::float,
                    total_reviews, price_usd::float, is_hidden_gem
                FROM game_stats
                ORDER BY total_recommendations DESC, app_id ASC
                LIMIT 10;
                """
            )
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
        return pd.DataFrame(rows, columns=cols), None
    except Exception as exc:
        return None, f"PostgreSQL Top 10 gagal dimuat ({type(exc).__name__}: {exc})"
    finally:
        if conn is not None:
            conn.close()


def fetch_pg_hidden_gems_page(
    cfg: Settings,
    *,
    page: int,
    page_size: int = 20,
) -> tuple[tuple[pd.DataFrame, int] | None, str | None]:
    """Ambil halaman daftar hidden gem dari `game_stats` urut `positive_ratio` menurun."""
    conn = None
    try:
        conn = get_pg_connection(cfg)
        offset = max(page - 1, 0) * page_size
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*)::bigint FROM game_stats WHERE is_hidden_gem = TRUE;"
            )
            total_count = int(cur.fetchone()[0])

            cur.execute(
                """
                SELECT
                    app_id, title, positive_ratio::float, total_reviews,
                    price_usd::float, total_recommendations, win, mac, linux
                FROM game_stats
                WHERE is_hidden_gem = TRUE
                ORDER BY positive_ratio DESC, total_reviews DESC, app_id ASC
                LIMIT %s OFFSET %s;
                """,
                (page_size, offset),
            )
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
        return (pd.DataFrame(rows, columns=cols), total_count), None
    except Exception as exc:
        return None, f"PostgreSQL Daftar Hidden Gems gagal dimuat ({type(exc).__name__}: {exc})"
    finally:
        if conn is not None:
            conn.close()


def fetch_pg_live_updates(cfg: Settings, limit: int = 20) -> tuple[dict[str, Any] | None, str | None]:
    """Ambil perbandingan dua observasi terakhir per game (dan observasi terbaru) dari `live_updates`."""
    conn = None
    try:
        conn = get_pg_connection(cfg)
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH ranked AS (
                    SELECT
                        l.app_id,
                        g.title,
                        l.price_usd::float AS price_usd,
                        l.steam_recommendations,
                        l.polled_at,
                        ROW_NUMBER() OVER (PARTITION BY l.app_id ORDER BY l.polled_at DESC, l.id DESC) AS rn
                    FROM live_updates l
                    JOIN games g ON g.app_id = l.app_id
                ),
                paired AS (
                    SELECT
                        cur.app_id,
                        cur.title,
                        prev.price_usd AS prev_price_usd,
                        cur.price_usd AS latest_price_usd,
                        (cur.price_usd - prev.price_usd) AS delta_price_usd,
                        prev.steam_recommendations AS prev_steam_recs,
                        cur.steam_recommendations AS latest_steam_recs,
                        cur.polled_at AS latest_polled_at
                    FROM ranked cur
                    LEFT JOIN ranked prev ON prev.app_id = cur.app_id AND prev.rn = 2
                    WHERE cur.rn = 1
                )
                SELECT *
                FROM paired
                ORDER BY
                    (prev_price_usd IS NOT NULL AND latest_price_usd IS DISTINCT FROM prev_price_usd) DESC,
                    (prev_price_usd IS NOT NULL) DESC,
                    latest_polled_at DESC,
                    app_id ASC
                LIMIT %s;
                """,
                (limit,),
            )
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

            cur.execute("SELECT COUNT(*)::bigint, COUNT(DISTINCT app_id)::bigint FROM live_updates;")
            total_obs, distinct_apps = cur.fetchone()

        return (
            {
                "df": pd.DataFrame(rows, columns=cols),
                "total_observations": int(total_obs or 0),
                "distinct_apps": int(distinct_apps or 0),
            },
            None,
        )
    except Exception as exc:
        return None, f"PostgreSQL Live Updates gagal dimuat ({type(exc).__name__}: {exc})"
    finally:
        if conn is not None:
            conn.close()


def fetch_mongo_cohort_metadata(
    cfg: Settings,
) -> tuple[dict[str, Any] | None, str | None]:
    """Ambil tags cohort, frekuensi tags ($unwind), dan map metadata cohort dari MongoDB."""
    client = None
    try:
        client, db = get_mongo_db(cfg)
        tag_pipeline = [
            {"$match": {"tags": "Indie"}},
            {"$project": {"_id": 0, "app_id": 1, "tags": 1}},
            {"$unwind": "$tags"},
            {
                "$group": {
                    "_id": "$tags",
                    "game_count": {"$sum": 1},
                    "app_ids": {"$push": "$app_id"},
                }
            },
            {"$sort": {"game_count": -1, "_id": 1}},
        ]
        tag_agg = list(db["game_metadata"].aggregate(tag_pipeline))

        docs_cursor = db["game_metadata"].find(
            {"tags": "Indie"},
            {"_id": 0, "app_id": 1, "description": 1, "tags": 1},
        )
        tags_by_app: dict[int, list[str]] = {}
        desc_by_app: dict[int, str] = {}
        for doc in docs_cursor:
            app_id = int(doc["app_id"])
            tags_by_app[app_id] = list(doc.get("tags") or [])
            desc_by_app[app_id] = str(doc.get("description") or "")

        return (
            {
                "tag_agg": tag_agg,
                "ordered_tags": [str(item["_id"]) for item in tag_agg],
                "tags_by_app": tags_by_app,
                "desc_by_app": desc_by_app,
            },
            None,
        )
    except Exception as exc:
        return None, f"MongoDB game_metadata tidak dapat diakses ({type(exc).__name__}: {exc})"
    finally:
        if client is not None:
            client.close()


def fetch_mongo_media_map(
    cfg: Settings,
    app_ids: list[int],
) -> tuple[dict[int, dict[str, Any]] | None, str | None]:
    """Ambil dokumen `game_media` dari MongoDB untuk daftar `app_id` tertentu."""
    if not app_ids:
        return {}, None
    client = None
    try:
        client, db = get_mongo_db(cfg)
        cursor = db["game_media"].find(
            {"app_id": {"$in": [int(aid) for aid in app_ids]}},
            {"_id": 0},
        )
        return {int(doc["app_id"]): doc for doc in cursor}, None
    except Exception as exc:
        return None, f"MongoDB game_media tidak dapat diakses ({type(exc).__name__}: {exc})"
    finally:
        if client is not None:
            client.close()


def fetch_mongo_etl_logs(cfg: Settings) -> tuple[dict[str, Any] | None, str | None]:
    """Ambil run terakhir per tahap dan waktu sinkron polling terakhir dari `etl_logs`."""
    client = None
    try:
        client, db = get_mongo_db(cfg)
        pipeline = [
            {"$sort": {"started_at": -1}},
            {"$group": {"_id": "$stage", "doc": {"$first": "$$ROOT"}}},
            {"$replaceRoot": {"newRoot": "$doc"}},
            {"$sort": {"started_at": -1}},
        ]
        latest_per_stage = list(db["etl_logs"].aggregate(pipeline))
        latest_overall = db["etl_logs"].find_one(sort=[("started_at", -1)])
        latest_polling = db["etl_logs"].find_one(
            {"stage": "polling"}, sort=[("started_at", -1)]
        )
        return (
            {
                "latest_per_stage": latest_per_stage,
                "latest_overall": latest_overall,
                "latest_polling": latest_polling,
            },
            None,
        )
    except Exception as exc:
        return None, f"MongoDB etl_logs tidak dapat diakses ({type(exc).__name__}: {exc})"
    finally:
        if client is not None:
            client.close()


def compute_tag_saturation_df(
    tag_agg: list[dict[str, Any]],
    ratio_by_app: dict[int, float],
) -> pd.DataFrame:
    """Gabungkan hasil `$unwind tags` MongoDB dengan rata-rata `positive_ratio` dari PG."""
    rows: list[dict[str, Any]] = []
    for entry in tag_agg:
        tag_name = str(entry["_id"])
        if tag_name == "Indie":
            # Seluruh kohort pasti memiliki tag 'Indie', sehingga dikecualikan dari saturasi tag niche.
            continue
        app_ids = entry.get("app_ids") or []
        ratios = [ratio_by_app[int(aid)] for aid in app_ids if int(aid) in ratio_by_app]
        if not ratios:
            continue
        game_count = int(entry["game_count"])
        avg_ratio = sum(ratios) / len(ratios)
        rows.append(
            {
                "tag": tag_name,
                "game_count": game_count,
                "avg_positive_ratio": avg_ratio,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    median_count = float(df["game_count"].median())
    df["niche_berkualitas"] = (df["game_count"] <= median_count) & (
        df["avg_positive_ratio"] >= 0.80
    )
    return df


# ---------------------------------------------------------------------------
# Caching ringan (maksimal DASHBOARD_REFRESH_SECONDS sesuai DB-01)
# ---------------------------------------------------------------------------


def _get_cache_ttl(cfg: Settings) -> int:
    return max(int(cfg.dashboard_refresh_seconds), 1)


@st.cache_data(ttl=5, show_spinner=False)
def _cached_game_stats(ttl_bucket: int) -> tuple[pd.DataFrame | None, str | None]:
    del ttl_bucket
    return fetch_pg_game_stats(get_settings())


@st.cache_data(ttl=5, show_spinner=False)
def _cached_cohort_metadata(ttl_bucket: int) -> tuple[dict[str, Any] | None, str | None]:
    del ttl_bucket
    return fetch_mongo_cohort_metadata(get_settings())


def _current_ttl_bucket(cfg: Settings) -> int:
    ttl = _get_cache_ttl(cfg)
    return int(datetime.now(timezone.utc).timestamp()) // ttl


# ---------------------------------------------------------------------------
# Komponen UI Streamlit
# ---------------------------------------------------------------------------


def _format_dt(dt_val: Any) -> str:
    if dt_val is None or (isinstance(dt_val, float) and pd.isna(dt_val)):
        return "Belum ada"
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is None:
            dt_val = dt_val.replace(tzinfo=timezone.utc)
        return dt_val.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    return str(dt_val)


def _snippet(text: str, max_len: int = 200) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        return "(Deskripsi tidak tersedia di dataset)"
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 3].rstrip() + "..."


def _render_game_card(
    item: dict[str, Any],
    description: str,
    media_doc: dict[str, Any] | None,
) -> None:
    app_id = item["app_id"]
    header_url = ""
    if media_doc and media_doc.get("status") == "ok":
        header_url = str(media_doc.get("header_image_url") or "").strip()
    store_url = (
        str(media_doc.get("store_url")).strip()
        if media_doc and media_doc.get("store_url")
        else f"https://store.steampowered.com/app/{app_id}/"
    )
    img_src = header_url if header_url else PLACEHOLDER_IMAGE_SVG
    price_label = "Gratis" if item["price_usd"] == 0.0 else f"${item['price_usd']:.2f}"
    platforms = [
        name
        for name, col in (("Windows", "win"), ("Mac", "mac"), ("Linux", "linux"))
        if item[col]
    ]

    with st.container(border=True):
        col_img, col_body = st.columns([1.15, 2.35], vertical_alignment="top")
        with col_img:
            st.image(img_src, width="stretch")
            if not header_url:
                st.caption("Foto belum di-enrichment / placeholder")
        with col_body:
            title_col, badge_col = st.columns([4, 1])
            with title_col:
                st.markdown(f"### {item['title']}")
            with badge_col:
                if item["is_hidden_gem"]:
                    st.markdown(":green-badge[Hidden Gem]")

            st.caption(
                f"Skor: **{item['score']:.1f}** | "
                f"Positive Ratio: **{item['positive_ratio'] * 100:.1f}%** | "
                f"Reviews: **{item['total_reviews']:,}** | "
                f"Harga: **{price_label}** | "
                f"Platform: {', '.join(platforms) if platforms else '-'}"
            )
            st.write(_snippet(description, 200))
            if item["tags"]:
                shown_tags = ", ".join(item["tags"][:8])
                if len(item["tags"]) > 8:
                    shown_tags += f" (+{len(item['tags']) - 8})"
                st.caption(f"**Tags:** {shown_tags}")
            st.info(item["reason"])
            st.link_button("Lihat di Steam Store", store_url)


def render_recommendation_section(cfg: Settings) -> None:
    """Panel (1) Mode Temukan Game Untukmu — berada di luar fragment agar input tidak ter-reset."""
    st.subheader("1. Temukan Game Untukmu")

    bucket = _current_ttl_bucket(cfg)
    games_df, pg_err = _cached_game_stats(bucket)
    mongo_meta, mongo_err = _cached_cohort_metadata(bucket)

    if pg_err:
        st.error(pg_err)
    if mongo_err:
        st.error(mongo_err)
    if pg_err or mongo_err or games_df is None or mongo_meta is None:
        st.warning("Mode rekomendasi membutuhkan PostgreSQL dan MongoDB aktif secara bersamaan.")
        return

    ordered_tags: list[str] = mongo_meta["ordered_tags"]

    with st.container(border=True):
        col1, col2, col3 = st.columns([2.2, 1.0, 1.3])
        with col1:
            selected_tags = st.multiselect(
                "Tags Favorit (urut frekuensi di cohort Indie, ketik untuk mencari)",
                options=ordered_tags,
                key="rec_selected_tags",
                placeholder="Pilih satu atau lebih tag (opsional)...",
            )
        with col2:
            max_price = st.number_input(
                "Harga Maksimal (USD)",
                min_value=0.0,
                value=None,
                step=1.0,
                key="rec_max_price",
                placeholder="Kosong = tanpa batas",
                help="Kosongkan untuk tanpa batas harga. Game gratis selalu lolos.",
            )
        with col3:
            selected_platforms = st.multiselect(
                "Platform yang Didukung",
                options=["Windows", "Mac", "Linux"],
                default=["Windows"],
                key="rec_platforms",
                placeholder="Semua platform",
            )

    ranked = filter_and_rank_recommendations(
        games_df,
        mongo_meta["tags_by_app"],
        selected_tags=selected_tags,
        max_price=max_price,
        selected_platforms=selected_platforms,
        limit=20,
    )

    if not ranked:
        st.info(
            "Belum ada game indie yang cocok dengan seluruh kombinasi filter tersebut. "
            "Coba kurangi jumlah tag favorit, naikkan atau kosongkan batas harga maksimal, "
            "atau longgarkan pilihan platform."
        )
        return

    st.caption(
        f"Menampilkan **{len(ranked)}** rekomendasi terbaik (maksimal 20) "
        "berdasarkan skor rule-based D-6."
    )

    media_map, media_err = fetch_mongo_media_map(cfg, [item["app_id"] for item in ranked])
    if media_err:
        st.warning(f"Media Steam gagal dimuat ({media_err}); menampilkan placeholder.")
        media_map = {}

    for item in ranked:
        _render_game_card(
            item=item,
            description=mongo_meta["desc_by_app"].get(item["app_id"], ""),
            media_doc=(media_map or {}).get(item["app_id"]),
        )


def render_live_header_status(cfg: Settings) -> None:
    """Status ETL terakhir, waktu sinkron Live Updates, dan indikator auto-refresh (DB-01)."""
    logs_data, mongo_err = fetch_mongo_etl_logs(cfg)
    col_status, col_sync, col_refresh = st.columns(3)

    if mongo_err or logs_data is None:
        col_status.error(mongo_err or "Status ETL tidak tersedia")
        col_sync.info("Sinkron Live Updates: -")
    else:
        latest = logs_data["latest_overall"]
        polling_doc = logs_data["latest_polling"]
        if latest:
            col_status.metric(
                "Status ETL Terakhir",
                f"{latest.get('stage', '-')} ({latest.get('status', '-')})",
                delta=_format_dt(latest.get("finished_at")),
            )
        else:
            col_status.metric("Status ETL Terakhir", "Belum ada run")

        if polling_doc:
            col_sync.metric(
                "Sinkron Live Updates Terakhir",
                _format_dt(polling_doc.get("finished_at")),
                delta=f"status: {polling_doc.get('status', '-')}",
            )
        else:
            col_sync.metric("Sinkron Live Updates Terakhir", "Belum ada polling")

    col_refresh.metric(
        "Auto-Refresh Dasbor",
        f"Aktif tiap {cfg.dashboard_refresh_seconds} dtk",
        delta=f"Diperbarui {_format_dt(datetime.now(timezone.utc))}",
    )


def render_analytics_panels(cfg: Settings) -> None:
    """Panel (2)..(5) di dalam st.fragment agar refresh berkala tanpa mereset form REC-01."""
    # (2) Baris KPI
    st.subheader("2. Ringkasan Cohort Indie (KPI)")
    kpis, kpi_err = fetch_pg_kpis(cfg)
    if kpi_err or kpis is None:
        st.error(kpi_err or "Gagal memuat KPI dari PostgreSQL.")
    else:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total Game Indie", f"{kpis['total_games']:,}")
        k2.metric("Rata-rata Positive Ratio", f"{kpis['avg_positive_ratio'] * 100:.2f}%")
        k3.metric("Median Total Reviews (D-2)", f"{kpis['median_total_reviews']:,.0f}")
        k4.metric("Jumlah Hidden Gems (D-3)", f"{kpis['hidden_gem_count']:,}")

    st.divider()

    # (3) Saturasi Tags + Harga vs Positive Ratio
    st.subheader("3. Saturasi Tags & Harga vs Positive Ratio")
    col_tags, col_price = st.columns(2)

    games_df, pg_games_err = fetch_pg_game_stats(cfg)
    mongo_meta, mongo_err = fetch_mongo_cohort_metadata(cfg)

    with col_tags:
        st.markdown("**Saturasi Tags Niche (MongoDB `$unwind` + PG `positive_ratio`)**")
        if mongo_err or mongo_meta is None:
            st.error(mongo_err or "MongoDB tags tidak tersedia.")
        elif pg_games_err or games_df is None:
            st.error(pg_games_err or "Data positive_ratio dari PostgreSQL tidak tersedia.")
        else:
            ratio_by_app = dict(
                zip(games_df["app_id"].astype(int), games_df["positive_ratio"].astype(float))
            )
            sat_df = compute_tag_saturation_df(mongo_meta["tag_agg"], ratio_by_app)
            if sat_df.empty:
                st.info("Belum ada data saturasi tag.")
            else:
                fig_tags = px.scatter(
                    sat_df,
                    x="game_count",
                    y="avg_positive_ratio",
                    color="niche_berkualitas",
                    hover_name="tag",
                    labels={
                        "game_count": "Jumlah Game pada Tag",
                        "avg_positive_ratio": "Rata-rata Positive Ratio",
                        "niche_berkualitas": "Niche Volume Kecil & Berkualitas",
                    },
                    color_discrete_map={True: "#10b981", False: "#64748b"},
                    height=380,
                )
                fig_tags.add_hline(y=0.80, line_dash="dash", line_color="#10b981")
                fig_tags.update_yaxes(tickformat=".0%")
                fig_tags.update_layout(margin=dict(l=10, r=10, t=20, b=10))
                st.plotly_chart(fig_tags, width="stretch")
                st.caption(
                    "Tag 'Indie' dikecualikan karena dimiliki seluruh cohort. "
                    "Titik hijau menandai tag bervolume kecil–menengah dengan rata-rata positive ratio ≥ 80%."
                )

    with col_price:
        st.markdown("**Harga (USD) vs Positive Ratio**")
        if pg_games_err or games_df is None:
            st.error(pg_games_err or "PostgreSQL tidak tersedia.")
        else:
            fig_price = go.Figure()
            non_hg = games_df[~games_df["is_hidden_gem"]]
            hg = games_df[games_df["is_hidden_gem"]]
            fig_price.add_trace(
                go.Scattergl(
                    x=non_hg["price_usd"],
                    y=non_hg["positive_ratio"],
                    mode="markers",
                    name="Non-Hidden Gem",
                    text=non_hg["title"],
                    marker=dict(size=4, color="#64748b", opacity=0.45),
                )
            )
            fig_price.add_trace(
                go.Scattergl(
                    x=hg["price_usd"],
                    y=hg["positive_ratio"],
                    mode="markers",
                    name="Hidden Gem (D-3)",
                    text=hg["title"],
                    marker=dict(size=5, color="#10b981", opacity=0.75),
                )
            )
            max_x = max(float(games_df["price_usd"].max()), 10.0)
            fig_price.add_shape(
                type="rect",
                x0=0,
                x1=max_x,
                y0=0.80,
                y1=1.0,
                line=dict(color="#10b981", width=2, dash="dash"),
            )
            fig_price.add_annotation(
                x=max_x * 0.98,
                y=0.98,
                text="Zona Hidden Gem (ratio ≥ 80% & reviews < median)",
                showarrow=False,
                xanchor="right",
                font=dict(color="#10b981", size=11),
            )
            fig_price.update_layout(
                xaxis_title="Harga (USD)",
                yaxis_title="Positive Ratio",
                yaxis=dict(tickformat=".0%", range=[0, 1.05]),
                height=380,
                margin=dict(l=10, r=10, t=20, b=10),
            )
            st.plotly_chart(fig_price, width="stretch")

    st.divider()

    # (4) Tren Rekomendasi + Top 10
    st.subheader("4. Tren Rekomendasi & Top 10 Game")
    col_trend, col_top10 = st.columns(2)

    with col_trend:
        st.markdown("**Tren Jumlah Rekomendasi per Bulan**")
        trend_df, trend_err = fetch_pg_monthly_trend(cfg)
        if trend_err or trend_df is None:
            st.error(trend_err or "Gagal memuat tren rekomendasi.")
        elif trend_df.empty:
            st.info("Belum ada data rekomendasi pada tabel `recommendations`.")
        else:
            fig_trend = px.area(
                trend_df,
                x="month",
                y="total_recommendations",
                labels={"month": "Bulan", "total_recommendations": "Jumlah Rekomendasi"},
                height=360,
            )
            fig_trend.update_layout(margin=dict(l=10, r=10, t=20, b=10))
            st.plotly_chart(fig_trend, width="stretch")

    with col_top10:
        st.markdown("**Top 10 Game Indie (`total_recommendations` Terbanyak)**")
        top10_df, top10_err = fetch_pg_top10(cfg)
        if top10_err or top10_df is None:
            st.error(top10_err or "Gagal memuat Top 10 game.")
        elif top10_df.empty:
            st.info("Belum ada data Top 10 game.")
        else:
            fig_top = px.bar(
                top10_df.sort_values("total_recommendations", ascending=True),
                x="total_recommendations",
                y="title",
                orientation="h",
                labels={"total_recommendations": "Total Recommendations", "title": "Game"},
                height=360,
            )
            fig_top.update_layout(margin=dict(l=10, r=10, t=20, b=10))
            st.plotly_chart(fig_top, width="stretch")

    st.divider()

    # (5) Daftar Hidden Gems lengkap, Log ETL terakhir, Panel Live Updates
    st.subheader("5. Daftar Hidden Gems, Log ETL, & Live Updates")

    st.markdown("**Daftar Hidden Gems Lengkap (Terpaginasi)**")
    page_size = 20
    if "hg_page_input" not in st.session_state:
        st.session_state["hg_page_input"] = 1

    hg_res, hg_err = fetch_pg_hidden_gems_page(
        cfg, page=int(st.session_state["hg_page_input"]), page_size=page_size
    )
    if hg_err or hg_res is None:
        st.error(hg_err or "Gagal memuat daftar hidden gems.")
    else:
        hg_df, hg_total = hg_res
        total_pages = max((hg_total + page_size - 1) // page_size, 1)
        if st.session_state["hg_page_input"] > total_pages:
            st.session_state["hg_page_input"] = total_pages
        p_col1, p_col2, _ = st.columns([1.2, 2, 3])
        with p_col1:
            current_page = int(
                st.number_input(
                    "Halaman",
                    min_value=1,
                    max_value=total_pages,
                    step=1,
                    key="hg_page_input",
                )
            )
        with p_col2:
            st.caption(
                f"Total **{hg_total:,}** hidden gem | Halaman **{current_page}** dari **{total_pages}**"
            )

        if hg_df.empty:
            st.info("Belum ada hidden gem.")
        else:
            media_map, media_err = fetch_mongo_media_map(
                cfg, [int(aid) for aid in hg_df["app_id"].tolist()]
            )
            if media_err:
                st.warning(f"Foto dari MongoDB game_media tidak tersedia ({media_err}).")
                media_map = {}

            for row in hg_df.itertuples(index=False):
                aid = int(row.app_id)
                media = (media_map or {}).get(aid)
                thumb = (
                    str(media.get("header_image_url")).strip()
                    if media and media.get("status") == "ok" and media.get("header_image_url")
                    else PLACEHOLDER_IMAGE_SVG
                )
                store_url = (
                    str(media.get("store_url")).strip()
                    if media and media.get("store_url")
                    else f"https://store.steampowered.com/app/{aid}/"
                )
                c_img, c_info, c_link = st.columns([1.0, 3.2, 1.0], vertical_alignment="center")
                with c_img:
                    st.image(thumb, width="stretch")
                with c_info:
                    price_str = "Gratis" if row.price_usd == 0 else f"${row.price_usd:.2f}"
                    st.markdown(
                        f"**{row.title}** (`app_id`: {aid}) — "
                        f"Positive Ratio: **{row.positive_ratio * 100:.2f}%** | "
                        f"Reviews: **{int(row.total_reviews):,}** | "
                        f"Harga: **{price_str}** | "
                        f"Recommendations: **{int(row.total_recommendations):,}**"
                    )
                with c_link:
                    st.link_button("Steam", store_url)

    st.divider()
    col_logs, col_live = st.columns(2)

    with col_logs:
        st.markdown("**Log ETL Terakhir per Tahap (MongoDB `etl_logs`)**")
        logs_data, logs_err = fetch_mongo_etl_logs(cfg)
        if logs_err or logs_data is None:
            st.error(logs_err or "Gagal memuat log ETL.")
        elif not logs_data["latest_per_stage"]:
            st.info("Belum ada catatan di koleksi `etl_logs`.")
        else:
            logs_df = pd.DataFrame(
                [
                    {
                        "stage": doc.get("stage"),
                        "status": doc.get("status"),
                        "rows_read": doc.get("rows_read"),
                        "rows_loaded": doc.get("rows_loaded"),
                        "rows_discarded": doc.get("rows_discarded"),
                        "finished_at": _format_dt(doc.get("finished_at")),
                        "notes": doc.get("notes", ""),
                    }
                    for doc in logs_data["latest_per_stage"]
                ]
            )
            st.dataframe(logs_df, width="stretch", hide_index=True)

    with col_live:
        st.markdown("**Live Updates (Sinkron Polling & Perubahan Harga Terakhir)**")
        logs_data, logs_err = fetch_mongo_etl_logs(cfg)
        if logs_err:
            st.warning(f"Waktu sinkron dari MongoDB tidak tersedia ({logs_err}).")
        elif logs_data and logs_data["latest_polling"]:
            poll_doc = logs_data["latest_polling"]
            st.caption(
                f"Waktu sinkron polling terakhir: **{_format_dt(poll_doc.get('finished_at'))}** "
                f"(status: `{poll_doc.get('status')}`)"
            )
        else:
            st.caption("Waktu sinkron polling terakhir: belum ada run polling.")

        live_res, live_err = fetch_pg_live_updates(cfg, limit=20)
        if live_err or live_res is None:
            st.error(live_err or "Gagal memuat `live_updates` dari PostgreSQL.")
        else:
            live_df: pd.DataFrame = live_res["df"]
            st.caption(
                f"Total observasi di `live_updates`: **{live_res['total_observations']:,}** "
                f"pada **{live_res['distinct_apps']:,}** game."
            )
            if live_df.empty:
                st.info("Belum ada data pada tabel `live_updates`.")
            else:
                st.dataframe(live_df, width="stretch", hide_index=True)


def main() -> None:
    """Entry point aplikasi Streamlit ELITIS."""
    cfg = get_settings()
    refresh_seconds = max(int(cfg.dashboard_refresh_seconds), 1)

    favicon_path = Path(__file__).resolve().parent / "favicon.ico"
    page_icon: str = str(favicon_path) if favicon_path.exists() else "🎮"

    st.set_page_config(
        page_title="Engine for Locating Indie Treasures in Steam",
        page_icon=page_icon,
        layout="wide",
    )
    st.title("Engine for Locating Indie Treasures in Steam")
    st.caption(
        "Dasbor penemuan game indie niche berkualitas di Steam berbasis arsitektur hybrid PostgreSQL + MongoDB."
    )

    @st.fragment(run_every=refresh_seconds)
    def _header_fragment() -> None:
        render_live_header_status(cfg)

    _header_fragment()
    st.divider()

    # (1) Form rekomendasi di luar fragment agar pilihan & scroll tidak direset tiap 5 detik (DB-06)
    render_recommendation_section(cfg)
    st.divider()

    # (2)-(5) Seluruh panel data berjalan di st.fragment(run_every=DASHBOARD_REFRESH_SECONDS)
    @st.fragment(run_every=refresh_seconds)
    def _panels_fragment() -> None:
        render_analytics_panels(cfg)

    _panels_fragment()


if __name__ == "__main__":
    main()
