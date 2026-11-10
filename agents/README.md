# agents/ templates

The config files that matter most were tracked nowhere
([docs/history/ade-everywhere-proposal.md](../docs/history/ade-everywhere-proposal.md) section 2 and 8 item 1). Phase 0
item 4.4 (2026-10-20) tracks them here as **templates**: the live file's structure, key order and comments, with
every secret, account id, host name and home path replaced by a placeholder. This is the section 4.2 layout
(`agents/<tui>/<file>.tmpl`); nothing here is applied yet. The proposal's chezmoi apply (section 4.4) will render
these with the companion's data, as a `modify_` merge and never a symlink, because each app also writes its own file.
Phase 1 (2026-11-09) declares secret names and field homes; the owned-key `modify_` merge helpers for Claude and
Codex landed 2026-11-10 under `agents/claude/modify_merge.py` and `agents/codex/modify_merge.py` (shared algorithm in
`agents/modify_merge_lib.py`). Chezmoi source-state wiring that calls them on apply is still deferred (queue item 12);
the helpers refuse the operator's live `~/.claude/settings.json` and `~/.codex/config.toml` until that slice.

**Current TUIs (Pi sole-TUI policy, 2026-11-09):** Claude Code, Codex, Hermes, and Pi as the sole general-purpose
third-party client. Pi has **no** `agents/pi/` template here yet (it shares `~/.agents/skills` with Codex via
`skill-everywhere`; its own runtime config stays outside this tree until templated). omp/OpenCode are retired live
targets; the OpenCode template row below is **history only**.

**Current TUIs (Pi sole-TUI policy, 2026-11-09):** Claude Code, Codex, Hermes, and Pi as the sole general-purpose
third-party client. Pi has **no** `agents/pi/` template here yet (it shares `~/.agents/skills` with Codex via
`skill-everywhere`; its own runtime config stays outside this tree until templated). omp/OpenCode are retired live
targets; the OpenCode template row below is **history only**.

| Template | Live file | Notes |
|---|---|---|
| [claude/settings.json.tmpl](claude/settings.json.tmpl) | `~/.claude/settings.json` | Claude Code also writes it (plugins, tui); [claude/modify_merge.py](claude/modify_merge.py) keeps unowned keys |
| [codex/config.toml.tmpl](codex/config.toml.tmpl) | `~/.codex/config.toml` | Codex writes `[projects.*]`, `[hooks.state.*]`, marketplace `last_revision`; [codex/modify_merge.py](codex/modify_merge.py) keeps them |
| [hermes/config.yaml.tmpl](hermes/config.yaml.tmpl) | `~/.hermes/config.yaml` | Hermes writes it too; `~/.hermes` is its own git repo |
| [opencode/opencode.json.tmpl](opencode/opencode.json.tmpl) | `~/.config/opencode/opencode.json` | **Retired TUI (2026-11-09).** Kept as an archive template until cleanup; not a current apply target. opencode also read `opencode.jsonc` (a 50-byte `$schema` stub, never templated). |

## Codex tool environment (2026-10-25)

`[shell_environment_policy]` in `codex/config.toml.tmpl` decides which variables a Codex tool command gets. It is
`inherit = "all"` (operator ruling, 2026-10-25: a tool keeps the launching terminal's environment, which restores the
Herdr (retired from djbclark-ade 2026-10-31; the variables still pass through under `inherit = "all"`) pane ids `HERDR_ENV HERDR_WORKSPACE_ID HERDR_TAB_ID HERDR_PANE_ID`, the routing paths `HERDR_SOCKET_PATH
HERDR_BIN_PATH`, and multiplexer and runtime variables such as `TERM`, `TMUX` and `SSH_AUTH_SOCK`), with Codex's default
`KEY`/`SECRET`/`TOKEN` name exclusions kept on (`ignore_default_excludes = false`) and the `set` keys applied after
them. There is no `include_only` allowlist: an arbitrary terminal environment reaches tools by decision. Outside Herdr
no `HERDR_*` variable exists, so none appears; no value is written into the file. Prefer native `paseo run` for new
agents; the Wave 6 shims `tools/acp-run` (via `bin/acp-dispatch`) and `skills/session-finder/relay.py` still drop the
four owner ids / keep no owner id until deletion. `tests/test_codex_shell_env_policy.py` pins the policy, including a
read-back through the installed `codex app-server` (no model call).

