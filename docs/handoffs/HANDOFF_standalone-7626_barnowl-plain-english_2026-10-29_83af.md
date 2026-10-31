---
schema_version: 1
handoff_id: 83af
parent_handoff_ids: []
lineage: none
chain: [standalone-7626]
repo: kool-ade
workspace: main
branch: master
head_sha: ff5ea1154a412e3ad1212341fba0dc4469d5df42
created_at: 2026-10-29T17:10:00-0400
writer: grok
---
# Handoff — BarnOwl plain English, Forgejo publish, sudo-secretspec prompt

## The Goal

Give Daniel a plain-English BarnOwl workflow: a skill in `kool-ade`, a shell command `g`, an in-client `:g show my subs`, a public Forgejo snapshot, version 1.0.1 only on `barnowl-history-loader`, and the MIT index updated. Then preserve, for the other coding agent, the prompt that asks for a non-NixOS Linux installer of sudo-secretspec. This session does not implement that installer.

The product work is done. This document is the close.

## Where We Are

Checked 2026-10-29 about 17:00 EDT on pastebin (Debian 13, user djbclark), before this handoff commit.

`~/src/djbclark-ade` is on `master`, clean, even with `origin/master`, at `ff5ea1154a412e3ad1212341fba0dc4469d5df42` (`barnowl: :g show my subs, and run shell g on grok-4.5`, parent `f144120`). This handoff commit is the only later commit, and it is local until the operator pushes it. `docs/queue.md` has no BarnOwl task.

GitHub canonical skill: `skills/barnowl/` in `github.com/djbclark/djbclark-ade`. Slash forms are `/barnowl` and `/g`. Shell form is `g list my subs` (`~/.local/bin/g` → `bin/g`). `~/.bashrc` (interactive only, after the early return) prepends `~/.local/bin`. `~/.owl/startup` ends with `perl do q{/home/djbclark/src/djbclark-ade/skills/barnowl/g-cmd.pl}`.

Forgejo, re-read from the API (token file used, value not printed):

- `djbclark/barnowl` public, `fork=false`, `parent=none`, branch `main` `39c1667600a4` "Drop the client version. That number belongs on barnowl-history-loader." Tags empty. Releases empty. README has "This works." and no "Version 1." heading. It is not a fork of the BarnOwl client.
- `djbclark/barnowl-history-loader` public, `main` `03aac710be18` "barnowl-history-loader 1.0.1". Tag `v1.0.1`. Release name `1.0.1`, tag `v1.0.1`, id `37`. README starts with `Version 1.0.1` and "This works."
- `djbclark/mit` public, `main` `506022365aa5` "Move version 1.0.1 to barnowl-history-loader". README has history-loader 1.0.1, the sentence "not a version of the BarnOwl client", and no `barnowl/releases/tag` link.
- All 22 public `djbclark` repos have a root `README.md`. One private repo was left alone.

Live client: tmux is not running (`no server running on /tmp/tmux-1000/default`). The only `barnowl` process is pid `702021` on `pts/0`, parent bash `688061`, up since about 11:00 EDT. `scripts/bo` still targets tmux session `barnowl`, which is absent. Do not send keys to `pts/0`.

`~/.config/forgejo/token` is mode `600`, 40 bytes. `~/.ssh/known_hosts` has 3 lines written while trying to reach the Mac. `/tmp/s-s.txt` is gone, by the operator's choice. No open bigteam job for this session.

## What We Tried

Failed, and why:

