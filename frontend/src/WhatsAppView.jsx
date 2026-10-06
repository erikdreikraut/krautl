import { useEffect, useState, useRef, useCallback } from "react";
import { api } from "./api.js";

const button = {border: "1px solid #DDD9C4", borderRadius: 6, padding: "7px 10px", background: "#FDFCEE"};
const labels = {angenommen: "An WhatsApp übergeben", sent: "Gesendet", delivered: "Zugestellt", read: "Gelesen", failed: "Fehlgeschlagen", unklar: "Versand unklar", uebergabe: "Versand wird geprüft", empfangen: "Empfangen"};

export function useWhatsAppEingang(alle, reload) {
  const [daten, setDaten] = useState({chats: [], meine: 0, alle: 0});
  const [fehler, setFehler] = useState("");
  const laden = useCallback(async () => {
    try {
      const [meine, andere] = await Promise.all([api.whatsappChats(false), api.whatsappChats(true)]);
      setDaten({chats: alle ? andere : meine, meine: meine.length, alle: andere.length});
      setFehler("");
    } catch (e) { setFehler(e.message); }
  }, [alle]);
  useEffect(() => { laden(); const timer = setInterval(laden, 5000); return () => clearInterval(timer); }, [laden]);
  return {...daten, fehler, neuLaden: async () => { await Promise.all([laden(), reload()]); }};
}

