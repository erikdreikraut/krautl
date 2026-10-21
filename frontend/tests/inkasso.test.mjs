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
  await act(async () => { view.root.findAllByType("th")[0].findByType("button").props.onClick(); });
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

test("Kanal, Telefonnummern und lokale Bestellübersicht; alter Snapshot bleibt nutzbar", async t => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: "custom" });
  t.after(() => server.close());
  const { InkassoListe } = await server.ssrLoadModule("/src/InkassoView.jsx");
  let opened = 0, closed = 0;
  const dialogMock = { showModal: () => opened++, close: () => closed++ };
  const row = { ...rows[0], kanal: "JTL-Wawi", telefone: ["0123 456", "+49 170 111"],
    bestellungen: [{ id: "9", nummer: "AU-9", kanal: "JTL-Wawi", datum: "2026-10-01T12:00:00",
      betrag: "99", waehrung: "EUR", positionen: [{ artikel: "Testartikel", sku: "SKU-9", menge: "2", einzelpreis: "12.50" }] }] };
  let view;
  t.after(() => view?.unmount());
  await act(async () => { view = create(React.createElement(InkassoListe, { daten: {
    rechnungen: [row, rows[1]], status: "ok", letzter_erfolg: "2026-10-21T12:00:00Z"
  } }), { createNodeMock: element => element.type === "dialog" ? dialogMock : null }); });
  assert.deepEqual(view.root.findAllByType("a").map(a => a.props.href), ["tel:0123456", "tel:+49170111"]);
  assert.equal(view.root.findAllByType("details").length, 0);
  assert.equal(view.root.findAllByType("dialog").length, 1);
  await act(async () => view.root.findByProps({ "aria-haspopup": "dialog" }).props.onClick());
  assert.equal(opened, 1);
  const closeButton = view.root.findAllByType("button").find(b => b.children.join("") === "Schließen");
  await act(async () => closeButton.props.onClick());
  assert.equal(closed, 1);
  const modal = view.root.findByType("dialog");
  const target = { getBoundingClientRect: () => ({ left: 10, right: 100, top: 10, bottom: 100 }) };
  modal.props.onClick({ target, currentTarget: target, clientX: 50, clientY: 50 });
  assert.equal(closed, 1);
  modal.props.onClick({ target, currentTarget: target, clientX: 0, clientY: 0 });
  assert.equal(closed, 2);
  const text = JSON.stringify(view.toJSON());
  for (const expected of [/JTL-Wawi/, /AU-9/, /Testartikel/, /SKU-9/, /Abgerechnete Positionen/, /Noch nicht abgerufen/]) {
    assert.match(text, expected);
  }
});

test("Zahlungsart: Apotheken als Standard, nur relevante Optionen, Auswahl bleibt bei Aktualisierung", async t => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: "custom" });
  t.after(() => server.close());
  const { InkassoListe } = await server.ssrLoadModule("/src/InkassoView.jsx");
  const data = { rechnungen: [
    { ...rows[0], zahlungsart_id: 12 },
    { ...rows[1], zahlungsart_id: 14 },
    { ...rows[0], id: "3", nummer: "IRRELEVANT", zahlungsart_id: 4 },
  ], letzter_erfolg: "2026-10-21T12:00:00Z", status: "ok" };
  let view;
  t.after(() => view?.unmount());
  await act(async () => { view = create(React.createElement(InkassoListe, { daten: data })); });
  const selection = () => view.root.findByType("select");
  assert.equal(selection().props.value, "12");
  assert.deepEqual(view.root.findAllByType("option").map(o => o.props.value), ["12", "14", "1", "2", "6", "alle"]);
  const numbers = () => view.root.findAllByType("tbody").flatMap(body => body.findAllByType("tr")).map(tr => tr.findAllByType("td")[1].children.join(""));
  assert.deepEqual(numbers(), ["R1"]);
  await act(async () => selection().props.onChange({ target: { value: "14" } }));
  assert.deepEqual(numbers(), ["R2"]);
  await act(async () => view.update(React.createElement(InkassoListe, { daten: { ...data } })));
  assert.equal(selection().props.value, "14");
  await act(async () => selection().props.onChange({ target: { value: "alle" } }));
  assert.deepEqual(numbers(), ["R2", "R1"]);
  assert.ok(!view.root.findAllByType("th").some(th => th.children.join("") === "Zahlungsart"));
  await act(async () => selection().props.onChange({ target: { value: "6" } }));
  assert.deepEqual(numbers(), []);
  assert.match(JSON.stringify(view.toJSON()), /ausgewählte Zahlungsart/);
  await act(async () => view.update(React.createElement(InkassoListe, { daten: { ...data, rechnungen: rows } })));
  assert.equal(selection().props.disabled, true);
  assert.deepEqual(numbers(), ["R2", "R1"]);
  assert.match(JSON.stringify(view.toJSON()), /ungefiltert/);
});

