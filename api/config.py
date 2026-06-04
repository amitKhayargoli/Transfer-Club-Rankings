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

MIN_YEAR = 2000
MAX_YEAR = 2025
MIN_TRANSFERS = 3
MIN_BUY_FEE = 100_000  # Minimum buy fee (€) to include a pair in ROI calculations
                       # Prevents near-free transfers (€1K buys) from inflating ROI

# ── Composite Score Weights ────────────────────────────────────────────────

WEIGHT_MEDIAN_ROI = 0.35
WEIGHT_TOTAL_PROFIT = 0.25
WEIGHT_HIT_RATE = 0.25
WEIGHT_VALUE_CREATION = 0.15
