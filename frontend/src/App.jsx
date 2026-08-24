import { useCallback, useEffect, useMemo, useState, useRef } from "react";
import {
  Search, ChevronDown, CheckCircle2, PenLine, Paperclip, X,
  Inbox as InboxIcon, Receipt, BookOpen, Check, FolderCog, Sparkles, Settings,
  LogOut, ShieldCheck, Trash2, UserRound, Eye, ArrowLeft,
} from "lucide-react";
import { api } from "./api.js";
import logo from "./assets/krautl-logo.png";
import { WissensdatenbankViewNeu } from "./WissensdatenbankView.jsx";

// Grün/Creme an den Logo-Farben ausgerichtet (#509B32 dunkelgrün,
// #FFFFD2 creme, #BEDC0F helles Blattgrün) — Amber/Rost bleiben als
// funktionale Signalfarben (Warnung/Fehler) unverändert.
const tokens = {
  paper: "#F8F6D9",
  paperRaised: "#FDFCEE",
  ink: "#242A1F",
  inkMuted: "#6C6F5F",
  line: "#DDD9C4",
  moss: "#4F9B2E",
  mossDeep: "#2C5A18",
  mossPale: "#E8F0C8",
  amber: "#B07B2E",
  amberPale: "#F3E7D2",
  rust: "#A5462F",
  rustPale: "#F1DED7",
};

const fontDisplay = { fontFamily: "'Source Serif 4', serif", fontWeight: 700 };
const fontSerif = { fontFamily: "'Source Serif 4', serif" };
const fontUI = { fontFamily: "'IBM Plex Sans', sans-serif" };
const fontMono = { fontFamily: "'IBM Plex Mono', monospace" };

// Feste Hauptkategorien-Namen kennen wir erst nach dem CSV-Import in die
// klassifikation-Tabelle — deshalb Farbe deterministisch aus dem Namen
// ableiten statt eine feste Zuordnungstabelle zu pflegen.
const FARB_ZYKLUS = [tokens.moss, tokens.amber, tokens.rust, tokens.inkMuted, tokens.mossDeep];
function farbeFuerKategorie(name) {
  if (!name) return tokens.inkMuted;
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return FARB_ZYKLUS[hash % FARB_ZYKLUS.length];
}

// Immer Berlin anzeigen — dreikraut sitzt dort, unabhängig davon, wessen
// Rechner/Zeitzone gerade auf die Oberfläche zugreift.
const ZEITZONE = "Europe/Berlin";

function formatZeit(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", timeZone: ZEITZONE });
}

const BERLIN_TAG_FORMAT = new Intl.DateTimeFormat("de-DE", {
  timeZone: ZEITZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

function berlinTag(datum) {
  const teile = Object.fromEntries(
    BERLIN_TAG_FORMAT.formatToParts(datum)
      .filter((teil) => teil.type !== "literal")
      .map((teil) => [teil.type, Number(teil.value)])
  );
  return {
    jahr: teile.year,
    wert: Date.UTC(teile.year, teile.month - 1, teile.day),
  };
}

function formatMailZeit(iso, jetzt = new Date()) {
  if (!iso) return "";
  const datum = new Date(iso);
  if (Number.isNaN(datum.getTime())) return "";
  const mailTag = berlinTag(datum);
  const heute = berlinTag(jetzt);
  const tageAbstand = Math.round((heute.wert - mailTag.wert) / 86_400_000);
  const uhrzeit = formatZeit(iso);
  if (tageAbstand === 0) return uhrzeit;
  if (tageAbstand === 1) return `Gestern, ${uhrzeit}`;
  const datumsOptionen = {
    day: "2-digit",
    month: "2-digit",
    ...(mailTag.jahr === heute.jahr ? {} : { year: "numeric" }),
    timeZone: ZEITZONE,
  };
  return `${datum.toLocaleDateString("de-DE", datumsOptionen)}, ${uhrzeit}`;
}

function formatDatum(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("de-DE", { timeZone: ZEITZONE });
}

function formatZeitpunkt(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: ZEITZONE });
}

function formatRechnungseingang(iso) {
  if (!iso) return "–";
  return new Date(iso).toLocaleString("de-DE", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit", timeZone: ZEITZONE,
  });
}

function formatBetrag(wert, waehrung = "EUR") {
  if (wert == null) return "";
  return wert.toLocaleString("de-DE", { style: "currency", currency: waehrung || "EUR" });
}

// Festes Set von Aktion_IDs (siehe data/mail-klassifikationen.csv). Neue
// Aktionen brauchen jeweils eigenen Code in app/aufgaben.py — dies ist nur die
// Anzeige, welche davon aktuell tatsächlich etwas auslösen.
const AKTION_LABEL = {
  BESTAETIGUNG_EINHOLEN: "Bestätigung einholen",
  MAIL_VERSCHIEBEN: "Mail verschieben",
  RECHNUNG_VERWALTEN: "Rechnung verwalten",
  ANTWORTVORSCHLAG_ERSTELLEN: "Antwortvorschlag erstellen",
  LIEFERANTENMAIL_BEARBEITEN: "Lieferantenmail bearbeiten",
  MARKETINGMAIL_BEARBEITEN: "Marketingmail bearbeiten",
  AUDIO_TRANSKRIBIEREN: "Audio transkribieren",
  SYSTEMMELDUNG_BEARBEITEN: "Systemmeldung bearbeiten",
  RECHTSSACHE_BEARBEITEN: "Rechtssache bearbeiten",
};
const AKTIVE_AKTIONEN = new Set([
  "BESTAETIGUNG_EINHOLEN",
  "MAIL_VERSCHIEBEN",
  "RECHNUNG_VERWALTEN",
  "ANTWORTVORSCHLAG_ERSTELLEN",
  "AUDIO_TRANSKRIBIEREN",
]);
const EDITIERBARE_AKTIONEN = Object.keys(AKTION_LABEL).filter((aktion) =>
  AKTIVE_AKTIONEN.has(aktion)
);

const EREIGNIS_LABEL = {
  klassifiziert: "Klassifiziert",
  bestaetigt: "Bestätigt",
  posteingang_bereinigt: "Posteingang bereinigt",
  verschoben: "Verschoben",
  verschieben_fehlgeschlagen: "Verschieben fehlgeschlagen",
  rechnung_verarbeitet: "Rechnung verarbeitet",
  rechnung_fehlgeschlagen: "Rechnung fehlgeschlagen",
  antwortvorschlag_erstellt: "Antwortvorschlag erstellt",
  antwortentwurf_erstellt: "Antwort begonnen",
  antwortvorschlag_fehlgeschlagen: "Antwortvorschlag fehlgeschlagen",
  antwort_pruefung_noetig: "Antwort noch nicht versandbereit",
  antwort_pruefung_uebersprungen: "KI-Prüfung übersprungen",
  antwort_versendet_test: "Testantwort an Mailserver übergeben",
  antwort_versendet: "Antwort an Mailserver übergeben",
  antwort_versand_fehlgeschlagen: "Antwortversand fehlgeschlagen",
  wissensvorschlag_erstellt: "Wissensvorschlag erstellt",
  wissenspruefung_fehlgeschlagen: "Wissensprüfung fehlgeschlagen",
  audio_transkribiert: "Audio transkribiert",
  audio_transkription_fehlgeschlagen: "Audiotranskription fehlgeschlagen",
  rollenzugriff_geaendert: "Rollenzugriff geändert",
  klassifikation_geaendert: "Mail-Klassifikation geändert",
  klassifikation_korrigiert: "Kategorie korrigiert",
  rechnungsstatus_geaendert: "Rechnungsstatus geändert",
  antwortvorschlag_verworfen: "Antwortvorschlag verworfen",
  mail_manuell_erledigt: "Manuell erledigt",
  mail_geloescht: "Mail gelöscht",
  mail_loeschen_fehlgeschlagen: "Mail-Löschung fehlgeschlagen",
  mail_zugewiesen: "Mail zugewiesen",
};
function farbeFuerEreignis(ereignis) {
  if (ereignis.endsWith("fehlgeschlagen")) return tokens.rust;
  if (ereignis === "mail_geloescht") return tokens.rust;
  if (["verschoben", "bestaetigt", "rechnung_verarbeitet", "antwortvorschlag_erstellt", "antwortentwurf_erstellt", "antwort_versendet_test", "antwort_versendet", "audio_transkribiert", "wissensvorschlag_erstellt", "mail_manuell_erledigt"].includes(ereignis)) return tokens.moss;
  return tokens.inkMuted;
}

function Badge({ label, color }) {
  return (
    <span className="inline-flex items-center pl-2 pr-2.5 py-1 text-xs shrink-0"
      style={{ ...fontMono, background: tokens.paperRaised, border: `1px solid ${tokens.line}`, borderLeft: `4px solid ${color}`, color: tokens.ink, letterSpacing: "0.02em" }}>
      {label}
    </span>
  );
}

function Konfidenz({ value }) {
  const color = value >= 0.85 ? tokens.moss : value >= 0.65 ? tokens.amber : tokens.rust;
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-10 h-1.5 rounded-full overflow-hidden" style={{ background: tokens.line }}>
        <div className="h-full rounded-full" style={{ width: `${value * 100}%`, background: color }} />
      </div>
      <span style={{ ...fontMono, color: tokens.inkMuted, fontSize: "11px" }}>{Math.round(value * 100)}%</span>
    </div>
  );
}

function NavTab({ icon: Icon, label, mobileLabel = label, count, active, onClick, accent }) {
  return (
    <button onClick={onClick} className="flex items-center gap-2 px-3.5 py-2.5 relative"
      style={{ ...fontUI, fontSize: "13.5px", fontWeight: active ? 600 : 500, color: active ? tokens.mossDeep : tokens.inkMuted }}>
      <Icon size={15} />
      <span className="nav-label-desktop">{label}</span>
      <span className="nav-label-mobile">{mobileLabel}</span>
      {count != null && (
        <span className="px-1.5 rounded-full" style={{ ...fontMono, fontSize: "10.5px", background: accent ? tokens.amberPale : tokens.mossPale, color: accent ? tokens.amber : tokens.mossDeep }}>
          {count}
        </span>
      )}
      {active && <span className="absolute left-0 right-0" style={{ bottom: "-1px", height: "2px", background: tokens.mossDeep }} />}
    </button>
  );
}

const AUSWAHL_BUTTON_STIL = {
  ...fontUI,
  fontSize: "11.5px",
  color: tokens.inkMuted,
  border: `1px solid ${tokens.line}`,
  borderRadius: "6px",
  background: tokens.paperRaised,
};

