# Wave 4 E7 (S-route) report: route_agent on Paseo's registry and usage, the quota gates deleted, model-routing rewritten

Writer: Claude (Opus 5.5) in worktree `.claude/worktrees/agent-a3493397bd11d5024`, branch `worktree-agent-a3493397bd11d5024`, based on
`claude/determined-maxwell-uvddaz` at bb76f46 (merged first; bb76f46 is an ancestor). Commits: f6271c1c (code), 265b5738 (skills,
docs, the Argon row), then this report. Brief: `docs/slim/briefs/wave4-E7-route.md`; rulings applied: "grok CLI retired, grok-bot
kept" (the grok rows of my four files), "Internal trust".

## A. Registry and quota sources

A1. **Registry** (`bin/route_agent.py` `paseo_provider_rows`, `paseo_providers`, `provider_models`). `paseo provider ls
--json` through `_paseo_json` (argv list, `ROUTE_AGENT_PASEO_TIMEOUT` default 15 s, in (0, 60]; never raises: a missing binary, a
timeout, a non-zero exit or malformed JSON give no rows). The roster is the rows with `enabled == "Enabled"` and `status ==
"available"`. **Retry:** while any row reads `loading` the call is repeated, at most twice, 3 s apart (6 s in all); a row still
`loading` after that is dropped with one stderr line (`paseo provider ls: still loading after 6s, treated as absent: …`).
`provider_models(p)` reads `paseo provider models <p> --json` once per process (module cache) and returns the `id`s, or None
when Paseo cannot say. `discover()` takes `paseo_providers()` where it took `installed_roster()`: curated rows are always present
(unchanged), and a provider nobody profiled joins with `default_profile` unless `never_route`/`[dispatch].operator_gated` names it.
Gone: `acp_list_output`, `acp_agents`, `headless_agents`, `orca_roster`, `include_orca`, `installed_roster`, `ORCA_DATA`,
`NON_ACP_HEADLESS`, `ACP_RUN`, `ROUTE_AGENT_INCLUDE_ORCA`. `ROUTE_AGENT_PASEO=off` drops both Paseo reads (the suite sets it in
`tests/conftest.py`); `ROUTE_AGENT_PASEO_BIN` names the binary.
A2. **`--model` validation:** `route_agent.py services --check-models` checks every curated `models` suggestion against its
provider's `paseo provider models` list (exit 1 when one is missing, 2 when a provider's list is unreadable; API pools and
Cursor Cloud are skipped). `services` also prints each service's provider status from `provider ls`. Not run against the Mac's
daemon (no Paseo here): Cursor's `default` (Auto) is a likely false MISSING if Paseo names Auto differently.
A3. **Second quota source** (`paseo_usage`, `usage_from_paseo`, `_fold_paseo`; line numbers as of 265b5738). `paseo usage ls --json` (15 s, memoised
30 s like the aiuse spawn; `ROUTE_AGENT_PASEO_USAGE_JSON=<path>` feeds canned rows for tests and wins over `ROUTE_AGENT_PASEO=off`).
Rows are keyed by `sourceId` (`opencode` maps to the `opencode-go` pool, other names through ALIASES). `report.status ==
"available"`: each window gives percent left from `remainingPct`, else 100 − `usedPct`, its `resetsAt` riding with the tightest;
each balance with a positive `limit` becomes a `"<unit> balance"` window at `remaining/limit`; a window whose label names
`fable` is the Claude Fable sublimit, not a pool window; a report older than `STALE_SOFT` (25 min, by `fetchedAt`) keeps only an
exhausted window. **The unknown rule:** any other status (`unavailable` with `problem`, `error`, missing) is an entry with
`remaining: None` and `unknown: "paseo usage <source>: report <status> (<problem.kind>)"`, never a pass. `icon` and `loginErrors`
are dropped (never copied into an entry).
A4. **Merge** (`load_snapshot`, :1265): aiuse is read first exactly as before; a dead collector (age > STALE_HARD) now empties only
aiuse's pools instead of returning early, then Paseo folds in: a pool aiuse does not know takes Paseo's entry; a known reading
goes through `_merge_pool` (the tightest known remaining wins and carries its bind fields; sublimits merge by the tighter); an
unknown Paseo report never loosens or replaces a reading (it is kept as `paseo_unknown` beside it), and stands alone as unknown
for a pool nobody else reports. When aiuse gives nothing, the snapshot age is Paseo's oldest available reading. Every pool entry
now carries `age_s` (its own reading's age). **`QuotaSource`** gained `paseo` (what was read, or why not) and `pools` (service ->
`aiuse` | `canned` | `snapshot` | `paseo` | `<aiuse source>+paseo`); `quota_source_info()` returns both, so `plan --json`, `route
--json` and `show` (a `from …` column, plus any unknown note) report the source per pool.

