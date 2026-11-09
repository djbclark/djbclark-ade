import assert from "node:assert/strict";
import { test } from "node:test";
import {
  activeClaimForPath,
  buildAdeClaimsBindOwnerArgv,
  buildAdeClaimsNewArgv,
  buildAdeClaimsReleaseArgv,
  buildAdeGitGuardInstallArgv,
  claimAllowsAgent,
  deriveClaimId,
  mergeAdeClaimIdEnv,
  mergeAgentBinPath,
  mergeOpenBeforeEnv,
  parseAgentCreateAfterAgent,
  parseAgentOpenBeforeRequest,
  parseClaimPointer,
  parseWorkspaceArchivePayload,
  parseWorktreePayload,
  resolveAdeClaimsScript,
  resolveClaimForCwd,
  resolveTrustedAdeClaimsScript,
  resolveTrustedAdeGitGuard,
  resolveTrustedAgentBinDir,
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

test("parseWorkspaceArchivePayload accepts Paseo docs shape", () => {
  assert.deepEqual(
    parseWorkspaceArchivePayload({ id: "ws-1", cwd: FIXTURE.path, name: "feature" }),
    { id: "ws-1", cwd: FIXTURE.path },
  );
});

test("parseWorkspaceArchivePayload rejects missing cwd", () => {
  assert.throws(
    () => parseWorkspaceArchivePayload({ id: "ws-1" }),
    /workspace\.cwd/,
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

test("buildAdeClaimsReleaseArgv maps release id", () => {
  assert.deepEqual(
    buildAdeClaimsReleaseArgv({
      adeClaimsScript: "/opt/ade/bin/ade_claims.py",
      claimId: "wt-claim-1",
    }),
    {
      python: "python3",
      script: "/opt/ade/bin/ade_claims.py",
      argv: ["release", "--id", "wt-claim-1"],
    },
  );
});

test("buildAdeGitGuardInstallArgv maps install path", () => {
  assert.deepEqual(
    buildAdeGitGuardInstallArgv({
      adeGitGuard: "/opt/ade/bin/ade-git-guard",
      worktreePath: FIXTURE.path,
    }),
    {
      guard: "/opt/ade/bin/ade-git-guard",
      argv: ["install", FIXTURE.path],
    },
  );
});

test("resolveClaimForCwd validates pointer against registry", () => {
  const claims = [
    { id: "stale", path: FIXTURE.path, shown_state: "released" },
    { id: "wt-claim-1", path: FIXTURE.path, shown_state: "active" },
    { id: "other-ws", path: "/elsewhere", shown_state: "active" },
  ];
  assert.equal(resolveClaimForCwd(claims, FIXTURE.path, "stale")?.id, "wt-claim-1");
  assert.equal(resolveClaimForCwd(claims, FIXTURE.path, "other-ws")?.id, "wt-claim-1");
  assert.equal(resolveClaimForCwd(claims, FIXTURE.path, "wt-claim-1")?.id, "wt-claim-1");
});

test("claimAllowsAgent only for unbound or matching owner", () => {
  assert.equal(claimAllowsAgent({ owner: {} }, "agent-a"), true);
  assert.equal(claimAllowsAgent({ owner: { agent: "agent-a" } }, "agent-a"), true);
  assert.equal(claimAllowsAgent({ owner: { agent: "agent-a" } }, "agent-b"), false);
  assert.equal(claimAllowsAgent({ owner: { record: "agent-b" } }, "agent-b"), true);
});

test("mergeAgentBinPath prepends and dedupes", () => {
  assert.deepEqual(
    mergeAgentBinPath({ PATH: "/usr/bin:/opt/ade/libexec/agent-bin" }, "/opt/ade/libexec/agent-bin"),
    { PATH: "/opt/ade/libexec/agent-bin:/usr/bin" },
  );
  assert.equal(
    mergeAgentBinPath({ PATH: "/opt/ade/libexec/agent-bin:/usr/bin" }, "/opt/ade/libexec/agent-bin"),
    undefined,
  );
  assert.deepEqual(
    mergeAgentBinPath({}, "/opt/ade/libexec/agent-bin", { fallbackPath: "/usr/bin" }),
    { PATH: "/opt/ade/libexec/agent-bin:/usr/bin" },
  );
});

test("mergeOpenBeforeEnv combines claim id and agent-bin PATH", () => {
  assert.deepEqual(
    mergeOpenBeforeEnv({ FOO: "1" }, {
      claimId: "wt-claim-1",
      agentBinDir: "/opt/ade/libexec/agent-bin",
      fallbackPath: "/usr/bin",
    }),
    {
      FOO: "1",
      ADE_CLAIM_ID: "wt-claim-1",
      PATH: "/opt/ade/libexec/agent-bin:/usr/bin",
    },
  );
  assert.equal(
    mergeOpenBeforeEnv({
      ADE_CLAIM_ID: "wt-claim-1",
      PATH: "/opt/ade/libexec/agent-bin:/usr/bin",
    }, {
      claimId: "wt-claim-1",
      agentBinDir: "/opt/ade/libexec/agent-bin",
    }),
    undefined,
  );
});

test("resolveTrustedAgentBinDir walks pluginRoot for libexec/agent-bin", () => {
  const pluginRoot = new URL("..", import.meta.url).pathname;
  const dir = resolveTrustedAgentBinDir({}, { pluginRoot });
  assert.match(dir, /\/libexec\/agent-bin$/);
});

test("resolveTrustedAdeGitGuard walks pluginRoot for bin/ade-git-guard", () => {
  const pluginRoot = new URL("..", import.meta.url).pathname;
  const guard = resolveTrustedAdeGitGuard({}, { pluginRoot });
  assert.match(guard, /\/bin\/ade-git-guard$/);
});
