import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { PLUGIN_VERSION } from "./constants.ts";

test("PLUGIN_VERSION matches package.json", () => {
  const pkg = JSON.parse(fs.readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  assert.equal(PLUGIN_VERSION, pkg.version);
});