- `grok -p --no-plan …` does not pass the prompt. `--single` / `-p` must receive the prompt itself. A later flag is not a value. `g list my subs` exited 2 until `bin/g` put the prompt on `--single`. An earlier argv check, before the model flags, showed `ARG1=--single` and `ARG2=/barnowl list my subs`.
- `zctl retrieve` fails with "No such file or directory while finding WindowGram port" while BarnOwl holds that port. Live subs come from `BarnOwl::zephyr_getsubs`, not `zctl retrieve`.
- Typing `g show my subs` at BarnOwl's `:` prompt returned `Unknown command 'g show my subs'` because `g` was only a shell command. `cmd.c` reports the whole line. Fixed by `g-cmd.pl`. The operator then said it works. Do not re-inject keys to re-test.
- Calling shell `g` from inside the same BarnOwl window deadlocks: the client blocks while Grok's `bo` waits to type into that client. `:g` stays in-process and only lists subs.
- sudo-secretspec cannot be installed here. On Linux, `install` / `uninstall` / `rollback` / `doctor` refuse. The published boundary is the NixOS module. This host is Debian 13, `nix` is absent, and `sudo -n true` fails. The word "experimental" was the operator's; the source does not use it.
- The first token-pipe draft broke in bash when a backslash continuation had a trailing space (`syntax error near unexpected token '|'`). The secret must stay inside the single-quoted `bash -c` script, and `printf` format must be `"%s"`. The operator ran a corrected one-line pipe. Do not print the token and do not repeat that pipe here.
- `gt` (the new Gitea CLI) needs Gitea 28. forgejo.mit.edu is Forgejo 16 (Gitea 1.22 API). `fj`  and `tea` 0.16.0 are what this host has. `fj --version` is not a flag. `tea` 0.16.0 and `gh` 2.103.3 were re-checked. `tea login add` was not run.
- Version 1.0 and then 1.0.1 were published on `djbclark/barnowl` (tags, releases, README). The operator said that number belongs only on `barnowl-history-loader`. Tags and releases were deleted there; the README version heading was removed; history-loader got `v1.0.1` and the mit index was corrected.
- Copying the sudo-secretspec prompt to `/tmp/s-s.txt` on the Mac failed. SSH to `djbclark@100.113.53.87` was `Permission denied (publickey)`. A pipe to `head` made an earlier exit status look like 0; that status was `head`'s. `tailscale ssh` wanted a coordination-server host key the node does not advertise. `tailscale file cp` to `mac:` printed `Access denied: file access denied` (the shell status was again the pipe's). The operator then chose to delete the pastebin copy. Do not recreate `/tmp/s-s.txt` and do not retry SSH or Taildrop unless they ask.
- `self-slash --dry-run "/new"` on this herdr pane (`w3:p3`, agent `grok`) warned that prompt detection only knows claude, cursor, omp, codex, and zcode, so the waiter will probably exit 5. The script also calls `gtail` and `gtr`, which are not installed here (`tail` and `tr` are). Dry-run still printed that it would send `/new`, then `/baton`.

## Key Decisions

Shell `g` is a separate command. It does not wrap or shadow the `grok` binary. Literal `grok list my subscriptions` would treat `list` as the prompt and `my` as a subcommand. Inside Grok, plain English and `/barnowl` and `/g` are the skill. `/g` is `disable-model-invocation` so the letter does not auto-fire.

`:g` is only `g show my subs` (also list/print/get, with or without "my"). Anything else errors and points at the shell. Sending a zephyr, changing subs, or quitting happens only when the English asks for it. Headless `g` cannot ask a second time. `g` uses `--permission-mode bypassPermissions` so `zctl` and tmux can run; the skill is the safety check. It also uses `--no-plan`, `--no-subagents`, `--max-turns 12`, `--cwd "$HOME"`, `--model grok-4.5`, `--reasoning-effort low`. Models on this account: grok-4.7, grok-4.7-build-fast, grok-4.6, grok-4.5. Effort: xhigh, high, medium, low. No mini model.

Drive only a tmux session named `barnowl`. That session is not running now. Do not point `bo` at `pts/0` and do not start tmux unless the operator asks.

HTTPS for GitHub, not SSH. Do not copy Mac private keys. This host has no SSH private key. Author for commits is the environment (`Daniel JB Clark <djbclark@gmail.com>`), not a new `~/.gitconfig`.

