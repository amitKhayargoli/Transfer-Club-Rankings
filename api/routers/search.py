"""
Unified search endpoint.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, literal_column
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

    # Search clubs (separate query - SQLite doesn't support UNION with LIMIT)
    club_q = select(
        literal_column("'club'").label("type"),
        Club.club_id.label("id"),
        Club.name.label("name"),
        Club.domestic_competition_id.label("subtitle"),
    ).where(Club.name.ilike(pattern)).limit(limit)

    club_result = await db.execute(club_q)
    club_rows = club_result.all()

    # Search players (separate query)
    player_q = select(
        literal_column("'player'").label("type"),
        Player.player_id.label("id"),
        Player.name.label("name"),
        Player.position.label("subtitle"),
    ).where(Player.name.ilike(pattern)).limit(limit)

    player_result = await db.execute(player_q)
    player_rows = player_result.all()

    # Combine and limit results
    rows = (club_rows + player_rows)[:limit]

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
