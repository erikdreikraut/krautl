import assert from "node:assert/strict";
import {test} from "node:test";
import React from "react";
import {act, create} from "react-test-renderer";
import {createServer} from "vite";

async function testEingang(t, {fensterAktiv = false} = {}) {
  const server = await createServer({server: {middlewareMode: true}, appType: "custom"});
  const vorher = {window: globalThis.window, document: globalThis.document};
  const media = Object.assign(new EventTarget(), {matches: false});
  globalThis.window = Object.assign(new EventTarget(), {matchMedia: () => media});
  globalThis.document = Object.assign(new EventTarget(), {
    visibilityState: fensterAktiv ? "visible" : "hidden", hasFocus: () => fensterAktiv,
  });
  let view;
  t.after(async () => {
    try { await act(async () => view?.unmount()); }
    finally {
      Object.assign(globalThis, vorher);
      await server.close();
    }
  });
  const {EntwurfPanel, PosteingangView} = await server.ssrLoadModule("/src/App.jsx");
  const {api} = await server.ssrLoadModule("/src/api.js");
  t.mock.method(api, "whatsappChats", async () => []);
  t.mock.method(api, "mailHtml", async () => ({}));
  return {api, EntwurfPanel, PosteingangView, mount: async element => {
    await act(async () => { view = create(element); });
    return view;
  }};
}

function mail(id, betreff, tag) {
  return {id, betreff, empfangenAm: `2026-09-${tag}T12:00:00Z`, zeit: tag,
    kat: "Test", katId: "TEST", absender: "Test", anhaenge: [], aufgaben: [], felder: {},
    zuweisbareRollen: ["admin", "sachbearbeiter"], konfidenz: 1};
}

test("Fehlende Belege erzeugen keinen Hinweis im Posteingang", async t => {
  const {api, PosteingangView, mount} = await testEingang(t);
  const aufgabe_typ = "RECHNUNG_VERWALTEN";
  const bestaetigen = t.mock.method(api, "mailBestaetigen", async () => ({
    status: "fehlgeschlagen", aufgabe_typ, detail: "Anhänge enthalten laut Auswertung keine Rechnung",
  }));
  const ohneBeleg = {...mail(1, "Ohne Beleg", "03"), bestaetigungErforderlich: true,
    aufgaben: [{id: 1, status: "fehlgeschlagen", aufgabe_typ, fehler: "Kein unterstützter Rechnungsanhang gefunden"}]};
  const mitFehler = {...mail(2, "Ablagefehler", "02"),
    aufgaben: [{id: 2, status: "fehlgeschlagen", aufgabe_typ, fehler: "Dropbox nicht erreichbar"}]};
  const view = await mount(React.createElement(PosteingangView, {
    mails: [ohneBeleg, mitFehler], katalog: [], benutzer: {benutzername: "erik"},
    alleMails: false, onReload: async () => {},
  }));
  const mailWaehlen = betreff => view.root.findAllByType("button").find(button =>
    button.findAllByType("div").some(div => div.children.includes(betreff))).props.onClick();
  await act(async () => mailWaehlen("Ohne Beleg"));
  assert.equal(view.root.findAllByProps({role: "alert"}).length, 0);
  const fertig = view.root.findAllByType("button").find(button => button.children.includes("Erledigt"));
  await act(async () => fertig.props.onClick());
  assert.equal(bestaetigen.mock.callCount(), 1);
  assert.doesNotMatch(JSON.stringify(view.toJSON()), /Anhänge enthalten laut Auswertung keine Rechnung/);
  assert.match(JSON.stringify(view.toJSON()), /Dropbox nicht erreichbar/);
});

test("Ein Termin wird auch bei übersetzter Mail oberhalb des Originaltexts angezeigt", async t => {
  const {api, PosteingangView, mount} = await testEingang(t);
  api.mailHtml.mock.mockImplementation(async () => ({html: "<p>Meeting invitation</p>", kalendertermine: [{
    beginn: "2026-12-02T10:00:00+00:00", ende: "2026-12-02T10:30:00+00:00",
    ganztag: false, zeitzone: null, abgesagt: false,
  }]}));
  const view = await mount(React.createElement(PosteingangView, {
    mails: [{...mail(3, "Einladung", "03"), uebersetzung: "Einladung auf Deutsch", originalsprache: "Englisch"}],
    katalog: [], benutzer: {benutzername: "erik"}, alleMails: false, onReload: async () => {},
  }));
  const anzeige = JSON.stringify(view.toJSON());
  assert.match(anzeige, /Kalendertermin.*2\. Dezember 2026.*11:00.*11:30/);
  assert.doesNotMatch(JSON.stringify(view.root.findByType("details").findAllByType("div").map(el => el.children.join(" "))), /Kalendertermin/);
});

