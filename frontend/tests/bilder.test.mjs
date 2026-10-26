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

test("Sammelimport sendet artikelweise, berichtet Konflikte und stoppt bei Verbindungsfehlern", async t => {
  const server=await createServer({server:{middlewareMode:true,hmr:false},appType:"custom"});
  t.after(()=>server.close());
  const {importiereVorschaudatei}=await server.ssrLoadModule("/src/BilderView.jsx");
  const item=sku=>({format:"krautl-shopvorschau-1",kanal:"2-2-1",sku,bilder:[]});
  const data={format:"krautl-shopvorschau-2",kanal:"2-2-1",artikel:["A","B","C"].map(item),ausgelassen:[{sku:"X",grund:"Datei fehlt"}]};
  const calls=[];
  const result=await importiereVorschaudatei(JSON.stringify(data),async body=>{
    const a=JSON.parse(body);calls.push(a.sku);
    if(a.sku==="B") throw Object.assign(new Error("Positionen passen nicht"),{status:409});
    return {importiert:2};
  });
  assert.deepEqual(calls,["A","B","C"]);
  assert.equal(result.importiert,4);
  assert.deepEqual(result.ausgelassen.map(a=>a.sku),["X","B"]);
  const stopped=await importiereVorschaudatei(JSON.stringify(data),async()=>{throw new Error("Netzfehler");});
  assert.match(stopped.abbruch,/erneut importiert/);
  assert.equal(stopped.importiert,0);
  data.artikel.push(item("A"));
  let sent=false;
  await assert.rejects(()=>importiereVorschaudatei(JSON.stringify(data),async()=>{sent=true;}),/doppelte/);
  assert.equal(sent,false);
});


test("Shop-Kategorien folgen Shop-Reihenfolge, Familien bleiben trotz Suche zusammen", async t => {
  const server = await createServer({server:{middlewareMode:true,hmr:false},appType:"custom"});
  t.after(()=>server.close());
  const {gruppieren,nachKategorien,BilderListe} = await server.ssrLoadModule("/src/BilderView.jsx");
  const first = {id:"z",name:"Zubehör",sortierung:[1]};
  const second = {id:"a",name:"Arzneien",sortierung:[2]};
  const data = rows.map(a=>({...a,kategorien:a.id==="parent" ? [second,first] : a.id==="other" ? [second] : []}));
  const sections = nachKategorien(gruppieren(data));
  assert.deepEqual(sections.map(s=>s.kategorie.id),["z","a"]);
  assert.deepEqual(sections[0].gruppen[0].artikel.map(a=>a.id),["parent","child"]);
  assert.equal(nachKategorien(gruppieren(data,false,"20"))[0].kategorie.id,"z");
  let view;
  await act(async()=>{view=create(React.createElement(BilderListe,{artikel:data,onArtikel:()=>{}}));});
  t.after(()=>act(()=>view.unmount()));
  assert.deepEqual(view.root.findAllByType("h3").map(h=>h.children[0]),["Zubehör","Arzneien"]);
});


test("Bilddialog sendet erst nach Bestätigung und behält bei Netzfehler dieselbe Auftrags-ID", async t=>{
  const server=await createServer({server:{middlewareMode:true,hmr:false},appType:"custom"});
  t.after(()=>server.close());
  const {BildDialog}=await server.ssrLoadModule("/src/BildDialog.jsx");
  const {api}=await server.ssrLoadModule("/src/api.js");
  const oldSend=api.bilderDatei, oldGross=api.bilderGross;
  const oldCreate=URL.createObjectURL, oldRevoke=URL.revokeObjectURL;
  URL.createObjectURL=()=>"blob:test";URL.revokeObjectURL=()=>{};
  const calls=[];
  api.bilderGross=async()=>{throw new Error("400");};
  api.bilderDatei=async(...args)=>{calls.push(args);if(calls.length===1)throw new Error("Verbindung verloren");return {id:"job",status:"wawi",meldung:"In Wawi bestätigt"};};
  t.after(()=>{api.bilderDatei=oldSend;api.bilderGross=oldGross;URL.createObjectURL=oldCreate;URL.revokeObjectURL=oldRevoke;});
  let view;
  await act(async()=>{view=create(React.createElement(BildDialog,{artikel:rows[0],bild:{id:"old",thumb:"abc",position:1},aktualisiert:async()=>{},schliessen:()=>{}}),{createNodeMock:e=>e.type==="dialog"?{showModal(){}}:null});});
  t.after(()=>act(()=>view.unmount()));
  assert.match(JSON.stringify(view.toJSON()),/gespeicherte kleine Vorschau/);
  const file={name:"früchte.png",size:100};
  await act(async()=>view.root.findByType("input").props.onChange({target:{files:[file],value:"x"}}));
  assert.equal(calls.length,0);
  const confirm=()=>view.root.findAllByType("button").find(b=>b.children.includes("Bestätigen und an Wawi übertragen"));
  await act(async()=>confirm().props.onClick());
  await act(async()=>confirm().props.onClick());
  assert.equal(calls.length,2);
  assert.equal(calls[0][3],calls[1][3]);
  assert.equal(calls[0][1],"old");
  assert.equal(calls[0][4],file);
  assert.match(JSON.stringify(view.toJSON()),/In Wawi bestätigt/);
});

