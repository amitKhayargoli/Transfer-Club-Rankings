"""
Reconstruction Runner — upgraded pipeline for the Graph Truth Engine.

Pipeline:
  detect → fingerprint → score → validated insert → analytics → validate → report

Compared to the old career_reconstructor.py:
  OLD: API → diff → insert
  NEW: API → normalize → fingerprint → confidence score → validated insert

Key improvements:
  - Robust Identity: TransferFingerprint handles fuzzy matching (NULL IDs, date variants)
  - Confidence Scoring: Every transfer is scored 0-1 before insertion
  - Graph Validation: Post-reconstruction health check
  - Dual-Signal Convergence: Unpaired sells + inserted rate + graph health
  - No Dedup Risk: Fingerprint matching prevents ALL duplicate scenarios
"""

import asyncio
import logging
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.enrich.transfer_fingerprint import (
    TransferFingerprint,
)
from scripts.enrich.confidence_scorer import (
    ConfidenceScorer, ConfidenceResult, MIN_INSERT_THRESHOLD,
    compute_confidence_distribution,
)
from scripts.enrich.graph_validator import (
    validate_transfer_graph, GraphValidationReport,
)

logger = logging.getLogger(__name__)

# Non-real Transfermarkt club IDs that are status markers, not actual clubs.
# Players transferring FROM these clubs will always appear as unpaired
# (no one ever arrives at "Without Club"), so they're excluded from detection.
NON_REAL_CLUBS = (515, 2113, 75)  # Without Club, Career break, Unknown


# ── New Detection Layer ───────────────────────────────────────────────────
# Uses fingerprint-based matching + timeline validation

async def detect_broken_chains(
    session: AsyncSession,
    min_fee: float = 100_000,
    max_count: int | None = None,
    exclude_player_ids: set[int] | None = None,
) -> list[tuple[int, str, float, int]]:
    """Detect structurally broken transfer chains using NOT EXISTS.

    Pure structural detection — no roi_pct dependency.
    Excludes:
    - Non-real clubs (Without Club=515, Career break=2113, Unknown=75)
    - Players already processed with 0 inserts (via exclude_player_ids)
    """
    exclude_clause = ""
    if exclude_player_ids:
        id_list = ",".join(str(pid) for pid in exclude_player_ids)
        exclude_clause = f"AND t.player_id NOT IN ({id_list})"

    result = await session.execute(text(f"""
        SELECT t.player_id, p.name,
               ROUND(SUM(t.transfer_fee), 0) as total_fee,
               COUNT(*) as sell_count
        FROM transfers t
        JOIN players p ON t.player_id = p.player_id
        JOIN clubs c ON t.from_club_id = c.club_id
        WHERE t.transfer_fee > :min_fee
          AND t.from_club_id IS NOT NULL
          AND t.from_club_id NOT IN {NON_REAL_CLUBS}
          AND NOT EXISTS (
              SELECT 1 FROM transfers t2
              WHERE t2.player_id = t.player_id
                AND t2.to_club_id = t.from_club_id
          )
          {exclude_clause}
        GROUP BY t.player_id
        ORDER BY SUM(t.transfer_fee) DESC
    """), {"min_fee": min_fee})

    results = [(int(r[0]), str(r[1]), float(r[2]), int(r[3])) for r in result]

    if max_count:
        results = results[:max_count]

    return results


async def detect_silent_origin_gaps(
    session: AsyncSession,
    min_fee: float = 100_000,
    max_count: int | None = None,
) -> list[tuple[int, str, float, int]]:
    """Detect players whose first transfer origin club is orphan/missing."""
    result = await session.execute(text("""
        WITH first_transfer AS (
            SELECT player_id, MIN(transfer_date) as first_date
            FROM transfers
            WHERE transfer_fee IS NOT NULL AND transfer_fee > :min_fee
            GROUP BY player_id
        )
        SELECT p.player_id, p.name,
               ROUND(COALESCE(ft_first.transfer_fee, 0), 0) as max_fee,
               COUNT(t_all.transfer_id) as transfer_count
        FROM first_transfer ft
        JOIN players p ON p.player_id = ft.player_id
        JOIN transfers ft_first ON ft_first.player_id = ft.player_id
            AND ft_first.transfer_date = ft.first_date
            AND ft_first.transfer_fee > :min_fee
        JOIN transfers t_all ON t_all.player_id = p.player_id
        WHERE ft_first.from_club_id IS NULL
           OR ft_first.from_club_id NOT IN (
               SELECT club_id FROM clubs WHERE club_id IS NOT NULL
           )
        GROUP BY p.player_id
        ORDER BY ft_first.transfer_fee DESC NULLS LAST
    """), {"min_fee": min_fee})

    results = [(int(r[0]), str(r[1]), float(r[2]), int(r[3])) for r in result]

    if max_count:
        results = results[:max_count]

    return results


