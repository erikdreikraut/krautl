import { useEffect, useState } from "react";
import { api } from "./api.js";

export function FaqAuswahl({ faqId, frage, ausgewaehlt, onGespeichert }) {
  const [wert, setWert] = useState(!!ausgewaehlt);
  const [speichert, setSpeichert] = useState(false);
  const [fehler, setFehler] = useState("");
  useEffect(() => setWert(!!ausgewaehlt), [faqId, ausgewaehlt]);

  const aendern = async (neu) => {
    setSpeichert(true);
    setFehler("");
    let eintrag;
    try {
      eintrag = await api.faqAuswahl(faqId, neu);
      setWert(eintrag.aktiv && eintrag.status === "freigegeben");
    } catch (e) {
      setFehler(`FAQ-Auswahl konnte nicht gespeichert werden: ${e.message}`);
      setSpeichert(false);
      return;
    }
    try { await onGespeichert(eintrag); }
    catch { setFehler("Auswahl gespeichert. Bitte die Ansicht neu laden."); }
    finally { setSpeichert(false); }
  };

  return <div style={{ fontFamily: "'IBM Plex Sans', sans-serif", fontSize: "12px" }}>
    <label className="inline-flex items-center gap-2 px-2.5 py-1.5" title="Für das FAQ aufnehmen · wird sofort gespeichert"
      style={{ border: `1px solid ${wert ? "#4F9B2E" : "#DDD9C4"}`, borderRadius: "5px", background: wert ? "#E8F0C8" : "#FDFCEE", color: wert ? "#2C5A18" : "#6C6F5F", fontWeight: wert ? 600 : 400, cursor: speichert ? "wait" : "pointer" }}>
      <input type="checkbox" checked={wert} disabled={speichert} onChange={(e) => aendern(e.target.checked)}
        aria-label={`In FAQ aufnehmen: ${frage}`} style={{ accentColor: "#4F9B2E" }}/>
      <span>{speichert ? "Wird gespeichert …" : "In FAQ aufnehmen"}</span>
    </label>
    {fehler && <p role="alert" className="mt-1" style={{ color: "#9A4024" }}>{fehler}</p>}
  </div>;
}
