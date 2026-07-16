"""
Pydantic schemas for API request/response serialization.
"""

import datetime
from typing import Optional

from pydantic import BaseModel


# ── Club Schemas ────────────────────────────────────────────────────────────

class ClubBase(BaseModel):
    club_id: int
    name: str
    club_code: Optional[str] = None
    domestic_competition_id: Optional[str] = None
    total_transfers: Optional[int] = None
    median_roi: Optional[float] = None
    annualized_roi: Optional[float] = None
    total_profit: Optional[float] = None
    hit_rate: Optional[float] = None
    value_creation: Optional[float] = None
    profit_per_deal: Optional[float] = None
    buying_club_premium: Optional[float] = None
    composite_score: Optional[float] = None

    model_config = {"from_attributes": True}


class ClubListResponse(BaseModel):
    clubs: list[ClubBase]
    total: int
    page: int
    per_page: int


class ClubDetailResponse(ClubBase):
    league_name: Optional[str] = None
    league_logo_url: Optional[str] = None
    top_sale: Optional["TransferBase"] = None


class ClubCompareResponse(BaseModel):
    club1: ClubDetailResponse
    club2: ClubDetailResponse


# ── Player Schemas ──────────────────────────────────────────────────────────

class PlayerBase(BaseModel):
    player_id: int
    name: str
    position: Optional[str] = None
    date_of_birth: Optional[datetime.date] = None
    current_club_id: Optional[int] = None
    current_club_name: Optional[str] = None
    market_value_in_eur: Optional[float] = None
    image_url: Optional[str] = None

    model_config = {"from_attributes": True}


class PlayerDetailResponse(PlayerBase):
    foot: Optional[str] = None
    height_in_cm: Optional[float] = None
    highest_market_value_in_eur: Optional[float] = None
    citizenship: Optional[str] = None
    agent_name: Optional[str] = None
    contract_expiry_date: Optional[datetime.date] = None


class PlayerListResponse(BaseModel):
    players: list[PlayerBase]
    total: int
    page: int
    per_page: int


# ── Transfer Schemas ────────────────────────────────────────────────────────

class TransferBase(BaseModel):
    transfer_id: int
    player_id: int
    player_name: Optional[str] = None
    from_club_id: Optional[int] = None
    to_club_id: Optional[int] = None
    from_club_name: Optional[str] = None
    to_club_name: Optional[str] = None
    transfer_date: Optional[datetime.date] = None
    transfer_fee: Optional[float] = None
    buy_fee: Optional[float] = None
    sell_fee: Optional[float] = None
    profit: Optional[float] = None
    roi_pct: Optional[float] = None
    annualized_roi_pct: Optional[float] = None
    tenure_years: Optional[float] = None
    player_position: Optional[str] = None
    transfer_type: Optional[str] = None
    age_at_transfer: Optional[float] = None

    model_config = {"from_attributes": True}


class TransferListResponse(BaseModel):
    transfers: list[TransferBase]
    total: int
    page: int
    per_page: int


# ── Player Valuation Schemas ────────────────────────────────────────────────

class PlayerValuationBase(BaseModel):
    date: Optional[datetime.date] = None
    market_value_in_eur: Optional[float] = None

    model_config = {"from_attributes": True}


# ── Dashboard Schemas ───────────────────────────────────────────────────────

class DashboardStatsResponse(BaseModel):
    total_transfers: int
    total_clubs: int
    total_profit: float
    biggest_profit_transfer: Optional[TransferBase] = None


class TopClubResponse(BaseModel):
    club: ClubBase
    rank: int


class DashboardTopClubsResponse(BaseModel):
    top_clubs: list[TopClubResponse]


# ── Search Schemas ──────────────────────────────────────────────────────────

class SearchResult(BaseModel):
    type: str  # "club" or "player"
    id: int
    name: str
    subtitle: Optional[str] = None  # league name for clubs, position for players


class SearchResponse(BaseModel):
    results: list[SearchResult]


# ── Window Metrics Schema ──────────────────────────────────────────────────

class ClubWindowMetrics(BaseModel):
    club_id: int
    window_key: str
    total_transfers: Optional[int] = None
    median_roi: Optional[float] = None
    total_profit: Optional[float] = None
    hit_rate: Optional[float] = None
    value_creation: Optional[float] = None
    composite_score: Optional[float] = None
    last_updated: Optional[datetime.datetime] = None

    model_config = {"from_attributes": True}


class ClubWindowMetricsResponse(BaseModel):
    clubs: list[ClubWindowMetrics]
    total: int
    page: int
    per_page: int


# ── Pipeline Schemas ────────────────────────────────────────────────────────

class PipelineRunResponse(BaseModel):
    status: str
    message: str
    clubs_loaded: int
    players_loaded: int
    transfers_loaded: int
    valuations_loaded: int
    pairs_computed: int = 0
    clubs_updated: int = 0


class PipelineStatusResponse(BaseModel):
    data_loaded: bool
    last_refresh: Optional[str] = None
    total_clubs: int
    total_players: int
    total_transfers: int