function AuswahlMenue({ label, title, icon: Icon, wert, optionen, onWaehlen, deaktiviert, breite = "280px" }) {
  const [offen, setOffen] = useState(false);
  const container = useRef(null);

  useEffect(() => {
    if (!offen) return undefined;
    const ausserhalbSchliessen = (ereignis) => {
      if (!container.current?.contains(ereignis.target)) setOffen(false);
    };
    document.addEventListener("pointerdown", ausserhalbSchliessen);
    return () => document.removeEventListener("pointerdown", ausserhalbSchliessen);
  }, [offen]);

  return (
    <div ref={container} className="relative">
      <button
        type="button"
        onClick={() => setOffen((alt) => !alt)}
        disabled={deaktiviert}
        title={title}
        aria-haspopup="menu"
        aria-expanded={offen}
        className="flex items-center gap-1.5 px-2.5 py-1.5 disabled:opacity-50"
        style={AUSWAHL_BUTTON_STIL}
      >
        {Icon && <Icon size={12} />}
        {label}
        <ChevronDown size={12} />
      </button>
      {offen && (
        <div
          role="menu"
          className="absolute right-0 top-full mt-1 py-1 overflow-y-auto auswahl-menue"
          style={{ width: breite, maxWidth: "calc(100vw - 24px)", maxHeight: "320px", zIndex: 50, background: tokens.paperRaised, border: `1px solid ${tokens.line}`, borderRadius: "7px", boxShadow: "0 8px 22px rgba(36, 42, 31, 0.14)" }}
        >
          {optionen.map((option) => (
            <button
              type="button"
              role="menuitem"
              key={option.value}
              onClick={() => {
                setOffen(false);
                if (option.value !== wert) onWaehlen(option.value);
              }}
              className="w-full flex items-center justify-between gap-3 px-3 py-2 text-left hover:bg-[#E8F0C8]"
              style={{ ...fontUI, fontSize: "12px", color: tokens.ink }}
            >
              <span>{option.label}</span>
              {option.value === wert && <Check size={13} style={{ color: tokens.moss }} />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function KategorieKorrektur({ mail, katalog, onKorrigiert }) {
  const [wird_gesendet, setWirdGesendet] = useState(false);

  async function korrigieren(neueId) {
    if (!neueId || neueId === mail.klassifikation_id) return;
    setWirdGesendet(true);
    try {
      await api.korrigiereKlassifikation(mail.id, neueId);
      await onKorrigiert();
    } finally {
      setWirdGesendet(false);
    }
  }

  return (
    <AuswahlMenue
      label={wird_gesendet ? "Wird geändert …" : "Kategorie ändern"}
      title="Mail einer anderen Kategorie zuordnen"
      wert={mail.klassifikation_id ?? ""}
      deaktiviert={wird_gesendet}
      breite="390px"
      optionen={katalog.map((k) => ({
        value: k.klassifikation_id,
        label: `${k.klassifikation_id} — ${k.hauptkategorie} / ${k.unterkategorie}`,
      }))}
      onWaehlen={korrigieren}
    />
  );
}

function BestaetigenButton({ mail, onBestaetigt }) {
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState(null);

  if (!mail.bestaetigungErforderlich) return null;

  async function bestaetigen() {
    setLaeuft(true);
    setFehler(null);
    try {
      const ergebnis = await api.mailBestaetigen(mail.id);
      if (ergebnis.status === "fehlgeschlagen") {
        setFehler(ergebnis.detail || "Folgeaufgabe fehlgeschlagen");
      }
      await onBestaetigt();
    } catch (e) {
      setFehler(e.message);
    } finally {
      setLaeuft(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      {fehler && <span title={fehler} style={{ ...fontUI, fontSize: "11px", color: tokens.rust }}>Aktion fehlgeschlagen</span>}
      <button onClick={bestaetigen} disabled={laeuft}
        className="flex items-center gap-1.5 px-3 py-2 disabled:opacity-60"
        style={{ ...fontUI, fontSize: "13px", fontWeight: 600, color: "#fff", background: tokens.moss, borderRadius: "6px" }}>
        <Check size={14} /> {laeuft ? "Wird bestätigt …" : "Bestätigen"}
      </button>
    </div>
  );
}

function MailLoeschenButton({ mail, onGeloescht }) {
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState("");

  async function loeschen() {
    const bestaetigt = window.confirm(
      `Mail „${mail.betreff}“ wirklich dauerhaft aus dem Postfach löschen?\n\nDiese Aktion kann nicht rückgängig gemacht werden.`
    );
    if (!bestaetigt) return;
    setLaeuft(true);
    setFehler("");
    try {
      await api.mailLoeschen(mail.id);
      await onGeloescht();
    } catch (e) {
      setFehler(e.message);
    } finally {
      setLaeuft(false);
    }
  }

  return (
    <div className="flex items-center gap-1.5">
      {fehler && <span title={fehler} style={{ ...fontUI, fontSize: "11px", color: tokens.rust }}>Löschen fehlgeschlagen</span>}
      <button
        onClick={loeschen}
        disabled={laeuft}
        title={laeuft ? "Mail wird gelöscht …" : "Mail dauerhaft aus dem Postfach löschen"}
        aria-label="Mail löschen"
        className="flex items-center justify-center w-8 h-8 disabled:opacity-50"
        style={{ color: tokens.rust, border: `1px solid ${tokens.rust}`, borderRadius: "6px", background: tokens.rustPale }}
      >
        <Trash2 size={13} />
      </button>
    </div>
  );
}

function ZuweisenButton({ mail, onZugewiesen }) {
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState("");

  async function zuweisen(rolle) {
    if (!rolle) return;
    setLaeuft(true);
    setFehler("");
    try {
      await api.mailZuweisen(mail.id, rolle);
      await onZugewiesen();
    } catch (e) {
      setFehler(e.message);
    } finally {
      setLaeuft(false);
    }
  }

  const aktuelleRolle = mail.zustaendigAdmin !== mail.zustaendigSachbearbeiter
    ? (mail.zustaendigAdmin ? "admin" : "sachbearbeiter")
    : "";
  return (
    <div className="flex items-center gap-1.5">
      {fehler && <span title={fehler} style={{ ...fontUI, fontSize: "11px", color: tokens.rust }}>Zuweisung fehlgeschlagen</span>}
      <AuswahlMenue
        label={laeuft ? "Wird zugewiesen …" : "Zuweisen"}
        title={`Derzeit zuständig: ${mail.zustaendigkeitLabel}`}
        icon={UserRound}
        wert={aktuelleRolle}
        deaktiviert={laeuft}
        optionen={[
          ...(mail.zuweisbareRollen.includes("admin")
            ? [{ value: "admin", label: "Erik (Admin)" }]
            : []),
          ...(mail.zuweisbareRollen.includes("sachbearbeiter")
            ? [{ value: "sachbearbeiter", label: "Guri, Ludwig (Sachbearbeiter)" }]
            : []),
        ]}
        onWaehlen={zuweisen}
      />
    </div>
  );
}

function AntwortAktionen({ mail, onErzeugt }) {
  const [laufendeAktion, setLaufendeAktion] = useState("");
  const [fehler, setFehler] = useState("");
  const istKundenservice = String(mail.kat || "").toUpperCase() === "KUNDENSERVICE";

  async function ausfuehren(aktion) {
    setLaufendeAktion(aktion);
    setFehler("");
    try {
      if (aktion === "vorschlag") await api.antwortentwurfErzeugen(mail.id);
      else await api.antwortBeginnen(mail.id);
      await onErzeugt();
    } catch (e) {
      setFehler(e.message);
    } finally {
      setLaufendeAktion("");
    }
  }

  return (
    <div className="flex flex-wrap items-center justify-center gap-2">
      {fehler && <span title={fehler} style={{ ...fontUI, fontSize: "11px", color: tokens.rust }}>Entwurf konnte nicht geöffnet werden</span>}
      {istKundenservice && (
        <button
          onClick={() => ausfuehren("vorschlag")}
          disabled={Boolean(laufendeAktion) || Boolean(mail.entwurf)}
          title="Antwortvorschlag mit dem dreikraut-Stilprofil erstellen"
          className="flex items-center gap-1.5 px-3 py-2 disabled:opacity-50"
          style={{ ...fontUI, fontSize: "13px", fontWeight: 600, color: tokens.mossDeep, border: `1px solid ${tokens.moss}`, borderRadius: "6px" }}
        >
          <Sparkles size={14} /> {laufendeAktion === "vorschlag" ? "Wird erstellt …" : "Vorschlag generieren"}
        </button>
      )}
      <button
        onClick={() => ausfuehren("antwort")}
        disabled={Boolean(laufendeAktion) || Boolean(mail.entwurf)}
        title="Leeren Antwortentwurf ohne KI-Vorschlag öffnen"
        className="flex items-center gap-1.5 px-3 py-2 disabled:opacity-50"
        style={{ ...fontUI, fontSize: "13px", fontWeight: 600, color: "#fff", background: tokens.moss, borderRadius: "6px" }}
      >
        <PenLine size={14} /> {laufendeAktion === "antwort" ? "Wird geöffnet …" : "Antworten"}
      </button>
    </div>
  );
}

function PosteingangView({ mails, katalog, benutzer, alleMails, onAlleMailsAendern, onReload }) {
  const [filter, setFilter] = useState(null);
  const [suchbegriff, setSuchbegriff] = useState("");
  const [selectedId, setSelectedId] = useState(mails[0]?.id ?? null);
  const [versandbestaetigungen, setVersandbestaetigungen] = useState({});
  const [mobileDetailOffen, setMobileDetailOffen] = useState(false);

  const kategorien = useMemo(() => [...new Set(mails.map((m) => m.kat))], [mails]);
  const kategorieGefiltert = filter ? mails.filter((m) => m.kat === filter) : mails;
  const suchtreffer = suchbegriff.trim().toLowerCase();
  const sichtbar = suchtreffer
    ? kategorieGefiltert.filter((m) => {
        const felderText = Object.values(m.felder || {}).join(" ");
        const text = [m.betreff, m.absender, m.absenderAdresse, m.snippet, m.katId, felderText]
          .filter(Boolean).join(" ").toLowerCase();
        return text.includes(suchtreffer);
      })
    : kategorieGefiltert;
  const selected = mails.find((m) => m.id === selectedId) ?? sichtbar[0] ?? null;
  const vorherigeMailIds = useRef(mails.map((m) => m.id));

  // Verschwindet die ausgewählte Mail aus der Liste (verschoben, gelöscht,
  // Zuständigkeit geändert …), auf den Nachfolger an ihrer alten Position
  // springen statt immer zurück zum ersten Eintrag.
  useEffect(() => {
    const vorherige = vorherigeMailIds.current;
    const nochVorhanden = mails.some((m) => m.id === selectedId);

    if (!nochVorhanden && selectedId != null) {
      const alterIndex = vorherige.indexOf(selectedId);
      if (alterIndex !== -1) {
        const sichtbarIds = new Set(sichtbar.map((m) => m.id));
        let naechsteAuswahl = null;
        for (let i = alterIndex + 1; i < vorherige.length; i++) {
          if (sichtbarIds.has(vorherige[i])) { naechsteAuswahl = vorherige[i]; break; }
        }
        if (naechsteAuswahl == null) {
          for (let i = alterIndex - 1; i >= 0; i--) {
            if (sichtbarIds.has(vorherige[i])) { naechsteAuswahl = vorherige[i]; break; }
          }
        }
        setSelectedId(naechsteAuswahl);
      }
    }

    vorherigeMailIds.current = mails.map((m) => m.id);
    // sichtbar bewusst nicht in den Deps: soll nur auf echte Mail-Reloads
    // reagieren, nicht auf lokale Filter-Wechsel.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mails]);

  useEffect(() => {
    if (filter && !kategorien.includes(filter)) setFilter(null);
  }, [filter, kategorien]);

  useEffect(() => {
    if (!selected) setMobileDetailOffen(false);
  }, [selected]);

  function mailOeffnen(id) {
    setSelectedId(id);
    setMobileDetailOffen(true);
  }

  async function aktionAbschliessen() {
    setMobileDetailOffen(false);
    await onReload();
  }

  async function anhangAnsehen(mailId, index) {
    const fenster = window.open("about:blank", "_blank");
    if (fenster) fenster.opener = null;
    try {
      const datei = await api.mailAnhangLaden(mailId, index);
      const url = URL.createObjectURL(datei);
      if (fenster) {
        fenster.location.href = url;
      } else {
        window.open(url, "_blank", "noopener,noreferrer");
      }
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (fehler) {
      if (fenster) fenster.close();
      window.alert(fehler.message || "Anhang konnte nicht geöffnet werden.");
    }
  }

  return (
    <div className="flex flex-1 min-h-0 mail-layout">
      <div className={`flex flex-col mail-list-panel ${mobileDetailOffen ? "mobile-hidden" : ""}`} style={{ width: "380px", borderRight: `1px solid ${tokens.line}` }}>
        <div className="flex items-center gap-2 px-4 py-3" style={{ borderBottom: `1px solid ${tokens.line}` }}>
          <Search size={14} style={{ color: tokens.inkMuted, flexShrink: 0 }} />
          <input
            type="text"
            value={suchbegriff}
            onChange={(e) => setSuchbegriff(e.target.value)}
            placeholder="Mails durchsuchen …"
            className="flex-1 min-w-0"
            style={{ ...fontUI, fontSize: "13px", color: tokens.ink, background: "transparent", border: "none", outline: "none" }}
          />
          {suchbegriff && (
            <button onClick={() => setSuchbegriff("")} aria-label="Suche zurücksetzen" style={{ color: tokens.inkMuted, flexShrink: 0 }}>
              <X size={13} />
            </button>
          )}
          {benutzer.rolle === "admin" && (
            <div className="flex items-center rounded-md overflow-hidden" style={{ border: `1px solid ${tokens.line}` }}>
              <button
                onClick={() => onAlleMailsAendern(false)}
                className="px-2 py-1"
                style={{ ...fontMono, fontSize: "9.5px", background: !alleMails ? tokens.mossDeep : tokens.paperRaised, color: !alleMails ? "#fff" : tokens.inkMuted }}
              >MEINE</button>
              <button
                onClick={() => onAlleMailsAendern(true)}
                className="px-2 py-1"
                style={{ ...fontMono, fontSize: "9.5px", background: alleMails ? tokens.mossDeep : tokens.paperRaised, color: alleMails ? "#fff" : tokens.inkMuted, borderLeft: `1px solid ${tokens.line}` }}
              >ALLE MAILS</button>
            </div>
          )}
        </div>
        <div className="flex items-center gap-1.5 px-4 py-2 overflow-x-auto" style={{ borderBottom: `1px solid ${tokens.line}` }}>
          <button onClick={() => setFilter(null)} className="px-2 py-1 rounded-full shrink-0"
            style={{ ...fontMono, fontSize: "11px", background: !filter ? tokens.mossDeep : "transparent", color: !filter ? "#fff" : tokens.inkMuted, border: `1px solid ${!filter ? tokens.mossDeep : tokens.line}` }}>
            ALLE
          </button>
          {kategorien.map((k) => (
            <button key={k} onClick={() => setFilter(k)} className="px-2 py-1 rounded-full shrink-0"
              style={{ ...fontMono, fontSize: "11px", background: filter === k ? tokens.mossDeep : "transparent", color: filter === k ? "#fff" : tokens.inkMuted, border: `1px solid ${filter === k ? tokens.mossDeep : tokens.line}` }}>
              {k.toUpperCase()}
            </button>
          ))}
        </div>
        <div className="flex-1 overflow-y-auto">
          {sichtbar.map((m) => (
            <button key={m.id} onClick={() => mailOeffnen(m.id)} className="w-full text-left px-4 py-3 flex flex-col gap-1.5"
              style={{ borderBottom: `1px solid ${tokens.line}`, background: selected?.id === m.id ? tokens.mossPale : "transparent" }}>
              <div className="flex items-center justify-between gap-2">
                <Badge label={m.katId} color={farbeFuerKategorie(m.kat)} />
                <span className="whitespace-nowrap" style={{ ...fontMono, fontSize: "11px", color: tokens.inkMuted }}>{m.zeit}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span style={{ ...fontSerif, fontSize: "14px", fontWeight: 600 }}>{m.absender}</span>
                {m.anhaenge.length > 0 && (
                  <Paperclip size={11} style={{ color: tokens.inkMuted, flexShrink: 0 }} />
                )}
              </div>
              <div style={{ ...fontSerif, fontSize: "13.5px" }}>{m.betreff}</div>
              <Konfidenz value={m.konfidenz} />
            </button>
          ))}
          {mails.length === 0 && (
            <div className="px-5 py-10 text-center" style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted }}>
              {alleMails
                ? "Keine Mails im Krautl-Posteingang."
                : "Der Posteingang für Deine Rolle ist leer."}
            </div>
          )}
        </div>
      </div>

      <div className={`flex-1 flex flex-col overflow-y-auto mail-detail-panel ${mobileDetailOffen ? "mobile-visible" : ""}`}>
        {selected && (
          <>
            <div className="px-6 pt-5 pb-4 mail-detail-header" style={{ borderBottom: `1px solid ${tokens.line}` }}>
              <button type="button" onClick={() => setMobileDetailOffen(false)} className="mobile-back-button items-center gap-1.5 mb-3 px-2.5 py-1.5" style={AUSWAHL_BUTTON_STIL}>
                <ArrowLeft size={14} /> Zur Mail-Liste
              </button>
              <div className="flex items-center justify-between gap-3 mail-detail-toolbar">
                <div className="flex items-center gap-3 mail-detail-meta">
                  <Badge label={selected.katId} color={farbeFuerKategorie(selected.kat)} />
                  <span style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted }}>
                    {selected.zielhinweis}
                  </span>
                  <span className="flex items-center gap-1" style={{ ...fontUI, fontSize: "11.5px", color: tokens.inkMuted }}>
                    <UserRound size={12} /> {selected.zustaendigkeitLabel}
                  </span>
                </div>
                <div className="flex flex-wrap items-center justify-end gap-2 mail-detail-actions">
                  <BestaetigenButton mail={selected} onBestaetigt={aktionAbschliessen} />
                  <ZuweisenButton mail={selected} onZugewiesen={aktionAbschliessen} />
                  <KategorieKorrektur mail={selected} katalog={katalog} onKorrigiert={onReload} />
                  <MailLoeschenButton mail={selected} onGeloescht={aktionAbschliessen} />
                </div>
              </div>
              <h2 style={{ ...fontDisplay, fontSize: "19px", marginTop: "12px" }}>{selected.betreff}</h2>
              <div style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted, marginTop: "4px" }}>
                {selected.absender}
                {selected.absenderAdresse && selected.absenderAdresse !== selected.absender
                  ? ` <${selected.absenderAdresse}>`
                  : ""}
                {` · ${selected.zeit}`}
              </div>
              {selected.antwortAnAdresse && (
                <div style={{ ...fontUI, fontSize: "12px", color: tokens.amber, marginTop: "2px", fontWeight: 600 }}>
                  Antworten gehen an: {selected.antwortAnAdresse} (abweichend vom Absender)
                </div>
              )}
            </div>
            <div className="px-6 py-4 mail-body" style={{ ...fontSerif, fontSize: "15px", lineHeight: 1.65, whiteSpace: "pre-wrap", overflowWrap: "anywhere", borderBottom: `1px solid ${tokens.line}` }}>{selected.snippet}</div>
            {Object.keys(selected.felder).length > 0 && (
              <div className="px-6 py-4 grid grid-cols-2 gap-3 mail-fields" style={{ borderBottom: `1px solid ${tokens.line}` }}>
                {Object.entries(selected.felder).map(([k, v]) => (
                  <div key={k}>
                    <div style={{ ...fontMono, fontSize: "10.5px", color: tokens.inkMuted, letterSpacing: "0.05em" }}>{k.toUpperCase()}</div>
                    <div style={{ ...fontUI, fontSize: "13.5px", fontWeight: 600, marginTop: "2px" }}>{v}</div>
                  </div>
                ))}
              </div>
            )}
            {selected.anhaenge.length > 0 && (
              <div className="px-6 py-4 flex flex-wrap gap-2 mail-anhaenge" style={{ borderBottom: `1px solid ${tokens.line}` }}>
                {selected.anhaenge.map((dateiname, index) => (
                  <button key={`${dateiname}-${index}`} onClick={() => anhangAnsehen(selected.id, index)}
                    className="flex items-center gap-1.5 px-2.5 py-1.5" style={{ ...fontUI, fontSize: "12.5px", color: tokens.ink, background: tokens.paperRaised, border: `1px solid ${tokens.line}`, borderRadius: "6px" }}>
                    <Paperclip size={12} style={{ color: tokens.inkMuted, flexShrink: 0 }} />
                    {dateiname}
                  </button>
                ))}
              </div>
            )}
            {selected.entwurf ? (
              <EntwurfPanel
                key={selected.entwurf.id}
                entwurf={selected.entwurf}
                kiPruefung={String(selected.kat || "").toUpperCase() === "KUNDENSERVICE"}
                onErledigt={onReload}
                onVersendet={(ergebnis) => setVersandbestaetigungen((alt) => ({
                  ...alt,
                  [selected.id]: ergebnis,
                }))}
              />
            ) : versandbestaetigungen[selected.id] ? (
              <div className="px-6 py-6 flex-1">
                <div className="px-3 py-2.5" style={{ background: tokens.mossPale, border: `1px solid ${tokens.moss}`, borderRadius: "6px" }}>
                  <div style={{ ...fontUI, fontSize: "12.5px", fontWeight: 600, color: tokens.mossDeep }}>
                    Antwort an den Mailserver übergeben
                  </div>
                  <div style={{ ...fontUI, fontSize: "12px", color: tokens.inkMuted, marginTop: "3px" }}>
                    Empfänger: {versandbestaetigungen[selected.id].empfaenger}<br />
                    BCC: {versandbestaetigungen[selected.id].bcc}<br />
                    SMTP-Nachrichten-ID: {versandbestaetigungen[selected.id].messageId}
                  </div>
                </div>
              </div>
            ) : (
              <div className="px-6 py-8 flex-1 flex flex-col items-center justify-center gap-3" style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted }}>
                <span>Noch keine Antwort begonnen.</span>
                <AntwortAktionen mail={selected} onErzeugt={onReload} />
              </div>
            )}
          </>
        )}
        {!selected && (
          <div className="flex-1 flex items-center justify-center" style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted }}>
            {alleMails
              ? "Keine Mails im Krautl-Posteingang."
              : "Für Deine Rolle wartet gerade keine Mail."}
          </div>
        )}
      </div>
    </div>
  );
}

function EntwurfPanel({ entwurf, kiPruefung, onErledigt, onVersendet }) {
  const [text, setText] = useState(entwurf.text);
  const [prueft, setPrueft] = useState(false);
  const [probleme, setProbleme] = useState([]);
  const [fehler, setFehler] = useState("");
  const [naechsterOhnePruefung, setNaechsterOhnePruefung] = useState(false);
  const [versanderfolg, setVersanderfolg] = useState(null);

  async function freigeben() {
    setPrueft(true);
    setProbleme([]);
    setFehler("");
    setVersanderfolg(null);
    try {
      const ergebnis = await api.entwurfFreigeben(entwurf.id, text);
      if (ergebnis.status === "pruefung_noetig") {
        setProbleme(ergebnis.probleme ?? ["Die Antwort benötigt noch eine Prüfung."]);
        setNaechsterOhnePruefung(Boolean(ergebnis.naechster_versuch_ohne_pruefung));
      } else {
        setVersanderfolg({
          empfaenger: ergebnis.empfaenger,
          bcc: ergebnis.bcc,
          messageId: ergebnis.message_id,
        });
        onVersendet({
          empfaenger: ergebnis.empfaenger,
          bcc: ergebnis.bcc,
          messageId: ergebnis.message_id,
        });
        await onErledigt();
      }
    } catch (e) {
      setFehler(e.message);
    } finally {
      setPrueft(false);
    }
  }
  async function verwerfen() {
    await api.entwurfVerwerfen(entwurf.id);
    await onErledigt();
  }

  return (
    <div className="px-6 py-4 flex-1 flex flex-col entwurf-panel">
      <div style={{ ...fontMono, fontSize: "10.5px", color: tokens.amber, letterSpacing: "0.05em" }}>ANTWORTENTWURF · WARTET AUF FREIGABE</div>
      <textarea value={text} onChange={(e) => setText(e.target.value)} className="mt-2 flex-1 p-3 resize-none"
        style={{ ...fontSerif, fontSize: "14.5px", background: tokens.paperRaised, border: `1px solid ${tokens.line}`, borderRadius: "6px", minHeight: "320px" }} />
      {probleme.length > 0 && (
        <div className="mt-3 px-3 py-2.5" style={{ background: tokens.amberPale, border: `1px solid ${tokens.amber}`, borderRadius: "6px" }}>
          <div style={{ ...fontUI, fontSize: "12.5px", fontWeight: 600, color: tokens.ink }}>
            Vor dem Versand bitte noch bearbeiten:
          </div>
          <ul className="mt-1 pl-5" style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted, listStyle: "disc" }}>
            {probleme.map((problem, index) => <li key={index}>{problem}</li>)}
          </ul>
        </div>
      )}
      {naechsterOhnePruefung && (
        <div className="mt-3 px-3 py-2.5" style={{ background: tokens.rustPale, border: `1px solid ${tokens.rust}`, borderRadius: "6px" }}>
          <div style={{ ...fontUI, fontSize: "12.5px", fontWeight: 600, color: tokens.rust }}>
            Die Kontroll-KI hat diesen Entwurf zweimal blockiert.
          </div>
          <div style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted, marginTop: "3px" }}>
            Der nächste Klick versendet die Antwort ohne eine weitere KI-Prüfung.
          </div>
        </div>
      )}
      {fehler && (
        <div className="mt-3" style={{ ...fontUI, fontSize: "12px", color: tokens.rust }}>{fehler}</div>
      )}
      {versanderfolg && (
        <div className="mt-3 px-3 py-2.5" style={{ background: tokens.mossPale, border: `1px solid ${tokens.moss}`, borderRadius: "6px" }}>
          <div style={{ ...fontUI, fontSize: "12.5px", fontWeight: 600, color: tokens.mossDeep }}>
            Antwort an den Mailserver übergeben
          </div>
          <div style={{ ...fontUI, fontSize: "12px", color: tokens.inkMuted, marginTop: "3px" }}>
            Empfänger: {versanderfolg.empfaenger}<br />
            BCC: {versanderfolg.bcc}<br />
            SMTP-Nachrichten-ID: {versanderfolg.messageId}
          </div>
        </div>
      )}
      <div className="flex items-center gap-2 mt-3">
        <button onClick={freigeben} disabled={prueft || Boolean(versanderfolg)} className="flex items-center gap-1.5 px-3 py-2 disabled:opacity-60" style={{ ...fontUI, fontSize: "13px", fontWeight: 600, color: "#fff", background: tokens.moss, borderRadius: "6px" }}>
          <Check size={13} /> {prueft
            ? (!kiPruefung || naechsterOhnePruefung ? "Antwort wird versendet …" : "Antwort wird geprüft …")
            : (versanderfolg
              ? "An Mailserver übergeben"
              : (naechsterOhnePruefung ? "Trotzdem senden" : "Antwort freigeben"))}
        </button>
        <button onClick={verwerfen} className="flex items-center gap-1.5 px-3 py-2" style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted, border: `1px solid ${tokens.line}`, borderRadius: "6px" }}>
          <X size={13} /> Verwerfen
        </button>
      </div>
      <div style={{ ...fontUI, fontSize: "11.5px", color: tokens.inkMuted, marginTop: "8px" }}>
        {kiPruefung
          ? "Vor dem Versand prüft die KI die Antwort auf offene Punkte. Die Antwort geht an den Absender der Kundenmail, eine Kontrollkopie per BCC an info@erikschweitzer.de."
          : "Diese Antwort wird ohne inhaltliche KI-Prüfung an den Absender versendet. Eine Kontrollkopie geht per BCC an info@erikschweitzer.de."}
      </div>
    </div>
  );
}

