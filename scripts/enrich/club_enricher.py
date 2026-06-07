"""
Club enrichment logic.

For each club:
1. Search by name in transfermarkt-api to find matching ID
2. Fetch club profile -> update clubs table
3. Fetch club players -> call player enrichment for each
4. Graph repair: find orphan clubs referenced in transfers but missing from clubs table
"""

import logging
import re
import time
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Club, Player, Transfer

logger = logging.getLogger(__name__)


# ── Club names that are metadata entries, not real clubs ────────────────────

NON_CLUB_NAMES = {
    "without club", "retired", "unknown", "career break",
    "without club a", "without club b", "career break a",
    "no club", "free agent", "unattached", "retired a",
}


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


# ── Graph Repair: Detect & fix missing source clubs ────────────────────────

# Patterns that indicate a club name is a reserve/youth team (low priority)
_RESERVE_PATTERNS = [
    r"\bu1[4-9]\b", r"\bu2[0-3]\b", r"\bU20\b", r"\bU19\b", r"\bU18\b", r"\bU17\b",
    r"\bII$", r"\bB$", r"\bB[\s_]", r"\bReservas\b", r"\bJong\b", r"\bJunior\b",
    r"\bJuvenil", r"\bSub-?1[4-9]\b", r"\bSub-?2[0-3]\b", r"\bYouth\b",
    r"\bUtd?\s*B$", r"\bFC\s*B$", r"Next Gen", r"\bU21\b", r"\bU23\b",
]


async def find_orphan_club_ids(
    session: AsyncSession,
    exclude_non_clubs: bool = True,
    exclude_reserves: bool = True,
    min_transfers: int = 1,
) -> list[tuple[int, str, int]]:
    """
    Find club IDs referenced in transfers/players but missing from the clubs table.

    Returns list of (club_id, club_name, transfer_count) ordered by transfer_count descending.

    Args:
        exclude_non_clubs: Filter out known metadata entries ("Without Club", "Retired", etc.)
        exclude_reserves: Filter out reserve/youth teams (U21, B teams, etc.)
        min_transfers: Minimum number of transfers referencing the club to include
    """
    raw = await session.execute(text("""
        SELECT cid, name, SUM(cnt) as total_cnt FROM (
            SELECT from_club_id AS cid, from_club_name AS name, COUNT(*) AS cnt
            FROM transfers WHERE from_club_id IS NOT NULL AND from_club_name IS NOT NULL
              AND from_club_name != ''
            GROUP BY from_club_id
            UNION ALL
            SELECT to_club_id, to_club_name, COUNT(*)
            FROM transfers WHERE to_club_id IS NOT NULL AND to_club_name IS NOT NULL
              AND to_club_name != ''
            GROUP BY to_club_id
        ) AS edge_counts
        WHERE cid NOT IN (SELECT club_id FROM clubs)
        GROUP BY cid, name
        ORDER BY SUM(cnt) DESC
    """))

    result = []
    for row in raw:
        cid, name, count = row[0], str(row[1] or ""), int(row[2])

        if count < min_transfers:
            continue

        if exclude_non_clubs and name.lower().strip() in NON_CLUB_NAMES:
            continue

        if exclude_reserves:
            is_reserve = False
            for pattern in _RESERVE_PATTERNS:
                if re.search(pattern, name, re.IGNORECASE):
                    is_reserve = True
                    break
            if is_reserve:
                continue

        result.append((cid, name, count))

    return result


