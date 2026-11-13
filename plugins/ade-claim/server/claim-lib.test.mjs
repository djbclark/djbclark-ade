import assert from "node:assert/strict";
import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  statSync,
  symlinkSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import {
  registerAdeClaimHooks,
  registerAgentClaimEnvHook,
  registerAgentClaimOwnerHook,
  registerWorkspaceArchiveReleaseHook,
  registerWorktreeClaimHook,
} from "./hook.mjs";
import {
  CLAIM_MODE_FILE,
  CLAIM_OBSERVE_LOG,
  MODE_FILE_READ_CAP,
  appendObserveLog,
  buildObserveEntry,
  redactUrlUserinfo,
  resolveClaimMode,
  activeClaimForPath,
  buildAdeClaimsBindOwnerArgv,
  buildAdeClaimsNewArgv,
  buildAdeClaimsReleaseArgv,
  buildAdeGitGuardInstallArgv,
  claimAllowsAgent,
  DEFAULT_CLAIM_TTL_HOURS,
  deriveClaimId,
  isAdeClaimDryRun,
  mergeAdeClaimIdEnv,
  mergeAgentBinPath,
  mergeOpenBeforeEnv,
  parseAgentCreateAfterAgent,
  parseAgentOpenBeforeRequest,
  parseClaimPointer,
  parseWorkspaceArchivePayload,
  parseWorktreePayload,
  planWorktreeClaimCreate,
  resolveAdeClaimsScript,
  resolveClaimForCwd,
  resolveClaimTtlHours,
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

test("resolveClaimTtlHours defaults to 72 and reads ADE_CLAIM_TTL", () => {
  assert.equal(resolveClaimTtlHours({}), DEFAULT_CLAIM_TTL_HOURS);
  assert.equal(resolveClaimTtlHours({ ADE_CLAIM_TTL: "24" }), 24);
  assert.equal(resolveClaimTtlHours({ ADE_CLAIM_TTL: "0" }), 0);
  assert.throws(() => resolveClaimTtlHours({ ADE_CLAIM_TTL: "-1" }), /ADE_CLAIM_TTL/);
  assert.throws(() => resolveClaimTtlHours({ ADE_CLAIM_TTL: "nope" }), /ADE_CLAIM_TTL/);
});

test("isAdeClaimDryRun accepts 1/true/yes", () => {
  assert.equal(isAdeClaimDryRun({}), false);
  assert.equal(isAdeClaimDryRun({ ADE_CLAIM_DRY_RUN: "0" }), false);
  assert.equal(isAdeClaimDryRun({ ADE_CLAIM_DRY_RUN: "1" }), true);
  assert.equal(isAdeClaimDryRun({ ADE_CLAIM_DRY_RUN: "TRUE" }), true);
  assert.equal(isAdeClaimDryRun({ ADE_CLAIM_DRY_RUN: " yes " }), true);
});

test("planWorktreeClaimCreate always wires --ttl and marks dry-run", () => {
  const live = planWorktreeClaimCreate(FIXTURE, {
    adeClaimsScript: "/opt/ade/bin/ade_claims.py",
    baseSha: "deadbeef",
    env: {},
  });
  assert.equal(live.dryRun, false);
  assert.equal(live.ttlHours, 72);
  assert.ok(live.argv.includes("--ttl"));
  assert.equal(live.argv[live.argv.indexOf("--ttl") + 1], "72");

  const dry = planWorktreeClaimCreate(FIXTURE, {
    adeClaimsScript: "/opt/ade/bin/ade_claims.py",
    baseSha: "cafebabe",
    env: { ADE_CLAIM_DRY_RUN: "1", ADE_CLAIM_TTL: "12" },
  });
  assert.equal(dry.dryRun, true);
  assert.equal(dry.ttlHours, 12);
  assert.equal(dry.argv[dry.argv.indexOf("--ttl") + 1], "12");
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

test("mergeAdeClaimIdEnv clears foreign ADE_CLAIM_ID when claimId is null", () => {
  assert.deepEqual(
    mergeAdeClaimIdEnv({ FOO: "1", ADE_CLAIM_ID: "foreign-claim" }, null),
    { FOO: "1" },
  );
  assert.deepEqual(
    mergeOpenBeforeEnv({ ADE_CLAIM_ID: "foreign-claim", PATH: "/usr/bin" }, {
      claimId: null,
      agentBinDir: "/opt/ade/libexec/agent-bin",
    }),
    { PATH: "/opt/ade/libexec/agent-bin:/usr/bin" },
  );
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

// ---------------------------------------------------------------------------
// Observe mode (#638 D1): one predicate, every hook, switchable per call.
// ---------------------------------------------------------------------------

function tmp(prefix = "ade-claim-obs-") {
  return mkdtempSync(join(tmpdir(), prefix));
}

/** A state dir the way the plugin expects it: own-user, not group/world-writable. */
function stateDirWith(modeText) {
  const dir = tmp();
  chmodSync(dir, 0o700);
  if (modeText !== undefined) writeFileSync(join(dir, CLAIM_MODE_FILE), modeText);
  return dir;
}

const CLEAN_ENV = {}; // no ADE_CLAIM_DRY_RUN

test("resolveClaimMode: missing file fails safe to observe", () => {
  const m = resolveClaimMode({ env: CLEAN_ENV, stateDir: stateDirWith() });
  assert.equal(m.mode, "observe");
  assert.match(m.reason, /missing/);
  assert.equal(resolveClaimMode({ env: CLEAN_ENV, stateDir: join(tmp(), "nope") }).mode, "observe");
});

test("resolveClaimMode: file says enforce / observe / garbage (re-read per call)", () => {
  const dir = stateDirWith("enforce\n");
  assert.equal(resolveClaimMode({ env: CLEAN_ENV, stateDir: dir }).mode, "enforce");
  writeFileSync(join(dir, CLAIM_MODE_FILE), "  Enforce  ");
  assert.equal(resolveClaimMode({ env: CLEAN_ENV, stateDir: dir }).mode, "enforce");
  writeFileSync(join(dir, CLAIM_MODE_FILE), "observe\n");
  assert.equal(resolveClaimMode({ env: CLEAN_ENV, stateDir: dir }).mode, "observe");
  for (const junk of ["", "enforced", "enforce observe", "yes", "1", "ENFORCE\u0000"]) {
    writeFileSync(join(dir, CLAIM_MODE_FILE), junk);
    assert.equal(resolveClaimMode({ env: CLEAN_ENV, stateDir: dir }).mode, "observe", JSON.stringify(junk));
  }
});

test("resolveClaimMode: env ADE_CLAIM_DRY_RUN forces observe over an enforce file", () => {
  const dir = stateDirWith("enforce");
  for (const v of ["1", "true", "YES", "on", "dry", "2"]) {
    assert.equal(resolveClaimMode({ env: { ADE_CLAIM_DRY_RUN: v }, stateDir: dir }).mode, "observe", v);
  }
  for (const v of ["0", "false", "no", "off", "", "  "]) {
    assert.equal(resolveClaimMode({ env: { ADE_CLAIM_DRY_RUN: v }, stateDir: dir }).mode, "enforce", JSON.stringify(v));
  }
});

test("resolveClaimMode: refuses symlinks, odd owners/perms, big files, bad dirs", () => {
  const real = tmp();
  writeFileSync(join(real, "elsewhere"), "enforce");
  // symlinked mode file
  const linked = stateDirWith();
  symlinkSync(join(real, "elsewhere"), join(linked, CLAIM_MODE_FILE));
  assert.equal(resolveClaimMode({ env: CLEAN_ENV, stateDir: linked }).mode, "observe");
  // symlinked state dir
  const dirLink = join(tmp(), "state");
  writeFileSync(join(real, CLAIM_MODE_FILE), "enforce");
  chmodSync(real, 0o700);
  symlinkSync(real, dirLink);
  assert.equal(resolveClaimMode({ env: CLEAN_ENV, stateDir: dirLink }).mode, "observe");
  assert.equal(resolveClaimMode({ env: CLEAN_ENV, stateDir: real }).mode, "enforce");
  // group/world-writable file or dir
  const loose = stateDirWith("enforce");
  chmodSync(join(loose, CLAIM_MODE_FILE), 0o666);
  assert.equal(resolveClaimMode({ env: CLEAN_ENV, stateDir: loose }).mode, "observe");
  chmodSync(join(loose, CLAIM_MODE_FILE), 0o600);
  chmodSync(loose, 0o777);
  assert.equal(resolveClaimMode({ env: CLEAN_ENV, stateDir: loose }).mode, "observe");
  // mode file is a directory
  const asDir = stateDirWith();
  mkdirSync(join(asDir, CLAIM_MODE_FILE));
  assert.equal(resolveClaimMode({ env: CLEAN_ENV, stateDir: asDir }).mode, "observe");
  // over the read cap, even when it starts with "enforce"
  const big = stateDirWith("enforce" + " ".repeat(MODE_FILE_READ_CAP));
  const m = resolveClaimMode({ env: CLEAN_ENV, stateDir: big });
  assert.equal(m.mode, "observe");
  assert.match(m.reason, /too large/);
});

test("buildObserveEntry caps and cleans values", () => {
  const e = buildObserveEntry({
    hook: "agent.open.before",
    mode: "observe",
    planned: { PATH: { prepend: "/x" }, note: "a\nb".repeat(500) },
    ids: { agent: "a1" },
    now: new Date("2026-11-13T01:02:03.000Z"),
  });
  assert.equal(e.ts, "2026-11-13T01:02:03.000Z");
  assert.ok(/** @type {string} */ (e.planned.note).length <= 512);
  assert.ok(!String(e.planned.note).includes("\n"));
});

test("appendObserveLog appends JSONL at 0600, rotates at the cap, refuses a symlink log", () => {
  const dir = stateDirWith();
  const base = { ts: "t", hook: "h", mode: "observe", planned: null };
  assert.equal(appendObserveLog({ ...base, n: 1 }, { stateDir: dir }), true);
  assert.equal(appendObserveLog({ ...base, n: 2 }, { stateDir: dir }), true);
  const logPath = join(dir, CLAIM_OBSERVE_LOG);
  const lines = readFileSync(logPath, "utf8").trim().split("\n").map((l) => JSON.parse(l));
  assert.deepEqual(lines.map((l) => l.n), [1, 2]);
  assert.equal(statSyncMode(logPath), 0o600);
  // rotate: tiny cap forces .1, new file holds only the newest line
  assert.equal(appendObserveLog({ ...base, n: 3 }, { stateDir: dir, maxBytes: 10 }), true);
  assert.equal(readFileSync(logPath, "utf8").trim().split("\n").length, 1);
  assert.equal(readFileSync(`${logPath}.1`, "utf8").trim().split("\n").length, 2);
  // oversize line is replaced by a stub, never written whole
  assert.equal(appendObserveLog({ ...base, planned: "x".repeat(10000) }, { stateDir: dir }), true);
  assert.match(readFileSync(logPath, "utf8"), /"truncated":true/);
  // a symlinked log is refused (and the link target untouched)
  const evil = stateDirWith();
  const target = join(tmp(), "target");
  writeFileSync(target, "keep\n");
  symlinkSync(target, join(evil, CLAIM_OBSERVE_LOG));
  assert.equal(appendObserveLog(base, { stateDir: evil }), false);
  assert.equal(readFileSync(target, "utf8"), "keep\n");
});

function statSyncMode(path) {
  return statSync(path).mode & 0o777;
}

/**
 * Offline harness: a fake Paseo server, fake trusted tools on disk (never executed), and a scripted
 * spawn that records every call. A call is "mutating" when it would write the registry or install hooks.
 */
function harness({ modeText, env = {}, claims } = {}) {
  const stateDir = stateDirWith(modeText);
  const tools = tmp("ade-claim-tools-");
  const claimsPy = join(tools, "ade_claims.py");
  const guard = join(tools, "ade-git-guard");
  const agentBin = join(tools, "agent-bin");
  mkdirSync(agentBin);
  writeFileSync(claimsPy, "# stub\n");
  writeFileSync(guard, "# stub\n");
  chmodSync(guard, 0o755);
  writeFileSync(join(agentBin, "git"), "# stub\n");
  const cwd = tmp("ade-claim-cwd-");
  const rows = claims ?? [{ id: "wt-test-1", path: cwd, shown_state: "active" }];
  /** @type {{ cmd: string, args: string[] }[]} */
  const calls = [];
  const spawn = (cmd, args) => {
    calls.push({ cmd, args });
    const sub = cmd === "git" ? args.slice(2).join(" ") : args[1];
    if (cmd === "git") {
      if (sub === "rev-parse HEAD") return { status: 0, stdout: "abc1234def\n", stderr: "" };
      if (sub === "config --get remote.origin.url") return { status: 0, stdout: "git@example.com:o/r.git\n", stderr: "" };
      if (sub === "rev-parse --git-dir") return { status: 0, stdout: ".git\n", stderr: "" };
    }
    if (cmd === "python3" && sub === "list") return { status: 0, stdout: JSON.stringify(rows), stderr: "" };
    return { status: 0, stdout: "", stderr: "" };
  };
  const lines = [];
  const deps = {
    env: { ADE_CLAIMS_PY: claimsPy, ADE_GIT_GUARD: guard, ADE_AGENT_BIN: agentBin, PATH: "/usr/bin", ...env },
    stateDir,
    spawn,
    log: (l) => lines.push(l),
    now: () => new Date("2026-11-13T00:00:00.000Z"),
  };
  const mutating = () => calls.filter((c) =>
    (c.cmd === "python3" && ["new", "bind-owner", "release"].includes(c.args[1])) || c.cmd === guard);
  const jsonl = () => {
    try {
      return readFileSync(join(stateDir, CLAIM_OBSERVE_LOG), "utf8").trim().split("\n").filter(Boolean).map((l) => JSON.parse(l));
    } catch {
      return [];
    }
  };
  const hooks = new Map();
  const server = { addHook: (name, fn) => { hooks.set(name, fn); return () => hooks.delete(name); } };
  return { deps, server, hooks, calls, mutating, jsonl, lines, cwd, stateDir, claimsPy, guard, agentBin };
}

const WT = (h) => ({ worktree: { path: h.cwd, branch: "ws/obs", sourceCheckout: "/src/repo" } });
const OPEN = (h, env = { KEEP: "1" }) => ({ request: { agentId: "agent-1", cwd: h.cwd, env } });

for (const mode of ["observe", "enforce"]) {
  const modeText = mode;
  test(`worktree.create.after [${mode}]`, async () => {
    const h = harness({ modeText });
    registerWorktreeClaimHook(h.server, h.deps);
    await h.hooks.get("worktree.create.after")(WT(h));
    const rec = h.jsonl();
    assert.equal(rec.length, 1);
    assert.equal(rec[0].hook, "worktree.create.after");
    assert.equal(rec[0].mode, mode);
    assert.equal(rec[0].planned.argv[2], "new");
    assert.equal(rec[0].planned.ttlHours, 72);
    assert.equal(rec[0].ids.worktree, h.cwd);
    if (mode === "observe") {
      assert.deepEqual(h.mutating(), []);
      assert.match(h.lines[0], /^ade-claim\[observe\] worktree\.create\.after/);
    } else {
      const m = h.mutating();
      assert.equal(m.length, 2, "new + guard install");
      assert.deepEqual(m[0].args.slice(0, 2), [h.claimsPy, "new"]);
      assert.equal(m[1].cmd, h.guard);
    }
  });

  test(`workspace.archive.after [${mode}]`, async () => {
    const h = harness({ modeText });
    registerWorkspaceArchiveReleaseHook(h.server, h.deps);
    await h.hooks.get("workspace.archive.after")({ workspace: { id: "ws-1", cwd: h.cwd } });
    const rec = h.jsonl();
    assert.equal(rec.length, 1);
    assert.equal(rec[0].mode, mode);
    assert.deepEqual(rec[0].planned.argv.slice(2), ["release", "--id", "wt-test-1"]);
    assert.equal(h.mutating().length, mode === "observe" ? 0 : 1);
  });

  test(`agent.create.after [${mode}]`, async () => {
    const h = harness({ modeText });
    registerAgentClaimOwnerHook(h.server, h.deps);
    await h.hooks.get("agent.create.after")({ agent: { id: "agent-1", cwd: h.cwd } });
    const rec = h.jsonl();
    assert.equal(rec.length, 1);
    assert.equal(rec[0].mode, mode);
    assert.deepEqual(rec[0].planned.argv.slice(2, 4), ["bind-owner", "--id"]);
    assert.equal(h.mutating().length, mode === "observe" ? 0 : 1);
  });

  test(`agent.open.before [${mode}]`, async () => {
    const h = harness({ modeText, env: { PATH: "/usr/bin" } });
    registerAgentClaimEnvHook(h.server, h.deps);
    const input = OPEN(h, { KEEP: "1", ADE_CLAIM_ID: "foreign" });
    const out = await h.hooks.get("agent.open.before")(input);
    const rec = h.jsonl();
    assert.equal(rec.length, 1);
    assert.equal(rec[0].mode, mode);
    assert.equal(rec[0].planned.wouldChange, true);
    assert.deepEqual(rec[0].planned.ADE_CLAIM_ID, { set: "wt-test-1" });
    assert.deepEqual(rec[0].planned.PATH, { prepend: h.agentBin });
    assert.ok(!JSON.stringify(rec[0]).includes("KEEP"), "launch env values never logged");
    assert.equal(h.mutating().length, 0);
    if (mode === "observe") {
      assert.equal(out, undefined, "request untouched: no ADE_CLAIM_ID, no PATH change");
      assert.equal(input.request.env.ADE_CLAIM_ID, "foreign");
    } else {
      assert.equal(out.env.ADE_CLAIM_ID, "wt-test-1");
      assert.equal(out.env.PATH.split(":")[0], h.agentBin);
      assert.equal(out.env.KEEP, "1");
    }
  });
}

test("every hook honours ADE_CLAIM_DRY_RUN over an enforce file, and the file is re-read per call", async () => {
  const h = harness({ modeText: "enforce", env: { ADE_CLAIM_DRY_RUN: "1" } });
  registerAdeClaimHooks(h.server, h.deps);
  await h.hooks.get("worktree.create.after")(WT(h));
  await h.hooks.get("workspace.archive.after")({ workspace: { id: "w", cwd: h.cwd } });
  await h.hooks.get("agent.create.after")({ agent: { id: "agent-1", cwd: h.cwd } });
  assert.equal(await h.hooks.get("agent.open.before")(OPEN(h)), undefined);
  assert.deepEqual(h.mutating(), []);
  assert.deepEqual(h.jsonl().map((r) => r.mode), ["observe", "observe", "observe", "observe"]);

  // No restart: flip the flag file and the very next call enforces.
  const h2 = harness({ modeText: "observe" });
  registerAgentClaimEnvHook(h2.server, h2.deps);
  assert.equal(await h2.hooks.get("agent.open.before")(OPEN(h2)), undefined);
  writeFileSync(join(h2.stateDir, CLAIM_MODE_FILE), "enforce\n");
  const out = await h2.hooks.get("agent.open.before")(OPEN(h2));
  assert.equal(out.env.ADE_CLAIM_ID, "wt-test-1");
  rmModeFile(h2);
  assert.equal(await h2.hooks.get("agent.open.before")(OPEN(h2)), undefined, "deleted flag = observe");
});

function rmModeFile(h) {
  unlinkSync(join(h.stateDir, CLAIM_MODE_FILE)); // deleted flag = observe
}

test("missing mode file = observe for all four hooks (fail safe)", async () => {
  const h = harness(); // no mode file
  registerAdeClaimHooks(h.server, h.deps);
  await h.hooks.get("worktree.create.after")(WT(h));
  await h.hooks.get("workspace.archive.after")({ workspace: { id: "w", cwd: h.cwd } });
  await h.hooks.get("agent.create.after")({ agent: { id: "agent-1", cwd: h.cwd } });
  assert.equal(await h.hooks.get("agent.open.before")(OPEN(h)), undefined);
  assert.deepEqual(h.mutating(), []);
  assert.equal(h.jsonl().length, 4);
});

test("observe never throws on a waiting hook (bad payload, missing trusted helper, bad TTL)", async () => {
  const h = harness({ modeText: "observe", env: { ADE_CLAIM_TTL: "nope" } });
  registerAdeClaimHooks(h.server, h.deps);
  await h.hooks.get("worktree.create.after")(WT(h)); // bad ADE_CLAIM_TTL
  await h.hooks.get("worktree.create.after")({ worktree: null });
  assert.equal(await h.hooks.get("agent.open.before")({ request: { agentId: "" } }), undefined);
  const rec = h.jsonl();
  assert.equal(rec.length, 3);
  assert.ok(rec.every((r) => typeof r.error === "string" && r.mode === "observe"));
  assert.deepEqual(h.mutating(), []);
  // ...while enforce still fails loudly (abort creation) as before
  const e = harness({ modeText: "enforce", env: { ADE_CLAIM_TTL: "nope" } });
  registerWorktreeClaimHook(e.server, e.deps);
  await assert.rejects(() => e.hooks.get("worktree.create.after")(WT(e)), /ADE_CLAIM_TTL/);
});

test("observe lookup is read-only: only git rev-parse/config and ade_claims.py list run", async () => {
  const h = harness({ modeText: "observe" });
  registerAdeClaimHooks(h.server, h.deps);
  await h.hooks.get("worktree.create.after")(WT(h));
  await h.hooks.get("workspace.archive.after")({ workspace: { id: "w", cwd: h.cwd } });
  await h.hooks.get("agent.create.after")({ agent: { id: "agent-1", cwd: h.cwd } });
  await h.hooks.get("agent.open.before")(OPEN(h));
  for (const c of h.calls) {
    const ok = (c.cmd === "git" && ["rev-parse", "config"].includes(c.args[2]))
      || (c.cmd === "python3" && c.args[1] === "list");
    assert.ok(ok, `unexpected spawn in observe: ${c.cmd} ${c.args.join(" ")}`);
  }
});

test("a credential in the remote URL never reaches the JSONL or the stderr line (both modes)", async () => {
  const token = "ghp_SECRETTOKEN123";
  for (const modeText of ["observe", "enforce"]) {
    const h = harness({ modeText });
    const spawn = h.deps.spawn;
    h.deps.spawn = (cmd, args) => (cmd === "git" && args.slice(2).join(" ") === "config --get remote.origin.url")
      ? { status: 0, stdout: `https://x-access-token:${token}@github.com/o/r.git\n`, stderr: "" }
      : spawn(cmd, args);
    registerWorktreeClaimHook(h.server, h.deps);
    await h.hooks.get("worktree.create.after")(WT(h));
    const logged = JSON.stringify(h.jsonl()) + h.lines.join("\n");
    assert.ok(!logged.includes(token), `${modeText}: token leaked`);
    assert.ok(logged.includes("https://<redacted>@github.com/o/r.git"), `${modeText}: host kept`);
    // the real argv (enforce) still carries the URL: only the log is redacted
    if (modeText === "enforce") {
      const run = h.calls.find((c) => c.cmd === "python3" && c.args[1] === "new");
      assert.ok(run.args.join(" ").includes(token));
    }
  }
  assert.equal(redactUrlUserinfo("git@example.com:o/r.git"), "git@example.com:o/r.git");
  assert.equal(redactUrlUserinfo("ssh://git@h/x https://u:p@h2/y"), "ssh://<redacted>@h/x https://<redacted>@h2/y");
});

test("enforce records the ade-git-guard install outcome", async () => {
  const h = harness({ modeText: "enforce" });
  const spawn = h.deps.spawn;
  h.deps.spawn = (cmd, args) => (cmd === h.guard ? { status: 73, stdout: "", stderr: "busy" } : spawn(cmd, args));
  registerWorktreeClaimHook(h.server, h.deps);
  await h.hooks.get("worktree.create.after")(WT(h));
  assert.equal(h.jsonl()[0].planned.install, "failed (exit 73) (soft)");
});
