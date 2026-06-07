"""
Player Career Reconstruction Engine — LEGACY MODULE.

This module now only contains profile enrichment functions used by
--enrich-profiles mode. All career detection and reconstruction logic
has moved to reconstruction_runner.py (the Graph Truth Engine pipeline).

Remaining functions:
  - detect_incomplete_profiles()
  - enrich_player_profile_only()
  - enrich_profiles_batch()

For career reconstruction, use:
  python scripts/enrich_data.py --reconstruct-careers
"""

import logging
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ── Profile Enrichment ────────────────────────────────────────────────────

async def detect_incomplete_profiles(
    session: AsyncSession,
    fields: list[str] | None = None,
    max_count: int | None = None,
) -> list[tuple[int, str, str]]:
    """Find players missing profile data (image_url, citizenship, etc.).

    These players have complete transfer histories but their profile fields
    haven't been populated yet — likely because they were loaded from CSV
    before the API enrichment was added.

    Args:
        fields: Profile fields to check. Defaults to ["image_url"]
        max_count: Max players to return

    Returns:
        List of (player_id, name, missing_field) sorted by market value
    """
    if fields is None:
        fields = ["image_url"]

    # Validate fields against whitelist to prevent SQL injection
    allowed = {"image_url", "citizenship", "agent_name", "contract_expiry_date", "position"}
    safe_fields = [f for f in fields if f in allowed]

    if not safe_fields:
        logger.warning("No valid fields specified: %s", fields)
        return []

    conditions = " OR ".join(f"p.{f} IS NULL" for f in safe_fields)

    result = await session.execute(text(f"""
        SELECT p.player_id, p.name
        FROM players p
        WHERE {conditions}
        ORDER BY p.market_value_in_eur DESC NULLS LAST
    """))

    results = [(int(r[0]), str(r[1]), ", ".join(safe_fields)) for r in result]

    if max_count:
        results = results[:max_count]

    return results


async def enrich_player_profile_only(
    session: AsyncSession,
    client: Any,
    player_id: int,
) -> dict:
    """Lightweight profile-only enrichment for a single player.

    Only fetches the player's Transfermarkt profile (not transfers or
    valuations) — 1 API call instead of 3. This is the right choice
    for players whose transfer history is already complete.

    Returns:
        dict with keys: updated, profile_field
    """
    stats = {"updated": False, "fields_found": []}

    try:
        profile = client.get_player_profile(str(player_id))
        if not profile:
            return stats

        from scripts.enrich.player_enricher import enrich_player_profile
        updated = await enrich_player_profile(session, player_id, profile)
        stats["updated"] = updated

        # Track which fields were populated
        if profile.get("imageUrl"):
            stats["fields_found"].append("image_url")
        if profile.get("citizenship"):
            stats["fields_found"].append("citizenship")
        if profile.get("agent"):
            stats["fields_found"].append("agent")

        await session.flush()

    except Exception as e:
        logger.error("  Failed to enrich profile for player %d: %s", player_id, e)
        raise

    return stats


async def enrich_profiles_batch(
    session: AsyncSession,
    client: Any,
    candidates: list[tuple[int, str, str]],
    dry_run: bool = False,
) -> dict:
    """Enrich profiles for a batch of players (profiles only, no transfers).

    Args:
        candidates: List of (player_id, name, fields_missing)
        dry_run: If True, only report what would be done

    Returns:
        dict with enrichment stats
    """
    stats = {
        "total_candidates": len(candidates),
        "processed": 0,
        "updated": 0,
        "failed": 0,
    }
    start_time = time.time()

    for idx, (player_id, player_name, fields) in enumerate(candidates, 1):
        if dry_run:
            logger.info(
                "  [%d/%d] [DRY RUN] Would enrich profile for %s (ID %d) — missing: %s",
                idx, stats["total_candidates"], player_name, player_id, fields,
            )
            stats["processed"] += 1
            continue

        player_start = time.time()

        try:
            result = await enrich_player_profile_only(session, client, player_id)
            elapsed = time.time() - player_start

            if result["updated"]:
                fields = ", ".join(result["fields_found"])
                logger.info(
                    "  [%d/%d] ✓ %s (ID %d): +%s in %.1fs",
                    idx, stats["total_candidates"], player_name, player_id,
                    fields, elapsed,
                )
                stats["updated"] += 1
            else:
                logger.info(
                    "  [%d/%d] ~ %s (ID %d): profile fetched but no new data in %.1fs",
                    idx, stats["total_candidates"], player_name, player_id, elapsed,
                )

            stats["processed"] += 1

        except Exception as e:
            logger.error(
                "  [%d/%d] ✗ Failed %s (ID %d): %s",
                idx, stats["total_candidates"], player_name, player_id, e,
            )
            stats["failed"] += 1

        # Progress report every 25 players
        if idx % 25 == 0:
            elapsed = time.time() - start_time
            rate = idx / elapsed if elapsed > 0 else 0
            remaining = stats["total_candidates"] - idx
            eta = remaining / rate if rate > 0 else 0
            logger.info(
                "  Progress: %d/%d | +%d profiles | Rate: %.1f/min | ETA: %.0fs",
                idx, stats["total_candidates"],
                stats["updated"], rate * 60, eta,
            )

    return stats
