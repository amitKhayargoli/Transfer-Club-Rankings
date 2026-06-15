"""
Feature extraction — builds the training matrix for the Hidden Gem model.

Part 6 of the Data Collection Spec.

For each training-eligible buy-sell pair (buy_date <= 2020, age <= 23):
  [A] Pre-transfer appearances (2 seasons before buy)
  [B] Market value trajectory
  [C] Player profile (position, region, agent, etc.)
  [D] Transfer context (league tiers, window, fee)
  [E] xG supplement (if available)

Output: data/models/training_features.csv
"""

import logging
import os
import sqlite3
from datetime import timedelta
from math import log

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Paths
DB_PATH = "data/transfer_roi.db"
OUTPUT_DIR = "data/models"
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "training_features.csv")

# Number of days before transfer to exclude MV (buffer)
MV_BUFFER_DAYS = 30

# Full-season minutes threshold
FULL_SEASON_MINUTES = 900


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_training_pairs(conn: sqlite3.Connection) -> pd.DataFrame:
    """Fetch all training-eligible buy-sell pairs."""
    query = """
        SELECT
            t.transfer_id        AS pair_id,
            t.player_id,
            p.name               AS player_name,
            t.from_club_id       AS selling_club_id,
            fc.name              AS selling_club_name,
            COALESCE(fc.domestic_competition_id, 'UNKNOWN') AS selling_league,
            COALESCE(fc.league_tier, 0) AS selling_league_tier,
            t.to_club_id         AS buying_club_id,
            bc.name              AS buying_club_name,
            COALESCE(bc.domestic_competition_id, 'UNKNOWN') AS buying_league,
            COALESCE(bc.league_tier, 0) AS buying_league_tier,
            t.transfer_date,
            t.buy_fee,
            t.sell_fee,
            t.roi_pct,
            t.is_gem,
            t.gem_tier,
            t.age_at_transfer    AS age_at_buy,
            t.transfer_window,
            t.tenure_years,
            t.profit,
            p.position,
            p.position_bucket,
            p.citizenship,
            p.citizenship_region,
            p.agent_name,
            p.agent_cluster,
            p.height_in_cm,
            p.foot,
            p.date_of_birth
        FROM transfers t
        JOIN players p ON t.player_id = p.player_id
        LEFT JOIN clubs fc ON t.from_club_id = fc.club_id
        LEFT JOIN clubs bc ON t.to_club_id = bc.club_id
        WHERE t.is_training_eligible = 1
          AND t.roi_pct IS NOT NULL
    """
    df = pd.read_sql_query(query, conn)
    logger.info("Loaded %d training-eligible pairs", len(df))
    return df


# ── Section [A]: Pre-Transfer Appearances ──────────────────────────────────


