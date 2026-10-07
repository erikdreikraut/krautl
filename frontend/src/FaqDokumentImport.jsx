import { useRef, useState } from "react";
import { Upload } from "lucide-react";
import { api } from "./api.js";

const feld = { border: "1px solid #DDD9C4", borderRadius: 5, padding: "8px", background: "#FDFCEE", width: "100%" };
const knopf = { border: "1px solid #DDD9C4", borderRadius: 5, padding: "8px 12px" };

export function FaqDokumentImport({ produkte, onReload }) {
  const [datei, setDatei] = useState(null);
  const [paare, setPaare] = useState(null);
  const [busy, setBusy] = useState(false);
  const [meldung, setMeldung] = useState("");
  const sperre = useRef(false);
  const aendern = (index, feld, wert) => setPaare((alt) => alt.map((p, i) => i === index ? { ...p, [feld]: wert } : p));
  const analysieren = async () => {
    if (!datei || sperre.current) return;
    if (datei.size > 10 * 1024 * 1024) { setMeldung("Die Datei darf höchstens 10 MB groß sein."); return; }
    sperre.current = true; setBusy(true); setPaare(null); setMeldung("Dokument wird ausgewertet …");
    try {
      const form = new FormData(); form.append("datei", datei);
      const ergebnis = await api.faqDokumentAnalysieren(form);
      setPaare(ergebnis.eintraege.map((p) => ({ ...p, ausgewaehlt: true })));
      setMeldung(ergebnis.eintraege.length ? "Bitte Produktzuordnung und Antworten prüfen." : "Keine Frage-Antwort-Paare erkannt. Enthält das Dokument mehr als 100 Paare, bitte aufteilen.");
    } catch (e) { setMeldung(e.message); }
    finally { sperre.current = false; setBusy(false); }
  };
  const ausgewaehlt = (paare || []).filter((p) => p.ausgewaehlt);
  const gueltig = ausgewaehlt.length > 0 && ausgewaehlt.every((p) => p.produkt_id && p.frage.trim() && p.antwort.trim() && p.kategorie.trim());
  const speichern = async () => {
    if (!gueltig || sperre.current) return;
    sperre.current = true; setBusy(true);
    try {
      const ergebnis = await api.faqDokumentUebernehmen({ dateiname: datei.name.slice(0, 250), eintraege: ausgewaehlt.map(({ ausgewaehlt, hinweis, ...p }) => p) });
      setPaare(null);
      setMeldung(`${ergebnis.angelegt} Entwürfe angelegt, ${ergebnis.uebersprungen} bereits vorhandene Fragen übersprungen. Im FAQ-Editor prüfen und aktivieren.`);
      try { await onReload(); } catch { setMeldung("Entwürfe gespeichert. Die Ansicht konnte nicht aktualisiert werden; bitte neu laden."); }
    } catch (e) { setMeldung(e.message); }
    finally { sperre.current = false; setBusy(false); }
  };
  return <section aria-label="FAQ aus Dokument importieren" className="mb-5 p-4" style={{ border: "1px solid #DDD9C4", borderRadius: 6, fontFamily: "'IBM Plex Sans', sans-serif", fontSize: 13 }}>
    <h4 className="flex items-center gap-2 mb-2" style={{ fontWeight: 600 }}><Upload size={15}/> FAQ aus Dokument</h4>
    <p className="mb-3" style={{ color: "#6C6F5F" }}>Dokument mit Produktangaben und Fragen/Antworten auswählen. Die Artikelnummer hat Vorrang vor ID und Name. Der Inhalt wird zur Auswertung an die KI übermittelt.</p>
    <div className="flex flex-wrap items-center gap-2">
      <input aria-label="FAQ-Dokument auswählen" type="file" accept=".pdf,.docx,.odt,.txt,.md,.csv,.json,.html,.htm" disabled={busy} style={{ maxWidth: "100%" }} onChange={(e) => { setDatei(e.target.files[0] || null); setPaare(null); setMeldung(""); }}/>
      <button type="button" disabled={busy || !datei} style={knopf} onClick={analysieren}>{busy ? "Bitte warten …" : "Mit KI auswerten"}</button>
    </div>
    <p className="mt-2" style={{ color: "#6C6F5F", fontSize: 12 }}>PDF, DOCX, ODT, TXT, Markdown, CSV, JSON oder HTML · maximal 10 MB und 100 Paare. Andere Formate bitte als PDF speichern.</p>
    {meldung && <p role="status" className="mt-3">{meldung}</p>}
    {!!paare?.length && <div className="mt-3">
      <p className="mb-3">Ausgewählte Paare werden als Entwürfe gespeichert. Bestehende Fragen werden übersprungen. Für Exporte bitte später im FAQ-Editor aktivieren.</p>
      {paare.map((p, i) => <fieldset key={i} disabled={busy} className="mb-3 p-3" style={{ border: "1px solid #DDD9C4", minWidth: 0 }}>
        <legend><label><input type="checkbox" checked={p.ausgewaehlt} onChange={(e) => aendern(i, "ausgewaehlt", e.target.checked)}/> Paar {i + 1} übernehmen</label></legend>
        <p className="mb-2">Im Dokument: {p.artikelnummer || "keine Artikelnummer"} · {p.produktname || "kein Produktname"}</p>
        {p.hinweis && <p className="mb-2" style={{ color: "#805619" }}>{p.hinweis}</p>}
        <label className="block mb-2">Produkt<select aria-label={`Produkt für Paar ${i + 1}`} style={feld} value={p.produkt_id || ""} onChange={(e) => aendern(i, "produkt_id", Number(e.target.value) || null)}><option value="">Bitte zuordnen …</option>{produkte.map((produkt) => <option key={produkt.id} value={produkt.id}>{produkt.artikelnummer || "—"} · {produkt.name}</option>)}</select></label>
        <label className="block mb-2">Rubrik<input style={feld} maxLength={100} value={p.kategorie} onChange={(e) => aendern(i, "kategorie", e.target.value)}/></label>
        <label className="block mb-2">Frage<textarea aria-label={`Frage für Paar ${i + 1}`} style={feld} maxLength={5000} rows={2} value={p.frage} onChange={(e) => aendern(i, "frage", e.target.value)}/></label>
        <label className="block">Antwort<textarea aria-label={`Antwort für Paar ${i + 1}`} style={feld} maxLength={20000} rows={5} value={p.antwort} onChange={(e) => aendern(i, "antwort", e.target.value)}/></label>
      </fieldset>)}
      <div className="flex flex-wrap gap-2"><button disabled={busy || !gueltig} style={{ ...knopf, background: "#E8F0C8" }} onClick={speichern}>{ausgewaehlt.length} als Entwurf übernehmen</button><button disabled={busy} style={knopf} onClick={() => { setPaare(null); setMeldung("Vorschau verworfen. Es wurde nichts gespeichert."); }}>Vorschau verwerfen</button></div>
    </div>}
  </section>;
}
