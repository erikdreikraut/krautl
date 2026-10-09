import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Database, Download, Pencil, Plus, RefreshCw, Save, Search, Sparkles, Trash2, X } from "lucide-react";
import { api } from "./api.js";
import { FaqDokumentImport } from "./FaqDokumentImport.jsx";
import { GoogleFaqFeed } from "./GoogleFaqFeed.jsx";
import { FaqAuswahl } from "./FaqAuswahl.jsx";
import { GoogleFaqAuswahl } from "./GoogleFaqAuswahl.jsx";

const imFaq = f => f.aktiv && f.status === "freigegeben";
const faqEditorDaten = f => ({...f, include_in_faq: imFaq(f)});

const farben = {
  paperRaised: "#FDFCEE", ink: "#242A1F", muted: "#6C6F5F", line: "#DDD9C4",
  moss: "#4F9B2E", mossDeep: "#2C5A18", mossPale: "#E8F0C8", amber: "#B07B2E",
};
const ui = { fontFamily: "'IBM Plex Sans', sans-serif" };
const serif = { fontFamily: "'Source Serif 4', serif" };
const mono = { fontFamily: "'IBM Plex Mono', monospace" };
const feld = { ...ui, fontSize: "13px", background: farben.paperRaised, border: `1px solid ${farben.line}`, borderRadius: "5px", color: farben.ink };

function Marke({ children, warn = false }) {
  return <span className="inline-flex px-2 py-1" style={{ ...mono, fontSize: "10px", border: `1px solid ${farben.line}`, borderLeft: `4px solid ${warn ? farben.amber : farben.moss}` }}>{children}</span>;
}

const statusNamen = { entwurf: "Entwurf", geprueft: "Geprüft", freigegeben: "Freigegeben", veraltet: "Veraltet" };

function StatusMarke({ status }) {
  const entwurf = status === "entwurf";
  return <span className="inline-flex shrink-0 items-center px-2 py-1" style={{
    ...ui, fontSize: "11px", fontWeight: 600, borderRadius: "4px",
    color: entwurf ? "#805619" : status === "freigegeben" ? farben.mossDeep : farben.muted,
    background: entwurf ? "#F8E5B4" : status === "freigegeben" ? farben.mossPale : farben.paperRaised,
  }}>{entwurf ? "Entwurf · prüfen" : statusNamen[status] || status}</span>;
}

function StatusAbschnitte({ eintraege, children }) {
  const stati = [...new Set(["entwurf", "geprueft", "freigegeben", "veraltet", ...eintraege.map((e) => e.status)])];
  return stati.map((status) => {
    const gruppe = eintraege.filter((e) => e.status === status);
    if (!gruppe.length) return null;
    const titel = status === "entwurf" ? "Entwürfe – noch zu prüfen" : statusNamen[status] || status;
    return <section key={status} aria-label={titel} className="mb-6">
      <h4 className="mb-3 flex items-center gap-2" style={{ ...ui, fontSize: "13px", fontWeight: 600, color: status === "entwurf" ? "#805619" : farben.mossDeep }}>
        {titel} <span style={{ ...mono, fontSize: "11px" }}>({gruppe.length})</span>
      </h4>
      {children(gruppe)}
    </section>;
  });
}

function eintragRahmen(status) {
  return {
    background: status === "entwurf" ? "#FFF5DC" : farben.paperRaised,
    border: `1px solid ${status === "entwurf" ? "#D6AD68" : farben.line}`,
    ...(status === "entwurf" ? { borderLeft: `4px solid ${farben.amber}` } : {}),
    borderRadius: "6px",
  };
}