def extract_appearance_features(
    conn: sqlite3.Connection, pairs: pd.DataFrame
) -> pd.DataFrame:
    """Extract pre-buy appearance stats for each pair.

    For each pair, looks at appearances at the SELLING club (from_club_id)
    within 2 years before the transfer date.
    """
    records = []

    for _, row in pairs.iterrows():
        pair_id = row["pair_id"]
        player_id = row["player_id"]
        club_id = row["selling_club_id"]
        buy_date = row["transfer_date"]

        if pd.isna(buy_date) or pd.isna(club_id):
            records.append(_empty_appearance(pair_id))
            continue

        buy_date = pd.Timestamp(buy_date)

        # 2-year window before the buy
        window_start = buy_date - timedelta(days=730)
        window_end = buy_date

        cursor = conn.execute(
            """
            SELECT
                COALESCE(SUM(a.minutes_played), 0) AS total_minutes,
                COALESCE(SUM(a.goals), 0)          AS total_goals,
                COALESCE(SUM(a.assists), 0)        AS total_assists,
                COALESCE(SUM(a.yellow_cards), 0)   AS total_yellow,
                COALESCE(SUM(a.red_cards), 0)      AS total_red,
                COUNT(DISTINCT a.game_id)          AS games_played
            FROM appearances a
            WHERE a.player_id = ?
              AND a.player_club_id = ?
              AND a.date >= ?
              AND a.date < ?
              AND a.minutes_played > 0
            """,
            (int(player_id), int(club_id), window_start.isoformat(), window_end.isoformat()),
        )
        app_row = cursor.fetchone()

        total_min = app_row["total_minutes"] or 0
        total_goals = app_row["total_goals"] or 0
        total_assists = app_row["total_assists"] or 0
        total_yellow = app_row["total_yellow"] or 0
        total_red = app_row["total_red"] or 0
        games_played = app_row["games_played"] or 0

        # Per-90 stats (only if minutes > 0)
        if total_min > 0:
            goals_per_90 = total_goals / total_min * 90
            assists_per_90 = total_assists / total_min * 90
            g_plus_a_per_90 = (total_goals + total_assists) / total_min * 90
            cards_per_90 = (total_yellow + total_red * 2) / total_min * 90
        else:
            goals_per_90 = None
            assists_per_90 = None
            g_plus_a_per_90 = None
            cards_per_90 = None

        # Split into last 12 months vs previous 12 months
        last_12m_start = buy_date - timedelta(days=365)
        prev_12m_start = buy_date - timedelta(days=730)

        # Last 12 months
        cursor.execute(
            """
            SELECT COALESCE(SUM(minutes_played), 0) as mins
            FROM appearances
            WHERE player_id = ?
              AND player_club_id = ?
              AND date >= ?
              AND date < ?
              AND minutes_played > 0
            """,
            (int(player_id), int(club_id), last_12m_start.isoformat(), window_end.isoformat()),
        )
        mins_last = cursor.fetchone()["mins"] or 0

        # Previous 12 months
        cursor.execute(
            """
            SELECT COALESCE(SUM(minutes_played), 0) as mins
            FROM appearances
            WHERE player_id = ?
              AND player_club_id = ?
              AND date >= ?
              AND date < ?
              AND minutes_played > 0
            """,
            (int(player_id), int(club_id), prev_12m_start.isoformat(), last_12m_start.isoformat()),
        )
        mins_prev = cursor.fetchone()["mins"] or 0

        # Minutes trend (None when no data — model handles missing)
        if mins_prev > 0:
            minutes_trend = mins_last / mins_prev
        elif mins_last > 0:
            minutes_trend = None  # trend undefined from zero baseline
        else:
            minutes_trend = None  # no data either way

        has_appearance_data = 1 if total_min >= FULL_SEASON_MINUTES else 0

        records.append(
            {
                "pair_id": pair_id,
                "goals_per_90": goals_per_90,
                "assists_per_90": assists_per_90,
                "g_plus_a_per_90": g_plus_a_per_90,
                "minutes_last_season": mins_last,
                "minutes_prev_season": mins_prev,
                "minutes_trend": minutes_trend,
                "games_played": games_played,
                "cards_per_90": cards_per_90,
                "has_appearance_data": has_appearance_data,
            }
        )

    result = pd.DataFrame(records)
    logger.info(
        "  [A] Appearance features: %d rows, %d with has_appearance_data=1",
        len(result),
        result["has_appearance_data"].sum(),
    )
    return result


def _empty_appearance(pair_id: int) -> dict:
    return {
        "pair_id": pair_id,
        "goals_per_90": None,
        "assists_per_90": None,
        "g_plus_a_per_90": None,
        "minutes_last_season": 0,
        "minutes_prev_season": 0,
        "minutes_trend": None,
        "games_played": 0,
        "cards_per_90": None,
        "has_appearance_data": 0,
    }


# ── Section [B]: Market Value Trajectory ────────────────────────────────────


