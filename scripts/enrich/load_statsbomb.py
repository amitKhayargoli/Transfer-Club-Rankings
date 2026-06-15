#!/usr/bin/env python3
"""
StatsBomb Open Data Loader — Hidden Gem Model, Part 3 (Data Collection Spec).

Extracts shot events with xG (expected goals) from StatsBomb's open data
for relevant competitions (Champions League, World Cup, Euros, Copa America,
and top 5 leagues) and matches them to our players table.

Pipeline:
  1. Read competitions.json from the zip
  2. For each relevant competition+season: read matches, then events
  3. Extract Shot events with statsbomb_xg
  4. Fuzzy-match players by name + team to our players table (cached per player)
  5. Store in statsbomb_shots table

Usage:
    python scripts/enrich/load_statsbomb.py
    python scripts/enrich/load_statsbomb.py --dry-run
    python scripts/enrich/load_statsbomb.py --priority high
    python scripts/enrich/load_statsbomb.py --competitions 16,55,43
"""

import argparse
import json
import logging
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path
from zipfile import ZipFile

from rapidfuzz import fuzz

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("statsbomb_loader")

# ── Paths ──────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ZIP_PATH = PROJECT_ROOT / "data" / "open-data-master.zip"
DB_PATH = PROJECT_ROOT / "data" / "transfer_roi.db"

# ── Relevant Competitions for Hidden Gem Model ─────────────────────────────

PRIORITY_HIGH = {
    16: "Champions League",
    55: "UEFA Euro",
    43: "FIFA World Cup",
    223: "Copa America",
}

PRIORITY_MEDIUM = {
    2: "Premier League",
    11: "La Liga",
    9: "1. Bundesliga",
    7: "Ligue 1",
    12: "Serie A",
    35: "UEFA Europa League",
}

PRIORITY_LOW = {
    81: "Liga Profesional",
}

ALL_COMPETITIONS = {}
ALL_COMPETITIONS.update(PRIORITY_HIGH)
ALL_COMPETITIONS.update(PRIORITY_MEDIUM)
ALL_COMPETITIONS.update(PRIORITY_LOW)

MATCH_THRESHOLD = 85


# ── Helpers ────────────────────────────────────────────────────────────────

def _normalize(s: str) -> str:
    """Remove accents/diacritics for better fuzzy matching."""
    nfkd = unicodedata.normalize("NFKD", s)
    return nfkd.encode("ascii", "ignore").decode("ascii")


def init_db(conn: sqlite3.Connection):
    """Create the statsbomb_shots table."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS statsbomb_shots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id       INTEGER,
            sb_player_id    INTEGER,
            sb_player_name  TEXT,
            match_id        INTEGER,
            competition_id  INTEGER,
            competition_name TEXT,
            season_id       INTEGER,
            season_name     TEXT,
            match_date      TEXT,
            team_name       TEXT,
            opponent_name   TEXT,
            minute          INTEGER,
            second          INTEGER,
            statsbomb_xg    REAL,
            shot_outcome    TEXT,
            shot_type       TEXT,
            body_part       TEXT,
            technique       TEXT,
            location_x      REAL,
            location_y      REAL,
            end_location_x  REAL,
            end_location_y  REAL,
            match_score     INTEGER,
            scraped_at      TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sb_player_id
        ON statsbomb_shots (player_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sb_match
        ON statsbomb_shots (competition_id, season_id)
    """)
    conn.commit()


def load_our_players(conn: sqlite3.Connection) -> list[dict]:
    """Load all players from our DB for fuzzy matching."""
    rows = conn.execute("""
        SELECT player_id, name, current_club_name
        FROM players
        WHERE name IS NOT NULL
    """).fetchall()

    players = []
    for r in rows:
        players.append({
            "player_id": r[0],
            "name": _normalize(str(r[1]).strip().lower()),
            "name_raw": str(r[1]),
            "club": _normalize(str(r[2]).strip().lower()) if r[2] else "",
        })
    return players