function RechnungenView({ rechnungen, onReload }) {
  const offen = rechnungen.filter((r) => ["offen", "unklar"].includes(r.zahlungsstatus));
  const erledigt = rechnungen.filter((r) => !["offen", "unklar"].includes(r.zahlungsstatus));

  const statusTexte = {
    offen: "Offen – Überweisung nötig",
    unklar: "Unklar – bitte prüfen",
    automatisch: "Automatisch / verrechnet",
    bezahlt: "Bezahlt",
    gutschrift: "Gutschrift",
  };

  async function statusAendern(id, zahlungsstatus) {
    await api.rechnungStatusAendern(id, zahlungsstatus);
    await onReload();
  }

  async function rechnungAnsehen(rechnung) {
    const fenster = window.open("about:blank", "_blank");
    if (fenster) fenster.opener = null;
    try {
      const datei = await api.rechnungDateiLaden(rechnung.id);
      const url = URL.createObjectURL(datei);
      if (fenster) {
        fenster.location.href = url;
      } else {
        window.open(url, "_blank", "noopener,noreferrer");
      }
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (fehler) {
      if (fenster) fenster.close();
      window.alert(fehler.message || "Rechnung konnte nicht geöffnet werden.");
    }
  }

  const statusAuswahl = (rechnung) => <select
    value={rechnung.zahlungsstatus}
    onChange={(e) => statusAendern(rechnung.id, e.target.value)}
    className="px-2 py-1.5"
    style={{ ...fontUI, width: "100%", minWidth: 0, fontSize: "12px", color: tokens.mossDeep, background: tokens.paperRaised, border: `1px solid ${tokens.line}`, borderRadius: "6px" }}
  >{Object.entries(statusTexte).map(([wert, text]) => <option key={wert} value={wert}>{text}</option>)}</select>;

  const ansichtButton = (rechnung) => <button
    type="button"
    onClick={() => rechnungAnsehen(rechnung)}
    className="flex shrink-0 items-center gap-1 px-2 py-1.5"
    style={{ ...fontUI, fontSize: "12px", color: tokens.mossDeep, background: tokens.paperRaised, border: `1px solid ${tokens.line}`, borderRadius: "6px", textDecoration: "none" }}
    title="Rechnungsoriginal in einem neuen Tab ansehen"
  >
    <Eye size={13} /> Ansehen
  </button>;

  return (
    <div className="flex-1 overflow-y-auto px-8 py-6 content-view rechnungen-view">
      <h2 style={{ ...fontDisplay, fontSize: "20px", color: tokens.mossDeep, marginBottom: "4px" }}>Offene Rechnungen</h2>
      <div className="flex items-center gap-1.5 mb-5" style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted }}>
        <FolderCog size={13} />
        Rechnungsoriginale werden automatisch abgelegt unter <span style={{ ...fontMono, fontSize: "11.5px" }}>/Rechnungen/{"{Jahr}"}/</span>. Automatisch bezahlte Rechnungen und Gutschriften erscheinen hier nicht.
      </div>

      <div className="invoice-table" style={{ border: `1px solid ${tokens.line}`, borderRadius: "8px", overflow: "hidden", background: tokens.paperRaised }}>
        <div className="grid px-4 py-2.5 invoice-table-head" style={{ gridTemplateColumns: "1fr 1.4fr .9fr .8fr .8fr 1.45fr", ...fontMono, fontSize: "10.5px", color: tokens.inkMuted, letterSpacing: "0.05em", borderBottom: `1px solid ${tokens.line}` }}>
          <div>EINGEGANGEN</div><div>AUSSTELLER</div><div>RECHNUNG-NR.</div><div>BETRAG</div><div>FÄLLIG AM</div><div>ZAHLUNGSSTATUS</div>
        </div>
        {offen.map((r) => (
          <div key={r.id} className="grid items-center px-4 py-3 invoice-row" style={{ gridTemplateColumns: "1fr 1.4fr .9fr .8fr .8fr 1.45fr", borderBottom: `1px solid ${tokens.line}` }}>
            <div className="invoice-date" style={{ ...fontMono, fontSize: "11.5px", color: tokens.inkMuted }}>{formatRechnungseingang(r.eingegangen_am)}</div>
            <div>
              <div style={{ ...fontSerif, fontSize: "14.5px", fontWeight: 600 }}>{r.aussteller}</div>
              <span title={r.zahlungshinweis || "Kein Zahlungshinweis erkannt"} style={{ ...fontUI, fontSize: "11px", color: r.zahlungsstatus === "unklar" ? tokens.rust : tokens.inkMuted }}>{r.zahlungshinweis || "Kein Zahlungshinweis erkannt"}</span>
            </div>
            <div style={{ ...fontMono, fontSize: "12.5px", color: tokens.inkMuted }}>{r.rechnungsnummer}</div>
            <div style={{ ...fontMono, fontSize: "13px" }}>{formatBetrag(r.bruttobetrag, r.waehrung)}</div>
            <div style={{ ...fontUI, fontSize: "13px", color: tokens.amber, fontWeight: 600 }}>{formatDatum(r.faellig_am)}</div>
            <div className="flex items-center gap-2 invoice-actions">
              {statusAuswahl(r)}
              {ansichtButton(r)}
            </div>
          </div>
        ))}
        {offen.length === 0 && (
          <div className="px-4 py-6 text-center" style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted }}>Keine offenen Rechnungen.</div>
        )}
      </div>

      <h3 className="mt-7 mb-3" style={{ ...fontDisplay, fontSize: "15px", color: tokens.inkMuted }}>Erledigt / kein manueller Zahlungsvorgang</h3>
      <div className="invoice-table" style={{ border: `1px solid ${tokens.line}`, borderRadius: "8px", overflow: "hidden", background: tokens.paperRaised }}>
        <div className="grid px-3 py-2.5 invoice-table-head" style={{ gridTemplateColumns: "1fr 1.8fr .9fr .8fr 1.55fr", ...fontMono, fontSize: "10.5px", color: tokens.inkMuted, letterSpacing: "0.05em", borderBottom: `1px solid ${tokens.line}` }}>
          <div>EINGEGANGEN</div><div>RECHNUNG</div><div>STATUS</div><div>BETRAG</div><div>ZAHLUNGSSTATUS</div>
        </div>
        {erledigt.map((r) => (
          <div key={r.id} className="grid items-center px-3 py-2 invoice-row invoice-row-done" style={{ gridTemplateColumns: "1fr 1.8fr .9fr .8fr 1.55fr", ...fontUI, fontSize: "13px", color: tokens.inkMuted, borderBottom: `1px solid ${tokens.line}` }}>
            <span className="invoice-date" style={{ ...fontMono, fontSize: "11.5px" }}>{formatRechnungseingang(r.eingegangen_am)}</span>
            <span className="flex items-center gap-2"><CheckCircle2 size={14} style={{ color: tokens.moss }} />{r.aussteller} · {r.rechnungsnummer}</span>
            <span title={r.zahlungshinweis || ""} style={{ fontSize: "11px" }}>{statusTexte[r.zahlungsstatus] || r.zahlungsstatus}</span>
            <span style={{ ...fontMono, fontSize: "12px" }}>{formatBetrag(r.bruttobetrag, r.waehrung)}</span>
            <div className="flex items-center gap-2 invoice-actions">
              {statusAuswahl(r)}
              {ansichtButton(r)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function WissensdatenbankView({ faqEintraege, faqVorschlaege, onReload }) {
  const gruppen = [...new Set(faqEintraege.map((f) => f.kategorie))];

  async function uebernehmen(id) {
    await api.faqVorschlagUebernehmen(id);
    await onReload();
  }
  async function verwerfen(id) {
    await api.faqVorschlagVerwerfen(id);
    await onReload();
  }

  return (
    <div className="flex-1 overflow-y-auto px-8 py-6">
      <div className="flex items-center gap-2 mb-1">
        <Sparkles size={16} style={{ color: tokens.amber }} />
        <h2 style={{ ...fontDisplay, fontSize: "20px", color: tokens.mossDeep }}>Vorschläge aus Kundenanfragen</h2>
      </div>
      <p className="mb-4" style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted }}>
        Fragen, die im FAQ noch nicht behandelt sind — nichts wird ohne Bestätigung veröffentlicht.
      </p>
      <div className="flex flex-col gap-3 mb-8">
        {faqVorschlaege.map((v) => (
          <div key={v.id} className="p-4" style={{ background: tokens.paperRaised, border: `1px solid ${tokens.line}`, borderLeft: `4px solid ${tokens.amber}`, borderRadius: "6px" }}>
            <div className="flex items-center justify-between mb-2">
              <Badge label={v.kategorie.toUpperCase()} color={tokens.amber} />
              <span style={{ ...fontMono, fontSize: "11px", color: tokens.inkMuted }}>Quelle: {v.quelle}</span>
            </div>
            <div style={{ ...fontSerif, fontSize: "15px", fontWeight: 600, marginBottom: "6px" }}>{v.frage}</div>
            <div style={{ ...fontSerif, fontSize: "14px", color: tokens.ink, lineHeight: 1.55 }}>{v.entwurf}</div>
            <div className="flex items-center gap-2 mt-3">
              <button onClick={() => uebernehmen(v.id)} className="flex items-center gap-1.5 px-3 py-1.5" style={{ ...fontUI, fontSize: "12.5px", fontWeight: 600, color: "#fff", background: tokens.moss, borderRadius: "6px" }}>
                <Check size={12} /> Ins FAQ übernehmen
              </button>
              <button onClick={() => verwerfen(v.id)} className="flex items-center gap-1.5 px-3 py-1.5" style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted, border: `1px solid ${tokens.line}`, borderRadius: "6px" }}>
                <X size={12} /> Verwerfen
              </button>
            </div>
          </div>
        ))}
        {faqVorschlaege.length === 0 && (
          <div style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted }}>Keine offenen Vorschläge.</div>
        )}
      </div>

      <h2 style={{ ...fontDisplay, fontSize: "17px", marginBottom: "12px" }}>Bestehendes FAQ</h2>
      {gruppen.map((g) => (
        <div key={g} className="mb-4">
          <div style={{ ...fontMono, fontSize: "10.5px", color: tokens.inkMuted, letterSpacing: "0.05em", marginBottom: "6px" }}>{g.toUpperCase()}</div>
          {faqEintraege.filter((f) => f.kategorie === g).map((f) => (
            <div key={f.id} className="py-2.5" style={{ borderBottom: `1px solid ${tokens.line}` }}>
              <div style={{ ...fontSerif, fontSize: "14.5px", fontWeight: 600 }}>{f.frage}</div>
              <div style={{ ...fontSerif, fontSize: "14px", color: tokens.inkMuted, marginTop: "2px" }}>{f.antwort}</div>
            </div>
          ))}
        </div>
      ))}
      {faqEintraege.length === 0 && (
        <div style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted }}>Noch keine FAQ-Einträge.</div>
      )}
    </div>
  );
}

