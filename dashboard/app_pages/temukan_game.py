"""Halaman kedua: Mode Temukan Game Untukmu (REC-01..REC-06, state bertahan lintas halaman)."""

from dashboard.shared import render_recommendation_section
from etl.config import get_settings

cfg = get_settings()
render_recommendation_section(cfg)
