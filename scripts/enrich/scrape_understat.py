#!/usr/bin/env python3
"""
Understat xG/xA Scraper — Hidden Gem Model, Part 2 (Data Collection Spec).

Fetches expected goals (xG), expected assists (xA), shots, key passes,
non-penalty xG, xG chain, and xG buildup for the top 5 European leagues
from 2014/15 to present via the Understat API.

Pipeline:
  1. For each league ± season: fetch all player stats from Understat
  2. Fuzzy-match Understat player names to our players table (rapidfuzz)
  3. Store results in player_xg table
  4. Report coverage stats

Usage:
    python scripts/enrich/scrape_understat.py
    python scripts/enrich/scrape_understat.py --leagues EPL,Bundesliga --seasons 2023
    python scripts/enrich/scrape_understat.py --dry-run
"""

import argparse
import asyncio
import logging
import sqlite3
import sys
import time
from pathlib import Path

import unicodedata

import aiohttp
from rapidfuzz import fuzz
from understat import Understat

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("understat_scraper")

# ── Constants ──────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "transfer_roi.db"

UNDERSTAT_LEAGUES = {
    "EPL": "GB1",         # England
    "La_liga": "ES1",     # Spain
    "Bundesliga": "L1",   # Germany
    "Serie_A": "IT1",     # Italy
    "Ligue_1": "FR1",     # France
}

SEASONS = list(range(2014, 2026))  # 2014/15 through 2025/26

# Minimum fuzzy match score (0-100) to consider a player matched
MATCH_THRESHOLD = 85

# Rate limiting — Understat is generally fast, but be polite
REQUEST_DELAY = 1.0


# ── Database Setup ─────────────────────────────────────────────────────────

def init_db():
    """Create the player_xg table if it doesn't exist."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS player_xg (
            player_id       INTEGER NOT NULL,
            season          TEXT NOT NULL,
            competition_id  TEXT NOT NULL,
            xG              REAL,
            xA              REAL,
            npxG            REAL,
            shots           INTEGER,
            key_passes      INTEGER,
            games           INTEGER,
            minutes         INTEGER,
            goals           INTEGER,
            assists         INTEGER,
            xGChain         REAL,
            xGBuildup       REAL,
            understat_id    INTEGER,
            match_score     INTEGER,
            has_understat_match INTEGER DEFAULT 1,
            scraped_at      TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (player_id, season, competition_id)
        )
    """)
    conn.commit()
    return conn


def load_our_players(conn):
    """Load all players from our DB for fuzzy matching.

    Returns:
        list of dicts with player_id, name, current_club_name, position
    """
    rows = conn.execute("""
        SELECT player_id, name, current_club_name, position
        FROM players
        WHERE name IS NOT NULL
    """).fetchall()

    players = []
    for r in rows:
        players.append({
            "player_id": r[0],
            "name": str(r[1]).strip().lower(),
            "name_raw": r[1],
            "club": str(r[2]).strip().lower() if r[2] else "",
            "position": r[3],
        })
    return players


# ── Fuzzy Matching ─────────────────────────────────────────────────────────

def _normalize(s: str) -> str:
    """Remove accents/diacritics for better fuzzy matching."""
    nfkd = unicodedata.normalize("NFKD", s)
    return nfkd.encode("ascii", "ignore").decode("ascii")


def match_player(
    understat_name: str, understat_team: str,
    our_players: list[dict],
    match_threshold: int = 85,
) -> tuple[int | None, int]:
    """Fuzzy-match an Understat player to our players table.

    Uses token_sort_ratio which is robust to:
      - "Erling Haaland" vs "Haaland, Erling"
      - "Christopher Nkunku" vs "Nkunku Christopher"
      - name prefixes/suffixes

    Also checks team name as a secondary signal if name match is borderline.

    Returns:
        (player_id, match_score) or (None, best_score)
    """
    uname = _normalize(understat_name.strip().lower())
    uteam = _normalize(understat_team.strip().lower()) if understat_team else ""

    best_id = None
    best_score = 0

    for p in our_players:
        # Try token_sort_ratio first — handles name ordering differences
        pname = _normalize(p["name"])
        score = fuzz.token_sort_ratio(uname, pname)

        # If score is borderline, check team match as tiebreaker
        if 70 <= score < match_threshold and uteam and p["club"]:
            pclub = _normalize(p["club"])
            team_score = fuzz.token_sort_ratio(uteam, pclub)
            if team_score >= 80:
                score = max(score, min(score + 15, 95))

        if score > best_score:
            best_score = score
            if score >= match_threshold:
                best_id = p["player_id"]

    return best_id, best_score


# ── Scraping ───────────────────────────────────────────────────────────────