function RollenMailzugriffView({ konfiguration, onReload }) {
  const sachbearbeiter = konfiguration.rollen.find((r) => r.id === "sachbearbeiter");
  const admin = konfiguration.rollen.find((r) => r.id === "admin");
  const [auswahl, setAuswahl] = useState(() => new Set(sachbearbeiter?.klassifikation_ids || []));
  const [speichert, setSpeichert] = useState(false);
  const [meldung, setMeldung] = useState("");
  const gruppen = useMemo(() => {
    const ergebnis = {};
    for (const k of konfiguration.klassifikationen) {
      (ergebnis[k.hauptkategorie] ||= []).push(k);
    }
    return ergebnis;
  }, [konfiguration]);

  useEffect(() => {
    setAuswahl(new Set(sachbearbeiter?.klassifikation_ids || []));
  }, [sachbearbeiter?.klassifikation_ids?.join("|")]);

  function umschalten(id) {
    setAuswahl((alt) => {
      const neu = new Set(alt);
      if (neu.has(id)) neu.delete(id); else neu.add(id);
      return neu;
    });
    setMeldung("");
  }

  function gruppeSetzen(klassifikationen, erlaubt) {
    setAuswahl((alt) => {
      const neu = new Set(alt);
      for (const k of klassifikationen) {
        if (erlaubt) neu.add(k.klassifikation_id); else neu.delete(k.klassifikation_id);
      }
      return neu;
    });
  }

  async function speichern() {
    setSpeichert(true); setMeldung("");
    try {
      await api.rollenMailzugriffSpeichern("sachbearbeiter", [...auswahl]);
      setMeldung("Mailzugriff gespeichert.");
      await onReload();
    } catch (fehler) {
      setMeldung(`Speichern fehlgeschlagen: ${fehler.message}`);
    } finally { setSpeichert(false); }
  }

  const nutzerNamen = (rolle) => (rolle?.benutzer || []).map((b) => b.name).join(", ");
  return <div className="flex-1 overflow-y-auto px-8 py-6 content-view rollen-view">
    <h2 style={{ ...fontDisplay, fontSize: "20px", color: tokens.mossDeep }}>Rollen & Mailzugriff</h2>
    <p className="mb-5" style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted }}>
      Admins sehen und bearbeiten alle Mailarten. Für Sachbearbeiter legen Sie die sichtbaren Klassifikationen fest.
    </p>
    <div className="grid grid-cols-2 gap-3 mb-6 rollen-summary">
      <div className="p-4" style={{ background: tokens.paperRaised, border: `1px solid ${tokens.line}`, borderLeft: `4px solid ${tokens.moss}`, borderRadius: "7px" }}>
        <div className="flex items-center gap-2"><ShieldCheck size={15} color={tokens.moss}/><b style={fontSerif}>Admin</b></div>
        <div className="mt-1" style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted }}>{nutzerNamen(admin)} · alle Mailarten</div>
      </div>
      <div className="p-4" style={{ background: tokens.paperRaised, border: `1px solid ${tokens.line}`, borderLeft: `4px solid ${tokens.amber}`, borderRadius: "7px" }}>
        <div className="flex items-center gap-2"><UserRound size={15} color={tokens.amber}/><b style={fontSerif}>Sachbearbeiter</b></div>
        <div className="mt-1" style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted }}>{nutzerNamen(sachbearbeiter)} · {auswahl.size} von {konfiguration.klassifikationen.length} Mailarten</div>
      </div>
    </div>
    <div className="grid grid-cols-2 gap-4 rollen-grid">
      {Object.entries(gruppen).map(([gruppe, klassifikationen]) => {
        const alle = klassifikationen.every((k) => auswahl.has(k.klassifikation_id));
        return <div key={gruppe} className="p-4" style={{ background: tokens.paperRaised, border: `1px solid ${tokens.line}`, borderRadius: "7px" }}>
          <div className="flex items-center justify-between mb-2">
            <b style={{ ...fontUI, fontSize: "12.5px", color: tokens.mossDeep }}>{gruppe}</b>
            <button onClick={() => gruppeSetzen(klassifikationen, !alle)} style={{ ...fontUI, fontSize: "11px", color: tokens.moss }}>{alle ? "Gruppe abwählen" : "Gruppe auswählen"}</button>
          </div>
          {klassifikationen.map((k) => <label key={k.klassifikation_id} className="flex items-start gap-2 py-1.5" style={{ ...fontUI, fontSize: "12px", color: tokens.ink }} title={k.beschreibung}>
            <input type="checkbox" checked={auswahl.has(k.klassifikation_id)} onChange={() => umschalten(k.klassifikation_id)} />
            <span><span style={fontMono}>{k.klassifikation_id}</span>{k.beschreibung && <span className="block" style={{ fontSize: "11px", color: tokens.inkMuted }}>{k.beschreibung}</span>}</span>
          </label>)}
        </div>;
      })}
    </div>
    <div className="flex items-center gap-3 mt-5">
      <button onClick={speichern} disabled={speichert} className="px-4 py-2" style={{ ...fontUI, fontSize: "12.5px", fontWeight: 600, color: "#fff", background: tokens.moss, borderRadius: "6px", opacity: speichert ? 0.6 : 1 }}>{speichert ? "Speichert …" : "Mailzugriff speichern"}</button>
      {meldung && <span style={{ ...fontUI, fontSize: "12.5px", color: tokens.mossDeep }}>{meldung}</span>}
    </div>
  </div>;
}

