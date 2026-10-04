import { useEffect, useState } from "react";
import { RefreshCw, Pencil } from "lucide-react";
import { api } from "./api.js";
import { GoogleFaqAuswahl } from "./GoogleFaqAuswahl.jsx";

const box = { background: "#FDFCEE", border: "1px solid #DDD9C4", borderRadius: "6px" };
const button = { ...box, color: "#2C5A18", fontSize: "13px" };

export function GoogleFaqFeed({ produkt, produkte, faqEintraege, onBearbeiten, onGoogleAuswahlGespeichert }) {
  const [produktId, setProduktId] = useState(produkt?.id || "");
  const [status, setStatus] = useState(null);
  const [vorschau, setVorschau] = useState(null);
  const [fehler, setFehler] = useState("");
  const [laeuft, setLaeuft] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => setProduktId(produkt?.id || ""), [produkt?.id]);
  useEffect(() => setVorschau(null), [produktId]);
  useEffect(() => {
    let aktiv = true;
    const laden = async () => {
      try {
        const [s, p] = await Promise.all([
          api.googleQaStatus(), produktId ? api.googleQaVorschau(produktId) : null,
        ]);
        if (aktiv) { setStatus(s); setVorschau(p); setFehler(""); }
      } catch (e) { if (aktiv) setFehler(e.message); }
    };
    laden();
    const timer = setInterval(laden, 30000);
    return () => { aktiv = false; clearInterval(timer); };
  }, [produktId, faqEintraege, produkte, version]);

  const auswahlGespeichert = async (eintrag) => {
    setVersion((v) => v + 1);
    await onGoogleAuswahlGespeichert(eintrag);
  };
  const generieren = async () => {
    setLaeuft(true); setFehler("");
    try { setStatus(await api.googleQaGenerieren()); setVersion((v) => v + 1); }
    catch (e) { setFehler(e.message); }
    finally { setLaeuft(false); }
  };
  const korrekturen = vorschau?.faq.filter((faq) => faq.ausgewaehlt && !faq.exportiert).length || 0;
  const feedUrl = `${window.location.origin}${status?.feed_pfad || "/feeds/google-product-faq.tsv"}`;

  return <section style={{ fontFamily: "'IBM Plex Sans', sans-serif", fontSize: "13px" }}>
    <div className="flex flex-wrap justify-between items-start gap-3 mb-4">
      <div><h3 style={{ fontFamily: "'Source Serif 4', serif", fontSize: "20px", fontWeight: 700 }}>Google-Merchant-Center-FAQ</h3>
        <p className="mt-1" style={{ color: "#6C6F5F" }}>Haken „Ergänzt die Artikelbeschreibung“ gesetzt: im Google-Export. Ohne Haken: nicht ausgewählt.</p></div>
      <button onClick={generieren} disabled={laeuft} className="flex items-center gap-2 px-3 py-2" style={{ ...button, opacity: laeuft ? 0.6 : 1 }}>
        <RefreshCw size={14} className={laeuft ? "animate-spin" : ""}/>{laeuft ? "Wird erzeugt …" : "Feed neu erzeugen"}
      </button>
    </div>
    <div className="p-4 mb-4" style={box}>
      <div style={{ color: "#6C6F5F" }}>Feed-URL · ohne Anmeldung abrufbar</div>
      <a href={feedUrl} target="_blank" rel="noopener noreferrer" className="block mt-1 break-all underline" style={{ color: "#2C5A18" }}>{feedUrl}</a>
      <div className="flex flex-wrap gap-x-8 gap-y-2 mt-4">
        <span><strong>{status?.anzahl_produkte ?? "–"}</strong> {status?.anzahl_produkte === 1 ? "Produkt" : "Produkte"}</span>
        <span><strong>{status?.anzahl_qa ?? "–"}</strong> {status?.anzahl_qa === 1 ? "Q&A-Paar" : "Q&A-Paare"}</span>
        <span>Letzte Generierung: <strong>{status?.letzte_generierung ? new Date(status.letzte_generierung).toLocaleString("de-DE") : "Noch nicht erzeugt"}</strong></span>
      </div>
      <p className="mt-3" style={{ color: "#6C6F5F" }}>Die Feed-ID ist exakt die gespeicherte Artikelnummer. Sie muss der ID im Google-Hauptfeed entsprechen.</p>
    </div>
    {(fehler || status?.fehler) && <div role="alert" className="p-3 mb-4" style={{ ...box, color: "#9A4024" }}>
      {fehler || status.fehler} Angezeigte Zahlen können vom letzten erfolgreichen Stand stammen.
    </div>}
    {status?.warnungen?.length > 0 ? <details className="p-3 mb-4" style={{ ...box, borderLeft: "4px solid #B07B2E" }} open>
      <summary style={{ fontWeight: 600 }}>{status.warnungen.length} Warnung{status.warnungen.length === 1 ? "" : "en"} · Ausgewählte FAQs bitte korrigieren</summary>
      <ul className="list-disc pl-5 mt-2 space-y-1">{status.warnungen.map((w) => <li key={`${w.produkt_id}-${w.faq_id}`}>{w.meldung}</li>)}</ul>
    </details> : status?.aktuell && <p className="mb-4" style={{ color: "#2C5A18" }}>Keine Validierungswarnungen.</p>}
    <div className="p-4" style={box}>
      <label htmlFor="google-faq-produkt" className="block mb-2" style={{ fontWeight: 600 }}>Produktvorschau</label>
      <select id="google-faq-produkt" value={produktId} onChange={(e) => setProduktId(e.target.value ? Number(e.target.value) : "")} className="w-full p-2" style={box}>
        <option value="">Produkt auswählen …</option>
        {produkte.map((p) => <option key={p.id} value={p.id}>{p.artikelnummer || "Ohne Artikelnummer"} · {p.name}</option>)}
      </select>
      <p className="mt-3" style={{ color: "#6C6F5F" }}>Maximal 30 Q&A pro Produkt, je 1.000 Zeichen für Frage und Antwort und zusammen 10.000 Zeichen. Nur bei Formatfehlern oder überschrittenen Google-Limits ist eine Korrektur nötig.</p>
      {vorschau && <>
        <p className="mt-4 mb-2"><strong>{vorschau.anzahl_qa} exportiert</strong> · {vorschau.faq.filter((faq) => !faq.ausgewaehlt).length} nicht ausgewählt{korrekturen > 0 && <> · {korrekturen} zu korrigieren</>} · {vorschau.zeichen.toLocaleString("de-DE")} / 10.000 Zeichen einschließlich Feed-Formatierung</p>
        {vorschau.faq.length === 0 && <p className="mt-3">Für dieses Produkt sind noch keine FAQs hinterlegt.</p>}
        {vorschau.faq.map((faq) => <article key={faq.faq_id} className="py-4" style={{ borderTop: "1px solid #DDD9C4" }}>
          <div className="flex justify-between gap-3"><strong>{faq.frage || "Leere Frage"}</strong>
            <button aria-label={`FAQ ${faq.faq_id} bearbeiten`} title="FAQ bearbeiten" onClick={() => onBearbeiten(faq.faq_id)} style={{ color: "#2C5A18" }}><Pencil size={14}/></button></div>
          <p className="mt-2" style={{ color: "#6C6F5F", overflowWrap: "anywhere" }}>{faq.antwort || "Leere Antwort"}</p>
          <div className="mt-2"><GoogleFaqAuswahl faqId={faq.faq_id} frage={faq.frage} ausgewaehlt={faq.ausgewaehlt} onGespeichert={auswahlGespeichert}/></div>
          <p className="mt-2" style={{ color: faq.exportiert ? "#2C5A18" : faq.ausgewaehlt ? "#9A6420" : "#6C6F5F", fontWeight: faq.ausgewaehlt ? 600 : 400 }}>{faq.exportiert ? "Im Google-Export" : faq.ausgewaehlt ? `Bitte korrigieren: ${faq.gruende.join(" · ")}` : "Nicht ausgewählt"}</p>
          <small style={{ color: "#6C6F5F" }}>Frage: {faq.zeichen_frage} / 1.000 · Antwort: {faq.zeichen_antwort} / 1.000 Zeichen</small>
        </article>)}
      </>}
      {produktId && !vorschau && !fehler && <p className="mt-4">Vorschau wird geladen …</p>}
    </div>
  </section>;
}
