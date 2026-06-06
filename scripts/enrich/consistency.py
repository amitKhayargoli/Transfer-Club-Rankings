"""
Data consistency checks for enriched data.

Runs after enrichment to verify:
- Referential integrity (no orphaned rows)
- Temporal consistency (dates are ordered, no future dates)
- Numerical plausibility (fees, values within expected ranges)
- Deduplication (no duplicate transfers/valuations)
"""

import logging
from datetime import date, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Club, Player, Transfer, PlayerValuation

logger = logging.getLogger(__name__)

MAX_ANNUALIZED_ROI = 500.0  # Cap for annualized ROI
MAX_FEE_EUR = 500_000_000   # €500M sanity check
MAX_MARKET_VALUE_EUR = 300_000_000  # €300M sanity check
MAX_TENURE_YEARS = 20       # Max tenure for same club-player pair
MAX_ROI_PCT = 10_000.0      # ±10,000% ROI flag threshold
MIN_AGE_FOR_TRANSFER = 14   # Min age for a transfer to be plausible


class ConsistencyReport:
    """Tracks all consistency check results."""

    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.info: list[str] = []
        self.counts: dict[str, int] = {}

    def add_error(self, msg: str, category: str = "General"):
        self.errors.append(f"[{category}] {msg}")

    def add_warning(self, msg: str, category: str = "General"):
        self.warnings.append(f"[{category}] {msg}")

    def add_info(self, msg: str, category: str = "General"):
        self.info.append(f"[{category}] {msg}")

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        lines = [
            "=== DATA CONSISTENCY REPORT ===",
            "",
        ]
        for section, items in [
            ("Referential Integrity", self._ref_integrity_items()),
            ("Temporal Consistency", self._temporal_items()),
            ("Numerical Plausibility", self._numerical_items()),
            ("Deduplication", self._dedup_items()),
        ]:
            if items:
                lines.append(f"  {section}:")
                for item in items:
                    lines.append(f"    {item}")
                lines.append("")

        total_errors = len(self.errors)
        total_warnings = len(self.warnings)
        status = "PASS" if self.passed else "FAIL"
        lines.append(
            f"  Overall: {status} "
            f"({total_errors} errors, {total_warnings} warnings)"
        )
        return "\n".join(lines)

    def _ref_integrity_items(self) -> list[str]:
        items = []
        for e in self.errors:
            if "referential" in e.lower():
                items.append(f"ERROR: {e}")
        for w in self.warnings:
            if "referential" in w.lower():
                items.append(f"WARN: {w}")
        for i in self.info:
            if "referential" in i.lower():
                items.append(f"INFO: {i}")
        return items or ["(no issues)"]

    def _temporal_items(self) -> list[str]:
        items = []
        for e in self.errors:
            if "temporal" in e.lower() or "date" in e.lower():
                items.append(f"ERROR: {e}")
        for w in self.warnings:
            if "temporal" in w.lower() or "date" in w.lower():
                items.append(f"WARN: {w}")
        for i in self.info:
            if "temporal" in i.lower() or "date" in i.lower():
                items.append(f"INFO: {i}")
        return items or ["(no issues)"]

    def _numerical_items(self) -> list[str]:
        items = []
        for e in self.errors:
            if "numerical" in e.lower() or "fee" in e.lower() or "roi" in e.lower():
                items.append(f"ERROR: {e}")
        for w in self.warnings:
            if "numerical" in w.lower() or "fee" in w.lower() or "roi" in w.lower():
                items.append(f"WARN: {w}")
        for i in self.info:
            if "numerical" in i.lower() or "fee" in i.lower() or "roi" in i.lower():
                items.append(f"INFO: {i}")
        return items or ["(no issues)"]

    def _dedup_items(self) -> list[str]:
        items = []
        for e in self.errors:
            if "dup" in e.lower():
                items.append(f"ERROR: {e}")
        for i in self.info:
            if "dup" in i.lower():
                items.append(f"INFO: {i}")
        return items or ["(no issues)"]


