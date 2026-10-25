# agents/ templates

The four config files that matter most were tracked nowhere
([docs/ade-everywhere-proposal.md](../docs/ade-everywhere-proposal.md) section 2 and 8 item 1). Phase 0
item 4.4 (2026-10-20) tracks them here as **templates**: the live file's structure, key order and comments, with
every secret, account id, host name and home path replaced by a placeholder. This is the section 4.2 layout
(`agents/<tui>/<file>.tmpl`); nothing here is applied yet. The proposal's chezmoi apply (section 4.4) will render
these with the companion's data, as a `modify_` merge and never a symlink, because each app also writes its own file.

| Template | Live file | Notes |
|---|---|---|
| [claude/settings.json.tmpl](claude/settings.json.tmpl) | `~/.claude/settings.json` | Claude Code also writes it (plugins, tui); a merge keeps unowned keys |
| [codex/config.toml.tmpl](codex/config.toml.tmpl) | `~/.codex/config.toml` | Codex writes `[projects.*]`, `[hooks.state.*]`, `[marketplaces.*]` |
| [opencode/opencode.json.tmpl](opencode/opencode.json.tmpl) | `~/.config/opencode/opencode.json` | opencode reads `opencode.jsonc` too; that file is a 50-byte `$schema` stub, so it is not templated. `tui.json` and `cli.json` beside them hold no secrets and are not templated yet |
| [hermes/config.yaml.tmpl](hermes/config.yaml.tmpl) | `~/.hermes/config.yaml` | Hermes writes it too; `~/.hermes` is its own git repo |

## Codex tool environment (2026-10-25)

`[shell_environment_policy]` in `codex/config.toml.tmpl` decides which variables a Codex tool command gets. It is
`inherit = "all"` plus an exact legacy `include_only` allowlist: the variables `inherit = "core"` gave (`HOME LANG
LC_ALL LC_CTYPE LOGNAME PATH SHELL TEMP TMP TMPDIR USER`, read back from Codex 0.164.0 on macOS), the four Herdr
owner ids (`HERDR_ENV HERDR_WORKSPACE_ID HERDR_TAB_ID HERDR_PANE_ID`), the two routing paths seen in a live Codex process
on 2026-10-25 (`HERDR_SOCKET_PATH HERDR_BIN_PATH`, service locations, not identity) and the `set` keys. Any other
`HERDR_*` (`HERDR_SESSION`, `HERDR_ACTIVE_*`, plugin variables) stays out. Outside Herdr none of the six exists, so none
appears; no value is written into the file. `acp-run` drops the four owner ids from the agents it starts; the relay
deliverer keeps no owner id. `tests/test_codex_shell_env_policy.py` pins it,
including a read-back through the installed `codex app-server` (no model call).

1. `include_only` runs after `set` (probed 2026-10-25, Codex 0.160.1, 0.163.0, 0.164.0): add a `set` key and its
   name to the allowlist together.
2. The newer `filters` table is not used: Codex 0.163.0 ignores it, and `inherit = "all"` would then pass every
   variable.
3. The live file is a regular file Codex also writes; there is no renderer yet. To change only the policy tables:
   `bin/codex-env-policy-apply TEMPLATE TARGET` (dry run, set values hidden; `--write` applies, and does nothing if already applied) replaces the two `shell_environment_policy` tables (and the comment above
   them) byte-for-byte, checks that every other table and the `set` values are unchanged, keeps a private (0600, O_EXCL) `.bak-UTC-TIME-env-policy`
   copy, writes a temp file beside the target and `os.replace`s it on the realpath, refusing if the file changed
   while it ran. A running Codex keeps the policy it started with; only sessions started after the change see it.

## Placeholder syntax

1. `{{ .field }}` is a value the companion provides (table below).
2. `{{ secret "NAME" }}` is a secret read from `sudo-secretspec` at apply time. `NAME` is the entry name where it
   is known (`JINA_API_KEY`, `EXA_API_KEY`:
   [skills/fallback-chains/references/web-access.md](../skills/fallback-chains/references/web-access.md) 5.1,
   5.6); a `TODO_` prefix means no entry is declared yet, so the name is a proposal.
3. `${NAME}` inside the Hermes template is Hermes's own reference to `~/.hermes/.env`; it is not a placeholder
   and stays as it is.
4. No other `{{ }}` form is allowed. `bin/ade-template-check` enforces all of this.

## Quoting (2026-10-20)

Every placeholder sits inside a quoted scalar, so a value with `#`, `: `, a quote or a leading `*`, `&` or `!`
cannot truncate itself or add keys. The renderer escapes the value for the quote it sits in:

1. JSON `"..."` and TOML basic `"..."`: JSON escapes of the value, without the outer quotes (chezmoi `toJson` with
   the outer quotes trimmed, or `quote`). TOML also forbids a raw DEL, which the escape must write as `\u007f`.
2. YAML `'...'`: every `'` doubled. A value with a newline or other control character cannot be single-quoted
   faithfully (YAML folds a newline to a space), and one in a comment (`sipb_llm_upstream_host`) would end the
   comment: the Phase 1 renderer refuses a value with a control character for any YAML placeholder.