Forgejo `djbclark/barnowl` is a pointer and a snapshot of the skill files, not a client fork and not a versioned release. The copy that stays current is GitHub `skills/barnowl`. Version 1.0.1 is only history-loader.

The two Unreleased changelog lines have no pull-request number. Both commits were direct pushes to `master`, which is what was asked. Leave them unless the operator asks for a PR.

The audit residual risk in sudo-secretspec (truncation or deletion of the whole ledger) is not part of the installer task.

This handoff is committed in the shared `~/src/djbclark-ade` checkout. The tree was clean and matched origin, and the filename is unique. It is not pushed: AGENTS.md has a general "commit and push" order and no "memory is data, push in place" exception. Standing order 9 wants a worktree for edits; this commit follows the handoff skill's Step 6 path instead.

## Decisions

- [decision] Shell `g` calls `grok --model grok-4.5 --reasoning-effort low --single` and does not shadow the grok binary; rejected: wrapping grok, and passing flags after `-p`; because the prompt must be the value of `--single`; decided_in [[HANDOFF_standalone-7626_barnowl-plain-english_2026-10-29_83af]]
- [decision] `:g` stays inside BarnOwl and only lists live subscriptions; rejected: launching Grok from the colon prompt; because Grok driving the same window stalls on the command that started it; decided_in [[HANDOFF_standalone-7626_barnowl-plain-english_2026-10-29_83af]]
- [decision] Version 1.0.1 is only `djbclark/barnowl-history-loader`; rejected: tagging `djbclark/barnowl`; because that repository is not the BarnOwl client; decided_in [[HANDOFF_standalone-7626_barnowl-plain-english_2026-10-29_83af]]
- [decision] Pastebin Forgejo auth is `~/.config/forgejo/token` mode 600, read into the environment; rejected: `tea login add`; because that stores the token in tea's config; decided_in [[HANDOFF_standalone-7626_barnowl-plain-english_2026-10-29_83af]]
- [decision] Do not install sudo-secretspec on this Debian host; rejected: running the NixOS-only lifecycle; because those commands refuse here and the installer work belongs to the other agent; decided_in [[HANDOFF_standalone-7626_barnowl-plain-english_2026-10-29_83af]]
- [ruling] "HTTPS is fine if the auth login makes that work." (djbclark, 2026-10-29)
- [ruling] "Oh we should proably use the weakest available model for it to avoid wasting tokens" (djbclark, 2026-10-29)
- [ruling] "I meant the version only for our barnowl-history-loader repo." (djbclark, 2026-10-29)
- [ruling] Selected "Delete the pastebin copy" for `/tmp/s-s.txt`, then "Handoff and continue". (djbclark, 2026-10-29)

## Relations

- decided_in [[HANDOFF_standalone-7626_barnowl-plain-english_2026-10-29_83af]]

## Evidence & Data

Files this session added or changed, all in `ff5ea11` except this handoff:

- `skills/barnowl/SKILL.md`, `skills/barnowl/g-cmd.pl`, `skills/barnowl/scripts/bo`, `bin/g`
- `claude/commands/g.md`, `zcode/commands/g.md`
- `README.md` and `docs/skills.md` (one row each, after gmail-search)
- `CHANGELOG.md` two Unreleased Added bullets, no `(#N)`
- Outside the repo: `~/.bashrc` barnowl block, `~/.owl/startup` perl `do` line, `~/.local/bin/g` symlink, `~/.grok/skills/barnowl` via skill-everywhere, `~/.grok/commands/g.md` and `~/.claude/commands/g.md` symlinks, `~/.local/bin/{gh,tea,fj}`, `~/.config/forgejo/token`, `~/.ssh/known_hosts`

`~/src/barnowl` is a depth-1 clone of `github.com/barnowl/barnowl`, clean, `master` at `1f65aee`. Not our commits. Command catalog source of truth is `commands.c` `OWLCMD_*` lines. Do not paste that list into the skill.

Tests:

