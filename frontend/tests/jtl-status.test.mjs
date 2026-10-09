import assert from "node:assert/strict";
import {test} from "node:test";
import React from "react";
import {act, create} from "react-test-renderer";
import {createServer} from "vite";

test("JTL-Status meldet Fehler und Sperren sichtbar", async t => {
  const server = await createServer({server: {middlewareMode: true}, appType: "custom"});
  t.after(() => server.close());
  const {JtlStatusAnzeige} = await server.ssrLoadModule("/src/JtlSyncStatus.jsx");
  let view;
  t.after(() => view?.unmount());
  const daten = {status: "ok", gesund: true, letzter_lauf: "2026-10-09T12:00:00Z",
    letzter_erfolg: "2026-10-09T12:00:00Z", offene_artikel: 0, gesperrte_artikel: 0, fehler: []};
  await act(async () => { view = create(React.createElement(JtlStatusAnzeige, {daten})); });
  assert.equal(view.root.findAllByProps({role: "alert"}).length, 0);
  assert.match(JSON.stringify(view.toJSON()), /Prüflauf erfolgreich/);
  await act(async () => { view.update(React.createElement(JtlStatusAnzeige, {daten: {...daten,
    status: "gesperrt", gesund: false, gesperrte_artikel: 1, offene_artikel: 1, fehler: ["20015: Rückleseprüfung fehlgeschlagen"]}})); });
  assert.equal(view.root.findAllByProps({role: "alert"}).length, 1);
  assert.match(JSON.stringify(view.toJSON()), /20015: Rückleseprüfung/);
  await act(async () => { view.update(React.createElement(JtlStatusAnzeige, {abrufFehler: true})); });
  assert.match(JSON.stringify(view.toJSON()), /Betrieb nicht bestätigt/);
  assert.doesNotMatch(JSON.stringify(view.toJSON()), /Prüflauf erfolgreich/);
});

test("Fehlgeschlagener Folgeabruf entfernt alten grünen Status", async t => {
  const server = await createServer({server: {middlewareMode: true}, appType: "custom"});
  t.after(() => server.close());
  const {JtlSyncStatus} = await server.ssrLoadModule("/src/JtlSyncStatus.jsx");
  const {api} = await server.ssrLoadModule("/src/api.js");
  let folgeabruf, view, scheitert = false;
  const originalTimeout = globalThis.setTimeout;
  t.mock.method(globalThis, "setTimeout", (fn, delay, ...args) => {
    if (delay === 30000) { folgeabruf = fn; return undefined; }
    return originalTimeout(fn, delay, ...args);
  });
  t.mock.method(api, "jtlSyncStatus", async () => {
    if (scheitert) throw new Error("Offline");
    return {status: "ok", gesund: true, fehler: []};
  });
  t.after(() => view?.unmount());
  await act(async () => { view = create(React.createElement(JtlSyncStatus)); });
  assert.match(JSON.stringify(view.toJSON()), /Prüflauf erfolgreich/);
  scheitert = true;
  await act(async () => { await folgeabruf(); });
  assert.match(JSON.stringify(view.toJSON()), /Betrieb nicht bestätigt/);
  assert.doesNotMatch(JSON.stringify(view.toJSON()), /Prüflauf erfolgreich/);
});