function Formular({ editor, setEditor, speichern, produkte, familien, faqGruppen, formularRef }) {
  const d = editor.daten;
  const set = (name, wert) => setEditor({ ...editor, daten: { ...d, [name]: wert } });
  const bezeichnung = editor.typ === "faq" ? "FAQ-Punkt" : editor.typ === "produkt" ? "Produkt" : "Wissenseintrag";
  return <div ref={formularRef} className="mb-5 p-4" style={{ background: farben.paperRaised, border: `1px solid ${farben.line}`, borderLeft: `4px solid ${farben.moss}`, borderRadius: "6px" }}>
    <div className="flex justify-between mb-3"><h3 style={{ ...serif, fontSize: "16px", fontWeight: 700 }}>{editor.id ? `${bezeichnung} bearbeiten` : `${bezeichnung} anlegen`}</h3><button onClick={() => setEditor(null)}><X size={15}/></button></div>
    {editor.typ === "produkt" && <div className="grid grid-cols-2 gap-3 knowledge-form-grid">
      <input className="px-3 py-2" style={feld} placeholder="Produktname" value={d.name} onChange={(e) => set("name", e.target.value)}/>
      <input className="px-3 py-2" style={feld} placeholder="Artikelnummer" value={d.artikelnummer} onChange={(e) => set("artikelnummer", e.target.value)}/>
      <input className="px-3 py-2" style={feld} placeholder="Produktfamilie" value={d.familie} onChange={(e) => set("familie", e.target.value)}/>
      <input className="px-3 py-2" style={feld} placeholder="Suchbegriffe, kommagetrennt" value={d.aliasesText} onChange={(e) => set("aliasesText", e.target.value)}/>
      <input className="col-span-2 px-3 py-2" style={feld} placeholder="Produktseiten-URL" value={d.website_url} onChange={(e) => set("website_url", e.target.value)}/>
      <label className="col-span-2 flex items-center gap-2" style={{ ...ui, fontSize: "12.5px" }}><input type="checkbox" checked={d.aktiv} onChange={(e) => set("aktiv", e.target.checked)}/> Produkt aktiv</label>
    </div>}
    {editor.typ === "wissen" && <div className="grid grid-cols-2 gap-3 knowledge-form-grid">
      <select className="px-3 py-2" style={feld} value={d.wissensart} onChange={(e) => set("wissensart", e.target.value)}><option value="allgemein">Allgemeines</option><option value="ablauf">Ablauf & Fallwissen</option><option value="produktfamilie">Produktfamilie</option><option value="produkt">Konkretes Produkt</option></select>
      <select className="px-3 py-2" style={feld} value={d.status} onChange={(e) => set("status", e.target.value)}><option value="entwurf">Entwurf</option><option value="geprueft">Geprüft</option><option value="freigegeben">Freigegeben</option><option value="veraltet">Veraltet</option></select>
      {d.wissensart === "produktfamilie" && <select className="col-span-2 px-3 py-2" style={feld} value={d.produktfamilie_id || ""} onChange={(e) => set("produktfamilie_id", e.target.value ? Number(e.target.value) : null)}><option value="">Produktfamilie wählen …</option>{familien.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select>}
      {d.wissensart === "produkt" && <select className="col-span-2 px-3 py-2" style={feld} value={d.produkt_id || ""} onChange={(e) => set("produkt_id", e.target.value ? Number(e.target.value) : null)}><option value="">Produkt wählen …</option>{produkte.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>}
      <input className="col-span-2 px-3 py-2" style={feld} placeholder="Titel" value={d.titel} onChange={(e) => set("titel", e.target.value)}/>
      <textarea className="col-span-2 px-3 py-2" style={feld} rows={6} placeholder="Verbindliche Fakten" value={d.inhalt} onChange={(e) => set("inhalt", e.target.value)}/>
      <input className="px-3 py-2" style={feld} placeholder="Quelle" value={d.quelle || ""} onChange={(e) => set("quelle", e.target.value)}/>
      <input className="px-3 py-2" style={feld} placeholder="Stand, z. B. 2026-07" value={d.stand || ""} onChange={(e) => set("stand", e.target.value)}/>
      <label className="col-span-2 flex items-center gap-2" style={{ ...ui, fontSize: "12.5px" }}><input type="checkbox" checked={d.sensibel} onChange={(e) => set("sensibel", e.target.checked)}/> Gesundheits-/rechtlich sensible Aussage</label>
    </div>}
    {editor.typ === "faq" && <div className="grid grid-cols-2 gap-3 knowledge-form-grid">
      <div><input list="faq-gruppen" className="w-full px-3 py-2" style={feld} placeholder="Gruppe, z. B. Anwendung & Praktisches" value={d.kategorie} onChange={(e) => set("kategorie", e.target.value)}/><datalist id="faq-gruppen">{faqGruppen.map((g) => <option key={g} value={g}/>)}</datalist></div>
      <label className="flex items-center gap-2" style={ui}><input type="checkbox" checked={!!d.include_in_faq} onChange={(e) => set("include_in_faq", e.target.checked)}/> In FAQ aufnehmen</label>
      <select className="col-span-2 px-3 py-2" style={feld} value={d.produkt_id || ""} onChange={(e) => set("produkt_id", e.target.value ? Number(e.target.value) : null)}><option value="">Allgemeine FAQ (kein Produkt)</option>{produkte.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
      <input className="col-span-2 px-3 py-2" style={feld} placeholder="Frage" value={d.frage} onChange={(e) => set("frage", e.target.value)}/>
      <textarea className="col-span-2 px-3 py-2" style={feld} rows={7} placeholder="Antwort – Absätze, - Aufzählungen und **Fettdruck** sind möglich" value={d.antwort} onChange={(e) => set("antwort", e.target.value)}/>
      <input className="px-3 py-2" style={feld} placeholder="Quelle" value={d.quelle || ""} onChange={(e) => set("quelle", e.target.value)}/>
      <input className="px-3 py-2" style={feld} type="number" placeholder="Reihenfolge" value={d.sortierung} onChange={(e) => set("sortierung", Number(e.target.value))}/>
      <p className="col-span-2" style={{ ...ui, fontSize: "12px", color: farben.muted }}>Mit „In FAQ aufnehmen“ gehört dieser Eintrag zum FAQ. Ohne Haken bleibt er ein Entwurf.</p>
      <div className="col-span-2">
        <label className="flex items-center gap-2" style={{ ...ui, fontSize: "12.5px" }}><input type="checkbox" checked={!!d.include_in_google_product_qa} onChange={(e) => set("include_in_google_product_qa", e.target.checked)}/> Für Google ausgewählt</label>
        <p className="mt-1" style={{ ...ui, fontSize: "12px", color: farben.muted }}>Mit diesem Haken wird das Frage/Antwort-Paar für den öffentlichen Google-Export ausgewählt, unabhängig vom FAQ-Status. Es gelten die Google-Format- und Größenlimits. Der JTL-HTML-Export bleibt unverändert.</p>
      </div>
    </div>}
    <button onClick={speichern} className="flex items-center gap-1.5 mt-3 px-3 py-2" style={{ ...ui, fontSize: "12.5px", fontWeight: 600, color: "#fff", background: farben.moss, borderRadius: "6px" }}><Save size={13}/> Speichern</button>
  </div>;
}

export function WissensdatenbankViewNeu({ basis, faqEintraege, vorschlaege, onReload }) {
  const [bereich, setBereich] = useState("wissen");
  const [auswahl, setAuswahl] = useState("alle");
  const [suche, setSuche] = useState("");
  const [produktsuche, setProduktsuche] = useState("");
  const [editor, setEditor] = useState(null);
  const [exportHtml, setExportHtml] = useState(null);
  const [meldung, setMeldung] = useState("");
  const [shopImportLaeuft, setShopImportLaeuft] = useState(false);
  const [rubrikEditor, setRubrikEditor] = useState(null);
  const formularRef = useRef(null);
  const loeschSperre = useRef(false);
  const [loescht, setLoescht] = useState(false);
  const produkte = basis?.produkte || [];
  const familien = basis?.familien || [];
  const familienNachId = Object.fromEntries(familien.map((f) => [f.id, f]));
  const produktSuchbegriffe = produktsuche.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const gefilterteProdukte = produkte.filter((p) => {
    const suchtext = [p.name, p.artikelnummer, ...(p.aliases || []),
      familienNachId[p.produktfamilie_id]?.name, p.website_url].filter(Boolean).join(" ").toLowerCase();
    return produktSuchbegriffe.every((begriff) => suchtext.includes(begriff));
  });
  const produktId = auswahl.startsWith("produkt:") ? Number(auswahl.split(":")[1]) : null;
  const familieId = auswahl.startsWith("familie:") ? Number(auswahl.split(":")[1]) : null;
  const produkt = produkte.find((p) => p.id === produktId);
  const familie = familien.find((f) => f.id === familieId);
  const passt = (text) => !suche.trim() || text.toLowerCase().includes(suche.trim().toLowerCase());

  const wissen = useMemo(() => (basis?.eintraege || []).filter((e) => {
    if (!passt(`${e.titel} ${e.inhalt} ${e.quelle || ""}`)) return false;
    if (auswahl === "alle") return true;
    if (["allgemein", "ablauf"].includes(auswahl)) return e.wissensart === auswahl;
    if (familie) return e.wissensart === "produktfamilie" && e.produktfamilie_id === familie.id;
    return produkt && (e.produkt_id === produkt.id || (e.wissensart === "produktfamilie" && e.produktfamilie_id === produkt.produktfamilie_id));
  }), [basis, auswahl, produktId, familieId, suche]);
  const faq = useMemo(() => faqEintraege.filter((e) => {
    if (!passt(`${e.kategorie} ${e.frage} ${e.antwort}`)) return false;
    if (auswahl === "alle") return true;
    if (familie) return produkte.some((p) => p.produktfamilie_id === familie.id && p.id === e.produkt_id);
    return produkt ? e.produkt_id === produkt.id : e.produkt_id == null;
  }), [faqEintraege, auswahl, produktId, familieId, suche, produkte]);
  const faqGruppen = [...new Set(
    faqEintraege
      .filter((e) => !produkt || e.produkt_id === produkt.id)
      .map((e) => e.kategorie)
      .filter(Boolean)
  )];

  useEffect(() => {
    if (editor) requestAnimationFrame(() => formularRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }, [editor?.typ, editor?.id]);

  useEffect(() => setRubrikEditor(null), [produktId]);

  const neu = (typ) => {
    if (typ === "google") { typ = "faq"; setBereich("faq"); }
    if (typ === "produkt") return setEditor({ typ, daten: { name: "", artikelnummer: "", familie: "", aliasesText: "", website_url: "", aktiv: true } });
    if (typ === "wissen") return setEditor({ typ, daten: { wissensart: produkt ? "produkt" : familie ? "produktfamilie" : auswahl === "ablauf" ? "ablauf" : "allgemein", titel: "", inhalt: "", produkt_id: produkt?.id || null, produktfamilie_id: familie?.id || produkt?.produktfamilie_id || null, quelle: "", stand: "", status: "entwurf", sensibel: false, schlagwoerter: [] } });
    const familienProdukte = familie ? produkte.filter((p) => p.produktfamilie_id === familie.id) : [];
    const faqProdukt = produkt || (familienProdukte.length === 1 ? familienProdukte[0] : null);
    setEditor({ typ, daten: { produkt_id: faqProdukt?.id || null, kategorie: "Allgemeines", frage: "", antwort: "", quelle: faqProdukt?.website_url || "", include_in_faq: false, sortierung: 0, include_in_google_product_qa: false } });
  };
  const speichern = async () => {
    const { typ, daten, id } = editor;
    try {
      if (typ === "produkt") await api.produktSpeichern(id, { ...daten, aliases: (daten.aliasesText || "").split(",").map((a) => a.trim()).filter(Boolean) });
      else if (typ === "wissen") await api.wissenSpeichern(id, daten);
      else await api.faqSpeichern(id, daten);
      setEditor(null); setMeldung("Gespeichert."); await onReload();
    } catch (fehler) { setMeldung(`Speichern fehlgeschlagen: ${fehler.message}`); }
  };
  const faqAuswahlGespeichert = async (eintrag) => {
    setEditor(aktuell => aktuell?.typ === "faq" && aktuell.id === eintrag.id
      ? {...aktuell, daten: {...aktuell.daten, include_in_faq: imFaq(eintrag)}} : aktuell);
    setExportHtml(null);
    await onReload();
  };
  const googleAuswahlGespeichert = async (eintrag) => {
    setEditor((aktuell) => aktuell?.typ === "faq" && aktuell.id === eintrag.id
      ? { ...aktuell, daten: { ...aktuell.daten, include_in_google_product_qa: eintrag.include_in_google_product_qa } }
      : aktuell);
    await onReload();
  };
  const faqLoeschen = async (eintrag) => {
    if (loeschSperre.current) return;
    if (!window.confirm(`FAQ wirklich dauerhaft löschen?

„${eintrag.frage}“

Das Löschen kann nicht rückgängig gemacht werden.`)) return;
    loeschSperre.current = true;
    setLoescht(true);
    try {
      await api.faqLoeschen(eintrag.id);
      setEditor((aktuell) => aktuell?.typ === "faq" && aktuell.id === eintrag.id ? null : aktuell);
      setExportHtml(null);
      setMeldung("FAQ gelöscht.");
      try { await onReload(); }
      catch { setMeldung("FAQ gelöscht. Bitte die Ansicht neu laden; die Aktualisierung ist fehlgeschlagen."); }
    } catch (fehler) {
      setMeldung(`FAQ konnte nicht gelöscht werden: ${fehler.message}`);
    } finally {
      loeschSperre.current = false;
      setLoescht(false);
    }
  };
  const rubrikSpeichern = async () => {
    const neuerName = rubrikEditor.neu.trim();
    if (!neuerName) {
      setMeldung("Der Rubrikname darf nicht leer sein.");
      return;
    }
    try {
      const ergebnis = await api.faqRubrikUmbenennen(produkt.id, rubrikEditor.alt, neuerName);
      setRubrikEditor(null);
      setMeldung(`Rubrik umbenannt. ${ergebnis.aktualisiert} FAQ-Punkte wurden aktualisiert.`);
      await onReload();
    } catch (fehler) {
      setMeldung(`Rubrik konnte nicht umbenannt werden: ${fehler.message}`);
    }
  };
  const exportieren = async () => {
    const ergebnis = await api.faqExport(produkt.id);
    if (!ergebnis.anzahl) {
      setExportHtml(null);
      setMeldung("Keine FAQ-Punkte mit „In FAQ aufnehmen“ ausgewählt.");
      return;
    }

    setExportHtml(ergebnis.html);
    try { await navigator.clipboard.writeText(ergebnis.html); setMeldung(`${ergebnis.anzahl} FAQ-Punkte als vollständiges JTL-HTML kopiert.`); }
    catch { setMeldung("HTML ist unten zum Kopieren geöffnet."); }
  };
  const shopProdukteImportieren = async () => {
    setShopImportLaeuft(true); setMeldung("Produktbestand wird aus dem Shop gelesen …");
    try {
      const ergebnis = await api.produkteAusShopImportieren();
      setMeldung(`${ergebnis.im_shop} Shop-Produkte gefunden · ${ergebnis.angelegt} neu angelegt · ${ergebnis.aktualisiert} aktualisiert.`);
      await onReload();
    } catch (fehler) {
      setMeldung(`Shop-Produkte konnten nicht aktualisiert werden: ${fehler.message}`);
    } finally { setShopImportLaeuft(false); }
  };
  const tab = (id, label) => <button onClick={() => setBereich(id)} className="pb-2" style={{ ...ui, fontSize: "13px", fontWeight: bereich === id ? 600 : 500, color: bereich === id ? farben.mossDeep : farben.muted, borderBottom: bereich === id ? `2px solid ${farben.mossDeep}` : "2px solid transparent" }}>{label}</button>;

  return <div className="flex-1 min-h-0 flex flex-col overflow-hidden knowledge-view">
    <div className="px-6 pt-5 knowledge-header" style={{ borderBottom: `1px solid ${farben.line}` }}>
      <div className="flex items-start justify-between gap-4 knowledge-header-row"><div><h2 style={{ ...serif, fontSize: "21px", fontWeight: 700, color: farben.mossDeep }}>Wissensdatenbank</h2><p style={{ ...ui, fontSize: "12.5px", color: farben.muted }}>{basis.eintraege.length} Wissenseinträge · {faqEintraege.length} FAQ · {vorschlaege.length} Vorschläge</p></div>
        <div className="flex gap-2 knowledge-tools"><div className="flex items-center gap-2 px-2.5 py-1.5 knowledge-search" style={{ background: farben.paperRaised, border: `1px solid ${farben.line}`, borderRadius: "6px" }}><Search size={13}/><input value={suche} onChange={(e) => setSuche(e.target.value)} placeholder="Wissen durchsuchen …" style={{ ...ui, fontSize: "12.5px", background: "transparent", outline: "none" }}/></div>{bereich !== "vorschlaege" && <button onClick={() => neu(bereich)} className="flex items-center gap-1.5 px-3 py-2 shrink-0" style={{ ...ui, fontSize: "12px", color: "#fff", background: farben.moss, borderRadius: "6px" }}><Plus size={13}/> {["faq", "google"].includes(bereich) ? "FAQ" : "Wissenseintrag"}</button>}</div></div>
      <div className="flex flex-wrap gap-5 mt-4">{tab("wissen", "Wissen")}{tab("faq", "FAQ")}{tab("google", "Google-FAQ-Feed")}{tab("vorschlaege", `Vorschläge ${vorschlaege.length || ""}`)}</div>
    </div>
    {bereich === "faq" && produkt && faqGruppen.length > 0 && <div className="flex flex-wrap items-center gap-2 px-6 py-2.5" style={{ background: farben.paperRaised, borderBottom: `1px solid ${farben.line}` }}>
      <span style={{ ...mono, fontSize: "10px", color: farben.muted }}>RUBRIKEN</span>
      {faqGruppen.map((g) => rubrikEditor?.alt === g ? <div key={g} className="flex items-center gap-1">
        <input autoFocus className="px-2 py-1" style={{ ...feld, width: "260px", fontSize: "12px" }} value={rubrikEditor.neu} onChange={(e) => setRubrikEditor({ ...rubrikEditor, neu: e.target.value })} onKeyDown={(e) => { if (e.key === "Enter") rubrikSpeichern(); if (e.key === "Escape") setRubrikEditor(null); }}/>
        <button title="Rubrik speichern" onClick={rubrikSpeichern} className="p-1" style={{ color: farben.mossDeep }}><Check size={14}/></button>
        <button title="Abbrechen" onClick={() => setRubrikEditor(null)} className="p-1" style={{ color: farben.muted }}><X size={14}/></button>
      </div> : <div key={g} className="flex items-center gap-1 px-2 py-1" style={{ border: `1px solid ${farben.line}`, borderRadius: "5px" }}>
        <span style={{ ...ui, fontSize: "11.5px", color: farben.muted }}>{g}</span>
        <button title="Rubriküberschrift bearbeiten" onClick={() => setRubrikEditor({ alt: g, neu: g })} className="p-0.5" style={{ color: farben.muted }}><Pencil size={11}/></button>
      </div>)}
    </div>}
    <div className="flex flex-1 min-h-0 knowledge-body"><aside className="w-56 shrink-0 overflow-y-auto p-4 knowledge-sidebar" style={{ background: farben.paperRaised, borderRight: `1px solid ${farben.line}` }}>
      {[["alle", "Alle Inhalte"], ["allgemein", "Allgemeines"], ["ablauf", "Abläufe & Fallwissen"]].map(([id, label]) => <button key={id} onClick={() => setAuswahl(id)} className="w-full text-left px-2.5 py-2" style={{ ...ui, fontSize: "12.5px", fontWeight: auswahl === id ? 600 : 400, color: auswahl === id ? farben.mossDeep : farben.muted, background: auswahl === id ? farben.mossPale : "transparent", borderRadius: "5px" }}>{label}</button>)}
      <div className="mt-5 px-2.5" style={{ ...mono, fontSize: "10px", color: farben.muted }}>PRODUKTFAMILIEN</div>{familien.map((f) => <button key={f.id} onClick={() => setAuswahl(`familie:${f.id}`)} className="w-full text-left px-2.5 py-2" style={{ ...ui, fontSize: "12px", fontWeight: familieId === f.id ? 600 : 400, color: familieId === f.id ? farben.mossDeep : farben.muted, background: familieId === f.id ? farben.mossPale : "transparent", borderRadius: "5px" }}>{f.name}</button>)}
      <label htmlFor="produktfilter" className="block mt-5 px-2.5" style={{ ...mono, fontSize: "10px", color: farben.muted }}>PRODUKTE</label>
      <div className="flex items-center gap-1.5 mt-2 mb-1 px-2 py-1.5" style={feld}>
        <Search size={13} className="shrink-0" aria-hidden="true"/>
        <input id="produktfilter" type="search" value={produktsuche} onChange={(e) => setProduktsuche(e.target.value)}
          placeholder="Produkte filtern …" aria-label="Produkte filtern" aria-describedby="produktfilter-hilfe"
          className="w-full min-w-0" style={{ ...ui, fontSize: "12px", background: "transparent" }}/>
        {produktsuche && <button type="button" onClick={() => setProduktsuche("")} title="Produktfilter zurücksetzen" aria-label="Produktfilter zurücksetzen" className="shrink-0 p-0.5"><X size={13}/></button>}
      </div>
      <p id="produktfilter-hilfe" className="sr-only">Suche nach Name, Artikelnummer, Suchbegriffen, Produktfamilie und URL. Alle eingegebenen Wörter müssen vorkommen.</p>
      {produktSuchbegriffe.length > 0 && <p role="status" className="px-2.5 py-1" style={{ ...ui, fontSize: "11px", color: farben.muted }}>{gefilterteProdukte.length} von {produkte.length} Produkten</p>}
      {gefilterteProdukte.map((p) => <div key={p.id} className="flex items-start">
        <button onClick={() => setAuswahl(`produkt:${p.id}`)} className="flex-1 min-w-0 text-left px-2.5 py-2" style={{ ...ui, fontSize: "12px", fontWeight: produktId === p.id ? 600 : 400, color: produktId === p.id ? farben.mossDeep : farben.muted, background: produktId === p.id ? farben.mossPale : "transparent", borderRadius: "5px", overflowWrap: "anywhere" }}>
          {p.name}
          <strong className="block" style={{ ...mono, fontSize: "11px", fontWeight: 700 }}>Art.-Nr.: {p.artikelnummer || "nicht hinterlegt"}</strong>
        </button>
        <button title="Produkt bearbeiten" onClick={() => setEditor({ typ: "produkt", id: p.id, daten: { ...p, familie: familienNachId[p.produktfamilie_id]?.name || "", aliasesText: (p.aliases || []).join(", ") } })} className="shrink-0 p-2" style={{ color: farben.muted }}><Pencil size={12}/></button>
      </div>)}
      {produktSuchbegriffe.length > 0 && gefilterteProdukte.length === 0 && <p className="px-2.5 py-2" style={{ ...ui, fontSize: "12px", color: farben.muted }}>Keine passenden Produkte.</p>}
      <button onClick={() => neu("produkt")} className="flex items-center gap-1.5 mt-2 px-2.5 py-2" style={{ ...ui, fontSize: "12px", color: farben.mossDeep }}><Plus size={12}/> Produkt anlegen</button>
      <button disabled={shopImportLaeuft} onClick={shopProdukteImportieren} className="flex items-center gap-1.5 px-2.5 py-2 text-left" style={{ ...ui, fontSize: "12px", color: farben.mossDeep, opacity: shopImportLaeuft ? 0.6 : 1 }}><RefreshCw size={12} className={shopImportLaeuft ? "animate-spin" : ""}/> Shop-Produkte aktualisieren</button>
    </aside>
    <main className="flex-1 overflow-y-auto p-6 knowledge-main">{meldung && <div className="mb-4 px-3 py-2" style={{ ...ui, fontSize: "12.5px", color: farben.mossDeep, background: farben.mossPale }}>{meldung}</div>}{editor && <Formular formularRef={formularRef} editor={editor} setEditor={setEditor} speichern={speichern} produkte={produkte} familien={familien} faqGruppen={faqGruppen}/>}
      {bereich === "wissen" && <>
        <div className="flex items-center gap-2 mb-4"><Database size={15} color={farben.moss}/><h3 style={{ ...serif, fontWeight: 700 }}>{produkt?.name || familie?.name || "Wissenseinträge"}</h3></div>
        <StatusAbschnitte eintraege={wissen}>{(gruppe) =>
          <div className="grid grid-cols-2 gap-3 knowledge-card-grid">{gruppe.map((e) =>
            <button key={e.id} onClick={() => setEditor({ typ: "wissen", id: e.id, daten: { ...e, schlagwoerter: e.schlagwoerter || [] } })}
              className="flex flex-col items-start text-left p-4" style={eintragRahmen(e.status)}>
              <div className="flex w-full justify-between items-start gap-2"><Marke warn={e.sensibel}>{e.wissensart.toUpperCase()}</Marke><StatusMarke status={e.status}/></div>
              <div className="mt-2" style={{ ...serif, fontWeight: 700 }}>{e.titel}</div>
              <div className="mt-1" style={{ ...ui, fontSize: "12.5px", color: farben.muted, lineHeight: 1.5 }}>{e.inhalt}</div>
            </button>
          )}</div>
        }</StatusAbschnitte>
        {wissen.length === 0 && <LeereAnsicht text="Noch kein passendes Wissen hinterlegt." aktion={() => neu("wissen")} label="Ersten Wissenseintrag anlegen"/>}
      </>}
      {bereich === "faq" && <>
        <FaqDokumentImport produkte={produkte} onReload={onReload}/>
        <div className="flex justify-between mb-4"><h3 style={{ ...serif, fontWeight: 700 }}>{produkt ? `FAQ · ${produkt.name} · Art.-Nr.: ${produkt.artikelnummer || "nicht hinterlegt"}` : "FAQ"}</h3>{produkt && <button onClick={exportieren} className="flex items-center gap-1.5 px-3 py-2" style={{ ...ui, fontSize: "12px", color: farben.mossDeep, border: `1px solid ${farben.line}`, borderRadius: "5px" }}><Download size={13}/> Aktuelles JTL-HTML kopieren</button>}</div>
        {[...new Set(faq.map((f) => f.kategorie))].map((g) => <div key={g} className="mb-5">
            <div className="mb-2" style={{ ...mono, fontSize: "10.5px", color: farben.muted }}>{g.toUpperCase()}</div>
            {faq.filter((f) => f.kategorie === g).map((f) => <article key={f.id} className="p-3 mb-2" style={eintragRahmen(imFaq(f) ? "freigegeben" : "entwurf")}>
              <button onClick={() => setEditor({ typ: "faq", id: f.id, daten: faqEditorDaten(f) })} className="block w-full text-left">
                <div className="flex justify-between items-start gap-3"><b style={serif}>{f.frage}</b></div>
                <div className="mt-1" style={{ ...serif, fontSize: "14px", color: farben.muted }}>{f.antwort}</div>
              </button>
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                <FaqAuswahl faqId={f.id} frage={f.frage} ausgewaehlt={imFaq(f)} onGespeichert={faqAuswahlGespeichert}/>
                <GoogleFaqAuswahl faqId={f.id} frage={f.frage} ausgewaehlt={f.include_in_google_product_qa} onGespeichert={googleAuswahlGespeichert}/>
                <button type="button" disabled={loescht} onClick={() => faqLoeschen(f)} aria-label={`FAQ löschen: ${f.frage}`} className="flex items-center gap-1.5 px-2 py-1" style={{ ...ui, fontSize: "12px", color: "#9A4332", border: `1px solid ${farben.line}`, borderRadius: "5px", opacity: loescht ? 0.5 : 1 }}><Trash2 size={13}/> Löschen</button>
              </div>
            </article>)}
          </div>)}
        {faq.length === 0 && <LeereAnsicht text="Noch keine FAQ für diese Auswahl." aktion={() => neu("faq")} label="Erstes FAQ anlegen"/>}
      </>}
      {bereich === "vorschlaege" && <><div className="flex items-center gap-2"><Sparkles size={16} color={farben.amber}/><h3 style={{ ...serif, fontWeight: 700 }}>Ergänzungen aus bearbeiteten Antworten</h3></div><p style={{ ...ui, fontSize: "12.5px", color: farben.muted }}>Nur wiederverwendbare Ergänzungen; nichts wird automatisch freigegeben.</p><div className="flex flex-col gap-3 mt-4">{vorschlaege.map((v) => <div key={v.id} className="p-4" style={{ background: farben.paperRaised, border: `1px solid ${farben.line}`, borderLeft: `4px solid ${farben.amber}` }}><div className="flex justify-between"><Marke warn>{(v.ziel === "faq" ? "FAQ" : v.wissensart).toUpperCase()}</Marke><span style={{ ...mono, fontSize: "10px" }}>Mail #{v.quelle_mail_id}</span></div><b className="block mt-2" style={serif}>{v.titel}</b><div style={{ ...serif, fontSize: "14px" }}>{v.inhalt}</div>{v.begruendung && <small style={{ ...ui, color: farben.muted }}>{v.begruendung}</small>}<div className="flex gap-2 mt-3"><button onClick={async () => { await api.wissensvorschlagUebernehmen(v.id, { ziel: v.ziel, wissensart: v.wissensart, produkt_id: v.produkt_id, titel: v.titel, inhalt: v.inhalt, kategorie: "Kundenfragen" }); await onReload(); }} className="flex items-center gap-1 px-3 py-1.5" style={{ ...ui, fontSize: "12px", color: "#fff", background: farben.moss }}><Check size={12}/> Als Entwurf übernehmen</button><button onClick={async () => { await api.wissensvorschlagVerwerfen(v.id); await onReload(); }} className="px-3 py-1.5" style={{ ...ui, fontSize: "12px", border: `1px solid ${farben.line}` }}>Verwerfen</button></div></div>)}</div>{vorschlaege.length === 0 && <LeereAnsicht text="Keine offenen Vorschläge. Sie entstehen nur, wenn eine bearbeitete Antwort wirklich neues Wissen enthält."/>}</>}
      {bereich === "google" && <GoogleFaqFeed produkt={produkt} produkte={produkte} faqEintraege={faqEintraege} onGoogleAuswahlGespeichert={googleAuswahlGespeichert} onBearbeiten={(id) => {
        const faq = faqEintraege.find((f) => f.id === id);
        if (faq) { setBereich("faq"); setEditor({ typ: "faq", id, daten: faqEditorDaten(faq) }); }
      }}/>}
      {exportHtml !== null && <div className="mt-5 p-4" style={{ background: farben.paperRaised, border: `1px solid ${farben.line}` }}><div className="flex justify-between"><b style={ui}>JTL-HTML · vollständig</b><button onClick={() => setExportHtml(null)}><X size={14}/></button></div><textarea readOnly value={exportHtml} onFocus={(e) => e.target.select()} rows={16} className="w-full mt-2 px-3 py-2" style={{ ...mono, fontSize: "11px", background: "#fff", border: `1px solid ${farben.line}` }}/></div>}
    </main></div>
  </div>;
}

function LeereAnsicht({ text, aktion, label }) {
  return <div className="py-12 text-center" style={{ ...ui, fontSize: "13px", color: farben.muted }}>{text}{aktion && <><br/><button onClick={aktion} className="mt-3 px-3 py-2" style={{ color: farben.mossDeep, border: `1px solid ${farben.line}`, borderRadius: "5px" }}>{label}</button></>}</div>;
}
