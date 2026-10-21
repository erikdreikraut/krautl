import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { act, create } from "react-test-renderer";
import { createServer } from "vite";

const rows = [
  { id: "1", datum: "2026-10-01", nummer: "R1", kunde: "Zach", betrag: "9.00", offen: "9", waehrung: "EUR" },
  { id: "2", datum: "2025-10-01", nummer: "R2", kunde: "Änne", betrag: "100.00", offen: "2.50", waehrung: "EUR", mahnsperre: true },
];

test("Datum, Beträge und Kundenname sortieren; Klick kehrt Richtung um", async t => {
  const server = await createServer({ server: { middlewareMode: true }, appType: "custom" });
  t.after(() => server.close());
  const { sortieren, InkassoListe } = await server.ssrLoadModule("/src/InkassoView.jsx");
  assert.deepEqual(sortieren(rows).map(x => x.id), ["2", "1"]);
  assert.deepEqual(sortieren(rows, "betrag").map(x => x.id), ["1", "2"]);
  assert.deepEqual(sortieren(rows, "offen").map(x => x.id), ["2", "1"]);
  assert.deepEqual(sortieren(rows, "kunde").map(x => x.id), ["2", "1"]);
  assert.deepEqual(sortieren(rows, "datum", -1).map(x => x.id), ["1", "2"]);
  let view;
  t.after(() => view?.unmount());
  await act(async () => { view = create(React.createElement(InkassoListe, { daten: { rechnungen: rows, status: "ok", letzter_erfolg: "2026-10-21T12:00:00Z" } })); });
  assert.equal(view.root.findAllByType("th")[0].props["aria-sort"], "ascending");
  await act(async () => { view.root.findAllByType("button")[0].props.onClick(); });
  assert.equal(view.root.findAllByType("th")[0].props["aria-sort"], "descending");
  assert.match(JSON.stringify(view.toJSON()), /Mahnsperre in Wawi/);
});

test("Unbekannt ist nicht leer; veraltete und fehlerhafte Stände warnen", async t => {
  const server = await createServer({ server: { middlewareMode: true }, appType: "custom" });
  t.after(() => server.close());
  const { InkassoListe } = await server.ssrLoadModule("/src/InkassoView.jsx");
  let view;
  t.after(() => view?.unmount());
  await act(async () => { view = create(React.createElement(InkassoListe, { daten: { rechnungen: [], veraltet: true } })); });
  assert.match(JSON.stringify(view.toJSON()), /Noch kein erfolgreicher Rechnungsabruf/);
  assert.doesNotMatch(JSON.stringify(view.toJSON()), /Keine offenen Rechnungen/);
  await act(async () => { view.update(React.createElement(InkassoListe, { daten: { rechnungen: rows, veraltet: true, letzter_erfolg: "2026-10-01T12:00:00Z", fehler: "HTTP 403" } })); });
  assert.match(JSON.stringify(view.toJSON()), /HTTP 403/);
  assert.match(JSON.stringify(view.toJSON()), /Datenstand ist veraltet/);
  assert.equal(view.root.findAllByProps({role: "alert"}).length, 1);
});
