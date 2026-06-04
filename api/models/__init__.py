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



class PlayerValuation(Base):
    __tablename__ = "player_valuations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(Integer, nullable=False)
    date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    market_value_in_eur: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_club_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    current_club_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    player_club_domestic_competition_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)


