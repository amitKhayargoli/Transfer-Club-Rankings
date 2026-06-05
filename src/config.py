"""
Configuration constants and paths for Transfer ROI Rankings.
"""

import os
from pathlib import Path

# ── Project Paths ──────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CLEAN_DIR = DATA_DIR / "clean"

# ── Kaggle Dataset ─────────────────────────────────────────────────────────

KAGGLE_DATASET = "davidcariboo/player-scores"
CLEANED_PAIRS = CLEAN_DIR / "pairs.csv"
CLEANED_CLUB_STATS = CLEAN_DIR / "club_stats.csv"

# ── Data Filtering ─────────────────────────────────────────────────────────

MIN_YEAR = 2000
MAX_YEAR = 2025

# Free transfers and undisclosed fees have fee = 0 or NaN.
# We exclude them from ROI calculations but count them in volume.
MIN_TRANSFERS = 10  # Minimum transfers for a club to be ranked

# ── Composite Score Weights ────────────────────────────────────────────────

WEIGHT_MEDIAN_ROI = 0.35
WEIGHT_TOTAL_PROFIT = 0.25
WEIGHT_HIT_RATE = 0.25
WEIGHT_VALUE_CREATION = 0.15

# ── CSV File Names (Kaggle dataset) ───────────────────────────────────────

TRANSFERS_FILE = "transfers.csv"
PLAYERS_FILE = "players.csv"
CLUBS_FILE = "clubs.csv"
VALUATIONS_FILE = "player_valuations.csv"
