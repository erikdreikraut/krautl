import { useCallback, useEffect, useMemo, useState, useRef } from "react";
import {
  Search, ChevronDown, CheckCircle2, PenLine, Paperclip, X,
  Inbox as InboxIcon, Receipt, BookOpen, Check, FolderCog, Sparkles, Settings,
  LogOut, ShieldCheck, Trash2, UserRound, Eye, ArrowLeft, Lock,
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
const MAX_ANTWORTANHAENGE = 10;
const MAX_ANTWORTANHAENGE_BYTES = 18 * 1024 * 1024;
const MAIL_RESERVIERUNG_VERZOEGERUNG_MS = 3_000;
const MAIL_RESERVIERUNG_HEARTBEAT_MS = 25_000;
const RESERVIERUNG_KURZNAMEN = {
  erik: "Erik",
  gursewak: "Guri",
  ludwig: "Ludwig",
  aneta: "Aneta",
};

function lesbareDateigroesse(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

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

function istDeutscheSprache(sprache) {
  const wert = String(sprache || "").trim().toLowerCase().replace("_", "-");
  return ["de", "de-de", "de-at", "de-ch", "deutsch", "german"].includes(wert);
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
  BESTAETIGUNG_EINHOLEN: "Erledigt-Klick verpflichtend",
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
  bestaetigt: "Erledigt (Pflichtschritt)",
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
  mail_uebersetzt: "Deutsche Arbeitsübersetzung erstellt",
  antwort_uebersetzung_fehlgeschlagen: "Antwortübersetzung fehlgeschlagen",
  mail_manuell_erledigt: "Manuell erledigt",
  mail_geloescht: "Mail gelöscht",
  mail_loeschen_fehlgeschlagen: "Mail-Löschung fehlgeschlagen",
  mail_zugewiesen: "Mail zugewiesen",
};
function farbeFuerEreignis(ereignis) {
  if (ereignis.endsWith("fehlgeschlagen")) return tokens.rust;
  if (ereignis === "mail_geloescht") return tokens.rust;
  if (["verschoben", "bestaetigt", "rechnung_verarbeitet", "antwortvorschlag_erstellt", "antwortentwurf_erstellt", "antwort_versendet_test", "antwort_versendet", "audio_transkribiert", "wissensvorschlag_erstellt", "mail_uebersetzt", "mail_manuell_erledigt"].includes(ereignis)) return tokens.moss;
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

function MailAnzahlTag({ anzahl, aktiv }) {
  if (!anzahl) return null;
  return (
    <span
      aria-label={`${anzahl} offene ${anzahl === 1 ? "Mail" : "Mails"}`}
      className="inline-flex items-center justify-center rounded-full"
      style={{
        minWidth: "17px",
        height: "17px",
        padding: "0 4px",
        ...fontMono,
        fontSize: "9px",
        fontWeight: 700,
        lineHeight: 1,
        background: aktiv ? "rgba(255, 255, 255, 0.22)" : tokens.mossPale,
        color: aktiv ? "#fff" : tokens.mossDeep,
        border: `1px solid ${aktiv ? "rgba(255, 255, 255, 0.38)" : tokens.moss}`,
      }}
    >
      {anzahl}
    </span>
  );
}

function MailReservierungsTag({ reservierung, benutzername }) {
  if (!reservierung || reservierung.benutzername === benutzername) return null;
  const name = RESERVIERUNG_KURZNAMEN[reservierung.benutzername]
    || reservierung.name
    || "ANDERE PERSON";
  const hinweis = `Wird gerade von ${name} bearbeitet`;
  return (
    <span
      role="status"
      aria-label={hinweis}
      title={hinweis}
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full whitespace-nowrap"
      style={{
        ...fontMono,
        fontSize: "9px",
        fontWeight: 700,
        letterSpacing: "0.02em",
        color: tokens.rust,
        background: tokens.rustPale,
        border: `1px solid ${tokens.rust}`,
      }}
    >
      <Lock size={9} aria-hidden="true" />
      GESPERRT · {String(name).toUpperCase()}
    </span>
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

  useEffect(() => {
    if (deaktiviert) setOffen(false);
  }, [deaktiviert]);

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
      {offen && !deaktiviert && (
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

function KategorieKorrektur({ mail, katalog, onKorrigiert, onMeldung, deaktiviert = false }) {
  const [wird_gesendet, setWirdGesendet] = useState(false);

  async function korrigieren(neueId) {
    if (!neueId || neueId === mail.klassifikation_id) return;
    setWirdGesendet(true);
    try {
      await api.korrigiereKlassifikation(mail.id, neueId);
      await onKorrigiert();
    } catch (e) {
      onMeldung(`Kategorie konnte nicht geändert werden: ${e.message}`);
    } finally {
      setWirdGesendet(false);
    }
  }

  return (
    <AuswahlMenue
      label={wird_gesendet ? "Wird geändert …" : "Kategorie ändern"}
      title={deaktiviert ? "Mail wird gerade von einer anderen Person bearbeitet" : "Mail einer anderen Kategorie zuordnen"}
      wert={mail.klassifikation_id ?? ""}
      deaktiviert={deaktiviert || wird_gesendet}
      breite="390px"
      optionen={katalog.map((k) => ({
        value: k.klassifikation_id,
        label: `${k.klassifikation_id} — ${k.hauptkategorie} / ${k.unterkategorie}`,
      }))}
      onWaehlen={korrigieren}
    />
  );
}

function ErledigtButton({ mail, onErledigt, onMeldung, deaktiviert = false }) {
  const [laeuft, setLaeuft] = useState(false);

  async function erledigen() {
    setLaeuft(true);
    try {
      const ergebnis = mail.bestaetigungErforderlich
        ? await api.mailBestaetigen(mail.id)
        : await api.mailErledigen(mail.id);
      if (ergebnis.status === "fehlgeschlagen") {
        onMeldung(`Automatik fehlgeschlagen: ${ergebnis.detail || "Unbekannter Fehler"}`);
      }
      await onErledigt(mail.id);
    } catch (e) {
      onMeldung(`Mail konnte nicht als erledigt markiert werden: ${e.message}`);
    } finally {
      setLaeuft(false);
    }
  }

  return (
    <button
      onClick={erledigen}
      disabled={deaktiviert || laeuft}
      title={
        deaktiviert
          ? "Mail wird gerade von einer anderen Person bearbeitet"
          : mail.bestaetigungErforderlich
          ? "Pflichtschritt bestätigen und vorgesehenen Ablauf fortsetzen"
          : "Mail in Krautl als erledigt markieren"
      }
      className="flex items-center gap-1.5 px-3 py-2 disabled:opacity-60"
      style={{ ...fontUI, fontSize: "13px", fontWeight: 600, color: "#fff", background: tokens.moss, borderRadius: "6px" }}
    >
      <Check size={14} /> {laeuft ? "Wird erledigt …" : "Erledigt"}
    </button>
  );
}

function StatusMeldung({ text, onSchliessen }) {
  if (!text) return null;
  return (
    <div
      role="alert"
      aria-live="assertive"
      className="status-meldung"
      style={{
        position: "fixed",
        right: "18px",
        bottom: "18px",
        zIndex: 1000,
        display: "flex",
        alignItems: "flex-start",
        gap: "12px",
        width: "min(430px, calc(100vw - 36px))",
        padding: "12px 14px",
        color: tokens.rust,
        background: tokens.rustPale,
        border: `1px solid ${tokens.rust}`,
        borderRadius: "8px",
        boxShadow: "0 8px 28px rgba(36, 42, 31, 0.18)",
        ...fontUI,
        fontSize: "12.5px",
        lineHeight: 1.45,
      }}
    >
      <span className="flex-1">{text}</span>
      <button
        type="button"
        onClick={onSchliessen}
        aria-label="Meldung schließen"
        title="Meldung schließen"
        style={{ color: tokens.rust, flexShrink: 0 }}
      >
        <X size={15} />
      </button>
    </div>
  );
}

function MailLoeschenButton({ mail, onGeloescht, deaktiviert = false }) {
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
      await onGeloescht(mail.id);
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
        disabled={deaktiviert || laeuft}
        title={deaktiviert
          ? "Mail wird gerade von einer anderen Person bearbeitet"
          : laeuft ? "Mail wird gelöscht …" : "Mail dauerhaft aus dem Postfach löschen"}
        aria-label="Mail löschen"
        className="flex items-center justify-center w-8 h-8 disabled:opacity-50"
        style={{ color: tokens.rust, border: `1px solid ${tokens.rust}`, borderRadius: "6px", background: tokens.rustPale }}
      >
        <Trash2 size={13} />
      </button>
    </div>
  );
}

function ZuweisenButton({ mail, onZugewiesen, deaktiviert = false }) {
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
        deaktiviert={deaktiviert || laeuft}
        optionen={[
          ...(mail.zuweisbareRollen.includes("admin")
            ? [{ value: "admin", label: "Erik (Admin)" }]
            : []),
          ...(mail.zuweisbareRollen.includes("sachbearbeiter")
            ? [{ value: "sachbearbeiter", label: "Guri, Ludwig, Aneta (Sachbearbeitung)" }]
            : []),
        ]}
        onWaehlen={zuweisen}
      />
    </div>
  );
}

function AntwortAktionen({ mail, onErzeugt, deaktiviert = false }) {
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
          disabled={deaktiviert || Boolean(laufendeAktion) || Boolean(mail.entwurf)}
          title="Antwortvorschlag mit dem dreikraut-Stilprofil erstellen"
          className="flex items-center gap-1.5 px-3 py-2 disabled:opacity-50"
          style={{ ...fontUI, fontSize: "13px", fontWeight: 600, color: tokens.mossDeep, border: `1px solid ${tokens.moss}`, borderRadius: "6px" }}
        >
          <Sparkles size={14} /> {laufendeAktion === "vorschlag" ? "Wird erstellt …" : "Vorschlag generieren"}
        </button>
      )}
      <button
        onClick={() => ausfuehren("antwort")}
        disabled={deaktiviert || Boolean(laufendeAktion) || Boolean(mail.entwurf)}
        title="Leeren Antwortentwurf ohne KI-Vorschlag öffnen"
        className="flex items-center gap-1.5 px-3 py-2 disabled:opacity-50"
        style={{ ...fontUI, fontSize: "13px", fontWeight: 600, color: "#fff", background: tokens.moss, borderRadius: "6px" }}
      >
        <PenLine size={14} /> {laufendeAktion === "antwort" ? "Wird geöffnet …" : "Antworten"}
      </button>
    </div>
  );
}

function MailInhalt({ mail }) {
  const [html, setHtml] = useState(null);
  const [textAnsicht, setTextAnsicht] = useState(false);

  useEffect(() => {
    let aktiv = true;
    setHtml(null);
    setTextAnsicht(false);

    api.mailHtml(mail.id)
      .then((ergebnis) => {
        if (aktiv) setHtml(ergebnis?.html || null);
      })
      .catch(() => {
        // Die gespeicherte Textansicht bleibt ein belastbarer Fallback, wenn
        // die Originalmail nicht mehr per IMAP auffindbar ist.
        if (aktiv) setHtml(null);
      });

    return () => { aktiv = false; };
  }, [mail.id]);

  if (!html || textAnsicht) {
    return (
      <div style={{ borderBottom: `1px solid ${tokens.line}` }}>
        {html && (
          <div className="px-6 pt-3 flex justify-end">
            <button
              type="button"
              onClick={() => setTextAnsicht(false)}
              className="px-2.5 py-1"
              style={AUSWAHL_BUTTON_STIL}
            >
              HTML-ANSICHT
            </button>
          </div>
        )}
        <div
          className="px-6 py-4 mail-body"
          style={{ ...fontSerif, fontSize: "15px", lineHeight: 1.65, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
        >
          {mail.snippet}
        </div>
      </div>
    );
  }

  return (
    <div style={{ borderBottom: `1px solid ${tokens.line}` }}>
      <div className="px-6 pt-3 flex items-center justify-between gap-3">
        <span
          title="Aktive Inhalte und externe Bilder sind zum Schutz vor Tracking blockiert."
          style={{ ...fontUI, fontSize: "11px", color: tokens.inkMuted }}
        >
          Sichere HTML-Ansicht
        </span>
        <button
          type="button"
          onClick={() => setTextAnsicht(true)}
          className="px-2.5 py-1"
          style={AUSWAHL_BUTTON_STIL}
        >
          TEXTANSICHT
        </button>
      </div>
      <div className="px-6 py-3">
        <iframe
          title={`HTML-Inhalt: ${mail.betreff}`}
          sandbox=""
          referrerPolicy="no-referrer"
          srcDoc={html}
          style={{
            display: "block",
            width: "100%",
            height: "min(680px, 65vh)",
            minHeight: "420px",
            border: `1px solid ${tokens.line}`,
            borderRadius: "6px",
            background: tokens.paperRaised,
          }}
        />
      </div>
    </div>
  );
}

function PosteingangView({ mails, katalog, benutzer, alleMails, mailZaehler, onAlleMailsAendern, onReload }) {
  const [filter, setFilter] = useState(null);
  const [suchbegriff, setSuchbegriff] = useState("");
  const [selectedId, setSelectedId] = useState(mails[0]?.id ?? null);
  const [versandbestaetigungen, setVersandbestaetigungen] = useState({});
  const [uebersetzungsstatus, setUebersetzungsstatus] = useState({});
  const [lokalAusgeblendeteMailIds, setLokalAusgeblendeteMailIds] = useState(() => new Set());
  const [mobileDetailOffen, setMobileDetailOffen] = useState(false);
  const [statusMeldung, setStatusMeldung] = useState("");
  const [istMobil, setIstMobil] = useState(
    () => window.matchMedia("(max-width: 767px)").matches
  );
  const [fensterAktiv, setFensterAktiv] = useState(
    () => document.visibilityState === "visible" && document.hasFocus()
  );
  const [lokaleReservierung, setLokaleReservierung] = useState(null);
  const gemeldeteAufgabenfehler = useRef(new Set());
  const eigeneReservierungMailId = useRef(null);
  const aktiveMailId = useRef(null);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 767px)");
    const aktualisieren = () => setIstMobil(media.matches);
    media.addEventListener("change", aktualisieren);
    return () => media.removeEventListener("change", aktualisieren);
  }, []);

  useEffect(() => {
    const aktualisieren = () => setFensterAktiv(
      document.visibilityState === "visible" && document.hasFocus()
    );
    document.addEventListener("visibilitychange", aktualisieren);
    window.addEventListener("focus", aktualisieren);
    window.addEventListener("blur", aktualisieren);
    return () => {
      document.removeEventListener("visibilitychange", aktualisieren);
      window.removeEventListener("focus", aktualisieren);
      window.removeEventListener("blur", aktualisieren);
    };
  }, []);

  const verfuegbareMails = useMemo(
    () => mails.filter((mail) => !lokalAusgeblendeteMailIds.has(mail.id)),
    [mails, lokalAusgeblendeteMailIds],
  );
  const kategorien = useMemo(
    () => [...new Set(verfuegbareMails.map((m) => m.kat))],
    [verfuegbareMails],
  );
  const kategorieGefiltert = filter
    ? verfuegbareMails.filter((m) => m.kat === filter)
    : verfuegbareMails;
  const suchtreffer = suchbegriff.trim().toLowerCase();
  const sichtbar = suchtreffer
    ? kategorieGefiltert.filter((m) => {
        const felderText = Object.values(m.felder || {}).join(" ");
        const text = [
          m.betreff, m.betreffDeutsch, m.absender, m.absenderAdresse,
          m.snippet, m.uebersetzung, m.katId, felderText,
        ]
          .filter(Boolean).join(" ").toLowerCase();
        return text.includes(suchtreffer);
      })
    : kategorieGefiltert;
  const selected = verfuegbareMails.find((m) => m.id === selectedId) ?? sichtbar[0] ?? null;
  const detailSichtbar = Boolean(selected && (!istMobil || mobileDetailOffen));
  const aktuelleReservierung = lokaleReservierung?.mailId === selected?.id
    ? lokaleReservierung
    : selected?.reservierung;
  const vonAnderemReserviert = Boolean(
    aktuelleReservierung
    && aktuelleReservierung.benutzername !== benutzer.benutzername
  );
  const reserviertVon = RESERVIERUNG_KURZNAMEN[
    aktuelleReservierung?.benutzername
  ] || aktuelleReservierung?.name || "einer anderen Person";
  const vorherigeMailIds = useRef(verfuegbareMails.map((m) => m.id));

  const reservierungFreigeben = useCallback((mailId, perBeacon = false) => {
    if (eigeneReservierungMailId.current !== mailId) return;
    eigeneReservierungMailId.current = null;
    setLokaleReservierung((aktuell) => (
      aktuell?.mailId === mailId ? null : aktuell
    ));
    if (perBeacon) {
      api.mailReservierungFreigebenBeacon(mailId);
    } else {
      api.mailReservierungFreigeben(mailId).catch(() => {});
    }
  }, []);

  useEffect(() => {
    const mailId = selected?.id ?? null;
    aktiveMailId.current = mailId;
    setLokaleReservierung(null);
    return () => {
      if (mailId != null) reservierungFreigeben(mailId);
    };
  }, [selected?.id, reservierungFreigeben]);

  useEffect(() => {
    if (!selected || !detailSichtbar || !fensterAktiv) return undefined;
    const mailId = selected.id;
    const timer = window.setTimeout(async () => {
      try {
        const ergebnis = await api.mailReservieren(mailId);
        if (aktiveMailId.current !== mailId) {
          if (ergebnis.eigene) {
            api.mailReservierungFreigeben(mailId).catch(() => {});
          }
          return;
        }
        setLokaleReservierung({ mailId, ...ergebnis });
        eigeneReservierungMailId.current = ergebnis.eigene ? mailId : null;
      } catch (fehler) {
        if (aktiveMailId.current === mailId && fehler.status !== 409) {
          setStatusMeldung(
            `Bearbeitungsreservierung konnte nicht aktiviert werden: ${fehler.message}`
          );
        }
      }
    }, MAIL_RESERVIERUNG_VERZOEGERUNG_MS);
    return () => window.clearTimeout(timer);
  }, [selected?.id, detailSichtbar, fensterAktiv]);

  useEffect(() => {
    const mailId = selected?.id;
    if (
      !mailId
      || !detailSichtbar
      || !fensterAktiv
      || eigeneReservierungMailId.current !== mailId
      || !lokaleReservierung?.eigene
    ) return undefined;

    const intervall = window.setInterval(async () => {
      try {
        const ergebnis = await api.mailReservieren(mailId);
        if (aktiveMailId.current !== mailId) return;
        setLokaleReservierung({ mailId, ...ergebnis });
        if (!ergebnis.eigene) eigeneReservierungMailId.current = null;
      } catch {
        // Ohne Lebenszeichen läuft die Reservierung serverseitig nach 90 s aus.
      }
    }, MAIL_RESERVIERUNG_HEARTBEAT_MS);
    return () => window.clearInterval(intervall);
  }, [
    selected?.id,
    detailSichtbar,
    fensterAktiv,
    lokaleReservierung?.mailId,
    lokaleReservierung?.eigene,
  ]);

  useEffect(() => {
    const beimSchliessen = () => {
      const mailId = eigeneReservierungMailId.current;
      if (mailId != null) reservierungFreigeben(mailId, true);
    };
    window.addEventListener("pagehide", beimSchliessen);
    return () => window.removeEventListener("pagehide", beimSchliessen);
  }, [reservierungFreigeben]);

  // Verschwindet die ausgewählte Mail aus der Liste (verschoben, gelöscht,
  // Zuständigkeit geändert …), auf den Nachfolger an ihrer alten Position
  // springen statt immer zurück zum ersten Eintrag.
  useEffect(() => {
    const vorherige = vorherigeMailIds.current;
    const nochVorhanden = verfuegbareMails.some((m) => m.id === selectedId);

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

    vorherigeMailIds.current = verfuegbareMails.map((m) => m.id);
    // sichtbar bewusst nicht in den Deps: soll nur auf echte Mail-Reloads
    // reagieren, nicht auf lokale Filter-Wechsel.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [verfuegbareMails]);

  useEffect(() => {
    const idsVomServer = new Set(mails.map((mail) => mail.id));
    setLokalAusgeblendeteMailIds((alt) => {
      const verbleibend = new Set(
        [...alt].filter((mailId) => idsVomServer.has(mailId))
      );
      return verbleibend.size === alt.size ? alt : verbleibend;
    });
  }, [mails]);

  useEffect(() => {
    if (filter && !kategorien.includes(filter)) setFilter(null);
  }, [filter, kategorien]);

  useEffect(() => {
    if (!selected) setMobileDetailOffen(false);
  }, [selected]);

  useEffect(() => {
    const fehlgeschlagen = selected?.aufgaben?.find(
      (aufgabe) => aufgabe.status === "fehlgeschlagen"
    );
    if (!fehlgeschlagen) return;
    const schluessel = [
      selected.id,
      fehlgeschlagen.id,
      fehlgeschlagen.fehler || "",
    ].join(":");
    if (gemeldeteAufgabenfehler.current.has(schluessel)) return;
    gemeldeteAufgabenfehler.current.add(schluessel);
    const bezeichnung = AKTION_LABEL[fehlgeschlagen.aufgabe_typ]
      || fehlgeschlagen.aufgabe_typ
      || "Automatik";
    setStatusMeldung(
      `Automatik fehlgeschlagen – ${bezeichnung}: ${fehlgeschlagen.fehler || "Unbekannter Fehler"}`
    );
  }, [selected]);

  const uebersetzungStarten = useCallback(async (mail) => {
    if (!mail || uebersetzungsstatus[mail.id]?.status === "laeuft") return;
    setUebersetzungsstatus((alt) => ({
      ...alt,
      [mail.id]: { status: "laeuft", fehler: "" },
    }));
    try {
      await api.mailUebersetzen(mail.id);
      setUebersetzungsstatus((alt) => ({
        ...alt,
        [mail.id]: { status: "fertig", fehler: "" },
      }));
      await onReload();
    } catch (fehler) {
      setUebersetzungsstatus((alt) => ({
        ...alt,
        [mail.id]: {
          status: "fehler",
          fehler: fehler.message || "Übersetzung fehlgeschlagen",
        },
      }));
    }
  }, [onReload, uebersetzungsstatus]);

  useEffect(() => {
    if (
      selected?.uebersetzungFehlt
      && !uebersetzungsstatus[selected.id]
    ) {
      uebersetzungStarten(selected);
    }
  }, [selected, uebersetzungsstatus, uebersetzungStarten]);

  function mailOeffnen(id) {
    if (selected?.id != null && selected.id !== id) {
      reservierungFreigeben(selected.id);
    }
    setSelectedId(id);
    setMobileDetailOffen(true);
  }

  function detailSchliessen() {
    if (selected?.id != null) reservierungFreigeben(selected.id);
    setMobileDetailOffen(false);
  }

  async function aktionAbschliessen() {
    if (selected?.id != null) reservierungFreigeben(selected.id);
    setMobileDetailOffen(false);
    await onReload();
  }

  async function erledigenAbschliessen(mailId) {
    reservierungFreigeben(mailId);
    setLokalAusgeblendeteMailIds((alt) => new Set([...alt, mailId]));
    setMobileDetailOffen(false);
    await onReload();
  }

  async function loeschenAbschliessen(mailId) {
    reservierungFreigeben(mailId);
    setLokalAusgeblendeteMailIds((alt) => new Set([...alt, mailId]));
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
          <div className="flex items-center rounded-md overflow-hidden" style={{ border: `1px solid ${tokens.line}` }}>
            <button
              onClick={() => onAlleMailsAendern(false)}
              className="flex items-center gap-1.5 px-2 py-1"
              style={{ ...fontMono, fontSize: "9.5px", background: !alleMails ? tokens.mossDeep : tokens.paperRaised, color: !alleMails ? "#fff" : tokens.inkMuted }}
            >
              <span>MEINE</span>
              <MailAnzahlTag anzahl={mailZaehler?.meine ?? 0} aktiv={!alleMails} />
            </button>
            <button
              onClick={() => onAlleMailsAendern(true)}
              className="flex items-center gap-1.5 px-2 py-1"
              style={{ ...fontMono, fontSize: "9.5px", background: alleMails ? tokens.mossDeep : tokens.paperRaised, color: alleMails ? "#fff" : tokens.inkMuted, borderLeft: `1px solid ${tokens.line}` }}
            >
              <span>ALLE MAILS</span>
              <MailAnzahlTag anzahl={mailZaehler?.alle ?? 0} aktiv={alleMails} />
            </button>
          </div>
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
              style={{
                borderBottom: `1px solid ${tokens.line}`,
                background: m.prioritaet === "hoch"
                  ? tokens.rustPale
                  : selected?.id === m.id ? tokens.mossPale : "transparent",
                boxShadow: selected?.id === m.id
                  ? `inset 3px 0 0 ${m.prioritaet === "hoch" ? tokens.rust : tokens.moss}`
                  : "none",
              }}>
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
              <div style={{ ...fontSerif, fontSize: "13.5px" }}>{m.betreffDeutsch || m.betreff}</div>
              <div className="flex items-center justify-between gap-2">
                <Konfidenz value={m.konfidenz} />
                <MailReservierungsTag
                  reservierung={
                    lokaleReservierung?.mailId === m.id
                      ? lokaleReservierung
                      : m.reservierung
                  }
                  benutzername={benutzer.benutzername}
                />
              </div>
            </button>
          ))}
          {verfuegbareMails.length === 0 && (
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
              <button type="button" onClick={detailSchliessen} className="mobile-back-button items-center gap-1.5 mb-3 px-2.5 py-1.5" style={AUSWAHL_BUTTON_STIL}>
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
                  <ErledigtButton
                    mail={selected}
                    onErledigt={erledigenAbschliessen}
                    onMeldung={setStatusMeldung}
                    deaktiviert={vonAnderemReserviert}
                  />
                  <ZuweisenButton mail={selected} onZugewiesen={aktionAbschliessen} deaktiviert={vonAnderemReserviert} />
                  <KategorieKorrektur
                    mail={selected}
                    katalog={katalog}
                    onKorrigiert={onReload}
                    onMeldung={setStatusMeldung}
                    deaktiviert={vonAnderemReserviert}
                  />
                  <MailLoeschenButton mail={selected} onGeloescht={loeschenAbschliessen} deaktiviert={vonAnderemReserviert} />
                </div>
              </div>
              <h2 style={{ ...fontDisplay, fontSize: "19px", marginTop: "12px" }}>{selected.betreffDeutsch || selected.betreff}</h2>
              {selected.betreffDeutsch && selected.betreffDeutsch !== selected.betreff && (
                <div style={{ ...fontUI, fontSize: "11.5px", color: tokens.inkMuted, marginTop: "3px" }}>
                  Originalbetreff: {selected.betreff}
                </div>
              )}
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
            {vonAnderemReserviert && (
              <div
                className="px-6 py-3 flex items-center gap-2"
                role="status"
                style={{
                  ...fontUI,
                  fontSize: "12.5px",
                  color: tokens.rust,
                  background: tokens.rustPale,
                  borderBottom: `1px solid ${tokens.line}`,
                }}
              >
                <UserRound size={14} />
                <strong>Wird gerade von {reserviertVon} bearbeitet.</strong>
                <span>Du kannst die Mail ansehen, aber nicht bearbeiten.</span>
              </div>
            )}
            {selected.entwurf ? (
              <EntwurfPanel
                key={selected.entwurf.id}
                entwurf={selected.entwurf}
                kiPruefung={String(selected.kat || "").toUpperCase() === "KUNDENSERVICE"}
                originalsprache={selected.originalsprache}
                onErledigt={aktionAbschliessen}
                onVersendet={(ergebnis) => setVersandbestaetigungen((alt) => ({
                  ...alt,
                  [selected.id]: ergebnis,
                }))}
                deaktiviert={vonAnderemReserviert}
              />
            ) : versandbestaetigungen[selected.id] ? (
              <div className="px-6 py-4" style={{ borderBottom: `1px solid ${tokens.line}` }}>
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
              <div className="px-6 py-4 flex flex-wrap items-center justify-between gap-3 antwort-bereich" style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted, borderBottom: `1px solid ${tokens.line}` }}>
                <span>Noch keine Antwort begonnen.</span>
                <AntwortAktionen mail={selected} onErzeugt={onReload} deaktiviert={vonAnderemReserviert} />
              </div>
            )}
            {selected.uebersetzung ? (
              <div className="px-6 py-4 mail-uebersetzung" style={{ background: tokens.mossPale, borderBottom: `1px solid ${tokens.line}` }}>
                <div style={{ ...fontMono, fontSize: "10.5px", color: tokens.mossDeep, letterSpacing: "0.05em" }}>
                  DEUTSCHE ARBEITSÜBERSETZUNG · ORIGINALSPRACHE: {selected.originalsprache.toUpperCase()}
                </div>
                <div style={{ ...fontSerif, fontSize: "15px", lineHeight: 1.65, whiteSpace: "pre-wrap", overflowWrap: "anywhere", marginTop: "8px" }}>
                  {selected.uebersetzung}
                </div>
              </div>
            ) : selected.uebersetzungFehlt ? (
              <div className="px-6 py-3 flex flex-wrap items-center justify-between gap-3 mail-uebersetzung" style={{ background: tokens.amberPale, borderBottom: `1px solid ${tokens.line}` }}>
                <div style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted }}>
                  {uebersetzungsstatus[selected.id]?.status === "fehler"
                    ? uebersetzungsstatus[selected.id].fehler
                    : "Deutsche Arbeitsübersetzung wird erstellt …"}
                </div>
                {uebersetzungsstatus[selected.id]?.status === "fehler" && (
                  <button type="button" onClick={() => uebersetzungStarten(selected)} disabled={vonAnderemReserviert} className="px-2.5 py-1.5 disabled:opacity-50" style={AUSWAHL_BUTTON_STIL}>
                    Erneut versuchen
                  </button>
                )}
              </div>
            ) : null}
            {selected.istFremdsprache && (
              <div className="px-6 pt-4 mail-original-label" style={{ ...fontMono, fontSize: "10.5px", color: tokens.inkMuted, letterSpacing: "0.05em" }}>
                ORIGINAL · {selected.originalsprache.toUpperCase()}
              </div>
            )}
            <MailInhalt key={selected.id} mail={selected} />
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
      <StatusMeldung
        text={statusMeldung}
        onSchliessen={() => setStatusMeldung("")}
      />
    </div>
  );
}

