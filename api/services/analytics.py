"""
Analytics pipeline — computes buy-sell pairs, ROI metrics, and club composite scores.

This is the core business logic that:
1. Matches buy and sell transfers for each player per club
2. Calculates ROI, annualized ROI, profit, tenure
3. Aggregates metrics by club (for the full dataset and per year window)
4. Computes composite scores
"""

import logging
from datetime import datetime
from typing import Optional

import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import (
    MIN_YEAR, MAX_YEAR, MIN_TRANSFERS, MIN_BUY_FEE,
    ANALYTICS_WINDOWS, DEFAULT_ANALYTICS_WINDOW,
    WEIGHT_MEDIAN_ROI, WEIGHT_TOTAL_PROFIT, WEIGHT_HIT_RATE, WEIGHT_VALUE_CREATION,
    WEIGHT_ANNUALIZED_ROI, WEIGHT_PROFIT_PER_DEAL,
)
from api.models import Club, ClubMetricsWindow, Player, Transfer, PlayerValuation

logger = logging.getLogger(__name__)


async def compute_buy_sell_pairs(session: AsyncSession) -> int:
    """
    Match buy and sell transfers for each player to compute ROI pairs.
    
    Logic: For each player, find transfers where a club buys a player
    and later sells them. Join on (player_id, club_id) with sell_date > buy_date.
    
    This uses pandas for the heavy lifting, then writes results back to Transfer rows.
    Returns number of pairs created.
    """
    # Load all transfers with fees into pandas
    query = select(Transfer).where(Transfer.transfer_fee.isnot(None), Transfer.transfer_fee > 0)
    result = await session.execute(query)
    all_transfers = result.scalars().all()

    if not all_transfers:
        logger.warning("No transfers with fees found to compute pairs")
        return 0

    rows = []
    for t in all_transfers:
        rows.append({
            "transfer_id": t.transfer_id,
            "player_id": t.player_id,
            "club_id": t.to_club_id,  # buying club
            "fee": t.transfer_fee,
            "date": t.transfer_date,
            "transfer_type": "buy",
        })
        rows.append({
            "transfer_id": t.transfer_id,
            "player_id": t.player_id,
            "club_id": t.from_club_id,  # selling club
            "fee": t.transfer_fee,
            "date": t.transfer_date,
            "transfer_type": "sell",
        })

    df = pd.DataFrame(rows)

    # Separate buys and sells
    buys = df[df["transfer_type"] == "buy"].copy()
    sells = df[df["transfer_type"] == "sell"].copy()

    if buys.empty or sells.empty:
        return 0

    # Rename for clarity in merge
    buys = buys.rename(columns={"fee": "buy_fee", "date": "buy_date", "transfer_id": "buy_transfer_id"})
    sells = sells.rename(columns={"fee": "sell_fee", "date": "sell_date", "transfer_id": "sell_transfer_id"})

    # Merge on player_id and club_id (club bought player, then sold them)
    pairs = sells.merge(
        buys,
        on=["player_id", "club_id"],
        suffixes=("_sell", "_buy"),
        how="inner",
    )

    # Only keep pairs where sell_date > buy_date (must sell after buying)
    pairs = pairs[pairs["sell_date"] > pairs["buy_date"]]

    if pairs.empty:
        return 0

    # Keep the last buy→sell pair per player-club (deduplicate)
    pairs = pairs.sort_values("sell_date").drop_duplicates(
        subset=["player_id", "club_id", "buy_transfer_id"],
        keep="last",
    )

    # Exclude pairs where the buy fee is below the minimum threshold
    pairs = pairs[pairs["buy_fee"] >= MIN_BUY_FEE]

    if pairs.empty:
        logger.warning("No pairs meet the minimum buy fee threshold of €%d", MIN_BUY_FEE)
        return 0

    # Calculate metrics
    pairs["profit"] = pairs["sell_fee"] - pairs["buy_fee"]
    pairs["roi_pct"] = (pairs["profit"] / pairs["buy_fee"]) * 100

    # Tenure in days and years
    pairs["tenure_days"] = (pd.to_datetime(pairs["sell_date"]) - pd.to_datetime(pairs["buy_date"])).dt.days
    pairs["tenure_years"] = pairs["tenure_days"] / 365.25

    # Annualized ROI - guard against overflow on quick flips
    def _calc_annualized(row):
        if row["tenure_years"] > 0 and row["buy_fee"] > 0:
            effective_years = max(row["tenure_years"], 7 / 365.25)
            ratio = row["sell_fee"] / row["buy_fee"]
            try:
                result = (ratio ** (1.0 / effective_years)) - 1
                return max(min(result, 5.0), -5.0)
            except (OverflowError, ValueError):
                return None
        return None

    pairs["annualized_roi_pct"] = pairs.apply(_calc_annualized, axis=1) * 100

    # Load player positions and names for enrichment
    player_info = {}
    player_query = select(Player.player_id, Player.name, Player.position)
    player_result = await session.execute(player_query)
    for row in player_result:
        player_info[row.player_id] = {"name": row.name, "position": row.position}

    # Load peak valuations
    peak_values = {}
    val_query = select(
        PlayerValuation.player_id,
        func.max(PlayerValuation.market_value_in_eur).label("peak_value"),
    ).group_by(PlayerValuation.player_id)
    val_result = await session.execute(val_query)
    for row in val_result:
        peak_values[row.player_id] = row.peak_value

    pairs["peak_value"] = pairs["player_id"].map(peak_values)
    pairs["value_creation_pct"] = (
        (pairs["peak_value"].fillna(0) - pairs["buy_fee"]) / pairs["buy_fee"] * 100
    )
    pairs["player_name"] = pairs["player_id"].map(lambda pid: player_info.get(pid, {}).get("name"))
    pairs["player_position"] = pairs["player_id"].map(lambda pid: player_info.get(pid, {}).get("position"))

    # Write back computed fields to Transfer rows on the buy transfer
    pair_count = 0
    for _, pair in pairs.iterrows():
        buy_id = pair.get("buy_transfer_id") or pair.get("sell_transfer_id")

        buy_fee_val = pair["buy_fee"]
        sell_fee_val = pair["sell_fee"]
        profit_val = pair["profit"]
        roi_val = pair["roi_pct"]
        annualized_val = pair.get("annualized_roi_pct")
        tenure_days_val = int(pair["tenure_days"]) if not pd.isna(pair.get("tenure_days")) else None
        tenure_years_val = pair.get("tenure_years")
        peak_val = pair.get("peak_value")
        value_create_val = pair.get("value_creation_pct")
        pos_val = pair.get("player_position")

        if buy_id and not pd.isna(buy_id):
            transfer = await session.get(Transfer, int(buy_id))
            if transfer:
                transfer.buy_fee = buy_fee_val
                transfer.sell_fee = sell_fee_val
                transfer.profit = profit_val
                transfer.roi_pct = roi_val
                transfer.annualized_roi_pct = annualized_val
                transfer.tenure_days = tenure_days_val
                transfer.tenure_years = tenure_years_val
                transfer.peak_value = peak_val
                transfer.value_creation_pct = value_create_val
                transfer.player_position = pos_val
                pair_count += 1

        if pair_count % 1000 == 0:
            await session.flush()

    await session.commit()
    logger.info("Computed %d buy-sell pairs", pair_count)
    return pair_count