## B. The frontier gate port

B1. **Where it lives:** `bin/ade_gates.py` is **trimmed to the frontier half** (735 → 227 lines), not ported into route_agent: the
acp-dispatch shim and the Agent-tool hook already import it, so its import surface stays put (section 1f). It keeps
`FRONTIER_DEFAULTS` (plus the new key below), `load_frontier`, `frontier_reason`, `judged_guard_block`, `judged_pool_block`,
`read_guard_state`, `iso`, `parse_utc`, `ny_date` (the hook's daily cap), `is_num`, `read_toml`, `baseline_limit`. `load_frontier`
keeps the baseline guard (a "higher" key up to its `[floors.frontier]` bound, a `*_min_left` key never below the code default);
profiles, env overrides, notices and locks are gone; `info["profile"]` is always None (the shim and hook read it).
B2. **`read_guard_state()`** returns `route_agent.claude_quota_state()` (route_agent imported lazily; any failure returns None,
which blocks): the merged snapshot's `claude` entry as `checked_at` (now minus that reading's `age_s`), `remaining` (tightest
window), `fable_left`, `windows`, `source`, `unknown`, `paseo_unknown`. `claude_quota_state` saves and restores `QuotaSource`, so a
caller's own `quota_source_info()` is not overwritten. `frontier_per_wave` calls `claude_quota_state()` directly for the claude
family. **`judged_guard_block`**, rewritten for that state, blocks in order on: not a dict; `unknown`; no usable `checked_at`; older
than 30 min (`GUARD_STATE_MAX_AGE_S`) or over a minute in the future; no window percentage; tightest window under
**`frontier1_window_min_left` (new key, 30: the quota guard's old tight level, code default and `gates.toml` value)**; no Fable
reading; Fable under `frontier1_min_left`. Both sources drop a non-exhausted window older than 25 min, so in practice a reading
blocks from 25 min ("no window percentage"), the 30-min check being the outer bound.
B2a. **Repair round (adversary notes):** a Paseo report whose `windows` or `balances` is not a list is now that pool's "not read"
(unknown) instead of a TypeError into `load_snapshot`, and `load_snapshot` also catches any parse error from `usage_from_paseo`
(Paseo "not read: … unparseable"), so nothing in the usage path raises (test with `windows: 5`). `paseo provider ls` is read once
per process (`_PROVIDER_ROWS`, cleared by `_reset_paseo_cache`), so a slice spawns it once. **The Fable floor stays at the old
guard's 15:** `frontier1_min_left` is 15 in the code default and `gates.toml` (it was 10, the old `fable_min_left`; the guard
stopped judged Fable use below 15). **What the port drops, recorded in `docs/gates.md` B2a:** the guard's `conserve` alerts (a
pace projection could raise it to tight) are gone, and the one tightest-window floor of 30 means the 5-hour floor rose from the
guard's 10 to 30 (weekly stays 30). **Confirmed:** an unknown Paseo report beside a fresh aiuse reading grants: aiuse is the
primary reading, and the fail-closed rule applies when no source reports Claude (test
`…a_fresh_aiuse_claude_reading_grants_and_an_unknown_paseo_report_does_not_take_it_away`).
B3. **The three test cases** (`tests/test_route_agent.py`
`TestFrontierConservative2026_10_18.test_frontier_per_wave_on_claude_with_a_fresh_a_stale_and_an_unknown_reading`): a canned
`paseo usage ls` Claude report fetched 30 s ago (weekly 70%, Fable 60%) gives `frontier_per_wave("claude") == 2`; the same fetched
40 min ago gives 1 ("min old"); a report with `status: unavailable` (rejected 403) and no aiuse reading gives 1 ("report
unavailable"). Also: `…needs_a_fresh_known_claude_reading_above_its_floors` runs `plan` over fresh/tight (weekly 20%)/stale/unknown/
no report (2/1/1/1/1, codex always 1), and `…a_fresh_aiuse_claude_reading_grants_and_an_unknown_paseo_report_does_not_take_it_away`
shows aiuse as the primary (fresh aiuse row plus Fable row with an unavailable Paseo report: 2; a 40-min-old aiuse row: 1).
`tests/test_gates.py` (rewritten, 49 tests) covers the loader, `judged_guard_block`'s order and boundaries, `judged_pool_block`
and `read_guard_state` in a child process against canned Paseo usage (available, unavailable, nothing readable).
B4. `governor_hold()` and `GOVERNOR_*` are gone with the governor, and so are the `held` parameter of `pool_usable`/
`fallback_block` (no caller outside route_agent passes it; the shim imports neither), the omp-judgment override in `route()`,
the hold note in `plan`/`unrouted_why`, and the `governor_hold` key of `plan --json`/`route --json`.
B5. `claude/hooks/frontier_agent_gate.py` follows: step 2 is `judged_guard_block(read_guard_state())`, with
`ROUTE_AGENT_AIUSE_TIMEOUT`/`ROUTE_AGENT_PASEO_TIMEOUT` defaulted to 5 s inside the hook (its settings timeout is 15 s); the
profile fields left its log rows. `tests/test_frontier_agent_gate.py` feeds canned Paseo usage instead of a guard file (missing,
unknown, stale 26/31 min, future, window floor 29.9/30, Fable floor) and drops the profile and guard-FIFO cases.
B6. **Import surface (1f), checked by introspection after the change:** every name in `docs/slim/reports/wave4-E6.md` section I
imports with an unchanged signature (`POLICY["dispatch"]` keys, `KINDS`, `BY_NAME`, `ALIASES`, `DEFAULT_PROFILE`,
`map_agent_to_provider`, `pool_service`, `load_snapshot(bypass_memo)`, `history_rows`, `estimate_from_history`,
`estimate_windows_from_rows`, `window_fit`, `floor_lookup`, `kind_floor_applies`, `repo_of`, `repo_floors`; `ade_gates.frontier_reason`,
`load_frontier(now)`, `judged_pool_block(family, t, now, guard_state, remaining)`, `read_guard_state()`, `iso`). `bin/acp-dispatch`
is not edited; `tests/test_acp_dispatch.py`'s frontier fixture now writes canned Paseo usage (its `gates_env`).

## C. Deleted

C1. `bin/claude-fleet-governor` (859 lines) and `tests/test_claude_fleet_governor.py` (1359); its plist was never tracked (written by
`--install`), so there is no plist to delete in the repo.
C2. `bin/claude-quota-guard` (922, both halves) and `tests/test_claude_quota_guard.py` (2082; it also held `quota_nudge.py`'s tests,
see H4); plist likewise generated by `--install`, not tracked.
C3. `bin/gate-profile` (502); its tests were the CLI half of `tests/test_gates.py` (1435 lines, rewritten to the frontier half, 257).
C4. The Claude-quota half of `bin/ade_gates.py`, of `config/gates.toml` (`[meta]`, `[governor]`, `[quota_guard]`,
`[floors.governor]`, `[floors.quota_guard]`, the `*_min_left` floor rows, `[profiles.away*]`; 155 → 36 lines) and of
`docs/gates.md` (259 → 83 lines, kept: the frontier half is KEEP, ruling 7).
C5. `bin/claude-cost-whatif` (100; it had no tests). `bin/claude-cost-mix`, `bin/go_model_policy.py`, `config/go-model-policy.json`
stay.
C6. `skills/effort-routing/`, `skills/fallback-chains/` (folded, E1). The chain checker and its dated references moved, by `git mv`,
to `skills/model-routing/scripts/chains-check.py` and `references/fallback-chains-{inventory,integration}.md`. In the repair
round the checker reports a missing or unparsable chain source (`~/.hermes/config.yaml` and the rest) as one stderr line and exit
1, no traceback (run here: "cannot read /root/.hermes/config.yaml: No such file or directory", exit 1).
C7. In `bin/route_agent.py`: the acp-run/headless/Orca discovery (A1), `governor_hold` (B4), the `grok` map row. In
`config/routing.toml`: the `grok` `[[service]]`, the `[discovery]` table (its `never_route` and `aliases` moved into `[routing]`,
`operator_gated` folded into `[dispatch].operator_gated`, which discovery now honours), `[escalation]`/`[escalation.next]` and
`[dispatch].auto_resume_max_wait_hours` (no reader since E6 retired `reroute` and auto-resume: `git grep` finds none).
C8. Not deleted, on purpose: `[substrate]` and `[hermes]` stay, because the kept `substrate` and `hermes-chain` commands read them
(`SUBSTRATE_LIFELINE`, `HERMES_MODELS`, `HERMES_PROVIDER_NAME`); brief 1a said `[substrate]` goes, section 2 said "if nothing reads
them": something does. `[lead]`, `[routing]`, `[calibrate]`, `[dispatch]` are read. The retired `opencode-zen` row stays (it is
what makes an `opencode-zen/…` model ineligible; dropping it would fold such a dispatch onto opencode-go through the alias).
C9. **PR 270 (`quota-surplus`): DISCARD, do not land.** session-guard covers the other end (pause at exhaustion, resume after the
reset), not "spend before reset", so the brief's stated reason does not hold; but the PR cannot land as written anyway: it is
built on `relay.py --fyi` lead pings (E3's shim), launchd, aiuse-only readings and `policy_public()["discovery"]` (that key is now
under `routing`), and route_agent's burn-first bonus already prefers a pool that would waste quota at its reset whenever a lead
plans. If the operator still wants the alert, it is a short Paseo schedule over `route_agent.py show`'s waste column, a new PR.

