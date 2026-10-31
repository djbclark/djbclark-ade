# djbclark-ade — an agentic development environment

One operator, many agent TUIs. This repo is the operating kit for running a
fleet of coding agents on one Mac as a single environment: the skills every
agent loads, the tools that start and steer them, and the docs that record
what was verified. It is the canonical git home for the orchestration and
session-hygiene pieces (moved here from `~/ops/site-djbclark` on 2026-10-08;
their old paths are symlinks into this checkout).

## The pieces

1. **Many TUIs.** Claude Code, Codex, Hermes, Cursor, opencode, Cline,
   Copilot, Qwen, muse, zcode, Antigravity (`agy`) and others, each on its own
   subscription or quota pool. [`skills/model-routing`](skills/model-routing/SKILL.md)
   and [`docs/model-routing.md`](docs/model-routing.md) say which one gets
   which work.
2. **herdr and Orca as the terminal fabric.** Every session lives in a herdr
   pane (workspace / tab / pane) or an Orca terminal, so it is visible,
   addressable and can be typed into by another session.
   [`docs/orca-integration.md`](docs/orca-integration.md) covers Orca's task DAG.
3. **ACP for agent-to-agent control.** [`tools/acp-run`](tools/acp-run/README.md)
   drives any agent that speaks the Agent Client Protocol: one-shot, an
   `--interactive` loop in a visible pane, `--resume`; yolo for every agent,
   with `--perm read-only` for a review that reads and `--perm deny` for a
   text-only run (2026-10-19).
4. **Skills, linked everywhere.** Each skill is one directory in
   [`skills/`](skills/); the [`skill-everywhere`](docs/skill-everywhere.md) script
   (`~/src/djbclark-ade/bin/skill-everywhere`, with a compatibility link at `~/ops/site-private/bin/skill-everywhere`) symlinks it into every TUI's skills dir, so one edit here reaches all of
   them.

## The loop

1. **Find and decide** — [`session-finder`](skills/session-finder/SKILL.md)
   (`fleet.py`) lists every live session of every TUI, says where it lives
   and which repos it is touching, and decides how work on a topic
   continues: message the running session, `/baton` from its handoff, resume
   a stopped one, or start a clean agent. `fleet.py conflicts` refuses
   overlap.
2. **Start** — `session-finder/launch.py` starts a session over ACP
   (`acp-run --interactive`) in a visible herdr tab or Orca terminal, with a
   claim on the files it will touch, and can `reply` to it later through its
   inbox.
3. **Answer everything from one window** — [`helm`](skills/helm/SKILL.md)
   (`helm.py scan`, no model tokens) collects every session waiting on the
   operator, reads its pending question verbatim, ranks the walk by how much
   unattended work each answer unlocks, and relays one item per prompt;
   idle sessions are told to audit themselves with `/loose`. Design record:
   [`docs/helm.md`](docs/helm.md). [`bin/fleet-watch`](bin/fleet-watch)
   (launchd, every 5 min) pings Hermes only when the picture changes.
   [`herdr-tidy`](skills/herdr-tidy/SKILL.md) then closes the panes that are
   safely idle and writes the ledger `/helm-all` reads them back from
   ([`docs/herdr-tidy.md`](docs/herdr-tidy.md)).
4. **Carry work across sessions** — [`loose`](skills/loose/SKILL.md) finds
   what is unfinished and walks it with [`steps`](skills/steps/SKILL.md);
   [`handoff`](skills/handoff/SKILL.md) writes the deep Tier 2 document,
   [`session-handoff`](skills/session-handoff/SKILL.md) the Tier 1 pointer,
   and [`baton`](skills/baton/SKILL.md) (also `/resume`) picks it up in a fresh session.
5. **Fan out** — [`bigteam`](skills/bigteam/SKILL.md) slices a job into
   disjoint, file-scoped assignments and dispatches them across vendors by
   quota pool, then integrates the results.

## Layout

