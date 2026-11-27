"""Halaman default: Monitoring Pipeline ELITIS (header status, KPI, analitik, hidden gems, Live Updates, Log ETL)."""

import streamlit as st

from dashboard.shared import render_analytics_panels, render_live_header_status
from etl.config import get_settings

cfg = get_settings()
refresh_seconds = max(int(cfg.dashboard_refresh_seconds), 1)


@st.fragment(run_every=refresh_seconds)
def _header_fragment() -> None:
    render_live_header_status(cfg)


_header_fragment()
st.divider()


@st.fragment(run_every=refresh_seconds)
def _panels_fragment() -> None:
    render_analytics_panels(cfg)


_panels_fragment()