export function WhatsAppChatPanel({id, benutzer, onReload, onZurueck}) {
  const [chat, setChat] = useState(null);
  const [text, setText] = useState("");
  const [datei, setDatei] = useState(null);
  const [notiz, setNotiz] = useState("");
  const [fehler, setFehler] = useState("");
  const [laeuft, setLaeuft] = useState(false);
  const [vorlagen, setVorlagen] = useState([]);
  const [vorlageIndex, setVorlageIndex] = useState("");
  const [parameter, setParameter] = useState([]);
  const [eigene, setEigene] = useState(false);
  const [basisRevision, setBasisRevision] = useState(null);
  const initialisiert = useRef(false);
  const versandAuftrag = useRef(null);
  const laden = useCallback(async () => {
    const c = await api.whatsappChat(id);
    setChat(c);
    if (!initialisiert.current) {
      setText(c.entwurf || ""); setNotiz(c.notiz || "");
      setBasisRevision(c.entwurf_revision ?? c.revision); initialisiert.current = true;
    }
    return c;
  }, [id]);
  useEffect(() => {
    let aktiv = true;
    const aktualisieren = async () => {
      if (!aktiv) return;
      try {
        await laden();
        if (document.visibilityState === "visible" && document.hasFocus()) {
          await api.whatsappReservieren(id);
          if (aktiv) setEigene(true);
        } else {
          await api.whatsappFreigeben(id);
          if (aktiv) setEigene(false);
        }
      } catch (e) { if (aktiv) {setFehler(e.message); setEigene(false);} }
    };
    aktualisieren(); const timer = setInterval(aktualisieren, 15000);
    return () => {aktiv = false; clearInterval(timer); api.whatsappFreigeben(id).catch(() => {});};
  }, [id, laden]);
  async function aktion(fn) {
    setLaeuft(true); setFehler("");
    try { await fn(); await laden(); await onReload(); }
    catch (e) { setFehler(e.message); }
    finally { setLaeuft(false); }
  }
  if (!chat) return <div className="p-6">{fehler || "Chat wird geladen …"}</div>;
  const gesperrt = !eigene || laeuft;
  const veraltet = basisRevision !== chat.revision && Boolean(text);
  const fensterOffen = chat.antwortfenster_bis && new Date(chat.antwortfenster_bis) > new Date();
  const rest = fensterOffen ? Math.max(1, Math.ceil((new Date(chat.antwortfenster_bis) - new Date()) / 3600000)) : 0;
  const vorlage = vorlageIndex === "" ? null : vorlagen[Number(vorlageIndex)];
  const vorlagenText = vorlage ? parameter.reduce((t, p, i) => t.replaceAll(`{{${i+1}}}`, p), vorlage.text) : "";
  const zustand = {offen: "Offen", wartet_auf_kunde: "Wartet auf Kunde", erledigt: "Erledigt"}[chat.status];
  const senden = async () => {
    if (!versandAuftrag.current) versandAuftrag.current = crypto.randomUUID();
    const form = new FormData();
    if (datei) {form.append("datei", datei); form.append("text", text); form.append("revision", basisRevision); form.append("auftrag_id", versandAuftrag.current);}
    const result = datei ? await api.whatsappDateiSenden(id, form) : await api.whatsappSenden(id, {text: vorlage ? vorlagenText || "Vorlage" : text, revision: basisRevision, auftrag_id: versandAuftrag.current, ...(vorlage ? {template_name: vorlage.name, template_sprache: vorlage.sprache, parameter} : {})});
    if (["angenommen", "sent", "delivered", "read"].includes(result.status)) {
      setText(""); setDatei(null); setVorlageIndex(""); versandAuftrag.current = null;
    } else throw new Error(result.fehler || "Versandstatus prüfen; nicht erneut senden.");
  };
  return <div className="flex flex-col min-h-0 flex-1" style={{color: "#242A1F"}}>
    <div className="p-5" style={{borderBottom: "1px solid #DDD9C4"}}>
      <button style={button} className="mobile-back-button" onClick={onZurueck}>Zurück zum Eingang</button>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><div style={{fontSize: 12, color: "#2C5A18"}}>WHATSAPP · {zustand}</div><h2 className="text-xl font-semibold">{chat.name}</h2><span className="text-sm">+{chat.kontakt_id}</span></div>
        <button disabled={gesperrt} style={button} onClick={() => aktion(() => api.whatsappAendern(id, "erledigen", {revision: chat.revision}))}>✓ Erledigt</button>
      </div>
      <div className="flex flex-wrap gap-2 mt-3">
        <label className="text-sm">Zuständig: <select aria-label="Chat zuweisen" disabled={gesperrt} value={chat.zustaendig_admin ? "admin" : "sachbearbeiter"} onChange={e => aktion(() => api.whatsappAendern(id, "zustaendigkeit", {revision: chat.revision, rolle: e.target.value}))} style={button}><option value="admin">Erik</option><option value="sachbearbeiter">Sachbearbeitung</option></select></label>
      </div>
      <div className="mt-3 text-sm" style={{color: fensterOffen ? "#2C5A18" : "#B07B2E"}}>{fensterOffen ? `Freie API-Antwort noch ungefähr ${rest} Stunden möglich.` : "24-Stunden-Fenster geschlossen. Eine freie API-Antwort ist gesperrt. Eine freigegebene Vorlage nutzen oder eine neue Kundennachricht abwarten."}</div>
      {chat.reserviert_von && chat.reserviert_von !== benutzer.benutzername && <div className="mt-2 text-sm">Wird von {chat.reserviert_von} bearbeitet.</div>}
    </div>
    <div className="p-5 flex flex-col gap-3" aria-label="WhatsApp-Chatverlauf">
      {chat.nachrichten.map(m => <div key={m.id} className="rounded-lg p-3 max-w-full" style={{alignSelf: "flex-start", marginLeft: m.richtung === "eingehend" ? 0 : "min(8%, 120px)", background: m.richtung === "eingehend" ? "#FDFCEE" : "#E8F0C8", width: "min(85%, 650px)", overflowWrap: "anywhere"}}>
        <div className="text-xs mb-1">{m.richtung === "eingehend" ? chat.name : m.quelle === "app" ? "Wir · Handy" : `Wir · ${m.gesendet_von || "Krautl"}`}</div>
        <div style={{whiteSpace: "pre-wrap"}}>{m.text}</div>
        {m.media && <button style={button} className="mt-2" onClick={() => aktion(async () => {
          const blob = await api.whatsappMedium(id, m.id); const url = URL.createObjectURL(blob);
          const a = document.createElement("a"); a.href = url; a.download = m.dateiname || `whatsapp-${m.id}`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 60000);
        })}>{m.dateiname || "Anhang herunterladen"}</button>}
        {m.status === "failed" && <button style={button} disabled={gesperrt} onClick={() => {versandAuftrag.current = null; setText(m.text); setBasisRevision(chat.revision); setDatei(null); setFehler("Antwort erneut prüfen und anschließend manuell senden. Anhänge gegebenenfalls erneut auswählen.");}}>Neue Antwort vorbereiten</button>}
        {["unklar", "uebergabe"].includes(m.status) && <div className="mt-2 text-sm"><p>Versand noch ungeklärt. Auf den Meta-Status warten. Nur mit einem verlässlichen Nachweis (z. B. Bestätigung des Empfängers oder technische Versandprüfung) manuell bestätigen; nicht erneut senden.</p>{[["versendet", "Versand nachgewiesen"], ["nicht_versendet", "Nichtversand nachgewiesen"]].map(([wert,label]) => <button key={wert} style={button} disabled={gesperrt} onClick={() => aktion(async () => {await api.whatsappVersandPruefen(id, m.id, {revision: chat.revision, text: wert}); versandAuftrag.current = null;})}>{label}</button>)}</div>}
        {m.transkript && <div className="mt-2 text-sm whitespace-pre-wrap"><strong>Transkript:</strong> {m.transkript}</div>}
        {m.typ === "audio" && !m.transkript && <button style={button} disabled={gesperrt} onClick={() => aktion(() => api.whatsappTranskribieren(id, m.id))}>Sprachnachricht transkribieren</button>}
        <div className="text-xs mt-2" style={{color: m.fehler ? "#A33E25" : "#6C6F5F"}}>{new Date(m.zeit).toLocaleString("de-DE", {timeZone: "Europe/Berlin"})} · {labels[m.status] || m.status}{m.fehler && ` · ${m.fehler}`}</div>
      </div>)}
    </div>
    <div className="p-5" style={{borderTop: "1px solid #DDD9C4"}}>
      {veraltet && <div className="mb-2 text-sm" style={{color: "#A33E25"}}>Neue Kundennachricht: Antwort prüfen. <button style={button} disabled={gesperrt} onClick={() => {setBasisRevision(chat.revision); versandAuftrag.current = null;}}>Antwort geprüft</button></div>}
      <label className="block text-sm mb-2" htmlFor={`wa-antwort-${id}`}>Antwort an {chat.name}</label>
      <textarea id={`wa-antwort-${id}`} value={text} disabled={gesperrt} rows={4} maxLength={datei ? 1024 : 4096} className="w-full p-3 rounded-md" style={{background: "#FDFCEE", border: "1px solid #DDD9C4"}} onChange={e => {setText(e.target.value);}} />
      {fensterOffen && <label className="block text-sm mt-2">Anhang (PDF bis 10 MB, JPG/PNG bis 5 MB)<input type="file" accept=".pdf,.jpg,.jpeg,.png" disabled={gesperrt} onChange={e => setDatei(e.target.files?.[0] || null)} className="block mt-1 max-w-full" /></label>}
      {!fensterOffen && <div className="my-3 p-3" style={{background: "#F3E7D2"}}>
        <button style={button} disabled={gesperrt} onClick={() => aktion(async () => setVorlagen(await api.whatsappVorlagen()))}>Freigegebene Textvorlagen laden</button>
        {vorlagen.length > 0 && <select aria-label="WhatsApp-Vorlage" style={button} className="block mt-2 w-full" value={vorlageIndex} onChange={e => {setVorlageIndex(e.target.value); setParameter(Array(vorlagen[Number(e.target.value)]?.parameter || 0).fill("")); versandAuftrag.current = null; setBasisRevision(chat.revision);}}><option value="">Vorlage wählen</option>{vorlagen.map((v,i) => <option key={`${v.name}-${v.sprache}`} value={i}>{v.name} · {v.sprache} · {v.kategorie}</option>)}</select>}
        {vorlage && <><div className="my-2 whitespace-pre-wrap text-sm">{vorlagenText}{vorlage.fusszeile && `\n${vorlage.fusszeile}`}</div>{parameter.map((p,i) => <label key={i} className="block text-sm">Platzhalter {i+1}<input aria-label={`Vorlagenparameter ${i+1}`} disabled={gesperrt} value={p} maxLength={1000} className="block p-2 my-1 w-full" onChange={e => setParameter(alt => alt.map((wert, index) => index === i ? e.target.value : wert))} /></label>)}<p className="text-xs">Vorlagen können kostenpflichtig sein. Nur für die vom Kunden gewünschte Kommunikation verwenden.</p></>}
      </div>}
      <div className="flex flex-wrap gap-2 mt-2">
        <button style={button} disabled={gesperrt} onClick={() => aktion(async () => {const result = await api.whatsappVorschlag(id); setText(result.text); setBasisRevision(result.revision); versandAuftrag.current = null;})}>✦ Antwort vorschlagen</button>
        <button style={button} disabled={gesperrt || veraltet} onClick={() => aktion(() => api.whatsappAendern(id, "entwurf", {text, revision: chat.revision}))}>Entwurf speichern</button>
        <button style={{...button, background: "#2C5A18", color: "white"}} disabled={gesperrt || (vorlage ? parameter.some(p => !p.trim()) : veraltet || !fensterOffen || (!text.trim() && !datei))} onClick={() => aktion(senden)}>{laeuft ? "Bitte warten …" : (vorlage ? "Vorlage senden" : "Antwort senden")}</button>
      </div>
      <label className="block text-sm mt-5">Interne Notiz<textarea value={notiz} disabled={gesperrt} onChange={e => setNotiz(e.target.value)} rows={2} className="w-full p-2 mt-1" style={{background: "#FDFCEE", border: "1px solid #DDD9C4"}} /></label>
      <button style={button} disabled={gesperrt} onClick={() => aktion(() => api.whatsappAendern(id, "notiz", {text: notiz, revision: chat.revision}))}>Notiz speichern</button>
      {fehler && <div role="alert" className="mt-3 text-sm" style={{color: "#A33E25"}}>{fehler}</div>}
    </div>
  </div>;
}

