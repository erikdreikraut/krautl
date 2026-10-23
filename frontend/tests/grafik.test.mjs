import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { act, create } from "react-test-renderer";
import { createServer } from "vite";

test("Grafik lädt nur Wissen und FAQ, zeigt zwei Bereiche und erlaubt Bearbeitung", async t => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: "custom" });
  t.after(() => server.close());
  const { GrafikAnwendung } = await server.ssrLoadModule("/src/GrafikAnwendung.jsx");
  const originalFetch = globalThis.fetch;
  const originalRaf = globalThis.requestAnimationFrame;
  const originalCancelRaf = globalThis.cancelAnimationFrame;
  globalThis.requestAnimationFrame = () => 1;
  globalThis.cancelAnimationFrame = () => {};
  const requests = [];
  globalThis.fetch = async url => {
    requests.push(url);
    assert.ok(["/api/wissensbasis", "/api/faq", "/api/bilder"].includes(url), `Unerlaubter Abruf: ${url}`);
    return { ok: true, json: async () => url.endsWith("wissensbasis") ? { produkte: [], familien: [], eintraege: [] } : url.endsWith("bilder") ? { artikel: [], status: "unbekannt" } : [] };
  };
  t.after(() => { globalThis.fetch = originalFetch; globalThis.requestAnimationFrame = originalRaf; globalThis.cancelAnimationFrame = originalCancelRaf; });
  let view;
  t.after(() => { act(() => view?.unmount()); });
  await act(async () => { view = create(React.createElement(GrafikAnwendung, { benutzer: { name: "Micha Durst", rolle: "grafik" }, onAbmelden: () => {} })); });
  assert.deepEqual(requests.sort(), ["/api/faq", "/api/wissensbasis"]);
  const nav = view.root.findByProps({ "aria-label": "Hauptnavigation" });
  assert.equal(nav.findAllByType("button").length, 2);
  assert.doesNotMatch(JSON.stringify(view.toJSON()), /Vorschläge|Inkasso|Mailabruf|Entwürfe|Einstellungen/);
  assert.match(JSON.stringify(view.toJSON()), /Produkt anlegen/);
  const add = view.root.findAllByType("button").find(b => b.children.includes("Wissenseintrag"));
  await act(async () => add.props.onClick());
  assert.match(JSON.stringify(view.toJSON()), /Speichern/);
  await act(async () => nav.findAllByType("button")[1].props.onClick());
  assert.match(JSON.stringify(view.toJSON()), /Shop-Artikel und ihre Bilder erstmals/);
});
