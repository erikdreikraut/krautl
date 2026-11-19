import assert from "node:assert/strict";
import {test} from "node:test";
import React from "react";
import {act, create} from "react-test-renderer";
import {createServer} from "vite";

test("Erledigen am Listenende öffnet direkt die nächstälteste Mail", async t => {
  const server = await createServer({server: {middlewareMode: true}, appType: "custom"});
  const vorher = {window: globalThis.window, document: globalThis.document};
  const media = Object.assign(new EventTarget(), {matches: false});
  globalThis.window = Object.assign(new EventTarget(), {matchMedia: () => media});
  globalThis.document = Object.assign(new EventTarget(), {visibilityState: "hidden"});
  let view;
  t.after(async () => {
    try { await act(async () => view?.unmount()); }
    finally {
      Object.assign(globalThis, vorher);
      await server.close();
    }
  });
  const {PosteingangView} = await server.ssrLoadModule("/src/App.jsx");
  const {api} = await server.ssrLoadModule("/src/api.js");
  t.mock.method(api, "whatsappChats", async () => []);
  const laden = t.mock.method(api, "mailHtml", async () => ({}));
  const erledigen = t.mock.method(api, "mailErledigen", async () => ({status: "erledigt"}));

  function mail(id, betreff, tag) {
    return {id, betreff, empfangenAm: `2026-09-${tag}T12:00:00Z`, zeit: tag,
      kat: "Test", katId: "TEST", absender: "Test", anhaenge: [], aufgaben: [], felder: {},
      zuweisbareRollen: ["admin", "sachbearbeiter"], konfidenz: 1};
  }
  const aelteste = mail(1, "Älteste Mail", "01");
  const mittlere = mail(2, "Nächste Mail", "01");
  const neueste = mail(3, "Neueste Mail", "03");
  const eingang = mails => React.createElement(PosteingangView, {
    mails, katalog: [], benutzer: {benutzername: "erik"}, alleMails: false,
    onReload: async () => view.update(eingang([mittlere, neueste])),
  });
  await act(async () => { view = create(eingang([aelteste, mittlere, neueste])); });
  const listenButton = betreff => view.root.findAllByType("button").find(button =>
    button.findAllByType("div").some(div => div.children.includes(betreff)));
  await act(async () => listenButton(aelteste.betreff).props.onClick());
  assert.equal(view.root.findByType("h2").children[0], aelteste.betreff);
  const abrufeVorErledigen = laden.mock.callCount();

  const fertigButton = view.root.findAllByType("button").find(button => button.children.includes("Erledigt"));
  await act(async () => fertigButton.props.onClick());
  assert.deepEqual(erledigen.mock.calls[0].arguments, [aelteste.id]);
  assert.equal(listenButton(aelteste.betreff), undefined);
  assert.equal(listenButton(mittlere.betreff).props["aria-current"], "true");
  assert.equal(view.root.findByType("h2").children[0], mittlere.betreff);
  assert.deepEqual(laden.mock.calls.slice(abrufeVorErledigen).map(call => call.arguments[0]), [mittlere.id]);
});
