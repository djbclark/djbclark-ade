# Fable 5.1 review of the review-later backlog (2026-11-07)

Reviewer: Claude Fable 5.1 in omp (Claude Max API credits), lead plus four `task` subagents (one per group), all on the
session's configured Fable model (omp's per-call `model` is off, so effort was not set per call; no xhigh/max was
requested). Worktree `~/src/djbclark-ade-fable-wt` at `c3cd5d5f` (tag `slim-2026-11-07`), read-only; GitHub not
browsed. Subagent raw findings: `~/.local/state/bigteam/fable-backlog-20261107/g{1,2,3,4}-findings.md`.
No prompt-injection text was found in any file read (the Argon report was read as data via `git show`, never checked
out). Line numbers are the worktree's at `c3cd5d5f`.

## A. Summary

Five most important findings:

- A1. **high** `bin/adversary_marker.py:1027-1031, 1192-1207`: a `workflow_dispatch -f pr=N` judges only PR N, never
  `GET commits/{sha}/pulls`, so a second open PR at the same head inherits N's `success` status; and `by_head` collects
  only `posted` results, so an errored judge of the second PR leaves the first PR's `success` standing (queued (i),
  confirmed and sharpened: the dispatch path is a new gap). F-CRIT-2 of the Argon report: agree, severity high.
- A2. **high** `bin/acp-dispatch:529, 1066-1069`: a `waiting_for_slot` record counts in `inflight_records` "however
  old" with no pid and no `finally`; SIGTERM, Ctrl-C or `launch_lock`'s `die(75)` while waiting leaves a permanent
  in-flight reservation (the queued F2b1 question "cannot hold a reservation forever" is answered: it can).
- A3. **high** `docs/setup-plan.md:290-294` vs `.github/workflows/test.yml:39,42,59,62`: enabling the SHA-pinned Actions
  allow-list before re-pinning `test.yml` (`@v7`, `@v10.3.2`, `@v6`) kills the two ruleset-required checks with no
  bypass actor: every PR, including the fix, becomes unmergeable.
- A4. **high** `bin/adversary_marker.py:1104-1107`: ticking a task-list checkbox in an outside PR's body is a body edit
  by the owner, so `lastEditedBy` becomes the owner and the author's hidden pasted APPROVE counts (queued (f),
  sharpened: one click, no typo fix needed).
- A5. **high** `docs/mcp-servers.md` (dd70d507 hunk): says `bin/firecrawl-router` "was deleted 2026-11-06 (Wave 3b)";
  it was restored by operator ruling 2026-11-07 (`docs/slim/log.md:79`, file in tree): a new false statement.

Verdict per group:

- A6. Group 1 (external boundary): **needs fixes** (F2a, F2d); F2a1 sound; F3d unsafe as an exposure, accepted.
- A7. Group 2 (dispatch and routing): **needs fixes** (F2b1 slot-wait leak, `_merge_pool` label mismatch, F2c
  Paseo-only reading passes the floor).
- A8. Group 3 (docs correctness): **needs fixes** (F1b 54 real / 2 refuted / 1 wrong fix; F1c one high; F1a one
  medium gap; roster check passes).
- A9. Group 4 (plans and operator material): **needs fixes** (F4a one unsafe step; F3b credential tarball; F4d
  `run` vs `get`); F4b sound with gaps; F4c sound.

