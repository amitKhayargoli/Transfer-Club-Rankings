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

from api.models import Club, Player

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
) -> list[tuple[int, str, int | None]]:
    """Get all players from clubs in the given leagues.

    Returns list of (player_id, player_name, current_club_id).
    """
    club_query = select(Club.club_id).where(
        Club.domestic_competition_id.in_(league_ids)
    )
    club_result = await session.execute(club_query)
    club_ids = [row[0] for row in club_result]

    if not club_ids:
        logger.warning("No clubs found for leagues: %s", league_ids)
        return []

    player_query = select(
        Player.player_id, Player.name, Player.current_club_id
    ).where(Player.current_club_id.in_(club_ids))
    player_result = await session.execute(player_query)
    players = [(row[0], row[1], row[2]) for row in player_result]

    logger.info(
        "Found %d players across %d clubs in leagues %s",
        len(players), len(club_ids), league_ids,
    )
    return players


async def get_players_by_clubs(
    session: AsyncSession,
    club_ids: list[int],
) -> list[tuple[int, str, int | None]]:
    """Get all players from specific clubs by their club IDs.

    Returns list of (player_id, player_name, current_club_id).
    """
    if not club_ids:
        return []

    player_query = select(
        Player.player_id, Player.name, Player.current_club_id
    ).where(Player.current_club_id.in_(club_ids))
    player_result = await session.execute(player_query)
    players = [(row[0], row[1], row[2]) for row in player_result]

    logger.info(
        "Found %d players across %d clubs (IDs: %s)",
        len(players), len(club_ids), club_ids,
    )
    return players