def _aggregate_pairs_to_metrics(pairs_data: list[dict]) -> pd.DataFrame:
    """Aggregate a list of pair dicts into per-club metrics.

    Returns a DataFrame with club metrics suitable for writing to Club or ClubMetricsWindow.
    """
    if not pairs_data:
        return pd.DataFrame()

    df = pd.DataFrame(pairs_data)

    agg = df.groupby("club_id").agg(
        total_transfers=("roi_pct", "count"),
        median_roi=("roi_pct", "median"),
        total_profit=("profit", "sum"),
        hit_rate=("profit", lambda x: (x > 0).sum() / len(x) * 100),
        value_creation=("value_creation_pct", "median"),
        annualized_roi=("annualized_roi_pct", "median"),
        profit_per_deal=("profit", "mean"),
    ).reset_index()

    buying_premiums = df[df["peak_value"].notna() & (df["peak_value"] > 0)].groupby("club_id")["sell_fee"].apply(
        lambda g: (((g - df.loc[g.index, "peak_value"]) / df.loc[g.index, "peak_value"]) * 100).median()
    )
    agg["buying_club_premium"] = agg["club_id"].map(buying_premiums)

    # Apply minimum transfers threshold (higher for smaller windows to avoid noise)
    min_t = max(MIN_TRANSFERS, 2)  # at least 2 deals for any window
    agg = agg[agg["total_transfers"] >= min_t]

    if agg.empty:
        return agg

    # Normalize metrics to 0-1 for composite score
    def _normalize(series):
        min_v, max_v = series.min(), series.max()
        if max_v == min_v:
            return pd.Series([0.5] * len(series))
        return (series - min_v) / (max_v - min_v)

    agg["norm_median_roi"] = _normalize(agg["median_roi"])
    agg["norm_total_profit"] = _normalize(agg["total_profit"])
    agg["norm_hit_rate"] = _normalize(agg["hit_rate"])
    agg["norm_value_creation"] = _normalize(agg["value_creation"])
    agg["norm_annualized_roi"] = _normalize(agg["annualized_roi"].fillna(0))
    agg["norm_profit_per_deal"] = _normalize(agg["profit_per_deal"])

    agg["composite_score"] = (
        WEIGHT_MEDIAN_ROI * agg["norm_median_roi"]
        + WEIGHT_TOTAL_PROFIT * agg["norm_total_profit"]
        + WEIGHT_HIT_RATE * agg["norm_hit_rate"]
        + WEIGHT_VALUE_CREATION * agg["norm_value_creation"]
        + WEIGHT_ANNUALIZED_ROI * agg["norm_annualized_roi"]
        + WEIGHT_PROFIT_PER_DEAL * agg["norm_profit_per_deal"]
    )

    return agg


