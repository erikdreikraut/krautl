import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api.js";

export function sortieren(rechnungen, feld = "datum", richtung = 1) {
  return [...rechnungen].sort((a, b) => {
    const wert = ["betrag", "offen"].includes(feld)
      ? Number(a[feld]) - Number(b[feld])
      : String(a[feld]).localeCompare(String(b[feld]), "de", { sensitivity: "base", numeric: true });
    return richtung * wert || String(a.id).localeCompare(String(b.id));
  });
}

const zeit = value => value ? new Date(value).toLocaleString("de-DE", { timeZone: "Europe/Berlin" }) : "noch keiner";
const geld = (wert, waehrung) => new Intl.NumberFormat("de-DE", { style: "currency", currency: waehrung }).format(Number(wert));
const zelle = { padding: "13px 16px", borderBottom: "1px solid #DDD9C4" };
const knopf = { padding: "6px 10px", border: "1px solid #DDD9C4", borderRadius: "5px", color: "#2C5A18", cursor: "pointer" };

export function Bestellung({ row }) {
  const dialog = useRef(null);
  if (!row.bestellungen?.length) return <span>Noch nicht abgerufen</span>;
  return <>
    <button type="button" style={{ ...knopf, whiteSpace: "nowrap" }} aria-haspopup="dialog"
      onClick={() => dialog.current.showModal()}>Bestellung ansehen</button>
    <dialog ref={dialog} className="inkasso-bestellung" aria-label={`Bestellung zu Rechnung ${row.nummer}`}
      onClick={event => {
        if (event.target !== event.currentTarget) return;
        const rect = event.currentTarget.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.current.close();
      }}
      style={{ margin: "auto", width: "min(760px, calc(100vw - 32px))", maxHeight: "85vh", overflow: "auto",
        padding: "24px", border: "1px solid #DDD9C4", borderRadius: "10px", background: "#FDFCEE", color: "#242A1F",
        boxShadow: "0 16px 60px #0004", textAlign: "left" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "16px", marginBottom: "16px" }}>
        <h3 style={{ fontWeight: 600 }}>Bestellung zu Rechnung {row.nummer}</h3>
        <button type="button" autoFocus style={knopf} onClick={() => dialog.current.close()}>Schließen</button>
      </div>
      <div style={{ overflowX: "auto" }}>
      {row.bestellungen.map(order => <section key={order.id} style={{ marginBottom: "16px" }}>
        <strong>Auftrag {order.nummer}</strong>
        <p>{order.kanal}{order.datum ? ` · ${String(order.datum).split("T")[0].split("-").reverse().join(".")}` : ""}</p>
        {order.betrag != null && <p>Auftragsbetrag: {geld(order.betrag, order.waehrung || row.waehrung)}</p>}
        <p style={{ margin: "8px 0", color: "#6C6F5F" }}>Abgerechnete Positionen dieser Rechnung:</p>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr><th scope="col">Artikel / SKU</th><th scope="col">Menge</th><th scope="col">Einzelpreis brutto</th></tr></thead>
          <tbody>{order.positionen.map((item, index) => <tr key={index}>
            <td style={{ padding: "6px 8px 6px 0" }}>{item.artikel || "Position"}{item.sku && <small style={{ display: "block" }}>{item.sku}</small>}</td>
            <td style={{ padding: "6px" }}>{item.menge ?? "—"}</td>
            <td style={{ padding: "6px", whiteSpace: "nowrap" }}>{item.einzelpreis == null ? "—" : geld(item.einzelpreis, row.waehrung)}</td>
          </tr>)}</tbody>
        </table>
      </section>)}
      </div>
    </dialog>
    <style>{".inkasso-bestellung::backdrop { background: rgba(0, 0, 0, 0.4); }"}</style>
  </>;
}

