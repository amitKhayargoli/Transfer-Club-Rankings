"""
Transfer API endpoints.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import Transfer
from api.schemas import TransferBase, TransferListResponse

router = APIRouter(prefix="/api/transfers", tags=["transfers"])


@router.get("", response_model=TransferListResponse)
async def list_transfers(
    club_id: Optional[int] = Query(None, description="Filter by club (buying or selling)"),
    position: Optional[str] = Query(None, description="Filter by player position"),
    min_roi: Optional[float] = Query(None, description="Minimum ROI percentage"),
    year_from: Optional[int] = Query(None, description="Start year"),
    year_to: Optional[int] = Query(None, description="End year"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(Transfer)

    if club_id:
        query = query.where(
            (Transfer.from_club_id == club_id) | (Transfer.to_club_id == club_id)
        )
    if position:
        query = query.where(Transfer.player_position == position)
    if min_roi is not None:
        query = query.where(Transfer.roi_pct >= min_roi)
    if year_from:
        query = query.where(func.extract("year", Transfer.transfer_date) >= year_from)
    if year_to:
        query = query.where(func.extract("year", Transfer.transfer_date) <= year_to)

    query = query.order_by(Transfer.transfer_date.desc().nullslast())

    total_q = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(total_q)
    total = total_result.scalar() or 0

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    transfers = result.scalars().all()

    return TransferListResponse(
        transfers=[TransferBase.model_validate(t) for t in transfers],
        total=total,
        page=page,
        per_page=per_page,
    )
