import { useEffect, useMemo, useState, useRef } from "react";
import {
  Search, ChevronRight, ChevronDown, CheckCircle2, PenLine, Send, Paperclip, X,
  Inbox as InboxIcon, Receipt, BookOpen, Check, FolderCog, Sparkles, Settings,
} from "lucide-react";
import { api } from "./api.js";

const tokens = {
  paper: "#F5F3E6",
  paperRaised: "#FCFBF4",
  ink: "#242A1F",
  inkMuted: "#6C6F5F",
  line: "#DDD9C4",
  moss: "#4C9A2A",
  mossDeep: "#2F5E1C",
  mossPale: "#E5EFD5",
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

function formatDatum(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("de-DE", { timeZone: ZEITZONE });
}

function formatZeitpunkt(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: ZEITZONE });
}

function formatBetrag(wert) {
  if (wert == null) return "";
  return wert.toLocaleString("de-DE", { style: "currency", currency: "EUR" });
}

// Festes Set von Aktion_IDs (siehe data/mail-klassifikationen.csv). Neue
// Aktionen brauchen jeweils eigenen Code in worker.py — dies ist nur die
// Anzeige, welche davon aktuell tatsächlich etwas auslösen.
const AKTION_LABEL = {
  MAIL_VERSCHIEBEN: "Mail verschieben",
  RECHNUNG_VERWALTEN: "Rechnung verwalten",
  LIEFERANTENMAIL_BEARBEITEN: "Lieferantenmail bearbeiten",
  MARKETINGMAIL_BEARBEITEN: "Marketingmail bearbeiten",
  AUDIO_TRANSKRIBIEREN: "Audio transkribieren",
  SYSTEMMELDUNG_BEARBEITEN: "Systemmeldung bearbeiten",
  RECHTSSACHE_BEARBEITEN: "Rechtssache bearbeiten",
};
const AKTIVE_AKTIONEN = new Set(["MAIL_VERSCHIEBEN"]);

