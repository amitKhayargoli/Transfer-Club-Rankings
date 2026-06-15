"""
scrape_transfermarkt_appearances.py — Scrape T3/T4 player season stats from Transfermarkt.

Uses Playwright to intercept the Transfermarkt performance API and extract
game-level stats (goals, assists, minutes, cards) for players from T3/T4
leagues in our training set. Aggregates by season+competition and stores
in the player_performances table for use in feature extraction.

Rate limit: 1.5s delay between players to avoid being blocked.
"""

import asyncio
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DB_PATH = "data/transfer_roi.db"
REQUEST_DELAY = 1.5  # seconds between players


def get_conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def create_staging_table(conn: sqlite3.Connection) -> None:
    """Create staging table for Transfermarkt performance data."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS player_performances (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id       INTEGER NOT NULL,
            season          TEXT NOT NULL,
            competition_id  TEXT NOT NULL,
            club_id         INTEGER,
            appearances     INTEGER DEFAULT 0,
            starts          INTEGER DEFAULT 0,
            minutes_played  INTEGER DEFAULT 0,
            goals           INTEGER DEFAULT 0,
            assists         INTEGER DEFAULT 0,
            yellow_cards    INTEGER DEFAULT 0,
            red_cards       INTEGER DEFAULT 0,
            games_count     INTEGER DEFAULT 0,
            data_source     TEXT DEFAULT 'transfermarkt',
            scraped_at      TEXT DEFAULT (datetime('now')),
            UNIQUE(player_id, season, competition_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pp_player ON player_performances(player_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pp_season ON player_performances(season)")
    conn.commit()


def get_target_players(conn: sqlite3.Connection) -> list[dict]:
    """Get distinct players from training pairs with T3/T4 selling clubs."""
    cursor = conn.execute("""
        SELECT DISTINCT t.player_id, p.name as player_name
        FROM transfers t
        JOIN players p ON t.player_id = p.player_id
        JOIN clubs c ON t.from_club_id = c.club_id
        WHERE t.is_training_eligible = 1
          AND c.league_tier IN (3, 4)
          AND c.domestic_competition_id IS NOT NULL
        ORDER BY t.player_id
    """)
    players = [{"id": r[0], "name": r[1]} for r in cursor.fetchall()]
    logger.info("Found %d T3/T4 players from training pairs to scrape", len(players))
    return players


def make_player_slug(name: str) -> str:
    """Convert a player name into a Transfermarkt URL slug."""
    if not name:
        return ""
    slug = name.lower()
    # Replace special characters
    replacements = {
        "á": "a", "à": "a", "ä": "a", "â": "a", "ã": "a",
        "é": "e", "è": "e", "ë": "e", "ê": "e",
        "í": "i", "ì": "i", "ï": "i", "î": "i",
        "ó": "o", "ò": "o", "ö": "o", "ô": "o", "õ": "o",
        "ú": "u", "ù": "u", "ü": "u", "û": "u",
        "ç": "c", "ñ": "n", "š": "s", "ž": "z",
        "đ": "d",
    }
    for old, new in replacements.items():
        slug = slug.replace(old, new)
    # Remove special chars, replace spaces with hyphens
    slug = "".join(c if c.isalnum() or c in [" ", "-"] else "" for c in slug)
    slug = "-".join(slug.split())
    slug = slug.strip("-")
    return slug


def save_performances(conn: sqlite3.Connection, player_id: int, perf_data: list[dict]) -> int:
    """Save aggregated season performances to the database."""
    if not perf_data:
        return 0

    saved = 0
    for perf in perf_data:
        season = perf["season"]
        competition_id = perf["competition_id"]
        club_id = perf.get("club_id")

        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO player_performances
                    (player_id, season, competition_id, club_id,
                     appearances, starts, minutes_played,
                     goals, assists, yellow_cards, red_cards, games_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    player_id, season, competition_id, club_id,
                    perf["appearances"], perf["starts"], perf["minutes_played"],
                    perf["goals"], perf["assists"], perf["yellow_cards"],
                    perf["red_cards"], perf["games_count"],
                ),
            )
            saved += 1
        except Exception as e:
            logger.warning("  Error saving %s %s: %s", player_id, season, e)

    conn.commit()
    return saved


def aggregate_performances(games: list[dict]) -> list[dict]:
    """Aggregate game-level stats into season+competition summaries.

    Each game dict: {competition_id, season_display, season_id, date,
                     club_id, minutes, goals, assists, yellow, red, is_starting}
    """
    from collections import defaultdict

    buckets: dict = defaultdict(lambda: {
        "appearances": 0, "starts": 0, "minutes_played": 0,
        "goals": 0, "assists": 0, "yellow_cards": 0, "red_cards": 0,
        "games_count": 0, "club_id": None,
    })

    for g in games:
        key = (g["competition_id"], g["season_display"])
        b = buckets[key]

        # Only count as appearance if they played > 0 minutes
        if g["minutes"] > 0:
            b["appearances"] += 1
        elif not g["is_starting"] and g["minutes"] == 0:
            # On bench but didn't play — not an appearance
            continue

        b["minutes_played"] += g["minutes"]
        b["goals"] += g["goals"]
        b["assists"] += g["assists"]
        b["yellow_cards"] += g["yellow"]
        b["red_cards"] += g["red"]
        b["games_count"] += 1

        if g["is_starting"]:
            b["starts"] += 1

        # Use most common club_id for this season
        b["club_id"] = g["club_id"]

    result = []
    for (comp_id, season), stats in buckets.items():
        result.append({
            "season": season,
            "competition_id": comp_id,
            "club_id": stats["club_id"],
            "appearances": stats["appearances"],
            "starts": stats["starts"],
            "minutes_played": stats["minutes_played"],
            "goals": stats["goals"],
            "assists": stats["assists"],
            "yellow_cards": stats["yellow_cards"],
            "red_cards": stats["red_cards"],
            "games_count": stats["games_count"],
        })

    return result


def parse_performance_api(api_data: dict) -> list[dict]:
    """Parse the Transfermarkt performance API response into game-level records."""
    if not api_data or not api_data.get("success"):
        return []

    perf_data = api_data.get("data", {}).get("performance", [])
    if not perf_data:
        return []

    games = []
    for game in perf_data:
        stats = game.get("statistics")
        if not stats:
            continue

        gi = game.get("gameInformation", {})
        ci = game.get("clubsInformation", {})

        competition_id = gi.get("competitionId", "")
        season_display = gi.get("season", {}).get("display", "")
        season_id = gi.get("season", {}).get("id")
        date_str = gi.get("date", {}).get("dateTimeUTC", "")

        # Club the player played for
        club_id = ci.get("club", {}).get("clubId")

        # Stats extraction
        pts = stats.get("playingTimeStatistics", {})
        gs = stats.get("goalStatistics", {})
        cs = stats.get("cardStatistics", {})

        minutes = pts.get("playedMinutes", 0) or 0
        is_starting = pts.get("isStarting", False) or False
        goals = gs.get("goalsScoredTotal", 0) or 0
        assists = gs.get("assists", 0) or 0
        yellow = cs.get("yellowCardNet", 0) or 0
        yellow_red = cs.get("yellowRedCard", 0) or 0
        # redCardsRescinded tracks rescinded red cards; use yellowRedCard
        # as the primary sending-off signal (two yellows = red card equivalent)
        red = cs.get("redCard", 0) or yellow_red

        games.append({
            "competition_id": competition_id,
            "season_display": season_display,
            "season_id": season_id,
            "date": date_str,
            "club_id": int(club_id) if club_id else None,
            "minutes": minutes,
            "goals": goals,
            "assists": assists,
            "yellow": yellow,
            "red": red,
            "is_starting": is_starting,
        })

    return games


async def scrape_player_page(
    browser, player_id: int, player_name: str
) -> list[dict]:
    """Scrape a single player's performance data from Transfermarkt.

    Returns list of aggregated season-level performance records.
    """
    slug = make_player_slug(player_name or str(player_id))
    url = f"https://www.transfermarkt.com/{slug}/leistungsdaten/spieler/{player_id}"

    api_result = {}

    async def intercept_response(response):
        if "performance-game" in response.url and "player" in response.url:
            try:
                api_result["data"] = await response.json()
            except Exception:
                pass

    page = await browser.new_page()
    page.on("response", intercept_response)

    try:
        await page.goto(url, timeout=20000, wait_until="networkidle")
        await page.wait_for_timeout(2000)

        if "data" not in api_result:
            logger.warning("  No API data for player %d (%s)", player_id, player_name)
            return []

        games = parse_performance_api(api_result["data"])
        if not games:
            logger.warning("  No games found for player %d", player_id)
            return []

        aggregated = aggregate_performances(games)
        logger.info(
            "  Player %d (%s): %d games → %d season-competition records",
            player_id, player_name, len(games), len(aggregated),
        )
        return aggregated

    except Exception as e:
        logger.error("  Error scraping player %d: %s", player_id, e)
        return []
    finally:
        await page.close()


async def main_async():
    logger.info("=" * 60)
    logger.info("TRANSFERMARKT APPEARANCE SCRAPER")
    logger.info("=" * 60)
    logger.info("")

    conn = get_conn()
    create_staging_table(conn)

    # Get players to scrape
    players = get_target_players(conn)
    if not players:
        logger.info("No players to scrape")
        return

    # Check which players already have data (resume support)
    existing = set()
    cursor = conn.execute("SELECT DISTINCT player_id FROM player_performances")
    for r in cursor.fetchall():
        existing.add(r[0])
    logger.info("Already have data for %d players", len(existing))

    # Filter to players not yet scraped. If a player already has data but
    # appears incomplete (fewer season records than expected), re-scrape by
    # deleting their old data first.
    to_scrape = []
    for p in players:
        if p["id"] in existing:
            cursor.execute(
                "SELECT COUNT(*) FROM player_performances WHERE player_id = ?",
                (p["id"],),
            )
            count = cursor.fetchone()[0]
            # Re-scrape if fewer than 5 season records (likely incomplete)
            if count < 5:
                conn.execute("DELETE FROM player_performances WHERE player_id = ?", (p["id"],))
                conn.commit()
                to_scrape.append(p)
        else:
            to_scrape.append(p)
    logger.info("Players to scrape: %d / %d", len(to_scrape), len(players))

    if not to_scrape:
        logger.info("All players already scraped!")
        conn.close()
        return

    # Scrape with Playwright
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        total_saved = 0
        scraped_count = 0

        for i, player in enumerate(to_scrape):
            logger.info(
                "[%d/%d] Player %d: %s",
                i + 1, len(to_scrape), player["id"], player["name"],
            )

            perf_data = await scrape_player_page(browser, player["id"], player["name"])

            if perf_data:
                saved = save_performances(conn, player["id"], perf_data)
                total_saved += saved
                scraped_count += 1

            # Rate limit between players
            if i < len(to_scrape) - 1:
                await asyncio.sleep(REQUEST_DELAY)

        await browser.close()

    # Summary
    conn.commit()
    cursor = conn.execute("SELECT COUNT(*) FROM player_performances")
    total_rows = cursor.fetchone()[0]
    cursor = conn.execute("SELECT COUNT(DISTINCT player_id) FROM player_performances")
    total_players = cursor.fetchone()[0]

    logger.info("")
    logger.info("=" * 60)
    logger.info("SCRAPING COMPLETE")
    logger.info("=" * 60)
    logger.info("")
    logger.info("Players scraped:  %d", scraped_count)
    logger.info("Total rows saved: %d", total_saved)
    logger.info("Total in DB:      %d rows for %d players", total_rows, total_players)

    conn.close()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