1. `ignore_default_excludes = false` is the one filter: it removes variables whose names contain `KEY`, `SECRET` or
   `TOKEN` before `set` runs. `set` values are never removed by it.
2. Do not add `include_only` or `filters` without an operator decision: Codex 0.163.0 ignores `filters`, and
   `include_only` runs after `set`.
3. The live file is a regular file Codex also writes and it holds credentials (MCP headers, tokens): **never `rg`,
   `grep -C`, `cat` or diff it, or print any context around the policy; use the helper's dry run.**
   `bin/codex-env-policy-apply TEMPLATE TARGET` prints a diff of the policy span only (the two `shell_environment_policy`
   tables and the comment block above them, old against new; only the template's own lines and `inherit`/`ignore_default_excludes` literals print, every other assignment line (including its key), comment and continuation is hidden;
   no line of any neighbouring table); `--write` applies it and does nothing if already applied. It replaces that span
   byte-for-byte, checks that every other table and the `set` values are unchanged, keeps a private (0600, O_EXCL)
   `.bak-UTC-TIME-env-policy` copy, writes a temp file beside the target and `os.replace`s it on the realpath, and
   refuses (exit 1, nothing replaced) if the file changed after it was read or after the temp file was written.
   Table headers may have trailing TOML comments; their comments remain hidden in the diff.
    Diagnostics name files and `set` keys, never values; a TOML parse error is reduced to line and column.
   A running Codex keeps the policy it started with; only sessions started after the change see it.
4. Detached fallback. Native `paseo run` and the transitional `acp-run` / relay deliverer already drop the four owner
   ids. A headless command started any other way from a Codex tool (for example `codex exec` or a worker script outside
   ACP) inherits the whole Codex environment (including the six Herdr names), so it must clear the owner ids itself:
   `env -u HERDR_ENV -u HERDR_WORKSPACE_ID -u HERDR_TAB_ID -u HERDR_PANE_ID COMMAND`. `HERDR_SOCKET_PATH` and
   `HERDR_BIN_PATH` are service routing, not identity, and may stay.

## Placeholder syntax

1. `{{ .field }}` is a value the companion provides (table below; example homes in [`companion/`](../companion/)).
2. `{{ secret "NAME" }}` is a secret read from `sudo-secretspec` at apply time. `NAME` must be declared in
   [`secrets/secretspec.toml`](../secrets/secretspec.toml) and listed in the Secrets table below.
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

Each field has a home in the private companion. Public examples (keys only, no operator data) live under
[`companion/`](../companion/).