def extract_mv_features(
    conn: sqlite3.Connection, pairs: pd.DataFrame
) -> pd.DataFrame:
    """Extract market value trajectory features for each pair.

    mv_at_transfer: max MV at least 30 days before the buy date
    mv_12mo_before: MV closest to 365 days before buy date
    mv_trend: (mv_at - mv_12mo) / mv_12mo
    fee_vs_mv: buy_fee / mv_at_transfer
    peak_mv_to_fee: max historical MV / buy_fee
    """
    records = []

    for _, row in pairs.iterrows():
        pair_id = row["pair_id"]
        player_id = row["player_id"]
        buy_date = row["transfer_date"]
        buy_fee = row["buy_fee"]

        if pd.isna(buy_date):
            records.append(_empty_mv(pair_id))
            continue

        buy_date = pd.Timestamp(buy_date)
        mv_cutoff = buy_date - timedelta(days=MV_BUFFER_DAYS)

        # mv_at_transfer: MAX market_value (highest recorded) within 30-day buffer
        cursor = conn.execute(
            """
            SELECT MAX(market_value_in_eur) as max_mv
            FROM player_valuations
            WHERE player_id = ?
              AND date <= ?
              AND market_value_in_eur IS NOT NULL
            """,
            (int(player_id), mv_cutoff.isoformat()),
        )
        mv_row = cursor.fetchone()
        mv_at = mv_row["max_mv"] if mv_row else None

        # mv_12mo_before: closest to 365 days before
        target_date = buy_date - timedelta(days=365)
        cursor.execute(
            """
            SELECT market_value_in_eur,
                   ABS(JULIANDAY(date) - JULIANDAY(?)) as day_diff
            FROM player_valuations
            WHERE player_id = ?
              AND date <= ?
              AND market_value_in_eur IS NOT NULL
            ORDER BY day_diff ASC
            LIMIT 1
            """,
            (target_date.isoformat(), int(player_id), mv_cutoff.isoformat()),
        )
        mv_12mo_row = cursor.fetchone()
        mv_12mo = mv_12mo_row["market_value_in_eur"] if mv_12mo_row else None

        # Peak historical MV (all-time, pre-transfer)
        cursor.execute(
            """
            SELECT MAX(market_value_in_eur) as peak
            FROM player_valuations
            WHERE player_id = ?
              AND date <= ?
              AND market_value_in_eur IS NOT NULL
            """,
            (int(player_id), mv_cutoff.isoformat()),
        )
        peak_row = cursor.fetchone()
        peak_mv = peak_row["peak"] if peak_row else None

        # Derived metrics
        mv_trend = None
        if mv_at is not None and mv_12mo is not None and mv_12mo > 0:
            mv_trend = (mv_at - mv_12mo) / mv_12mo

        fee_vs_mv = None
        if mv_at is not None and mv_at > 0 and buy_fee is not None and buy_fee > 0:
            fee_vs_mv = buy_fee / mv_at

        peak_mv_to_fee = None
        if peak_mv is not None and peak_mv > 0 and buy_fee is not None and buy_fee > 0:
            peak_mv_to_fee = peak_mv / buy_fee

        records.append(
            {
                "pair_id": pair_id,
                "mv_at_transfer": mv_at,
                "mv_12mo_before": mv_12mo,
                "mv_trend": mv_trend,
                "fee_vs_mv": fee_vs_mv,
                "peak_mv_to_fee": peak_mv_to_fee,
            }
        )

    result = pd.DataFrame(records)
    has_mv = result["mv_at_transfer"].notna().sum()
    logger.info("  [B] MV features: %d rows, %d with mv_at_transfer", len(result), has_mv)
    return result


def _empty_mv(pair_id: int) -> dict:
    return {
        "pair_id": pair_id,
        "mv_at_transfer": None,
        "mv_12mo_before": None,
        "mv_trend": None,
        "fee_vs_mv": None,
        "peak_mv_to_fee": None,
    }


# ── Section [C]: Player Profile ────────────────────────────────────────────


