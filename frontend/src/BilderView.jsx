import { useCallback, useEffect, useRef, useState } from "react";
import { Image, RefreshCw, Search, X, EyeOff } from "lucide-react";
import { BildDialog } from "./BildDialog.jsx";
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

const kategorieVergleich = (a, b) => {
  if (!a) return b ? 1 : 0;
  if (!b) return -1;
  for (let i = 0; i < Math.max(a.sortierung.length, b.sortierung.length); i++) {
    if (a.sortierung[i] === undefined) return -1;
    if (b.sortierung[i] === undefined) return 1;
    if (a.sortierung[i] !== b.sortierung[i]) return a.sortierung[i] - b.sortierung[i];
  }
  return a.name.localeCompare(b.name, "de") || a.id.localeCompare(b.id);
};

export function nachKategorien(gruppen) {
  const abschnitte = new Map();
  for (const gruppe of gruppen) {
    const kandidaten = gruppe.sortierung.kategorien?.length ? gruppe.sortierung.kategorien : gruppe.artikel.flatMap(a => a.kategorien || []);
    const kategorie = [...kandidaten].sort(kategorieVergleich)[0];
    const key = kategorie?.id || "unbekannt";
    if (!abschnitte.has(key)) abschnitte.set(key, {kategorie, gruppen: []});
    abschnitte.get(key).gruppen.push(gruppe);
  }
  return [...abschnitte.values()].sort((a,b) => kategorieVergleich(a.kategorie,b.kategorie));
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

function Thumbnail({ artikel, bild, position, onBild, auftrag, ungeprueft }) {
  const [fehler, setFehler] = useState(false);
  const meldung = bild.fehler || (fehler || !bild.thumb ? "Vorschau nicht verfügbar" : "");
  const status = auftrag ? (auftrag.status === "wawi" ? ["W", "In Wawi bestätigt; Shop-Veröffentlichung ungeprüft", "#286480"] : [auftrag.status === "abgelehnt" ? "!" : "…", auftrag.meldung, "#986c14"]) : ungeprueft || !bild.thumb ? ["?", "Bildstand nicht vollständig geprüft", "#986c14"] : ["✓", "Gespeicherter Wawi-Stand für den Shop; Veröffentlichung nicht live geprüft", "#2C7A25"];
  return <figure className="shrink-0" style={{ width: "120px" }}>
    <button type="button" aria-label={`Bild ${bild.position ?? position+1} von ${artikel.sku} vergrößern`} onClick={()=>onBild?.(artikel,bild)} style={{position:"relative",display:"block"}}>

    {(fehler || !bild.thumb) ? <div role="img" aria-label={`Bildposition ${bild.position ?? position + 1}: ${meldung}`} title={meldung} className="flex items-center justify-center" style={{ ...box, height: "90px", fontSize: "11px", textAlign: "center"  , color: "#9A4332", padding: "6px" }}>Bild nicht verfügbar</div> : <img
      src={`/api/bilder/${encodeURIComponent(artikel.id)}/thumb/${bild.thumb}`} loading="lazy" decoding="async"
      width="120" height="90" alt={`${artikel.name} – Bild ${position + 1}`} onError={() => setFehler(true)}
      style={{ ...box, objectFit: "contain", width: "120px", height: "90px", background: "white" }} />}
    <span title={status[1]} aria-label={status[1]} style={{position:"absolute",right:3,top:3,borderRadius:4,padding:"0 5px",background:status[2],color:"white",fontWeight:700,fontSize:12}}>{status[0]}</span>
    </button>
    <figcaption className="mt-1 truncate" title={bild.dateiname} style={{ fontSize: "10px", color: "#6C6F5F" }}>{bild.position ?? position + 1}{bild.hauptbild ? " · Hauptbild" : ""}</figcaption>
    {bild.quelle === "ameise" && <p style={{ fontSize: "10px", color: "#6C6F5F" }}>Exportvorschau</p>}
    {bild.fehler && <details className="mt-1" style={{ fontSize: "11px", color: "#9A4332", overflowWrap: "anywhere" }}><summary style={{ cursor: "pointer" }}>Fehlerdetails</summary>{bild.fehler}</details>}
  </figure>;
}

const bildStand = a => JSON.stringify([a.revision,a.bilder.map(b=>[b.id,b.position,b.hauptbild])]);

export function BildReihe({a, onBild, auftraege=[], gesperrt=false, ungeprueft=false, aktualisiert=async()=>{}}) {
  const [entwurf,setEntwurf]=useState(null), [sendet,setSendet]=useState(false), [info,setInfo]=useState("");
  const drag=useRef(null), klickSperre=useRef(0), auftrag=useRef(null);
  const blockiert=gesperrt||ungeprueft||a.ausgeblendet||sendet||auftraege.some(j=>j.artikel===a.id&&["sendet","unklar"].includes(j.status));
  const veraltet=entwurf&&entwurf.stand!==bildStand(a);
  const liste=entwurf&&!veraltet ? entwurf.ids.map(id=>a.bilder.find(b=>b.id===id)) : a.bilder;
  const bewegen=(von,nach)=>{
    if(blockiert||veraltet||von===nach)return;
    const ids=liste.map(b=>b.id), start=ids.indexOf(von), ziel=ids.indexOf(nach);
    if(start<0||ziel<0)return;
    ids.splice(ziel,0,ids.splice(start,1)[0]);
    auftrag.current=null;setInfo("");
    setEntwurf({ids,stand:bildStand(a),vorher:a.bilder.map(b=>({id:b.id,position:b.position,hauptbild:b.hauptbild})),revision:a.revision});
  };
  const speichern=async()=>{
    if(blockiert||veraltet||!entwurf)return;
    if(!auftrag.current)auftrag.current=crypto.randomUUID();
    setSendet(true);setInfo("Reihenfolge wird übertragen …");
    try {
      const r=await api.bilderReihenfolge(a.id,{anfrage_id:auftrag.current,revision:entwurf.revision,reihenfolge:entwurf.ids,vorher:entwurf.vorher});
      setInfo(r.meldung);
      if(r.status==="wawi"){setEntwurf(null);auftrag.current=null;}
    } catch(e) {setInfo(e.message);}
    finally {setSendet(false);await aktualisiert();}
  };
  return <div className="min-w-0 flex-1">
    <div className="flex items-start gap-3 overflow-x-auto pb-1">
      {liste.map((original,n)=>{
        const bild=entwurf&&!veraltet ? {...original,position:n+1,hauptbild:n===0} : original;
        const job=[...auftraege].reverse().find(j=>j.artikel===a.id&&(j.neu_id===bild.id||j.bild_id===bild.id||j.reihenfolge?.includes(bild.id)));
        return <div key={bild.id} className="shrink-0" draggable={!blockiert&&!veraltet&&liste.length>1} aria-label={`Bildposition ${n+1} verschieben`}
          onDragStart={e=>{if(blockiert||veraltet){e.preventDefault();return;}drag.current=bild.id;e.dataTransfer.effectAllowed="move";e.dataTransfer.setData("text/plain",bild.id);}}
          onDragOver={e=>{if(drag.current&&!blockiert&&!veraltet){e.preventDefault();e.dataTransfer.dropEffect="move";}}}
          onDrop={e=>{e.preventDefault();bewegen(drag.current,bild.id);drag.current=null;klickSperre.current=Date.now()+300;}}
          onDragEnd={()=>{drag.current=null;klickSperre.current=Date.now()+300;}}
          onClickCapture={e=>{if(Date.now()<klickSperre.current){e.preventDefault();e.stopPropagation();}}}>
          <Thumbnail artikel={a} bild={bild} position={n} onBild={entwurf ? undefined : onBild} ungeprueft={ungeprueft}
            auftrag={entwurf ? {status:"entwurf",meldung:"Reihenfolge noch nicht gespeichert"} : job}/>
          {liste.length>1&&<button type="button" aria-label={`Bild ${n+1} verschieben: Pfeil links oder rechts`} title="Ziehen oder mit den Pfeiltasten verschieben" disabled={blockiert||!!veraltet}
            onKeyDown={e=>{const ziel=e.key==="ArrowLeft"?n-1:e.key==="ArrowRight"?n+1:-1;if(ziel>=0&&ziel<liste.length){e.preventDefault();bewegen(bild.id,liste[ziel].id);}}}
            style={{fontSize:11,color:"#6C6F5F",cursor:"grab"}}>↔</button>}
        </div>;
      })}
      <button type="button" aria-label={`Bild zu ${a.sku} hinzufügen`} title="Bild hinzufügen" onClick={()=>onBild?.(a,null)} disabled={blockiert||!!entwurf} className="shrink-0" style={{...box,width:120,height:90,fontSize:32,color:"#2C5A18"}}>+</button>
      {!a.bilder.length&&<span className="py-7" style={{color:"#6C6F5F"}}>Keine Shop-Bilder zugeordnet</span>}
    </div>
    {entwurf&&<div className="flex flex-wrap items-center gap-3 mt-2">
      <button type="button" style={button} disabled={blockiert||!!veraltet} onClick={speichern}>Reihenfolge speichern</button>
      <button type="button" disabled={sendet} onClick={()=>{setEntwurf(null);auftrag.current=null;setInfo("");}}>Verwerfen</button>
      {veraltet&&<span style={{fontSize:11}}>Bildbestand wurde geändert. Bitte Entwurf verwerfen und neu sortieren.</span>}
    </div>}
    {info&&<p role="status" className="mt-2" style={{fontSize:12}}>{info}</p>}
  </div>;
}

export function BilderListe({ artikel, ausgeblendete, suche, onArtikel, nurBildfehler, ungeprueft = [], onBild, auftraege = [], gesperrt=false, aktualisiert }) {
  const gruppen = gruppieren(artikel, ausgeblendete, suche, nurBildfehler);
  return <div aria-label="Shop-Artikel und Bilder">
    {nachKategorien(gruppen).map(abschnitt => <section key={abschnitt.kategorie?.id || "unbekannt"} className="mb-5">
      <h3 className="mt-4 mb-2" style={{fontSize:"13px", fontWeight:600, color:"#2C5A18"}} hidden={!abschnitt.kategorie}>{abschnitt.kategorie?.name}</h3>
      {abschnitt.gruppen.map(gruppe => <div key={gruppe.id}>

      {gruppe.artikel.map((a, i) => <div key={a.id} className="flex gap-4 py-2" style={{ opacity: a.ausgeblendet ? 0.6 : 1 }}>
        <div className="shrink-0" style={{ width: "clamp(140px, 22vw, 230px)", paddingLeft: a.parent_id ? "12px" : 0, borderLeft: a.parent_id ? "3px solid #BEDC0F" : undefined }}>
          <button type="button" onClick={() => onArtikel(a.id)} className="text-left" style={{ color: "#2C5A18", fontWeight: 600, lineHeight: 1.4, overflowWrap: "anywhere", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }} title={a.name}>{a.name}</button>
          <div className="mt-1" style={{ fontSize: "11px", color: "#6C6F5F" }}>Art.-Nr. {a.sku}{a.parent_id ? " · Variante" : ""}</div>
          {!!a.kategorien?.length && <p className="mt-1" style={{fontSize:"10px", color:"#6C6F5F"}}>{a.kategorien.map(k=>k.name).join(" · ")}</p>}
          {a.kategorie_fehler && <p title={a.kategorie_fehler} style={{fontSize:"10px", color:"#6C6F5F"}}>Kategoriezuordnung nicht verfügbar</p>}
          {ungeprueft.some(u => u.id === a.id) && <p className="mt-1" style={{ color: "#9A4332", fontSize: "11px" }}>Details ungeprüft · bisheriger Bilderstand</p>}
          {a.ausgeblendet && <span className="flex items-center gap-1 mt-1" style={{ fontSize: "11px" }}><EyeOff size={12} /> Ausgeblendet</span>}
        </div>
        <BildReihe a={a} onBild={onBild} auftraege={auftraege} gesperrt={gesperrt} ungeprueft={ungeprueft.some(u=>u.id===a.id)} aktualisiert={aktualisiert}/>

      </div>)}
    </div>)}
    </section>)}
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
  const fehlend = sichtbar.reduce((n,a)=>n+a.bilder.filter(b=>!b.thumb).length,0);
  const ersatz = sichtbar.reduce((n,a)=>n+a.bilder.filter(b=>b.quelle==="ameise"&&b.thumb).length,0);
  return <details className="mb-3" style={{fontSize:12,color:"#6C6F5F"}}>
    <summary role={fehler||abbruch ? "alert" : "status"} style={{cursor:"pointer"}}>
      {titel}{ungeprueft.length ? ` · ${ungeprueft.length} Artikel ungeprüft` : ""}{fehlend ? ` · ${fehlend} Vorschauen fehlen` : ""}
      {laeuft ? ` · ${daten.fortschritt||"Wird geladen …"}` : ""}
    </summary>
    <div className="mt-2" style={{lineHeight:1.6}}>
      {daten?.letzter_erfolg&&<p>Letzter vollständiger Abgleich: {zeit(daten.letzter_erfolg)}</p>}
      {daten?.lauf_beendet_am&&<p>Letzter beendeter Durchlauf: {zeit(daten.lauf_beendet_am)}</p>}
      {daten?.teilstand&&<p>Der letzte Abgleich ist nicht vollständig bestätigt. Das bedeutet nicht, dass sämtliche angezeigten Artikel fehlen oder fehlerhaft sind.</p>}
      {ersatz>0&&<p>{ersatz} Bilder haben eine verfügbare Exportvorschau.</p>}
      {anzahl>0&&<p>{anzahl} Bildabrufe waren gestört; davon fehlen aktuell {fehlend} Vorschauen.</p>}
      {artikelFehler&&<p>Artikel {artikelFehler[1]}: HTTP {artikelFehler[2]}. Die Ursache ist noch ungeklärt.</p>}
      {ungeprueft.length>0&&<ul style={{paddingLeft:20,listStyle:"disc"}}>{ungeprueft.map(a=><li key={a.id}><strong>{a.sku}</strong> · {a.name} · {a.vorhanden?"Bisherige Bilder erhalten":"Bildbestand noch unbekannt"}<p>{a.fehler}</p></li>)}</ul>}
      {abbruch&&<p>{abbruch}</p>}{fehler&&<p>{fehler}</p>}
    </div>
  </details>;
}

export async function importiereVorschaudatei(text, senden, fortschritt = () => {}) {
  const data = JSON.parse(text);
  if (data.format !== "krautl-shopvorschau-2") {
    const result = await senden(text);
    return {importiert: result.importiert, verarbeitet: 1, ausgelassen: []};
  }
  if (data.kanal !== "2-2-1" || !Array.isArray(data.artikel) || !data.artikel.length || data.artikel.length > 2000) {
    throw new Error("Ungültige Sammel-Vorschaudatei.");
  }
  const gesehen = new Set();
  const pakete = data.artikel.map(a => {
    if (a.format !== "krautl-shopvorschau-1" || a.kanal !== "2-2-1" ||
        typeof a.sku !== "string" || !a.sku.trim() || gesehen.has(a.sku) || !Array.isArray(a.bilder)) {
      throw new Error("Ungültige oder doppelte Artikel in der Sammeldatei.");
    }
    gesehen.add(a.sku);
    const body = JSON.stringify(a);
    if (new Blob([body]).size > 1024 * 1024) throw new Error(`Artikel ${a.sku}: Vorschauen größer als 1 MB.`);
    return {sku:a.sku, body};
  });
  const ausgelassen = Array.isArray(data.ausgelassen) ? data.ausgelassen.map(a=>({sku:String(a.sku),grund:String(a.grund)})) : [];
  let importiert = 0, verarbeitet = 0;
  for (let i = 0; i < pakete.length; i++) {
    const paket = pakete[i];
    fortschritt(`Import ${i + 1} von ${pakete.length}: Artikel ${paket.sku}`);
    try {
      const result = await senden(paket.body);
      importiert += result.importiert;
      verarbeitet++;
    } catch (e) {
      if ([400,409].includes(e.status) && !/aktualisierung läuft bereits/i.test(e.message)) {
        ausgelassen.push({sku:paket.sku, grund:e.message});
      } else {
        return {importiert,verarbeitet,ausgelassen,abbruch:`Import bei ${paket.sku} angehalten: ${e.message}. Bereits importierte Vorschauen bleiben erhalten. Die Datei kann erneut importiert werden.`};
      }
    }
  }
  return {importiert,verarbeitet,ausgelassen};
}

export function BilderView() {
  const [daten, setDaten] = useState(null);
  const [bildAuswahl,setBildAuswahl] = useState(null);
  const [auftragFehler,setAuftragFehler] = useState("");
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
  const [importErgebnis, setImportErgebnis] = useState(null);
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
    setImportiert(true); setImportInfo(""); setImportErgebnis(null);
    try {
      if (file.size > 20 * 1024 * 1024) throw new Error("Vorschaudatei darf höchstens 20 MB groß sein.");
      const result = await importiereVorschaudatei(await file.text(), api.bilderExportvorschau, setImportInfo);
      setImportErgebnis(result);
      setImportInfo(`${result.importiert} fehlende Vorschauen ergänzt; ${result.verarbeitet} Artikel geprüft, ${result.ausgelassen.length} ausgelassen. Wawi unverändert.`);
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
      </div>
      <button type="button" onClick={aktualisieren} disabled={startet || laeuft || importiert || !daten} className="flex items-center gap-2" style={{ ...button, opacity: startet || laeuft || !daten ? 0.5 : 1 }}><RefreshCw size={15} className={laeuft ? "animate-spin" : ""} />{laeuft || startet ? "Wird aktualisiert …" : "Aktualisieren"}</button>
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
      {importErgebnis?.abbruch && <p role="alert" className="mt-2">{importErgebnis.abbruch}</p>}
      {!!importErgebnis?.ausgelassen.length && <details className="mt-2"><summary>Ausgelassene Artikel anzeigen</summary><ul>
        {importErgebnis.ausgelassen.map((a,i)=><li key={i}>{a.sku}: {a.grund}</li>)}
      </ul></details>}
    </details>
    {(daten?.bildauftraege||[]).filter(j=>["sendet","unklar"].includes(j.status)).map(j=><div key={j.id} className="mb-2 p-2" style={box}><p>{daten?.artikel.find(a=>a.id===j.artikel)?.sku}: {j.meldung}</p><button onClick={async()=>{setAuftragFehler("");try{await api.bilderAuftragPruefen(j.id);await laden();}catch(e){setAuftragFehler(e.message);}}}>Wawi-Stand prüfen</button></div>)}
    {auftragFehler&&<p role="alert">{auftragFehler}</p>}
    <BilderStatus daten={daten} fehler={fehler} />
    {!daten && !fehler && <p>Lade Bilderübersicht …</p>}
    {daten && !daten.letzter_erfolg && !daten.artikel.length ? <p className="py-12 text-center" style={{ color: "#6C6F5F" }}>Mit „Aktualisieren“ lädst du die Shop-Artikel und ihre Bilder erstmals aus der Wawi.</p> : daten && <BilderListe aktualisiert={laden} onBild={(artikel,bild)=>setBildAuswahl({artikel,bild})} auftraege={daten.bildauftraege||[]} gesperrt={laeuft} ungeprueft={daten.ungeprueft || []} nurBildfehler={nurBildfehler} artikel={daten.artikel} ausgeblendete={ausgeblendete} suche={suche} onArtikel={id => { setDialogFehler(""); setAuswahl(id); }} />}
    {bildAuswahl&&<BildDialog artikel={bildAuswahl.artikel} bild={bildAuswahl.bild} schliessen={()=>setBildAuswahl(null)} aktualisiert={laden} gesperrt={laeuft||bildAuswahl.artikel.ausgeblendet||(daten?.ungeprueft||[]).some(u=>u.id===bildAuswahl.artikel.id)||(daten?.bildauftraege||[]).some(j=>j.artikel===bildAuswahl.artikel.id&&["sendet","unklar"].includes(j.status))}/>}
    {artikel && <ArtikelDialog artikel={artikel} speichern={speichern} schliessen={() => setAuswahl(null)} laeuft={speichert} fehler={dialogFehler} />}
  </section>;
}
