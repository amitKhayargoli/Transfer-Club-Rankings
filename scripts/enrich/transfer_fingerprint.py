"""
Transfer Fingerprint System — robust identity resolution for transfer graph edges.

Replaces the fragile composite key (from_club_id, to_club_id, date) with
a multi-signal fingerprint that handles:
- NULL club IDs (fall back to club names)
- Date normalization (season-aware, not raw date only)
- Fee bucket normalization (avoid false non-matches on currency rounding)
- Optional Transfermarkt internal ID (if available from API)

Usage:
    fp = TransferFingerprint.from_api_transfer(transfer_dict, player_id)
    match = fp.matches(other_fp)  # returns 0.0-1.0 match confidence
    hash = fp.compute_hash()       # deterministic unique key
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Fee bucket boundaries (in EUR)
FEE_BUCKETS = [
    (0, "free"),
    (100_000, "micro"),
    (500_000, "small"),
    (1_000_000, "low"),
    (5_000_000, "mid_low"),
    (10_000_000, "mid"),
    (25_000_000, "mid_high"),
    (50_000_000, "high"),
    (100_000_000, "very_high"),
]


def _fee_bucket(fee: Any) -> str:
    """Assign a transfer fee to a discrete bucket.

    Handles string fees from API responses ('100000000') and numeric types.
    """
    if fee is None:
        return "unknown"
    try:
        fee_val = float(fee) if not isinstance(fee, (int, float)) else float(fee)
    except (ValueError, TypeError):
        return "unknown"
    for threshold, label in sorted(FEE_BUCKETS, key=lambda x: x[0]):
        if threshold == 0 and fee_val == 0:
            return label
        if fee_val < threshold:
            return label
    return "elite"


def _normalize_club_id(club_id: Any) -> int | None:
    """Normalize a club ID to int or None."""
    if club_id is None:
        return None
    try:
        return int(club_id)
    except (ValueError, TypeError):
        return None


def _normalize_club_name(name: Any) -> str | None:
    """Normalize a club name — strip, lowercase, remove common prefixes."""
    if not name:
        return None
    cleaned = str(name).strip().lower()
    # Remove common prefixes that cause false non-matches
    for prefix in ["fc ", "f.c. ", "club ", "a.f.c. ", "sc ", "sv ", "bv ", "tsv ", "vfl "]:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    return cleaned


def _season_from_date(d: date | None) -> str | None:
    """Convert a date to a season string (e.g. '2023-2024')."""
    if d is None:
        return None
    if d.month >= 7:  # July cutoff for season boundary
        return f"{d.year}-{d.year + 1}"
    return f"{d.year - 1}-{d.year}"


def _normalize_date(d: date | str | None) -> date | None:
    """Normalize a date to a date object."""
    if d is None:
        return None
    if isinstance(d, date):
        return d
    if isinstance(d, str):
        from scripts.enrich.player_enricher import _parse_transfermarkt_date
        return _parse_transfermarkt_date(d)
    return None


@dataclass(frozen=True)
class TransferFingerprint:
    """Immutable fingerprint for a transfer edge.

    Combines multiple signals into a single identity that can be matched
    across API responses and database records, even when individual fields
    differ slightly.
    """
    player_id: int
    from_club_id: int | None
    to_club_id: int | None
    from_club_name: str | None
    to_club_name: str | None
    transfer_season: str | None
    transfer_date: date | None
    fee_bucket: str
    fee_exact: float | None
    transfermarkt_id: str | None  # Transfermarkt internal ID (if available)

    @classmethod
    def from_api_transfer(cls, transfer_dict: dict, player_id: int) -> "TransferFingerprint":
        """Create a fingerprint from a Transfermarkt API transfer dict."""
        club_from = transfer_dict.get("clubFrom", {})
        club_to = transfer_dict.get("clubTo", {})

        from_id = _normalize_club_id(club_from.get("id"))
        to_id = _normalize_club_id(club_to.get("id"))

        raw_date = transfer_dict.get("date")
        parsed_date = _normalize_date(raw_date)

        # Try to extract Transfermarkt transfer ID if available
        tm_id = transfer_dict.get("id") or transfer_dict.get("transferId") or None
        if tm_id is not None:
            tm_id = str(tm_id)

        return cls(
            player_id=player_id,
            from_club_id=from_id,
            to_club_id=to_id,
            from_club_name=_normalize_club_name(club_from.get("name")),
            to_club_name=_normalize_club_name(club_to.get("name")),
            transfer_season=transfer_dict.get("season") or _season_from_date(parsed_date),
            transfer_date=parsed_date,
            fee_bucket=_fee_bucket(transfer_dict.get("fee")),
            fee_exact=transfer_dict.get("fee"),
            transfermarkt_id=tm_id,
        )

    @classmethod
    def from_db_transfer(cls, row: tuple) -> "TransferFingerprint":
        """Create a fingerprint from a DB transfers row.

        Args:
            row: Tuple from DB query:
                (player_id, from_club_id, to_club_id, from_club_name, to_club_name,
                 transfer_date, transfer_season, transfer_fee)
        """
        (player_id, from_id, to_id, from_name, to_name,
         t_date, t_season, t_fee) = row[:8]

        return cls(
            player_id=int(player_id),
            from_club_id=_normalize_club_id(from_id),
            to_club_id=_normalize_club_id(to_id),
            from_club_name=_normalize_club_name(from_name),
            to_club_name=_normalize_club_name(to_name),
            transfer_season=t_season,
            transfer_date=_normalize_date(t_date),
            fee_bucket=_fee_bucket(t_fee),
            fee_exact=t_fee,
            transfermarkt_id=None,  # DB doesn't store Transfermarkt IDs yet
        )

    def compute_hash(self) -> str:
        """Deterministic hash for exact dedup.

        Uses the most reliable available signals: Transfermarkt ID if available,
        otherwise the composite key with fee bucket normalization.
        """
        if self.transfermarkt_id:
            raw = f"tm:{self.player_id}:{self.transfermarkt_id}"
        else:
            raw = (
                f"composite:{self.player_id}:{self.from_club_id or 'nil'}:"
                f"{self.to_club_id or 'nil'}:{self.transfer_season or 'noseason'}:"
                f"{self.fee_bucket}"
            )
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def matches(self, other: "TransferFingerprint", min_confidence: float = 0.85) -> tuple[bool, float, list[str]]:
        """Compare two fingerprints and determine if they represent the same transfer.

        Returns:
            (is_match, confidence_score, reasons)
        """
        reasons = []

        # Perfect match via Transfermarkt ID
        if self.transfermarkt_id and other.transfermarkt_id:
            if self.transfermarkt_id == other.transfermarkt_id:
                return True, 1.0, ["exact_transfermarkt_id"]

        # Must have same player
        if self.player_id != other.player_id:
            return False, 0.0, ["different_players"]

        score = 0.0
        total_weight = 0.0

        # 1. Club IDs (highest weight)
        if self.from_club_id is not None and other.from_club_id is not None:
            if self.from_club_id == other.from_club_id:
                score += 0.35
                reasons.append("from_club_id_match")
            total_weight += 0.35
        elif self.from_club_name and other.from_club_name:
            if self.from_club_name == other.from_club_name:
                score += 0.25
                reasons.append("from_club_name_match")
            total_weight += 0.25

        if self.to_club_id is not None and other.to_club_id is not None:
            if self.to_club_id == other.to_club_id:
                score += 0.35
                reasons.append("to_club_id_match")
            total_weight += 0.35
        elif self.to_club_name and other.to_club_name:
            if self.to_club_name == other.to_club_name:
                score += 0.25
                reasons.append("to_club_name_match")
            total_weight += 0.25

        # 2. Season (medium weight)
        if self.transfer_season and other.transfer_season:
            if self.transfer_season == other.transfer_season:
                score += 0.15
                reasons.append("season_match")
            total_weight += 0.15

        # 3. Fee bucket (lower weight)
        if self.fee_bucket == other.fee_bucket:
            score += 0.15
            reasons.append(f"fee_bucket_match:{self.fee_bucket}")
        total_weight += 0.15

        # Normalize score to 0-1
        normalized = score / total_weight if total_weight > 0 else 0.0
        is_match = normalized >= min_confidence

        return is_match, round(normalized, 3), reasons

    def to_insert_dict(self) -> dict:
        """Convert to dict for DB insertion with fingerprint metadata."""
        return {
            "fingerprint_hash": self.compute_hash(),
            "confidence_score": None,  # Set by confidence_scorer
            "confidence_reasons": [],
        }