test("Auswahl aktualisieren sendet nur gefilterte IDs aller Seiten und sperrt während eines Auftrags", async t => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: "custom" });
  t.after(() => server.close());
  const { InkassoListe } = await server.ssrLoadModule("/src/InkassoView.jsx");
  const { api } = await server.ssrLoadModule("/src/api.js");
  const calls = [];
  const original = api.inkassoAktualisieren;
  t.after(() => { api.inkassoAktualisieren = original; });
  api.inkassoAktualisieren = async ids => { calls.push(ids); return { status: "wartet", anzahl: ids.length }; };
  const rechnungen = Array.from({ length: 51 }, (_, i) => ({ ...rows[0], id: String(i + 1), zahlungsart_id: 12 }));
  rechnungen.push({ ...rows[1], id: "999", zahlungsart_id: 14 });
  let view, accepted;
  const data = { rechnungen, status: "ok", letzter_erfolg: "2026-10-21T12:00:00Z" };
  t.after(() => view?.unmount());
  await act(async () => { view = create(React.createElement(InkassoListe, { daten: data, onAuftrag: value => { accepted = value; } })); });
  const button = () => view.root.findAllByType("button").find(b => b.props.title?.startsWith("Aktualisiert nur"));
  await act(async () => { await button().props.onClick(); });
  assert.equal(calls.length, 1);
  assert.deepEqual(new Set(calls[0]), new Set(rechnungen.slice(0, 51).map(r => r.id)));
  assert.equal(accepted.anzahl, 51);
  await act(async () => view.update(React.createElement(InkassoListe, { daten: { ...data, aktualisierung: accepted } })));
  assert.equal(button().props.disabled, true);
  assert.match(JSON.stringify(view.toJSON()), /51 Rechnungen warten/);
});


test("Hinweis: Entwurf bleibt beim Nachladen erhalten, Fehler behalten Text, Speichern haengt an und Wiederholung nutzt dieselbe Anfrage", async t => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: "custom" });
  t.after(() => server.close());
  const { InkassoListe } = await server.ssrLoadModule("/src/InkassoView.jsx");
  const { api } = await server.ssrLoadModule("/src/api.js");
  const original = api.inkassoHinweis;
  t.after(() => { api.inkassoHinweis = original; });
  let view, saved, fail = true, requestId;
  t.after(() => view?.unmount());
  api.inkassoHinweis = async (id, text, anfrageId) => {
    assert.deepEqual([id, text], ["1", "Telefoniert"]);
    assert.match(anfrageId, /^[a-f0-9-]{36}$/);
    if (requestId) assert.equal(anfrageId, requestId);
    requestId = anfrageId;
    if (fail) throw new Error("Konflikt");
    return { hinweis: true, hinweise: [{ text, nutzer: "erik", zeit: "2026-10-21T12:00:00Z" }] };
  };
  const props = { daten: { rechnungen: [{ ...rows[0], hinweis: true, hinweise: [{ text: "Alt", nutzer: "erik", zeit: "2026-10-21T12:00:00Z" }] }], letzter_erfolg: "2026-10-21T12:00:00Z" }, onHinweis: (...args) => { saved = args; } };
  await act(async () => { view = create(React.createElement(InkassoListe, props), { createNodeMock: () => ({ showModal() {} }) }); });
  assert.equal(view.root.findAllByType("svg").length, 1);
  await act(async () => view.root.findByProps({ "aria-label": "Notizen ansehen: R1" }).props.onClick());
  assert.equal(view.root.findByType("textarea").props.value, "");
  assert.match(JSON.stringify(view.toJSON()), /Alt/);
  await act(async () => view.root.findByType("textarea").props.onChange({ target: { value: "Telefoniert" } }));
  await act(async () => view.update(React.createElement(InkassoListe, { ...props, daten: { ...props.daten, rechnungen: [] } })));
  assert.equal(view.root.findByType("textarea").props.value, "Telefoniert");
  await act(async () => view.root.findByType("form").props.onSubmit({ preventDefault() {} }));
  assert.match(JSON.stringify(view.toJSON()), /Konflikt/);
  assert.equal(view.root.findByType("textarea").props.value, "Telefoniert");
  fail = false;
  await act(async () => view.root.findByType("form").props.onSubmit({ preventDefault() {} }));
  assert.deepEqual(saved, ["1", { hinweis: true, hinweise: [{ text: "Telefoniert", nutzer: "erik", zeit: "2026-10-21T12:00:00Z" }] }]);
  assert.equal(view.root.findAllByType("dialog").length, 0);
});


test("Acht-Wochen-Grenze folgt Berliner Kalendertagen, auch beim Sommerzeitwechsel", async t => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: "custom" });
  t.after(() => server.close());
  const { altersgruppen } = await server.ssrLoadModule("/src/InkassoView.jsx");
  const daten = [{ id: "55", datum: "2026-08-27" }, { id: "56", datum: "2026-08-26" }, { id: "57", datum: "2026-08-25" }];
  const split = date => altersgruppen(daten, new Date(date)).map(group => group.map(row => row.id));
  assert.deepEqual(split("2026-10-21T12:00:00Z"), [["56", "57"], ["55"]]);
  assert.deepEqual(split("2026-10-20T22:30:00Z"), [["56", "57"], ["55"]]);
  const spring = altersgruppen([{ datum: "2026-02-02" }, { datum: "2026-02-03" }], new Date("2026-03-29T22:30:00Z"));
  assert.deepEqual(spring.map(group => group.length), [1, 1]);
});
