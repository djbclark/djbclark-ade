# Queue — accepted, not started

Work the operator has explicitly queued. Newest first. Items leave this file
when they ship (into the relevant doc) or when they're dropped (say why).

## `paseo-bypass-watch` test gaps from adversary round 4 (PR 121 merged 2026-10-29 as 306039a; djbclark deferred them 2026-10-29 via `/steps`: "track everything like it and resurface at the appropriate time")

Both are coverage gaps only; the code is exact and the adversary APPROVED 78f3a5c. Full report: `~/.local/state/bigteam/adhoc-2026-10-29/watch-adv4-report.md` (B1, B3). Not started by design.

1. **B1, low.** Two mutants pass all 58 tests, a case-folded and a prefix mode comparison. Add `"Auto"`, `"DEFAULT"` and `"autoSomething"` to the parametrize list of `test_only_default_and_auto_modes_are_acted_on` in `tests/test_paseo_bypass_watch.py`, expecting no flip.
2. **B3, very low.** Mutant `o_verify_accepts_auto` (`if after not in (TARGET_MODE, "auto")`, line 283 of `bin/paseo-bypass-watch`) survives. Add a test where the set "succeeds" but the seat still reads `auto`, and assert the post-set verify rejects it.

**Resurface when** (any one): someone edits `bin/paseo-bypass-watch` or `tests/test_paseo_bypass_watch.py`, so fold these into that PR; djbclark decides to install the watcher's launchd job (do these first, since an installed watcher runs unattended); a new adversary round touches the watcher; or `/baton` on the chain `secrets-collect-yes-bypass-watch-2026-10-29` reads this file (reader protocol step 4). Also listed under Next steps of that chain's `SESSION_LOG.md`. Remove this entry when both ship.

**Related decision, also deferred 2026-10-29 (djbclark, `/steps`: "Not now, track it"):** installing a launchd job for `bin/paseo-bypass-watch` (`--loop 10` or longer). Not installed; the watcher is a hand-run tool until then. Ask djbclark again when the two tests above have shipped, or when a UI-opened claude seat is seen sitting in `default`/`auto` unflipped. Install by site-djbclark's Ansible role or the ade install path, never a hand-written plist (home item 18), in a claimed workspace.

## Context visibility in Paseo and compact/handoff discipline: examine, search, discuss, fix (djbclark via session ab4e97be, 2026-10-27)

djbclark: "all of this needs to be examined, searched about, talked about, and fixed." Only measured so far, nothing fixed. The brief with the
scripts is `~/.local/state/ade-briefs/context-visibility-and-handoff-audit-2026-10-27.md` (relay id 37f55ad9). Related: `docs/context-hygiene.md`,
memory `reference_paseo_claude_context_window_controls.md`, `feedback_self_compact.md`.

