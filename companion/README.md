# Companion field homes (Phase 1)

Examples for the private companion data the `agents/` templates read. Declarations of
secrets live in [`../secrets/secretspec.toml`](../secrets/secretspec.toml); values stay in
`sudo-secretspec`.

| Example | Becomes (private companion) | Holds |
|---|---|---|
| [`operator.toml.example`](operator.toml.example) | `operator.toml` | `home`, `[discord]`, `[hermes]`, `[sipb]` |
| [`machines/host.toml.example`](machines/host.toml.example) | `machines/<hostname>.toml` | `chatgpt_app`, `codex_browser_client_sha256s`, `brew_prefix`, `[signal]` |

`home_escaped` is derived from `home` at render time (each `/` → `\/`). Chezmoi `modify_`
merges for Claude and Codex are still deferred (queue item 12); these files only name the
homes so Phase 1 can stop using `TODO_*` proposals.