class PlayerMatcher:
    """Caches fuzzy-match results by (player_name, team_name) for efficiency."""

    def __init__(self, our_players: list[dict], threshold: int = MATCH_THRESHOLD):
        self.our_players = our_players
        self.threshold = threshold
        self.cache: dict[tuple[str, str], tuple[int | None, int]] = {}

    def match(self, sb_name: str, sb_team: str) -> tuple[int | None, int]:
        key = (_normalize(sb_name.strip().lower()), _normalize(sb_team.strip().lower()))
        if key in self.cache:
            return self.cache[key]

        result = self._do_match(key[0], key[1])
        self.cache[key] = result
        return result

    def _do_match(self, uname: str, uteam: str) -> tuple[int | None, int]:
        best_id = None
        best_score = 0

        for p in self.our_players:
            score = fuzz.token_sort_ratio(uname, p["name"])

            if 70 <= score < self.threshold and uteam and p["club"]:
                team_score = fuzz.token_sort_ratio(uteam, p["club"])
                if team_score >= 80:
                    score = max(score, min(score + 15, 95))

            if score > best_score:
                best_score = score
                if score >= self.threshold:
                    best_id = p["player_id"]

        return best_id, best_score


# ── Data Extraction ────────────────────────────────────────────────────────

def extract_shot_data(
    match_info: dict,
    events: list[dict],
    matcher: PlayerMatcher,
    conn: sqlite3.Connection,
    dry_run: bool = False,
) -> dict:
    """Extract shot events from a match and store in DB.

    Returns stats dict.
    """
    stats = {"shots_total": 0, "shots_matched": 0, "shots_stored": 0}

    match_id = match_info["match_id"]
    match_date = match_info.get("match_date", "")
    home_team = match_info.get("home_team", {}).get("home_team_name", "")
    away_team = match_info.get("away_team", {}).get("away_team_name", "")

    # Competition context (enriched by process_match)
    comp_id = match_info.get("competition_id")
    comp_name = match_info.get("competition_name")
    season_id = match_info.get("season_id")
    season_name = match_info.get("season_name")

    for event in events:
        if event.get("type", {}).get("name") != "Shot":
            continue

        stats["shots_total"] += 1
        player = event.get("player", {})
        sb_player_id = player.get("id")
        sb_player_name = player.get("name", "")
        team_name = event.get("team", {}).get("name", "")
        opponent = away_team if team_name == home_team else home_team

        player_id, match_score = matcher.match(sb_player_name, team_name)
        if player_id is None:
            continue

        stats["shots_matched"] += 1

        shot = event.get("shot", {})
        location = event.get("location", [None, None])
        end_location = shot.get("end_location", [None, None, None])

        if dry_run:
            stats["shots_stored"] += 1
            continue

        conn.execute("""
            INSERT INTO statsbomb_shots
                (player_id, sb_player_id, sb_player_name,
                 match_id, competition_id, competition_name,
                 season_id, season_name,
                 match_date,
                 team_name, opponent_name,
                 minute, second,
                 statsbomb_xg, shot_outcome, shot_type,
                 body_part, technique,
                 location_x, location_y,
                 end_location_x, end_location_y,
                 match_score)
            VALUES (?,?,?,
                    ?,?,?,
                    ?,?,
                    ?,
                    ?,?,
                    ?,?,
                    ?,?,?,
                    ?,?,
                    ?,?,
                    ?,?,
                    ?)
        """, (
            player_id,
            sb_player_id,
            sb_player_name,
            match_id,
            comp_id,
            comp_name,
            season_id,
            season_name,
            match_date,
            team_name,
            opponent,
            event.get("minute", 0),
            event.get("second", 0),
            shot.get("statsbomb_xg"),
            shot.get("outcome", {}).get("name"),
            shot.get("type", {}).get("name"),
            shot.get("body_part", {}).get("name"),
            shot.get("technique", {}).get("name"),
            location[0],
            location[1],
            end_location[0],
            end_location[1],
            match_score,
        ))
        stats["shots_stored"] += 1

    # Commit after each match
    if not dry_run and stats["shots_stored"] > 0:
        conn.commit()

    return stats