async def scrape_league_season(
    understat: Understat,
    league: str,
    season: int,
    our_players: list[dict],
    conn: sqlite3.Connection,
    dry_run: bool = False,
) -> dict:
    """Scrape one league-season and store xG data.

    Returns dict with stats for this batch.
    """
    stats = {
        "league": league,
        "season": season,
        "players_found": 0,
        "players_matched": 0,
        "players_stored": 0,
        "players_unmatched": 0,
        "players_minutes_short": 0,
    }

    try:
        logger.info("  Fetching %s %s/%s...", league, season, season + 1)
        raw_players = await understat.get_league_players(league, season)
        stats["players_found"] = len(raw_players)

        if not raw_players:
            logger.info("  No players returned for %s %s", league, season)
            return stats

        competition_id = UNDERSTAT_LEAGUES.get(league, league)
        rows_to_insert = []

        for up in raw_players:
            player_id, match_score = match_player(
                up["player_name"], up.get("team_title", ""), our_players
            )

            if player_id is None:
                stats["players_unmatched"] += 1
                continue

            minutes = int(float(up.get("time", 0)))

            # Only store if they played meaningful minutes
            if minutes < 90:
                stats["players_minutes_short"] += 1
                continue

            stats["players_matched"] += 1

            games = int(float(up.get("games", 0)))

            rows_to_insert.append((
                player_id,
                f"{season}/{season + 1}",
                competition_id,
                float(up.get("xG", 0)),
                float(up.get("xA", 0)),
                float(up.get("npxG", 0)),
                int(float(up.get("shots", 0))),
                int(float(up.get("key_passes", 0))),
                games,
                minutes,
                int(float(up.get("goals", 0))),
                int(float(up.get("assists", 0))),
                float(up.get("xGChain", 0)),
                float(up.get("xGBuildup", 0)),
                int(up.get("id", 0)),
                match_score,
            ))

        if rows_to_insert and not dry_run:
            conn.executemany("""
                INSERT OR REPLACE INTO player_xg
                    (player_id, season, competition_id,
                     xG, xA, npxG, shots, key_passes,
                     games, minutes, goals, assists,
                     xGChain, xGBuildup,
                     understat_id, match_score)
                VALUES (?,?,?, ?,?,?,?,?,
                        ?,?,?,?,
                        ?,?,
                        ?,?)
            """, rows_to_insert)
            conn.commit()

        stats["players_stored"] = len(rows_to_insert)
        logger.info(
            "  %s %s: %d found → %d matched (≥90min) → %d stored | unmatched=%d short_min=%d",
            league, season,
            stats["players_found"], stats["players_matched"], stats["players_stored"],
            stats["players_unmatched"], stats["players_minutes_short"],
        )

    except Exception as e:
        logger.error("  Error scraping %s %s: %s", league, season, e)

    return stats


