"""
Rate-limited client wrapping the transfermarkt-api service classes.

Adds the transfermarkt-api path to sys.path so its modules can be imported,
then wraps each service class with rate limiting and error handling.
"""

import sys
import time
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Path to the cloned transfermarkt-api repo
TRANSFERMARKT_API_PATH = Path("/tmp/transfermarkt-api")

if str(TRANSFERMARKT_API_PATH) not in sys.path:
    sys.path.insert(0, str(TRANSFERMARKT_API_PATH))


class RateLimiter:
    """Simple rate limiter that enforces a minimum interval between calls."""

    def __init__(self, min_interval: float = 2.5):
        self.min_interval = min_interval
        self._last_call_time = 0.0

    def wait(self):
        """Block until the minimum interval has elapsed since the last call."""
        now = time.monotonic()
        elapsed = now - self._last_call_time
        if elapsed < self.min_interval:
            sleep_time = self.min_interval - elapsed
            logger.debug("Rate limiter: sleeping %.2fs", sleep_time)
            time.sleep(sleep_time)
        self._last_call_time = time.monotonic()


class TransfermarktClient:
    """
    Client that wraps the transfermarkt-api service classes with
    rate limiting, retries, and consistent error handling.

    All scrapers are instantiated once per call (they are dataclasses
    that fetch and parse data in __post_init__).
    """

    def __init__(self, rate_limit: float = 2.5, max_retries: int = 3):
        self.rate_limiter = RateLimiter(min_interval=rate_limit)
        self.max_retries = max_retries

    def _call_with_retry(self, service_cls, **kwargs) -> dict[str, Any] | None:
        """Instantiate a service and call its fetch method with retries."""
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self.rate_limiter.wait()
                service = service_cls(**kwargs)
                # Each service has its own fetch method name - detect it
                method_name = self._get_fetch_method(service_cls.__name__)
                result = getattr(service, method_name)()
                return result
            except Exception as e:
                last_error = e
                logger.warning(
                    "Attempt %d/%d failed for %s(%s): %s",
                    attempt, self.max_retries,
                    service_cls.__name__, kwargs, e,
                )
                if attempt < self.max_retries:
                    backoff = 2 ** attempt
                    logger.info("Backing off %ds before retry...", backoff)
                    time.sleep(backoff)
        logger.error(
            "All %d attempts failed for %s(%s): %s",
            self.max_retries, service_cls.__name__, kwargs, last_error,
        )
        return None

    @staticmethod
    def _get_fetch_method(class_name: str) -> str:
        """Map service class name to its fetch method name."""
        mapping = {
            "TransfermarktPlayerProfile": "get_player_profile",
            "TransfermarktPlayerTransfers": "get_player_transfers",
            "TransfermarktPlayerMarketValue": "get_player_market_value",
            "TransfermarktPlayerSearch": "search_players",
            "TransfermarktClubSearch": "search_clubs",
            "TransfermarktClubProfile": "get_club_profile",
            "TransfermarktClubPlayers": "get_club_players",
            "TransfermarktCompetitionSearch": "search_competitions",
            "TransfermarktCompetitionClubs": "get_competition_clubs",
        }
        return mapping.get(class_name, "get_" + class_name.split("Transfermarkt")[-1].lower())

    # ── Player methods ──────────────────────────────────────────────────

    def get_player_profile(self, player_id: str) -> dict[str, Any] | None:
        """Fetch a player's profile information."""
        from app.services.players.profile import TransfermarktPlayerProfile
        return self._call_with_retry(TransfermarktPlayerProfile, player_id=player_id)

    def get_player_transfers(self, player_id: str) -> dict[str, Any] | None:
        """Fetch a player's full transfer history."""
        from app.services.players.transfers import TransfermarktPlayerTransfers
        return self._call_with_retry(TransfermarktPlayerTransfers, player_id=player_id)

    def get_player_market_value(self, player_id: str) -> dict[str, Any] | None:
        """Fetch a player's market value history."""
        from app.services.players.market_value import TransfermarktPlayerMarketValue
        return self._call_with_retry(TransfermarktPlayerMarketValue, player_id=player_id)

    def search_players(self, player_name: str, page_number: int = 1) -> dict[str, Any] | None:
        """Search for players by name."""
        from app.services.players.search import TransfermarktPlayerSearch
        return self._call_with_retry(
            TransfermarktPlayerSearch,
            query=player_name,
            page_number=page_number,
        )

    # ── Club methods ────────────────────────────────────────────────────

    def search_clubs(self, club_name: str) -> dict[str, Any] | None:
        """Search for clubs by name."""
        from app.services.clubs.search import TransfermarktClubSearch
        return self._call_with_retry(TransfermarktClubSearch, query=club_name)

    def get_club_profile(self, club_id: str) -> dict[str, Any] | None:
        """Fetch a club's profile information."""
        from app.services.clubs.profile import TransfermarktClubProfile
        return self._call_with_retry(TransfermarktClubProfile, club_id=club_id)

    def get_club_players(self, club_id: str, season_id: str | None = None) -> dict[str, Any] | None:
        """Fetch a club's current squad."""
        from app.services.clubs.players import TransfermarktClubPlayers
        return self._call_with_retry(
            TransfermarktClubPlayers,
            club_id=club_id,
            season_id=season_id,
        )
