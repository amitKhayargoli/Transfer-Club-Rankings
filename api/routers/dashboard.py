"""
Dashboard API endpoints.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import Club, Transfer
from api.schemas import (
    DashboardStatsResponse,
    DashboardTopClubsResponse,
    TopClubResponse,
    TransferBase,
)
from api.config import MIN_TRANSFERS

# Leagues that match the Rankings page filtering (top European leagues)
_ENRICHED_LEAGUES = ["GB1", "ES1", "IT1", "FR1", "L1", "PO1", "NL1", "A1"]

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)):
    # Total transfers
    total_transfers_q = select(func.count(Transfer.transfer_id))
    total_transfers = (await db.execute(total_transfers_q)).scalar() or 0

    # Total clubs
    total_clubs_q = select(func.count(Club.club_id))
    total_clubs = (await db.execute(total_clubs_q)).scalar() or 0

    # Total profit across all clubs
    total_profit_q = select(func.coalesce(func.sum(Club.total_profit), 0))
    total_profit = (await db.execute(total_profit_q)).scalar() or 0.0

    # Biggest single profit transfer
    biggest_profit_q = select(Transfer).where(
        Transfer.profit.isnot(None)
    ).order_by(Transfer.profit.desc().nullslast()).limit(1)
    biggest_result = await db.execute(biggest_profit_q)
    biggest_transfer = biggest_result.scalar_one_or_none()

    return DashboardStatsResponse(
        total_transfers=total_transfers,
        total_clubs=total_clubs,
        total_profit=total_profit,
        biggest_profit_transfer=TransferBase.model_validate(biggest_transfer) if biggest_transfer else None,
    )


@router.get("/top-clubs", response_model=DashboardTopClubsResponse)
async def get_top_clubs(db: AsyncSession = Depends(get_db)):
    query = select(Club).where(
        Club.composite_score.isnot(None),
        Club.total_transfers >= MIN_TRANSFERS,
        Club.domestic_competition_id.in_(_ENRICHED_LEAGUES),
    ).order_by(Club.composite_score.desc().nullslast()).limit(10)

    result = await db.execute(query)
    clubs = result.scalars().all()

    from api.schemas import ClubBase

    return DashboardTopClubsResponse(
        top_clubs=[
            TopClubResponse(rank=i + 1, club=ClubBase.model_validate(c))
            for i, c in enumerate(clubs)
        ]
    )