const EREIGNIS_LABEL = {
  klassifiziert: "Klassifiziert",
  verschoben: "Verschoben",
  verschieben_fehlgeschlagen: "Verschieben fehlgeschlagen",
};
function farbeFuerEreignis(ereignis) {
  if (ereignis === "verschieben_fehlgeschlagen") return tokens.rust;
  if (ereignis === "verschoben") return tokens.moss;
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

function NavTab({ icon: Icon, label, count, active, onClick, accent }) {
  return (
    <button onClick={onClick} className="flex items-center gap-2 px-3.5 py-2.5 relative"
      style={{ ...fontUI, fontSize: "13.5px", fontWeight: active ? 600 : 500, color: active ? tokens.mossDeep : tokens.inkMuted }}>
      <Icon size={15} />
      {label}
      {count != null && (
        <span className="px-1.5 rounded-full" style={{ ...fontMono, fontSize: "10.5px", background: accent ? tokens.amberPale : tokens.mossPale, color: accent ? tokens.amber : tokens.mossDeep }}>
          {count}
        </span>
      )}
      {active && <span className="absolute left-0 right-0" style={{ bottom: "-1px", height: "2px", background: tokens.mossDeep }} />}
    </button>
  );
}

function KategorieKorrektur({ mail, katalog, onKorrigiert }) {
  const [offen, setOffen] = useState(false);
  const [wird_gesendet, setWirdGesendet] = useState(false);

  async function korrigieren(neueId) {
    if (!neueId || neueId === mail.klassifikation_id) { setOffen(false); return; }
    setWirdGesendet(true);
    try {
      await api.korrigiereKlassifikation(mail.id, neueId);
      await onKorrigiert();
    } finally {
      setWirdGesendet(false);
      setOffen(false);
    }
  }

  if (!offen) {
    return (
      <button onClick={() => setOffen(true)} className="flex items-center gap-1.5 px-2.5 py-1"
        style={{ ...fontUI, fontSize: "12px", color: tokens.inkMuted, border: `1px solid ${tokens.line}`, borderRadius: "6px" }}>
        Kategorie korrigieren <ChevronRight size={12} />
      </button>
    );
  }

  return (
    <select
      autoFocus
      disabled={wird_gesendet}
      defaultValue={mail.klassifikation_id ?? ""}
      onChange={(e) => korrigieren(e.target.value)}
      onBlur={() => setOffen(false)}
      className="px-2 py-1"
      style={{ ...fontMono, fontSize: "11.5px", border: `1px solid ${tokens.line}`, borderRadius: "6px", background: tokens.paperRaised }}
    >
      <option value="" disabled>Klassifikation wählen …</option>
      {katalog.map((k) => (
        <option key={k.klassifikation_id} value={k.klassifikation_id}>
          {k.klassifikation_id} — {k.hauptkategorie} / {k.unterkategorie}
        </option>
      ))}
    </select>
  );
}

function PosteingangView({ mails, katalog, onReload }) {
  const [filter, setFilter] = useState(null);
  const [selectedId, setSelectedId] = useState(mails[0]?.id ?? null);

  const kategorien = [...new Set(mails.map((m) => m.kat))];
  const sichtbar = filter ? mails.filter((m) => m.kat === filter) : mails;
  const selected = mails.find((m) => m.id === selectedId) ?? sichtbar[0] ?? null;

  if (mails.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center" style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted }}>
        Noch keine Mails abgerufen — der minütliche Postfach-Abruf läuft im Hintergrund.
      </div>
    );
  }

  return (
    <div className="flex flex-1 min-h-0">
      <div className="flex flex-col" style={{ width: "380px", borderRight: `1px solid ${tokens.line}` }}>
        <div className="flex items-center gap-2 px-4 py-3" style={{ borderBottom: `1px solid ${tokens.line}` }}>
          <Search size={14} style={{ color: tokens.inkMuted }} />
          <span style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted }}>Mails durchsuchen …</span>
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
            <button key={m.id} onClick={() => setSelectedId(m.id)} className="w-full text-left px-4 py-3 flex flex-col gap-1.5"
              style={{ borderBottom: `1px solid ${tokens.line}`, background: selected?.id === m.id ? tokens.mossPale : "transparent" }}>
              <div className="flex items-center justify-between gap-2">
                <Badge label={m.katId} color={farbeFuerKategorie(m.kat)} />
                <span style={{ ...fontMono, fontSize: "11px", color: tokens.inkMuted }}>{m.zeit}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span style={{ ...fontSerif, fontSize: "14px", fontWeight: 600 }}>{m.absender}</span>
              </div>
              <div style={{ ...fontSerif, fontSize: "13.5px" }}>{m.betreff}</div>
              <Konfidenz value={m.konfidenz} />
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 flex flex-col overflow-y-auto">
        {selected && (
          <>
            <div className="px-6 pt-5 pb-4" style={{ borderBottom: `1px solid ${tokens.line}` }}>
              <div className="flex items-center justify-between">
                <Badge label={selected.katId} color={farbeFuerKategorie(selected.kat)} />
                <KategorieKorrektur mail={selected} katalog={katalog} onKorrigiert={onReload} />
              </div>
              <h2 style={{ ...fontDisplay, fontSize: "19px", marginTop: "12px" }}>{selected.betreff}</h2>
              <div style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted, marginTop: "4px" }}>{selected.absender} · {selected.zeit} Uhr</div>
            </div>
            <div className="px-6 py-4" style={{ ...fontSerif, fontSize: "15px", lineHeight: 1.65, borderBottom: `1px solid ${tokens.line}` }}>{selected.snippet}</div>
            {Object.keys(selected.felder).length > 0 && (
              <div className="px-6 py-4 grid grid-cols-2 gap-3" style={{ borderBottom: `1px solid ${tokens.line}` }}>
                {Object.entries(selected.felder).map(([k, v]) => (
                  <div key={k}>
                    <div style={{ ...fontMono, fontSize: "10.5px", color: tokens.inkMuted, letterSpacing: "0.05em" }}>{k.toUpperCase()}</div>
                    <div style={{ ...fontUI, fontSize: "13.5px", fontWeight: 600, marginTop: "2px" }}>{v}</div>
                  </div>
                ))}
              </div>
            )}
            {selected.entwurf ? (
              <EntwurfPanel entwurf={selected.entwurf} onErledigt={onReload} />
            ) : (
              <div className="px-6 py-8 flex-1 flex items-center justify-center" style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted }}>
                Für diese Mail ist keine Antwort vorgesehen — Aktion läuft autonom.
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function EntwurfPanel({ entwurf, onErledigt }) {
  const [text, setText] = useState(entwurf.text);

  async function freigeben() {
    await api.entwurfFreigeben(entwurf.id, text);
    await onErledigt();
  }
  async function verwerfen() {
    await api.entwurfVerwerfen(entwurf.id);
    await onErledigt();
  }

  return (
    <div className="px-6 py-4 flex-1 flex flex-col">
      <div style={{ ...fontMono, fontSize: "10.5px", color: tokens.amber, letterSpacing: "0.05em" }}>ANTWORTENTWURF · WARTET AUF FREIGABE</div>
      <textarea value={text} onChange={(e) => setText(e.target.value)} className="mt-2 flex-1 p-3 resize-none"
        style={{ ...fontSerif, fontSize: "14.5px", background: tokens.paperRaised, border: `1px solid ${tokens.line}`, borderRadius: "6px", minHeight: "100px" }} />
      <div className="flex items-center gap-2 mt-3">
        <button onClick={freigeben} className="flex items-center gap-1.5 px-3 py-2" style={{ ...fontUI, fontSize: "13px", fontWeight: 600, color: "#fff", background: tokens.moss, borderRadius: "6px" }}>
          <Send size={13} /> Freigeben &amp; senden
        </button>
        <button onClick={verwerfen} className="flex items-center gap-1.5 px-3 py-2" style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted, border: `1px solid ${tokens.line}`, borderRadius: "6px" }}>
          <X size={13} /> Verwerfen
        </button>
      </div>
    </div>
  );
}

