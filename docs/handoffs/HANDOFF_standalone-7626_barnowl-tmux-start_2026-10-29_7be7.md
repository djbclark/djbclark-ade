---
schema_version: 1
handoff_id: 7be7
parent_handoff_ids: [83af]
lineage: inferred
chain: [standalone-7626]
repo: kool-ade
workspace: main
branch: master
head_sha: b68befa2d38c0b2fabf1e0ed36eafe7c46a031c0
created_at: 2026-10-29T17:54:00-0400
writer: grok
---
# Handoff — BarnOwl start path, herdr vs tmux, memory version fix

## The Goal

After the first handoff of this chain, answer the open operational questions: put the version story right in durable memory, choose how to host the live client (herdr vs tmux), and document how to start BarnOwl with Kerberos tickets so `bo` / `g` work. Do not implement the sudo-secretspec Debian installer (still the other agent's job; full prompt is in the parent handoff).

## Where We Are

Quick pass over the delta since parent `83af`. Checked 2026-10-29 ~17:53 EDT on pastebin.

`~/src/djbclark-ade` is on `master` at `b68befa` (`docs: handoff barnowl-plain-english`), ahead of `origin/master` by 1, working tree clean before this handoff commit. Product commits for the skill remain `ff5ea11` / `f144120` on GitHub.

Forgejo (API, token not printed): `djbclark/barnowl` tags and releases empty; `barnowl-history-loader` tag `v1.0.1`, release id 37. Unchanged and correct.

Host: no tmux server. No `barnowl` process (the earlier `pts/0` pid 702021 is gone). `bo` is not on `PATH` (only `~/src/djbclark-ade/skills/barnowl/scripts/bo`). `g` is on `PATH` via `~/.local/bin/g`. Kerberos TGT for `djbclark@ATHENA.MIT.EDU` expires 23:09 tonight; `renew until` is the same time, so `kinit -R` cannot extend past that. `krenew` / `kstart` are not installed; Debian package name is `kstart`. `zhm` is running. `/tmp/s-s.txt` is still absent.

Workspace memory was wrong about versions; it is fixed (see Evidence). Parent Tier 2 still holds the sudo-secretspec prompt and the full product narrative.

## What We Tried

- After handoff `83af`, `self-slash "/new"` queued but warned that Grok panes are outside its prompt-detection set and that `gtail` / `gtr` / `gsed` / `grealpath` are missing on this Debian host. The session did not clear; the operator kept working in the same context. That is why this handoff's lineage is inferred.
- `kinit -R` failed here with `Credentials cache I/O operation failed while saving to cache` and would not have extended life anyway (`Expires` equals `renew until`). Do not rely on renew with the current ticket.
- Pure herdr as the driver for `bo` was considered and rejected for now: `bo` is hard-wired to `tmux send-keys` / `capture-pane` on session `barnowl`. Herdr has `pane send-text` / `send-keys` / `read`, but using them means rewriting `bo`.

## Key Decisions

Version 1.0.1 stays only on history-loader. Stale memory that put v1.0 / v1.0.1 on `djbclark/barnowl` was rewritten so later sessions do not re-publish a wrong number.

For hosting the live client: prefer plain tmux (`tmux new-session -A -s barnowl barnowl`). If the operator wants BarnOwl visible inside herdr, run that same tmux command inside a herdr pane. Do not rewrite `bo` for pure herdr unless someone wants to drop tmux on purpose.

Bare `bo` does not start BarnOwl. Start recipe: valid tickets, then the named tmux session. Long-lived auto-renew needs `kstart` (`krenew`) plus tickets issued with a renew lifetime past the current expiry (`kinit -r …`). Agents still must not run `kinit` (password).

## Decisions

- [decision] Keep driving BarnOwl through tmux session `barnowl`; rejected: rewriting `bo` for pure herdr now; because herdr send/read exist but the skill and `g` already depend on tmux; decided_in [[HANDOFF_standalone-7626_barnowl-tmux-start_2026-10-29_7be7]]
- [decision] tmux inside a herdr pane is fine when the operator wants BarnOwl in the herdr UI; rejected: treating herdr alone as enough for `bo`; because `bo` does not speak herdr; decided_in [[HANDOFF_standalone-7626_barnowl-tmux-start_2026-10-29_7be7]]
- [decision] Document start as tickets then `tmux new-session -A -s barnowl barnowl`; rejected: implying bare `bo` or bare `barnowl` is the automation entry; because `bo` is not on PATH and only attaches to the named session; decided_in [[HANDOFF_standalone-7626_barnowl-tmux-start_2026-10-29_7be7]]
- [decision] Rewrite workspace memory so version 1.0.1 is only on barnowl-history-loader; rejected: leaving topics/barnowl-release-v1.md claiming Forgejo barnowl v1.0; because live Forgejo and the operator's ruling disagree with that topic; decided_in [[HANDOFF_standalone-7626_barnowl-tmux-start_2026-10-29_7be7]]
- [ruling] "Fix C1. Can I run in herdr instead of tmux, or would it be less pain to just use tmux, or even tmux inside of herdr? Do all of C1 before moving to the second item." (djbclark, 2026-10-29)
- [ruling] "Does just typing \"bo\" in a shell do the right thing, or in general how to start up barnowl with renewing tickets correctly?" (djbclark, 2026-10-29)

## Relations

- continues [[HANDOFF_standalone-7626_barnowl-plain-english_2026-10-29_83af]]
- decided_in [[HANDOFF_standalone-7626_barnowl-tmux-start_2026-10-29_7be7]]

## Evidence & Data

Parent handoff (product ship, sudo-secretspec prompt, Forgejo SHAs at first close):
`docs/handoffs/HANDOFF_standalone-7626_barnowl-plain-english_2026-10-29_83af.md`

Memory fixed this session (outside git):

- `~/.grok/memory-v2/workspaces/djbclark-be0ac6f0/topics/barnowl-release-v1.md` — rewritten: 1.0.1 only on history-loader
- `~/.grok/memory-v2/workspaces/djbclark-be0ac6f0/topics/forgejo-barnowl-repo.md` — no version; not a client fork
- `~/.grok/memory-v2/workspaces/djbclark-be0ac6f0/observations/_inbox/2026-10-29-barnowl-version-correction.md` — supersedes wrong turn-14 inbox notes (inbox is append-only)

Start map:

| Input | Result |
|---|---|
| `bo` | not on PATH; does not start BarnOwl |
| full path `…/scripts/bo` with no args | usage only; needs tmux session `barnowl` |
| `barnowl` on a tty | live client; `bo`/`g` will not find it |
| `tmux new-session -A -s barnowl barnowl` | session `bo`/`g` expect |
| `g list my subs` | Grok → `bo` → that tmux session |

Long-run tickets (operator-run; agents do not `kinit`):

```bash
kinit -r 7d -l 10h
aklog   # if AFS matters
# after: sudo apt install kstart
tmux new-session -A -s barnowl -- krenew -t -K 60 -- barnowl
```

Without `krenew`, renew by hand inside the renew window, or `kinit` again after expiry.

Tests this segment: none run (Q&A and memory edits only). Forgejo tags rechecked via API.

Unpushed on ade before this commit: `b68befa`. This handoff adds another local docs commit.

## Operator Feedback

- Fix C1 (version placement in durable notes) before answering herdr vs tmux.
- Wanted a clear start path: whether bare `bo` is enough, and how renewing tickets fits.

## Where We're Going

1. Next action: wait unless the operator asks to bring the live client back. Then they run `kinit` (current tickets die at 23:09 with no renew headroom); after that, `tmux new-session -A -s barnowl barnowl` (plain, or inside a herdr pane). Do not send keys to a non-tmux BarnOwl. Do not write `/tmp/s-s.txt`.
2. Optional: install Debian `kstart` and use the `krenew -t` launch line above for multi-hour sessions. Needs sudo and operator OK.
3. Optional: push the local ade commits (`b68befa` and this handoff). No memory-is-data push exception; leave until asked.
4. Still carried from parent: sudo-secretspec Debian installer is for the other coding agent; prompt text is in `HANDOFF_…_83af.md` Evidence. Do not implement it here. Do not put a version back on `djbclark/barnowl`.

## Detached jobs

none

## Quick Start

```bash
git -C ~/src/djbclark-ade status -sb
git -C ~/src/djbclark-ade log -2 --oneline
tmux list-sessions
klist
```

Read parent then this file:

- `docs/handoffs/HANDOFF_standalone-7626_barnowl-plain-english_2026-10-29_83af.md`
- `docs/handoffs/HANDOFF_standalone-7626_barnowl-tmux-start_2026-10-29_7be7.md`

Tier 1: `~/.local/state/handoffs/kool-ade/main/SESSION_LOG.md` → `chains/standalone-7626/SESSION_LOG.md`.