function EinstellungenMenu({ active, onWaehlen }) {
  const [offen, setOffen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    function aussenKlick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOffen(false);
    }
    document.addEventListener("mousedown", aussenKlick);
    return () => document.removeEventListener("mousedown", aussenKlick);
  }, []);

  return (
    <div className="relative settings-menu" ref={ref}>
      <button onClick={() => setOffen((o) => !o)} className="flex items-center gap-2 px-3.5 py-2.5 relative"
        style={{ ...fontUI, fontSize: "13.5px", fontWeight: active ? 600 : 500, color: active ? tokens.mossDeep : tokens.inkMuted }}>
        <Settings size={15} /> <span className="nav-label-desktop">Einstellungen</span><span className="nav-label-mobile">Mehr</span> <ChevronDown size={12} />
        {active && <span className="absolute left-0 right-0" style={{ bottom: "-1px", height: "2px", background: tokens.mossDeep }} />}
      </button>
      {offen && (
        <div className="absolute z-10 py-1 settings-dropdown" style={{ top: "100%", left: 0, minWidth: "200px", background: tokens.paperRaised, border: `1px solid ${tokens.line}`, borderRadius: "6px", boxShadow: "0 4px 12px rgba(0,0,0,0.08)" }}>
          <button onClick={() => { onWaehlen("klassifikationen"); setOffen(false); }} className="w-full text-left px-3.5 py-2"
            style={{ ...fontUI, fontSize: "13px", color: tokens.ink }}>
            Mail-Klassifikationen
          </button>
          <button onClick={() => { onWaehlen("aktionslog"); setOffen(false); }} className="w-full text-left px-3.5 py-2"
            style={{ ...fontUI, fontSize: "13px", color: tokens.ink }}>
            Aktionslog
          </button>
          <button onClick={() => { onWaehlen("rollen"); setOffen(false); }} className="w-full text-left px-3.5 py-2"
            style={{ ...fontUI, fontSize: "13px", color: tokens.ink }}>
            Rollen & Mailzugriff
          </button>
        </div>
      )}
    </div>
  );
}