async def compute_club_metrics(session: AsyncSession) -> int:
    """
    Aggregate all transfer pairs by club and compute composite score on the Club model.
    This uses ALL data (no year filter).
    """
    query = select(Transfer).where(Transfer.roi_pct.isnot(None))
    result = await session.execute(query)
    pairs = result.scalars().all()

    if not pairs:
        logger.warning("No computed pairs found to aggregate")
        return 0

    data = []
    for p in pairs:
        data.append({
            "club_id": p.to_club_id,
            "profit": p.profit,
            "roi_pct": p.roi_pct,
            "annualized_roi_pct": p.annualized_roi_pct,
            "value_creation_pct": p.value_creation_pct,
            "sell_fee": p.sell_fee,
            "peak_value": p.peak_value,
        })

    agg = _aggregate_pairs_to_metrics(data)

    if agg.empty:
        logger.warning("No clubs meet the minimum transfers threshold of %d", MIN_TRANSFERS)
        return 0

    club_count = 0
    for _, row in agg.iterrows():
        club = await session.get(Club, int(row["club_id"]))
        if club:
            club.total_transfers = int(row["total_transfers"])
            club.median_roi = row["median_roi"]
            club.total_profit = row["total_profit"]
            club.hit_rate = row["hit_rate"]
            club.value_creation = row["value_creation"]
            club.annualized_roi = row.get("annualized_roi")
            club.profit_per_deal = row.get("profit_per_deal")
            club.buying_club_premium = row.get("buying_club_premium")
            club.composite_score = row["composite_score"]
            club.last_updated = datetime.now()
            club_count += 1

        if club_count % 100 == 0:
            await session.flush()

    await session.commit()
    logger.info("Updated metrics for %d clubs (all data)", club_count)
    return club_count


