"""Nur das neue Opt-in ergänzen; bestehende FAQ bleiben unverändert/off."""
import asyncio

from sqlalchemy import inspect, text


async def migriere(conn):
    vorhanden = await conn.run_sync(lambda c: {
        spalte["name"] for spalte in inspect(c).get_columns("faq_eintrag")
    })
    if "include_in_google_product_qa" not in vorhanden:
        await conn.execute(text(
            "ALTER TABLE faq_eintrag ADD COLUMN include_in_google_product_qa "
            "BOOLEAN NOT NULL DEFAULT FALSE"
        ))


async def main():
    from app.db import engine
    async with engine.begin() as conn:
        await migriere(conn)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
