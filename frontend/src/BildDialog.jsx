import {useEffect,useRef,useState} from "react";
import {X} from "lucide-react";
import {api} from "./api.js";

export function BildDialog({artikel,bild,schliessen,aktualisiert,gesperrt=false}) {
  const ref=useRef(null);
  const [gross,setGross]=useState(null), [hinweis,setHinweis]=useState("");
  const [file,setFile]=useState(null), [vorschau,setVorschau]=useState(null);
  const [sendet,setSendet]=useState(false), [ergebnis,setErgebnis]=useState(null), [fehler,setFehler]=useState("");
  const auftrag=useRef(null);
  const fallback=bild?.thumb ? `/api/bilder/${encodeURIComponent(artikel.id)}/thumb/${bild.thumb}` : null;
  useEffect(()=>{ref.current?.showModal();},[]);
  useEffect(()=>{
    if (!bild) return;
    let aktiv=true, url;
    setHinweis("Großansicht wird geladen …");
    api.bilderGross(artikel.id,bild.id).then(blob=>{
      if (aktiv) {url=URL.createObjectURL(blob);setGross(url);setHinweis("");}
    }).catch(()=>{if(aktiv)setHinweis("Großansicht nicht abrufbar. Angezeigt wird die gespeicherte kleine Vorschau.");});
    return ()=>{aktiv=false;if(url)URL.revokeObjectURL(url);};
  },[artikel.id,bild?.id]);
  useEffect(()=>{
    if(!file){setVorschau(null);return;}
    const url=URL.createObjectURL(file);setVorschau(url);
    return ()=>URL.revokeObjectURL(url);
  },[file]);
  const waehlen=e=>{
    const f=e.target.files?.[0];e.target.value="";
    if(!f)return;
    setFehler("");
    if(f.size>20*1024*1024 || !/\.(jpe?g|png|webp)$/i.test(f.name)) {setFehler("Bitte JPG, PNG oder WebP bis 20 MB auswählen.");return;}
    setFile(f);auftrag.current=crypto.randomUUID();
  };
  const bestaetigen=async()=>{
    if(sendet||!file||ergebnis||gesperrt)return;
    setSendet(true);setFehler("");
    try {
      const result=await api.bilderDatei(artikel.id,bild?.id,artikel.revision,auftrag.current,file);
      setErgebnis(result);
    } catch(e) {
      setFehler(e.message);
      // Keep request ID and file: an explicit retry can only retrieve this same intent.
    } finally {setSendet(false);await aktualisiert();}
  };
  const pruefen=async()=>{
    setSendet(true);setFehler("");
    try {setErgebnis(await api.bilderAuftragPruefen(ergebnis.id));}
    catch(e){setFehler(e.message);}
    finally{setSendet(false);await aktualisiert();}
  };
  return <dialog ref={ref} onCancel={e=>{e.preventDefault();if(!sendet)schliessen();}} aria-labelledby="bild-dialog-titel" style={{width:"min(1000px,94vw)",maxHeight:"92vh",overflowY:"auto",padding:24,border:"1px solid #DDD9C4",borderRadius:8,background:"#FDFCEE",color:"#242A1F"}}>
    <div className="flex justify-between gap-4"><div><h3 id="bild-dialog-titel" style={{fontSize:18,fontWeight:600}}>{bild ? "Bild ansehen und austauschen" : "Bild hinzufügen"}</h3><p>{artikel.name} · {artikel.sku}{bild ? ` · Position ${bild.position}` : ""}</p></div><button disabled={sendet} onClick={schliessen} aria-label="Bilddialog schließen"><X/></button></div>
    <div className="flex flex-wrap gap-4 my-4">
      {bild && <figure className="flex-1" style={{minWidth:240}}><figcaption>Aktuelles Bild</figcaption>{(gross||fallback) ? <img src={gross||fallback} alt="Aktuelles Artikelbild" style={{maxHeight:"55vh",maxWidth:"100%",objectFit:"contain",margin:"auto"}}/> : <p>Keine Vorschau verfügbar.</p>}{hinweis&&<p className="mt-2 text-sm">{hinweis}</p>}</figure>}
      {vorschau&&<figure className="flex-1" style={{minWidth:240}}><figcaption>Neue Datei: {file.name}</figcaption><img src={vorschau} alt="Neue Bilddatei zur Bestätigung" style={{maxHeight:"55vh",maxWidth:"100%",objectFit:"contain",margin:"auto"}}/></figure>}
    </div>
    {!ergebnis&&<><label className="block my-3">{bild ? "Ersatzbild auswählen" : "Neues Bild auswählen"}<input className="block mt-2" aria-label="Neue Bilddatei" type="file" accept=".jpg,.jpeg,.png,.webp" onChange={waehlen} disabled={sendet||gesperrt}/></label>
      <p className="text-sm mb-3">{bild ? "Ersetzt dieses Bild in allen bisherigen Kanälen. Kanalzuordnungen, Positionen und Hauptbild bleiben erhalten." : "Fügt das Bild am Ende der JTL-Shop-Bilder hinzu."}{!bild && " Andere Verkaufskanäle behalten ihre Bilder."}</p>
      {gesperrt&&<p>Änderungen sind während eines Abgleichs oder bei einem ungeklärten Bildauftrag gesperrt.</p>}
      <button onClick={bestaetigen} disabled={!file||sendet||gesperrt} style={{padding:"8px 12px",border:"1px solid #2C5A18",borderRadius:4,opacity:!file||sendet||gesperrt?0.5:1}}>{sendet ? "Übertragung läuft …" : "Bestätigen und an Wawi übertragen"}</button></>}
    {ergebnis&&<p role="status" className="mt-3">{ergebnis.meldung}</p>}
    {ergebnis&&["sendet","unklar"].includes(ergebnis.status)&&<button className="mt-3" onClick={pruefen} disabled={sendet}>Wawi-Stand prüfen (ohne erneuten Upload)</button>}
    {fehler&&<p role="alert" className="mt-3" style={{color:"#9A4332"}}>{fehler}</p>}
  </dialog>;
}