test("Erledigen am Listenende öffnet direkt die nächstälteste Mail", async t => {
  const {api, PosteingangView, mount} = await testEingang(t);
  const laden = api.mailHtml;
  const erledigen = t.mock.method(api, "mailErledigen", async () => ({status: "erledigt"}));
  const aelteste = mail(1, "Älteste Mail", "01");
  const mittlere = mail(2, "Nächste Mail", "01");
  const neueste = mail(3, "Neueste Mail", "03");
  const eingang = mails => React.createElement(PosteingangView, {
    mails, katalog: [], benutzer: {benutzername: "erik"}, alleMails: false,
    onReload: async () => view.update(eingang([mittlere, neueste])),
  });
  const view = await mount(eingang([aelteste, mittlere, neueste]));
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


test("Nach einem 502 wird die Reservierung derselben offenen Mail erneut versucht", async t => {
  const {api, PosteingangView, mount} = await testEingang(t, {fensterAktiv: true});
  const zeitgeber = new Map();
  let nummer = 0;
  Object.assign(window, {
    setTimeout(fn) { zeitgeber.set(++nummer, fn); return nummer; },
    clearTimeout(id) { zeitgeber.delete(id); },
    setInterval: t.mock.fn(),
    clearInterval: t.mock.fn(),
  });
  t.mock.method(api, "mailReservierungFreigeben", async () => ({}));
  let versuch = 0;
  const reservieren = t.mock.method(api, "mailReservieren", async () => {
    if (versuch++ === 0) throw Object.assign(new Error("Proxy nicht erreichbar"), {status: 502});
    return {eigene: true, benutzername: "erik"};
  });
  const view = await mount(React.createElement(PosteingangView, {
    mails: [mail(17, "Bleibt offen", "01")], katalog: [], benutzer: {benutzername: "erik"},
    alleMails: false, onReload: async () => {},
  }));
  async function timerAusloesen() {
    assert.equal(zeitgeber.size, 1);
    const [[id, fn]] = zeitgeber;
    zeitgeber.delete(id);
    await act(async () => fn());
  }
  await timerAusloesen();
  assert.equal(view.root.findAllByProps({role: "alert"}).length, 0);
  await timerAusloesen();
  assert.deepEqual(reservieren.mock.calls.map(call => call.arguments), [[17], [17]]);
  assert.equal(view.root.findByType("h2").children[0], "Bleibt offen");
  assert.equal(view.root.findAllByProps({role: "alert"}).length, 0);
  assert.equal(zeitgeber.size, 0);
  assert.equal(window.setInterval.mock.callCount(), 1);
});


test("Wieder geöffneter Entwurf zeigt gespeicherte Prüffassung und bewusstes Trotzdem senden", async t => {
  const {api, EntwurfPanel, mount} = await testEingang(t);
  const freigeben = t.mock.method(api, "entwurfFreigeben", async () => ({
    status: "versendet", empfaenger: "test@example.test",
  }));
  const view = await mount(React.createElement(EntwurfPanel, {
    entwurf: {id: 426, text: "Gespeicherte Überarbeitung", pruefprobleme: ["Offener Punkt"], naechsterOhnePruefung: true},
    kiPruefung: true, originalsprache: "Deutsch", onVersendet() {}, onGeprueft() {}, async onErledigt() {},
  }));
  assert.equal(view.root.findByType("textarea").props.value, "Gespeicherte Überarbeitung");
  assert.match(JSON.stringify(view.toJSON()), /Offener Punkt/);
  assert.equal(freigeben.mock.callCount(), 0);
  const senden = view.root.findAllByType("button").find(button => button.children.includes("Trotzdem senden"));
  await act(async () => senden.props.onClick());
  assert.deepEqual(freigeben.mock.calls[0].arguments, [426, "Gespeicherte Überarbeitung", [], true]);
});


test("Mailanhang lädt die Datei mit ihrem Namen herunter und meldet Abruffehler", async t => {
  const {mount, PosteingangView} = await testEingang(t);
  const listenname = "Auswertung.xlsx";
  const dateiname = "Auswertung für November.xlsx";
  const bytes = new Uint8Array([80, 75, 3, 4, 42]);
  let headers = {"Content-Disposition": `attachment; filename*=UTF-8''${encodeURIComponent(dateiname)}`};
  let fehlt = false;
  const abruf = t.mock.method(globalThis, "fetch", async () => fehlt
    ? Response.json({detail: "Anhang nicht mehr vorhanden."}, {status: 404})
    : new Response(bytes, {headers}));
  const downloads = [];
  const anlegen = t.mock.method(URL, "createObjectURL", () => "blob:mailanhang");
  window.setTimeout = () => {};
  document.body = {append() {}};
  document.createElement = tag => {
    assert.equal(tag, "a");
    return {click() { downloads.push({adresse: this.href, name: this.download}); }, remove() {}};
  };
  const view = await mount(React.createElement(PosteingangView, {
    mails: [{...mail(17, "Mit Anhang", "01"), anhaenge: [listenname]}], katalog: [],
    benutzer: {benutzername: "erik"}, alleMails: false, onReload: async () => {},
  }));
  const knopf = view.root.findByProps({title: `${listenname} herunterladen`});
  await act(async () => knopf.props.onClick());
  assert.equal(abruf.mock.calls[0].arguments[0], "/api/mails/17/anhaenge/0");
  assert.deepEqual(downloads, [{adresse: "blob:mailanhang", name: dateiname}]);
  assert.deepEqual(new Uint8Array(await anlegen.mock.calls[0].arguments[0].arrayBuffer()), bytes);

  headers = {};
  await act(async () => knopf.props.onClick());
  assert.equal(downloads[1].name, listenname);

  fehlt = true;
  await act(async () => knopf.props.onClick());
  assert.equal(downloads.length, 2);
  assert.match(JSON.stringify(view.toJSON()), /Anhang nicht mehr vorhanden/);
});
