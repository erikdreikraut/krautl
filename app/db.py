import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncConnection, AsyncSession

from .models import Base

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def schema_anlegen(conn: AsyncConnection) -> None:
    if conn.dialect.name == "postgresql":
        # App und Mail-Worker starten beim Deployment gemeinsam.
        await conn.execute(text("SELECT pg_advisory_xact_lock(540114824903)"))
    await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
