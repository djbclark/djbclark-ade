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
IDs/controls, Pi's modeless catalog, and unverified providers refuse ordinary
creation with a diagnostic. Retired omp/OpenCode routes are not restored.

`agent.open.before` checks saved mode/control evidence on resume, refresh and
import; missing evidence or drift refuses opening. This hook can check or refuse,
not mutate saved modes. History reads do not open a runtime and remain allowed.
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

Source contracts were inspected at upstream `4df5307e` (0.16.0-beta.2 source).
Older hosts without the catalog/control SDK report unavailable rather than
claiming coverage. This cloud run had no Paseo executable/daemon; mocked tests
prove local planning and calls, not installed runtime behavior.