3. TOML literal strings (`'...'`) and unquoted YAML or TOML values cannot carry a placeholder.
4. `home` and `home_escaped` are filled as they are (a home path is assumed to have none of these characters, and `home_escaped`
   is already escaped for the JSON string inside TOML).

`bin/ade-template-check` enforces it: it renders a second time with `a'b"c: #d\e` in every placeholder but the home
ones, escaped as above, and each parsed string must equal that value; an unquoted placeholder fails to parse or
parses to something else.

## Fields

| Field | Meaning | Example shape | Companion provides it from |
|---|---|---|---|
| `home` | the operator's home directory; every absolute home path is `{{ .home }}/...` | `/Users/alex` or `/home/alex` | the chezmoi built-in home dir, `operator.toml` `home` |
| `home_escaped` | `home` with each `/` written `\/` (Codex's `notify` carries a JSON string inside TOML) | `\/Users\/alex` | derived from `home` |
| `chatgpt_app` | where `ChatGPT.app` lives (Codex's node_repl, CLI path and notify helper point inside it) | `/Applications/ChatGPT.app` | `machines/<host>.toml` `chatgpt_app` |
| `codex_browser_client_sha256s` | comma-separated SHA-256 digests of the browser clients Codex trusts (app-bundle specific) | two 64-hex digests joined by a comma | `machines/<host>.toml`, copied from a working install |
| `discord_home_channel_id` | Hermes's Discord home channel id; also the free-response channel | 19-digit string | `operator.toml` `[discord]` |
| `discord_home_channel_name` | display name of that channel, inside single quotes (see Quoting) | `Example server / #general` | `operator.toml` `[discord]` |
| `discord_user_id` | the operator's Discord user id | 19-digit string | `operator.toml` `[discord]` |
| `hermes_dashboard_user` | Hermes dashboard basic-auth user name | `alex` | `operator.toml` `[hermes]` |
| `signal_account` | the phone number Hermes's Signal gateway runs as, also its home channel | `+15555550100` | `machines/<host>.toml` `[signal]` |
| `sipb_llm_upstream_host` | host name of the SIPB LLM server behind the local proxy (a comment) | `llms.example.edu` | `operator.toml` `[sipb]` |

## Secrets

| Secret | Used by | Why a secret |
|---|---|---|
| `JINA_API_KEY` | opencode `mcp.jina.headers.Authorization` | plaintext Bearer key in the live file (web-access.md 5.3.2) |
| `EXA_API_KEY` | opencode `mcp.exa.headers.x-api-key` | plaintext key in the live file (web-access.md 5.3.2) |
| `TODO_BEZALEL_API_KEY` | codex `mcp_servers.bezalel.http_headers.Authorization` | plaintext Bearer token in the live file; Hermes's `.env` calls it `MCP_BEZALEL_API_KEY` |
| `TODO_LITELLM_HERMES_KEY` | hermes `providers.litellm-local.api_key` | a `sk-` style key for the local LiteLLM proxy |
| `TODO_HERMES_DASHBOARD_PASSWORD_HASH` | hermes `dashboard.basic_auth.password_hash` | a scrypt hash; offline-guessable, so treated as a secret |

## Kept as-is (machine-specific, not secret)

1. Model lists and provider catalogs (SIPB, Cline, LiteLLM, opencode `provider.sipb.models`).
2. Loopback ports of the shared MCP servers and proxies: 8890 (sipb-llms-proxy), 4000 (LiteLLM), 18765 (Signal
   bridge), 18790, 18796, 18798, 18800, 18802, 18804, 23373, 6806.
3. Homebrew-prefixed tool paths (`/opt/homebrew/...`, Apple silicon); a Linux apply needs a `brew_prefix` field
   or a per-OS branch (Phase 1).
4. `timezone: America/New_York` in the Hermes template and `/Applications/ExtraBar.app` in the Codex one.
5. Codex's plugin cache path and `BROWSER_USE_CODEX_APP_VERSION` (`26.915.31945`): Codex-managed, they change on
   its upgrade.
6. Public GitHub marketplace and plugin sources, and the `[projects.*]` trust list under `{{ .home }}`.

## Left out of the Codex template

`[hooks.state.*]` (Codex-written trust hashes of the hook files; Codex recomputes them), the two `[projects.*]`
entries under `/private/tmp` (session scratch with a session id in the path), and `last_revision` lines in
`[marketplaces.*]` (Codex-written git SHAs).

## Checking

```
bin/ade-template-check            # credential scan + render-and-parse of every template
bin/ade-template-check --diff     # also: key paths that differ from the live file (never values)
```

Exit 0 clean, 1 findings. It needs no live file (CI runs it through `tests/test_ade_template_check.py`); YAML needs
PyYAML (`uv run --with pyyaml`). A new template goes in `agents/<tui>/`, its live path in `LIVE` in the tool, and
every new placeholder in the tables above.
