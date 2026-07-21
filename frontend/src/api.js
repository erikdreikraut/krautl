const BASIS = "/api";

async function anfrage(pfad, optionen) {
  const antwort = await fetch(`${BASIS}${pfad}`, optionen);
  if (!antwort.ok) {
    throw new Error(`${optionen?.method || "GET"} ${pfad} fehlgeschlagen: ${antwort.status}`);
  }
  if (antwort.status === 204) return null;
  return antwort.json();
}

function postForm(pfad, params) {
  const query = new URLSearchParams(params).toString();
  return anfrage(`${pfad}?${query}`, { method: "POST" });
}

export const api = {
  mails: () => anfrage("/mails"),
  klassifikationen: () => anfrage("/klassifikationen"),
  korrigiereKlassifikation: (mailId, neueKlassifikationId, notiz) =>
    postForm(`/mails/${mailId}/korrektur`, {
      neue_klassifikation_id: neueKlassifikationId,
      ...(notiz ? { notiz } : {}),
    }),

  rechnungen: () => anfrage("/rechnungen"),
  rechnungAlsBezahlt: (rechnungId) =>
    anfrage(`/rechnungen/${rechnungId}/als-bezahlt`, { method: "POST" }),

  faq: () => anfrage("/faq"),
  faqVorschlaege: () => anfrage("/faq/vorschlaege"),
  faqVorschlagUebernehmen: (id) =>
    anfrage(`/faq/vorschlaege/${id}/uebernehmen`, { method: "POST" }),
  faqVorschlagVerwerfen: (id) =>
    anfrage(`/faq/vorschlaege/${id}/verwerfen`, { method: "POST" }),

  entwuerfe: () => anfrage("/entwuerfe"),
  entwurfFreigeben: (id, finalerText) =>
    postForm(`/entwuerfe/${id}/freigeben`, { finaler_text: finalerText }),
  entwurfVerwerfen: (id) => anfrage(`/entwuerfe/${id}/verwerfen`, { method: "POST" }),
};