function EntwurfPanel({
  entwurf, kiPruefung, originalsprache, onErledigt, onVersendet,
  deaktiviert = false,
}) {
  const [text, setText] = useState(entwurf.text);
  const [anhaenge, setAnhaenge] = useState([]);
  const [prueft, setPrueft] = useState(false);
  const [probleme, setProbleme] = useState([]);
  const [fehler, setFehler] = useState("");
  const [naechsterOhnePruefung, setNaechsterOhnePruefung] = useState(false);
  const [versanderfolg, setVersanderfolg] = useState(null);
  const dateiEingabe = useRef(null);

  function anhaengeAuswaehlen(event) {
    const neueDateien = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (neueDateien.length === 0) return;
    const auswahl = [...anhaenge, ...neueDateien];
    if (auswahl.length > MAX_ANTWORTANHAENGE) {
      setFehler(`Maximal ${MAX_ANTWORTANHAENGE} Anhänge pro Antwort erlaubt.`);
      return;
    }
    const gesamtgroesse = auswahl.reduce((summe, datei) => summe + datei.size, 0);
    if (gesamtgroesse > MAX_ANTWORTANHAENGE_BYTES) {
      setFehler("Anhänge dürfen zusammen höchstens 18 MB groß sein.");
      return;
    }
    setFehler("");
    setAnhaenge(auswahl);
  }

  function anhangEntfernen(index) {
    setAnhaenge((aktuell) => aktuell.filter((_, position) => position !== index));
  }

  async function freigeben() {
    setPrueft(true);
    setProbleme([]);
    setFehler("");
    setVersanderfolg(null);
    try {
      const ergebnis = await api.entwurfFreigeben(entwurf.id, text, anhaenge);
      if (ergebnis.status === "pruefung_noetig") {
        setProbleme(ergebnis.probleme ?? ["Die Antwort benötigt noch eine Prüfung."]);
        setNaechsterOhnePruefung(Boolean(ergebnis.naechster_versuch_ohne_pruefung));
      } else {
        setVersanderfolg({
          empfaenger: ergebnis.empfaenger,
          bcc: ergebnis.bcc,
          messageId: ergebnis.message_id,
          anhaenge: ergebnis.anhaenge ?? [],
        });
        onVersendet({
          empfaenger: ergebnis.empfaenger,
          bcc: ergebnis.bcc,
          messageId: ergebnis.message_id,
          anhaenge: ergebnis.anhaenge ?? [],
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
    <div className="px-6 py-4 flex flex-col entwurf-panel" style={{ borderBottom: `1px solid ${tokens.line}` }}>
      <div style={{ ...fontMono, fontSize: "10.5px", color: tokens.amber, letterSpacing: "0.05em" }}>ANTWORTENTWURF · DEUTSCHE ARBEITSFASSUNG · WARTET AUF FREIGABE</div>
      <textarea value={text} onChange={(e) => setText(e.target.value)} disabled={deaktiviert} className="mt-2 p-3 resize-y disabled:opacity-70"
        style={{ ...fontSerif, fontSize: "14.5px", background: tokens.paperRaised, border: `1px solid ${tokens.line}`, borderRadius: "6px", minHeight: "320px" }} />
      <div className="flex items-center gap-2 mt-3 flex-wrap">
        <input
          ref={dateiEingabe}
          type="file"
          multiple
          onChange={anhaengeAuswaehlen}
          disabled={deaktiviert || prueft || Boolean(versanderfolg)}
          style={{ display: "none" }}
        />
        <button
          type="button"
          onClick={() => dateiEingabe.current?.click()}
          disabled={deaktiviert || prueft || Boolean(versanderfolg)}
          className="flex items-center gap-1.5 px-3 py-2 disabled:opacity-60"
          style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted, border: `1px solid ${tokens.line}`, borderRadius: "6px", background: tokens.paperRaised }}
        >
          <Paperclip size={13} /> Anhänge hinzufügen
        </button>
        <span style={{ ...fontUI, fontSize: "11.5px", color: tokens.inkMuted }}>
          Maximal 10 Dateien, zusammen 18 MB
        </span>
      </div>
      {anhaenge.length > 0 && (
        <div className="mt-2 flex flex-col gap-1.5">
          {anhaenge.map((datei, index) => (
            <div key={`${datei.name}-${datei.lastModified}-${index}`} className="flex items-center justify-between gap-3 px-3 py-2" style={{ background: tokens.paperRaised, border: `1px solid ${tokens.line}`, borderRadius: "6px" }}>
              <div className="flex items-center gap-2 min-w-0">
                <Paperclip size={13} color={tokens.mossDeep} />
                <span title={datei.name} className="truncate" style={{ ...fontUI, fontSize: "12.5px", color: tokens.ink }}>
                  {datei.name}
                </span>
                <span style={{ ...fontUI, fontSize: "11.5px", color: tokens.inkMuted, whiteSpace: "nowrap" }}>
                  {lesbareDateigroesse(datei.size)}
                </span>
              </div>
              <button type="button" onClick={() => anhangEntfernen(index)} disabled={deaktiviert || prueft} title="Anhang entfernen" className="p-1 disabled:opacity-60" style={{ color: tokens.rust }}>
                <X size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
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
            {versanderfolg.anhaenge.length > 0 && <>Anhänge: {versanderfolg.anhaenge.join(", ")}<br /></>}
            SMTP-Nachrichten-ID: {versanderfolg.messageId}
          </div>
        </div>
      )}
      <div className="flex items-center gap-2 mt-3">
        <button onClick={freigeben} disabled={deaktiviert || prueft || Boolean(versanderfolg)} className="flex items-center gap-1.5 px-3 py-2 disabled:opacity-60" style={{ ...fontUI, fontSize: "13px", fontWeight: 600, color: "#fff", background: tokens.moss, borderRadius: "6px" }}>
          <Check size={13} /> {prueft
            ? (!kiPruefung || naechsterOhnePruefung ? "Antwort wird versendet …" : "Antwort wird geprüft …")
            : (versanderfolg
              ? "An Mailserver übergeben"
              : (naechsterOhnePruefung ? "Trotzdem senden" : "Antwort freigeben"))}
        </button>
        <button onClick={verwerfen} disabled={deaktiviert} className="flex items-center gap-1.5 px-3 py-2 disabled:opacity-60" style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted, border: `1px solid ${tokens.line}`, borderRadius: "6px" }}>
          <X size={13} /> Verwerfen
        </button>
      </div>
      <div style={{ ...fontUI, fontSize: "11.5px", color: tokens.inkMuted, marginTop: "8px" }}>
        {kiPruefung
          ? "Vor dem Versand prüft die KI die Antwort auf offene Punkte. Die Antwort geht an den Absender der Kundenmail, eine Kontrollkopie per BCC an info@erikschweitzer.de."
          : "Diese Antwort wird ohne inhaltliche KI-Prüfung an den Absender versendet. Eine Kontrollkopie geht per BCC an info@erikschweitzer.de."}
        {originalsprache && !istDeutscheSprache(originalsprache)
          ? ` Du bearbeitest ausschließlich die deutsche Arbeitsfassung. Unmittelbar vor dem Versand übersetzt Krautl sie automatisch in ${originalsprache}.`
          : ""}
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

function EinstellungenMenu({ active, onWaehlen, istAdmin }) {
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
          {istAdmin && (
            <button onClick={() => { onWaehlen("rollen"); setOffen(false); }} className="w-full text-left px-3.5 py-2"
              style={{ ...fontUI, fontSize: "13px", color: tokens.ink }}>
              Rollen & Mailzugriff
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function KlassifikationZeile({ klassifikation: k, onGespeichert }) {
  const fachlicheAufgaben = (k.aufgaben ?? []).map((a) => a.aufgabe_typ);
  const [beschreibung, setBeschreibung] = useState(k.beschreibung ?? "");
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
        beschreibung,
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
        <textarea
          value={beschreibung}
          onChange={(e) => { setBeschreibung(e.target.value); setMeldung(""); }}
          maxLength={4000}
          rows={4}
          aria-label={`Beschreibung für ${k.klassifikation_id}`}
          style={{ ...fontSerif, fontSize: "13px", lineHeight: 1.4, color: tokens.ink, width: "100%", marginTop: "5px", padding: "7px 8px", resize: "vertical", background: tokens.paper, border: `1px solid ${tokens.line}`, borderRadius: "5px" }}
        />
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
  const laufenderAbruf = useRef(null);

  const laden = useCallback(async ({
    imHintergrund = false,
    nachLaufendemAbruf = false,
  } = {}) => {
    while (laufenderAbruf.current) {
      if (imHintergrund && !nachLaufendemAbruf) return laufenderAbruf.current;
      await laufenderAbruf.current;
    }

    const abruf = (async () => {
      try {
        const istAdmin = benutzer?.rolle === "admin";
        const [health, mails, mailZaehler, katalog, rechnungen, faq, faqVorschlaege, wissensbasis, wissensvorschlaege, entwuerfe, rollenMailzugriff] = await Promise.all([
          api.health(), api.mails(alleMails), api.mailZaehler(), api.klassifikationen(), api.rechnungen(), api.faq(), api.faqVorschlaege(), api.wissensbasis(), api.wissensvorschlaege(), api.entwuerfe(alleMails),
          istAdmin ? api.rollenMailzugriff() : Promise.resolve(null),
        ]);
        setDaten({ health, mails, mailZaehler, katalog, rechnungen, faq, faqVorschlaege, wissensbasis, wissensvorschlaege, entwuerfe, rollenMailzugriff });
        setFehler(null);
      } catch (e) {
        if (e.status === 401) {
          onNichtAngemeldet();
          return;
        }
        // Ein vorübergehender Hintergrundfehler soll die bereits sichtbare
        // Oberfläche nicht durch eine Fehlerseite ersetzen.
        if (!imHintergrund) setFehler(e.message);
      }
    })();
    laufenderAbruf.current = abruf;
    try {
      await abruf;
    } finally {
      if (laufenderAbruf.current === abruf) laufenderAbruf.current = null;
    }
  }, [onNichtAngemeldet, benutzer, alleMails]);

  const mailspalteLaden = useCallback(async () => {
    if (document.visibilityState !== "visible") return undefined;
    if (laufenderAbruf.current) return laufenderAbruf.current;

    const abruf = (async () => {
      try {
        const [mails, mailZaehler] = await Promise.all([
          api.mails(alleMails),
          api.mailZaehler(),
        ]);
        setDaten((aktuell) => (
          aktuell ? { ...aktuell, mails, mailZaehler } : aktuell
        ));
      } catch (e) {
        if (e.status === 401) onNichtAngemeldet();
        // Ein fehlgeschlagener Kurzabruf lässt die vorhandene Liste stehen.
        // Der vollständige 30-Sekunden-Abruf versucht es erneut.
      }
    })();
    laufenderAbruf.current = abruf;
    try {
      await abruf;
    } finally {
      if (laufenderAbruf.current === abruf) laufenderAbruf.current = null;
    }
    return undefined;
  }, [onNichtAngemeldet, alleMails]);

  useEffect(() => {
    laden();

    const vollstaendigesIntervall = window.setInterval(
      () => {
        if (document.visibilityState === "visible") {
          laden({ imHintergrund: true, nachLaufendemAbruf: true });
        }
      },
      30_000,
    );
    const mailspaltenIntervall = window.setInterval(
      () => mailspalteLaden(),
      10_000,
    );
    const beiRueckkehr = () => {
      if (document.visibilityState === "visible") {
        laden({ imHintergrund: true, nachLaufendemAbruf: true });
      }
    };
    document.addEventListener("visibilitychange", beiRueckkehr);
    window.addEventListener("focus", beiRueckkehr);

    return () => {
      window.clearInterval(vollstaendigesIntervall);
      window.clearInterval(mailspaltenIntervall);
      document.removeEventListener("visibilitychange", beiRueckkehr);
      window.removeEventListener("focus", beiRueckkehr);
    };
  }, [laden, mailspalteLaden]);

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
  const [alleMails, setAlleMails] = useState(true);
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
        originalsprache: m.originalsprache,
        prioritaet: String(klass?.standard_prio || "normal").toLowerCase(),
        betreffDeutsch: m.betreff_deutsch,
        uebersetzung: m.text_deutsch,
        istFremdsprache: Boolean(m.originalsprache && !istDeutscheSprache(m.originalsprache)),
        uebersetzungFehlt: !m.originalsprache || Boolean(
          m.originalsprache
          && !istDeutscheSprache(m.originalsprache)
          && !m.text_deutsch
        ),
        zeit: formatMailZeit(m.empfangen_am),
        konfidenz: m.konfidenz,
        aufgaben: m.aufgaben ?? [],
        bestaetigungErforderlich: Boolean(m.bestaetigung_erforderlich),
        zustaendigAdmin: Boolean(m.zustaendig_admin),
        zustaendigSachbearbeiter: Boolean(m.zustaendig_sachbearbeiter),
        zuweisbareRollen: m.zuweisbare_rollen ?? ["admin", "sachbearbeiter"],
        zustaendigkeitLabel: (() => {
          if (m.zustaendig_admin && m.zustaendig_sachbearbeiter) return "Erik, Guri, Ludwig und Aneta";
          if (m.zustaendig_admin) return "Erik (Admin)";
          if (m.zustaendig_sachbearbeiter) return "Guri, Ludwig, Aneta (Sachbearbeitung)";
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
        reservierung: m.reservierung ? {
          benutzername: m.reservierung.benutzername,
          name: m.reservierung.name,
          letzterKontakt: m.reservierung.letzter_kontakt,
          laeuftAb: m.reservierung.laeuft_ab,
        } : null,
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
          <EinstellungenMenu
            active={["klassifikationen", "aktionslog", "rollen"].includes(tab)}
            onWaehlen={setTab}
            istAdmin={benutzer.rolle === "admin"}
          />
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
        mailZaehler={daten.mailZaehler}
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
