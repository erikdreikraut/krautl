import test from "node:test";
import assert from "node:assert/strict";
import { pruefhinweise } from "../src/pruefhinweise.js";
const issues = [
  {typ: "sprachfehler", beschreibung: "Tippfehler: Versandkosten statt Versankosten."},
  {typ: "kernfrage_unbeantwortet", beschreibung: "Offene Frage: Ist die Menge bestellbar?"},
];
test("objects, JSON strings and nested JSON become separate descriptions", () => {
  for (const input of [issues, JSON.stringify(issues), [JSON.stringify(issues)], {probleme: issues}]) {
    assert.deepEqual(pruefhinweise(input), issues.map(i => i.beschreibung));
  }
});
test("malformed quoted JSON keeps descriptions without technical keys", () => {
  assert.deepEqual(pruefhinweise('[{"typ":"sprachfehler","beschreibung":"Tippfehler: "Versankosten" korrigieren."},{"typ":"sprachfehler","beschreibung":"Name korrigieren."}]'),
    ['Tippfehler: "Versankosten" korrigieren.', "Name korrigieren."]);
});
test("ordinary text and meaningful brackets remain intact", () => {
  assert.deepEqual(pruefhinweise("- Tippfehler korrigieren.\n- Platzhalter [Name] entfernen."),
    ["Tippfehler korrigieren.", "Platzhalter [Name] entfernen."]);
});
test("unknown objects are not rendered as raw JSON or silently hidden", () => {
  assert.equal(pruefhinweise({typ: "internal"}).length, 1);
  assert.ok(!pruefhinweise({typ: "internal"})[0].includes("internal"));
});