def extract_profile_features(pairs: pd.DataFrame) -> pd.DataFrame:
    """Extract player profile features: one-hot encoded categories.

    Features:
      - age_at_buy (numeric, already in pairs)
      - position_bucket -> one-hot (10 cols: CF, LW, RW, AM, CM, DM, LB, RB, CB, GK + Other)
      - height_in_cm (numeric, keep as-is, model will normalize)
      - foot -> one-hot (Left, Right, Both, Unknown)
      - citizenship_region -> one-hot (Europe, South America, Africa, Asia, Other, Unknown)
      - agent_cluster -> one-hot (Mega, Active, Small, Solo, Unknown)
      - is_international (1/0 — based on having a national team citizenship)
    """
    profile = pairs[["pair_id", "age_at_buy", "height_in_cm", "position_bucket",
                     "foot", "citizenship_region", "agent_cluster"]].copy()

    # Age at buy
    profile["age_at_buy"] = pd.to_numeric(profile["age_at_buy"], errors="coerce")

    # Height
    profile["height_in_cm"] = pd.to_numeric(profile["height_in_cm"], errors="coerce")

    # One-hot: position_bucket
    position_dummies = pd.get_dummies(
        profile["position_bucket"].fillna("Other"),
        prefix="pos",
    )
    # Ensure all expected position columns exist, plus a catch-all Other
    for pos in ["CF", "LW", "RW", "AM", "CM", "DM", "LB", "RB", "CB", "GK"]:
        col = f"pos_{pos}"
        if col not in position_dummies.columns:
            position_dummies[col] = 0
    # Add an explicit "Other" column. If position_bucket is NULL or an
    # unmapped value, all 10 bucket dummies will be 0, and is_other=1
    # signals "unknown/unmapped position."
    known_buckets = {"CF", "LW", "RW", "AM", "CM", "DM", "LB", "RB", "CB", "GK"}
    profile["is_other_position"] = (~profile["position_bucket"].isin(known_buckets)).astype(int)

    # One-hot: foot
    foot_map = {"Left": "Left", "Right": "Right", "Both": "Both"}
    profile["foot_clean"] = profile["foot"].map(foot_map).fillna("Unknown")
    foot_dummies = pd.get_dummies(profile["foot_clean"], prefix="foot")
    for f in ["foot_Left", "foot_Right", "foot_Both", "foot_Unknown"]:
        if f not in foot_dummies.columns:
            foot_dummies[f] = 0

    # One-hot: citizenship_region
    region_map = {
        "Europe": "Europe", "South America": "South America",
        "Africa": "Africa", "Asia": "Asia",
    }
    profile["region_clean"] = profile["citizenship_region"].map(region_map).fillna("Unknown")
    region_dummies = pd.get_dummies(profile["region_clean"], prefix="region")
    for r in ["region_Europe", "region_South America", "region_Africa",
              "region_Asia", "region_Unknown"]:
        if r not in region_dummies.columns:
            region_dummies[r] = 0

    # One-hot: agent_cluster
    agent_map = {"Mega": "Mega", "Active": "Active", "Small": "Small", "Solo": "Solo"}
    profile["agent_clean"] = profile["agent_cluster"].map(agent_map).fillna("Unknown")
    agent_dummies = pd.get_dummies(profile["agent_clean"], prefix="agent")
    for a in ["agent_Mega", "agent_Active", "agent_Small", "agent_Solo", "agent_Unknown"]:
        if a not in agent_dummies.columns:
            agent_dummies[a] = 0

    # Placeholder: is_international — we don't have national team cap data yet.
    # Always 0 until we integrate an international caps source.
    profile["is_international"] = 0

    # Combine
    result = pd.concat(
        [
            profile[["pair_id", "age_at_buy", "height_in_cm", "is_international", "is_other_position"]],
            position_dummies,
            foot_dummies,
            region_dummies,
            agent_dummies,
        ],
        axis=1,
    )

    logger.info("  [C] Profile features: %d rows, %d columns", len(result), len(result.columns))
    return result


# ── Section [D]: Transfer Context ──────────────────────────────────────────


