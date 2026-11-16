# claude-settings-apply (st-apply, 2026-11-15)

`bin/ade-settings-apply` (module `bin/ade_settings_apply.py`) merges `agents/claude/settings.json.tmpl` into the live
`~/.claude/settings.json`; `bin/ade-update` runs it (`--check` = dry-run, otherwise `--apply`) in the canonical checkout
when the template and the live file exist. Operator ruling 2026-11-15; lead rulings R1-R6.

1. **Hooks (ADE-owned only).** A hook whose command runs a script under `~/src/djbclark-ade/` or `~/.claude/{hooks,helpers}/`
   is matched per event by (script path, first non-flag argument). Live wins: a live `|| exit 0` wrapper is kept and no unwrapped
   duplicate is added. A template hook with no live twin is added as its own group. Other hooks (paseo, collie) are never applied.
2. **`permissions.deny`** is a union; no live entry is removed.
3. **Everything else:** a template key path absent from live is added only under `/sandbox`, `/modelSettings` and `/skillOverrides`
   (the `ADD_ABSENT` tuple; `env`, plugins, marketplaces, helpers and the rest are listed, never auto-added, so a deliberate absence
   or an injected template key cannot reach every session). `sandbox.filesystem.denyRead` is a union like `permissions.deny`. An
   existing live value is never overwritten or removed. A differing scalar (`model`, `deniedMcpServers`) is only listed as
   "template differs, not applied". One branch (`walk` in `merge`) to drop if the add-absent rule is withdrawn.
4. **Dry-run by default**, key paths only (never values), except the full `/sandbox` block when it would be added (it changes Bash
   behaviour for every new session). `--apply` copies live to `settings.json.bak-<UTC stamp>` (mode kept), writes a temp file beside
   and `os.replace`s it onto the realpath, and refuses (exit 1, nothing written) if a live key path would disappear.
5. `--render-template` prints the merged result with the home path as `{{ .home }}`; that is how the template is re-refreshed.
6. `bin/ade-update` reads the template from the committed revision (`git show <target>:...`), never the working tree. An ADE hook
   that differs from live only in matcher or timeout is listed ("live kept"), not changed. The apply re-reads live before the
   replace and aborts if it changed; backups are created exclusively (never overwrite an earlier one).