# ── Fingerprint-based Reconstruction ──────────────────────────────────────


async def _retry_flush(session: AsyncSession, max_retries: int = 5, base_delay: float = 0.5):
    """Flush session with exponential backoff on 'database is locked' errors.

    Retries at the flush level so API calls (~5s per player) aren't wasted
    on retries of the entire career reconstruction function.
    """
    for attempt in range(max_retries):
        try:
            await session.flush()
            return
        except Exception as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)  # 0.5, 1.0, 2.0, 4.0, 8.0
                logger.warning(
                    "  Database locked, retrying flush in %.1fs (attempt %d/%d)",
                    delay, attempt + 1, max_retries,
                )
                await asyncio.sleep(delay)
                try:
                    await session.rollback()
                except Exception:
                    pass
            else:
                raise


async def reconstruct_player_career_v2(
    session: AsyncSession,
    client: Any,
    player_id: int,
    confidence_threshold: float = MIN_INSERT_THRESHOLD,
) -> dict:
    """Reconstruct player career using fingerprint-based matching.

    Pipeline: API → normalize → fingerprint → confidence score → validated insert

    Returns:
        dict with keys:
            profile_updated, transfers_found, transfers_attempted,
            transfers_inserted, confidence_distribution, skipped_reasons
    """
    stats = {
        "profile_updated": False,
        "transfers_found": 0,
        "transfers_attempted": 0,
        "transfers_inserted": 0,
        "confidence_scores": [],
        "skipped_reasons": [],
    }

    try:
        # 1. Profile enrichment (unchanged)
        profile = client.get_player_profile(str(player_id))
        if profile:
            from scripts.enrich.player_enricher import enrich_player_profile
            updated = await enrich_player_profile(session, player_id, profile)
            stats["profile_updated"] = updated

        # 2. Fetch all transfers from API
        transfers_data = client.get_player_transfers(str(player_id))
        if not transfers_data:
            return stats

        api_transfers = transfers_data.get("transfers", [])
        stats["transfers_found"] = len(api_transfers)

        if not api_transfers:
            return stats

        # 3. Fetch existing DB transfers for this player
        db_rows = await session.execute(
            text("""
                SELECT player_id, from_club_id, to_club_id,
                       from_club_name, to_club_name,
                       transfer_date, transfer_season, transfer_fee
                FROM transfers WHERE player_id = :pid
            """),
            {"pid": player_id},
        )
        existing_db = db_rows.fetchall()

        # 4. Build DB fingerprint set
        db_fingerprints = []
        for row in existing_db:
            try:
                fp = TransferFingerprint.from_db_transfer(row)
                db_fingerprints.append(fp)
            except Exception as e:
                logger.warning("  Failed to fingerprint DB row for player %d: %s", player_id, e)

        # 5. For each API transfer: fingerprint → score → decide
        scorer = ConfidenceScorer()
        to_insert = []
        confidence_results: list[ConfidenceResult] = []

        for api_t in api_transfers:
            try:
                api_fp = TransferFingerprint.from_api_transfer(api_t, player_id)
            except Exception as e:
                logger.warning("  Failed to fingerprint API transfer for player %d: %s", player_id, e)
                stats["skipped_reasons"].append("fingerprint_failed")
                continue

            result = scorer.score_api_transfer(api_fp, db_fingerprints)
            confidence_results.append(result)
            stats["confidence_scores"].append(result.score)

            if result.insert_decision == "reject":
                stats["skipped_reasons"].append(f"rejected:{result.score}")
                continue

            if result.insert_decision == "review" and result.score < confidence_threshold:
                stats["skipped_reasons"].append(f"below_threshold:{result.score}")
                continue

            # Decision: insert
            to_insert.append((api_t, api_fp, result))
            stats["transfers_attempted"] += 1

        # 6. Insert only high-confidence transfers
        if to_insert:
            from scripts.enrich.player_enricher import (
                _parse_transfermarkt_date, _parse_fee, _parse_market_value,
                _compute_age_at_transfer,
            )
            from api.config import MIN_YEAR
            from api.models import Transfer

            player_result = await session.execute(
                text("SELECT name, date_of_birth FROM players WHERE player_id = :pid"),
                {"pid": player_id},
            )
            player_row = player_result.fetchone()
            player_name = player_row[0] if player_row else None
            raw_dob = player_row[1] if player_row else None
            player_dob = _parse_transfermarkt_date(str(raw_dob)) if raw_dob else None

            inserted = 0
            for api_t, api_fp, result in to_insert:
                club_from = api_t.get("clubFrom", {})
                club_to = api_t.get("clubTo", {})

                from_club_id = api_fp.from_club_id
                to_club_id = api_fp.to_club_id

                transfer_date = _parse_transfermarkt_date(api_t.get("date"))
                transfer_fee = _parse_fee(api_t.get("fee"))
                market_value = _parse_market_value(api_t.get("marketValue"))

                if transfer_date and transfer_date.year < MIN_YEAR:
                    continue

                age_at_transfer = _compute_age_at_transfer(player_dob, transfer_date)
                fp_hash = api_fp.compute_hash()

                import json

                transfer = Transfer(
                    player_id=player_id,
                    player_name=player_name,
                    from_club_id=from_club_id,
                    to_club_id=to_club_id,
                    from_club_name=club_from.get("name"),
                    to_club_name=club_to.get("name"),
                    transfer_date=transfer_date,
                    transfer_season=api_t.get("season") or api_fp.transfer_season,
                    transfer_fee=transfer_fee,
                    market_value_in_eur=market_value,
                    age_at_transfer=age_at_transfer,
                    confidence_score=result.score,
                    fingerprint_hash=fp_hash,
                    confidence_reasons=json.dumps(result.reasons[:5]),
                )
                session.add(transfer)
                inserted += 1
                db_fingerprints.append(api_fp)  # prevent self-dupes in batch

            stats["transfers_inserted"] = inserted

            if inserted > 0:
                await _retry_flush(session)

        # 7. Market values (unchanged)
        mv_data = client.get_player_market_value(str(player_id))
        if mv_data:
            from scripts.enrich.player_enricher import enrich_player_valuations
            await enrich_player_valuations(session, player_id, mv_data)

        await _retry_flush(session)

    except Exception as e:
        logger.error("  Failed to reconstruct player %d: %s", player_id, e)
        raise

    return stats