function KlassifikationZeile({ klassifikation: k, onGespeichert }) {
  const fachlicheAufgaben = (k.aufgaben ?? []).map((a) => a.aufgabe_typ);
  const [zielpostfach, setZielpostfach] = useState(k.zielpostfach ?? "");
  const [zielordner, setZielordner] = useState(k.zielordner ?? "");
  const [aufgaben, setAufgaben] = useState(fachlicheAufgaben);
  const [speichert, setSpeichert] = useState(false);
  const [meldung, setMeldung] = useState("");

  function aufgabeAendern(index, wert) {
    setAufgaben((alt) => alt.map((a, i) => i === index ? wert : a));
    setMeldung("");
  }

  function aufgabeEntfernen(index) {
    setAufgaben((alt) => alt.filter((_, i) => i !== index));
    setMeldung("");
  }

  function aufgabeHinzufuegen(wert) {
    if (!wert) return;
    setAufgaben((alt) => [...alt, wert]);
    setMeldung("");
  }

  async function speichern() {
    setSpeichert(true);
    setMeldung("");
    try {
      await api.klassifikationSpeichern(k.klassifikation_id, {
        zielpostfach,
        zielordner,
        aufgaben,
      });
      setMeldung("Gespeichert");
      await onGespeichert();
    } catch (e) {
      setMeldung(e.message);
    } finally {
      setSpeichert(false);
    }
  }

  return (
    <div className="grid items-start px-4 py-3 classification-row" style={{ gridTemplateColumns: "1.3fr 1.8fr .65fr 1.25fr 2.2fr", borderBottom: `1px solid ${tokens.line}` }}>
      <div>
        <Badge label={k.klassifikation_id} color={farbeFuerKategorie(k.hauptkategorie)} />
      </div>
      <div>
        <div style={{ ...fontSerif, fontSize: "14px", fontWeight: 600 }}>{k.hauptkategorie} · {k.unterkategorie}</div>
        <div style={{ ...fontSerif, fontSize: "13px", color: tokens.inkMuted, marginTop: "2px" }}>{k.beschreibung}</div>
      </div>
      <div style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted }}>{k.standard_prio}</div>
      <div className="pr-3 flex flex-col gap-1.5">
        <input
          value={zielpostfach}
          onChange={(e) => { setZielpostfach(e.target.value); setMeldung(""); }}
          placeholder="Zielpostfach"
          style={{ ...fontUI, fontSize: "12.5px", width: "100%", padding: "6px 7px", background: tokens.paper, border: `1px solid ${tokens.line}`, borderRadius: "5px" }}
        />
        <input
          value={zielordner}
          onChange={(e) => { setZielordner(e.target.value); setMeldung(""); }}
          placeholder="Zielordner"
          style={{ ...fontUI, fontSize: "12.5px", width: "100%", padding: "6px 7px", background: tokens.paper, border: `1px solid ${tokens.line}`, borderRadius: "5px" }}
        />
      </div>
      <div className="flex flex-col gap-2">
        {aufgaben.map((aufgabe, index) => (
          <div key={index} className="flex items-center gap-2">
            <select
              value={aufgabe}
              onChange={(e) => aufgabeAendern(index, e.target.value)}
              style={{ ...fontUI, fontSize: "12.5px", flex: 1, padding: "6px 7px", background: tokens.paper, border: `1px solid ${tokens.line}`, borderRadius: "5px" }}
            >
              {!EDITIERBARE_AKTIONEN.includes(aufgabe) && (
                <option value={aufgabe} disabled>
                  {AKTION_LABEL[aufgabe] ?? aufgabe} (noch nicht implementiert)
                </option>
              )}
              {EDITIERBARE_AKTIONEN.map((aktion) => (
                <option key={aktion} value={aktion}>{AKTION_LABEL[aktion]}</option>
              ))}
            </select>
            <button
              onClick={() => aufgabeEntfernen(index)}
              title="Aktion entfernen"
              className="p-1.5"
              style={{ color: tokens.rust, border: `1px solid ${tokens.line}`, borderRadius: "5px" }}
            >
              <X size={13} />
            </button>
          </div>
        ))}
        <select
          value=""
          onChange={(e) => aufgabeHinzufuegen(e.target.value)}
          style={{ ...fontUI, fontSize: "12.5px", padding: "6px 7px", color: tokens.inkMuted, background: tokens.paperRaised, border: `1px dashed ${tokens.line}`, borderRadius: "5px" }}
        >
          <option value="">Aktion hinzufügen …</option>
          {EDITIERBARE_AKTIONEN.map((aktion) => (
            <option key={aktion} value={aktion}>{AKTION_LABEL[aktion]}</option>
          ))}
        </select>
        <div className="flex items-center gap-2">
          <button
            onClick={speichern}
            disabled={speichert}
            className="flex items-center gap-1.5 px-2.5 py-1.5"
            style={{ ...fontUI, fontSize: "12.5px", color: "#fff", background: tokens.moss, borderRadius: "5px", opacity: speichert ? .6 : 1 }}
          >
            <Check size={13} /> {speichert ? "Speichert …" : "Speichern"}
          </button>
          {meldung && (
            <span style={{ ...fontUI, fontSize: "11.5px", color: meldung === "Gespeichert" ? tokens.mossDeep : tokens.rust }}>
              {meldung}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function KlassifikationenView({ katalog, onReload }) {
  return (
    <div className="flex-1 overflow-y-auto px-8 py-6 content-view classifications-view">
      <h2 style={{ ...fontDisplay, fontSize: "20px", color: tokens.mossDeep, marginBottom: "4px" }}>Mail-Klassifikationen</h2>
      <p className="mb-5" style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted }}>
        Legt fest, wie eingehende Mails eingeordnet werden und was danach automatisch passiert.
        Zielordner und Aufgaben gelten für künftig klassifizierte Mails. {katalog.length} Einträge.
      </p>

      <div className="classification-table" style={{ border: `1px solid ${tokens.line}`, borderRadius: "8px", overflow: "hidden", background: tokens.paperRaised }}>
        <div className="grid px-4 py-2.5 classification-head" style={{ gridTemplateColumns: "1.3fr 1.8fr .65fr 1.25fr 2.2fr", ...fontMono, fontSize: "10.5px", color: tokens.inkMuted, letterSpacing: "0.05em", borderBottom: `1px solid ${tokens.line}` }}>
          <div>ID</div><div>BESCHREIBUNG</div><div>PRIO</div><div>POSTFACH / ORDNER</div><div>AKTIONEN IN REIHENFOLGE</div>
        </div>
        {katalog.map((k) => (
          <KlassifikationZeile
            key={k.klassifikation_id}
            klassifikation={k}
            onGespeichert={onReload}
          />
        ))}
        {katalog.length === 0 && (
          <div className="px-4 py-6 text-center" style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted }}>
            Noch keine Klassifikationen importiert.
          </div>
        )}
      </div>
    </div>
  );
}