1. **Measured 2026-10-27 (transcripts Oct 23-27, `~/.local/state/self-slash.log`).** Paseo Desktop's context meter divides by the manifest's 1M window and
   ignores `autoCompactWindow` (300000, ruled 2026-10-24, unchanged), so a session at its real wall reads about 27% (upstream getpaseo/paseo#4949, open).
   `paseo inspect --json` `LastUsage` read all zeros on a running Claude agent; `bin/context-budget-check` measures only the fresh-session baseline.
   48 native compactions on Oct 23-27, all `trigger=auto`, `preTokens` median about 267k; self-slash `/compact` used once (Oct 25); 27 handoff cycles
   (tapering: 4, 9, 10, 3, 1 per day); 4 "gave up, no empty input prompt seen" (nothing sent) and 2 failed successor launches on Oct 23-24.
   Not checked: whether `context_size_nudge.py` warnings were seen and acted on (`~/.claude/state/context-nudges.json`, 484 sessions, levels up to 19),
   why handoffs did not fire before the wall, non-Claude agents.
2. **Order of work.** (a) Examine the nudge state against the 35 sessions that peaked at 200-270k and the two failure classes (root-cause fix in this repo,
   code not only docs, `~/CLAUDE.md` item 11). (b) Web search first (item 14): how others surface live per-agent context, Paseo's plans for #4949 and any
   context API. (c) Talk to djbclark with numbered options before building: a live per-agent readout (tokens vs 300k, perhaps through fleet-watch), tighter
   nudge tiers or an automatic task-boundary handoff, and a comment on #4949 (item 38: dupe-search first). (d) Build what he picks, in a claimed workspace,
   with tests, a CHANGELOG line and an adversary verdict. Ask before touching `~/.claude/settings.json`.

## Port the Linux suite and the g-tool symlinks to uutils (found 2026-10-28; PR 102 pinned CI to `ubuntu-24.04` as the stopgap)

`ubuntu-latest` moved to `ubuntu-26.04` on 2026-10-28, whose coreutils are Rust uutils multicall binaries. The `pytest-linux` step that symlinks `~/.local/bin/g<tool>`
to `command -v <tool>` then fails ("Requested utility `gtr` does not match executable name"), 90 tests failed (`test_ade_git_hooks`, `test_self_slash*`,
`test_wait_file`, `test_acp_dispatch*`, others) and the job hit its 30 minute cap (run 40723793153; last green run 40669526660 on 24.04). Wanted: a wrapper script per
tool (`exec tr "$@"` style, or GNU coreutils from the `gnu-coreutils` package if the image has it) instead of a symlink, the suite green on 26.04, then unpin. The
pin comment in `.github/workflows/test.yml` says the same. GitHub retires an old image on its own schedule, so this is not optional forever.

## Sibling `RecursionError` readers: governor and quota-guard (adversary r1 on PR 97, PR 98 merged 2026-10-28 as 1f56db3; djbclark ruled last in the queue)

PR 98 made `ade_gates.read_guard_state` read a `RecursionError` from `json` as unreadable. Two readers of the same guard state files keep the exposure
(Python 3.13 and older raise `RecursionError` on deeply nested JSON under the 64 KiB cap): `guard_level` in `bin/claude-fleet-governor` and `load_state` in
`bin/claude-quota-guard`. Optionally make the hook call `g.read_guard_state()` instead of its own copy (r1 finding 2). Failing tests first, forcing
`RecursionError` the way PR 98's test does (a real nest does not trip on Python 3.14); one adversary round; CHANGELOG `Fixed` line.

## Verified peer messaging, round 2: "always acknowledged", and the gaps found (djbclark, direct, 2026-10-25)

djbclark, 2026-10-25, after seeing this relayed text from djbclark-ade-8d: "ack from djbclark-ade-8d (430f45ba), no reply needed beyond this": he wanted it so that **things always need an acknowledgement, and when none arrives the requesting agent has to handle that**; is the missing part just later in the implementation, or a flaw in what already landed? Answer (2026-10-25): mostly rollout and wiring, plus one design scoping that needs his ruling. Builds on "Verified peer messaging" (PR 74, merged 6f54e89; AGENTS.md standing order 10). Nothing below is started.

1. **Ruling needed (the only design question).** The landed design is "proof, not conversation" (scoping by Dann 5 after djbclark asked whether relay should ALWAYS require a reply; rules A-E in the section above): delivery proof is mechanical and needs no reply; an agent-level reply is required only for a question or a request for action (`--expect-ack`, tracked, escalated); an FYI that provably landed needs none. djbclark's wording is stronger ("always"). Two layers reconcile them without an infinite regress: **L1 transport proof for every message, default-on, no reply, applies to acks too**; **L2 agent-level ack for every non-ack message**, tracked as an expectation, overdue goes to the requester and then the operator. Acks, "no reply needed" texts and acks of acks are exempt from L2 (otherwise two agents ack each other forever); they still get L1. Recommended: L1 always plus L2 as landed (question or action), widened to handoffs, decisions and "PR N merged" only on his yes. Decide: keep E, or widen L2.
   **RULED 2026-10-25 (djbclark, `/steps` option 1): keep the landed rule (L2 only for a question or a request for action) and make L1 delivery proof always-on and default; the widened and the literal-always forms were declined.** Build target for items 3-7 below.
2. **Not live (rollout, not design).** On 2026-10-25 `~/src/djbclark-ade` sat 6 commits behind master, so the relay in use had none of PR 74: `relay.py ... --expect-ack` failed with "unrecognized arguments" in this session, and a peer's relayed text arrived as `[relay from unknown]` (no sender header). Fix: a designated promoter fast-forwards the shared checkout (AGENTS.md order 9, exception b), and `ade-update` keeps every installed copy current; verify with `relay.py --help | rg expect-ack` after.
   **Done 2026-10-25 (djbclark approved in `/steps`): `~/src/djbclark-ade` fast-forwarded to 22fbc63 (clean tree, `--ff-only`, no commit); `relay.py --help` lists `--expect-ack`. Still open: `ade-update` for the other installed copies.**
   **Done 2026-10-28 for this Mac:** every installed `session-finder` (`~/.claude`, `~/.agents`, `~/.config/opencode`, `~/.omp/agent`, `~/.copilot`, `~/.cline`, `~/.grok` `skills/session-finder`) is a symlink to `~/src/djbclark-ade/skills/session-finder`, at c6668ff = `origin/master`; each `relay.py --help` lists `--expect-ack`; `bin/ade-update --check` exit 0 ("result: current"). Other machines were not checked.
3. **`--ack` is opt-in.** Without it `queued` and `accepted` still exit 0, because fleet-watch, load-watch, session-load-watch and rumination-watch read 0 as "taken or queued". So a plain send is not verified unless the caller asks. Fix: make those four pass `--no-ack` (or accept exit 3), then flip the default to verify; test that each watcher still behaves.
   **Done 2026-10-25 (branch `feat/relay-ack-default`, PR #NN) for relay.py and the three in-repo watchers: the delivery watch is the default for an agent session (10 s beyond `--wait`), `--no-ack`/`RELAY_NO_ACK=1` turn it off, a launchd-run declared job keeps the legacy exits, `bin/load-watch` (both relay calls), `bin/session-load-watch` and `bin/rumination-watch` pass `--no-ack` with a test each. Still open, DECIDED 2026-10-25 (adversary A r1, A3): `fleet-watch` (site-djbclark repo, a separate repo, not edited by this PR) must pass `--no-ack` on its two relay calls, `upr_send_line` (~line 908, `runb 60 "$UPSTREAM_RELAY" "$target" "$text"`) and `upr_relay` (~line 955, `runb 180 ...`), because an agent that runs `fleet-watch --relay-test` or `--relay-to` from its session is an identified sender and would otherwise get exit 3 for a queued line (and `upr_relay` would fall back to `upr_dispatch`). That follow-up must land AFTER this PR merges and the shared checkout is fast-forwarded: until then relay rejects the unknown `--no-ack` flag (exit 2), so an earlier change would break fleet-watch's relays.**
   **fleet-watch done 2026-10-28 (PR #NN above is PR 81, merged 2026-10-26; site-djbclark 8ff9803, pushed to master and `~/ops/site-djbclark` fast-forwarded):** both relay calls pass `--no-ack` (`bin/fleet-watch` `upr_send_line` and `upr_relay`), with `tests/test_fleet_watch_upstream.py` `test_every_relay_turns_the_delivery_watch_off` (fails with either flag removed).
4. **Escalation is print-only (rule D).** `relay.py --sweep` prints `OVERDUE ack ID ...` lines, but nothing runs it on a schedule or pings the operator: "the lead wires `hermes-ping`" was left undone. Fix: run `--sweep` from `bin/fleet-watch` (a script, not a recurring model prompt, `~/CLAUDE.md` item 13) and send one `hermes-ping` per overdue expectation, once.
   **Done 2026-10-26 (site-djbclark PR 236, https://github.com/djbclark/site-djbclark/pull/236):** `ack_watch` in `bin/fleet-watch`, called from `check`, runs `relay.py --sweep` on fleet-watch's launchd schedule and sends one `hermes-ping` per `OVERDUE ack ID` line, once (state `~/.local/state/fleet-watch/ack-overdue.json`, live: written 2026-10-28 05:55).
5. **Requester-handles-it is only half there.** A deferred record that fails or expires sends the sender one notice (relay.py, 2026-10-25), and an expectation records the owner, but no rule yet tells the requesting agent what to do on `OVERDUE` or exit 3 (re-send by another route with `--via`, ask for a named ack, else report to the operator, never assume read). Put those steps in the `session-finder` SKILL.md "Verified peer messaging" section and in the home file pointer (Opus only).
   **Done 2026-10-25 (same PR) in SKILL.md "Verified peer messaging" item 1, steps a-d. Still open: the home file pointer (Opus only).**
6. **Receiver half not built.** A turn that began with `[relay from ...]` and ended without a `relay.py` call (answered in prose only) is flagged by the skill text but has no Stop-hook nudge (left to the lead by design). Build it; it is the case that started standing order 10.
   **Built 2026-10-26 (PR 75, `claude/hooks/relay_prose_nudge.py`, registered in `agents/claude/settings.json.tmpl` under `Stop`). Still open: the live `~/.claude/settings.json` has no entry (checked 2026-10-28); installing it is djbclark's step by design (PR 75 body, "Install"): the idempotent snippet in `~/.local/state/bigteam/adhoc-2026-10-25/ack-build-C-report.md` ("Install command for djbclark").**
7. **Test the terminator.** Add a test that an `ack <id>` reply, a "no reply needed" text and an ack of an ack never create an expectation and never loop, while each still gets L1 proof.
   **Done 2026-10-25 (same PR): `tests/test_relay_verified.py` `TestTerminators`. The terminator had one hole, fixed in relay.py: an `ack ID` reply or a "no reply needed" text got the first-contact footer asking for a reply, and opened a link that showed `ONE-WAY` for ever; it now carries no footer, opens no link and takes no `--expect-ack`/`--needs-reply`. Repair after adversary A r1 (BLOCK at e79d640, A1), DECIDED 2026-10-25: (a) an explicit `--expect-ack` or `--needs-reply` wins over the surface text, so only the bare loop shape (`ack ID` alone, or a no-reply phrase alone) is refused (exit 2); (b) a no-reply phrase counts only at the END of the text, so a quoted or negated mention is no terminator; (c) the `ack ID` terminator is `ack ID` alone or with a remark of at most 40 characters in parentheses or after a colon, no `?`, no request word (please, pls, could, would, can you, need, must, then, now, tell me, let me know); `ack the PR and merge it` or `ack q1: merged; now please rebase PR 14 onto master` is an ordinary text (first-contact footer, the peer answers `ack ID`: one bounded extra message, the noise cost accepted against a missed message), and `ack X thanks` with an unbracketed remark is likewise ordinary.**
   **Repair round 2 (adversary A r2, BLOCK at 4b5d7f7, 2026-10-26):** (R1) a no-reply phrase is a terminator only as the LAST CLAUSE (`NO_REPLY_RE` anchored to the text start or one of `.!?;,([` or a dash, so `Can you review PR 12? The bot said no reply needed` is no terminator and exits 2 asking for `--expect-ack`; `FYI merged no reply needed` with no separator is an ordinary text, one extra `ack ID`); (R2) docs: never put `--expect-ack`/`--needs-reply` on an ack whose remark asks nothing new, or two agents chain acks for ever; (R3) `is_terminator` searches the stripped text, so a quoted bare phrase agrees with `is_bare_terminator`; (R4) accepted, the `REQUEST_WORD` list stays advisory.
8. **Prose-nudge hook and relay disagree on what an ack is (known limit, 2026-10-26; PR 75 adversary rounds 3 and 4, R4b, R4c and F6).** `claude/hooks/relay_prose_nudge.py` exempts an `ack <ID> ...` text, a text starting `no reply needed` and one starting `FYI` with a first-contact footer, so an action request that merely starts that way (`ack the status please`, `ack q1 - please rebase PR 14 onto master`, `No reply needed on the log, but please merge PR 14 now.`, `FYI please pause your build`) is not nudged; an `FYI` text is silent even WITH a `?` (`FYI: load is 11, can you pause your build?`, from every sender, footer or none, because the FYI test runs before the `?` rule; only relay's reply footer overrides it). Slice A (`feat/relay-ack-default`) merged in #81, so relay's `is_terminator` classifies those as non-terminators that DO get the footer, so the two definitions differ. The gap only under-nudges, so it cannot loop. **Follow-up after PR 75 (slice A merged in #81; not done in PR 75):** the hook shares relay's `is_terminator` as its single ack/no-reply predicate (and drops `ACK`, `ACK_BARE`, `NO_REPLY`), with a test that both agree on one corpus. **Acceptance corpus:** the `R`-owed rows under `DISAGREEMENTS with slice A` in `~/.local/state/bigteam/adhoc-2026-10-25/adv75r3/corpus.out` (texts in `corpus.py`; **18 request texts** in all, counted by adversary round 4 in `adv75r4/corpus.out`: 17 still silent under a first-contact footer, plus `ack q1: is that the SHA you meant?`, fixed 2026-10-26): `ack the status please`, `ack the PR and merge it`, `ack q1: now please rebase PR 14 onto master`, `ack q1 - please rebase PR 14 onto master`, `ack q1 please rebase PR 14 onto master`, `ack q1, then run the tests and report back`, `ack q1! next: send me the log`, `ack q1: is that the SHA you meant?` (fixed 2026-10-26: a `?` is never an ack), `ack q1` + newline + `please restart the service`, the same with a tab and with an NBSP, `ack q1 see https://x.test/a?b=1 and restart it`, `ack q1 bitte den Dienst neu starten`, `ack q1 サービスを再起動してください`, `ack q1: ` + 3400 x `ok ` + ` now please restart the service`, `No reply needed on the log, but please merge PR 14 now.`, `FYI: load is 11, can you pause your build?`, `FYI please pause your build`; each must nudge (or be refused by relay) under a first-contact footer. Also pass: `Shall I merge PR 14 tomorrow? No need to reply.` (fixed 2026-10-26 in the hook: `no need to reply` / `no response needed` at the end are no-reply texts). **Accepted, documented in the hook docstring (round 4):** F4, two envelopes in one prompt (no harness writes it): only the first is read, so the route of one is never mixed with the token of the other; F7, a herdr pane id with no `(DIR)` (the sender's cwd is gone) counts `?`, so its `--fyi` question is nudged once, while only a raw socket client can spell a pane id with a `(DIR)` from a non-herdr sender (relay's `clean()` and `safe_label` strip `:` and `()`), which silences only its own question. relay.py `URL_RE` has the same quadratic scheme class as the hook's pre-fix one (`[a-z0-9+.-]*`; bound it to `{0,31}`), and `route_socket` could send `forced_tag` like the pane route for symmetry; both are follow-ups.
9. **A sender with a fleet row but no readable transcript could not use `--expect-ack`** (Codex review of PR 81, `relay-transcript-gap-followup.md`, 2026-10-25; djbclark ruled 2026-10-26 "the lead builds this after PR 81 merges"): a `?` text was told to use `--expect-ack`, which was then refused ("needs this session's own transcript"), so a native Hermes or OMP caller could not ask a real question through relay at all. ~~Dead end.~~ **Done 2026-10-26 (branch `feat/expect-ack-no-transcript`, PR #87):** relay-side resolution. When the TARGET answers through relay.py with a text that begins `ack ID` to the session that opened the expectation, relay closes the record itself (`acked_via: "relay"`), the identity being the fleet's `self` row, never the text; it applies ONLY to a record with no transcript (`tx` null: a transcript-backed record, e.g. a Claude sender, is closed by its transcript alone, as before) and counts only for an answer whose delivery watch ran and whose route to the asker proved delivered, or handed, with no proof to take, to something that keeps the text (`KEEPING_ROUTES`: a Paseo agent the daemon accepted it for, an ACP launch or dispatch inbox; named from the route result, never from a screen match). Never failed, refused, pulled back, `--no-ack` (no watch ran), a pane's proofless "queued" (a screen heuristic over a header identical for every message of one peer: adversary r2 A1 on 5eb19af), run by a deliverer, or watched by a delivery proof that ran out: a false ack is worse than a missing one (adversary r1 A1/A2 on 426cf09). The record stores `tx: null` and `--sweep` reads no transcript for it; the transcript path still closes the replies that do not come through relay. A caller with NO session (a launchd job, `RELAY_SENDER_NAME`) is still refused `--expect-ack` (nothing could answer it). Tests: `tests/test_relay_verified.py` `TestExpectWithoutTranscript`, `TestExpectNoTranscriptPaneQueued`. Left alone, DECIDED: first-contact link acks (`ack <sender id>`) still resolve only from the sender's transcript, so a transcript-less sender's links show `ONE-WAY`; an ack the target had to queue for a busy peer resolves nothing (its deliverer runs as no session), so the target resends it once the peer is idle; likewise an ack deferred to a BUSY no-transcript Paseo recipient never closes (`defer_send` counts only a deliverer outcome line whose result word, read from the right (`outcome_result`), is `delivered`; a recipient NAME holding `: delivered;` fools nothing, adversary r3 A2), so that sender may go OVERDUE although it was delivered: the safe direction, do not loosen the gate (adversary r2 A5). **A native pane sender with no transcript (OMP, Hermes TUI, opencode, gemini, pi in a herdr or tmux pane) can NEVER close an expectation by relay (adversary r3 A1): its only return route is the pane, whose only evidence is a screen match, so every `--expect-ack` it opens goes OVERDUE even when the target answered at once. That is the safe direction (a missing ack, never a false one), and the operator closes it by hand.** The relay-side close works for a sender reached by a route that proves delivery or keeps the text (a non-Claude Paseo agent, an ACP launch or an acp-dispatch slice); a sender with a readable transcript closes by that transcript, as before. **Sender identity widened 2026-10-30:** fleet lists a `pid*` process-scan row (`self = pid in ancestors`, no transcript, no Paseo id) BEFORE the Paseo row of the same agent, so relay's old "first `self` row" took the pid: `sender: pid19798`, `sender_paseo: ""`, `tl_base: null`, an expectation that could never close and a footer naming a pid (live 2026-10-29, a Paseo Antigravity agent). `fleet.sender_row` now takes the row that can prove an ack: AMONG SEVERAL `self` ROWS, one with a transcript, else one with a Paseo id that PROVES it hosts this process (ties keep fleet's order; a transcript row gets no second vote for also carrying a Paseo id, because a transcript already proves the ack and neither `ack_proof_note` nor `timeline_base` reads a transcript row's Paseo id -- local-review of 2026-10-30), so a row an inherited `PASEO_AGENT_ID` merely marks `self` cannot win; relay and the `fleet list` link annotation both use that row. A sender left with no watcher is told at the send what is true for its case, and only when a footer asked for the ack: an `--expect-ack` from a row with no transcript and no keeping route (a `pid*` row, a native pane TUI) is told the expectation MAY not close on its own, because a Codex target's `route_pane` can resolve a transcript and report `delivered` (adversary r3 D2), and is given `--retire` -- unless its answer can arrive over a route that KEEPS the text (a Paseo agent, an ACP launch, a dispatch inbox), which `expect_resolve_by_relay` closes, and then it is not warned at all; a Paseo row whose timeline could not be read is told the record closes only when the target sends `ack ID` through relay.py; and a FIRST-CONTACT link, which opens no record, is told the peer's `ack` to that first contact cannot mark it acked rather than promised an `ack` that `ack_sweep` has no transcript and no baseline to read (a later answered `--expect-ack` to the same peer still marks it, adversary r3 D3). The footer names the id relay wrote under, and for a `pid*` sender that id is the pid: it is the only name that sender has, not a better one. As above, no ack reopens that door. The `SENDER_OVERRIDE` gate is unchanged.
   **Known gap (adversary r3 A4, not fixed, separate change):** an interactive ACP launch whose acp-run was killed with no result still lists as alive and its inbox is still written (`route_launch` checks no pid; `fleet._pid_alive` exists), so an ack to it closes `acked_via: relay` for a dead return path; the same for an acp-dispatch slice killed before its `.done`.
   **Early answer (Codex P2 on PR 87, fixed 2026-10-26):** the ID is reserved before the send and the `open` record was written only after it returned, so an `ack ID` that a Hermes target sent during its blocking turn found a `reserved` record, was ignored, and the open record then went OVERDUE for an answered question. Now the reservation carries both ends (`expect_stamp`, after the target resolves), `expect_resolve_by_relay` closes a fresh `reserved` record under the same gate as an `open` one (`acked`, `early: true`), `note_links_and_expect` never reopens an early-acked record (and marks the new link acked), and `expect_release` drops a reservation or an early ack when nothing was sent. An early-acked ID is held until its send returns (`sent: true`, adversary r5 F1), at most `EXPECT_RESERVE_TTL` (600 s) after the reservation. The 600 s `EXPECT_RESERVE_TTL` bites only a send that blocks 600 s or more after the reservation (Hermes with `--wait` about 600 or more): its late ack is lost and the question goes OVERDUE, and a send that blocks longer can lose even an early answer and the ID to another relay; at the default `--wait 20` a Hermes turn returns `unverified` after `max(100, --wait)` s and the open record is written normally. A busy non-Claude pane sender or a non-steerable Paseo sender gets the ack deferred, so such a question can still go OVERDUE (same as the open path).
   **Codex P2 #2 on PR 87, fixed 2026-10-27 (the Hermes caller's identity):** the early-answer and the later relay-side close ran only for a caller with a fleet `self` row, which a Hermes gateway conversation never has (`fleet._hermes_gateway` builds its row with `self: False`), so the Hermes answer could not close the record on the real identity path; five tests passed only through a fabricated `self`. Now `hermes_caller` (relay.py) reads the caller: the full `HERMES_SESSION_ID` equals one live `hermes-gw` row's session id AND the process descends from the pid written in that conversation's lock file (`hermes_lock_path(sid)`) or in `~/.hermes/gateway.pid`, with no `fleet.PROC_AGENTS` agent other than Hermes between (`descends_from`: the anchor pid itself passes, a pid-1 anchor too; the lock file is read as digits and `gateway.pid` as JSON, its `pid` value through `int()`, see A4a); `expect_resolve_by_relay` reads it as `CTX["caller"]` and compares the target's FULL session id. A recognised Hermes caller drops the `self` mark a relayed turn inherits from its asker's herdr pane (so the answer to a herdr asker is no longer refused as "that is this session" and no record or footer names the asker), and it may CLOSE but never OPEN (`--expect-ack` from it exits 2, message amended). Tests no longer fabricate `self` (`answer_as_hermes`). **Known bounds, documented not fixed:** A4a (wide form, adversary round 10 F1, 2026-10-27) every identity here is environment, two files and the process tree of one Unix user, and nothing is verified beyond that: `hermes_turn_pid` and `hermes_gateway_pid` read the lock file's digits or `gateway.pid`'s JSON `pid` with no liveness, command, flock or `start_time` check, so ANY deliberate same-user process (not only one inside the Hermes gateway) can pass as Hermes conversation X by setting `HERMES_SESSION_ID` to a live gateway row's full session id and writing the pid of one of its own ancestors (or `1`, which `descends_from` accepts as the anchor itself) into `hermes_lock_path(sid)` or `~/.hermes/gateway.pid`; a process inside the gateway (a delegated subagent included) needs no file write to answer for another conversation of that gateway. It is the same class as `HERDR_PANE_ID=… relay.py` already impersonating a pane; an outside shell that only sets variables is still refused, unless a pid left in that conversation's lock file (kept at least 7 days after its last relayed turn, until a later relay into Hermes prunes it) or in `gateway.pid` now belongs to the shell or one of its ancestors (pid reuse; relay checks no liveness). A4b the walk's foreign-agent stop knows only `fleet.PROC_AGENTS` (omp, pi, gemini and any agent not in `fleet.PROC_AGENTS` started inside a turn passes; a Paseo-hosted agent is not a descendant of a turn, so it is a false negative and does not pass); A4c Hermes may rotate a conversation's session id (compression), and an answer from the new id leaves the record open and OVERDUE (conservative).
   **PR 87 round 10, behaviour change and further known bounds (2026-10-27, docs only, no code change):** F4 a recognised Hermes caller can no longer defer a send to a busy target: `defer_send` takes its ident from the dropped `self` row, so the relay exits 1 "deferring needs an identifiable sender"; before this change a relayed turn from a herdr asker deferred under the ASKER's id, so the failure notices went to the asker (misattribution); the new refusal is the safe direction. F3 `--plan` skips the Hermes identity, so in a relayed herdr-asker turn it still prints "that is this session" while the real send goes through. F2 a lock file holding a Unicode digit (`²`) raises ValueError in `hermes_turn_pid` (`isdigit` is true, `int` fails) and blocks every send of that conversation until the file is fixed; reachable only by a same-user process writing the lock. F5 the mutants `len(rows) != 1` -> `not rows` and dropping `host == "hermes-gw"` from `hermes_caller`'s row filter survive and are unreachable in production (`sessions.id` is a primary key; a herdr row with the same sid gives two rows, which the one-row check refuses). **Known wording to fix when relay.py is next edited** (these still overstate; the code is as described above): relay.py:80-81 "relay proves it from the full HERMES_SESSION_ID and its process tree"; relay.py:206 "a Hermes gateway conversation is the target's end when relay PROVES it (`hermes_caller`: ... this process below that conversation's own turn process or the gateway process, no other agent between ...)"; relay.py:1188-1191 (`descends_from`) "Strict ... the top of the tree, a pid missing from TABLE or 40 steps without ANCHOR is False" (an anchor of 1, or the anchor pid itself, is True); relay.py:1205-1206 (`hermes_turn_pid`) "The pid `route_hermes` wrote into the lock file ... (the `hermes --resume SID -z` process, which holds the lock for the whole turn ...)" (it returns any digits in the file); relay.py:1215 (`hermes_gateway_pid`) "the process every native gateway conversation runs in" (any pid in the file); relay.py:1224-1228 (`hermes_caller`) "descends from that conversation's turn process (the pid in its lock file) or from the gateway process ... a variable any shell can set proves nothing alone ... Same-uid residuals (a deliberate forger inside the gateway process, an omp or Paseo-hosted agent inside a turn, ...)" (any same-user process that writes the file can forge; the agents missed are omp, pi, gemini and any agent not in `fleet.PROC_AGENTS`); relay.py:2911 (`expect_resolve_by_relay`) "the Hermes conversation `hermes_caller` proves"; also relay.py:1188 "with no agent other than Hermes on the way", 1190-1191 "a Claude, Codex or other agent session started inside a Hermes turn", 206 and 1225 "no other agent between" (the stop is `fleet.PROC_AGENTS` only, so omp, pi and gemini pass), relay.py:3121 (comment) "this process speaks for that Hermes conversation" (same overstatement as relay.py:80-81), and optionally relay.py:1781 (`hermes_holder`) "for the turn that holds the lock" (the file may name a dead or reused pid; display string only).

   **Left for a later PR (adversary r2, 2026-10-30; not regressions, not in PR 162):** (a) `fleet._proc_scan` does not attach the Paseo id it already holds for the process it scans, which is probably why a Paseo agent's own ancestor TUI also got a `pid*` row -- unconfirmed, the process was gone, and `sender_row` stays correct with or without the attach; (b) a process whose ONLY `self` row is an inherited `PASEO_AGENT_ID` is still named as that agent (one `self` row is returned unchecked, and `relay.sender_name`'s `own_paseo_id()` accepts the env id with no hosting check) -- unchanged by PR 162, and it needs the same hosting proof as `sender_row`. **(c) (adversary 4 F2, 2026-10-30, pre-existing):** two transcript `self` rows tie under the new rule and fall to fleet's order, which for Claude rows is the lexicographic pid order of `~/.claude/sessions/*.json` (`fleet.py:498`), not ancestry order -- so in a nested case (an inner Claude session under an outer one, both with transcripts) the sender may be named as the OUTER session. The rule before PR 162 was strictly worse here (always outer), so this is not a regression; the fix is to break transcript ties by ancestry depth, preferring the row whose `pid` sits nearest the front of `ancestors()`, with a test that orders `[outer, inner]` and `[inner, outer]`.
Next (2026-10-28): item 1 is RULED; items 2 (this Mac), 3, 4 and 7 are done; open: 5 (home file pointer, Opus only), 6 (djbclark installs the built hook into the live settings), 8 (the hook shares relay's `is_terminator`).

## Research: how to keep `relay.py` (and self-slash) from blocking on TUI picklists and similar modal states (djbclark, direct, 2026-10-28)

djbclark, 2026-10-28: "Do web searches and get advice of frontier agents and do any other work to determine the best way to avoid the issues with relay.py blocking on picklists and similar issues we have been seeing." He supplied a starting report from Gemini (agy), saved verbatim at `~/.local/state/ade-briefs/picklist-deadlock-gemini-report-2026-10-28.md`; **do not consult agy/Gemini as one of the agents** (we already have its answer). Scope: agent-to-agent delivery and `self-slash` input into a pane that is in a modal state (a picklist or question card, a permission prompt, a slash-command or `@` file-picker menu, a raw-mode dialog), and the human-facing side only where it feeds the deadlock. The human's own picklists stay: `/steps`, numbered question cards and `AskUserQuestion` are his chosen UX (`~/CLAUDE.md` item 8, `skills/steps`), so any "deny the tool" idea must be scoped to the agents it protects, not turned on everywhere.

1. **Collect the failures first (examine).** From `~/.local/state/self-slash.log` ("gave up, no empty input prompt seen" x4, PR 110 widens that read), `relay.py --pending` and its deferred-send records, relay `queued`/`unverified` outcomes that never became `delivered`, a steer that replaced a running Codex review turn, and session transcripts where a relayed text arrived while a card was open. One table: date, route (paseo / dispatch / launch / pane / socket), target TUI, what state the target was in, what the sender saw, how it ended. Check what the pane route does today when the target shows a picker: `prompt_line.py` classifies a draft versus an empty prompt; whether it recognises a picker, a permission prompt or a slash-menu is **unverified** and is the first thing to read. The Paseo route already refuses a target with a pending permission or question (`paseo agent inspect`), so measure how often the other routes lack the same check.
2. **Web search first (`~/CLAUDE.md` item 14; the `fallback-chains` ladder, shared `mcp__firecrawl__*` first).** How other multiplexers and orchestrators deliver messages to an agent that is mid-picklist: Claude Code hooks (`PreToolUse` on `AskUserQuestion`, `PermissionRequest`, `Notification`, `Stop`), headless and ACP elicitation / permission requests, out-of-band message buses (MCP mail, SQLite or HTTP inboxes), Paseo, herdr and tmux input semantics (`send-keys` versus bracketed paste versus a real prompt API). Dupe-search upstream issues for the same failure.
3. **Gemini's starting claims are leads, not facts; verify each before relying on it.** (a) `claude --disallowedTools "AskUserQuestion,EnterPlanMode,ExitPlanMode"` and `permissions.deny` entries remove the tool (check the live CLI and docs; also that denying it does not break `/steps`, `skills/steps` and every skill that asks a question); (b) "a wildcard `permissions.allow` makes `AskUserQuestion` return an empty string" (reproduce or drop); (c) a `PreToolUse` hook can intercept the question payload and answer without rendering the card (check the hook contract, exit codes and timeouts); (d) the four projects it names exist and do what it says: [ZiuChen/ask-user-questions](https://github.com/ZiuChen/ask-user-questions), [mcp_agent_mail](https://github.com/dicklesworthstone/mcp_agent_mail), [Roasbeef/substrate](https://github.com/Roasbeef/substrate), [humanlayer](https://github.com/humanlayer/humanlayer) (read the code and licence; none is adopted on the strength of a summary; `~/CLAUDE.md` item 5 asks djbclark before any new MCP server); (e) "stop using stdin / `tmux send-keys` as the inter-agent bus" against what `relay.py` already does (steer through Paseo, `acp-dispatch tell`, launch inboxes; the pane route is the last resort) and whether a mail-style inbox would replace the pane route or only add a fifth one; (f) "assume-and-log" for non-destructive questions against standing orders 4 and 6 and the batching rule in memory (`feedback_fix_gaps_without_asking.md`). Its drop-in skill and `settings.json` snippet are **not installed**; `~/.claude/settings.json` is touched only after asking djbclark.
4. **Consult frontier agents (the `frontier` skill; `route_agent.py plan` for the rest; quota-gated, so check `aiuse --available --json` first and use the omp credits or wait for a reset, never a fresh fan-out).** Give each the same brief: the incident table from item 1, the architecture (relay routes in `skills/session-finder/relay.py`, `bin/self-slash`, `prompt_line.py`, Paseo steer semantics), and Gemini's report as a document to critique. Ask for the best design, what to reject and why, and what could still deadlock. Candidates: Opus 5.5 high (judgment), codex and Fable high through `frontier`, Grok if it has quota. **Never agy/Gemini.** Record each answer with its model, date and a verbatim key quote; where they disagree, say so.
5. **Other work to do before choosing.** (a) A reproduction harness: a fake pane or a real throwaway herdr pane showing a picker, a permission prompt and a slash menu, and a test that each route either refuses with a clear status or reaches the agent without being swallowed. (b) Decide the state taxonomy the sender must read before any send (idle empty, draft, busy, picker, permission, slash-menu, unknown) and whether it comes from the screen, the transcript, the agent's own API or a hook-written state file. (c) Decide what a sender does when the target is in a modal state: wait, defer (the existing deferred send), route elsewhere, or report to the operator; and the timeout. (d) Decide whether agents that receive relays should lose `AskUserQuestion` (denied per agent profile) in favour of a queued question that relay, `/helm` or Hermes can answer. (e) Check the same class in `self-slash` (types `/new`, `/compact` into a pane), `launch.py`, `acp-run` interactive launches and `helm` auto-answering.
6. **Then talk to djbclark.** Numbered options with cost, risk and a recommendation; build only what he picks. Build in a claimed workspace with failing tests first, a CHANGELOG line and an adversary verdict marker; ask before touching `~/.claude/settings.json` or adding any MCP server.

Placement (2026-10-28): after the peer-messaging round 2 section because it is the same feature (delivery to a peer that cannot take input); it can run in parallel with the context-visibility audit entry at the top, but it shares `self-slash` with PR 110 (merge or rebase on it first) and `relay.py` with the open items above. Status 2026-10-28: nothing started; Gemini's report only.

## Research: web prior art before code spelunking, Python over bash, Kiro/LSP (djbclark, direct, 2026-10-25)

Three research questions, one frontier consult (Codex `gpt-6-astra`, advise only, 2026-10-25; it searches the web first and cites sources); a fourth, item 4, was added the same day and is not part of that consult. **Nothing here is built.** The consult returns recommendations; djbclark rules on them before any implementation slice. Existing rules this extends: `~/CLAUDE.md` items 14 and 7 (search first), `feedback_web_search_before_local_spelunking.md`, `feedback_prefer_python_over_shell.md`.

1. **Make every agent more likely to run a web prior-art search before spending tokens reading code.** The search tools cost no money (the shared self-hosted Firecrawl on SIPB Hyades, Exa, Jina, Parallel; djbclark believes SearXNG is also available, which the consult is asked to verify); the open question is the **token cost of processing results versus the tokens a search saves**, which nobody has measured. Deliver: a recommended mechanism (a hook nudge, a skill, a sub-agent that returns a digest, `read_url` with a `question`, cached research notes in Basic Memory), a budget (how many tokens a search may cost before it stops paying), when NOT to search, and how we would measure it.
2. **Move as much agent work as possible from bash to Python**, possibly with typing extensions or checkers that help AI (pyright/ty/basedpyright strict, `typing_extensions`, pydantic/msgspec, beartype, typed subprocess wrappers, PEP 723 `uv run --script`, a shared typed helper library for argv runs, SSH, atomic writes, JSON/TOML). Djbclark's expectation: this removes the frequent nested-quoting and heredoc failures (three cycles lost on 2026-10-25). Deliver: which tools, a Bash-tool hook that detects quoting-heavy commands and steers to Python (we already have PreToolUse guards for `| head &&` and bare `sed`), a helper-library sketch, and evidence from CodeAct-style "Python as the action space" work.
3. **Kiro CLI's LSP integration (language server protocol) for coding accuracy and speed.** Find out what `kiro-cli` (2.34.0 is installed at `~/.local/bin/kiro-cli`) actually does with LSP, whether other agents can reuse it, and which of our TUIs already have LSP (Claude Code has an `LSP` tool; check Codex, omp, OpenCode, Cline, Copilot). Deliver: measured or cited accuracy/speed gains, token cost of diagnostics, and a recommended integration seam (one shared LSP service versus per-agent), with the servers worth running here (pyright/ty, TypeScript, gopls, rust-analyzer, nixd, bash-language-server).
4. **Would Cerevisor ([cerevisor.com](https://cerevisor.com/); "Mac AI orchestration app", djbclark, direct, 2026-10-25) be useful to us anywhere?** First look from a web search (2026-10-25, unverified beyond the vendor's own pages): a desktop app for macOS and Windows that runs a team of agents, each on its own model (Claude Code, Codex, Cursor, Gemini, API models, local Ollama); you review the plan before a run; workflows are built visually on a canvas; data stays local; free to start; skills land in `~/.claude/skills/` and state in `~/.cerevisor/` (its uninstall page says so). Find out: what it really is (closed or open source, price, how it drives the CLIs: ACP, the Agent SDK or by spawning them), and whether any of it beats what we already run, namely the micro graph (Claude Code dynamic workflows), the macro graph (Orca task DAG), `acp-dispatch`, `bigteam`, `helm` and `route_agent.py`. Candidate uses to test or rule out: a visual plan-review canvas in front of `/bigteam`; a human-supervised front end for the coding factory (`docs/coding-factory.md`); a second reviewer or approval surface; any piece worth lifting as an idea (plan preview, per-agent model assignment, reusable workflow templates) rather than adopting. Check against our constraints before any trial: it writes to `~/.claude/skills/` (`docs/skills.md` says every agent reads this repo's skills through one symlink, and Paseo's skill sync once wrote through such symlinks and overwrote vendored skills, memory `project_paseo_skill_sync_writes_through_symlinks`), its data directory and credentials must go through `sudo-secretspec` and never a vendor store we cannot audit, it must run yolo-equivalent agents and honour our hooks, and it must not bypass `acp-dispatch` routing or the claim registry. Deliver: a verdict (adopt, trial in one worktree, borrow ideas only, or not useful), the evidence with sources quoted, and the smallest trial that would change the verdict. **Not started; read-only research only (Opus 5.5 high via omp, web research first, `--kind research`); routing needs djbclark's go, like items 1-3.** A new tool or plugin also needs the `apply-toolchain-prompt.md` question (`~/CLAUDE.md` item 5) before any install.

Status (2026-10-25): consult done (Codex `gpt-6-astra`, advise-only), report `~/.local/state/bigteam/adhoc-2026-10-25/research-web-python-lsp-report.md` (318 lines, sources quoted; sections B recommendations, C decisions, D slices D2-D9, E experiments). **RULED 2026-10-25 (djbclark, `/steps` option 2, "approve, but measure first"): the advisor's seven decisions are approved as recommended** (C1 bounded conditional web nudge in shadow then advisory, not unconditional web-first; C2 prior-art scout on demand only; C3 six-function stdlib typed helper, not shellous/Plumbum; C4 basedpyright strict for new helper/scripts only; C5 LSP via native clients with shared binaries and isolated per-worktree processes, no broker first; C6 extend the accepted Basic Memory recall/cache work; C7 defer new tool/MCP installs until a pilot shows a gap). **Kiro is out of scope (djbclark, 2026-10-25): he does not want to use kiro-cli; the question is whether LSP code understanding can serve Claude, Cline and OpenCode.** Kiro has no reusable LSP endpoint (it launches ordinary stdio servers per workspace); the LSP trial (report slice D7, reframed) is therefore the same language servers in the other TUIs: Claude's `local-lsp`/`clangd-lsp`/`rust-analyzer-lsp` plugins verified with a real query, OpenCode `lsp` enabled (off by default; no `lsp` key in `~/.config/opencode/opencode.json`), Cline CLI checked (an MCP bridge such as Serena only if it has no LSP), one Python and one TS workspace, output caps of about 1,000 tokens per query and ten new diagnostics per batch, compared with and without. **Queued now: only slice D2 (shadow telemetry: `claude/hooks/prior_art_nudge.py`, shadow only, no prompt changes) plus the read-only transcript analysis E1 (frequency of external-tree read runs, tokens returned, failed shell quoting, retries).** Held until those numbers exist: D3 retrieval contract and cache, D4 helper, D5 Bash-guard Python hints, D6 type-check feedback, the LSP trial, D9 eval harness. Not started; routing D2/E1 needs djbclark's go.

**D2 built, in shadow (2026-10-26, branch `feat/prior-art-shadow`, PR 85; adversary rounds 1 to 4 repaired 2026-10-26).** `claude/hooks/prior_art_nudge.py` (PostToolUse, PostToolUseFailure and UserPromptSubmit in `agents/claude/settings.json.tmpl`, same `hook-deadline 2` wrapper as `quota_nudge.py`) only records: nothing is printed to the model, no prompt changes, and nothing changes until numbers exist (decision C1). One JSON line per event goes to `~/.claude/state/prior-art-shadow/<session id>.jsonl` (`PRIOR_ART_STATE` overrides the directory, which should hold nothing else; `PRIOR_ART_SHADOW=0` disables; 5 MB cap); carry-over is `<session id>.state.json` for the main agent and `<session id>.<agent key>.state.json` per subagent (Claude Code puts the parent's `session_id` and the subagent's `agent_id` in the payload, so parallel subagents never share a run counter or a web-before flag; a record from a subagent has `agent`). Every record has `schema: 2` and `classifier_version: 5` (5 added the value `unresolved` to `path_class`: a value, not a field, so `schema` stays 2), because the records keep no raw input: a later reclassification tells old rows from new by those. **What is stored, exactly:** the category, booleans, counts and timestamps (`tokens_est` is `bytes // 4`); a pseudonym of the session id (the session id is also the file name); `event` only as `PostToolUse`, `PostToolUseFailure`, `UserPromptSubmit` or `other`; `tool` only for a known built-in tool name or `mcp__<server>` for an MCP server on the fixed lists (the tool name after the server is dropped; else `other`, `mcp__other` or `mcp__<kind>_server`); `client` only as a model family from a fixed list, for Claude its tier, then up to three one- or two-digit version numbers (else `claude-code`); for a fetched URL `host_class` (`loopback`, `private_ip`, `internal`, `public`, `invalid`) and, for a public URL whose registrable domain is on the fixed allowlist in the hook, `host` (that domain only); for a read path `path_class` (`cwd`, `src`, `ops`, `memory`, `nix`, `cache`, `state`, `home`, `tmp`, `other`, and `unresolved` for a Bash read whose every path word needs an unknown variable); `dropped`, the events lost to a held lock since the previous record (the lock wait is bounded to 0.5 s of wall time so the count is written before the hook deadline). **Never stored:** a command, path, query, URL, prompt, tool output, a host outside the allowlist or a server name outside it. Bash is parsed (`shlex`, after heredoc bodies, comments and backslash-newlines are cut and backticks become `$( )`): each pipeline's first command decides, pipe filters (`head`, `wc`, ...) and redirects with their targets are ignored, `cd` moves relative paths (and does not leak out of `( )` or `$( )`), `sudo`/`env`/`timeout`/`bash -c` are unwrapped, the first positional of `rg`/`grep` and the script of `sed`/`awk` are not paths. `ls`, `rg`, `fd`, `find`, `tree`, `graft` and `grep -r` with no path read the cwd; a stdin reader (`cat`, `head`, `tail`, `wc`, `sed`, `awk`, `less`, `more`, `bat`, `grep` without `-r`) with no path is not a read (`cat > f <<EOF` is a write), unless it has `< file`, whose target is its path (a `< file` is read together with any path words, so `cat 1 < /nix/store/x` is external; a digit touching the operator is the fd of `2>f`, not a word: R3-2). Variables (R3-1): the same command's literal assignments (`X=...; cat $X/a`, several per line, quoted values, `~` and `$HOME`, `export`/`declare`, a value built from an earlier one) and literal for-loop word lists are resolved before a read word is classified; a word that still needs an unknown variable (`"$OUT"`, a `$( )` or backtick value, `${X:-y}`, `$1`, a name set by `read`, in a child shell or in a finished subshell) is never the cwd: with no other resolved path the event is `private_other` with `path_class: unresolved`, which does not reset `run_length`, and with another resolved path only that path counts. A `$( )` or backtick substitution inside double quotes is NOT scanned (round 4 removed the round-3 scan: it read the text of a heredoc inside `"$( )"` as commands, so a commit or PR body with markdown backticks invented `web` and external reads; `echo "$(find /nix/store)"` is a miss, see the stated limits). Web is `WebSearch`/`WebFetch`, MCP web servers by name (Firecrawl, Exa, Jina, Parallel, Context7, DeepWiki, Tavily and others, with or without the `claude_ai_` prefix), `curl`/`wget`/`web-get` to a public URL (`127.1`, hex, octal and decimal addresses are classified by their address), `gh search`, `gh api repos/<other owner>/<repo>/(contents|readme|releases|git/|tags|tarball|zipball)` and `gh repo view|clone <other owner>/<repo>`; an owner that is a variable or placeholder (`$REPO`, `{owner}`, `:owner`) is unknown, and polling another owner's PRs, issues or CI is not web; memory is the Basic Memory and similar MCP servers plus reads under `~/ops/*/memory`, `~/.claude/projects/*/memory`, `~/.agents` and `~/kb`. The state directory keeps files for 30 days (`PRIOR_ART_RETENTION_DAYS`); a prompt prunes older ones at most once a day, and only names of the form `<session id>[.a<12 hex>].(jsonl|state.json|lock|drops)` and `.st-XXXXXXXX` temporaries (each event touches the session's lock so a live session's lock never looks old). Summarise one session with:

```
jq -s 'map(select(.category)) as $all | ($all | map(select(.category != "task_change"))) as $e | {events: ($e | length), prompts: (($all | length) - ($e | length)), tasks: ($e | map(.task_seq) | unique | length), by_category: ($e | group_by(.category) | map({(.[0].category): length}) | add // {}), bytes: ($e | map(.bytes) | add // 0), tokens_est: ($e | map(.tokens_est) | add // 0), external_runs: ($e | map(select(.external_run)) | length), duplicates: ($e | map(select(.duplicate)) | length), retries: ($e | map(select(.retry)) | length), quoting_failures: ($e | map(select(.quoting_failure)) | length), web_or_memory_events: ($e | map(select(.category == "web" or .category == "memory")) | length), subagent_events: ($e | map(select(.agent)) | length), dropped: ($e | map(.dropped // 0) | add // 0)}' ~/.claude/state/prior-art-shadow/<session id>.jsonl
```

Not installed in the live `~/.claude/settings.json` yet (the install snippet is in the D2 slice report); the decision to move from shadow to an advisory nudge waits for E1's numbers. Known heuristic limits (adversary D11, round 2 and round 7, documented only): a subagent's `task_seq` can go backwards when a parent prompt resets it (its own idle rule had counted ahead), so grouping by (agent, task_seq) can merge two tasks, while the per-record booleans stay right; a subagent still working when the user sends a prompt is reset mid-run, by design; a path under `~/src` or `~/ops` counts as own code even when it is a cloned third-party repo (16 of 122 git dirs under `~/src` in the 2026-10-26 sample); a `vendor/` directory inside an own repo counts as an external tree; `/opt/homebrew/Cellar` and `~/.rustup` count as `private_other`; `curl` run on a remote host through `ssh` is not a web event; a variable in a path: the cwd default of R2-8.5 was a shared bug of the hook and the adversary's round-2 reading, retracted in round 3 (R3-1). In the frozen 30-session sample (2,572 events, 2,150 Bash) 232 of the hook's 748 own-code events were variable-only reads, 221 of them agent state, home or tmp files. Classifier 4 (5 since round 4, which only drops the double-quoted scan) resolves same-command literal assignments and for-loop lists and buckets what stays unknown as `private_other` with `path_class: unresolved`: own_code 748 -> 487, `unresolved` 4 events, 261 events leave own_code (state 214, home 31, tmp 5, other buckets). Classifier 5 on the same set: own_code 488, private_other 1,956 plus 4 unresolved, web 83, memory 36, external_code 5; 7 of 2,572 events differ from classifier 4 (6 lose a `path_class` the double-quoted scan had set, 1, a `for` loop over `/tmp` files with `echo "$(cat $f)"` followed by an `ls tests/...` in an own repo, is own_code again instead of private_other); of the 292 own-code Bash events with a `$NAME` in the command, 31 stay own code because they also read a literal own path. Still wrong: a `cd` to an unresolved directory keeps the old cwd for later relative reads, a variable holding several words is one path, and a loop variable keeps its list for the rest of the command. Stated limits of adversary round 4 (documented, not fixed, none in the frozen set; each with the adversary's reproduction, cwd `~/src/djbclark-ade`): a pipeline or background assignment counts, bash runs it in a subshell (`X=src/a.py | true; cat $X`, `X=src/a.py & cat $X` -> own_code); an array binds the name to the empty string (`A=(~/.claude/state/x); cat ${A}x.md` -> own_code); `+=` is not an assignment (`X=src/; X+=../../../.claude/state; cat $X/a` -> own_code, bash reads state); `printf -v` and `mapfile` leave the name as it was (`X=src/a.py; printf -v X %s ~/.claude/state/x; cat $X` -> own_code); quotes are gone after tokenising, so a single-quoted or escaped `$X` and a quoted `~` are expanded (`X='$HOME/a'`, `cat '$X'`, `cat \$X`, `X="~/a"`: an own read is lost, conservative); `HOME=/tmp/h; cat ~/x` expands the tilde to the real home; `cat $PWD/x` is `unresolved`; a `bash -c` child starts with an empty variable table, so `export X=/nix/store/a; bash -c 'cat $X'` is `unresolved` where bash passes the exported value (R4-3, pinned by a test: nothing of the parent's reaches the child, the miss is of an external read); a `case` pattern's `)` closes a `( )` scope early (`( case $1 in a) cd /tmp;; esac; X=~/.claude/state/x ); cat $X` -> state, the assignment leaks); `cd "$VAR"` keeps the old cwd (`cd "$STATE_DIR" && cat run.json` -> own_code/cwd); a stdin reader with a path word and `< file` counts the redirect file too (R4-5: `cat 1 < /nix/store/x`, `wc -l "2"< node_modules/a.js` -> external_code, bash reads only the path word) and `0<>f` (read-write stdin) is missed. Stated limits of adversary round 3 (documented, not fixed): `$((1<<2))` and `(( x << 2 ))` are read as a heredoc (1 of 2,150); an escaped or nested backtick is not split; shapes bash reads differently from the lexer (ANSI-C `$'it\'s'`, an unclosed quoted heredoc delimiter) fall to the coarse split, which can invent a read (0 of 2,150 fell back in the sample); `\;` as in `find -exec ... \;` is a command separator (0 of 2,150 with a word after it); a command substitution inside double quotes is not scanned at all (R4-1, removed on purpose, do not re-add casually: `echo "$(find /nix/store)"` is a miss; on the frozen set of 2,150 Bash commands the round-3 double-quoted scan appended a substitution on 58 commands (25 of them classify as a read or non-private category on their own) and changed 7 events against none (1 own_code -> private_other, 6 only a `path_class`), whereas a heredoc inside `"$( )"` is the standard commit and PR body form of every other Claude Code session); `OWN_GITHUB_OWNERS` is only `djbclark`, so a public repo of an org djbclark belongs to counts as web (3 events in 7 days, 0 private; a `gh api repos/<member org>/<private repo>/contents` would too); `gh api https://api.github.com/repos/...` (a full-URL endpoint) is not web (0 in 7 days); `gh search code --owner djbclark` counts as web; `rg PATTERN < file` counts as a read of the cwd (rg searches stdin when it has no path; not measured); a scheme-less `curl pypi.org/x` is not web (R2-8.2; 0 of 2,150 in that sample); a symlink into a memory directory is not memory, the rule is textual (R2-8.7; 68 symlinks sit under the memory roots on 2026-10-26, how many events touch them was not measured); a main agent whose session id has the form `X.a<12 hex>` would share state with a subagent of session `X` (R2-8.6; Claude Code's ids are UUIDs, so none occur); the prune patterns delete any file shaped like a session file in the state directory, so `PRIOR_ART_STATE` must point at a directory of its own (R2-7; the default is one); `$(( a << b ))` arithmetic is read as a heredoc (not seen in the sample).

## Follow-ups after PR 73 and PR 74 (merged 2026-10-25; adversary rounds, none blocking)

PR 73 merged as b2bd2a1, PR 74 as 6f54e89 (adversary `APPROVE` 39cd2db and `APPROVE` 3402d84). Each item below was reproduced by the adversary and judged Low or informational; nothing here is started.

1. **relay.py R5-1 (Low, PR 74 round 5)**: `send_paseo` matches `probe_raw or probe_esc` for every text, but a headerless text (a Paseo-agent sender, `sender_tag()` returns "") is always stored escaped by the daemon, so `probe_raw` only adds false-`delivered` surface there (`ours="it's"` is certified by another message's line `it's green now`). Fix: use the raw probe only when the text carries the `[relay from ` header (`route_paseo` passes `raw=bool(tag)`, or `send_paseo` tests `text.startswith("[relay from ")`); the deferred deliverer keeps both probes (it adds a header and keeps the record's `PASEO_AGENT_ID`).
2. **relay.py R5-3 (Low, pre-existing)**: a whole text that is a prefix of another pending text from the same sender is certified by that text's line (`done` by `done and merged`). Fix: end-anchor the probes (`probe_raw + '"'`, `probe_esc + '\\n</paseo-system>'`); read Paseo's `delivery.js` join of queued prompts (`\n\n`) before choosing the terminator.
3. **relay.py, from rounds 2 and 3 of PR 74**: r2 A3 (an `aka` name match; a declared label spelling a session-id header); r2 A6 (a relay that died after reserving an ID blocks its sender's retry for 10 min); r2 A7 (`--expect-ack` to an acp-dispatch record closes only if the slice answers through relay.py); r3 A1 (a Hermes target's `who` holds the date word `sid[:8]`); r3 A2 (`hermes_forged` is a full match, so a suffixed label still poses as Hermes); r3 A3 (a rotated Hermes session's reply never closes); r3 A4 (`who: []` fails open on a hand-edited link); r3 A5 (two stale `inherit = "core"` comments). Details: `~/.local/state/bigteam/adhoc-2026-10-25/adv-relay-r2-report.md` and `adv-relay-r3-report.md`.
4. **routing (PR 73, round 5 notes)**: LOW, the snapshot-file fallback (pre-existing at ca9d3b6) admits on a file up to 25 minutes old when aiuse itself fails, so "fail-closed" holds only when no snapshot file exists; INFO, a hanging aiuse can now cost up to three timeouts per foreground dispatch; INFO, the dispatch post-load fresh read is unconditional over agents; INFO, two post-run memo readers are not admission boundaries. Also three P3 notes from round 4 (ca9d3b6): legacy stored windows, the docs scope of the window floor, a test `SESSION_FINDER_STATE` leak.
5. **Open Codex panes**: `w2F:p45` (`~/src/djbclark-ade`) and `w2Q:p1` (`~/ops/site-djbclark/macos`) sit behind permission dialogs only djbclark can answer; relays to both failed (2026-10-25). Not an agent task.

## relay.py deferred send and Paseo sender label (2026-10-24, branch `feat/relay-deferred-send`, PR #57)

Built, repair round 2 (2026-10-24) after a second adversary BLOCK, not merged: a busy target no longer loses the text (`relay.py`
prints `queued: <id>` and exits 0 for a caller it can identify; 0600 record under `~/.local/state/relay/deferred/`, detached
`--deliver` with its own clean environment, `--pending`, `--cancel`, `--sweep`) and `sender_name` reads `PASEO_AGENT_ID`.
`load-watch` passes `--no-defer` for incident briefs (a queued brief arrives after the spike; only `watcher test` may queue).
A caller with no identifiable sender (fleet-watch's `upr_relay`, load-watch, cron scripts) gets exit 1 "deferring needs an
identifiable sender" on a busy target, which is the behaviour before this branch: fleet-watch's `upr_dispatch` reads rc 1 as a
refused relay and falls back to a worker (checked 2026-10-24). **site-private follow-up** (not edited here): `upr_relay` could pass `--idle S`. Open:
(1) no launchd job re-arms queued records after a reboot yet; they wait for the next `relay.py` run (its opportunistic sweep)
or `relay.py --sweep`, by the brief; (2) a Claude-pane target is never deferred (it queues natively); (3) one deliverer
process per queued record (at most 100), only the head of a target's queue polls it; (4) `--cancel` has no sender check
(same-uid operator surface); (5) `PASEO_AGENT_ID` can be forged by a same-user process, as `HERDR_PANE_ID` can; (6) the
bounds can be starved by a same-user process that mints sender keys (100 in all; never silent: exit 1 "deferred queue
full"), one sender can fill one target's 20, and a deliverer stuck in a send holds its own record's owed notice until a later
sweep; (7) a Paseo daemon error is tolerated for only 3 looks, 5 s apart (about 10-15 s): raise `DEFER_ERRORS` or space
the looks if a longer restart must be survived; (8) at QUEUE time a herdr pane row with no session id, transcript or pid is not deferred (exit 1 with the `--idle S` hint)
when `pane process-info` fails, or when no foreground process, or more than one, is named like the agent (the herdr label
or a binary `fleet.PROC_AGENTS` maps to it; with one foreground process in all, that one is taken); at POLL time the stored
pid only has to be among the pane's foreground pids (tool and MCP children come and go), and a pane herdr cannot read
counts as an error that fails the message only after 3 in a row (about 10-15 s, as in (7)); (9) two records left by an earlier test run sit in
`~/.local/state/relay/deferred/` (`20261024-194844-fe1631`, `20261024-194854-57fcc1`) and are pruned by a sweep a week after
they went final; the test suite now points `RELAY_DEFER_DIR` at a temp directory (`tests/conftest.py`) and
`tests/test_zz_relay_real_state_untouched.py` fails if a freshly loaded relay would point at the real directory.
Round 4 residuals (APPROVE f3873a2, 2026-10-24; all LOW/NIT, each ends in a notice and loses nothing): (C1, C2 and C4 fixed in #60, 2026-10-25: a row with a session id or transcript no longer checks the stored pid at poll time; a herdr row is judged by membership even with fleet's own pid, and an undetected pane with several same-named processes is refused at queue time (defensive, 2026-10-25: fleet reports undetected rows as `unknown`, so none is deferred today; if that changes, keep the pid check for them); `deliverer_env` passes the three directories resolved); (B3, NIT) `deliverer_env` resolves symlinks where `.absolute()` would do, so a symlinked `RELAY_UNSENT` puts the deliverer's pane locks beside the link target until the first rewrite (no symlinks in real state); (C3) a sid-less pane whose TUI has a same-named foreground child (npm/npx wrapper plus native binary, `codex exec` in the TUI's pgrp) has two name hits, so the queue is refused with exit 1 "Retry with --idle S" (not observed live; herdr's process-info carries no ppid for a tie-break); (C5) a deferred Hermes turn starts with cwd `/`, informational.

## tuios support: do it LAST (djbclark, direct, 2026-10-24)

djbclark, 2026-10-24: "Queue for very end, although we can consider it a little now to make room for it any work between
now and then: Add support for tuios (new herdr-like thing that looks cool). paseo is our first-class interface; herdr is
secondary, and tuios for the moment is tertiary, so ask before you do anything for it that would cost a lot of tokens. Do
web searches about it and make heavy use of web searches during all of your work in general."

1. **Tier and rule.** Paseo first-class, herdr secondary, tuios tertiary (for now). **Ask djbclark before any tuios step
   that costs many tokens** (a research slice, an adapter, a skill, an `acp-run`/`herdr-tidy`/`session-finder` port); a
   web search or a README read is cheap and needs no ask. It runs after everything else in this file.
2. **What it is (web, 2026-10-24).** [github.com/Gaurav-Gosain/tuios](https://github.com/Gaurav-Gosain/tuios), docs at
   [tuios.dev/docs](https://tuios.dev/docs): a Go (Bubble Tea v2) terminal multiplexer and window manager, vim-style modal
   interface, BSP tiling, up to 9 workspaces, kitty graphics, a daemon that keeps sessions alive. Install: `brew install
   tuios` (or `go install github.com/Gaurav-Gosain/tuios/cmd/tuios@latest`, or the install script; `tuios update`).
3. **Why it matters here: it is built for coding agents.** Per its README: agent state per pane (working, waiting, done,
   errored) and an **Inbox** of everything waiting on you across sessions and machines (approvals, questions, mail, errors);
   `tuios ask-human`, `tuios send-agent-message`; `tuios fan` (one prompt to several agents, mixed harnesses, each in its own
   git worktree), `tuios start-agent`; **pane grants** (`read`, `write`, `fan`, `respond`, `admin`); an **MCP server**
   (`tuios mcp`, read-only by default); a **tmux shim** (`tuios tmux-shim`, for tools that drive tmux, such as Claude Code
   agent teams); `tuios --skill` (the guide an agent in a pane reads); a JSON verb protocol for driving the daemon; **hosts**
   (`tuios hosts add`, ssh, Tailscale) and remote sessions (`tuios attach --host`); resume of each agent conversation after a
   daemon restart; Program Status Protocol (OSC 7501) and shell hooks on window, session and agent events.
4. **Likely shape of the work (not started; each needs the ask in item 1):** 1. a read-only research slice (Opus 5.5 high via
   omp, web research plus the repo's `docs/AGENT_STATE.md` and `AGENTS.md`) on how tuios maps onto what `helm`, `herdr-tidy`,
   `autorename`, `session-finder`, `relay.py` and `herdr-sleeper` do for herdr, and what overlaps Paseo's own host and
   Subagents features (see "Paseo connected hosts"); 2. the security view (pane grants vs our `--perm` and yolo policy, the
   tmux shim, `tuios mcp`) in `docs/threat-model.md`; 3. a tertiary-tier port, smallest useful first (naming rule next to
   `-pt`/`-pw`, then session discovery, then Inbox into `helm`), only if the research says it earns its keep.
5. **Standing order from the same message: use web searches heavily in all work**, not only here (memory
   `feedback_heavy_web_search`).

## bm-lint (PR 55) and pr-wait (PR 58) follow-ups (merged 2026-10-25 as 3d0c2e2 and 7c3b73c)

Both merged at adversary APPROVE and clean Codex reviews; these were disclosed in the PR bodies and left unfixed on purpose. Reports: `~/.local/state/bigteam/ade-queue-build-2026-10-24/adv-bm-w3-r6-report.md`, `adv-prwait-r5-report.md`. Also open: the weekly `bm-lint` hook-up in site-djbclark `fleet-watch` (`bm-w3-fleet-watch.patch` in that directory, parked until PR 55 merged: offer it to djbclark).
1. **bm-lint LOW**: a config project path holding a lone surrogate (`"/tmp/x\ud800y"`) still aborts the run with `internal error: UnicodeEncodeError` (`os.walk` in `check_empty_projects`, `bin/bm-lint:418-425`); class name only, nothing leaks. Fix: wrap the walk in `try/except ValueError` and list the project as `not fully readable` (the `"\0"` test then becomes redundant).
2. **bm-lint LOW**: a partial read (some notes skipped, the rest clean) prints `ok, no findings` with rc 0 by contract; the headline could show the skipped count. On a filesystem without `d_type`, a subdirectory under a 0444 directory might be filed as a file [INFERENCE]. Earlier LOWs: CommonMark fence edge cases, a newline in a filename in text mode, the `skipped` cap loses names.
3. **pr-wait MEDIUM (missed post)**: `push_stamp` takes the earliest check-suite `created_at` of the head sha and ignores `head_branch`, so a sha pushed earlier to another ref (a backup or stacked branch with push-triggered CI) dates the push too early; a request for the previous head between the two pushes then counts and the wait ends `codex-stuck`. Fix: keep only suites whose `head_branch` is the PR's `head.ref`, fall back to no stamp (which posts).
4. **pr-wait LOW**: (a) no push stamp (no CI app): a previous head's request within 120 s plus any clock skew before an errored POST is indistinguishable from ours (docstring says "120 s", add "plus any clock skew"); (b) a lost or deleted request-state file, or another `$PR_WAIT_STATE_DIR`, on a no-stamp repo with no marker lets a new run post a third time, and the `load_request_state` docstring (~:629) still says the timeline guards a first post; (c) a request in the same second as the push stamp is not counted (strict `>`): `skills/bigteam/SKILL.md` should say "after a push, start pr-wait and do not post by hand"; (d) `@Codex review` / `... please` is not counted as a request (one extra capped post); on a fork PR the PR author's own request stops pr-wait from posting.
5. **Both**: Codex's PR review stuck "Running" on PR 55 head 7a59802 (openai/codex#55890); `pr-wait` now re-requests once, but the cause is upstream.

## ade-scan-state follow-up 3 after PR 47 (adversary round 3, 2026-10-24)

PR 47 merged (6234a18) at adversary APPROVE; djbclark chose to queue these LOWs rather than fix them (report: `~/.local/state/bigteam/adhoc-2026-10-24/adv-shallow-47-r3-report.md`). 1. **LOW**: `tests/test_ade_scan_state.py` asserts `git clone --bare` once per row, not inside each note (a row with two notes passes if one says a plain clone); assert it in each note's span. 2. **LOW**: the shallow note on the odd-name `all-refs.bundle` row (`bin/ade-scan-state-doc`, the `ODD_NAME_NOTE` branch) has no test; set `c["branch"] = "b\ufffd"` on the real record in the branch case and expect `all-refs.bundle` with `+refs/*:refs/bundle/*`. 3. **LOW**: the comment above `_shallow_note` and the test's "a non-forced update would be rejected" overstate: into `refs/bundle/*` a non-forced fetch also succeeds on a fresh bare clone; reword to "a fetch into `refs/heads/*` would be rejected". 4. INFO: the CHANGELOG line says "now say" for "every bundle row" (should be "says") and omits the odd-name row.

## ade-scan-state follow-up 2 after PR 39 (adversary round 70, 2026-10-24)

PR 39 was approved at head 14c7347 (no BLOCK or MEDIUM). Left for one small later PR (`adhoc-2026-10-24/adv-scan-70-report.md`): 1. **DONE in PR 47 (2026-10-24)**: a shallow checkout WITH an origin still gets `HEAD.bundle`, `branch-<b>.bundle`, `all-refs.bundle` and `local-only.bundle` rows (`bin/ade-scan-state-doc` ~779-822) that cannot be cloned alone (`git clone` rc 128); read `c.get("shallow")` in those rows too and either copy `shallow` beside the bundle or say "restore by fetching into a clone of origin; keep origin". 3. **DONE in the follow-up 2b PR (2026-10-24)**: a row whose scan saw a gitfile naming a git directory outside the checkout pastes `GITDIR_REQUIRED_FMT`, which fails (nonzero, `gitdir capture FAILED: .git is not a file` on stderr) when `.git` is no longer a file; the plain `GITDIR_FMT` stays a silent no-op for an ordinary `.git` directory. 4. **DONE in the same PR**: the PR 39 CHANGELOG line is split into eight, one per change. 5. **LEFT, by design (2026-10-24)**: `merge_repositories` keeps the first spelling, which its docstring says and `test_one_directory_under_two_spellings_is_one_embedded_repository_not_two` pins; a symlink spelling is unreachable today (adversary round 70), so no test can show a `realpath` preference without inventing an input; the only reachable case is the case-insensitive pair, where either spelling is the same directory.

Open LOWs from the PR 54 adversary round (APPROVE at 8b0ecfd, merged 9d8f896, 2026-10-24): b. **LOW**: the split CHANGELOG line for `--separate-git-dir` names only `bin/ade-scan-state-doc`, but PR 39 made that change mainly in `bin/ade-scan-state` (docstrings) and `docs/threat-model.md:322`; widen the file list. c. **INFO**: a skipped linked worktree whose gitfile points back (skipped for alternates, a time-out) still gets the plain `GITDIR_FMT`, so a missing `.git` at paste time exits 0 having archived nothing (the gap item 3 closed only for the foreign case); by design in the PR body, revisit if it bites.

Open LOWs and INFO from the 2026-10-24 landing rounds (PRs 37, 38, 32, merged a40e21a, a637686, 8cb18f7): g. PR 37 **LOW**, recorded as accepted: in-tree link amplification in canonical mode (`cp -rL` copies each link to one in-tree file); and a check-versus-copy TOCTOU via a swapped path component (`unsafe_links` in `bin/skill-everywhere`, needs a local writer). h. PR 38 **LOW**: the rearm hint prints "up to 2.0 h" for waits just over 2 h; a `wait_timeout` within about 60 s of 7200 can have its waiter killed just before its 124; the usage header says 7200000 is named only for short waits. Landing note (2026-10-24): six PRs landed in one evening and every merge moved master, which re-conflicted `CHANGELOG.md` for the next (each PR adds a line at the top of `### Fixed`); a small `CHANGELOG` union helper at `~/.local/state/bigteam/pr-landing-2026-10-24/union-merge.py` did the resolution, and a merge queue or a rule that PRs add their line at a random position would end the treadmill.

## Consider: drop the brew Paseo and run our fork instead (djbclark, direct, 2026-10-24): ASK FIRST, it is disruptive

djbclark, 2026-10-24: "At appropriate point, consider if we want to remove the paseo brew install and instead just use our fork (make sure the CLI tools are on the PATH and the GUI App gets replaced and all the daemons/launchd is updated with new locations etc). Ask me before doing this work as it will be disruptive."

1. **Today (verified 2026-10-24):** brew cask `paseo` 0.13.0 (`/opt/homebrew/Caskroom/paseo/0.13.0`, installed 11:15 AM) puts `/Applications/Paseo.app` (bundle `sh.paseo.desktop`); `/opt/homebrew/bin/paseo` and `~/.local/bin/paseo` are both symlinks to `/Applications/Paseo.app/Contents/Resources/bin/paseo`; launchd has `com.djbclark.paseo-desktop` (`~/Library/LaunchAgents`, opens `/Applications/Paseo.app`) and a `paseo-upgrade` label whose plist I did not find under `~/Library/LaunchAgents`, `~/ops/site-djbclark/roles` or `bin/` (locate it first). The fork is `~/src/paseo` ([djbclark/paseo](https://github.com/djbclark/paseo), upstream [getpaseo/paseo](https://github.com/getpaseo/paseo)), currently on branch `feat/workspace-identity-accent`, 4 commits ahead of `upstream/main`; packages: app, cli, client, desktop, protocol, relay, server, plugin.
2. **Decide first (research, cheap):** why we want the fork (our patches: workspace identity accent, tab colors, lifecycle), what we lose (brew's automatic upgrades and the signed, notarized upstream build; an unsigned fork build needs a Gatekeeper decision), and how the fork would track upstream releases (a rebase cadence, a CI build on GitHub runners per item 37, never a heavy build on the Mac). Web-search the desktop packaging (`packages/desktop`, electron-builder or similar) and whether upstream publishes build instructions.
3. **If djbclark says go (ask separately, naming what it interrupts: every Paseo agent, this window included):** 1. build the fork's desktop app and CLI; 2. `brew uninstall --cask paseo` only after the fork build runs; 3. put the fork's `paseo` on PATH at `~/.local/bin/paseo` (and remove the `/opt/homebrew/bin` symlink or point it at the fork) so every client (`acp-run`, `relay.py`, `fleet.py`, the load watcher) finds it; 4. replace `/Applications/Paseo.app` with the fork app and update `com.djbclark.paseo-desktop` and `paseo-upgrade` (through the Ansible role in site-djbclark, never a live plist edit, rule 18); 5. grep djbclark-ade, site-djbclark and site-private for the old paths (`/Applications/Paseo.app`, `/opt/homebrew/Caskroom/paseo`); 6. restart the daemon once, verify `paseo --version`, `paseo ls`, the connected-hosts round trip and the skill-sync guard (memory `project_paseo_skill_sync_writes_through_symlinks`).
4. **Order:** after the connected-hosts upgrade is verified on stock 0.13.0 (so a regression can be told apart from the fork), before tuios. Not started; blocked on djbclark's go.

## Paseo connected hosts: make full use of them, after we quiesce and upgrade Paseo (djbclark, direct, 2026-10-24)

Status 2026-10-24 (afternoon, after the research slice; report `~/.local/state/bigteam/pr-landing-2026-10-24/connected-hosts-research2-report.md`): the Mac daemon is already 0.13.0 (`daemonVersion` 0.13.0, 127.0.0.1:7263), so no restart is needed; `paseo host ls` is empty (nothing connected). Correction: the report's recommendation of `get` is withdrawn (`get.sipb.cloud` is down, hyades microVM slots are used up). Host choice (djbclark): the eventual host is vps-primary as user `bb`, which is already logged into the agent services. Read-only look at vps-primary, 2026-10-24: `bb` exists (uid 994, home `/var/lib/bb`, logins present for Claude, Codex, Cursor, omp, grok, Hermes, copilot, gh, zcode); a Paseo daemon already runs there as `bb` (listening on 127.0.0.1, the tailnet IP and the tailnet IPv6, port 7263) but it is **0.11.4**, and connected hosts need **0.13.0+ on both daemons**, so the vps-primary package (nix, `paseo-bin`) must be bumped first through the `nixos/` flake and the pushed `deploy-vps-primary` branch, never by hand; disk is 87% used (3.9 G free), RAM 3.8 GB (about 2.6 GB available) against BB's 3G cap; `bb` has no `~/.ssh`, so the `ssh://` transport needs a key added through the flake, or use `host:port` over the tailnet if the daemon accepts it. A scrappable podman-microVM trial first is optional; nothing is installed, connected or deployed without djbclark's yes.

Status 2026-10-25 (djbclark: scrap the bigger-server work, keep the current vps-primary): Hetzner CX33/CX43 rescale, the Netcup/OVH trials and the restock watcher are dropped (watcher PR https://github.com/djbclark/site-djbclark/pull/231 closed unmerged, branch `ops/hetzner-restock-watch` kept on origin at edf21b3, adversary-approved). Landed instead: https://github.com/djbclark/site-djbclark/pull/232 (paseo-nix 6b79032 = Paseo 0.13.0, journald `SystemMaxUse=200M`; weekly nix-gc 14 d, optimise and grub limit 10 were already there), promoted to `deploy-vps-primary` at 22ea786 and applied with `systemctl start nixos-upgrade`. Verified on the host 2026-10-25 (04:18 AM UTC): `nixos-version --configuration-revision` 22ea786, `paseo` 0.13.0, service active, journal 157 MB; root is still 85% (4.4 G free) because the old and new Paseo closures coexist until the weekly 14-day GC, the 7.5 GB swap partition cannot be reclaimed without a repartition, and a Hetzner Volume (EUR 0.0767/GB/month per the pricing API, 10 GB minimum; the 0.057 figure here earlier was wrong) was the cheap way to add space and was created the same day. Update 2026-10-25 (05:2x UTC): bb's home moved to a 15 GB Hetzner Volume 107263872 `vps-primary-bb-home` (ext4, UUID cef32561-f50a-4332-ae46-b5ee5a1570eb, nbg1, about EUR 1.15/month, grow in place then `resize2fs`) via site-djbclark#233; root disk now 49% (15 G free), volume 75%. The BB service (bb.service, tailnet 443/38443) was removed from vps-primary, the `bb` user stays for Paseo (djbclark: BB is deprecated); the Mac's BB host daemon (port 38888 LaunchAgent) has no server and can be uninstalled. Connected hosts: `paseo host add 'wss://vps-primary.greyhound-sidemirror.ts.net:7263' --label vps-primary` from the Mac, status online (registration hst_c77a1bb4-4b9e-4eec-aa48-592c6dc0363d); ssh:// stays the documented fallback (needs a key for `bb` through the flake). Test agent (2026-10-25): `paseo --host wss://vps-primary.greyhound-sidemirror.ts.net:7263 run --workspace <id> --provider codex ...` ran on vps-primary as `bb` from the Mac (workspace made with `workspace create --isolation local --path /var/lib/bb/...`, then archived; scratch dir removed). Swap partition kept (djbclark: may be needed). Mac BB host daemon LaunchAgent unloaded and its plist moved to `~/.local/state/retired-launchagents/`, ports 38886/38887/38888 released in `registry/ports.yml` (2026-10-25). The later hardening PR (djbclark, 2026-10-25) also carries the ssh:// fallback (authorized key for `bb`, then register a second host). Hardening done (2026-10-25, site-djbclark#234, rev a7c2aa7): bb uid 994 / gid 991 pinned, mount `rw,nosuid,nodev`, Hetzner delete-protection on volume 107263872. The ssh:// fallback needs no key (djbclark already has ssh access): Paseo allows ONE registration per daemon (a second gives `duplicate_host`), so fail over by swapping the connection: `paseo host update <registrationId> --connection 'ssh://djbclark@100.125.249.107?daemonPort=7263'` and back to `wss://vps-primary.greyhound-sidemirror.ts.net:7263` (tested online both ways). The swap partition stays (djbclark: may be needed). Nothing open on vps-primary.

djbclark, 2026-10-24: "Add to appropriate point in our queue, we should make full use of this new feature (before doing
this we'll need to run out the queue / quiesse here so we can install the latest paseo version that supports this and
then restart paseo)". The feature is from the changelog of Paseo **v0.13.0-beta.2**, shipped in stable **0.13.0** (2026-10-24; [beta.2 notes](https://newreleases.io/project/github/getpaseo/paseo/release/v0.13.0-beta.2), [releases](https://github.com/getpaseo/paseo/releases); docs `docs/connected-hosts.md` in the repo). **Installed by 11:15 AM EDT 2026-10-24** (brew cask 0.13.0, `Paseo.app` and `paseo --version` both 0.13.0); whether the running daemon is on 0.13.0 is unverified (it was restarted onto beta.1 at 9:57 AM), and a restart needs djbclark's separate yes (memory `feedback_ask_before_restarting_paseo_daemon`). Status 2026-10-24 (about 10:00 AM EDT): another session restarted the daemon 0.12.0 -> 0.13.0-beta.1 (09:57-09:58 AM) on djbclark's instruction, so the quiesce in item 1 is done for that restart; beta.1 lacks connected hosts, so item 1 now reduces to: verify the daemon version, ask, restart onto 0.13.0, then item 2. Changelog text: "Connect your daemon to another machine, then ask an agent
to delegate work there": `paseo host add 192.168.1.20:6767 --label studio`, `paseo host add 'ssh://me@build-box' --label
build-box`, `paseo host add 'relay://...' --label laptop`; "Added connected hosts, so agents can create, prompt and
monitor agents on other machines and see them in the Subagents track (#7370, #7593)".

1. **Order (djbclark's): run the queue out first, quiesce, then upgrade.** Let running slices and adversary rounds
   finish (rule: never throw away paid-for work), land open PRs, write the handoffs, then install the newest Paseo and
   restart the daemon (a restart keeps agent identity and drops the in-flight turn, see the Paseo-restart memory), then
   verify with `paseo --version` and one `paseo host add` round trip. Re-check the skill-sync guard
   (`agents.skills.selection` in `~/.paseo/config.json`): a daemon start overwrote the vendored paseo skills once
   (2026-10-23).
2. **Then design the use, one slice, read-only research first** (Opus 5.5 high via omp; web research on the release
   notes and PRs 7370 and 7593): which machines to connect (the NixOS boxes get and vps-primary, the Hermes host, Hyades
   microVMs over `ssh://`, a relay for the laptop), what the security boundary is (a connected host means an agent here
   can prompt agents there: threat-model entry, `--perm`/yolo policy per host, secrets only via `sudo-secretspec`), how
   delegation relates to `acp-dispatch`, `acp-run` and Orca (a host becomes one more route in `route_agent.py plan`, never
   an all-vendor fan-out), and how names stay `human name + id` across hosts.
3. **Build after djbclark rules on the design**: host roster doc, `docs/mcp-servers.md`/README entries, a `paseo host`
   health line in the fleet watcher, and the `-pt`/`-pw` naming rule extended to remote agents (see "Paseo tabs").
4. Not started; blocked on item 1 (quiesce) and on the Paseo release being installed.

## Phase 0 scan of bigteam and the Orca checkouts (proposal §8 item 1, djbclark 2026-10-20)

1. **Scan, capture list and tool: done 2026-10-20 (PR #27).** `bin/ade-scan-state` and
   `docs/ade-everywhere-phase0-scan-2026-10-20.md` list the unique bigteam reports, dirty trees, untracked
   files and unpushed commits. Nothing was copied, pushed or deleted. Open, each needs djbclark: (a) where the
   41 unreferenced bigteam report sets are copied (one destination); (b) `~/src/one-offs` (37 commits, no
   remote) and its Orca worktree `Hermes`: host it or bundle it; (c) push or bundle the branches with commits on
   no origin branch (doc section 3.2). The 54.5 GiB `adhoc-2026-10-18/hm-promo-rehearsal/` is scratch; deleting
   it is a later cleanup decision.

## Make better use of Basic Memory (djbclark, direct, 2026-10-23)

djbclark, 2026-10-23: "Add another item to appropriate phrase: Look into making better use of basic memory, I do not
think we are using it that much/makeing the best use of it, but I could be wrong. Do web searches etc." Status
2026-10-23: **research done; djbclark accepted all eight recommendations 2026-10-23; Q1 (the security upgrade) is DONE,
the rest is queued until the Claude quota resets** (`design-basicmemory`, Opus 5.5 high via omp, web research,
read-only; brief `~/.local/state/bigteam/ade-2026-10-20-phase0-queue/brief-design-basicmemory.md`, report
`~/.local/state/bigteam/adhoc-2026-10-23/design-basicmemory-report.md`). Verdict, last 30 days: djbclark is right about
the tool and wrong about the store. 680 notes in `main`, and 301 of 3,074 Claude sessions (9.8%) touch the store as
files, but only 32 sessions (1.0%) made any Basic Memory MCP call (46 calls: `search_notes` 23, `write_note` 15,
`build_context` and `schema_*` 0, `recent_activity` 1), Codex made none, there are zero `decision` notes, and Hermes's
provider has been off since about 2026-10-03. **Q1 done 2026-10-23 (~9:20 PM):** GHSA-4gfv-c2mm-mvj2 (High, 7.7: no
Host/Origin check on the HTTP transports, so DNS rebinding from any web page) affected our v0.23.2 streamable-http
server; upgraded with `uv tool upgrade basic-memory` to v0.24.1 after an index backup in
`~/.basic-memory/backup-2026-10-23/`, restarted `com.djbclark.basic-memory-mcp`, verified a foreign `Host` gets 421
and a foreign `Origin` gets 403 while a loopback request is served; sessions reconnect with `/mcp`. Rulings Q2-Q8: 2.
shadow our own `claude/hooks/bm_recall.py` (titles only, 400 tokens at most) against `bm hook session-start` for a
week, keep the cheaper one that passes the recall evaluation, never both live; 3. move the 193 per-project auto-memory
files into `site-private/memory/projects/<slug>/` with symlinks back (a dir already symlinked into its repo keeps being
its own project); 4. re-enable Hermes's Basic Memory provider with `capture_per_turn: false`; 5. remove the 8 empty
`~/agent-memory/*` projects, archive (not delete) the 3 dead `basic-memory/` subtrees; 6. handoffs older than 30 days go
to `handoffs/archive/`; 7. backfill `type:` on the 321 prefixed root notes by one reversible script commit; 8. a
`ruling` only for something djbclark said (quoted, dated), agents' own choices are `decision` notes with a relation to
the handoff or PR. Build: the report's W2-W8 (drift fixes, `bin/bm-lint`, `bm_recall.py` in shadow mode, handoff
observations and relations, type backfill and schemas, recall evaluation harness, Q3/Q4 config), Sonnet 5.5 workers.
Phase placement: R2 now, the M1 track beside Phase 1, R7/R9 with proposal 6.4 / Phase 5. The report measures the store (note counts, growth,
relations, orphans) and real agent use (MCP tool calls per day from the transcripts), compares with the per-project
auto-memory files, `docs/handoffs/`, `session-finder` and Hermes memory, surveys what works elsewhere, and recommends
capture and recall hooks, note schemas and consolidation, plus the phase it belongs in
([`docs/ade-everywhere-proposal.md`](ade-everywhere-proposal.md) section 8; levels in
[`docs/ai-memory-landscape.md`](ai-memory-landscape.md)). Nothing is built.

## Heavier use of Hermes worktrees and cow pastures so agents stop stepping on each other (djbclark, direct, 2026-10-23)

djbclark, 2026-10-23: "Also add to appropriate phase if we haven't yet, we should probably be making heavier use of
hermes worktrees and cow pastures, to avoid agents stepping on each other's toes. Do web searches and consult a
strong model on this as well." Status 2026-10-23: **design done, all seven recommendations accepted by djbclark
2026-10-23, build queued until the Claude quota resets** (report
`~/.local/state/bigteam/adhoc-2026-10-23/design-isolation-report.md`, Opus 5.5 high via omp with web research; brief
`~/.local/state/bigteam/ade-2026-10-20-phase0-queue/brief-design-isolation.md`). Rulings: 1. Hermes stays never a
target (`hermes -w` is not used; its design is borrowed). 2. No agent edits in the primary `~/src/<repo>` (integration
and fast-forward only; the lead's doc commits move to its own pasture). 3. `~/ops` may get a linked worktree outside
`~/ops` when two agents must write one ops repo, guard-enforced (`stash` and autostash refused in `~/ops`). 4.
`acp-dispatch --workspace auto` is the default for `--kind code`, `shared` opt-in. 5. The git guard covers
acp-run-launched agents plus a Claude hook first; `~/.local/bin/git` only after a week with no false refusals. 6. The
placement is a queue gate **I0 (workspace isolation)** ahead of Phase 1's first parallel fan-out, with Phase F section
4 and proposal 9.4 consuming its adapter. 7. The reaper removes clean, merged and released pastures without asking;
dirty or unpushed ones only ping. The build is the report's slices W1-W8 (claim library and guard `ade-git-guard`,
`cow-pasture` claims and reaper, `acp-dispatch --workspace`, acp-run PATH, Claude hook, gate test, docs, home rules),
Sonnet 5.5 `code` workers, adversary on W1 and W3 at minimum. The report decided which phase of
[`docs/ade-everywhere-proposal.md`](ade-everywhere-proposal.md) section 8 this belongs in (or a step before Phase 0),
what "Hermes worktrees" is (Hermes is never a routing target: whether its worktree mode as a user feature needs a
ruling), when an agent gets a pasture, worktree or the shared checkout, claim files, and guards in `bin/cow-pasture` /
`acp-dispatch` against `reset --hard`, `checkout --` and `stash` in a pasture the agent did not create. Motivating
incident (2026-10-23): a `git reset --hard origin/...` ran inside the phase0-scan pasture and wiped uncommitted edits.
Nothing is built; the phase placement is added here and to the proposal once the report lands.

## Paseo tabs: how to use them, a `-pt` naming rule, autorename for tabs, and a rename-history store (djbclark, direct, 2026-10-23)

djbclark, 2026-10-23: "I just realized paseo has tabs. Put in the appropriate place and ask a strong model to consider
how we should use tabs. Add a naming convention for paseo tabs that the titles are all lower case and hyphenated and
end in -pt (paseo tab) and the names should be short as only around 17 characters are visible even if it is the only
tab. Also make autorename work with paseo tabs, and just like workspaces we need to track the names of tab to be able
to find them even if the user changes them in the UI after the autorename etc. This history system should also apply
to herdr panes, tabs, and workspaces, our sqlite database might be a good place to do this, but again consult with a
strong model on this problem, and ask me any questions that come up when this feature implementation surfaces."
Status 2026-10-23: **design done, all ten recommendations accepted by djbclark 2026-10-23, build queued until the
Claude quota resets** (report `~/.local/state/bigteam/adhoc-2026-10-23/design-tabs-report.md`, Opus 5.5 high via omp;
brief `~/.local/state/bigteam/ade-2026-10-20-phase0-queue/brief-design-tabs.md`). Rulings: 1. The Paseo agent name is
the short tab name (`adv-r3-pr31-pt`); the sentence title stays in the provider session and the `-pw` workspace name.
2. Workers and adversary rounds are sub-agent tabs in the lead's workspace. 3. The store is a new
`~/.local/state/ade/names.sqlite` (not session-finder's index). 4. An unexplained rename counts as `user`, so `--auto`
never touches it. 5. A launchd job `com.djbclark.ade-names` (60 s Paseo poll, 5 min herdr reconcile) plus a herdr
plugin, plist in this repo. 6. `-p` is retired for Paseo workspaces (`-pw` only). 7. Closing a top-level Paseo agent tab
archives the agent; a Paseo mode for `herdr-tidy` is a later slice. 8. Names are kept forever, with `ade-names forget`.
9. Autorename stays in-session; the poller only observes. 10. The rule lives in the autorename skill,
`workspace-layout.md` and the repo AGENTS.md row, no home item. The build is the report's slices 1-8 (docs, `paseo_tab_name`
and the `--auto` agent-name guard, `bin/ade-names`, herdr plugin and launchd, consumers, session-finder, backup entry,
upstream issue draft), Sonnet 5.5 workers; slice 8 and 1 may go first and slice 2 alone fixes the `--auto` overwrite bug.

1. **Tab usage convention**: what lives in a tab, one agent per tab or not, how the skills create, reuse and close tabs.
2. **Naming rule**: lowercase, hyphenated, ending `-pt`, about 17 visible characters including the suffix; goes into
   the `autorename` suffix table (`-t` herdr tab, `-p` herdr pane, `-pw` Paseo workspace) and `workspace-layout.md`.
3. **`autorename` for Paseo tabs**, never overwriting a name the user set.
4. **Name-history store** for herdr workspaces/tabs/panes and Paseo workspaces/tabs: every name seen or set, who set it,
   when and the stable id, so a lookup by any historical name or id finds the object and its session after a UI
   rename; SQLite is the candidate, the design slice decides where and how it is observed.
5. **Questions for djbclark** come out of the design report (its section 6): relay them as they surface.

## Make full use of the podman, kev, laya and hyades-docker microVMs (djbclark, direct, 2026-10-23)

djbclark, 2026-10-23: "At an appropriate point, make sure that we make full use of the podman, kev and laya
/hyades-docker microvms in our ade and work." Queued; **start after PRs
[27](https://github.com/djbclark/djbclark-ade/pull/27) and [31](https://github.com/djbclark/djbclark-ade/pull/31)
merge** (both open 2026-10-23). Nothing is built.

1. **Inventory first** (one read-only `scout` slice; the report goes into a new `docs/microvms.md`). What each gives
   today, from the repo's own docs (2026-10-23, to verify): (a) **podman**: rootless podman is the engine of the
   forgejo.mit.edu runner (`skills/forgejo-ci/SKILL.md`: one libkrun microVM per job, `capacity = 4`, stock labels
   have git/node/python3/podman/go but no gcc, JDK or Android SDK) and the push path of `hyades-docker`'s
   `hyades-registry`; whether this Mac runs podman as a local sandbox for untrusted code and tests is unchecked.
   (b) **hyades-docker**: OCI images run as libkrun microVMs at `NAME.sipb.cloud` on SIPB Hyades (`docs/skills.md`;
   `scripts/hyades` is the SSH console). (c) **kev and laya**: djbclark's two Jev-like System One microVMs
   (Kev-0.8B at djbclark-kev.sipb.cloud, Laya at djbclark-laya.sipb.cloud), the yes/no/choice/score judges of the
   `jevlike` skill (`JEVLIKE_API_KEY` in sudo-secretspec); `docs/jev.md` says `bin/jev` is still in shadow mode:
   check whether kev and laya are what its sites would call. Record per resource: what it can run, limits (disk,
   missing toolchains, the TSI loopback bug and its shim), cost or quota, who can reach it, key, restart behaviour.
2. **Then route to them instead of the Mac**: heavy tests and builds (`forgejo-ci` as the CI lane; `load-watch ci
   decide DIR ci "CI CMD"` records a repo as CI-first and `bg` reads it), adversary probes that run code (the 2026-10-20
   round-18 probe that ran the backup tool against the real HOME is the case a disposable microVM prevents), and
   `--perm deny` reviews of untrusted repos (see the crush and `acp-run --perm deny` entries below); kev and laya as
   `jevlike` gates (`decide: yes|no|escalate`) at the sites `docs/jev.md` lists. Cheapest next step: item 1, then one
   `ci decide` per repo that already has a workflow. Blockers: PRs 27 and 31; the Hyades runner is shared (never fan out
   past its capacity); the `jevlike` key is only djbclark's; agents never post on `SIPB/*` (home rule 35).
3. **Restated by djbclark, 2026-10-23** (a duplicate of item 2's kev/laya half, folded in here): "add using the
   Jev-like hyades things we set up to djbclark-ade process", the two servers being Kev and Laya (`jevlike` skill;
   source `~/src/jev-like-hyades`). Process sites to check against `docs/jev.md`'s list: `bin/jev`'s shadow sites
   (`pick-seat`, `stuck-check`, `merge-gate`), and whether a kev/laya `merge_gate` can stand in for the paid plan in
   "Buy a Jev plan before the factory's merge gate goes live (SF-Q10)" below.

## Orchestration rules from the load watcher (djbclark via load-watch agent 96a17744, 2026-10-23)

1. **Name a workspace by its human name AND its id.** Add to `docs/orchestration-practices.md` (and the brief template
   in `skills/bigteam/SKILL.md`): wherever a brief, relay, report or message names a Paseo workspace, give the name the
   GUI shows (the `-p`/`-pw` name, e.g. `paseo-workspace-navigation-plugins-pw`) and its id (`wks_5363dce7237adb53`);
   for an agent give the agent id too. A GUI rename (see "Paseo workspace names after a handoff") makes a name alone
   unreliable, an id alone unreadable. One small Sonnet doc slice.
2. **Find an owner or peer session with `/session-finder`, never by messaging to guess; make `fleet.py` and `paseo ls`
   print workspace name + id.** Today: `fleet.py show`, `session-find.py`, and the Paseo state file
   `~/.paseo/agents/<cwd-slug>/<agent-id>.json` whose `workspaceId` maps to `paseo workspace ls`. Example: the
   `relay.py` owner agent 24f5b849-6835-464d-925e-35e67f911657 is in `paseo-workspace-navigation-plugins-pw`
   (`wks_5363dce7237adb53`). Better architecture: `fleet.py` joins `paseo workspace ls --json` so a Paseo row shows
   workspace name + id and nobody reads the state file; that is step (4) of "Paseo workspace names after a handoff",
   one slice, not two. `paseo ls` printing the workspace is Paseo's to change: draft it in `docs/upstream-issues.md`
   if `fleet.py` cannot cover it. Reply by relay to 96a17744 when done.
3. **Load-watch folded into planning.** In the tree 2026-10-23: `load-watch admit` has the compressor-churn gate
   (`--max-mem-churn`, default 60000 pages/s, calibrated from 215 samples), `load-watch sample` warns on sustained
   churn, `bg` asks `admit` (exit 75 = hold, fails open), `acp-dispatch` holds on exit 75, `skills/loadwatch/SKILL.md`
   says so. **Not done**: the planning rules themselves in `docs/orchestration-practices.md` and every slice brief
   (`skills/bigteam/SKILL.md`): check `load-watch admit --json` before a large fan-out; builds and tests only through
   `bg` or CI, never `BG_LOAD_WAIT=0`; dispatch only through `acp-dispatch`; **one test run at a time, both Pythons
   sequential, never parallel**; no new local pytest or dispatch while load per core >= 1.5 (`uptime`). Why: at
   2026-10-23 13:54Z load was 42-62 on 8 cores with swap at 90% from three concurrent local pytest runs (two from the
   fleet-governor slice on both Pythons at once, one from quota-guard) plus three omp dispatches; nothing was killed.
   Each of these ships its CHANGELOG line with its own PR (review rule 10).
4. **Push on completion, as code** (djbclark, via the load watcher). Every delegation made by `relay.py`,
   `acp-dispatch` or `launch` records the requester's Paseo agent id; when a Paseo agent's turn ends (status leaves
   `running`) a hook or the dispatch footer sends "done: <title>, status, report path" to the recorded requester through
   `relay.py`; for dispatched slices `acp-dispatch`'s waiter is extended the same way. Why: three waiters per PR head were
   two thirds of one lead's notification turns (first section below, item 3). Until it ships: a one-shot status waiter
   script, never a recurring prompt (home rule 13). Open design points: where the requester id lives (a record field),
   a requester that is itself a dispatched slice, the relay refusal gate for non-Claude hosts (relay item 10 below),
   and that each push costs the requester one turn. Reply by relay to 96a17744 when scoped.

## PR 31 (`claude-fleet-governor`) and the 2026-10-23 quota emergency

PR [31](https://github.com/djbclark/djbclark-ade/pull/31), open 2026-10-23 at 8b8af99 (adversary gov-10 APPROVE).
Why it exists: at 12:58Z the Claude 5-hour window was 70% used (~26%/h, projected out ~14:05Z against a reset at
14:59:59Z); djbclark: "make sure we don't ever hit claude quota before a reset ... cover all workspaces and agent
sessions". The six Paseo Claude agents were switched Opus to Sonnet 5.5 in place through the daemon's
`set_agent_model_request` (`~/.local/state/ade/paseo-set-model.mjs`, now `bin/paseo-set-model.mjs` in the PR; originals
in `~/.local/state/ade/fleet-governor.json`); 6ebd939 (the orchestrator) followed at 13:25Z.

1. **Restore the seven downshifted agents after the reset** unless djbclark prefers Sonnet (Fable stays off): 955e2b2,
   24f5b84, 6f79643, b735ee2, 607a30b, ae2549c to `claude-opus-5`; 6ebd939 to `claude-opus-5-5`, with
   `paseo-set-model.mjs <id> <original>` from `fleet-governor.json` while the governor is not live; after PR 31 merges,
   `--install` plus the printed `launchctl bootstrap` line, and its `plan_moves` does it. The reset was 14:59:59Z;
   whether the restore ran is not recorded: read `fleet-governor.json` first.
2. **Gate for Agent-tool sub-agents** (after PR 29, merged). A model change by daemon RPC never reaches them: on
   2026-10-23 two Opus adversary sub-agents (5.1M and 3.0M cache-read tokens in 30 minutes) ran on Opus while their
   parents were on Sonnet. Fix: the PreToolUse `Agent|Task` gate `claude/hooks/frontier_agent_gate.py` reads
   `quota-guard.json` and at `watch` or worse returns `updatedInput.model = "sonnet"` for opus/fable sub-agents (or
   denies with the omp command). Pairs with `CLAUDE_CODE_SUBAGENT_MODEL` (PR 29 and 30 follow-ups, item 2). One small PR.
3. **Claude Code outside Paseo** (herdr or Orca panes, plain `claude`) is out of `setModel`'s reach. `ps` showed no such
   `claude` on 2026-10-23 (every parent is the Paseo daemon), so today: type `/model sonnet` into an idle pane or launch
   on Sonnet (`~/.claude/settings.json` `model` is already `sonnet`); the hook advice of PR 29 covers the rest.
4. **PR 31 findings left open on purpose** (adversary gov-10 and rounds 4 and 8): (a) LOW: one shared window fresh and
   the other stale (45-90 min): the level comes from partial evidence and `plan_moves` restores agents; treat a dropped
   shared window as stale (episode state `stale`, one ping) or plan no restore. (b) LOW: the window-stale exit 10
   writes no state and never pings (the newest-snapshot-stale path does). (c) LOW: the `hours = resets - cur_at` mutant
   and the exact 45:00 stale boundary are unpinned by tests. (d) LOW: `load_snapshots` raises OverflowError on a
   parseable year-1 `collected_at` (`claude-fleet-governor:258`) before any side effect (exit 12, nothing changed).
   (e) INFO: `bin/paseo-set-model.mjs` `client.close()` can hang and turn a successful setModel into exit 13/124: race
   it with a 3 s timer. (f) INFO: a record whose `resets_at` is None or unparseable is kept silently forever; model and
   agent ids rejected by the fullmatch regexes fail silently; `set` from state reaches stdout/stderr only.

## Follow-ups from PRs 29 and 30 and the 2026-10-20 exhaustion post-mortem (2026-10-23)

Context: on 2026-10-20 the Claude weekly window hit 100% 2.6 days early; the lead ran on Fable, the adversary on
Opus, and nothing acted on aiuse's `conserve` alert. PR 29 (`bin/claude-quota-guard`, lead rule Opus 5.5 high)
and PR 30 (`self-slash --finish --successor`) shipped the recommendations; the post-mortem's other finding was
that the lead's transcript held 579 background-notification turns against 49 operator prompts, each re-reading
a 150-200k context: the notification-per-turn multiplier, not the model, was the volume.

1. **DONE 2026-10-23** (`[lead] pipeline_effort = "medium"`, `route_agent.py` default/validation, `policy --md` line, SKILL.md item 12, tests; PR [33](https://github.com/djbclark/djbclark-ade/pull/33), merged d06d48c; open LOW from its adversary round 2: no test pins that `xhigh` and `max` are accepted). **Effort as a lever** (Anthropic: "tuning effort is often a better lever than switching models"; Opus 5.5
   defaults to medium): add to the routing policy that a pipeline-driving lead (PR loops, waiters, merges) runs
   Sonnet 5.5 at **medium**, high only for judgment turns; effort changes on 5.5/Fable 5.1 keep the prompt cache.
   One Sonnet `code` slice: `skills/model-routing/SKILL.md` item 12, `config/routing.toml` `[lead]`
   `pipeline_effort`, `route_agent.py policy --md`, a test.
2. **DONE 2026-10-23 (djbclark approved; `bin/claude-settings-env` DEFAULTS (add-only) plus the template line, applied live by running it):** **`CLAUDE_CODE_SUBAGENT_MODEL=sonnet`** in `~/.claude/settings.json` `env` (via `agents/claude/settings.json.tmpl`):
   an Agent-tool sub-agent with no `model:` inherits the lead's model, so a Fable or Opus lead silently spawns
   Fable or Opus sub-agents; `claude/agents/adversary.md` keeps its explicit `model: opus`. One small PR.
3. **One aggregating waiter per PR**: promote `~/.local/state/bigteam/adhoc-2026-10-23/pr-wait.sh` (waits for CI
   checks and Codex's `codex-review-state:v1` marker for the exact head, then lists the findings created after
   the request as JSON) to `bin/pr-wait` with a test and a line in `skills/bigteam/SKILL.md`: three waiters per head
   (CI, Codex, adversary) were two thirds of the notification turns. Never re-arm a waiter that is already
   running (the load watcher found eight duplicates on 2026-10-20).
   Waiter lessons from PR 27 (2026-10-23, fold into `bin/pr-wait`): treat Codex's `code_review.status: failed` as
   terminal, not only `completed` (pass 35 failed on Codex's side with no inline comment; re-request at the next head);
   give a pass stuck in `running` a timeout that reports "stuck" (pass 40 sat over 60 minutes and the waiter timed out
   silently); `gh api --jq` takes no `--arg` (the findings query failed with "accepts 1 arg(s), received 4"), so fetch
   with `gh api ... --paginate > f.json`, then `jq -s --arg t ... f.json`; the adversary appends its own `## Round NN`
   section to its report file, so the lead must not append a second copy (rounds 43 and 44 were deduplicated).
   **Done 2026-10-23** (`bin/pr-wait`, `tests/test_pr_wait.py`, `skills/bigteam/SKILL.md`): one waiter per repo + PR + head
   (CI checks of the exact head plus the Codex marker; `completed` and `failed` terminal; stuck bound `--codex-stuck`,
   default 45 min, exit 3; `gh` failures retried, exit 6 if still failing at the deadline; paginated output parsed as
   concatenated pages; findings by `original_commit_id` / review `commit_id` of the head and the Codex bot author, no time window; markers believed only from the Codex app), a lock refusing a duplicate (exit 4). Not done:
   the adversary-report round dedup lesson is a lead habit, not a waiter feature.
   **Open LOW from PR 34's adversary (2026-10-24, head a15ecb7; D1 and D2 fixed in the PR, D3 and D4 left):**
   D3 stale summary: `finish()` is the only writer, and the summary carries no run id or start time. Scenario: run A on head H
   ends `merge_ready: true`; a re-requested Codex review or an unresolved thread makes run B start on H; a third agent gets exit 4
   ("read its files"), reads `PREFIX-summary.json` at once and sees run A's `merge_ready: true`. A crash gives exit 1 plus the
   previous summary. Fix: once the lock is held, write `PREFIX-summary.json` atomically as `{"result":"running","pid":...,
   "started_at":...}` (or delete the old `PREFIX-*` files), put `pid` and `started_at` in the final summary too, and make the
   exit-4 message say "wait for pid N to exit, then read". D4 macOS identity ([INFERENCE], not reproduced): the lock identity is
   the text of `ps -o lstart=`, a local-time rendering, so the docstring's "stored absolutely" holds only for the kernel value.
   Scenario: the Mac's automatic timezone changes while a waiter runs; a second `pr-wait` on the same head computes a different
   lstart string for the live holder, `lock_live` returns False, it takes over, and two waiters run on one head. Fix: read
   `pbi_start_tvsec`/`pbi_start_tvusec` through libproc `proc_pidinfo(PROC_PIDTBSDINFO)` (ctypes) or `sysctl kern.proc.pid.<pid>`;
   or keep lstart, also store the epoch, and compare within +-1 s after parsing both in the same zone.
4. **PR 29 queued findings** (hypothetical aiuse payload shapes; `bin/claude-quota-guard`): (a) a windowless live
   row bound by the 5-hour window leaves the snapshot's weekly unjudged (adversary round 7); (b) **DONE 2026-10-23** (Codex 4361062506;
   `decide` now builds a summary window for every windowless row beside the detailed ones, then the Fable supplement; tests `test_s2_*`) a detailed
   default row plus a summary-only Fable row: synthesize a window for every summary-only row (Codex pass 6);
   (c) **DONE 2026-10-23** (Codex 4361062518; only the snapshot row holding the `_lowest()` Fable window ages the decision, both paths; tests `test_s1_*`)
   several snapshot accounts with Fable windows: age only the account `_lowest()` picked (Codex pass 6);
   (d) the `p3` concurrency test's 0.2 s lock budget can flake under load, and the hook's worst case is 0.2 s
   against the docstring's "well under 100 ms" (round 10); (e) the hook's unreadable line (round 9) and the
   `live_only` `fed` rule were tightened in fix 8; re-check after (b) (2026-10-23: (b) landed, `fed` covers both paths).
   (f) **PR 36 adversary round 3, queued 2026-10-24** (LOW, hypothetical shapes; head e10c705): (f1) a summary row's
   reset and pace come only from the snapshot, never from the live detailed twin beside it
   (`bin/claude-quota-guard:427-428`, `display = snap_windows` is the only twin source passed to `_summary_window`).
   Input: a detailed default row (age 10, weekly 80% reset 2026-10-28, 5-hour 90%), a summary row
   (`headroom_percent` 50, `binding_window` "Claude Code weekly", age 10, no `available_at`), and a snapshot account at
   age 18000 holding weekly 70% reset 2026-10-28: `rows_age_s` is 18000 (stale, watch, collector-down ping) although a
   10 s old row has the same reset; with no snapshot and aiuse rc 3 `weekly_resets_at` and `resets_at` are None
   (the advice loses its reset phrase), which the pre-PR mixed shape reported. Suggested fix:
   `_summary_window(r, claude_windows(rows) or display)`, or try the live detailed twin first and fall back to the
   snapshot, so only a snapshot twin that was really needed ages the decision. (f2) a summary-only Fable row's
   `headroom_percent` is in shared-weekly units in aiuse 3.10.0 (`analysis/selfdescribe.py:827-854`:
   `effective_headroom(binding)`, scaled by `max_share_of_parent_percent`, `headroom_basis: "shared_weekly"`; live
   2026-10-24 20:03Z: row headroom 40.0 while the Fable window shows `remaining_percent` 80.0, share 50), but
   `_summary_window` (:360-361) relabels any `pool_family: "fable"` row's headroom as the Fable cap's remaining.
   Input: a detailed default row plus a summary-only Fable row with headroom 12.5 and basis shared_weekly (real Fable
   cap 25% left): `fable_left` 12.5, level `watch`; the true value is above `watch_fable` 15, so `ok`; a Fable row
   bound by the shared weekly (headroom 20) gives `fable_left` 20 while the real cap is 80. Errors are on the cautious
   side and real aiuse sends `windows[]` today; the live-only path had this before the PR. Suggested fix: when
   `headroom_basis == "shared_weekly"` or `binding_window` is not the Fable label, classify by `binding_window` and do
   not force the Fable label (or document in the docstring that the summary Fable value is in shared-weekly units).
5. **PR 30 queued findings** (`bin/self-slash`, adversary round 3): `SELF_SLASH_SUCCESSOR_SETTLE` accepts a leading
   zero (`08`/`09`, an octal arithmetic error after `paseo run`) and has no upper bound (cap 600); workspace proof
   compares realpaths case-sensitively, so on APFS a case-variant sibling row can let an empty local workspace be
   archived. Also unverified live until the first real successor run: the `--json` row shapes of `workspace ls`,
   `terminal ls`, `ls` (every parse failure keeps the workspace) and `paseo run /baton` as a first prompt.
   **Update 2026-10-23:** the first live successor run's three bugs are fixed on master in 184b14d; the two round-3
   LOWs above still stand. PR [35](https://github.com/djbclark/djbclark-ade/pull/35) (open) carries 184b14d's review
   LOWs and the bash 3.2 empty-array fix that the macOS CI job has failed on since 184b14d.
6. **Paseo in-place model change**: `docs/upstream-issues.md` entry 17 drafts `paseo agent model <id> <model>`;
   on 2026-10-23 the rework-p lead switched every running Paseo Claude agent in place through the daemon's
   `set_agent_model_request` (`~/.local/state/ade/paseo-set-model.mjs`), which the entry should cite as the
   working RPC; the `claude-fleet-governor` branch (peer 6ebd939) builds the enforcing actor on top of the guard's
   state file.
   **Update 2026-10-23:** the governor is now PR [31](https://github.com/djbclark/djbclark-ade/pull/31) (open); when it
   merges, cite `bin/paseo-set-model.mjs` in entry 17 as the working RPC. Its restore, sub-agent gate and open findings
   are in "PR 31 (`claude-fleet-governor`) and the 2026-10-23 quota emergency" above.
7. **Live `~/.claude/settings.json` lacks the `context_size_nudge.py` registration** that `agents/claude/settings.json.tmpl`
   carries (found by the quota-guard slice; possibly lost in the 2026-10-20 graft restore): apply the template or
   add both UserPromptSubmit entries (`context_size_nudge.py`, `quota_nudge.py`) by hand, then
   `bin/claude-quota-guard --install` and the printed `launchctl bootstrap` line (operator items of PR 29).
   **Update 2026-10-23:** the live settings do carry the registration; the hook failed because
   `claude/hooks/context_size_nudge.py` had been 100644 since 836b306 (2026-10-19): `hook-deadline` exec'd it and
   exited 127. d618809 restored +x on it and 11 other shebang scripts; it runs again (rc 0).
8. **Unresolved Codex findings on merged PRs** (2026-10-23): head-only finding selection missed every finding Codex
   left on an earlier head (PR 32 nearly merged past a P1 that way). A GraphQL `reviewThreads` survey found about 50
   unresolved, not-outdated Codex threads on merged PRs 15-30. A read-only triage slice is checking each against
   master (`~/.local/state/bigteam/rework2-codex-triage/codex-triage-report.md`); `bin/pr-wait` (PR
   [34](https://github.com/djbclark/djbclark-ade/pull/34)) gains `merge_ready` and open earlier-head findings, and
   AGENTS.md rule 9 is corrected in the same PR.
9. **Accepted LOWs and declined findings from the 2026-10-23 rework-2 PRs** (residual, one small PR each when picked up):
   1. PR 38 adversary round 1 LOWs (acp-dispatch rearm hint): L1 "up to 2.0 h" rounds down for waits of 7201-7379 s (round up); L2 compare wait_timeout with TOOL_TIMEOUT_MAX_S minus two 60 s passes so boundary waits get the re-arm text; L3 usage header (bin/acp-dispatch:186-188) should say the hint always names timeout 7200000 and adds the re-arm rule for long or unlimited waits. Report: ~/.local/state/bigteam/rework2-codex-triage/adv-codex-fix-c-1-report.md
   2. PR 37 adversary round 1 LOWs (skill-everywhere): in-tree link amplification in canonical mode; check-vs-cp TOCTOU via an outside path component; the inherited SKILL_EVERYWHERE_NO_COPY drop in ade-update:313 is untested. Report: ~/.local/state/bigteam/rework2-codex-triage/adv-codex-fix-b-1-report.md
   3. PR 32 adversary round 6 LOW: tests/test_bin_modes.py docstring and CHANGELOG say "outside tests/", while the code exempts any tests/ directory at any depth.
   4. PR 33 adversary round 2 LOW: no test pins that `xhigh` and `max` are accepted as [lead] effort values.
   5. Declined from the 2026-10-23 Codex triage (threads left open): PR 25 4323896253 (relay.py Claude-derived custom provider ids; refuses safely) and PR 22 4323297397 (acp-dispatch footer slot wildcard; the stripping also cleans a copied footer, which helped on 2026-10-23).

## Follow-ups from the 2026-10-20 reviews

1. **`bin/firecrawl-router` serve-only form binds any `--listen` with no token** (adversary, threat-model
   review 2026-10-20: `--open` refuses a non-loopback address, serve-only does not). Make serve-only refuse a
   non-loopback `--listen` the same way; one small PR with a test.
   **Done 2026-10-20** (PR 14): both tokenless forms refuse a non-loopback `--listen` (exit 2) and `serve()`
   checks the address it actually bound before it accepts a request. Carried from that review (adversary
   INFO, non-blocking): (a) the tokenless loopback handler does not check the `Host` header, so a page in a
   local browser could reach it by DNS rebinding; add a `Host` allow-list (`127.0.0.1`, `localhost`, the bound
   port); (b) the bearer compare at the handler uses `!=`; use `hmac.compare_digest`. One small PR for both.
   **Done 2026-10-22** (commit on master, bin/firecrawl-router + tests): the tokenless handler
   refuses any `Host` that is not a loopback name with the bound port (403), and the bearer compare uses
   `hmac.compare_digest`.
2. **Claude API credits from the Admin API, not by hand** (djbclark, 2026-10-20): the Admin API has no balance
   endpoint, but `/v1/organizations/cost_report` gives spend; remaining promo = grant ($200, 2026-10-13, expires
   2026-11-08) minus cost since the grant. Plan: an `aiuse` collector behind `ANTHROPIC_ADMIN_KEY` in
   `sudo-secretspec` (djbclark creates the key in the console, Organization settings > Admin keys), grant
   parameters stay in the `set-credits` override, a launchd/`fleet-watch` job refreshes it (never a model prompt,
   home rule 13). Key stored as `ANTHROPIC_ADMIN_KEY` 2026-10-20 (runtime declaration, optional). **Collector merged
   2026-10-20** (aiuse PRs 38 and 40, main 5b0b9f9: `aiuse refresh-credits omp`, hourly launchd template
   `packaging/launchd/com.djbclark.aiuse-credits-refresh.plist`); **not live on this Mac until aiuse 3.8.0 is
   released** (`just release 3.8.0` in `~/src/aiuse`, publishes PyPI and Homebrew; this Mac runs the Homebrew 3.7.2)
   and the launchd job is loaded per the aiuse README. **Done 2026-10-20**: aiuse 3.8.0 released (PyPI, GitHub release, Homebrew tap; this Mac upgraded) and `com.djbclark.aiuse-credits-refresh` bootstrapped, hourly, run-at-load. Codex's "Path to threat model file" set to `docs/threat-model.md` the same day (djbclark, GUI). The figure is a lower bound (it counts all org spend).
   Also (adversary on the aiuse branch, finding 5, 2026-10-20): `bin/route_agent.py` reads aiuse's `latest.json`
   directly, so it never sees the operator credits override; make it read `aiuse --available --json` (or the
   same resolver aiuse uses) so routing and the quota gate agree. Small djbclark-ade PR after the aiuse branch merges.
   **Done 2026-10-20, PR 12 merged (72252da)**: `route_agent.py` runs `aiuse --available --json` (available-row
   contract fields; `windows[]` only tightens; `excluded[]` and absent pools read 0 on a fresh payload), falls back
   to the snapshot file with a stderr log and `quota_source` in the output; `ROUTE_AGENT_AIUSE_JSON` feeds canned
   output, `ROUTE_AGENT_AIUSE=off` pins the file read (set by `tests/conftest.py`). Not done: `acp-dispatch`'s `aiuse_reset_time` (bin/acp-dispatch ~2210)
   still reads `latest.json` directly for a refusal's reset time; the quota gate itself (`load_snapshot()`) moved.

3. **Load gate follow-ups** (adversary final pass on PR 7, 2026-10-20, informational): (a) on `--detach
   --no-wait` a missing `ACP_DISPATCH_LOAD_WATCH` is only visible in the runner log and the record; warn at
   dispatch and have `check` mention `load_gate.error`; (b) resolving symlinks stores a Homebrew override as its
   versioned Cellar path, so a `brew upgrade` during the wait makes the runner start without the gate (store the
   unresolved absolute path, resolve at run time); (c) exit 0 is trusted over the JSON `status`, so a wrapper that
   exits 0 while printing "hot" is admitted; (d) the deferred deadline covers `load_wait` plus the 180 s subprocess
   grace (abccaae) but not the older overload hold (up to 900 s at 4x cores or critical memory pressure), which
   runs after the gate on every detached path, so in that rare case the waiter returns 124 while the runner
   still holds. Deferred by design from the same review: a machine-wide admission
   token (N3) and recording `ACP_DISPATCH_LOAD_WATCH`/`ACP_DISPATCH_STATE` for the runner beyond the cap (N5/I1).
4. **`cursor-cloud` place in `acp-dispatch`, not done in the first slice** (adversary APPROVE on 270a7f5,
   2026-10-20, shipped on condition that this entry exists): (a) no reboot auto-resume for cloud records: the
   login sweep skips them, the SIGTERM report names the agent and the `acp-dispatch resume RECORD` to run;
   (b) no cancel on timeout or ERROR: Cursor's API has `POST /v1/agents/{id}/runs/{runId}/cancel`, only
   `bin/cursor-cloud` lacks a `cancel` subcommand; add it and call it from the poller, until then a timed-out run
   spends until Cursor ends it; (c) the 24 h poll cap (`CLOUD_MAX_SECONDS`) is read, not unit-tested; (d) nothing
   ran against the live API: watch the first live slice and record its in-progress run status and whether
   `git.branches[].branch` is filled in. Lows from the same review: (R1) the result-text branch step matches
   `.cursor/...` paths (`BRANCH: cursor/rules/foo.mdc`) and never checks the name against origin; keep only names
   in `git ls-remote` and tighten the regex to `(?<![./\w])cursor/`; (R2) `CLOUD_ACTIVE` is a guessed status list,
   so a healthy run longer than 20 polls can end as ERROR; treat any non-terminal status as active, bounded by
   the deadline, and record the raw status; (R3, info) the ls-remote fallback runs `git fetch` in the operator's
   checkout from the poller and from `check`/`reap`. Added at 9319d57 (adversary APPROVE, 2026-10-20): (e) the
   overlap scan that refuses to attribute a branch while another cloud slice on the same repo is in flight sees
   only this machine's STATE_ROOT; (S1) `CLOUD_MAX_SECONDS` is a default, not a ceiling: `extend`, a huge
   `--timeout` or a hand-edited `timeout` pushes the re-read deadline without limit, and a non-numeric value
   crashes the poller (clamp to the cap, `try/except` the conversion); (S2) a record whose dispatcher died during
   the launch call (status running, `cloud_agent_id` null, no pid) is never reaped and overlaps every later slice
   on that repo, and a peer with a non-numeric `finished` raises in `cloud_overlapping` (skip peers without
   `cloud_agent_id`, ignore peers older than timeout + cap, guard the conversions); (S3) a result-text branch
   confirmed on origin may predate the launch (also require the head to differ from `cloud_heads_before`).
   S1-S3 fixed at ee66114 (adversary APPROVE, 2026-10-20); info left: (T1) a hand-edited future `launched_at`
   still moves the deadline base; (T2) on Linux a cloud record whose background poller died before writing its
   pid is never reaped. From the 8f881ee pass (Codex P1 fixed: an unfinished cloud record is refused unless
   `--force`): (U1) for a record left by a crash during the launch call (no `cloud_agent_id`) the refusal
   says "resume", but resume dies with "never launched an agent", so only `--force` works; point at
   `cursor-cloud list` and `--force` when there is no agent id; (U2) `--force` drops the first agent's id from
   the record (carry it as `prior_cloud_agent_ids`); (U3) no lock between the same-name check and the write,
   so two simultaneous dispatches can still launch two agents (the race exists for local slices too).
5. **Done 2026-10-20** (PR 15). Endpoint variables could send keys anywhere (adversary and Codex, threat-model review 2026-10-20):
   `CURSOR_CLOUD_API` in `bin/cursor-cloud`; `FIRECRAWL_SELFHOST_URL`, `FIRECRAWL_FALLBACK_URL`,
   `FIRECRAWL_ROUTER_SIPB_BASE` and `FIRECRAWL_ROUTER_LITELLM_BASE` in `bin/firecrawl-router`. Require https
   (Cursor: https://api.cursor.com only) or loopback unless a test flag is set, and stop the Authorization header
   following a redirect: urllib copies every header onto the redirected request, to any host; `bin/failover.py`
   already avoids this with `_NoRedirect` and `add_unredirected_header`. One PR with tests.
   Carried (adversary round 2 on PR 15, both LOW): (a) `reexec_env()` in `bin/cursor-cloud` is a deny-list; it
   does not drop `DYLD_INSERT_LIBRARIES`, `LD_PRELOAD` or `OPENSSL_*`; (b) `build_opener` in both tools still
   installs urllib's default `ProxyHandler`, so an `*_proxy` variable set after the re-exec would still route the
   call; pass an empty `ProxyHandler({})` explicitly.

6. **Done 2026-10-20** (PR 17). Three `tests/test_route_agent.py` tests failed on a host where omp is ready (pre-existing on master,
   confirmed 2026-10-20 at d6c27da): `TestDiscovery::test_measured_idle_capacity_beats_unmeasured`,
   `TestPlanWave::test_no_room_comes_back_as_none_not_an_error`,
   `TestQualityBand::test_the_2026_10_18_case_queues_code_instead_of_routing_far_down`. They pass with
   `ROUTE_AGENT_OMP_READY=0`, so CI (no omp login) is green while a local `bg` run is red. Fix: pin the probe in
   `tests/conftest.py` (`ROUTE_AGENT_OMP_READY` is `0` unless the shell sets `0` or `1`) and give the omp case its own test.
   Carried (adversary, 2026-10-20): (a) with omp ready and no quota reading, an unmeasured omp outranks a measured
   pool in all three scenarios (`TestOmpReadyRoster` names the case as left out); (b) `_merge_pool` in
   `bin/route_agent.py` lets a stale `None` reading overwrite a measured one (adversary LOW on PR 13).
7. **Carried from the PR 12 reviews** (adversary rounds 1-6 and Codex, 2026-10-20, none blocking): (a) the
   available-row fields `binding_window`, `available_at` and `requires_operator_approval` are stored on the pool
   entry but nothing in `route()`/`plan()` reads them (the live omp row says `requires_operator_approval: true`;
   omp is gated by its ready probe and the credits ruling instead); (b) the 30 s aiuse memo's first, spawning
   serve returns the stored object rather than a copy (no caller mutates it); (c) `excluded: true` is set on the
   whole entry when only the `fable` sublimit was excluded; (d) `acp-dispatch`'s `aiuse_reset_time` still reads
   `latest.json` directly (item 2); (e) **lead ruling to confirm with djbclark**: the aiuse path reports Fable as the
   row's least-applicable headroom (22 live where the file read gave the sublimit window's own 44), so
   `FABLE_MIN_LEFT=10` now switches to Opus at roughly 20 % of the cap rather than 10 %; kept because it is the
   contract value and the conservative one. **Ruled 2026-10-20 (djbclark): keep 10.** It is aiuse's contract unit (the same
   `headroom_percent` every pool's threshold uses) and the only option that protects the shared weekly as well as
   the sublimit; Opus takes over at 20 % of the Fable sublimit or 10 % of the shared weekly, whichever first.
8. **Delete the credential vault after 2026-11-19** (owner: djbclark; adversary round 8 on PR 16, 2026-10-20):
   `~/.local/state/ade/credential-bak/` (0700; 13 `.bak` key copies moved there from the agent config dirs on
   2026-10-20, manifest `MANIFEST-2026-10-20.txt`, see docs/ade-everywhere-inventory-2026-10-20-stores.md 5.5).
   Nothing reads it; once the 30-day keep lapses, `rm -r` it and drop this item.
9. **Phase 0 item 4.4: track the four untracked config files as templates** (proposal §8 item 1, djbclark
   2026-10-20). **Done 2026-10-20 (PR #23):** `agents/{claude,codex,opencode,hermes}/` hold
   `settings.json.tmpl`, `config.toml.tmpl`, `opencode.json.tmpl` and `config.yaml.tmpl` (secrets as
   `{{ secret "NAME" }}`, home paths as `{{ .home }}`, host and account ids as `{{ .field }}`, all listed in
   `agents/README.md`); `bin/ade-template-check` scans them for credentials, renders and parses them, and with
   `--diff` names the keys that differ from the live file; `tests/test_ade_template_check.py` runs in CI. Open
   for Phase 1: declare the `TODO_*` secret names in `secrets/secretspec.toml`, give each field a place in
   `operator.toml` or `machines/<host>.toml`, and turn the Codex and Claude templates into `modify_` merges.
   Scanner LOWs from the adversary's round 3 on PR #23 (all measured, none blocking): the scheme-word group
   in `bin/ade-template-check` can take a short letter-initial key for the scheme (fix: letters-only scheme
   word or a closed list); the `]` terminator lets a tail after a placeholder or env ref through (accept
   `]` only when it closes the value); `_FLAG` misses `--key` and `--access-key` (end the rule with
   `key`); `headers: - name: X / value: <key>` lists: the nearest key is `value`, so the parsed-scalar pass should
   use the sibling `name` (adversary round 6, R6-3). Operator items: the public templates publish Hermes's
   approvals, Claude's allowlist and Codex's trust list.
10. **`session-finder/relay.py` Paseo channel, carried from PR [25](https://github.com/djbclark/djbclark-ade/pull/25)**
    (Codex, 2026-10-20, non-blocking): (a) a Paseo agent absent from `fleet.sessions()` is stored with its provider id
    literally, so a custom provider such as `my-claude` that `extends: "claude"` is refused by `refusal()` unless
    `--idle` is given; resolve the custom id to its base through Paseo's provider config before the Claude check. (b) a
    nested session launched from a Paseo agent's shell inherits `PASEO_AGENT_ID`, so the sender tag is omitted and the
    recipient sees the outer agent as the sender; verify the caller is the hosted agent (the agent record's cwd and
    pid) before dropping the tag.

## Paseo workspace names after a handoff (djbclark, 2026-10-20)

djbclark, 2026-10-20: "we should change the new automatic handoff -> new/clear -> baton system so that Paseo
workspace windows get an informative, short name (only the first few words show) so they are easy to identify
in Workspaces. Currently they all get named 'Resume session from baton handoff'." Paseo titles an agent from
its first prompt, and after `self-slash "/new"` (PR #19) that prompt is the bare `/baton` the `--then` waiter
sends. Queued (one Sonnet `code` slice after PR #19 merges): (1) read Paseo's bundled CLI
(`cli/dist/commands/agent/`) for a title or rename command and use it from `bin/self-slash` when one exists;
(2) otherwise, or as well, have `--then` send `/baton <repo>: <first words of the Tier 1 active_work>` so the
first words name the task (the `baton` skill ignores the trailing text as a label), and have `handoff` Step 8's
autorename cover the Paseo host; (3) a test with the fake `paseo` asserting the sent prompt starts with the
label. Never rename or send to a live agent in tests.

Also (djbclark, 2026-10-20, in the `/steps` session running as Paseo agent 6ebd939): he renamed that session's
workspace to `djbclark-ade-rework-p` in the Paseo GUI, and another agent looking for it by that name could not find
it; it saw the old name. Verified the same day: `paseo ls -g` lists the agent under its first-prompt NAME
("I want to move my entire AI development environment to djbcl..."), the GUI workspace name appears nowhere in that
listing, and `session-finder` (`fleet.py`) names a Paseo-hosted session from the agent record, so a GUI rename is
invisible to every agent that looks sessions up by name. The slice above must (4) find where Paseo keeps a
workspace's GUI name (the daemon API or its store under `~/.paseo`), have `session-finder` show both the workspace
name and the agent name, and make its rename path (1) set the name the GUI shows, so a manual GUI rename and an
agent rename are the same thing.

## `bin/load-watch` `send_to` has the relay's round-1 exposure (adversary on PR #25, 2026-10-20)

`send_to` (bin/load-watch, around line 536) still scrubs `PASEO_AGENT_ID`/`PASEO_AGENT_CWD` and runs `paseo send
<target> --no-wait --behavior steer <text>` without `--` and without the archived/permission gate: the text it
sends is unlabelled (arrives as the operator's turn) and a target or text starting with `-` is an option. Its text
is composed by load-watch, so lower risk, but fix before it ever sends untrusted text: call
`skills/session-finder/relay.py` instead of its own `paseo send`, or copy relay.py's `--`, label and `paseo_gate`.
One small Sonnet `code` slice with the fake `paseo`.

**Update 2026-10-23:** the `--` half is done (`86b288b`: argv is `send --no-wait --json --behavior steer -- <target> <text>`;
the same commit added a bounded retry on the daemon-restart codes, `9f9cae8`). Still open: the label and the archived/permission
gate above. Adversary APPROVE on both commits (reports `~/.local/state/agent-reports/14564811-383c-4575-9cf7-2b4ba5845f6d/`);
open lows on `86b288b`: (R1) a retry that dies by timeout never sets the give-up flag, so later sends in a long Paseo outage
can each pay up to about 30 s again; (R2) one stray warning line on stderr makes the JSON parse fail and silently turns the retry
off (parse the last JSON line, or each line); (R3, pre-existing) `subprocess.run(text=True)` can raise `UnicodeDecodeError`
outside the `except`, aborting the sample (use `errors="replace"`); (R4) the usage text says "the rest of that process make one
attempt each"; (R5) a comment at the argv saying every option must precede `--` (an option placed after it silently becomes
text and the send goes to the default daemon). No test covers R1.

## ADE-everywhere Phase 0, preserve and classify (djbclark, 2026-10-20; proposal section 8 item 1)

1. **Backups: done 2026-10-20 (PR #24).** `bin/ade-backup-stores` takes the `.backup`-API copy of every live session
   database, the per-session trees and file stores of inventory section 3, and the Hermes JSONL export, into
   `~/.local/state/ade/backups/<UTC>/` with a `MANIFEST.json`. Nothing is deleted from any store. The first real
   generation, `20261020T081802Z`, predates the credential scrub: it holds OpenCode's `credential` rows and 68 Cursor
   `mcp-auth.json` files, so the operator scrubs or deletes it and takes a new one. Open: run it on a
   schedule (no launchd job yet), and decide how long generations are kept; each is ~10 GB. A configured store that does not exist is `"status": "missing"` in the manifest and on
   stderr, exit 0 (`--strict-stores`: exit 1); a Cursor session without any `meta.json` (14 of 101 on 2026-10-20) is
   a `sidecar_missing` warning, store `ok`, an error only under `--strict-stores` (Codex review of PR #24, 2026-10-20;
   relaxed on adversary round 13, since every real run would otherwise be `partial`); a `meta.json` that is a symlink,
   excluded or gone during the copy is an error, store `partial`.
   Adversary round 2 on PR #24 (LOW/INFO, queued): a trigger on a scrubbed OpenCode table could copy the
   deleted values into another table on the copy (refuse or `DROP TRIGGER` on the copy, then count the scrubbed
   values in the copy's bytes after `VACUUM`); the schema guard misses `authorization`, `cookie`, `jwt`,
   `refresh`, `pwd`, `session_key`, `api-key` and exempts a table named `tokens` (apply the counter exemption to
   numeric columns only); SQLite files inside file stores (copilot `session.db`, muse `cron.db`, grok
   `session_search.sqlite`) get no guard at run time (route them through `backup_sqlite`); a killed run leaves an
   unscrubbed `<stamp>.part` that nothing reports; `seal_and_hash` should open with `O_NOFOLLOW`; `hermes`
   children should get `stdin=DEVNULL`. Operator: OpenCode's three API keys also sit in its transcript rows (317
   occurrences in `part.data` and `session_message`), so every generation is secret-bearing; if one ever leaves
   the Mac, rotate those keys.
   **Carried 2026-10-23** from adversary rounds 4-22 and Codex passes 19-21 on PR #24 (merged as f9d388d; LOW/INFO, all
   still open unless marked; the fixes made inside the PR are not repeated): (a) *Schedule and interpreter*: a
   scheduled run passes `--strict-stores` and pins a modern interpreter (uv's or PATH python3 3.14), because under
   /usr/bin/python3 (3.9.6, SQLite 3.54.0) a quiet WAL-mode source with no `-shm` beside it fails `ro_connect`
   ("unable to open database file"); plus operator items: the launchd schedule, a retention for generations, and
   whether a missing store on another machine is an error. (b) *Link and swap gates*: the root-link follow gate is wide
   (a same-user relayout of a store root to `~/.ssh` or `~` would be copied; fix: per-store expected link targets,
   HOME and secrets directories as errors); a symlinked PARENT of a store root (`~/.cursor` itself a link) is followed
   without the HOME check; `O_NOFOLLOW` guards only the last component, so a session DIRECTORY swapped for a symlink
   after the `under_symlink` check is followed by `ro_connect` and `copy_regular` alike (fix: open the resolved root
   once and walk each component with `os.open(part, O_NOFOLLOW | O_DIRECTORY, dir_fd=...)`, taking the expected inode
   from the final descriptor); `ro_connect` without a `base` still follows a parent link swapped in between
   `is_linked` and the open (walk from HOME with `O_NOFOLLOW`, `base=excluder.real_home`); `?nofollow=1` in a SQLite
   URI is ignored by Python's sqlite3 (checked on 3.53.1), so the fd identity check in `ro_connect` is the only guard,
   with a swap-and-swap-back window of microseconds; single-file roots copy through `copy2(follow_symlinks=False)` after
   the gate and keep a tiny FIFO race (route them through `copy_regular`); hard links pass the identity check and are
   copied as content; `check_tree_sidecars` looks sidecars up by absolute path after the schema check, so a session
   directory or ancestor replaced in between can pair the old database with a replacement tree's `meta.json` under
   `--check-schemas --strict-stores` (exit 0; Codex pass 21 P2; look the sidecar up relative to the held session
   directory descriptor as the copy does). (c) *Manifest reporting*: a root link to a FILE is listed in `root_symlinks`
   like a tree; a refused root link is in the manifest but not on stderr; a followed Hermes link is not in
   `root_symlinks`; `root_symlinks` also lists dangling targets, which appear under `missing` too; a tree root that
   exists but is not a directory yields no databases silently. (d) *Exclusions and guards*: `~/.ssh` is not on the
   exclusion list (nothing configured reads it today, but a future file store under `~` would copy keys; also add SSH
   key names, `.netrc` and AWS `credentials`); `--check-schemas` only lstats file-store roots and never opens their
   files, so a credential file added to a file store's glob is not caught; it opens excluded-name databases read-only
   for their schema; Muse's `tui-history.jsonl` holds everything typed into that TUI (covered by the usage warning). (e)
   *Dry run*: it never opens a database, so it cannot predict a schema-guard failure (an unexplained `api_key` column
   gives dry-run rc 0 while the real run is rc 1): say so in the usage text and point to `--check-schemas`; it accepts
   any nonempty `ADE_BACKUP_HERMES` without resolving it (`bin/ade-backup-stores:1816`, still `os.environ.get` on
   2026-10-23), so a nonexistent or non-executable override gives `--dry-run --only hermes-export` rc 0 while the real
   run fails with FileNotFoundError (Codex pass 21 P2; resolve with `shutil.which` / `os.access(X_OK)` and report an
   error); `check_tree_sidecars` lstats by path, so a parent directory swapped for a link mid-run is passed through once
   (reveals only a name and file type). (f) *Disclosure*: adversary round 18's probe ran the tool for real against the
   real HOME (no content copied; 274 Cursor `store.db-shm` mtimes bumped; manifest deleted); the adversary definition
   now forbids it (e9a77fe).
2. **Scan: `bin/ade-scan-state` and `bin/ade-scan-state-doc`** (PR [27](https://github.com/djbclark/djbclark-ade/pull/27),
   open 2026-10-23 at c4d9835; adversary round 61 APPROVE). A read-only scan of the bigteam task trees and the Orca
   checkouts, and the generator of `docs/ade-everywhere-phase0-scan-2026-10-20.md`. About 60 adversary rounds and 54
   Codex passes; every MEDIUM and P1 is fixed in the PR. Queued from them (LOW/INFO, 2026-10-20 to 2026-10-23; none
   blocks the merge; fixed findings are not repeated, and those given without a fix commit may already be fixed, so
   re-check against the code first). **Operator decision:** the committed snapshot is stale and its generator now
   differs: section 3.1 names only 4 of a task's reports (`research-brain-emulation-agent-teams` has 22), the scan's
   JSON was not kept (`phase0-scan-work/scan.json` holds the rendered markdown), and the doc predates the `graft/` and
   bundle-prefix changes (its do-not-run note covers it). Re-rendering needs a fresh `bin/ade-scan-state` run (read-only
   on the checkouts, no `--fetch`), then regenerate and commit. Sub-items: (a) *What counts as pushed*: stale
   `refs/remotes/origin/*` refs can hide a commit origin has since dropped (a merged-and-deleted or force-pushed branch;
   `--fetch` or `ls-remote` per repo would see it); a linked worktree outside the scanned roots is invisible from its
   main checkout (`git worktree list` per repo); tags on branchless commits are not counted; a local-path origin reads
   "pushed"; `_remote_cache` is keyed by (common dir, first origin url) without the `--remote` flag (no CLI path mixes
   them today); `local_only_verified` can be true while `invalid_origin_refs` > 0 (optionally false then); history
   reachable only through a nonempty `info/grafts` reads clean and pushed (flag it); a forged `objects/info/commit-graph`
   (`-c core.commitGraph=false`); an origin that lies is by design (stated in the usage text). **`--fetch` writes
   whatever origin sends into the checkout with no size bound** (Codex pass 45 P2, security): only the 120 s timeout
   limits it; a real fix is a quarantine repository with disk accounting (or a size-limited object store); documented in
   the help text, opt-in. (b) *Credentials*: an empty fragment counts as a credential on scp and transport forms but not
   on `scheme://`; scp `user:pw@host:repo` is not flagged (ssh, never handed to a helper as argv; INFO); the `%`-rule
   over-flags IPv6 zone ids (`[fe80::1%10]`) and local paths with `%3A` (safe direction, no change); `config_offenders`
   still prints a secret placed in a url PATH segment of a subsection (`url.https://h/tok/SECRET/.insteadOf`,
   `credential.https://h/SECRET.helper`, `includeIf.hasconfig:remote.*.url:https://h/SECRET/**.path`). (c) *Generated
   commands*: a detached-HEAD row emits `push`/`bundle create refs/heads/HEAD`, which fail loudly (r13; emit `HEAD` for
   the bundle and no push when the branch is `HEAD`); the 3.1 copy command (`cd <task dir> && gcp --parents -t <DEST>/...`)
   needs an absolute `<DEST>`; bundle rows write to the fixed `~/ops/site-private/bundles/<rel>/all.bundle` (inside the
   site-private repo) instead of `<DEST>`, so a reader following `<DEST>` elsewhere must rewrite it (decide whether
   bundles belong there or in a non-repo vault); the "(branches not itemised)" label beside a HEAD row is misleading
   though the `--all` bundle captures everything; the section-3 preamble could say the BSD fallbacks (`cp` without
   `--parents`) need coreutils and gnu-tar; a literal `|` inside a fmt string (`||`) is not escaped by `code()`, so the
   gitdir, modified and stash rows split their table cell in GFM (escape `|` in fmt text; tests comparing raw `||` would
   need `\|\|`); a split index (`core.splitIndex`) needs `sharedindex.*` copied beside the index copy; the manifest
   member `modified.list` collides with a tracked top-level `modified.list` on extraction (use a `.git-capture/` member
   name via `--transform`); the children step's nonzero exit stops the chain silently (`|| { cat hidden.err >&2; false; }`);
   `SYMLINK_GITDIR_FMT` on a link to a linked worktree's admin dir fails loudly without archiving the commondir (reuse
   `GITDIR_FMT`'s step) and `GITDIR_FMT` refuses `gitdir: x\n\n`, which git accepts (loud, nothing lost); the gitdir span
   archives any directory a `.git` file names (empty path, non-git or hostile target) with rc 0 (check `$g/HEAD` and
   `$c/objects` first, and `[ -d "$g/refs" ]`); the submodule row's plain `git status` can run
   `<common>/modules/<sub>/hooks/post-index-change` (same trust as the superproject's hooks; prefix its git calls with
   `-c core.hooksPath=/dev/null -c core.fsmonitor=false`, or state in the docstring and `docs/threat-model.md` that hooks
   are trusted like the human's own); a corrupt stash ref also gives rc 1 (reached only when the reflog file is missing);
   a lone surrogate outside U+DC80..DCFF reaches `_quote` and prints as `\ud800` text (refuse it there); `gfm_cells` is
   applied only to the real submodule checkout's rows (assert it on the counts-unknown, `.git`-symlink and push/bundle
   rows too); display `esc(in_code=False)` writes a value's `\|` as `\\|`, which renders as `|` (display only). (d)
   *Refinements of the reflog and hidden-path rows*: the reflog count
   (`rev-list --count --reflog`) flags most active checkouts for ~30 days after an amend, squash-merge or force-fetch;
   walk only `HEAD` and `refs/heads/*` reflogs including other worktrees, leave `refs/remotes/*` out, optionally drop
   patch-id-equal commits; the index-hidden count could also require that the worktree file differs from the index blob
   (`ls-files -s` against `hash-object --stdin-paths`) so sparse checkouts stop flagging; an assume-unchanged or
   skip-worktree submodule gitlink is a hidden directory with a `.git` file and is reported as an embedded pointer
   repository on top of the submodule handling; a checkout with untracked paths AND a repository found only under a
   hidden path does not name the hidden one in the `what` cell (the command is in the row); the pointer-repo note is
   inexact when the pointed-at gitdir is inside the checkout. (e) *Scanner reach and wording*: a repository nested under
   a `SKIP_DIRS` name (`target/`, `node_modules/`) is not scanned and the help text does not list those names; only
   top-level submodules are listed (no `--recursive`); a stash reflog that is a FIFO hangs the scan and one linked to
   /dev/zero exhausts memory (needs write access to the checkout's `.git`); `scan_bigteam` lists the bigteam root with an
   unguarded `os.scandir` (an unreadable root raises); `newest_mtime` and `du_bytes` ignore unreadable dirs (size and
   mtime columns only); the "(reference search failed)" labels are narrow for a traversal-incomplete task; a symlinked
   `.gitignore` or `.gitattributes` makes the scan `incomplete` without naming the file; a global absolute `lfs.storage`
   store shared by several checkouts is archived once per checkout; very long hidden paths (~1 KB each, up to the 1000
   cap) could hit E2BIG, which `run()` turns into rc 124 (`scan incomplete`, not partial); `render` raises on
   `summary.bigteam.verdicts: null` and on `bigteam` without `tasks` (the scanner never writes either); a `config.worktree`
   holding an outside `core.worktree` is refused even without `extensions.worktreeConfig`, a case variant of the
   checkout name is refused (APFS), and a malformed operator global config makes every push row bundle-only
   (conservative; none repaired). (f) *Prose that goes stale*: `bin/ade-scan-state-doc` section 2 hard-codes
   "the 41 `unique`/`mixed` bigteam report sets" (line ~471), false on a git-only scan and after the numbers move (round
   61 LOW; compute it from the data). (g) *Tests*: the `$GTAR` source-count guard in
   `test_every_archive_ignores_the_operators_tar_options` is textual; optionally run the whole-directory and
   submodule-untracked commands under `TAR_OPTIONS=--exclude=*` too.

## Keep every machine current, and a changelog (djbclark, 2026-10-20; proposal Q26, T8)

djbclark, 2026-10-20: "We need a clear way to keep all of djbclark-ade up-to-date on new
systems, and also we should have a changelog so people know what changes or new features are
added." Done the same day: `CHANGELOG.md` (Keep a Changelog form, seeded from the merged PRs
since 2026-10-09), AGENTS.md code-review rule 10 (every PR adds its line), README "Update
(this machine)" (the manual procedure today), proposal v2.4 (T8, 4.4 item 9, §9.4 Q26). Queued:

1. **Done 2026-10-20** (PR #20) **`bin/ade-update`, the interim one command** (one small PR, Sonnet `code` slice): fetch once,
   check the upstream commit, and fast-forward `~/src/djbclark-ade` to exactly that checked SHA
   (never a second `git pull` that could move past what was checked; stop and print `git status`
   on a dirty tree or a diverged branch; never stash another agent's edits), then `bin/skill-everywhere --check` over every
   `skills/*` (relink what is missing), the `~/.claude/{commands,agents,hooks}` symlink check,
   and print the `CHANGELOG.md` entries between `~/.local/state/ade/applied` (written at the end)
   and the new head; `--check` only reports. A test with a temp repo. README's section then
   names it. It becomes `ade update` in Phase 1 (proposal 4.4 item 9).
   **Carried 2026-10-23 from adversary rounds 10, 11, 17 and 18 on PR #20 (merged; LOW/INFO):** (a) `--check` misses a
   case-only collision on a case-insensitive filesystem (apply stays safe: git refuses, exit 2): compare `casefold()`ed
   paths when `core.ignorecase` is true. (b) `git status --ignored -uall` lists every file under every ignored tree (5k
   entries here); use `--ignored=matching` if a huge `node_modules` ever matters. (c) an installed
   `~/.local/bin/ade-update` must resolve into the canonical checkout: the tool warns on stderr when it runs from
   elsewhere, but the Phase 1 installer or the daily timer (item 2) should verify it. (d) `run()` decodes git output as
   strict UTF-8, so a non-UTF-8 upstream path crashes every mode with rc 1 (not in the documented exit set; fail-closed);
   upstream entry names print raw in the text report (JSON is safe). (e) `helper_env` always drops
   `SKILL_EVERYWHERE_ONLY`, but `docs/skill-everywhere.md:70` needs it on the Grok Bot box, where nothing runs
   `ade-update`; the R15-2 test checks `helper_env` but not that `check_skills` and `link_skills` use it. Out of scope for
   that PR, in `bin/skill-everywhere` on master: `render_copy` runs under `set -e` inside `&&`/`eval` (the errexit is
   ignored there), and check mode leaks a `mktemp` file.
2. **A daily `--check` timer** (launchd here, systemd user unit on Linux) that writes a
   "behind by N commits" line Hermes's dashboard and `ade doctor` can show; a `fleet-watch`
   notice when a machine is more than a week behind. After item 1.
3. **Tag the first release** once CI, the changelog rule and `bin/ade-update` have landed:
   `v0.1.0`, `Unreleased` moved under it, so `ade update` has a delta to print and `ade-kit`
   (Phase 7) has a starting point.

## Cloud-agent readiness: Codex Cloud environment, Cursor API key (ruling 2026-10-19)

`docs/ade-everywhere-proposal.md` §11.5 rules that paid-for cloud agents are used first for
slices that can leave the Mac. Two need djbclark once: (1) environment `ccarenv_02c6721d65dc4191b57a76a84baa4121` for `djbclark-ade` created
2026-10-19, but codex-cli 0.163.0 cannot see new-style environments (`codex cloud exec` exits 1,
"no cloud environments are available for this workspace"; upstream openai/codex#50182 and
#51585, open). Re-probe after each codex-cli release (`codex cloud exec --env <ID> --branch
<b> "<task>"`); route chosen (round 3, 2026-10-19): `@codex` on a GitHub issue, scriptable with
`gh` and the factory's intake path. The Codex GitHub app is installed; the first task is
https://github.com/djbclark/djbclark-ade/issues/4, but the connector answered twice "To use
Codex here, create an environment for this repo" even after djbclark re-checked the
environment's binding, so the connector reads the same catalog the CLI does. Blocked as a builder on both
routes until OpenAI fixes new-style environment discovery (openai/codex#50182; non-review
mentions are a separate open bug); the load-admit fix went to the local builder instead (three adversary rounds, PR 7 opened 2026-10-20). What
works today: `@codex review` on a PR (PR 5 reviewed clean, 2026-10-19), so Codex is a third
reviewer next to the adversary and Cursor's Security Agent (auto review on PR open was switched on 2026-10-19 in the repo and personal settings, but on PR 9 it answered "To use Codex here, create an environment for this repo": the same catalog bug as the task mentions, so every PR still needs a manual `@codex review` comment, which works without an environment; Codex's reviews of PR 7 gave three valid P2s, all fixed). Cursor's Bugbot is *disabled* for this repo (`bugbot run verbose=true` on PR 7, 2026-10-20: "Bugbot is disabled for this repository"); enabling it is djbclark's call at https://www.cursor.com/dashboard/bugbot, not needed while three reviewers already run. Re-trigger issue 4 with an `@codex`
comment after the next Codex release or when the connector's reply changes. Then a `codex-cloud` place in
`acp-dispatch`/`route_agent.py` so the router can pick it (§11.5 rule 4);
(2) DONE 2026-10-19: the Cursor user API key is `CURSOR_API_KEY` in `sudo-secretspec`
(runtime declaration, optional; read it only through `sudo-secretspec run`); `bin/cursor-cloud`
launches, inspects and follows up agents (first slice merged as PR 5, 2026-10-19; `@cursor` on
issue 6 is the GitHub-mention test: it fires on a *comment*, not the issue body, 2026-10-20, agent bc-614266a6, docs slice as PR 8, $1.04 at API price); DONE 2026-10-20: the `cursor-cloud` place in `acp-dispatch`
(record, 30 s poller, report with `BRANCH:`/`COST:`, no PR) and a `cursor-cloud` service in `route_agent.py`/`config/routing.toml`
(branch `feat/cursor-cloud-route`); `codex-cloud` stays open on the upstream catalog bug. (3) The Max plan's
monthly API credits are the `omp credits` pool in `aiuse` (djbclark, 2026-10-19): rename the
pool, verify the balance on the Anthropic console, and route one API-key workload at it.

## The Claude API credits (omp): finish the wiring (decided 2026-10-19)

The per-run omp gate is lifted (`skills/model-routing/SKILL.md`, proposal SF-Q19): the credits
are a normal tier, `api-only` work first, else `code`/`bulk` via `acp-run omp --model
anthropic/claude-sonnet-5-5`. Open, in order: (1) DONE 2026-10-19 (round 3): djbclark ran `omp login` for Anthropic; the
credential row is clean and `acp-run omp --model anthropic/claude-sonnet-5-5 -p ...` answered.
Still to confirm: that a slice's cost lands on the credits pool in `aiuse` (console 2026-10-19:
$95.57 of $200 left, expires 2026-11-08; `aiuse` showed 100% unused, so its CodexBar reading is
stale or another row: fix in `~/src/aiuse`). (2) DONE 2026-10-19 in `~/src/aiuse` (8a9dc43):
`requires_operator_approval` dropped on the omp row, the row keeps the name `omp` (tools look it
up), `--json` carries `credits_label: "Claude API credits"`; still open there: the "burn before
reset" suggestion late in the grant period, which `route_agent.py` already has (`grant_days`,
`grant_waste`). (3) The `api-only`
callers (`bin/failover.py` Claude SDK route, a verdict classifier) take their key from the
secret backend, not from omp: check that key draws these credits, then have them ask
`route_agent.py route --kind api-only` for the balance before a batch.

## Buy a Jev plan before the factory's merge gate goes live (SF-Q10, 2026-10-19)

`bin/jev` runs in shadow mode. Phase F's automatic merge (proposal §8 item 9.5) needs a live
`merge_gate` decision; before F2b the lead prompts djbclark to buy a Jev or equivalent plan and
set up access (`TYPESAFE_API_KEY` via `sudo-secretspec`).

## Paseo Telegram plugin replaces Hermes's relay (SF-Q16, 2026-10-19)

Decided: the Paseo Telegram plugin (`daaaaave/telegram`) becomes the phone surface. Blocked
today: its registry version requires Paseo `>=0.11.2 <0.12.0` and the daemon is 0.12.0; wait
for a compatible release, then one Phase F item re-points `hermes-ping`, the approval buttons
and home rule 12, with Hermes's relay as the rollback.

## Telegram for 2fado, Herald and agent web searches: talk first (djbclark, 2026-10-25)

djbclark asked (2026-10-25) to set Telegram up for the Paseo `2fado` plugin (`@xpufx/paseo-twofado` 0.1.3, daemon `2fadod`, "Telegram Fallback: unconfigured")
and "in general", at an appropriate point in the queue, after a talk with him about what it does and whether it helps us, web searches included. **Ruling 2026-10-25 (djbclark, after the talk): parked until SF-Q16 (the section below) is settled; then decide on one bot. Configure nothing before that.** (Original note: do not configure
anything before the talk.) Findings 2026-10-25 (read of the plugin README and github.com/xpufx/2fado): 2fado gates only commands an agent chooses to run as
`2fado run -- <argv>` (policy allow / deny / ask a human on Telegram; fail closed; runs as the daemon user, no escalation in the default build), plus `ask`/`notify`
petitions; it does not intercept Claude Code's own tool calls, MCP calls (`WebSearch`, `firecrawl_*`) or `sudo-ask`. A web-search gate would need a PreToolUse hook that calls
`2fado ask`. Overlaps: the SF-Q16 item below (Paseo Telegram plugin replacing Hermes's relay, blocked on a Paseo version range), `hermes-ping`, Hermes's
`permissions_respond`, `/helm`, and Herald (spoken waiting alert). Ties to the "ask before costly steps" rule in `feedback_heavy_web_search`.

## ade-git-guard (PR 59): redesign O2 adopted after round 9 BLOCK on 7df76ad (djbclark, 2026-10-25)

Round 9 (Opus, `adv-iso-w1-r9-report.md`) BLOCKed on F1: `git --attr-source HEAD <write>` and `git --shallow-file /dev/null fetch origin +main:cb` move a claimed branch with rc 0, because
`parse_git_argv` skips an unknown global option as one token. After nine rounds of argv-spelling bypasses djbclark asked for a design consult: web research (`dcg`, `cc-safety-net` are argv-pattern
guards, both "not a sandbox"; GitLab Gitaly uses `reference-transaction` in production) and a Fable 5.1 frontier consult (`frontier-pr59-design-report.md`). Measured 2026-10-25 on git 2.56.0: a
`reference-transaction` hook refused both round-9 spellings, `branch -f` and `update-ref`, allowed unrelated ops, and was disabled only by `-c core.hooksPath=...`.
**Decision: O2.** `reference-transaction` (prepared) and `pre-push` hooks in the repo's common git dir are the ref enforcement, fail-open on a hook crash, humans exempt; the shim shrinks on the same
branch to fail-closed rules the hooks cannot see (config keys that disable hooks, `push --no-verify`, foreign-workspace read-only allowlist, `worktree` verbs, `branch -m/-c` destinations, unknown
option or subcommand = refused); the fetch/push preflights, output-file rules and shell-string `check` analyser go. Proof test: every r7-r9 argv form through the real git must fail with the claimed ref
unmoved. Build slice `o2-build-pr59` (Sonnet 5.5 via omp) dispatched 2026-10-25; then ONE adversary round with a new brief (argv spelling out of scope; ask for ref writes without a transaction, hook
disabling through config, no-ref harms in a foreign tree, false refusals of the owner). Open follow-ups: upstream report that `branch -m/-c` destinations are not reported to the hook (files backend);
config-based hooks (git 2.54+) as an install route, verify composition first; wire `ade-git-guard install` into `cow-pasture`, `acp-dispatch` and `acp-run` (W2/W3/W4). F2 (docs pointer to the N6/N7
entries) is moot once `docs/git-guard.md` is rewritten.

## ade-git-guard (PR 59): O2 redesign built on the PR branch (2026-10-25); what is left

djbclark adopted the frontier advisor's O2 design (`frontier-pr59-design-report.md`, 2026-10-25) after nine adversary rounds of argv-parser bypasses: refs are enforced by
git's `reference-transaction` and `pre-push` hooks, the shim shrank to what hooks cannot see and fails closed (`docs/git-guard.md`). The rounds-8 and -9 residuals N6 and N7 and
the r9 F1 (`--attr-source`, `--shallow-file`) are gone with the dry-run preflight they were about (an unknown leading option is now refused). Open:
1. **Next adversary round, with a NEW brief** (O2 plan step 5): argv spelling is out of scope by construction. Ask for (a) ref writes that reach disk without a reference transaction
   (a `packed-refs` edit, `git replace`, `git notes`, a `symbolic-ref` of a per-worktree ref), (b) hook disabling through config the shim does not see (`HOME`/`XDG_CONFIG_HOME`
   pointing at a file, `GIT_CONFIG_SYSTEM`, a repo-level `core.hooksPath` written by hand), (c) no-ref harms in a foreign tree, (d) false refusals of the owner's ordinary work.
2. **Upstream report, `branch -m|-M|-c|-C` destinations (git, files backend)**: a rename reports its SOURCE deletion to `reference-transaction` but not the destination creation, and
   a copy reports nothing (measured on git 2.56 in /tmp, 2026-10-25; git-hooks-ext documents the same for 2.27-2.55; Jiang Xin's 2022 series did not land). Dupe-search git's list,
   draft a minimal reproduction (a hook that logs stdin; `git branch -c a b`), file it (AGENTS.md item 38). Until it lands the shim keeps the destination rule.
3. **Config-based hooks (git 2.54+, `hook.<event>.command`)**: they may let `acp-run` inject the guard through `GIT_CONFIG_COUNT` into repositories nobody installed. Verify FIRST whether
   a config hook for `reference-transaction` runs alongside `.git/hooks/reference-transaction` or replaces it, and whether `-c hook.*.enabled=false` from an agent beats an env-injected one
   (the shim refuses `hook.*` keys regardless). Do not build on it before that is measured.
4. **Wire the call sites** (not in PR 59): W2 `cow-pasture create` runs `ade-git-guard install <pasture>`; W3 `acp-dispatch` exports `ADE_CLAIM_ID` and installs in the repository at claim
   time; W4 `acp-run` puts `libexec/agent-bin` first on agents' PATH; the operator runs `ade-git-guard install` once over `~/src/*` and `~/orca/projects/*`. Check Hermes (it turns repository
   hooks off in its trees) before relying on the hooks there.
5. **`git replay`, `git history`, `git refs migrate` (new in 2.54-2.56)** write refs and should reach the hook (NOT measured); the shim's `KNOWN_SUBS` lists them as ordinary subcommands.
   Re-measure the hook on each when a claimed branch is in play.
6. **Output files into an unclaimed checkout (accepted residual, 2026-10-25; Codex threads on PR 59 for `stash show --output` and `format-patch -o`)**: replayed at ac2fc56, `git stash show -p
   --output=f` and `git format-patch -1 -o .` replace a peer's uncommitted file in an unclaimed checkout (rc 0); in a claimed foreign workspace they are refused. `docs/git-guard.md`
   NOT covered item 14 says so. If djbclark wants it closed: a slim shim rule refusing `--output*`, `-o` and `--output-directory` on `stash show` and `format-patch` when the target lies
   outside the caller's claimed workspace (the O2 removal of the output-file rules is the reason it is open), plus tests that fail before and an adversary round.

## acp-dispatch launchd label with a slash (PR 62, merged e15aeb9, 2026-10-25): lows from adversary round 1

Verdict `APPROVE ac0e0d8`. Left open:
1. **Docs, low**: `bin/acp-dispatch` usage text (the `launchd's last exit status` line and the `no longer loaded` line) and the `launchd_print` docstring still say `launchctl print gui/$UID/<label>`; a slash label is
   looked up with `launchctl list` and its last exit is never read (reap goes to rc 0 if delivered, else 255 `lost`). One clause at each place.
2. **Test gap, low**: the auto-resume resubmit path (`resubmit_auto_resume`) also carries a slash label under `--task`; `STATEFUL_LAUNCHCTL` in `tests/test_acp_dispatch_auto_resume.py` handles only `print`.
   Add a `list)` case and one reboot-resume test with `--task /abs`.
3. **Info**: `launchctl list` asks the caller's own bootstrap domain; a `check` run from an ssh login does not see a job submitted from the GUI session, so a slash label still reads as gone there.

## Verified peer messaging (djbclark, 2026-10-25; part of the big ADE queue)

djbclark, 2026-10-25: always verify the other agent got the message, or we may sit on a one-way receive-only link; "make sure that always happens as part of the big djbclark-ade queue". Case: the
herdr successor `29a5535c` sent a contract proposal; the reply was written only in prose, then relayed (`relay.py` status: `queued`, the target was inside a long command): not yet proven. Standing order 10 in AGENTS.md
states the rule. Build items, each one Sonnet `code` slice with a test:
1. **`relay.py --ack`**: after a send that is not `delivered`, keep watching (transcript or inbox of the target, bounded by `--wait`) and print `delivered`, `unverified` or `not delivered` as the exit status
   (today `queued` exits 0 like a delivery); add `--expect-ack ID` that waits for a reply message naming the sender.
2. **First-contact ack**: the first relay to a session this sender has never messaged appends "reply `ack <sender id>` through relay.py"; `fleet.py` records which peers have ever acked, so a one-way link shows as such.
3. **Inbound relays**: a relayed message that asks a question is answered by a relay to its sender (the footer names the route); a reply written only in the receiver's prose is flagged by the `session-finder` skill text and by a Stop-hook nudge when a turn began with `[relay from ...]` and ended with no `relay.py` call.

**Landed 2026-10-25 (branch `feat/relay-verified-delivery`, PR #NN; `skills/session-finder/relay.py`, `fleet.py`, SKILL.md "Verified peer messaging"):**
1. `--ack` is opt-in: without it `queued`/`accepted` still exit 0 because fleet-watch, load-watch, session-load-watch and rumination-watch read 0 as "taken or queued" (checked 2026-10-25); with it a send that is only accepted or queued is watched for `--wait` more seconds and exits 0 delivered, 1 not delivered, 3 unverified (new). Proof per route: pane enqueue (transcript `tx_state`), Claude socket frame to a working session and Paseo send to a Claude agent (the text or envelope in its transcript), deferred record (the deliverer's outcome line must say `: delivered;`). ACP inbox (`launch`, `dispatch`) has no transcript to read: unverified at once.
2. `--expect-ack ID` (+ `--needs-reply`, `--fyi`, `--ack-within S`): a `?` outside a URL or `--needs-reply` from an identifiable session is refused (exit 2) without it; the record is `<deferred dir>/expect/ID.json`, listed by `--pending` (rows `"kind": "expect"`, `overdue`), resolved by `--sweep` from the sender's transcript. Escalation (D) is print-only: `--sweep` prints `OVERDUE ack ID ...` lines; the lead wires `hermes-ping` there (hook: `relay.py --sweep` output, or `relay.py --pending --json | jq '.[] | select(.overdue)'`, from fleet-watch).
3. First contact: footer on the first send per sender>target pair; `~/.local/state/relay/links.json` ledger; `fleet.py list` shows `link: acked | ONE-WAY`. Not done by design (left for the lead): the Stop-hook nudge (see the report's DECIDED).
4. **Home instruction file (Opus only)**: item 24 (3) of `~/.claude/CLAUDE.md` gains one clause pointing at standing order 10; dispatched `acp-dispatch omp --model anthropic/claude-opus-5-5 --kind judgment` on 2026-10-25.
5. **Refuse an unresolvable sender (djbclark, 2026-10-25, relayed by the load-watcher agent bb2a32df)**: every relayed text must carry reverse contact info, so a relay whose sender cannot be resolved is not sent: exit 4 (`NO_SENDER_EXIT`; 0, 1, 2, 3 were taken), nothing sent, queued, deferred or recorded, `--json` `{"sent": false, "error": "no_sender", ...}`, the text names what was checked and says to re-run with `RELAY_SENDER_NAME=<label>`; `--plan` unaffected. `[relay from unknown]` no longer exists in any sent text. Callers that run with no session now declare a sender: `bin/load-watch` (`relay_env()`, both relay calls), `bin/session-load-watch`, `launchd/com.djbclark.rumination-watch.plist` (already did); `fleet-watch upstream` (site-djbclark, outside this repo) still needs `RELAY_SENDER_NAME=fleet-watch` (report 2026-10-25).

Scoping (Dann 5, lead of techno-euphora, relayed 2026-10-25, after djbclark asked whether relay should ALWAYS require a reply): mandate PROOF, not conversation. Delivery proof (the text reached the
target's transcript) is mechanical and needs no reply; a reply (the target read it and acted) costs the target a turn, and a send to a working cline or ACP agent cannot steer, so forcing one on every message
doubles traffic, interrupts work and is wrong for one-way messages (a status, a handoff pointer, "PR 61 is merged"). Evidence: this chain's own handoff a621 item 6 carried a 30-minute waiter and a "peer may
be unreachable" note for a peer (`29a5535c`) that was in fact reachable and responsive - its ack was
verified both ways 31 s AFTER that handoff line was written (b457 log, 04:08:31 vs a621 created_at
04:08:00), so the line was stale rather than the link broken. A later relay by Dann 5 reached the same
peer immediately. The real cost stands either way: a 30-minute waiter and a false "may be unreachable"
note, spent because `queued` looked like success and nothing distinguished "not yet delivered" from
"cannot deliver". The items keep their shape and gain:
A. `queued` never exits 0 as if delivered (item 1, first and unchanged).
B. `--expect-ack ID` is REQUIRED for a message that asks a question or requests action, and is record state, not a blocking wait: set at send time, shown by `relay.py --pending` (sender, target, age), resolved by
   a later `--sweep` when the reply arrives, so no turn is held open on a peer's schedule.
C. First contact with a peer always asks for an ack (item 2, standing order 10).
D. No ack within a bounded time escalates to the operator, never assumed read.
E. Everything else: verified delivery is enough; an FYI that provably landed needs no reply.

## Software factory, Phase F (decided 2026-10-19)

Proposal §8 item 9 and §9.3. Starts after Phase 1's first PR. First slices: `bin/factory` F1
orchestrator (claude sonnet, high), Jev `pick-seat`/`stuck-check`/`merge-gate` sites in shadow,
the workspace adapter (cow + worktree). Pilot repo `djbclark-ade`, allowlist of small
non-security tasks.

## A read-only codex advisor ends on its first refused escalation (found 2026-10-19)

Under `acp-run codex --perm read-only` a shell command that needs network or writes is an
escalation request; acp-run refuses it (correct) and codex-acp then ends the turn with
`stopReason: cancelled` (exit 1, no report; `sf-research-codex2`: 520 s, 47 tools, 5.0M tokens
lost when it asked to run `gh api repos/... rulesets`). Claude under read-only simply gets no
Bash tool and carries on. Candidates: (1) on a refused request under `--perm read-only`, acp-run
sends one follow-up prompt ("that command was refused; continue without it") instead of ending;
(2) the read-only brief footer tells codex that any escalation ends the run; (3) both. Until
decided, codex advisory reads run `--perm all` with the advisor tree check as the guard (as on
2026-10-19 for sf-research-codex3).

## self-slash cannot drive omp (found 2026-10-13, needs an operator decision)

`bin/self-slash "/quit"` from an omp session in herdr pane w34:p2 queued, waited, and gave
up: `~/.local/state/self-slash.log` 14:23:03-14:24:03 "no input prompt on screen yet" x9,
then "gave up, no empty input prompt seen". Cause: it looks for Claude's `❯` (or
cursor's `→`) input marker, and omp draws a boxed composer (`composer.shape: box` in
`~/.omp/agent/config.yml`). herdr does identify the pane (`herdr pane get` →
`.result.pane.agent` = `"omp"`; an earlier "agent: null" read the wrong JSON path), so
self-slash can branch on it the way it does for cursor. So `/quit` and `/compact` via
self-slash, and `/loose` Rule 4's quit, do not work in omp yet. **Decide:** teach
self-slash omp's composer (screen scraping, breaks if the composer shape changes), or
add a command channel to the omp bridge extension (`skills/autorename/omp-bridge.ts`),
if omp's extension API can run a slash command or end a session.

## Ralph on OpenCode v2: postponed (operator, 2026-10-13)

**Postponed by the operator ("postpone all ralph work"); do nothing until raised.**
State when parked: the opencode-ralph-tui wrappers (`vendor/gate-scripts/`, live copies in
`~/.local/bin/`) were pointed at v2 in `bea2e9d`, then switched back to v1
(`~/.opencode/bin/opencode`, 1.18.32) in `d3de341` at the operator's request, so Ralph runs
v1 while parked even though plain `opencode` is v2. Findings, from the v2 trial, none acted on:
1. `bun ~/src/vendor/ralph-tui/dist/cli.js doctor --agent opencode-go` detects v2 2.0.27 but
   fails the preflight with exit 130. Running the same args by hand (`opencode-ralph-tui run
   --format json "<prompt>"`) gives v2 JSON events and then `provider.quota` 402 "Insufficient
   account funds": the agent sets `provider = "opencode-go"` but no `model`, so no `--model`
   is passed and v2 falls back to its default model. Untested: an explicit opencode-go model.
2. ralph-tui's opencode plugin (`src/plugins/agents/builtin/opencode.ts` ~414-455) passes
   `--variant`, which v2's `run` lacks (v2 takes `--model provider/model#variant`), and its
   JSON parser was written for v1 events; neither is checked against v2.
3. `ralph` on PATH (`/opt/homebrew/bin/ralph`, 2.10.1) is Homebrew's ralph-orchestrator
   (mikeyobrien), a different project from ralph-tui, which still runs from the fork via
   `bun ~/src/vendor/ralph-tui/dist/cli.js`. Decide which one "Ralph" means before resuming.

## Resurface 2026-10-14 (operator, 2026-10-13): first real SkillOpt-Sleep night, backends, -C repos

**Queued 2026-10-13 by the operator: "resurface tomorrow".** Any session that opens
this repo on or after 2026-10-14 raises these three first, one `/steps` prompt each:
1. **Read the first night on the new chain** (03:30 on 2026-10-14): `nights.jsonl` and
   `attempts.jsonl` in `~/.local/state/skillopt-sleep/`, `skillopt-sleep status`. Did the
   per-prompt retries, the stripped opencode/agy startup, the direct SIPB entries and the
   lowered floors (0 for opencode-go/agy/zcode, 5 for claude) get sources through? Did crush
   and the new Hermes/grok/muse/cline/acp-dispatch adapters run? Measure prompts and tokens
   per source. Token capture landed 2026-10-13: attempts.jsonl attempt rows and
   nights.jsonl rows carry `tokens` (backend-reported counts, never estimates; see
   docs/failover.md).

   **READ 2026-10-20 — sub-item 1 is done.** Source: `nights.jsonl` (101 rows, 49 nights)
   and `attempts.jsonl` (288 rows) for 2026-10-14 onward, plus `~/.local/bin/skillopt-sleep
   status` (it is on PATH; there is no `bin/skillopt-sleep` in this repo).
   1. **Metering is wider than this item claimed.** "agy and crush are unmetered
      (`tokens: null`)" and "zcode and hermes are unmetered until a log shows `result.usage`"
      were already false on the 2026-10-14 night: agy reported 126 metered / 1.21M total,
      crush 53 / 623k, hermes 46 / 824k; zcode reported on 10-16 (13 / 2.90M) and 10-17
      (1 / 23k). `tokens: null` now means only that the source got 0 prompts.
   2. **`source` is the transcript source; `tui` is the backend that answered it.** opencode's
      night rows read `prompts: 0` while `attempts.jsonl` carries 45 successful opencode
      answers since 10-14 — opencode-go is the workhorse, not idle. A 0 in a night row is not
      a dead backend.
   3. **Two accepted proposals in seven nights**, both from the new adapters: acp_dispatch
      (10-14) and codex (10-18). Every other night produced 0 and the gate rejected.
   4. **The 10-19 night did not finish**: `status: "stopped: deadline 06:30 passed"`, rc null,
      after 247 prompts and 25.7M tokens for 0 proposals — the most expensive night of the set.
      On 10-19 and 10-20 only the `claude` source ran; the rest of the chain did not execute.
   5. **Night 49 (10-20) establishes nothing about the real chain**: `backend: handoff`,
      `replay: mock`, 0 sessions harvested, 5 mined tasks, gate reject (held-out 0.257 ->
      0.257).
   6. **Backend faults worth fixing**, from `attempts.jsonl` `why`:
      a. agy's invalid model id — **closed 2026-10-20, it was already fixed.** The two
         `acp-run: no model 'gemini-3.8-flash-medium'` rows are 2026-10-18 04:15 and 05:04;
         `2dab22e` (2026-10-18 06:15 local) stopped gluing the effort onto the id, because
         agy 1.4.1 lists bare model ids and takes a `thinking_level` option. The rows predate
         the fix, so there is no code change here. (Raised by `djbclark-ade-db`, which read the
         rows as 10-12/13; the dates above are the verified ones. The entry as first written
         read as a live fault and was not one.)
      b. agy pools `antigravity/claude_gpt` and `antigravity/gemini` report "not in `aiuse
         --available`" (rows 2026-10-12 to 10-14; 7 and 6 of them inside the 10-14 window).
         **Checked 2026-10-20: not a fault, the same class as (d).** `antigravity/claude_gpt`
         really is exhausted -- Claude/GPT weekly 99% used, resets Sat Oct 24 2:18pm -- so the
         refusal is correct, and `antigravity/gemini` is listed in `aiuse --available` today at
         32% headroom, with `hidden_pools` and `excluded` both empty. The pool keys match the
         ones `--available` emits, so the mechanism works and the rows record exhaustion, not a
         lookup bug. One loose thread, not reproducible: at 10:46 today `--available` omitted
         gemini while `aiuse --json` showed all three of its windows `ok`, and four minutes
         later it listed it with the identical headroom figure; `apply_frozen_measurements` is
         the plausible mechanism (a frozen measurement deliberately suppresses a pool). If the
         night rows show agy skipped while gemini has headroom, look there first.
      c. zcode `project_token_login_failed` x4, classified `transient` so it retries into the
         same wall, plus one rc=124 after 914s with 41 tool calls.
      d. claude was refused 6 times at `headroom 4.0% <= floor 5.0%` — the floor working as
         designed, not a fault.
      e. opencode-go answers at 2.8-5.2% headroom against a 0.0% floor.
2. **Denied backends** (`hermes`, `cursor`, `cline`, `clinepass`, `opus`, `fable` in
   `failover.DENY`; `muse`, `pi`, `grok`, `codex`, `copilot` in night.json/skillopt-night):
   the operator kept them denied on 2026-10-13 ("revisit after tonight"). With the night's real
   counts, decide whether Hermes or codex joins as a late chain entry. `aiuse --available`
   shows only opencode-go, claude (default and Fable) and antigravity/gemini; codex, cursor,
   copilot, grok, pi and muse have no window.
3. **The `-C` strip gap** in the next entry: the operator chose to note it and do no work on
   2026-10-13; raise it again.

## Crush under `--perm deny`: adversary findings 1-4 (DECIDED 2026-10-14: crush excluded from deny-mode reviews; fixes still not made)

**Queued after the review of 71ac081 (scratchpad adv3-report.md). Since the same day
the SkillOpt night runs its chain with `perm: all` (operator decision), so none of
these affects the night; they matter for `--perm deny` runs of crush (acp-dispatch
read-only reviews).** (1) An untrusted `-C` repo's project `crushrc` runs as shell at crush
startup and its files can leak; acp-run only warns (acp-run ~828-835). (2) MCP tools are not
covered by `disabled_tools`, so the logged `"tools": "none"` can be false (~825). (3) The
shadow-bypass scanner for the user's crushrc is a denylist and misses real bypasses (~746-749,
859). (4) The 29-name tool snapshot fails open after a crush upgrade (~726-737). Notes 5-8 (git
boundary, literal keys copied from a user crush.json, `/toggle_yolo` as a prompt, crush deny
sessions' DB deleted with the temp dir) are in the report. **Decided 2026-10-14 (operator,
via /steps): leave crush out of deny-mode reviews** — acp-dispatch deny-mode reviews of
untrusted repos run on opencode/agy until the findings are fixed; hardening the fork
remains possible later but is not queued.

## acp-run --perm deny: what the user-config strip still lets through

**Queued 2026-10-13 (adversary review of the deny strip, finding 5). Needs an
operator decision.** Since 2026-10-13 a non-interactive `--perm deny` run starts
opencode and agy without the user's global plugins, MCP servers and hooks
(tools/acp-run/README.md). Still loaded: agy's workspace `.agents/` plugins
(skills, hooks, MCP) in the `-C` dir, and opencode's skills from
`~/.claude/skills` and `~/.agents/skills` (opencode 2.0.27 has no switch for
them). Plugin hooks run code without any tool permission request, so deny and
the exit-77 tripwire cannot see them. Not a regression (the old behaviour
loaded everything), and failover runs in an empty temp dir. **Decide:** should
`--perm deny` against an untrusted `-C` repo (an acp-dispatch read-only review
of someone else's code) refuse, copy the repo without `.agents/`, or shadow
agy's workspace roots, and is opencode's skill loading acceptable?

## acp-run: classify quota and outage failures at the source

**Queued 2026-10-12 (operator, from the acp-dispatch pool-guard work, 4bbf180).
Not started; a cleanup, not urgent.** `acp-run` files zcode's
`1310 [Weekly/Monthly Limit Exhausted. Your limit will reset at <time>]` as a
plain failure and opencode-go's `ServiceUnavailableError` as `fail=transient`,
so `acp-dispatch`'s `failure_class()` re-parses stderr to find quota and outage.
Move that into acp-run: emit `fail=quota` with the reset time for 1310 (and
the other limit phrasings in `failure_class`'s `quota_terms`), and a stable
`fail=outage` for service-unavailable / 5xx / connection failures. Then shrink
`failure_class` to trust acp-run's class. Check first that no live run owns
`tools/acp-run/acp-run` (it was owned by the sipb-bench run on 2026-10-12).

## SkillOpt-Sleep phase 2: pluggable transcript sources and backends

**Queued 2026-10-12 (operator asked for SkillOpt across all agent runs).
Partly done the same day:** zcode, agy and crush adapters ship in
`bin/skillopt_sources.py` (docs/skillopt-sleep.md section 7). Remaining: (1) the
upstream PR offered in microsoft/SkillOpt#314 (entry points for sources and
backends, unknown backend raises, public helpers; per-source checkpoint is
#312), once upstream answers; (2) adapters for Hermes, grok, muse,
cline and acp-dispatch job reports, each with the replay-session filter; (3)
add them to `bin/skillopt-night`'s source loop. Drop the runner's codex shim
when upstream PR 282 merges.

## Research checker: namespace-aware citations across runs

**Queued 2026-10-10 (operator, hiwymi `/loose`). Not started.** Research runs
in one project reuse evidence ids (`E0949` is one row in
`hiwymi/research/ai-heaven/evidence.jsonl` and a different row in
`research/soul-md-autonomy/`). `skills/research/scripts/research_check.py
claims` only checks that a cited id exists in the run's own ledger, so a
finding from another run cited as a bare id passes while pointing at the wrong
source. GPT-6 Astra proposed the fix in the ai-heaven spec dialogue (turn 20,
amendment A8); Grok 4.7 accepted it as rule R-src-5 but did not claim a checker
run (`spec/ai-heaven/notes/grok-phase4-verdicts.md`, Phase 5 rulings, A-8).
Build: a `research_check.py` subcommand (or a spec-side checker) that (1)
resolves every relative link into another run's report by file **and**
fragment, (2) lists every superscript id that also exists in a sibling run's
ledger and shows the cited row's title beside the sentence for review, and (3)
flags any sentence that names another run's report and carries a local
superscript. Lead's hand check of the phase-5 spec (a28fa05, 2026-10-10): no
links into other runs; 5 of 48 cited ids also exist in the soul-md ledger and
all 5 resolve to the intended ai-heaven rows; nothing to fix. Drop this item
when the subcommand ships and the research skill's SKILL.md names it.

## Watch Orca upstream for structural-reorg verbs

**Queued 2026-09-26. Watcher built; waiting on upstream.** We filed
[stablyai/orca#23272](https://github.com/stablyai/orca/issues/23272) (CLI
parity with herdr for move/swap/resize/reorder) and commented on #9632, #12306
and #8766. Run `bin/orca-reorg-watch` periodically (exit 10 = something moved:
an issue/PR changed state or comment count, or the installed `orca` gained a
verb). When it fires: read the change, re-probe `orca terminal --help`, update
`skills/reorg-orca/SKILL.md` §3/§4 (move gaps from "cannot" to "can"), and
refresh the gap list in [upstream-issues.md](upstream-issues.md) §3. Gate to
watch first: PR #15108 (`orca terminal move`). Drop this item when the verbs
in the skill's §4 table have shipped or upstream declines them.

## Quota-aware automatic cross-vendor subagent routing

**Queued 2026-08-23. Not started.** Hindsight initiative page
`kp-2e1513989ca5483ea8709dab2ce6a7f3`.

Automatically choose which vendor's agent runs a given piece of subagent work,
instead of the operator or the orchestrating session hand-picking it. Two
inputs:

1. **Ability/strength profile per service** — what each agent is actually good
   at, which is the judgment half of [model-routing.md](model-routing.md)'s
   "Which AI for which work" section, made machine-readable.
2. **Live quota headroom** — from `aiuse --json`, polled periodically. The
   operator explicitly left room for **faster methods** than polling: a cached
   snapshot with a TTL, a local daemon holding state, or a push/event signal
   if any service offers one. A full `aiuse --json` takes ~1 min, which is far
   too slow to sit in the path of a routing decision.

**Why it's worth doing** (measured 2026-08-23T23:30Z): antigravity, opencode-go,
zai, and devin were all at ~0% used while claude carried the session. That is
paid capacity expiring unused every cycle, and the only reason is that routing
is manual and the human defaults to what's familiar.

**Constraints it must respect** — the standing orders in
[AGENTS.md](../AGENTS.md): free and chronically-unused pools first for bulk;
claude/codex for judgment; **never** bulk-route to clinepass (it is the
Hindsight/hermes lifeline); prepaid tier retired until an operator top-up.

**Open design questions** (not yet decided):

- Where does the router live — a Claude Code workflow, an Orca dispatch layer,
  a standalone binary, or inside `aiuse` itself?
- Does it route *nodes within* a graph (per-subagent) or whole tasks?
- What happens on a wrong call — is there a fallback/retry ladder, and who
  notices the output was worse?
- How does ability-profiling stay honest as models change? (Snapshot dates,
  like everything else here.)
- Does it also decide **effort level**, not just vendor?

## Dynamic self-adjustment of model version and effort by token efficiency

**Queued 2026-08-23. Not started.** Sibling to the routing item above — that
one picks *which vendor* runs work; this one picks *how much thinking* the
current session spends on it.

The session should raise and lower its own model tier and effort level based
on observed **token-use efficiency** — dropping to a cheaper tier or lower
effort for mechanical stretches (file edits, doc writing, command running) and
climbing back for genuine judgment. Today this is manual (`/model`, per-agent
`model`/`effort` overrides) and therefore usually left wherever it was last
set — typically too high, which is exactly the waste this is meant to catch.

**Open questions:**

- What is the efficiency signal? Output tokens per useful action, revision/
  retry rate, tool-calls-per-turn, or something learned?
- Can a session change its *own* model mid-flight, or must this be expressed
  as dispatch to subagents at chosen tiers (which works today)?
- What prevents oscillation, and what prevents a cheap tier from silently
  degrading a task the operator cared about?
- Should it be advisory (tell the operator "this stretch is mechanical, drop
  to sonnet") before it is ever automatic? The operator's instinct on the
  Hermes side was stop-and-prompt first, automate later — same shape here.

## S1 Phase B — foundation landed, adapters next

**Started 2026-08-23.** `site-djbclark/bin/hindsight_s1.py` is in and tested;
the schema is live on `~/.hindsight/candidates.sqlite3` alongside Phase A
(14 candidate rows verified intact). What remains, in order:

1. **Claude tail/checkpoint adapter** — read `~/.claude/projects/*/*.jsonl`,
   one event per record, `source_locator` = byte range + record index,
   resuming from `ingest_checkpoint`. This is the piece that stops the
   ongoing evidence loss: Claude Code garbage-collects those transcripts,
   which already cost us attribution for 15 documents (recorded as the
   store's first `ingest_gap`).
2. **Live Hermes sink** — every committed message/tool event into S1
   idempotently, `state.db` staying source-compatible during migration.
3. **Backfill** — surviving transcripts, MEMORY/USER, candidate store,
   Hindsight export; record historical gaps rather than claiming coverage.
4. **Attachments/tool events**, then trigram/neighbor retrieval alongside the
   exact search that exists.
5. **Backup coverage check** — `snapshot` produces a consistent file via
   `VACUUM INTO`; confirm Arq picks up snapshots and CAS objects rather than
   a live WAL.

## Implement cow — DONE 2026-08-23 (first pass)

Installed (`cow 0.1.10`), configured, and in use.

- **Install:** `brew trust joeinnes/tap` first, then `brew install cow` — the
  plain `brew install cow` in the README fails, there is no homebrew-core
  formula. (Operator did the trust step.)
- **Shell integration:** `cow install` → `cowcd` function + completion in
  `~/.bashrc`.
- **MCP:** registered user-scope, `claude mcp add --scope user cow -- cow mcp`,
  verified ✔ Connected. Being stdio, it needs no daemon and survives reboots
  by construction — Claude Code spawns it per session from `~/.claude.json`,
  and the binary lives in `/opt/homebrew/bin`.
- **Retroactive migration:** `cow migrate --all` in `~/.hermes/hermes-agent`
  converted **8 worktrees** into pastures. `cow stats`: **3.7 GB on disk for
  29.2 GB of logical content.** Two worktrees with uncommitted work
  (`memory-capacity-guard-v2`, `upstream-merge`) were skipped by design —
  migrating them needs `--force` and an operator decision.

**Gotcha worth remembering:** the first migration run failed on every
candidate and rolled each one back cleanly. Cause was an uncommitted
`.gitignore` edit in the source repo (left by an earlier `graft build`),
which blocks branch checkout. Fix was to keep the tracked `.gitignore`
pristine and put graft's ignore rules in `.git/info/exclude` instead — the
right place for tool-local cache rules in a fork that tracks upstream.

**Status 2026-09-20 — proactive use built, Orca half-verified.** The
"automatic cow for all repos" the operator remembered did not exist: nothing
in hooks, settings, cron, LaunchAgents or the ops repos invoked cow. Now:

- `bin/cow-pasture` (this repo) + `skills/cow-workspaces` (live copy in
  `~/.claude/skills/`) are the mechanism: `cow-pasture create <name> --source
  <repo> [--orca]`. Nothing runs unprompted; turning it off = delete the skill.
- **Secrets, verified:** `cow create` copies gitignored `.env` (and its `uchg`
  flag) into the pasture — tested on a throwaway repo and on `~/src/aiuse`.
  The wrapper scrubs gitignored secret-like files by default.
- **Scope decided:** primary checkouts under `~/src`, `~/orca/projects`,
  `~/.hermes`; never `~/ops/*` (wrapper refuses). Linked worktrees
  (`core-*`, `libntech-*`, `ss-*`, `ralph-tui-*-plugin`) are ineligible.
- **Orca:** `orca repo add --path` makes `worker-start --worktree path:` resolve
  (verified: worktree reused, terminal created). The dispatch then stalled at
  `agent_readiness` because **Claude Code's folder-trust dialog fires in any
  new directory** and Orca has no Claude trust preset (it has Codex/Cursor/
  Copilot ones). Operator decision pending on the mechanism; end-to-end
  `worker_done` not yet observed. See `docs/orca-integration.md`.
- "Compact into cow" = reclaim disk by migrating (operator, 2026-09-20);
  the dirty Hermes worktrees stay un-migrated until their changes are
  committed or discarded (no `--force`).

Still to do: finish the Orca end-to-end test once the trust mechanism is
chosen; teach Hermes's `headless-agent-orchestration` skill to call
`cow-pasture` instead of bare `cow create`; `cow gc --merged` pass on the
Hermes pastures with the operator's go.

**`~/src/ops-worktrees/` (13 dirs, 492MB) — surveyed, needs an operator
decision, do not bulk-delete.** These belong to the retired regime and sit on
their own bare store (`~/src/ops-worktrees/.store/*.git`), so `cow migrate`
from `~/ops/*` finds nothing — they would have to be migrated from the store.
Before anything is deleted or migrated, note that **10 workspaces still hold
live work**:

| workspace / repo | dirty | unmerged commits |
|---|---|---|
| `secretspec-drift-hardening/stayturgid` | 30 | 0 |
| `secretspec-drift-hardening/site-djbclark` | 24 | 0 |
| `secretspec-drift-hardening/site-private` | 7 | 0 |
| `stayturgid-2.0/stayturgid` | 1 | **4** |
| `archive-maynarddaycare-pages/site-private` | 1 | 1 |
| `cloudflare-operator-token-declaration/site-private` | 1 | 1 |
| `find-hub-integration-plan/site-private` | 1 | 1 |
| `coderabbit-feeder-workspace/Shizuku` | 0 | 1 |
| `coderabbit-feeder-workspace/RevengeQuickSwitcher` | 1 | 0 |
| `agent-communication-harness/ops-djbclark` | 2 | 0 |

`secretspec-drift-hardening` (61 uncommitted files across three repos) and
`stayturgid-2.0` (4 unmerged commits) are the ones with real work at risk.

**Migration attempted 2026-08-23 and BLOCKED — cow cannot do it.** These are
worktrees of bare stores under `~/src/ops-worktrees/.store/*.git`, and cow
refuses both ends: from a worktree it errors *"is a git worktree, not a
primary repository"*, and from the bare store *"No VCS found at source"*
(also via `cow create --source`). There is no primary working checkout in
that layout for cow to clone, so `cow migrate` is not a path here. Nothing
was moved or deleted.

**Safety net in place** (`~/ops-worktrees-preserved-2026-08-23/`, 1.3MB,
durable — not in `/tmp`): per workspace, the branch name, `git diff HEAD` as
a patch, `status.txt`, the unmerged-commit list, and a `format-patch` series.
**9 of 10 uncommitted patches verified applicable** via
`git apply --check --reverse`; the tenth had no diff, only an unmerged commit
(exported). A full CoW copy also exists in the session scratchpad, but that
lives under `/private/tmp` and should not be relied on.

**Recommended endgame** (operator decision — do not bulk-delete unasked):
the worktree regime is retired, so the goal is not to move these into cow but
to *land or archive* the outstanding work and reclaim 492MB. Per workspace:
apply the patch onto the matching repo in `~/ops`, commit and push, then drop
the workspace. `secretspec-drift-hardening` is the one that needs real review
rather than a mechanical replay.

### Original decision record

<https://github.com/joeinnes/cow> · `brew trust joeinnes/tap && brew install cow`.

### Baseline measured 2026-08-23 (step 1 partly done)

Benchmarked `cp -c -R` against `cp -R` on `~/ops/stayturgid` (677MB) on this
machine's APFS root volume. **CoW engages, and the win is space, not speed:**

| | wall clock | disk actually consumed |
|---|---|---|
| plain `cp -R` | 43.8s | 677 MB |
| CoW `cp -c -R` | 10.7s | **~10 MB** |

So ~4× faster but ~67× cheaper on disk. Note the gap with rift's marketing
claim of "<0.1s on a 10GB folder" — 10.7s for 677MB is nowhere near that, so
treat any tool's speed claim as unverified until measured here. Whatever we
adopt, the reason is space and dependency reuse.

**Two caveats found while measuring, both of which argue for a tool over the
raw baseline:**

- `cp -c -R` copies **everything**, including `.env`. An agent workspace made
  this way inherits real secrets. This is exactly what cow's/rift's
  "excludes artifacts and dependencies by default" is for — but confirm cow
  excludes *secrets*, not just `node_modules`.
- The copied `.env` carried the `uchg` (user-immutable) flag, so the test
  clone refused to delete until `chflags -R nouchg`. Any cleanup/GC path
  needs to handle immutable flags or it will strand workspaces.

Remaining for step 1:

1. **Install cow — the documented path does not work.** `brew install cow`
   fails (no such formula in homebrew-core; brew suggests `crow`/`cot`/`cog`).
   Find the real install route — a custom tap, `cargo install cow-cli`, or a
   GitHub release — and confirm the MCP server actually ships with it before
   committing to the tool.
2. Wire the agents, which is the point: `cow` ships an **MCP server** and
   Claude integration via environment variables, so start there rather than
   writing an adapter. Register it the way `hermes` was registered
   (`claude mcp add --scope user`), then teach Hermes about it — its
   `headless-agent-orchestration` skill currently creates worker workspaces
   the old way.
3. Point Orca macro-graph dispatch at it (`worker-start --worktree` is the
   highest-volume workspace creator here, so it is both the best payoff and
   the safest place for a first failure).
4. Decide what happens to `~/src/ops-worktrees/` — now that the
   worktree/PR/release regime is retired, that layout has much less reason to
   exist, and cow workspaces may replace it outright.
5. Keep the plain-git baseline (`git worktree add --no-checkout` +
   `cp -c -R`) documented as the fallback, so nothing hard-depends on a tool
   we can drop.

### Rationale — the options that were considered

Every parallel-agent workflow here creates workspaces — Orca macro-graph
dispatch (`worker-start --worktree`), Hermes's `headless-agent-orchestration`
(one isolated workspace per worker), Claude Code's own worktree isolation.
`git worktree` pays a full checkout each time and gives you none of the
untracked state (`node_modules`, build output), so every new workspace needs a
reinstall before an agent can do anything. Filesystem copy-on-write fixes both
at once. Candidates, with what actually distinguishes them:

| Option | Shape | Notes |
|---|---|---|
| **Plain git + CoW copy** | no new dependency | `git worktree add --no-checkout ../ws` then `cp -c -R . ../ws` (macOS APFS) or `cp --reflink=always -R . ../ws` (btrfs/XFS). **This is the control** — any tool has to beat it to earn its install. |
| [cow](https://github.com/joeinnes/cow) | `brew install cow` / `cargo install cow-cli` | **Explicitly built for running multiple coding agents in parallel.** APFS `clonefile`, reflinks on btrfs/XFS, falls back elsewhere. Ships an **MCP server** and Claude integration via env vars, plus create/list/remove/sync/extract and run-inside-workspace commands. The only candidate where the agent wiring already exists. |
| [rift](https://github.com/anomalyco/rift) | `npm i -g rift-snapshot` | Same CoW idea; claims <0.1s on a 10GB folder, excludes build artifacts by default, `.rift.toml` pre/post-create hooks, JS/Bun FFI. **Experimental, no agent integration** — that wiring would be ours. |
| [jj (Jujutsu)](https://github.com/jj-vcs/jj) | different VCS, Git-compatible | Not a CoW-workspace tool — a broader bet: no staging area, first-class conflicts, operation log with undo, working-copy-as-commit, and good multi-workspace ergonomics. Git-backed so existing tooling keeps working. Still pre-1.0 with breaking changes possible. Solves more than the workspace problem, and costs more to adopt. |

Background reading: [Git without the clone — durable versioned workspaces for
AI agents](https://pub.towardsai.net/git-without-the-clone-durable-versioned-workspaces-for-ai-agents-b280241fe5ca).

**Why cow won:** its MCP server means Hermes and Claude can drive it without
us writing an adapter, and it is the only candidate built explicitly for
running coding agents in parallel. Caveat carried into implementation: that
is a README claim, not yet a measurement — step 1 above exists to check it.

**`jj` remains open and separate.** It is a different and larger bet (a whole
VCS), it solves more than the workspace problem, and choosing cow does not
foreclose it. Worth its own evaluation another time.

## Completed 2026-08-23 (kept briefly for reference)

- **`~/src/ops-worktrees/` retired and deleted** (491MB reclaimed). Before
  deleting, every branch was verified present on a remote and all
  uncommitted + untracked work preserved *in git*, not as loose patches:
  `feature/agent-communication-harness` (a 14.6KB untracked
  `agent_communicate.py` that `git diff HEAD` had missed entirely),
  `feature/secretspec-drift-hardening` across all three repos (18 untracked
  files — the sudo-secretspec broker, installer, drift-check, audit lib and 8
  test files, **none of which existed in master**), and three unpushed
  branches now on origin. The *tracked* edits in secretspec-drift-hardening
  were confirmed superseded — they modify files the merged PRs deleted — and
  were discarded deliberately. Backups deleted afterwards.
- **Upstream issues filed**: [NanoNets/Graft#185](https://github.com/NanoNets/Graft/issues/185)
  (statusline says "not built" for a built-but-empty graph) and
  [vectorize-io/hindsight#3735](https://github.com/vectorize-io/hindsight/issues/3735)
  (config keys read but undocumented).
- **Stray banks removed**: `hermes-telegram` and `herdr-shared`, both last
  written 2026-08-11 and holding only retention-pilot `candidate-*` docs, with
  no live config referencing them. Exported to `~/hindsight-backups/` first —
  the discipline the earlier `hermes-default-hermes` mistake earned. Bank
  topology is now exactly 11 per-repo banks plus `hermes-shared`.
- **cow rolled into the agent stack**: Hermes's `headless-agent-orchestration`
  skill now says to use `cow create --print-path` for worker workspaces,
  with the two rules that bit us (source tree must be clean; a pasture carries
  `.env`). The Orca composition (`--worktree path:$(cow create … --print-path)`)
  is documented in [orca-integration.md](orca-integration.md) but **not yet
  exercised in a live dispatch**.
- **S1 Hermes event sink** built and backfilled (`bin/hindsight_s1_hermes.py`,
  13 tests).

## Ingest web-interface AI conversations into the memory system

**Queued 2026-08-23. Not started.**

Conversations held through AI *web* interfaces — especially Gemini and Grok —
are currently invisible to the memory system. S1 ingests Claude Code
transcripts and Hermes's `state.db`; anything typed into a browser is lost to
it. That is a real hole: web sessions are where a lot of exploratory thinking
happens, and they are exactly the "disjoint conversations with no repo" shape.

Scope both directions:

- **Backfill** what already exists in those accounts.
- **Ongoing capture** so future web conversations flow in without ceremony.

### VESTI assessed 2026-08-23 — right tool for most of it, one real gap

[abraxas914/vesti](https://github.com/abraxas914/vesti) (心迹, TypeScript,
public, local checkout at `~/src/vesti`, also an Orca project) describes
itself as a *"local-first AI conversation memory hub to capture, search,
summarize, and export chats across major AI platforms"* — which is exactly
this problem, already built.

**What it covers.** A Chrome extension silently captures conversations on
**ChatGPT, Claude, Gemini, DeepSeek, Qwen and Doubao**, extracting full
multi-turn content with timestamps and platform metadata, deduplicating, and
persisting to local IndexedDB. No manual export step, no tagging.

**The gap: Grok is not supported.** The platform list above is exhaustive, so
half of what was asked for needs a new capture adapter. That is the honest
cost of choosing VESTI — everything else it gives us free.

**How the integration would work.** The extension exposes a clean
`StorageApi` contract (`packages/vesti-ui/src/types.ts:412`) —
`getConversations`, `getMessages`, `getTopics` — and supports
`ExportFormat = "json" | "txt" | "md"`. So the data is reachable; the only
question is transport out of IndexedDB, which a browser extension cannot
write to arbitrary paths from. Options, cheapest first:

1. **Manual JSON export → S1 adapter.** Fine for the *backfill* half. A
   `vesti` producer adapter is the same shape as the Claude and Hermes ones
   (~150 lines): one S1 event per message, `source_locator` = conversation +
   message id, resuming by id.
2. **A localhost receiver.** Implement an alternate `StorageApi` backend, or
   a small mirror hook, that POSTs each captured conversation to a tiny local
   endpoint which appends to a file S1 tails. This is the clean answer for
   *ongoing* capture and keeps the extension's local-first property.
3. **Read the extension's IndexedDB from the Chrome profile directly.**
   Works without touching VESTI, but couples us to LevelDB internals and
   breaks whenever the schema moves. Fallback only.

**Recommendation:** option 1 to backfill, option 2 for ongoing, and treat
Grok as separate work — likely its own capture adapter in VESTI (upstreamable)
rather than a bespoke scraper here.

Still worth comparing for the backfill: each vendor's official export (Google
Takeout for Gemini, X/Grok export) is bulk one-shot — useless for ongoing
capture, but it needs no extension and no browser session.

Where it lands: **S1** is the right home for the raw conversations (it already
holds 448k events and is producer-agnostic — a `gemini` / `grok` adapter is
the same shape as the Claude and Hermes ones). Curated takeaways belong
wherever curated memory ends up, not in the transcript store.

Watch for: exports are bulk one-shot (fine for backfill, useless for ongoing),
and anything scraping a logged-in session needs care with credentials and
terms of service.

## Token-cost hygiene (from video analysis, 2026-08-24)

Analysed <https://youtu.be/V0XbuApxlhg> ("You're Paying Anthropic 20x MORE
Than You Need To") against
[code.claude.com/docs/en/costs](https://code.claude.com/docs/en/costs).
Transcript pulled with `yt-dlp --write-auto-subs` — a YouTube page fetch
returns only the title.

**Its central claim holds and the docs confirm it:** the full conversation is
re-sent on every request, prompt caching re-reads that history at the cached
rate, and the cache lifetime is **one hour on a subscription** (five minutes
on usage credits or API keys). A one-line question in an all-day session
still draws usage for the whole conversation.

**One claim is unverified.** The video lists actions that supposedly reset the
cache outright — switching model, changing effort, fast mode, connecting an
MCP server, plugins, denying a tool, upgrading Claude Code. **None of that
appears in the docs**, which describe cache misses purely in time terms. Do
not repeat it as fact; it matters because it would make mid-session
`/model` switching costly, which is advice we give.

Actionable here, in order of expected value:

1. **Run `/usage` and `/context`.** `/usage` attributes recent usage to
   individual skills, subagents, plugins and MCP servers. That measures our
   31 skills and 7 MCP servers instead of guessing at them, and flags
   behaviours (long context, cache misses) accounting for >10% of usage.
2. **Run `/insights`.** Not previously known here: it analyses recent
   sessions and writes `~/.claude/usage-data/report.html` covering friction
   points — misunderstood requests, buggy code — rather than token counts.
3. **Keep instruction files lean.** Docs say aim for **under 200 lines** and
   move specialised instructions into skills, which load on demand.
   `djbclark-ade/AGENTS.md` is **180 lines** and grew substantially on
   2026-08-23; `site-private/home-agents.md` is 135. Both load in an ops
   session. Trim before adding more.
4. **Consider `ENABLE_PROMPT_CACHING_1H=1`** — preserves the one-hour cache
   lifetime while drawing on usage credits. Currently unset.
5. **Prefer `/clear` over `/compact`** between unrelated tasks: clearing
   costs nothing, while compaction reads the conversation it summarises and
   is itself a large request.

**Good news the video implies otherwise about:** MCP tool definitions are
*deferred by default* — only names and server instructions enter context
until a tool is used — so our seven servers cost far less than the video's
framing suggests. Verify with `/context` rather than pruning on instinct.

**Also worth knowing:** agent teams use roughly **7x** the tokens of a normal
session, and scheduled tasks send full context on every fire even while the
session is idle.

Not adopted: the output-token scaffolds (ponytail, caveman, "be brief" one
liners). The video rates them least effective, and output tokens are the
smaller half of the problem.

## Review the Copilot subscription ($29/mo)

**Queued 2026-08-24. After the current loose ends.** Corrected from an
inferred $10 — it is the **$29/month** tier, which makes it the third most
expensive plan on the fleet after claude ($100) and grok ($30).

What makes it worth a deliberate look rather than a reflex cut:

- Its measured peak draw is ~30%, so it is genuinely used, unlike the
  never-drawn plans.
- But it is **`access: forbidden`** for everything except GitHub's own
  clients — it cannot be routed to by Hermes or used as a general model
  provider, so it contributes nothing to the shared pool.
- The question is therefore narrow: is GitHub-native PR review and repo Q&A
  worth $29/mo *on its own*, given `gh` CLI plus any routable model can do
  much of the same work at no marginal cost?

Do this once the plan ranking has ~14 days of history, so the utilisation
figure means something.

## Monthly plans that work with Hermes — researched 2026-08-24

**Short answer: ClinePass is unusual, and that is why it works.** The
industry pattern is that a flat monthly subscription buys access through the
vendor's *own clients*, while programmatic access is a separate pay-per-token
API. ClinePass is a flat-rate **API-key bundle**, which is exactly what an
agent like Hermes needs.

Checked:

| Plan | Monthly? | Usable by Hermes? |
|---|---|---|
| **ClinePass** ~$9.99 | yes | **Yes** — flat-rate API key bundle. Currently our only paid Hermes pool |
| **z.ai GLM Coding** $18 / $72 / $160 | yes | **No, as written.** Ships an OpenAI- *and* Anthropic-compatible endpoint (the only drop-in Claude Code replacement besides Anthropic), but the plan is explicitly *"limited to officially supported coding tools and is not a general API subscription"*. Hermes is not one of the 20+ supported tools |
| **Kimi / Moonshot** $19 Moderato, $99 Allegro | yes | **No** — consumer plans cover chat plus Kimi Code credits; the Moonshot API is separate pay-per-token (~$0.60–0.95/M in) |
| Google AI Pro $19.99 | yes | **No** — chat interface only, API bills separately |
| ChatGPT Plus $20 | yes | Tolerated but not committed; reserved for coding anyway |
| GitHub Copilot $29 | yes | **Forbidden** for third-party clients |

**Implication.** There is no obvious second flat-rate pool to add. The
realistic ways to widen Hermes's supply are: a second ClinePass-style bundle
if one appears, pay-per-token API credit (openrouter/deepseek — the retired
prepaid tier), or **upgrading the z.ai plan only if their terms change**.
Worth re-checking periodically; this category moved fast in 2026.

Also noted for the plan review: z.ai's tiers are **Lite $18 / Pro $72 /
Max $160**, so there is headroom to buy more of a pool we already use — via
the zcode TUI, not Hermes.

## Also outstanding (raised, not formally queued)

- **Restart the `hindsight` MCP server** in any long-running session started
  before 2026-08-23 20:00 — it caches the bank it launched with and will keep
  writing to `hermes-shared`. New sessions are fine.
- **Confirm-then-delete two leftover banks**: `hermes-telegram` (5 docs) and
  `herdr-shared` (1 doc). Left in place because a running gateway may still
  write to them.
- **`just ops-memory-sync` is failing for site-djbclark** —
  `docs/plans/memory-architecture-v2.md` is unreleased past ops-v1.3.26.
  Needs a release cut or a revert.
- **File the two upstream issue drafts** in
  [upstream-issues.md](upstream-issues.md) — operator decision, they go to
  third-party trackers.
- **Type `skills/session-finder/launch.py`** (decided 2026-10-09: leave for
  now): basedpyright with default rules reports 52 pre-existing errors there
  (untyped launch-record dicts, Optional access in the helm-reply path); the
  tests pass and both test files are clean. A separate typing pass, not a
  blocker.
- **`cow-pasture remove A B --force` ignores `--force` with several names**
  (seen 2026-10-09): the first dirty pasture prints "Not a TTY — defaulting
  to no" and nothing is removed; one name per call works. Fix the flag
  handling in `bin/cow-pasture`.
- **Herdr-only ADE capabilities, Orca parity gaps** (surveyed 2026-10-09,
  after `bin/self-slash` gained its Orca backend). Refuse in Orca:
  autorename's `relocate-pane.sh`, `launch.py start_tui` (zcode/muse).
  (`/orc`, `/orc-meta` + `orc_watchdog.py` and herdr-orchestration were
  retired 2026-10-09 instead.) Silent skips:
  autorename placement (`herdr_place.py`), the herdr SessionStart hook
  (Orca's own hook covers it). Degraded: `launch.py close` leaves Orca
  terminals open; acp-run reports agent state only to herdr; helm/fleet mark
  non-Claude Orca TUIs `unknown` (tidy.py's Orca status merge could be
  reused); bigteam Step 0 and session-finder rung d describe only herdr;
  `where.py` uses a possibly stale `$ORCA_TERMINAL_HANDLE`. Easy wins:
  `orca terminal close/rename/create --command/send`. No Orca equivalent:
  moving a terminal between worktrees, reporting agent state into an Orca
  terminal. herdr-sleeper needs no port (Orca Agent hibernation).
  **Done 2026-10-09 (easy wins):** `launch.py close` now closes the Orca
  terminal a launch was hosted in (`orca terminal close --terminal`, skipped
  for the caller's own terminal and for handles Orca no longer lists; test
  `tests/test_launch_orca_close.py`; verified live 2026-10-10, which found and fixed a
  `terminal create` handle-parse bug and failed starts and closes leaving their claim blocking the repo); autorename needs no Orca step (Orca's
  terminal title already follows the session's `custom-title` record; noted in
  its SKILL.md); bigteam Step 0 and session-finder rung d now give the Orca
  commands. **Still queued:** `launch.py start_tui`, acp-run agent-state reporting into Orca,
  helm/fleet `unknown` status for non-Claude Orca TUIs, `where.py` stale
  handle, `terminal create --command/send` as a herdr-pane substitute.

## Re-check Context7 use (on or after 2026-10-24)

Added to Claude Code 2026-10-09; kept on 2026-10-10 (~0.2k tokens/session) while
Claude Docs and other connectors were cut (docs/disabled-skills.md). Count
`mcp__claude_ai_Context7__` calls in `~/.claude/projects/*/*.jsonl` since
2026-10-10; if still ~0, ask djbclark whether to block it too. Firecrawl
(~5.6k/session, ~250 calls/week) is the costly one; see the same doc.


## Orca's short PostCompact hook (watch stablyai/orca#25211)

Orca adds a ~3 KB shell wrapper as Claude Code's `PostCompact` hook. Claude Code
prints it after every `/compact` and keeps it in context (~1k tokens). Orca rewrites
`~/.claude/settings.json` on each start, so a local edit does not stick. Upstream:
issue stablyai/orca#25209 (we +1'd and commented, 2026-10-10) and fix PR #25211.
The fork carries the fix as branch `djbclark/short-postcompact-hook` (upstream
`main` + the PR commit, rebased 2026-10-10, **not built**). Build it only if
djbclark asks; once a release ships #25211, delete that branch.

## Review the Jev-vs-GLiDE dual review — DONE 2026-10-25 (findings; djbclark chose Jev-only shadow)

**Started 2026-10-11 (operator).** The Jev-only prompt-effort review was closed the
same day; see `docs/jev.md` "Dual review". Jev and GLiDE answer the same prompt-effort
(hook) and agent-choice (`route_agent.py --brief`) questions side by side for at most 12
days; the window closes itself (mode goes off). On 2026-10-23 run
`bin/jev report --review dual-1 --json` and `bin/jev disagreements --site
agent-choice --between`, label disagreements, then ask djbclark per backend: act, keep
shadow, or off. A self-removing launchd job (`com.djbclark.jev-remind-2026-10-23`)
pings Hermes that morning.

**Outcome (2026-10-25).** Report `jev-dual1-review-report.md` (bigteam task `ade-queue-build-2026-10-24`): nothing met the promotion bar. The agent-choice rows are 97.5% pytest fixtures; every timeout
hit both backends at once (shared deadline); 44% of prompt-effort rows are Herald voice-announcer prompts; no operator labels exist. On 36 decided disagreement rows (one agent's reading) GLiDE was
right 21, Jev 11, neither 4. djbclark chose to restore Jev-only shadow: `bin/jev review stop` and `~/.config/jev/backends` removed (copy was `jev,glide`), mode `shadow`. Findings a later window would need:
fixtures run with `JEV_MODE=off`, the hook skips non-human prompts, the report's default `--since` follows the review window, separate deadlines per backend, a per-site backends setting.


## Why the `sed` edit failed twice (queued 2026-10-14, operator) — DONE 2026-10-14

Cause: macOS BSD `/usr/bin/sed` rejects `1{/^$/d}` (`extra characters at the end of d command`; BSD needs
`1{/^$/d;}`), and the redirect still created an empty `body.md`, which `gh issue create --body-file` filed
(libkrun#926). GNU sed is installed as `gsed`. Fixed in `~/CLAUDE.md` item 33 (`home-agents.md`, site-djbclark
`0e3fbf4`; `cursor/home-agents.mdc` likewise): never feed a `--body-file` from a pipeline, check `[ -s f ]`
first, use `gsed`. Memory: `feedback_exit_status_through_pipe.md` (site-private `e5c12bd`). The forgejo skill
scripts have no `--body-file` use, so they needed no guard.

## Flaky MockWebServer tests on the SIPB runner — DONE 2026-10-14

Root causes found with a Python churn repro, a standalone okhttp 4.11 MockWebServer loop (`java-churn/`) and C probes
(`duplex-probe.c`, `reuse-probe.c`, `dup-bind-probe.py`), each checked against a normal Linux kernel (Ubuntu 24.04
container): (1) the shim's port seed repeated within a second, so consecutive servers got the same port, and
libkrun TSI keeps a listener closed during a blocked `accept()` alive (libkrun#929); (2) a blocked `recv()` blocks
`send()` on the same socket, which stalled WebSocket clients (libkrun#819/#926); (3) TSI sockets always have
`SO_REUSEPORT` (libkrun#860), so duplicate listens succeed. Fixed in `loopback-port-shim.c` (new seed plus ring of
recent ports; wait in `poll()` before blocking reads and accepts). The full Plektra suite (1,417 tests) now fails only
`CornerButtonThemeTest` (also fails on GitHub Actions and a laptop), in runs 229 and 230 in a row, 3 m 4 s test step.
Tickets updated: libkrun#926 (retitled, comment), #819, #860, new #929; SIPB/hyades#2 comment 25. Wrong turns, kept
because they cost time: a Python keep-alive repro that was negative (and had its own acceptor bug), `SO_RCVTIMEO` is not
honoured under TSI (use `poll`), and `forgejo-api --help` was run once by mistake (posted nothing).
The 3-of-20 `reuse-probe` failures with the shim were stale listeners leaked by earlier no-shim runs on the same fixed port
(each swallows one connection, then they are gone within 60 s); on a clean port the shim gives 60 of 60 at gaps of 0 to
50 ms (runs 235, 236; libkrun#929 corrected). Checked 2026-10-14 evening: no new upstream replies on
libkrun#819, #860, #926 or #929 after ours (#860's maintainer note is from 2026-09-22). SIPB/hyades#2 and
libkrun#924 did get maintainer replies; they are recorded in the `forgejo-ci` skill (keep Plektra's ext4 loop
image; do not pursue writeback, extra virtiofs workers, or DAX). `CornerButtonThemeTest` is an upstream Plektra issue.

## Make the loopback shim available by default on forgejo.mit.edu, then ask SIPB (queued 2026-10-14, operator)

**Start only after the shim works perfectly**: the `reuse-probe` residue is explained (done 2026-10-14: stale listeners leaked by earlier
rounds, not the shim), and a few more full-suite runs stay clean (two so far, runs 229 and 230).

1. Look into how the shim (`loopback-port-shim.c` (in the new repo, `~/src/loopback-port-shim`)) could always be used by
   forgejo.mit.edu jobs, where appropriate: for example baked into the runner image or the `ubuntu` label's base
   image, loaded through `/etc/ld.so.preload` by the runner or a container entrypoint, or a shared setup action; and
   when it is not appropriate (jobs that never use loopback, jobs that bring their own network setup, anything that
   relies on `shutdown()` or blocking-read semantics). Check what SIPB controls (image, runner config) versus what a
   job can do (the derived workflow builds it with `gcc` in about 1 s today, needing `gcc libc6-dev` installed first),
   and whether a precompiled shim would do (musl/glibc, arm64/x86_64).
2. Then open a ticket on SIPB/hyades with that request and links to all the shim code and evidence: the shim, the
   probes (`duplex-probe.c`, `reuse-probe.c`, `dup-bind-probe.py`, `java-churn/`), `skills/forgejo/SKILL.md` item 5,
   the numbers (suite 7 failures to 1; 800 MockWebServer iterations in 1 s instead of 150 s), and the libkrun tickets
   (#818, #819, #860, #926, #929). Link it from SIPB/hyades#2. Show the draft to djbclark before filing, and state
   plainly that the real fix belongs in libkrun's TSI driver.

**Progress 2026-10-14.** Step 1 is done: `docs/shim-by-default.md` in the new repo (how jobs run, the six ways to
get the shim into jobs, why not global yet, alternative job images with measured pull times). Step 2 is FILED (2026-10-14, djbclark approved
the draft): https://forgejo.mit.edu/SIPB/hyades/issues/3, linked from SIPB/hyades#2 (comment 28); text in
`docs/tickets/sipb-hyades-shim-request-draft.md` in the new repo. Verified along
the way: the shim builds and works identically on the ubuntu, alpine and rocky labels (run 238); job-level `container:`
works on the runner (run 239; `ghcr.io/cirruslabs/android-sdk:36` pulled in 47 s and already has SDK 36, but JDK 21 and no
`node`); curl -L download speed 79 to 102 MB/s and `mount -o remount,dax` does nothing (run 237, SIPB/hyades#2 comment 26).

**Answered 2026-10-14 evening. Do not re-ask.** @xy on #3: passt for the CI runner only (not Hyades) until upstream TSI fixes; the shim may enter ci-images only after a human has reviewed and understood the code. djbclark's comment 69: he will not review the C, and SIPB may close the ticket. Plektra keeps the opt-in preload in `ghcr.io/djbclark/ci-image-plektra`. If SIPB enables passt for CI, re-run the suite without the shim before removing it. #2's disk reply is the same day's `forgejo-ci` skill update: keep the ext4 loop image.

3. **Make the forgejo skill cover all of this** (added 2026-10-14, operator: "Make a forgejo skill, and include proper use
   of shim and image selection in it, as well as anything else useful we have discovered"; the request said "forgego",
   read as forgejo). A `forgejo` skill already exists (`skills/forgejo/SKILL.md`: API, tokens, tea/fj, git, some CI
   notes); extend and reorganise it, or split a CI half into its own skill if SKILL.md gets too long, decided when doing
   it (a new skill goes in `skills/<name>/` here, `docs/skills.md`). Include at least: (a) when and how to use the shim
   (opt-in snippet, the three TSI behaviours in one paragraph, what it does not cover: Go and static binaries; `SO_RCVTIMEO`
   is not honoured under TSI, so use `poll`); (b) image selection: stock labels and what they lack, job-level `container:`
   overrides, images are never re-pulled (pin by digest), `actions/checkout` needs `node` in the image, measured pull
   times, our own image if built; (c) how to run and read probe workflows (`push-probe.sh`, waiting on a run, reading a
   job log by API, `exit 124` meaning, line-buffer output, use a fresh port per run because stale listeners drain over about
   a minute); (d) runner facts (capacity 4, one krun microVM per job, shared host loopback, labels to images, resources);
   (e) ticket etiquette learned (search before filing, wait for testing, label AI preparation, correct yourself in the
   ticket, `forgejo-api` never `--help`, `--body-file` guard); (f) the suite results and what still fails
   (`CornerButtonThemeTest`); (g) the SIPB and libkrun ticket map. Keep SKILL.md under about 200 lines and push detail
   into `docs/*.md` of the new repo.

4. **Build our own CI image: DONE 2026-10-14** (operator said yes; hosted on public ghcr.io, built by GitHub Actions for amd64).
   `ghcr.io/djbclark/ci-image-plektra` (canonical repo forgejo.mit.edu/djbclark/ci-image-plektra; GitHub mirror builds it; local `~/src/ci-image-plektra`):
   `FROM ghcr.io/cirruslabs/android-sdk:36` + JDK 17 + node 18 + `/usr/local/lib/portshim.so` (source pinned by commit
   `SHIM_SHA`). Run 240 on the runner: `actions/checkout` works, the shim fixes the duplex stall and 20 of 20 reuse rounds.
   `DERIVE_IMAGE=ghcr.io/...@sha256:<digest> push-bench.sh asis BRANCH` runs the full suite on it (run 241). Remaining: bump
   the digest when the Dockerfile changes; ask SIPB (in #3) whether they prefer to host the image themselves.
5. **forgejo skill: DONE 2026-10-14** as the new `skills/forgejo-ci/` (CI half split out of `skills/forgejo`; evidence in
   `docs/runner-notes.md` of the new repo), linked into every TUI with `skill-everywhere`, rows in README and `docs/skills.md`.
6. **Public shim repo: DONE 2026-10-14, and it is now the only home** (operator: "move to just using the new repo"):
   https://forgejo.mit.edu/djbclark/loopback-port-shim (MIT; local `~/src/loopback-port-shim`): shim, probes, docs, ticket texts,
   probe workflows, `ci/tools/` scripts, and the `forgejo-ci` skill (`skills/forgejo-ci` here is a symlink into it).
   `skills/forgejo/examples/plektra/` is a README pointer with an old-name to new-path table (tickets already filed link there).
   SIPB/hyades#3 body points at the repo (comment 30). Every link in the filed issues (libkrun #819, #860, #926, #929; SIPB/hyades #2, #3) was edited to
   point at the new repo too (2026-10-14); the README there has a "What is not in this repository" section (local-timings.md, generated workflow,
   the general forgejo skill, pre-move history). The CI image's Dockerfile now pins the new repo's commit; rebuilt, digest
   `sha256:90a5de59e4a7efaa70b4de6af3221023151a2087cfb2689cecfe18a6a1cf602e`, run 242 passed. Nothing left.

## `hermes` route in relay.py (asked via the load-watch session, 2026-10-23)

Relayed by the load-watch session (ac1d55cc) as djbclark's ask: agents should be able to message the live Hermes
gateway agent with `relay.py`. Design: `~/.local/state/bigteam/loadgate-followup-2026-10-23/hermesbidi-report.md` (Q4).

1. **Verified 2026-10-23** on a throwaway oneshot session (`~/.local/state/bigteam/relay-hermes-route/`):
   `hermes --resume SID -z TEXT` with stdin closed replied from the earlier turn's context, grew the same session
   from 2 to 4 messages and created no new one; an unknown sid exits 1 with "session not found" and creates nothing.
   **Real gateway run 2026-10-23** (load-watch session relayed djbclark's yes): `relay.py hermes:16790ed2` (Telegram topic
   inbox-ops) rc 0, `delivered`, reply `RELAY OK`, stored user row tagged `[relay from djbclark-ade-61]`,
   0600 lock free afterwards (`message_count` is a per-run counter a `-z` turn rewrites, not the transcript size: the session
   has 4102 message rows); evidence in `~/.local/state/bigteam/relay-hermes-route/real/`.
2. **Built; adversary rounds 1 and 2 BLOCKed, repaired** (reports in `~/.local/state/bigteam/relay-hermes-route/`,
   `adversary-report-1.md`, `adversary-report-2.md`): route `hermes` in `skills/session-finder/relay.py`
   (`route_hermes`, the only route for a `hermes-gw` row with a `sid`; no fallback), `TestHermesRoute` in
   `tests/test_relay_fallback.py`. Round 1: exact not-found match, no self-relay, no kill, scrubbed env, reply as data.
   Round 2: started line before the wait and floor 100 s (a caller's own tool timeout), per-conversation flock, a
   nested relay tagged as Hermes, self-refusal by chat identity, `ACP_OPERATOR_APPROVED` scrubbed, 0600 reply files with
   pruning, format characters stripped, hop claim narrowed to nested `hermes -z` turns. Round 3 was APPROVE (below).
   The later `fleet.py` agent_close fix (4572876) had no adversary round of its own: a read-only SQL change, covered by a
   unit test and checked on the real database.
   Open by design: **R1-M2** (a relay while the gateway is mid-turn: `fleet.py` fixes the row at `idle`, and the
   gateway's cached agent may not see the relayed exchange until it reloads; "delivered" means "ran on the stored
   transcript"), **R1-L4** (the exchange is invisible in the chat but is history for djbclark's next turn; consider a
   one-line chat notice), **R2-L6** (a profile Hermes with its own `HERMES_HOME` gets "not sent" for another profile's conversation;
   documented). Hop counting across non-Hermes routes (R2-M3) is not enforced: documented as nested-`-z`-only.
   **Round 3: APPROVE at a70d792** (`adversary-report-3.md`); its M1-M3 and L4/L5/L6a/L8 are repaired in the next commit
   (claims made true about a caller's tree-kill, session-key self-refusal for desktop, real-process lock test, handler
   test). Left open by design, low: R3-L1 (not-found forgery by a process that rewrites the `.err` within 50 ms), R3-L2 (signal in the
   microsecond window before the handler). FIXED e494801 (2026-10-23, each with a test a mutant fails): R1-L5e (`This session is too long to
   reload safely` with rc 1, empty stdout and that single line is "not sent: that Hermes thread is too large to reload", from
   `assert_resume_safe` running before any write in `hermes_cli/oneshot.py`); R3-L3 (RELAY_HOPS and RELAY_SENDER are ignored when the
   nearest agent ancestor, read from `ps`, is another agent than Hermes (superseded 2026-10-24: ignored when another agent sits between the relay and `RELAY_HOP_PARENT`); an unrecognised tree still counts them, so loop protection
   fails closed: NOT TRUE for the real Hermes process, see the 2026-10-24 repair below); R3-L6b (a prune that loses the race still removes the `.err`), R3-L6c (lock files idle 7 days are pruned if unheld; the
   lock is re-opened when its inode is no longer the path), R3-L6d (the child's pid is written into the lock file and named in the refusal),
   R3-L6e (a sid too long for a file name, or a symlinked lock, is a clean "not sent"); R3-L8e (`reply_file` in the `--json` result of a
   timed-out or failed turn).
   **2026-10-23, load-watch report:** a relayed turn ends its row with `end_reason=agent_close`; the gateway treats that as
   recoverable (`hermes_state_common._RECOVERABLE_END_REASONS`) and reopened the same session about five minutes later
   (`~/.hermes/logs/gateway.log`: "reopened ended session 20261005_212354_16790ed2 ... keeping route"), so no context is lost
   and the next Telegram message continues the same session. The bug was fleet.py hiding the row in that window; fixed
   (`_hermes_gateway` lists `agent_close` rows not superseded by a newer row of the same session key).
3. **Installed 2026-10-23 16:29** by Hermes itself on a relayed brief from the load-watch session (djbclark's ask): `~/.hermes/skills/peer-relay` is a symlink to `skills/peer-relay`. Hermes-to-peer direction is the load watcher's retest.

## relay.py pane route: lows after adversary round 9 (2026-10-23)

Rounds 1-9 on the route ladder; round 9's four mediums are repaired in eda41d3. Its lows (reports:
`~/.local/state/bigteam/adhoc-2026-10-23/relay-ladder-adversary-report-9.md`, items 5, 6, 8, 10), working tree of
2026-10-23, awaiting the lead's review and a round-10 adversary pass:

1. DONE 2026-10-23: an enqueue is "queued" (exit 0), never "delivered"; an enqueue followed by a `remove` for any reason
   but `absorbed_mid_turn`/`delivered_to_agent` (the two reasons real transcripts carry), or by a `popAll`, is "pulled":
   unverified, never submitted for the operator, its retry types nothing (`tx_state`, `PULLED_WHY`).
2. DONE 2026-10-23: an entry whose recorded draft is "" (we never saw our copy) is proven only by a user or enqueue line
   stamped between its typing time (new `typed` field; old entries: `at` - 30 s) and `at` + 10 s (`proof_window`); a
   retry that pressed Enter itself accepts a line stamped after that press.
3. DONE 2026-10-23: chose the simpler repair, not keying: while an earlier text's entry is unproven and younger than
   the TTL, a different text is skipped (not typed), so the earlier text's retry cannot type it twice. Cost: that
   session takes no other text by pane for up to an hour after an unproven send (the socket route still can).
4. OPEN (skipped 2026-10-23, no suitable live pane): no real `herdr agent read --format ansi` or `tmux capture-pane -e`
   capture of an idle Claude Code pane is committed as a fixture; `box_parse` is proven on synthetic screens only (a
   statusline row of 10+ `─` below the box, or queued messages drawn as `❯` rows under a rule, would make it skip for
   good). Needs a Claude Code TUI running in a herdr or tmux pane; capture read-only, scrub, commit under
   `tests/fixtures/`, add a `box_parse` test.

Round 1 (2026-10-23) BLOCKed this: the stamp window decided a press (a recalled copy of a delivered text could be submitted
twice), commit 4572876 listed closed keyless subagent/desktop children as live Hermes conversations, and the unsent file had no
lock. Repaired the same day (the stamp only claims success; `end_reason='agent_close' AND session_key IS NOT NULL AND source <>
'subagent'`; `flock` on the unsent file and per pane); round 2 APPROVED (reports `~/.local/state/bigteam/relay-pane-lows/
adversary-report.md`, `adversary-report-2.md`). Lows from round 2, all FIXED d2e3e27 (2026-10-23, each with a test a mutant fails): (P1)
`pulled_and_discarded` now decides on the unwindowed state (a copy submitted by hand after the window keeps the entry); (P2) a `dequeue` credits our
text only when the next user line or `queued_command` attachment IS our text, else ours stays queued; (P3) a held pane lock returns "skip", so the
socket route may still deliver; (P4) tests for the failed temp-file removal and the final transcript look; (P5) an entry records its transcript file,
and one whose pane now has another transcript is never pressed, retyped or proven ("unverified", `MOVED_WHY`).

## Paseo agents in fleet.py and relay.py: lows after adversary review (2026-10-23)

`fleet.py` lists every non-archived Paseo agent of any provider; `relay.py` takes a hex id prefix of 6+ characters; a working agent whose
provider cannot steer (cline and every other ACP provider) is refused. Adversary APPROVE (report
`~/.local/state/bigteam/paseo-listing/adversary-report.md`). Lows, all repaired 2026-10-23 on `fix/queued-lows-2026-10-23`, each with a test a
mutant fails: (L1) FIXED 543bbcc: tests for helm keeping a Claude-on-Paseo agent in the attention queue, the 20 s `paseo ls` timeout, the
exit-code check and the `--all` wiring; (L2) FIXED 543bbcc: `fleet.py` reads one `paseo permit ls --json` and marks a running agent with
a pending card `blocked` (`paseo_pending`); helm shows a `permission` item pointing at the Paseo UI / `paseo permit allow|deny` (never keys), relay refuses it;
(L3) FIXED 543bbcc, decided: a Paseo agent with no Claude registry row never matches by name (workspace title) in `find()`, only by id, Paseo id or hex
prefix; (L4) FIXED 543bbcc, decided: no pre-send detection exists (`inspect` and `agent logs` carry no compaction or review-turn state; checked in the
Paseo 0.13 CLI source), so the guard is a refusal: a working codex, omp, opencode or pi agent needs `--steer`, claude stays steered by default (the accepted
residual). Say if omp should be steered by default again: one constant, `fleet.PASEO_STEER_DEFAULT`. The workspace-name ledger (rework lead, brief
`~/.local/state/bigteam/workspace-name-ledger/brief.md`) builds on this; it must not rely on matching a sid-less Paseo row by title.

## Queued lows branch: adversary BLOCK and repair (2026-10-24)

Adversary BLOCK on `fix/queued-lows-2026-10-23` at 91d3d72 (`~/.local/state/bigteam/queued-lows-2026-10-23/adversary-report.md`): H1, M1, L1-L6.
Repaired the same day, each with a test a mutant fails (`queued-lows-repair-1-report.md` in that folder lists the commits and mutants):
(H1) R3-L3 walked the `ps` tree looking for a process NAMED hermes, but the real one is `python3 -I -c import os, ...`, so a relay Hermes made
inside a relayed turn reached the original caller's claude: wrong sender tag, no hop count. Now `hermes_env` sets `RELAY_HOP_PARENT` (the starting relay's pid)
and `hermes_hops` counts when the walk up from `getppid()` reaches that pid (or pid <= 1) before another agent, else ignores the markers; no or a bad
`RELAY_HOP_PARENT` counts (fails closed). (M1) a Paseo agent with several pending cards showed only the first, and `paseo permit allow AGENT` without a request id
approves ALL of them (`deny` without one fails): cards keep their request ids, helm prints `allow|deny AGENT REQUEST_ID` per card (8 shown, then `paseo permit ls`),
the fingerprint covers every id. (L1) `fleet.clean_text` (moved from `relay.clean_reply`) also cleans card text. (L2) the pane lock file holds a hash of the text in
flight: the same text stops, a different one skips to the socket. (L3) a refused Hermes lock flock on a replaced inode is retried. (L4) a moved P5 entry blocking another text
says so. (L5) a tool_result-only user line no longer ends the wait for the prompt a `dequeue` handed over; the real ordering with a `queued_command` attachment is not in the
operator's transcripts (checked 2026-10-24: no attachment follows a dequeue in ~5000 of them), so this is the safe reading, pinned by a test only. (L6) docs. Open from this round: none (round 2, below, found M-A and L-A to L-F).

## Queued lows branch: adversary round 2, APPROVE at 98f3d61 (2026-10-24)

Report: `~/.local/state/bigteam/queued-lows-2026-10-23/adversary-queued-lows-2-report.md` (M-A, L-A to L-F; no regression from the repair).
FIXED on the branch, each with a test a mutant fails (`queued-lows-repair-2-report.md` lists commits and mutants): (L-A) a Paseo request id must start with a letter
or digit (`--all` and `-h` matched the old pattern, and commander reads `allow AGENT --all` as the option: approve every card); helm prints
`paseo permit allow|deny <agent> -- <request id>` (checked 2026-10-24 against the commander 12.1.0 inside Paseo.app: `--` ends option parsing). (L-B) the `relay.py`
usage text states the real rule (the markers are ignored when another agent sits between the relay and `RELAY_HOP_PARENT`, the pid of the relay that started the turn).
(L-C) `RELAY_SENDER` is accepted only as `hermes [A-Za-z0-9_-]{1,8}`. (L-E) the dequeue scan skips a user line only when every block is a `tool_result` (superseded by round 3 LOW-2 below).
Scope (M-A, docs only): the hop count and the `hermes ...` tag cover relays Hermes starts through its terminal tool and background processes (both keep `RELAY_*`).
A relay started from Hermes's `execute_code` sandbox is NOT covered: `~/.hermes/hermes-agent/tools/code_execution_env.py:25-26,75-86` (`_scrub_child_env`) keeps only
PATH, HOME, USER, LANG, LC_, TERM, TMP*, SHELL, LOGNAME, XDG_, PYTHONPATH, VIRTUAL_ENV, CONDA and a short HERMES_ allowlist, so the inner relay sees no `RELAY_HOPS`,
`hermes_hops()` is 0, `sender_name` takes the `self` row (the caller's own Claude session: fleet marks it `self` through the ancestor pid or the inherited `HERDR_PANE_ID`),
and the nested turn starts again at `RELAY_HOPS=1`. The chain is still bounded by the per-conversation Hermes locks; the label is accidental, not a security boundary.
Adversary round 3, APPROVE at a062b41 (`adversary-queued-lows-3-report.md`, 2026-10-24): LOW-1 to LOW-3 FIXED on the branch, each with a test a mutant fails: (LOW-1) the `--` in helm's `cmd_keys`
refusal for a Paseo item is pinned (d4cc9e3); (LOW-2) the dequeue scan skips a user line with a `tool_result` block and no text block, so an AskUserQuestion answer with a pasted image is skipped again
and an image-only or document-only prompt still counts as someone else's (e3049ff); (LOW-3) CHANGELOG shows `paseo permit allow|deny <agent> -- <request id>` on the 2026-10-23 line (f059b7b; this file's round-1 record stays as history).

OPEN (adversary fix text kept; not implemented, 2026-10-24):

1. **M-A, env-free detection of a relayed turn (MEDIUM).** `relay.py` already writes the Hermes child's pid into the conversation's lock file (`route_hermes`).
   The inner relay walks its ancestors and, for each one, checks whether it is the pid recorded in a lock file under `HERMES_DIR` that is currently held (a non-blocking
   flock fails). If such a pid comes before any other agent, the relay is inside a relayed turn. The hop count is the number of such ancestors, and the sender is
   `hermes <sid[-8:]>` with the sid taken from the lock file name. This also removes the forgery residual of L-C (a process inside the turn can unset `RELAY_HOPS`
   or set `RELAY_HOP_PARENT` to a pid outside its ancestry; the L-C fix only stops a forged *name*). The `RELAY_HOPS` env markers can then become a cross-check or go.
2. **L-D, the pane lock's hash can be missed while the holder releases (LOW). FIXED 2026-10-24 (#49):** `pane_sending` returns None for an empty file after its retries and `route_pane` asks for the lock again (`PANE_LOCK_ASKS`, 5 times) before it skips; test `test_a_holder_that_releases_while_its_hash_is_unreadable_is_asked_again_not_skipped_to_the_socket`, mutant checked. Original finding: `_flock` truncates the file in `finally` before `os.close` and `pane_sending` reads it
   five times over 100 ms. If B's non-blocking flock fails while A holds the lock, and A then truncates and closes, B reads an empty file, `pane_sending` returns False,
   B returns "skip" and goes to `route_socket`, which has no check for an unproven entry: A's text, already typed and recorded, arrives twice. The same happens if A
   has not written its hash within 100 ms of taking the lock (a loaded machine). Fix: when `pane_sending` sees an empty file after its retries, try the pane lock once
   more (blocking briefly or polling). If the lock is now free, take the normal path under it, where `pane_send`'s P5 check sees A's entry; do not skip to the socket.
   (B's "stop ... do not resend" while A's own routes all fail tells B's caller not to resend something A's caller was told was not sent: acceptable, the same text.)
3. **L-F, the CHANGELOG lines for the queued lows carry no PR number** (code-review rule 10): fixed 2026-10-24, the lines end with PR 40.
4. Accepted residual (L-D, adversary B2, 2026-10-24): a holder that proved delivery (`forget`) or a non-claude pane leaves no entry, so a relay of the same text that wins the
   lock inside the release window types it a second time (before L-D a non-claude pane, or a claude pane with no socket, ended "not sent" there). It is what a relay arriving just after the holder does anyway.
5. Accepted residual (L-A, related): `permit allow` picks the first card whose `id === reqId || id.startsWith(reqId)` in list order, so a request id that is a proper
   prefix of an earlier card's id would answer that other card; with UUID or `permission-<uuid>` ids it cannot happen.

## An absolute "all work in a worktree" commandment? (djbclark, direct, 2026-10-25; decision pending)

djbclark, 2026-10-25: "we are having agent conflicts too often. Should we move to having an absolute commandment that work always be done in worktrees? If unsure do web and frontier model (codex has headroom) consultations." Today only a BRANCH must start in its own worktree (AGENTS.md standing order 9); edits, commits and test runs in a shared checkout are allowed with `git-commit-own`.
Evidence so far (2026-10-25): (1) the 2026-10-24 three-session collision in the shared checkout; (2) a merge of origin/master into a branch worktree conflicted in `CHANGELOG.md` while a dispatched slice was starting in that worktree; (3) the shared `~/src/djbclark-ade` checkout carries another session's uncommitted `skills/session-finder/SKILL.md` edit; (4) `docs/queue.md` and `CHANGELOG.md` are touched by nearly every PR (constant conflicts that a worktree does not remove); (5) one worktree is handed from a build slice to its repair slice to the adversary in turn.
Web (2026-10-25, [Augment Code guide](https://www.augmentcode.com/guides/git-worktrees-parallel-ai-agent-execution), [Claude Code worktrees docs](https://code.claude.com/docs/en/worktrees)): worktrees remove file overwrites and `.git/index.lock` contention, but not runtime clashes (ports, databases), file-level dependencies between agents or merge conflicts on shared files; the guide's mitigations are non-overlapping file domains, `git rerere`, a clean test baseline and deterministic port assignment. Claude Code itself blocks Edit/Write and unverifiable Bash on the MAIN checkout once a session runs in a worktree: precedent for enforcing the rule instead of only writing it.
Frontier consult (Codex gpt-6-astra, advise only, 2026-10-25, report `~/.local/state/bigteam/adhoc-2026-10-25/frontier-worktree-commandment-report.md`): **adopt with named exceptions.** It found that djbclark already ruled this on 2026-10-23 (section "Heavier use of Hermes worktrees and cow pastures", ruling 2: no agent edits in the primary `~/src/<repo>`), so the gap is rollout and enforcement, not a new rule: standing order 9 still allows shared-master commits and `skills/cow-workspaces/SKILL.md:33` still says to edit `~/ops` in place. Rule text it proposes: every source edit, stage, commit, build, test and one-line docs or queue change happens in an exclusively claimed task workspace (a linked worktree OR an independent cow pasture or clone, created from a recorded base); ONE executor at a time may mutate a workspace (lead, repair slice and adversary hand it on only after the previous writer's processes exit; a reviewer that runs tests is a writer); shared primaries are reference and integration places only. Named exceptions: read-only inspection; a designated promoter's serialized, clean, approved fast-forward of a primary or `~/ops` master; installation, runtime-health and non-repository maintenance under a claim on the real target. No exception because a change is small. Not covered by isolation, with the cheapest fix: CHANGELOG and queue conflicts (per-change changelog FRAGMENT files aggregated by one writer; serialize queue edits through the coordinator's workspace; no blind union merge of edited decisions), stale bases (the sole writer finishes the merge and records a clean start SHA BEFORE a slice is dispatched; this is the 2026-10-25 incident), two agents in one worktree (an active-executor lease distinct from the lead's claim: `ade_claims.py` allows same-owner replacement at line 298), branch-name collisions (task plus unique suffix, reserved across clones), shared caches, ports and `~/ops` atomicity (a fast-forward changes files one by one; readers can see a mixture). Enforcement order: (1) finish the launch integration: `acp-dispatch` and interactive launches select or claim the workspace BEFORE the agent starts, refuse a launch into an unresolved merge or rebase, record start SHA and executor; (2) extend `ade-git-guard`: refuse add/commit and index writes in integration checkouts and foreign workspaces (a cow pasture is a primary checkout, so the test is "claimed task workspace", not ".git is a file"); (3) then changelog fragments. Git has no generic pre-add hook and `reference-transaction` covers refs only, so the editing layer must be the launcher. Pilot before enforcing: one ADE code task, one one-line queue task, one ops promotion, a submodule task, a fixed-cwd agent and a long-lived server; measure setup delay, disk, path-binding failures and false refusals. Existing dirty shared edits (today `skills/session-finder/SKILL.md` in `~/src/djbclark-ade`) need an owner-led migration, never an automatic stash or reset.
Status: **ADOPTED by djbclark 2026-10-25 ("adopt it, then enforce in stages")**. Rule text landed in AGENTS.md standing order 9 and `skills/cow-workspaces/SKILL.md` (transitional clause: `~/ops` keeps its plain-master practice until the ops-promotion pilot passes). Home file clause: Opus-only, dispatched (`~/.local/state/bigteam/adhoc-2026-10-25/home-worktree-brief.md`). Staged enforcement, each a Sonnet `code` slice with an adversary round, in this order: S1 launcher claim (`acp-dispatch` and interactive launches select or claim the workspace BEFORE the agent starts; refuse a launch into an unresolved merge or rebase; record start SHA and executor; an active-executor lease distinct from the lead's claim, since `ade_claims.py` allows same-owner replacement); S2 `ade-git-guard` refuses `add`, `commit` and index writes in integration checkouts and foreign workspaces (a cow pasture is a primary checkout: the test is "claimed task workspace", not ".git is a file"); S3 CHANGELOG fragments (one file per change, one aggregating writer; changes the code-review rule 10 and the CHANGELOG header); S4 the six-case pilot (an ADE code task, a one-line queue task, an ops promotion, a submodule task, a fixed-cwd agent, a long-lived server: setup delay, disk, path-binding failures, false refusals) before any hard refusal and before `~/ops` leaves plain-master. S1 and S2 build on PR 59 (W1) and the I0 slices W2-W8. Related open builds: I0 slices W2-W8 of the 2026-10-23 design (PR 59 is W1), the relay and fleet slices queued 2026-10-25.
