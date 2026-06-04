"""
Service that loads raw CSV data into the database.

Handles the initial data population by reading the Kaggle-downloaded
CSV files and inserting them into SQLAlchemy models.
"""

import logging
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import DATA_RAW_DIR, MIN_YEAR, MAX_YEAR
from api.models import Club, Player, Transfer, PlayerValuation

logger = logging.getLogger(__name__)


def _parse_date(val) -> date | None:
    """Safely parse a date value from CSV."""
    if pd.isna(val):
        return None
    try:
        return pd.to_datetime(val).date()
    except (ValueError, TypeError):
        return None


def _parse_float(val) -> float | None:
    if pd.isna(val):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_int(val) -> int | None:
    if pd.isna(val):
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _in_year_range(date_val: date | None, min_year: int, max_year: int) -> bool:
    """Check if a date falls within the year range."""
    if date_val is None:
        return True
    return min_year <= date_val.year <= max_year


async def load_clubs(session: AsyncSession, file_path: Path | None = None) -> int:
    """Load clubs from CSV into the clubs table. Returns count loaded."""
    path = file_path or DATA_RAW_DIR / "clubs.csv"
    df = pd.read_csv(path, dtype=str)
    count = 0
    for _, row in df.iterrows():
        club = Club(
            club_id=_parse_int(row.get("club_id")) or 0,
            name=row.get("name", ""),
            club_code=row.get("club_code"),
            domestic_competition_id=row.get("domestic_competition_id"),
        )
        existing = await session.get(Club, club.club_id)
        if existing:
            existing.name = club.name
            existing.club_code = club.club_code
            existing.domestic_competition_id = club.domestic_competition_id
        else:
            session.add(club)
        count += 1
        if count % 5000 == 0:
            await session.flush()
    await session.commit()
    logger.info("Loaded %d clubs", count)
    return count


async def load_players(session: AsyncSession, file_path: Path | None = None) -> int:
    """Load players from CSV into the players table. Returns count loaded."""
    path = file_path or DATA_RAW_DIR / "players.csv"
    df = pd.read_csv(path, dtype=str)
    count = 0
    for _, row in df.iterrows():
        player = Player(
            player_id=_parse_int(row.get("player_id")) or 0,
            name=row.get("name", ""),
            first_name=row.get("first_name"),
            last_name=row.get("last_name"),
            position=row.get("position"),
            sub_position=row.get("sub_position"),
            date_of_birth=_parse_date(row.get("date_of_birth")),
            current_club_id=_parse_int(row.get("current_club_id")),
            current_club_name=row.get("current_club_name"),
            foot=row.get("foot"),
            height_in_cm=_parse_float(row.get("height_in_cm")),
            market_value_in_eur=_parse_float(row.get("market_value_in_eur")),
            highest_market_value_in_eur=_parse_float(row.get("highest_market_value_in_eur")),
        )
        existing = await session.get(Player, player.player_id)
        if existing:
            existing.name = player.name
            existing.position = player.position
            existing.current_club_id = player.current_club_id
            existing.current_club_name = player.current_club_name
            existing.market_value_in_eur = player.market_value_in_eur
        else:
            session.add(player)
        count += 1
        if count % 5000 == 0:
            await session.flush()
    await session.commit()
    logger.info("Loaded %d players", count)
    return count


