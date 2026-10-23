import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { act, create } from "react-test-renderer";
import { createServer } from "vite";

const rows = [
  { id: "parent", name: "Kräuter", sku: "10", parent_id: null, bilder: [], revision: 0, ausgeblendet: false },
  { id: "child", name: "Kräuter 100 g", sku: "20", parent_id: "parent", bilder: [{id:"img", thumb:"abc", dateiname:"bild.jpg"}], revision: 0, ausgeblendet: false },
  { id: "hidden", name: "Ausgeblendet", sku: "30", parent_id: null, bilder: [], revision: 1, ausgeblendet: true },
  { id: "other", name: "Andere", sku: "100", parent_id: null, bilder: [], revision: 0, ausgeblendet: false },
];

test("Bilder gruppiert echte Vater/Kinder und filtert ausgeblendete Artikel und Suche", async t => {
  const server = await createServer({server:{middlewareMode:true, hmr:false}, appType:"custom"});
  t.after(() => server.close());
  const { gruppieren, BilderListe } = await server.ssrLoadModule("/src/BilderView.jsx");
  const groups = gruppieren(rows);
  assert.deepEqual(groups.map(g => g.artikel.map(a => a.id)), [["other"], ["parent", "child"]]);
  assert.equal(gruppieren(rows, true).length, 3);
  assert.deepEqual(gruppieren(rows, false, "20")[0].artikel.map(a=>a.id), ["child"]);
  let selected;
  let view;
  await act(async () => { view = create(React.createElement(BilderListe, {artikel:rows, onArtikel:id=>selected=id})); });
  t.after(() => act(() => view.unmount()));
  assert.equal(view.root.findAllByType("img").length, 1);
  assert.equal(view.root.findByType("img").props.loading, "lazy");
  const child = view.root.findAllByType("button").find(b=>b.children.includes("Kräuter 100 g"));
  await act(async()=>child.props.onClick());
  assert.equal(selected, "child");
});

test("Bilder-Popup speichert Ausblenden mit Revision; Filter erlaubt erneutes Einblenden", async t => {
  const server = await createServer({server:{middlewareMode:true, hmr:false}, appType:"custom"});
  t.after(() => server.close());
  const { BilderView } = await server.ssrLoadModule("/src/BilderView.jsx");
  const originalFetch = globalThis.fetch;
  const data = structuredClone(rows);
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push([url, options]);
    if (options.method === "PUT") {
      const body = JSON.parse(options.body);
      const a = data.find(a=>url.includes(`/${a.id}/`));
      assert.equal(body.revision, a.revision);
      a.ausgeblendet = body.ausgeblendet; a.revision++;
      return {ok:true, json:async()=>({status:"gespeichert"})};
    }
    assert.equal(url, "/api/bilder");
    return {ok:true, json:async()=>({artikel:structuredClone(data), status:"ok", letzter_erfolg:"2026-10-23T11:00:00Z"})};
  };
  t.after(()=> { globalThis.fetch = originalFetch; });
  let view;
  await act(async () => { view = create(React.createElement(BilderView), {createNodeMock: e=>e.type==="dialog" ? {showModal(){}}:null}); });
  t.after(()=>act(()=>view.unmount()));
  const button = name => view.root.findAllByType("button").find(b=>b.children.includes(name));
  assert.equal(calls.filter(([,o])=>o.method==="POST").length, 0);
  await act(async()=>button("Kräuter").props.onClick());
  await act(async()=>view.root.findByType("dialog").findByType("input").props.onChange({target:{checked:true}}));
  assert.equal(button("Kräuter"), undefined);
  await act(async()=>view.root.findAllByType("input").find(i=>i.props.type==="checkbox").props.onChange({target:{checked:true}}));
  assert.ok(button("Kräuter"));
  await act(async()=>button("Kräuter").props.onClick());
  await act(async()=>view.root.findByType("dialog").findByType("input").props.onChange({target:{checked:false}}));
  assert.equal(data[0].ausgeblendet, false);
  assert.equal(data[0].revision, 2);
  assert.equal(calls.filter(([,o])=>o.method==="PUT").length, 2);
});
