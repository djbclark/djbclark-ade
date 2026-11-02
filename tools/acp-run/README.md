# acp-run

Run one prompt through a coding agent over the
[Agent Client Protocol](https://agentclientprotocol.com) (ACP), headless, and get
the agent's final message on stdout. It is how one agent on this machine hands a
self-contained task to another vendor's agent: Claude Code, Codex, Copilot,
opencode, Cursor, Qwen Code, Devin, Cline, Hermes, Antigravity (`agy`), Grok and
zcode (through the third-party `zcode-acp-server`). Vendor, model, effort and
context for each agent are in the 2026-10-15 section below. acp-run sets
`ZCODE_BIN` to that package's `vendor/zcode.cjs` when the file is present, so
`--model` works (fixed 2026-10-15; the 2026-10-11 "refuses every switch" note
was the missing variable, measured while the weekly limit was also exhausted).
A 2026-10-15 prompt still died at the z.ai login (`project_token_login_failed`),
which is outside acp-run.

A single-file [uv script](https://docs.astral.sh/uv/guides/scripts/) on the
official Python SDK (`agent-client-protocol`); no daemon, no state beyond its
logs. MIT licensed. The SDK is pinned below 1.0 until 1.0 is tested.

```sh
acp-run --list                                  # agents and the command each runs
acp-run claude --info                           # modes, config options, auth methods
acp-run codex -C ~/src/repo --add-dir ~/.local/state/bigteam/task -p 'Reply with exactly: OK' --model gpt-6-astra
acp-run copilot -C ~/src/repo -f brief.md --perm deny --timeout 1200 > report.md
acp-run codex -C ~/src/repo --interactive --inbox /tmp/codex-in   # a session you keep prompting
```

## What it adds over a bare ACP client

1. **A per-agent table**: the launch command for each agent, per-agent default
   config options (`DEFAULT_SET`), each agent's own auto-approve mode (`YOLO_SET`),
   and environment set-up where an agent needs it.
2. **A permission policy** answering every `session/request_permission`.
   acp-run runs yolo for every agent (operator 2026-10-14): there are three
   policies, `all`, `read-only` (2026-10-19) and `deny`. `read-only`: the agent
   may read and change nothing. Its read-only tools (ACP kinds `read`, `search`,
   `fetch`) run without a permission request and are answered yes if they ask;
   any other tool trips the tripwire (exit 77) and any other request is refused.
   claude gets a session whose built-in tools are only Read, Grep, Glob, LS,
   WebFetch and WebSearch (`_meta.claudeCode.options.tools`; no user settings, no
   MCP servers, mode `default`); codex the `read-only` mode (its sandbox runs shell commands
   unasked, so an unasked `execute` does not trip there, 2026-10-19); opencode a
   `permission` block (`OPENCODE_CONFIG_CONTENT`) allowing read, glob, grep, list,
   webfetch, websearch and denying the rest; zcode `plan` mode with the backend session
   limited to Read, Glob, Grep, LS, WebFetch and WebSearch and Bash, Write, Edit and the
   other mutating tools removed (`zcode-denylist-shim.cjs`, below). Every other agent is
   refused with exit 2 and a one-line reason (no equivalent mode verified);
   `acp-run <agent> --info` lists the `perm_modes` an agent supports. `deny` gives
   claude no tools at all, so it is for a text-only answer, never a review that
   has to read. The old `scoped:P1,P2` and `ask` are still
   accepted for old callers but are not enforced: each prints one line,
   `acp-run: warning: --perm <value> is no longer enforced: acp-run runs yolo
   for every agent (treated as --perm all); use --perm read-only for a read-only
   run`, and the run is exactly `--perm all` (`ask` no longer needs
   `--interactive`).
   - `all` (default): allow everything, including under `--interactive`.
   - `deny`: refuse everything, and make the agent actually ask (2026-10-12,
     after an adversary review found four agents ran tools without ever asking):
     claude-agent-acp gets a session with no built-in tools, no user settings
     (so no `bypassPermissions` default or allow rules), no MCP servers and no
     bypass (`_meta.claudeCode.options`), then mode `default`; zcode starts in
     `plan` (`ZCODE_ACP_MODE`) with its tools removed from the session and a per-run
     settings file (`ZCODE_CLI_SETTINGS_FILE`, removed afterwards) with MCP servers,
     plugins, skills, subagents and hooks off. The tool removal is
     `tools/acp-run/zcode-denylist-shim.cjs`, started as `ZCODE_BIN` from the per-run dir
     (2026-10-24): `zcode app-server --stdio` ignores `--disallowed-tools` (so
     `ZCODE_DISALLOWED_TOOLS` and the settings file's `permission.disallowedTools` removed
     nothing; a live read-only run was offered Bash and ran `ls` unasked, since plan mode
     lets read-only shell through) and zcode-acp-server's `session/create` carries no
     `toolDenylist`. The shim adds `toolDenylist` (`ZCODE_DISALLOWED_TOOLS`) and
     `toolAllowlist` (`ZCODE_ACP_RUN_ALLOWLIST`: the reading tools under read-only, a name
     no tool has under deny) to `session/create`, `session/resume` and `session/send`
     (`send` takes no allowlist). Without a real `vendor/zcode.cjs` the run fails with
     exit 1 (config) rather than start unguarded. Left over under deny: the Task and
     plan-mode control tools; the two read-only built-in MCP tools
     (`mcp__web_reader__webReader`, `mcp__4_5v_mcp__analyze_image`) under read-only;
     agy runs in mode `default`; crush runs without `--yolo` (now added only
     under `all`) and, since 2026-10-13, with **no tools at all** (below);
     opencode gets `OPENCODE_CONFIG_CONTENT={"permission":"deny"}`.
     Grok under `--perm deny` drops `--always-approve` and runs on a per-run
     `GROK_HOME` (Per-agent choices, item 6).
     A tripwire backs this up: any non-think tool call that starts or completes
     without a permission request cancels the turn and exits 77. The `claude -p`
     fallback runs with `--tools ""`, `--strict-mcp-config`, `--disallowedTools '*'`
     and `--setting-sources project` (no user hooks), and always reads its prompt
     from stdin. `--tripwire-exempt-kinds read,search` lets tool calls of those
     read-only ACP kinds run unasked without tripping (failover passes it for agy
     only; any other kind is a usage error). Options are never abbreviated (`allow_abbrev=False`): `--per all`
     is an error, not `--perm all`.
     Since 2026-10-13 a `deny` run that is not `--interactive` also starts
     **opencode and agy without the user's plugins, MCP servers and hooks**
     (claude and zcode already ran that way). On the 2026-10-13 SkillOpt-Sleep
     night all 21 failed attempts died while the agent started: opencode's
     "Location plugins did not finish activating" and agy's "MCP: 7 server(s)
     still connecting after 32s". Neither agent has a switch for it, so each gets
     a per-run 0700 temp config, removed after the run; the user's own files are
     only read, never changed:
     - opencode (v2.0.27): `OPENCODE_CONFIG_DIR=<tmp>` replaces
       `~/.config/opencode` as its global config directory, so the plugin dirs
       there (`plugins/rtk.ts`, ...) are never scanned. `<tmp>/opencode.json`
       holds only `$schema`, `provider`, `model`, `small_model`,
       `enabled_providers`, `disabled_providers` and `experimental.max_retries`
       from the user's `opencode.json`/`opencode.jsonc` (and `OPENCODE_CONFIG`,
       which is then unset): no `mcp`, `plugin`, `agent`, `command`, hooks.
       `OPENCODE_DISABLE_PROJECT_CONFIG=1` (and `OPENCODE_CONFIG_PROJECT_DISABLE=1`)
       skips project `.opencode/` dirs and `opencode.json` files. Logins
       (`opencode-go/`) live in opencode's data dir and still work. Not stripped:
       skills in `~/.claude/skills` and `~/.agents/skills` (opencode reads them
       with no switch to turn it off) and any `.well-known` remote config.
     - agy: `GEMINI_HOME=<tmp>` is a shadow like `~/.local/share/agy-acp-home`
       (symlinks to everything in `~/.gemini`, login included) whose `config/`
       has an empty `mcp_config.json`, an empty `hooks.json` and an empty
       `plugins/` (agy plugins carry their own MCP servers and hooks). Workspace
       `.agents/` plugins in `-C` are not stripped.
     - crush (crush-acp 88a67503, `crush_strip_config`): `CRUSH_GLOBAL_CONFIG=<tmp>/config`
       holds a `crushrc` that defines no-op shell functions `mcp`, `lsp`, `hook`
       and `permissions` (crush's interpreter resolves a function before its
       config builtin; checked against the real build), passes `option` through
       only for `request-timeout`, `disable-skill`, `auto-summarize`,
       `provider-auto-update`, `default-providers` and `metrics`, then `source`s
       the user's `crushrc` in place (its provider and API key are never copied).
       A user `crush.json` there is copied with only `$schema`, `providers`,
       `models` and a few options. Moving the config dir also drops crush's
       global context files (`CRUSH.md` beside it, `AGENTS.md` above it), and
       `CRUSH_SKILLS_DIR=<tmp>/skills` (empty) lists no global skill. A user
       `crushrc` that says `command`/`builtin` before a config builtin, or
       `unset -f`, could get past the shadows, so the strip refuses it (the run
       keeps the user's config and says so; tools stay off either way). Not
       scanned: files the user's `crushrc` itself `source`s.
     **crush under every `deny` run (`crush_deny_dir`, 2026-10-13):** crush-acp asks
     permission for `bash`, `edit`, `write`, `fetch` and `download`, but runs its
     read-only tools (`glob`, `grep`, `ls`, `view`, `sourcegraph`, LSP lookups)
     and bash's built-in safe commands without asking; on the 2026-10-13 03:43
     SkillOpt-Sleep canary it ran `glob` unasked and the tripwire fired. Neither
     ACP mode (`ask`, `code`) changes that. Crush builds each agent's tools from an
     allow list (`allToolNames()` minus `options.disabled_tools`), so acp-run
     disables every name on it (`CRUSH_TOOLS`) in two per-run config layers:
     `CRUSH_GLOBAL_DATA=<tmp>/data` (merged after the user's global config) and
     the workspace file under `--data-dir <tmp>/project` (merged last, after any
     project `crush.json`/`crushrc`), with `auto_lsp: false` and
     `permissions.skip_requests: false`. Crush merges config arrays by appending,
     so no other layer can take a tool back off the list. MCP servers a project
     config names (from `-C` up to the git root) get `disabled: true` there.
     `--data-dir` also keeps crush's session database out of `-C`. The catalog
     cache `providers.json` is copied in. This half has no fallback and applies
     with `--interactive` and `--keep-user-config` too; it is logged as a
     `deny_config` record. Result (2026-10-13, the real failover preflight): the
     canary prompt got 0 tool calls (the model wrote a fake `<bash ...>` as text),
     no file, rc 0; `Reply with exactly: OK` answered OK.
     The log gets a `user_config` record naming what was stripped (server, plugin
     and key names only, never values) and the result record `user_config:
     "stripped"`. `--keep-user-config` or `ACP_RUN_KEEP_USER_CONFIG=1` keeps the
     user's config (logged as `"action": "kept"`); if the temp config cannot be
     built, or an opencode config file cannot be read or parsed (JSONC with
     comments and trailing commas is fine), the run keeps it too and says so on
     stderr, naming the file. `--perm all` and `--interactive` runs are
     unchanged unless `--strip-user-config` is given.
     `--strip-user-config` (env `ACP_RUN_STRIP_USER_CONFIG=1`, 2026-10-13) applies
     the same strip under any non-interactive `--perm` for opencode, agy, crush,
     zcode and grok. It is a startup-reliability switch, not a permission control: the
     SkillOpt-Sleep night runs `--perm all --strip-user-config` (operator,
     2026-10-13). Outside deny nothing permission-related is added: opencode gets
     no `OPENCODE_CONFIG_CONTENT`, agy and zcode keep their `--perm all` yolo modes,
     crush keeps every built-in tool (a per-run `crush-strip-` data dir and
     `--data-dir` with only `auto_lsp: false` and project MCP servers disabled,
     logged as `strip_config`; crushrc `mcp`/`lsp`/`hook`/`permissions` shadowed as
     under deny), and zcode gets a per-run `ZCODE_CLI_SETTINGS_FILE` with MCP,
     plugins, skills and hooks off and the user's `permission` block untouched.
     Temp dirs are `acp-run-<agent>-strip-<pid>-*` and are swept like deny dirs.
     Under `--perm deny` the flag adds nothing; `--keep-user-config` wins.
     Hardening after the adversary review (2026-10-13): config layers are
     deep-merged as opencode does; a literal secret in a provider block (an
     `apiKey`-, `token`-, `secret`-like key or any `headers` value) goes to the
     child as `ACP_RUN_OPENCODE_SECRET_<n>` and appears in the file only as
     `{env:...}` (values that are not printable ASCII, or contain a quote,
     backslash or brace, stay in the 0600 file and are listed in
     `secrets_in_file`); relative `{file:x}` references are made absolute. This
     is **not secret-free**: the env var reaches every child process the agent
     starts (LSP servers, formatters, crash dumps). What it buys is that nothing
     secret is left on disk after a SIGKILL. The temp dir is built after the
     signal handlers are in place and removed before the cancel/kill waits
     (opencode, zcode) or right after the agent has been stopped (agy, which can
     still write a rotated credential under its home while it shuts down), so
     SIGTERM and early errors leave nothing behind. It is not removed right after `session/new`: opencode
     watches its config dir and reloads on change, and agy keeps reading its
     home. Dirs are named `acp-run-<agent>-deny-<pid>-*`, and every deny run
     first sweeps this user's such dirs under the temp base that are older than
     3 hours, belong to a dead pid (1-7 digits; anything else is never swept),
     and are real dirs (never symlinks): that covers runs killed with SIGKILL.
     A failing sweep only prints a warning; it never stops the run.
3. **`--add-dir DIR` (repeatable)**: add extra workspace roots sent as
   `additionalDirectories` in `session/new`. If advertised in `initialize` (in
   `agentCapabilities` or `sessionCapabilities`), it is sent directly; if
   unadvertised, it is still sent, falling back with a one-line log to a retry
   without it if rejected. Lets an agent whose file tools are confined to its
   workspace roots read and write outside `-C` (such as `acp-dispatch` report
   folders). **agy ignores it** (2026-10-11): agy_acp_server 1.3.0 accepts the
   field but never passes it to its allowed-directory list, so agy's file tools
   still refuse paths outside `-C`.
4. **`--model`, `--mode`, `--effort LEVEL`, `--context SIZE` and `--set ID=VALUE`**
   for any config option `--info` lists. Since 2026-10-15, `--effort` and
   `--context` are the normalized names (`256k`, `500k`, `1m`, and the other
   sizes that agent's section lists). Order: provider, model, other `--set`
   and mode, then effort, then context. A value the agent or the chosen model
   cannot take is a usage error (exit 2) before any prompt, and it lists the
   valid values. qwen, zcode and agy do not clamp. Stderr, before the summary
   line: `acp-run: applied: model=... effort=... ctx=...` (also on the JSONL
   `result` record as `applied`, a separate `applied` record, and `--json`).
   Unreadable values are `(unverified)`. A requested value the agent reports
   differently is failure class `config`, exit 1. On cursor,
   `--set reasoning_effort=LEVEL` hits only option id `reasoning_effort`
   (`grok-4.7`, `claude-sonnet-5-5`, `claude-haiku-5-5`, `gemini-4-argon`,
   `gemini-3.8-flash`). Use `--effort` on the other cursor models.
   `--info --model M [--effort] [--context] [--set]` applies that combination
   with no prompt. `--info --all-models` is the per-model option matrix.
   The per-agent section below is the table.
5. **An audit trail**: every ACP event is logged as JSONL (default
   `~/.local/state/acp-run/`), ending with a `result` record (summary and exit
   code), and one summary line goes to stderr: stop reason, seconds, tool calls,
   permissions allowed/denied, tokens, cost, failure class, log path.
6. **Timeouts that cancel the turn** (`session/cancel`), and a bounded handshake
   with retries (`--handshake-tries`), falling back to `claude -p` for the
   `claude` agent when its ACP session never starts (`--no-fallback` to disable).
   The fallback runs as a known conversation (`claude -p --session-id`: the
   `--session-id UUID` you pass, else a fresh one) and logs it as `new_session`,
   so a later `--resume` reaches exactly that conversation. Over ACP,
   claude-agent-acp chooses the id and gives it to Claude as `--session-id`, so
   the logged `new_session` id is already Claude's own.
   `--handshake-timeout` (env `ACP_RUN_HANDSHAKE_TIMEOUT`) bounds `initialize`
   and `session/new` each: 40 s by default, 90 s for `claude`, whose
   `session/new` takes 13 s on an idle machine and 17-24 s under heavy load.
   Each handshake try starts a fresh agent after a timeout, or after a
   `transient` ACP error in `initialize` or `session/new` (backoff 1, 2, 4..
   10 s; nothing has run yet, so a retry repeats nothing). Added 2026-10-13
   after opencode's `ServiceUnavailableError` ("Location plugins did not finish
   activating") failed 24 `session/new` calls in one night with no retry. Quota,
   plan, auth and unclassified errors are not retried. The timeout error names
   the step that hung (`initialize hung`, `session/new hung`).
   A prompt that finishes on the same tick as a 1 s poll times out is taken as
   finished. Before 2026-10-13 it was reported as a timeout (exit 124), which
   threw away two good answers.
   `--wrapup-grace S` (off by default; `acp-dispatch` passes 300) sends one more
   prompt after the timeout cancel (`--wrapup TEXT`, default "time is up, write
   your final report now") and waits up to S seconds, so a slice cut off in a
   hung command still writes its report; the run still exits 124 and the summary
   says `wrapup=<stop reason|timeout|skipped|error>`. Added 2026-10-10 after an
   opencode slice with verified work lost its report to a `git commit` whose
   pre-commit Gradle hook queued on the machine-wide Gradle slot.
   `--timeout 0` removes the turn deadline and disables the wrap-up turn;
   handshake limits still apply. While waiting, acp-run checks `<log>.extend`
   at intervals of at most 30 seconds. Write a nonnegative whole number of
   seconds there to add to the current deadline, or `0` to remove it. Positive
   extensions leave an unlimited turn unlimited. The file is consumed and
   deleted; malformed input is logged and ignored. `deadline_extended` records
   carry the old and new monotonic deadlines (`null` means unlimited). A costly
Go advisory turn (`--go-advisory`, see the OpenCode Go section) never extends:
acp-run deletes the file, logs `deadline_extension_refused` and keeps the deadline
fixed at start + `--timeout` (at most 600 s), so a hand-edited control file cannot
bypass it either.
7. **Safe permission answers**: only an offered `allow_once` or `reject_once`
   option is ever selected. Never an `*_always` option, which an agent may save
   beyond this run (Hermes writes `allow_always` to a permanent allowlist), and
   never `cancelled`, which cancels the whole turn. An allow with no
   `allow_once` offered becomes a `reject_once`; with neither offered the agent
   gets a JSON-RPC error. A tool call with no kind gets one inferred from its
   title (`Edit ...` is an edit, as acpx does), logged as `inferred_kind` in the
   permission record.
8. **Delivery checks.** Agents report some provider failures as a normal answer
   (`end_turn`). acp-run fails such a turn (exit 1, a `FAILED <class>` line on
   stderr, `"failure"` in `--json`) when the whole short reply is a refusal
   (`Upgrade your plan to continue`), when it is the model declining the task
   (`Sorry, I cannot fulfill your request ...`: class `refused`, never retried, and
   acp-dispatch records it as NO-REPORT), or when the reply ends in a provider or
   transport error line (`Error: RetriableError: [unavailable] PING timed out`),
   reported as "reply truncated; edits may be present". ACP errors are classified
   the same way: `quota`, `plan`, `auth` or `transient`. The patterns are a short
   table at the top of the script (`FAILURE_CLASSES`, `REPLY_REFUSALS`,
   `MODEL_REFUSALS`, `TAIL_ERROR`).
9. **Opt-in prompt retry** (`--prompt-retries N`, default 0): a prompt that fails
   with a transient error before any tool call or permission request is retried
   with backoff (1, 2, 4 s, at most 10 s). Quota, plan and auth failures are not
   retried.
10. **Opt-in machine-load guard** (`--max-load L`, env `ACP_RUN_MAX_LOAD`): refuse
   to start (exit 75) while the 1-minute load average per CPU core is above `L`;
   `--load-wait SECS` (env `ACP_RUN_LOAD_WAIT`) waits up to that long for the
   load to drop first. Off by default.
11. **Clean interrupts**: SIGINT/SIGTERM send `session/cancel`, stop the agent
    and exit 130/143, so a killed run does not leave the agent running.
12. **An interactive mode** (`--interactive`, below): one ACP session that stays
    open for more prompts, from a terminal, a pipe or a drop directory.
13. **Verify-and-retry (`--verify CMD`)**: an opt-in verify loop for models that end
    their turn early (`end_turn`) before finishing work. Runs `CMD` as a shell command
    with `-C DIR` as cwd (exit 0 = pass). If `CMD` fails, acp-run sends a follow-up
    prompt into the same session with the exit code and truncated output (last 40
    lines, max 3000 chars), instructing the agent to fix the problem and retry.
    Retries up to `--verify-retries N` times (default 2), with `--verify-timeout SECS`
    (default 180) per check run. Respects the overall `--timeout` deadline.
    The run summary (stderr line, `--json`, and JSONL log `result` record) records
    `verify=pass|fail` and `verify_attempts=<n>`. A final failed verification prints
    a warning on stderr and preserves exit 0 (off by default; callers decide).

    ```sh
    acp-run crush -C dir -p '...' --verify 'python3 -m unittest' --verify-retries 2
    ```

## Per-agent choices: vendor, model, effort, context (2026-10-15)

Landed 2026-10-15 (6528ccf, 77bd2bf, 0221561, faead67, ada7620). Value lists are from that agent's `--info` on this Mac that day. Regenerate: `acp-run <agent> --info --all-models` (per-model option matrix, no prompt). One combination, no prompt: `acp-run <agent> --info --model M [--effort L] [--context S] [--set ID=VALUE]`.

1. `--effort`: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra`, `default`. Aliases, not clamps: `extra-high`=`xhigh`, `off`=`none`. `--context`: `200k`, `256k`, `272k`, `400k`, `500k`, `1m`, or a positive integer (`k`=1000, `m`=1,000,000).
2. Order, every agent: provider, model, other `--set` and mode, effort, context. A model switch resets effort and context and changes which values exist.
3. A LEVEL or SIZE the agent or model cannot take exits 2 before any prompt and names the valid values. qwen, zcode and agy do not clamp. agy `xhigh`/`max` exit 2.
4. Read-back, stderr before the summary line: `acp-run: applied: model=... effort=... ctx=...`. Same fields on the JSONL `result` record (`applied`), a separate `applied` record, and `--json`. Unreadable values are marked `(unverified)` (`effort=high(unverified)`). A requested value the agent reports differently is failure class `config`, exit 1 (option response before the prompt, or `usage_update.size` after the turn). Under `--interactive` the line is still printed; a post-turn window mismatch does not change the exit code.
5. `--meta JSON` deep-merges into `session/new` `_meta` over `systemPrompt` and the deny meta. `--agent-arg ARG` (repeatable) appends to the launch command. `--agent-env K=V` (repeatable; one argument may be `K=V,K2=V2`, split only before another `NAME=`) appends to the child environment. Per host, `~/.config/acp-run.env` or `$ACP_RUN_ENV_FILE`: `ACP_RUN_ARGS_<AGENT>` (shell-split), `ACP_RUN_ENV_<AGENT>="K=V,K=V"`.
6. `HERDR_PANE_ID`, `HERDR_ENV`, `HERDR_WORKSPACE_ID` and `HERDR_TAB_ID` (the last two since 2026-10-25, when the Codex tool environment began to pass the herdr ids on), `PASEO_AGENT_ID`, `PASEO_AGENT_CWD` and `ORCA_TERMINAL_HANDLE` and `ADE_OPENCODE_SESSION_ID` and `ADE_OPENCODE_DIRECTORY` are removed on every run, and `ACP_RUN_AGENT=1` is set (2026-10-20: `bin/self-slash` refuses lifecycle actions when it sees the marker; a slice that kept `PASEO_AGENT_ID` could `/clear` or archive the caller's Paseo agent). (`ACP_RUN` itself is taken: it holds the acp-run path for `session-finder`.) Under `--perm deny`, grok starts without `--always-approve` on a per-run `GROK_HOME`: symlinks to `~/.grok` except `hooks/`, `skills/`, `plugins/`, `installed-plugins/` and `config.toml`. The copy drops `[[hooks.*]]`, `[plugins]`, `[mcp_servers.*]`, `ui.permission_mode`, `ui.yolo`, and ends with `[permission] ask = ["*"]` (deny > ask > allow). tomllib requires the copy to equal the original minus exactly those parts; otherwise grok keeps the user's home and the run says so. A token rewritten as a regular file in the temp home is copied back. `--strip-user-config` is the same strip without the permission table. Every other non-interactive grok run (`--perm all`, what `acp-dispatch` uses) also starts on a stripped `GROK_HOME` without the user's hooks, skills and plugins (2026-10-15), keeping MCP servers, the permission mode and auth (no `ask` rule); the `user_config` log record names the `home`. `ACP_RUN_GROK_USER_HOOKS=1` (or `--keep-user-config`) keeps `~/.grok`; `--interactive` always does.
7. `acp-dispatch --effort` and `--context` are first-class. Checked with the model before anything is written (`acp-run <agent> --info --model M --effort E --context C`), stored on the job record, kept by `resume`. `--acp-arg` still forwards other flags; a dash-leading value needs `--acp-arg=--meta`. zcode `--model` is accepted and still optional.
8. No `--fast`. Use `--set fast=on|off` (claude Opus only), `--set fast=true|false` (cursor), `--set fast-mode=on|off` (codex), or a model id (`grok-4.7-build-fast`, copilot `claude-opus-4.8-fast`). Thinking budget: `--agent-env MAX_THINKING_TOKENS=N` or `ACP_RUN_ENV_CLAUDE`. Not implemented (exit 2, or not a flag): hermes shadow home for effort/context, crush `/set_reasoning_effort`, opencode/qwen context caps (`OPENCODE_CONFIG_CONTENT` `limit.context` untested; a cap cannot raise a window), agy `--auth-method` (`AGY_ACP_DEFAULT_MODEL` via `ACP_RUN_ENV_AGY`), `ZCODE_ACP_QUOTA_AUTO_RESUME=0` (operator's choice). Claude `--context 1m` does not add `[1m]`.

(The `ocx-*` grok ids, OpenAI models via the opencodex proxy on `127.0.0.1:10100`, went with the proxy on 2026-10-19.) Cursor `--set reasoning_effort=LEVEL` hits only option id `reasoning_effort`: `grok-4.7`, `claude-sonnet-5-5`, `claude-haiku-5-5`, `gemini-4-argon`, `gemini-3.8-flash`. Other cursor models use option `effort` or `reasoning`; use `--effort`.

`pick_config` tries every option of a category and ignores a trailing `(openai)` or `[1m]` (`--model qwen3.8-max` selects `qwen3.8-max(openai)`). An ambiguous short name exits 2 (hermes `claude-sonnet-5.5`). `--info` without `--model` is the default model's options only. hermes and crush `--info` include `session/new`'s `models`.

### claude

https://code.claude.com/docs/en/model-config — claude-agent-acp 0.90.0, Claude Code 2.1.300.

Provider is inherited env only (`ANTHROPIC_BASE_URL`, `CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX`). No `--provider`. Until 2026-10-19 this Mac's `HTTPS_PROXY` was the opencodex intercept `127.0.0.1:10200`, which added GPT rows (descriptions starting `opencodex`) to claude's model list; the proxy is uninstalled and the list is Anthropic-only again.

`--model` (unique-token match): `default`/`opus` = Opus 5.5, `fable` = Fable 5.1, `sonnet` = Sonnet 5.5, `haiku` = Haiku 5.5, `claude-sonnet-5`, `claude-opus-5`, `claude-fable-5`, `claude-opus-4-8`, `claude-opus-4-7`, `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`. TUI also `best`, `opusplan`, full ids, `[1m]`.

Effort option `effort`: `low` `medium` `high` `xhigh` `max`, plus `default`. No `xhigh` on Opus 4.6 or Sonnet 4.6. No option on Haiku 4.5 and older. Defaults: `high`; Opus/Sonnet/Haiku 5.5 `medium`; Opus 4.7 `xhigh`. `ultracode` is a setting, not a level. Also `CLAUDE_CODE_EFFORT_LEVEL`, settings `effortLevel` / `modelSettings` (`max` refused there), `ultrathink`.

Context: Fable 5.1, Fable 5, Sonnet 5, Sonnet 5.5, Haiku 5.5, Opus 4.7+ are 1M native. Opus 4.6 and Sonnet 4.6 are 200K, 1M only via `[1m]` (plan dependent) — `--context 1m` does not add that suffix. `--context 200k` sets child `CLAUDE_CODE_DISABLE_1M_CONTEXT=1` (haiku `usage_update.size` 1000000 to 200000). `--context 1m` leaves the model's own window. Other sizes exit 2. A 1m request that comes back 200k is `FAILED config`. Auto-compact 100K–1M: `--autocompact`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW`. Gateway: `CLAUDE_CODE_MAX_CONTEXT_TOKENS`.

Fast option `fast` `on`/`off` only on `opus`, `claude-opus-5`, `claude-opus-4-8`. Not on fable, sonnet, haiku, Opus 4.7, Opus 4.6. Extended thinking is always on for 5.5 and Fable.

### codex

https://developers.openai.com/codex/config-reference , openai/codex#53742, #53336 — codex-acp 2.2.2 (@openai/codex 0.160.1), cli 0.162.1.

Env `MODEL_PROVIDER`, `CODEX_API_KEY`, `OPENAI_API_KEY`, or `--oss --local-provider lmstudio`/`ollama`. This Mac: ChatGPT Plus. No `--provider`.

Models: `gpt-6.1-sol`, `gpt-6-astra`, `gpt-6-sol`, `gpt-6-luna` (user default), `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`. Hidden: `gpt-reserve`, `codex-auto-review`.

Effort option `reasoning_effort`. `low medium high xhigh max ultra` on gpt-6.1-sol, gpt-6-astra, gpt-6-sol, gpt-5.6-sol, gpt-5.6-terra. No `ultra` on gpt-6-luna, gpt-5.6-luna. Defaults: 6.1-sol, 6-astra, 5.6-sol `low`; the rest `medium`. CLI docs also list `minimal`. TUI: `-c model_reasoning_effort`, `/model`.

Context is fixed by the model: gpt-6.1-sol 500000 (475000 effective); every other visible model 272000 (258400); all have `max_context_window` 872000 and `effective_context_window_percent` 95. `--context 500k` only with `--model gpt-6.1-sol`; `--context 272k` only on the others; anything else exits 2 (the message names `--model gpt-6.1-sol`). Does not change the model. The launch-time `CODEX_CONFIG` (`model_context_window`, merged with any `CODEX_CONFIG` already in the env, `ACP_RUN_ENV_CODEX` or `--agent-env`; a value that is not a JSON object exits 2) is how the size is set; on codex 0.162.1 / codex-acp 2.2.2 (400000 reads 380000, 200000 reads 190000, gpt-6.1-sol 800000 reads 760000) the path works. Read-back after the turn: `usage_update.size` must be SIZE × 95% (rounded, 1 token slack), else failure class `config`, exit 1; the `applied:` line shows `ctx=400k/380000` (requested/effective).

Fast: `--set fast-mode=on` or `off` (all 7). `service_tier` `fast` (priority) / `flex` / default. Priority copy: 6.1-sol and 6-astra "2x speed, increased usage"; 6-sol and 6-luna "1.5x speed"; 5.6 "1.5x speed, increased usage". `features.fast_mode`.

### copilot

https://github.blog/changelog/2026-06-04-larger-context-windows-and-configurable-reasoning-levels-for-github-copilot/ , https://docs.github.com/en/copilot/reference/ai-models/supported-models , github/copilot-cli#3481 — CLI 1.0.95.

GitHub login only. Not passed through: `COPILOT_PROVIDER_TYPE` `openai`/`azure`/`anthropic`, `_BASE_URL` `_API_KEY` `_API_KEY_COMMAND` `_BEARER_TOKEN` `_WIRE_API` (`completions`/`responses`) `_TRANSPORT` (`http`/`websockets`) `_MODEL_ID` `_WIRE_MODEL` `_MAX_PROMPT_TOKENS` `_MAX_OUTPUT_TOKENS` `_HEADERS`, `COPILOT_OFFLINE=true`.

Models: `auto` (listed twice, first wins; ACP starts on `claude-sonnet-5.5`, not TUI `model: auto`), `claude-sonnet-5.5`, `claude-sonnet-5`, `claude-fable-5.1`, `claude-fable-5`, `claude-opus-5.5`, `claude-opus-5`, `claude-opus-4.8`, `claude-opus-4.8-fast` (fast mode; 30× `_meta.copilotUsage`), `claude-haiku-5.5`, `claude-haiku-4.5`, `gpt-6.1-sol`, `gpt-6-sol`, `gpt-6-luna`, `gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.3-codex`, `gpt-5-mini`, `mai-code-1.1-flash`, `gemini-3.8-flash`, `gemini-3.7-flash`, `grok-4.7`, `grok-4.6`, `grok-4.5`, `kimi-k3`, `gemini-4-argon`. `copilot help config` also `claude-sonnet-4.6`. **That is the CLI 1.0.95 catalog; what a given account is offered differs: `acp-run copilot --info` on djbclark's account, CLI 1.0.105, 2026-11-02, lists 15 ids: `auto`, `claude-sonnet-5.5`, `claude-sonnet-5`, `claude-haiku-5.5`, `claude-haiku-4.5`, `gpt-6-luna`, `gpt-6.1-terra`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.3-codex`, `mai-code-1.1-flash`, `gemini-3.8-flash`, `grok-4.7`, `grok-4.6`, `kimi-k3` (no Opus, Fable, Sol, Astra; `pick_config` rejects any id not offered, so run `--info` before dispatching a model).** `--auto-tier efficiency|balance|intelligence` is not wired (`COPILOT_AUTO_TIER`, model `auto` only).

Effort option `reasoning_effort` (launch `--reasoning-effort` is the same knob and survives a model switch). CLI set `none minimal low medium high xhigh max`; picker is the subset; default `medium`. `low,medium,high,xhigh,max`: sonnet-5.5, sonnet-5, fable-5.1, fable-5, opus-5.5, opus-5, opus-4.8, opus-4.8-fast, haiku-5.5, gpt-6-astra (each prefixed `claude-` or bare gpt as in the model list). `none,low,medium,high,xhigh,max`: gpt-6.1-sol, gpt-6-sol, gpt-6-luna, gpt-5.6-sol, gpt-5.6-terra, gpt-5.6-luna. `none,low,medium,high,xhigh`: gpt-5.5, gpt-5.4, gpt-5.4-mini. `low,medium,high,xhigh`: gpt-5.3-codex, grok-4.7, grok-4.6. `low,medium,high`: gpt-5-mini, mai-code-1.1-flash, gemini-3.8-flash, gemini-3.7-flash, grok-4.5, gemini-4-argon. `low,high,max`: kimi-k3. No option: `auto`, `claude-haiku-4.5` (CLI `--reasoning-effort` with `--model auto` exits 1).

Context is a launch flag, not an ACP option: `200k`/`256k`/`272k` → `--context default`; `1m` → `--context long_context`; else exit 2. `--model` is repeated on that server command, because `session/set_config_option model` resets the tier (measured 272000 vs 922000). Read-back by tier: ≤300000 default, ≥800000 long. Measured default 272000 (gpt-5.4, gpt-5.5); long 922000 on gpt-5.5 (picker "1.1M"); long costs more credits. Copilot's 1M table, not filtered by acp-run: Claude Sonnet 4.6/5/5.5, Opus 4.8/5/5.5 and fast, Haiku 5.5, Fable 5/5.1, GPT-5.3-Codex, 5.4, 5.5, 5.6 Luna/Sol/Terra, GPT-6 Astra/Luna/Sol, 6.1 Sol, Kimi K3. A miss is `FAILED config`. TUI: `/model`+Tab, `contextTier`, `/model --session`.

### opencode

https://opencode.ai/docs/models/ , https://opencode.ai/v2/docs/models , https://models.dev/api.json — 2.0.29.

Connected: alibaba 58, alibaba-cn 90, opencode (Zen) 44, opencode-go 31, sipb 19 (242 ids, same as `opencode models`). Provider is the slash prefix. Examples: `opencode/claude-opus-5-5`, `opencode/claude-sonnet-5-5`, `opencode/claude-fable-5-1`, `opencode/gpt-6-sol`, `opencode/gpt-6.1-sol`, `opencode/gpt-5.5`, `opencode-go/glm-5.3`, `opencode-go/kimi-k3`, `opencode-go/deepseek-v4-pro`, `opencode-go/qwen3.8-max`, `sipb/qwen3.6:35b-a3b-q4_K_M`. No user `model`: `opencode-go/gemini-4-argon-contributor`. Dashes, not dots. TUI `/models`, `opencode run -m provider/model[#variant]`. Effort is re-read after a second model set (the first response can still be the previous model's list).

Effort option `effort`; `default` = no variant, always offered. Groups plus `default`, 2026-10-15. `none,low,medium,high,xhigh,max`: opencode/claude-opus-5-5, gpt-6-astra, gpt-6-sol, gpt-6.1-sol, opencode-go/deepseek-v4-pro, gpt-6-luna, grok-4.6. `low,medium,high,xhigh,max`: opencode/claude-fable-5-1, claude-sonnet-5, claude-sonnet-5-5, claude-haiku-4-5, gpt-6-luna (Zen), grok-4.7, deepseek-v4-pro (Zen), opencode-go/claude-haiku-5-5. `none,low,medium,high,xhigh`: gpt-5.5, gpt-5.5-pro, gpt-5.4-nano, gpt-5.3-codex-spark. `low,medium,high,xhigh`: gpt-5.4-mini, grok-build-0.1, opencode-go/grok-4.7, hy3. `medium,high,xhigh`: gpt-5.6-terra. `minimal,low,medium,high,xhigh`: muse-spark-1.3-contributor-free, nemotron-3-ultra-free, opencode-go/qwen3.7-plus. `minimal,low,medium,high`: gemini-3.8-flash. `low,medium,high`: opencode/gemini-4-argon, glm-5.3, gemini-3.5-flash-lite, opencode-go/glm-5.2, cat-jam-free, every `sipb/*`. `low,high,max`: kimi-k3, gemini-3.1-pro, gpt-5.3-codex, deepseek-v4.1-flash (Zen), opencode-go/gemini-4-argon-contributor. Also `none,high,max` / `high,max` / `max` / `none,thinking` / `none,low,medium,xhigh` / `none,low,high,max` / `none,low,high` on Alibaba, Qwen, Longcat, Muse, Space-Bunny, Kimi-code, Hy4. No effort option on 97 Alibaba/Qwen/DeepSeek-R1 ids. No fast switch (`#variant` is effort).

Context exits 2. `limit.context`: opencode/claude-opus-5-5 1000000; gpt-6-sol 1050000 (`input` 922000); opencode-go/glm-5.2 1000000; kimi-k3 1048576; most Qwen/Alibaba 131072–262144. Missing limit treated as 200000 (`sipb`; servers run ~32K). `compaction.*`.

### cursor

https://cursor.com/docs/models/grok-4-7 , https://cursor.com/docs/cli/reference/parameters , https://cursor.com/docs/cli/acp — cursor-agent 2026.10.14-0f9edde. No prompt sent.

`--model` is the plain id. Rejected: presets (`grok-4.7-high-fast`) and brackets (`claude-opus-4-8[context=1m,effort=high,fast=false]`). `default` = Auto. Vendors covered below: Claude Fable 5.1/5, Opus 5.5/5/4.8/4.7/4.6/4.5, Sonnet 5.5/5/4.6/4.5/4, Haiku 5.5/4.5; GPT-5.6 Sol/Terra/Luna, 5.5, 5.4, 5.4 mini/nano, 5.3 Codex, 5.2, 5.1, 5 mini; Gemini 4 Argon, 3.8/3.7/3.6/3.5/3 Flash, 3.1 Pro, 2.5 Flash; Grok 4.7/4.6/4.5; Composer 2.5; Muse Spark 1.3; Kimi K3, K2.7 Code; GLM 5.2, 5.3, 5.3 Flash.

`--effort`: category `thought_level`, never id `thinking`. `xhigh` = `extra-high`. `--context`: option `context`, or exit 2 if the model has none. Grok 4.7 input above 256k is 2×; Fast is 3×. Fast is the Premium default. `--set fast=true|false`, `--set thinking=true|false` only where listed.

1. Grok 4.7: context `256k`/`500k`; [reasoning_effort] default `high` of `low`/`medium`/`high`/`xhigh`; fast `false`/`true`.
2. Grok 4.6: [effort] `low`/`medium`/`high` (default)/`xhigh`; fast. Grok 4.5: [effort] `low`/`medium`/`high` (default); fast default `true`. Composer 2.5: fast only, default `true`.
3. Opus 5.5: context `300k`/`1m`; [effort] default `medium` of `low`/`medium`/`high`/`xhigh`/`max`; fast. Opus 5 and 4.8: thinking; context `300k`/`1m`; [effort] default `high`, low through max; fast. Opus 4.7: same, effort default `xhigh`. Opus 4.6: thinking; context `200k`/`1m`; [effort] `low`/`medium`/`high`/`max` (no `xhigh`); no fast. Opus 4.5: thinking only.
4. Fable 5.1 and 5: thinking; context `300k`/`1m`; [effort] low through max, default high; no fast. Sonnet 5.5: context `300k`/`1m`; [reasoning_effort] low through max, default high. Sonnet 5: thinking, context, [effort]. Sonnet 4.6: thinking; context `200k`/`1m`; [effort] `low`/`medium`/`high`/`max`. Sonnet 4.5: thinking. Sonnet 4: thinking default `false`. Haiku 5.5: thinking; context `300k`/`1m`; [reasoning_effort] low through max. Haiku 4.5: thinking.
5. GPT-5.6 Sol/Terra/Luna: context `272k`/`1m`; [reasoning] default `medium` of `none`/`low`/`medium`/`high`/`xhigh`/`max`; fast. GPT-5.5 and 5.4: context `272k`/`1m`; [reasoning] `none`/`low`/`medium`/`high`/`extra-high`; fast. GPT-5.4 mini/nano: [reasoning] `none`/`low`/`medium`/`high`/`xhigh`. GPT-5.3 Codex: [reasoning] `low`/`medium`/`high`/`extra-high` (default `extra-high`); fast. GPT-5.2: [reasoning] low through `extra-high`; fast. GPT-5.1: `low`/`medium`/`high`. GPT-5 mini: none.
6. Gemini 4 Argon and 3.8 Flash: [reasoning_effort] `low`/`medium`/`high`. 3.7 Flash: [effort] `low`/`medium`/`high`. 3.6 Flash: [effort] `minimal`/`low`/`medium`/`high`. 3.1 Pro, 3 Flash, 3.5 Flash, 2.5 Flash: none.
7. Muse Spark 1.3: context `300k`/`1m`; [effort] `minimal`/`low`/`medium`/`high` (default)/`xhigh`/`max`. Kimi K3: [reasoning] `low`/`high`/`max` (default max). K2.7 Code: none. GLM 5.2: `high`/`max`. GLM 5.3 and 5.3 Flash: `low`/`high`/`max`.

### qwen

https://qwenlm.github.io/qwen-code-docs/en/users/configuration/model-providers/ , https://github.com/QwenLM/qwen-code/blob/main/docs/users/configuration/settings.md , QwenLM/qwen-code#8698 — 0.25.1.

Not a flag: `--auth-type` `openai` `openai-responses` `anthropic` `qwen-oauth` `gemini` `vertex-ai`. Entries live in `settings.json` `modelProviders.<authType>[]`. Here, 10 Coding Plan models at `https://coding-intl.dashscope.aliyuncs.com/v1`; Bailian `qwen3.8-max` at `https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1`. `--info` auth: `openai` only. Suffix `(openai)` is the authType. Live: `--model qwen3.8-max --effort low` → `qwen3.8-max(openai)`, effort low, ctx 1m.

Models: `qwen3.5-plus`, `qwen3.6-plus` (Pro only), `qwen3.7-plus`, `glm-5`, `kimi-k2.5`, `MiniMax-M2.5`, `qwen3-coder-plus`, `qwen3-coder-next`, `qwen3-max-2026-01-23`, `glm-4.7`, `qwen3.8-max`. Also `fastModel`, `advisorModel`, `--advisor`, `/model --fast --vision --voice --compaction --image`. `/model --fast` picks `fastModel`, not effort.

Effort option `reasoning_effort`: only a listed value. `none`/`default` only on `qwen3.5-plus`, `qwen3.6-plus`, `qwen3.7-plus`, `kimi-k2.5`, `qwen3-max-2026-01-23`. `qwen3.8-max`: `none` `low` `medium` `xhigh` (default `xhigh`); `high` and `max` exit 2. `glm-5`, `glm-4.7`, `MiniMax-M2.5`: `none` `default` `low` `medium` `high` `xhigh` `max`. Coders `qwen3-coder-plus`, `qwen3-coder-next`: no option. TUI `/effort` is the wider `low`–`max`. glm/MiniMax extra tiers may be `enable_thinking` no-ops on the Coding Plan (not re-checked with `--openai-logging`). Vendor notifications without a prefix are extension notifications.

Context exits 2. `generationConfig.contextWindowSize`: `qwen3.5-plus` `qwen3.6-plus` `qwen3.7-plus` `qwen3-coder-plus` 1000000; `kimi-k2.5` `qwen3-coder-next` `qwen3-max-2026-01-23` 262144; `glm-5` `glm-4.7` 202752; `MiniMax-M2.5` 196608; `qwen3.8-max` unset (models.dev; live turn 1m). A lower size only compacts earlier. `context.autoCompactThreshold` 0.85.

### cline

https://docs.cline.bot/cli/cli-reference , https://docs.cline.bot/usage/acp , https://docs.cline.bot/sdk/model-providers , cline/cline#14820 — 3.0.71.

`--set provider=cline` (313, usage billing), `cline-pass` (18; acp-run default, before the model), `openai-codex` (9). TUI `cline auth -p ID -k KEY -m MODEL` (30+ providers).

`cline/` examples: `anthropic/claude-sonnet-5.5` (default there), `claude-opus-5.5`, `claude-opus-5`, `claude-fable-5.1`, `claude-haiku-5.5`, `openai/gpt-6.1-sol` and `-pro`, `gpt-6-sol` and `-pro`, `gpt-6-luna` and `-pro`, `gpt-6-astra` and `-pro`, `x-ai/grok-4.7`, `grok-4.6`, `google/gemini-3.8-flash`, `meta/muse-spark-1.3`, `~openai/gpt-sol-latest`, `:free` (313). `cline-pass/`: `mimo-v2.6-flash` (ACP default), `mimo-v2.6-pro`, `deepseek-v4.1-flash`, `deepseek-v4-pro`, `glm-5.3`, `glm-5.3-flash`, `kimi-k3`, `qwen3.7-plus`, `qwen3.7-max`, `qwen3.8-max`, `minimax-m3`, `mimo-v2.5`, `mimo-v2.5-pro`, `muse-spark-1.3-contributor`. `cline-free/`: `solar-mini4`, `mimo-v2.6-flash`, `step-5-preview`, `muse-spark-1.3-contributor`. `openai-codex`: `gpt-6.1-sol`, `gpt-6-luna`, `gpt-6-sol`, `gpt-6-astra`, `gpt-5.6-luna`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.5`, `gpt-5.3-codex-spark`. TUI's saved `cline-pass/deepseek-v4.1-flash` is not the ACP start. `-pro` ids are models, not a fast flag.

`--effort` is launch `--thinking` `none` `low` `medium` `high` `xhigh`. `max` exits 2. `default` adds nothing. No ACP option: effort read-back `(unverified)`. Omitted, ACP sends `reasoning_effort: "none"` (file `~/.cline/data/settings/providers.json` says `medium` and is ignored). Bare CLI `--thinking` means medium. `--context` exits 2 (catalog window; `ModelInfo.contextWindow` for custom models only). `--compaction agentic|basic|off` (default `agentic`) is not `--context`.

### hermes

`~/.hermes/hermes-agent/website/docs/user-guide/features/acp.md` — 0.21.5. No provider prompt.

`config_options` null. `--model` is `session/set_model` on `session/new` `models` (436; `have:` shows 40 then "... N more"). Read-back `(unverified)`. `--set` is stored and ignored. Shape `provider:model` or `custom:name:model`. Counts: nous 64, openrouter 61, anthropic 13, openai-codex 13, copilot 30, copilot-acp 31, xai-oauth 14, alibaba 15, alibaba-cn 15, alibaba-coding-plan 10, opencode-zen 88, opencode-free 5, custom 77 (`custom:sipb-llms:*`). `model.provider` here `cline2`. Examples: `nous:anthropic/claude-fable-5.1`, `nous:openai/gpt-6-astra`, `nous:openai/gpt-6.1-sol`, `openai-codex:gpt-6.1-sol`, `anthropic:claude-opus-5`, `xai-oauth:grok-4.7`, `alibaba-coding-plan:qwen3.7-plus`, `opencode-zen:big-pickle`, `custom:sipb-llms:deepseek-r1:32b`. `claude-sonnet-5.5` is ambiguous and refused; `nous:anthropic/claude-sonnet-5.5` is not. Audit current: `custom:big-pickle`. Not persisted. `hermes --provider` is oneshot/tui only.

`--effort` exits 2. `config.yaml`: `agent.reasoning_effort` (`medium` here), `agent.reasoning_overrides`. Levels `none minimal low medium high xhigh max ultra`. Provider wire clamps: Codex GPT-6 Astra low through max (`ultra` dropped), Kimi K3 `low`/`high`/`max`, Grok 4.6+ through `xhigh`. TUI `--reasoning`, `/reasoning`. No `HERMES_HOME` shadow.

`--context` exits 2. Bigger window = model id `openai-codex:gpt-6-astra-900k`, `openai-codex:gpt-6-sol-900k`. Resolve: `model.context_length`, `providers.<p>.models.<m>.context_length`, `~/.hermes/context_length_cache.yaml`, endpoint, models.dev, else 128K. Cache: gpt-5.5 codex 272000, nous 1050000. `compression.threshold` 0.4, `threshold_tokens` 100000. `-pro` `-fast` `-flex` `-900k` are ids (`gpt-6-astra-pro` and the same suffixes).

### zcode

https://docs.z.ai/guides/llm/glm-5.3 , zcode-acp-server README — CLI 0.16.9, zcode-app-cli 3.15.3-35, server 0.69.3.

acp-run sets `ZCODE_BIN=<pkg>/vendor/zcode.cjs` when that file and `vendor/provider/zcode-builtin.json` exist. `--model` works because of that. Fixed 2026-10-15: earlier the server used `which zcode` (symlink, no `.js`), skipped `ZCODE_BUILTIN_PROVIDER_CONFIG_FILE`, and rejected every switch ("unsupported config option or switch failed: model"). The 2026-10-11 weekly-limit note was a different failure. Dispatch still allows omitting `--model` (two models). A 2026-10-15 prompt died `project_token_login_failed` at z.ai, same on the old binary. `--info` proven; a turn is not.

**Login that does not expire (2026-10-18): the account provider in manual mode.** `account:zai-individual-coding-plan` (the `builtin:zai-coding-plan\GLM-5.3` ids) has a second auth mode, the one the desktop app uses: with `account-provider:<id>:auth-source` = `manual` in `~/.zcode/v2/credentials.json` it sends the Coding Plan API key stored for that account and never does the OAuth exchange that fails a day after each `zcode login` (zai-org/feedback#1001). `bin/zcode-key-auth apply` sets it from sudo-secretspec's `ZAI_CODING_PLAN_API_KEY` (zcode's `enc:v1` AES-256-GCM, read from the 3.15.3 bundle); launchd re-checks every 6 h and pings only on a repair. Proved with a HOME holding no OAuth or JWT entry: a turn completed. **Never run `zcode login` now**: it writes `oauth` back (the launchd check undoes it). The paragraph below stays true: the separate API-key providers are still not selectable (#1067).

Provider switch not shown to work (2026-10-16: `builtin:zai` with a Coding Plan API key in `~/.zcode/v2/config.json` is listed and even becomes a new session's `currentValue`, but `set_config_option(model)` to it fails `Provider Registry 中不存在 Model`, `zcode --model builtin:zai/GLM-5.3 --prompt` exits 1 the same way, and `ZCODE_PROVIDER=builtin:zai` is ignored: every turn ran on `account:zai-individual-coding-plan`. Filed zai-org/feedback#1067; the key stays in sudo-secretspec as `ZAI_CODING_PLAN_API_KEY` for when a build can use it. Until then zcode is account login only, and an expired login is acp-dispatch class `auth`, zai-org/feedback#1001.) Plan ids: `account:{zai,bigmodel}-{individual,team}-coding-plan` and `start-plan`, `account:*-offpeak-idle-plan`, `account:*-highspeed-card` (10), plus `builtin:zai-coding-plan`, `builtin:zai` (API key), `builtin:bigmodel*`, `builtin:zai-start-plan`. Custom `~/.zcode/v2/provider_config.json`. Here only `builtin:zai-coding-plan` is on. `zai-start-plan` = `coding_plan_not_entitled`. Pin: `ZCODE_PROVIDER=builtin:zai-coding-plan`. Probes of `builtin:zai` and `builtin:zai-start-plan` still returned only coding-plan GLM-5.3.

Models: `builtin:zai-coding-plan\GLM-5.3`, `builtin:zai-coding-plan\GLM-5.3-Flash` (a bare `--model GLM-5.3` or `GLM-5.3-Flash` means the coding-plan id, 2026-10-24: the list also holds `builtin:zai\GLM-5.3`, the API-key pool, and a full id still works). Registry also GLM-5.2, GLM-5-Turbo (start/team), GLM-5.1/4.x custom. A switch resets effort to `max`.

Effort option `thought`. GLM-5.3 and Flash: `low` `high` `max` (default `max`, cannot disable). GLM-5.2: `disabled` `high` `max`. GLM-5-Turbo and GLM-5.1: `disabled` `enabled`. No map onto a neighbor: `medium` and `xhigh` exit 2 on GLM-5.3. `default` keeps the model default. `disabled` aliases to `none` and matches an option that canonicalizes to `none`.

Windows fixed: 5.3 / Flash / 5.2 = 1000000 (out 128000); 5-Turbo, 5.1, glm-5, 4.x = 200000; GLM-4.5 = 131072; custom id `[1m]` = 1000000; `properties.contextWindow` sets a custom model. `--context N` is `ZCODE_ACP_AUTO_COMPACT_THRESHOLD` (compact once `contextUsed` ≥ N), not a larger window. ctx `(unverified)`. No fast toggle.

### agy

`agy --help`; CLI 1.3.5, server 1.3.0. https://antigravity.google/docs/models is stale (3.6 Flash, Claude 4.6). `agy models` not run.

OAuth offers Gemini, Claude, GPT-OSS, the last two only when `clientInfo.name` is `zed` / JetBrains / Xcode (acp-run sends `zed`). Creds: `oauth-personal` (here), `oauth-business` (no Claude/GPT-OSS), `GEMINI_API_KEY` with optional `GOOGLE_GEMINI_BASE_URL`, Vertex (Gemini-only hard-coded list: 3.1 Pro, 3.5/3.6/3.7/3.8 Flash). No `--provider`, no `--auth-method`.

Ids: `gemini-3.8-flash-{high,medium,low}`, `claude-opus-5-5-{low,medium,high}`, `claude-sonnet-5-5-{low,medium,high}`, `gpt-oss-120b-medium`. API key adds `gemini-3.1-pro-high`, `gemini-3.1-pro-low` (base `gemini-3.1-pro-preview`). `AGY_ACP_DEFAULT_MODEL` default `gemini-3.8-flash-high`.

agy 1.4.1 (2026-10-18) lists bare ids (`gemini-4-argon`, `gemini-3.8-flash`, `claude-opus-5-5`, `claude-sonnet-5-5`, `gpt-oss-120b-medium`) plus a `thinking_level` option (low/medium/high, default high), which `--effort` sets like any other effort option. Before 1.4.1, `--effort low|medium|high` picked `<base>-<level>` (`claude-opus-5-5` + high → `claude-opus-5-5-high`); acp-run still does that when no thought-level option is offered. `xhigh` and `max` exit 2, not rewritten to high. `agy -p --effort max` can reach them; acp-run does not call it. `gpt-oss-120b` is fixed `-medium`. ThinkingLevel: 1 LOW, 2 MEDIUM, 3 HIGH, 4 MINIMAL, 5 EXTRA_HIGH. Options: `model`, `mode` only. `--context` exits 2. Gemini 3.x Flash and 3.1 Pro: 1048576. OAuth `maxTokens` from CCPA `fetchAvailableModels`. Claude and GPT-OSS windows not measured.

### omp

`omp acp` (omp 18.12.2, added to the table 2026-10-19 when the per-run gate was lifted: its Claude
API credits are a normal tier). The session has no `model` config option, so `--model M` becomes
the root flag (`omp --model M acp`, M like `anthropic/claude-sonnet-5-5`); `--effort` drives its
`thinking` option, which lists low..max once a Claude model is set. A run without a Claude `--model`
exits 2: omp's configured default is `github-copilot/gpt-5.6-luna` and would spend the Copilot
reserve (`ACP_RUN_OMP_ANY_MODEL=1` overrides). Needs an enabled Anthropic login in omp
(`omp login`); with an expired one the run ends `No API key found for anthropic` (2026-10-19).

### kiro

`kiro-cli acp` (Homebrew cask `kiro-cli` 2.34.0, added 2026-10-25), native ACP. Under `--perm all`
acp-run starts `kiro-cli acp --trust-all-tools` (`-a`; a flag of `acp` and `chat`, not of the root
command), the YOLO of the `~/.bashrc` `kiro-cli()` function. `--perm deny` and `--perm read-only` are refused
(exit 2): Kiro runs workspace reads, grep, glob and `code` edits without a permission request
([built-in tools](https://kiro.dev/docs/reference/built-in-tools)), so deny could only trip after the tool
ran. Use `--perm all` with a read-only brief and a diff check. `acp-dispatch`'s preflight reruns with
`--perm all` after that refusal.
First run on a machine (2026-10-25): `session/new` blocks while Kiro downloads the 83 MB
`all-MiniLM-L6-v2` semantic-search model to `~/.semantic_search/models/` (a restart begins the
download again), about 66 s here (kirodotdev/Kiro#12118), so the default 2 x 40 s handshake would time out
and every retry restart it. acp-run gives kiro 120 s per try (`HANDSHAKE_TIMEOUT`;
`--handshake-timeout S` or `ACP_RUN_HANDSHAKE_TIMEOUT` overrides). Later runs: `Reply with exactly: OK`
took 4.4 s.
`route_agent.py` never routes it (`[discovery].never_route`): dispatch it by name. The macOS input
method (`kiro-cli integrations install input-method`) is not needed and cannot be enabled on macOS 27
(aws/amazon-q-developer-cli#3916).

### goose

`goose acp` (Homebrew `block-goose-cli` 1.55.0, added 2026-10-23), launched through
`~/.local/bin/goose-scout`: AWS Bedrock Llama 4 Scout (`us.meta.llama4-scout-17b-instruct-v1:0`,
us-east-1). Since 2026-10-23 goose-scout routes goose (provider `litellm`, non-streaming) through a
private LiteLLM proxy on 127.0.0.1:4012 (`~/.config/goose-scout/`, started on demand under
sudo-secretspec, which injects `AWS_BEARER_TOKEN_BEDROCK`). Its callbacks prepend a rules file to
the system prompt, turn an `echo hi`-style shell reply into text, and stop a tool call that repeats
one already run this turn (re-asking Scout without tools for the answer). Before the proxy, Scout
answered "say hi" with five shell calls and repeated `ls /tmp | head -3` until timeout.
`GOOSE_SCOUT_BACKEND=bedrock` restores the direct route.
**Off since 2026-10-28** (`~/.config/goose-scout/DISABLED`, memory pressure); since 2026-10-29
its Bedrock API key is also deactivated, so even removing the marker gives 403 until Bedrock is
re-enabled (djbclark-ade issue 141).

Session modes: `auto` (yolo, YOLO_SET), `approve`, `smart_approve`, `chat`. DENY_SET uses
`approve`: `chat` set over ACP still ran the shell tool (tripwire, 2026-10-23); with `approve`
goose asks and acp-run denies (perm=0+/1-). Verified 2026-10-23: `just say hi` -> text, tools=0;
`Run the shell command: echo yolo-test` -> tools=1 perm=0+/0-. goose reports Scout's context as
10m.

### grok

https://docs.x.ai/developers/grok-4-7 , https://docs.x.ai/developers/pricing — 1.0.52.

`cli-chat-proxy.grok.com/v1` (grok.com, `XAI_API_KEY`, or `cached_token`). `[model_providers.X]` / `[model.Y]` in `~/.grok/config.toml`. `GROK_MODELS_BASE_URL`, `GROK_MODELS_LIST_URL`. Models: `grok-4.7` (default; server `grok-4.7-build`, fingerprint `fp_5719f1aec35dd73c`), `grok-4.7-build-fast` (same fingerprint, 2×, 1.5× on long context, not free), `grok-4.6`, `grok-4.5` (the `ocx-gpt-*` ids left with the opencodex proxy, 2026-10-19). No `--fast`.

Effort `reasoning_effort`, also sent as `reasoningEffort` on the window's `session/set_model`. `low medium high` (default high) `xhigh` on 4.7, 4.7-build-fast, 4.6. 4.5 stops at `high`. Docs also list menu ids `none`, `minimal`.

Context: `session/set_model` `_meta.contextWindow`. Must be in initialize `modelState.availableModels[]._meta.contextWindows`. Measured: four xAI ids 256000 (default) and 500000. `300k` on 4.7 exits 2 (`valid: 256k, 500k`). Config ids `context_window` / `context` / `contextWindow` return "Invalid params". Read-back: `_x.ai/session/info` `context.total`. Live `grok-4.7` low + 500k → `acp-run: applied: model=grok-4.7 effort=low ctx=500k`. TUI `/context-window`, `[model.X] context_window`, `context_windows=[256000,500000]`. Session-scoped; follows a model that lists it; smaller triggers auto-compact. Long-context price from a 200k prompt.

### crush

https://github.com/charmbracelet/crush/pull/2450 — crush-acp v0.98.2, `88a675032c64`.

Catalog 41 providers / 1793 models: aihubmix 349, vercel 297, openrouter 283, venice 125, cortecs 99, opencode-zen 85, opencode-go 38, ionet 37, copilot 35, openai 32, anthropic 18, gemini 11, xai 7, plus bedrock, azure, vertexai, groq, deepseek, zai, moonshot. `provider add`: `openai` `openai-compat` `openrouter` `vercel` `anthropic` `google` `azure` `bedrock` `google-vertex` `hyper` `litellm` `llamacpp` `lmstudio` `ollama` `omlx`. Here: `sipb-llms` in `~/.config/crush/crushrc` (`qwen3.6:35b-a3b-q4_K_M`, `qwen3.5:35b`), Hyper login in the interactive dir. Data dir `~/.local/share/crush-acp` (`CRUSH_GLOBAL_DATA`); `ACP_RUN_CRUSH_DATA` moves it.

ACP models: `sipb-llms:qwen3.5:35b`, `sipb-llms:qwen3.6:35b-a3b-q4_K_M` (current). TUI large/small Ctrl+P, Tab. `--model` is `session/set_model` and crush writes `crush.json` `models.large` (`ScopeGlobal`). Allowed only with `ACP_RUN_CRUSH_DATA`, `--perm deny`, or `--strip-user-config`; else exit 2 (default dir is shared). Read-back `(unverified)`.

`--effort` exits 2. SIPB models: `can_reason`, no `reasoning_levels`, `extra_body` `reasoning_effort: high`. Catalog: fable/opus and gpt-6.1-sol `low,medium,high,xhigh,max`; gpt-6-sol and gpt-6-luna also `none`; gemini 3.8 and grok-4.5 `low,medium,high`; deepseek-v4-flash `low,high,max`; most open models `low,medium,high`; 565 none. Schema lists only `low,medium,high`; crush uses the model's list. `think` bool for Anthropic/Hyper. No `/set_reasoning_effort` turn.

`--context` exits 2. Catalog mostly 1000000–1050000; grok-4.5 500000; copilot Claude 200000–264000; opencode-go glm/kimi ~1M. crushrc `--context-window` (SIPB 32768). `max_tokens` schema max 200000. `disable_auto_summarize`.

### devin

Not installed (`devin-cli` 3000.11.3 via `brew install --cask devin-cli`). Registry: https://agentrq.com/docs/agents/devin .

## Dispatch slice controls (2026-10-11)

An advisory review that must *read* the repo runs with `--perm read-only`
(claude, codex, opencode, zcode; elsewhere `--perm all` with a brief that says "do
not edit" and a diff check). Under `--perm deny` claude gets a session with no
built-in tools at all, so a reading review printed its tool calls as text and
ended in seconds (2026-10-19, two frontier slices lost, then recovered as
"done"). Since then (a) `acp-dispatch --role advise --perm deny` is refused with
exit 2; (b) acp-run fails a turn that made no tool call and replied with pseudo
tool-call markup (`<invoke name=`, `<function_calls>`, a fenced `tool_call` or
`json` block holding a tool and its arguments, `print(default_api.`) as
`FAILED fake-tool-calls`, exit 1, with a line naming `--perm read-only`; (c)
acp-dispatch never recovers such a run's final message: the record is
`no-report` with `NO-REPORT: fake-tool-calls` and no DONE. XML markup quoted in a
code block, or in a run that made real tool calls, passes. `--perm deny` is for
a run that must not touch anything and needs no tools.
`acp-dispatch <agent> ... --timeout 0` starts a slice without a time limit.
Its record-based rearm waiter and detached wait have no deadline, even with an
explicit `--wait-timeout`. For finite slices, the existing default remains
timeout + wrap-up grace + 300 seconds; `--wait-timeout 0` makes just the waiter
unlimited. Already-running record-based waiters follow later extensions.

`acp-dispatch --effort` and `--context` (2026-10-15) are first-class. They are
checked with the model before anything is written
(`acp-run <agent> --info --model M --effort E --context C`), stored on the job
record, and kept by `resume`. `--acp-arg` still forwards other flags; a
dash-leading value needs `--acp-arg=--meta`. zcode `--model` is accepted and
still optional.

`acp-dispatch extend <out>/jobs/<name>.json 3600` adds an hour to a running
slice. Use `0` to remove its deadline. The command atomically writes the control
file and records the requested total limit; acp-run's log confirms application.
Pending positive extensions accumulate. Finished slices are refused, and so is
every extension (`0` included) of a costly Go advisory slice, whose record carries
`--go-advisory` (exit 2, nothing written).

`acp-dispatch resume <out>/jobs/<name>.json --timeout 14400` continues a
finished slice in its original ACP session. Optional `-p TEXT` or `-f FILE`
replaces the continuation prompt; `--detach --no-wait` uses the normal runner
and rearm contract. Without a new timeout it reuses the recorded limit. The
record stores the session id as soon as it is observed, and legacy records
recover it from the log's `new_session` event. Agents advertising neither
load nor resume are refused with exit 2. The previous report is preserved as
`<name>-r1-report.md`, then `-r2`, and so on; each revision also keeps its brief,
log, final text and stderr. Normal output and `.done` paths remain stable.

`acp-dispatch reroute <out>/jobs/<name>.json (--agent A --model M | --escalate)`
continues a stopped slice from its checkpoint on another pool (2026-10-18).
`--escalate` climbs exactly one rung of the cheap-first `[escalation]` ladder
in `config/routing.toml` (operator decision 1.4) and takes `route_agent`'s top
route for the next kind, excluding the pool that failed; every dispatch gate
still runs and the top rung refuses with exit 2 — never straight to frontier.
Long-reset rule (same day): a quota stop whose reset is more than
`[dispatch].auto_resume_max_wait_hours` (6) away is not auto-resumed in place;
`check` prints a ready-to-run reroute line instead, and the scheduled resume
tries to wake the Mac first (`sudo -n pmset schedule wake`, recorded in
`auto_resume.wake`; cancelled best-effort when the resume runs or the schedule
is cancelled). That needs the NOPASSWD rule in
`config/sudoers.d/acp-dispatch-pmset` (only `pmset schedule wake *` and
`pmset schedule cancel wake *`; operator-approved and installed 2026-10-18):
`visudo -cf` it, then `sudo install -m 0440 -o root -g wheel
config/sudoers.d/acp-dispatch-pmset /etc/sudoers.d/`. Without it the wake
records `unavailable: ...` and the resume runs at the Mac's next wake.

`acp-dispatch tell <out>/jobs/<name>.json "stop after step 3"` sends a message
into a running slice (2026-10-18). It appends a `## MSG N` entry to
`<record>.inbox.md` next to the record, and for a `claude` slice also writes
one JSON frame to the live session's messaging socket (found via
`~/.claude/sessions/<pid>.json`; undocumented protocol, so a miss is never an
error — the inbox is the source of truth). A bare report path works as RECORD
when no `.json` exists (Agent-tool sub-agents): the inbox becomes
`<report>.inbox.md`. A finished record is refused with exit 2 and the `resume`
command to use instead. The footer has the slice answer each message with
`REPLY N:` in `<record>.replies.md`; `check` shows `inbox: N sent, M answered`
and `resume` carries unanswered messages into the prompt.

`acp-dispatch outcome <record> --ci pass --review fail --merged` records what
became of a finished slice's work (2026-10-18): `outcome.ci`/`outcome.review`
("pass" | "fail") and `outcome.merged` (`--not-merged` writes false), merged
into earlier calls, the fields `route_agent.py calibrate` re-ranks pools from.
`--review fail` means the lead's review found a defect that had to be fixed
before merge, even when the fixed work then merged.
An unfinished record, or no flag at all, is refused with exit 2.

For `agy`, the footer instead names
`<-C>/.acp-dispatch/<task>-<name>-report.md` and its `.done`. Dispatch adds
`.acp-dispatch/` once to the workspace repository's local Git exclude file
(non-Git workspaces need no exclude). Finalize moves the report to the normal
out folder before publishing its `.done`. Records retain both pairs of paths.

## Interactive mode

`acp-run <agent> --interactive` (`-i`) keeps the ACP connection, which is the
session, open and reads prompt after prompt in one process. The one-shot contract
is unchanged without it: stdout is the final message, stderr one summary line.

```sh
acp-run claude -C ~/src/repo -i                              # type at the prompt
acp-run claude -C ~/src/repo -i -p 'Read AGENTS.md first.'   # first prompt from -p/-f
acp-run codex -C ~/src/repo -i --inbox /tmp/codex-in         # also take files dropped there
acp-run claude -C ~/src/repo -i --resume SESSION_ID          # reopen an earlier session
```

1. **Output.** Agent text streams to stdout as it arrives; each tool call is one
   `⚙ <title>` line and a failed one a `✗` line. Thoughts show only with
   `--show-thinking`. After each turn it prints the stop reason, seconds and tool
   count, then waits for the next prompt.
2. **Prompt sources**, whichever comes first. A line on stdin is one prompt. A
   `*.txt` or `*.md` file dropped into `--inbox DIR` (polled every second, taken in
   name order, deleted once read) is one prompt, whole file. The first prompt
   comes from `-p` or `-f`; without either it starts at the prompt. A prompt that
   arrives during a turn queues as the next one. `--timeout` applies to each turn.
3. **Commands.** `/exit` (or EOF) ends the session; typed at the terminal during
   a turn it cancels that turn first, while from a pipe or the inbox it waits
   behind the prompts already queued. `/cancel` cancels the running turn
   (`session/cancel`) and returns to the prompt.
4. **Ctrl-C** cancels the running turn, or exits when idle. The agent runs in its
   own process group, so the terminal's interrupt does not hit it directly.
   SIGHUP exits 129.
5. **Delivery checks per turn.** Each turn gets the checks above; a failed one
   prints `FAILED <class>` and returns to the prompt rather than ending the
   session. On exit the stderr summary carries `turns=N` (or `--json` the last
   turn's text), and the exit code is the last turn's (0 when no turn ran).
6. **Permissions.** Requests are answered by the `--perm` policy without
   asking: `all` (the default) allows each one, `deny` refuses each one. The
   interactive `--perm ask` y/n prompt was removed on 2026-10-14 (operator:
   acp-run runs yolo for every agent); `--perm ask` now warns and runs as
   `all`.
7. **`--resume ID`** reopens an ACP session with `session/load` (history is
   replayed to the log only, not printed) or `session/resume`, whichever the agent
   advertises in `initialize` (`--info` shows `loadSession` and
   `sessionCapabilities`). It exits 2 if the agent advertises neither.
   Since 2026-10-18 (ACP session-resume RFD): with both advertised it calls
   `session/resume` first (no replay, "0 messages") and falls back to
   `session/load` only on a -32601/-32602 error (logged as
   `resume_fallback_load`). `--add-dir` is sent again, in full, on whichever call
   runs, but only when the agent advertises
   `sessionCapabilities.additionalDirectories`; otherwise one stderr line says the
   extra directories were not sent. An unknown id (resource-not-found) or a replay
   from a different session id exits 2 before any prompt. At the end of every
   run (after the last `--interactive` turn) it sends `session/close` when the
   agent advertises `sessionCapabilities.close`, before stopping the agent
   (5 s, errors only logged as `close_session_failed`).
8. **herdr reports.** In a herdr pane (`HERDR_PANE_ID` set; `HERDR_BIN_PATH` or
   `herdr` on `PATH`) it reports `working` and `idle` as source `acp-run`
   (`blocked`, for a pending `--perm ask` question, went with it on 2026-10-14), with a resume command
   (`acp-run <agent> -C DIR --interactive --resume ID ...`), and releases the
   pane on exit. Reports run in the background and never hold up the session.
   herdr before 0.9.2 rejects the resume command, so on 0.9.1 it is dropped.
   The agent process is started without `HERDR_PANE_ID` and `HERDR_ENV`, so its
   own herdr hooks (Claude Code's report as `herdr:claude`) do not compete for
   the pane.
9. **Sending a prompt from outside.** On herdr 0.9.1 `herdr agent prompt <pane>
   TEXT` cannot reach an acp-run session, so a caller uses the inbox (write a
   `.txt` file into `--inbox DIR`; write to a temporary name and rename it, so a
   half-written file is not picked up) or `herdr pane run <pane> TEXT`, which
   sends a line to the pane's terminal, where acp-run reads it from stdin.
10. **The log gets a `turn` record per turn** (`n`, `stop_reason`, `seconds`,
    `exit`, and `failure`, `error` or `warning` when set), written before the
    final `result` record, which carries `turns`. A one-shot run writes one `turn`
    record too.

## Git identity guard (2026-10-26)

ACP's reference-transaction hook keeps agent commits under the operator's identity,
without replacing fixture identities in temporary repositories. Its configuration
travels through `GIT_CONFIG_PARAMETERS`, so Codex's default KEY/SECRET/TOKEN
environment-name exclusions remain enabled without stripping `GIT_CONFIG_KEY_n`
out of a counted tuple. No Codex policy change is needed.

Before launching, acp-run converts complete inherited `GIT_CONFIG_COUNT` tuples
using Git's single-quoted format. Configuration order stays: inherited counted
entries, ACP's guard entries, then existing `GIT_CONFIG_PARAMETERS` text. Nested
launches normalize inherited tuples too, without adding the guard twice. An invalid
count or a missing key/value refuses the launch with exit 2 and a variable-name-only
diagnostic; the incomplete tuple is never cleared as a fallback. An empty
`GIT_CONFIG_COUNT` is zero, the way Git reads it (`env && *env` in `config.c`), so a
launcher that exports it empty still launches. A counted key that embeds
a credential refuses too, by index only, never by value: the name-based exclusion used
to keep such a token out of an agent's tool environment, and the quoted transport would hand
it over. It refuses in two ways.

By URL position: every URL-scoped family counts, not just `url.*` — git resolves
`http.<url>.*` and `credential.<url>.*` for the matching URL as well (`git config
--get-urlmatch http.sslVerify https://user:token@host/x` answers the setting configured
under that subsection, and answers nothing for another host) — so every `://` in the key
must be followed by an authority without `@`, whatever the section (`url.`, `HTTP.`) or
scheme (`HTTPS://`) case, and past any run of slashes (`https:///user:token@host` sends
that userinfo although its authority is empty), and username-only userinfo refuses with it
(`url.ssh://git@github.com/.insteadOf`), because a username cannot be told apart from a
token without decoding it. A `?` or `#` after a `://` refuses too: a query or a fragment is
a credential position git matches exactly, with no `@` needed — with
`http.https://example.org/repo?access_token=TOK3N.sslVerify` configured,
`git config --get-urlmatch http.sslVerify 'https://example.org/repo?access_token=TOK3N'`
answers `true` while the same URL without the query answers nothing, and a loopback
`git ls-remote` sent the token in its request target (2026-10-30). A query is legitimate in a
real remote (`https://dev.azure.com/o/p/_git/r?path=/src`, a cgit web url `?h=main`), so such a
key refuses too: that is the intended trade, and it stays usable in `~/.gitconfig`. The one
exception is an `includeIf.hasconfig:` glob pattern with a `?` wildcard, which cannot travel
through a counted config. A `credential.` subsection that is
a PARTIAL url with no scheme is the one form git resolves as well — measured with
`git credential fill`, a helper under `credential.example.org.helper` runs for
`url=https://example.org/x`, and one under `credential.<userinfo>@example.org.helper` runs
for `url=https://<userinfo>@example.org/x` — so such a subsection refuses whenever its
authority carries `@` at all, or a `?`/`#`: no colon is required, because a GitHub PAT is
used as a username and git url-decodes `%3A`, so `credential.user%3Atoken@host.helper`
matches a request whose username is literally `user:token`.

By token shape: a name matching a known token pattern (`ghp_`, `github_pat_`, `glpat-`,
`xox?-`, `sk-`, `hf_`, `npm_`, `pypi-`, `AIza`, `AKIA`/`ASIA`, an `eyJ` JWT header, each
with a length floor) refuses wherever it appears in the key, in a subsection
(`remote.<token>.url`) and in a URL path alike — the name filter hid the token whether or
not git resolves the key, so the exposure is the NAME, not the setting's meaning. Three
limits keep that off ordinary names: a match never starts mid-word, each prefix is matched
in the case its issuer uses, and each floor sits just under the real token length, measured
per issuer (`ghp_` 36, `github_pat_` 82, `glpat-` 20, `hf_` 34, `npm_` 36, and LiteLLM's
default generated `sk-` + 22). Refusing a name that merely resembles a prefix
(`remote.sk-learn-upstream-fork.url`, `remote.ghp_mirror01.url`,
`remote.pypi-mirror-internal-eu.url`) would break a launch for nothing, and an earlier head
refused exactly those (adversary round 10, 2026-10-30). A non-default shorter LiteLLM key
and a name glued straight onto a token with no separator (`remote.xghp_…url`) are the
documented limits, as is a name whose `sk-` body is long enough to reach the floor. Only
KEYS are checked: a credential in a counted VALUE (`GIT_CONFIG_VALUE_n`) never went through
the name filter, so refusing one would be a different change. A secret of an unknown shape
sitting in a path segment cannot be told apart from path data
(`url.https://example.org/@scope/.insteadOf` must travel), so it still travels: that is
this check's documented limit.

Both of those checks also run on every **percent-decoded** spelling of the key, not only the
text as written, because the exposure is the name and not the setting's meaning: an agent
reads the converted key and can decode it. Measured with `git config --get-urlmatch
http.sslVerify <url>` on git 2.56.0, a setting written under
`http.https://host/ghp%5Fabc....sslVerify` answers for both `https://host/ghp_abc...` and
`https://host/ghp%5Fabc...`, so git treats the spellings as one subsection too (codex
security review, 2026-10-30). Decoding repeats until the text stops changing — each step
strictly shortens, so it terminates — which covers a double encoding (`ghp%255F...`);
escapes that are not valid escapes are left alone, so a `%` in ordinary path data travels.
The cost is a key that only spells a credential once decoded, such as
`credential.user%40host.helper` or `url.https%3A%2F%2Fuser%3Atoken%40host/x.insteadOf`:
that refuses too, which is the intended trade, and both stay usable in `~/.gitconfig`.

A port has no `@`, so `credential.https://host:8443.helper`, the plain
`credential.example.org.helper`, an ordinary `remote.origin.url` and a name that only
resembles a prefix (`remote.sk-1.url`) still travel. Use a credential helper or
`~/.gitconfig` for the rest. The workspace Git guard recognizes only the exact ACP
hook event and expected guard path in this environment transport, while retaining
compatibility with older counted launches.

## Exit codes

| Code | Meaning |
| ---- | ------- |
| 0 | `end_turn` with some output |
| 1 | another stop reason, an agent error, an empty reply (no text and no tool calls; or no text under `--perm deny` or `read-only`, or after a denied permission), or a delivery-check failure (quota, plan, auth, provider error, truncated reply, or `FAILED fake-tool-calls`: no tool ran and the reply is tool calls printed as text) |
| 2 | usage error, or invalid/incomplete counted Git environment configuration (before agent launch) |
| 5 | empty reply and every permission request was denied (the code acpx uses) |
| 75 | refused to start by `--max-load` |
| 127 | the agent binary is not on `PATH` after `ACP_RUN_BIN_WAIT` seconds (default 90, `0` disables, at most 600, junk means the default; an upgrade may be relinking it, 2026-10-20). The binary is the program the launch command runs: for crush, `crush-acp` behind its `env NAME=VAL` wrapper, never `env` (2026-10-23); `--list` marks it `--` the same way |
| 77 | under `--perm deny` or `read-only` a tool ran without a permission request (tripwire; the turn is cancelled) |
| 124 | timed out (`session/cancel` sent first, then the agent is killed) |
| 130, 143 | interrupted by SIGINT, SIGTERM (with `--interactive` also 129 on SIGHUP; Ctrl-C cancels a running turn instead of exiting) |

A reply with text exits 0 even when every permission was denied (a `--perm
deny` review can still deliver its report); the summary line then carries a
`warning=`.

Run `acp-run --help` for every flag.

## Install

Needs [uv](https://docs.astral.sh/uv/) and the agents' own CLIs/adapters.

The script itself is self-contained (a `uv run --script` header pulls its
dependencies): a copy on your PATH runs every agent and every non-Go model
with no other file. On this machine it lives in djbclark-ade
at `tools/acp-run/acp-run`
and is reached as `~/.local/bin/acp-run` → `~/ops/site-private/bin/acp-run` →
`~/ops/site-djbclark/tools/acp-run` → here. Elsewhere, copy the script onto
your PATH:

```sh
install -m 755 tools/acp-run/acp-run ~/.local/bin/acp-run
acp-run --list
```

**OpenCode Go models need the Go policy bundle** (added 2026-10-25; guard added
2026-10-25). The policy stays in one place, `bin/go_model_policy.py` +
`config/go-model-policy.json`, and the context guard in one place,
`opencode-plugins/go-context/`. acp-run loads them only when a requested or
applied model is `opencode-go/…`, from exactly two roots and never from
`sys.path`, the cwd, the script's own directory or the user's OpenCode config:
(1) the checkout the script runs from (`tools/acp-run/acp-run` with `../../bin`,
`../../config` and `../../opencode-plugins`: running or symlinking it in place
just works), else (2) the installed bundle `~/.local/share/acp-run/go-policy/`:

```text
~/.local/share/acp-run/go-policy/bin/go_model_policy.py
~/.local/share/acp-run/go-policy/config/go-model-policy.json
~/.local/share/acp-run/go-policy/opencode-plugins/go-context/index.js
~/.local/share/acp-run/go-policy/opencode-plugins/go-context/package.json
```

```sh
d=~/.local/share/acp-run/go-policy
install -d "$d/bin" "$d/config" "$d/opencode-plugins/go-context"
install -m 644 bin/go_model_policy.py "$d/bin/"
install -m 644 config/go-model-policy.json "$d/config/"
install -m 644 opencode-plugins/go-context/index.js opencode-plugins/go-context/package.json "$d/opencode-plugins/go-context/"
```

Re-run those lines whenever the classification or the guard changes (the copy is
a snapshot). To track the checkout instead, make `bin`, `config` and
`opencode-plugins` in `$d` symlinks to the checkout's directories: the guard reads
`<its real dir>/../../config/go-model-policy.json`, and acp-run refuses a Go launch
whose guard would read a different policy file than the helper enforces.

Why the guard is part of the bundle: a Go launch with `--perm read-only` or
deny, or with `--strip-user-config`, replaces OpenCode's global config with a
per-run 0700 directory (no user plugins, MCP, project config; see above). That
directory gets exactly one plugin, `plugins/ade-go-context`, a symlink to the
trusted guard of the root above, so the cost guard survives sanitizing while every
other plugin stays excluded (a user plugin of the same name is not copied). If the
guard is absent, incomplete or paired with another policy file, the Go launch is
refused (exit 2 before any agent starts; exit 1 if it is only noticed later),
never run unguarded. Non-Go launches never read the guard. A Go launch that is not
sanitized (`--perm all` without `--strip-user-config`, `--interactive`,
`--keep-user-config`) runs on the user's own OpenCode config, where the guard is
whatever the user linked (`opencode-plugins/go-context/README.md`).

Without the bundle, non-Go prompts run as before, and a Go prompt is refused
before any agent starts (exit 2 at launch, exit 1 if the applied model turns out
to be Go), with a message naming the paths tried. A missing, unparsable or invalid
policy never falls back to a permissive default. If a checkout helper exists but
cannot load its policy, the run is refused rather than falling back to an installed
snapshot.

The agent table reflects the machine it was written on (for example Cline is
pinned to the `cline-pass` provider, and `agy` runs Google's first-party ACP
server from `~/.local/share/agy-acp-server/`); edit `AGENTS`, `DEFAULT_SET` and
`YOLO_SET` at the top of the script for yours.

`agy` notes (verified 2026-10-09): YOLO is the session config option
`mode=yolo` (`default | auto_edit | yolo`), set automatically. agy runs
commands in whichever of its workspaces sorts first, often its own skills
dir rather than `-C`, so acp-run names the working directory at the top of
the prompt. It also drops any inherited `HTTPS_PROXY` for agy (the opencodex
proxy, uninstalled 2026-10-19, answered it with 407).

**The clientInfo gate (2026-10-10).** agy_acp_server 1.3.0 offers its
non-Gemini models (`claude-opus-5-5-*`, `claude-sonnet-5-5-*`,
`gpt-oss-120b-medium`) only to clients whose ACP `clientInfo.name` it
recognises as Zed, Xcode or JetBrains; any other name gets the `gemini-*`
models alone, and `--model claude-...` fails with "no model". acp-run
therefore sends `zed` for agy (`CLIENT_NAME` in the script). Upstream:
google-antigravity/antigravity-cli#1168, pingdotgg/t3code#16489. If
`acp-run agy --info` lists no `claude-*` value, check that first.

**Which server (compared 2026-10-10).** acp-run keeps Google's own
`agy_acp_server.par` 1.3.0, the newest release (ACP registry
`antigravity-acp` and dl.google.com; agy CLI 1.3.3 ships no newer ACP
server). Since 2026-10-17 acp-run runs the newest version dir under
`~/.local/share/agy-acp-server/` instead of a hard-coded 1.3.0, and agy is kept at the
registry's latest (1.4.1 that day; on Linux the registry adds `--uid=`). Checked again 2026-10-18:
agy CLI 1.4.2 (Homebrew) still runs server 1.4.1, the newest published (the registry lists 1.4.1;
dl.google.com answers 404 for 1.4.2, 1.4.3 and 1.5.0). The 1.3.0 notes
in this file are as tested then. The alternatives and why not:

1. simonepri/refined-antigravity-acp 1.4.2 wraps the same binary, so it
   inherits the gate (our opt-in `REFINED_AGY_CLIENT_NAME`,
   simonepri/refined-antigravity-acp#49, is unmerged); it replaces the
   `mode` option and renames models to base id plus `thought_level`,
   injects steering prompts and rewrites the session SQLite. Its hang,
   crash-recycle and loop fixes are the reason to revisit it if those
   show up in agy runs.
2. shubzkothekar/antigravity-acp (Bun) spawns the `agy` CLI per prompt,
   the path with the hidden burst limit, and downloads its own `agy`.
3. An `agy -p` adapter of our own: the same burst-limit problem.

To try another server for one run, set `ACP_RUN_AGY_SERVER` to its
command (one path, `~` expanded), for example a newer server unpacked to
`~/.local/share/agy-acp-server/<version>/agy_acp_server.par`, or
`$(command -v refined-antigravity-acp)` once #49 lands (it needs
`REFINED_AGY_ACP_BIN` pointing at the 1.3.0 binary and its
`REFINED_AGY_CLIENT_NAME`). Unset it to go back. Check `--info` for the
`mode` option and model ids before relying on it: `YOLO_SET` and
`--model` use the stock server's names.

## Crush data dir (2026-10-14)

`acp-run crush` hands crush-acp `CRUSH_GLOBAL_DATA=~/.local/share/crush-acp`, the same dir the
interactive `crush` shell function uses, so a model picked in the TUI is also the model
`acp-run` runs on. `ACP_RUN_CRUSH_DATA=<dir>` moves it for one run (`~` expanded); the SIPB
benchmark (`skills/sipb-llm-bench/bench.py`) sets it to a private dir with the model under test
pinned in `crush.json` and the catalog cache `providers.json` copied in, so it never edits the
shared file.

## Why not acpx?

[acpx](https://github.com/openclaw/acpx) is the maintained general-purpose ACP CLI
and is the better choice for most people. On 2026-10-05 it lacked two things this
script exists for: permission rules scoped to file paths (since dropped:
acp-run runs yolo, with only `deny` as a gate, operator 2026-10-14), and per-agent
environment and default config options. If acpx gains those, a thin wrapper over
it would replace this script.

Several of the ideas above come from acpx (MIT): exit code 5, prompt retries on
transient errors, tool-kind inference from titles, cooperative interrupts.

### OpenCode Go bounded advice (2026-10-25)

OpenCode prompt runs require `--model provider/model`; an unqualified or omitted
model could resolve to Go without a cost check. Before prompting, the applied
model must exactly match that qualified ID, with verified read-back; fuzzy
aliases and unverified resumed selection are refused. Routine models are listed in
`config/go-model-policy.json` (a standalone copy needs the bundle, see Install). Costly Go models require `--go-advisory --perm
read-only --timeout 600` (a positive timeout no greater than 600). They refuse
interactive mode, prompt retries and `--verify`; wrap-up grace is disabled.
Go model selection through `--set model=...` is refused. Unknown Go models fail
closed until classified. This does not restrict other providers' models.
`acp-dispatch` supplies the flag only for an explicit bounded advisory role.
See [context hygiene](../../docs/context-hygiene.md) for native V2 compaction.

Identity-guard corrections (2026-10-30): the hook command shell-quotes its path. Nested launches verify
the inherited hook configuration and reinstall missing pairs instead of trusting the email marker alone.
Credential-bearing counted keys remain refused for every agent: converting them to PARAMETERS would
make them readable to agents that filter KEY names, so this conservative transport rule is shared.

On 2026-10-31 (PR 175), the identity-hook exemption began requiring the exact expected guard path
and its canonical shell quoting. A path containing shell syntax followed by `/../` cannot gain an
exemption through lexical path normalization.
