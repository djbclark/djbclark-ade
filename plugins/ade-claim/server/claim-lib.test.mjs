import assert from "node:assert/strict";
import { test } from "node:test";
import {
  activeClaimForPath,
  buildAdeClaimsBindOwnerArgv,
  buildAdeClaimsNewArgv,
  deriveClaimId,
  mergeAdeClaimIdEnv,
  parseAgentCreateAfterAgent,
  parseAgentOpenBeforeRequest,
  parseClaimPointer,
  parseWorktreePayload,
  resolveAdeClaimsScript,
  resolveTrustedAdeClaimsScript,
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

test("resolveTrustedAdeClaimsScript does not need a worktree payload", () => {
  const pluginRoot = new URL("..", import.meta.url).pathname;
  const script = resolveTrustedAdeClaimsScript({}, { pluginRoot });
  assert.match(script, /\/bin\/ade_claims\.py$/);
});

test("parseAgentOpenBeforeRequest accepts Paseo docs shape", () => {
  assert.deepEqual(
    parseAgentOpenBeforeRequest({
      agentId: "agent-123",
      cwd: FIXTURE.path,
      env: { COMPANY_ENV: "development" },
    }),
    {
      agentId: "agent-123",
      cwd: FIXTURE.path,
      env: { COMPANY_ENV: "development" },
    },
  );
});

test("parseAgentOpenBeforeRequest rejects missing cwd", () => {
  assert.throws(
    () => parseAgentOpenBeforeRequest({ agentId: "a" }),
    /request\.cwd/,
  );
});

test("parseAgentCreateAfterAgent accepts agent id and cwd", () => {
  assert.deepEqual(
    parseAgentCreateAfterAgent({ id: "agent-9", cwd: FIXTURE.path, title: null }),
    { id: "agent-9", cwd: FIXTURE.path },
  );
});

test("activeClaimForPath matches active claim by trimmed path", () => {
  const claims = [
    { id: "other", path: "/elsewhere", shown_state: "active" },
    { id: "wt-claim-1", path: `${FIXTURE.path}/`, shown_state: "active" },
    { id: "released", path: FIXTURE.path, shown_state: "released" },
  ];
  assert.equal(activeClaimForPath(claims, FIXTURE.path)?.id, "wt-claim-1");
  assert.equal(activeClaimForPath(claims, "/no/such"), null);
});

test("parseClaimPointer trims and validates", () => {
  assert.equal(parseClaimPointer("  wt-claim-1\n"), "wt-claim-1");
  assert.equal(parseClaimPointer("   "), null);
  assert.throws(() => parseClaimPointer("bad id!"), /valid claim id/);
});

test("mergeAdeClaimIdEnv adds ADE_CLAIM_ID or no-ops when already set", () => {
  assert.deepEqual(
    mergeAdeClaimIdEnv({ FOO: "1" }, "wt-claim-1"),
    { FOO: "1", ADE_CLAIM_ID: "wt-claim-1" },
  );
  assert.equal(mergeAdeClaimIdEnv({ ADE_CLAIM_ID: "wt-claim-1" }, "wt-claim-1"), undefined);
  assert.equal(mergeAdeClaimIdEnv({}, null), undefined);
});

test("buildAdeClaimsBindOwnerArgv maps owner bind fields", () => {
  const built = buildAdeClaimsBindOwnerArgv({
    adeClaimsScript: "/opt/ade/bin/ade_claims.py",
    claimId: "wt-claim-1",
    ownerAgent: "agent-123",
    ownerRecord: "agent-123",
  });
  assert.deepEqual(built, {
    python: "python3",
    script: "/opt/ade/bin/ade_claims.py",
    argv: [
      "bind-owner",
      "--id", "wt-claim-1",
      "--owner-agent", "agent-123",
      "--owner-record", "agent-123",
    ],
  });
});
