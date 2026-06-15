#!/usr/bin/env python3
"""Quick database state check before running reconstruction."""
import sqlite3

conn = sqlite3.connect("data/transfer_roi.db")
c = conn.cursor()

print("=== INTEGRITY CHECK ===")
c.execute("PRAGMA integrity_check")
print(f"Integrity: {c.fetchone()[0]}")
print()

print("=== DATABASE STATE ===")
for table in ["transfers", "players", "appearances", "clubs", "player_valuations", "competitions", "club_metrics_windows"]:
    try:
        c.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"  {table}: {c.fetchone()[0]:,}")
    except Exception as e:
        print(f"  {table}: MISSING ({e})")

c.execute("SELECT COUNT(*) FROM transfers WHERE roi_pct IS NOT NULL")
print(f"  Buy-sell pairs: {c.fetchone()[0]:,}")

c.execute("SELECT COUNT(*) FROM transfers WHERE confidence_score IS NOT NULL")
print(f"  Reconstructed transfers: {c.fetchone()[0]:,}")

# Unpaired sells (broken chains)
c.execute("""
    SELECT COUNT(*), ROUND(COALESCE(SUM(t.transfer_fee), 0), 0)
    FROM transfers t
    WHERE t.transfer_fee > 100000
      AND t.from_club_id IS NOT NULL
      AND t.from_club_id NOT IN (515, 2113, 75)
      AND NOT EXISTS (
          SELECT 1 FROM transfers t2
          WHERE t2.player_id = t.player_id
            AND t2.to_club_id = t.from_club_id
      )
""")
row = c.fetchone()
print(f"  Unpaired sells: {row[0]:,} (€{row[1]:,.0f})")

print()
print("=== TOP 10 BROKEN CHAINS ===")
c.execute("""
    SELECT t.player_id, p.name,
           ROUND(SUM(t.transfer_fee), 0) as total_fee,
           COUNT(*) as sell_count
    FROM transfers t
    JOIN players p ON t.player_id = p.player_id
    WHERE t.transfer_fee > 100000
      AND t.from_club_id IS NOT NULL
      AND t.from_club_id NOT IN (515, 2113, 75)
      AND NOT EXISTS (
          SELECT 1 FROM transfers t2
          WHERE t2.player_id = t.player_id
            AND t2.to_club_id = t.from_club_id
      )
    GROUP BY t.player_id
    ORDER BY SUM(t.transfer_fee) DESC
    LIMIT 10
""")
for r in c.fetchall():
    print(f"  ID {r[0]}: {r[1]} -- EUR{r[2]:,.0f} ({r[3]} sells)")

# Check confidence distribution
c.execute("SELECT confidence_score FROM transfers WHERE confidence_score IS NOT NULL")
scores = [r[0] for r in c.fetchall()]
if scores:
    print(f"\nExisting reconstructed transfers confidence distribution ({len(scores)} total):")
    print(f"  High (>=0.9):   {sum(1 for s in scores if s >= 0.9)}")
    print(f"  Med (0.7-0.9):  {sum(1 for s in scores if 0.7 <= s < 0.9)}")
    print(f"  Low (<0.7):     {sum(1 for s in scores if s < 0.7)}")

# Check if API client is available
print()
print("=== API CLIENT CHECK ===")
import sys
from pathlib import Path
api_path = Path("/tmp/transfermarkt-api")
print(f"  transfermarkt-api at /tmp/transfermarkt-api: {'EXISTS' if api_path.exists() else 'MISSING'}")

conn.close()
print()
print("=== READY ===")
