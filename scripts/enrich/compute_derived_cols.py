#!/usr/bin/env python3
"""
Compute Derived Columns — Hidden Gem Model, Part 6 (Data Collection Spec).

Adds and populates the following computed columns:

  players.position_bucket     — CF/LW/RW/AM/CM/DM/LB/RB/CB/GK/Other
  players.citizenship_region  — South America/Europe/Africa/Asia/Other
  players.agent_cluster       — Mega/Active/Small/Solo/Unknown

  transfers.transfer_window   — summer/winter
  transfers.is_gem            — 1 if roi_pct >= 100
  transfers.gem_tier          — 0=none, 1=Silver(100%), 2=Gold(500%), 3=Elite(1000%)

Usage:
    python scripts/enrich/compute_derived_cols.py
    python scripts/enrich/compute_derived_cols.py --dry-run
"""

import argparse
import logging
import sqlite3
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("derived_cols")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "transfer_roi.db"

# ── Position Bucket Mapping ────────────────────────────────────────────────

POSITION_MAP = {
    "Centre-Forward": "CF",
    "Second Striker": "CF",
    "Attack": "CF",
    "Left Winger": "LW",
    "Left Midfield": "LW",
    "Right Winger": "RW",
    "Right Midfield": "RW",
    "Attacking Midfield": "AM",
    "Central Midfield": "CM",
    "Midfield": "CM",
    "Defensive Midfield": "DM",
    "Left-Back": "LB",
    "Right-Back": "RB",
    "Centre-Back": "CB",
    "Defender": "CB",
    "Goalkeeper": "GK",
}


# ── Citizenship Region Mapping ─────────────────────────────────────────────

SOUTH_AMERICA = {
    "Argentina", "Bolivia", "Brazil", "Chile", "Colombia", "Ecuador",
    "Guyana", "Paraguay", "Peru", "Suriname", "Uruguay", "Venezuela",
}

AFRICA = {
    "Algeria", "Angola", "Benin", "Botswana", "Burkina Faso", "Burundi",
    "Cameroon", "Cape Verde", "Central African Republic", "Chad", "Comoros",
    "Congo", "DR Congo", "Djibouti", "Egypt", "Equatorial Guinea", "Eritrea",
    "Ethiopia", "Gabon", "Gambia", "Ghana", "Guinea", "Guinea-Bissau",
    "Ivory Coast", "Kenya", "Lesotho", "Liberia", "Libya", "Madagascar",
    "Malawi", "Mali", "Mauritania", "Mauritius", "Morocco", "Mozambique",
    "Namibia", "Niger", "Nigeria", "Rwanda", "Sao Tome and Principe",
    "Senegal", "Seychelles", "Sierra Leone", "Somalia", "South Africa",
    "South Sudan", "Sudan", "Swaziland", "Tanzania", "Togo", "Tunisia",
    "Uganda", "Zambia", "Zimbabwe",
}

ASIA = {
    "Afghanistan", "Armenia", "Australia", "Azerbaijan", "Bahrain",
    "Bangladesh", "Bhutan", "Brunei", "Cambodia", "China", "Cyprus",
    "East Timor", "Georgia", "India", "Indonesia", "Iran", "Iraq",
    "Israel", "Japan", "Jordan", "Kazakhstan", "Kuwait", "Kyrgyzstan",
    "Laos", "Lebanon", "Malaysia", "Maldives", "Mongolia", "Myanmar",
    "Nepal", "North Korea", "Oman", "Pakistan", "Palestine", "Philippines",
    "Qatar", "Saudi Arabia", "Singapore", "South Korea", "Sri Lanka",
    "Syria", "Taiwan", "Tajikistan", "Thailand", "Turkey", "Turkmenistan",
    "United Arab Emirates", "Uzbekistan", "Vietnam", "Yemen",
}

EUROPE = {
    "Albania", "Andorra", "Austria", "Belarus", "Belgium", "Bosnia and Herzegovina",
    "Bulgaria", "Croatia", "Czech Republic", "Denmark", "England", "Estonia",
    "Faroe Islands", "Finland", "France", "Germany", "Greece", "Hungary",
    "Iceland", "Italy", "Kosovo", "Latvia", "Liechtenstein", "Lithuania",
    "Luxembourg", "Malta", "Moldova", "Monaco", "Montenegro", "Netherlands",
    "North Macedonia", "Norway", "Poland", "Portugal", "Ireland", "Romania",
    "Russia", "San Marino", "Scotland", "Serbia", "Slovakia", "Slovenia",
    "Spain", "Sweden", "Switzerland", "Ukraine", "United Kingdom", "Vatican City",
    "Wales",
}