Counts: critical 0, high 5, medium 20, low ~25 (F1b's low rows counted once as a block).

## B. Findings per item

### B1. F2a. review-launch, review-pr, adversary-marker.yml, adversary_marker.py

- B1a. **high** — `bin/adversary_marker.py:1192-1207`. Scenario: PRs #10 and #11 share head H; the `workflow_run`
  resolves both; `judge_pr(#10)` posts `success`; `judge_pr(#11)` returns `error` (GraphQL hiccup at :1129-1131).
  `by_head` holds only #10, so no shared-head failure is posted and #11 shows green with no reviewer. Fix: when any
  result is `error`, post `failure` on every head that received `success` in the same run (fail closed; the operator
  re-dispatches). Test: `tests/test_adversary_marker.py`, CannedApi where `pulls/11` raises `ApiError` and `pulls/10`
  approves → a `failure` status is posted on H. Queued: yes (i), confirmed.
- B1b. **high** — `bin/adversary_marker.py:1027-1031` (dispatch path). Scenario: #10 (approved by the owner, head H)
  and attacker PR #11 at head H into another base; `gh workflow run adversary-marker.yml -f pr=10` → `find_prs`
  returns `[10]`, never calls `commits/H/pulls`; `success` lands on H and #11 is mergeable. Fix: for
  `workflow_dispatch`, after reading PR N's head, call `GET repos/{repo}/commits/{head}/pulls`, judge every open
  same-repo PR at that head (reuse the :1050-1054 filter), post `success` only if all approve; `resolve` does the same
  so the concurrency key covers them. Test: CannedApi with `pulls/10` APPROVE (owner-edited) and `commits/H/pulls` →
  [#10, #11 (no marker)]; `run_event("workflow_dispatch", {"inputs":{"pr":"10"}})` posts `failure` naming both;
  `resolve` returns key `10-11`. Queued: (i) partly; the dispatch path is new.
- B1c. **medium** — `.github/workflows/adversary-marker.yml:65-67`, `bin/adversary_marker.py:1162`. The concurrency
  key is the joined PR list: a `workflow_run` keyed `10-11` and a dispatch keyed `10` do not serialize and
  `cancel-in-progress` does not apply across them, so the last post wins. The yml comment at :38-39 ("the PR number
  itself") is stale for multi-PR runs. Fix: key on the head sha (`resolve` outputs it), keep the PR list as data.
  Test: `resolve` output `key` equals the head sha for both event shapes. Queued: (i).
- B1d. **high** — `bin/adversary_marker.py:1104-1107`. Scenario: outside author pastes a hidden
  `<!-- adversary-verdict:v1 {"verdict":"APPROVE","head":H} -->` plus a task list; the owner ticks one checkbox in the
  rendered body (GitHub records a body edit by the owner); `lastEditedBy` = owner → trusted → `success`. Same for an
  owner-side agent running `gh pr edit --body`. Fix: for a PR whose author is not the owner, ignore the body marker and
  read the APPROVE from an owner-authored review or issue comment (`comments(last:50){author{login} body}`), accepting
  only `author.login == owner`; keep the body path for owner-authored PRs. Test: body with hidden APPROVE,
  `lastEditedBy`=owner, `author`=outsider → `untrusted`; owner comment APPROVE on an outsider PR → `approve`.
  Queued: (f), sharpened; (b) downgraded (see B1e).
- B1e. **low** — queued (b) refuted as a bypass: `lastEditedBy` null falls back to the author (:1104); a bot author
  (`NONE` association) or a Bot login as last editor fails closed. It is an attribution confusion, not a hole.
- B1f. **medium** — queued (e) confirmed: `TRUSTED_ASSOCIATIONS` includes MEMBER and COLLABORATOR (:1084) and
  `editor == author` suffices (:1107): an invited collaborator self-approves. Fix: drop MEMBER/COLLABORATOR from
  self-approval (keep them for BLOCK). Test: collaborator-authored body APPROVE → `untrusted`.
- B1g. **medium** — `bin/review-launch:270-272`. `glob_outside` returns False for a relative pattern, so `Glob
  pattern="link/**"` through a committed symlink `link -> /outside` is not judged by the launcher; only Claude Code's
  own `blockReadsOutsideWorkingDirectories` (:116) stands, and the self-check (`check_targets` :473-480) never
  exercises a symlink. `Read link/x` IS caught (:256-259, realpath). [INFERENCE] whether Claude resolves symlinks in
  that setting. Fix: resolve the relative pattern's prefix with `os.path.realpath(os.path.join(base, prefix))` and apply
  `path_outside`; add a self-check target `wt/link -> outside` (`Glob` and `Read`, required); `bin/review-pr` refuses
  (exit 2) a head whose `git ls-files -s` has mode `120000` entries resolving outside the worktree. Test:
  `tests/test_review_launch.py`: temp wt with `link -> /tmp/x`; `glob_outside("link/**", wt, wt)` True. Queued: no.
- B1h. **medium** — `bin/review-pr:170-186`. Trust is by PR `author` only: a trusted-author PR whose head was pushed
  by a collaborator (shared branch, "allow edits by maintainers") is reviewed as trusted. Low practical risk; note it.
- B1i. **medium** — `bin/review-launch:96`, `bin/acp-dispatch:111`: `--mode read-only` keeps `WebFetch`, an egress
  channel; the mode name hides it. Fix: document "read-only = network on" or make `--perm deny` the default for
  untrusted input.
- B1j. **low** — queued (g) confirmed: `ensure_check` :615-623 trusts any file under `REVIEW_LAUNCH_STATE_DIR` whose
  `key` matches, no expiry or signature (same-user threat). Fix: re-run when older than 24 h, or HMAC with a 0600
  per-user secret.
- B1k. **low** — queued (h) confirmed as designed: the trip fires on the `assistant` tool_use event (:414-420) after
  the call may have started; the self-check proves the first layer per version. No change.
- B1l. **low** — queued (j) downgraded: the bypass scan (:682-683) walks every argv token, so a prompt token like
  `--agents=x` causes a false refusal (exit 2), never a bypass (the prompt goes after `--`, :152). Fix: scan only
  tokens before the first `-p`/`-f` value, or `parse_known_args` and refuse leftovers.
- B1m. Content-type allowlist (:100, :405-407): any item not in {text, thinking, redacted_thinking, tool_use} trips,
  including `fallback`. Sound. Docs: review-boundary.md:37 and AGENTS.md rules 1, 9, 11 match the code.

### B2. F2a1. The self-check model fix

- B2a. Sound: `check_key` (:562-565) hashes `model or ""` into the key, so a model-A check is never reused for B;
  `fallback` is not in `CONTENT_TYPES`, so it trips inside a launch.
- B2b. **low** — `bin/review-launch:564`: `""` means "Claude's default model", which can change without a
  `claude --version` change, so an old `""` check may describe a different model. Fix: key on the init event's
  `model` field, re-run when it differs. Test: two fake `claude` binaries with the same version but different init
  `model` → two check files. Queued: no.

### B3. F2d. Cross-check of the Argon injection report

- B3a. F-CRIT-1 (fleet-watch / home-agents item 24): **not checkable** from the worktree (`site-public-djbclark`,
  `home-agents.md` outside). Severity if true: high, not critical (needs the launchd job and a registered session).
- B3b. F-CRIT-2: **agree, high not critical** (lead confirmed): mechanism at B1b/B1c; the attacker's PR must carry the
  exact already-approved commit, so the merged content is the approved content; the harm is the wrong base and a DoS
  flip; `bin/pr-policy` closes stranger PRs within 600 s.
- B3c. F-HIGH-1 (attribution): **agree** on items 1 (checkbox, B1d) and 3 (collaborator, B1f); **partly** on 2 (App/bot
  edits fail closed, B1e); **disagree** on 4 as live: the Action exists only in this repo; `config/pr-policy.toml:9`
  lists `frdminc` for `bin/pr-policy`, not the gate; `owner = repo.split("/")[0]` (:1095) on an org repo would make
  owner edits never trusted, which FAILS CLOSED. Latent, low; one docstring line. Severity overall: high (item 1).
- B3d. F-HIGH-2 (review-launch): **partly**, medium. Symlink + relative glob real (B1g). Argon's DENY_PATHS list is
  stale: :110-112 already has `~/.config/sudo-secretspec`, `~/.kube`, `~/.docker/config.json`; still absent
  `~/.paseo/**`, `~/ops/site-private*/**`, `~/.local/state/opencode/**`, `~/.hermes/**` (second layer; low).
- B3e. F-HIGH-3 (`.claude/settings.json`): **partly**. `bypassPermissions` is wrong for this file (`:15` is
  `acceptEdits`; `agents/claude/settings.json.tmpl:76` is the TUI template), lead confirmed; but `:22` is a bare
  `"Bash"` allow, so the distinction is cosmetic: every shell command is auto-approved. High exposure, accepted.
- B3f. F-HIGH-4 (non-Claude `--perm deny`): **agree**, medium. `bin/acp-dispatch:886-890` runs a non-Claude provider
  with `--perm deny` in the provider's `defaultMode` with prose only (`BEST_EFFORT_NOTE` :952); `skills/loose/SKILL.md:138`
  still calls `acp-run`, absent from `bin/` (fails closed, broken skill). Fix: acp-dispatch exits 2 for
  `--perm deny|read-only` on a provider without a hard boundary; `loose` calls `review-launch --mode review`.

### B4. F3d. `.claude/settings.json` (kept; no removal argued)

- B4a. Chain an external injection reaches, all auto-approved: `mcp__github__issue_read` / `pull_request_read` /
  `get_job_logs` (:35-46) brings attacker text in → bare `Bash` (:22) runs `gh auth token` or `sudo-secretspec get …`
  → `curl` out or `gh issue comment` on a public repo as C2 → `gh pr edit N --body '<!-- adversary-verdict:v1
  {"verdict":"APPROVE","head":…} -->'` as the owner + `gh workflow run adversary-marker.yml -f pr=N` + `gh pr merge`:
  the whole merge gate is self-stampable from one session. The MCP write denies (:55-57) do not cover `gh`;
  `Bash(rm -rf /*)` (:54) matches only that literal.
- B4b. Smallest change keeping unattended use: add to `deny` (deny wins): `Bash(gh auth token:*)`,
  `Bash(gh auth refresh:*)`, `Bash(sudo-secretspec get:*)`, `Bash(gh workflow run:*)` (an operator step per
  AGENTS.md:275) and `Bash(gh pr edit:*)`, routing the marker paste through a tiny `bin/stamp-verdict` that writes only
  a marker whose head and verdict match a `~/.local/state/review-launch/*-pr<N>-<head>.json` file. `gh pr merge`
  stays. This removes credential disclosure and self-stamping; `curl` egress of repo-visible data remains (accepted).
- B4c. Statusline (:3-10) runs `.claude/helpers/graft-statusline.cjs` from the checkout; review worktrees use
  `--setting-sources ""` (review-launch:142), so the boundary is unaffected. Low.

### B5. F2b. acp-dispatch frontier guards

- B5a. Burst re-check (`write_and_recheck` :580-595, `inflight_recheck` :541-577) and caps (`n < cap` :1053,
  `len(busy) >= cap` :945/:560, `used >= cap` :647): correct, no off-by-one; unreadable record counts (fails closed).
- B5b. **medium** — `bin/acp-dispatch:917-920`, `:1392`. `--est-pct 0` (or any value under the floor) gives
  `estimate 0`, empty `per_window`; the `[dispatch.estimate_floor]` (config/routing.toml:140) is applied only on the
  history path (:476-486), so the slice is admitted at any remaining % and reserves 0 for those behind it. Whether
  `--est-pct` is an operator override is undocumented. Fix: `estimate = max(a.est_pct, floor)` (and `min(…, cap)`),
  `source="explicit (floored)"`, or require `ACP_OPERATOR_APPROVED`. Test: `dispatch("codex","gpt-6-astra","--kind",
  "frontier","--est-pct","0")` at 30 % left → exit 5 `wont-fit`, `estimated_usage_pct >= 60`. Queued: no.
- B5c. **low** — :549-553: the per-wave cap counts only records ahead by `started`, so a slice judged first can still
  be withdrawn by `inflight_recheck`; fails toward withdrawal, note in docs only.

### B6. F2b1. The three Codex fixes (2a4cd51)

- B6a. **high** — `bin/acp-dispatch:1066-1069, :529, :376-392, :351`. Scenario: a gated dispatch sets
  `waiting_for_slot=True` and sleeps at :1069; SIGTERM/Ctrl-C, or `launch_lock` `die(…, 75)` at :388 after
  `LOCK_GRACE_S` (reachable now because `recheck_after_wait` runs `pool_reading(fresh=True)` inside `launch.lock`), or
  any exception under the lock. Nothing clears the flag (only the normal returns :1023, :1060, :1084 do); `atexit`
  (:351) releases only the load-watch reservation; `inflight_records` (:529) counts a `waiting_for_slot` record however
  old. Result: a permanent in-flight reservation until a human edits the record. Fix: write `pid=os.getpid()` with the
  flag, count a waiting record only while `pid_alive`, wrap the wait in `try/finally` (+ SIGTERM handler) that writes
  `status="unavailable", unavailable_class="load", finished=now, waiting_for_slot=None`. Test:
  `tests/test_acp_dispatch.py TestLoadGateAndCap`: `waiting.json` with `waiting_for_slot: True`, a dead pid, `started`
  3×grace old → `inflight_records` returns `[]`; end-to-end `LW_MAX_AGENTS=1 --load-wait 60`, SIGTERM after the flag
  appears → `finished` set. Queued: F2b1 asked exactly this; not in a–j.
- B6b. **medium** — `:1048-1058, :1075`. Lock order launch → inflight is right (no reverse acquisition anywhere) but
  the fresh quota read (aiuse + `paseo usage ls` subprocesses) runs under `launch.lock`, whose acquisition is
  `LOCK_NB` + 180 s grace + `die(75)`: one slow read makes every concurrent dispatcher exit 75 (and, with B6a, leak).
  Fix: take the fresh reading before `with launch_lock():` on the `waited` iteration; keep only `inflight_recheck`
  under the locks. Test: fake aiuse sleeping past a patched `LOCK_GRACE_S` while a second gated dispatch waits → the
  second fails only by the agents-cap deadline text, record `finished`.
- B6c. **low** — `:1072-1089, :552-556`: after a wait the frontier allowance is re-judged on the per-wave count only;
  `judged_pool_block` (cap/window floors) is not re-run on the fresh reading, so a slice granted at 60 % launches after
  the pool fell to 15 %. Fix: re-call `frontier_judged(...)` in `recheck_after_wait` when `rec["frontier_judged"]`.
- B6d. Envelope read (`:1182-1196`): every bad shape (`null`, list, string, int, `structured_output` null/string, missing
  `report`) raises and is caught → `no-report` exit 3; sound. **low** — the reader ignores an envelope's own `exit`/
  `check` fields when the process rc is 0, and no fake mode exercises a `fallback` trip ([INFERENCE] on review-launch's
  exit discipline). Fix: classify by `doc["exit"]` when non-zero; add FAKE_RL_MODE `tripped-envelope`.
- B6e. **medium** — `bin/route_agent.py:714` (`_merge_caps` by exact key), `:1183` (Paseo label = `label or id`),
  `:829`; regression test `tests/test_route_agent.py:2446-2453` uses one label ("5-hour") on both sides. The repo's own
  fixtures label aiuse windows `"weekly"` (tests/test_gates.py:162) and Paseo's `"Weekly"` (tests/test_acp_dispatch.py:416,
  tests/test_gates.py:220): merged `windows` carries both keys, the per-window tightening never fires for the weekly
  window, and `binding_window_note`, `measured_usage_windows` and `reserved_usage` carry a phantom second weekly.
  `remaining = min` still holds, so admission is not loosened; `_tighter` treats None as unknown (never loosens), right.
  Fix: normalise labels (`lower()`, map Paseo ids `five_hour`→"5-hour", `weekly`→"weekly") in `usage_from_paseo`.
  Test: `_merge_pool(into={"claude": {"remaining": 70, "windows": {"5-hour": 70, "weekly": 90}}}, "claude",
  usage_from_paseo([row("claude", windows=[win("Weekly", left=50)])])["claude"])` → one `weekly` key = 50. Queued: no.
- B6f. **low** — `:713`: `pace_ratio`/`window_minutes` are dropped when Paseo is the tighter side (its entries carry
  None), so the burn-first pace penalty disappears. Fix: keep `prior[k]` when `merged.get(k) is None`.

### B7. F2c. route_agent frontier gate on merged quota

- B7a. The rule as implemented (`_fold_paseo` :1255-1261 records `paseo_unknown`; `judged_guard_block`
  ade_gates.py:195-197 blocks only on `unknown`; docs/gates.md:49-50 says so) is a defensible reading of the ruling
  **when aiuse is fresh and complete**: aiuse is primary, its staleness (>25 min → windows None) and the fable sublimit
  already fail closed. No code assumes `five_hour`/`session` labels exist (`usage_from_paseo` is label-agnostic; the
  gate reads `remaining` and `fable_left`).
- B7b. **medium** — `bin/route_agent.py:1262-1265, :705-716, :845-846, :1388-1405`; `bin/ade_gates.py:203-208`.
  Scenario C: aiuse's Claude row is 26 min old (5-hour was 10 % last read; now `windows={"5-hour": None, "weekly":
  None}`, `remaining: None`), Paseo fresh `Weekly` 65 %, `Weekly (Fable)` 38 %. Merge → `remaining 65`, Paseo's
  `age_s`; gate: not unknown, fresh, 65 ≥ 30, 38 ≥ 15 → **grants** with the 5-hour window (the one the 30 % floor was
  raised for, gates.md B2a) unmeasured. Scenario B (aiuse has no claude row) grants the same way. Scenario A (aiuse
  fresh 5-hour 20 %) correctly denies. Fix: in `judged_guard_block` block when any `state["windows"]` value is None and
  require the known Claude window set (`[frontier] claude_windows = ["5-hour", "weekly"]` in config/gates.toml) to carry
  numbers, so a Paseo-only reading fails closed as gates.md:50 promises. Test: `tests/test_gates.py`: aiuse without
  claude (and a 26-min-old row), `ROUTE_AGENT_PASEO_USAGE_JSON` = weekly 65 / fable 38 → block names the missing
  5-hour window; `frontier_per_wave("claude")` returns the closed 1. Queued: no.
- B7c. **low** — `:1189-1193`: a Paseo `problem.kind` that signals a real limit (rate-limited/exhausted) is folded as
  `unknown` and, beside a ≤25-min aiuse cache, does not block ([INFERENCE] on Paseo's kinds). Fix: treat a limit-class
  problem as remaining 0.

### B8. F1b. The 57 unverified W3 findings

Table in section C. Verdict: 54 real (7 medium, rest low under the docs' dated banners), 2 refuted (threat:208,
threat:273), 1 real with a wrong proposed fix (tui:388). Every JSON `line` is offset against the worktree (−7
rearchitecture, −14/−15 threat-model, −7 tui-lessons, −10 upstream-issues); the quoted text is present in each case
checked. No row is a pure dated-history sentence.

### B9. F1c. The 87 W3 fixes (dd70d507)

- B9a. **high** — `docs/mcp-servers.md` (diff line 341: "the router (`bin/firecrawl-router`) was deleted 2026-11-06
  (slim-down Wave 3b), so no GitHub token remains on the Mac side"). `bin/firecrawl-router` exists; `docs/slim/log.md:79`
  records its restoration by operator ruling 2026-11-07; `docs/threat-model.md:33,122` (same commit) say "kept". An
  agent auditing secrets or re-pointing `com.djbclark.firecrawl-mcp` skips the router. Fix: "deleted in Wave 3b and
  restored by the operator's ruling of 2026-11-07; verify the token claim against `bin/firecrawl-router`". Test: a docs
  check failing when a doc says `bin/<name>` is deleted while it exists. Queued: no.
- B9b. **low** — `docs/skills.md` (diff 565): "E10 deleted `paseo-screen`, `retro`, `steps` and `skillopt-sleep`":
  the skills exist; E10 deleted their slash wrappers (reports/wave3-E10.md:20,24). Fix: say "wrappers".
- B9c. **low** — the shim is dated "since 2026-11-06" in AGENTS.md:14, rearchitecture.md:452, agent-guard-contract.md
  and "since 2026-11-07" in orchestration-practices.md and four other hunks (E6 merged 2026-11-07 ~05:30Z, log.md:105).
  Pick 2026-11-07.
- B9d. Checked consistent: `identity_refusal` at `bin/acp-dispatch:658`; `load-watch admit` exit 75; `.mcp.json` lists
  `graft`; trust-table rows match ledger-rulings.md:64; vendor fleet-watch entry matches README/AGENTS.

### B10. F1a. The completeness critic (README.md, AGENTS.md)

- B10a. `bin/ade-roster --check`: rc=0, no output (log `roster-check.log`): README's roster matches.
- B10b. **medium** — `README.md:61-66`, `AGENTS.md:17,150`: the retired list names replacements for bigteam
  (`fan-out`), the quota guard/fleet governor (Paseo plugins) and pr-wait/local-review (`review-pr`) but none for:
  helm (`paseo permit ls`, only in rearchitecture.md:498), self-slash and the successor launch (`skills/handoff`,
  docs/context-hygiene.md), session-finder search (`paseo ls -a`), autorename (docs/workspace-layout.md), herdr-sleeper
  (Paseo persistence) and the web ladder (none: R2-15). Fix: one "replaced by" phrase per retired tool in README:61-66.
- B10c. Standing orders vs 2026-11-07 rulings: orders 9, 10 and Machine context checked, no contradiction; rule 9
  (Codex advisory) matches threat-model.md:86. Orders 1–8 and 11 not cross-checked line by line (budget).

### B11. F3b. operator-batch.md and operator-prompts.md

- B11a. **medium** — batch C22-C27 / prompts P11 group 3: `~/Library/LaunchAgents/com.djbclark.mods-reminder.plist`
  runs `~/src/djbclark-ade/skills/teach/scripts/next_item.py`; `teach` moved to site-djbclark
  (changelog.d/claude-determined-maxwell-uvddaz.md:9) and the path is absent from the Mac checkout; C27 relinks the
  command but no item repoints the job, so it fails every tick after the merge. Fix: a C item repointing
  `ProgramArguments` (or bootout). Test: `plutil -p` shows the new path. Queued: no.
- B11b. **medium** — batch C48, C51, C52 / P11 group 6 (unattended): the backup tarball includes `~/.grok`
  (`auth.json` present), `~/.gemini/oauth_creds.json`, `~/.pi`, `~/.zcode`, `~/.config/goose`, `~/.cline`,
  `~/.copilot`: credential homes into a default-mode tarball in `$HOME` with no exclusions (`bin/ade-backup-stores`
  excludes them on purpose). C52's "after confirming no tool uses it" cannot be done by a no-stop agent. Fix: an
  `--exclude` list (`auth.json`, `oauth_creds.json`, `*token*`, `credentials*`), `chmod 600`, make C52 a stop point.
  Test: `tar tzf` has no `auth.json|oauth_creds`. Queued: no.
- B11c. **medium** — batch C20 `sudo rm /etc/sudoers.d/acp-dispatch-pmset` in a no-stop prompt: hangs or fails on the
  password prompt; the file is already absent on this Mac. Fix: mark "operator, by hand; already absent 2026-11-07".
- B11d. **low** — prompts P11 group 2 "C16, C17 and C19 name unverified labels": C17 is the `rm ~/.local/bin/{web-get,
  web-digest}` line (already gone); the unverified labels are C15, C16, C19.
- B11e. **low** — batch C7, C9-C19: of the plists the batch deletes only `com.djbclark.acp-dispatch-reap.plist` exists;
  only acp-dispatch-reap, load-watch, firecrawl-mcp are loaded; C1's `jev_effort_hook.py` is gone too. Harmless
  ("skip any not loaded") but say so.
- B11f. **low** — batch C29/C31 omit `~/.claude/commands/herdr-tidy.md` and `orca-tidy.md` (present; skills deleted
  2026-10-31).
- B11g. **low** — batch C5 vs `agents/claude/settings.json.tmpl:533`: the template still registers
  `claude/hooks/quota_nudge.py` (its state file's producer is gone), so every render re-adds the hook C5 removes by
  hand. Fix: drop the template entry and the hook in the follow-up PR; adjust `tests/test_hook_deadline_timeouts.py`.
- B11h. **low** — C9 `skillopt-sleep` was a `uv tool` install: `uv tool uninstall`, not `rm` of the link; C23
  `skill-everywhere report` wording unclear; P11 group 3 says `--check` alone, which the tool rejects without names
  or `--all`.
- B11i. Commands checked against repo tool usage and found to exist: `load-watch admit|watcher show|set --name|test|
  sample --dry-run -v`, `review-launch --check --mode`, `route_agent.py services --check-models|show`, `acp-dispatch
  --model --kind --perm --name -p -C --task`, `context-budget-check --instruction-lint`, `skill-everywhere
  --all|--check|--remove|<name>`, `ade-update`. Order inside A/B/C: no step consumes a later step's output.

### B12. F4a. docs/setup-plan.md

- B12a. **high** — `docs/setup-plan.md:290-294` (S5 SHA-pinned Actions allow-list) vs `.github/workflows/test.yml:39,
  42,59,62` (`actions/checkout@v7`, `astral-sh/setup-uv@v10.3.2`, `actions/setup-node@v6`; only
  `adversary-marker.yml` is SHA-pinned). Scenario: `just harden actions` runs before `test.yml` is re-pinned → the
  `pytest-linux` and `context-policy` jobs cannot start → the two ruleset-required checks never post → every PR,
  including the fix, is unmergeable (no bypass actors). Fix: S5.1 "first pin `test.yml` to SHAs (plus a dependabot.yml
  or zizmor check), then enable the allow-list". Test: a test over `.github/workflows/*.yml` asserting every `uses:` is
  `@<40-hex>`; fails on the worktree today. Queued: no.
- B12b. **medium** — `:281-283` (S5 "collaborators only"; "a Dependabot PR must still work"): no `.github/dependabot.yml`
  exists, so nothing breaks there today; the live risk is the opposite: our own PRs come from Claude Code's GitHub
  integration (`claude/determined-maxwell-uvddaz`) and Cursor Cloud (`bin/cursor-cloud`), and AI review comments from
  Apps (rule 9). Whether an App-authored PR or comment passes a collaborators-only PR/issue/interaction limit is
  stated nowhere ([INFERENCE]). Fix: a probe step per App in a throwaway repo before `just harden` applies the limits;
  record the outcome in `[hardening]`.
- B12c. **medium** — `:255-271` (S4 unattended `just update --auto`): no rollback. Concrete: (a) a Paseo daemon
  upgrade restarts it and loses unfinished turns (A1; "mid-turn" skip still restarts idle resumable sessions,
  `session-recovery` under trial A4/A6); (b) an automatic plugin upgrade installs unsandboxed daemon code without the
  "read the source" review the plugin policy requires (A2, PLAN J6); (c) a `graft` upgrade can change the graph format
  and MCP tool set with no `graft build` after; (d) `skill-everywhere --all` after a site fast-forward relinks
  everything unreviewed. Fix: per-component `hold`/`rollback` fields in `[install]`; auto-update only components whose
  probe (`review-launch --check`, `graft build`) passes; plugins and provider CLIs opt-in.
- B12d. **medium** — `:323-345` (S7, Grok Bot with the owner's GitHub session): S7.4's never-list omits that the bot
  can (i) edit any PR body and write the `adversary-verdict:v1 APPROVE` marker the gate trusts (an OWNER edit),
  defeating the gate; (ii) delete the `merge-gate` environment or rotate the App key; (iii) set repository secrets;
  (iv) act on every other owner repo. "Change nothing else" in a prompt is advisory. Fix: add those to S7.4, prefer the
  second test account's session, require the API read-back plus an audit-log check that only the expected setting
  changed. Test: `bin/ade-browser-task` refuses templates naming `/pull/`, `/settings/secrets`, `/settings/rules`,
  `/settings/environments`.
- B12e. **low** — order and feasibility: S3b.5 (deliver keys to Paseo) needs Paseo installed and probed (S3) and the
  plugins that read provider tokens (`session-guard`) need the keys before their settings apply; the plan does not say
  `just keys` runs before plugin settings. S8.1's `.github/app-manifest.json`, S7.2's `prompts/browser/`, S3a's
  `prompts/setup/hermes.md` do not exist and are not marked "to be created". S1's "local file wins" means a local
  `[hardening]`/`[install]` override is not drift under S6; say which file the drift check reads.
- B12f. Unverified external facts (no primary source fetched here): line 64 `brew install
  frdminc/sudo-secretspec/sudo-secretspec` (the installed binary is `/usr/local/bin/sudo-secretspec`); line 67 aiuse
  "Homebrew or PyPI" (installed via pipx); lines 69-71 `npx skills add getpaseo/paseo`, the plugin author list,
  `claude-code-entrypoint-env`; line 76 `scripts/sync-plugins.mjs` behaviour; lines 79-80 the four `djbclark/paseo-*`
  repos; line 92 antigravity as a Paseo provider; line 120 the `ovhcloud-api` skill; S3b.1 `sudo-secretspec check|set`,
  `secrets-collect` upstream, `run` requiring `TELEGRAM_BOT_TOKEN` (line 192); S5.1 the github.blog "restrict PRs to
  collaborators" (2026-02-13), "Issues: collaborators only (2026-06)" (Visual Studio Magazine only), interaction
  limits `six_months`, GitHub MCP lockdown mode (PR 1391), "code scanning for AI applications" (pondero.ai only), "the
  2026 Comment and Control disclosures", `safe-settings` org-only (line 309); the `pull_request_target` brownouts
  2026-11-09/16 (from research/wave4-2026-11-06.md).

### B13. F4b. vendor/README.md

- B13a. **low** — `vendor/README.md:22-33`. All named homes exist on this Mac (`~/src/sudo-secretspec`, `~/src/peer-link`,
  `~/src/paseo4herdr`, `~/src/herdr4paseo`, `~/src/paseo-runner`, `~/src/paseo`, `~/src/litellm`,
  `~/ops/site-public-djbclark`, `~/ops/site-private`, `~/.local/bin/cswap`, `~/.local/bin/aiuse`, the Hermes skill,
  `~/.codex/hooks.json`). Gaps: no local path for site-djbclark (`~/ops/site-public-djbclark`, third
  `skill-everywhere` root, bin/skill-everywhere:21,47), site-private, or the two bridge repos (one GitHub repo named
  for both, unverified); brew path for sudo-secretspec doubtful (binary under `/usr/local/bin`); graft "v0.12.0" stale
  (0.28.1 installed). Missing rows referenced elsewhere: `~/ops/site-private/bin/hook-deadline` (every Claude hook
  runs through it, agents/claude/settings.json.tmpl:533: the important one), `com.djbclark.firecrawl-mcp` + the
  `~/.local/bin/firecrawl-router` link, site-djbclark's `bin/heavy-shim` and `bin/change-hermes-ssh-gate` (C27, C40),
  `prompts/paseo-contribution-review.md` (C70), `tools/book-to-kb` (C26). Fix: add local paths and those rows.

### B14. F4c. PR 297 body claims (docs/slim/log.md:74-85)

- B14a. The log paraphrases the body (no verbatim What changed / Tests / checklist). Checked true: `bin/firecrawl-router`
  restored and `tests/test_firecrawl_router.py` has 61 `def test_` (not run); templates' `firecrawl` MCP entries back
  in codex, hermes, opencode templates; no `(#0)` left in `changelog.d/`; `.claude/settings.json` present with
  `acceptEdits`; `bin/review-pr --model` exists; `tests/test_agent_guard.py`, `tests/test_review_launch.py`,
  `bin/claude_identity.py` + the stub at the old path exist; 17 `tests/test_acp_run_*` still present (D1 follow-up).
- B14b. **low** — partial/unverifiable: `agents/claude/settings.json.tmpl` and `.mcp.json` carry no firecrawl entry;
  whether the Claude template had one before Wave 3b needs the pre-slim tag. CI green, the marker, "three Codex findings
  fixed in 2a4cd51", the "63 failed / all baseline" numbers and the C7/C1 re-run paste are GitHub/runtime facts, not
  checkable here. No false claim found.

### B15. F4d. docs/setup-plan.md S3b (API keys)

- B15a. **medium** — `docs/setup-plan.md:216-218` (S3b.3 probes under `sudo-secretspec run`) and `:242-246` (S3b.5
  delivery "from inside `sudo-secretspec run`"): AGENTS.md review rule 3 (:284-288) requires `get` for a tool that
  needs only some keys; a per-provider `curl` probe with every other provider's key, the Telegram token and GitHub
  tokens in its environment is the forbidden case (one wrong URL or redirect leaks the store). Fix: each probe and
  delivery uses `sudo-secretspec get NAME`, child env limited to that one key (as `bin/pr-policy` does). Test: a fake
  secretspec in tests/ asserting the probe child's env holds exactly one `*_KEY`/`*_TOKEN`. Queued: no.
- B15b. **medium** — `:242-246` "value passed on stdin or in the environment, never in argv": env is readable by any
  same-user process (`ps -E`) and may be logged by the CLI's debug output; and "if Paseo has no store the daemon runs
  under `sudo-secretspec run`" hands every key to the daemon and, unless scrubbed, to every agent it spawns. Fix: stdin
  only; no-store case launches Paseo with `get` of the registry's `paseo` keys only; a `doctor` probe
  `paseo run … env | grep -c _KEY` = 0.
- B15c. **low** — S3b.1 registry omissions: `FIRECRAWL_SELFHOST_API_KEY`, `FIRECRAWL_ROUTER_SIPB_KEY`,
  `FIRECRAWL_ROUTER_LITELLM_KEY`, `MIT_SIPB_API_KEY` (bin/firecrawl-router), `FASTINO_API_KEY` (skills-lock.json),
  `MCP_BEZALEL_API_KEY`/`TODO_BEZALEL_API_KEY`, `TODO_HERMES_DASHBOARD_PASSWORD_HASH` (agents/hermes/config.yaml.tmpl),
  `HERMES_CLINE_API_KEY`, `DJBCLARK_FORGEJO_MIT_EDU_TOKEN` (config/pr-policy.toml); `ORCA_AGENT_HOOK_TOKEN`/`ORCA_PANE_KEY`
  should be listed as retired. S3a.3 should say the agent never runs `sudo-secretspec set` through its own Bash tool
  (the value would land in the tool transcript). Otherwise no key in argv, log, tracked file, clipboard or chat.

## C. F1b table

| finding (file:json-line) | worktree line | verdict | fix or reason |
|---|---|---|---|
| rearch:255 | 248 | real (low) | fix as proposed; vendor/README.md and AGENTS.md:34 say site-djbclark `bin/fleet-watch`; the row still says `~/ops/site-private/bin`. |
| rearch:258 | 251 | real (low) | `pr-wait`/`local-review` deleted (E8, log.md:105); README.md:64-65 says so; row contradicts README. |
| rearch:260 | 253 | real (low) | add "done 2026-11-06 (E2)" like rows 246/497-499. |
| rearch:267 | 260 | real (low) | add "done by E11 2026-11-07 for djbclark-ade/AGENTS.md; `~/AGENTS.md` pass open". |
| rearch:296 | 289 | real (low) | banner line 499 records the C7 drain; add the dated line here. |
| rearch:369 | 362 | real (low) | drop cline and grok (ledger-rulings pool audit; grok CLI ruling 2026-11-07). |
| rearch:399 | 392 | real (low) | zcode/crush dropped 2026-11-06 (status table line 33 says acp-run goes in Wave 6). |
| rearch:411 | 404 | real (low) | "today" → "on 2026-10-30"; none of the four files/lines exist. |
| rearch:424 | 417 | real (medium) | `.github/workflows/test.yml:121-122` runs `bin/ade-roster --check`; "runs only pytest" is false; date it. |
| rearch:446 | 439 | real (low) | queue.md no longer carries PR 118; mark closed 2026-10-31 (gh state not re-verified). |
| rearch:451 | 444 | real (low) | queue.md rewritten by E11 (138 lines); say so. |
| rearch:456 | 449 | real (low) | fleet.py / test_relay_fallback.py gone (E3/E3b); mark closed. |
| rearch:509 | 502 | real (medium) | contradicts the omp KEEP ruling (Codex/Claude API credits, not the subscription window) and `[lead].fable_lead`; restate. |
| rearch:575 | 568 | real (medium) | `config/gates.toml` exists (docs/gates.md:1-3, trimmed 2026-11-07); "deleted 2026-11-07" is false; `bin/gate-profile` went. |
| rearch:626 | 620 | real (low) | drop cline and grok. |
| rearch:641 | 635 | real (low) | quota guard deleted (E7), `/bigteam` is `skills/fan-out`; restate against Wave 6. |
| threat:182 | 168 | real (low) | banner :12-13 lists skillopt-night as deleted; date the sentence. |
| threat:187 | 173 | real (low) | zcode-key-auth deleted (banner :12); date it. |
| threat:201 | 181 | real (low) | mark Gap 2 closed by retirement. |
| threat:208 | 188 | **refuted** | the fix says the router "was deleted 2026-11-06 (3b)"; it was restored by operator ruling 2026-11-07 (log.md:79; file exists; threat-model.md:33,122 "kept"). The env-var gap is live; leave the text. |
| threat:243 | 224 | real (medium) | AGENTS.md:158: branch protection enforced for admins since 2026-10-31; Gap 1 "no branch protection" is stale. |
| threat:263 | 243 | real (medium) | contradicts ledger-rulings.md:64 (owner-attributed artifacts are ours); rewrite as proposed. |
| threat:273 | — | **refuted / already fixed** | "Codex is reviewer-only (`docs/queue.md`)" no longer appears; threat-model.md:86 cites AGENTS.md rule 9. |
| threat:279 | 259 | real (low) | replace zcode-key-auth with `bin/deadline`/`bin/pr-policy`. |
| threat:311 | 297 | real (low) | runner scripts gone (threat-model.md:638 entry 2 says removed); rewrite Control. |
| threat:322 | 307 | real (medium) | persistence claim false since E6 (shim submits no launchd job); rewrite as outcome-misreport. |
| threat:331 | 317 | real (low) | `wait_for_capacity`/`machine_overloaded` gone (entry 4, line 644); internal contradiction. |
| threat:335 | 320 | real (low) | reduce to the fail-open `admit` gap. |
| threat:353 | 338 | real (low) | path is site-public (vendor/README.md:870-871); drop the dead-link remark. |
| tui:162 | 155 | real (low) | model-routing.md is 93 lines; cite `pre-slim-2026-11-06`. |
| tui:163 | 157 | real (low) | skillopt_sources.py gone (E10); reword. |
| tui:183 | 176 | real (low) | tui:729 cites the pre-slim tag; make this pointer match. |
| tui:184 | 177 | real (low) | align D2c with row H6 (no Copilot plan). |
| tui:197 | 191 | real (low) | line 715 uses `git show pre-slim…:docs/queue.md (~1200–1216)`; line 191 still bare. |
| tui:199 | 192 | real (low) | drop `docs/model-routing.md ~222`. |
| tui:237 | 230 | real (low) | pre-slim tag. |
| tui:259 | 252 | real (low) | line 692 (A8 muse) says retired 2026-11-06 (H8); 252 still "pending". |
| tui:264 | 258 | real (low) | done by E9. |
| tui:281 | 274 | real (low) | pre-slim tag. |
| tui:303 | 297 | real (medium) | contradicts ledger-rulings.md:60 (pi retired, not ported); close "port fail-closed". |
| tui:309 | 303 | real (low) | reword as done. |
| tui:335 | 329 | real (low) | `fleet.EXACT_EXECUTABLES` gone; `bin/agent_guard.py` survives. |
| tui:358 | 351 | real (low) | web-digest*/skill-get absent from bin/; say gone (R2-15). |
| tui:360 | 354 | real (low) | agy → "antigravity (Paseo provider)". |
| tui:367 | 360 | real (medium) | same contradiction as tui:303. |
| tui:378 | 371 | real (low) | qualify per internal-trust ruling (threat-model.md:679 does). |
| tui:388 | 381 | real, fix **wrong** | the six tools are gone, but "relay.py, itself gone 2026-11-20" is false: `skills/session-finder/relay.py` exists; AGENTS.md:126,154 say the shim lasts until 2026-11-20. Write "scheduled for removal 2026-11-20". |
| tui:391 | 385 | real (low) | as proposed. |
| tui:398 | 391 | real (medium) | superseded by ledger-rulings.md:60; close G1. |
| tui:400 | 393 | real (low) | drop the hygiene list; `identity_refusal` is `bin/acp-dispatch:658`, not acp-run ~1867 as the fix says; cite agent-guard-contract. |
| tui:404 | 397 | real (low) | `bin/route_agent.py:2150` still names provider `cline` for clinepass; the fix's open item is confirmed. |
| tui:409 | 403 | real (low) | retarget or drop. |
| tui:416 | 410 | real (low) | close items (muse H8, roster at README). |
| tui:419 | 413 | real (low) | as proposed. |
| upstream:225 | 225 | real (low) | add "(deleted 2026-11-06, E2)". |
| upstream:1252 | 1242 | real (low) | line 787 (same doc) says shim deleted; 1242 still present tense. |
| upstream:1273 | 1263 | real (low) | point at docs/workspace-layout.md; past tense. |

## D. Strike lines for docs/slim/fable-review-later.md

- D1. `~~F1a. W3 docs critic, completeness pass ...~~ reviewed 2026-11-07 by Fable 5.1 (omp), see fable-review-2026-11-07.md`
- D2. `~~F1b. W3 findings never verified ...~~ reviewed 2026-11-07 by Fable 5.1 (omp), see fable-review-2026-11-07.md`
- D3. `~~F1c. The 87 confirmed W3 fixes ...~~ reviewed 2026-11-07 by Fable 5.1 (omp), see fable-review-2026-11-07.md`
- D4. `~~F2a. bin/review-launch, bin/review-pr, .github/workflows/adversary-marker.yml, bin/adversary_marker.py ...~~ reviewed 2026-11-07 by Fable 5.1 (omp), see fable-review-2026-11-07.md`
- D5. `~~F2a1. The self-check model fix ...~~ reviewed 2026-11-07 by Fable 5.1 (omp), see fable-review-2026-11-07.md`
- D6. `~~F2b. bin/acp-dispatch shim's frontier guards ...~~ reviewed 2026-11-07 by Fable 5.1 (omp), see fable-review-2026-11-07.md`
- D7. `~~F2b1. The three Codex fixes on PR 297 ...~~ reviewed 2026-11-07 by Fable 5.1 (omp), see fable-review-2026-11-07.md`
- D8. `~~F2c. bin/route_agent.py frontier gate on merged quota ...~~ reviewed 2026-11-07 by Fable 5.1 (omp), see fable-review-2026-11-07.md`
- D9. `~~F2d. Gemini 4 Argon's injection report cross-check ...~~ reviewed 2026-11-07 by Fable 5.1 (omp), see fable-review-2026-11-07.md` (F-CRIT-1 not checkable from the repo)
- D10. `~~F3b. Wave 6: the final PR body ... and docs/slim/operator-batch.md ...~~ reviewed 2026-11-07 by Fable 5.1 (omp), see fable-review-2026-11-07.md`
- D11. `~~F3d. .claude/settings.json ...~~ reviewed 2026-11-07 by Fable 5.1 (omp), see fable-review-2026-11-07.md`
- D12. `~~F4a. docs/setup-plan.md ...~~ reviewed 2026-11-07 by Fable 5.1 (omp), see fable-review-2026-11-07.md`
- D13. `~~F4b. vendor/README.md's additions ...~~ reviewed 2026-11-07 by Fable 5.1 (omp), see fable-review-2026-11-07.md`
- D14. `~~F4c. The PR 297 body's claims ...~~ reviewed 2026-11-07 by Fable 5.1 (omp), see fable-review-2026-11-07.md`
- D15. `~~F4d. docs/setup-plan.md S3b ...~~ reviewed 2026-11-07 by Fable 5.1 (omp), see fable-review-2026-11-07.md`

F3c (a `bin/review-pr` run on Fable) was excluded by the brief and is not struck.

## E. What could not be checked, credits, subagents

- E1. F-CRIT-1 of the Argon report: `site-public-djbclark/bin/fleet-watch` and `home-agents.md` are outside the
  worktree (repo-only rule). Argon lines 234-599 (F-MED-*) out of scope.
- E2. GitHub state: the ruleset's App-id pinning, PR 118's state, CI/marker/Codex claims in the PR 297 body, whether
  App-authored PRs pass collaborators-only limits, whether Claude Code's `blockReadsOutsideWorkingDirectories`
  resolves symlinks (all marked [INFERENCE] where used).
- E3. Live CLIs not run (brief R3 and AGENTS.md item 6): `sudo-secretspec check|set`, `herdr plugin unlink`, `paseo
  schedule create --timezone/--mode`, `npx skills add`; Paseo's real window label strings and `problem.kind`
  vocabulary (fixtures used). `bin/review-launch`'s `--json` envelope exit discipline (B6d) not read in budget.
- E4. F1a: AGENTS.md orders 1–8 and 11+ not cross-checked line by line against checkin-rulings.md. F1c: diff lines
  177-278 read as added text only. No test suite was run (review-only; `bin/ade-roster --check` is the one command run
  in the worktree).
- E5. Credits: `aiuse --available --json` before (07:21 EST): omp row `usable_now: true`, pool `anthropic_api`
  ("api key": no window percentages reported); claude row 29 % remaining weekly (not used by this review). After:
  see the delivery report (same omp row shape; the API-key pool reports no percentage).
- E6. Subagents: four omp `task` workers (G1SecurityBoundary, G2DispatchRouting, G3DocsCorrectness, G4PlansOperator),
  one per group, on the session's configured Fable model (per-call model selection is disabled in this omp; effort
  not settable per call, no xhigh/max requested); runtimes 3–6 minutes, about $1.7–3.1 each by omp's meter.