def extract_transfer_context(pairs: pd.DataFrame) -> pd.DataFrame:
    """Extract transfer context features.

    Features:
      - log_buy_fee = log(buy_fee + 1)
      - selling_league_tier (1-4, from clubs join)
      - buying_league_tier (1-4)
      - league_jump = buying_tier - selling_tier
      - is_january_window (1 if transfer_window = 'winter')
      - contract_years_remaining (NULL if missing — we don't have this table yet)
    """
    context = pairs[["pair_id", "selling_league_tier",
                     "buying_league_tier", "transfer_window"]].copy()

    # log_buy_fee — fetch from original pairs (not in context to avoid merge conflict)
    context["log_buy_fee"] = pairs["buy_fee"].apply(
        lambda x: log(float(x) + 1) if pd.notna(x) and float(x) > 0 else None
    )

    # League tier (0 = unknown)
    context["selling_league_tier"] = pd.to_numeric(
        context["selling_league_tier"], errors="coerce"
    ).fillna(0).astype(int)
    context["buying_league_tier"] = pd.to_numeric(
        context["buying_league_tier"], errors="coerce"
    ).fillna(0).astype(int)

    # League jump
    context["league_jump"] = (
        context["buying_league_tier"] - context["selling_league_tier"]
    )

    # January window
    context["is_january_window"] = (
        context["transfer_window"].str.lower() == "winter"
    ).astype(int)

    # Contract years remaining — always NULL for now
    context["contract_years_remaining"] = None

    logger.info("  [D] Transfer context: %d rows", len(context))
    return context


# ── Section [E]: xG Supplement ──────────────────────────────────────────────


def extract_xg_features(
    conn: sqlite3.Connection, pairs: pd.DataFrame
) -> pd.DataFrame:
    """Extract xG supplement if available.

    Joins player_xg table for the season just before the buy transfer.
    """
    records = []

    for _, row in pairs.iterrows():
        pair_id = row["pair_id"]
        player_id = row["player_id"]
        buy_date = row["transfer_date"]

        if pd.isna(buy_date):
            records.append(_empty_xg(pair_id))
            continue

        buy_date = pd.Timestamp(buy_date)
        buy_year = buy_date.year

        # Understat seasons are labeled "2014/2015" covering Aug-May.
        # For a buy in summer 2016, the most recent completed season is "2015/2016".
        # For a winter buy in Jan 2017, the current season is "2016/2017" (player
        # played Aug-Dec 2016 before the move). Same formula works for both.
        season_label = f"{buy_year - 1}/{buy_year}"

        cursor = conn.execute(
            """
            SELECT xG, xA, npxG, minutes, goals, shots
            FROM player_xg
            WHERE player_id = ?
              AND season = ?
              AND minutes IS NOT NULL
              AND minutes > 0
            LIMIT 1
            """,
            (int(player_id), season_label),
        )
        xg_row = cursor.fetchone()

        if xg_row:
            xg_val = xg_row["xG"] or 0
            xa_val = xg_row["xA"] or 0
            minutes_xg = xg_row["minutes"] or 0
            goals_xg = xg_row["goals"] or 0

            xg_per_90 = xg_val / minutes_xg * 90 if minutes_xg > 0 else None
            xa_per_90 = xa_val / minutes_xg * 90 if minutes_xg > 0 else None
            goals_vs_xg = (goals_xg / minutes_xg * 90) - xg_per_90 if minutes_xg > 0 and xg_per_90 is not None else None

            records.append({
                "pair_id": pair_id,
                "xg_per_90": xg_per_90,
                "xa_per_90": xa_per_90,
                "goals_vs_xg": goals_vs_xg,
                "has_xg_data": 1,
            })
        else:
            records.append(_empty_xg(pair_id))

    result = pd.DataFrame(records)
    has_xg = result["has_xg_data"].sum()
    logger.info("  [E] xG features: %d rows, %d with xG data", len(result), has_xg)
    return result


def _empty_xg(pair_id: int) -> dict:
    return {
        "pair_id": pair_id,
        "xg_per_90": None,
        "xa_per_90": None,
        "goals_vs_xg": None,
        "has_xg_data": 0,
    }