def process_match(
    zf: ZipFile,
    match_info: dict,
    comp_name: str,
    season_name: str,
    comp_id: int,
    season_id: int,
    matcher: PlayerMatcher,
    conn: sqlite3.Connection,
    dry_run: bool = False,
) -> dict:
    """Process a single match: read events, extract shots."""
    match_id = match_info["match_id"]
    events_path = f"open-data-master/data/events/{match_id}.json"

    if events_path not in zf.namelist():
        return {"shots_total": 0, "shots_matched": 0, "shots_stored": 0}

    try:
        events = json.loads(zf.read(events_path))
    except Exception as e:
        logger.warning("  Error reading events for match %d: %s", match_id, e)
        return {"shots_total": 0, "shots_matched": 0, "shots_stored": 0}

    # Enrich match_info with competition/season context
    match_info["competition_name"] = comp_name
    match_info["season_name"] = season_name
    match_info["competition_id"] = comp_id
    match_info["season_id"] = season_id

    return extract_shot_data(match_info, events, matcher, conn, dry_run)


def process_competition_season(
    zf: ZipFile,
    comp_id: int,
    comp_name: str,
    season_entry: dict,
    matcher: PlayerMatcher,
    conn: sqlite3.Connection,
    dry_run: bool = False,
) -> dict:
    """Process all matches in a competition+season."""
    season_id = season_entry["season_id"]
    season_name = season_entry["season_name"]

    matches_path = f"open-data-master/data/matches/{comp_id}/{season_id}.json"

    if matches_path not in zf.namelist():
        logger.info("  No matches file for %s %s", comp_name, season_name)
        return {"matches": 0, "shots_total": 0, "shots_matched": 0, "shots_stored": 0}

    try:
        matches = json.loads(zf.read(matches_path))
    except Exception as e:
        logger.warning("  Error reading matches for %s %s: %s", comp_name, season_name, e)
        return {"matches": 0, "shots_total": 0, "shots_matched": 0, "shots_stored": 0}

    stats = {"matches": len(matches), "shots_total": 0, "shots_matched": 0, "shots_stored": 0}

    for match_info in matches:
        match_stats = process_match(
            zf, match_info, comp_name, season_name,
            comp_id, season_id,
            matcher, conn, dry_run,
        )
        stats["shots_total"] += match_stats["shots_total"]
        stats["shots_matched"] += match_stats["shots_matched"]
        stats["shots_stored"] += match_stats["shots_stored"]

    logger.info(
        "  %s %s: %d matches, %d shots total, %d matched, %d stored",
        comp_name, season_name,
        stats["matches"], stats["shots_total"],
        stats["shots_matched"], stats["shots_stored"],
    )

    return stats


# ── Main Runner ────────────────────────────────────────────────────────────