test("Bildliste öffnet Thumbnail und Plus; Wawi-Erfolg wird nicht als Shop-Erfolg markiert",async t=>{
  const server=await createServer({server:{middlewareMode:true,hmr:false},appType:"custom"});
  t.after(()=>server.close());
  const {BilderListe}=await server.ssrLoadModule("/src/BilderView.jsx");
  let chosen,view;
  await act(async()=>{view=create(React.createElement(BilderListe,{artikel:rows,onArtikel:()=>{},onBild:(a,b)=>chosen=[a,b],auftraege:[{artikel:"child",neu_id:"img",status:"wawi"}]}));});
  t.after(()=>act(()=>view.unmount()));
  const thumb=view.root.findByProps({"aria-label":"Bild 1 von 20 vergrößern"});
  await act(async()=>thumb.props.onClick());
  assert.equal(chosen[1].id,"img");
  await act(async()=>view.root.findByProps({"aria-label":"Bild zu 20 hinzufügen"}).props.onClick());
  assert.equal(chosen[1],null);
  assert.ok(view.root.findByProps({"aria-label":"In Wawi bestätigt; Shop-Veröffentlichung ungeprüft"}));
});


test("Drag-and-drop bleibt lokal bis Speichern, erstes Bild wird Hauptbild und Polling erhält Entwurf", async t=>{
  const server=await createServer({server:{middlewareMode:true,hmr:false},appType:"custom"});
  t.after(()=>server.close());
  const {BildReihe}=await server.ssrLoadModule("/src/BilderView.jsx");
  const {api}=await server.ssrLoadModule("/src/api.js");
  const old=api.bilderReihenfolge,calls=[];
  api.bilderReihenfolge=async(...args)=>{calls.push(args);return {status:"wawi",meldung:"In Wawi bestätigt"};};
  t.after(()=>{api.bilderReihenfolge=old;});
  const a={...rows[0],bilder:[{id:"a",position:1,hauptbild:true,thumb:"x"},{id:"b",position:2,hauptbild:false,thumb:"y"}]};
  let view;
  const render=a=>React.createElement(BildReihe,{a,onBild:()=>{},aktualisiert:async()=>{}});
  await act(async()=>{view=create(render(a));});t.after(()=>act(()=>view.unmount()));
  const slots=()=>view.root.findAll(n=>n.type==="div"&&n.props.draggable!==undefined);
  const transfer={setData(){}};
  await act(async()=>slots()[1].props.onDragStart({dataTransfer:transfer}));
  await act(async()=>slots()[0].props.onDrop({preventDefault(){}}));
  assert.equal(calls.length,0);
  await act(async()=>view.update(render(structuredClone(a))));
  assert.equal(view.root.findAllByType("img")[0].props.src.endsWith("/y"),true);
  assert.match(view.root.findAllByType("figcaption")[0].children.join(""),/1.*Hauptbild/);
  const save=()=>view.root.findAllByType("button").find(b=>b.children.includes("Reihenfolge speichern"));
  await act(async()=>save().props.onClick());
  assert.deepEqual(calls[0][1].reihenfolge,["b","a"]);
  assert.deepEqual(calls[0][1].vorher,a.bilder.map(({id,position,hauptbild})=>({id,position,hauptbild})));
  assert.equal(calls.length,1);
});

test("Geänderter Bildbestand sperrt Reihenfolgeentwurf statt ihn zu überschreiben",async t=>{
  const server=await createServer({server:{middlewareMode:true,hmr:false},appType:"custom"});t.after(()=>server.close());
  const {BildReihe}=await server.ssrLoadModule("/src/BilderView.jsx");
  const a={...rows[0],bilder:[{id:"a",position:1,hauptbild:true},{id:"b",position:2,hauptbild:false}]};
  let view;
  await act(async()=>{view=create(React.createElement(BildReihe,{a}));});t.after(()=>act(()=>view.unmount()));
  await act(async()=>view.root.findByProps({"aria-label":"Bild 2 verschieben: Pfeil links oder rechts"}).props.onKeyDown({key:"ArrowLeft",preventDefault(){}}));
  await act(async()=>view.update(React.createElement(BildReihe,{a:{...a,bilder:[...a.bilder,{id:"c",position:3,hauptbild:false}]}})));
  assert.equal(view.root.findAllByType("button").find(b=>b.children.includes("Reihenfolge speichern")).props.disabled,true);
  assert.match(JSON.stringify(view.toJSON()),/Bildbestand wurde geändert/);
});
