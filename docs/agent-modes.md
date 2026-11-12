# A. Ordinary-agent permissions and readback

A1. **2026-11-12 operator decision:** ordinary agent openings, children, trusted
internal reviewers and successors run YOLO. Preserve explicit operator
restrictions; external-security-critical work uses the restricted review
boundary. The November 6 slim plan's blanket restricted-review wording does not
overrule this later decision. No automatic trust classifier or retired route is
introduced. Self-compact/handoff entry points are a separate unit; they consume
`plan_unattended_config` and `verify_unattended_snapshot` from `bin/paseo_yolo.py`.

A2. Evidence is two steps: a native catalog/control provides concrete IDs/options,
then a fresh native inspect proves exact agent identity, provider, live
unarchived status, current mode, and mode membership (or the effective option).
A create/set-mode receipt alone is not proof. Missing fields and mode drift fail
verification. Uppercase CLI inspect may omit option readback; Cursor then remains
unverified through that interface, even when its create hook requested auto_accept.

| A3. Native provider | Source-backed selection, also requiring native evidence | Remaining limit |
|---|---|---|
| Claude | `bypassPermissions` in exact catalog | Installed runtime/readback still required |
| Codex | `full-access` in exact catalog | Same |
| Antigravity | `full-access` in exact catalog | Same; availability/entitlement gates unchanged |
| Native Copilot | `allow-all` in exact catalog | No router row added; retired CLI remains retired |
| Cursor | Advertised ACP toggle `auto_accept`, native option readback | CLI inspect lacking options cannot verify/repair it |
| Pi | No invented mode: source returns an empty mode list | Extension UI requests remain possible; no universal mode/control proof |
| Hermes / other dynamic providers | Native unique `isUnattended` marker if actually available | Otherwise explicit unavailable; no invented ID or label reconstruction |
| omp / OpenCode / retired client IDs | Refused by ordinary planner | No route reactivation |

# B. Commands and effects

B1. `bin/ade-agent-mode check FULL_ID [--home PATH] [--json]` reads native inspect
and provider availability. Exit 0 is verified or explicit restrictive exemption,
1 is drift/unverified live mode, 2 is unavailable/invalid. A prefix that native
Paseo resolves to a different full ID is refused. No files, modes, prompts,
archives, reloads or daemon settings are written.

B2. `bin/ade-agent-mode repair FULL_ID [--dry-run|--yes] [--home PATH] [--json]`
plans by default; `--dry-run` is explicit plan-only spelling. A needed repair is
planned only for an already-live idle unarchived agent with a source-backed
catalogued mode. **`--yes` currently refuses a needed mutation (exit 2):** native
`setAgentMode` first ensures an interactive session, and an agent can close
between any idle check and that call. Native source exposes no atomic live-only
precondition, so this command never dispatches that potentially reopening call.
A second inspect would narrow the race, not fix it. Already-verified agents are
no-ops; explicit restrictive modes remain exempt. `--home` selects the same
native daemon for all reads. No remote host inference or hidden retry is made.

B3. Closed/running drift repair is refused; applying idle drift repair remains
blocked on an atomic native live-only mutation. The open hook cannot patch mode
configuration, so a refused agent needs an explicitly created verified successor
or a future native atomic config/open facility. This unit does not automatically
restart anything or claim continuous live monitoring. A resume preflight checks
saved values only; `check` after opening establishes current evidence. Mode
changes after a check can still drift; repeat native readback at the next
consequential boundary.

B4. The direct-Claude `review-pr` / `review-launch` restricted boundary is kept
for external-security-critical review. Since 2026-11-12 (W2) `review-pr` also
has a trusted internal runtime: for a PR the repository owner authored,
`--runtime auto` (the default) launches `review-launch --mode trusted`
(`--permission-mode bypassPermissions`, Bash added, no read-boundary claim); any
other author, and `--runtime restricted`, keep `--mode review`. The trusted
launch proves its own init event (tools, `bypassPermissions`, cwd, no MCP) and
nothing more; it is not a Paseo-created agent, so the native create/readback
evidence above does not apply to it, and an ordinary Paseo review path for
trusted work remains separate, unbuilt work. See
[docs/review-boundary.md](review-boundary.md).

B5. The installed plugin applies to UI/CLI/MCP creates and resume/refresh/import
opens. The transitional `acp-dispatch --perm all` and dialogue launchers pass
source-backed native modes, then verify inspect before accepting the launch;
unverified new agents receive a native stop request and a refused result.
The first pointer may already have reached that new runtime; this is not a
pre-send transaction. Unknown/dynamic modes through these legacy CLI paths
refuse rather than fall back to a prompting provider default. Cursor's native
SDK create hook remains distinct from these CLI-only paths. No new call sites
should adopt the transitional shim.

# C. Source evidence and validation

C1. Upstream snapshot [4df5307e](https://github.com/getpaseo/paseo/tree/4df5307eaab6b22d06fe54a45c68211b3413f45c), inspected 2026-11-12:
[native mode manifests](https://github.com/getpaseo/paseo/blob/4df5307eaab6b22d06fe54a45c68211b3413f45c/packages/protocol/src/provider-manifest.ts),
[Antigravity catalog](https://github.com/getpaseo/paseo/blob/4df5307eaab6b22d06fe54a45c68211b3413f45c/plugins/antigravity-provider/server/internal/catalog.ts),
[ACP auto_accept](https://github.com/getpaseo/paseo/blob/4df5307eaab6b22d06fe54a45c68211b3413f45c/packages/server/src/server/agent/providers/acp-agent.ts),
[Pi mode limitation](https://github.com/getpaseo/paseo/blob/4df5307eaab6b22d06fe54a45c68211b3413f45c/packages/server/src/server/agent/providers/pi/agent.ts),
[hook payloads/failure behavior](https://github.com/getpaseo/paseo/blob/4df5307eaab6b22d06fe54a45c68211b3413f45c/packages/server/src/server/plugins/lifecycle/index.ts),
[SDK provider snapshot/controls and agent refresh](https://github.com/getpaseo/paseo/blob/4df5307eaab6b22d06fe54a45c68211b3413f45c/packages/client/src/index.ts),
[CLI provider labels](https://github.com/getpaseo/paseo/blob/4df5307eaab6b22d06fe54a45c68211b3413f45c/packages/cli/src/commands/provider/ls.ts),
[mode mutation and interactive-open behavior](https://github.com/getpaseo/paseo/blob/4df5307eaab6b22d06fe54a45c68211b3413f45c/packages/server/src/server/agent/agent-manager.ts).
The upstream protocol's `AgentMode` wire schema omits `isUnattended`; source-known
IDs plus actual catalog membership cover those modes without inventing a flag.
This source snapshot is evidence, not a runtime version pin.

C2. Mock tests cover catalog identity/availability, missing/duplicate IDs,
advertised controls and absent readback, explicit restriction, resume drift,
exact effective readback, default no-mutation planning, native repair capability refusal, fail-stop launch
readback and no restart/send repair paths. This cloud environment has no Paseo
executable or daemon; no live permission switches, plugin installations, provider
accounts or runtime acceptance are claimed. After operator-authorized install,
verify current UI/CLI/MCP children and resumed agents on each available provider,
including negative drift and unsupported-field diagnostics. Unsupported cases
remain open until authoritative native evidence is available.
