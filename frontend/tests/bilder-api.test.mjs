import assert from "node:assert/strict";
import { test } from "node:test";
import { api } from "../src/api.js";

test("Bilddatei wird für Austausch und Hinzufügen mit stabiler Auftrags-ID gesendet", async t => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    calls.push({url: new URL(url, "https://krautl.test"), options});
    if (calls.length === 1) throw new Error("Verbindung verloren");
    return new Response(JSON.stringify({id: "job", status: "wawi"}), {status: 200});
  };
  t.after(() => { globalThis.fetch = originalFetch; });
  const file = new Blob(["image content"], {type: "image/png"});
  await assert.rejects(api.bilderDatei("article", "old-image", 3, "replace-id", file), /Verbindung verloren/);
  assert.equal((await api.bilderDatei("article", "old-image", 3, "replace-id", file)).status, "wawi");
  assert.equal((await api.bilderDatei("article", null, 3, "add-id", file)).status, "wawi");
  assert.equal(calls.length, 3);
  for (const {url, options} of calls) {
    assert.equal(url.pathname, "/api/bilder/article/datei");
    assert.equal(url.searchParams.get("revision"), "3");
    assert.equal(options.method, "POST");
    assert.equal(options.headers["Content-Type"], "application/octet-stream");
    assert.equal(options.body, file);
  }
  assert.equal(calls[0].url.search, calls[1].url.search);
  assert.equal(calls[1].url.searchParams.get("anfrage_id"), "replace-id");
  assert.equal(calls[1].url.searchParams.get("bild_id"), "old-image");
  assert.equal(calls[2].url.searchParams.get("anfrage_id"), "add-id");
  assert.equal(calls[2].url.searchParams.has("bild_id"), false);
});
