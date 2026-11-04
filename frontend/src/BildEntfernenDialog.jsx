import {useEffect,useRef,useState} from 'react';
import {api} from './api.js';
export function BildEntfernenDialog({artikel,bild,auftraege,gesperrt,schliessen,aktualisiert}) {
 const ref=useRef(null), revision=useRef(artikel.revision), request=useRef(crypto.randomUUID());
 const [id,setId]=useState(bild.id),[sendet,setSendet]=useState(false),[gestartet,setGestartet]=useState(false),[info,setInfo]=useState('');
 const job=auftraege.find(j=>j.id===request.current), selected=artikel.bilder.find(b=>b.id===id);
 const disabled=sendet||gestartet||revision.current!==artikel.revision||gesperrt||!selected||!artikel.entfernen_erlaubt;
 useEffect(()=>{ref.current?.showModal();},[]);
 useEffect(()=>{if(job?.status==='wawi')schliessen();},[job?.status,schliessen]);
 const bestaetigen=async()=>{
  if(disabled)return;
  setSendet(true);setGestartet(true);setInfo('Entfernen wird geprüft …');
  try {
   const r=await api.bilderEntfernen(artikel.id,{bild_id:id,revision:revision.current,anfrage_id:request.current});
   if(r.status==='wawi')schliessen();else setInfo(r.meldung);
  }catch(e){
   if(e.status===401||e.status===403){
    setGestartet(false);
    setInfo(e.status===401?'Bitte erneut anmelden. Der Löschauftrag wurde nicht angenommen.':'Keine Berechtigung zum Entfernen. Der Löschauftrag wurde nicht angenommen.');
   }else setInfo(e.message+' Bitte den Auftragsstatus prüfen; nicht erneut entfernen.');
  }
  finally{setSendet(false);await aktualisiert();}
 };
 return <dialog ref={ref} onCancel={e=>{e.preventDefault();if(!sendet)schliessen();}} aria-labelledby="bild-entfernen-titel" style={{padding:24,maxWidth:500,background:'#FDFCEE',border:'1px solid #DDD9C4',borderRadius:8}}>
  <h3 id="bild-entfernen-titel" style={{fontSize:18,fontWeight:600}}>Bild aus dem JTL-Shop entfernen?</h3>
  <p>{artikel.name} · {artikel.sku}</p>
  <select aria-label="Zu entfernendes Bild" value={id} disabled={gestartet} onChange={e=>setId(e.target.value)}>{artikel.bilder.map((b,i)=><option key={b.id} value={b.id}>Bild {i+1}</option>)}</select>
  {selected?.thumb&&<img src={`/api/bilder/${encodeURIComponent(artikel.id)}/thumb/${selected.thumb}`} alt="Ausgewähltes Bild" style={{display:'block',width:240,height:180,objectFit:'contain',margin:'16px auto'}}/>}
  <p>Dieses Bild wird beim Artikel aus dem JTL-Shop entfernt. Die übrigen Bilder rücken auf. Originaldatei und andere Kanäle bleiben erhalten.</p>
  {revision.current!==artikel.revision&&!gestartet&&<p role="alert">Bildbestand geändert. Bitte schließen und neu auswählen.</p>}
  {(job?.meldung||info)&&<p role="status">{job?.meldung||info}</p>}
  <div style={{display:'flex',gap:20,marginTop:20}}><button type="button" disabled={disabled} onClick={bestaetigen}>Entfernen bestätigen</button><button type="button" disabled={sendet} onClick={schliessen}>{gestartet?'Schließen':'Abbrechen'}</button></div>
 </dialog>;
}