async def run(leagues: list[str], seasons: list[int], dry_run: bool = False, match_threshold: int = MATCH_THRESHOLD, resume: bool = False, reload: bool = False) -> dict:
    """Run the full Understat scraper.

    Args:
        resume: Skip league-seasons that already have data in player_xg.
        reload: Clear existing player_xg data for these leagues first.

    Returns aggregate stats dict.
    """
    global MATCH_THRESHOLD
    MATCH_THRESHOLD = match_threshold
    overall = {
        "leagues_scraped": 0,
        "seasons_scraped": 0,
        "players_found": 0,
        "players_matched": 0,
        "players_stored": 0,
        "players_unmatched": 0,
        "seasons_skipped": 0,
        "elapsed_seconds": 0,
        "leagues": {},
    }

    start_time = time.time()

    logger.info("=" * 60)
    logger.info("UNDERSTAT xG/xA SCRAPER")
    logger.info("=" * 60)
    logger.info("Leagues: %s", ", ".join(leagues))
    logger.info("Seasons: %d-%d (%d seasons)", seasons[0], seasons[-1], len(seasons))
    logger.info("Match threshold: %d", MATCH_THRESHOLD)
    if resume:
        logger.info("Mode: resume — skipping seasons already in DB")
    if reload:
        logger.info("Mode: reload — clearing existing data first")
    if dry_run:
        logger.info("DRY RUN — no data will be written\n")
    else:
        logger.info("")

    # Initialize DB
    conn = init_db()
    our_players = load_our_players(conn)
    logger.info("Loaded %d players from DB for fuzzy matching\n", len(our_players))

    # Build set of already-seen (competition_id, season) if in resume mode
    seen_seasons: set[tuple[str, str]] = set()
    if resume:
        rows = conn.execute(
            "SELECT DISTINCT competition_id, season FROM player_xg"
        ).fetchall()
        seen_seasons = {(str(r[0]), str(r[1])) for r in rows}
        logger.info("Found %d existing league-seasons in DB — will skip them\n", len(seen_seasons))

    # If reload, clear data for these leagues
    if reload:
        for league in leagues:
            comp_id = UNDERSTAT_LEAGUES.get(league, league)
            deleted = conn.execute(
                "DELETE FROM player_xg WHERE competition_id = ?", (comp_id,)
            ).rowcount
            logger.info("Cleared %d existing rows for %s (%s)", deleted, league, comp_id)
        conn.commit()
        seen_seasons.clear()  # All data is gone anyway

    async with aiohttp.ClientSession() as session:
        understat = Understat(session)

        for league_idx, league in enumerate(leagues, 1):
            league_stats = {
                "players_found": 0,
                "players_matched": 0,
                "players_stored": 0,
                "players_unmatched": 0,
            }

            comp_id = UNDERSTAT_LEAGUES.get(league, league)
            logger.info("[%d/%d] %s — %s", league_idx, len(leagues), league, comp_id)

            for season_idx, season in enumerate(seasons, 1):
                season_key = f"{season}/{season + 1}"

                # Skip if this league-season already has data (resume mode)
                if resume and (comp_id, season_key) in seen_seasons:
                    overall["seasons_skipped"] += 1
                    continue

                result = await scrape_league_season(
                    understat, league, season, our_players, conn, dry_run
                )

                league_stats["players_found"] += result["players_found"]
                league_stats["players_matched"] += result["players_matched"]
                league_stats["players_stored"] += result["players_stored"]
                league_stats["players_unmatched"] += result["players_unmatched"]

                await asyncio.sleep(REQUEST_DELAY)

            overall["leagues"][league] = league_stats
            logger.info(
                "  Total for %s: %d found → %d matched → %d stored\n",
                league,
                league_stats["players_found"],
                league_stats["players_matched"],
                league_stats["players_stored"],
            )

    # Aggregate
    for ls in overall["leagues"].values():
        overall["players_found"] += ls["players_found"]
        overall["players_matched"] += ls["players_matched"]
        overall["players_stored"] += ls["players_stored"]
        overall["players_unmatched"] += ls["players_unmatched"]

    overall["elapsed_seconds"] = time.time() - start_time
    overall["leagues_scraped"] = len(leagues)
    seasons_done = len(leagues) * len(seasons) - overall["seasons_skipped"]
    overall["seasons_scraped"] = max(seasons_done, 0)

    # Close DB
    conn.close()

    return overall


def print_report(stats: dict):
    """Print a formatted report of the scrape results."""
    print("\n" + "=" * 60)
    print("UNDERSTAT SCRAPE REPORT")
    print("=" * 60)
    print(f"  Leagues scraped:   {stats['leagues_scraped']}")
    print(f"  Seasons scraped:   {stats['seasons_scraped']}")
    print(f"  Seasons skipped:   {stats.get('seasons_skipped', 0)}")
    print(f"  Players found:     {stats['players_found']:,}")
    print(f"  Players matched:   {stats['players_matched']:,}")
    print(f"  Players stored:    {stats['players_stored']:,}")
    print(f"  Players unmatched: {stats['players_unmatched']:,}")
    if stats["players_found"] > 0:
        match_rate = stats["players_matched"] / stats["players_found"] * 100
        print(f"  Match rate:        {match_rate:.1f}%")
    print(f"  Elapsed:           {stats['elapsed_seconds']:.1f}s")
    print()

    for league, ls in stats.get("leagues", {}).items():
        print(f"  {league:15s}  {ls['players_found']:>5d} found → {ls['players_matched']:>5d} matched → {ls['players_stored']:>5d} stored")

    print("=" * 60)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scrape xG/xA data from Understat for top 5 leagues"
    )
    parser.add_argument(
        "--leagues",
        default=",".join(UNDERSTAT_LEAGUES.keys()),
        help="Comma-separated leagues (default: all 5)",
    )
    parser.add_argument(
        "--seasons",
        default=None,
        help="Comma-separated seasons to scrape (default: 2014-2025)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write to database, just report what would be done",
    )
    parser.add_argument(
        "--match-threshold",
        type=int,
        default=MATCH_THRESHOLD,
        help=f"Fuzzy match threshold (default: {MATCH_THRESHOLD})",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Clear existing player_xg data for these leagues before loading (default: append)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip league-seasons that already have data in the database (incremental)",
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    leagues = [l.strip() for l in args.leagues.split(",") if l.strip()]
    invalid = [l for l in leagues if l not in UNDERSTAT_LEAGUES]
    if invalid:
        logger.error("Invalid leagues: %s. Valid: %s", invalid, list(UNDERSTAT_LEAGUES.keys()))
        sys.exit(1)

    if args.seasons:
        seasons = [int(s.strip()) for s in args.seasons.split(",") if s.strip()]
    else:
        seasons = SEASONS

    stats = await run(leagues, seasons, dry_run=args.dry_run, match_threshold=args.match_threshold,
                      resume=args.resume, reload=args.reload)
    print_report(stats)


if __name__ == "__main__":
    asyncio.run(main())