async def compute_club_metrics_for_window(session: AsyncSession, window_key: str) -> int:
    """Aggregate transfer pairs filtered by buy_year >= window_key and store in ClubMetricsWindow.

    Returns number of clubs updated (0 if window_key is already up-to-date).
    """
    min_buy_year = int(window_key)

    # Load buy transfers with computed pairs, filtered by buy year
    query = select(Transfer).where(
        Transfer.roi_pct.isnot(None),
        Transfer.buy_fee.isnot(None),
        Transfer.transfer_date.isnot(None),
        func.extract("year", Transfer.transfer_date) >= min_buy_year,
    )
    result = await session.execute(query)
    pairs = result.scalars().all()

    if not pairs:
        logger.info("No pairs found for window %s, skipping", window_key)
        return 0

    data = []
    for p in pairs:
        data.append({
            "club_id": p.to_club_id,
            "profit": p.profit,
            "roi_pct": p.roi_pct,
            "annualized_roi_pct": p.annualized_roi_pct,
            "value_creation_pct": p.value_creation_pct,
            "sell_fee": p.sell_fee,
            "peak_value": p.peak_value,
        })

    agg = _aggregate_pairs_to_metrics(data)

    if agg.empty:
        logger.info("No clubs meet minimum transfers threshold for window %s", window_key)
        return 0

    # Upsert into ClubMetricsWindow
    club_count = 0
    for _, row in agg.iterrows():
        club_id = int(row["club_id"])

        # Check for existing record
        existing_q = select(ClubMetricsWindow).where(
            ClubMetricsWindow.club_id == club_id,
            ClubMetricsWindow.window_key == window_key,
        )
        existing_result = await session.execute(existing_q)
        existing = existing_result.scalar_one_or_none()

        if existing:
            existing.total_transfers = int(row["total_transfers"])
            existing.median_roi = row["median_roi"]
            existing.total_profit = row["total_profit"]
            existing.hit_rate = row["hit_rate"]
            existing.value_creation = row["value_creation"]
            existing.annualized_roi = row.get("annualized_roi")
            existing.profit_per_deal = row.get("profit_per_deal")
            existing.buying_club_premium = row.get("buying_club_premium")
            existing.composite_score = row["composite_score"]
            existing.last_updated = datetime.now()
        else:
            window_metrics = ClubMetricsWindow(
                club_id=club_id,
                window_key=window_key,
                total_transfers=int(row["total_transfers"]),
                median_roi=row["median_roi"],
                total_profit=row["total_profit"],
                hit_rate=row["hit_rate"],
                value_creation=row["value_creation"],
                annualized_roi=row.get("annualized_roi"),
                profit_per_deal=row.get("profit_per_deal"),
                buying_club_premium=row.get("buying_club_premium"),
                composite_score=row["composite_score"],
                last_updated=datetime.now(),
            )
            session.add(window_metrics)
        club_count += 1

        if club_count % 100 == 0:
            await session.flush()

    await session.commit()
    logger.info("Updated metrics for %d clubs for window %s+", club_count, window_key)
    return club_count


async def compute_all_window_metrics(session: AsyncSession) -> dict:
    """Compute club metrics for every configured analytical window.

    Returns dict of window_key -> clubs_updated count.
    """
    results = {}
    for window in ANALYTICS_WINDOWS:
        key = str(window)
        count = await compute_club_metrics_for_window(session, key)
        results[key] = count
    return results


async def run_full_analytics(session: AsyncSession) -> dict:
    """Run the full analytics pipeline: pairs → club metrics (all data + per window)."""
    pairs_count = await compute_buy_sell_pairs(session)
    clubs_count = await compute_club_metrics(session)
    window_counts = await compute_all_window_metrics(session)

    return {
        "pairs_computed": pairs_count,
        "clubs_updated": clubs_count,
        "windows_updated": window_counts,
    }
