"""
Analytics pipeline — computes buy-sell pairs, ROI metrics, and club composite scores.

This is the core business logic that:
1. Matches buy and sell transfers for each player per club
2. Calculates ROI, annualized ROI, profit, tenure
3. Aggregates metrics by club
4. Computes composite scores
"""

import logging
from datetime import datetime
from typing import Optional

import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import MIN_YEAR, MAX_YEAR, MIN_TRANSFERS, MIN_BUY_FEE, WEIGHT_MEDIAN_ROI, WEIGHT_TOTAL_PROFIT, WEIGHT_HIT_RATE, WEIGHT_VALUE_CREATION
from api.models import Club, Player, Transfer, PlayerValuation

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
    # Prevents near-free transfers (€1K buys) from inflating ROI calculations
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

    # Annualized ROI
    def _calc_annualized(row):
        if row["tenure_years"] > 0 and row["buy_fee"] > 0:
            ratio = row["sell_fee"] / row["buy_fee"]
            return (ratio ** (1.0 / row["tenure_years"])) - 1
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

    # Write back computed fields to Transfer rows — on BOTH buy and sell sides
    pair_count = 0
    for _, pair in pairs.iterrows():
        buy_id = pair.get("buy_transfer_id") or pair.get("sell_transfer_id")
        sell_id = pair.get("sell_transfer_id")

        # Common fields to set on both sides
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

        # NOTE: Profit/ROI is intentionally only stored on the buy transfer.
        # Sell transfers get their profit from the API endpoint which looks up
        # the corresponding buy transfer for the club being viewed.
        # This avoids data corruption when a transfer is both a sell for one
        # club AND a buy for another (the analytics loop would overwrite data).

        if pair_count % 1000 == 0:
            await session.flush()

    await session.commit()
    logger.info("Computed %d buy-sell pairs", pair_count)
    return pair_count


async def compute_club_metrics(session: AsyncSession) -> int:
    """
    Aggregate transfer pairs by club and compute composite score.
    Returns number of clubs updated.
    """
    # Load all transfers with computed pairs
    query = select(Transfer).where(Transfer.roi_pct.isnot(None))
    result = await session.execute(query)
    pairs = result.scalars().all()

    if not pairs:
        logger.warning("No computed pairs found to aggregate")
        return 0

    # Build a DataFrame from all pairs
    data = []
    for p in pairs:
        data.append({
            "club_id": p.to_club_id,  # The buying club (the one that made the profit/loss)
            "profit": p.profit,
            "roi_pct": p.roi_pct,
            "annualized_roi_pct": p.annualized_roi_pct,
            "value_creation_pct": p.value_creation_pct,
            "sell_fee": p.sell_fee,
        })

    df = pd.DataFrame(data)

    # Aggregate by club
    agg = df.groupby("club_id").agg(
        total_transfers=("roi_pct", "count"),
        median_roi=("roi_pct", "median"),
        total_profit=("profit", "sum"),
        hit_rate=("profit", lambda x: (x > 0).sum() / len(x) * 100),
        value_creation=("value_creation_pct", "median"),
    ).reset_index()

    # Apply minimum transfers threshold
    agg = agg[agg["total_transfers"] >= MIN_TRANSFERS]

    if agg.empty:
        logger.warning("No clubs meet the minimum transfers threshold of %d", MIN_TRANSFERS)
        return 0

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

    # Composite score
    agg["composite_score"] = (
        WEIGHT_MEDIAN_ROI * agg["norm_median_roi"]
        + WEIGHT_TOTAL_PROFIT * agg["norm_total_profit"]
        + WEIGHT_HIT_RATE * agg["norm_hit_rate"]
        + WEIGHT_VALUE_CREATION * agg["norm_value_creation"]
    )

    # Write back to Club records
    club_count = 0
    for _, row in agg.iterrows():
        club = await session.get(Club, int(row["club_id"]))
        if club:
            club.total_transfers = int(row["total_transfers"])
            club.median_roi = row["median_roi"]
            club.total_profit = row["total_profit"]
            club.hit_rate = row["hit_rate"]
            club.value_creation = row["value_creation"]
            club.composite_score = row["composite_score"]
            club.last_updated = datetime.now()
            club_count += 1

        if club_count % 100 == 0:
            await session.flush()

    await session.commit()
    logger.info("Updated metrics for %d clubs", club_count)
    return club_count


async def run_full_analytics(session: AsyncSession) -> dict:
    """Run the full analytics pipeline: pairs → club metrics."""
    pairs_count = await compute_buy_sell_pairs(session)
    clubs_count = await compute_club_metrics(session)

    return {
        "pairs_computed": pairs_count,
        "clubs_updated": clubs_count,
    }
