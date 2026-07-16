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
from api.config import MIN_TRANSFERS, ANALYTICS_WINDOWS, DEFAULT_WINDOW
from api.utils import enrich_transfer_types


# ── Helper: build ClubBase from window metrics + Club metadata ────────────

def _build_club_base_from_window(wm: ClubMetricsWindow, club: Club) -> ClubBase:
    """Build a ClubBase from ClubMetricsWindow + Club metadata.

    ClubMetricsWindow does not store name/club_code/domestic_competition_id,
    so we need the joined Club row to construct a valid ClubBase.
    """
    return ClubBase(
        club_id=wm.club_id,
        name=club.name,
        club_code=club.club_code,
        domestic_competition_id=club.domestic_competition_id,
        total_transfers=wm.total_transfers,
        median_roi=wm.median_roi,
        annualized_roi=wm.annualized_roi,
        total_profit=wm.total_profit,
        hit_rate=wm.hit_rate,
        value_creation=wm.value_creation,
        profit_per_deal=wm.profit_per_deal,
        buying_club_premium=wm.buying_club_premium,
        composite_score=wm.composite_score,
    )


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
    window: Optional[str] = Query(DEFAULT_WINDOW, description=f"Analytical year window. Defaults to {DEFAULT_WINDOW}+."),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    # Determine whether to use windowed metrics or full Club metrics
    use_window = window and window in [str(w) for w in ANALYTICS_WINDOWS]

    if use_window:
        # Query from ClubMetricsWindow with precomputed window metrics.
        # Must join Club to get name/club_code/domestic_competition_id
        # since ClubMetricsWindow does not store those columns.
        query = select(ClubMetricsWindow, Club).join(
            Club, ClubMetricsWindow.club_id == Club.club_id
        ).where(
            ClubMetricsWindow.window_key == window
        )

        # Apply league filter via Club (already joined)
        if league:
            query = query.where(Club.domestic_competition_id == league)
        elif leagues:
            league_ids = [l.strip() for l in leagues.split(",") if l.strip()]
            query = query.where(Club.domestic_competition_id.in_(league_ids))

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
        rows = result.all()

        clubs = [_build_club_base_from_window(wm, club) for wm, club in rows]

        return ClubListResponse(
            clubs=clubs,
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
    window: Optional[str] = Query(DEFAULT_WINDOW, description=f"Analytical year window. Defaults to {DEFAULT_WINDOW}+."),
    db: AsyncSession = Depends(get_db),
):
    from fastapi import HTTPException

    club_ids = [int(x.strip()) for x in ids.split(",")]
    if len(club_ids) != 2:
        raise HTTPException(status_code=400, detail="Provide exactly 2 club IDs")

    use_window = window and window in [str(w) for w in ANALYTICS_WINDOWS]

    async def _fetch_top_sale(cid: int, min_year: int | None) -> TransferBase | None:
        """Fetch the most profitable sale for a given club.

        A "sale" is a buy-sell pair where the club appears as from_club_id
        (the club that owned the player and is selling them).
        """
        q = select(Transfer).where(
            Transfer.from_club_id == cid,
            Transfer.profit.isnot(None),
            Transfer.profit > 0,
        )
        if min_year is not None:
            q = q.where(
                Transfer.transfer_date.isnot(None),
                func.extract("year", Transfer.transfer_date) >= min_year,
            )
        q = q.order_by(Transfer.profit.desc().nullslast()).limit(1)
        r = await db.execute(q)
        t = r.scalar_one_or_none()
        return TransferBase.model_validate(t) if t else None

    min_year = int(window) if (window and window in [str(w) for w in ANALYTICS_WINDOWS]) else None

    # Common helper: build a club response with top sale
    async def _build_club(cid: int) -> ClubDetailResponse:
        if window and window in [str(w) for w in ANALYTICS_WINDOWS]:
            wm_q = select(ClubMetricsWindow).where(
                ClubMetricsWindow.club_id == cid,
                ClubMetricsWindow.window_key == window,
            )
            wm_result = await db.execute(wm_q)
            wm = wm_result.scalar_one_or_none()
            if wm:
                club_entity = await db.get(Club, cid)
                if not club_entity:
                    raise HTTPException(status_code=404, detail=f"Club {cid} not found")
                base = _build_club_base_from_window(wm, club_entity)
            else:
                club_entity = await db.get(Club, cid)
                if not club_entity:
                    raise HTTPException(status_code=404, detail=f"Club {cid} not found")
                base = ClubBase.model_validate(club_entity)
        else:
            club_entity = await db.get(Club, cid)
            if not club_entity:
                raise HTTPException(status_code=404, detail=f"Club {cid} not found")
            base = ClubBase.model_validate(club_entity)

        resp = ClubDetailResponse.model_validate(base)
        resp.league_name = COMPETITION_NAMES.get(base.domestic_competition_id or "")
        if base.domestic_competition_id:
            resp.league_logo_url = f"https://tmssl.akamaized.net/images/logo/medium/{base.domestic_competition_id.lower()}.png"
        # Attach top sale
        top_sale = await _fetch_top_sale(cid, min_year)
        resp.top_sale = top_sale
        return resp

    return ClubCompareResponse(
        club1=await _build_club(club_ids[0]),
        club2=await _build_club(club_ids[1]),
    )


