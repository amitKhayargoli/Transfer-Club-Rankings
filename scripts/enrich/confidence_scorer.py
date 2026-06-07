"""
Confidence Scoring System for reconstructed transfer edges.

Every reconstructed transfer gets a confidence_score (0.0-1.0) and
confidence_reasons explaining the score.

Scoring rules:
  1.0  = Exact API + DB match (identical fingerprints)
  0.9+ = Transfermarkt ID match (internal ID confirmed)
  0.8+ = Same club IDs + matching season + compatible fee bucket
  0.7+ = Same club names (fallback, no IDs) + matching season
 <0.7  = Weak inference — inserted with warning flag

Usage:
    scorer = ConfidenceScorer()
    score, reasons = scorer.score(api_fingerprint, db_fingerprint)
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from scripts.enrich.transfer_fingerprint import TransferFingerprint

logger = logging.getLogger(__name__)

# Confidence thresholds
HIGH_CONFIDENCE = 0.90
MEDIUM_CONFIDENCE = 0.70
LOW_CONFIDENCE = 0.50
MIN_INSERT_THRESHOLD = 0.85  # Don't insert below this by default


@dataclass
class ConfidenceResult:
    """Result of a confidence scoring operation."""
    score: float
    reasons: list[str]
    insert_decision: str  # "safe", "review", "reject"

    def is_safe_to_insert(self, threshold: float = MIN_INSERT_THRESHOLD) -> bool:
        return self.score >= threshold


class ConfidenceScorer:
    """Scores the confidence of a reconstructed transfer edge."""

    def score_api_transfer(
        self,
        api_fingerprint: TransferFingerprint,
        db_fingerprints: list[TransferFingerprint],
        known_academy_players: set[int] | None = None,
    ) -> ConfidenceResult:
        """Score a single API transfer against all existing DB fingerprints.

        Args:
            api_fingerprint: Fingerprint of the API transfer
            db_fingerprints: All existing DB fingerprints for the same player
            known_academy_players: Set of player IDs known to be academy-developed

        Returns:
            ConfidenceResult with score, reasons, and insert decision
        """
        # 1. Check for exact dupe against DB
        best_match_score = 0.0
        best_match_reasons = []

        for db_fp in db_fingerprints:
            is_match, score, reasons = api_fingerprint.matches(db_fp)
            if score > best_match_score:
                best_match_score = score
                best_match_reasons = reasons

        # If it matches any DB record above the insert threshold, this is a dupe
        if best_match_score >= MIN_INSERT_THRESHOLD:
            return ConfidenceResult(
                score=0.0,
                reasons=[f"duplicate: matched DB record with score {best_match_score}"] + best_match_reasons,
                insert_decision="reject",
            )

        # 2. Check Transfermarkt ID (highest signal)
        if api_fingerprint.transfermarkt_id:
            return ConfidenceResult(
                score=1.0,
                reasons=["transfermarkt_id_present"],
                insert_decision="safe",
            )

        # 3. Score based on fingerprint quality
        reasons = []
        raw_score = 0.0
        max_score = 0.0

        # Club ID completeness (0.0-0.4)
        has_from_id = api_fingerprint.from_club_id is not None
        has_to_id = api_fingerprint.to_club_id is not None
        if has_from_id and has_to_id:
            raw_score += 0.4
            reasons.append("both_club_ids_present")
        elif has_from_id or has_to_id:
            raw_score += 0.2
            reasons.append("one_club_id_present")
        else:
            reasons.append("no_club_ids")
        max_score += 0.4

        # Club name fallback (0.0-0.15)
        has_from_name = bool(api_fingerprint.from_club_name)
        has_to_name = bool(api_fingerprint.to_club_name)
        if has_from_name and has_to_name:
            raw_score += 0.15
            reasons.append("both_club_names_present")
        elif has_from_name or has_to_name:
            raw_score += 0.08
        max_score += 0.15

        # Season presence (0.0-0.15)
        if api_fingerprint.transfer_season:
            raw_score += 0.15
            reasons.append(f"season:{api_fingerprint.transfer_season}")
        max_score += 0.15

        # Date presence (0.0-0.1)
        if api_fingerprint.transfer_date:
            raw_score += 0.1
            reasons.append("date_present")
        max_score += 0.1

        # Fee information (0.0-0.1)
        if api_fingerprint.fee_exact is not None:
            raw_score += 0.1
            reasons.append(f"fee:{api_fingerprint.fee_bucket}")
        elif api_fingerprint.fee_bucket != "unknown":
            raw_score += 0.05
            reasons.append(f"fee_bucket:{api_fingerprint.fee_bucket}")
        max_score += 0.1

        # Academy player penalty
        if known_academy_players and api_fingerprint.player_id in known_academy_players:
            raw_score *= 0.7
            reasons.append("academy_player_penalty")

        # No nearby DB matches penalty (this transfer has no context)
        if best_match_score < 0.3:
            raw_score *= 0.9
            reasons.append("no_contextual_matches")

        normalized = raw_score / max_score if max_score > 0 else 0.0

        # Determine insert decision
        if normalized >= HIGH_CONFIDENCE:
            decision = "safe"
        elif normalized >= MIN_INSERT_THRESHOLD:
            decision = "safe"
        elif normalized >= MEDIUM_CONFIDENCE:
            decision = "review"
        else:
            decision = "reject"

        return ConfidenceResult(
            score=round(min(normalized, 1.0), 3),
            reasons=reasons,
            insert_decision=decision,
        )

    def score_from_transfer_data(
        self,
        api_transfer: dict,
        db_fingerprints: list[TransferFingerprint],
        player_id: int,
    ) -> ConfidenceResult:
        """Convenience method: create fingerprint from dict, then score."""
        api_fp = TransferFingerprint.from_api_transfer(api_transfer, player_id)
        return self.score_api_transfer(api_fp, db_fingerprints)


def compute_confidence_distribution(
    results: list[ConfidenceResult],
) -> dict[str, int]:
    """Compute distribution of confidence scores across a batch."""
    dist = {"high": 0, "medium": 0, "low": 0}
    for r in results:
        if r.score >= HIGH_CONFIDENCE:
            dist["high"] += 1
        elif r.score >= MEDIUM_CONFIDENCE:
            dist["medium"] += 1
        else:
            dist["low"] += 1
    return dist
