# ade-yolo (Paseo plugin)

Snapshot **2026-11-12**. Ordinary agent creates, including MCP children and trusted
internal reviewers, request unattended permissions. Only an explicit operator
restriction or external-security-critical work stays restricted. No trust
classifier is added here. `defaultMode` and display labels never prove YOLO.

The awaited `agent.create.before` hook reads the exact native provider catalog.
Claude `bypassPermissions`, Codex/Antigravity `full-access`, and native Copilot
`allow-all` require membership in that catalog. The latter adds no router row and
does not restore the retired Copilot CLI. A unique native `isUnattended` mode is
also accepted if the host actually preserves that field. Cursor uses its
advertised ACP `auto_accept` toggle through `providerOptions`, preserving a
catalogued mode when present. Unavailable/disabled/loading providers, missing
IDs/controls, and unverified providers (Hermes, any unknown modeless provider) refuse ordinary
creation with a diagnostic. **Pi is the one explicit exception (2026-11-12):** its catalog is modeless, but Pi never raises permission
requests (with no UI-prompting Pi extension installed: a Pi `extension_ui_request` confirm/select becomes a permission question, so a future prompting extension voids this premise), so a ready, modeless Pi catalog is unattended by construction and the create passes unchanged
(no mode is invented). Pi with modes uses the same unique native `isUnattended` rule as any provider;
unmarked modes refuse. A Pi catalog that is not enabled/ready gets no exemption. The
allowlist (`UNATTENDED_BY_CONSTRUCTION`) is not generalised to other providers. Retired omp/OpenCode routes are not restored.

`agent.open.before` checks saved mode/control evidence on resume, refresh and
import. **Drift** (evidence present and contradicting) and **missing evidence** refuse only for agents
this plugin created: `agent.create.before` stamps those with metadata `ade-yolo.applied`. An agent without
that stamp is *legacy*: created before the plugin was installed (Hermes included), while it was disabled,
internal, imported, or stripped of its stamp (the SDK exposes no install time, so "no stamp" is a superset of
"created before install"). Legacy agents are allowed with a warning naming the agent id, provider,
saved mode and `auto_accept` value, with no catalog lookup or mode mutation. Retired providers
(omp, opencode, crush, agy, grok) are refused first for ordinary non-exempt opens, legacy or not.
If the host drops the metadata, every agent reads as legacy and receives the allow-and-log policy. This hook can check or
refuse, not mutate saved modes. History reads do not open a runtime and remain allowed.
A matching saved value is a **preflight**, not post-open proof. Native runtime
readback remains necessary after opening; see [agent modes](../../docs/agent-modes.md).

Explicit `plan`, `read-only`, `dontAsk`, metadata `ade-yolo.skip: true`, or metadata
`ade.work-scope: external-security-critical|operator-restrictive` preserve the
operator's restrictive request. These metadata are declarations by our caller,
not conclusions inferred from external text. Trusted internal review does not
implicitly set them.

Installation is a separate live operation; this change does not install/enable:

```sh
paseo plugin install /absolute/path/to/djbclark-ade/plugins/ade-yolo
paseo plugin ls --json  # verify enabled/running on the intended daemon
```

## Install impact (read before installing; snapshot 2026-11-12)

Installing no longer refuses any pre-existing agent because of its saved mode, missing evidence,
or unavailable catalog. Agents without an `ade-yolo.applied` stamp remain in their saved mode and
are allowed with a warning, including Claude `default`, Codex `auto`, Cursor `agent` with absent/false
`auto_accept`, and Pi/Hermes without a saved mode. Installing invalidates plugin sessions; their next
prompt can run a `refresh` open and emit that warning. Identity checks and the existing retired-provider
policy still apply. Stamped agents continue to refuse missing evidence or drift. The hook cannot mutate
modes; refusing a legacy agent in a more restrictive mode would only create operator work.

## Canary procedure (lead runs this after merge)