# ── Main Pipeline ──────────────────────────────────────────────────────────


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    logger.info("=" * 60)
    logger.info("FEATURE EXTRACTION PIPELINE")
    logger.info("=" * 60)
    logger.info("")

    conn = get_db()

    # Step 1: Load training pairs
    logger.info("Step 1: Loading training-eligible pairs...")
    pairs = fetch_training_pairs(conn)
    logger.info("  %d training pairs loaded", len(pairs))
    logger.info("")

    # Step 2: Extract features for each section
    logger.info("Step 2: Extracting features...")
    logger.info("")

    logger.info("[A] Pre-transfer appearances...")
    app_features = extract_appearance_features(conn, pairs)

    logger.info("[B] Market value trajectory...")
    mv_features = extract_mv_features(conn, pairs)

    logger.info("[C] Player profile...")
    profile_features = extract_profile_features(pairs)

    logger.info("[D] Transfer context...")
    context_features = extract_transfer_context(pairs)

    logger.info("[E] xG supplement...")
    xg_features = extract_xg_features(conn, pairs)

    # Step 3: Merge all features on pair_id
    logger.info("")
    logger.info("Step 3: Merging all feature sections...")

    # Start with target variables from pairs
    targets = pairs[["pair_id", "player_id", "player_name", "transfer_date",
                     "buy_fee", "sell_fee", "roi_pct", "is_gem", "gem_tier",
                     "selling_club_name", "buying_club_name",
                     "selling_league", "buying_league",
                     "agent_name", "position"]].copy()

    # Rename agent_name and position to avoid confusion with derived versions
    targets.rename(columns={
        "agent_name": "agent_name_raw",
        "position": "position_raw",
    }, inplace=True)

    # Merge all feature DataFrames
    result = targets.copy()
    for feature_df in [app_features, mv_features, profile_features,
                       context_features, xg_features]:
        result = result.merge(feature_df, on="pair_id", how="left")

    # Step 4: Reorder columns — targets first, then features
    logger.info("Step 4: Writing output...")

    # Move target columns to front
    target_cols = ["pair_id", "player_id", "player_name", "transfer_date",
                   "is_gem", "gem_tier", "roi_pct", "buy_fee", "sell_fee"]
    feature_cols = [c for c in result.columns if c not in target_cols]
    result = result[target_cols + feature_cols]

    # Write to CSV
    result.to_csv(OUTPUT_PATH, index=False)

    # Step 5: Summary stats
    logger.info("")
    logger.info("=" * 60)
    logger.info("FEATURE EXTRACTION COMPLETE")
    logger.info("=" * 60)
    logger.info("")
    logger.info("Output: %s", OUTPUT_PATH)
    logger.info("Rows:   %d", len(result))
    logger.info("Cols:   %d", len(result.columns))
    logger.info("")

    # Coverage summary
    logger.info("Feature coverage:")
    logger.info("  has_appearance_data=1: %d / %d (%.1f%%)",
                result["has_appearance_data"].sum(),
                len(result),
                result["has_appearance_data"].sum() / len(result) * 100)
    logger.info("  mv_at_transfer not null: %d / %d (%.1f%%)",
                result["mv_at_transfer"].notna().sum(),
                len(result),
                result["mv_at_transfer"].notna().sum() / len(result) * 100)
    logger.info("  has_xg_data=1: %d / %d (%.1f%%)",
                result["has_xg_data"].sum(),
                len(result),
                result["has_xg_data"].sum() / len(result) * 100)

    # Class balance
    gem_count = result["is_gem"].sum()
    logger.info("")
    logger.info("Class balance:")
    logger.info("  Gems (is_gem=1): %d (%.1f%%)", gem_count, gem_count / len(result) * 100)
    logger.info("  Non-gems (is_gem=0): %d (%.1f%%)",
                len(result) - gem_count,
                (len(result) - gem_count) / len(result) * 100)

    conn.close()


if __name__ == "__main__":
    main()
