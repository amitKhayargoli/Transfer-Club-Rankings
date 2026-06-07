"""
Club API endpoints.
"""

import math
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import Club, ClubMetricsWindow, Transfer
from api.schemas import (
    ClubBase,
    ClubDetailResponse,
    ClubListResponse,
    ClubCompareResponse,
    ClubWindowMetrics,
    ClubWindowMetricsResponse,
    TransferBase,
    TransferListResponse,
)
from api.config import MIN_TRANSFERS, ANALYTICS_WINDOWS
from api.utils import enrich_transfer_types

# ── Competition name mapping ──────────────────────────────────────────────

COMPETITION_NAMES = {
    "GB1": "English Premier League",
    "ES1": "LaLiga",
    "IT1": "Serie A",
    "FR1": "Ligue 1",
    "L1": "Swiss Super League",
    "BE1": "Belgian Pro League",
    "NL1": "Eredivisie",
    "PO1": "Primeira Liga",
    "BRA1": "Campeonato Brasileiro Série A",
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
    "CL": "UEFA Champions League",
    "EL": "UEFA Europa League",
    "ECLQ": "UEFA Conference League Qualifying",
    "ELQ": "UEFA Europa League Qualifying",
    "CLQ": "UEFA Champions League Qualifying",
    "FAC": "FA Cup",
    "CGB": "EFL Cup",
    "CDR": "Copa del Rey",
    "DFB": "DFB-Pokal",
    "CIT": "Coppa Italia",
    "DFL": "DFL-Supercup",
    "FRCH": "Trophée des Champions",
    "BESC": "Belgian Super Cup",
    "EURO": "UEFA Euro",
    "FIWC": "FIFA World Cup",
    "COPA": "Copa América",
    "AFCN": "Africa Cup of Nations",
    "AFAC": "AFC Asian Cup",
    "UCOL": "UEFA Conference League",
    "USC": "UEFA Super Cup",
    "SUC": "Spanish Supercopa",
    "SCI": "Italian Supercoppa",
    "GBCS": "FA Community Shield",
    "POCP": "Portuguese League Cup",
    "POSU": "Portuguese Super Cup",
    "NLP": "KNVB Cup",
    "NLSC": "Johan Cruyff Shield",
    "SFA": "Scottish FA Cup",
    "GRP": "Greek Cup",
    "RUP": "Russian Cup",
    "RUSS": "Russian Super Cup",
    "DKP": "Danish Cup",
    "UKRP": "Ukrainian Cup",
    "UKRS": "Ukrainian Super Cup",
}

router = APIRouter(prefix="/api/clubs", tags=["clubs"])