function RechnungenView({ rechnungen, onReload }) {
  const offen = rechnungen.filter((r) => r.zahlungsstatus !== "bezahlt");
  const bezahlt = rechnungen.filter((r) => r.zahlungsstatus === "bezahlt");

  async function alsBezahlt(id) {
    await api.rechnungAlsBezahlt(id);
    await onReload();
  }

  return (
    <div className="flex-1 overflow-y-auto px-8 py-6">
      <h2 style={{ ...fontDisplay, fontSize: "20px", color: tokens.mossDeep, marginBottom: "4px" }}>Offene Rechnungen</h2>
      <div className="flex items-center gap-1.5 mb-5" style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted }}>
        <FolderCog size={13} />
        Anhänge werden unabhängig hiervon automatisch abgelegt unter <span style={{ ...fontMono, fontSize: "11.5px" }}>/Rechnungen/{"{Jahr}"}/{"{Monat}"}/</span>
      </div>

      <div style={{ border: `1px solid ${tokens.line}`, borderRadius: "8px", overflow: "hidden", background: tokens.paperRaised }}>
        <div className="grid px-4 py-2.5" style={{ gridTemplateColumns: "1.6fr 1fr 1fr 1fr 1.2fr", ...fontMono, fontSize: "10.5px", color: tokens.inkMuted, letterSpacing: "0.05em", borderBottom: `1px solid ${tokens.line}` }}>
          <div>AUSSTELLER</div><div>RECHNUNG-NR.</div><div>BETRAG</div><div>FÄLLIG AM</div><div></div>
        </div>
        {offen.map((r) => (
          <div key={r.id} className="grid items-center px-4 py-3" style={{ gridTemplateColumns: "1.6fr 1fr 1fr 1fr 1.2fr", borderBottom: `1px solid ${tokens.line}` }}>
            <div style={{ ...fontSerif, fontSize: "14.5px", fontWeight: 600 }}>{r.aussteller}</div>
            <div style={{ ...fontMono, fontSize: "12.5px", color: tokens.inkMuted }}>{r.rechnungsnummer}</div>
            <div style={{ ...fontMono, fontSize: "13px" }}>{formatBetrag(r.bruttobetrag)}</div>
            <div style={{ ...fontUI, fontSize: "13px", color: tokens.amber, fontWeight: 600 }}>{formatDatum(r.faellig_am)}</div>
            <button onClick={() => alsBezahlt(r.id)} className="flex items-center gap-1.5 px-2.5 py-1 justify-self-start"
              style={{ ...fontUI, fontSize: "12px", color: tokens.moss, border: `1px solid ${tokens.moss}`, borderRadius: "6px" }}>
              <Check size={12} /> Als bezahlt markieren
            </button>
          </div>
        ))}
        {offen.length === 0 && (
          <div className="px-4 py-6 text-center" style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted }}>Keine offenen Rechnungen.</div>
        )}
      </div>

      <h3 className="mt-7 mb-3" style={{ ...fontDisplay, fontSize: "15px", color: tokens.inkMuted }}>Erledigt</h3>
      <div className="flex flex-col gap-1.5">
        {bezahlt.map((r) => (
          <div key={r.id} className="flex items-center gap-3 px-3 py-2" style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted }}>
            <CheckCircle2 size={14} style={{ color: tokens.moss }} />
            <span style={{ textDecoration: "line-through" }}>{r.aussteller} · {r.rechnungsnummer}</span>
            <span style={{ ...fontMono, fontSize: "12px", marginLeft: "auto" }}>{formatBetrag(r.bruttobetrag)}</span>
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
    <div className="relative" ref={ref}>
      <button onClick={() => setOffen((o) => !o)} className="flex items-center gap-2 px-3.5 py-2.5 relative"
        style={{ ...fontUI, fontSize: "13.5px", fontWeight: active ? 600 : 500, color: active ? tokens.mossDeep : tokens.inkMuted }}>
        <Settings size={15} /> Einstellungen <ChevronDown size={12} />
        {active && <span className="absolute left-0 right-0" style={{ bottom: "-1px", height: "2px", background: tokens.mossDeep }} />}
      </button>
      {offen && (
        <div className="absolute z-10 py-1" style={{ top: "100%", left: 0, minWidth: "200px", background: tokens.paperRaised, border: `1px solid ${tokens.line}`, borderRadius: "6px", boxShadow: "0 4px 12px rgba(0,0,0,0.08)" }}>
          <button onClick={() => { onWaehlen("klassifikationen"); setOffen(false); }} className="w-full text-left px-3.5 py-2"
            style={{ ...fontUI, fontSize: "13px", color: tokens.ink }}>
            Mail-Klassifikationen
          </button>
          <button onClick={() => { onWaehlen("aktionslog"); setOffen(false); }} className="w-full text-left px-3.5 py-2"
            style={{ ...fontUI, fontSize: "13px", color: tokens.ink }}>
            Aktionslog
          </button>
        </div>
      )}
    </div>
  );
}

