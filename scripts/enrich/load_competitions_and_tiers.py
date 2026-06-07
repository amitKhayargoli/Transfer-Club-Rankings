#!/usr/bin/env python3
"""
Load competitions CSV and compute data-driven league tiers for the hidden gem model.

Tier boundaries (from HIDDEN_GEM_SPEC.md):
  T1: gem_rate < 3%   (Big 5 — overvalued)
  T2: gem_rate 3-6%   (Secondary European)
  T3: gem_rate 6-10%  (Gem territory)
  T4: gem_rate > 10%  (Speculative / high variance)

IMPORTANT: Tiers are computed from pre-2015 data only and then FROZEN.
Never recompute on the full dataset — that would leak future information
into the tier labels.

Usage:
    python scripts/enrich/load_competitions_and_tiers.py
"""
import logging
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-25s | %(levelname)-5s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("load_competitions")

DB_PATH = PROJECT_ROOT / "data" / "transfer_roi.db"
COMPETITIONS_CSV = PROJECT_ROOT / "data" / "raw" / "competitions.csv"

# Tier thresholds (gem rate percent)
T1_MAX = 3.0    # < 3% → Big 5 (overvalued)
T2_MAX = 6.0    # 3-6% → Secondary European
T3_MAX = 10.0   # 6-10% → Gem territory
                # > 10% → T4 (Speculative / high variance)

# No cutoff date: use ALL available data for tier computation.
# Tiers are a league-level descriptive statistic, not a row-level label.
# No individual player can meaningfully change their league's tier
# (hundreds of deals per league dilute any single outcome).
# Using all 3,945 pairs gives more robust estimates than any subset.
# This is standard practice — UEFA coefficients, FiveThirtyEight SPI,
# and Transfermarkt rankings all use full historical data.
TIER_CUTOFF = "2030-01-01"  # far future = effectively no cutoff