function AktionslogView() {
  const [monat, setMonat] = useState("");
  const [tagImMonat, setTagImMonat] = useState("");
  const [seite, setSeite] = useState(1);
  const [proSeite, setProSeite] = useState(50);
  const [antwort, setAntwort] = useState({ eintraege: [], gesamt: 0, seite: 1, seiten: 1 });
  const [laedt, setLaedt] = useState(true);
  const [fehler, setFehler] = useState("");

  const tageImMonat = useMemo(() => {
    if (!monat) return 0;
    const [jahr, monatsnummer] = monat.split("-").map(Number);
    return new Date(jahr, monatsnummer, 0).getDate();
  }, [monat]);

  useEffect(() => {
    let aktiv = true;
    setLaedt(true);
    setFehler("");
    const tag = monat && tagImMonat
      ? `${monat}-${String(tagImMonat).padStart(2, "0")}`
      : "";
    api.aktionslog({ monat, tag, seite, proSeite })
      .then((daten) => {
        if (aktiv) setAntwort(daten);
      })
      .catch((error) => {
        if (aktiv) setFehler(error.message);
      })
      .finally(() => {
        if (aktiv) setLaedt(false);
      });
    return () => { aktiv = false; };
  }, [monat, tagImMonat, seite, proSeite]);

  const eintraege = antwort.eintraege ?? [];
  const ersterEintrag = antwort.gesamt === 0 ? 0 : (antwort.seite - 1) * antwort.pro_seite + 1;
  const letzterEintrag = Math.min(antwort.gesamt, antwort.seite * antwort.pro_seite);

  return (
    <div className="flex-1 overflow-y-auto px-8 py-6 content-view action-log-view">
      <h2 style={{ ...fontDisplay, fontSize: "20px", color: tokens.mossDeep, marginBottom: "4px" }}>Aktionslog</h2>
      <p className="mb-4" style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted }}>
        Was Krautl tatsächlich getan hat — Klassifizierungen, Bestätigungen und Verschiebe-Versuche,
        neueste zuerst.
      </p>

      <div className="action-log-filter flex items-end gap-3 mb-4" style={{ flexWrap: "wrap" }}>
        <label style={{ ...fontUI, fontSize: "11px", color: tokens.inkMuted }}>
          <span className="block mb-1">MONAT</span>
          <input
            type="month"
            value={monat}
            onChange={(event) => {
              setMonat(event.target.value);
              setTagImMonat("");
              setSeite(1);
            }}
            style={{ border: `1px solid ${tokens.line}`, borderRadius: "6px", background: tokens.paperRaised, padding: "7px 9px", color: tokens.ink }}
          />
        </label>
        <label style={{ ...fontUI, fontSize: "11px", color: tokens.inkMuted }}>
          <span className="block mb-1">TAG (OPTIONAL)</span>
          <select
            value={tagImMonat}
            disabled={!monat}
            onChange={(event) => { setTagImMonat(event.target.value); setSeite(1); }}
            style={{ minWidth: "105px", border: `1px solid ${tokens.line}`, borderRadius: "6px", background: tokens.paperRaised, padding: "8px 9px", color: tokens.ink }}
          >
            <option value="">Alle Tage</option>
            {Array.from({ length: tageImMonat }, (_, index) => index + 1).map((tag) => (
              <option key={tag} value={tag}>{tag}.</option>
            ))}
          </select>
        </label>
        <label style={{ ...fontUI, fontSize: "11px", color: tokens.inkMuted }}>
          <span className="block mb-1">EINTRÄGE PRO SEITE</span>
          <select
            value={proSeite}
            onChange={(event) => { setProSeite(Number(event.target.value)); setSeite(1); }}
            style={{ minWidth: "90px", border: `1px solid ${tokens.line}`, borderRadius: "6px", background: tokens.paperRaised, padding: "8px 9px", color: tokens.ink }}
          >
            {[25, 50, 100, 200].map((anzahl) => <option key={anzahl} value={anzahl}>{anzahl}</option>)}
          </select>
        </label>
        {(monat || tagImMonat) && (
          <button
            type="button"
            onClick={() => { setMonat(""); setTagImMonat(""); setSeite(1); }}
            style={{ ...fontUI, fontSize: "12px", border: `1px solid ${tokens.line}`, borderRadius: "6px", padding: "8px 11px", background: tokens.paperRaised, color: tokens.inkMuted }}
          >
            Filter löschen
          </button>
        )}
      </div>

      {fehler && (
        <div className="mb-4 px-4 py-3" style={{ ...fontUI, fontSize: "12.5px", color: tokens.rust, background: tokens.rustPale, border: `1px solid ${tokens.rust}`, borderRadius: "6px" }}>
          Aktionslog konnte nicht geladen werden: {fehler}
        </div>
      )}

      <div className="action-log-table" style={{ border: `1px solid ${tokens.line}`, borderRadius: "8px", overflow: "hidden", background: tokens.paperRaised }}>
        <div className="grid px-4 py-2.5 action-log-head" style={{ gridTemplateColumns: "1fr 1.35fr 1.45fr 1.1fr 2.3fr", ...fontMono, fontSize: "10.5px", color: tokens.inkMuted, letterSpacing: "0.05em", borderBottom: `1px solid ${tokens.line}` }}>
          <div>ZEIT</div><div>EREIGNIS</div><div>MAIL VON</div><div>AUSGELÖST VON</div><div>DETAIL</div>
        </div>
        {eintraege.map((e) => (
          <div key={e.id} className="grid items-start px-4 py-3 action-log-row" style={{ gridTemplateColumns: "1fr 1.35fr 1.45fr 1.1fr 2.3fr", borderBottom: `1px solid ${tokens.line}` }}>
            <div style={{ ...fontMono, fontSize: "12px", color: tokens.inkMuted }}>{formatZeitpunkt(e.erstellt_am)}</div>
            <div>
              <Badge label={(EREIGNIS_LABEL[e.ereignis] ?? e.ereignis).toUpperCase()} color={farbeFuerEreignis(e.ereignis)} />
            </div>
            <div style={{ ...fontSerif, fontSize: "13.5px" }}>{e.mail_absender || "—"}</div>
            <div style={{ ...fontUI, fontSize: "12.5px", color: tokens.ink }}>{e.ausgeloest_von || "Krautl"}</div>
            <div style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted, wordBreak: "break-word" }}>{e.detail}</div>
          </div>
        ))}
        {!laedt && !fehler && eintraege.length === 0 && (
          <div className="px-4 py-6 text-center" style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted }}>
            Für diesen Zeitraum wurden keine Aktionen protokolliert.
          </div>
        )}
        {laedt && (
          <div className="px-4 py-6 text-center" style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted }}>
            Aktionslog wird geladen …
          </div>
        )}
      </div>

      <div className="flex items-center justify-between gap-3 mt-4" style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted, flexWrap: "wrap" }}>
        <span>{ersterEintrag}–{letzterEintrag} von {antwort.gesamt} Einträgen</span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={seite <= 1 || laedt}
            onClick={() => setSeite((wert) => Math.max(1, wert - 1))}
            style={{ border: `1px solid ${tokens.line}`, borderRadius: "6px", padding: "7px 11px", background: tokens.paperRaised, color: tokens.ink, opacity: seite <= 1 || laedt ? 0.45 : 1 }}
          >
            Zurück
          </button>
          <span>Seite {antwort.seite} von {antwort.seiten}</span>
          <button
            type="button"
            disabled={seite >= antwort.seiten || laedt}
            onClick={() => setSeite((wert) => wert + 1)}
            style={{ border: `1px solid ${tokens.line}`, borderRadius: "6px", padding: "7px 11px", background: tokens.paperRaised, color: tokens.ink, opacity: seite >= antwort.seiten || laedt ? 0.45 : 1 }}
          >
            Weiter
          </button>
        </div>
      </div>
    </div>
  );
}

function verwendeKrautlDaten(onNichtAngemeldet, benutzer, alleMails) {
  const [daten, setDaten] = useState(null);
  const [fehler, setFehler] = useState(null);
  const laedt = useRef(false);

  const laden = useCallback(async ({ imHintergrund = false } = {}) => {
    if (laedt.current) return;
    laedt.current = true;
    try {
      const istAdmin = benutzer?.rolle === "admin";
      const [health, mails, katalog, rechnungen, faq, faqVorschlaege, wissensbasis, wissensvorschlaege, entwuerfe, rollenMailzugriff] = await Promise.all([
        api.health(), api.mails(alleMails), api.klassifikationen(), api.rechnungen(), api.faq(), api.faqVorschlaege(), api.wissensbasis(), api.wissensvorschlaege(), api.entwuerfe(alleMails),
        istAdmin ? api.rollenMailzugriff() : Promise.resolve(null),
      ]);
      setDaten({ health, mails, katalog, rechnungen, faq, faqVorschlaege, wissensbasis, wissensvorschlaege, entwuerfe, rollenMailzugriff });
      setFehler(null);
    } catch (e) {
      if (e.status === 401) {
        onNichtAngemeldet();
        return;
      }
      // Ein vorübergehender Hintergrundfehler soll die bereits sichtbare
      // Oberfläche nicht durch eine Fehlerseite ersetzen.
      if (!imHintergrund) setFehler(e.message);
    } finally {
      laedt.current = false;
    }
  }, [onNichtAngemeldet, benutzer, alleMails]);

  useEffect(() => {
    laden();

    const intervall = window.setInterval(
      () => laden({ imHintergrund: true }),
      30_000,
    );
    const beiRueckkehr = () => {
      if (document.visibilityState === "visible") laden({ imHintergrund: true });
    };
    document.addEventListener("visibilitychange", beiRueckkehr);
    window.addEventListener("focus", beiRueckkehr);

    return () => {
      window.clearInterval(intervall);
      document.removeEventListener("visibilitychange", beiRueckkehr);
      window.removeEventListener("focus", beiRueckkehr);
    };
  }, [laden]);

  return { daten, fehler, neuLaden: laden };
}

function LoginView({ onAngemeldet }) {
  const [benutzername, setBenutzername] = useState("");
  const [passwort, setPasswort] = useState("");
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState("");

  async function absenden(e) {
    e.preventDefault();
    setLaeuft(true);
    setFehler("");
    try {
      const benutzer = await api.login(benutzername, passwort);
      onAngemeldet(benutzer);
    } catch (error) {
      setFehler(
        error.status === 401
          ? "Benutzername oder Passwort ist nicht richtig."
          : error.message
      );
    } finally {
      setLaeuft(false);
    }
  }

  return (
    <div className="w-full h-full min-h-screen flex items-center justify-center p-6" style={{ background: tokens.paper }}>
      <form onSubmit={absenden} className="w-full p-7" style={{ maxWidth: "390px", background: tokens.paperRaised, border: `1px solid ${tokens.line}`, borderRadius: "10px" }}>
        <img src={logo} alt="Krautl" style={{ height: "48px", width: "auto", margin: "0 auto 24px" }} />
        <h1 style={{ ...fontDisplay, fontSize: "22px", color: tokens.mossDeep }}>Bei Krautl anmelden</h1>
        <p style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted, marginTop: "5px", marginBottom: "20px" }}>
          Bitte mit Deinem persönlichen Konto anmelden.
        </p>
        <label style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted }}>
          Benutzername
          <input
            autoFocus
            autoComplete="username"
            value={benutzername}
            onChange={(e) => setBenutzername(e.target.value)}
            className="block w-full mt-1.5 px-3 py-2.5"
            style={{ ...fontUI, fontSize: "14px", background: tokens.paper, border: `1px solid ${tokens.line}`, borderRadius: "6px", color: tokens.ink }}
          />
        </label>
        <label className="block mt-4" style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted }}>
          Passwort
          <input
            type="password"
            autoComplete="current-password"
            value={passwort}
            onChange={(e) => setPasswort(e.target.value)}
            className="block w-full mt-1.5 px-3 py-2.5"
            style={{ ...fontUI, fontSize: "14px", background: tokens.paper, border: `1px solid ${tokens.line}`, borderRadius: "6px", color: tokens.ink }}
          />
        </label>
        {fehler && <div className="mt-3" style={{ ...fontUI, fontSize: "12.5px", color: tokens.rust }}>{fehler}</div>}
        <button
          type="submit"
          disabled={laeuft || !benutzername || !passwort}
          className="w-full mt-5 px-3 py-2.5 disabled:opacity-50"
          style={{ ...fontUI, fontSize: "13.5px", fontWeight: 600, color: "#fff", background: tokens.moss, borderRadius: "6px" }}
        >
          {laeuft ? "Anmeldung läuft …" : "Anmelden"}
        </button>
      </form>
    </div>
  );
}