function KlassifikationenView({ katalog }) {
  return (
    <div className="flex-1 overflow-y-auto px-8 py-6">
      <h2 style={{ ...fontDisplay, fontSize: "20px", color: tokens.mossDeep, marginBottom: "4px" }}>Mail-Klassifikationen</h2>
      <p className="mb-5" style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted }}>
        Legt fest, wie eingehende Mails eingeordnet werden und was danach automatisch passiert.
        Nur lesbar — Bearbeiten folgt später. {katalog.length} Einträge.
      </p>

      <div style={{ border: `1px solid ${tokens.line}`, borderRadius: "8px", overflow: "hidden", background: tokens.paperRaised }}>
        <div className="grid px-4 py-2.5" style={{ gridTemplateColumns: "1.4fr 2fr 1fr 1fr 1.6fr", ...fontMono, fontSize: "10.5px", color: tokens.inkMuted, letterSpacing: "0.05em", borderBottom: `1px solid ${tokens.line}` }}>
          <div>ID</div><div>BESCHREIBUNG</div><div>PRIO</div><div>ZIEL</div><div>AKTION</div>
        </div>
        {katalog.map((k) => {
          const aktiv = AKTIVE_AKTIONEN.has(k.aktion_id);
          return (
            <div key={k.klassifikation_id} className="grid items-start px-4 py-3" style={{ gridTemplateColumns: "1.4fr 2fr 1fr 1fr 1.6fr", borderBottom: `1px solid ${tokens.line}` }}>
              <div>
                <Badge label={k.klassifikation_id} color={farbeFuerKategorie(k.hauptkategorie)} />
              </div>
              <div>
                <div style={{ ...fontSerif, fontSize: "14px", fontWeight: 600 }}>{k.hauptkategorie} · {k.unterkategorie}</div>
                <div style={{ ...fontSerif, fontSize: "13px", color: tokens.inkMuted, marginTop: "2px" }}>{k.beschreibung}</div>
              </div>
              <div style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted }}>{k.standard_prio}</div>
              <div style={{ ...fontMono, fontSize: "11.5px", color: tokens.inkMuted }}>
                {k.zielpostfach ? <>{k.zielpostfach}<br />{k.zielordner}</> : "—"}
              </div>
              <div className="flex items-center gap-1.5">
                <span title={aktiv ? "Läuft automatisch" : "Noch nicht automatisiert"}
                  className="inline-block rounded-full" style={{ width: "7px", height: "7px", background: aktiv ? tokens.moss : tokens.line, flexShrink: 0 }} />
                <span style={{ ...fontUI, fontSize: "12.5px" }}>{AKTION_LABEL[k.aktion_id] ?? k.aktion_id}</span>
              </div>
            </div>
          );
        })}
        {katalog.length === 0 && (
          <div className="px-4 py-6 text-center" style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted }}>
            Noch keine Klassifikationen importiert.
          </div>
        )}
      </div>
    </div>
  );
}

