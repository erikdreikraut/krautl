import { useMemo, useState } from "react";
import { Check, Database, Download, Pencil, Plus, Save, Search, Sparkles, X } from "lucide-react";
import { api } from "./api.js";

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

function Formular({ editor, setEditor, speichern, produkte, familien }) {
  const d = editor.daten;
  const set = (name, wert) => setEditor({ ...editor, daten: { ...d, [name]: wert } });
  return <div className="mb-5 p-4" style={{ background: farben.paperRaised, border: `1px solid ${farben.line}`, borderLeft: `4px solid ${farben.moss}`, borderRadius: "6px" }}>
    <div className="flex justify-between mb-3"><h3 style={{ ...serif, fontSize: "16px", fontWeight: 700 }}>{editor.id ? "Eintrag bearbeiten" : "Neuen Eintrag anlegen"}</h3><button onClick={() => setEditor(null)}><X size={15}/></button></div>
    {editor.typ === "produkt" && <div className="grid grid-cols-2 gap-3">
      <input className="px-3 py-2" style={feld} placeholder="Produktname" value={d.name} onChange={(e) => set("name", e.target.value)}/>
      <input className="px-3 py-2" style={feld} placeholder="Artikelnummer" value={d.artikelnummer} onChange={(e) => set("artikelnummer", e.target.value)}/>
      <input className="px-3 py-2" style={feld} placeholder="Produktfamilie" value={d.familie} onChange={(e) => set("familie", e.target.value)}/>
      <input className="px-3 py-2" style={feld} placeholder="Suchbegriffe, kommagetrennt" value={d.aliasesText} onChange={(e) => set("aliasesText", e.target.value)}/>
      <input className="col-span-2 px-3 py-2" style={feld} placeholder="Produktseiten-URL" value={d.website_url} onChange={(e) => set("website_url", e.target.value)}/>
      <label className="col-span-2 flex items-center gap-2" style={{ ...ui, fontSize: "12.5px" }}><input type="checkbox" checked={d.aktiv} onChange={(e) => set("aktiv", e.target.checked)}/> Produkt aktiv</label>
    </div>}
    {editor.typ === "wissen" && <div className="grid grid-cols-2 gap-3">
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
    {editor.typ === "faq" && <div className="grid grid-cols-2 gap-3">
      <input className="px-3 py-2" style={feld} placeholder="Abschnitt, z. B. Anwendung & Praktisches" value={d.kategorie} onChange={(e) => set("kategorie", e.target.value)}/>
      <select className="px-3 py-2" style={feld} value={d.status} onChange={(e) => set("status", e.target.value)}><option value="entwurf">Entwurf</option><option value="freigegeben">Freigegeben</option><option value="veraltet">Veraltet</option></select>
      <select className="col-span-2 px-3 py-2" style={feld} value={d.produkt_id || ""} onChange={(e) => set("produkt_id", e.target.value ? Number(e.target.value) : null)}><option value="">Allgemeine FAQ (kein Produkt)</option>{produkte.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
      <input className="col-span-2 px-3 py-2" style={feld} placeholder="Frage" value={d.frage} onChange={(e) => set("frage", e.target.value)}/>
      <textarea className="col-span-2 px-3 py-2" style={feld} rows={7} placeholder="Antwort – Absätze, - Aufzählungen und **Fettdruck** sind möglich" value={d.antwort} onChange={(e) => set("antwort", e.target.value)}/>
      <input className="px-3 py-2" style={feld} placeholder="Quelle" value={d.quelle || ""} onChange={(e) => set("quelle", e.target.value)}/>
      <input className="px-3 py-2" style={feld} type="number" placeholder="Reihenfolge" value={d.sortierung} onChange={(e) => set("sortierung", Number(e.target.value))}/>
      <label className="col-span-2 flex items-center gap-2" style={{ ...ui, fontSize: "12.5px" }}><input type="checkbox" checked={d.aktiv} onChange={(e) => set("aktiv", e.target.checked)}/> Im aktuellen FAQ enthalten</label>
    </div>}
    <button onClick={speichern} className="flex items-center gap-1.5 mt-3 px-3 py-2" style={{ ...ui, fontSize: "12.5px", fontWeight: 600, color: "#fff", background: farben.moss, borderRadius: "6px" }}><Save size={13}/> Speichern</button>
  </div>;
}

export function WissensdatenbankViewNeu({ basis, faqEintraege, vorschlaege, onReload }) {
  const [bereich, setBereich] = useState("wissen");
  const [auswahl, setAuswahl] = useState("alle");
  const [suche, setSuche] = useState("");
  const [editor, setEditor] = useState(null);
  const [exportHtml, setExportHtml] = useState(null);
  const [meldung, setMeldung] = useState("");
  const produkte = basis?.produkte || [];
  const familien = basis?.familien || [];
  const familienNachId = Object.fromEntries(familien.map((f) => [f.id, f]));
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

  const neu = (typ) => {
    if (typ === "produkt") return setEditor({ typ, daten: { name: "", artikelnummer: "", familie: "", aliasesText: "", website_url: "", aktiv: true } });
    if (typ === "wissen") return setEditor({ typ, daten: { wissensart: produkt ? "produkt" : familie ? "produktfamilie" : auswahl === "ablauf" ? "ablauf" : "allgemein", titel: "", inhalt: "", produkt_id: produkt?.id || null, produktfamilie_id: familie?.id || produkt?.produktfamilie_id || null, quelle: "", stand: "", status: "entwurf", sensibel: false, schlagwoerter: [] } });
    setEditor({ typ, daten: { produkt_id: produkt?.id || null, kategorie: "Allgemeines", frage: "", antwort: "", quelle: produkt?.website_url || "", status: "entwurf", sortierung: 0, aktiv: true } });
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
  const exportieren = async () => {
    const ergebnis = await api.faqExport(produkt.id); setExportHtml(ergebnis.html);
    try { await navigator.clipboard.writeText(ergebnis.html); setMeldung("JTL-HTML wurde in die Zwischenablage kopiert."); }
    catch { setMeldung("HTML ist unten zum Kopieren geöffnet."); }
  };
  const tab = (id, label) => <button onClick={() => setBereich(id)} className="pb-2" style={{ ...ui, fontSize: "13px", fontWeight: bereich === id ? 600 : 500, color: bereich === id ? farben.mossDeep : farben.muted, borderBottom: bereich === id ? `2px solid ${farben.mossDeep}` : "2px solid transparent" }}>{label}</button>;

  return <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
    <div className="px-6 pt-5" style={{ borderBottom: `1px solid ${farben.line}` }}>
      <div className="flex items-start justify-between gap-4"><div><h2 style={{ ...serif, fontSize: "21px", fontWeight: 700, color: farben.mossDeep }}>Wissensdatenbank</h2><p style={{ ...ui, fontSize: "12.5px", color: farben.muted }}>{basis.eintraege.length} Wissenseinträge · {faqEintraege.length} FAQ · {vorschlaege.length} Vorschläge</p></div>
        <div className="flex gap-2"><div className="flex items-center gap-2 px-2.5 py-1.5" style={{ background: farben.paperRaised, border: `1px solid ${farben.line}`, borderRadius: "6px" }}><Search size={13}/><input value={suche} onChange={(e) => setSuche(e.target.value)} placeholder="Wissen durchsuchen …" style={{ ...ui, fontSize: "12.5px", background: "transparent", outline: "none" }}/></div>{bereich !== "vorschlaege" && <button onClick={() => neu(bereich)} className="flex items-center gap-1.5 px-3 py-2" style={{ ...ui, fontSize: "12px", color: "#fff", background: farben.moss, borderRadius: "6px" }}><Plus size={13}/> {bereich === "faq" ? "FAQ" : "Wissenseintrag"}</button>}</div></div>
      <div className="flex gap-5 mt-4">{tab("wissen", "Wissen")}{tab("faq", "FAQ")}{tab("vorschlaege", `Vorschläge ${vorschlaege.length || ""}`)}</div>
    </div>
    <div className="flex flex-1 min-h-0"><aside className="w-56 shrink-0 overflow-y-auto p-4" style={{ background: farben.paperRaised, borderRight: `1px solid ${farben.line}` }}>
      {[["alle", "Alle Inhalte"], ["allgemein", "Allgemeines"], ["ablauf", "Abläufe & Fallwissen"]].map(([id, label]) => <button key={id} onClick={() => setAuswahl(id)} className="w-full text-left px-2.5 py-2" style={{ ...ui, fontSize: "12.5px", fontWeight: auswahl === id ? 600 : 400, color: auswahl === id ? farben.mossDeep : farben.muted, background: auswahl === id ? farben.mossPale : "transparent", borderRadius: "5px" }}>{label}</button>)}
      <div className="mt-5 px-2.5" style={{ ...mono, fontSize: "10px", color: farben.muted }}>PRODUKTFAMILIEN</div>{familien.map((f) => <button key={f.id} onClick={() => setAuswahl(`familie:${f.id}`)} className="w-full text-left px-2.5 py-2" style={{ ...ui, fontSize: "12px", fontWeight: familieId === f.id ? 600 : 400, color: familieId === f.id ? farben.mossDeep : farben.muted, background: familieId === f.id ? farben.mossPale : "transparent", borderRadius: "5px" }}>{f.name}</button>)}
      <div className="mt-5 px-2.5" style={{ ...mono, fontSize: "10px", color: farben.muted }}>PRODUKTE</div>{produkte.map((p) => <div key={p.id} className="flex items-start"><button onClick={() => setAuswahl(`produkt:${p.id}`)} className="flex-1 text-left px-2.5 py-2" style={{ ...ui, fontSize: "12px", fontWeight: produktId === p.id ? 600 : 400, color: produktId === p.id ? farben.mossDeep : farben.muted, background: produktId === p.id ? farben.mossPale : "transparent", borderRadius: "5px" }}>{p.name}<span className="block" style={{ ...mono, fontSize: "9.5px" }}>{p.artikelnummer || familienNachId[p.produktfamilie_id]?.name}</span></button><button title="Produkt bearbeiten" onClick={() => setEditor({ typ: "produkt", id: p.id, daten: { ...p, familie: familienNachId[p.produktfamilie_id]?.name || "", aliasesText: (p.aliases || []).join(", ") } })} className="p-2" style={{ color: farben.muted }}><Pencil size={12}/></button></div>)}
      <button onClick={() => neu("produkt")} className="flex items-center gap-1.5 mt-2 px-2.5 py-2" style={{ ...ui, fontSize: "12px", color: farben.mossDeep }}><Plus size={12}/> Produkt anlegen</button>
    </aside>
    <main className="flex-1 overflow-y-auto p-6">{meldung && <div className="mb-4 px-3 py-2" style={{ ...ui, fontSize: "12.5px", color: farben.mossDeep, background: farben.mossPale }}>{meldung}</div>}{editor && <Formular editor={editor} setEditor={setEditor} speichern={speichern} produkte={produkte} familien={familien}/>}
      {bereich === "wissen" && <><div className="flex items-center gap-2 mb-4"><Database size={15} color={farben.moss}/><h3 style={{ ...serif, fontWeight: 700 }}>{produkt?.name || familie?.name || "Wissenseinträge"}</h3></div><div className="grid grid-cols-2 gap-3">{wissen.map((e) => <button key={e.id} onClick={() => setEditor({ typ: "wissen", id: e.id, daten: { ...e, schlagwoerter: e.schlagwoerter || [] } })} className="text-left p-4" style={{ background: farben.paperRaised, border: `1px solid ${farben.line}`, borderRadius: "6px" }}><div className="flex justify-between"><Marke warn={e.sensibel}>{e.wissensart.toUpperCase()}</Marke><span style={{ ...mono, fontSize: "10px", color: farben.muted }}>{e.status}</span></div><div className="mt-2" style={{ ...serif, fontWeight: 700 }}>{e.titel}</div><div className="mt-1" style={{ ...ui, fontSize: "12.5px", color: farben.muted, lineHeight: 1.5 }}>{e.inhalt}</div></button>)}</div>{wissen.length === 0 && <LeereAnsicht text="Noch kein passendes Wissen hinterlegt." aktion={() => neu("wissen")} label="Ersten Wissenseintrag anlegen"/>}</>}
      {bereich === "faq" && <><div className="flex justify-between mb-4"><h3 style={{ ...serif, fontWeight: 700 }}>{produkt ? `FAQ · ${produkt.name}` : "FAQ"}</h3>{produkt && <button onClick={exportieren} className="flex items-center gap-1.5 px-3 py-2" style={{ ...ui, fontSize: "12px", color: farben.mossDeep, border: `1px solid ${farben.line}`, borderRadius: "5px" }}><Download size={13}/> Gesamtes JTL-HTML kopieren</button>}</div>{[...new Set(faq.map((f) => f.kategorie))].map((g) => <div key={g} className="mb-5"><div style={{ ...mono, fontSize: "10.5px", color: farben.muted }}>{g.toUpperCase()}</div>{faq.filter((f) => f.kategorie === g).map((f) => <button key={f.id} onClick={() => setEditor({ typ: "faq", id: f.id, daten: { ...f } })} className="block w-full text-left py-3" style={{ borderBottom: `1px solid ${farben.line}` }}><div className="flex justify-between"><b style={serif}>{f.frage}</b><span style={{ ...mono, fontSize: "10px", color: farben.muted }}>{f.status}</span></div><div style={{ ...serif, fontSize: "14px", color: farben.muted }}>{f.antwort}</div></button>)}</div>)}{faq.length === 0 && <LeereAnsicht text="Noch keine FAQ für diese Auswahl." aktion={() => neu("faq")} label="Erstes FAQ anlegen"/>}</>}
      {bereich === "vorschlaege" && <><div className="flex items-center gap-2"><Sparkles size={16} color={farben.amber}/><h3 style={{ ...serif, fontWeight: 700 }}>Ergänzungen aus bearbeiteten Antworten</h3></div><p style={{ ...ui, fontSize: "12.5px", color: farben.muted }}>Nur wiederverwendbare Ergänzungen; nichts wird automatisch freigegeben.</p><div className="flex flex-col gap-3 mt-4">{vorschlaege.map((v) => <div key={v.id} className="p-4" style={{ background: farben.paperRaised, border: `1px solid ${farben.line}`, borderLeft: `4px solid ${farben.amber}` }}><div className="flex justify-between"><Marke warn>{(v.ziel === "faq" ? "FAQ" : v.wissensart).toUpperCase()}</Marke><span style={{ ...mono, fontSize: "10px" }}>Mail #{v.quelle_mail_id}</span></div><b className="block mt-2" style={serif}>{v.titel}</b><div style={{ ...serif, fontSize: "14px" }}>{v.inhalt}</div>{v.begruendung && <small style={{ ...ui, color: farben.muted }}>{v.begruendung}</small>}<div className="flex gap-2 mt-3"><button onClick={async () => { await api.wissensvorschlagUebernehmen(v.id, { ziel: v.ziel, wissensart: v.wissensart, produkt_id: v.produkt_id, titel: v.titel, inhalt: v.inhalt, kategorie: "Kundenfragen" }); await onReload(); }} className="flex items-center gap-1 px-3 py-1.5" style={{ ...ui, fontSize: "12px", color: "#fff", background: farben.moss }}><Check size={12}/> Als Entwurf übernehmen</button><button onClick={async () => { await api.wissensvorschlagVerwerfen(v.id); await onReload(); }} className="px-3 py-1.5" style={{ ...ui, fontSize: "12px", border: `1px solid ${farben.line}` }}>Verwerfen</button></div></div>)}</div>{vorschlaege.length === 0 && <LeereAnsicht text="Keine offenen Vorschläge. Sie entstehen nur, wenn eine bearbeitete Antwort wirklich neues Wissen enthält."/>}</>}
      {exportHtml !== null && <div className="mt-5 p-4" style={{ background: farben.paperRaised, border: `1px solid ${farben.line}` }}><div className="flex justify-between"><b style={ui}>JTL-HTML · vollständig</b><button onClick={() => setExportHtml(null)}><X size={14}/></button></div><textarea readOnly value={exportHtml} onFocus={(e) => e.target.select()} rows={16} className="w-full mt-2 px-3 py-2" style={{ ...mono, fontSize: "11px", background: "#fff", border: `1px solid ${farben.line}` }}/></div>}
    </main></div>
  </div>;
}

function LeereAnsicht({ text, aktion, label }) {
  return <div className="py-12 text-center" style={{ ...ui, fontSize: "13px", color: farben.muted }}>{text}{aktion && <><br/><button onClick={aktion} className="mt-3 px-3 py-2" style={{ color: farben.mossDeep, border: `1px solid ${farben.line}`, borderRadius: "5px" }}>{label}</button></>}</div>;
}