def get_region(citizenship: str | None) -> str | None:
    """Map a citizenship string to a region bucket."""
    if not citizenship:
        return None

    # Handle comma-separated dual citizenships — use the first one
    primary = citizenship.split(",")[0].strip()

    if primary in SOUTH_AMERICA:
        return "South America"
    if primary in AFRICA:
        return "Africa"
    if primary in ASIA:
        return "Asia"
    if primary in EUROPE:
        return "Europe"
    return "Other"


def compute_agent_cluster(conn: sqlite3.Connection) -> dict[str, str]:
    """Compute agent clusters by counting player representation.

    Returns a dict of {agent_name: cluster_label}.
    """
    rows = conn.execute("""
        SELECT agent_name, COUNT(*) as cnt
        FROM players
        WHERE agent_name IS NOT NULL AND agent_name NOT IN ('no agent', '')
        GROUP BY agent_name
        ORDER BY cnt DESC
    """).fetchall()

    clusters: dict[str, str] = {}

    for idx, (agent_name, count) in enumerate(rows):
        if idx < 10:
            clusters[agent_name] = "Mega"
        elif count >= 5:
            clusters[agent_name] = "Active"
        elif count >= 2:
            clusters[agent_name] = "Small"
        else:
            clusters[agent_name] = "Solo"

    clusters["no agent"] = "Solo"
    # Empty string handled via the 'no agent' query below

    return clusters


def compute_transfer_window(transfer_date: str | None) -> str | None:
    """Determine if a transfer happened in summer or winter window."""
    if not transfer_date:
        return None
    try:
        month = int(transfer_date.split("-")[1])
        # Summer: July (7) - December (12)
        # Winter: January (1) - June (6)
        return "summer" if month >= 7 else "winter"
    except (IndexError, ValueError):
        return None


def compute_gem_tier(roi_pct: float | None) -> int:
    """Classify a buy-sell pair by ROI tier."""
    if roi_pct is None or roi_pct < 0:
        return 0
    if roi_pct < 100:
        return 0
    if roi_pct < 500:
        return 1  # Silver
    if roi_pct < 1000:
        return 2  # Gold
    return 3  # Elite


# ── Main Logic ────────────────────────────────────────────────────────────