## D. C3 hits for J2b (tendcf, nix2cf, site-djbclark)

D1. The brief's command, `grep -rn "gate-profile\|ade_gates\|claude-quota-guard\|claude-fleet-governor"` over `/home/user/tendcf`
(branch `slim-c3-2026-11`), `/home/user/nix2cf` (`slim-c3-2026-11`) and `/home/user/site-djbclark` (`slim-intake/2026-11`):
**no hits** (read-only clones, 2026-11-07). Nothing to edit there for the quota gates.
D2. Related, for the lead: `tendcf/AGENTS.md:57` and `nix2cf/AGENTS.md:64` (review route 3) run `acp-dispatch antigravity --model
gemini-4-argon --kind frontier` after the slim-down. On the branch before this slice that line exited 2 ("antigravity is not
eligible for --kind frontier"; probed with the shim and the fake paseo): E9 had removed every antigravity row. This slice
restores the `antigravity-argon` row (E5). Their `AGENTS.md:43` and `:50` still say `route_agent.py plan … through /bigteam`
(bigteam was replaced by `fan-out` in E6): J2b's edit. `site-djbclark/bin/mine_sessions.py:30` and `home-agents.md:54` name
route_agent in prose only.

## E. model-routing and routing.toml after

E1. `skills/model-routing/SKILL.md` (829 → 139 lines): A. Claude tiers by role (PLAN G: Fable 5.2 leads/architects/adversaries,
Opus 5.5 rewrites/reviewers, Sonnet 5.5 audits/deletions/inventories, Haiku 5.5 mechanical) with A6 flagging the conflict below;
B. effort (levels, precedence, defaults, set sub-agent effort explicitly, the classification table, caching, the context window;
from effort-routing); C. one row per surviving pool (its role and its "never"; ranks, kinds' models and numbers are left to
`policy --md`); D. routing (plan/route/show/services, climb on a verified failure, the frontier allowance, quota limits are the
plugins', in-flight reservation); E. reading quota (aiuse then `paseo usage ls`, the four misreading rules); F. fallback chains
(the model-chain half: no automatic chain for a dispatched slice; Hermes/LiteLLM sources; the checker and references);
G. multiple-choice decisions. `route_agent.py policy --md` gained a "Pools" table (service, Paseo provider, billing, note) and the
`frontier1_window_min_left`/`frontier2_min_left` rows, so the skill copies nothing it prints.
E2. **Fable leads (operator ruling 2026-11-07, repair round):** "allowed for now, with an easy way to turn them off later". One
switch, `fable_lead = true` in `[lead]` of `config/routing.toml`, read with `.get` (absent means false, so an older file keeps the
2026-10-23 never-a-Fable-lead rule; a non-boolean is refused naming the file). `route_agent.py` exposes it as
`LEAD_FABLE_ALLOWED` and `policy --md` prints `lead.fable_lead` with a sentence that follows it; `claude/hooks/context_size_nudge.py`
(the only code that enforced never-Fable) reads the same key (tomllib, or a line scan of `[lead]` under a Python without it; false
when the file is unreadable) and gives a Fable session no relaunch-on-Opus note while it is true. The skill (A6) and
`docs/model-routing.md` (G2) name the one line to flip. Tests each way: `test_the_shipped_policy_allows_a_fable_lead_and_policy_md_says_so`,
`test_a_lead_table_without_fable_lead_keeps_the_never_fable_rule` (absent, false, non-boolean), and in the nudge suite
`test_fable_lead_true_means_no_relaunch_note`, `test_fable_lead_absent_false_or_unreadable_keeps_the_relaunch_note`,
`test_fable_lead_line_scan_without_tomllib`.
E3. `docs/model-routing.md` (505 → 90 lines), dated 2026-11-07: where the numbers live, the pool table, the registry, the two quota
sources and the merge, the frontier gate's Claude reading, the OpenCode Go cost policy, and three kept reasons.
E4. `config/routing.toml` services after: `claude`, `omp`, `codex`, `opencode-zen-free`, `opencode-go`, `cursor-auto`, `cursor`,
`cursor-cloud`, **`antigravity-argon` (restored)**, `clinepass`, `opencode-zen` (retired). Tables: `[routing]` (now with
`never_route`, `aliases`), `[calibrate]`, `[dispatch]` (+ `estimate_floor`, `repo_overrides`), `[lead]`, `[substrate]`, `[hermes]`.
`never_route` gained `grok` and `grok-bot` (aiuse still reports both accounts; `grok-bot` was not listed before, so it could have
been discovered as an unprofiled bulk pool). `kinds` keeps `github` and `realtime-web` (no pool now; a plan leaves them queued).
E5. **Decided differently from the brief: the Argon row is back.** J2 keeps the antigravity plan, the C3 PRs and the E6 requirement
expect `acp-dispatch antigravity … --kind frontier` to work, and it was refused. Restored exactly as PR 224 ruled it (operator
2026-10-31: frontier FALLBACK only behind codex and claude, `fallback_after`, its own `gemini_argon` window, rank 5, max 1), now
`agent = "antigravity"`; `gemini-4-argon` is again in `[dispatch].frontier_models`; `map_agent_to_provider("antigravity",
"gemini-4-argon*")` → `("antigravity", "gemini_argon")`, any other antigravity model → None (its other pools stay unrouted, and
`antigravity` stays `never_route`). Gap, reported not fixed: the E6 shim does not apply `fallback_block`, so the fallback-only
rule holds in `plan`/`route` but not at dispatch; tendcf's AGENTS.md already tells the lead "Argon is fallback-only". Tests:
`TestArgonFrontierFallback`. Revert = drop that row and the map branch if the lead prefers E9's decision.
E6. The cursor-cloud row's dispatch line is now `cursor-cloud launch --repo <url> --ref <branch> --prompt-file <brief> --model M`
(E6 retired `acp-dispatch cursor-cloud`); the placeholder line without a model names `paseo provider models <agent>`.

## F. Reference edits (outside my four files)

F1. Code and tests: `claude/hooks/frontier_agent_gate.py` (B5); `claude/hooks/context_size_nudge.py` (`QUOTA_GUARD_PATH`,
`_guard_level`, `SUCCESSOR_SONNET` and the tight/critical branches gone; `_successor_target(model)`: a Fable session still gets
the relaunch-on-Opus note) and `claude/hooks/handoff-tools/tests/test_context_size_nudge.py`; `claude/agents/adversary.md:8-14`
(the sonnet-override comment reads `route_agent.py show`); `bin/ade_sched.py:4` (docstring); `tests/conftest.py`
(`ROUTE_AGENT_PASEO=off`; the governor and gate-profile pins gone; `CLAUDE_QUOTA_GUARD_STATE` kept for `quota_nudge.py`);
`tests/fakes/paseo` (extended: `provider models`, `usage ls`, `FAKE_PASEO_LOADING`, `FAKE_PASEO_USAGE_RC`).
F2. Docs: `docs/deadline.md:26-28` (the `reroute:RECORD` mode: the shim retires `reroute`, so it now kills and pings "reroute
FAILED"), `docs/scheduling.md:6,150`, `docs/upstream-issues.md:1184`, `docs/threat-model.md:52,265,269`,
`docs/paseo-only-rearchitecture.md:233,242,555,557`, `docs/orchestration-practices.md:4`, `docs/disabled-skills.md:97,172`,
`docs/claude-cache-cost-research-report.md:111`, `docs/software-factory-research-digest-2026-10-19.md:55`,
`docs/model-tiers-design.md` (a status note, like E10's for failover.py: its rows naming the deleted tools are a design record, 21
names left in place).
F3. Zero-reference check (`git grep` for `acp-run --list`, `claude-fleet-governor`, `claude-quota-guard`, `gate-profile`,
`claude-cost-whatif`, `effort-routing`, `fallback-chains`, `routing-recalibrate`, `quota-guard.json`, the usual exemptions) leaves,
on purpose: `claude/hooks/quota_nudge.py` (6, DECIDE, H4); `docs/model-tiers-design.md` (21, F2); `tools/acp-run/acp-run:17` and
`tools/acp-run/README.md:17,553` (acp-run's own `--list` flag, documented while the SHIM lives, rule 8); `tests/fixtures/context-now.txt:322-323`
(captured `/context` output, test data); the reference names in `skills/model-routing/references/fallback-chains-*.md` (moved
files keep their names); and the lines in G (merger's, E11's, E9c's).
F4. **Not edited because E9c edits the same file in this wave (ruling 11):** `skills/handoff/SKILL.md:315` ("a quota-guard
downgrade"), `:330-331` (the "`claude-fleet-governor` steer names its own successor" paragraph: delete), `:333-354` (the "Quota
guard `critical`" paragraph reading `~/.local/state/ade/quota-guard.json`: no file is written any more, so it never fires; replace
with one line: when `route_agent.py show` reads claude exhausted, hand off to an omp successor), `:360` ("(b) the state file's
`level` is `tight`": delete); `skills/research/SKILL.md:143` ("`model-routing` / `effort-routing` skills": `model-routing` only).
F5. `bin/deadline` (E5's file, done here at the lead's request in the repair round): `--on-expire reroute:RECORD` is refused by the
parser with exit 2 pointing at `relay` (`check_action`); the `acp-dispatch reroute` call, its "outcome UNKNOWN" branch and the
unused `sh_nokill` helper are gone; a record registered with `reroute:` before the change is stopped, nothing is dispatched, and
the owner and the operator get the "reroute FAILED ... nothing replaced it" notice. Usage text (:5, :18, the parser, the
no-pid refusal) and `docs/deadline.md` (:26-29, :31, :206, items 22-23) follow. `tests/test_deadline.py` 84 passed (the reroute
tests rewritten: refused at `start`, refused by the parser, an older record); `tests/test_deadline_wrappers.py` has only its 2
baseline failures.

## G. Merger's lines

G1. `README.md:78` (`bin/` row): the `claude-fleet-governor` sentence ("keeps every Claude session … `bin/route_agent.py` reads its
`level`") goes; `route_agent.py` reads "pick a vendor … from `paseo provider ls` and the merged aiuse + `paseo usage ls` quota".
`README.md:83` (the `bin/claude-quota-guard` + `quota_nudge.py` row): delete the guard; keep or drop `quota_nudge.py` with H4.
`README.md:106-107` (`fallback-chains`, `effort-routing` rows): delete; the `model-routing` row may say "effort and fallback chains
folded in". `README.md:245-248` (item 16, `docs/gates.md`): "the frontier allowance (`config/gates.toml [frontier]`)", no profiles.
G2. `docs/skills.md:63-64` (`fallback-chains`, `effort-routing`): delete.
G3. `agents/claude/settings.json.tmpl:100` (`"effort-routing": "user-invocable-only"`): delete. Its hook lines `:415`
(SessionStart, `cswap_quota_context.sh`) and `:534` (UserPromptSubmit, `quota_nudge.py`) wait for H4.
G4. `.github/workflows/test.yml`: nothing (it runs `tests/` whole; no deleted file is named).
G5. For E11 (AGENTS.md): `:45` doc-table row ("`config/gates.toml` and `bin/gate-profile` (2026-10-26): the Claude quota gates'
numbers … `away` profile") → "the frontier allowance (`config/gates.toml [frontier]`)"; `:86-87` order 7 ("route per
`skills/model-routing/SKILL.md` *Routing policy*": that heading is now section D, and `route_agent.py policy --md` is the one copy
of the numbers); `:142-144` ("**`acp-run --list` is the agent registry** … discovers agents from it plus installed headless TUIs")
→ "`paseo provider ls --json` is the agent registry (2026-11-07): `bin/route_agent.py` discovers providers from it
(docs/model-routing.md C)".

## H. Operator steps (Mac)

H1. `launchctl bootout gui/$UID/com.djbclark.claude-fleet-governor` and `launchctl bootout gui/$UID/com.djbclark.claude-quota-guard`,
then `rm ~/Library/LaunchAgents/com.djbclark.claude-fleet-governor.plist ~/Library/LaunchAgents/com.djbclark.claude-quota-guard.plist`.
Optional cleanup: `~/.local/state/ade/fleet-governor.json`, `quota-guard.json`, `gate-profile.json`, `gate-profile.log`.
H2. Install and verify session-guard and usage-auto-resume (PLAN D4, the J6 batch) before the final merge: a session that hits the
Claude limit pauses and continues after the reset.
H3. After `ade update`: `bin/route_agent.py services --check-models` against the live daemon (expect exit 0; a MISSING line is a
model id to correct in `config/routing.toml`). Expect false MISSING lines for Claude's curated aliases (`opus`, `fable`,
`sonnet` in the claude row) until they are mapped to Paseo's full model ids, and for Cursor's `default` (Auto) if Paseo names it
differently. Then `bin/route_agent.py show` to see each pool's source (`aiuse`, `paseo`, `aiuse+paseo`).
H4. **The quota_nudge decision (R2-18, DECIDE):** `claude/hooks/quota_nudge.py` reads the deleted guard's state file and is silent
without it, so it is inert from the moment the guard stops; its tests went with `tests/test_claude_quota_guard.py`. Live hook
lines: `~/.claude/settings.json` UserPromptSubmit `"$HOME"/ops/site-private/bin/hook-deadline 2 "$HOME"/src/djbclark-ade/claude/hooks/quota_nudge.py`
(template `:534`) and SessionStart `"$HOME"/.claude/hooks/cswap_quota_context.sh` (template `:415`, reads `cswap`, not the guard,
so it still prints the Claude windows). Recommendation: remove `quota_nudge.py` and its hook line once session-guard is verified
(H2); keep `cswap_quota_context.sh` if its SessionStart line is still wanted.

## I. Tests

I1. Before the change (a clean detached worktree at bb76f46): targeted set `tests/test_route_agent*.py tests/test_gates.py
tests/test_acp_dispatch.py tests/test_load_watch_admit.py tests/test_frontier_agent_gate.py tests/test_go_model_policy.py`:
618 passed, 2 skipped; `test_context_size_nudge.py`: 128 passed.
I2. After (HEAD 265b5738): the same set **431 passed, 2 skipped, 0 failed** (the old 1435-line `test_gates.py` and the deleted
governor/guard classes account for the drop); `test_context_size_nudge.py` 63 passed (the guard-level cases went with the guard).
I4. **Repair round (after the adversary's APPROVE at b812f13 with notes):** targeted set 435 passed, 2 skipped, 0 failed;
`test_context_size_nudge.py` 72 passed; `tests/test_deadline.py` 84 passed, `tests/test_deadline_wrappers.py` 2 failed (both
baseline rows, `[dispatch]` cases) of 23. No second full suite, per the lead.
I3. Full suite in a detached worktree of 265b5738 (`/tmp/w4e7-verify`, the `docs/slim/baseline.md` command): **63 failed, 5,601
passed, 27 skipped, 1,232 subtests passed in 574 s**. Every failure is a baseline row, by exact test id: `test_ade_git_hooks.py` 45,
`test_ade_git_guard.py` 10, `test_wait_file.py` 3, `test_acp_run_git_identity.py` 3, `test_deadline_wrappers.py` 2 (the same
per-file counts as the baseline table). **No new failure.** (E6/E8 reported 70; the seven fewer are no regression of mine to
explain: none of the 63 is in a file this slice touched.)

## J. Lost on purpose

J1. The fleet governor's pause: moving live Paseo agents Fable→Opus and Opus→Sonnet at tight/critical, the critical steer to an omp
successor, the restore after reset, and route_agent's "claude held" for code/bulk/research/mechanical.
J2. The quota guard's enforcement (`ok/watch/tight/critical` levels, `conserve` alerts, hermes pings per level) and its state file
`~/.local/state/ade/quota-guard.json`, which `quota_nudge.py`, the handoff skill's critical rule and the context nudge's downshift
read; the frontier gate reads the merged snapshot instead.
J3. Gate profiles and the `away` profile (`gate-profile set/extend/clear`, floors, daily nudges, expiry pings).
J4. `bin/claude-cost-whatif` (the TTL and compaction what-if; the 2026-10-18 numbers stay in `docs/disabled-skills.md`).
J5. acp-run discovery (`acp-run --list` `ok` rows, the headless list, Orca's roster): an agent acp-run could launch but Paseo does
not list is no longer discovered.
J6. The `[escalation]` ladder as data (the climb is a rule in the skill, D2) and the grok pool (`realtime-web` has no pool).
