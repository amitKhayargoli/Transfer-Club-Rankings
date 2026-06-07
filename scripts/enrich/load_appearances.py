#!/usr/bin/env python3
"""
Load appearances.csv into the database and analyze which leagues produce
the most high-ROI transfers.

Uses bulk inserts via executemany for 10-100x faster loading.

Usage:
    python scripts/enrich/load_appearances.py                # Load CSV only
    python scripts/enrich/load_appearances.py --analyze      # Load + analysis
    python scripts/enrich/load_appearances.py --skip-load    # Just analysis
"""

import argparse
import logging
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
logger = logging.getLogger("load_appearances")

CSV_PATH = PROJECT_ROOT / "data" / "raw" / "appearances.csv"
DB_PATH = PROJECT_ROOT / "data" / "transfer_roi.db"


def create_table_sync():
    """Create the appearances table using sync sqlite3 (avoids locking issues)."""
    import sqlite3

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS appearances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appearance_id TEXT NOT NULL UNIQUE,
            game_id INTEGER,
            player_id INTEGER NOT NULL,
            player_club_id INTEGER,
            player_current_club_id INTEGER,
            date TEXT,
            player_name TEXT,
            competition_id TEXT,
            yellow_cards INTEGER,
            red_cards INTEGER,
            goals INTEGER,
            assists INTEGER,
            minutes_played INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_appearances_player ON appearances(player_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_appearances_club ON appearances(player_club_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_appearances_comp ON appearances(competition_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_appearances_date ON appearances(date)")
    conn.commit()
    conn.close()
    logger.info("✓ appearances table ready")


def load_appearances_bulk(batch_size: int = 50000, insert_batch: int = 500):
    """Load CSV using batched inserts.

    Uses executemany with sub-batches of `insert_batch` rows to stay
    within SQLite's SQL variable limit (999 by default).
    """
    import sqlite3
    import pandas as pd

    if not CSV_PATH.exists():
        logger.error("CSV not found at %s", CSV_PATH)
        return 0

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous = OFF")  # Speed up bulk insert
    conn.execute("PRAGMA cache_size = -8000000")  # 8GB cache

    logger.info("Reading %s ...", CSV_PATH)
    total_rows = sum(1 for _ in open(CSV_PATH)) - 1  # count lines minus header
    logger.info("CSV has ~%d rows", total_rows)

    chunks = pd.read_csv(
        CSV_PATH,
        chunksize=batch_size,
        dtype={
            "appearance_id": str,
            "game_id": "Int64",
            "player_id": "Int64",
            "player_club_id": "Int64",
            "player_current_club_id": "Int64",
            "yellow_cards": "Int64",
            "red_cards": "Int64",
            "goals": "Int64",
            "assists": "Int64",
            "minutes_played": "Int64",
        },
        parse_dates=["date"],
    )

    total = 0
    chunk_num = 0
    start = time.time()

    for chunk in chunks:
        chunk_num += 1
        chunk = chunk.where(chunk.notna(), None)

        # Convert date column to string for SQLite
        if "date" in chunk.columns:
            chunk["date"] = chunk["date"].astype(str).replace("NaT", None)

        # Insert in sub-batches of `insert_batch` rows to avoid SQL variable limit
        for i in range(0, len(chunk), insert_batch):
            sub = chunk.iloc[i:i + insert_batch]
            sub.to_sql(
                "appearances",
                conn,
                if_exists="append",
                index=False,
                method="multi",
            )

        total += len(chunk)
        elapsed = time.time() - start
        rate = total / elapsed if elapsed > 0 else 0
        eta = (total_rows - total) / rate if rate > 0 else 0
        logger.info(
            "  Chunk %d: %d rows (total: %d, rate: %.0f rows/s, ETA: %.0fs)",
            chunk_num, len(chunk), total, rate, eta,
        )

    conn.execute("PRAGMA synchronous = FULL")  # Restore safety
    conn.commit()
    conn.close()

    logger.info("✓ Loaded %d appearances in %.1fs", total, time.time() - start)
    return total


async def analyze_high_roi_leagues(limit: int = 30):
    """Analyze which leagues produce the most high-ROI transfers."""
    from api.database import async_session_factory
    from sqlalchemy import text

    async with async_session_factory() as session:
        # ── Analysis 1: Selling leagues with best ROI on youth ──
        logger.info("Running high-ROI league analysis...")

        result = await session.execute(text("""
            SELECT
                c.domestic_competition_id AS origin_league,
                COUNT(DISTINCT t.transfer_id) AS total_deals,
                COUNT(DISTINCT CASE WHEN t.roi_pct >= 100 AND t.age_at_transfer <= 23 THEN t.transfer_id END) AS gems,
                ROUND(AVG(CASE WHEN t.roi_pct >= 100 AND t.age_at_transfer <= 23 THEN t.roi_pct END), 1) AS avg_gem_roi,
                ROUND(SUM(CASE WHEN t.roi_pct >= 100 AND t.age_at_transfer <= 23 THEN t.profit END), 0) AS gem_profit,
                ROUND(
                    COUNT(DISTINCT CASE WHEN t.roi_pct >= 100 AND t.age_at_transfer <= 23 THEN t.transfer_id END) * 100.0 /
                    NULLIF(COUNT(DISTINCT t.transfer_id), 0), 1
                ) AS gem_rate_pct,
                ROUND(AVG(CASE WHEN t.roi_pct >= 100 AND t.age_at_transfer <= 23 THEN t.buy_fee END), 0) AS avg_buy_fee,
                ROUND(AVG(CASE WHEN t.roi_pct >= 100 AND t.age_at_transfer <= 23 THEN t.sell_fee END), 0) AS avg_sell_fee
            FROM transfers t
            JOIN clubs c ON t.from_club_id = c.club_id
            WHERE t.roi_pct IS NOT NULL
              AND c.domestic_competition_id IS NOT NULL
            GROUP BY c.domestic_competition_id
            HAVING COUNT(DISTINCT t.transfer_id) >= 10
            ORDER BY gems DESC
            LIMIT :lim
        """), {"lim": limit})
        rows = result.fetchall()

        print("\n" + "=" * 130)
        print("TOP LEAGUES PRODUCING HIGH-ROI YOUTH TRANSFERS")
        print("=" * 130)
        print(f"{'League':<10} {'Deals':<8} {'Gems':<8} {'Gem%':<8} {'Avg ROI':<10} {'Profit':<14} {'Avg Buy':<14} {'Avg Sell':<14}")
        print("-" * 130)
        for r in rows:
            profit_str = f"€{r[4]/1_000_000:.0f}M" if r[4] and abs(r[4]) >= 1_000_000 else str(r[4] or 0)
            buy_str = f"€{r[6]/1_000:.0f}K" if r[6] else "-"
            sell_str = f"€{r[7]/1_000_000:.1f}M" if r[7] else "-"
            print(f"{str(r[0]):<10} {r[1]:<8} {r[2]:<8} {str(r[5])+'%' if r[5] else '-':<8} {str(r[3])+'%' if r[3] else '-':<10} {profit_str:<14} {buy_str:<14} {sell_str:<14}")

        # ── Analysis 2: Top gem-factory clubs ──
        print("\n" + "=" * 130)
        print("TOP GEM-FACTORY CLUBS (sold players ≤23 for ≥100% ROI)")
        print("=" * 130)

        result2 = await session.execute(text("""
            SELECT
                c.name AS club,
                c.domestic_competition_id AS league,
                COUNT(DISTINCT t.transfer_id) AS sold,
                COUNT(DISTINCT CASE WHEN t.roi_pct >= 100 AND t.age_at_transfer <= 23 THEN t.transfer_id END) AS gems,
                ROUND(
                    COUNT(DISTINCT CASE WHEN t.roi_pct >= 100 AND t.age_at_transfer <= 23 THEN t.transfer_id END) * 100.0 /
                    NULLIF(COUNT(DISTINCT t.transfer_id), 0), 1
                ) AS gem_pct,
                ROUND(SUM(CASE WHEN t.roi_pct >= 100 AND t.age_at_transfer <= 23 THEN t.profit END), 0) AS gem_profit
            FROM transfers t
            JOIN clubs c ON t.from_club_id = c.club_id
            WHERE t.roi_pct IS NOT NULL
              AND c.domestic_competition_id IS NOT NULL
            GROUP BY c.club_id
            HAVING COUNT(DISTINCT t.transfer_id) >= 5
            ORDER BY gems DESC
            LIMIT :lim
        """), {"lim": limit})
        rows2 = result2.fetchall()

        print(f"{'Club':<35} {'League':<8} {'Sold':<8} {'Gems':<8} {'Gem%':<8} {'Gem Profit':<16}")
        print("-" * 100)
        for r in rows2:
            profit_str = f"€{r[5]/1_000_000:.0f}M" if r[5] and abs(r[5]) >= 1_000_000 else str(r[5] or 0)
            print(f"{str(r[0])[:34]:<35} {str(r[1]):<8} {r[2]:<8} {r[3]:<8} {str(r[4])+'%' if r[4] else '-':<8} {profit_str:<16}")

        # ── Analysis 3: Hidden gem signature profile ──
        print("\n" + "=" * 100)
        print("HIDDEN GEM SIGNATURE — avg profile of a high-ROI youth deal")
        print("=" * 100)

        result3 = await session.execute(text("""
            SELECT
                COALESCE(t.player_position, 'Unknown') AS position,
                COUNT(*) AS cnt,
                ROUND(AVG(t.age_at_transfer), 1) AS avg_age,
                ROUND(AVG(t.buy_fee), 0) AS avg_buy,
                ROUND(AVG(t.sell_fee), 0) AS avg_sell,
                ROUND(AVG(t.roi_pct), 1) AS avg_roi,
                ROUND(AVG(t.tenure_years), 1) AS avg_tenure
            FROM transfers t
            WHERE t.roi_pct >= 100
              AND t.age_at_transfer <= 23
              AND t.buy_fee IS NOT NULL
              AND t.sell_fee IS NOT NULL
            GROUP BY t.player_position
            ORDER BY cnt DESC
        """))
        rows3 = result3.fetchall()
        print(f"{'Position':<20} {'Count':<8} {'Age':<10} {'Avg Buy':<14} {'Avg Sell':<14} {'Avg ROI':<10} {'Tenure':<10}")
        print("-" * 90)
        for r in rows3:
            buy_str = f"€{r[3]/1_000:.0f}K" if r[3] else "-"
            sell_str = f"€{r[4]/1_000_000:.1f}M" if r[4] else "-"
            print(f"{str(r[0])[:19]:<20} {r[1]:<8} {str(r[2])+'y':<10} {buy_str:<14} {sell_str:<14} {str(r[5])+'%':<10} {str(r[6])+'y':<10}")

        # ── Analysis 4: Which agents deliver the best gems? ──
        print("\n" + "=" * 100)
        print("TOP AGENTS — who brings the best youth deals?")
        print("=" * 100)

        result4 = await session.execute(text("""
            SELECT
                COALESCE(p.agent_name, 'Unknown') AS agent,
                COUNT(DISTINCT t.transfer_id) AS deals,
                COUNT(DISTINCT CASE WHEN t.roi_pct >= 100 AND t.age_at_transfer <= 23 THEN t.transfer_id END) AS gems,
                ROUND(AVG(CASE WHEN t.roi_pct >= 100 AND t.age_at_transfer <= 23 THEN t.roi_pct END), 1) AS avg_gem_roi,
                ROUND(SUM(CASE WHEN t.roi_pct >= 100 AND t.age_at_transfer <= 23 THEN t.profit END), 0) AS gem_profit
            FROM transfers t
            JOIN players p ON t.player_id = p.player_id
            WHERE t.roi_pct IS NOT NULL
              AND p.agent_name IS NOT NULL
            GROUP BY p.agent_name
            HAVING gems >= 3
            ORDER BY gems DESC
            LIMIT 20
        """))
        rows4 = result4.fetchall()
        print(f"{'Agent':<35} {'Deals':<8} {'Gems':<8} {'Avg ROI':<10} {'Gem Profit':<16}")
        print("-" * 80)
        for r in rows4:
            profit_str = f"€{r[4]/1_000_000:.0f}M" if r[4] and abs(r[4]) >= 1_000_000 else str(r[4] or 0)
            print(f"{str(r[0])[:34]:<35} {r[1]:<8} {r[2]:<8} {str(r[3])+'%' if r[3] else '-':<10} {profit_str:<16}")


async def main():
    parser = argparse.ArgumentParser(description="Load appearances and analyze high-ROI transfers")
    parser.add_argument("--analyze", action="store_true", help="Also run ROI analysis after loading")
    parser.add_argument("--skip-load", action="store_true", help="Skip loading, just run analysis")
    parser.add_argument("--limit", type=int, default=30, help="Limit for analysis results")
    args = parser.parse_args()

    start = time.time()

    # Create table (sync — avoids async locking issues)
    create_table_sync()

    # Load CSV (sync — bulk load with executemany/pandas)
    if not args.skip_load:
        total = load_appearances_bulk()
        if total == 0:
            logger.warning("No appearances loaded")
    else:
        logger.info("Skipping load (--skip-load)")

    # Analysis (async)
    if args.analyze:
        await analyze_high_roi_leagues(limit=args.limit)

    elapsed = time.time() - start
    logger.info("Done in %.1fs", elapsed)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
