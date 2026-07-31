"""Redaktionelle Wissensbasis, Produktauswahl und JTL-FAQ-Export."""
import asyncio
import html
import os
import re

from anthropic import Anthropic
from sqlalchemy import select

from .models import (
    Entwurf, FaqEintrag, Mail, Produkt, Wissenseintrag,
    WissensVorschlag,
)


WISSENSARTEN = {"allgemein", "ablauf", "produktfamilie", "produkt"}
WISSENSSTATUS = {"entwurf", "geprueft", "freigegeben", "veraltet"}
FAQ_STATUS = {"entwurf", "freigegeben", "veraltet"}


def produkt_fuer_text(produkte: list[Produkt], text: str) -> Produkt | None:
    text = (text or "").casefold()
    treffer = []
    for produkt in produkte:
        begriffe = [produkt.artikelnummer, produkt.name, *(produkt.aliases or [])]
        passende = [b for b in begriffe if b and str(b).casefold() in text]
        if passende:
            treffer.append((max(len(str(b)) for b in passende), produkt))
    return max(treffer, key=lambda eintrag: eintrag[0])[1] if treffer else None


async def relevante_wissensbasis(session, mail: Mail) -> tuple[Produkt | None, list, list]:
    produkte = (await session.execute(
        select(Produkt).where(Produkt.aktiv.is_(True))
    )).scalars().all()
    produkt = produkt_fuer_text(
        produkte,
        f"{mail.betreff}\n{mail.text_auszug}\n{mail.klassifikation_id or ''}",
    )
    wissen = (await session.execute(
        select(Wissenseintrag).where(Wissenseintrag.status == "freigegeben")
    )).scalars().all()
    passend = []
    for eintrag in wissen:
        if eintrag.wissensart in {"allgemein", "ablauf"}:
            passend.append(eintrag)
        elif produkt and eintrag.wissensart == "produkt" and eintrag.produkt_id == produkt.id:
            passend.append(eintrag)
        elif (
            produkt and eintrag.wissensart == "produktfamilie"
            and eintrag.produktfamilie_id == produkt.produktfamilie_id
        ):
            passend.append(eintrag)
    faq = (await session.execute(
        select(FaqEintrag).where(
            FaqEintrag.aktiv.is_(True),
            FaqEintrag.status == "freigegeben",
        )
    )).scalars().all()
    faq = [eintrag for eintrag in faq if eintrag.produkt_id is None or (
        produkt is not None and eintrag.produkt_id == produkt.id
    )]
    return produkt, passend, faq


def wissen_als_text(eintraege: list[Wissenseintrag]) -> str:
    if not eintraege:
        return "Noch keine passenden freigegebenen Wissenseinträge vorhanden."
    return "\n\n".join(
        f"Wissensart: {e.wissensart}\nTitel: {e.titel}\nFakten: {e.inhalt}\n"
        f"Quelle: {e.quelle or 'nicht angegeben'}\nStand: {e.stand or 'nicht angegeben'}"
        for e in eintraege
    )


def _inline_html(text: str) -> str:
    """Sehr kleines, sicheres Redaktionsformat: **fett** und Weblinks."""
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        r'<a href="\2">\1</a>',
        escaped,
    )


def _antwort_html(text: str) -> str:
    absaetze = [absatz.strip() for absatz in re.split(r"\n\s*\n", text) if absatz.strip()]
    ergebnis = []
    for absatz in absaetze:
        zeilen = absatz.splitlines()
        if zeilen and all(re.match(r"^\s*[-*]\s+", zeile) for zeile in zeilen):
            ergebnis.append("        <ul>")
            ergebnis.extend(
                f"          <li>{_inline_html(re.sub(r'^\s*[-*]\s+', '', zeile))}</li>"
                for zeile in zeilen
            )
            ergebnis.append("        </ul>")
        else:
            ergebnis.append(
                f"        <p>{_inline_html(absatz).replace(chr(10), '<br>')}</p>"
            )
    return "\n".join(ergebnis)


def faq_als_jtl_html(produkt: Produkt, faq: list[FaqEintrag]) -> str:
    """Exportiert alle freigegebenen Produkt-FAQ im vorhandenen JTL-Schema."""
    faq = sorted(faq, key=lambda e: (e.sortierung, e.kategorie.casefold(), e.id))
    gruppen: dict[str, list[FaqEintrag]] = {}
    for eintrag in faq:
        gruppen.setdefault(eintrag.kategorie or "Allgemeines", []).append(eintrag)
    zeilen = [
        '<div itemscope itemtype="https://schema.org/FAQPage" class="accordion" id="faq">',
        "",
    ]
    nummer = 1
    for kategorie, eintraege in gruppen.items():
        zeilen.extend([
            f"  <!-- Abschnitt: {html.escape(kategorie)} -->",
            f'  <h2 class="mt-4 mb-2">{html.escape(kategorie)}</h2>',
            "",
        ])
        for eintrag in eintraege:
            ziel = f"faq-{nummer}"
            zeilen.extend([
                '  <div itemscope itemprop="mainEntity" itemtype="https://schema.org/Question" class="card">',
                f'    <div itemprop="name" class="card-header btn" aria-expanded="false" aria-controls="{ziel}" data-toggle="collapse" data-target="#{ziel}" data-parent="#faq">',
                f"      {html.escape(eintrag.frage)}",
                "    </div>",
                f'    <div itemscope itemprop="acceptedAnswer" itemtype="https://schema.org/Answer" class="collapse" id="{ziel}" data-parent="#faq">',
                '      <div itemprop="text" class="card-body">',
                _antwort_html(eintrag.antwort),
                "      </div>",
                "    </div>",
                "  </div>",
                "",
            ])
            nummer += 1
    zeilen.append("</div>")
    return "\n".join(zeilen)


