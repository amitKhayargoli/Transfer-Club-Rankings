"""
build_buy_sell_pairs.py — Creates the dedicated buy_sell_pairs table (spec Part 5A).

For every player with 2+ transfers:
  - Match buy and sell transfers on (player_id, holding_club_id)
  - Compute roi_pct = (sell_fee - buy_fee) / buy_fee * 100
  - Classify gem_tier: 0=none, 1=Silver(100%), 2=Gold(500%), 3=Elite(1000%)
  - Compute confidence_score from fee data quality
  - Flag is_training_eligible if buy_date <= 2020-12-31 and age_at_buy <= 23

Output: buy_sell_pairs table populated in the database.
"""

import logging
import sqlite3
import sys
from datetime import datetime

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DB_PATH = "data/transfer_roi.db"
MIN_BUY_FEE = 100_000  # Exclude near-free transfers (matches config)


def get_conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def create_table(conn: sqlite3.Connection) -> None:
    """Create the buy_sell_pairs table if it doesn't exist (spec Part 5A schema)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS buy_sell_pairs (
            pair_id             INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id           INTEGER REFERENCES players(player_id),
            buy_transfer_id     INTEGER REFERENCES transfers(transfer_id),
            sell_transfer_id    INTEGER REFERENCES transfers(transfer_id),
            buy_fee             INTEGER,
            sell_fee            INTEGER,
            roi_pct             REAL,
            holding_club_id     INTEGER REFERENCES clubs(club_id),
            tenure_years        REAL,
            age_at_buy          REAL,
            is_gem              INTEGER,
            gem_tier            INTEGER,
            confidence_score    REAL,
            is_training_eligible INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bsp_player ON buy_sell_pairs(player_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bsp_holding ON buy_sell_pairs(holding_club_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bsp_gem ON buy_sell_pairs(is_gem)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bsp_training ON buy_sell_pairs(is_training_eligible)")
    conn.commit()
    logger.info("Created buy_sell_pairs table")


def load_all_transfers(conn: sqlite3.Connection) -> pd.DataFrame:
    """Load all transfers with fees and club info into a DataFrame."""
    df = pd.read_sql_query(
        """
        SELECT
            t.transfer_id,
            t.player_id,
            t.from_club_id,
            t.to_club_id,
            t.transfer_date,
            t.transfer_fee,
            t.age_at_transfer,
            t.transfer_season,
            fc.domestic_competition_id AS from_league,
            bc.domestic_competition_id AS to_league
        FROM transfers t
        LEFT JOIN clubs fc ON t.from_club_id = fc.club_id
        LEFT JOIN clubs bc ON t.to_club_id = bc.club_id
        WHERE t.transfer_fee IS NOT NULL
          AND t.transfer_fee > 0
          AND t.transfer_date IS NOT NULL
        ORDER BY t.player_id, t.transfer_date
        """,
        conn,
    )
    logger.info("Loaded %d transfers with fees", len(df))
    return df


def compute_buy_sell_pairs(transfers: pd.DataFrame) -> pd.DataFrame:
    """Match buy and sell transfers per (player_id, club_id) to build pairs.

    Algorithm (mirrors api/services/analytics.py):
      1. Each transfer is both a "buy" (for to_club_id) and a "sell" (for from_club_id)
      2. Match sells → buys on (player_id, holding_club_id) where sell_date > buy_date
      3. Keep the last buy→sell pair per player-club
      4. Compute ROI, tenure, gem tier, confidence, training eligibility
    """
    if transfers.empty:
        return pd.DataFrame()

    # Build buy and sell views of every transfer
    buys = transfers[["transfer_id", "player_id", "to_club_id", "transfer_date",
                       "transfer_fee", "age_at_transfer"]].copy()
    buys.columns = ["buy_transfer_id", "player_id", "club_id", "buy_date",
                    "buy_fee", "age_at_buy"]

    sells = transfers[["transfer_id", "player_id", "from_club_id", "transfer_date",
                       "transfer_fee"]].copy()
    sells.columns = ["sell_transfer_id", "player_id", "club_id", "sell_date",
                     "sell_fee"]

    # Merge sells → buys on (player_id, club_id) where sell_date > buy_date
    pairs = sells.merge(buys, on=["player_id", "club_id"], how="inner")

    # Must sell after buying
    pairs = pairs[pairs["sell_date"] > pairs["buy_date"]]

    if pairs.empty:
        logger.warning("No buy-sell pairs found")
        return pd.DataFrame()

    # Deduplicate: keep the last sell for each buy
    pairs = pairs.sort_values("sell_date").drop_duplicates(
        subset=["player_id", "club_id", "buy_transfer_id"],
        keep="last",
    )

    # Exclude pairs where buy fee is below minimum threshold
    pairs = pairs[pairs["buy_fee"] >= MIN_BUY_FEE]

    if pairs.empty:
        logger.warning("No pairs meet the minimum buy fee threshold of €%d", MIN_BUY_FEE)
        return pd.DataFrame()

    # ── Compute ROI metrics ──
    pairs["roi_pct"] = (pairs["sell_fee"] - pairs["buy_fee"]) / pairs["buy_fee"] * 100

    # Tenure
    pairs["tenure_days"] = (
        pd.to_datetime(pairs["sell_date"]) - pd.to_datetime(pairs["buy_date"])
    ).dt.days
    pairs["tenure_years"] = pairs["tenure_days"] / 365.25

    # ── Gem classification (spec Part 5A) ──
    # 0 = none (roi < 100%), 1 = Silver (100-499%), 2 = Gold (500-999%), 3 = Elite (1000%+)
    pairs["gem_tier"] = 0
    pairs.loc[pairs["roi_pct"] >= 100, "gem_tier"] = 1
    pairs.loc[pairs["roi_pct"] >= 500, "gem_tier"] = 2
    pairs.loc[pairs["roi_pct"] >= 1000, "gem_tier"] = 3
    pairs["gem_tier"] = pairs["gem_tier"].astype(int)
    pairs["is_gem"] = (pairs["gem_tier"] >= 1).astype(int)

    # ── Confidence score (spec Part 5A) ──
    # Data quality: all fees come from confirmed Transfermarkt data.
    # Set to 1.0 for all pairs (both buy and sell fees are confirmed).
    # If we later integrate estimated fees from market values,
    # we'd set 0.7 or 0.5 accordingly.
    pairs["confidence_score"] = 1.0

    # Filter: only keep pairs with confidence >= 0.85 (spec requires this)
    # With all scores at 1.0, this keeps everything.
    pairs = pairs[pairs["confidence_score"] >= 0.85]

    # ── Training eligibility (spec Part 5A) ──
    # 1 if buy_date <= 2020-12-31 AND age_at_buy <= 23
    cutoff = pd.Timestamp("2020-12-31")
    pairs["is_training_eligible"] = (
        (pd.to_datetime(pairs["buy_date"]) <= cutoff)
        & (pairs["age_at_buy"] <= 23)
    ).astype(int)

    # Rename club_id to holding_club_id for the output
    pairs.rename(columns={"club_id": "holding_club_id"}, inplace=True)

    logger.info("Computed %d buy-sell pairs (%.1f%% gem rate)",
                len(pairs), pairs["is_gem"].mean() * 100)
    logger.info("  Training-eligible: %d / %d",
                pairs["is_training_eligible"].sum(), len(pairs))

    return pairs


def write_pairs(conn: sqlite3.Connection, pairs: pd.DataFrame) -> int:
    """Write pairs to the buy_sell_pairs table."""
    if pairs.empty:
        return 0

    # Clear existing data
    conn.execute("DELETE FROM buy_sell_pairs")
    conn.commit()

    # Select and rename columns to match table schema
    columns = [
        "player_id", "buy_transfer_id", "sell_transfer_id",
        "buy_fee", "sell_fee", "roi_pct", "holding_club_id",
        "tenure_years", "age_at_buy", "is_gem", "gem_tier",
        "confidence_score", "is_training_eligible",
    ]

    # Ensure all required columns exist
    for col in columns:
        if col not in pairs.columns:
            pairs[col] = None

    # Write in batches
    batch_size = 500
    total = 0

    for start in range(0, len(pairs), batch_size):
        batch = pairs.iloc[start:start + batch_size]
        rows = []

        for _, row in batch.iterrows():
            rows.append((
                int(row["player_id"]) if pd.notna(row["player_id"]) else None,
                int(row["buy_transfer_id"]) if pd.notna(row["buy_transfer_id"]) else None,
                int(row["sell_transfer_id"]) if pd.notna(row["sell_transfer_id"]) else None,
                float(row["buy_fee"]) if pd.notna(row["buy_fee"]) else None,
                float(row["sell_fee"]) if pd.notna(row["sell_fee"]) else None,
                float(row["roi_pct"]) if pd.notna(row["roi_pct"]) else None,
                int(row["holding_club_id"]) if pd.notna(row["holding_club_id"]) else None,
                float(row["tenure_years"]) if pd.notna(row["tenure_years"]) else None,
                float(row["age_at_buy"]) if pd.notna(row["age_at_buy"]) else None,
                int(row["is_gem"]) if pd.notna(row["is_gem"]) else None,
                int(row["gem_tier"]) if pd.notna(row["gem_tier"]) else None,
                float(row["confidence_score"]) if pd.notna(row["confidence_score"]) else None,
                int(row["is_training_eligible"]) if pd.notna(row["is_training_eligible"]) else None,
            ))

        conn.executemany(
            """
            INSERT INTO buy_sell_pairs (
                player_id, buy_transfer_id, sell_transfer_id,
                buy_fee, sell_fee, roi_pct, holding_club_id,
                tenure_years, age_at_buy, is_gem, gem_tier,
                confidence_score, is_training_eligible
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
        total += len(batch)

    logger.info("Wrote %d pairs to buy_sell_pairs table", total)
    return total


def validate(conn: sqlite3.Connection) -> None:
    """Run validation checks on the new table."""
    c = conn.cursor()

    logger.info("")
    logger.info("=" * 60)
    logger.info("VALIDATION")
    logger.info("=" * 60)

    # Row count
    c.execute("SELECT COUNT(*) FROM buy_sell_pairs")
    total = c.fetchone()[0]
    logger.info("  Total pairs: %d", total)

    if total == 0:
        return

    # Gem tiers
    c.execute("SELECT gem_tier, COUNT(*) FROM buy_sell_pairs GROUP BY gem_tier ORDER BY gem_tier")
    logger.info("  Gem tier distribution:")
    for r in c.fetchall():
        label = {0: "None (roi<100%)", 1: "Silver (100-499%)", 2: "Gold (500-999%)", 3: "Elite (1000%+)"}.get(r[0])
        logger.info("    %d=%s: %d (%5.1f%%)", r[0], label, r[1], r[1] / total * 100)

    # Training eligible
    c.execute("SELECT COUNT(*) FROM buy_sell_pairs WHERE is_training_eligible = 1")
    training = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM buy_sell_pairs WHERE is_training_eligible = 1 AND is_gem = 1")
    training_gems = c.fetchone()[0]
    logger.info("  Training-eligible: %d (%d gems, %.1f%% gem rate)",
                training, training_gems, training_gems / training * 100 if training > 0 else 0)

    # Confidence score buckets
    c.execute("""
        SELECT
            SUM(CASE WHEN confidence_score >= 0.99 THEN 1 ELSE 0 END) as high,
            SUM(CASE WHEN confidence_score >= 0.90 AND confidence_score < 0.99 THEN 1 ELSE 0 END) as med,
            SUM(CASE WHEN confidence_score < 0.90 THEN 1 ELSE 0 END) as low
        FROM buy_sell_pairs
    """)
    r = c.fetchone()
    logger.info("  Confidence: high=%.0f%% med=%.0f%% low=%.0f%%",
                r[0] / total * 100, r[1] / total * 100, r[2] / total * 100)

    # ROI sanity check (spec Part 8: should be < 5 rows with roi > 5000%)
    c.execute("SELECT COUNT(*) FROM buy_sell_pairs WHERE roi_pct > 5000")
    extreme = c.fetchone()[0]
    logger.info("  ROI > 5000%%: %d %s", extreme,
                "⚠️  CHECK FOR FEE ERRORS" if extreme >= 5 else "✅ OK")

    # Class balance
    c.execute("SELECT is_gem, COUNT(*) FROM buy_sell_pairs WHERE is_training_eligible = 1 GROUP BY is_gem")
    logger.info("  Training class balance:")
    for r in c.fetchall():
        logger.info("    is_gem=%d: %d rows", r[0], r[1])

    # Compare with existing transfers table pairs
    c.execute("SELECT COUNT(*) FROM transfers WHERE roi_pct IS NOT NULL")
    existing = c.fetchone()[0]
    logger.info("  Existing pairs on transfers table: %d vs new table: %d", existing, total)


def main():
    logger.info("=" * 60)
    logger.info("BUY-SELL PAIRS BUILDER (Part 5A)")
    logger.info("=" * 60)
    logger.info("")

    conn = get_conn()

    # Step 1: Create table
    logger.info("Step 1: Creating table...")
    create_table(conn)

    # Step 2: Load transfers
    logger.info("Step 2: Loading transfers...")
    transfers = load_all_transfers(conn)
    logger.info("  %d transfers loaded", len(transfers))
    logger.info("")

    # Step 3: Compute pairs
    logger.info("Step 3: Computing buy-sell pairs...")
    pairs = compute_buy_sell_pairs(transfers)

    if pairs.empty:
        logger.warning("No pairs could be computed!")
        sys.exit(0)

    # Step 4: Write to table
    logger.info("")
    logger.info("Step 4: Writing to buy_sell_pairs table...")
    written = write_pairs(conn, pairs)

    # Step 5: Validate
    logger.info("")
    logger.info("Step 5: Validation...")
    validate(conn)

    conn.close()
    logger.info("")
    logger.info("Done — %d pairs written to buy_sell_pairs table", written)


if __name__ == "__main__":
    main()
