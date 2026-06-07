"""
Configuration for the FastAPI backend.
"""

import os
from pathlib import Path

# ── Paths ───────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DATA_CLEAN_DIR = PROJECT_ROOT / "data" / "clean"

# ── Database ────────────────────────────────────────────────────────────────

# Default to SQLite for local development; override with DATABASE_URL env var
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite+aiosqlite:///{PROJECT_ROOT / 'data' / 'transfer_roi.db'}",
)

# ── API ─────────────────────────────────────────────────────────────────────

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))

# ── Data Filtering ──────────────────────────────────────────────────────────

# Scrape boundary: store everything from this range
# Set to 2000 to capture full career arcs (CR7's Man Utd→RM 2009, Sporting→ManUtd 2003, etc.)
MIN_YEAR = 2000
MAX_YEAR = 2026
MIN_TRANSFERS = 3
MIN_BUY_FEE = 100_000  # Minimum buy fee (€) to include a pair in ROI calculations
                       # Prevents near-free transfers (€1K buys) from inflating ROI

# Analytical boundary: separate from scrape boundary
# The dashboard will precompute rankings for these windows so users can
# slice by different eras without re-scraping.
ANALYTICS_WINDOWS = [2010, 2015, 2020]
DEFAULT_ANALYTICS_WINDOW = 2015  # Default dashboard filter (modern scouting era)

# ── Composite Score Weights ────────────────────────────────────────────────

WEIGHT_MEDIAN_ROI = 0.35
WEIGHT_TOTAL_PROFIT = 0.25
WEIGHT_HIT_RATE = 0.25
WEIGHT_VALUE_CREATION = 0.15
WEIGHT_ANNUALIZED_ROI = 0.10
WEIGHT_PROFIT_PER_DEAL = 0.10

# New: updated composite weights (sum must equal 1.0)
WEIGHT_MEDIAN_ROI_NEW = 0.25
WEIGHT_TOTAL_PROFIT_NEW = 0.20
WEIGHT_HIT_RATE_NEW = 0.20
WEIGHT_VALUE_CREATION_NEW = 0.15
WEIGHT_ANNUALIZED_ROI_NEW = 0.10
WEIGHT_PROFIT_PER_DEAL_NEW = 0.10