export function WhatsAppArchiv({benutzer}) {
  const [chats, setChats] = useState([]); const [suche, setSuche] = useState("");
  const [status, setStatus] = useState(null); const [diagnose, setDiagnose] = useState([]);
  const [id, setId] = useState(null); const [fehler, setFehler] = useState("");
  const laden = useCallback(async () => {try {setChats(await api.whatsappChats(false, true, suche)); setStatus(await api.whatsappStatus()); if(benutzer.rolle === "admin") setDiagnose((await api.whatsappDiagnose()).fehler); setFehler("");} catch(e) {setFehler(e.message);}}, [suche]);
  useEffect(() => {const t = setTimeout(laden, 250); return () => clearTimeout(t);}, [laden]);
  return <div className="flex flex-1 min-h-0 overflow-auto flex-col md:flex-row">
    <div className={`p-4 md:w-80 shrink-0 ${id ? "hidden md:block" : ""}`}><h2 className="text-lg">WhatsApp-Verlauf</h2><p className="text-sm mt-2">{status?.aktiv && status?.eingerichtet ? "Anbindung aktiviert; Live-Nachweis noch separat prüfen." : "Anbindung noch nicht aktiviert oder eingerichtet."}</p>{diagnose.map(e => <div key={e.id} role="alert" className="text-sm mt-2">Eingangsereignis #{e.id}: {e.fehler} <button style={button} onClick={async () => {try {await api.whatsappEreignisWiederholen(e.id); await laden();}catch(err){setFehler(err.message);}}}>Erneut verarbeiten</button></div>)}<input aria-label="Chats durchsuchen" placeholder="Name, Nummer oder Nachricht …" className="w-full p-2 my-3" value={suche} onChange={e => setSuche(e.target.value)} />{fehler && <div role="alert">{fehler}</div>}{chats.map(c => <button key={c.id} className="block w-full text-left p-3" style={{borderBottom: "1px solid #DDD9C4", background: id === c.id ? "#E8F0C8" : "transparent"}} onClick={() => setId(c.id)}><strong>{c.name}</strong><div className="text-sm">{c.vorschau}</div><div className="text-xs">{{offen: "Offen", wartet_auf_kunde: "Wartet auf Kunde", erledigt: "Erledigt"}[c.status] || c.status}</div></button>)}{!chats.length && <p>Keine Chats gefunden.</p>}</div>
    {id && <WhatsAppChatPanel key={id} id={id} benutzer={benutzer} onReload={laden} onZurueck={() => setId(null)} />}
  </div>;
}