- `g list my subs` exited 0 in about 27 seconds and printed the live triples, before the grok-4.5 flags existed. The log was deleted at the operator's request. Not re-run.
- The grok-4.5 and `--reasoning-effort low` flags were reviewed in `bin/g` and not exercised with a model call.
- The operator said `:g show my subs` works after a BarnOwl restart. Not re-tested by sending keys.
- `bo run 'getvar logging'` printed `on`, and a perl `do` of `g-cmd.pl` loaded inside the old tmux client. That tmux server is gone.
- Forgejo API re-check above. No skill unit tests were added. `perl -c` on `g-cmd.pl` warns about a constant because it runs the file as a script; `do` from startup is the real load.

Kerberos was `djbclark@ATHENA.MIT.EDU`, cache `FILE:/tmp/krb5cc_1000`, valid 2026-10-29 09:19–19:19 when checked. Do not run `kinit` if it has expired.

Host bits that are not the product: Tailscale node `pastebin` `100.104.212.89`. Mac is `mac` / `100.113.53.87`, online. No `SSH_AUTH_SOCK`. No passwordless sudo. `hermes-ping` is not installed. `~/.local/state/handoffs` did not exist before this handoff. `session_log.py` on this host is `~/src/djbclark-ade/claude/hooks/handoff-tools/session_log.py` (the `~/.claude/hooks/handoff-tools` symlink is absent). PyYAML 6.0.2 is on system `python3` 3.13.

### Prompt for the sudo-secretspec coding agent

This is the only durable copy. The operator asked for it at `/tmp/s-s.txt` on the Mac. Delivery failed. They then chose to delete the pastebin file. Do not write it back to `/tmp/s-s.txt` unless they ask. Do not change the audit-ledger residual risk.

```text
Add an imperative installer for non-NixOS Linux. Keep the NixOS module.

Today `platform::lifecycle_refusal` refuses `install`, `uninstall`, `rollback`, and `doctor` on every Linux target. The message says the privilege boundary is only the NixOS module `services.sudo-secretspec` (`nix/module.nix`, `nixosModules.default`). That is true for NixOS and wrong for Debian and other ordinary Linux. On Debian, `sudo` is `/usr/bin/sudo`, `/usr/bin` exists, and there is no `/run/current-system`.

The Linux constants in `sudo-secretspec-cli/src/platform.rs` are NixOS-shaped: `SUDOERS_SECURE_PATH` is `/run/current-system/sw/bin:/run/wrappers/bin`, and `CLIENT_PATH` is `/run/current-system/sw/bin/sudo-secretspec`. `install.rs::linux_sudoers_text` therefore omits the `timestamp_timeout=0` client line and the `doctor` grants, and the tests `linux_policy_grants_broker_verbs_only` and `linux_sudoers_text_refuses_non_principal_identities` lock that in. The broker path `/usr/libexec/sudo-secretspec`, config `/etc/sudo-secretspec.toml`, sudoers file `/etc/sudoers.d/sudo-secretspec`, vault `/var/lib/sudo-secretspec`, and service account `sudo-secretspec` can stay. The client path and `secure_path` cannot.

Do this:

1. Split "Linux" from "NixOS". NixOS keeps declarative install: `install` / `uninstall` / `rollback` / `doctor` still refuse there and still point at `services.sudo-secretspec`. A rebuild remains the only way that boundary changes. `systemd.tmpfiles` and the store-path broker stay as they are.

2. On non-NixOS Linux, `sudo-secretspec install` creates the same boundary the macOS installer creates, with Debian paths: service user and group `sudo-secretspec` (no leading underscore; hyphen allowed), vault `/var/lib/sudo-secretspec` mode 0700 owned by that user, protected config, a broker binary at `/usr/libexec/sudo-secretspec` that is a different file from the public client, and a staged sudoers file that cannot take effect until `visudo` accepts it. `uninstall` and `rollback` work. `doctor` checks this layout, not the macOS one (`/bin/ls`, Homebrew, `/etc/static`, a `sudoers.d` `#include` line).

