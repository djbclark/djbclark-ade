# Pi agent profiles (2026-11-03)

## Profiles

`.pi/agents/astra-worker.md` and `.pi/agents/frontier-astra.md` are the canonical
Pi `subagent` profiles and ship in this repository. Installed copies live in
`~/.pi/agent/agents/`; installing or refreshing them is a manual step, nothing in
this repo copies or links them. Pi's `subagent` extension ([docs/pi-subagent.md](pi-subagent.md))
reads user profiles from `~/.pi/agent/agents/` and project profiles from the nearest `.pi/agents/`.

Both pin `openai/gpt-6-astra:high`. They deliberately do **not** pass the ACP
`frontier-exec` advise-only gate (`ACP_OPERATOR_APPROVED=frontier-exec`, see
[docs/gates.md](gates.md)): native Pi use of Astra was authorized by the operator on
2026-11-03, and these profiles run in Pi directly, not through `acp-run`/`acp-dispatch`.
