"""One-time conversion of the old JTL export selection into explicit approval.

Only active drafts, which the old export included, become approved. Deprecated
and inactive FAQ are not promoted. A durable marker prevents later drafts from
being approved when this migration is run again.
"""
import asyncio
import json
from sqlalchemy import text

NAME = "faq_freigabe_20261007"


async def migriere(conn):
    if conn.dialect.name == "postgresql":
        await conn.execute(text("SELECT pg_advisory_xact_lock(1924432)"))
    await conn.execute(text("CREATE TABLE IF NOT EXISTS krautl_datenmigration (name VARCHAR(100) PRIMARY KEY, detail TEXT NOT NULL)"))
    vorhanden = (await conn.execute(text("SELECT detail FROM krautl_datenmigration WHERE name=:name"), {"name": NAME})).scalar_one_or_none()
    if vorhanden is not None:
        return {"bereits_ausgefuehrt": True, "freigegeben": 0}
    ids = list((await conn.execute(text("SELECT id FROM faq_eintrag WHERE aktiv=TRUE AND status='entwurf' ORDER BY id"))).scalars())
    await conn.execute(text("UPDATE faq_eintrag SET status='freigegeben' WHERE aktiv=TRUE AND status='entwurf'"))
    await conn.execute(text("INSERT INTO krautl_datenmigration (name, detail) VALUES (:name, :detail)"), {"name": NAME, "detail": json.dumps({"freigegebene_ids": ids})})
    return {"bereits_ausgefuehrt": False, "freigegeben": len(ids)}


async def main():
    from app.db import engine
    async with engine.begin() as conn:
        ergebnis = await migriere(conn)
    print(json.dumps(ergebnis))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