| Path | What |
|---|---|
| [`skills/`](skills/) | The skills (table below). |
| [`tools/acp-run/`](tools/acp-run/) | `acp-run`, the ACP client every launcher uses. |
| [`bin/`](bin/) | `acp-dispatch` (hand a slice to an agent and get its report back: wraps `acp-run`, appends [`docs/dispatch-footer.md`](docs/dispatch-footer.md), checks `--model` against the agent's live list before it starts, writes report/`.done`/record, exit codes for no-report and `BLOCKED:`, a `rearm` waiter that exits with the `check` verdict, and since 2026-10-18 an automatic in-place resume of a quota-stopped slice: a launchd one-shot reopens the same ACP session after the reset, gated on live headroom, up to 3 attempts; `--no-auto-resume` opts out; a slice a Mac restart/logout killed is tagged `killed: SIGTERM (system restart)` and resumed in place once per boot by the login sweep; and `acp-dispatch reap`, which finalizes a slice whose process died without finalize so no reader shows it running, with a launchd sweep [`launchd/com.djbclark.acp-dispatch-reap.plist`](launchd/com.djbclark.acp-dispatch-reap.plist) installed by `reap --install`), `fleet-watch` (fleet change notices), `load-watch` (no-model launchd monitor, every 20 s: after 5 minutes at load >= 2 per core it finds the agent session whose processes used the CPU, writes it a brief, types one line into its pane and pings Hermes, so heavy builds move to Forgejo CI; `load-watch ci-only add` then makes `bg` refuse local builds in that repo; [`launchd/com.djbclark.load-watch.plist`](launchd/com.djbclark.load-watch.plist), `load-watch install`), `rumination-watch` (the entity's voice in the head: a no-model launchd script that re-touches open threads and speaks on change, about mail, jobs, PRs, a stale chain log or a wedged seat, and since 2026-10-30 also speaks from an unchanged pass when the seat's one `--why` probe says `idle` while its Tier 1 chain log still declares `- Next steps:` (the COUNT only, never another seat's step text; `RW_IDLE_NUDGE=0` turns it off, `RW_IDLE_NUDGE_S` sets the 3 h per-seat cooldown; #157); djbclark’s 2026-10-30 option-3 ruling also authorises opt-in absent-seat starts: `RW_AUTO_SEAT=1` (OFF by default until field-tested), explicit `RW_AUTO_SEAT_PROVIDER` (no model/thinking flags), `RW_AUTO_SEAT_S=3600`: at most one attempt per role per window, confirmed or not; a start whose id was lost refuses further starts until direct inspect reconciles that attempt's retained id (candidate, attempt and unresolved timestamps must agree; the id is retained across owner changes until reconciliation and remains a handle for the next fresh diagnosis even after AGENT_NOT_FOUND; matching `Id` or explicit `AGENT_NOT_FOUND`), or operator reconciliation for no-id starts (stop the watcher, verify the attempt in Paseo, then remove `told["auto-seat unresolved:ROLE"]` from the state JSON; titles and empty listings cannot authorize recovery or another start); unbound/no-ID attempts page once and failed notices retry; returned-ID attempts page only after a reconciliation read fails, every invocation outcome is logged, and only pre-invocation refusals are suppressed once per window. Owner discovery is refreshed immediately before starting; changed owners or failed configured lookups forbid a start. Relay send timeouts settle as unverified and are never blindly retried. Only inspect-confirmed `gone` starts: when relay cannot diagnose a UUID-shaped id, an extra `paseo agent inspect --json -- <id>` costs up to 20 s (no model) and proves absence only on three readings — explicit `AGENT_NOT_FOUND`, or a record that names the SAME id and says `Status: closed` or `Archived: true` — because a finished seat leaves its `closed` record behind and relay calls that `refused` for SENDING (13 of the 25 agents on this Mac, 2026-10-30); errors, timeouts, unreadable bodies, a reply naming another agent and unknown shapes never prove absence. `error` is a broken read, `refused` is a finished/archived session or non-idle/running Paseo state, and `unknown` means no diagnosis; `error` and `unknown` do not auto-start and still page the human when no owner resolves, while a `refused` or `archived` id gets the one probe and starts only on one of those three readings. `silent`/`working`/`idle` and `card:*` never start (narrowing his "including after a hard error" ruling; he can overrule it). A `silent` hung seat is NOT replaced, so the individual can stay dark until the human acts. Retains returned ids as fallback behind explicit overrides and live registered successors; names the absolute Tier 1 file without copying steps and still pages him with the automatically started id. **Field check, measured 2026-10-30:** a seat created exactly the way this starts one *is* reachable — `fleet.py` listed it with a real `chan`/`reach`, `relay.py --why` read its own reply, and a real relayed line was delivered and answered — so the "start a seat it cannot then speak to" risk did not reproduce; the start also runs as `env -u PASEO_AGENT_ID`, because a caller's `PASEO_AGENT_ID` makes the new seat that agent's subagent, and it opens the seat's Paseo Desktop tab with `paseo agent open` once confirmed (a `paseo run` agent has no tab, so an invisible seat hitting a `card:*` — which it never answers — would be the same darkness one level down), where a failed open is logged, put in the page to him and never fails the start, a seat that only comes alive by recovery gets the same one attempt per id, and `RW_AUTO_SEAT_NO_OPEN` (`1`/`true`/`yes`/`on`) skips it on a host with no desktop; since 2026-10-29 every non-dry `pass` first fast-forwards the checkout it runs from to `origin/<branch>` (issue #143), so a merged fix reaches the launchd job with no hand pull: `merge-base` then `--ff-only`, never a merge commit, reset, stash or checkout, refusing on a dirty tracked tree, a git operation in progress, a detached HEAD or local commits origin lacks, and re-reading HEAD and the branch after the fetch so it cannot follow a branch switch; `RW_NO_DEPLOY=1` turns it off, `--dry-run` never deploys, `status` prints the last deploy; [`launchd/com.djbclark.rumination-watch.plist`](launchd/com.djbclark.rumination-watch.plist)), `cow-pasture` (APFS copy-on-write workspaces), `herdr-sleeper` (idle-pane sleep), `herdr-jump` (focus a `w22:t4` address from a `prefix+:` popup), `herdr-ai` (natural language to Herdr commands from a `prefix+alt+i` popup), `orca-reorg-watch`, `self-slash` (an agent queues a built-in slash command into its own herdr pane, Orca terminal or Paseo agent, e.g. `"/new"` followed by one `/baton`; since 2026-10-20 `--finish` ends the session, which on Paseo, where `/quit` is not a command, waits for idle and archives the agent without `--force`, and `"/quit"` there maps to it; `/new`, `/clear`, `/reset` and `--finish` hold a per-agent lifecycle lock; since 2026-10-23 `--finish --successor PROVIDER/MODEL [--thinking ID] [--mode MODE] [--title TEXT] [--workspace ID] [--keep-workspace] [--baton PATH]`, Paseo only, starts a new top-level agent running `/baton` on that model in the same workspace (`--baton PATH`, an absolute path to an existing file, makes it `/baton PATH` to resume that chain log; `--mode` defaults to this agent's mode for the same provider (an empty mode passes none), `bypassPermissions` for a claude successor from another provider, else the provider's own default; without `--mode`, an inspect of this agent lacking a Provider or a Mode string, or giving one that is not a plain id, exits 11 with nothing started) and archives this one only once the successor is verified, exit 11 and nothing archived otherwise; the old workspace is archived only when proven unneeded, `--keep-workspace` skips that), `skillopt-night` (nightly SkillOpt-Sleep cycle over every agent's transcripts; launchd job in [`launchd/`](launchd/)), `failover.py` (run a task through an ordered chain of agent routes with policy, preflight and an attempt log; [`docs/failover.md`](docs/failover.md)), `route_agent.py` (`route`/`plan`: pick a vendor, or spread a wave of slice kinds over pools by live headroom; bigteam re-plans at every slice boundary), `cursor-cloud` (launch and inspect Cursor Cloud Agents: `launch --repo <url> --ref <branch> --prompt-file F`, then `status`/`run`/`usage`/`followup`; key from `sudo-secretspec`, `autoCreatePR` always false; since 2026-10-20 also `acp-dispatch cursor-cloud --kind code|bulk|mechanical`, a slice with record, poller and report, and a `cursor-cloud` row in `route_agent.py`), `ade-update` (since 2026-10-20: keep this machine current: one `git fetch`, then `git merge --ff-only` of the commit it checked, relink missing skills in the canonical checkout (report-only in any other), check the `CLAUDE.md` and `~/.claude` symlinks, print the `CHANGELOG.md` entries new since the revision recorded in `~/.local/state/ade/applied`; `--check` reports only and exits 10 when behind; see "Update (this machine)" below), `ade-backup-stores` (since 2026-10-20, ADE-everywhere Phase 0: a SQLite online-backup copy of every live session database, per-session trees with their sidecars, the file stores with every credential file name and path, the `credential-bak` vault and symlinks left out, credential tables scrubbed from the SQLite copies (OpenCode: `credential`, `account`, `control_account`, `account_state`, `session_share.secret`) behind a schema guard that fails the run on any other credential-looking table or column (`--check-schemas` runs it read-only on the live databases), and the Hermes JSONL export (run on a scratch copy of the Hermes database; `ADE_BACKUP_HERMES` names the `hermes` binary), into `~/.local/state/ade/backups/<UTC>/` with a `MANIFEST.json` of sha256 hashes, built in `<UTC>.part/` and renamed when complete (a `.part` directory or no `MANIFEST.json` means an interrupted run); `--dry-run`, `--only`, `--json`, `--strict-stores`; a configured store that does not exist is `"status": "missing"` in the manifest and on stderr, exit 0 (`--strict-stores`: exit 1), a Cursor session whose required `meta.json` does not exist is a `sidecar_missing` warning (db copied, store `ok`; an error under `--strict-stores`), and one that is symlinked, excluded or gone during the copy is an error and its store `partial`; exit 2 for a destination that exists, holds a source store, sits inside one or inside a git repo; [`docs/ade-everywhere-inventory-2026-10-20-stores.md`](docs/ade-everywhere-inventory-2026-10-20-stores.md) section 3), `ade-scan-state` (Phase 0 scan that changes no work, scans only a checkout whose config uses allowlisted keys (any other is listed as skipped) and has `ade-scan-state-doc` render its doc: bigteam task dirs with size, newest mtime, `CLAIM` state, report files, unclosed job records and a `unique`/`mixed`/`scratch` verdict, plus git checkouts under Orca, `~/.cow/pastures` and any root with branch, dirty and untracked counts, unpushed commits, stashes and whether the branch is on origin; `--json` or `--markdown`; first run in [`docs/ade-everywhere-phase0-scan-2026-10-20.md`](docs/ade-everywhere-phase0-scan-2026-10-20.md)), `ade-template-check` (credential scan, render-and-parse and `--diff` by key path over the `agents/` templates, 2026-10-20)., `claude-fleet-governor` (2026-10-23: keeps every Claude session on the Mac from exhausting the subscription before a reset; projects each aiuse window to its reset, levels `ok`/`tight`/`critical`, and moves Paseo agents in place: Fable to Opus always, Opus/Fable to Sonnet at tight, a steer to hand off to omp API credits at critical, restore after the reset; exit 0/1/2, 10 stale data, 11 a call failed; launchd every 300 s via `--install`; `bin/route_agent.py` reads its `level`), `paseo-set-model` (`set <agent> <model>` switches a live Paseo agent's model in place through the daemon's own `set_agent_model_request`, the CLI has none; `list --json` lists every agent; exit 3 no such agent, 4 model not applied), `local-review` (Codex's code review run locally on the exact head of a PR in a clean detached worktree; the head-named result file is what `pr-wait --local-codex` reads instead of the GitHub bot's marker; exit 0 clean, 1 findings, 2 usage, 3 failed, 4 duplicate run), `pr-wait` (one aggregating waiter per PR head: CI checks of the exact head plus Codex's `codex-review-state:v1` marker, one summary line and `PREFIX-{checks,codex,findings,open-findings,summary}.json` (`merge_ready` is true only with CI green, Codex completed on the head, no unresolved Codex review thread of any head and a marker that agrees, security findings included; `merge_blockers` says why not); exit 0 done, 1 timeout, 2 usage or lock guard busy, 3 Codex stuck, 4 duplicate waiter alive, 5 head moved, 6 timeout while `gh` failed; lock under `~/.local/state/pr-wait/`; since 2026-10-24 it also posts one `@codex review` when the head has no Codex marker and no request since its server-stamped push time (check-suite created_at or force-push event, never a commit date), and once more after `--rerequest-after S` (default 600) of the code review’s `running` state (completed code is not requested again while security is pending), never a third, with `--no-request` to only wait; summary fields `codex_requested` and `codex_request_note`; 2026-10-23), `claude-settings-env` (adds the `env` keys the live `~/.claude/settings.json` needs: `GRAFT_NO_GITIGNORE=1` enforced, `CLAUDE_CODE_SUBAGENT_MODEL=sonnet` as a default an operator value overrides; `--check`; run by hand, 2026-10-23). |
| [`claude/commands/`](claude/commands/) | Claude Code slash commands: the thin wrappers `/helm-all`, `/session-finder-all`, `/resume`, `/herdr-tidy`, `/orca-tidy` (herdr-tidy over Orca terminals), `/skillopt-sleep`. |
| [`claude/hooks/prior_art_nudge.py`](claude/hooks/prior_art_nudge.py) | Prior-art shadow telemetry (2026-10-26, slice D2 of the web-prior-art research, `docs/queue.md`): a PostToolUse / PostToolUseFailure / UserPromptSubmit hook that only RECORDS, one JSON line per event in `~/.claude/state/prior-art-shadow/<session id>.jsonl` (`PRIOR_ART_STATE` overrides, and should be a directory of its own; mode 0600 in a 0700 dir, files opened `O_NOFOLLOW`; 5 MB cap, then one `{"capped":true}` line; files older than 30 days pruned at most daily, only names of the form `<session id>[.a<12 hex>].(jsonl\|state.json\|lock\|drops)`), when an agent reads code in an external tree (`node_modules`, `site-packages`, `.cargo/registry`, `~/.cache`, `vendor`, Nix store), reads or searches memory, or searches or fetches the web (WebSearch/WebFetch, MCP web servers by name, `curl` to a public URL, `gh search`, `gh api repos/<other owner>/...` for code, docs and releases paths only): category, output bytes and a `bytes // 4` token estimate, the external-read run length, duplicate and retry calls, shell quoting failures, task changes, `schema` / `classifier_version`; Bash is parsed (pipe filters, redirects, heredoc bodies and comments ignored; a stdin reader such as `cat`, `wc` or `sed` with no path is not a read unless it has `< file`; `cd` and assignments inside `( )` do not leak; a command substitution inside double quotes is not scanned, so `echo "$(find /nix/store)"` is a miss and a heredoc inside `"$( )"`, the commit and PR body form, is text of the outer command), and each subagent has its own carry-over state. Never prints, blocks or changes a prompt; never records a command, path, query, URL, prompt or output: it stores categories, booleans, counts, a fetched URL's `host_class` plus its registrable domain only when that is on a fixed allowlist, a fixed `path_class` enum, and `event`, tool and model only from fixed lists (an MCP tool is recorded as its server alone; a model as a family, for Claude its tier, and up to three version numbers). Known limits: a path variable that stays unknown (`cat "$OUT"`) is `private_other` with `path_class: unresolved`, never the cwd (same-command literal assignments and for-loop lists are resolved; R3-1; round-3 stated limits in `docs/queue.md`), an `OWN_GITHUB_OWNERS` of `djbclark` alone, a scheme-less `curl host/x` is not web, a symlink into a memory directory is not memory, a session id of the form `X.a<12 hex>` would share state with a subagent of session `X`. `PRIOR_ART_SHADOW=0` turns it off. Tests: `tests/test_prior_art_nudge.py`. |
| [`bin/claude-quota-guard`](bin/claude-quota-guard), [`claude/hooks/quota_nudge.py`](claude/hooks/quota_nudge.py) | Claude quota guard (2026-10-23): `check` (launchd every 15 min after `--install`; macOS only, exit 69 elsewhere) turns aiuse's Claude weekly / 5-hour / Fable windows (read from the snapshot when `aiuse --available` drops an exhausted Claude) and `conserve` alerts into `ok` / `watch` / `tight` / `critical` (exit 0-3; exit 10 = Claude nowhere in aiuse or its snapshot, aiuse unreadable, any container present but not a list of objects, a corrupt snapshot, or another check holding `<state>.lock`; exit 10 never writes a level: level, advice and numbers stay as they were, a failed read records `unreadable_since` and the second failing run in a row sends one ping per episode, the next good read clears it; 64 = bad thresholds env; 69 = `--install` off macOS), writes `~/.local/state/ade/quota-guard.json`, pings once per level per reset period; data older than 3 h (dead collector) is `stale`, raises the level to at least `watch` and sends one ping per stale episode; the UserPromptSubmit hook prints the level's advice once per session and level, and an `[quota-guard unreadable]` line once the guard has pinged about an unreadable episode and is still failing (a one-off hiccup or a stopped guard prints nothing); the hook's once-per-session memory is updated under a flock. See `skills/model-routing/SKILL.md` *Probes* and *Routing policy* items 12-13. |
| [`claude/hooks/relay_prose_nudge.py`](claude/hooks/relay_prose_nudge.py) | Claude Code Stop hook (2026-10-25, standing order 10): when the turn began with a message from a relay sender and made no `relay.py` Bash call and no `SendMessage` to that sender, and the text asks for an answer, it prints `{"decision": "block", "reason": ...}` once: "You answered a relayed message in prose; the sender does not see it. Reply with relay.py ID ... If it needs no answer, end the turn; if it asks for one, start your relay reply with ack X". The sender is the `[relay from KIND ID ...]` header at the very start of the text (pane, inbox and Paseo routes; a user entry or a `queued_command` attachment) or, on the socket route, which writes no header, the `from-name="relay.py (LABEL)"` attribute of the `<cross-session-message>` envelope (read as the header). Claude Code logs a socket frame for a busy receiver as a `queued_command` attachment holding the bare envelope (all 124 envelope-bearing peer attachments of 174), and for an idle one as a user entry with `isMeta: true` and `origin.kind: "peer"` whose content is a harness prefix (`Another Claude session sent a message:` and a newline), the envelope and a harness suffix after the closing tag (all 108 envelope-bearing peer user entries of 176 (the other 68 are teammate or task entries that parse to nothing)); the hook reads both, cutting the body at the first closing tag and unescaping it. Verified from real transcripts (2026-10-26): those two shapes and the pane shapes; [INFERENCE]: no relay frame to an idle session was ever observed (all 7 relay or acp-dispatch frames were to busy ones), but Claude Code's handler sets `isMeta` and the peer origin for every socket frame. A deferred send's `[queued Nm ago]` after the header or envelope is skipped. A text asks for an answer when it ends with relay's own `[reply through relay.py ...]` or `[first contact from ...]` footer (read only at the very end), or has a `?` outside a URL unless relay enforced footers on that sender, which only a herdr pane id with a `(DIR)` suffix shows (a Paseo uuid, a session-id prefix, `hermes TAIL` or a pane id with no `(DIR)` says nothing, so its `?` counts). Silent for statements, `ack <ID>` texts with no `?` (with or without an answer after the ID), `no reply needed` / `no need to reply` / `no response needed` and `FYI` texts, a header with no usable ID, a second Stop in the turn (`stop_hook_active`, a per-session state file), any parse error (fails open); known limit (deferred): an `ack ...`, `no reply needed ...` or `FYI ...` text that goes on to ask for an action without a `?` is read as an exemption, and an `FYI` text is silent even with a `?` (docs/queue.md, "Verified peer messaging, round 2", item 8). Reads the last 256 KB of the transcript, no network, never calls relay.py. `RELAY_PROSE_NUDGE_OFF=1` disables it. Registered in `agents/claude/settings.json.tmpl` (Stop); tests `tests/test_relay_prose_nudge.py` |
| [`bin/ade-git-guard`](bin/ade-git-guard), [`libexec/agent-bin/git`](libexec/agent-bin/git), [`libexec/git-hooks/`](libexec/git-hooks/), [`bin/ade_claims.py`](bin/ade_claims.py) | Workspace claims and the git guard (2026-10-24, isolation slice W1; O2 redesign 2026-10-25; reference: [`docs/git-guard.md`](docs/git-guard.md)). **Two enforcement points.** Refs are guarded by git's own hooks, `reference-transaction` (refuses, in `prepared`, an agent's update of a branch another agent's active claim names, a `HEAD`/branch update inside a workspace another agent claims, a `refs/stash` update in a linked worktree; logs every change to a claimed branch in `committed`) and `pre-push` (a push to a claimed branch), so no argv spelling (`fetch . main:heads/cb`, `branch -f`, `update-ref`, `push . main:cb`, ...) gets round them; they are installed per repository by `ade-git-guard install [DIR]` (chain-preserving: an old hook becomes `NAME.pre-ade`; exit 78 while `core.hooksPath` is set to any value, an empty one included) and lazily by the shim, and **fail open** on any crash of the hook, bash or python (only its exit 77 refuses; the shim fails closed when git cannot say whether `core.hooksPath` is set, and asks git, never a text parse, for `core.hooksPath` and `remote.origin.url`). The shim (`git ARGS` through a relative symlink to `bin/ade-git-guard`) runs the real git, or exits **77** with the owner, claim id and a safe alternative on stderr and one JSON line in `~/.local/state/ade/guard.log`, when an agent (`ACP_RUN_AGENT=1` or `ADE_CLAIM_ID` set; a human shell, git hooks and pre-commit are never touched) runs destructive git in an unclaimed checkout (`reset --hard`, `stash`, `checkout <path>`, `clean`, `rm -f`, `commit -a`, `add -A`, autostash, `rebase -x`), anything but a small read allowlist in a workspace another claim owns (cwd or any `-C`/`--git-dir`/`--work-tree`/`GIT_DIR`/`GIT_WORK_TREE` value), `worktree remove|move|prune` of a claimed worktree or the destination of `branch -m|-M|-c|-C` (what no hook sees), and it **fails closed** on an unknown leading option or subcommand, `-c`/env config that sets `core.hooksPath` or a `hook.*`/`include.*` key, and `push --no-verify`. `ade-git-guard --real-git` prints the git it would run. Claims live in `~/.local/state/ade/claims/<id>.json` (`ADE_STATE_DIR` moves the directory) with the pointer `<git-dir>/ade-claim`; `ade_claims.py new/show/find/list/set-state/guard/install/hook-ref/hook-push` (exit 0 ok, 1 not found, 2 usage, 3 id exists, 4 path owned by another owner, 73/78 install, 77 refused). `ACP_OPERATOR_APPROVED=git-guard` allows and logs one call. Not covered: libgit2/gitoxide writers, a harness that turns repository hooks off (Hermes), repositories without the hooks, `env -i`, writes that open no ref transaction (direct `packed-refs`/loose-ref edits, `replace`, `notes`), a repository's own `core.hooksPath`, a rewritten `remote.origin.url`, same-uid forgery of the hook's inputs; the full list is [`docs/git-guard.md`](docs/git-guard.md) "What is NOT covered". **Integration status 2026-10-25: only the guard, the hooks and the claim library exist**; `cow-pasture` installing the hooks (W2), `acp-dispatch` exporting `ADE_CLAIM_ID` (W3) and `acp-run` putting `libexec/agent-bin` on agents' PATH (W4) are not wired, so no live session goes through it yet. |
| [`bin/bm-lint`](bin/bm-lint) | Basic Memory store hygiene lint (2026-10-24): `bin/bm-lint [STORE]` (default `$BM_LINT_STORE`, else `~/ops/site-private/memory`) reads the store's markdown files, never the SQLite index, and reports missing `type:` on `feedback_`/`reference_`/`project_`/`user_` notes, empty config projects, dead subtrees, stale handoffs, orphan notes, duplicate titles, unresolved wiki-links, undated `[ruling]` and unlinked `[decision]` observations (a relation or an http(s) Markdown link to a PR, issue or commit page counts as provenance for a `[decision]` only, never as an in-store relation; code fences and inline code are skipped), unverified `status: active` notes, oversize notes and dead `~/` paths. Flags: `--json` (one object with stable per-finding `key`s; local-only, it names note paths), `--config CONFIG` (default `$BM_LINT_CONFIG`, else `~/.basic-memory/config.json`; unreadable = empty-project check skipped), `--handoff-days N` (30), `--dead-days N` (30), `--verify-days N` (90), `--max-bytes N` (51200; larger notes keep their size, observation and path checks but their relations are not parsed). Each `N` default can come from `$BM_LINT_HANDOFF_DAYS`, `$BM_LINT_DEAD_DAYS`, `$BM_LINT_VERIFY_DAYS`, `$BM_LINT_MAX_BYTES`. Exit codes: 0 no findings, 1 findings, 2 error (store root unreadable or not a directory, a run that read no note at all while some were skipped, bad arguments or `BM_LINT_*` value, any internal error). Read-only: it writes nothing, opens only regular files inside the store, never follows a symlinked file or directory, and lists unreadable notes and directories, dangling or looping symlinks, notes that could not be parsed (`notes: not parsed: <rel>`, skipped alone) and other skipped paths under `skipped` (path only); an internal error prints the exception class name only. Findings carry paths, line numbers and counts, never note text; `--json` is local-only. Tests: `tests/test_bm_lint.py`. |
| [`bin/context-watch`](bin/context-watch) | Live context readout (2026-10-28): one line per running Claude Code agent, fullest first, `<id8> <title> 214k/267k (80%) wall in 53k`: tokens from the newest non-sidechain usage block of the session transcript (the parser of `claude/hooks/context_size_nudge.py`, imported, not copied) against the agent's own compaction ceiling (`autoCompactWindow`, per-model or global, capped at the model's window, minus the 33k buffer). Agents from `paseo ls -g --background --json` (session from `~/.paseo/agents/*/<id>.json`), else transcripts modified in the last 30 min (`--source recent`); `--json`, `--min-pct N`; an unreadable size prints `?`; read-only, exit 0. Why: `paseo inspect` has no context fields (getpaseo/paseo#4949). Reference: [`docs/context-hygiene.md`](docs/context-hygiene.md) section 6. |
| [`docs/context-hygiene.md`](docs/context-hygiene.md) | Earlier context warnings, Go native compaction, and safe handoff/new/baton boundaries (2026-10-25). |
| [`agents/`](agents/README.md) | Config templates for Claude Code, Codex, opencode and Hermes (placeholders for secrets, home paths and host ids), checked by `bin/ade-template-check` (below). |
| [`docs/`](docs/) | Design records and dated operating knowledge (list below). |
| [`plugins/`](plugins/) | `herdr-sleeper` herdr plugin (dev source of djbclark/herdr-sleeper). agent-radar, a Claude Code mod, was removed on 2026-10-18 (docs/apply-toolchain-prompt.md says how to uninstall it). |
| [`.claude/workflows/graph-audit.js`](.claude/workflows/graph-audit.js) | Micro-graph example workflow (`/graph-audit`). |
| [`vendor/`](vendor/README.md) | Vendored snapshots and pointers to things with their own homes. |
| [`AGENTS.md`](AGENTS.md) | Entry point for any agent working here (`CLAUDE.md` links to it). |

## Skills

| Skill | One line |
|---|---|
| [`bigteam`](skills/bigteam/SKILL.md) | Run a prompt as a multi-vendor fan-out: probe every quota pool, slice into file-scoped assignments, dispatch, integrate. |
| [`model-routing`](skills/model-routing/SKILL.md) | Which vendor × model × effort for which work; reading `aiuse` pools. |
| [`oc-go-key`](skills/oc-go-key/SKILL.md) | Recover a session that stopped on `Go usage limit exceeded` / `Insufficient account funds`: `scripts/go-status` reads the live account state, `oc-go-key use <label>` swaps it for running sessions, and the aborted turn is resumed by relay — never by opening a new tab. |
| [`fallback-chains`](skills/fallback-chains/SKILL.md) | Every failure chain on this machine, and the not-started plan to make them one system. |
| [`aws-rules`](skills/aws-rules/SKILL.md) | AWS Agent Toolkit rules and this machine's AWS setup facts (profile, Region, `aws-mcp`); on demand, never in `AGENTS.md`. |
| [`effort-routing`](skills/effort-routing/SKILL.md) | Match this session's own reasoning effort to the stretch of work in front of it. |
| [`session-finder`](skills/session-finder/SKILL.md) | Which session is or ever was on a topic (live or ended, handoff chains, memory; `/session-finder-all` searches everything), where it lives, and how the work continues (`fleet.py`, which lists every Paseo agent of any provider too; `relay.py`, which takes a Paseo id prefix and queues a send from an identifiable caller to a busy non-steerable agent for delivery when it is idle, `queued: <id>`, exit 0; `launch.py`). |
| [`helm`](skills/helm/SKILL.md) | Answer every waiting session of every TUI from one window, ranked by work unlocked (`helm.py`); `/helm-all` adds ended sessions that still hold open work, panes `herdr-tidy` closed and sleeping panes that are gone. |
| [`herdr-tidy`](skills/herdr-tidy/SKILL.md) | Close idle herdr panes safely, every TUI, Hermes, shells and herdr-sleeper stubs: `tidy.py` classifies each pane, performs the precondition (`/handoff`), writes a close ledger with the exact resume command, closes the tab; fails closed. `/herdr-tidy`; `--host orca` does the same for Orca terminals (`/orca-tidy`). |
| [`autorename`](skills/autorename/SKILL.md) | Title the current Claude Code, zcode, Grok, or cursor-agent session the way `/rename` does and name its own tab, nothing else (Paseo tab or herdr tab label; `/autorename all` is the herdr-only layout pass, refused in Paseo; `autorename.py`, `herdr_place.py`; nudge hook `autorename_nudge.py`: Claude Code and zcode on UserPromptSubmit, Grok on Stop, cursor-agent through the Claude registration); `workspace-layout.md` is the workspace/tab/pane naming and re-arrangement procedure. |
| [`ralph-tui-orchestration`](skills/ralph-tui-orchestration/SKILL.md) | The Ralph TUI + Beads multi-repo controller (dormant since 2026-08-23). |
| [`cow-workspaces`](skills/cow-workspaces/SKILL.md) | Isolated agent workspaces as APFS `cow` pastures (`bin/cow-pasture`), not worktrees. |
| [`handoff`](skills/handoff/SKILL.md) | Deep Tier 2 handoff document, chain-tagged and mined from the whole conversation. |
| [`session-handoff`](skills/session-handoff/SKILL.md) | Read/write the out-of-tree Tier 1 session pointer for any git repo. |
| [`baton`](skills/baton/SKILL.md) | Start-of-session resume from the Tier 1 pointer (`/baton`, `/resume`). |
| [`loose`](skills/loose/SKILL.md) | Audit the session for loose ends, step through them, then offer `/handoff` or quit. |
| [`loadwatch`](skills/loadwatch/SKILL.md) | Make this session the machine's one load watcher (`load-watch watcher set`): every load incident, unexplained spike and job-guard trip comes here; investigates when the load is abnormal. |
| [`cfenginewatch`](skills/cfenginewatch/SKILL.md) | Make this session the one CFEngine upstream-PR watcher (`fleet-watch upstream --relay-to`): reviewer events on djbclark's upstream PRs are relayed here and worked via `/bigteam`, prepare-and-stop. |
| [`paseowatch`](skills/paseowatch/SKILL.md) | Make this session the one Paseo-contribution watcher (`fleet-watch upstream --profile paseo --relay-to`): maintainer replies on djbclark's PRs, issues and Discussions in getpaseo/paseo and zcode-acp are relayed here and worked via `/bigteam`, prepare-and-stop; no worker fallback. |
| [`watch`](skills/watch/SKILL.md) | Bring up every watcher session at once (`bin/watch up`, table in `config/watch.toml`): one live, registered watcher agent per domain (CFEngine PRs, Paseo contributions, load) in its own Paseo workspace, only the missing ones started, model/effort/context from `route_agent.py` and recent event load, registration verified; never replaces a live watcher without `--force`. |
| [`peer-relay`](skills/peer-relay/SKILL.md) | Hermes messages a peer agent session by running `session-finder/relay.py` (best route, falls back itself; never resend an unverified one; a send from an identifiable caller to a busy agent is queued, `queued: <id>`, exit 0; an anonymous caller gets exit 1). |
| [`steps`](skills/steps/SKILL.md) | Walk open items one multiple-choice prompt at a time, recommendation first. |
| [`create-hook`](skills/create-hook/SKILL.md) | Native Codex hooks: `hooks.json` paths, PascalCase events, trust review, allow/deny JSON, timeouts, append-only merge and uninstall; Codex 0.164.0 snapshot (2026-10-25), Codex only. |
| [`research`](skills/research/SKILL.md) | Evidence-grounded research: verbatim-quote claim log, counter-evidence pass, `research_check.py` verifies quotes and citations. |
| [`dialogue`](skills/dialogue/SKILL.md) | Multi-model dialogue that produces one artifact with a final-word model; `dialogue.py` runs pinned routes, checks footers and gates the final word. |
| [`book-to-kb`](skills/book-to-kb/SKILL.md) | Add a book to the local `~/kb` knowledge base so any session can query it cheaply. |
| [`gmail-search`](skills/gmail-search/SKILL.md) | Local full-text search of the whole mailbox in ~100 ms; read-only. |
| [`barnowl`](skills/barnowl/SKILL.md) | BarnOwl and Zephyr from plain English: subscriptions, locate, zwrite, any BarnOwl command, against the live tmux session `barnowl` (`scripts/bo`, on pastebin.xvm.mit.edu). |
| [`graft`](skills/graft/SKILL.md) | Use the graft code graph before grepping or reading source. |
| [`todo`](skills/todo/SKILL.md) | Optional do-whenever tasks, kept as Basic Memory notes. |
| [`terminus-kira`](skills/terminus-kira/SKILL.md) | Delegate a task to a sandboxed coding agent in an Apple Container VM. |
| [`sipb-llm-bench`](skills/sipb-llm-bench/SKILL.md) | Benchmark a model on SIPB LLMs (or any OpenAI-compatible server) as a coding-agent backend: probes, tool-call conformance, two scored tasks. |
| [`forgejo`](https://forgejo.mit.edu/djbclark/sipb-agent-skills/src/branch/main/skills/forgejo/SKILL.md) | (Canonical files live in [sipb-agent-skills](https://forgejo.mit.edu/djbclark/sipb-agent-skills); local dir is a symlink.) Use a Forgejo instance (default `forgejo.mit.edu`) with the token in `sudo-secretspec`: `setup-token`, `forgejo-api`, `tea-forgejo`. CI on forgejo.mit.edu is the `forgejo-ci` skill. |
| [`forgejo-ci`](skills/forgejo-ci/SKILL.md) | Runs CI on SIPB Hyades (forgejo.mit.edu `ubuntu`, libkrun microVMs): runner facts, job-image selection (our own `ghcr.io/djbclark/ci-image-plektra`), the loopback `LD_PRELOAD` shim for libkrun TSI bugs, probe tooling, ticket etiquette and the ticket map. |
| [`hyades-docker`](https://forgejo.mit.edu/djbclark/sipb-agent-skills/src/branch/main/skills/hyades-docker/SKILL.md) | (Canonical files live in [sipb-agent-skills](https://forgejo.mit.edu/djbclark/sipb-agent-skills); local dir is a symlink.) Deploy OCI images to SIPB Hyades (`*.sipb.cloud` microVMs): the SSH console with a real exit status (`scripts/hyades`), `hyades.json`, podman-first registry pushes, SIPB/hyades-action CI secrets, update tokens; vendored upstream docs and full console help. |
| [`coderabbit-feeder`](skills/coderabbit-feeder/SKILL.md) | Queue a CodeRabbit review for a PR where CodeRabbit is not installed. |
| [`siyuan`](skills/siyuan/SKILL.md) | SiYuan notes: concepts, API, templates, flashcards; with `siyuan-article-import`, `siyuan-excalidraw`, `siyuan-markdown` (vendored from `zhiluop/siyuan-skills`). |
| [`skillopt-sleep`](skills/skillopt-sleep/SKILL.md) | Review the nightly SkillOpt-Sleep cycle (`bin/skillopt-night`): last night's report, free mock dry-run, per-skill adoption, the backend failover chain (`chain-check`). |
| [`skillopt-sleep-learned`](skills/skillopt-sleep-learned/SKILL.md) | The catch-all skill SkillOpt-Sleep proposes edits to; lessons that belong to no single skill. |
| [`reorg-orca`](skills/reorg-orca/SKILL.md) | Reorganize an Orca setup from the CLI; says which moves Orca cannot do yet. |

Every skill with its trigger phrases and how to use it: [`docs/skills.md`](docs/skills.md).
One skill, `1password`, is private and stays in `~/ops/site-private/skills/`;
`tell-chief-of-staff` moved here on 2026-10-14.

## Install (this machine)

Every TUI's skills dir links **directly** at this repo (collapsed 2026-10-14,
no hub, no chains): `~/.claude/skills/<name>` →
`~/src/djbclark-ade/skills/<name>`. To add one:

```sh
~/src/djbclark-ade/bin/skill-everywhere <name>          # link into every TUI
~/src/djbclark-ade/bin/skill-everywhere --check <name>  # verify
```

How each TUI finds skills, and how to prove one loaded: the script's
[skill-everywhere README](docs/skill-everywhere.md).

`acp-run` is on PATH as `~/.local/bin/acp-run` → `~/ops/site-private/bin/acp-run`
→ `~/ops/site-djbclark/tools/acp-run/acp-run` → here; `fleet-watch`'s launchd
job runs `~/ops/site-private/bin/fleet-watch`, which resolves here the same
way. `helm.py` imports `fleet` from the sibling `skills/session-finder/`.

### Update (this machine)

Since 2026-10-20, run `~/src/djbclark-ade/bin/ade-update` (`--check` first to see what it would do, `--json` for a
machine-readable report; `--repo` and `--state` override the checkout, which must be the top of its work
tree, and the record). It is
idempotent and safe to run daily. It does, in order, every step below; nothing here is done by hand:

```sh
~/src/djbclark-ade/bin/ade-update --check        # report only; exit 10 when behind
~/src/djbclark-ade/bin/ade-update                # pull, skills, symlinks, changelog delta
```

1. **Pull.** It fetches once, checks that commit, and fast-forwards to exactly that commit
   (`git merge --ff-only <sha>`; no second fetch, so a newer upstream commit waits for the next run). A path the
   update would change or create that has a local modification, an untracked file or an
   ignored file (or collides with one as a parent or child path, `foo` against `foo/bar`) stops it (exit 2,
   nothing merged); a diverged branch stops it (exit 3); it never makes a merge commit, stashes or resets.
2. **Skills.** `skill-everywhere --check` over every `skills/*`; a missing, dangling or chained
   link is relinked, anything the script leaves alone is printed with the command to run. Links change
   only when `--repo` is the canonical skills home (`~/src/djbclark-ade`, or the parent of
   `$SKILL_EVERYWHERE_ADE`); any other checkout (a pasture, a second clone) gets a report-only skill
   step, since linking would repoint every TUI's live skills into it. A skill directory whose name is
   not `[A-Za-z0-9][A-Za-z0-9._-]*` is skipped and reported. The `skill-everywhere` it runs is the one beside
   the running `ade-update` (`$SKILL_EVERYWHERE_ADE` only says where the skills live, it never chooses code),
   with the canonical checkout's `bin/` and then `PATH` as fallbacks in the canonical checkout only, else the
   step is skipped with a note: a checkout given by `--repo` (a pasture, a second clone, an untrusted PR
   branch) never has its own `bin/` executed, not even under `--check`. A `skill-everywhere --check` that crashes
   (nonzero exit, bar its own `warning:` status), does not end with its `== end` sentinel line, or leaves a skill
   without a header or without any TUI row, is an error (exit 4: "skill check incomplete"), never a partial
   success. A link call that exits 1 with an empty stderr or only `warning:`/`error:` lines is the script's own
   "left alone": the follow-up check decides, so a link it cannot fix is exit 10 naming the row, on the first
   run too, with no state recorded; any other nonzero exit or crash-like stderr is exit 4 (naming the rows
   still not in place when the check can list them). When `ade-update` itself runs from a path other than the
   canonical checkout it warns on stderr: the `skill-everywhere` beside it is the one that runs.
3. **Symlinks.** `CLAUDE.md` is a symlink to `AGENTS.md`, and every file in `claude/{commands,agents,
   hooks}` is linked from `~/.claude/`; a gap is reported with the `ln` command (not changed; outside the
   canonical checkout the rows are counted only). `--check` on a checkout that is behind also lists the entries
   upstream adds under `claude/{commands,agents,hooks}` as "new upstream" links (not counted as problems; apply
   pulls first and then reports them with the fix).
4. **Changelog.** It prints the [CHANGELOG.md](CHANGELOG.md) entries new since the commit recorded
   in `~/.local/state/ade/applied` (every Unreleased entry the first time), then records the new
   HEAD there. Every pull request adds its line to the changelog (AGENTS.md code-review rule 10),
   so that is the one place that says what changed and what is new.

Exit codes: 0 current, 10 behind (`--check`) or a link unresolved (including one `skill-everywhere` leaves alone, on the first run), 2 dirty, 3 diverged (git's explicit
non-fast-forward refusal only), 4 git, network, `skill-everywhere` (not found from the canonical checkout, failed or incomplete) or state-file failure (including a `--repo`
that is not the top of its work tree, and any other `git merge --ff-only` failure such as a timeout or lost
authentication). It becomes `ade update` in Phase 1 (proposal 4.4 item 9); a daily `--check` timer
is queued in `docs/queue.md`.

## agents/ templates

`agents/<tui>/<file>.tmpl` tracks the four config files that were tracked nowhere (Phase 0 item 4.4,
2026-10-20): `~/.claude/settings.json`, `~/.codex/config.toml`, opencode's `opencode.json` and
`~/.hermes/config.yaml`. Each is the live file's structure and key order with every secret as
`{{ secret "NAME" }}` (a `sudo-secretspec` entry), every home path as `{{ .home }}` and every host name,
account or chat id as `{{ .field }}`; [`agents/README.md`](agents/README.md) lists each placeholder and what
was kept as machine-specific. Nothing applies them yet (the chezmoi source state is Phase 1). `bin/ade-template-check` is
the gate: it scans every template for credential patterns and shapes (a heuristic that catches the key
forms it knows, not every secret, so a person still reads a regenerated template before it is pushed), renders
it with plain and with hostile dummy values to prove it still parses, and with `--diff` names the keys that
differ from the live file (paths, never values, though a path can hold a home path or session id); CI runs it
through `tests/test_ade_template_check.py`.

## Docs

1. [`docs/model-routing.md`](docs/model-routing.md) — every service on this
   machine mapped to its TUI, subscription vs prepaid vs free, effort levers.
2. [`docs/orca-integration.md`](docs/orca-integration.md) — runnable Orca
   macro-graph sequences and live-run lessons.
3. [`docs/helm.md`](docs/helm.md) — helm's design record and what was verified.
4. [`docs/agent-sleep.md`](docs/agent-sleep.md) — idle agents and RAM: Orca
   hibernation and `herdr-sleeper`.
5. [`docs/coding-factory.md`](docs/coding-factory.md) — the unattended
   issue → PR → merge question, answered.
6. [`docs/queue.md`](docs/queue.md) — work queued by the operator, and blockers.
7. [`docs/ai-memory-landscape.md`](docs/ai-memory-landscape.md) — the levels
   of AI memory this machine is building toward.
8. [`docs/mcp-servers.md`](docs/mcp-servers.md) — the MCP server roster.
9. [`docs/upstream-issues.md`](docs/upstream-issues.md) — bug drafts for
   third-party projects.
10. [`docs/herdr-jump.md`](docs/herdr-jump.md) — jump to a Herdr address
    (`w22:t4`) from the keyboard: why Herdr has no such action, the
    `bin/herdr-jump` popup, and the third-party navigator evaluation.
11. [`docs/herdr-tidy.md`](docs/herdr-tidy.md) — closing idle herdr panes
    safely: the pane classes, the close ledger, the cracks closed in
    `fleet.py`/`helm.py` (busy-background, undetected TUIs, closed and sleeping
    items), the first pass (2026-10-08) and the requests left for herdr-sleeper.
12. [`docs/herdr-ai.md`](docs/herdr-ai.md) — `bin/herdr-ai`: type "move to the
    sleeper tab" or "rename this workspace ops" in a popup; a fast free model
    plans Herdr commands from a snapshot index, the script validates every id
    against the snapshot and asks for a `y` before anything destructive.
13. [`docs/apply-toolchain-prompt.md`](docs/apply-toolchain-prompt.md) — a
    drop-in prompt (v5.1) that has a Claude Code orchestrator apply the
    stayturgid/aiuse/Graft toolchain, subagents, skills/plugins, tests, CI and
    CodeRabbit to another repo, with backups and restore recipes; its preamble
    says how to run it or cut it to a budget.
14. [`docs/skillopt-sleep.md`](docs/skillopt-sleep.md) — the nightly
    SkillOpt-Sleep cycle: what runs when, paths, config, choosing the backend,
    reading a night, adopting and rolling back, unsupported sources and the
    pluggable-source plan.
15. [`docs/failover.md`](docs/failover.md) — `bin/failover.py`, the reusable
    chain library: route registry, deny list and allowlists, preflight against
    `aiuse --available`, ordered attempts with a JSONL log, fresh-context `ask`. `bin/skillopt_sources.py`
    reads zcode, agy and crush session stores into SessionDigest JSON for it.
16. [`docs/threat-model.md`](docs/threat-model.md) — the threat model (2026-10-20): assets, trust
    boundaries, entry points and ranked threats; what a security review of a PR reads.
17. [`docs/git-guard.md`](docs/git-guard.md) — `bin/ade-git-guard`, the ref hooks and the claim registry: the two
    enforcement points (hooks for refs, the shim for what hooks cannot see), commands, exit codes (0/2/73/77/78),
    claim lifecycle, what is refused and what is not covered, the `ACP_OPERATOR_APPROVED=git-guard` override,
    fail-open, and the integration status (only W1 is built; W2-W4 call sites are listed).
18. [`docs/gates.md`](docs/gates.md) — `config/gates.toml` and `bin/gate-profile` (2026-10-26): the Claude quota gates'
    (`claude-fleet-governor`, `claude-quota-guard`) numbers versioned in git with floors a profile may not cross, and a
    temporary expiring `away` profile (`set --for 72h`), its fail-safe rules and a worked three-day example, and (2026-10-27)
    the `[frontier]` gate: a standing rule (no profile needed): an agent may use a frontier model on its own judgment with a one-line `--frontier-reason`, capped.

## Architecture: agent graphs at two altitudes

The repo began (2026-08-23) as a reference architecture for running Claude as
a **graph of agents**, prompted by
[Graph Engineering with Claude](https://x.com/0xCodez/article/2079141496981184512)
(@0xCodez, 2026-07-20), a tutorial for Claude Code's built-in *dynamic
workflows*. It adds the second altitude the article doesn't cover:
[Orca](https://github.com/stablyai/orca) (forked to
[djbclark/orca](https://github.com/djbclark/orca)), which orchestrates whole
agent *processes* rather than in-process subagents.

### Two graphs, two altitudes

**Micro graph — Claude Code dynamic workflows (in-process).**
Inside a single Claude Code session, the `Workflow` tool runs a plain
JavaScript orchestration script that spawns subagents: `agent()` for one
node, `parallel()`/`pipeline()` to fan work out, JSON-schema contracts on
every node's output, `phase()` for progress grouping. Coordination costs
zero model tokens because it's code, not a conversation turn. Ceiling: one
Claude Code process, one model account, one machine.

See [`.claude/workflows/graph-audit.js`](.claude/workflows/graph-audit.js)
for a working example — fan out N review dimensions, verify each finding
adversarially, synthesize a report. Saved workflows surface as skills by
name in any Claude Code session in this repo (verified 2026-08-23), so
invoke it as `/graph-audit`, optionally with args like
`{"target": "src/"}` — or just ask for "the graph-audit workflow on
<path>".

**Macro graph — Orca orchestration (cross-process).**
Orca's `orchestration` layer is a task DAG across *separate* agent CLI
processes — Codex, Claude Code, OpenCode, Cursor, Gemini, Grok, droid — each
in its own git worktree, possibly on another machine (`--on <environment>`).
A coordinator creates a Run, creates Tasks with `--deps`, dispatches each to
a worker with `worker-start --agent <cli> --worktree ...`, and waits on
`worker_done`/`escalation` via a blocking `check --wait`. This is the same
node/edge vocabulary as the article — a Task is a node, a dependency is an
edge — but the nodes are whole agent sessions with their own filesystems,
not subagents inside one context window. Ceiling: however many worktrees
and machines you're willing to run concurrently; monitorable from the Orca
mobile app.

Full command reference: `orca skills get orchestration` (version-matched to
the running Orca build, currently 1.4.188 — don't rely on a cached copy of
this doc, the binary is the source of truth).

### How they compose

A macro-graph node (an Orca Task dispatched to a Claude Code worker) can
itself run a micro-graph (a dynamic workflow) as its job body. Concretely:
create a Run, create one Task per service whose spec says "run the
graph-audit workflow here", `worker-start` each Task with `--agent claude`
in its own worktree, then block on `check --wait` until every worker
reports `worker_done`. The runnable command sequence lives only in
[`docs/orca-integration.md`](docs/orca-integration.md) — one copy, so this
README can't drift from it (a drift the first graph-audit run actually
caught); the binary-served `orca skills get orchestration` remains the
authority over both.

Each worker is a full Claude Code session that fans out *its own* subagents
in-process via `Workflow` — free coordination inside each node, paid-for
(a real process, a real worktree) coordination between nodes. Use the macro
graph when nodes need process/filesystem isolation, a different CLI or
model account per node, cross-machine placement, or human-in-the-loop
monitoring from the phone. Use the micro graph for everything inside one
node's boundary — it's cheaper and has no worktree/process overhead.

**Heterogeneous fleets are a requirement here, not an option.** The micro
graph is Claude-only by construction — Workflow subagents are always
Claude. The macro graph is the heterogeneity layer: Orca's orchestration
lifecycle (`worker_done`, `ask`/`reply`, escalation, heartbeats) is
CLI-agnostic, so one DAG can dispatch Tasks to claude, codex, opencode,
grok, or cursor workers (all installed on this machine) and they
interoperate through the same structured mailbox instead of sharing a
context window. Group addresses (`@claude`, `@codex`, `@opencode`, …)
exist for genuine fan-out messages. Route each Task to whichever agent is
best or cheapest for it — the article's model-tiering move (step 12),
generalized across vendors.

**A third altitude already exists on this machine and isn't duplicated
here:** `ralph-tui` + beads runs a continuous, scheduled controller loop
over the `ops-djbclark` suite (stayturgid / site-djbclark / site-private /
Shizuku) — the article's pattern 11 (loop-until-dry) applied at the
repo-controller level, converting a PRD into beads issues that agents work
continuously. See the [`ralph-tui-orchestration`](skills/ralph-tui-orchestration/SKILL.md)
skill (in this repo since 2026-10-08) for that system.
**Status 2026-09-21: dormant** — the `ralph-tui` binary is gone from PATH
and its controller workspaces were deleted with `~/src/ops-worktrees/` on
2026-08-23; only `~/.config/ralph-tui/` survives. See
[`docs/coding-factory.md`](docs/coding-factory.md).

### graph-audit and macro-graph status (2026-08-23)

`graph-audit` has run twice for real, pointed at this repo itself:

1. First run (pre-edit script): slow but complete (7 agents, ~33 min,
   finishing in the background long after its findings were read from the
   journal mid-run). Final tally: five findings, four confirmed, one
   refuted — all four confirmed ones were independently identified and
   fixed before the run even finished.
2. Second run (17 agents): the full Audit → Verify → Synthesize graph
   completed, confirming 9 findings — including two prompt-injection
   channels in the workflow's own prompts and a missing-`--ack` deadlock
   in the Orca doc's fan-out loop. All nine are fixed as of this commit,
   and the workflow now accounts for confirmed vs refuted vs
   unadjudicated outcomes explicitly.

A live heterogeneous macro-graph dispatch has also completed: one claude
worker plus one codex worker under a single Run, both tasks settled
`completed`, with failure/recovery lessons recorded in
[`docs/orca-integration.md`](docs/orca-integration.md).