def run(competitions: dict[int, str], dry_run: bool = False, reload: bool = False) -> dict:
    """Run the full StatsBomb loader. Returns aggregate stats dict.

    Args:
        reload: If True, clear existing statsbomb_shots data before loading.
                If False (default), append to existing data.
    """
    overall = {
        "competitions_processed": 0,
        "seasons_processed": 0,
        "matches_processed": 0,
        "shots_total": 0,
        "shots_matched": 0,
        "shots_stored": 0,
        "elapsed_seconds": 0,
        "details": {},
    }

    start_time = time.time()

    logger.info("=" * 60)
    logger.info("STATSBOMB OPEN DATA LOADER")
    logger.info("=" * 60)
    comp_list = ", ".join(f"{cid} ({name})" for cid, name in competitions.items())
    logger.info("Competitions: %s", comp_list)
    logger.info("Match threshold: %d", MATCH_THRESHOLD)
    if dry_run:
        logger.info("DRY RUN — no data written\n")
    else:
        logger.info("")

    if not ZIP_PATH.exists():
        logger.error("StatsBomb zip not found at %s", ZIP_PATH)
        return overall

    conn = sqlite3.connect(str(DB_PATH))
    init_db(conn)
    # Only delete data for competitions being loaded (not all data)
    comp_ids = list(competitions.keys())
    placeholders = ",".join("?" * len(comp_ids))
    deleted = conn.execute(f"DELETE FROM statsbomb_shots WHERE competition_id IN ({placeholders})", comp_ids).rowcount
    if deleted > 0:
        logger.info("Cleared %d existing shots for %d competition(s)", deleted, len(comp_ids))
    our_players = load_our_players(conn)
    logger.info("Loaded %d players from DB\n", len(our_players))

    with ZipFile(str(ZIP_PATH)) as zf:
        comp_data = json.loads(zf.read("open-data-master/data/competitions.json"))

        # Build player matcher once (with cache)
        matcher = PlayerMatcher(our_players)

        # Group seasons by competition
        comp_seasons: dict[int, list[dict]] = {}
        for entry in comp_data:
            cid = entry["competition_id"]
            if cid in competitions:
                comp_seasons.setdefault(cid, []).append(entry)

        for comp_id, comp_name in sorted(competitions.items()):
            seasons = comp_seasons.get(comp_id, [])
            if not seasons:
                logger.info("No seasons found for %s (comp_id=%d)", comp_name, comp_id)
                continue

            seasons.sort(key=lambda s: s.get("season_id", 0))
            comp_total = {"matches": 0, "shots_total": 0, "shots_matched": 0, "shots_stored": 0}

            for season_entry in seasons:
                season_stats = process_competition_season(
                    zf, comp_id, comp_name, season_entry,
                    matcher, conn, dry_run,
                )
                for k in comp_total:
                    comp_total[k] += season_stats[k]

            overall["details"][comp_name] = comp_total
            overall["matches_processed"] += comp_total["matches"]
            overall["shots_total"] += comp_total["shots_total"]
            overall["shots_matched"] += comp_total["shots_matched"]
            overall["shots_stored"] += comp_total["shots_stored"]

            logger.info(
                "Total for %s: %d matches, %d shots → %d matched → %d stored\n",
                comp_name, comp_total["matches"],
                comp_total["shots_total"],
                comp_total["shots_matched"],
                comp_total["shots_stored"],
            )

    conn.close()
    overall["elapsed_seconds"] = time.time() - start_time
    overall["competitions_processed"] = len(competitions)

    return overall


def print_report(stats: dict):
    """Print a formatted report."""
    print("\n" + "=" * 60)
    print("STATSBOMB LOAD REPORT")
    print("=" * 60)
    print(f"  Competitions:      {stats['competitions_processed']}")
    print(f"  Matches processed: {stats['matches_processed']:,}")
    print(f"  Shots total:       {stats['shots_total']:,}")
    print(f"  Shots matched:     {stats['shots_matched']:,}")
    print(f"  Shots stored:      {stats['shots_stored']:,}")
    if stats["shots_total"] > 0:
        match_rate = stats["shots_matched"] / stats["shots_total"] * 100
        print(f"  Match rate:        {match_rate:.1f}%")
    print(f"  Elapsed:           {stats['elapsed_seconds']:.1f}s")
    print()

    for comp_name, comp_stats in stats.get("details", {}).items():
        print(f"  {comp_name:25s}  {comp_stats['shots_total']:>6d} shots → {comp_stats['shots_matched']:>5d} matched → {comp_stats['shots_stored']:>5d} stored  ({comp_stats['matches']} matches)")

    print("=" * 60)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Load StatsBomb open data shots with xG into database"
    )
    parser.add_argument(
        "--competitions",
        default=None,
        help="Comma-separated competition IDs (default: all relevant)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report without writing to database",
    )
    parser.add_argument(
        "--priority",
        choices=["high", "medium", "low", "all"],
        default="high",
        help="Competition priority level to load (default: high)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Clear existing statsbomb_shots data before loading (default: append)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.competitions:
        cids = [int(c.strip()) for c in args.competitions.split(",") if c.strip()]
        competitions = {cid: ALL_COMPETITIONS.get(cid, f"Unknown({cid})") for cid in cids}
    elif args.priority == "high":
        competitions = PRIORITY_HIGH
    elif args.priority == "medium":
        competitions = {}
        competitions.update(PRIORITY_HIGH)
        competitions.update(PRIORITY_MEDIUM)
    elif args.priority == "low":
        competitions = ALL_COMPETITIONS
    else:
        competitions = ALL_COMPETITIONS

    stats = run(competitions, dry_run=args.dry_run, reload=args.reload)
    print_report(stats)
