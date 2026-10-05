import { useEffect, useState } from "react";
import { RefreshCw, Search } from "lucide-react";
import { api } from "./api.js";

const rahmen = { background: "#FDFCEE", border: "1px solid #DDD9C4", borderRadius: "6px" };
const knopf = { ...rahmen, padding: "7px 10px", color: "#2C5A18", fontSize: "12px" };
const zeit = (wert) => wert ? new Date(wert).toLocaleString("de-DE", { timeZone: "Europe/Berlin" }) : "Zeitpunkt nicht gespeichert";
const ablageText = {
  gespeichert: "Kopie im Mailordner Gesendet",
  ausstehend: "Kopie im Mailordner wird abgelegt",
  fehler: "Kopie im Mailordner fehlt",
  historisch: "Ältere Antwort aus KRAUTL",
};

export function GesendeteAntwortenView() {
  const [suche, setSuche] = useState("");
  const [seite, setSeite] = useState(1);
  const [version, setVersion] = useState(0);
  const [liste, setListe] = useState(null);
  const [auswahlId, setAuswahlId] = useState(null);
  const [antwort, setAntwort] = useState(null);
  const [listenFehler, setListenFehler] = useState("");
  const [detailFehler, setDetailFehler] = useState("");
  const [laedt, setLaedt] = useState(true);
  const [kopiert, setKopiert] = useState(false);

  useEffect(() => {
    const timer = setInterval(() => setVersion(v => v + 1), 30000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    let aktiv = true;
    setLaedt(true);
    const timer = setTimeout(async () => {
      try {
        const daten = await api.gesendeteAntworten({ suche, seite });
        if (aktiv) {
          setListe(daten); setListenFehler("");
          setAuswahlId(id => daten.eintraege.some(e => e.id === id) ? id : daten.eintraege[0]?.id || null);
        }
      } catch (e) { if (aktiv) setListenFehler(e.message); }
      finally { if (aktiv) setLaedt(false); }
    }, 250);
    return () => { aktiv = false; clearTimeout(timer); };
  }, [suche, seite, version]);
  useEffect(() => { setAntwort(null); setDetailFehler(""); }, [auswahlId]);
  useEffect(() => {
    if (!auswahlId) return;
    let aktiv = true;
    api.gesendeteAntwort(auswahlId).then(daten => {
      if (aktiv) { setAntwort(daten); setDetailFehler(""); }
    }).catch(e => { if (aktiv) setDetailFehler(e.message); });
    return () => { aktiv = false; };
  }, [auswahlId, version]);

  const kopieAblegen = async () => {
    setKopiert(true); setDetailFehler("");
    const id = auswahlId;
    try {
      const daten = await api.gesendeteAntwortAblegen(id);
      setAntwort(aktuell => aktuell?.id === id ? { ...aktuell, ...daten } : aktuell);
      setVersion(v => v + 1);
    } catch (e) { setDetailFehler(e.message); }
    finally { setKopiert(false); }
  };

  return <section className="flex-1 overflow-y-auto p-4 md:p-6" style={{ fontFamily: "'IBM Plex Sans', sans-serif", fontSize: "13px" }}>
    <div className="flex flex-wrap justify-between items-start gap-3 mb-4">
      <div><h2 style={{ fontFamily: "'Source Serif 4', serif", fontSize: "21px", color: "#2C5A18", fontWeight: 700 }}>Gesendete Antworten</h2>
        <p className="mt-1" style={{ color: "#6C6F5F" }}>Neueste zuerst · auch Antworten auf bereits erledigte Anfragen.</p></div>
      <button style={knopf} onClick={() => setVersion(v => v + 1)} className="flex items-center gap-2"><RefreshCw size={14}/> Aktualisieren</button>
    </div>
    <label className="flex items-center gap-2 p-2 mb-4" style={rahmen}>
      <Search size={15} aria-hidden="true"/>
      <input type="search" aria-label="Gesendete Antworten durchsuchen" placeholder="Name, Empfänger, Betreff oder Antwort durchsuchen …"
        value={suche} onChange={e => { setSuche(e.target.value); setSeite(1); }}
        className="w-full min-w-0" style={{ background: "transparent" }}/>
    </label>
    {listenFehler && <p role="alert" className="mb-3" style={{ color: "#A5462F" }}>{listenFehler}</p>}
    <p role="status" className="mb-3" style={{ color: "#6C6F5F" }}>{laedt ? "Wird geladen …" : `${liste?.gesamt || 0} ${liste?.gesamt === 1 ? "Antwort" : "Antworten"} gefunden`}</p>
    <div className="grid gap-4 md:grid-cols-3">
      <div className="min-w-0">
        {liste?.eintraege.map(e => <button key={e.id} onClick={() => setAuswahlId(e.id)} aria-pressed={auswahlId === e.id}
          className="block w-full text-left p-3 mb-2" style={{ ...rahmen, background: auswahlId === e.id ? "#E8F0C8" : rahmen.background, overflowWrap: "anywhere" }}>
          <strong className="block">{e.kunde}</strong><span className="block mt-1">{e.betreff}</span>
          <small className="block mt-2" style={{ color: "#6C6F5F" }}>{zeit(e.versendet_am)}</small>
          {e.imap_status === "fehler" && <small className="block mt-1" style={{ color: "#A5462F" }}>Kopie im Mailordner fehlt</small>}
        </button>)}
        {!laedt && !listenFehler && liste?.gesamt === 0 && <p>Keine passenden gesendeten Antworten gefunden.</p>}
        {liste?.seiten > 1 && <div className="flex flex-wrap items-center justify-between gap-2 mt-3">
          <button style={knopf} disabled={laedt || liste.seite <= 1} onClick={() => setSeite(liste.seite - 1)}>Zurück</button>
          <span>Seite {liste.seite} / {liste.seiten}</span>
          <button style={knopf} disabled={laedt || liste.seite >= liste.seiten} onClick={() => setSeite(liste.seite + 1)}>Weiter</button>
        </div>}
      </div>
      <article className="md:col-span-2 min-w-0">
        {detailFehler && <p role="alert" className="p-3 mb-3" style={{ ...rahmen, color: "#A5462F" }}>{detailFehler}</p>}
        {auswahlId && !antwort && !detailFehler && <p>Antwort wird geladen …</p>}
        {antwort && <div className="p-4" style={rahmen}>
          <h3 style={{ fontFamily: "'Source Serif 4', serif", fontSize: "19px", fontWeight: 700, overflowWrap: "anywhere" }}>{antwort.betreff}</h3>
          <div className="mt-2 space-y-1" style={{ color: "#6C6F5F", overflowWrap: "anywhere" }}>
            <p>{antwort.historisch ? "Empfänger laut Anfrage" : "An"}: <strong>{antwort.empfaenger}</strong></p>
            {antwort.absender && <p>Von: {antwort.absender} · {antwort.gesendet_von}</p>}
            <p>An Mailserver übergeben: {zeit(antwort.versendet_am)}</p>
            {antwort.message_id && <p style={{ fontSize: "11px" }}>Message-ID: {antwort.message_id}</p>}
          </div>
          <div className="p-3 my-4" style={{ background: antwort.imap_status === "fehler" ? "#F1DED7" : "#E8F0C8", borderRadius: "5px" }}>
            <strong>{ablageText[antwort.imap_status]}</strong>
            {antwort.imap_ordner && <p>Ordner: {antwort.imap_ordner}</p>}
            {antwort.historisch && <p className="mt-1">Diese Antwort stammt aus der Zeit vor der vollständigen Mailablage. Eine Mailkopie samt Versandanhängen wurde damals noch nicht gespeichert.</p>}
            {antwort.imap_fehler && <p role="alert" className="mt-1">{antwort.imap_fehler}</p>}
            {["fehler", "ausstehend"].includes(antwort.imap_status) && <button disabled={kopiert} onClick={kopieAblegen} style={knopf} className="mt-2">{kopiert ? "Kopie wird abgelegt …" : "Kopie in Gesendet ablegen"}</button>}
          </div>
          <h4 style={{ fontWeight: 600 }}>Versendete Antwort</h4>
          <div className="mt-2" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", lineHeight: 1.6 }}>{antwort.text || "Kein versendeter Antworttext gespeichert."}</div>
          {antwort.text_deutsch && antwort.text_deutsch !== antwort.text && <details className="mt-4"><summary>Freigegebene deutsche Fassung</summary>
            <div className="mt-2" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{antwort.text_deutsch}</div></details>}
          {!antwort.historisch && <div className="mt-4">
            <p style={{ color: "#6C6F5F" }}>Anhänge: {antwort.anhaenge?.length ? antwort.anhaenge.join(", ") : "Keine"}</p>
            <a href={`/api/gesendet/${antwort.id}/eml`} className="inline-block underline mt-2" style={{ color: "#2C5A18" }}>Gesendete Mail einschließlich Anhängen herunterladen (.eml)</a>
          </div>}
          <details className="mt-5 pt-3" style={{ borderTop: "1px solid #DDD9C4" }}><summary>Ursprüngliche Anfrage · {antwort.anfrage.betreff}</summary>
            <p className="mt-2" style={{ color: "#6C6F5F" }}>Gespeicherter Auszug · {zeit(antwort.anfrage.empfangen_am)}</p>
            <div className="mt-2" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{antwort.anfrage.text}</div>
          </details>
        </div>}
      </article>
    </div>
  </section>;
}
