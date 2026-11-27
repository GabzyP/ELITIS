"""Entry point aplikasi Streamlit ELITIS (navigasi 2 halaman: Monitoring Pipeline & Temukan Game)."""

from __future__ import annotations

from pathlib import Path
import sys

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.shared import (  
    PLACEHOLDER_IMAGE_SVG,
    PLATFORM_COL_MAP,
    build_recommendation_reason,
    compute_recommendation_score,
    compute_tag_saturation_df,
    fetch_mongo_cohort_metadata,
    fetch_mongo_etl_logs,
    fetch_mongo_media_map,
    fetch_pg_game_stats,
    fetch_pg_hidden_gems_page,
    fetch_pg_kpis,
    fetch_pg_live_updates,
    fetch_pg_monthly_trend,
    fetch_pg_top10,
    filter_and_rank_recommendations,
    render_analytics_panels,
    render_live_header_status,
    render_recommendation_section,
)


def main() -> None:
    """Konfigurasi halaman multipage Streamlit ELITIS dan jalankan halaman aktif."""
    favicon_path = Path(__file__).resolve().parent / "favicon.ico"
    page_icon: str = str(favicon_path) if favicon_path.exists() else "🎮"

    st.set_page_config(
        page_title="Engine for Locating Indie Treasures in Steam",
        page_icon=page_icon,
        layout="wide",
    )

    page = st.navigation(
        [
            st.Page(
                "app_pages/monitoring.py",
                title="Monitoring Pipeline",
                icon=":material/monitoring:",
                url_path="monitoring",
                default=True,
                help=(
                    "Pantau status ETL, KPI cohort Indie, grafik analitik, "
                    "daftar hidden gems lengkap, Live Updates, dan Log ETL dengan auto-refresh 5 detik."
                ),
            ),
            st.Page(
                "app_pages/temukan_game.py",
                title="Temukan Game",
                icon=":material/sports_esports:",
                url_path="temukan-game",
                help=(
                    "Cari rekomendasi game indie terbaik sesuai tags favorit, "
                    "batas harga maksimal, dan platform menggunakan skor rule-based D-6."
                ),
            ),
        ],
        position="top",
    )

    st.title("Engine for Locating Indie Treasures in Steam")
    st.caption(
        "Dasbor penemuan game indie niche berkualitas di Steam berbasis arsitektur hybrid PostgreSQL + MongoDB."
    )

    page.run()


if __name__ == "__main__":
    main()