The plugin is not installed by this repo. Never prompt an operator's own agent or Hermes: the canary resumes
only throwaway agents it created. Providers are a closed list: claude, codex, antigravity, pi, cursor, each only
if enabled in `paseo provider ls --json`. Other enabled providers are not created in step 1; if probed in step 4, use `cline` (never a Hermes
throwaway), and the create is an **expected refusal** (hermes, cline: unverified; grok and other retired clients: retired). Run in
order; stop and roll back on a result not listed as expected.

0. Audit before installing: list unarchived agents (`paseo ls -g --json`) and, per id,
   `/Users/djbclark/src/djbclark-ade/bin/ade-agent-mode check <id> --json`; a Claude/Codex/Antigravity/Copilot agent whose
   saved Mode is neither the YOLO id nor `plan`/`read-only`/`dontAsk` (typically saved `default`/`auto`), or a Cursor
   agent saving `auto_accept` other than true, remains allowed if unstamped and logs its saved configuration.
   The CLI's `unavailable`/`drift` status does not predict a legacy hook refusal. Note whether Hermes is listed (step 5).
1. Create throwaways **before installing** so they are legacy (no stamp). Launch each one top-level
   through Python subprocess argv lists, with both its process cwd and `--cwd` set to the scratch directory.
   Remove inherited agent **and workspace** placement from a copy of the environment; keep the daemon/host
   selection unchanged. Use this helper for every create in steps 1, 4 and 6:

   ```python
   import json
   import os
   from pathlib import Path
   import subprocess

   scratch = Path("/absolute/path/to/canary/scratch").resolve()
   scratch.mkdir(parents=True, exist_ok=True)
   env = os.environ.copy()
   for key in ("PASEO_AGENT_ID", "PASEO_AGENT_CWD", "PASEO_WORKSPACE_ID"):
       env.pop(key, None)

   def create_throwaway(provider_model, mode=None):
       argv = ["paseo", "run", "--provider", provider_model,
               "--cwd", str(scratch), "--wait-timeout", "2m", "--json"]
       if mode is not None:
           argv += ["--mode", mode]
       argv += ["--", "reply with the word ok"]
       result = subprocess.run(argv, cwd=scratch, env=env, capture_output=True,
                               text=True, timeout=300)
       result.check_returncode()
       created = json.loads(result.stdout)
       agent_id = created["agentId"]
       print("Created throwaway:", agent_id, flush=True)
       # Persist this id in the canary record before inspection so rollback can archive it.
       inspected = subprocess.run(
           ["paseo", "agent", "inspect", agent_id, "--json"],
           cwd=scratch, env=env, capture_output=True, text=True, timeout=300,
           check=True,
       )
       snapshot = json.loads(inspected.stdout)
       if (Path(snapshot["Cwd"]).resolve() != scratch
               or snapshot.get("ParentAgentId") is not None):
           raise RuntimeError(f"Unexpected placement for {agent_id}; stop and roll back")
       return agent_id
   ```

   Call `create_throwaway("<provider>/<model>")` per enabled provider; also make a Claude one with
   `create_throwaway("claude/<model>", "bypassPermissions")`. Record every id, including any whose placement
   check fails, for step 7. Inspect the **first** create before proceeding to another create or installation.
   Require its actual `Cwd` to equal scratch and `ParentAgentId` to be null; enforce the same check for later creates.

   **Placement finding (2026-11-12):** the original agent-scoped command ignored the scratch `--cwd` and inherited
   the caller workspace. A retry removing only `PASEO_AGENT_ID` and `PASEO_AGENT_CWD`, also using scratch as the
   subprocess cwd, created a top-level agent but still reused the caller workspace while `PASEO_WORKSPACE_ID`
   remained inherited. Both runs stopped before installation and archived their throwaways. A third run removing
   **all three** variables as above live-proved scratch `Cwd` and null `ParentAgentId` for six legacy creates
   (Claude default/bypass, Codex, Antigravity, Pi and Cursor). The first create reported a new scratch workspace,
   rather than reusing the shared repository workspace. This proves placement for that launch form; the full
   plugin canary **did not pass**: Cursor legacy resume failed after installation (see below).
