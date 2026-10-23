import { useCallback, useEffect, useState } from "react";
import { BookOpen, Image, LogOut } from "lucide-react";
import { api } from "./api.js";
import logo from "./assets/krautl-logo.png";
import { WissensdatenbankViewNeu } from "./WissensdatenbankView.jsx";
import { BilderView } from "./BilderView.jsx";

export function GrafikAnwendung({ benutzer, onAbmelden }) {
  const [tab, setTab] = useState("wissen");
  const [daten, setDaten] = useState(null);
  const [fehler, setFehler] = useState("");
  const [version, setVersion] = useState(0);
  const neuLaden = useCallback(() => setVersion(v => v + 1), []);
  useEffect(() => {
    let aktiv = true;
    let laeuft = false;
    const laden = async () => {
      if (laeuft) return;
      laeuft = true;
      try {
        const [basis, faq] = await Promise.all([api.wissensbasis(), api.faq()]);
        if (aktiv) { setDaten({ basis, faq }); setFehler(""); }
      } catch (e) {
        if (aktiv) {
          if (e.status === 401) onAbmelden();
          else setFehler(e.message);
        }
      } finally { laeuft = false; }
    };
    laden();
    const timer = setInterval(laden, 30000);
    return () => { aktiv = false; clearInterval(timer); };
  }, [version, onAbmelden]);

  return <div className="w-full h-full flex flex-col krautl-app" style={{ background: "#F8F6D9", minHeight: "640px", color: "#242A1F" }}>
    <header className="flex items-center px-5 krautl-header" style={{ borderBottom: "1px solid #DDD9C4", background: "#FDFCEE" }}>
      <div className="flex items-center gap-2.5 pr-5 py-2 krautl-logo"><img src={logo} alt="Krautl" style={{ height: "34px", width: "auto" }} /></div>
      <nav aria-label="Hauptnavigation" className="flex items-center krautl-nav">
        {[["wissen", "Wissensdatenbank", BookOpen], ["bilder", "Bilder", Image]].map(([id, label, Icon]) => <button
          key={id} type="button" onClick={() => setTab(id)} aria-current={tab === id ? "page" : undefined}
          className="flex items-center gap-2 px-3 py-4" style={{ color: tab === id ? "#2C5A18" : "#6C6F5F", borderBottom: `2px solid ${tab === id ? "#4F9B2E" : "transparent"}`, fontFamily: "'IBM Plex Sans', sans-serif", fontSize: "13px" }}>
          <Icon size={15} />{label}
        </button>)}
      </nav>
      <div className="ml-auto flex items-center gap-2 krautl-header-meta" style={{ fontFamily: "'IBM Plex Sans', sans-serif", fontSize: "12.5px" }}>
        <span>{benutzer.name} · Grafik</span>
        <button type="button" onClick={onAbmelden} title="Abmelden" aria-label="Abmelden" className="p-2"><LogOut size={15} /></button>
      </div>
    </header>
    {tab === "bilder" ? <BilderView /> : <>
      {fehler && <div role="alert" className="px-6 py-3">{fehler} <button type="button" onClick={neuLaden}>Erneut laden</button></div>}
      {daten ? <WissensdatenbankViewNeu basis={daten.basis} faqEintraege={daten.faq} vorschlaege={[]} zeigeVorschlaege={false} onReload={neuLaden} /> : !fehler && <p className="p-6">Wissensdatenbank wird geladen …</p>}
    </>}
  </div>;
}