@router.get("/sell-leaders", response_model=ClubListResponse)
async def list_sell_leaders(
    league: Optional[str] = Query(None, description="Filter by league"),
    window: Optional[str] = Query(DEFAULT_WINDOW, description=f"Analytical year window. Defaults to {DEFAULT_WINDOW}+."),
    min_transfers: int = Query(3, description="Minimum transfers threshold"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Clubs ranked by total profit from selling players."""
    use_window = window and window in [str(w) for w in ANALYTICS_WINDOWS]

    if use_window:
        query = select(ClubMetricsWindow, Club).join(
            Club, ClubMetricsWindow.club_id == Club.club_id
        ).where(
            ClubMetricsWindow.window_key == window,
            ClubMetricsWindow.total_profit.isnot(None),
        )
        if league:
            query = query.where(Club.domestic_competition_id == league)
        query = query.where(ClubMetricsWindow.total_transfers >= min_transfers)
        query = query.order_by(ClubMetricsWindow.total_profit.desc().nullslast())

        total_q = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(total_q)
        total = total_result.scalar() or 0

        query = query.offset((page - 1) * per_page).limit(per_page)
        result = await db.execute(query)
        rows = result.all()

        clubs = [_build_club_base_from_window(wm, club) for wm, club in rows]

        return ClubListResponse(
            clubs=clubs,
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
    window: Optional[str] = Query(DEFAULT_WINDOW, description=f"Analytical year window. Defaults to {DEFAULT_WINDOW}+."),
    min_transfers: int = Query(3, description="Minimum transfers threshold"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Clubs ranked by value creation (developing talent and selling high)."""
    use_window = window and window in [str(w) for w in ANALYTICS_WINDOWS]

    if use_window:
        query = select(ClubMetricsWindow, Club).join(
            Club, ClubMetricsWindow.club_id == Club.club_id
        ).where(
            ClubMetricsWindow.window_key == window,
            ClubMetricsWindow.value_creation.isnot(None),
        )
        if league:
            query = query.where(Club.domestic_competition_id == league)
        elif leagues:
            league_ids = [l.strip() for l in leagues.split(",") if l.strip()]
            query = query.where(Club.domestic_competition_id.in_(league_ids))
        query = query.where(ClubMetricsWindow.total_transfers >= min_transfers)
        query = query.order_by(ClubMetricsWindow.value_creation.desc().nullslast())

        total_q = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(total_q)
        total = total_result.scalar() or 0

        query = query.offset((page - 1) * per_page).limit(per_page)
        result = await db.execute(query)
        rows = result.all()

        clubs = [_build_club_base_from_window(wm, club) for wm, club in rows]

        return ClubListResponse(
            clubs=clubs,
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


@router.get("/metrics/stats")
async def get_metrics_stats(
    window: Optional[str] = Query(DEFAULT_WINDOW, description=f"Window to compute stats from. Defaults to {DEFAULT_WINDOW}+."),
    db: AsyncSession = Depends(get_db),
):
    """Return population mean and std for each composite-score metric.

    Used by the Compare page to Z-score normalize radar chart values
    so metrics with different scales (ROI vs Hit Rate vs Value Creation)
    can be meaningfully compared.
    """
    use_window = window and window in [str(w) for w in ANALYTICS_WINDOWS]

    if use_window:
        q = select(ClubMetricsWindow).where(ClubMetricsWindow.window_key == window)
        result = await db.execute(q)
        rows = result.scalars().all()
    else:
        q = select(Club)
        result = await db.execute(q)
        rows = result.scalars().all()

    if not rows:
        return {}

    import statistics as stats

    def _metric_stats(values: list[float | None]) -> dict:
        clean = [v for v in values if v is not None]
        if len(clean) < 2:
            return {"mean": 0, "std": 1}
        return {
            "mean": stats.mean(clean),
            "std": stats.stdev(clean) if len(clean) > 1 else 1,
        }

    return {
        "median_roi": _metric_stats([r.median_roi for r in rows]),
        "total_profit": _metric_stats([r.total_profit for r in rows]),
        "hit_rate": _metric_stats([r.hit_rate for r in rows]),
        "value_creation": _metric_stats([r.value_creation for r in rows]),
        "annualized_roi": _metric_stats([r.annualized_roi for r in rows]),
        "profit_per_deal": _metric_stats([r.profit_per_deal for r in rows]),
        "composite_score": _metric_stats([r.composite_score for r in rows]),
    }


@router.get("/{club_id}", response_model=ClubDetailResponse)
async def get_club(
    club_id: int,
    window: Optional[str] = Query(DEFAULT_WINDOW, description=f"Analytical year window. Defaults to {DEFAULT_WINDOW}+."),
    db: AsyncSession = Depends(get_db),
):
    club = await db.get(Club, club_id)
    if not club:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Club not found")

    use_window = window and window in [str(w) for w in ANALYTICS_WINDOWS]

    if use_window:
        # Fetch window metrics
        wm_q = select(ClubMetricsWindow).where(
            ClubMetricsWindow.club_id == club_id,
            ClubMetricsWindow.window_key == window,
        )
        wm_result = await db.execute(wm_q)
        wm = wm_result.scalar_one_or_none()

        if wm:
            base = _build_club_base_from_window(wm, club)
        else:
            base = ClubBase.model_validate(club)
    else:
        base = ClubBase.model_validate(club)

    # Look up league name from competitions data
    league_name = None
    league_logo_url = None
    if club.domestic_competition_id:
        league_name = COMPETITION_NAMES.get(club.domestic_competition_id)
        if league_name:
            league_logo_url = f"https://tmssl.akamaized.net/images/logo/medium/{club.domestic_competition_id.lower()}.png"

    resp = ClubDetailResponse.model_validate(base)
    resp.league_name = league_name
    resp.league_logo_url = league_logo_url
    return resp


@router.get("/{club_id}/transfers", response_model=TransferListResponse)
async def get_club_transfers(
    club_id: int,
    window: Optional[str] = Query(DEFAULT_WINDOW, description=f"Filter transfers by buy year. Defaults to {DEFAULT_WINDOW}+."),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    # Transfers where club bought (to) or sold (from)
    query = select(Transfer).where(
        (Transfer.from_club_id == club_id) | (Transfer.to_club_id == club_id)
    )

    # Apply window filter: only deals with buy year >= window
    use_window = window and window in [str(w) for w in ANALYTICS_WINDOWS]
    if use_window:
        min_year = int(window)
        query = query.where(
            Transfer.transfer_date.isnot(None),
            func.extract("year", Transfer.transfer_date) >= min_year,
        )

    query = query.order_by(Transfer.transfer_date.desc().nullslast())

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



