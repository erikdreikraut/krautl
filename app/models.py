"""
Datenmodell für Krautl.

Grundprinzip: Jede Tabelle, die Nutzer-Korrekturen speichert (Korrektur,
EntwurfKorrektur, FaqVorschlag), ist bewusst so angelegt, dass sie direkt als
Few-Shot-Quelle für künftige Klassifizierungs-/Entwurfs-Prompts dienen kann —
kein Fine-Tuning nötig, siehe CLAUDE.md.
"""
from datetime import datetime
from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, ForeignKey, Text, JSON, UniqueConstraint, func
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Postfach(Base):
    __tablename__ = "postfach"

    id: Mapped[int] = mapped_column(primary_key=True)
    adresse: Mapped[str] = mapped_column(String(255), unique=True)
    funktion: Mapped[str] = mapped_column(String(50))  # z.B. "info", "service"
    imap_host: Mapped[str] = mapped_column(String(255))

    mails: Mapped[list["Mail"]] = relationship(back_populates="postfach")


class Klassifikation(Base):
    """Entspricht 1:1 der aus n8n übernommenen Klassifikationstabelle."""
    __tablename__ = "klassifikation"

    klassifikation_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    hauptkategorie: Mapped[str] = mapped_column(String(100))
    unterkategorie: Mapped[str] = mapped_column(String(150))
    beschreibung: Mapped[str] = mapped_column(Text)
    standard_prio: Mapped[str] = mapped_column(String(20))
    zielpostfach: Mapped[str | None] = mapped_column(String(255), nullable=True)
    zielordner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    aktion_id: Mapped[str] = mapped_column(String(50))

    aufgaben: Mapped[list["KlassifikationAufgabe"]] = relationship(
        back_populates="klassifikation", order_by="KlassifikationAufgabe.position",
        cascade="all, delete-orphan",
    )