async def load_transfers(session: AsyncSession, file_path: Path | None = None) -> int:
    """Load transfers from CSV into the transfers table. Returns count loaded.
    Filters to the configured year range (MIN_YEAR - MAX_YEAR).
    Deduplicates by (player_id, from_club_id, to_club_id, transfer_date) to
    prevent duplicates on re-run."""
    path = file_path or DATA_RAW_DIR / "transfers.csv"

    # Build set of existing composite keys to avoid duplicates on re-run
    existing = set()
    result = await session.execute(
        text("SELECT player_id, from_club_id, to_club_id, transfer_date FROM transfers")
    )
    for row in result:
        dt = str(row.transfer_date) if row.transfer_date is not None else ""
        existing.add((row.player_id, row.from_club_id, row.to_club_id, dt))

    chunksize = 50000
    total = 0
    for chunk in pd.read_csv(path, dtype=str, chunksize=chunksize):
        for _, row in chunk.iterrows():
            transfer_date = _parse_date(row.get("transfer_date"))

            # Apply year filtering
            if transfer_date and not _in_year_range(transfer_date, MIN_YEAR, MAX_YEAR):
                continue

            # Skip if this row already exists in the database
            key = (
                _parse_int(row.get("player_id")) or 0,
                _parse_int(row.get("from_club_id")),
                _parse_int(row.get("to_club_id")),
                str(transfer_date) if transfer_date else "",
            )
            if key in existing:
                continue

            transfer = Transfer(
                player_id=key[0],
                player_name=row.get("player_name"),
                from_club_id=key[1],
                to_club_id=key[2],
                from_club_name=row.get("from_club_name"),
                to_club_name=row.get("to_club_name"),
                transfer_date=transfer_date,
                transfer_season=row.get("transfer_season"),
                transfer_fee=_parse_float(row.get("transfer_fee")),
                market_value_in_eur=_parse_float(row.get("market_value_in_eur")),
            )
            session.add(transfer)
            existing.add(key)
            total += 1
            if total % 10000 == 0:
                await session.flush()
        await session.flush()
    await session.commit()
    logger.info("Loaded %d transfers (filtered %d–%d)", total, MIN_YEAR, MAX_YEAR)
    return total


async def load_player_valuations(session: AsyncSession, file_path: Path | None = None) -> int:
    """Load player valuations from CSV into the player_valuations table.
    Filters to the configured year range.
    Deduplicates by (player_id, date, market_value_in_eur) to prevent
    duplicates on re-run."""
    path = file_path or DATA_RAW_DIR / "player_valuations.csv"

    # Build set of existing composite keys
    existing = set()
    result = await session.execute(
        text("SELECT player_id, date, market_value_in_eur FROM player_valuations")
    )
    for row in result:
        dt = str(row.date) if row.date is not None else ""
        existing.add((row.player_id, dt, row.market_value_in_eur))

    chunksize = 50000
    total = 0
    for chunk in pd.read_csv(path, dtype=str, chunksize=chunksize):
        for _, row in chunk.iterrows():
            val_date = _parse_date(row.get("date"))

            if val_date and not _in_year_range(val_date, MIN_YEAR, MAX_YEAR):
                continue

            val = _parse_float(row.get("market_value_in_eur"))
            key = (
                _parse_int(row.get("player_id")) or 0,
                str(val_date) if val_date else "",
                val,
            )
            if key in existing:
                continue

            valuation = PlayerValuation(
                player_id=key[0],
                date=val_date,
                market_value_in_eur=val,
                current_club_id=_parse_int(row.get("current_club_id")),
                current_club_name=row.get("current_club_name"),
                player_club_domestic_competition_id=row.get("player_club_domestic_competition_id"),
            )
            session.add(valuation)
            existing.add(key)
            total += 1
            if total % 10000 == 0:
                await session.flush()
        await session.flush()
    await session.commit()
    logger.info("Loaded %d player valuations (filtered %d–%d)", total, MIN_YEAR, MAX_YEAR)
    return total


async def run_pipeline(session: AsyncSession) -> dict:
    """Run the full data pipeline: load CSVs, compute analytics."""
    from api.services.analytics import run_full_analytics

    logger.info("Starting data pipeline...")

    clubs_count = await load_clubs(session)
    players_count = await load_players(session)
    transfers_count = await load_transfers(session)
    valuations_count = await load_player_valuations(session)

    logger.info("Loading complete. Running analytics...")
    analytics_result = await run_full_analytics(session)

    logger.info("Pipeline complete: %d clubs, %d players, %d transfers, %d valuations | %d pairs, %d clubs scored",
                clubs_count, players_count, transfers_count, valuations_count,
                analytics_result["pairs_computed"], analytics_result["clubs_updated"])

    return {
        "clubs": clubs_count,
        "players": players_count,
        "transfers": transfers_count,
        "valuations": valuations_count,
        "pairs_computed": analytics_result["pairs_computed"],
        "clubs_updated": analytics_result["clubs_updated"],
    }