async def reconstruct_careers_batch_v2(
    session: AsyncSession,
    client: Any,
    candidates: list[tuple[int, str, float, int]],
    dry_run: bool = False,
    confidence_threshold: float = MIN_INSERT_THRESHOLD,
) -> dict:
    """Batch reconstruction with confidence tracking.

    Returns dict with full stats including confidence distribution.
    """
    stats = {
        "total_candidates": len(candidates),
        "processed": 0,
        "profile_updated": 0,
        "transfers_found": 0,
        "transfers_attempted": 0,
        "transfers_inserted": 0,
        "failed": 0,
        "skipped": 0,
        "confidence_scores": [],
    }
    start_time = time.time()

    for idx, (player_id, player_name, fee_value, _) in enumerate(candidates, 1):
        if dry_run:
            fee_str = f"€{fee_value/1_000_000:.1f}M" if fee_value >= 1_000_000 else f"€{fee_value:,.0f}"
            logger.info(
                "  [%d/%d] [DRY RUN] Would reconstruct %s (ID %d): %s",
                idx, stats["total_candidates"], player_name, player_id, fee_str,
            )
            stats["processed"] += 1
            continue

        player_start = time.time()

        result = None
        error_msg = ""
        try:
            result = await reconstruct_player_career_v2(
                session, client, player_id,
                confidence_threshold=confidence_threshold,
            )
        except Exception as e:
            error_msg = str(e)
            # Retry once on transient SQLite locking errors
            if "database is locked" in error_msg:
                await asyncio.sleep(1.5)  # longer backoff for lock contention
                try:
                    await session.rollback()
                    result = await reconstruct_player_career_v2(
                        session, client, player_id,
                        confidence_threshold=confidence_threshold,
                    )
                except Exception as retry_err:
                    error_msg = f"{error_msg} (retry: {retry_err})"
                    logger.error("  [%d/%d] ✗ Retry also failed for %s (ID %d): %s",
                                  idx, stats["total_candidates"], player_name, player_id, retry_err)
                    await session.rollback()
            else:
                try:
                    await session.rollback()
                except Exception:
                    pass

        if result is None:
            logger.error("  [%d/%d] ✗ Failed %s (ID %d): %s", idx, stats["total_candidates"], player_name, player_id, error_msg)
            stats["failed"] += 1
            continue

        # Single stats-accumulation path — used by both first attempt and retry
        elapsed = time.time() - player_start

        if result["profile_updated"]:
            stats["profile_updated"] += 1
        stats["transfers_found"] += result["transfers_found"]
        stats["transfers_attempted"] += result["transfers_attempted"]
        stats["transfers_inserted"] += result["transfers_inserted"]
        stats["confidence_scores"].extend(result["confidence_scores"])
        stats["processed"] += 1

        # Track players with 0 inserts (used by pipeline to skip future iterations)
        if result["transfers_inserted"] == 0:
            stats.setdefault("zero_insert_ids", []).append(player_id)

        fee_str = f"€{fee_value/1_000_000:.1f}M" if fee_value >= 1_000_000 else f"€{fee_value:,.0f}"

        if result["transfers_inserted"] > 0:
            avg_conf = sum(result["confidence_scores"]) / max(len(result["confidence_scores"]), 1)
            logger.info(
                "  [%d/%d] ✓ %s (ID %d): +%d transfers (attempted %d/%d, avg conf %.2f) in %.1fs — %s",
                idx, stats["total_candidates"], player_name, player_id,
                result["transfers_inserted"], result["transfers_attempted"],
                result["transfers_found"], avg_conf, elapsed, fee_str,
            )
        else:
            reasons = set(result["skipped_reasons"][:3])
            reason_str = ", ".join(reasons) if reasons else "all existed"
            logger.info(
                "  [%d/%d] ~ %s (ID %d): 0 new transfers (%d found, %s) in %.1fs",
                idx, stats["total_candidates"], player_name, player_id,
                result["transfers_found"], reason_str, elapsed,
            )
            stats["skipped"] += 1

        if idx % 10 == 0 and not dry_run:
            elapsed = time.time() - start_time
            rate = idx / elapsed if elapsed > 0 else 0
            remaining = stats["total_candidates"] - idx
            eta = remaining / rate if rate > 0 else 0
            logger.info(
                "  Progress: %d/%d | +%d inserts | Conf: %s | Rate: %.1f/min | ETA: %.0fs",
                idx, stats["total_candidates"],
                stats["transfers_inserted"],
                _format_confidence_summary(stats["confidence_scores"]),
                rate * 60, eta,
            )

    # Compute confidence distribution
    if stats["confidence_scores"]:
        dist = {"high": 0, "medium": 0, "low": 0}
        for s in stats["confidence_scores"]:
            if s >= 0.9:
                dist["high"] += 1
            elif s >= 0.7:
                dist["medium"] += 1
            else:
                dist["low"] += 1
        stats["confidence_distribution"] = dist
    else:
        stats["confidence_distribution"] = {"high": 0, "medium": 0, "low": 0}

    return stats


