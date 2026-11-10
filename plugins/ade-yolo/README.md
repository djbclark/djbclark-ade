# ade-yolo (Paseo plugin)

Restores the ADE YOLO / Bypass policy for every new Paseo agent.

| Hook | Behaviour |
| --- | --- |
| `agent.create.before` | Set `config.modeId` to the provider's unattended mode (`bypassPermissions`, `full-access`, OpenCode `build` + `auto_accept`, …) when the create would otherwise start in Always Ask (`default`), `auto`, `acceptEdits`, or with no mode. |

## Why

Wave 4 E6 mapped ordinary launches to each provider's `defaultMode`, and the slim-down deleted `paseo-bypass-watch` / `paseo-new-seat`'s Bypass flip. MCP subagents and UI seats then opened in Always Ask and stalled on the first tool call. Standing policy is YOLO; restrictive review stays on `bin/review-launch` and explicit `plan` / `read-only`.

External malicious / prompt-injection content (untrusted GitHub artifacts) is handled as **data** under AGENTS.md Trust and the review boundary — not by leaving agents in Always Ask.

## Opt out

- Create with `modeId: "plan"` or `"read-only"` (kept).
- Set metadata `ade-yolo.skip: true` on the create request.

## Install (operator only)

```bash
paseo plugin install /absolute/path/to/djbclark-ade/plugins/ade-yolo
paseo plugin ls --json   # id=ade-yolo → enabled/running
```

`ade-install` / doctor observe the catalog row and **never** install or enable this plugin.
