"""
Datenmodell für Krautl.

Grundprinzip: Jede Tabelle, die Nutzer-Korrekturen speichert (Korrektur,
EntwurfKorrektur, FaqVorschlag), ist bewusst so angelegt, dass sie direkt als
Few-Shot-Quelle für künftige Klassifizierungs-/Entwurfs-Prompts dienen kann —
kein Fine-Tuning nötig, siehe CLAUDE.md.
"""
from datetime import datetime
from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, ForeignKey, Text, func
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
    empfangen_am: Mapped[datetime] = mapped_column(DateTime)
    spam_score: Mapped[float | None] = mapped_column(Float, nullable=True)

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

    postfach: Mapped["Postfach"] = relationship(back_populates="mails")
    korrekturen: Mapped[list["Korrektur"]] = relationship(back_populates="mail")
    entwuerfe: Mapped[list["Entwurf"]] = relationship(back_populates="mail")


class Korrektur(Base):
    """Feedback-Loop für die Kategorisierung: eine Nutzerkorrektur pro Zeile."""
    __tablename__ = "korrektur"

    id: Mapped[int] = mapped_column(primary_key=True)
    mail_id: Mapped[int] = mapped_column(ForeignKey("mail.id"))
    alte_klassifikation_id: Mapped[str] = mapped_column(String(50))
    neue_klassifikation_id: Mapped[str] = mapped_column(String(50))
    notiz: Mapped[str | None] = mapped_column(Text, nullable=True)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    mail: Mapped["Mail"] = relationship(back_populates="korrekturen")


class Entwurf(Base):
    """Antwortentwurf — verlässt das System ausschließlich über manuelle Freigabe."""
    __tablename__ = "entwurf"

    id: Mapped[int] = mapped_column(primary_key=True)
    mail_id: Mapped[int] = mapped_column(ForeignKey("mail.id"))
    text_ki: Mapped[str] = mapped_column(Text)
    text_final: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "wartet" | "freigegeben" | "verworfen"
    status: Mapped[str] = mapped_column(String(20), default="wartet")
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    versendet_am: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    mail: Mapped["Mail"] = relationship(back_populates="entwuerfe")


class Rechnung(Base):
    __tablename__ = "rechnung"

    id: Mapped[int] = mapped_column(primary_key=True)
    mail_id: Mapped[int | None] = mapped_column(ForeignKey("mail.id"), nullable=True)
    aussteller: Mapped[str] = mapped_column(String(255))
    rechnungsnummer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rechnungsdatum: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    faellig_am: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    bruttobetrag: Mapped[float | None] = mapped_column(Float, nullable=True)
    waehrung: Mapped[str] = mapped_column(String(10), default="EUR")
    # "offen" | "bezahlt" | "unklar"
    zahlungsstatus: Mapped[str] = mapped_column(String(20), default="unklar")
    dateipfad: Mapped[str | None] = mapped_column(String(500), nullable=True)


class FaqEintrag(Base):
    __tablename__ = "faq_eintrag"

    id: Mapped[int] = mapped_column(primary_key=True)
    kategorie: Mapped[str] = mapped_column(String(100))
    frage: Mapped[str] = mapped_column(Text)
    antwort: Mapped[str] = mapped_column(Text)
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
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Aktionslog(Base):
    """Protokoll tatsächlich ausgeführter Worker-Aktionen (Klassifizierung,
    Verschieben) — zum Nachvollziehen, was mit einer Mail passiert ist, ohne
    in die Server-Logs schauen zu müssen."""
    __tablename__ = "aktionslog"

    id: Mapped[int] = mapped_column(primary_key=True)
    mail_id: Mapped[int | None] = mapped_column(ForeignKey("mail.id"), nullable=True)
    # "klassifiziert" | "verschoben" | "verschieben_fehlgeschlagen"
    ereignis: Mapped[str] = mapped_column(String(50))
    detail: Mapped[str] = mapped_column(Text)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
