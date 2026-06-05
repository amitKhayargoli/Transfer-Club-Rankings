"""
Unified search endpoint.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, union, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import Club, Player
from api.schemas import SearchResponse, SearchResult

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=SearchResponse)
async def unified_search(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    pattern = f"%{q}%"

    # Search clubs
    club_q = select(
        literal_column("'club'").label("type"),
        Club.club_id.label("id"),
        Club.name.label("name"),
        Club.domestic_competition_id.label("subtitle"),
    ).where(Club.name.ilike(pattern)).limit(limit)

    # Search players
    player_q = select(
        literal_column("'player'").label("type"),
        Player.player_id.label("id"),
        Player.name.label("name"),
        Player.position.label("subtitle"),
    ).where(Player.name.ilike(pattern)).limit(limit)

    union_q = union(club_q, player_q).limit(limit)
    result = await db.execute(union_q)
    rows = result.all()

    return SearchResponse(
        results=[
            SearchResult(
                type=row.type,
                id=row.id,
                name=row.name,
                subtitle=row.subtitle,
            )
            for row in rows
        ]
    )
