"""
League-level API endpoints - aggregated spending and per-league club rankings.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import Club
from api.config import MIN_TRANSFERS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/leagues", tags=["leagues"])

# ── Competition name mapping ──────────────────────────────────────────────

COMPETITION_NAMES: dict[str, str] = {
    "GB1": "Premier League",
    "ES1": "LaLiga",
    "IT1": "Serie A",
    "FR1": "Ligue 1",
    "L1": "Swiss Super League",
    "BE1": "Belgian Pro League",
    "NL1": "Eredivisie",
    "PO1": "Primeira Liga",
    "BRA1": "Brasileirão Série A",
    "ARG1": "Argentine Primera División",
    "C1": "Super League Greece",
    "DK1": "Danish Superliga",
    "AUS1": "A-League Men",
    "A1": "Austrian Bundesliga",
    "NO1": "Eliteserien",
    "SE1": "Allsvenskan",
    "SC1": "Scottish Premiership",
    "TR1": "Süper Lig",
    "RU1": "Russian Premier Liga",
    "PL1": "Polish Ekstraklasa",
    "TS1": "Czech Chance Liga",
    "RO1": "Romanian Superliga",
    "KR1": "Croatian HNL",
    "SER1": "Serbian SuperLiga",
    "UKR1": "Ukrainian Premier League",
    "MEX1": "Liga MX",
    "MLS1": "Major League Soccer",
    "JAP1": "J1 League",
    "KRS1": "K League 1",
    "SA1": "Saudi Pro League",
    "COL1": "Liga BetPlay",
}

# ── Pydantic schemas (inline to keep things simple) ───────────────────────

from pydantic import BaseModel


class LeagueStats(BaseModel):
    id: str
    name: str
    total_clubs: int
    total_transfers: int
    total_profit: float
    avg_profit_per_club: float


class LeagueSpendingResponse(BaseModel):
    leagues: list[LeagueStats]


@router.get("/spending", response_model=LeagueSpendingResponse)
async def get_league_spending(
    min_transfers: int = Query(
        MIN_TRANSFERS,
        description="Minimum total transfers for a league to appear",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate transfer profit/loss by league. Negative = net spending."""
    result = await db.execute(
        select(
            Club.domestic_competition_id,
            func.count(Club.club_id).label("total_clubs"),
            func.coalesce(func.sum(Club.total_transfers), 0).label("total_transfers"),
            func.coalesce(func.sum(Club.total_profit), 0).label("total_profit"),
        )
        .where(
            Club.domestic_competition_id.isnot(None),
            Club.total_profit.isnot(None),
        )
        .group_by(Club.domestic_competition_id)
        .having(func.coalesce(func.sum(Club.total_transfers), 0) >= min_transfers)
        .order_by(func.coalesce(func.sum(Club.total_profit), 0).asc())
    )
    rows = result.all()

    leagues = [
        LeagueStats(
            id=row.domestic_competition_id,
            name=COMPETITION_NAMES.get(row.domestic_competition_id, row.domestic_competition_id),
            total_clubs=row.total_clubs,
            total_transfers=row.total_transfers,
            total_profit=round(row.total_profit, 0),
            avg_profit_per_club=round(row.total_profit / row.total_clubs, 0) if row.total_clubs > 0 else 0,
        )
        for row in rows
    ]

    return LeagueSpendingResponse(leagues=leagues)
