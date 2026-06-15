#!/usr/bin/env python3
"""Check remaining state after reconstruction run."""
import sqlite3

conn = sqlite3.connect("data/transfer_roi.db")
c = conn.cursor()

c.execute("SELECT COUNT(*) FROM transfers WHERE confidence_score IS NOT NULL")
print(f"Reconstructed transfers: {c.fetchone()[0]:,}")

c.execute("SELECT COUNT(*) FROM transfers WHERE roi_pct IS NOT NULL")
print(f"Buy-sell pairs: {c.fetchone()[0]:,}")

c.execute("SELECT COUNT(*) FROM transfers")
print(f"Total transfers: {c.fetchone()[0]:,}")

# Simplified unpaired check
c.execute("""
    SELECT COUNT(DISTINCT t.player_id), ROUND(SUM(t.transfer_fee))
    FROM transfers t
    WHERE t.transfer_fee > 100000
      AND t.from_club_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM transfers t2
          WHERE t2.player_id = t.player_id
            AND t2.to_club_id = t.from_club_id
      )
""")
r = c.fetchone()
print(f"Unpaired player chains: {r[0]} (EUR{r[1]:,.0f})")

# Silent origin gaps
c.execute("""
    SELECT COUNT(DISTINCT p.player_id)
    FROM players p
    JOIN transfers t ON t.player_id = p.player_id
    WHERE t.transfer_fee > 100000
      AND (t.from_club_id IS NULL OR t.from_club_id NOT IN (SELECT club_id FROM clubs))
""")
print(f"Players with missing origin clubs: {c.fetchone()[0]:,}")

conn.close()
