"""
Graph Validation Layer.

Validates the integrity of the football transfer graph after reconstruction.
Detects broken edges, timeline violations, and produces a graph_health_score.

Usage:
    report = await validate_transfer_graph(session)
    print(report["graph_health_score"])
    print(report["broken_players"][:5])
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class GraphValidationReport:
    """Complete validation report for the transfer graph."""
    total_players: int = 0
    total_edges: int = 0
    broken_players: list[dict] = field(default_factory=list)
    timeline_violations: list[dict] = field(default_factory=list)
    disconnected_segments: list[dict] = field(default_factory=list)
    orphan_edges: list[dict] = field(default_factory=list)
    duplicate_edges: list[dict] = field(default_factory=list)
    missing_continuity: int = 0
    graph_health_score: float = 1.0

    def summary(self) -> str:
        """Human-readable summary of the report."""
        lines = [
            "Graph Validation Report",
            "=" * 60,
            f"  Players analyzed:    {self.total_players}",
            f"  Total edges:         {self.total_edges}",
            f"  Graph health score:  {self.graph_health_score:.2f} / 1.00",
            "",
            "  Issues found:",
            f"    Timeline violations:    {len(self.timeline_violations)}",
            f"    Disconnected segments:  {len(self.disconnected_segments)}",
            f"    Orphan edges:           {len(self.orphan_edges)}",
            f"    Duplicate edges:        {len(self.duplicate_edges)}",
            f"    Missing continuity:     {self.missing_continuity}",
        ]
        return "\n".join(lines)


async def validate_transfer_graph(
    session: AsyncSession,
    max_broken_samples: int = 20,
) -> GraphValidationReport:
    """Run comprehensive validation on the transfer graph.

    Detects:
    - Timeline violations: sell recorded before buy (back-in-time)
    - Disconnected segments: player's career chain has gaps
    - Orphan edges: transfers where origin club isn't in clubs table
    - Duplicate edges: same (player, from, to, date) appearing 2+ times
    - Missing continuity: player career starts from nowhere

    Returns:
        GraphValidationReport with health score (0.0–1.0)
    """
    report = GraphValidationReport()

    # Count totals
    result = await session.execute(text("SELECT COUNT(*) FROM transfers"))
    report.total_edges = result.scalar() or 0

    result = await session.execute(text("SELECT COUNT(*) FROM players"))
    report.total_players = result.scalar() or 0

    # 1. Timeline violations (sell BEFORE buy — impossible order)
    #    t1 = a transfer FROM a club (sell), t2 = a transfer TO that same club (buy)
    #    If t1.date < t2.date, the club sold the player before they bought them.
    result = await session.execute(text(f"""
        SELECT t1.player_id, p.name,
               t1.from_club_id as sell_club_id,
               fc.name as sell_club_name,
               t1.transfer_date as sell_date,
               t2.transfer_date as buy_date,
               ROUND(t1.transfer_fee, 0) as sell_fee
        FROM transfers t1
        JOIN players p ON t1.player_id = p.player_id
        JOIN transfers t2 ON t1.player_id = t2.player_id
            AND t1.from_club_id = t2.to_club_id
            AND t1.transfer_date < t2.transfer_date
        LEFT JOIN clubs fc ON t1.from_club_id = fc.club_id
        WHERE t1.transfer_fee > 100000
           OR t2.transfer_fee > 100000
        ORDER BY (t1.transfer_fee + t2.transfer_fee) DESC
        LIMIT {max_broken_samples}
    """))
    for r in result:
        report.timeline_violations.append({
            "player_id": r[0],
            "player_name": r[1],
            "sell_club_id": r[2],
            "sell_club_name": r[3],
            "sell_date": str(r[4]),
            "buy_date": str(r[5]),
            "sell_fee": r[6],
            "type": "sell_before_buy",
        })

    # 2. Disconnected segments (player has career chain break)
    result = await session.execute(text(f"""
        WITH ordered AS (
            SELECT player_id, from_club_id, to_club_id, transfer_date,
                   LAG(to_club_id) OVER (
                       PARTITION BY player_id ORDER BY transfer_date
                   ) as prev_to_club
            FROM transfers
            WHERE player_id IN (
                SELECT player_id FROM transfers
                GROUP BY player_id HAVING COUNT(*) >= 3
            )
        )
        SELECT player_id, COUNT(*) as breaks
        FROM ordered
        WHERE prev_to_club IS NOT NULL
          AND prev_to_club != from_club_id
        GROUP BY player_id
        HAVING COUNT(*) >= 1
        ORDER BY COUNT(*) DESC
        LIMIT {max_broken_samples}
    """))
    for r in result:
        report.disconnected_segments.append({
            "player_id": r[0],
            "breaks": r[1],
        })

    # 3. Orphan edges (from_club_id not in clubs table)
    result = await session.execute(text(f"""
        SELECT t.player_id, p.name,
               t.from_club_id, t.from_club_name,
               COUNT(*) as occurrences,
               ROUND(MAX(t.transfer_fee), 0) as max_fee
        FROM transfers t
        JOIN players p ON t.player_id = p.player_id
        WHERE t.from_club_id IS NOT NULL
          AND t.from_club_id NOT IN (
              SELECT club_id FROM clubs WHERE club_id IS NOT NULL
          )
        GROUP BY t.player_id
        ORDER BY MAX(t.transfer_fee) DESC NULLS LAST
        LIMIT {max_broken_samples}
    """))
    for r in result:
        report.orphan_edges.append({
            "player_id": r[0],
            "player_name": r[1],
            "from_club_id": r[2],
            "from_club_name": r[3],
            "occurrences": r[4],
            "max_fee": r[5],
        })

    # 4. Duplicate edges (same composite key appearing 2+ times)
    result = await session.execute(text(f"""
        SELECT player_id, from_club_id, to_club_id, transfer_date, COUNT(*) as cnt
        FROM transfers
        WHERE player_id IS NOT NULL
        GROUP BY player_id, from_club_id, to_club_id, transfer_date
        HAVING COUNT(*) > 1
        LIMIT {max_broken_samples}
    """))
    for r in result:
        report.duplicate_edges.append({
            "player_id": r[0],
            "from_club_id": r[1],
            "to_club_id": r[2],
            "transfer_date": str(r[3]),
            "count": r[4],
        })

    # 5. Missing continuity (players whose first transfer is incomplete)
    result = await session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT player_id, MIN(transfer_date) as first_date
            FROM transfers
            GROUP BY player_id
        ) ft
        JOIN transfers t ON t.player_id = ft.player_id
            AND t.transfer_date = ft.first_date
        WHERE t.from_club_id IS NULL
    """))
    report.missing_continuity = result.scalar() or 0

    # ── Health Score Computation (uses TRUE totals, not sampled) ──

    # Get true counts for health score
    result = await session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT t1.player_id
            FROM transfers t1
            JOIN transfers t2 ON t1.player_id = t2.player_id
                AND t1.from_club_id = t2.to_club_id
                AND t1.transfer_date < t2.transfer_date
            WHERE t1.transfer_fee > 100000 OR t2.transfer_fee > 100000
            GROUP BY t1.player_id
        )
    """))
    true_timeline_violations = result.scalar() or 0

    result = await session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT player_id, COUNT(*) as breaks
            FROM (
                SELECT player_id, from_club_id, to_club_id, transfer_date,
                       LAG(to_club_id) OVER (
                           PARTITION BY player_id ORDER BY transfer_date
                       ) as prev_to_club
                FROM transfers
                WHERE player_id IN (
                    SELECT player_id FROM transfers
                    GROUP BY player_id HAVING COUNT(*) >= 3
                )
            )
            WHERE prev_to_club IS NOT NULL
              AND prev_to_club != from_club_id
            GROUP BY player_id
        )
    """))
    true_disconnected = result.scalar() or 0

    result = await session.execute(text("""
        SELECT COUNT(DISTINCT player_id)
        FROM transfers t
        WHERE t.from_club_id IS NOT NULL
          AND t.from_club_id NOT IN (
              SELECT club_id FROM clubs WHERE club_id IS NOT NULL
          )
    """))
    true_orphan = result.scalar() or 0

    result = await session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT player_id, from_club_id, to_club_id, transfer_date, COUNT(*) as cnt
            FROM transfers
            WHERE player_id IS NOT NULL
            GROUP BY player_id, from_club_id, to_club_id, transfer_date
            HAVING COUNT(*) > 1
        )
    """))
    true_duplicates = result.scalar() or 0

    # Compute health score from TRUE totals
    score = 1.0

    if report.total_edges > 0:
        violation_rate = true_timeline_violations / max(report.total_edges, 1)
        score -= violation_rate * 8  # Severe penalty

    score -= min(true_disconnected * 0.002, 0.15)  # Cap at 0.15
    score -= min(true_orphan * 0.001, 0.10)  # Cap at 0.10
    score -= min(true_duplicates * 0.03, 0.20)  # Cap at 0.20
    score -= min((report.missing_continuity / 10000), 0.10)  # Cap at 0.10

    report.graph_health_score = round(max(0.0, min(score, 1.0)), 3)

    return report


async def check_player_career_continuity(
    session: AsyncSession,
    player_id: int,
) -> dict:
    """Validate a single player's career chain continuity.

    Returns dict with:
        is_continuous: bool
        gaps: list of (from_club, to_club, date) where chain breaks
        total_transfers: int
    """
    result = await session.execute(text("""
        SELECT from_club_id, to_club_id, from_club_name, to_club_name,
               transfer_date, transfer_fee
        FROM transfers
        WHERE player_id = :pid
        ORDER BY transfer_date ASC
    """), {"pid": player_id})

    transfers = result.fetchall()

    if len(transfers) <= 1:
        return {
            "is_continuous": True,
            "gaps": [],
            "total_transfers": len(transfers),
        }

    gaps = []
    for i in range(1, len(transfers)):
        prev = transfers[i - 1]
        curr = transfers[i]

        # Check: does previous to_club match current from_club?
        if prev.to_club_id != curr.from_club_id:
            gaps.append({
                "from": curr.from_club_name,
                "to": curr.to_club_name,
                "date": str(curr.transfer_date),
                "expected_from_club_id": prev.to_club_id,
                "actual_from_club_id": curr.from_club_id,
            })

    return {
        "is_continuous": len(gaps) == 0,
        "gaps": gaps,
        "total_transfers": len(transfers),
    }
