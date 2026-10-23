import { useCallback, useEffect, useRef, useState } from "react";
import { Image, RefreshCw, Search, X, EyeOff } from "lucide-react";
import { api } from "./api.js";

const ui = { fontFamily: "'IBM Plex Sans', sans-serif", fontSize: "13px" };
const box = { border: "1px solid #DDD9C4", borderRadius: "6px", background: "#FDFCEE" };
const button = { ...ui, ...box, color: "#2C5A18", padding: "8px 12px" };
const zeit = wert => wert ? new Date(wert).toLocaleString("de-DE", { timeZone: "Europe/Berlin" }) : "Noch kein erfolgreicher Abruf";

export function gruppieren(artikel, ausgeblendete = false, suche = "", nurBildfehler = false) {
  const begriffe = suche.toLocaleLowerCase("de").trim().split(/\s+/).filter(Boolean);
  const ids = new Map(artikel.map(a => [a.id, a]));
  const gruppen = new Map();
  for (const a of artikel) {
    if (!ausgeblendete && a.ausgeblendet) continue;
    if (nurBildfehler && !a.bilder.some(b => b.fehler)) continue;
    if (!begriffe.every(b => `${a.name} ${a.sku}`.toLocaleLowerCase("de").includes(b))) continue;
    const key = a.parent_id || a.id;
    if (!gruppen.has(key)) gruppen.set(key, []);
    gruppen.get(key).push(a);
  }
  const vergleichen = (a, b) => a.name.localeCompare(b.name, "de", { numeric: true }) || a.sku.localeCompare(b.sku, "de", { numeric: true });
  return [...gruppen.entries()].map(([id, rows]) => ({
    id,
    artikel: rows.sort((a, b) => Number(Boolean(a.parent_id)) - Number(Boolean(b.parent_id)) || vergleichen(a, b)),
    sortierung: ids.get(id) || rows[0],
  })).sort((a, b) => vergleichen(a.sortierung, b.sortierung));
}

