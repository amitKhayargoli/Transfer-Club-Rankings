#!/usr/bin/env python3
"""Create the appearances table."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import asyncio
from api.database import engine, Base
from api.models import Appearance  # noqa: F401 — register model

async def create():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created successfully")
    
    # Verify
    import sqlite3
    conn2 = sqlite3.connect(str(Path(__file__).resolve().parent.parent.parent / "data" / "transfer_roi.db"))
    c = conn2.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='appearances'")
    if c.fetchone():
        print("✓ appearances table exists")
    else:
        print("✗ appearances table NOT found")
    conn2.close()

asyncio.run(create())