@router.get("", response_model=ClubListResponse)
async def list_clubs(
    league: Optional[str] = Query(None, description="Filter by single league (domestic_competition_id)"),
    leagues: Optional[str] = Query(None, description="Filter by comma-separated league IDs, e.g. 'GB1,FR1,ES1'"),
    min_transfers: int = Query(MIN_TRANSFERS, description="Minimum transfers threshold"),
    sort_by: str = Query("composite_score", description="Sort field"),
    sort_order: str = Query("desc", description="Sort order: asc or desc"),
    window: Optional[str] = Query(None, description=f"Analytical year window: one of {ANALYTICS_WINDOWS}. Defaults to all-time if omitted."),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    # Determine whether to use windowed metrics or full Club metrics
    use_window = window and window in [str(w) for w in ANALYTICS_WINDOWS]

    if use_window:
        # Query from ClubMetricsWindow with precomputed window metrics
        query = select(ClubMetricsWindow).where(
            ClubMetricsWindow.window_key == window
        )
        # Apply league filter via Club join
        if league:
            query = query.join(Club, ClubMetricsWindow.club_id == Club.club_id).where(
                Club.domestic_competition_id == league
            )
        elif leagues:
            league_ids = [l.strip() for l in leagues.split(",") if l.strip()]
            query = query.join(Club, ClubMetricsWindow.club_id == Club.club_id).where(
                Club.domestic_competition_id.in_(league_ids)
            )

        query = query.where(ClubMetricsWindow.total_transfers >= min_transfers)

        # Sorting
        sort_col = getattr(ClubMetricsWindow, sort_by, ClubMetricsWindow.composite_score)
        if sort_order == "desc":
            query = query.order_by(sort_col.desc().nullslast())
        else:
            query = query.order_by(sort_col.asc().nullslast())

        # Pagination
        total_q = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(total_q)
        total = total_result.scalar() or 0

        query = query.offset((page - 1) * per_page).limit(per_page)
        result = await db.execute(query)
        window_metrics = result.scalars().all()

        return ClubListResponse(
            clubs=[ClubBase.model_validate(wm) for wm in window_metrics],
            total=total,
            page=page,
            per_page=per_page,
        )
    else:
        # Full Club model query (existing behavior, all-time metrics)
        query = select(Club)

        if league:
            query = query.where(Club.domestic_competition_id == league)
        elif leagues:
            league_ids = [l.strip() for l in leagues.split(",") if l.strip()]
            query = query.where(Club.domestic_competition_id.in_(league_ids))

        query = query.where(Club.total_transfers >= min_transfers)

        sort_col = getattr(Club, sort_by, Club.composite_score)
        if sort_order == "desc":
            query = query.order_by(sort_col.desc().nullslast())
        else:
            query = query.order_by(sort_col.asc().nullslast())

        total_q = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(total_q)
        total = total_result.scalar() or 0

        query = query.offset((page - 1) * per_page).limit(per_page)
        result = await db.execute(query)
        clubs = result.scalars().all()

        return ClubListResponse(
            clubs=[ClubBase.model_validate(c) for c in clubs],
            total=total,
            page=page,
            per_page=per_page,
        )


@router.get("/compare", response_model=ClubCompareResponse)
async def compare_clubs(
    ids: str = Query(..., description="Comma-separated club IDs, e.g. '294,610'"),
    db: AsyncSession = Depends(get_db),
):
    from fastapi import HTTPException

    club_ids = [int(x.strip()) for x in ids.split(",")]
    if len(club_ids) != 2:
        raise HTTPException(status_code=400, detail="Provide exactly 2 club IDs")

    club1 = await db.get(Club, club_ids[0])
    club2 = await db.get(Club, club_ids[1])

    if not club1 or not club2:
        raise HTTPException(status_code=404, detail="One or both clubs not found")

    return ClubCompareResponse(
        club1=ClubDetailResponse.model_validate(club1),
        club2=ClubDetailResponse.model_validate(club2),
    )


@router.get("/sell-leaders", response_model=ClubListResponse)
async def list_sell_leaders(
    league: Optional[str] = Query(None, description="Filter by league"),
    window: Optional[str] = Query(None, description=f"Analytical year window: one of {ANALYTICS_WINDOWS}"),
    min_transfers: int = Query(3, description="Minimum transfers threshold"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Clubs ranked by total profit from selling players."""
    use_window = window and window in [str(w) for w in ANALYTICS_WINDOWS]

    if use_window:
        query = select(ClubMetricsWindow).where(
            ClubMetricsWindow.window_key == window,
            ClubMetricsWindow.total_profit.isnot(None),
        )
        if league:
            query = query.join(Club, ClubMetricsWindow.club_id == Club.club_id).where(
                Club.domestic_competition_id == league
            )
        query = query.where(ClubMetricsWindow.total_transfers >= min_transfers)
        query = query.order_by(ClubMetricsWindow.total_profit.desc().nullslast())

        total_q = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(total_q)
        total = total_result.scalar() or 0

        query = query.offset((page - 1) * per_page).limit(per_page)
        result = await db.execute(query)
        window_metrics = result.scalars().all()

        return ClubListResponse(
            clubs=[ClubBase.model_validate(wm) for wm in window_metrics],
            total=total,
            page=page,
            per_page=per_page,
        )
    else:
        query = select(Club)
        if league:
            query = query.where(Club.domestic_competition_id == league)
        query = query.where(Club.total_profit.isnot(None), Club.total_transfers >= min_transfers)
        query = query.order_by(Club.total_profit.desc().nullslast())

        total_q = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(total_q)
        total = total_result.scalar() or 0

        query = query.offset((page - 1) * per_page).limit(per_page)
        result = await db.execute(query)
        clubs = result.scalars().all()

        return ClubListResponse(
            clubs=[ClubBase.model_validate(c) for c in clubs],
            total=total,
            page=page,
            per_page=per_page,
        )


@router.get("/academy-leaders", response_model=ClubListResponse)
async def list_academy_leaders(
    league: Optional[str] = Query(None, description="Filter by league"),
    leagues: Optional[str] = Query(None, description="Filter by comma-separated league IDs, e.g. 'GB1,FR1,ES1'"),
    window: Optional[str] = Query(None, description=f"Analytical year window: one of {ANALYTICS_WINDOWS}"),
    min_transfers: int = Query(3, description="Minimum transfers threshold"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Clubs ranked by value creation (developing talent and selling high)."""
    use_window = window and window in [str(w) for w in ANALYTICS_WINDOWS]

    if use_window:
        query = select(ClubMetricsWindow).where(
            ClubMetricsWindow.window_key == window,
            ClubMetricsWindow.value_creation.isnot(None),
        )
        if league:
            query = query.join(Club, ClubMetricsWindow.club_id == Club.club_id).where(
                Club.domestic_competition_id == league
            )
        elif leagues:
            league_ids = [l.strip() for l in leagues.split(",") if l.strip()]
            query = query.join(Club, ClubMetricsWindow.club_id == Club.club_id).where(
                Club.domestic_competition_id.in_(league_ids)
            )
        query = query.where(ClubMetricsWindow.total_transfers >= min_transfers)
        query = query.order_by(ClubMetricsWindow.value_creation.desc().nullslast())

        total_q = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(total_q)
        total = total_result.scalar() or 0

        query = query.offset((page - 1) * per_page).limit(per_page)
        result = await db.execute(query)
        window_metrics = result.scalars().all()

        return ClubListResponse(
            clubs=[ClubBase.model_validate(wm) for wm in window_metrics],
            total=total,
            page=page,
            per_page=per_page,
        )
    else:
        query = select(Club)
        if league:
            query = query.where(Club.domestic_competition_id == league)
        elif leagues:
            league_ids = [l.strip() for l in leagues.split(",") if l.strip()]
            query = query.where(Club.domestic_competition_id.in_(league_ids))
        query = query.where(Club.value_creation.isnot(None), Club.total_transfers >= min_transfers)
        query = query.order_by(Club.value_creation.desc().nullslast())

        total_q = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(total_q)
        total = total_result.scalar() or 0

        query = query.offset((page - 1) * per_page).limit(per_page)
        result = await db.execute(query)
        clubs = result.scalars().all()

        return ClubListResponse(
            clubs=[ClubBase.model_validate(c) for c in clubs],
            total=total,
            page=page,
            per_page=per_page,
        )


@router.get("/{club_id}", response_model=ClubDetailResponse)
async def get_club(club_id: int, db: AsyncSession = Depends(get_db)):
    club = await db.get(Club, club_id)
    if not club:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Club not found")

    # Look up league name from competitions data
    league_name = None
    league_logo_url = None
    if club.domestic_competition_id:
        league_name = COMPETITION_NAMES.get(club.domestic_competition_id)
        if league_name:
            league_logo_url = f"https://tmssl.akamaized.net/images/logo/medium/{club.domestic_competition_id.lower()}.png"

    resp = ClubDetailResponse.model_validate(club)
    resp.league_name = league_name
    resp.league_logo_url = league_logo_url
    return resp


@router.get("/{club_id}/transfers", response_model=TransferListResponse)
async def get_club_transfers(
    club_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    # Transfers where club bought (to) or sold (from)
    query = select(Transfer).where(
        (Transfer.from_club_id == club_id) | (Transfer.to_club_id == club_id)
    ).order_by(Transfer.transfer_date.desc().nullslast())

    total_q = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(total_q)
    total = total_result.scalar() or 0

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    transfers = result.scalars().all()

    # Build response with transfer type classification & profit propagation
    enriched = await enrich_transfer_types(transfers, club_id=club_id, db=db)

    return TransferListResponse(
        transfers=enriched,
        total=total,
        page=page,
        per_page=per_page,
    )



