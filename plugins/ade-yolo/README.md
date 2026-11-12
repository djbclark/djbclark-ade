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
(no mode is invented). A Pi catalog that lists modes, or is not enabled/ready, gets no exemption. The
allowlist (`UNATTENDED_BY_CONSTRUCTION`) is not generalised to other providers. Retired omp/OpenCode routes are not restored.

`agent.open.before` checks saved mode/control evidence on resume, refresh and
import. **Drift** (evidence present and contradicting) refuses. **Missing evidence** refuses only for agents
this plugin created: `agent.create.before` stamps those with metadata `ade-yolo.applied`. An agent without
that stamp is *legacy*: created before the plugin was installed (Hermes included), while it was disabled,
internal, imported, or stripped of its stamp (the SDK exposes no install time, so "no stamp" is a superset of
"created before install"; none of these can escalate, they only turn a refusal into allow-and-log): missing evidence is allowed and logged
(`ade-yolo: <id>: legacy agent without saved mode evidence; allowed`, written to the plugin's stderr), with no
catalog lookup. Retired providers (omp, opencode, crush, agy, grok) are refused first, legacy or not. Drift refuses legacy agents too: see *Install impact*. If the
host drops the metadata, every agent reads as legacy and only drift refuses. This hook can check or
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

Drift refuses **legacy agents too**. Hosts save the provider's default mode on every agent: Claude `default`,
Codex `auto`, Cursor `agent`, Antigravity `full-access`, Pi none. Installing the plugin makes the host re-check
every live, idle agent on its next prompt (`hooks.changed` invalidates plugin sessions, then a `refresh` open
runs `agent.open.before`). A legacy Claude/Codex agent with a saved non-YOLO mode is refused as drift, and every
later prompt is refused until the mode is repaired (a verified successor, set to the YOLO mode) or
`paseo plugin disable ade-yolo`. On this host that was at least 23 unarchived Claude `default` agents and 2 Codex
`auto` agents, the lead's own session included if it runs in `default` mode. Only agents with **no** saved
mode (Pi, Hermes-style dynamic providers, pre-mode records) get the allow-and-log path.

## Canary procedure (lead runs this after merge)

The plugin is not installed by this repo. Never prompt an operator's own agent or Hermes: the canary resumes
only throwaway agents it created. Providers are a closed list: claude, codex, antigravity, pi, cursor, each only
if enabled in `paseo provider ls --json`. Other enabled providers are not created in step 0; their step-2
creates are **expected refusals** (hermes, cline: unverified; grok and other retired clients: retired). Run in
order; stop and roll back on a result not listed as expected.

0. Audit before installing: list unarchived agents (`paseo ls -g --json`) and, per id,
   `/Users/djbclark/src/djbclark-ade/bin/ade-agent-mode check <id> --json`; every agent that is not
   `verified`/`exempt` (saved `default`/`auto`) will be refused on its next prompt once installed. The operator
   decides (repair, successor, or accept) before step 1. Note whether Hermes is listed (step 5).
1. Create throwaways **before installing** so they are legacy (no stamp). Per provider, in a scratch dir:
   `paseo run --provider <provider>/<model> --cwd <scratch dir> --wait-timeout 2m --json -- "reply with the word ok"`.
   Record ids; also make a Claude one with `--mode bypassPermissions`.
2. Install from a clean pinned tree, not the shared checkout. The host records the directory path, so the
   worktree is the live plugin source: **it must persist** until rollback or reinstall. Run
   `git -C /Users/djbclark/src/djbclark-ade fetch origin`, then
   `git -C /Users/djbclark/src/djbclark-ade worktree add --detach /Users/djbclark/src/djbclark-ade-yolo-plugin-wt origin/master`,
   record the sha, then `paseo plugin install /Users/djbclark/src/djbclark-ade-yolo-plugin-wt/plugins/ade-yolo`.
   `paseo plugin ls --json` shows `ade-yolo` enabled/running.
3. Resume the step-1 throwaways (`paseo send <id> "ok"`). Expected per provider:
   Claude `--mode bypassPermissions`: opens, no log line (match). Plain Claude and Codex (saved `default`/`auto`):
   **refused as drift**, expected. Antigravity (saved `full-access`): opens, no log line. Pi (no saved mode):
   opens and the plugin stderr (`paseo plugin logs ade-yolo`) shows `legacy agent without saved mode evidence;
   allowed`. Cursor (saved `agent`): opens with `legacy agent without saved auto_accept; allowed`, or report it
   unverified if `listControls` is unavailable.
4. New creates: repeat step 1 per provider (now stamped). Expected `ade-agent-mode check <id> --json`
   (absolute path): Claude `bypassPermissions`, Codex/Antigravity `full-access`: `verified`. **Cursor and Pi
   report `unavailable` (exit 2) from that CLI by design** (it passes no controls; Pi has no mode): their
   pass criterion is that the create succeeded. Also confirm hermes/cline creates (if attempted) refuse as
   expected, never as a surprise.
5. Hermes: do not prompt it. If it was listed before install, `paseo ls -g --json` still lists it with the same
   id/status afterwards, and its next natural open shows no `ade-yolo` refusal.
6. Restrictive escape: create a throwaway with `--mode plan` (Claude); `ade-agent-mode check` reports `exempt`.
   (`ade-yolo.skip` is metadata-only: reachable through MCP `create_agent` metadata, not `paseo run`.)
7. Archive every throwaway.

Rollback (exact): `paseo plugin remove ade-yolo` (the uninstall; `paseo plugin disable ade-yolo` is the
reversible off switch, and the immediate cure for agents refused as drift), then `paseo plugin ls --json` shows
no `ade-yolo` row; then `git -C /Users/djbclark/src/djbclark-ade worktree remove /Users/djbclark/src/djbclark-ade-yolo-plugin-wt`.

Source contracts were inspected at upstream `4df5307e` (0.16.0-beta.2 source).
Older hosts without the catalog/control SDK report unavailable rather than
claiming coverage. This cloud run had no Paseo executable/daemon; mocked tests
prove local planning and calls, not installed runtime behavior.
