import { Image } from "lucide-react";

export function BilderView() {
  return <section className="flex-1 overflow-y-auto px-6 py-5" style={{ color: "#242A1F" }}>
    <h2 style={{ fontFamily: "'Source Serif 4', serif", fontSize: "21px", fontWeight: 700, color: "#2C5A18" }}>Bilder</h2>
    <div className="flex flex-col items-center gap-3 py-16" style={{ color: "#6C6F5F", fontFamily: "'IBM Plex Sans', sans-serif", fontSize: "13px" }}>
      <Image size={32} aria-hidden="true" />
      <p>Hier sind noch keine Bilder hinterlegt.</p>
    </div>
  </section>;
}