2. Install from a clean pinned tree, not the shared checkout. The host records the directory path, so the
   worktree is the live plugin source: **it must persist** until rollback or reinstall. Run
   `git -C /Users/djbclark/src/djbclark-ade fetch origin`, then
   `git -C /Users/djbclark/src/djbclark-ade worktree add --detach /Users/djbclark/src/djbclark-ade-yolo-plugin-wt origin/master`,
   record the sha, then `paseo plugin install /Users/djbclark/src/djbclark-ade-yolo-plugin-wt/plugins/ade-yolo`.
   `paseo plugin ls --json` shows `ade-yolo` enabled/running.
3. Resume the step-1 throwaways (`paseo send --no-wait <id> "ok"`, then a bounded `paseo wait`). Expected per provider:
   All legacy throwaways open without mode mutation. Plugin stderr (`paseo plugin logs ade-yolo`) warns
   `ade-yolo: <id>: provider=<provider> saved mode=<JSON value> auto_accept=<JSON value>; legacy agent allowed without mode mutation`.
   Expect Claude `default` or `bypassPermissions`, Codex `auto`, Antigravity `full-access`, Cursor `agent`,
   and Pi `null` as saved mode values; absent `auto_accept` logs `null`. No legacy catalog/control lookup is required.
4. New creates: repeat step 1 per provider using `create_throwaway` and its placement check (now stamped). Expected `ade-agent-mode check <id> --json`
   (absolute path): Claude `bypassPermissions`, Codex/Antigravity `full-access`: `verified`. **Cursor and Pi
   report `unavailable` (exit 2) from that CLI by design** (it passes no controls; Pi has no mode): their
   pass criterion is that the create succeeded. Also confirm hermes/cline creates (if attempted) refuse as
   expected, never as a surprise.
5. Hermes: do not prompt it. If it was listed before install, `paseo ls -g --json` still lists it with the same
   id/status afterwards, and its next natural open shows no `ade-yolo` refusal.
6. Restrictive escape: use `create_throwaway("claude/<model>", "plan")` with the same placement check;
   `ade-agent-mode check` reports `exempt`.
   (`ade-yolo.skip` is metadata-only: reachable through MCP `create_agent` metadata, not `paseo run`.)
7. Archive every throwaway.

Rollback (exact): `paseo plugin remove ade-yolo` (the uninstall; `paseo plugin disable ade-yolo` is the
reversible off switch, and the immediate cure for agents refused as drift), then `paseo plugin ls --json` shows
no `ade-yolo` row; then `git -C /Users/djbclark/src/djbclark-ade worktree remove /Users/djbclark/src/djbclark-ade-yolo-plugin-wt`.

Source contracts were inspected at upstream `4df5307e` (0.16.0-beta.2 source).
Older hosts without the catalog/control SDK report unavailable rather than
claiming coverage. The original cloud run had no Paseo executable/daemon;
its mocked tests prove local planning and calls.

**Live canary (2026-11-12):** installation from clean detached `23e965993aa30b05e26f9f59ebb0b94e6ac961e9`
reached enabled/running without a daemon restart. Claude default, Codex, Antigravity and Pi legacy throwaways
resumed with unchanged saved modes; observed warning values matched step 3 (including Pi `null`). Cursor legacy
resume then failed with `Failed to send message: Invalid params: Session "<session-id>" not found`.
The run stopped immediately, removed the plugin and source worktree, and archived all six throwaways.
The error alone does not establish a plugin root cause. The explicit-bypass Claude resume, stamped creates,
restrictive escape and full-canary success remain unverified; rerun the complete procedure after diagnosis.

**Plugin-free control (2026-11-12):** a new Cursor throwaway launched with the same three-variable form;
its immediate second-message send and a further send after 60 seconds idle were both accepted without the
session-not-found error. Inspections bracketing the idle interval showed idle status and unchanged `UpdatedAt`.
The activity returned `Upgrade your plan to continue`, limiting comparison with a functioning model session.
The run stopped after the control, archived its throwaway, and left the plugin uninstalled. Cursor resume
session-not-found remains an **unexpected** canary result; this control did not justify treating it as a
pre-existing limitation or attributing it to the plugin.