function ArtikelDialog({ artikel, speichern, schliessen, laeuft, fehler }) {
  const ref = useRef(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return <dialog ref={ref} onCancel={e => { e.preventDefault(); if (!laeuft) schliessen(); }} style={{ ...ui, ...box, color: "#242A1F", width: "min(440px, 92vw)", padding: "24px" }} aria-labelledby="bilder-artikel-titel">
    <div className="flex justify-between items-start gap-4">
      <div><h3 id="bilder-artikel-titel" style={{ fontSize: "18px", fontWeight: 600 }}>{artikel.name}</h3><p className="mt-1" style={{ color: "#6C6F5F" }}>Art.-Nr. {artikel.sku}</p></div>
      <button type="button" disabled={laeuft} onClick={schliessen} aria-label="Schließen"><X size={18} /></button>
    </div>
    <label className="flex items-center gap-3 mt-6"><input autoFocus type="checkbox" checked={artikel.ausgeblendet} disabled={laeuft} onChange={e => speichern(e.target.checked)} /> Ausblenden</label>
    <p className="mt-3" style={{ color: "#6C6F5F", lineHeight: 1.5 }}>Ausgeblendete Artikel werden in dieser Bilderverwaltung bei Aktualisierungen übersprungen. Im Shop bleibt der Artikel unverändert. Über „Ausgeblendete anzeigen“ kannst du ihn wieder einblenden.</p>
    {laeuft && <p role="status" className="mt-3">Wird gespeichert …</p>}
    {fehler && <p role="alert" className="mt-3" style={{ color: "#9A4332" }}>{fehler}</p>}
  </dialog>;
}

function Thumbnail({ artikel, bild, position }) {
  const [fehler, setFehler] = useState(false);
  const meldung = bild.fehler || (fehler || !bild.thumb ? "Vorschau nicht verfügbar" : "");
  return <figure className="shrink-0" style={{ width: "120px" }}>
    {(fehler || !bild.thumb) ? <div role="img" aria-label={`Bildposition ${bild.position ?? position + 1}: ${meldung}`} title={meldung} className="flex items-center justify-center" style={{ ...box, height: "90px", fontSize: "11px", textAlign: "center"  , color: "#9A4332", padding: "6px" }}>Bild nicht verfügbar</div> : <img
      src={`/api/bilder/${encodeURIComponent(artikel.id)}/thumb/${bild.thumb}`} loading="lazy" decoding="async"
      width="120" height="90" alt={`${artikel.name} – Bild ${position + 1}`} onError={() => setFehler(true)}
      style={{ ...box, objectFit: "contain", width: "120px", height: "90px", background: "white" }} />}
    <figcaption className="mt-1 truncate" title={bild.dateiname} style={{ fontSize: "10px", color: "#6C6F5F" }}>{bild.position ?? position + 1}{bild.hauptbild ? " · Hauptbild" : ""}</figcaption>
    {bild.quelle === "ameise" && <p style={{ fontSize: "10px", color: "#6C6F5F" }}>Exportvorschau</p>}
    {bild.fehler && <details className="mt-1" style={{ fontSize: "11px", color: "#9A4332", overflowWrap: "anywhere" }}><summary style={{ cursor: "pointer" }}>Fehlerdetails</summary>{bild.fehler}</details>}
  </figure>;
}

export function BilderListe({ artikel, ausgeblendete, suche, onArtikel, nurBildfehler, ungeprueft = [] }) {
  const gruppen = gruppieren(artikel, ausgeblendete, suche, nurBildfehler);
  return <div className="flex flex-col gap-3" aria-label="Shop-Artikel und Bilder">
    {gruppen.map(gruppe => <div key={gruppe.id} style={{ ...box, overflow: "hidden" }}>
      {gruppe.artikel.map((a, i) => <div key={a.id} className="flex gap-4 px-4 py-3" style={{ borderTop: i ? "1px solid #DDD9C4" : undefined, opacity: a.ausgeblendet ? 0.6 : 1, background: a.parent_id ? "#FAF9E6" : undefined }}>
        <div className="shrink-0" style={{ width: "clamp(140px, 22vw, 230px)", paddingLeft: a.parent_id ? "12px" : 0, borderLeft: a.parent_id ? "3px solid #BEDC0F" : undefined }}>
          <button type="button" onClick={() => onArtikel(a.id)} className="text-left" style={{ color: "#2C5A18", fontWeight: 600, lineHeight: 1.4, overflowWrap: "anywhere", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }} title={a.name}>{a.name}</button>
          <div className="mt-1" style={{ fontSize: "11px", color: "#6C6F5F" }}>Art.-Nr. {a.sku}{a.parent_id ? " · Variante" : ""}</div>
          {ungeprueft.some(u => u.id === a.id) && <p className="mt-1" style={{ color: "#9A4332", fontSize: "11px" }}>Details ungeprüft · bisheriger Bilderstand</p>}
          {a.ausgeblendet && <span className="flex items-center gap-1 mt-1" style={{ fontSize: "11px" }}><EyeOff size={12} /> Ausgeblendet</span>}
        </div>
        <div className="flex items-start gap-3 overflow-x-auto min-w-0 flex-1 pb-1">
          {a.bilder.map((bild, n) => <Thumbnail key={`${bild.id}-${bild.thumb}`} artikel={a} bild={bild} position={n} />)}
          {!a.bilder.length && <span className="py-7" style={{ color: "#6C6F5F" }}>Keine Shop-Bilder zugeordnet</span>}
        </div>
      </div>)}
    </div>)}
    {!gruppen.length && <p className="py-12 text-center" style={{ color: "#6C6F5F" }}>Keine Artikel für diese Auswahl.</p>}
  </div>;
}

export function BilderStatus({ daten, fehler }) {
  if (!daten && !fehler) return null;
  const laeuft = daten?.status === "laeuft";
  const abbruch = daten?.fehler;
  const sichtbar = (daten?.artikel || []).filter(a => !a.ausgeblendet);
  const anzahl = sichtbar.reduce((n, a) => n + a.bilder.filter(b => b.fehler).length, 0);
  const ungeprueft = (daten?.ungeprueft || []).filter(u => !daten?.artikel?.some(a => a.id === u.id && a.ausgeblendet));
  const artikelFehler = abbruch?.match(/^Artikel (.+?) \(Details\):.*HTTP (\d+)/);
  const titel = fehler ? "Verbindung zur Übersicht gestört" : laeuft ? "Abgleich läuft" :
    abbruch ? "Abgleich abgebrochen" : ungeprueft.length && daten?.lauf_beendet_am ? "Durchlauf beendet – Artikel ungeprüft" : daten?.teilstand ? "Abgleich noch unvollständig" :
    daten?.letzter_erfolg ? "Abgleich abgeschlossen" : "Noch kein Abgleich gestartet";
  return <div role={fehler || abbruch ? "alert" : "status"} className="mb-4 p-3" style={{ ...box, color: "#242A1F" }}>
    <strong>{titel}</strong>
    {artikelFehler ? <p className="mt-1">Die Wawi kann die Details von Artikel {artikelFehler[1]} nicht liefern (HTTP {artikelFehler[2]}). Die Ursache ist noch ungeklärt.</p> :
      abbruch ? <p className="mt-1">Der Abruf wurde durch einen Fehler unterbrochen. Einzelheiten stehen unter „Technische Details“.</p> : null}
    {fehler && <p className="mt-1">Die Anzeige konnte nicht aktualisiert werden. Der angezeigte Stand kann veraltet sein.</p>}
    <p className="mt-1">{sichtbar.length} Artikel im gespeicherten Bestand.{daten?.teilstand ? " Die Liste ist noch nicht vollständig geprüft; Artikel können fehlen oder veraltet sein." : ""}</p>
    {anzahl > 0 && <p className="mt-1">{anzahl} Bilder sind über die API nicht abrufbar. Sie erscheinen als Platzhalter oder, falls importiert, als Exportvorschau. „Nur Artikel mit Bildfehlern“ zeigt die betroffenen Artikel.</p>}
    {ungeprueft.length > 0 && <details className="mt-2" open>
      <summary style={{ cursor: "pointer" }}>{ungeprueft.length} Artikel ungeprüft</summary>
      <p className="mt-1">Die Wawi lieferte nach drei Versuchen keine Artikeldetails. Der Abgleich wird mit den übrigen Artikeln fortgesetzt. Beim nächsten Aktualisieren werden diese Artikel erneut geprüft.</p>
      <ul className="mt-2" style={{ paddingLeft: "20px", listStyle: "disc" }}>{ungeprueft.map(a => <li key={a.id}>
        <strong>{a.sku}</strong> · {a.name} · {a.vorhanden ? "Bisherige Bilder erhalten" : "Bildbestand noch unbekannt"}
        <details><summary style={{ cursor: "pointer" }}>Fehlerdetails</summary>{a.fehler}</details>
      </li>)}</ul>
    </details>}
    {laeuft && <p className="mt-2" style={{ color: "#2C5A18" }}>{daten.fortschritt || "Artikel werden geladen …"}</p>}
    {(abbruch || fehler) && <details className="mt-2"><summary style={{ cursor: "pointer" }}>Technische Details</summary>
      {abbruch && <p>{abbruch}</p>}{fehler && <p>{fehler}</p>}
    </details>}
  </div>;
}

export function BilderView() {
  const [daten, setDaten] = useState(null);
  const [fehler, setFehler] = useState("");
  const [suche, setSuche] = useState("");
  const [ausgeblendete, setAusgeblendete] = useState(false);
  const [nurBildfehler, setNurBildfehler] = useState(false);
  const [auswahl, setAuswahl] = useState(null);
  const [speichert, setSpeichert] = useState(false);
  const [dialogFehler, setDialogFehler] = useState("");
  const [startet, setStartet] = useState(false);
  const [importInfo, setImportInfo] = useState("");
  const [importiert, setImportiert] = useState(false);
  const abruf = useRef(0);
  const aktiv = useRef(false);
  const laden = useCallback(async () => {
    const nr = ++abruf.current;
    try {
      const d = await api.bilder();
      if (aktiv.current && nr === abruf.current) { setDaten(d); setFehler(""); }
    } catch (e) { if (aktiv.current && nr === abruf.current) setFehler(e.message); }
  }, []);
  useEffect(() => {
    aktiv.current = true;
    laden();
    const timer = setInterval(laden, 5000);
    return () => { aktiv.current = false; ++abruf.current; clearInterval(timer); };
  }, [laden]);
  const aktualisieren = async () => {
    setStartet(true); setFehler("");
    try { await api.bilderAktualisieren(); await laden(); }
    catch (e) { setFehler(e.message); }
    finally { setStartet(false); }
  };
  const exportImport = async event => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setImportiert(true); setImportInfo("");
    try {
      if (file.size > 1024 * 1024) throw new Error("Vorschaudatei darf höchstens 1 MB groß sein.");
      const result = await api.bilderExportvorschau(await file.text());
      setImportInfo(`Artikel ${result.sku}: ${result.importiert} fehlende Vorschauen ergänzt. Wawi unverändert.`);
      await laden();
    } catch (e) { setImportInfo(e.message); }
    finally { setImportiert(false); }
  };
  const artikel = daten?.artikel.find(a => a.id === auswahl);
  const speichern = async hidden => {
    setSpeichert(true); setDialogFehler("");
    try { await api.bilderAusblenden(artikel.id, hidden, artikel.revision); await laden(); setAuswahl(null); }
    catch (e) { setDialogFehler(e.message); if (e.status === 409) await laden(); }
    finally { setSpeichert(false); }
  };
  const laeuft = daten?.status === "laeuft";
  const sichtbar = daten?.artikel.filter(a => !a.ausgeblendet).length || 0;
  return <section className="flex-1 min-h-0 overflow-y-auto px-6 py-5" style={{ ...ui, color: "#242A1F" }}>
    <div className="flex flex-wrap justify-between items-start gap-3 mb-4">
      <div><h2 className="flex items-center gap-2" style={{ fontFamily: "'Source Serif 4', serif", fontSize: "21px", fontWeight: 700, color: "#2C5A18" }}><Image size={22} /> Bilder</h2>
        <p className="mt-1" style={{ color: "#6C6F5F" }}>Shop-Bilder · {sichtbar} Artikel · {(daten?.artikel.length || 0) - sichtbar} ausgeblendet</p>
        <p className="mt-1" style={{ fontSize: "11px", color: "#6C6F5F" }}>{daten?.letzter_erfolg ? `Letzter vollständiger Abgleich: ${zeit(daten.letzter_erfolg)}` : "Ein vollständiger Abgleich steht noch aus."}</p>
      </div>
      <button type="button" onClick={aktualisieren} disabled={startet || laeuft || !daten} className="flex items-center gap-2" style={{ ...button, opacity: startet || laeuft || !daten ? 0.5 : 1 }}><RefreshCw size={15} className={laeuft ? "animate-spin" : ""} />{laeuft || startet ? "Wird aktualisiert …" : "Aktualisieren"}</button>
    </div>
    <div className="flex flex-wrap gap-5 items-center mb-5">
      <label className="flex items-center gap-2 px-3 py-2" style={box}><Search size={15} /><input type="search" aria-label="Artikelname oder Artikelnummer suchen" placeholder="Name oder Artikelnummer …" value={suche} onChange={e => setSuche(e.target.value)} style={{ background: "transparent", outline: "none" }} /></label>
      <label className="flex items-center gap-2"><input type="checkbox" checked={ausgeblendete} onChange={e => setAusgeblendete(e.target.checked)} /> Ausgeblendete anzeigen</label>
      <label className="flex items-center gap-2"><input type="checkbox" checked={nurBildfehler} onChange={e => setNurBildfehler(e.target.checked)} /> Nur Artikel mit Bildfehlern</label>
    </div>
    <details className="mb-4" style={{ fontSize: "12px" }}>
      <summary style={{ cursor: "pointer" }}>Ersatzvorschauen aus Shop-Export</summary>
      <p className="my-2">Vorbereitete Krautl-Vorschaudatei auswählen. Ergänzt nur fehlende Vorschauen; Wawi bleibt unverändert.</p>
      <input aria-label="Shop-Vorschaudatei importieren" type="file" accept=".json" disabled={laeuft || importiert} onChange={exportImport} />
      {importInfo && <p role="status" className="mt-2">{importInfo}</p>}
    </details>
    <BilderStatus daten={daten} fehler={fehler} />
    {!daten && !fehler && <p>Lade Bilderübersicht …</p>}
    {daten && !daten.letzter_erfolg && !daten.artikel.length ? <p className="py-12 text-center" style={{ color: "#6C6F5F" }}>Mit „Aktualisieren“ lädst du die Shop-Artikel und ihre Bilder erstmals aus der Wawi.</p> : daten && <BilderListe ungeprueft={daten.ungeprueft || []} nurBildfehler={nurBildfehler} artikel={daten.artikel} ausgeblendete={ausgeblendete} suche={suche} onArtikel={id => { setDialogFehler(""); setAuswahl(id); }} />}
    {artikel && <ArtikelDialog artikel={artikel} speichern={speichern} schliessen={() => setAuswahl(null)} laeuft={speichert} fehler={dialogFehler} />}
  </section>;
}