async def repair_missing_clubs(
    session: AsyncSession,
    client: Any,
    dry_run: bool = False,
    batch_size: int | None = None,
    min_transfers: int = 1,
    include_reserves: bool = False,
) -> dict:
    """
    Find orphan clubs (referenced in transfers but missing from clubs table)
    and fetch their profiles from Transfermarkt to upsert them.

    This is the "graph repair" step — it ensures the club graph is complete so
    that every referenced club_id exists in the clubs table.

    Args:
        client: TransfermarktClient instance with rate limiting
        dry_run: If True, only report what would be done
        batch_size: Max clubs to process (None = all)
        min_transfers: Minimum transfer count for a club to be included
        include_reserves: If True, also process reserve/youth teams

    Returns:
        dict with keys: found, processed, succeeded, failed, skipped
    """
    orphan_clubs = await find_orphan_club_ids(
        session,
        exclude_non_clubs=True,
        exclude_reserves=not include_reserves,
        min_transfers=min_transfers,
    )

    if not orphan_clubs:
        logger.info("No orphan clubs found — the graph is complete!")
        return {"found": 0, "processed": 0, "succeeded": 0, "failed": 0, "skipped": 0}

    # Filter existing clubs so we only process truly new ones
    existing_ids = set()
    raw_existing = await session.execute(text("SELECT club_id FROM clubs"))
    for row in raw_existing:
        existing_ids.add(int(row[0]))

    to_process = [(cid, name, cnt) for cid, name, cnt in orphan_clubs if cid not in existing_ids]

    if batch_size:
        to_process = to_process[:batch_size]

    if dry_run:
        logger.info(
            "[DRY RUN] Found %d orphan clubs (%d will be processed, %d already exist)",
            len(orphan_clubs), len(to_process), len(orphan_clubs) - len(to_process),
        )
        for cid, name, cnt in to_process[:20]:
            logger.info("  [DRY RUN] Would fetch club %d: '%s' (%d transfers)", cid, name, cnt)
        if len(to_process) > 20:
            logger.info("  ... and %d more", len(to_process) - 20)
        return {
            "found": len(orphan_clubs),
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": len(orphan_clubs) - len(to_process),
        }

    stats = {"found": len(orphan_clubs), "processed": 0, "succeeded": 0, "failed": 0, "skipped": 0}
    start_time = time.time()

    for idx, (club_id, club_name, transfer_count) in enumerate(to_process, 1):
        # Check again (in case another batch added it)
        existing = await session.get(Club, club_id)
        if existing:
            stats["skipped"] += 1
            continue

        try:
            profile = client.get_club_profile(str(club_id))
            if not profile:
                logger.warning("  No profile for club %d (%s), inserting minimal record", club_id, club_name)
                # Still insert the club with just the name so the graph is connected
                club = Club(
                    club_id=club_id,
                    name=club_name[:100],
                )
                session.add(club)
                await session.flush()
                stats["succeeded"] += 1
                continue

            # Create or update the club record
            club = Club(
                club_id=club_id,
                name=club_name[:100],
            )
            session.add(club)
            await session.flush()

            # Enrich with profile data
            updated = await enrich_club_profile(session, club, profile)
            stats["succeeded"] += 1

            if updated:
                logger.info(
                    "  [%d/%d] ✓ Club %d: '%s' (%d transfers) — %s",
                    idx, len(to_process), club_id, profile.get("name", club_name),
                    transfer_count,
                    profile.get("league", {}).get("id", "no league") if isinstance(profile.get("league"), dict) else "",
                )
            else:
                logger.info(
                    "  [%d/%d] ✓ Club %d: '%s' (%d transfers) — minimal insert",
                    idx, len(to_process), club_id, club_name, transfer_count,
                )

        except Exception as e:
            logger.error("  [%d/%d] ✗ Failed club %d (%s): %s", idx, len(to_process), club_id, club_name, e)
            # Still insert a minimal record so the graph is at least connected
            try:
                club = Club(club_id=club_id, name=club_name[:100])
                session.add(club)
                await session.flush()
                stats["succeeded"] += 1
            except Exception:
                stats["failed"] += 1

        stats["processed"] += 1

        if idx % 50 == 0:
            await session.commit()
            elapsed = time.time() - start_time
            rate = idx / elapsed if elapsed > 0 else 0
            logger.info(
                "  Progress: %d/%d clubs | Rate: %.1f/min | Succeeded: %d | Failed: %d",
                idx, len(to_process), rate * 60, stats["succeeded"], stats["failed"],
            )

    await session.commit()
    elapsed = time.time() - start_time
    logger.info(
        "\nGraph repair complete: %d clubs processed in %.1fs (%.1f/min). "
        "Succeeded: %d, Failed: %d, Skipped: %d",
        stats["processed"], elapsed,
        stats["processed"] / elapsed * 60 if elapsed > 0 else 0,
        stats["succeeded"], stats["failed"], stats["skipped"],
    )

    return stats


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
