import assert from "node:assert/strict";
import { test } from "node:test";
import {
  buildAdeClaimsNewArgv,
  deriveClaimId,
  parseWorktreePayload,
  resolveAdeClaimsScript,
} from "./claim-lib.mjs";

const FIXTURE = {
  path: "/home/me/src/djbclark-ade.cursor-feature-wt",
  branch: "cursor/feature-x",
  sourceCheckout: "/home/me/src/djbclark-ade",
};

test("parseWorktreePayload accepts Paseo docs shape", () => {
  assert.deepEqual(parseWorktreePayload(FIXTURE), FIXTURE);
});

test("parseWorktreePayload rejects missing branch", () => {
  assert.throws(
    () => parseWorktreePayload({ path: "/x", sourceCheckout: "/y" }),
    /worktree\.branch/,
  );
});

test("deriveClaimId sanitizes branch and path basename and appends unique suffix", () => {
  const id = deriveClaimId(FIXTURE, { randomHex: () => "a1b2c3d4" });
  assert.equal(id, "wt-cursor-feature-x-djbclark-ade.cursor-feature-wt-a1b2c3d4");
  const a = deriveClaimId(FIXTURE);
  const b = deriveClaimId(FIXTURE);
  assert.notEqual(a, b);
});

test("buildAdeClaimsNewArgv maps hook fields to ade_claims.py new", () => {
  const built = buildAdeClaimsNewArgv(FIXTURE, {
    adeClaimsScript: "/opt/ade/bin/ade_claims.py",
    baseSha: "deadbeef",
    repoOrigin: "git@github.com:djbclark/djbclark-ade.git",
    ttlHours: 72,
    ownerRecord: "rec-1",
  });
  assert.equal(built.python, "python3");
  assert.equal(built.script, "/opt/ade/bin/ade_claims.py");
  assert.equal(built.argv[0], "new");
  assert.equal(built.argv[1], "--id");
  assert.match(built.argv[2], /^wt-cursor-feature-x-djbclark-ade\.cursor-feature-wt-[0-9a-f]{8}$/);
  assert.deepEqual(built.argv.slice(3), [
    "--path", FIXTURE.path,
    "--branch", FIXTURE.branch,
    "--base-sha", "deadbeef",
    "--created-by", "paseo-ade-claim-plugin",
    "--repo-origin", "git@github.com:djbclark/djbclark-ade.git",
    "--owner-record", "rec-1",
    "--ttl", "72",
  ]);
});

test("resolveAdeClaimsScript prefers ADE_CLAIMS_PY when readable", () => {
  // ADE_CLAIMS_PY must point at an existing readable path in this environment.
  const self = new URL(import.meta.url).pathname;
  assert.equal(
    resolveAdeClaimsScript(FIXTURE, { ADE_CLAIMS_PY: self }),
    self,
  );
});

test("resolveAdeClaimsScript refuses checkout-local helpers", () => {
  assert.throws(
    () => resolveAdeClaimsScript(FIXTURE, {}, {}),
    /ADE_CLAIMS_PY|checkout-local/,
  );
});

test("resolveAdeClaimsScript walks pluginRoot for bin/ade_claims.py", () => {
  // This repo layout: plugins/ade-claim/server → … → bin/ade_claims.py
  const pluginRoot = new URL("..", import.meta.url).pathname;
  const script = resolveAdeClaimsScript(FIXTURE, {}, { pluginRoot });
  assert.match(script, /\/bin\/ade_claims\.py$/);
});
