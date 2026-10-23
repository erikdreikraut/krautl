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
    if (url === "/api/bilder/exportvorschau") {
      assert.equal(options.method, "POST");
      assert.equal(options.body, '{"format":"test"}');
      return {ok:true,json:async()=>({sku:"20810",importiert:1})};
    }
    if (options.method === "PUT") {
      const body = JSON.parse(options.body);
      const a = data.find(a=>url.includes(`/${a.id}/`));
      assert.equal(body.revision, a.revision);
      a.ausgeblendet = body.ausgeblendet; a.revision++;
      return {ok:true, json:async()=>({status:"gespeichert"})};
    }
    assert.equal(url, "/api/bilder");
    return {ok:true, json:async()=>({artikel:structuredClone(data), status:"ok", teilstand:true, letzter_erfolg:"2026-10-23T11:00:00Z"})};
  };
  t.after(()=> { globalThis.fetch = originalFetch; });
  let view;
  await act(async () => { view = create(React.createElement(BilderView), {createNodeMock: e=>e.type==="dialog" ? {showModal(){}}:null}); });
  t.after(()=>act(()=>view.unmount()));
  assert.match(JSON.stringify(view.toJSON()), /Abgleich noch unvollständig/);
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
  await act(async()=>view.root.findByProps({"aria-label":"Shop-Vorschaudatei importieren"}).props.onChange({
    target:{files:[{size:17,text:async()=>'{"format":"test"}'}],value:""}
  }));
  assert.match(JSON.stringify(view.toJSON()),/fehlende Vorschauen ergänzt/);

});

test("Fehlendes Bild bleibt als Platzhalter mit Position sichtbar und wird nach Reparatur ersetzt", async t => {
  const server = await createServer({server:{middlewareMode:true, hmr:false}, appType:"custom"});
  t.after(() => server.close());
  const { BilderListe } = await server.ssrLoadModule("/src/BilderView.jsx");
  const artikel = [{...rows[0], bilder:[
    {id:"bad", thumb:null, position:5, fehler:"Wawi-Bildabruf: HTTP 400."},
    {id:"good", thumb:"abc", position:6}
  ]}];
  let view;
  await act(async()=>{view=create(React.createElement(BilderListe,{artikel}));});
  t.after(()=>act(()=>view.unmount()));
  assert.equal(view.root.findAllByType("img").length,1);
  assert.match(view.root.findByProps({role:"img"}).props["aria-label"], /Bildposition 5.*HTTP 400/);
  artikel[0].bilder[0]={id:"bad",thumb:"repaired",position:5,fehler:"HTTP 400",quelle:"ameise"};
  await act(async()=>view.update(React.createElement(BilderListe,{artikel})));
  assert.equal(view.root.findAllByType("img").length,2);
  assert.equal(view.root.findAllByProps({role:"img"}).length,0);
  assert.match(JSON.stringify(view.toJSON()),/Exportvorschau/);
});

test("Ein Status trennt Artikelabbruch und Bildfehler; Filter erhält Ausblendungen", async t => {
  const server = await createServer({server:{middlewareMode:true, hmr:false}, appType:"custom"});
  t.after(()=>server.close());
  const {BilderStatus, gruppieren} = await server.ssrLoadModule("/src/BilderView.jsx");
  const artikel = structuredClone(rows);
  artikel[0].bilder=[{id:"bad",thumb:null,fehler:"HTTP 400",position:5}];
  artikel[2].bilder=[{id:"hidden-bad",thumb:null,fehler:"HTTP 404",position:1}];
  let view;
  await act(async()=>{view=create(React.createElement(BilderStatus,{daten:{
    artikel,teilstand:true,status:"fehler",fehler:"Artikel 20562-50 (Details): Direkte JTL-API: HTTP 500."
  }}));});
  t.after(()=>act(()=>view.unmount()));
  const text=JSON.stringify(view.toJSON());
  assert.equal(view.root.findAllByProps({role:"alert"}).length,1);
  assert.match(text,/Abgleich abgebrochen/);
  assert.match(text,/20562-50/);
  assert.match(text,/Ursache ist noch ungeklärt/);
  assert.equal(view.root.findAllByType("details").length,1);
  assert.deepEqual(gruppieren(artikel,false,"",true).flatMap(g=>g.artikel.map(a=>a.id)),["parent"]);
  assert.equal(gruppieren(artikel,true,"",true).flatMap(g=>g.artikel).length,2);
});

test("Übersprungene Artikel werden getrennt mit unbekanntem Bildbestand aufgeführt", async t => {
  const server=await createServer({server:{middlewareMode:true,hmr:false},appType:"custom"});
  t.after(()=>server.close());
  const {BilderStatus}=await server.ssrLoadModule("/src/BilderView.jsx");
  let view;
  await act(async()=>{view=create(React.createElement(BilderStatus,{daten:{
    artikel:[],status:"warnung",teilstand:true,lauf_beendet_am:"2026-10-23T12:00:00Z",
    ungeprueft:[{id:"x",sku:"20562-50",name:"Ungeprüfter Artikel",vorhanden:false,fehler:"HTTP 500"}]
  }}));});
  t.after(()=>act(()=>view.unmount()));
  const text=JSON.stringify(view.toJSON());
  assert.match(text,/Durchlauf beendet – Artikel ungeprüft/);
  assert.match(text,/20562-50/);
  assert.match(text,/Bildbestand noch unbekannt/);
  assert.doesNotMatch(text,/Keine Shop-Bilder zugeordnet/);
  assert.equal(view.root.findAllByProps({role:"alert"}).length,0);
});
