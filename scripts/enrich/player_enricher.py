"""
Player enrichment logic.

For each player:
1. Fetch profile from transfermarkt-api -> update players table
2. Fetch market value history -> upsert player_valuations table
3. Fetch transfer history -> upsert transfers table
"""

import logging
import re
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import MIN_YEAR
from api.models import Player, Transfer, PlayerValuation

logger = logging.getLogger(__name__)


def _parse_transfermarkt_date(date_str: str | None) -> date | None:
    """Parse a date string from Transfermarkt (e.g. 'Jan 1, 2020' or '2020-01-01')."""
    if not date_str:
        return None
    date_str = date_str.strip()
    if not date_str:
        return None
    for fmt in ("%b %d, %Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d %b %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except (ValueError, TypeError):
            continue
    logger.warning("Could not parse date: %s", date_str)
    return None


def _parse_market_value(value_str: str | None) -> float | None:
    """Parse a Transfermarkt market value string to a float in EUR.

    Examples: '€100m' -> 100_000_000, '€500k' -> 500_000, '€1.2bn' -> 1_200_000_000
    """
    if not value_str:
        return None
    value_str = value_str.strip().replace("\u20ac", "").replace("€", "").strip()
    if not value_str:
        return None
    multiplier = 1.0
    if value_str.endswith("bn"):
        multiplier = 1_000_000_000
        value_str = value_str[:-2]
    elif value_str.endswith("m"):
        multiplier = 1_000_000
        value_str = value_str[:-1]
    elif value_str.endswith("k"):
        multiplier = 1_000
        value_str = value_str[:-1]
    elif value_str.endswith("Th."):
        multiplier = 1_000
        value_str = value_str[:-3]
    value_str = value_str.strip()
    try:
        return float(value_str) * multiplier
    except (ValueError, TypeError):
        return None


def _parse_fee(fee_str: str | None) -> float | None:
    """Parse a transfer fee string. Falls back to market value parsing for monetary values."""
    if not fee_str:
        return None
    fee_str = fee_str.strip()

    # Handle special cases
    if fee_str.lower() in ("-", "free transfer", "free", "loan", "end of loan", "?"):
        return None  # free/loan transfers have no fee, matching existing DB convention
    if fee_str.lower() in ("retired", "without club", "career break"):
        return None

    # Try direct numeric
    try:
        return float(fee_str.replace(",", ""))
    except (ValueError, TypeError):
        pass

    # Try parsing as market value style (€Xm, €Xk)
    return _parse_market_value(fee_str)


def _compute_age_at_transfer(
    date_of_birth: date | None,
    transfer_date: date | None,
) -> float | None:
    """Compute a player's age in years at the time of a transfer."""
    if not date_of_birth or not transfer_date:
        return None
    delta = transfer_date - date_of_birth
    return delta.days / 365.25


def _extract_position(profile: dict) -> str | None:
    """Extract the main position string from the profile's position dict."""
    pos = profile.get("position", {})
    if isinstance(pos, dict):
        main = pos.get("main")
        if main:
            return main.strip()
    elif isinstance(pos, str):
        return pos.strip()
    return None


def _extract_other_positions(profile: dict) -> str | None:
    """Extract sub-position(s) from the profile."""
    pos = profile.get("position", {})
    if isinstance(pos, dict):
        others = pos.get("other", [])
        if others and isinstance(others, list):
            return ", ".join(o.strip() for o in others if o)
    return None


def _extract_club_id(profile: dict) -> int | None:
    """Extract current club ID from profile's club dict."""
    club = profile.get("club", {})
    club_id = club.get("id")
    if club_id:
        try:
            return int(club_id)
        except (ValueError, TypeError):
            pass
    return None


def _extract_club_name(profile: dict) -> str | None:
    """Extract current club name from profile's club dict."""
    club = profile.get("club", {})
    return club.get("name") or None


def _extract_height(profile: dict) -> float | None:
    """Parse height string like '1.88 m' to float."""
    height = profile.get("height")
    if not height:
        return None
    height = height.strip()
    match = re.match(r"(\d+[.,]?\d*)", height)
    if match:
        try:
            return float(match.group(1).replace(",", "."))
        except (ValueError, TypeError):
            pass
    return None


def _extract_citizenship(profile: dict) -> str | None:
    """Extract citizenship(s) from the profile's citizenship list.

    Returns comma-separated string of nationalities, e.g. 'Argentina,Italy'.
    """
    citizenship = profile.get("citizenship")
    if citizenship and isinstance(citizenship, list):
        cleaned = [c.strip() for c in citizenship if c and c.strip()]
        if cleaned:
            return ", ".join(cleaned)
    return None


def _extract_agent(profile: dict) -> str | None:
    """Extract agent name from the profile's agent dict."""
    agent = profile.get("agent")
    if agent and isinstance(agent, dict):
        name = agent.get("name")
        if name and name.strip():
            return name.strip()
    return None


def _extract_contract_expiry(profile: dict) -> date | None:
    """Extract contract expiry date from the profile's club dict."""
    club = profile.get("club", {})
    if club and isinstance(club, dict):
        contract = club.get("contract_expires")
        if contract:
            return _parse_transfermarkt_date(str(contract))
    return None


async def enrich_player_profile(
    session: AsyncSession,
    player_id: int,
    profile: dict,
) -> bool:
    """Update a player's record with data from the transfermarkt-api profile.

    Returns True if the player was updated, False if not found.
    """
    player = await session.get(Player, player_id)
    if not player:
        logger.warning("Player %d not found in DB, skipping profile update", player_id)
        return False

    # Position
    position = _extract_position(profile)
    if position:
        player.position = position

    sub_position = _extract_other_positions(profile)
    if sub_position:
        player.sub_position = sub_position

    # Date of birth
    dob = profile.get("dateOfBirth")
    if dob:
        parsed_dob = _parse_transfermarkt_date(dob)
        if parsed_dob:
            player.date_of_birth = parsed_dob

    # Current club
    club_id = _extract_club_id(profile)
    if club_id:
        player.current_club_id = club_id
    club_name = _extract_club_name(profile)
    if club_name:
        player.current_club_name = club_name

    # Foot
    foot = profile.get("foot")
    if foot and foot.strip():
        player.foot = foot.strip().lower()

    # Height
    height = _extract_height(profile)
    if height:
        player.height_in_cm = height

    # Market value
    mv = profile.get("marketValue")
    if mv:
        parsed_mv = _parse_market_value(mv)
        if parsed_mv is not None:
            player.market_value_in_eur = parsed_mv

    # --- NEW: Scouting enrichment fields ---

    # Citizenship (critical for understanding scouting markets)
    citizenship = _extract_citizenship(profile)
    if citizenship:
        player.citizenship = citizenship

    # Agent (important for Benfica/Wolves/agent-pipeline analysis)
    agent = _extract_agent(profile)
    if agent:
        player.agent_name = agent

    # Contract expiry (determines leverage in transfer negotiations)
    contract_expiry = _extract_contract_expiry(profile)
    if contract_expiry:
        player.contract_expiry_date = contract_expiry

    # Player image URL (from Transfermarkt CDN)
    image_url = profile.get("imageUrl") or profile.get("image_url")
    if image_url:
        player.image_url = str(image_url).strip()

    return True


async def enrich_player_valuations(
    session: AsyncSession,
    player_id: int,
    market_value_data: dict,
) -> int:
    """Insert market value history for a player.

    Returns the number of valuations inserted.
    """
    history = market_value_data.get("marketValueHistory", [])
    if not history:
        logger.info("No market value history for player %d", player_id)
        return 0

    # Get existing valuations to avoid duplicates
    existing = set()
    result = await session.execute(
        text("SELECT date, market_value_in_eur FROM player_valuations WHERE player_id = :pid"),
        {"pid": player_id},
    )
    for row in result:
        dt = str(row.date) if row.date else ""
        existing.add((dt, row.market_value_in_eur))

    count = 0
    for entry in history:
        val_date = _parse_transfermarkt_date(entry.get("date"))
        val_value = _parse_market_value(str(entry.get("marketValue", "")))
        if not val_date or val_value is None:
            continue
        # Use config-based minimum year instead of hardcoded 2015
        if val_date.year < MIN_YEAR:
            continue

        key = (str(val_date), val_value)
        if key in existing:
            continue

        # Extract club info if available
        club_id = None
        raw_club_id = entry.get("clubId")
        if raw_club_id:
            try:
                club_id = int(raw_club_id)
            except (ValueError, TypeError):
                pass

        valuation = PlayerValuation(
            player_id=player_id,
            date=val_date,
            market_value_in_eur=val_value,
            current_club_id=club_id,
            current_club_name=entry.get("clubName"),
        )
        session.add(valuation)
        existing.add(key)
        count += 1

    if count > 0:
        await session.flush()
        logger.info("Inserted %d valuations for player %d", count, player_id)

    return count


async def enrich_player_transfers(
    session: AsyncSession,
    player_id: int,
    transfers_data: dict,
) -> int:
    """Insert transfer history for a player.

    Returns the number of transfers inserted.
    """
    transfers = transfers_data.get("transfers", [])
    if not transfers:
        logger.info("No transfer history for player %d", player_id)
        return 0

    # Get existing transfers to avoid duplicates
    existing = set()
    result = await session.execute(
        text(
            "SELECT player_id, from_club_id, to_club_id, transfer_date "
            "FROM transfers WHERE player_id = :pid"
        ),
        {"pid": player_id},
    )
    for row in result:
        dt = str(row.transfer_date) if row.transfer_date else ""
        existing.add((row.player_id, row.from_club_id, row.to_club_id, dt))

    # Look up player name and DOB once (not inside the loop)
    player_result = await session.execute(
        text("SELECT name, date_of_birth FROM players WHERE player_id = :pid"),
        {"pid": player_id},
    )
    player_row = player_result.fetchone()
    player_name = player_row[0] if player_row else None
    raw_dob = player_row[1] if player_row else None
    player_dob = _parse_transfermarkt_date(str(raw_dob)) if raw_dob else None

    count = 0
    for t in transfers:
        club_from = t.get("clubFrom", {})
        club_to = t.get("clubTo", {})

        from_club_id = None
        raw_from = club_from.get("id")
        if raw_from:
            try:
                from_club_id = int(raw_from)
            except (ValueError, TypeError):
                pass

        to_club_id = None
        raw_to = club_to.get("id")
        if raw_to:
            try:
                to_club_id = int(raw_to)
            except (ValueError, TypeError):
                pass

        transfer_date = _parse_transfermarkt_date(t.get("date"))
        transfer_fee = _parse_fee(t.get("fee"))
        market_value = _parse_market_value(t.get("marketValue"))

        # Use config-based minimum year instead of hardcoded 2015
        if transfer_date and transfer_date.year < MIN_YEAR:
            continue

        # Build dedup key
        dt_str = str(transfer_date) if transfer_date else ""
        key = (player_id, from_club_id, to_club_id, dt_str)
        if key in existing:
            continue

        # Compute age at transfer from DOB
        age_at_transfer = _compute_age_at_transfer(player_dob, transfer_date)

        transfer = Transfer(
            player_id=player_id,
            player_name=player_name,
            from_club_id=from_club_id,
            to_club_id=to_club_id,
            from_club_name=club_from.get("name"),
            to_club_name=club_to.get("name"),
            transfer_date=transfer_date,
            transfer_season=t.get("season"),
            transfer_fee=transfer_fee,
            market_value_in_eur=market_value,
            age_at_transfer=age_at_transfer,
        )
        session.add(transfer)
        existing.add(key)
        count += 1

    if count > 0:
        await session.flush()
        logger.info("Inserted %d transfers for player %d", count, player_id)

    return count
