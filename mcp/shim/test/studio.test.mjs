// Every STUDIO_GENERATE request the NotebookLM web app sent during the
// 2026-10-22 capture, rebuilt from the options that were chosen in its dialog.
// Run: node --test mcp/shim/test/
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { buildParams } from "../studio.js";

const cases = JSON.parse(fs.readFileSync(new URL("./recorded-studio-requests.json", import.meta.url)));

for (const c of cases) {
  test(`matches the web app: ${c.label}`, () => {
    assert.deepEqual(buildParams("NOTEBOOK_ID", ["SOURCE_ID"], c.kind, c.focus, c.options), c.expected);
  });
}

test("rejects a length NotebookLM doesn't offer for the format", () => {
  assert.throws(() => buildParams("N", ["S"], "audio_overview", "", { format: "debate", length: "long", language: "en" }), /not offered/);
});

test("a custom report needs a description", () => {
  assert.throws(() => buildParams("N", ["S"], "report", "", { format: "document", template: "custom", language: "en" }), /needs a description/);
});
