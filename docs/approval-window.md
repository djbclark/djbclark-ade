# The approval window also answers agent permission prompts (2026-11-22)

Operator ruling, 2026-11-22: "we want our limited-duration token to also avoid prompts such as this". The "token" is the
sudo-ask approval window (site-public-djbclark, `sudo-ask grant [DURATION]`: one Touch ID opens a timed window, 1 minute to 24
hours). While it is open, `sudo-ask` commands run without a dialog. This change makes the same window clear **agent
tool-permission prompts** too: Paseo's Accept/Deny card and Claude Code's own prompt. Nothing here opens, extends or ends a
window; it only reads one.

The prompt that started it: under Paseo, a Claude agent in bypass mode ran `rm -f $S/all.done $S/*.log` and the card read
"Dangerous rm operation on possibly-empty variable path: $S/*.log ... (rewrite it as "${S:?}"/*.log or use a literal path)".
That is Claude Code's built-in `rm` safety check. No allow rule and no PreToolUse hook approves it; in bypass mode it falls
through to the host's `canUseTool` callback, which for Paseo is the card (docs: permission-modes.md, agent-sdk/permissions.md,
hooks.md on code.claude.com).

## I. What the window covers

***1.*** **`sudo-ask` commands** (the site repo's `roles/sudo_ask_grant`): unchanged by this change; the root helper judges them.

***2.*** **Paseo permission requests of every provider** (Claude, Codex, OpenCode, Pi, OMP and the ACP-backed ones): the
responder `bin/ade-approval-window` (logic in `bin/ade_approval_window.py`) lists pending requests and allows the ones the
policy below allows, for any agent.

***3.*** **A Claude Code session Paseo does not run**: the `PermissionRequest` hook `claude/hooks/approval_window_permit.py`
returns the documented allow decision under the same policy and window check. It prints nothing otherwise, so the normal prompt
is shown.

## II. The window file

`/var/db/sudo-ask/grant` (directory `root:wheel 0755`, file `root:wheel 0644`), JSON `{expires_utc, granted_utc,
granted_by_uid, duration_s, nonce}`, written by the root helper `sudo-ask-granted grant` (site-public-djbclark branch
`feat/sudo-ask-grant-window`, `roles/sudo_ask_grant/files/sudo-ask-granted`, `read_grant`). `read_window` in
`bin/ade_approval_window.py` mirrors that reader and fails closed. The window is open only when:

- the directory and the file are owned by root and neither is group- or world-writable (`mode & 0o022 == 0`);
- the directory and the file are not symlinks (`lstat`; the open uses `O_NOFOLLOW` and re-checks the inode and mode on the
  descriptor);
- the file is at most 4096 bytes and the JSON has all five fields, with the helper's types (the nonce is 32 lower-case hex digits);
- `duration_s` is 60 s to 24 h and `expires_utc - granted_utc == duration_s`; `granted_utc` is not more than 120 s ahead of the clock;
- `expires_utc` is in the future and **not more than 24 h away** (a far-future file is tampering, so it is closed).

Any error is "closed". The path is hard-coded; only function parameters (tests) move it. The installed
`/usr/local/libexec/sudo-ask-granted` was an unreviewed draft when this was written: nothing here runs it, calls `sudo-ask
grant|revoke|status` or uses sudo.

## III. Policy while the window is open

First match wins. The audit line records the rule.

***1.*** **Stays pending** (the operator is asked as before):

***a.*** *Not a plain tool request*: Paseo's `kind` is `plan`, `question`, `mode` or `other` (or missing), or the tool name is a question
or plan name (`AskUserQuestion`, `ExitPlanMode`, `EnterPlanMode`, `CodexPlanApproval`, `request_user_input`, ...; the stem
list is copied from `bin/ade-auto-permit`). Allowing a question answers nothing and allowing a plan skips the review. Rules
`kind:*`, `question:*`.

***b.*** *Unreadable* (rule `unreadable:*`): a command tool (Bash, CodexBash, `execute`, any request with a `command` field) with no
command text, a file tool (Write, Edit, Read, `CodexFileChange`, ...) with no path, a request with no input, detail or title at
all, or a string over 200,000 characters. `CodexFileChange` carries only a free-text reason, so Codex file-change prompts always
stay pending.

***c.*** *The sudo-ask denylist* (rule `denylist:*`), mirrored from the site helper's `PROTECTED`, `TRIPWIRE`, `ALWAYS_DENY` and
verb lists: any string of the request (command, path, title, reason, raw ACP input; never file content or diff text) containing
`sudoers`, `pam.d`, `sudo.conf`, `sudo-ask-grant`, `sudo-ask-granted`, `/db/sudo-ask`, `secretspec` (the
`sudo-secretspec` broker, its policy, its test boundary), `/usr/local/libexec`, `/usr/local/sbin`, `com.apple.TCC`, `tcc.db`,
`Library/Keychains`, `.keychain` or `dslocal`; and a command that runs `visudo`, `csrutil`, `nvram`, `tccutil`, `fdesetup`,
`pwpolicy`, `systemsetup`, `dseditgroup`, `sysadminctl`, `passwd`, `profiles`, `fdisk`, `gpt`, `asr`, `newfs_*`, `mkfs*`,
`sudo-ask grant|revoke`, `diskutil` with any verb outside the read-only list (so `erase*`, `secureErase`, `apfs delete*`),
`dscl` unless it only reads, or `security` unless its verb is read-only (so keychain edits stay pending). A word such as
`passwd` or `security` counts only where a command stands (first word, after `sudo`/`env`/`time`/...), so `echo passwd` and
`cat /etc/passwd` do not trip it.

***d.*** *A critical-path removal* (rule `critical-rm:*`, or `critical-reason` when the card's own title or description says "critical
path"): `rm`, `rmdir`, `unlink`, `srm`, `shred`, `find ... -delete`, or `chmod|chown|chgrp|chflags -R`, aimed at `/`, `~`, `$HOME`,
`/Users`, a home directory (`/Users/<name>`), `/System` (and its tree), `/usr`, `/etc`, `/var`, `/private`, `/Volumes/<volume>`,
`/bin`, `/sbin`, `/opt`, `/opt/homebrew`, `/usr/local`, `/Library`, `/Applications`, `/tmp`, the system `bin`/`lib` trees,
or `D/*` for any of them. Symlinks are resolved (`/etc` is `/private/etc`). Variables are modelled as **empty**, the failure Claude
Code's own check warns about: `rm -rf $S/` is `rm -rf /` and stays pending, `rm -rf $S/*` is `rm -rf /*` and stays pending.

***2.*** **Allowed** (rule `allow:window`): everything else, any agent, any provider. In particular **the "possibly-empty variable"
class from the screenshot is allowed**: `rm -f $S/all.done $S/*.log` models as `/all.done` and `/*.log`, which name no critical
path. Allowed are also MCP tools, WebFetch, ordinary Bash and file edits, and the hold list of `bin/ade-auto-permit`
(`respond_to_permission`, `set_agent_mode`, ...) is **not** applied: the operator's ruling is no prompts while the window is open.

***3.*** **Window closed** (missing, expired, revoked, or any check above fails): nothing at all. The responder does not contact
the daemon, writes no log line, and the hook prints nothing.

## IV. How it answers (Paseo's interface, read from source on 2026-11-22)

Paseo's loopback Agent MCP route, `POST http://127.0.0.1:7263/mcp/agents` (`daemon.listen` in `~/.paseo/config.json`; stateless
streamable HTTP, no session; `packages/server/src/server/bootstrap.ts:1537`, open when no daemon password is set, as here):

- `list_pending_permissions` (`packages/server/src/server/agent/tools/paseo-tools.ts:3211`) returns every pending request of every
  agent with the whole request: `name`, `kind`, `title`, `description`, `input`, `detail`, `metadata`.
- `respond_to_permission` (`paseo-tools.ts:3245`) takes the exact `agentId`, `requestId` and `{behavior: "allow"}`.

Why not the CLI: `paseo permit ls --json` rows carry only `id`, `agentId`, `name` and `description`
(`packages/cli/src/commands/permit/ls.ts:8-14, 28-38`). A Claude Bash request has no description, and its command lives in `input`
and `detail` (`providers/claude/agent.ts:5030-5067`; Paseo does not forward the SDK's decision reason), so the CLI cannot tell
`rm -rf /` from `ls`. `paseo permit allow AGENT REQUEST` (`permit/allow.ts`) matches request ids by prefix; the MCP tool is exact.
The responder refuses any daemon URL that is not `http://<loopback>/mcp/agents`, bypasses proxies, and treats any unreadable
answer as an error with nothing approved.

```sh
bin/ade-approval-window status [--json]            # exit 0 open, 1 closed; never contacts the daemon
bin/ade-approval-window respond --once             # one sweep
bin/ade-approval-window watch [--interval S] [--duration S]
```

`watch` polls every 2 s at most (a smaller `--interval` is raised to 2) and contacts the daemon only while a grant file exists. The
window is re-read before **every** allow. One responder per audit path (a lock file), so overlapping runs never double-answer.

Audit: `~/.local/state/djbclark-ade/approval-window/permits.jsonl` (mode 0600), one line per decision: `time` (UTC), `agent`,
`provider`, `tool`, `request`, `command` (at most 200 characters, credential-looking text replaced by `<redacted>`), `decision`
(`allow`, `hold`, `error`) and `rule`. The `allow` line is written **before** the answer is sent; a log that cannot be written
means nothing is allowed. Held requests are logged once per `watch` run (a one-shot `respond` or a new run logs them again).

## V. Threat notes

***1.*** **An agent cannot open or extend a window.** The grant file and its directory are root-owned and not writable by the
operator's user; only the root helper writes them, and `grant` needs Touch ID (the site's sudoers drop-in).

***2.*** **No new power.** An agent can already call `paseo permit allow` or the MCP `respond_to_permission` itself today (Paseo
has no per-caller authorization on its loopback routes). This tool adds no capability beyond automating the operator's own Accept,
inside a window the operator opened.

***3.*** **It approves for ALL agents on the machine, a compromised one included, until the window expires or is revoked.** A prompt
injected into one agent can have its next Bash card answered. The window is the bound: pick the shortest duration that covers the
work, and `sudo-ask --revoke` ends it.

***4.*** **The denylist is a guard rail, not a sandbox.** It reads the text of the request. `sudo''ers`, a variable, a glob, a script
the agent wrote first and ran later, or `python3 -c` that opens `/etc/sudoers` are not seen. The same limits the site helper
documents for root commands apply. (The prompts replaced here belong to agents that run as the operator, not as root, so the
worst case is the operator's own files, which a bypass-mode agent could already change.)

***5.*** **Fail closed everywhere**: a window that cannot be proven open, a daemon answer that is not Paseo's shape, an unwritable
audit log, an unreadable request: nothing is allowed.

***6.*** No `ade.kind=external-review` hold (`bin/ade-auto-permit` has one): the operator's rule here is "any agent". No launcher sets
that label today.

## VI. Enabling it (nothing is installed by the change that added this)

***1.*** Open a window: `sudo-ask grant 2h` (the site tool; Touch ID). Check: `bin/ade-approval-window status`.

***2.*** Paseo agents: either run `bin/ade-approval-window watch` in a Paseo terminal, or render the launchd template
`config/launchd/com.djbclark.ade-approval-window.plist` (`bin/ade-sched render`, then install after the operator's yes; it is a
template, no inventory row selects it, and its log directory must exist). It runs `watch --duration 50` every 60 s (an
`ade-job-run` admission lock covers the whole run, so a reconcile defers while one runs).

***3.*** Non-Paseo Claude Code: the hook is registered in `agents/claude/settings.json.tmpl` under `PermissionRequest` (matcher `*`, behind
`hook-deadline 8`, outer timeout 15, after Orca's own entry); it takes effect when the operator
applies the template (`bin/ade-settings-apply`) and `ade update` links the hook.

## VII. Open items (live checks the lead makes)

***1.*** Whether a `PermissionRequest` hook's allow clears a prompt that is already showing (the interactive countdown) is
**not documented**; hooks.md says only that the hook runs when Claude Code "is about to ask you for permission", and that for a
call that reaches an Agent SDK `canUseTool` callback the hooks "run alongside your host, and whichever decides first applies".
So, for Paseo's own Claude agents, the hook (if their settings load it) may also win the race; the responder is the primary route
there and is the same policy either way.

***2.*** Codex file changes (`CodexFileChange`) and other requests that expose no path stay pending by rule (III 1b).

***3.*** The grant schema and the denylist are mirrored from an unreleased site branch; when the site tool changes either,
update `read_window` and the lists here in the same change (`tests/test_ade_approval_window.py` pins both).

***4.*** `ade-auto-permit` (a separate, name-only, always-on sweep, template only) is unchanged.

Tests: `tests/test_ade_approval_window.py` (the checker, the policy, the responder against a fake daemon and against a fake HTTP
opener that speaks Paseo's MCP framing, the CLI, the hook). Nothing in them opens a socket or reads the real grant, daemon or log.