def _format_confidence_summary(scores: list[float]) -> str:
    """Format confidence score list as a short summary string."""
    if not scores:
        return "no_scores"
    avg = sum(scores) / len(scores)
    high = sum(1 for s in scores if s >= 0.9)
    return f"avg={avg:.2f}, high={high}/{len(scores)}"


# ── Convergence Engine ────────────────────────────────────────────────────
# Triple-signal convergence: unpaired sells + inserted rate + graph health

async def count_unpaired_sells(session: AsyncSession) -> dict:
    """Audit structurally unpaired sells (for convergence checking)."""
    result = await session.execute(text(f"""
        SELECT COUNT(*), ROUND(COALESCE(SUM(t.transfer_fee), 0), 0)
        FROM transfers t
        JOIN clubs c ON t.from_club_id = c.club_id
        WHERE t.transfer_fee > 100000
          AND t.from_club_id IS NOT NULL
          AND t.from_club_id NOT IN {NON_REAL_CLUBS}
          AND NOT EXISTS (
              SELECT 1 FROM transfers t2
              WHERE t2.player_id = t.player_id
                AND t2.to_club_id = t.from_club_id
          )
    """))
    row = result.fetchone()
    return {"count": int(row[0]), "total_value": float(row[1])}


async def run_reconstruction_pipeline(
    session: AsyncSession,
    client: Any,
    dry_run: bool = False,
    batch_size: int = 50,
    max_iterations: int = 5,
    min_fee: float = 100_000,
    strategy: str = "by_fee",
    confidence_threshold: float = MIN_INSERT_THRESHOLD,
) -> dict:
    """Run the full Graph Truth Engine pipeline.

    Flow per iteration:
    1. Detect broken chains (structural NOT EXISTS)
    2. For each candidate: API → fingerprint → confidence score → validated insert
    3. Re-run analytics
    4. Validate graph health
    5. Check convergence (triple-signal)

    Convergence requires ALL:
    - Unpaired sells <= 10
    - Transfers inserted == 0 for 2 consecutive iterations
    - Graph health score >= 0.95
    """
    from scripts.enrich.analytics_runner import run_analytics

    overall = {
        "iterations": 0,
        "total_processed": 0,
        "total_attempted": 0,
        "total_inserted": 0,
        "total_failed": 0,
        "unpaired_before": 0,
        "unpaired_after": 0,
        "graph_health_before": 1.0,
        "graph_health_after": 1.0,
        "converged": False,
        "convergence_reason": "",
        "confidence_distribution": {"high": 0, "medium": 0, "low": 0},
        "graph_validation": None,
    }

    logger.info("=" * 65)
    logger.info("GRAPH TRUTH ENGINE — RECONSTRUCTION PIPELINE")
    logger.info("=" * 65)
    logger.info("Batch: %d | Max iter: %d | Min fee: €%.0fK | Conf threshold: %.2f",
                 batch_size, max_iterations, min_fee / 1000, confidence_threshold)
    logger.info("Strategy: %s | Convergence: triple-signal", strategy)
    logger.info("")

    # Audit starting state
    before = await count_unpaired_sells(session)
    overall["unpaired_before"] = before["count"]

    try:
        health_before = await validate_transfer_graph(session)
        overall["graph_health_before"] = health_before.graph_health_score
        logger.info("Starting state: %d unpaired sells | Graph health: %.3f",
                     before["count"], health_before.graph_health_score)
    except Exception as e:
        logger.warning("Graph validation failed (non-fatal): %s", e)
        overall["graph_health_before"] = None

    prev_iter_inserted = None
    processed_ids: set[int] = set()  # players already processed with 0 inserts — skip future iterations

    for iteration in range(1, max_iterations + 1):
        logger.info("\n" + "─" * 65)
        logger.info("ITERATION %d/%d", iteration, max_iterations)
        logger.info("─" * 65)

        # Step 1: Detect
        if strategy == "silent":
            candidates = await detect_silent_origin_gaps(session, min_fee, batch_size)
        else:
            candidates = await detect_broken_chains(session, min_fee, batch_size, exclude_player_ids=processed_ids)

        if not candidates:
            logger.info("No more candidates — converged!")
            overall["converged"] = True
            overall["convergence_reason"] = "zero_candidates"
            break

        logger.info("Detected %d candidates", len(candidates))

        # Step 2: Reconstruct with fingerprinting + confidence
        recon_stats = await reconstruct_careers_batch_v2(
            session, client, candidates,
            dry_run=dry_run,
            confidence_threshold=confidence_threshold,
        )

        overall["total_processed"] += recon_stats["processed"]
        overall["total_attempted"] += recon_stats["transfers_attempted"]
        overall["total_inserted"] += recon_stats["transfers_inserted"]
        overall["total_failed"] += recon_stats["failed"]
        overall["iterations"] = iteration

        # Track players with 0 inserts so we skip them in future iterations
        for pid in recon_stats.get("zero_insert_ids", []):
            processed_ids.add(pid)

        # Aggregate confidence distribution
        cd = recon_stats.get("confidence_distribution", {"high": 0, "medium": 0, "low": 0})
        overall["confidence_distribution"]["high"] += cd["high"]
        overall["confidence_distribution"]["medium"] += cd["medium"]
        overall["confidence_distribution"]["low"] += cd["low"]

        if dry_run:
            continue

        # Step 3: Re-run analytics
        if recon_stats["transfers_inserted"] > 0:
            logger.info("\nRe-running analytics...")
            try:
                analytics_result = await run_analytics(session)
                logger.info("Analytics: %d pairs, %d clubs updated",
                             analytics_result.get("pairs_computed", 0),
                             analytics_result.get("clubs_updated", 0))
            except Exception as e:
                logger.error("Analytics failed: %s", e)

        # Step 4: Validate graph health
        try:
            health = await validate_transfer_graph(session)
            overall["graph_health_after"] = health.graph_health_score
            overall["graph_validation"] = health
            logger.info("Graph health: %.3f — timeline violations: %d, disconnected: %d",
                         health.graph_health_score,
                         len(health.timeline_violations),
                         len(health.disconnected_segments))
        except Exception as e:
            logger.warning("Graph validation failed: %s", e)

        # Step 5: Triple-signal convergence check
        remaining = await count_unpaired_sells(session)
        overall["unpaired_after"] = remaining["count"]
        fixed = before["count"] - remaining["count"]

        inserted_this_iter = recon_stats["transfers_inserted"]

        health_now = overall.get("graph_health_after", 0) or 0
        signal_1 = remaining["count"] <= 10
        signal_2 = inserted_this_iter == 0
        signal_3 = health_now >= 0.95

        logger.info(
            "Iteration %d: %d unpaired (fixed %d) | +%d inserts | health=%.3f",
            iteration, remaining["count"], fixed,
            inserted_this_iter, health_now,
        )
        logger.info("Signals: unpaired=%s, inserts=%s, health=%s",
                     "✓" if signal_1 else "✗",
                     "✓" if signal_2 else "✗",
                     "✓" if signal_3 else "✗")

        # Triple-signal: converge only when ALL 3 conditions are met
        if signal_1 and signal_2 and signal_3:
            # Check consecutive zeros for inserts (double-tap safety)
            if prev_iter_inserted is not None and inserted_this_iter == 0 and prev_iter_inserted == 0:
                logger.info("Converged! All 3 signals stable for 2 consecutive iterations")
                overall["converged"] = True
                overall["convergence_reason"] = "triple_signal_convergence"
                break
        elif signal_1 and signal_2:
            logger.info("Signals 1+2 OK, waiting for graph health >= 0.95 (current: %.3f)", health_now)

        prev_iter_inserted = inserted_this_iter

    # Final graph validation
    try:
        final_health = await validate_transfer_graph(session)
        overall["graph_health_after"] = final_health.graph_health_score
        overall["graph_validation"] = final_health
    except Exception:
        pass

    # Final report
    after = await count_unpaired_sells(session)
    overall["unpaired_after"] = after["count"]

    logger.info("\n" + "=" * 65)
    logger.info("RECONSTRUCTION PIPELINE COMPLETE")
    logger.info("=" * 65)
    logger.info("  Iterations:          %d/%d", overall["iterations"], max_iterations)
    logger.info("  Players processed:   %d", overall["total_processed"])
    logger.info("  Transfers attempted: %d", overall["total_attempted"])
    logger.info("  Transfers inserted:  %d", overall["total_inserted"])
    logger.info("  Failed:              %d", overall["total_failed"])
    logger.info("  Unpaired sells:      %d → %d", overall["unpaired_before"], overall["unpaired_after"])
    cd = overall["confidence_distribution"]
    logger.info("  Confidence:          H=%d M=%d L=%d", cd["high"], cd["medium"], cd["low"])
    logger.info("  Graph health:        %.3f → %.3f",
                 overall.get("graph_health_before", 0),
                 overall.get("graph_health_after", 0))
    logger.info("  Converged:           %s (%s)", overall["converged"], overall["convergence_reason"])
    logger.info("")

    return overall