VORSCHLAGS_TOOL = {
    "name": "wissenszuwachs_pruefen",
    "description": "Erkennt höchstens einen wirklich wiederverwendbaren Wissens- oder FAQ-Vorschlag.",
    "input_schema": {
        "type": "object",
        "properties": {
            "vorschlag_noetig": {"type": "boolean"},
            "ziel": {"type": "string", "enum": ["wissen", "faq"]},
            "wissensart": {"type": "string", "enum": sorted(WISSENSARTEN)},
            "produkt_id": {"type": "integer"},
            "titel": {"type": "string"},
            "inhalt": {"type": "string"},
            "begruendung": {"type": "string"},
        },
        "required": ["vorschlag_noetig", "ziel", "wissensart", "titel", "inhalt", "begruendung"],
    },
}


def _vorschlag_synchron(
    mail: Mail,
    ki_text: str,
    finaler_text: str,
    produkte: list[Produkt],
    wissen: list[Wissenseintrag],
    faq: list[FaqEintrag],
) -> dict:
    produktliste = "\n".join(
        f"{p.id}: {p.name} (Artikelnummer {p.artikelnummer or '-'})" for p in produkte
    ) or "Keine Produkte angelegt."
    antwort = Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"], timeout=120.0
    ).messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        system=(
            "Prüfe nach einer bearbeiteten Kundenantwort, ob durch die menschliche "
            "Bearbeitung ein neues, allgemein wiederverwendbares dreikraut-Faktum oder "
            "eine wertvolle FAQ-Antwort hinzugekommen ist. Reine Stiländerungen, "
            "Höflichkeit, Einzelfalldaten, Namen, Bestellnummern und bereits vorhandenes "
            "Wissen sind kein Vorschlag. Erfinde nichts. Erzeuge höchstens einen kompakten "
            "Vorschlag. Für FAQ muss die Formulierung von der einzelnen Person gelöst sein. "
            "produkt_id nur setzen, wenn die Zuordnung sicher ist; sonst weglassen."
        ),
        tools=[VORSCHLAGS_TOOL],
        tool_choice={"type": "tool", "name": "wissenszuwachs_pruefen"},
        messages=[{"role": "user", "content": (
            f"=== PRODUKTE ===\n{produktliste}\n\n"
            f"=== BESTEHENDES WISSEN ===\n{wissen_als_text(wissen)}\n\n"
            f"=== BESTEHENDE FAQ ===\n" + "\n\n".join(
                f"{e.kategorie}: {e.frage}\n{e.antwort}" for e in faq
            ) + "\n\n=== KUNDENFRAGE ===\n"
            f"{mail.betreff}\n{mail.text_auszug}\n\n"
            f"=== URSPRÜNGLICHER KI-ENTWURF ===\n{ki_text}\n\n"
            f"=== TATSÄCHLICH FREIGEGEBENE FASSUNG ===\n{finaler_text}"
        )}],
    )
    for block in antwort.content:
        if block.type == "tool_use":
            return block.input
    return {"vorschlag_noetig": False}


async def wissenszuwachs_nach_antwort_pruefen(
    session, mail: Mail, entwurf: Entwurf, finaler_text: str
) -> WissensVorschlag | None:
    """Prüft bei manueller Änderung und veröffentlicht niemals selbst."""
    # Ohne menschliche Änderung kann auch kein neues menschlich ergänztes
    # Wissen entstanden sein. Jede inhaltliche Änderung wird dagegen geprüft;
    # selbst ein kurzer ergänzter Satz kann fachlich entscheidend sein.
    if entwurf.text_ki.strip() == finaler_text.strip():
        return None
    vorhanden = (await session.execute(
        select(WissensVorschlag).where(WissensVorschlag.entwurf_id == entwurf.id)
    )).scalar_one_or_none()
    if vorhanden:
        return vorhanden
    produkte = (await session.execute(
        select(Produkt).where(Produkt.aktiv.is_(True))
    )).scalars().all()
    wissen = (await session.execute(
        select(Wissenseintrag).where(Wissenseintrag.status == "freigegeben")
    )).scalars().all()
    faq = (await session.execute(
        select(FaqEintrag).where(FaqEintrag.aktiv.is_(True), FaqEintrag.status == "freigegeben")
    )).scalars().all()
    daten = await asyncio.to_thread(
        _vorschlag_synchron, mail, entwurf.text_ki, finaler_text,
        produkte, wissen, faq,
    )
    if not daten.get("vorschlag_noetig"):
        return None
    produkt_ids = {p.id for p in produkte}
    produkt_id = daten.get("produkt_id")
    if produkt_id not in produkt_ids:
        produkt_id = None
    vorschlag = WissensVorschlag(
        quelle_mail_id=mail.id,
        entwurf_id=entwurf.id,
        produkt_id=produkt_id,
        ziel=daten.get("ziel") if daten.get("ziel") in {"wissen", "faq"} else "wissen",
        wissensart=(
            daten.get("wissensart") if daten.get("wissensart") in WISSENSARTEN else "allgemein"
        ),
        titel=(daten.get("titel") or "Wissensvorschlag").strip(),
        inhalt=(daten.get("inhalt") or "").strip(),
        begruendung=(daten.get("begruendung") or "").strip() or None,
    )
    if not vorschlag.inhalt:
        return None
    session.add(vorschlag)
    await session.flush()
    return vorschlag
