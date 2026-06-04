"""
Utility functions for classifying transfer types.
"""

import re
from collections import defaultdict
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Transfer
from api.schemas import TransferBase


# Patterns that indicate a club is a reserve/youth team
RESERVE_PATTERNS = [
    r"\bu19\b", r"\bu21\b", r"\bu23\b", r"\bu18\b", r"\bu20\b",
    r"\bII$", r"\bB$", r"\bB[\s_]", r"\bReservas\b",
    r"\bYouth\b", r"\bJong\b", r"\bJunior\b",
    r"\bUtd?\s*B$", r"\bFC\s*B$",
]


def classify_transfer(t: TransferBase) -> str:
    """Determine the type of a transfer from its data.

    Returns one of: "paid", "contract_expired", "retired",
                    "youth_promotion", "free_transfer", "loan_return"
    """
    # Paid transfers — always a "paid transfer"
    if t.transfer_fee and t.transfer_fee > 0:
        return "paid"

    to_name = (t.to_club_name or "").strip()
    from_name = (t.from_club_name or "").strip()

    # Retired / contract expired
    if to_name.lower() == "retired":
        return "retired"
    if to_name.lower() == "without club":
        return "contract_expired"

    # Youth / reserve promotion
    for pattern in RESERVE_PATTERNS:
        if re.search(pattern, from_name, re.IGNORECASE):
            return "youth_promotion"
        if re.search(pattern, to_name, re.IGNORECASE):
            return "sent_to_reserves"

    # Default for €0 / no-fee transfers
    return "free_transfer"


def detect_loans(
    transfers: list[Transfer],
    player_transfers: dict[int, list[Transfer]] | None = None,
) -> set[int]:
    """Identify loan transfers by finding paired transfers with swapped clubs within ~2 years.

    Returns a set of transfer_ids that are likely loan deals.
    """
    if player_transfers is None:
        player_transfers = defaultdict(list)
        for t in transfers:
            player_transfers[t.player_id].append(t)

    loan_ids: set[int] = set()

    for t in transfers:
        if (
            not t.from_club_id
            or not t.to_club_id
            or not t.transfer_date
            or (t.transfer_fee and t.transfer_fee > 0)
        ):
            continue
        # Look for another transfer for the same player where clubs are swapped
        for other in player_transfers.get(t.player_id, []):
            if (
                other.transfer_id != t.transfer_id
                and other.from_club_id == t.to_club_id
                and other.to_club_id == t.from_club_id
                and other.transfer_date is not None
                # Both sides should be fee-free to avoid matching a loan return
                # with a permanent paid transfer
                and (not other.transfer_fee or other.transfer_fee == 0)
            ):
                # Check the transfers are within ~2 years of each other (typical loan duration)
                day_diff = abs((t.transfer_date - other.transfer_date).days)
                if day_diff <= 730:
                    loan_ids.add(t.transfer_id)
                    loan_ids.add(other.transfer_id)
                    break

    return loan_ids


async def enrich_transfer_types(
    transfers: list[Transfer],
    club_id: Optional[int] = None,
    db: Optional[AsyncSession] = None,
) -> list[TransferBase]:
    """Convert a list of Transfer ORM objects to TransferBase Pydantic models
    with transfer_type and (for club pages) propagated profit on sell side.
    """
    # Build buy map for profit propagation (club detail page)
    buys_by_player: dict[int, list[Transfer]] = defaultdict(list)
    if club_id and db:
        buy_query = select(Transfer).where(
            (Transfer.to_club_id == club_id)
            & (Transfer.transfer_fee.isnot(None))
            & (Transfer.transfer_fee > 0)
        ).order_by(Transfer.transfer_date.desc())
        buy_result = await db.execute(buy_query)
        for b in buy_result.scalars().all():
            buys_by_player[b.player_id].append(b)

    # Build a map of player_id -> list of transfers for loan detection
    player_transfers: dict[int, list[Transfer]] = defaultdict(list)
    for t in transfers:
        player_transfers[t.player_id].append(t)

    # Identify loan transfer IDs
    loan_ids = detect_loans(transfers, player_transfers)

    result = []
    for t in transfers:
        data = TransferBase.model_validate(t)

        # Classify transfer type (loan detection overrides free_transfer)
        base_type = classify_transfer(data)
        if base_type == "free_transfer" and t.transfer_id in loan_ids:
            data.transfer_type = "loan"
        else:
            data.transfer_type = base_type

        # For club detail: propagate profit to sell transfers
        if club_id and t.from_club_id == club_id and data.profit is None:
            if t.transfer_fee and t.transfer_fee > 0:
                for buy in buys_by_player.get(t.player_id, []):
                    if (
                        buy.transfer_date
                        and t.transfer_date
                        and t.transfer_date > buy.transfer_date
                        and buy.profit is not None
                    ):
                        data.buy_fee = buy.buy_fee
                        data.sell_fee = buy.sell_fee
                        data.profit = buy.profit
                        data.roi_pct = buy.roi_pct
                        data.annualized_roi_pct = buy.annualized_roi_pct
                        data.player_position = buy.player_position
                        break

        result.append(data)

    return result
