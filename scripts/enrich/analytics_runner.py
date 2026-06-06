"""
Analytics re-run wrapper.

Calls the existing analytics pipeline services to recompute
buy-sell pairs and club metrics after enrichment.
"""

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def run_analytics(session: AsyncSession) -> dict:
    """Re-run the full analytics pipeline (buy-sell pairs + club metrics).

    This calls the existing services from api.services.analytics.

    Returns:
        dict with keys: pairs_computed, clubs_updated
    """
    from api.services.analytics import compute_buy_sell_pairs, compute_club_metrics

    logger.info("Re-running analytics pipeline after enrichment...")

    pairs_count = await compute_buy_sell_pairs(session)
    logger.info("Computed %d buy-sell pairs", pairs_count)

    clubs_count = await compute_club_metrics(session)
    logger.info("Updated metrics for %d clubs", clubs_count)

    return {
        "pairs_computed": pairs_count,
        "clubs_updated": clubs_count,
    }
