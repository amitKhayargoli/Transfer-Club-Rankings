"""
Dashboard API endpoints.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import Club, ClubMetricsWindow, Transfer
from api.schemas import (
    DashboardStatsResponse,
    DashboardTopClubsResponse,
    TopClubResponse,
    TransferBase,
    ClubBase,
)
from api.config import MIN_TRANSFERS, DEFAULT_WINDOW

# Leagues that match the Rankings page filtering (top European leagues)
_ENRICHED_LEAGUES = ["GB1", "ES1", "IT1", "FR1", "L1", "PO1", "NL1", "A1"]

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)):
    # Total transfers (post-2014 only)
    total_transfers_q = select(func.count(Transfer.transfer_id)).where(
        Transfer.transfer_date.isnot(None),
        func.extract("year", Transfer.transfer_date) >= 2015,
    )
    total_transfers = (await db.execute(total_transfers_q)).scalar() or 0

    # Total clubs (with metrics in 2015+ window)
    total_clubs_q = select(func.count()).select_from(
        select(ClubMetricsWindow.club_id).where(
            ClubMetricsWindow.window_key == DEFAULT_WINDOW
        ).subquery()
    )
    total_clubs = (await db.execute(total_clubs_q)).scalar() or 0

    # Total profit across clubs (from 2015+ window)
    total_profit_q = select(func.coalesce(func.sum(ClubMetricsWindow.total_profit), 0)).where(
        ClubMetricsWindow.window_key == DEFAULT_WINDOW
    )
    total_profit = (await db.execute(total_profit_q)).scalar() or 0.0

    # Biggest single profit transfer (post-2014 only)
    biggest_profit_q = select(Transfer).where(
        Transfer.profit.isnot(None),
        Transfer.transfer_date.isnot(None),
        func.extract("year", Transfer.transfer_date) >= 2015,
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
    # Use 2015+ window metrics with enriched league filter
    query = select(ClubMetricsWindow, Club).join(
        Club, ClubMetricsWindow.club_id == Club.club_id
    ).where(
        ClubMetricsWindow.window_key == DEFAULT_WINDOW,
        ClubMetricsWindow.composite_score.isnot(None),
        ClubMetricsWindow.total_transfers >= MIN_TRANSFERS,
        Club.domestic_competition_id.in_(_ENRICHED_LEAGUES),
    ).order_by(ClubMetricsWindow.composite_score.desc().nullslast()).limit(10)

    result = await db.execute(query)
    rows = result.all()

    # Reuse the helper from clubs.py
    from api.routers.clubs import _build_club_base_from_window

    return DashboardTopClubsResponse(
        top_clubs=[
            TopClubResponse(rank=i + 1, club=_build_club_base_from_window(wm, club))
            for i, (wm, club) in enumerate(rows)
        ]
    )
