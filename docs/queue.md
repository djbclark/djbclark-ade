# Queue — accepted, not started

Work the operator has explicitly queued. Newest first. Items leave this file
when they ship (into the relevant doc) or when they're dropped (say why).

## Follow-ups from the 2026-10-20 reviews

1. **`bin/firecrawl-router` serve-only form binds any `--listen` with no token** (adversary, threat-model
   review 2026-10-20: `--open` refuses a non-loopback address, serve-only does not). Make serve-only refuse a
   non-loopback `--listen` the same way; one small PR with a test.
   **Done 2026-10-20** (PR 14): both tokenless forms refuse a non-loopback `--listen` (exit 2) and `serve()`
   checks the address it actually bound before it accepts a request. Carried from that review (adversary
   INFO, non-blocking): (a) the tokenless loopback handler does not check the `Host` header, so a page in a
   local browser could reach it by DNS rebinding; add a `Host` allow-list (`127.0.0.1`, `localhost`, the bound
   port); (b) the bearer compare at the handler uses `!=`; use `hmac.compare_digest`. One small PR for both.
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

## Keep every machine current, and a changelog (djbclark, 2026-10-20; proposal Q26, T8)

djbclark, 2026-10-20: "We need a clear way to keep all of djbclark-ade up-to-date on new
systems, and also we should have a changelog so people know what changes or new features are
added." Done the same day: `CHANGELOG.md` (Keep a Changelog form, seeded from the merged PRs
since 2026-10-09), AGENTS.md code-review rule 10 (every PR adds its line), README "Update
(this machine)" (the manual procedure today), proposal v2.4 (T8, 4.4 item 9, §9.4 Q26). Queued:

1. **`bin/ade-update`, the interim one command** (one small PR, Sonnet `code` slice): `git -C
   ~/src/djbclark-ade pull --ff-only` (stop and print `git status` on a dirty tree or a diverged
   branch; never stash another agent's edits), then `bin/skill-everywhere --check` over every
   `skills/*` (relink what is missing), the `~/.claude/{commands,agents,hooks}` symlink check,
   and print the `CHANGELOG.md` entries between `~/.local/state/ade/applied` (written at the end)
   and the new head; `--check` only reports. A test with a temp repo. README's section then
   names it. It becomes `ade update` in Phase 1 (proposal 4.4 item 9).
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
      b. agy pools `antigravity/claude_gpt` (7 refusals) and `antigravity/gemini` (6) report
         "not in `aiuse --available`".
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

## Review the Jev-vs-GLiDE dual review (ends by 2026-10-23)

**Started 2026-10-11 (operator).** The Jev-only prompt-effort review was closed the
same day; see `docs/jev.md` "Dual review". Jev and GLiDE answer the same prompt-effort
(hook) and agent-choice (`route_agent.py --brief`) questions side by side for at most 12
days; the window closes itself (mode goes off). On 2026-10-23 run
`bin/jev report --review dual-1 --json` and `bin/jev disagreements --site
agent-choice --between`, label disagreements, then ask djbclark per backend: act, keep
shadow, or off. A self-removing launchd job (`com.djbclark.jev-remind-2026-10-23`)
pings Hermes that morning.

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
