import assert from "node:assert/strict";
import {test} from "node:test";
import React from "react";
import {act, create} from "react-test-renderer";
import {createServer} from "vite";

test("FAQ zeigt Artikelnummern und nur zwei unabhängige Auswahlhaken", async t => {
  const server = await createServer({server: {middlewareMode: true, hmr: {port: 0}}, appType: "custom"});
  t.after(() => server.close());
  const {WissensdatenbankViewNeu} = await server.ssrLoadModule("/src/WissensdatenbankView.jsx");
  const {api} = await server.ssrLoadModule("/src/api.js");
  const eintrag = {id: 1, produkt_id: 1, kategorie: "Test", frage: "Frage?", antwort: "Antwort", status: "entwurf", aktiv: false, include_in_google_product_qa: true, sortierung: 0};
  const auswahl = t.mock.method(api, "faqAuswahl", async (id, wert) => ({...eintrag, aktiv: wert, status: wert ? "freigegeben" : "entwurf"}));
  const speichern = t.mock.method(api, "faqSpeichern", async () => ({}));
  const vorher = globalThis.requestAnimationFrame;
  globalThis.requestAnimationFrame = fn => fn();
  let view;
  t.after(async () => { await act(async () => view?.unmount()); globalThis.requestAnimationFrame = vorher; });
  await act(async () => { view = create(React.createElement(WissensdatenbankViewNeu, {
    basis: {produkte: [{id: 1, name: "Testprodukt", artikelnummer: "00123"}], familien: [], eintraege: []},
    faqEintraege: [eintrag], vorschlaege: [], onReload: async () => {},
  })); });
  const buttons = () => view.root.findAllByType("button");
  await act(async () => buttons().find(b => b.children.includes("FAQ")).props.onClick());
  await act(async () => buttons().find(b => b.children.includes("Testprodukt")).props.onClick());
  assert.equal(view.root.findAllByType("strong").filter(el => el.children.includes("00123")).length, 2);
  assert.doesNotMatch(JSON.stringify(view.toJSON()), /Art.-Nr.:|nicht hinterlegt/);
  assert.equal(view.root.findAllByType("input").filter(i => i.props.type === "checkbox").length, 2);
  const faqHaken = () => view.root.findByProps({"aria-label": "In FAQ aufnehmen: Frage?"});
  await act(async () => faqHaken().props.onChange({target: {checked: true}}));
  assert.deepEqual(auswahl.mock.calls[0].arguments, [1, true]);
  const google = view.root.findByProps({"aria-label": "Für Google auswählen: Frage?"});
  assert.equal(google.props.checked, true);
  await act(async () => buttons().find(b => b.findAllByType("b").some(el => el.children.includes("Frage?"))).props.onClick());
  assert.equal(view.root.findAllByType("select").length, 1); // Nur die Produktzuordnung.
  const editorHaken = view.root.findAllByType("input").filter(i => i.props.type === "checkbox" && !i.props["aria-label"]);
  assert.equal(editorHaken.length, 2);
  await act(async () => editorHaken[0].props.onChange({target: {checked: true}}));
  await act(async () => buttons().find(b => b.children.includes(" Speichern")).props.onClick());
  assert.equal(speichern.mock.calls[0].arguments[1].include_in_faq, true);
  assert.equal(speichern.mock.calls[0].arguments[1].include_in_google_product_qa, true);
});