3. The public client lives on the real `PATH` (`/usr/local/bin/sudo-secretspec` is fine). `secure_path` includes `/usr/bin` and the client directory. NOPASSWD is granted only for the broker path and the broker verbs that are granted today. Do not grant NOPASSWD for `install`, `uninstall`, `rollback`, or `doctor`. Do not grant `ALL`. Keep the identity grammar that rejects `ALL` and other non-principals.

4. Detect NixOS by the running system (`/run/current-system` or the equivalent you already trust), not by `target_os = "linux"`. A binary built on Debian must refuse the imperative installer when it is actually running on NixOS, and a binary built for NixOS must keep the module's baked broker path (`SUDO_SECRETSPEC_BROKER_PATH`).

5. Ship a Linux x86_64 artifact. The current release assets are the macOS arm64 bottle. Debian has no `nix` and no passwordless `sudo` until the operator runs the installer.

Leave the audit ledger's residual risk alone. Truncation and whole-ledger deletion are undetectable from inside the ledger; that is documented in `audit.rs` and is not this task.

Read `platform.rs`, `install.rs` (`run`, `sudoers_text`, `linux_sudoers_text`, `stage_sudoers`), and `nix/module.nix` before editing. Add tests that a Debian-shaped policy names `/usr/bin` and the client path, that the NixOS policy text is unchanged, and that `lifecycle_refusal` still fires on NixOS and not on Debian. Run the existing installer tests.
```

## Operator Feedback

- Do not invent tokens. Say exactly what a missing credential blocks.
- HTTPS for `gh`. Do not fetch Mac SSH private keys.
- The Forgejo repo is public.
- They use bash. The token pipe's quoting bug was bash, not zsh.
- "it works" after `:g show my subs` was added. Then push, and say that it works.
- Weakest model, to avoid wasting tokens. Then "I mean 1.0.1".
- Every public Forgejo project needs a README. Update the mit index for what it lacked or what changed.
- The version number was meant only for `barnowl-history-loader`, not for a BarnOwl client fork. The Forgejo barnowl repo is not that fork; the README now says so on the mit index.
- First `/loose`: delete scratch, then keep working.
- Second `/loose`: delete the pastebin prompt file, then hand off and continue.
- They asked for the prompt at `/tmp/s-s.txt` on the Mac. That copy was not delivered.

## Where We're Going

1. Next action: stop. Read `docs/handoffs/HANDOFF_standalone-7626_barnowl-plain-english_2026-10-29_83af.md` and wait. Do not edit BarnOwl, Forgejo, or sudo-secretspec. The other coding agent owns the Debian installer. The prompt is the fenced block in Evidence above. Do not write `/tmp/s-s.txt`.
2. Only if the operator asks to drive the live client again: tmux has no server, so `bo` cannot see session `barnowl`. The only client is pid `702021` on `pts/0`. Do not send keys there. Do not start tmux unless they ask.
3. Optional, not requested: live-test `g list my subs` with the grok-4.5 flags; add pull-request numbers to the two changelog lines; push this handoff commit. Leave all three unless they ask.
4. Do not `kinit`, do not send a zephyr, do not change subscriptions, do not delete `~/.config/forgejo/token`, do not install sudo-secretspec on pastebin, do not put a version number back on `djbclark/barnowl`.

## Detached jobs

none

## Quick Start

```bash
git -C ~/src/djbclark-ade status -sb
git -C ~/src/djbclark-ade log -1 --oneline
tmux list-sessions
```

Tier 1 pointer, after Step 7: `~/.local/state/handoffs/kool-ade/main/SESSION_LOG.md` redirects to `chains/standalone-7626/SESSION_LOG.md`.

Skill body: `~/src/djbclark-ade/skills/barnowl/SKILL.md`. Shell entry: `~/src/djbclark-ade/bin/g`.