async def run_consistency_checks(session: AsyncSession) -> ConsistencyReport:
    """Run all consistency checks and return a report."""
    report = ConsistencyReport()
    today = date.today()

    # ── 1. Referential Integrity ────────────────────────────────────────

    # Orphaned transfers
    orphaned_transfers = await session.execute(
        text("""
            SELECT COUNT(*) FROM transfers t
            LEFT JOIN players p ON t.player_id = p.player_id
            WHERE p.player_id IS NULL
        """)
    )
    orphaned_count = orphaned_transfers.scalar() or 0
    if orphaned_count:
        report.add_warning(
            f"{orphaned_count} transfers reference non-existent players"
        )
    else:
        report.add_info("0 orphaned transfers", category="Referential")

    # Orphaned valuations
    orphaned_vals = await session.execute(
        text("""
            SELECT COUNT(*) FROM player_valuations v
            LEFT JOIN players p ON v.player_id = p.player_id
            WHERE p.player_id IS NULL
        """)
    )
    orphaned_val_count = orphaned_vals.scalar() or 0
    if orphaned_val_count:
        report.add_warning(
            f"Referential: {orphaned_val_count} valuations reference non-existent players"
        )
    else:
        report.add_info("0 orphaned valuations", category="Referential")

    # Clubs referenced in players but not in clubs table
    missing_clubs = await session.execute(
        text("""
            SELECT COUNT(DISTINCT p.current_club_id) FROM players p
            LEFT JOIN clubs c ON p.current_club_id = c.club_id
            WHERE p.current_club_id IS NOT NULL AND c.club_id IS NULL
        """)
    )
    missing_club_count = missing_clubs.scalar() or 0
    if missing_club_count:
        report.add_warning(
            f"Referential: {missing_club_count} clubs referenced by players but not in clubs table"
        )
    else:
        report.add_info("all club references valid", category="Referential")

    # ── 2. Temporal Consistency ─────────────────────────────────────────

    # Future transfers
    future_transfers = await session.execute(
        text("SELECT COUNT(*) FROM transfers WHERE transfer_date > :today"),
        {"today": today},
    )
    future_count = future_transfers.scalar() or 0
    if future_count:
        report.add_warning(
            f"Temporal: {future_count} transfers have future dates (pre-arranged deals)"
        )
    else:
        report.add_info("0 future-dated transfers", category="Temporal")

    # Transfers before plausible age
    young_transfers = await session.execute(
        text(f"""
            SELECT COUNT(*) FROM transfers t
            JOIN players p ON t.player_id = p.player_id
            WHERE p.date_of_birth IS NOT NULL
              AND t.transfer_date IS NOT NULL
              AND t.transfer_date < date(p.date_of_birth, '+{MIN_AGE_FOR_TRANSFER} years')
        """)
    )
    young_count = young_transfers.scalar() or 0
    if young_count:
        report.add_warning(
            f"Temporal: {young_count} transfers occurred before age {MIN_AGE_FOR_TRANSFER}"
        )
    else:
        report.add_info(f"Temporal: no transfers before age {MIN_AGE_FOR_TRANSFER}")

    # ── 3. Numerical Plausibility ───────────────────────────────────────

    # Fees exceeding sanity threshold
    high_fees = await session.execute(
        text("SELECT COUNT(*) FROM transfers WHERE transfer_fee > :max_fee"),
        {"max_fee": MAX_FEE_EUR},
    )
    high_fee_count = high_fees.scalar() or 0
    if high_fee_count:
        report.add_warning(
            f"Numerical: {high_fee_count} transfers have fees > €{MAX_FEE_EUR:,}"
        )
    else:
        report.add_info(f"Numerical: no fees exceed €{MAX_FEE_EUR:,}")

    # Market values exceeding sanity threshold
    high_mv = await session.execute(
        text("SELECT COUNT(*) FROM players WHERE market_value_in_eur > :max_mv"),
        {"max_mv": MAX_MARKET_VALUE_EUR},
    )
    high_mv_count = high_mv.scalar() or 0
    if high_mv_count:
        report.add_warning(
            f"Numerical: {high_mv_count} players have market value > €{MAX_MARKET_VALUE_EUR:,}"
        )
    else:
        report.add_info(f"Numerical: no market values exceed €{MAX_MARKET_VALUE_EUR:,}")

    # Extreme ROI values
    high_roi = await session.execute(
        text("""
            SELECT COUNT(*) FROM transfers
            WHERE roi_pct IS NOT NULL AND ABS(roi_pct) > :max_roi
        """),
        {"max_roi": MAX_ROI_PCT},
    )
    high_roi_count = high_roi.scalar() or 0
    if high_roi_count:
        report.add_warning(
            f"Numerical: {high_roi_count} transfers have ROI > ±{MAX_ROI_PCT:,.0f}%"
        )
    else:
        report.add_info(f"Numerical: no ROI values exceed ±{MAX_ROI_PCT:,.0f}%")

    # ── 4. Deduplication ────────────────────────────────────────────────

    # Duplicate transfers (same composite key)
    dup_transfers = await session.execute(
        text("""
            SELECT COUNT(*) FROM (
                SELECT player_id, from_club_id, to_club_id, transfer_date, COUNT(*)
                FROM transfers
                WHERE player_id IS NOT NULL
                GROUP BY player_id, from_club_id, to_club_id, transfer_date
                HAVING COUNT(*) > 1
            ) dups
        """)
    )
    dup_transfer_count = dup_transfers.scalar() or 0
    if dup_transfer_count:
        report.add_error(
            f"Dedup: {dup_transfer_count} duplicate transfer groups found"
        )
    else:
        report.add_info("no duplicate transfers detected", category="Dedup")

    # Duplicate valuations
    dup_vals = await session.execute(
        text("""
            SELECT COUNT(*) FROM (
                SELECT player_id, date, market_value_in_eur, COUNT(*)
                FROM player_valuations
                WHERE player_id IS NOT NULL AND date IS NOT NULL
                GROUP BY player_id, date, market_value_in_eur
                HAVING COUNT(*) > 1
            ) dups
        """)
    )
    dup_val_count = dup_vals.scalar() or 0
    if dup_val_count:
        report.add_warning(
            f"Dedup: {dup_val_count} duplicate valuation groups found"
        )
    else:
        report.add_info("no duplicate valuations detected", category="Dedup")

    return report