export function InkassoListe({ daten }) {
  const [feld, setFeld] = useState("datum");
  const [richtung, setRichtung] = useState(1);
  const [seite, setSeite] = useState(0);
  const rows = useMemo(() => sortieren(daten.rechnungen, feld, richtung), [daten.rechnungen, feld, richtung]);
  const letzte = Math.max(0, Math.ceil(rows.length / 50) - 1);
  const aktuelle = Math.min(seite, letzte);
  const waehlen = key => {
    setRichtung(feld === key ? -richtung : 1);
    setFeld(key);
    setSeite(0);
  };
  const warnung = daten.fehler || daten.veraltet || daten.status === "laeuft";
  return <>
    <div role={warnung ? "alert" : "status"} style={{ margin: "16px 0", padding: "12px 16px", borderRadius: "6px", background: warnung ? "#F3E7D2" : "#E8F0C8" }}>
      {!daten.letzter_erfolg ? <p>Noch kein erfolgreicher Rechnungsabruf. Die Liste ist noch nicht verfügbar.</p>
        : <p>{rows.length} offene Rechnungen · Datenstand: {zeit(daten.letzter_erfolg)}</p>}
      {daten.status === "laeuft" && <p>Rechnungsabruf läuft. Ein vorhandener Datenstand bleibt bis zum Abschluss sichtbar.</p>}
      {daten.fehler && <p>Abruf fehlgeschlagen: {daten.fehler}</p>}
      {daten.veraltet && daten.letzter_erfolg && <p>Der Datenstand ist veraltet. Zahlungsstände vor weiterer Bearbeitung prüfen.</p>}
    </div>
    {daten.letzter_erfolg && <>
      <div style={{ overflowX: "auto", background: "#FDFCEE", border: "1px solid #DDD9C4", borderRadius: "6px" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left" }}>
          <thead><tr>
            {[["datum", "Rechnungsdatum"], ["nummer", "Rechnungs-Nr."], ["kunde", "Kundenname"], ["kanal", "Kanal"], ["betrag", "Betrag"], ["offen", "Offener Betrag"]].map(([key, label]) =>
              <th key={key} scope="col" aria-sort={feld === key ? richtung === 1 ? "ascending" : "descending" : "none"}
                style={{ ...zelle, fontSize: "12px", fontWeight: 500, whiteSpace: "nowrap", textAlign: ["betrag", "offen"].includes(key) ? "right" : "left" }}>
                <button onClick={() => waehlen(key)} style={{ cursor: "pointer", color: "#2C5A18" }}>{label}{feld === key ? richtung === 1 ? " ↑" : " ↓" : " ↕"}</button>
              </th>)}
            <th scope="col" style={zelle}>Telefonnummer(n)</th>
            <th scope="col" style={zelle}>Bestellung</th>
            <th scope="col" style={zelle}>Hinweis</th>
          </tr></thead>
          <tbody>{rows.slice(aktuelle * 50, (aktuelle + 1) * 50).map(row => <tr key={row.id}>
            <td style={{ ...zelle, whiteSpace: "nowrap" }}>{row.datum.split("-").reverse().join(".")}</td>
            <td style={zelle}>{row.nummer}</td>
            <td style={{ ...zelle, fontWeight: 500 }}>{row.kunde}</td>
            <td style={zelle}>{row.kanal || "Noch nicht abgerufen"}</td>
            <td style={{ ...zelle, textAlign: "right", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>{geld(row.betrag, row.waehrung)}</td>
            <td style={{ ...zelle, textAlign: "right", whiteSpace: "nowrap", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{geld(row.offen, row.waehrung)}</td>
            <td style={zelle}>{row.telefone?.length ? row.telefone.map(nummer =>
              <a key={nummer} href={`tel:${nummer.replace(/[^+0-9]/g, "")}`} style={{ display: "block", whiteSpace: "nowrap", color: "#2C5A18" }}>{nummer}</a>)
              : row.telefone ? "Nicht hinterlegt" : "Noch nicht abgerufen"}</td>
            <td style={zelle}><Bestellung row={row} /></td>
            <td style={zelle}>{row.mahnsperre ? "Mahnsperre in Wawi" : "—"}</td>
          </tr>)}</tbody>
        </table>
        {rows.length === 0 && <p style={{ padding: "24px", textAlign: "center" }}>Keine offenen Rechnungen im betrachteten Inkasso-Bestand zum angezeigten Datenstand.</p>}
      </div>
      {rows.length > 50 && <div style={{ display: "flex", gap: "12px", alignItems: "center", marginTop: "12px" }}>
        <button style={knopf} disabled={aktuelle === 0} onClick={() => setSeite(aktuelle - 1)}>Zurück</button>
        <span>Seite {aktuelle + 1} von {letzte + 1}</span>
        <button style={knopf} disabled={aktuelle === letzte} onClick={() => setSeite(aktuelle + 1)}>Weiter</button>
      </div>}
    </>}
  </>;
}

export function InkassoView() {
  const [daten, setDaten] = useState(null);
  const [fehler, setFehler] = useState(null);
  useEffect(() => {
    let aktiv = true, timer, controller;
    async function laden() {
      controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 15000);
      try {
        const result = await api.inkasso(controller.signal);
        if (aktiv) { setDaten(result); setFehler(null); }
      } catch {
        if (aktiv) setFehler("Die Inkasso-Liste ist aktuell nicht erreichbar. Ein eventuell angezeigter Stand ist nicht bestätigt.");
      } finally {
        clearTimeout(timeout);
        if (aktiv) timer = setTimeout(laden, 60000);
      }
    }
    laden();
    return () => { aktiv = false; clearTimeout(timer); controller?.abort(); };
  }, []);
  return <section style={{ padding: "24px 16px", fontFamily: "'IBM Plex Sans', sans-serif", fontSize: "13px", color: "#242A1F" }}>
    <h2 style={{ fontFamily: "'Source Serif 4', serif", fontWeight: 700, fontSize: "20px", color: "#2C5A18" }}>Inkasso</h2>
    {fehler && <p role="alert" style={{ color: "#A5462F", marginTop: "16px" }}>{fehler}</p>}
    {!daten && !fehler && <p role="status" style={{ marginTop: "16px" }}>Rechnungsstand wird geladen …</p>}
    {daten && <InkassoListe daten={daten} />}
  </section>;
}