function AktionslogView({ eintraege }) {
  return (
    <div className="flex-1 overflow-y-auto px-8 py-6">
      <h2 style={{ ...fontDisplay, fontSize: "20px", color: tokens.mossDeep, marginBottom: "4px" }}>Aktionslog</h2>
      <p className="mb-5" style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted }}>
        Was der Postfach-Abruf tatsächlich getan hat — Klassifizierungen und Verschiebe-Versuche,
        neueste zuerst.
      </p>

      <div style={{ border: `1px solid ${tokens.line}`, borderRadius: "8px", overflow: "hidden", background: tokens.paperRaised }}>
        <div className="grid px-4 py-2.5" style={{ gridTemplateColumns: "1.1fr 1.4fr 1.6fr 2.5fr", ...fontMono, fontSize: "10.5px", color: tokens.inkMuted, letterSpacing: "0.05em", borderBottom: `1px solid ${tokens.line}` }}>
          <div>ZEIT</div><div>EREIGNIS</div><div>MAIL</div><div>DETAIL</div>
        </div>
        {eintraege.map((e) => (
          <div key={e.id} className="grid items-start px-4 py-3" style={{ gridTemplateColumns: "1.1fr 1.4fr 1.6fr 2.5fr", borderBottom: `1px solid ${tokens.line}` }}>
            <div style={{ ...fontMono, fontSize: "12px", color: tokens.inkMuted }}>{formatZeitpunkt(e.erstellt_am)}</div>
            <div>
              <Badge label={(EREIGNIS_LABEL[e.ereignis] ?? e.ereignis).toUpperCase()} color={farbeFuerEreignis(e.ereignis)} />
            </div>
            <div style={{ ...fontSerif, fontSize: "13.5px" }}>{e.mailLabel}</div>
            <div style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted, wordBreak: "break-word" }}>{e.detail}</div>
          </div>
        ))}
        {eintraege.length === 0 && (
          <div className="px-4 py-6 text-center" style={{ ...fontUI, fontSize: "13px", color: tokens.inkMuted }}>
            Noch keine Aktionen protokolliert.
          </div>
        )}
      </div>
    </div>
  );
}

