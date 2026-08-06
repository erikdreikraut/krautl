const BASIS = "/api";

async function anfrage(pfad, optionen) {
  const antwort = await fetch(`${BASIS}${pfad}`, optionen);
  if (!antwort.ok) {
    let detail = "";
    try {
      const fehler = await antwort.json();
      detail = fehler.detail ? ` – ${fehler.detail}` : "";
    } catch {
      // Manche Proxy-Fehler liefern kein JSON.
    }
    const meldung = new Error(`${optionen?.method || "GET"} ${pfad} fehlgeschlagen: ${antwort.status}${detail}`);
    meldung.status = antwort.status;
    throw meldung;
  }
  if (antwort.status === 204) return null;
  return antwort.json();
}

async function dateiAnfrage(pfad) {
  const antwort = await fetch(`${BASIS}${pfad}`);
  if (!antwort.ok) {
    let detail = "Datei konnte nicht geöffnet werden.";
    try {
      const fehler = await antwort.json();
      if (fehler.detail) detail = fehler.detail;
    } catch {
      // Proxy-Fehler enthalten nicht immer eine lesbare Antwort.
    }
    throw new Error(detail);
  }
  return antwort.blob();
}

function postForm(pfad, params) {
  const query = new URLSearchParams(params).toString();
  return anfrage(`${pfad}?${query}`, { method: "POST" });
}

export const api = {
  angemeldeterBenutzer: () => anfrage("/auth/me"),
  login: (benutzername, passwort) =>
    anfrage("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ benutzername, passwort }),
    }),
  logout: () => anfrage("/auth/logout", { method: "POST" }),
  health: () => anfrage("/health"),
  mails: (alle = false) => anfrage(alle ? "/mails?alle=true" : "/mails"),
  klassifikationen: () => anfrage("/klassifikationen"),
  klassifikationSpeichern: (klassifikationId, daten) =>
    anfrage(`/klassifikationen/${klassifikationId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(daten),
    }),
  aktionslog: () => anfrage("/aktionslog"),
  rollenMailzugriff: () => anfrage("/rollen-mailzugriff"),
  rollenMailzugriffSpeichern: (rolle, klassifikationIds) =>
    anfrage(`/rollen-mailzugriff/${rolle}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ klassifikation_ids: klassifikationIds }),
    }),
  mailBestaetigen: (mailId) =>
    anfrage(`/mails/${mailId}/bestaetigen`, { method: "POST" }),
  mailErledigen: (mailId) =>
    anfrage(`/mails/${mailId}/erledigen`, { method: "POST" }),
  mailLoeschen: (mailId) =>
    anfrage(`/mails/${mailId}`, { method: "DELETE" }),
  mailZuweisen: (mailId, rolle) =>
    anfrage(`/mails/${mailId}/zustaendigkeit`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rolle }),
    }),
  korrigiereKlassifikation: (mailId, neueKlassifikationId, notiz) =>
    postForm(`/mails/${mailId}/korrektur`, {
      neue_klassifikation_id: neueKlassifikationId,
      ...(notiz ? { notiz } : {}),
    }),

  rechnungen: () => anfrage("/rechnungen"),
  rechnungAlsBezahlt: (rechnungId) =>
    anfrage(`/rechnungen/${rechnungId}/als-bezahlt`, { method: "POST" }),
  rechnungStatusAendern: (rechnungId, zahlungsstatus) =>
    anfrage(`/rechnungen/${rechnungId}/zahlungsstatus`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ zahlungsstatus }),
    }),
  rechnungDateiLaden: (rechnungId) =>
    dateiAnfrage(`/rechnungen/${rechnungId}/datei`),

  faq: () => anfrage("/faq"),
  wissensbasis: () => anfrage("/wissensbasis"),
  produktSpeichern: (id, daten) =>
    anfrage(id ? `/produkte/${id}` : "/produkte", {
      method: id ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(daten),
    }),
  produkteAusShopImportieren: () =>
    anfrage("/produkte/shop-import", { method: "POST" }),
  wissenSpeichern: (id, daten) =>
    anfrage(id ? `/wissen/${id}` : "/wissen", {
      method: id ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(daten),
    }),
  faqSpeichern: (id, daten) =>
    anfrage(id ? `/faq/${id}` : "/faq", {
      method: id ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(daten),
    }),
  faqRubrikUmbenennen: (produktId, alteKategorie, neueKategorie) =>
    anfrage("/faq-rubriken", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        produkt_id: produktId,
        alte_kategorie: alteKategorie,
        neue_kategorie: neueKategorie,
      }),
    }),
  faqExport: (produktId) => anfrage(`/produkte/${produktId}/faq-export`),
  wissensvorschlaege: () => anfrage("/wissensvorschlaege"),
  wissensvorschlagUebernehmen: (id, daten) =>
    anfrage(`/wissensvorschlaege/${id}/uebernehmen`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(daten),
    }),
  wissensvorschlagVerwerfen: (id) =>
    anfrage(`/wissensvorschlaege/${id}/verwerfen`, { method: "POST" }),
  faqVorschlaege: () => anfrage("/faq/vorschlaege"),
  faqVorschlagUebernehmen: (id) =>
    anfrage(`/faq/vorschlaege/${id}/uebernehmen`, { method: "POST" }),
  faqVorschlagVerwerfen: (id) =>
    anfrage(`/faq/vorschlaege/${id}/verwerfen`, { method: "POST" }),

  entwuerfe: (alle = false) => anfrage(alle ? "/entwuerfe?alle=true" : "/entwuerfe"),
  antwortentwurfErzeugen: (mailId) =>
    anfrage(`/mails/${mailId}/antwortentwurf`, { method: "POST" }),
  entwurfFreigeben: (id, finalerText) =>
    anfrage(`/entwuerfe/${id}/freigeben`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ finaler_text: finalerText }),
    }),
  entwurfVerwerfen: (id) => anfrage(`/entwuerfe/${id}/verwerfen`, { method: "POST" }),
};
