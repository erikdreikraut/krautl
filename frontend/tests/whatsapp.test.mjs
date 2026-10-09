import assert from "node:assert/strict";
import {test} from "node:test";
import React from "react";
import {act, create} from "react-test-renderer";
import {createServer} from "vite";

test("WhatsApp-Antworten ohne echten Versand", async t => {
  const server = await createServer({server: {middlewareMode: true}, appType: "custom"});
  t.after(() => server.close());
  const {WhatsAppChatPanel} = await server.ssrLoadModule("/src/WhatsAppView.jsx");
  const {api} = await server.ssrLoadModule("/src/api.js");

  async function chatOeffnen(t, {fokus = true, revision = 1, entwurf = "", entwurfRevision = null, fensterOffen = true, reservierungsFehler = false} = {}) {
    const doc = new EventTarget();
    const win = new EventTarget();
    doc.visibilityState = "visible";
    doc.hasFocus = () => fokus;
    t.mock.method(globalThis, "setInterval", () => 1);
    t.mock.method(globalThis, "clearInterval", () => {});
    const vorher = {document: globalThis.document, window: globalThis.window, requestAnimationFrame: globalThis.requestAnimationFrame};
    Object.assign(globalThis, {document: doc, window: win, requestAnimationFrame: fn => fn()});
    const chat = {id: 1, name: "Testkontakt", kontakt_id: "491234", revision,
      entwurf, entwurf_revision: entwurfRevision, status: "offen", nachrichten: [],
      antwortfenster_bis: new Date(Date.now() + (fensterOffen ? 3600000 : -3600000)).toISOString()};
    t.mock.method(api, "whatsappChat", async () => ({...chat}));
    t.mock.method(api, "whatsappReservieren", async () => {
      if (reservierungsFehler) throw new Error("Chat wird von einer anderen Person bearbeitet");
      return {eigene: true};
    });
    t.mock.method(api, "whatsappFreigeben", async () => ({}));
    const senden = t.mock.method(api, "whatsappSenden", async () => ({status: "angenommen"}));
    const feld = {focus: t.mock.fn(), setSelectionRange: t.mock.fn(), selectionStart: 2, selectionEnd: 2, maxLength: 4096};
    let view;
    await act(async () => { view = create(React.createElement(WhatsAppChatPanel, {
      id: 1, benutzer: {benutzername: "test"}, onReload: async () => {},
    }), {createNodeMock: el => el.type === "textarea" ? feld : null}); });
    t.after(async () => {
      try { await act(async () => view.unmount()); }
      finally { Object.assign(globalThis, vorher); }
    });
    const antwort = () => view.root.findByProps({id: "wa-antwort-1"});
    const button = () => view.root.findAllByType("button").find(b => b.children.includes("Antwort senden"));
    return {senden, feld, chat, antwort, button,
      schreiben: async value => act(async () => antwort().props.onChange({target: {value}})),
      taste: async (extra = {}) => act(async () => antwort().props.onKeyDown({key: "Enter", nativeEvent: {}, preventDefault() {}, currentTarget: feld, ...extra})),
      fokus: async wert => act(async () => { fokus = wert; win.dispatchEvent(new Event(wert ? "focus" : "blur")); }),
      sichtbar: async wert => act(async () => { doc.visibilityState = wert ? "visible" : "hidden"; doc.dispatchEvent(new Event("visibilitychange")); }),
    };
  }

  for (const weg of ["Enter", "Button"]) await t.test(`${weg} sendet genau einmal`, async t => {
    const c = await chatOeffnen(t);
    await c.schreiben("Hallo");
    assert.equal(c.button().props.disabled, false);
    if (weg === "Enter") await c.taste();
    else await act(async () => c.button().props.onClick());
    assert.equal(c.senden.mock.callCount(), 1);
    assert.equal(c.senden.mock.calls[0].arguments[1].text, "Hallo");
    assert.equal(c.antwort().props.value, "");
  });

  await t.test("Shift+Enter ersetzt die Auswahl durch einen Zeilenumbruch; Strg+Enter sendet nicht", async t => {
    const c = await chatOeffnen(t);
    await c.schreiben("Hallo");
    c.feld.selectionEnd = 4;
    await c.taste({shiftKey: true});
    assert.equal(c.antwort().props.value, "Ha\no");
    assert.deepEqual(c.feld.setSelectionRange.mock.calls[0].arguments, [3, 3]);
    await c.taste({ctrlKey: true});
    assert.equal(c.antwort().props.value, "Ha\no");
    assert.equal(c.senden.mock.callCount(), 0);
  });

  await t.test("Rückkehr aus anderem Fenster oder Tab entsperrt sofort und stiehlt keinen Fokus", async t => {
    const c = await chatOeffnen(t, {fokus: false});
    assert.equal(c.antwort().props.disabled, true);
    await c.fokus(true);
    assert.equal(c.antwort().props.disabled, false);
    await c.schreiben("Hallo");
    await c.sichtbar(false);
    assert.equal(c.button().props.disabled, true);
    await c.sichtbar(true);
    assert.equal(c.button().props.disabled, false);
    assert.equal(c.feld.focus.mock.callCount(), 1);
    await c.taste();
    assert.equal(c.senden.mock.callCount(), 1);
  });

  for (const [grund, optionen] of [
    ["abgelaufenes Antwortfenster", {fensterOffen: false}],
    ["veralteter Entwurf", {revision: 2, entwurf: "Alt", entwurfRevision: 1}],
    ["fremde Reservierung", {reservierungsFehler: true}],
  ]) await t.test(`${grund} verhindert weiterhin Versand`, async t => {
    const c = await chatOeffnen(t, optionen);
    await c.schreiben("Hallo");
    assert.equal(c.button().props.disabled, true);
    await c.taste();
    await act(async () => c.button().props.onClick());
    assert.equal(c.senden.mock.callCount(), 0);
  });

  await t.test("Tastenwiederholung und Texteingabe-Komposition senden nicht", async t => {
    const c = await chatOeffnen(t);
    await c.schreiben("Hallo");
    await c.taste({repeat: true});
    await c.taste({nativeEvent: {isComposing: true}});
    assert.equal(c.senden.mock.callCount(), 0);
  });

  await t.test("Enter und Klick während laufendem Versand erzeugen keinen zweiten Auftrag", async t => {
    const c = await chatOeffnen(t);
    let fertig;
    c.senden.mock.mockImplementation(() => new Promise(resolve => { fertig = resolve; }));
    await c.schreiben("Hallo");
    let versand;
    await act(async () => {
      const senden = c.button().props.onClick;
      versand = senden();
      senden();
    });
    await c.taste();
    assert.equal(c.senden.mock.callCount(), 1);
    await act(async () => { fertig({status: "angenommen"}); await versand; });
  });

  await t.test("Unklarer Versand erhält Text und Auftrags-ID ohne automatische Wiederholung", async t => {
    const c = await chatOeffnen(t);
    c.senden.mock.mockImplementation(async () => { throw new Error("Timeout"); });
    await c.schreiben("Hallo");
    await c.taste();
    assert.equal(c.senden.mock.callCount(), 1);
    assert.equal(c.antwort().props.value, "Hallo");
    await c.fokus(false);
    await c.fokus(true);
    assert.equal(c.senden.mock.callCount(), 1);
    await c.taste();
    assert.equal(c.senden.mock.calls[0].arguments[1].auftrag_id, c.senden.mock.calls[1].arguments[1].auftrag_id);
  });
});
