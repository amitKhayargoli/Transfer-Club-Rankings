"""
Club enrichment logic.

For each club:
1. Search by name in transfermarkt-api to find matching ID
2. Fetch club profile -> update clubs table
3. Fetch club players -> call player enrichment for each
"""

import logging
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Club, Player, Transfer

logger = logging.getLogger(__name__)


def _name_similarity(name_a: str, name_b: str) -> float:
    """Compute similarity ratio between two club names (case-insensitive)."""
    a = name_a.lower().strip()
    b = name_b.lower().strip()
    return SequenceMatcher(None, a, b).ratio()


def _find_best_club_match(
    search_results: list[dict],
    target_name: str,
    threshold: float = 0.6,
) -> dict | None:
    """Find the best matching club in search results by name similarity."""
    best_match = None
    best_score = 0.0

    for club in search_results:
        score = _name_similarity(target_name, club.get("name", ""))
        if score > best_score:
            best_score = score
            best_match = club

    if best_score >= threshold:
        logger.debug(
            "Matched '%s' -> '%s' (score: %.2f)",
            target_name, best_match.get("name"), best_score,
        )
        return best_match

    logger.warning(
        "No good match for '%s' (best: '%s' score=%.2f, below threshold=%.2f)",
        target_name,
        best_match.get("name") if best_match else "None",
        best_score,
        threshold,
    )
    return None


async def enrich_club_profile(
    session: AsyncSession,
    db_club: Club,
    profile: dict,
) -> bool:
    """Update a club's record with data from the transfermarkt-api profile.

    Returns True if the club was updated.
    """
    updated = False

    name = profile.get("name")
    if name and name.strip():
        db_club.name = name.strip()
        updated = True

    url = profile.get("url")
    if url:
        slug = url.strip("/").split("/")[0] if "/" in url else None
        if slug and slug != "startseite":
            db_club.club_code = slug
            updated = True

    league = profile.get("league")
    if league and isinstance(league, dict):
        comp_id = league.get("id")
        if comp_id:
            db_club.domestic_competition_id = comp_id
            updated = True

    if updated:
        await session.flush()

    return updated


async def get_players_by_league(
    session: AsyncSession,
    league_ids: list[str],
) -> list[tuple[int, str, int | None, float]]:
    """Get all players associated with clubs in the given leagues.

    Finds players through two approaches:
    1. **Transfer history**: players who have a transfer TO or FROM a club in the
       target league (filtered to exclude retired players via a JOIN with
       ``Player.current_club_name != "Retired"``).
    2. **Current club**: players whose ``current_club_id`` matches a club in the
       target league **and** who have a ``market_value_in_eur > 0`` **and** are not
       marked as retired (``current_club_name != "Retired"``).

    Returns a deduplicated list of (player_id, player_name, current_club_id, market_value_in_eur),
    sorted by market value descending (highest-value players first).
    """
    from sqlalchemy import select as sa_select

    # ── 1. Resolve league club IDs ────────────────────────────────────────

    club_query = select(Club.club_id).where(
        Club.domestic_competition_id.in_(league_ids)
    )
    club_result = await session.execute(club_query)
    club_ids = [row[0] for row in club_result]

    if not club_ids:
        logger.warning("No clubs found for leagues: %s", league_ids)
        return []

    logger.info("Found %d clubs in leagues %s", len(club_ids), league_ids)

    # ── 2. Players with a transfer TO / FROM a league club ────────────────

    transfer_player_ids: set[int] = set()
    from_result = await session.execute(
        sa_select(Transfer.player_id)
        .join(Player, Transfer.player_id == Player.player_id)
        .where(
            Transfer.from_club_id.in_(club_ids),
            Player.current_club_name != "Retired",
        )
        .distinct()
    )
    to_result = await session.execute(
        sa_select(Transfer.player_id)
        .join(Player, Transfer.player_id == Player.player_id)
        .where(
            Transfer.to_club_id.in_(club_ids),
            Player.current_club_name != "Retired",
        )
        .distinct()
    )
    transfer_player_ids = {
        row[0] for row in from_result
    } | {
        row[0] for row in to_result
    }

    logger.info(
        "Found %d players via transfer history with league clubs",
        len(transfer_player_ids),
    )

    # ── 3. Players whose current_club_id is a league club ─────────────────

    current_club_result = await session.execute(
        sa_select(Player.player_id, Player.name, Player.current_club_id, Player.market_value_in_eur)
        .where(Player.current_club_id.in_(club_ids))
    )
    current_club_rows = [(row[0], row[1], row[2], row[3] or 0) for row in current_club_result]
    current_club_player_ids = {row[0] for row in current_club_rows}

    logger.info(
        "Found %d players via current_club_id in league clubs",
        len(current_club_player_ids),
    )

    # Players found only via current_club_id (not already covered by transfer history)
    # are included if they have a market value > 0 and are not retired.
    # This catches stars whose transfers are not yet in the DB (e.g. Enzo, Haaland, etc.).
    only_current_club_ids = current_club_player_ids - transfer_player_ids

    active_only_current_ids: set[int] = set()
    if only_current_club_ids:
        active_result = await session.execute(
            sa_select(Player.player_id)
            .where(
                Player.player_id.in_(list(only_current_club_ids)),
                Player.market_value_in_eur > 0,
                Player.current_club_name != "Retired",
            )
        )
        active_only_current_ids = {row[0] for row in active_result}

    # ── 4. Combine both approaches ────────────────────────────────────────

    valid_player_ids: set[int] = transfer_player_ids | active_only_current_ids

    # Build player info lookup for all valid IDs
    player_info: dict[int, tuple[str, int | None, float]] = {
        row[0]: (row[1], row[2], row[3]) for row in current_club_rows
    }

    # Fetch player info for transfer-based players not in current_club_rows
    missing_ids = [pid for pid in valid_player_ids if pid not in player_info]
    if missing_ids:
        missing_result = await session.execute(
            sa_select(Player.player_id, Player.name, Player.current_club_id, Player.market_value_in_eur)
            .where(Player.player_id.in_(missing_ids))
        )
        for row in missing_result:
            player_info[row[0]] = (row[1], row[2], row[3] or 0)

    players = [
        (pid, player_info[pid][0], player_info[pid][1], player_info[pid][2])
        for pid in valid_player_ids
        if pid in player_info
    ]

    # Sort by market value descending (biggest stars first)
    players.sort(key=lambda p: p[3], reverse=True)

    skipped = len(current_club_rows) - len(players)
    logger.info(
        "Found %d players to enrich (%d via transfer history, %d via current club, "
        "%d skipped as inactive) across %d clubs in leagues %s",
        len(players),
        len(transfer_player_ids),
        len(active_only_current_ids),
        skipped,
        len(club_ids),
        league_ids,
    )
    return players


