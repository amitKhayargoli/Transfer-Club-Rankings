#!/usr/bin/env python3
"""
Data enrichment script - backfills missing data from Transfermarkt.

Fetches player profiles, transfer histories, and market valuations
from the transfermarkt-api (felipeall/transfermarkt-api) and upserts
them into the existing database.

Usage:
    python scripts/enrich_data.py --leagues GB1,ES1,IT1,L1,FR1,PO1 --rate-limit 2.5
    python scripts/enrich_data.py --dry-run --batch-size 5
    python scripts/enrich_data.py --start-from 1000 --retries 5
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

# Ensure the project root is on sys.path so we can import api.* modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-25s | %(levelname)-5s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("enrich_data")

# ── Default leagues (top 5 + Liga Portugal) ──────────────────────────
DEFAULT_LEAGUES = ["GB1", "ES1", "IT1", "L1", "FR1", "PO1"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill missing Transfermarkt data from transfermarkt-api",
    )
    parser.add_argument(
        "--leagues",
        default=",".join(DEFAULT_LEAGUES),
        help="Comma-separated league IDs to enrich (default: GB1,ES1,IT1,L1,FR1,PO1)",
    )
    parser.add_argument(
        "--club-ids",
        default=None,
        help="Comma-separated club IDs to enrich (e.g. 31 for Liverpool). Overrides --leagues.",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=1.0,
        help="Minimum seconds between API calls (default: 1.0)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Max retries per failed request (default: 3)",
    )
    parser.add_argument(
        "--auto-analytics",
        action="store_true",
        default=True,
        help="Re-run analytics pipeline after enrichment (default: True)",
    )
    parser.add_argument(
        "--no-analytics",
        action="store_false",
        dest="auto_analytics",
        help="Skip analytics re-run after enrichment",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without making changes",
    )
    parser.add_argument(
        "--start-from",
        type=int,
        default=None,
        help="Resume enrichment from a specific player_id",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Process at most N players then stop (for testing)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip players who already have any transfers in the database",
    )
    parser.add_argument(
        "--graph-repair",
        action="store_true",
        help="Run graph repair to find orphan clubs (referenced in transfers but missing from clubs table) and fetch their profiles",
    )
    parser.add_argument(
        "--repair-min-transfers",
        type=int,
        default=3,
        help="Minimum transfer count for an orphan club to be repaired (default: 3)",
    )
    parser.add_argument(
        "--repair-batch-size",
        type=int,
        default=None,
        help="Max orphan clubs to repair in this run (default: all)",
    )
    parser.add_argument(
        "--include-reserves",
        action="store_true",
        help="Include reserve/youth teams in graph repair (excluded by default)",
    )
    parser.add_argument(
        "--reconstruct-careers",
        action="store_true",
        help="Run player career reconstruction: detect broken transfer chains and repair them",
    )
    parser.add_argument(
        "--recon-batch-size",
        type=int,
        default=50,
        help="Players to reconstruct per iteration (default: 50)",
    )
    parser.add_argument(
        "--recon-max-iterations",
        type=int,
        default=5,
        help="Max reconstruction loop iterations (default: 5)",
    )
    parser.add_argument(
        "--recon-min-fee",
        type=float,
        default=100_000,
        help="Minimum fee for unpaired sells to be candidates (default: €100K)",
    )
    parser.add_argument(
        "--recon-strategy",
        choices=["by_fee", "silent"],
        default="by_fee",
        help="Detection strategy: by_fee (structural unpaired sells), silent (missing/orphan origin clubs) (default: by_fee)",
    )
    parser.add_argument(
        "--enrich-profiles",
        action="store_true",
        help="Run profile-only enrichment: fills in missing image_url, citizenship, agent_name for players with complete transfers",
    )
    parser.add_argument(
        "--profile-fields",
        nargs="*",
        default=["image_url"],
        help="Profile fields to check for missing data (default: image_url)",
    )
    parser.add_argument(
        "--profile-batch-size",
        type=int,
        default=100,
        help="Players to enrich per profile run (default: 100)",
    )
    return parser.parse_args()


async def main():
    args = parse_args()
    league_ids = [lid.strip() for lid in args.leagues.split(",") if lid.strip()]
    club_ids = None
    if args.club_ids:
        club_ids = [int(cid.strip()) for cid in args.club_ids.split(",") if cid.strip()]

    logger.info("=" * 60)
    logger.info("Transfermarkt Data Enrichment Script")
    logger.info("=" * 60)
    if club_ids:
        logger.info("Club IDs: %s", club_ids)
    else:
        logger.info("Leagues: %s", ", ".join(league_ids))
    logger.info("Rate limit: %.1fs between calls", args.rate_limit)
    logger.info("Max retries: %d", args.retries)
    logger.info("Auto-analytics: %s", args.auto_analytics)
    logger.info("Dry run: %s", args.dry_run)
    if args.start_from:
        logger.info("Starting from player_id: %d", args.start_from)
    if args.batch_size:
        logger.info("Batch size limit: %d players", args.batch_size)
    if args.skip_existing:
        logger.info("Skip existing: yes (players with existing transfers will be skipped)")
    logger.info("")

    # ── Import project modules ──────────────────────────────────────────

    from api.database import async_session_factory
    from api.models import Player, Club, Transfer
    from sqlalchemy import select

    from scripts.enrich.transfermarkt_client import TransfermarktClient
    from scripts.enrich.player_enricher import (
        enrich_player_profile,
        enrich_player_transfers,
        enrich_player_valuations,
    )
    from scripts.enrich.club_enricher import get_players_by_league, get_players_by_clubs, repair_missing_clubs
    from scripts.enrich.reconstruction_runner import (
        run_reconstruction_pipeline, detect_broken_chains, detect_silent_origin_gaps,
        count_unpaired_sells,
    )
    from scripts.enrich.career_reconstructor import (
        detect_incomplete_profiles, enrich_profiles_batch,
    )
    from scripts.enrich.analytics_runner import run_analytics
    from scripts.enrich.consistency import run_consistency_checks

    # ── Initialize clients ──────────────────────────────────────────────

    client = TransfermarktClient(
        rate_limit=args.rate_limit,
        max_retries=args.retries,
    )

    # ── Stats tracking ──────────────────────────────────────────────────

    stats = {
        "players_processed": 0,
        "players_skipped": 0,
        "players_failed": 0,
        "profiles_updated": 0,
        "transfers_inserted": 0,
        "valuations_inserted": 0,
        "clubs_enriched": 0,
    }
    start_time = time.time()

    # ── Main enrichment loop ────────────────────────────────────────────

    async with async_session_factory() as session:
        # If --reconstruct-careers mode, run the career reconstruction engine
        if args.reconstruct_careers:
            logger.info("\n" + "=" * 60)
            logger.info("CAREER RECONSTRUCTION MODE")
            logger.info("=" * 60)

            # Dry-run: just report candidates without making changes
            if args.dry_run:
                logger.info("\nDetecting candidates for career reconstruction...")
                if args.recon_strategy == "silent":
                    candidates = await detect_silent_origin_gaps(
                        session, min_fee=args.recon_min_fee, max_count=1000,
                    )
                else:
                    candidates = await detect_broken_chains(
                        session, min_fee=args.recon_min_fee, max_count=1000,
                    )
                logger.info(
                    "Found %d players needing reconstruction (min fee: €%.0fK, strategy: %s)",
                    len(candidates), args.recon_min_fee / 1000, args.recon_strategy,
                )
                print(f"\n{'Player ID':>10} {'Name':<35} {'Unpaired Value':>20} {'Sells':>8}")
                print(f"{'-'*10} {'-'*35} {'-'*20} {'-'*8}")
                for pid, name, fee, count in candidates[:30]:
                    fee_str = f"€{fee/1_000_000:.1f}M" if fee >= 1_000_000 else f"€{fee:,.0f}"
                    print(f"{pid:>10} {str(name)[:35]:<35} {fee_str:>20} {count:>8}")
                if len(candidates) > 30:
                    print(f"  ... and {len(candidates) - 30} more")
                print(f"\nTotal: {len(candidates)} players with €{sum(f for _,_,f,_ in candidates)/1_000_000:.0f}M in unpaired sells")
                elapsed = time.time() - start_time
                print(f"\nElapsed time: {elapsed:.1f}s")
                return

            # Full reconstruction using Graph Truth Engine pipeline
            recon_stats = await run_reconstruction_pipeline(
                session=session,
                client=client,
                dry_run=False,
                batch_size=args.recon_batch_size,
                max_iterations=args.recon_max_iterations,
                min_fee=args.recon_min_fee,
                strategy=args.recon_strategy,
            )

            stats["players_processed"] = recon_stats["total_processed"]
            stats["transfers_inserted"] = recon_stats["total_inserted"]

            elapsed = time.time() - start_time
            cd = recon_stats.get("confidence_distribution", {})
            gv = recon_stats.get("graph_validation")

            print("\n" + "=" * 65)
            print("GRAPH TRUTH ENGINE — RECONSTRUCTION REPORT")
            print("=" * 65)
            print(f"  Iterations:          {recon_stats['iterations']}")
            print(f"  Players processed:   {recon_stats['total_processed']}")
            print(f"  Transfers inserted:  {recon_stats['total_inserted']}")
            print(f"  Players failed:      {recon_stats['total_failed']}")
            print(f"  Unpaired sells:      {recon_stats['unpaired_before']} → {recon_stats['unpaired_after']}")
            if recon_stats["unpaired_before"] > 0:
                reduction = (1 - recon_stats["unpaired_after"] / recon_stats["unpaired_before"]) * 100
                print(f"  Reduction:           {reduction:.1f}%")
            print(f"  Confidence:          H={cd.get('high',0)} M={cd.get('medium',0)} L={cd.get('low',0)}")
            if gv:
                print(f"  Graph health:        {gv.graph_health_score:.3f}")
            print(f"  Converged:           {recon_stats['converged']} ({recon_stats.get('convergence_reason','')})")
            print(f"  Elapsed time:        {elapsed:.1f}s")
            print("=" * 65)
            return

        # If --enrich-profiles mode, run lightweight profile-only enrichment
        if args.enrich_profiles:
            logger.info("\n" + "=" * 60)
            logger.info("PROFILE ENRICHMENT MODE")
            logger.info("=" * 60)
            logger.info(
                "Checking for missing profile fields: %s (batch size: %d)",
                ", ".join(args.profile_fields), args.profile_batch_size,
            )

            candidates = await detect_incomplete_profiles(
                session,
                fields=args.profile_fields,
                max_count=args.profile_batch_size,
            )

            logger.info("Found %d players with missing profile data", len(candidates))

            if args.dry_run:
                print(f"\n{'Player ID':>10} {'Name':<35} {'Missing Field':>20}")
                print(f"{'-'*10} {'-'*35} {'-'*20}")
                for pid, name, field in candidates[:30]:
                    print(f"{pid:>10} {str(name)[:35]:<35} {field:>20}")
                if len(candidates) > 30:
                    print(f"  ... and {len(candidates) - 30} more")
                print(f"\nTotal: {len(candidates)} players need profile enrichment")
                elapsed = time.time() - start_time
                print(f"\nElapsed time: {elapsed:.1f}s")
                return

            profile_stats = await enrich_profiles_batch(
                session, client, candidates, dry_run=False,
            )

            stats["players_processed"] = profile_stats["processed"]
            stats["profiles_updated"] = profile_stats["updated"]

            elapsed = time.time() - start_time
            print("\n" + "=" * 60)
            print("PROFILE ENRICHMENT SUMMARY")
            print("=" * 60)
            print(f"  Candidates found:   {profile_stats['total_candidates']}")
            print(f"  Profiles enriched:  {profile_stats['updated']}")
            print(f"  Failed:             {profile_stats['failed']}")
            print(f"  Elapsed time:       {elapsed:.1f}s")
            print("=" * 60)
            return

        # If --graph-repair mode, skip player enrichment and just fix the graph
        if args.graph_repair:
            logger.info("\n" + "=" * 60)
            logger.info("GRAPH REPAIR MODE")
            logger.info("=" * 60)
            logger.info(
                "Finding orphan clubs (min %d transfers, include_reserves=%s)...",
                args.repair_min_transfers, args.include_reserves,
            )
            repair_stats = await repair_missing_clubs(
                session=session,
                client=client,
                dry_run=args.dry_run,
                batch_size=args.repair_batch_size,
                min_transfers=args.repair_min_transfers,
                include_reserves=args.include_reserves,
            )
            stats["clubs_enriched"] = repair_stats["succeeded"]

            # Skip to summary — no player enrichment, analytics, or consistency checks
            # that would only be relevant for player data changes
            elapsed = time.time() - start_time
            print("\n" + "=" * 60)
            print("GRAPH REPAIR SUMMARY")
            print("=" * 60)
            if args.dry_run:
                print("  DRY RUN - no changes were made")
            print(f"  Orphan clubs found: {repair_stats['found']}")
            print(f"  Clubs enriched:     {stats['clubs_enriched']}")
            print(f"  Failed:             {repair_stats['failed']}")
            print(f"  Elapsed time:       {elapsed:.1f}s")
            print("=" * 60)
            return

        # Step 1: Get all players (by club IDs or league)
        if club_ids:
            players = await get_players_by_clubs(session, club_ids)
        else:
            players = await get_players_by_league(session, league_ids)
        logger.info("Found %d players to process", len(players))

        if not players:
            logger.warning("No players found in the specified leagues. Exiting.")
            return

        # Players are already sorted by market value descending from get_players_*

        # Apply start_from filter
        if args.start_from:
            players = [p for p in players if p[0] >= args.start_from]
            logger.info(
                "After start_from=%d filter: %d players remaining",
                args.start_from, len(players),
            )

        # Pre-compute set of players that already have transfers (for --skip-existing)
        players_with_transfers: set[int] = set()
        if args.skip_existing:
            existing_result = await session.execute(
                select(Transfer.player_id).distinct()
            )
            players_with_transfers = {row[0] for row in existing_result}
            # Filter out players with existing transfers from the processing list
            total_before = len(players)
            players = [p for p in players if p[0] not in players_with_transfers]
            skipped_count = total_before - len(players)
            stats["players_skipped"] += skipped_count
            logger.info(
                "Skip existing: %d players already have transfers, %d remaining to process",
                skipped_count, len(players),
            )

        # Apply batch_size limit
        if args.batch_size:
            players = players[:args.batch_size]
            logger.info("Batch limited to first %d players", len(players))

        # Step 2: Process each player
        for idx, (player_id, player_name, club_id, market_value) in enumerate(players, 1):
            if args.dry_run:
                logger.info("  [DRY RUN] Would fetch and update player %d", player_id)
                stats["players_processed"] += 1
                continue

            player_start = time.time()
            p_status = "failed"
            p_elapsed = 0
            p_profile = "-"
            p_transfers = 0
            p_valuations = 0

            try:
                # 2a. Fetch player profile
                profile = client.get_player_profile(str(player_id))
                if not profile:
                    logger.warning("  No profile data for player %d, skipping", player_id)
                    stats["players_skipped"] += 1
                    continue

                # 2b. Fetch transfers
                transfers_data = client.get_player_transfers(str(player_id))

                # 2c. Fetch market value history
                mv_data = client.get_player_market_value(str(player_id))

                # 2d. Update database within a savepoint
                # begin_nested() auto-rolls back the savepoint on exception
                async with session.begin_nested():
                    profile_updated = await enrich_player_profile(
                        session, player_id, profile,
                    )
                    if profile_updated:
                        stats["profiles_updated"] += 1

                    if mv_data:
                        val_count = await enrich_player_valuations(
                            session, player_id, mv_data,
                        )
                        stats["valuations_inserted"] += val_count

                    if transfers_data:
                        t_count = await enrich_player_transfers(
                            session, player_id, transfers_data,
                        )
                        stats["transfers_inserted"] += t_count

                    await session.flush()

                stats["players_processed"] += 1
                p_status = "ok"
                p_elapsed = int(time.time() - player_start)
                p_profile = "✓" if profile_updated else "-"
                p_transfers = len(transfers_data.get("transfers", [])) if transfers_data else 0
                p_valuations = len(mv_data.get("marketValueHistory", [])) if mv_data else 0

            except Exception as e:
                logger.error("  Failed to enrich player %d: %s", player_id, e, exc_info=True)
                stats["players_failed"] += 1
                p_elapsed = int(time.time() - player_start)
                p_status = "failed"

            # ── Big progress block (every player) ──────────────────────────
            total_elapsed = time.time() - start_time
            rate_per_sec = idx / total_elapsed if total_elapsed > 0 else 0
            remaining = len(players) - idx
            eta_seconds = remaining / rate_per_sec if rate_per_sec > 0 else 0
            if eta_seconds > 99 * 3600:
                eta_str = "99h+"
            elif eta_seconds >= 3600:
                eta_str = f"{int(eta_seconds) // 3600}h {int(eta_seconds) % 3600 // 60}m"
            elif eta_seconds >= 60:
                eta_str = f"{int(eta_seconds) // 60}m {int(eta_seconds) % 60}s"
            else:
                eta_str = f"{int(eta_seconds)}s"

            status_icon = "✓" if p_status == "ok" else "✗"
            print()
            print(f"{'█' * 60}")
            print(f"  [{idx}/{len(players)}] {player_name} (ID {player_id})  {status_icon}  {p_elapsed}s")
            if p_status == "ok":
                print(f"  Profile: {p_profile}  |  Transfers: {p_transfers}  |  "
                      f"Valuations: {p_valuations}")
            else:
                print(f"  FAILED - see error above")
            print(f"  {'─' * 56}")
            print(f"  ETA: {eta_str}  |  Rate: {rate_per_sec * 60:.1f}/min")
            print(f"  Total: Profiles: {stats['profiles_updated']}  |  "
                  f"Transfers: {stats['transfers_inserted']}  |  "
                  f"Valuations: {stats['valuations_inserted']}  |  "
                  f"Failed: {stats['players_failed']}")
            print(f"{'█' * 60}")

        # Step 3: Re-run analytics if requested
        if args.auto_analytics and not args.dry_run and stats["players_processed"] > 0:
            logger.info("\n" + "=" * 60)
            logger.info("Re-running analytics pipeline...")
            logger.info("=" * 60)
            try:
                analytics_result = await run_analytics(session)
                stats["pairs_computed"] = analytics_result["pairs_computed"]
                stats["clubs_updated"] = analytics_result["clubs_updated"]
                logger.info(
                    "Analytics complete: %d pairs, %d clubs updated",
                    analytics_result["pairs_computed"],
                    analytics_result["clubs_updated"],
                )
            except Exception as e:
                logger.error("Analytics re-run failed: %s", e, exc_info=True)
        elif args.dry_run:
            logger.info("\n  [DRY RUN] Would re-run analytics pipeline")

        # Step 4: Run consistency checks
        logger.info("\n" + "=" * 60)
        logger.info("Running data consistency checks...")
        logger.info("=" * 60)
        if args.dry_run:
            logger.info("  [DRY RUN] Would run consistency checks")
        else:
            try:
                report = await run_consistency_checks(session)
                print("\n" + report.summary())
                if not report.passed:
                    logger.error(
                        "Consistency checks FAILED with %d errors. Review the report above.",
                        len(report.errors),
                    )
            except Exception as e:
                logger.error("Consistency checks failed: %s", e, exc_info=True)

        # Step 5: Print final summary
        elapsed = time.time() - start_time
        print("\n" + "=" * 60)
        print("ENRICHMENT SUMMARY")
        print("=" * 60)
        if args.dry_run:
            print(f"  DRY RUN - no changes were made")
        print(f"  Players processed:  {stats['players_processed']}")
        print(f"  Players failed:     {stats['players_failed']}")
        print(f"  Players skipped:    {stats['players_skipped']}")
        print(f"  Profiles updated:   {stats['profiles_updated']}")
        print(f"  Transfers inserted: {stats['transfers_inserted']}")
        print(f"  Valuations inserted:{stats['valuations_inserted']}")
        if "pairs_computed" in stats:
            print(f"  Pairs computed:     {stats['pairs_computed']}")
        if "clubs_updated" in stats:
            print(f"  Clubs updated:      {stats['clubs_updated']}")
        print(f"  Elapsed time:       {elapsed:.1f}s")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
