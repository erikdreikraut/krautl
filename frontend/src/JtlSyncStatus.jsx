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
  const laden = !daten && !abrufFehler;
  const warnung = abrufFehler || (!laden && !daten.gesund);
  const statusText = laden ? "FAQ-Upload: Status wird geladen" : abrufFehler
    ? "JTL-FAQ: Status nicht erreichbar – Betrieb nicht bestätigt"
    : (texte[daten.status] || "JTL-FAQ: Status unbekannt");
  const farbe = laden ? "#817D6B" : warnung ? "#A5462F" : "#2C5A18";
  return <details style={{ position: "relative", flexShrink: 0,
    fontFamily: "'IBM Plex Sans', sans-serif", fontSize: "12px", color: farbe }}>
    <summary title={statusText + (!abrufFehler && daten?.letzter_lauf ? ` · ${zeit(daten.letzter_lauf)}` : "")}
      aria-label={`FAQ-Upload – ${statusText}`}
      style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: "6px", whiteSpace: "nowrap",
        listStyle: "none", paddingRight: "12px", borderRight: "1px solid #DDD8C3" }}>
      <span aria-hidden="true" style={{ width: "8px", height: "8px", borderRadius: "50%", flexShrink: 0,
        background: laden ? "#817D6B" : warnung ? "#A5462F" : "#539D22" }} />
      <span role={warnung ? "alert" : "status"} aria-label={statusText}>FAQ-Upload</span>
    </summary>
    <div style={{ position: "absolute", right: 0, top: "calc(100% + 12px)", zIndex: 50,
      width: "min(360px, calc(100vw - 32px))", maxHeight: "60vh", overflowY: "auto",
      padding: "12px", borderRadius: "5px", background: "#FFFEF5", border: "1px solid #DDD8C3",
      boxShadow: "0 4px 16px #0002", fontSize: "13px", whiteSpace: "normal", overflowWrap: "anywhere" }}>
      <p style={{ fontWeight: 600 }}>{statusText}</p>
      {laden ? <p>Der aktuelle Status wird abgefragt.</p> : abrufFehler
        ? <p>Die Statusabfrage ist fehlgeschlagen. Krautl versucht es in 30 Sekunden erneut.</p>
        : <div style={{ marginTop: "8px" }}>
          <p>{daten.detail}</p>
          <p>Letzter Prüflauf: {zeit(daten.letzter_lauf)}</p>
          <p>Letzter erfolgreicher Prüflauf: {zeit(daten.letzter_erfolg)}</p>
          {daten.offene_artikel != null && <p>Offene Artikel aus dem letzten Prüflauf: {daten.offene_artikel} · Gesperrt: {daten.gesperrte_artikel}</p>}
          {daten.fehler?.length > 0 && <ul style={{ paddingLeft: "20px", listStyle: "disc" }}>{daten.fehler.map((text, i) => <li key={i}>{text}</li>)}</ul>}
          {daten.status === "gesperrt" && <p>Ein Neustart löst die Sperre nicht auf. Den offenen Schreibvorgang prüfen lassen.</p>}
        </div>}
    </div>
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
