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
requests, so a ready, modeless Pi catalog is unattended by construction and the create passes unchanged
(no mode is invented). A Pi catalog that lists modes, or is not enabled/ready, gets no exemption. The
allowlist (`UNATTENDED_BY_CONSTRUCTION`) is not generalised to other providers. Retired omp/OpenCode routes are not restored.

`agent.open.before` checks saved mode/control evidence on resume, refresh and
import. **Drift** (evidence present and contradicting) refuses. **Missing evidence** refuses only for agents
this plugin created: `agent.create.before` stamps those with metadata `ade-yolo.applied`. An agent without
that stamp is *legacy* (created before the plugin was installed, Hermes included; the SDK exposes no
install time, so "no stamp" is the exact equivalent): missing evidence is allowed and logged
(`ade-yolo: <id>: legacy agent without saved mode evidence; allowed`), with no catalog lookup. If the
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

The plugin is not installed by this repo. Run in order; stop and roll back on the first failure.

1. Install and verify: `paseo plugin install /Users/djbclark/src/djbclark-ade/plugins/ade-yolo`, then
   `paseo plugin ls --json` shows `ade-yolo` enabled/running.
2. Enumerate: `paseo provider ls --json`; canary every provider that is enabled (claude, codex,
   antigravity, pi, cursor if present). Skip disabled ones and say so.
3. For each, create a throwaway agent with a one-line prompt, e.g.
   `paseo run --provider <provider>/<model> --json -- "reply with the word ok"`, then verify mode readback:
   `bin/ade-agent-mode check <agent-id> --json` reports `status=verified` (Claude `bypassPermissions`,
   Codex/Antigravity `full-access`, Cursor `auto_accept`). **Pi:** creation must succeed and no mode readback
   exists (modeless by design). Archive each throwaway agent afterward.
4. Resume one pre-existing idle agent (not Hermes): `paseo send <idle-agent-id> "ok"`. It must open; the
   daemon log shows the `legacy agent without saved mode evidence; allowed` line when it has no saved mode.
5. Confirm Hermes is untouched: `paseo ls -g --json` still lists it with the same id/status, and a
   `paseo send` to it opens (legacy allow) with no `ade-yolo` refusal.
6. Negative check: a create with metadata `ade-yolo.skip: true` or mode `plan` still creates restricted.

Rollback (exact): `paseo plugin remove ade-yolo` (the uninstall; `paseo plugin disable ade-yolo` is the
reversible off switch), then `paseo plugin ls --json` shows no `ade-yolo` row.

Source contracts were inspected at upstream `4df5307e` (0.16.0-beta.2 source).
Older hosts without the catalog/control SDK report unavailable rather than
claiming coverage. This cloud run had no Paseo executable/daemon; mocked tests
prove local planning and calls, not installed runtime behavior.
