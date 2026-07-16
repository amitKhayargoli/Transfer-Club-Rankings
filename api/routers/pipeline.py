"""
Pipeline API endpoints  trigger data loading and check status.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db, init_db
from api.models import Club, ClubMetricsWindow, Player, Transfer, PlayerValuation
from api.services.data_loader import run_pipeline
from api.schemas import PipelineRunResponse, PipelineStatusResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.post("/run", response_model=PipelineRunResponse)
async def trigger_pipeline(db: AsyncSession = Depends(get_db)):
    """Load all CSV data into the database."""
    logger.info("Pipeline triggered via API")

    # Ensure tables exist
    await init_db()

    # Run the data loading pipeline
    result = await run_pipeline(db)

    return PipelineRunResponse(
        status="success",
        message="Data pipeline completed successfully",
        clubs_loaded=result["clubs"],
        players_loaded=result["players"],
        transfers_loaded=result["transfers"],
        valuations_loaded=result["valuations"],
        pairs_computed=result["pairs_computed"],
        clubs_updated=result["clubs_updated"],
    )


@router.get("/status", response_model=PipelineStatusResponse)
async def get_pipeline_status(db: AsyncSession = Depends(get_db)):
    """Check if data has been loaded into the database."""
    total_clubs = (await db.execute(select(func.count(Club.club_id)))).scalar() or 0
    total_players = (await db.execute(select(func.count(Player.player_id)))).scalar() or 0
    total_transfers = (await db.execute(select(func.count(Transfer.transfer_id)))).scalar() or 0

    # Check 2015+ window status
    window_q = select(ClubMetricsWindow.last_updated).where(
        ClubMetricsWindow.window_key == "2015"
    ).order_by(ClubMetricsWindow.last_updated.desc().nullslast()).limit(1)
    window_result = await db.execute(window_q)
    window_last_updated = window_result.scalar_one_or_none()

    data_loaded = total_clubs > 0 and total_players > 0 and total_transfers > 0

    return PipelineStatusResponse(
        data_loaded=data_loaded,
        last_refresh=window_last_updated.isoformat() if window_last_updated else (datetime.now().isoformat() if data_loaded else None),
        total_clubs=total_clubs,
        total_players=total_players,
        total_transfers=total_transfers,
    )
