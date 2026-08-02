"""Rollenbasierte Zugriffsprüfung für eingehende Mails."""

from sqlalchemy import select

from .models import Mail, RollenMailzugriff


ROLLE_ADMIN = "admin"
ROLLE_SACHBEARBEITER = "sachbearbeiter"


def ist_admin(benutzer: dict) -> bool:
    return benutzer.get("rolle") == ROLLE_ADMIN


async def verweigerte_klassifikationen(session, benutzer: dict) -> set[str]:
    if ist_admin(benutzer):
        return set()
    if benutzer.get("rolle") != ROLLE_SACHBEARBEITER:
        return {"*"}
    return set((await session.execute(
        select(RollenMailzugriff.klassifikation_id).where(
            RollenMailzugriff.rolle == ROLLE_SACHBEARBEITER,
            RollenMailzugriff.darf_sehen.is_(False),
        )
    )).scalars().all())


async def darf_klassifikation_sehen(
    session, benutzer: dict, klassifikation_id: str | None
) -> bool:
    if ist_admin(benutzer):
        return True
    if benutzer.get("rolle") != ROLLE_SACHBEARBEITER:
        return False
    if not klassifikation_id:
        return True
    zugriff = (await session.execute(select(RollenMailzugriff.darf_sehen).where(
        RollenMailzugriff.rolle == ROLLE_SACHBEARBEITER,
        RollenMailzugriff.klassifikation_id == klassifikation_id,
    ))).scalar_one_or_none()
    # Noch nicht konfigurierte und neu hinzugekommene Mailarten bleiben in der
    # Einführungsphase sichtbar, bis ein Admin sie ausdrücklich abwählt.
    return zugriff is not False


async def darf_mail_sehen(session, benutzer: dict, mail: Mail | None) -> bool:
    return bool(mail) and await darf_klassifikation_sehen(
        session, benutzer, mail.klassifikation_id
    )
