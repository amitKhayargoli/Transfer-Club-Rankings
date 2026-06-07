"""
SQLAlchemy ORM models for Transfer ROI Rankings.

Mirrors the PostgreSQL schema defined in the web-app-spec.md.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from api.database import Base


class Club(Base):
    __tablename__ = "clubs"

    club_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    club_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    domestic_competition_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Aggregated metrics (populated after pipeline runs)
    total_transfers: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    median_roi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    annualized_roi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hit_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value_creation: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    profit_per_deal: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    buying_club_premium: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    composite_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ClubMetricsWindow(Base):
    """Precomputed club metrics for specific year windows.

    This allows the dashboard to switch between different analytical boundaries
    (e.g. 2010+ for legacy BVB deals, 2015+ for modern era, 2018+ for Brighton era)
    without recomputing on the fly.
    """
    __tablename__ = "club_metrics_windows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    club_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    window_key: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "2010", "2015", "2018"

    # Same metric fields as Club model
    total_transfers: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    median_roi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    annualized_roi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hit_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value_creation: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    profit_per_deal: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    buying_club_premium: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    composite_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Player(Base):
    __tablename__ = "players"

    player_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    first_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    position: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sub_position: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    current_club_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    current_club_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    foot: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    height_in_cm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_value_in_eur: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    highest_market_value_in_eur: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # New enrichment fields for scouting pipeline analysis
    citizenship: Mapped[Optional[str]] = mapped_column(String, nullable=True, comment="Comma-separated list of nationalities")
    agent_name: Mapped[Optional[str]] = mapped_column(String, nullable=True, comment="Agent representing the player")
    contract_expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, comment="Contract expiry at current club")
    image_url: Mapped[Optional[str]] = mapped_column(String, nullable=True, comment="Player photo URL from Transfermarkt")




class Transfer(Base):
    __tablename__ = "transfers"

    transfer_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(Integer, nullable=False)
    player_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    from_club_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    to_club_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    from_club_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    to_club_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    transfer_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    transfer_season: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    transfer_fee: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_value_in_eur: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Computed buy-sell pair fields
    buy_fee: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sell_fee: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    roi_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    annualized_roi_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tenure_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tenure_years: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    peak_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value_creation_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    player_position: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    age_at_transfer: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Graph Truth Engine fields
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Confidence score for reconstructed transfers (0.0-1.0)")
    fingerprint_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True, comment="Deterministic fingerprint for dedup resolution")
    confidence_reasons: Mapped[Optional[str]] = mapped_column(String, nullable=True, comment="JSON-serialized list of confidence reason strings")



class Competition(Base):
    """Competition/league metadata from the davidcariboo dataset.

    Used to assign league tiers for the hidden gem model.
    """
    __tablename__ = "competitions"

    competition_id: Mapped[str] = mapped_column(String, primary_key=True)
    competition_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sub_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    country_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    country_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    domestic_league_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    confederation: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    total_clubs: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class Appearance(Base):
    """Per-game appearance stats from the davidcariboo/player data dataset.

    One row per player per game. Contains performance metrics like
    goals, assists, minutes_played that power the hidden gem model.
    """
    __tablename__ = "appearances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    appearance_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    game_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    player_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    player_club_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    player_current_club_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    player_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    competition_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    yellow_cards: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    red_cards: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    goals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    assists: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    minutes_played: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class PlayerValuation(Base):
    __tablename__ = "player_valuations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(Integer, nullable=False)
    date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    market_value_in_eur: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_club_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    current_club_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    player_club_domestic_competition_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)


