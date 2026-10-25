---
name: create-hook
description: >-
  Create, edit, review or remove native OpenAI Codex CLI hooks (~/.codex/hooks.json,
  <repo>/.codex/hooks.json, inline [hooks] in config.toml): PascalCase events
  (PreToolUse, PermissionRequest, Stop, SessionStart ...), command or MCP hooks,
  trust review, deny/allow output. Use for "add a Codex hook", "write hooks.json
  for Codex", "block a command in Codex". NOT for Cursor, Claude Code or Grok
  hooks, and not for Codex's separate `notify` setting.
---

# create-hook — native Codex hooks

Verified **2026-10-25 against Codex CLI 0.164.0**: the official page
(<https://developers.openai.com/codex/hooks>, which redirects to
<https://learn.chatgpt.com/docs/hooks>) and the `rust-v0.164.0` source
(`codex-rs/hooks/`, `codex-rs/config/src/hook_config.rs`). Hooks change fast. Before
relying on a detail below for a newer `codex --version`, re-read the official page and
the generated schemas in `codex-rs/hooks/schema/generated/` on GitHub.

This skill is **Codex only**. Cursor uses `.cursor/hooks.json` with camelCase events
(`preToolUse`, `beforeShellExecution` ...); those names and paths do nothing in Codex,
and Codex's PascalCase files do nothing in Cursor. A Cursor hook guide, if wanted,
is a different skill (`create-cursor-hook`), never this one.

When asked for a hook, do not stop at describing the format: gather what is missing,
then write the files, then give the operator the trust steps (section 4).

## 1. Where hooks live and how they load

| Scope | File | Loads when |
|---|---|---|
| User | `~/.codex/hooks.json` or `[hooks]` in `~/.codex/config.toml` (`$CODEX_HOME`, default `~/.codex`) | always |
| Project | `<repo>/.codex/hooks.json` or `<repo>/.codex/config.toml` | only if the project `.codex/` layer is trusted |
| Managed | `requirements.toml`, system, MDM, cloud | policy; trusted by policy, cannot be disabled by the user |
| Plugin | `hooks/hooks.json` in an enabled plugin, or `hooks` in `.codex-plugin/plugin.json` | plugin enabled **and** each hook trusted |

1. **Every layer's hooks run; a higher layer never replaces a lower one.** A layer with both
   `hooks.json` and inline `[hooks]` merges them and warns; use one form per layer.
2. **Hooks are on by default** (`[features] hooks = true`, stable). `codex_hooks` is a
   deprecated alias. `hooks = false` turns everything off; `allow_managed_hooks_only = true`
   in `requirements.toml` skips user, project, session and plugin hooks.
3. Only `command` and `mcp_tool` handlers run. `prompt` and `agent` handlers parse but are
   skipped with a warning. Cursor-style `"type": "prompt"` hooks therefore never work.
4. A **parse error in `hooks.json` skips that whole file** (warning only). Validate JSON
   before and after every write.
5. Commands run on Unix as `$SHELL -lc '<command>'` (fallback `/bin/sh`), a **login shell**,
   with the session `cwd` as working directory. A noisy shell profile that prints to stdout
   can corrupt JSON output. Resolve repo scripts from the git root
   (`"$(git rev-parse --show-toplevel)/.codex/hooks/x.py"`) because Codex may start in a
   subdirectory. `commandWindows` overrides the command on Windows.

## 2. Events

Event names are exact, case-sensitive PascalCase. `matcher`: `""`, `"*"` or omitted matches
all; a pattern made only of letters, digits, `_` and `|` is an **exact** name or `|`-list
(`Bash` does not match `BashOutput`; `mcp__memory` does not match
`mcp__memory__create_entities`); anything else is an **unanchored** regex (`^Bash` matches
`BashOutput`; use `^mcp__memory__` for a whole server).

| Event | `matcher` filters | Can steer? |
|---|---|---|
| `SessionStart` | `startup`, `resume`, `clear`, `compact`, `fork` | adds context |
| `UserPromptSubmit` | ignored | block prompt, add context |
| `PreToolUse` | tool name | deny, rewrite input, add context |
| `PermissionRequest` | tool name | allow / deny / no decision |
| `PostToolUse` | tool name | replace result with feedback, add context |
| `PreCompact`, `PostCompact` | `manual`, `auto` | `continue:false` stops compaction |
| `SubagentStart`, `SubagentStop` | agent type | context; `SubagentStop` can continue |
| `Stop` | ignored | `decision:"block"` makes Codex continue |
| `Interrupt` | ignored | advisory only |
| `SessionEnd` | `other` | advisory only, always synchronous |

Tool names: shell and unified exec match as `Bash`; `apply_patch` also matches `Edit` and
`Write` (input still says `apply_patch`); MCP tools are `mcp__server__tool`; other local
function tools match their own name. Hosted tools (`WebSearch`) never hook. `write_stdin`
does not re-run `PreToolUse`. **Tool hooks are a guardrail, not an enforcement boundary.**
`PreModelRequest` / `PostModelRequest` exist in 0.164.0 source (observation only) but are not
in the official docs; do not build on them.

### Input (stdin, one JSON object)

Common: `session_id`, `transcript_path` (null or a path; format unstable), `cwd`,
`hook_event_name`, `model`, and on most events `turn_id` and `permission_mode`
(`default`, `acceptEdits`, `plan`, `dontAsk`, `bypassPermissions`). Tool events add
`tool_name`, `tool_input` (`.command` for Bash and `apply_patch`; arguments object for MCP),
and `PreToolUse` / `PostToolUse` add `tool_use_id`; `PostToolUse` adds `tool_response`.
`PermissionRequest` has **no** `tool_use_id`. `Stop` adds `stop_hook_active` and
`last_assistant_message`. Subagent events add `agent_id`, `agent_type`.
**`cwd` is the session directory, not the selected tool's working directory**
(<https://github.com/openai/codex/issues/48064>, open on 2026-10-25): a `PermissionRequest`
for `exec_command` with another `workdir` still reports the session `cwd`. Never treat it as
the directory a command will run in.

### Output and exit codes

1. Exit 0, empty stdout: success, no effect.
2. **Exit 2 with a reason on stderr blocks** (`PreToolUse`, `PermissionRequest` = deny,
   `PostToolUse`, `UserPromptSubmit`) or continues (`Stop`, `SubagentStop`). Exit 2 with empty
   stderr is a hook *failure*, not a block.
3. **Any other non-zero exit, a crash, a timeout or invalid JSON is a non-blocking failure:
   Codex reports it and carries on.** Hooks fail **open**. A safety hook must catch its own
   exceptions and emit a deny (or exit 2 with a reason) itself.
4. `SessionStart`, `UserPromptSubmit`, `SubagentStart`: plain-text stdout becomes developer
   context. `Stop`, `SubagentStop`, `Interrupt`: stdout must be JSON or empty (plain text is
   invalid). `PreToolUse`, `PermissionRequest`, `PostToolUse`: plain text is ignored.
5. Common JSON fields (`continue`, `stopReason`, `systemMessage`, `suppressOutput`) only work
   where listed in the docs. `PreToolUse` and `PermissionRequest` reject `continue:false`,
   `stopReason` and `suppressOutput:true`, and `PostToolUse` rejects `suppressOutput:true`:
   the run is marked failed and **its decision is discarded** (`PreToolUse`/`PostToolUse`:
   the tool proceeds; `PermissionRequest`: the normal approval prompt). Never add these
   fields to a deny or block.
6. Context returned as `additionalContext` is capped near 2,500 tokens per hook (the rest
   is spilled to a temp file with a preview); `additionalContextLimit` on the handler tunes
   it. Keep it small, and never put secrets in output.

**PreToolUse** deny (also accepted: `{"decision":"block","reason":"..."}`, or exit 2):

```json
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"why"}}
```

Rewrite: `permissionDecision:"allow"` plus `updatedInput` (Bash and `apply_patch` need a string
`command`; MCP and function tools take the replacement arguments object). `"ask"`,
`decision:"approve"` and `updatedInput` without `allow` are unsupported (failed run, tool
proceeds). PreToolUse `allow` is a rewrite, not a grant of approval: use `PermissionRequest`.
A deny needs a **non-empty** reason: in 0.164.0 source a block with no reason text lets the
tool run.

**PermissionRequest** decides an approval Codex is about to ask for:

Allow, **or** deny: print exactly one of these objects, never both:

```json
{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}
```

```json
{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"deny","message":"why"}}}
```

Print nothing to leave the decision to the normal prompt. A reserved `updatedInput`,
`updatedPermissions` or `interrupt: true` invalidates the **whole** output (a deny sent with
it is dropped and the normal prompt follows); never send them. Invalid output never
becomes an allow.

**Stop** continues the turn: `{"decision":"block","reason":"Run the failing tests again."}`
(the reason becomes a new user-style prompt). Check `stop_hook_active` or the hook loops.

## 3. Approval, concurrency and what hooks cannot do

1. **All matching hooks from all layers start concurrently, and results are folded
   conservatively: any `deny` wins; otherwise any `allow` lets the request proceed without a
   prompt; no decision falls to the normal approval flow.** There is no "first answer wins"
   and no ordering you can rely on between hooks. Two approval sources (say a terminal
   policy and a phone relay) therefore need **one broker hook** that owns the race and
   returns a single answer; adding a second hook beside an existing one does not make them
   race, it makes the worse answer win.
2. `PermissionRequest` runs **only when Codex would prompt**, before the guardian or terminal
   prompt appears, and the turn waits for it. It does not race the terminal UI
   (<https://github.com/openai/codex/issues/39835>, open on 2026-10-25). A slow remote-approval
   hook blocks the terminal until it answers or times out, so set a short `timeout`. With
   `approval_policy = "never"` or commands that need no approval, it never fires; gate those
   with `PreToolUse`.
3. **Timeout** (`timeout`, whole seconds, minimum 1): default **600** for every event except
   `SessionEnd` and `Interrupt`, which default to **1** and are clamped to **1-3**. A timeout
   is a non-blocking failure (item 3 of Output). MCP hooks use the shorter of hook and
   server timeout.
4. `"async": true` runs a command hook in the background: it cannot block, approve or
   rewrite (use it for logging); up to 8 run at once per session; `SessionEnd` ignores it.
5. `mcp_tool` hooks call an already-connected MCP server
   (`{"type":"mcp_tool","server":"s","tool":"t","input":{"p":"${tool_input.file_path}"}}`);
   a missing server, an unavailable tool or an error does **not** block; `SessionEnd` does not
   support them.
6. Hooks do not replace the sandbox or approval policy, and nothing here emulates a
   "cancel" or "trust" that Codex does not implement.
7. **Native `notify` is independent.** `notify = [...]` in `config.toml` is the legacy
   turn-end program (the payload JSON is its final argument). Hooks neither replace it nor
   disable it, and a `Stop` hook is a different mechanism with a different payload. Edit one
   without touching the other, and never claim a hook "replaces notify".

## 4. Trust review (never skip, never bypass)

Before a non-managed hook runs, the operator must review and trust it. Codex hashes the
**normalized hook definition** (event, matcher, handler fields such as `command`, `timeout`,
`async`, `statusMessage`), not the script file, and stores it in the **user** `config.toml`:

```toml
[hooks.state."/Users/me/.codex/hooks.json:pre_tool_use:1:0"]
trusted_hash = "sha256:..."
```

The key is `<source file>:<event in snake_case>:<matcher-group index>:<handler index>`.

1. A new or changed hook is `Untrusted` / `Modified` and is **skipped** (a startup warning
   points at `/hooks`). Trust is two separate things, keep them apart:
   - **Approval of the definition** is the operator's decision. Show the exact definition
     (event, matcher, command, timeout, async) and proceed only on authorization that covers
     that specific hook: the operator asking for it, or a standing instruction naming it.
     Ask only when that authorization is missing; do not ask when it exists.
   - **The `/hooks` step** is the mechanical recording of that approval. With authorization
     for this hook, an assistant that can drive the TUI may open `/hooks`, check that the
     listed definition matches what was authorized, and trust it; otherwise hand the
     operator the one step. Never say an assistant categorically cannot, and never tell the
     operator to type or restart something they have already authorized you to do.
   Afterwards confirm `/hooks` lists it as trusted. Hash trust via `/hooks` is the only path.
2. **Do not restart live TUIs.** Sessions load hooks at start and on a config refresh
   (`Session::refresh_hooks`, 0.164.0 source); whether a new or edited `hooks.json` is
   picked up by an already-running session was not verified, so assume it is not. Prove a
   hook in a **fresh, controlled session** (a new `codex` in a scratch directory), or wait
   for the operator's natural restart. Any change to a hook's definition makes it `Modified`
   (new hash) and skipped again until re-trusted; do not assume a running session sees it.
3. **For user and project hooks, editing the script body does not change the hash**, so
   trust covers the command line, not the script's contents (plugin hooks are different:
   Codex also fingerprints the plugin's content). Keep hook scripts where only the operator
   can write.
4. **Never** use `--dangerously-bypass-hook-trust`, and never hand-edit `[hooks.state]` or
   any Codex database or state file to mark a hook trusted. The `/hooks` browser is the only
   path. Plugin hooks are not trusted by installing the plugin.
5. Because the trust key contains **indexes**, inserting, reordering or deleting a group
   shifts the keys of every later group in that event: their trust no longer matches, so they
   stop running until re-reviewed. **Always append new matcher groups at the end of an event's
   array**, as their own group (not as an extra handler inside someone else's group).

## 5. Gather requirements, then write

1. Scope: user (`~/.codex/hooks.json`) or project (`<repo>/.codex/hooks.json`, shared, and
   trusted per project)? Prefer project for repo policy, user for personal tooling.
2. Event and matcher: the narrowest that fits (table above).
3. Effect: audit, deny, allow, rewrite, add context, or continue. Fail open or fail closed?
4. Command or MCP hook. Prefer a script file over a long inline command.

### Minimal example: deny a command

`~/.codex/hooks/deny_force_push.py` (a fail-closed `PreToolUse` policy):

```python
#!/usr/bin/env python3
import json, sys

def deny(reason):
    json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse",
               "permissionDecision": "deny", "permissionDecisionReason": reason}}, sys.stdout)

try:
    command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    if isinstance(command, str) and "git push --force" in command:
        deny("Force push needs the operator.")
except Exception as exc:  # hooks fail open; a policy hook must fail closed itself
    deny(f"policy hook error: {exc}")
```

Handler (append as its own group in `~/.codex/hooks.json`):

```json
{"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
  {"type": "command", "command": "python3 ~/.codex/hooks/deny_force_push.py",
   "timeout": 10, "statusMessage": "Checking Bash command"}]}]}}
```

Smoke test without Codex: `echo '{"tool_input":{"command":"git push --force"}}' | python3 ~/.codex/hooks/deny_force_push.py`
prints the deny JSON; a harmless command prints nothing. Then trust it as in section 4.

### Minimal example: PermissionRequest

Allow only read-only `git status`, deny nothing, leave everything else to the prompt:

```python
import json, sys
e = json.load(sys.stdin)
if e.get("tool_name") == "Bash" and e.get("tool_input", {}).get("command") == "git status":
    json.dump({"hookSpecificOutput": {"hookEventName": "PermissionRequest",
               "decision": {"behavior": "allow"}}}, sys.stdout)
```

Matcher `Bash`, `timeout` 10. To deny, use `{"behavior":"deny","message":"..."}` instead.

## 6. Coexist with existing hooks, and uninstall

Machines already carry hooks from other tools (approval relays, command rewriters, habit
gates, plugin hooks). Preserve all of them.

1. **Read the whole existing file first** and keep a dated copy (`hooks.json.bak-YYYY-MM-DD`,
   not overwritten if it exists) before the first change. Never replace the file with a fresh template.
2. Merge with **one helper**, `hookedit.py` (below): it appends your group last, or removes by
   exact `command`, keeping every other key (including `description`). Run it as
   `python3 hookedit.py PATH add EVENT 'GROUP_JSON'` or `python3 hookedit.py PATH remove EVENT 'COMMAND'`.
   It reports `updated` or `unchanged`. It needs an existing file: on a missing one it fails
   with `FileNotFoundError` and writes nothing. To start from nothing, create the file once
   with exclusive creation, which refuses an existing file (user scope `0o600`; a project
   `.codex/hooks.json` is shared through git, so `0o644`, and it only loads once the
   project's `.codex/` layer is trusted):

```sh
python3 -c 'import os,sys; p=sys.argv[1]; os.makedirs(os.path.dirname(p), exist_ok=True); fd=os.open(p, os.O_WRONLY|os.O_CREAT|os.O_EXCL, int(sys.argv[2],8)); os.write(fd, b"{\"hooks\": {}}\n")' ~/.codex/hooks.json 600
```

```python
#!/usr/bin/env python3
import contextlib, json, os, stat, sys, tempfile

def update_json(path, mutate):
    """Apply mutate(doc) -> changed?; replace atomically; abort if the file moved meanwhile."""
    real = os.path.realpath(path)                   # edit the target, never replace a symlink
    with open(real, "rb") as f:
        snapshot = f.read()
    doc = json.loads(snapshot)                      # corrupt file: fail loudly
    if not mutate(doc):
        return False
    mode = stat.S_IMODE(os.stat(real).st_mode)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(real), prefix=".hooks-", suffix=".tmp")  # private, unique
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)                         # keep the original permissions
        with open(tmp) as f:
            json.load(f)                            # re-parse what will be installed
        with open(real, "rb") as f:
            if f.read() != snapshot:                # last check before the swap
                sys.exit(f"{real} changed while editing; aborted, nothing written")
        os.replace(tmp, real)
        return True
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)                          # no-op after a successful replace

def add(event, group):
    def mutate(doc):
        groups = doc.setdefault("hooks", {}).setdefault(event, [])
        if group in groups:                         # idempotent
            return False
        groups.append(group)                        # append only: never reorder
        return True
    return mutate

def remove(event, command):
    def mutate(doc):
        groups = doc.get("hooks", {}).get(event, [])
        kept, changed = [], False
        for g in groups:
            hooks = g.get("hooks", [])
            rest = [h for h in hooks if h.get("command") != command]
            if len(rest) == len(hooks):
                kept.append(g)                      # untouched, empty or hooks-less included
                continue
            changed = True
            if rest:
                kept.append(dict(g, hooks=rest))    # a group this call emptied is dropped
        if not changed:
            return False                            # no match: nothing rewritten
        if kept:
            doc["hooks"][event] = kept
        else:
            del doc["hooks"][event]
        return True
    return mutate

if __name__ == "__main__":
    path, verb, event, arg = sys.argv[1:5]
    changed = update_json(path, add(event, json.loads(arg)) if verb == "add" else remove(event, arg))
    print("updated" if changed else "unchanged")
```

   The unchanged-bytes check is optimistic: it narrows the window but **cannot serialize a
   writer that does not cooperate** (another agent can still write between the check and the
   replace, and its edit is then lost). Not race-free. A production installer needs a shared
   advisory lock that every writer takes, or a retry loop around a fresh snapshot; never
   describe this helper as race-free. If it aborts, re-read the file and run it again.

3. **Uninstall removes only your own entry** (`remove`, exact `command` you wrote), never a
   whole event or file. `remove` leaves every group it did not change byte-for-byte as it was
   (empty or `hooks`-less groups included) and drops only a group this call emptied. Dropping
   that group shifts the trust index of every group after it in the event, so if anything
   sits after yours those later hooks lose trust until re-reviewed in `/hooks`: say so (a
   group appended last shifts nothing). Leave the `[hooks.state]` lines alone. Delete the
   hook script file only if you created it, and `~/.codex/hooks/` only if you created it and
   it is now empty.
4. Do not touch `notify`, `[features]`, `[hooks.state]`, plugin directories or other tools'
   scripts. If the target layer has inline `[hooks]` in `config.toml`, add to that form rather
   than creating a second `hooks.json` that triggers the merge warning.
5. Existing hooks of unknown purpose run concurrently with yours and a `deny` from any wins;
   an `allow` from yours does not override another hook's `deny`.

## 7. Review checklist before finishing

1. Events are PascalCase, paths are `.codex/`, no `.cursor/` anywhere.
2. `matcher` follows the exact-name/regex rule (section 2): `Bash` is exact, `^mcp__memory__`
   covers a whole server; ignored events have none.
3. Policy script fails closed; `timeout` set short for `PermissionRequest`.
4. JSON parses; existing entries unchanged; new group last.
5. Trust handled per section 4: definition shown and authorized, `/hooks` hash path only,
   no bypass flag, no state edits, no restart of live TUIs.
6. Docs consulted for the installed version: `codex --version`, then the official page.