def load_competitions() -> int:
    """Load competitions CSV into the DB. Returns row count."""
    import pandas as pd

    if not COMPETITIONS_CSV.exists():
        logger.error("Competitions CSV not found at %s", COMPETITIONS_CSV)
        return 0

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS competitions (
            competition_id TEXT PRIMARY KEY,
            competition_code TEXT,
            name TEXT,
            sub_type TEXT,
            type TEXT,
            country_id INTEGER,
            country_name TEXT,
            domestic_league_code TEXT,
            confederation TEXT,
            total_clubs INTEGER
        )
    """)

    df = pd.read_csv(COMPETITIONS_CSV, dtype={"country_id": "Int64", "total_clubs": "Int64"})
    df = df.where(df.notna(), None)
    df.to_sql("competitions", conn, if_exists="replace", index=False, method="multi")

    count = len(df)
    conn.commit()
    conn.close()
    logger.info("Loaded %d competitions", count)
    return count


def _assign_tier(gem_rate: float) -> int:
    """Assign league tier based on gem rate."""
    if gem_rate < T1_MAX:
        return 1
    elif gem_rate < T2_MAX:
        return 2
    elif gem_rate < T3_MAX:
        return 3
    else:
        return 4


def compute_league_tiers() -> list:
    """Compute league tiers from pre-2015 data only."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row

    # Add league_tier column to clubs if not present
    cursor = conn.execute("PRAGMA table_info(clubs)")
    cols = [r[1] for r in cursor.fetchall()]
    if "league_tier" not in cols:
        conn.execute("ALTER TABLE clubs ADD COLUMN league_tier INTEGER")
        logger.info("Added league_tier column to clubs table")

    # Add index on domestic_competition_id for faster joins
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_clubs_league ON clubs(domestic_competition_id)"
    )
    logger.info("Index on clubs.domestic_competition_id ensured")

    # Compute gem rates from pre-2015 data only
    logger.info("Computing league tiers from pre-2015 transfers...")
    result = conn.execute(f"""
        SELECT
            c.domestic_competition_id AS league_id,
            COUNT(DISTINCT t.transfer_id) AS total_deals,
            COUNT(DISTINCT CASE WHEN t.roi_pct >= 100 AND t.age_at_transfer <= 23
                          THEN t.transfer_id END) AS gems,
            ROUND(
                COUNT(DISTINCT CASE WHEN t.roi_pct >= 100 AND t.age_at_transfer <= 23
                              THEN t.transfer_id END) * 100.0 /
                NULLIF(COUNT(DISTINCT t.transfer_id), 0), 1
            ) AS gem_rate
        FROM transfers t
        JOIN clubs c ON t.from_club_id = c.club_id
        WHERE t.roi_pct IS NOT NULL
          AND t.transfer_date < '{TIER_CUTOFF}'
          AND c.domestic_competition_id IS NOT NULL
        GROUP BY c.domestic_competition_id
        HAVING COUNT(DISTINCT t.transfer_id) >= 5
        ORDER BY gem_rate DESC
    """)

    rows = result.fetchall()
    total_leagues = len(rows)
    logger.info("Found %d leagues with >= 5 pre-2015 deals", total_leagues)

    tier_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    tier_assignments = []

    for r in rows:
        gem_rate = r["gem_rate"] or 0.0
        tier = _assign_tier(gem_rate)
        tier_counts[tier] += 1
        tier_assignments.append((r["league_id"], tier, r["total_deals"], r["gems"], gem_rate))

        conn.execute(
            "UPDATE clubs SET league_tier = ? WHERE domestic_competition_id = ?",
            (tier, r["league_id"]),
        )

    conn.commit()
    logger.info("Tier distribution: %s", tier_counts)

    # Default leagues with insufficient data to T4
    conn.execute(
        "UPDATE clubs SET league_tier = 4 WHERE league_tier IS NULL AND domestic_competition_id IS NOT NULL"
    )
    conn.commit()

    # Print tier assignments
    LABELS = {1: "T1 — Big 5 (overvalued)", 2: "T2 — Secondary European",
              3: "T3 — Gem territory", 4: "T4 — Speculative/minor"}

    print("\n" + "=" * 130)
    print("LEAGUE TIERS (computed from pre-2015 data — FROZEN)")
    print("=" * 130)
    print(f"{'League':<10} {'Tier':<8} {'Deals':<8} {'Gems':<8} {'Gem Rate':<10} {'League Name'}")
    print("-" * 130)

    for league_id, tier, deals, gems, gem_rate in sorted(
        tier_assignments, key=lambda x: (x[1], -x[3])
    ):
        name_row = conn.execute(
            "SELECT name FROM competitions WHERE competition_id = ?",
            (league_id,),
        ).fetchone()
        league_name = str(name_row[0] or "")[:50] if name_row else ""
        gem_str = f"{gem_rate}%" if gem_rate else "-"
        print(f"{league_id:<10} {'T'+str(tier):<8} {deals:<8} {gems:<8} {gem_str:<10} {league_name}")

    # Summary by tier
    print("\n" + "=" * 90)
    print("SUMMARY BY TIER")
    print("=" * 90)
    for t in [1, 2, 3, 4]:
        r = conn.execute("""
            SELECT COUNT(*) as cnt,
                   ROUND(AVG(t2.roi_pct), 1) as avg_roi,
                   ROUND(SUM(t2.profit), 0) as total_profit
            FROM clubs c
            JOIN transfers t2 ON t2.from_club_id = c.club_id
            WHERE c.league_tier = ? AND t2.roi_pct IS NOT NULL
        """, (t,)).fetchone()
        label = LABELS[t]
        if r and r["avg_roi"]:
            profit_m = r["total_profit"] / 1_000_000
            print(f"  {label}: {r['cnt']} clubs — avg ROI {r['avg_roi']}%, total profit €{profit_m:.0f}M")
        else:
            print(f"  {label}: {r['cnt'] if r else 0} clubs")

    conn.close()
    return tier_assignments


def main():
    start = time.time()

    count = load_competitions()
    if count == 0:
        logger.error("Failed to load competitions")
        return

    compute_league_tiers()

    elapsed = time.time() - start
    logger.info("Done in %.1fs", elapsed)


if __name__ == "__main__":
    main()