class KlassifikationAufgabe(Base):
    """Geordnete Aufgabenvorlage einer Klassifikation.

    `bestaetiger_typ`/`bestaetiger_referenz` sind bewusst schon vorhanden,
    `alle`, `rolle` oder `nutzer` als mögliche Bestätiger-Ziele aufnehmen.
    """
    __tablename__ = "klassifikation_aufgabe"
    __table_args__ = (
        UniqueConstraint("klassifikation_id", "position", name="uq_klassifikation_aufgabe_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    klassifikation_id: Mapped[str] = mapped_column(
        ForeignKey("klassifikation.klassifikation_id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    aufgabe_typ: Mapped[str] = mapped_column(String(50))
    parameter: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    bestaetiger_typ: Mapped[str] = mapped_column(String(20), default="alle")
    bestaetiger_referenz: Mapped[str | None] = mapped_column(String(255), nullable=True)

    klassifikation: Mapped["Klassifikation"] = relationship(back_populates="aufgaben")


class RollenMailzugriff(Base):
    """Legt je Rolle und Mail-Klassifikation fest, ob sie sichtbar ist."""
    __tablename__ = "rollen_mailzugriff"
    __table_args__ = (
        UniqueConstraint("rolle", "klassifikation_id", name="uq_rolle_mailklassifikation"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rolle: Mapped[str] = mapped_column(String(50), index=True)
    klassifikation_id: Mapped[str] = mapped_column(
        ForeignKey("klassifikation.klassifikation_id", ondelete="CASCADE"), index=True
    )
    darf_sehen: Mapped[bool] = mapped_column(Boolean, default=True)


class Mail(Base):
    __tablename__ = "mail"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[str] = mapped_column(String(998), unique=True, index=True)
    imap_uid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    postfach_id: Mapped[int] = mapped_column(ForeignKey("postfach.id"))

    absender_name: Mapped[str] = mapped_column(String(255))
    absender_adresse: Mapped[str] = mapped_column(String(255))
    betreff: Mapped[str] = mapped_column(Text)
    text_auszug: Mapped[str] = mapped_column(Text)
    empfangen_am: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    spam_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Nur die Dateinamen — der Inhalt wird bei Bedarf erneut per IMAP geladen
    # (siehe app/mail_anhaenge.py), damit Anhänge nicht doppelt in der
    # Datenbank liegen.
    anhang_dateinamen: Mapped[list | None] = mapped_column(JSON, nullable=True)

    klassifikation_id: Mapped[str | None] = mapped_column(
        ForeignKey("klassifikation.klassifikation_id"), nullable=True
    )
    konfidenz: Mapped[float] = mapped_column(Float, default=0.0)
    aktion_erforderlich: Mapped[bool] = mapped_column(Boolean, default=False)

    kundennummer: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bestellnummer: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rechnungsnummer: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # "offen" | "geprueft" — wird "geprueft" sobald der Mensch die Kategorie
    # bestätigt oder korrigiert hat.
    pruefstatus: Mapped[str] = mapped_column(String(20), default="offen")
    im_krautl_posteingang: Mapped[bool] = mapped_column(Boolean, default=True)
    # Die Rollen-Matrix bestimmt die anfängliche Zuständigkeit. Eine
    # manuelle Zuweisung setzt anschließend genau eine der beiden Rollen.
    zustaendig_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    zustaendig_sachbearbeiter: Mapped[bool] = mapped_column(Boolean, default=True)
    zustaendigkeit_manuell: Mapped[bool] = mapped_column(Boolean, default=False)

    postfach: Mapped["Postfach"] = relationship(back_populates="mails")
    korrekturen: Mapped[list["Korrektur"]] = relationship(back_populates="mail")
    entwuerfe: Mapped[list["Entwurf"]] = relationship(back_populates="mail")
    aufgaben: Mapped[list["MailAufgabe"]] = relationship(
        back_populates="mail", order_by="MailAufgabe.position", cascade="all, delete-orphan"
    )


class MailAufgabe(Base):
    """Konkreter, unveränderlicher Aufgabenplan einer einzelnen Mail."""
    __tablename__ = "mail_aufgabe"
    __table_args__ = (
        UniqueConstraint("mail_id", "position", name="uq_mail_aufgabe_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    mail_id: Mapped[int] = mapped_column(ForeignKey("mail.id", ondelete="CASCADE"), index=True)
    klassifikation_aufgabe_id: Mapped[int | None] = mapped_column(
        ForeignKey("klassifikation_aufgabe.id", ondelete="SET NULL"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer)
    aufgabe_typ: Mapped[str] = mapped_column(String(50))
    parameter: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # "blockiert" | "wartet" | "erledigt" | "fehlgeschlagen"
    status: Mapped[str] = mapped_column(String(20), default="blockiert", index=True)
    bestaetiger_typ: Mapped[str] = mapped_column(String(20), default="alle")
    bestaetiger_referenz: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bestaetigt_von: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bestaetigt_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    erledigt_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fehler: Mapped[str | None] = mapped_column(Text, nullable=True)

    mail: Mapped["Mail"] = relationship(back_populates="aufgaben")


class Korrektur(Base):
    """Feedback-Loop für die Kategorisierung: eine Nutzerkorrektur pro Zeile."""
    __tablename__ = "korrektur"

    id: Mapped[int] = mapped_column(primary_key=True)
    mail_id: Mapped[int] = mapped_column(ForeignKey("mail.id"))
    alte_klassifikation_id: Mapped[str] = mapped_column(String(50))
    neue_klassifikation_id: Mapped[str] = mapped_column(String(50))
    notiz: Mapped[str | None] = mapped_column(Text, nullable=True)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    mail: Mapped["Mail"] = relationship(back_populates="korrekturen")


class Entwurf(Base):
    """Antwortentwurf — verlässt das System ausschließlich über manuelle Freigabe."""
    __tablename__ = "entwurf"

    id: Mapped[int] = mapped_column(primary_key=True)
    mail_id: Mapped[int] = mapped_column(ForeignKey("mail.id"))
    text_ki: Mapped[str] = mapped_column(Text)
    text_final: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "wartet" | "versendet" | "verworfen"
    status: Mapped[str] = mapped_column(String(20), default="wartet")
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    versendet_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    mail: Mapped["Mail"] = relationship(back_populates="entwuerfe")


class Rechnung(Base):
    __tablename__ = "rechnung"
    __table_args__ = (UniqueConstraint("dublettenschluessel", name="uq_rechnung_dublette"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    mail_id: Mapped[int | None] = mapped_column(ForeignKey("mail.id"), nullable=True)
    aussteller: Mapped[str] = mapped_column(String(255))
    rechnungsnummer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rechnungsdatum: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    faellig_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bruttobetrag: Mapped[float | None] = mapped_column(Float, nullable=True)
    waehrung: Mapped[str] = mapped_column(String(10), default="EUR")
    # "offen" | "automatisch" | "bezahlt" | "gutschrift" | "unklar"
    zahlungsstatus: Mapped[str] = mapped_column(String(20), default="unklar")
    zahlungshinweis: Mapped[str | None] = mapped_column(Text, nullable=True)
    dateipfad: Mapped[str | None] = mapped_column(String(500), nullable=True)
    dateipfade: Mapped[list | None] = mapped_column(JSON, nullable=True)
    dublettenschluessel: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Produktfamilie(Base):
    __tablename__ = "produktfamilie"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    beschreibung: Mapped[str | None] = mapped_column(Text, nullable=True)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)


class Produkt(Base):
    __tablename__ = "produkt"

    id: Mapped[int] = mapped_column(primary_key=True)
    produktfamilie_id: Mapped[int | None] = mapped_column(
        ForeignKey("produktfamilie.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), unique=True)
    artikelnummer: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    aliases: Mapped[list | None] = mapped_column(JSON, nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)


class Wissenseintrag(Base):
    """Freigegebene Fakten, getrennt nach Geltungsbereich und Quelle."""
    __tablename__ = "wissenseintrag"

    id: Mapped[int] = mapped_column(primary_key=True)
    # allgemein | ablauf | produktfamilie | produkt
    wissensart: Mapped[str] = mapped_column(String(30), index=True)
    produktfamilie_id: Mapped[int | None] = mapped_column(
        ForeignKey("produktfamilie.id", ondelete="SET NULL"), nullable=True, index=True
    )
    produkt_id: Mapped[int | None] = mapped_column(
        ForeignKey("produkt.id", ondelete="SET NULL"), nullable=True, index=True
    )
    titel: Mapped[str] = mapped_column(String(255))
    inhalt: Mapped[str] = mapped_column(Text)
    quelle: Mapped[str | None] = mapped_column(Text, nullable=True)
    stand: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # entwurf | geprueft | freigegeben | veraltet
    status: Mapped[str] = mapped_column(String(20), default="entwurf", index=True)
    sensibel: Mapped[bool] = mapped_column(Boolean, default=False)
    schlagwoerter: Mapped[list | None] = mapped_column(JSON, nullable=True)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FaqEintrag(Base):
    __tablename__ = "faq_eintrag"

    id: Mapped[int] = mapped_column(primary_key=True)
    produkt_id: Mapped[int | None] = mapped_column(
        ForeignKey("produkt.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kategorie: Mapped[str] = mapped_column(String(100))
    frage: Mapped[str] = mapped_column(Text)
    antwort: Mapped[str] = mapped_column(Text)
    quelle: Mapped[str | None] = mapped_column(Text, nullable=True)
    # entwurf | freigegeben | veraltet
    status: Mapped[str] = mapped_column(String(20), default="freigegeben", index=True)
    sortierung: Mapped[int] = mapped_column(Integer, default=0)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)


class FaqVorschlag(Base):
    """Kandidat für einen neuen FAQ-Eintrag, erkannt aus einer Kundenanfrage.
    Wird erst nach manueller Freigabe zu einem FaqEintrag."""
    __tablename__ = "faq_vorschlag"

    id: Mapped[int] = mapped_column(primary_key=True)
    quelle_mail_id: Mapped[int] = mapped_column(ForeignKey("mail.id"))
    kategorie: Mapped[str] = mapped_column(String(100))
    frage: Mapped[str] = mapped_column(Text)
    entwurf_antwort: Mapped[str] = mapped_column(Text)
    # "offen" | "uebernommen" | "verworfen"
    status: Mapped[str] = mapped_column(String(20), default="offen")
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Aktionslog(Base):
    """Protokoll tatsächlich ausgeführter Worker-Aktionen (Klassifizierung,
    Verschieben) — zum Nachvollziehen, was mit einer Mail passiert ist, ohne
    in die Server-Logs schauen zu müssen."""
    __tablename__ = "aktionslog"

    id: Mapped[int] = mapped_column(primary_key=True)
    mail_id: Mapped[int | None] = mapped_column(ForeignKey("mail.id"), nullable=True)
    # "klassifiziert" | "bestaetigt" | "verschoben" | "verschieben_fehlgeschlagen"
    ereignis: Mapped[str] = mapped_column(String(50))
    ausgeloest_von: Mapped[str] = mapped_column(
        String(100), default="Krautl", server_default="Krautl"
    )
    detail: Mapped[str] = mapped_column(Text)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WissensVorschlag(Base):
    """Ein einzelner, nach Antwortversand erkannter Ergänzungsvorschlag."""
    __tablename__ = "wissens_vorschlag"
    __table_args__ = (
        UniqueConstraint("entwurf_id", name="uq_wissens_vorschlag_entwurf"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    quelle_mail_id: Mapped[int] = mapped_column(ForeignKey("mail.id"), index=True)
    entwurf_id: Mapped[int | None] = mapped_column(
        ForeignKey("entwurf.id", ondelete="SET NULL"), nullable=True
    )
    produkt_id: Mapped[int | None] = mapped_column(
        ForeignKey("produkt.id", ondelete="SET NULL"), nullable=True
    )
    # wissen | faq
    ziel: Mapped[str] = mapped_column(String(20))
    wissensart: Mapped[str] = mapped_column(String(30), default="allgemein")
    titel: Mapped[str] = mapped_column(String(255))
    inhalt: Mapped[str] = mapped_column(Text)
    begruendung: Mapped[str | None] = mapped_column(Text, nullable=True)
    # offen | uebernommen | verworfen
    status: Mapped[str] = mapped_column(String(20), default="offen", index=True)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemStatus(Base):
    """Lebenszeichen dauerhaft laufender Hintergrunddienste."""
    __tablename__ = "system_status"

    dienst: Mapped[str] = mapped_column(String(50), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), default="startet")
    letzter_lauf: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    letzter_erfolg: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    letzter_fehler: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
