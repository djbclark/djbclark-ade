# barnowl skill: how the sandboxed reads were designed and reviewed (2026-10-31)

The record behind [#197](https://github.com/djbclark/djbclark-ade/pull/197) (and the open
finding on #193 that asked for it). The raw reports are in
`~/.local/state/bigteam/bo-log-sandbox/` on the Mac (`<model>-<round>-report.md`); this file keeps
what a later reader needs: what was asked, what each round found, what changed, what is left.

## The problem

`skills/barnowl` lets yolo agents (full shell) drive the live BarnOwl on pastebin. Zephyr text
(bodies, instances, zsigs, hosts, the screen) is written by other people, so reading it is a
prompt-injection channel into an agent that can send zephyrs, run BarnOwl commands and evaluate
Perl as the operator. A SKILL.md prose rule is advice, not a boundary (Codex security review of #193).

## Who reviewed what

| Round | codex `gpt-6-astra` | Claude (claude TUI, monthly subscription) |
|---|---|---|
| Design | read-only advisor: threat model, verdict on four designs | Fable 5.1, same brief |
| Review 1 | BLOCK, 5 findings | Fable: BLOCK, 2 P1 |
| Review 2 | cancelled at 67 s under load (two gaps noted) | Fable's safeguards declined; the harness retried on Opus 4.8: APPROVE |
| Review 3 | BLOCK: resize race, session-name targeting, perl wrapper wording | not run |
| Review 4 | not run | Fable declined again; Opus 4.8 retry: APPROVE (pane pinning delta) |
| PR review | Codex (GitHub): zlocate/zctl status, 8 MiB window, quadratic header regex, "confirm every Perl" | |

Both design reports converged: sanitizing and framing (A) is necessary but not a boundary; a quarantined
model (B) was deferred; a human confirmation (C) is a boundary only if the agent cannot type into the
client itself, which needs a restricted ssh key with a forced command.

## Findings that changed the code

1. **Confirmation showed only part of the command** (truncated to 160 characters, punctuation turned into
   `?`). Now the whole command is shown or the command is refused: it must fit one line at the pane
   width minus 25, be printable ASCII, and contain no `{`, `}` or `\`.
2. **Measured on BarnOwl 1.10** (real client, 80 columns): a `start_question` prompt longer than the pane
   wraps and, with a one-line type window, only its last line is visible (100 characters showed
   `...ENDMARK? [y/N]:`, 86 showed `[y/N]:`; 79 showed whole, 80 did not). This is where the width rule comes from.
3. **Taint with a timer, then taint at all, was the wrong control.** A TTL let a long-lived agent regain
   ungated Perl; "ask only after a Zephyr read" ignores injection from web pages, PRs and repo files.
   `bo perl` and every non-read-only `bo run` are now always confirmed.
4. **Pane targeting by session name** can resolve to the operator's shell window. The pane is pinned by id
   (`%N`), must run `barnowl`, must be the active window of an attached client, and width, visibility and
   command are re-checked when the answer arrives.
5. **Read cursor** moved by claimed timestamps (a forged future header suppressed later messages) and
   dropped unread messages beyond `--last`. Now a byte offset plus a file signature, paging forward.
6. **Regex `--grep` and regex header parsing** could run quadratically on attacker text. Now a literal
   substring and plain string splits.
7. Framed argparse errors (no echo of arguments), private scratch files in a 0700 state dir (no
   rm-then-recreate in `/tmp`), exit statuses of `zctl`/`zlocate` kept, `history_cut` when a log exceeds
   the 8 MiB read window, a `bo asks:` question left on screen blocks the next caller.

## What is not solved (accepted)

- Plain English in a body can still mislead a summary; the sanitizer removes hidden channels, not meaning.
- The confirmation is a boundary only for an agent that holds the restricted `pastebin-bo` key and not the
  operator's main pastebin key. The main key (`id_ed25519_mit`) is still a plain file key readable by
  agents, and the operator chose on 2026-10-31 to leave it (afs-mount and other jobs use it unattended).
- Confirmation fatigue: a human who answers `y` reflexively.
- The Goose module (`djbclark/barnowl`) was a parallel injectable executor; fixed separately in
  `6c4049d` there (BarnOwl decides confirmation, sanitized context, linear parsing).

## Tests

`tests/test_barnowl_skill.py` (29, fake tmux and fake `zctl`/`zlocate`) passes on macOS and Debian; the
confirmation flow was also run end to end against a real BarnOwl 1.10 in tmux and on the live client.