async def get_players_by_clubs(
    session: AsyncSession,
    club_ids: list[int],
) -> list[tuple[int, str, int | None, float]]:
    """Get all players associated with specific clubs by their club IDs.

    Uses the same dual approach as :func:`get_players_by_league`:
    transfer history + current_club_id.

    Returns list of (player_id, player_name, current_club_id, market_value_in_eur),
    sorted by market value descending.
    """
    if not club_ids:
        return []

    from sqlalchemy import select as sa_select

    # ── 1. Players with a transfer TO / FROM specified clubs ──────────────

    transfer_player_ids: set[int] = set()
    from_result = await session.execute(
        sa_select(Transfer.player_id)
        .join(Player, Transfer.player_id == Player.player_id)
        .where(
            Transfer.from_club_id.in_(club_ids),
            Player.current_club_name != "Retired",
        )
        .distinct()
    )
    to_result = await session.execute(
        sa_select(Transfer.player_id)
        .join(Player, Transfer.player_id == Player.player_id)
        .where(
            Transfer.to_club_id.in_(club_ids),
            Player.current_club_name != "Retired",
        )
        .distinct()
    )
    transfer_player_ids = {
        row[0] for row in from_result
    } | {
        row[0] for row in to_result
    }

    logger.info(
        "Found %d players via transfer history with clubs (IDs: %s)",
        len(transfer_player_ids), club_ids,
    )

    # ── 2. Players whose current_club_id matches specified clubs ──────────

    current_club_result = await session.execute(
        sa_select(Player.player_id, Player.name, Player.current_club_id, Player.market_value_in_eur)
        .where(Player.current_club_id.in_(club_ids))
    )
    current_club_rows = [(row[0], row[1], row[2], row[3] or 0) for row in current_club_result]
    current_club_player_ids = {row[0] for row in current_club_rows}

    logger.info(
        "Found %d players via current_club_id in specified clubs",
        len(current_club_player_ids),
    )

    # Players found only via current_club_id (not already covered by transfer history)
    # are included if they have a market value > 0 and are not retired.
    # This catches stars whose transfers are not yet in the DB (e.g. Enzo, Haaland, etc.).
    only_current_club_ids = current_club_player_ids - transfer_player_ids

    active_only_current_ids: set[int] = set()
    if only_current_club_ids:
        active_result = await session.execute(
            sa_select(Player.player_id)
            .where(
                Player.player_id.in_(list(only_current_club_ids)),
                Player.market_value_in_eur > 0,
                Player.current_club_name != "Retired",
            )
        )
        active_only_current_ids = {row[0] for row in active_result}

    # ── 3. Combine ────────────────────────────────────────────────────────

    valid_player_ids: set[int] = transfer_player_ids | active_only_current_ids

    player_info: dict[int, tuple[str, int | None, float]] = {
        row[0]: (row[1], row[2], row[3]) for row in current_club_rows
    }
    missing_ids = [pid for pid in valid_player_ids if pid not in player_info]
    if missing_ids:
        missing_result = await session.execute(
            sa_select(Player.player_id, Player.name, Player.current_club_id, Player.market_value_in_eur)
            .where(Player.player_id.in_(missing_ids))
        )
        for row in missing_result:
            player_info[row[0]] = (row[1], row[2], row[3] or 0)

    players = [
        (pid, player_info[pid][0], player_info[pid][1], player_info[pid][2])
        for pid in valid_player_ids
        if pid in player_info
    ]
    # Sort by market value descending (biggest stars first)
    players.sort(key=lambda p: p[3], reverse=True)

    skipped = len(current_club_rows) - len(players)
    logger.info(
        "Found %d active players (%d via transfers, %d via current club, "
        "%d skipped) across %d clubs (IDs: %s)",
        len(players),
        len(transfer_player_ids),
        len(active_only_current_ids),
        skipped,
        len(club_ids),
        club_ids,
    )
    return players