function verwendeKrautlDaten() {
  const [daten, setDaten] = useState(null);
  const [fehler, setFehler] = useState(null);

  async function laden() {
    try {
      const [mails, katalog, rechnungen, faq, faqVorschlaege, entwuerfe, aktionslog] = await Promise.all([
        api.mails(), api.klassifikationen(), api.rechnungen(), api.faq(), api.faqVorschlaege(), api.entwuerfe(), api.aktionslog(),
      ]);
      setDaten({ mails, katalog, rechnungen, faq, faqVorschlaege, entwuerfe, aktionslog });
      setFehler(null);
    } catch (e) {
      setFehler(e.message);
    }
  }

  useEffect(() => { laden(); }, []);

  return { daten, fehler, neuLaden: laden };
}

export default function KrautlUI() {
  const [tab, setTab] = useState("posteingang");
  const { daten, fehler, neuLaden } = verwendeKrautlDaten();

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
        betreff: m.betreff,
        snippet: m.text_auszug,
        zeit: formatZeit(m.empfangen_am),
        konfidenz: m.konfidenz,
        felder,
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

    const aktionslog = daten.aktionslog.map((e) => {
      const mail = e.mail_id != null ? mailsNachId[e.mail_id] : null;
      return {
        ...e,
        mailLabel: mail ? mail.betreff : e.mail_id != null ? `Mail #${e.mail_id}` : "—",
      };
    });

    return { mails, faqVorschlaege, aktionslog };
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
  const offeneRechnungen = daten.rechnungen.filter((r) => r.zahlungsstatus !== "bezahlt").length;

  return (
    <div className="w-full h-full flex flex-col" style={{ background: tokens.paper, minHeight: "640px", color: tokens.ink }}>
      <header className="flex items-center px-5" style={{ borderBottom: `1px solid ${tokens.line}`, background: tokens.paperRaised }}>
        <div className="flex items-baseline gap-1.5 pr-5 py-2.5" style={{ borderRight: `1px solid ${tokens.line}`, marginRight: "8px" }}>
          <span style={{ ...fontDisplay, fontSize: "19px", color: tokens.mossDeep }}>Krautl</span>
          <span style={{ ...fontMono, fontSize: "10px", color: tokens.inkMuted }}>dreikraut</span>
        </div>
        <nav className="flex items-center">
          <NavTab icon={InboxIcon} label="Posteingang" active={tab === "posteingang"} onClick={() => setTab("posteingang")} />
          <NavTab icon={Receipt} label="Rechnungen" count={offeneRechnungen} accent active={tab === "rechnungen"} onClick={() => setTab("rechnungen")} />
          <NavTab icon={BookOpen} label="Wissensdatenbank" count={abgeleitet.faqVorschlaege.length} accent active={tab === "wissen"} onClick={() => setTab("wissen")} />
          <EinstellungenMenu active={tab === "klassifikationen" || tab === "aktionslog"} onWaehlen={setTab} />
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <PenLine size={13} style={{ color: tokens.amber }} />
          <span style={{ ...fontUI, fontSize: "12.5px", color: tokens.inkMuted }}>{entwuerfeOffen} Entwürfe warten auf Freigabe</span>
        </div>
      </header>

      {tab === "posteingang" && <PosteingangView mails={abgeleitet.mails} katalog={daten.katalog} onReload={neuLaden} />}
      {tab === "rechnungen" && <RechnungenView rechnungen={daten.rechnungen} onReload={neuLaden} />}
      {tab === "wissen" && <WissensdatenbankView faqEintraege={daten.faq} faqVorschlaege={abgeleitet.faqVorschlaege} onReload={neuLaden} />}
      {tab === "klassifikationen" && <KlassifikationenView katalog={daten.katalog} />}
      {tab === "aktionslog" && <AktionslogView eintraege={abgeleitet.aktionslog} />}
    </div>
  );
}
