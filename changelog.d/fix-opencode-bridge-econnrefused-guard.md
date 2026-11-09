### Fixed

- `bin/opencode-plugin-guard` can now clear Paseo's blank OpenCode model list: run without `--check`, it patches the `paseo-managed-bridge` plugin's stale-binding check (OpenCode's Bun reports a refused connection as `error.code === "ECONNREFUSED"`, which the plugin missed, so every bind returned HTTP 500 after a Paseo daemon restart). On demand only, no restart; upstream getpaseo/paseo#8780. (#281)