| Field | Meaning | Example shape | Companion provides it from |
|---|---|---|---|
| `home` | the operator's home directory; every absolute home path is `{{ .home }}/...` | `/Users/alex` or `/home/alex` | chezmoi built-in home dir, or `operator.toml` `home` ([example](../companion/operator.toml.example)) |
| `home_escaped` | `home` with each `/` written `\/` (Codex's `notify` carries a JSON string inside TOML) | `\/Users\/alex` | derived from `home` at render time |
| `chatgpt_app` | where `ChatGPT.app` lives (Codex's node_repl, CLI path and notify helper point inside it) | `/Applications/ChatGPT.app` | `machines/<host>.toml` `chatgpt_app` ([example](../companion/machines/host.toml.example)) |
| `codex_browser_client_sha256s` | comma-separated SHA-256 digests of the browser clients Codex trusts (app-bundle specific) | two 64-hex digests joined by a comma | `machines/<host>.toml` `codex_browser_client_sha256s` |
| `discord_home_channel_id` | Hermes's Discord home channel id; also the free-response channel | 19-digit string | `operator.toml` `[discord].home_channel_id` |
| `discord_home_channel_name` | display name of that channel, inside single quotes (see Quoting) | `Example server / #general` | `operator.toml` `[discord].home_channel_name` |
| `discord_user_id` | the operator's Discord user id | 19-digit string | `operator.toml` `[discord].user_id` |
| `hermes_dashboard_user` | Hermes dashboard basic-auth user name | `alex` | `operator.toml` `[hermes].dashboard_user` |
| `signal_account` | the phone number Hermes's Signal gateway runs as, also its home channel | `+15555550100` | `machines/<host>.toml` `[signal].account` |
| `sipb_llm_upstream_host` | host name of the SIPB LLM server behind the local proxy (a comment) | `llms.example.edu` | `operator.toml` `[sipb].llm_upstream_host` |
| `brew_prefix` | Homebrew prefix for tool paths on Linux apply (not yet substituted in templates) | `/home/linuxbrew/.linuxbrew` | `machines/<host>.toml` `brew_prefix` |

## Secrets

Declared in [`secrets/secretspec.toml`](../secrets/secretspec.toml) (Phase 1, 2026-11-09). Values stay in
`sudo-secretspec`.

| Secret | Used by | Why a secret |
|---|---|---|
| `JINA_API_KEY` | retired OpenCode template `mcp.jina.headers.Authorization` | plaintext Bearer key in the live file (archive only) |
| `EXA_API_KEY` | retired OpenCode template `mcp.exa.headers.x-api-key` | plaintext key in the live file (archive only) |
| `MCP_BEZALEL_API_KEY` | codex `mcp_servers.bezalel.http_headers.Authorization` | plaintext Bearer token in the live file; Hermes `.env` uses the same name |
| `LITELLM_HERMES_KEY` | hermes `providers.litellm-local.api_key` | a `sk-` style key for the local LiteLLM proxy |
| `HERMES_DASHBOARD_PASSWORD_HASH` | hermes `dashboard.basic_auth.password_hash` | a scrypt hash; offline-guessable, so treated as a secret |

## Kept as-is (machine-specific, not secret)

1. Model lists and provider catalogs (SIPB, Cline, LiteLLM; retired OpenCode `provider.sipb.models` stays in the archive template).
2. Loopback ports of the shared MCP servers and proxies: 8890 (sipb-llms-proxy), 4000 (LiteLLM), 18765 (Signal
   bridge), 18790, 18796, 18798, 18800, 18802, 18804, 23373, 6806.
3. Homebrew-prefixed tool paths (`/opt/homebrew/...`, Apple silicon); a Linux apply substitutes `brew_prefix` from
   `machines/<host>.toml` (field home declared above; templates still hard-code the Mac prefix until that apply).
4. `timezone: America/New_York` in the Hermes template and `/Applications/ExtraBar.app` in the Codex one.
5. Codex's plugin cache path and `BROWSER_USE_CODEX_APP_VERSION` (`26.915.31945`): Codex-managed, they change on
   its upgrade.
6. Public GitHub marketplace and plugin sources, and the `[projects.*]` trust list under `{{ .home }}`.

## Codex hooks (2026-11-09)

`agents/codex/config.toml.tmpl` carries inline `[[hooks.PreToolUse]]` / `[[hooks.PostToolUse]]` for
`secret_read_gate.py` (matcher `Bash|Edit|Write|apply_patch`) and `bin/post-edit-check --hook` (matcher
`Edit|Write|apply_patch`). Prefer this form over a second `~/.codex/hooks.json` at the user layer (Codex merges both and
warns). `[features] hooks = true` is already on. Live apply of the template into `~/.codex/config.toml` waits for the
operator (order 11); after apply, trust the new handlers in `/hooks`. Docs: `docs/secret-deny.md`,
`docs/post-edit-check.md`.

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
PyYAML (`uv run --with pyyaml`). A new template goes in `agents/<tui>/`, its live path in `LIVE` in the tool, every
new field in the Fields table and `companion/*.example`, and every new secret in the Secrets table and
`secrets/secretspec.toml`.

## Owned-key `modify_` merge helpers (2026-11-10)

Claude and Codex configs are read-modify-write targets: the app also writes the file, so apply must keep unowned
live keys and only set keys the rendered template owns. The helpers take already-rendered desired content (no
secret reads here) and a live document:

```
agents/claude/modify_merge.py --desired RENDERED.json --live LIVE.json [--write OUT.json]
agents/codex/modify_merge.py  --desired RENDERED.toml --live LIVE.toml [--write OUT.toml]
```

`--live` defaults to stdin and omit `--write` to print the merge (chezmoi `modify_` shape). Dicts merge
recursively; lists and scalars from the template replace. Live-only keys stay (Claude plugins/tui extras; Codex
`[hooks.trust.*]`, `/private/tmp` `[projects.*]`, marketplace `last_revision`). `--write` refuses the real
`~/.claude/settings.json` and `~/.codex/config.toml`. Shared algorithm: [`modify_merge_lib.py`](modify_merge_lib.py);
tests in `tests/test_agents_modify_merge.py`.
