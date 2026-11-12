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
catalog lookup. Retired providers (omp, opencode, crush, agy, grok) are refused first, legacy or not. If the
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

## Canary procedure (lead runs this after merge; snapshot 2026-11-12)

The plugin is not installed by this repo. Never prompt an operator's own agent or Hermes: the canary resumes
only throwaway agents it created. Run in order; stop and roll back on the first unexpected result.

0. **Before installing**, per enabled provider from `paseo provider ls --json` (claude, codex, antigravity, pi,
   cursor if present; skip and report disabled ones), create two idle throwaway agents, so they are legacy
   (no stamp) by construction: `paseo run --provider <provider>/<model> --json -- "reply with the word ok"`.
   Make one of the Claude throwaways with `--mode default` (the drift case). Record ids.
1. Install from a clean pinned tree, not the shared checkout: `git -C /Users/djbclark/src/djbclark-ade fetch origin`,
   `git -C /Users/djbclark/src/djbclark-ade worktree add --detach /Users/djbclark/src/djbclark-ade-yolo-canary-wt origin/master`,
   record the sha, then `paseo plugin install /Users/djbclark/src/djbclark-ade-yolo-canary-wt/plugins/ade-yolo`.
   `paseo plugin ls --json` shows `ade-yolo` enabled/running. Keep that worktree until rollback.
2. New creates: per enabled provider create a fresh throwaway as in step 0 (it now gets the stamp). Expected
   `bin/ade-agent-mode check <id> --json`: Claude `bypassPermissions`, Codex/Antigravity `full-access`:
   `verified`. **Cursor and Pi report `unavailable` (exit 2) from that CLI by design** (it passes no controls,
   and Pi has no mode): for them the pass criterion is that the create succeeded rather than being refused.
3. Resume the step-0 throwaways (legacy, no saved mode): each opens (`paseo send <id> "ok"`), and the plugin
   stderr (`paseo plugin logs ade-yolo` if the host offers it) shows `legacy agent without saved mode
   evidence; allowed`. The `--mode default` Claude throwaway must be **refused as drift**: that refusal is the
   expected result, not a failure.
4. Hermes: do not prompt it. `paseo ls -g --json` still lists it with the same id/status; its next natural
   open must show no `ade-yolo` refusal.
5. Restrictive escape: create a throwaway with `--mode plan` (Claude); it creates restricted and
   `ade-agent-mode check` reports `exempt`. (`ade-yolo.skip` is metadata-only: reachable through the MCP
   `create_agent` metadata, not `paseo run`.)
6. Archive every throwaway.

Rollback (exact): `paseo plugin remove ade-yolo` (the uninstall; `paseo plugin disable ade-yolo` is the
reversible off switch), then `paseo plugin ls --json` shows no `ade-yolo` row; remove the canary worktree.

Source contracts were inspected at upstream `4df5307e` (0.16.0-beta.2 source).
Older hosts without the catalog/control SDK report unavailable rather than
claiming coverage. This cloud run had no Paseo executable/daemon; mocked tests
prove local planning and calls, not installed runtime behavior.
