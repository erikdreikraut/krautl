"""Rollenbasierte Zugriffsprüfung für eingehende Mails."""

from sqlalchemy import and_, or_, select

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
    if not mail or not await darf_klassifikation_sehen(
        session, benutzer, mail.klassifikation_id
    ):
        return False
    # Admins behalten die Gesamtaufsicht und können dadurch auch eine zuvor an
    # die Sachbearbeitung vergebene Mail wieder neu zuweisen. Sachbearbeiter
    # dürfen dagegen eine ausdrücklich Erik zugewiesene Mail weder über einen
    # direkten API-Aufruf noch über abgeleitete Datensätze öffnen.
    if ist_admin(benutzer):
        return True
    if mail.zustaendigkeit_manuell:
        return (
            benutzer.get("rolle") == ROLLE_SACHBEARBEITER
            and mail.zustaendig_sachbearbeiter
        )
    return True


def mailzugriffsfilter(benutzer: dict):
    """SQL-Filter für alle Mails, auf die eine Rolle grundsätzlich zugreifen darf."""
    if ist_admin(benutzer):
        return None
    if benutzer.get("rolle") == ROLLE_SACHBEARBEITER:
        return or_(
            Mail.zustaendigkeit_manuell.is_(False),
            Mail.zustaendig_sachbearbeiter.is_(True),
        )
    # Für unbekannte Rollen ist die Bedingung absichtlich unerfüllbar.
    return Mail.id.is_(None)


def zustaendigkeitsfilter(benutzer: dict, alle: bool = False):
    """SQL-Filter für zwei überschneidungsfreie Arbeitslisten.

    MEINE enthält die der eigenen Rolle zugeordneten Mails. ALLE MAILS ist
    der gemeinsame Vorrat ohne jede manuelle Zuweisung und ohne Mails, die
    bereits unter MEINE stehen.
    """
    if ist_admin(benutzer):
        return (
            and_(
                Mail.zustaendigkeit_manuell.is_(False),
                Mail.zustaendig_admin.is_(False),
            )
            if alle
            else Mail.zustaendig_admin.is_(True)
        )
    if benutzer.get("rolle") == ROLLE_SACHBEARBEITER:
        meine = Mail.zustaendig_sachbearbeiter.is_(True)
        if not alle:
            return meine
        return and_(
            Mail.zustaendigkeit_manuell.is_(False),
            Mail.zustaendig_sachbearbeiter.is_(False),
        )
    # Für unbekannte Rollen ist die Bedingung absichtlich unerfüllbar.
    return Mail.id.is_(None)


async def standard_zustaendigkeit(
    session, klassifikation_id: str | None
) -> tuple[bool, bool]:
    """Leitet die anfängliche Arbeitsverteilung aus der Rollen-Matrix ab.

    Admin ist standardmäßig NICHT zuständig — sonst wäre jede Mail von
    Anfang an "MEINE" für den Admin, und der MEINE/ALLE-Schalter sowie das
    manuelle Zuweisen könnten nie etwas sichtbar verändern. Admin wird nur
    durch explizites Zuweisen (oder den Sicherheits-Fallback beim
    Reklassifizieren, siehe main.py) zuständig.
    """
    sachbearbeiter = await darf_klassifikation_sehen(
        session,
        {"rolle": ROLLE_SACHBEARBEITER},
        klassifikation_id,
    )
    return False, sachbearbeiter
