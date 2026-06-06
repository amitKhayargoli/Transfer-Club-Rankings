"""
Player API endpoints.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import Club, Player, Transfer, PlayerValuation
from api.schemas import (
    PlayerBase,
    PlayerDetailResponse,
    PlayerListResponse,
    TransferBase,
    PlayerValuationBase,
)
from collections import defaultdict

from api.utils import classify_transfer, detect_loans

router = APIRouter(prefix="/api/players", tags=["players"])


@router.get("", response_model=PlayerListResponse)
async def list_players(
    q: Optional[str] = Query(None, description="Search query (fuzzy match on name)"),
    position: Optional[str] = Query(None, description="Filter by position"),
    club_id: Optional[int] = Query(None, description="Filter by current club"),
    league: Optional[str] = Query(None, description="Filter by league (domestic_competition_id)"),
    sort_by: str = Query("market_value_in_eur", description="Field to sort by"),
    sort_order: str = Query("desc", description="Sort direction: asc or desc"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=200, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    # Allowlist of safe sort fields
    ALLOWED_SORT_FIELDS = {"market_value_in_eur", "name", "position", "date_of_birth", "current_club_name"}
    if sort_by not in ALLOWED_SORT_FIELDS:
        sort_by = "market_value_in_eur"

    query = select(Player)

    # Build the base query with filters
    if q:
        query = query.where(Player.name.ilike(f"%{q}%"))
    if position:
        query = query.where(Player.position == position)
    if club_id:
        query = query.where(Player.current_club_id == club_id)
    if league:
        query = query.join(Club, Player.current_club_id == Club.club_id).where(
            Club.domestic_competition_id == league
        )

    # Sort by requested field
    sort_col = getattr(Player, sort_by, Player.market_value_in_eur)
    if sort_order == "asc":
        query = query.order_by(sort_col.asc().nullslast())
    else:
        query = query.order_by(sort_col.desc().nullslast())

    # Total count
    total_q = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(total_q)
    total = total_result.scalar() or 0

    # Paginate
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    players = result.scalars().all()

    return PlayerListResponse(
        players=[PlayerBase.model_validate(p) for p in players],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{player_id}", response_model=PlayerDetailResponse)
async def get_player(player_id: int, db: AsyncSession = Depends(get_db)):
    from fastapi import HTTPException

    player = await db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    return PlayerDetailResponse.model_validate(player)


@router.get("/{player_id}/transfers", response_model=list[TransferBase])
async def get_player_transfers(player_id: int, db: AsyncSession = Depends(get_db)):
    query = select(Transfer).where(Transfer.player_id == player_id).order_by(Transfer.transfer_date.asc().nullslast())
    result = await db.execute(query)
    transfers = result.scalars().all()

    # Build a map of club -> most recent buy transfer with profit
    buy_map: dict[int, Transfer] = {}
    for t in transfers:
        if t.to_club_id and t.transfer_fee and t.transfer_fee > 0 and t.roi_pct is not None:
            buy_map[t.to_club_id] = t

    # Detect loans from paired transfers
    player_map: dict[int, list[Transfer]] = defaultdict(list)
    for t in transfers:
        player_map[t.player_id].append(t)
    loan_ids = detect_loans(transfers, player_map)

    # Build response with transfer type & profit propagation (Pydantic models, not ORM)
    enriched = []
    for t in transfers:
        data = TransferBase.model_validate(t)

        # Classify the transfer type (loan overrides free_transfer)
        base_type = classify_transfer(data)
        if base_type == "free_transfer" and t.transfer_id in loan_ids:
            data.transfer_type = "loan"
        else:
            data.transfer_type = base_type

        # Propagate profit from matching buy for sell-side transfers
        if t.from_club_id and data.profit is None and t.transfer_fee and t.transfer_fee > 0:
            buy = buy_map.get(t.from_club_id)
            if buy and buy.transfer_date and t.transfer_date and t.transfer_date > buy.transfer_date:
                data.buy_fee = buy.buy_fee
                data.sell_fee = buy.sell_fee
                data.profit = buy.profit
                data.roi_pct = buy.roi_pct
                data.annualized_roi_pct = buy.annualized_roi_pct
                data.player_position = buy.player_position

        enriched.append(data)

    enriched.reverse()
    return enriched


@router.get("/{player_id}/valuations", response_model=list[PlayerValuationBase])
async def get_player_valuations(player_id: int, db: AsyncSession = Depends(get_db)):
    query = select(PlayerValuation).where(
        PlayerValuation.player_id == player_id
    ).order_by(PlayerValuation.date.asc().nullslast())
    result = await db.execute(query)
    valuations = result.scalars().all()
    return [PlayerValuationBase.model_validate(v) for v in valuations]
