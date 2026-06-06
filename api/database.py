"""
Database engine, session factory, and base model for SQLAlchemy.
"""

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from api.config import DATABASE_URL

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"timeout": 15},  # Wait up to 15s for SQLite lock instead of failing immediately
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """Set WAL mode on every new connection to prevent stale journal files.

    WAL mode is stored in the database file itself, so this is a no-op after
    the first time. It's set here (not just in init_db()) so it applies to
    ALL consumers: the API server AND standalone scripts like enrich_data.py.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()

async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """FastAPI dependency that yields an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Create all tables (idempotent - uses IF NOT EXISTS semantics)."""
    from api.models import Base  # noqa: F401  ensure models are registered
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
