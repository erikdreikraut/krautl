import { useEffect, useState } from "react";
import { api } from "./api.js";

const texte = {
  ok: "JTL-FAQ: letzter Prüflauf erfolgreich",
  deaktiviert: "JTL-FAQ-Abgleich ist ausgeschaltet",
  unbekannt: "JTL-FAQ: noch kein Prüflauf bestätigt",
  ausgeblieben: "JTL-FAQ: seit mindestens 15 Minuten kein Prüflauf bestätigt",
  gesperrt: "JTL-FAQ-Abgleich gesperrt – Prüfung erforderlich",
  fehler: "JTL-FAQ-Abgleich meldet Fehler",
  offen: "JTL-FAQ: Übertragung noch nicht vollständig",
};

function zeit(wert) {
  return wert ? new Date(wert).toLocaleString("de-DE", {
    timeZone: "Europe/Berlin", day: "2-digit", month: "2-digit",
    hour: "2-digit", minute: "2-digit",
  }) : "noch keiner";
}

export function JtlStatusAnzeige({ daten, abrufFehler }) {
  if (!daten && !abrufFehler) return null;
  const warnung = abrufFehler || !daten.gesund;
  return <details style={{ margin: "8px 20px", padding: "8px 12px", borderRadius: "5px", flexShrink: 0, maxHeight: "30vh", overflowY: "auto",
    fontFamily: "'IBM Plex Sans', sans-serif", fontSize: "13px",
    background: warnung ? "#F1DED7" : "#E8F0C8", color: warnung ? "#A5462F" : "#2C5A18" }}>
    <summary style={{ cursor: "pointer" }}>
      <span role={warnung ? "alert" : "status"}>
        {abrufFehler ? "JTL-FAQ: Status nicht erreichbar – Betrieb nicht bestätigt" : (texte[daten.status] || "JTL-FAQ: Status unbekannt")}
      </span>
      {!abrufFehler && daten.letzter_lauf && <span> · {zeit(daten.letzter_lauf)}</span>}
    </summary>
    {abrufFehler ? <p>Die Statusabfrage ist fehlgeschlagen. Krautl versucht es in 30 Sekunden erneut.</p> : <div style={{ marginTop: "8px" }}>
      <p>{daten.detail}</p>
      <p>Letzter erfolgreicher Prüflauf: {zeit(daten.letzter_erfolg)}</p>
      {daten.offene_artikel != null && <p>Offene Artikel aus dem letzten Prüflauf: {daten.offene_artikel} · Gesperrt: {daten.gesperrte_artikel}</p>}
      {daten.fehler?.length > 0 && <ul style={{ paddingLeft: "20px", listStyle: "disc" }}>{daten.fehler.map((text, i) => <li key={i}>{text}</li>)}</ul>}
      {daten.status === "gesperrt" && <p>Ein Neustart löst die Sperre nicht auf. Den offenen Schreibvorgang prüfen lassen.</p>}
    </div>}
  </details>;
}

export function JtlSyncStatus() {
  const [zustand, setZustand] = useState({ daten: null, abrufFehler: false });
  useEffect(() => {
    let aktiv = true, timer, controller;
    async function laden() {
      controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      try {
        const daten = await api.jtlSyncStatus(controller.signal);
        if (!daten || typeof daten.gesund !== "boolean" || !daten.status) throw new Error("Ungültiger Status");
        if (aktiv) setZustand({ daten, abrufFehler: false });
      } catch {
        if (aktiv) setZustand({ daten: null, abrufFehler: true });
      } finally {
        clearTimeout(timeout);
        if (aktiv) timer = setTimeout(laden, 30000);
      }
    }
    laden();
    return () => { aktiv = false; clearTimeout(timer); controller?.abort(); };
  }, []);
  return <JtlStatusAnzeige {...zustand} />;
}