export default function KrautlUI() {
  const [benutzer, setBenutzer] = useState(undefined);

  useEffect(() => {
    api.angemeldeterBenutzer()
      .then(setBenutzer)
      .catch(() => setBenutzer(null));
  }, []);

  if (benutzer === undefined) {
    return (
      <div className="w-full h-full min-h-screen flex items-center justify-center" style={{ ...fontUI, background: tokens.paper, color: tokens.inkMuted }}>
        Anmeldung wird geprüft …
      </div>
    );
  }
  if (!benutzer) {
    return <LoginView onAngemeldet={setBenutzer} />;
  }
  return (
    <KrautlAnwendung
      benutzer={benutzer}
      onAbmelden={async () => {
        try {
          await api.logout();
        } finally {
          setBenutzer(null);
        }
      }}
    />
  );
}

function KrautlAnwendung({ benutzer, onAbmelden }) {
  const [tab, setTab] = useState("posteingang");
  const [alleMails, setAlleMails] = useState(false);
  const { daten, fehler, neuLaden } = verwendeKrautlDaten(onAbmelden, benutzer, alleMails);

  const abgeleitet = useMemo(() => {
    if (!daten) return null;
    const katalogNachId = Object.fromEntries(daten.katalog.map((k) => [k.klassifikation_id, k]));
    const entwurfNachMailId = Object.fromEntries(daten.entwuerfe.map((e) => [e.mail_id, e]));
    const mailsNachId = Object.fromEntries(daten.mails.map((m) => [m.id, m]));

    const mails = daten.mails.map((m) => {
      const klass = katalogNachId[m.klassifikation_id];
      const felder = {};
      if (m.kundennummer) felder["Kundennummer"] = m.kundennummer;
      if (m.bestellnummer) felder["Bestellnummer"] = m.bestellnummer;
      if (m.rechnungsnummer) felder["Rechnungsnummer"] = m.rechnungsnummer;
      if (m.spam_score != null) felder["Spam-Score"] = m.spam_score;
      const entwurfRoh = entwurfNachMailId[m.id];
      return {
        id: m.id,
        klassifikation_id: m.klassifikation_id,
        kat: klass?.hauptkategorie ?? "Unklassifiziert",
        katId: m.klassifikation_id ?? "UNKLASSIFIZIERT",
        absender: m.absender_name || m.absender_adresse,
        absenderAdresse: m.absender_adresse,
        antwortAnAdresse: m.antwort_an_adresse,
        betreff: m.betreff,
        snippet: m.text_auszug,
        zeit: formatMailZeit(m.empfangen_am),
        konfidenz: m.konfidenz,
        aufgaben: m.aufgaben ?? [],
        bestaetigungErforderlich: Boolean(m.bestaetigung_erforderlich),
        zustaendigAdmin: Boolean(m.zustaendig_admin),
        zustaendigSachbearbeiter: Boolean(m.zustaendig_sachbearbeiter),
        zuweisbareRollen: m.zuweisbare_rollen ?? ["admin", "sachbearbeiter"],
        zustaendigkeitLabel: (() => {
          if (m.zustaendig_admin && m.zustaendig_sachbearbeiter) return "Erik, Guri und Ludwig";
          if (m.zustaendig_admin) return "Erik (Admin)";
          if (m.zustaendig_sachbearbeiter) return "Guri, Ludwig (Sachbearbeiter)";
          return "nicht zugewiesen";
        })(),
        zielhinweis: (() => {
          const zielpostfach = klass?.zielpostfach;
          const zielordner = klass?.zielordner;
          const quelle = m.quellpostfach;
          const bleibt = !zielpostfach
            || (zielpostfach === quelle && (!zielordner || zielordner.toUpperCase() === "INBOX"));
          if (bleibt) {
            return `bleibt in ${quelle ?? "seinem Postfach"}${zielordner ? ` / ${zielordner}` : ""}`;
          }
          return `wird verschoben nach ${zielpostfach}${zielordner ? ` / ${zielordner}` : ""}`;
        })(),
        felder,
        anhaenge: m.anhang_dateinamen ?? [],
        entwurf: entwurfRoh ? { id: entwurfRoh.id, text: entwurfRoh.text_ki } : null,
      };
    });

    const faqVorschlaege = daten.faqVorschlaege.map((v) => {
      const quelleMail = mailsNachId[v.quelle_mail_id];
      return {
        id: v.id,
        kategorie: v.kategorie,
        frage: v.frage,
        entwurf: v.entwurf_antwort,
        quelle: quelleMail
          ? `${quelleMail.absender_name || quelleMail.absender_adresse}, ${formatZeit(quelleMail.empfangen_am)}`
          : `Mail #${v.quelle_mail_id}`,
      };
    });

    return { mails, faqVorschlaege };
  }, [daten]);

  if (fehler) {
    return (
      <div className="w-full h-full flex items-center justify-center p-8" style={{ ...fontUI, background: tokens.paper, color: tokens.rust }}>
        Verbindung zum Krautl-Backend fehlgeschlagen: {fehler}
      </div>
    );
  }

  if (!daten || !abgeleitet) {
    return (
      <div className="w-full h-full flex items-center justify-center" style={{ ...fontUI, background: tokens.paper, color: tokens.inkMuted }}>
        Lade Daten …
      </div>
    );
  }

  const entwuerfeOffen = daten.entwuerfe.length;
  const offeneRechnungen = daten.rechnungen.filter((r) => ["offen", "unklar"].includes(r.zahlungsstatus)).length;

  return (
    <div className="w-full h-full flex flex-col krautl-app" style={{ background: tokens.paper, minHeight: "640px", color: tokens.ink }}>
      <header className="flex items-center px-5 krautl-header" style={{ borderBottom: `1px solid ${tokens.line}`, background: tokens.paperRaised }}>
        <div className="flex items-center gap-2.5 pr-5 py-2 krautl-logo" style={{ borderRight: `1px solid ${tokens.line}`, marginRight: "8px" }}>
          <img src={logo} alt="Krautl" style={{ height: "34px", width: "auto" }} />
        </div>
        <nav className="flex items-center krautl-nav">
          <NavTab icon={InboxIcon} label="Posteingang" mobileLabel="Postfach" active={tab === "posteingang"} onClick={() => setTab("posteingang")} />
          <NavTab icon={Receipt} label="Rechnungen" count={offeneRechnungen} accent active={tab === "rechnungen"} onClick={() => setTab("rechnungen")} />
          <NavTab icon={BookOpen} label="Wissensdatenbank" mobileLabel="Wissen" count={daten.wissensvorschlaege.length} accent active={tab === "wissen"} onClick={() => setTab("wissen")} />
          {benutzer.rolle === "admin" && <EinstellungenMenu active={["klassifikationen", "aktionslog", "rollen"].includes(tab)} onWaehlen={setTab} />}
        </nav>
        <div className="ml-auto flex items-center gap-2 krautl-header-meta">
          <span
            className="flex items-center gap-1.5 pr-3 mr-1 header-worker"
            title={daten.health.mail_worker.detail || ""}
            style={{
              ...fontUI,
              fontSize: "12px",
              color: daten.health.mail_worker.aktiv ? tokens.mossDeep : tokens.rust,
              borderRight: `1px solid ${tokens.line}`,
            }}
          >
            <span
              className="inline-block w-2 h-2 rounded-full"
              style={{ background: daten.health.mail_worker.aktiv ? tokens.moss : tokens.rust }}
            />
            {daten.health.mail_worker.aktiv
              ? `Mailabruf aktiv · ${formatZeit(daten.health.mail_worker.letzter_lauf)} Uhr`
              : "Mailabruf nicht aktiv"}
          </span>
          <PenLine className="header-drafts-icon" size={13} style={{ color: tokens.amber }} />
          <span className="header-drafts-text" style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted }}>{entwuerfeOffen} Entwürfe warten auf Freigabe</span>
          <div className="flex items-center gap-1.5 pl-3 ml-1 header-user" style={{ borderLeft: `1px solid ${tokens.line}` }}>
            <UserRound size={13} style={{ color: tokens.mossDeep }} />
            <span className="header-user-name" style={{ ...fontUI, fontSize: "12.5px", color: tokens.ink }}>{benutzer.name} · {benutzer.rolle === "admin" ? "Admin" : "Sachbearbeiter"}</span>
            <button
              onClick={onAbmelden}
              title="Abmelden"
              className="p-1.5 ml-1"
              style={{ color: tokens.inkMuted, borderRadius: "5px" }}
            >
              <LogOut size={13} />
            </button>
          </div>
        </div>
      </header>

      {tab === "posteingang" && <PosteingangView
        mails={abgeleitet.mails}
        katalog={daten.katalog}
        benutzer={benutzer}
        alleMails={alleMails}
        onAlleMailsAendern={setAlleMails}
        onReload={neuLaden}
      />}
      {tab === "rechnungen" && <RechnungenView rechnungen={daten.rechnungen} onReload={neuLaden} />}
      {tab === "wissen" && <WissensdatenbankViewNeu basis={daten.wissensbasis} faqEintraege={daten.faq} vorschlaege={daten.wissensvorschlaege} onReload={neuLaden} />}
      {tab === "klassifikationen" && <KlassifikationenView katalog={daten.katalog} onReload={neuLaden} />}
      {tab === "aktionslog" && <AktionslogView />}
      {tab === "rollen" && daten.rollenMailzugriff && <RollenMailzugriffView konfiguration={daten.rollenMailzugriff} onReload={neuLaden} />}
    </div>
  );
}