def add_columns(conn: sqlite3.Connection, dry_run: bool = False):
    """Add derived columns to the database tables."""
    changes = 0

    # ── players.position_bucket ──
    logger.info("Adding players.position_bucket...")
    if not dry_run:
        try:
            conn.execute("ALTER TABLE players ADD COLUMN position_bucket TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            logger.info("  Column already exists")

        for pos, bucket in POSITION_MAP.items():
            conn.execute(
                "UPDATE players SET position_bucket = ? WHERE position = ? AND position_bucket IS NULL",
                (bucket, pos),
            )
        # Everything else → Other
        conn.execute(
            "UPDATE players SET position_bucket = 'Other' WHERE position_bucket IS NULL AND position IS NOT NULL"
        )
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM players WHERE position_bucket IS NOT NULL").fetchone()[0]
        logger.info("  Set position_bucket for %d players", count)

    # ── players.citizenship_region ──
    logger.info("Adding players.citizenship_region...")
    if not dry_run:
        try:
            conn.execute("ALTER TABLE players ADD COLUMN citizenship_region TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            logger.info("  Column already exists")

        rows = conn.execute(
            "SELECT player_id, citizenship FROM players WHERE citizenship IS NOT NULL AND citizenship_region IS NULL"
        ).fetchall()
        for pid, cit in rows:
            region = get_region(cit)
            if region:
                conn.execute(
                    "UPDATE players SET citizenship_region = ? WHERE player_id = ?",
                    (region, pid),
                )
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM players WHERE citizenship_region IS NOT NULL").fetchone()[0]
        logger.info("  Set citizenship_region for %d players", count)

    # ── players.agent_cluster ──
    logger.info("Adding players.agent_cluster...")
    if not dry_run:
        try:
            conn.execute("ALTER TABLE players ADD COLUMN agent_cluster TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            logger.info("  Column already exists")

        clusters = compute_agent_cluster(conn)
        # Log cluster distribution from the caller
        mega = sum(1 for c in clusters.values() if c == "Mega")
        active = sum(1 for c in clusters.values() if c == "Active")
        small = sum(1 for c in clusters.values() if c == "Small")
        solo = sum(1 for c in clusters.values() if c == "Solo")
        logger.info("  Agent clusters: %d Mega, %d Active, %d Small, %d Solo", mega, active, small, solo)

        for agent, cluster in clusters.items():
            if agent == "no agent":
                conn.execute(
                    "UPDATE players SET agent_cluster = ? WHERE (agent_name = ? OR agent_name = '') AND agent_cluster IS NULL",
                    (cluster, agent),
                )
            else:
                conn.execute(
                    "UPDATE players SET agent_cluster = ? WHERE agent_name = ? AND agent_cluster IS NULL",
                    (cluster, agent),
                )
        # Everything NULL → Unknown
        conn.execute(
            "UPDATE players SET agent_cluster = 'Unknown' WHERE agent_cluster IS NULL"
        )
        conn.commit()
        counts = conn.execute(
            "SELECT agent_cluster, COUNT(*) FROM players GROUP BY agent_cluster ORDER BY COUNT(*) DESC"
        ).fetchall()
        for cluster, cnt in counts:
            logger.info("  %s: %d players", cluster, cnt)

    # ── transfers.transfer_window ──
    logger.info("Adding transfers.transfer_window...")
    if not dry_run:
        try:
            conn.execute("ALTER TABLE transfers ADD COLUMN transfer_window TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            logger.info("  Column already exists")

        rows = conn.execute(
            "SELECT transfer_id, transfer_date FROM transfers WHERE transfer_date IS NOT NULL AND transfer_window IS NULL"
        ).fetchall()
        for tid, date in rows:
            window = compute_transfer_window(date)
            if window:
                conn.execute(
                    "UPDATE transfers SET transfer_window = ? WHERE transfer_id = ?",
                    (window, tid),
                )
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM transfers WHERE transfer_window IS NOT NULL").fetchone()[0]
        logger.info("  Set transfer_window for %d transfers", count)

    # ── transfers.is_gem ──
    logger.info("Adding transfers.is_gem and transfers.gem_tier...")
    if not dry_run:
        try:
            conn.execute("ALTER TABLE transfers ADD COLUMN is_gem INTEGER")
            conn.commit()
        except sqlite3.OperationalError:
            logger.info("  is_gem column already exists")

        try:
            conn.execute("ALTER TABLE transfers ADD COLUMN gem_tier INTEGER")
            conn.commit()
        except sqlite3.OperationalError:
            logger.info("  gem_tier column already exists")

        conn.execute("""
            UPDATE transfers
            SET is_gem = CASE WHEN roi_pct IS NOT NULL AND roi_pct >= 100 THEN 1 ELSE 0 END,
                gem_tier = CASE
                    WHEN roi_pct IS NULL OR roi_pct < 100 THEN 0
                    WHEN roi_pct < 500 THEN 1
                    WHEN roi_pct < 1000 THEN 2
                    ELSE 3
                END
            WHERE roi_pct IS NOT NULL
        """)
        conn.commit()
        gems = conn.execute("SELECT COUNT(*) FROM transfers WHERE is_gem = 1").fetchone()[0]
        tiers = conn.execute(
            "SELECT gem_tier, COUNT(*) FROM transfers WHERE roi_pct IS NOT NULL GROUP BY gem_tier ORDER BY gem_tier"
        ).fetchall()
        logger.info("  Total gems (ROI>=100%%): %d", gems)
        for tier, cnt in tiers:
            label = ["None", "Silver", "Gold", "Elite"][min(tier, 3)]
            logger.info("    %s (T%d): %d transfers", label, tier, cnt)

    # ── is_training_eligible on buy-sell pairs ──
    logger.info("Adding is_training_eligible flag...")
    if not dry_run:
        try:
            conn.execute("ALTER TABLE transfers ADD COLUMN is_training_eligible INTEGER DEFAULT 0")
            conn.commit()
        except sqlite3.OperationalError:
            logger.info("  Column already exists")

        conn.execute("""
            UPDATE transfers
            SET is_training_eligible = 1
            WHERE roi_pct IS NOT NULL
              AND transfer_date IS NOT NULL
              AND transfer_date < '2021-01-01'
              AND age_at_transfer <= 23
        """)
        conn.commit()
        eligible = conn.execute("SELECT COUNT(*) FROM transfers WHERE is_training_eligible = 1").fetchone()[0]
        logger.info("  Training-eligible pairs (buy ≤2020, age≤23): %d", eligible)

    return changes


def main():
    parser = argparse.ArgumentParser(
        description="Compute derived columns for the hidden gem model"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without making changes",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("COMPUTE DERIVED COLUMNS")
    logger.info("=" * 60)
    if args.dry_run:
        logger.info("DRY RUN — no data will be modified\n")

    conn = sqlite3.connect(str(DB_PATH))
    start = time.time()

    add_columns(conn, dry_run=args.dry_run)

    elapsed = time.time() - start
    logger.info("\nDone in %.1fs", elapsed)
    conn.close()


if __name__ == "__main__":
    main()
