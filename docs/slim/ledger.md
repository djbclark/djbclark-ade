# Slim-down ledger (Wave 1)

Round 2, 2026-11-06 21:35Z: 282 agents in all (5 readers, 92 code KEEP rows refuted with 3 votes each, 2 critic passes; 19.5M subagent tokens). 12 KEEP rows fell (section B); the Lead column carries the rulings. Posted, not awaited (PLAN.md H ruling).

Source: workflow W1 (PLAN.md H1): 5 Sonnet 5.5 readers (bin, skills, tests, docs, outside) → dedup by path → 3-lens refute of each code KEEP row (Paseo-or-plugin-replaces-it, nothing-calls-it-after-the-deletions, a-ruling-retires-it; majority of 3) → 1 Opus 5.5 completeness critic. Full rows with evidence and every vote: `docs/slim/ledger-rows.json`. Columns: `plan` is PLAN.md E; `proposed` is the reader's; `Lead` is the lead's ruling where it differs or decides (ledger-rulings.md, numbered; R2-n are the round-2 answers); blank Lead means plan and proposed agree. Dispositions: DELETE, MOVE (target column: site-djbclark, docs/history, bin/, peer-link), REPLACE, SHIM (lives until the follow-up PR after one live cycle), KEEP, DECIDE. `plan` is PLAN.md section E; `proposed` is the reader's reading of the evidence; a row whose proposed value differs from the plan is marked ≠ and listed in section C.

Counts: 627 rows; plan {'SHIM': 4, 'DELETE': 234, 'KEEP': 197, 'UNLISTED': 82, 'MOVE': 61, 'REPLACE': 19, 'DECIDE': 28, 'DELETE (retired providers only)': 2}; proposed {'SHIM': 15, 'DELETE': 248, 'KEEP': 207, 'MOVE': 60, 'REPLACE': 16, 'DECIDE': 81}; 92 KEEP rows voted, 12 refuted by majority; 50 rows disagree with the plan; 119 paths the plan never names.

## A. Lead's rulings on the critic's questions (defaults; the operator overrides by reply)

Numbered as the critic numbered them (section F4). Each is applied in the ledger and in the slice briefs unless the operator replies otherwise; "default" marks a call the lead made where the plan was silent.

1. **`bin/failover.py`**: the three refuters found its only live importer is `bin/skillopt-night` (DELETE, J4); `route_agent.py` and `ade_gates.py` mention it only in comments. Ruling: DELETE with `skillopt-night` in E10, `docs/failover.md` to `docs/history/`, and AGENTS.md's "reuse it, never hand-roll a fallback" row is rewritten in E11 to name `paseo run`'s model chain. E7's "KEEP the model-chain half" is withdrawn: no kept code consumes it. (default; one reader had it KEEP)
   **`bin/pytest`**: 47 lines, named by review rule 2 and by `tests/test_bin_pytest.py`; replaceable by `uv run … pytest` but the rule text points at it. Ruling: KEEP as is; E11 may replace rule 2's wording and delete it then. (default)
2. **MOVE targets**: yes, split. The ledger's Target column reads site-djbclark, docs/history, bin/ or peer-link; "?" rows are resolved in their slice brief.
3. **`tests/test_acp_run_*`**: SHIM, not DELETE: they go with `acp-run` in the follow-up PR (E6); until then only the retired-provider cases are trimmed in E9. The two boundary files (`test_acp_run_deny.py`, `test_acp_run_read_only.py`) are the source of `bin/review-launch`'s boundary tests (E8) and are ported, not deleted.
4. **The two tests that stay with `agent_guard.py`** (report B1d): `tests/test_acp_dispatch_identity.py` and `tests/test_omp_operator_gate.py`. `agent_guard.py` is KEEP through Wave 6; whether it outlives the shim is decided in the follow-up PR, by whether `review-launch` or a surviving Pi path uses it.
5. **`go_model_policy.py` and `config/go-model-policy.json`**: SHIM (go with `acp-run` in the follow-up PR), and only if the J2 pool audit retires opencode; PR 260 is decided first (C3).
6. **herdr server** (`bin/herdr-server-run`, `config/launchd/dev.herdr.server.plist`, their test, the installed plist): KEEP until the C7 drain output shows no herdr pane holds a Claude session and the operator says the two bridges no longer need the server; one DECIDE row for all four, resolved at Wave 2's gate.
7. **E11's docs keep-list**: amended. A doc whose tool is KEEP stays, trimmed (`deadline.md`, `gates.md` frontier half, `model-routing.md`, `pr-policy.md`, `dispatch-footer.md`, `skills.md`, `mcp-servers.md`, `skill-everywhere.md`, `upstream-issues.md`, `git-guard.md`, `scheduling.md`, `secret-deny.md`, `agent-guard-contract.md`, `context-hygiene.md` with its links rewritten). `failover.md` goes to history with its tool (ruling 1). E11's list is "the rest to history", applied after this rule.
8. **Shared files**: `agents/claude/settings.json.tmpl` (hook and skill entries) and `.github/workflows/test.yml` (test paths) are the serial merger's, like README rows: each slice's report names the lines; the lead edits them at merge. The live `~/.claude/settings.json` hook lines are the operator's (C2), and the list grows by `skills/autorename/autorename_nudge.py` and `claude/hooks/relay_prose_nudge.py` (reader finding), so four hook files, not two.
9. **`codex-env-policy-apply`**: struck from E9's retired-helper list; Codex is kept (J2). KEEP with `agents/codex/config.toml.tmpl`.
10. **`skills/create-hook`, `skills/btww`, `skills/hand`**: trim the retired-provider rows now (E9); existence waits on the J2 pool audit's omp/opencode answer, which needs `aiuse --json` from the Mac (added to the Wave 2 operator batch).
11. **KEEP code naming `cow-pasture`** (`bin/ade_claims.py:1272`, `bin/ade-git-guard:18`): E2 makes the reference-only edit when it deletes `cow-pasture`; the rule for every wave: the deleting slice removes references in KEEP files that no other slice of the same wave edits, and names them in its report.
12. **`skills/autorename/workspace-layout.md`**: E4 moves it to `docs/workspace-layout.md` (trimmed to Paseo naming) and AGENTS.md's pointer follows in E11.
13. **`bin/web-digest-mcp`**: follows `web-digest` (E9 "web-digest*"): one DECIDE on whether a small-context provider survives.
14. **`bg`**: `bin/bg` is in site-djbclark (seen in the clone, 2026-11-06); `claude/hooks/bg_test_gate.py:23` names `~/ops/site-private/bin/bg`, so the Mac may carry a private wrapper too. It gets a C3 row (calls `load-watch admit`, registers deadlines); which path is live is a one-line check in the Wave 2 operator batch (`ls -la ~/ops/site-private/bin/bg ~/ops/site-public-djbclark/bin/bg`).
15. **Root and provider files with no row** (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `opencode.json`, `skills-lock.json`, `.pi/`, `.kiro/`, `.windsurf/`, `.cursor/`, `.gemini/`, `.adal/`, `.codex/`, `.agents/`, `.claude-plugin/`, `.mcp.json`, `claude/agents/`, `.claude/`, `graft/`): E9 enumerates the provider directories in its brief (one row each, delete with the provider); E11 owns the root files; `graft/` is rebuilt last. No ledger rows now.

Also from the critic, applied without a question: stale "live process" notes on `acp-dispatch`, `acp-run` and `acp-dispatch-wait` rows are superseded by J1 (all three slices exited); the five symlinked skills read UNLINK, not DELETE; `skills/session-finder/fleet.py` is SHIM with the E5 gate, not KEEP; `tools/acp-run` sub-files and `skills/session-finder` sub-files (adapters/, where.py, nested_pty.py, prompt_line.py) inherit their parent's row; `/etc/sudoers.d/acp-dispatch-pmset` joins the Wave 4 operator batch as a removal step.

## Round 2 (2026-11-06 21:35Z, 92 code KEEP rows voted, 12 refuted; the critic's second list, numbered R2-n)

R2-1. The rulings file overrides the rows: the ledger's **Lead** column carries each ruling (this file is its source); rows are not rewritten.
R2-2. **`skills/ade-paseo*` (six vendored Paseo skills)**: three refuters are right that upstream ships them (`skills/ade-paseo/UPSTREAM.md`: vendored from getpaseo/paseo @ fcda2f1 with three local patches: narrowed descriptions so upstream's "handoff"/"stuck" triggers did not steal requests from this repo's `handoff` skill and `dialogue`; an interim worktree-isolation line; the `ade-` prefix because Paseo overwrites unprefixed names, getpaseo/paseo#7700). Patch 1's reason disappears when D3 replaces `handoff`/`baton` with native `/paseo-handoff` and E6 replaces `dialogue`; patch 2 was interim. Ruling: REPLACE in Wave 3 (E10) by Paseo's own shipped skills (`npx skills add getpaseo/paseo`, or the Paseo home's skill selection switched from `{"mode":"custom","skills":[]}` to the bundle), an operator step after the D3 trial; until then KEEP. The redundant `claude/commands/*.md` wrappers (`paseo-screen`, `retro`, `steps`: each skill's `name:` already exposes the slash command; `skillopt-sleep` goes with J4; `teach` moves with E1) are DELETE in E10.
R2-3. herdr server: as ruling 6 (one DECIDE at the C7 gate for all four rows; `tests/test_ade_sched.py:650` is edited then).
R2-4. **`skills/session-finder/session-history.py` and `launchd/com.djbclark.session-history-update.plist`**: DELETE (the script indexes transcripts for session-finder, which goes; no KEEP consumer); the plist in E5, the script in E3; the installed LaunchAgent joins the Wave 3 operator batch (`launchctl bootout gui/$UID/com.djbclark.session-history-update`).
R2-5. context-budget: confirmed (J3): the plist and the `install`/`uninstall` subcommands go in E5; `tests/test_context_budget_check.py:285-292` is rewritten in the same slice; the check itself stays as a Paseo schedule.
R2-6. `claude-quota-guard`: its installed `check` LaunchAgent stays until E7's frontier gate reads `paseo usage ls --json` (research wave3 item 6: the command is `usage ls`, percentages per window); `com.djbclark.claude-fleet-governor` is booted out with E7 (Wave 4 operator batch).
R2-7. `tests/test_fleet_*.py` (7 files): SHIM with `fleet.py`; deleted in E5 when `fleet.py` goes.
R2-8. `tests/test_bigteam_prune.py`: MOVE with diskfree (already in the E1 brief).
R2-9. acp-dispatch tests: the shim's one test is seeded from `test_acp_dispatch.py` (exit codes and record) and `test_acp_dispatch_load_gate.py` (admit gate, cap); `_classify`, `_outcome`, `_brief_footer` contribute one assertion each; the rest go in E6 (`_cursor_cloud`, `_frontier_reason`, `_routing` after their DECIDE rows resolve).
R2-10. `effort-routing` and `fallback-chains`: fold both into `model-routing` (E7, as PLAN E7 says); `fallback-chains`' web-access half follows `web-get` (DECIDE, R2-15).
R2-11. `skills/loadwatch`: DELETE in E5; load-watch's find-and-tell message is reworded to carry the instruction itself (one paragraph), not a skill pointer.
R2-12. `create-hook`, `btww`, `hand`: one shared DECIDE pending `aiuse --json` (ruling 10; operator batch line 8).
R2-13. omp and opencode: the same pool audit gates the ~25 DECIDE rows; Wave 3's E9 part runs after the paste.
R2-14. Cursor: on J2's keep list (cursor-agent); stays unless the pool audit shows its plan is reachable through another provider; `cursor-cloud` rows DECIDE until then.
R2-15. Small-context provider: DECIDE at Wave 3 after the audit; if none survives, `web-get`, `web-digest*`, `firecrawl-router` and their tests go in Wave 3's E9 part.
R2-16. `dialogue` and `research`: the 1-hour Claude-subagent port is attempted in E6 (`dialogue.py:751` is the seam); DELETE if it fails the hour (PLAN E6).
R2-17. `tell-chief-of-staff`: E6/E9j (pointer stays here, code to peer-link); E1 leaves it.
R2-18. `quota_nudge.py` and `cswap_quota_context.sh` (and their live hook lines): DECIDE after session-guard is verified on the Mac (D4); if removed, the hook lines join C2's operator edit.
R2-19. Confirmed: the lead trims the template's four DELETE hook lines, the `herdr-agent-state.sh` hook and the DELETE-skill entries at merge (ruling 8); the live `~/.claude/settings.json` edit for the four C2 hook files is the operator's before the final merge.
R2-20. `bg`: operator batch line 9.
R2-21. `fleet-watch`: `site-djbclark/bin/fleet-watch` (seen in the clone); the paused watchers' LaunchAgents are listed by batch line 6 (`launchctl list | grep com.djbclark`).
R2-22. Provider dot-dirs: keep the kept providers' dirs (`.cursor`, `.codex`, `.agents`, `.claude-plugin`); delete only retired providers' (`.kiro`, `.windsurf`, `.gemini`, `.adal`, `.pi`) in E9's Wave 3 part after the audit.
R2-23. `scripts/github-ci-run`: nothing in site-djbclark names it (grep of the clone, 2026-11-06); only `skills/loadwatch/SKILL.md:178` (DELETE) does. DECIDE in E5: delete unless the operator uses it by hand.
R2-24. adhoc `adversary-pr254f` record and its launchd label: operator batch line 10.
R2-25. aiuse `opencode-go` exclusion: PR 260 first (C3), then drop only if opencode retires.
R2-26. `bin/npm_metadata.py` and its test (0 refs): DELETE in E10.


## B. KEEP rows refuted by majority

### `bin/failover.py` (plan KEEP, E7)

- vote 1: refuted=True (medium): The only code consumer of failover.py's API is bin/skillopt-night. It does `import failover` and uses failover.load_chain, ask_many, Pacing, run_bounded and DENY. PLAN.md D8 and J4 (answered 2026-11-06) say skillopt-night is deleted, along with its plist. bin/ade_gates.py and bin/route_agent.py have no `import failover`. The grep hits are only comments: ade_gates.py:4 says acp-dispatch puts bin/ … — docs/slim/PLAN.md:399 (E7), :230 (D8), :741 (J4 answered: delete); bin/skillopt-night:103 `import failover`; bin/ade_gates.py:4 and bin/route_agent.py:2185 (comments only); PLAN.md D6 row (acp-dispat…
- vote 2: refuted=True (medium): The row's caller list does not hold up under grep. The only live importer of failover is bin/skillopt-night (line 103, `import failover`). docs/slim/PLAN.md lines 579-581 and D8 (line 230) put skillopt-night, skillopt_sources.py, the skillopt-sleep skill and its plist on the DELETE list (J4, answered). bin/route_agent.py and bin/ade_gates.py never import failover. Their hits are only a comment ab… — bin/skillopt-night:103 (sole import); docs/slim/PLAN.md:230, 399, 579-581 (skillopt-night DELETE, J4; E7 failover route half = paseo run); bin/route_agent.py:2185 and bin/ade_gates.py:4 (comments onl…
- vote 3: refuted=True (medium): The reader's evidence is mostly wrong. grep finds no `import failover` or `from failover` in bin/ade_gates.py or bin/route_agent.py. Their hits are comments only: ade_gates.py:4 mentions acp-dispatch's use, and route_agent.py:2185 says failover.py "cannot import the router". The one real importer in bin/ is skillopt-night (`import failover`, :103). PLAN.md D8 and its line ~579 mark `skillopt-nigh… — docs/slim/PLAN.md:399 (E7 "failover.py KEEP only the model-chain half"); docs/slim/PLAN.md D8 (:230) and :579 (skillopt-night DELETE, J4); bin/skillopt-night:103 (the only code importer); bin/ade_gat…

### `bin/pytest` (plan UNLISTED, none)

- vote 1: refuted=True (medium): bin/pytest is a 47-line wrapper that execs `uv run --with pytest --with pyyaml --with agent-client-protocol>=0.9,<1.0 python -m pytest tests/ -q`. uv is a maintained tool that already does this, and nothing in the wrapper is unique. A `[dependency-groups] test` entry in pyproject.toml, or a one-line documented uv command, gives `uv run pytest` with the same pinned deps and removes the drift risk … — /home/user/djbclark-ade/bin/pytest:25-33; /home/user/djbclark-ade/claude/hooks/bg_test_gate.py:50-61 (SEGMENT accepts `uv run ... python -m pytest`); AGENTS.md:276-277 (prose mention only); docs/slim…
- vote 2: refuted=True (medium): Grep finds no executable caller of bin/pytest. The only references to the path are AGENTS.md review rule 2 (lines 276-277), tests/test_bin_pytest.py (the wrapper's own drift test), a comment in tests/conftest.py, skills/firecrawl/SKILL.md (which uses /opt/homebrew/bin/pytest, not this wrapper), and docs and handoffs. The row's "callers" are not callers. .github/workflows/test.yml runs `uv run --w… — bin/pytest docstring; .github/workflows/test.yml:50,108,118-119; AGENTS.md:276-277; tests/test_bin_pytest.py; bin/routing-recalibrate:81; claude/hooks/bg_test_gate.py:51; bin/load-watch:357; docs/sli…
- vote 3: refuted=True (low): No ruling retires it: PLAN.md has no row for bin/pytest, and A2, B2, J2, E9 and the check-in rulings don't mention it. The refutation rests on a replacement. The wrapper is a roughly 40-line `uv run` incantation. CI doesn't call it, since .github/workflows/test.yml lines 50, 108 and 118 inline the same `uv run --with pytest --with pyyaml --with 'agent-client-protocol>=0.9,<1.0' python -m pytest t… — .github/workflows/test.yml:50,108,118 (inline uv command); claude/hooks/bg_test_gate.py:54 (recognizes uv run / python -m pytest); docs/slim/baseline.md:3 (raw command used); docs/slim/PLAN.md sectio…

### `skills/ade-paseo` (plan UNLISTED, none)

- vote 1: refuted=True (medium): `ade-paseo` is Paseo's own `paseo` skill, vendored with only one patch that touches it: the `ade-` rename. The description-narrowing patch (1) and the worktree-isolation patch (2) apply only to the advisor, committee and handoff skills. UPSTREAM.md says the bundled `paseo` is already ahead of this copy (compared 2026-10-23), and the skill has no scripts or tests. The bundled `paseo` skill therefo… — skills/ade-paseo/UPSTREAM.md (patches 1-3, "`paseo` and `paseo-plugin` are ahead of this copy"); docs/skill-everywhere.md:149-166; agents/claude/settings.json.tmpl:89; docs/slim/PLAN.md D3 (native /p…
- vote 2: refuted=True (medium): Nothing executable calls skills/ade-paseo. I grepped the repo, bin and tools: the only referrers are docs (AGENTS.md, CLAUDE.md, docs/skills.md, docs/skill-everywhere.md, docs/apply-toolchain-prompt.md, docs/paseo-only-rearchitecture.md) and one skillOverrides name in agents/claude/settings.json.tmpl:89. That entry only mutes the skill's auto-trigger, so it goes with the skill. docs/slim/PLAN.md … — grep results: docs/slim/PLAN.md has no ade-paseo entry; AGENTS.md:16,21,61; docs/skills.md:111; docs/skill-everywhere.md:149-166; docs/paseo-only-rearchitecture.md:45,49,284; docs/apply-toolchain-pro…
- vote 3: refuted=True (medium): No ruling retires it. PLAN.md lists no ade-paseo row, and A2, B2, J2 and E9 are about providers and TUIs, not this skill. A replacement does exist. The skill is a verbatim vendored copy of upstream getpaseo/paseo `skills/paseo`, which Paseo ships in its own bundle. UPSTREAM.md says the bundle is already ahead of this copy (compared 2026-10-23 against 0.13.0; the installed Paseo is 0.15.x). The on… — skills/ade-paseo/UPSTREAM.md (vendored from fcda2f1, "paseo and paseo-plugin are ahead of this copy", patches 1-3); docs/skill-everywhere.md:149-166 (section 3a, selection {"mode":"custom","skills":[…

### `skills/ade-paseo-plugin` (plan UNLISTED, none)

- vote 1: refuted=True (medium): skills/ade-paseo-plugin is an unmodified vendored copy of upstream getpaseo/paseo `skills/paseo-plugin` (skills/ade-paseo/UPSTREAM.md:3-8), renamed with the ade- prefix so Paseo's own skill sync does not overwrite it. UPSTREAM.md:28-30 says the installed Paseo bundle's `paseo-plugin` is already ahead of this copy (checked 2026-10-23). The skill is not an ADE tool: it is Paseo's own authoring guid… — skills/ade-paseo/UPSTREAM.md:3-8 and :28-30; skills/ade-paseo-plugin/SKILL.md (frontmatter and "Check current documentation"); agents/claude/settings.json.tmpl:94; docs/slim/PLAN.md D9 row (line 231)…
- vote 2: refuted=True (medium): The skill is an unmodified vendored copy of upstream Paseo's `paseo-plugin` skill (`skills/ade-paseo/UPSTREAM.md` lists three local patches, none of which touch this skill). It was only renamed with an `ade-` prefix so Paseo's own skill sync would not overwrite it. That sync already ships the same skill under the unprefixed name, so Paseo supplies the replacement. Its only caller is a `"user-invo… — skills/ade-paseo/UPSTREAM.md:1-15 (vendored from getpaseo/paseo, prefix is to avoid Paseo skill-sync overwrite); agents/claude/settings.json.tmpl:94; grep of docs/slim/PLAN.md finds no mention of ade…
- vote 3: refuted=False (medium): No operator ruling (A2, B2, J2, E9, check-in rulings) names or retires this skill. It is a vendored copy of upstream Paseo's `paseo-plugin` skill, and Paseo is the only harness. J6 installs 13 plugins and D9 may add a ~100-line Paseo hook plugin, so the skill is still needed as the authoring reference. Paseo ships this skill in its own bundle, but UPSTREAM.md says the vendored copy exists because… — skills/ade-paseo-plugin/SKILL.md; skills/ade-paseo/UPSTREAM.md:3-24; docs/slim/PLAN.md J6 (line 748), D9 (line 231); agents/claude/settings.json.tmpl:94; docs/slim/ledger.md:215

### `skills/session-finder/fleet.py` (plan KEEP, E3, E5 (until load-watch and context-watch read paseo ls))

- vote 1: refuted=True (medium): The plan itself rules that fleet.py does not stay permanently. PLAN.md E3 and E5 (lines 306-308 and 334-340) keep it only until load-watch attribution and context-watch are rewritten to read `paseo ls -a -g --json`, and then "fleet.py can go". The plan's D5 row KEEPs only load-watch's two interfaces (`admit` and find-and-tell via `paseo send`), not fleet.py. Wave 3 sequencing (line 605) puts E5's… — docs/slim/PLAN.md:306-308, 334-340, 605, and the D1, D2 and D5 rows (lines 223-227); skills/session-finder/fleet.py:745-806 (_paseo_rows builds rows from `paseo ls` with no pid); bin/load-watch:262-2…
- vote 2: refuted=True (medium): The plan's own ruling is that fleet.py is transitional, not permanent. Every caller is either a deletion target or has a named replacement. Callers I traced: skills/helm/helm.py:57 and lead.md/auto.md (helm is REPLACE/DELETE in E4/D2), session-finder/launch.py:63 (DELETE in E3), bin/rumination-watch (DELETE in E5, and it only mentions fleet.py in a comment), and test_fleet_*.py (DELETE in E3). Th… — docs/slim/PLAN.md:306-309 and 337-342 (E3/E5: fleet.py stays until load-watch attribution and context-watch read `paseo ls -a -g --json`, then goes); docs/slim/PLAN.md:827 (fleet.py is SHIM with the …
- vote 3: refuted=True (high): PLAN.md already rules that fleet.py does not stay. E3 says it "stays until load-watch's attribution and context-watch read Paseo (paseo ls -a -g --json) ... which is part of E5, then goes." E5 adds that load-watch and context-watch are rewritten to read `paseo ls -a -g --json` "so fleet.py can go (E3)". It also requires a hot-path test that runs cmd_sample on a synthetic sustained spike, which gu… — docs/slim/PLAN.md E3 (~lines 306-310) and E5 (~lines 338-343); PLAN.md:827 amendment; docs/slim/ledger.md:30, 100, 141-142, 162, 187, 245, 262, 270, 536-542, 589, 620

### `claude/commands/paseo-screen.md` (plan UNLISTED, none)

- vote 1: refuted=True (medium): The wrapper claude/commands/paseo-screen.md (8 lines) only says "follow the mounted paseo-screen skill" and passes $ARGUMENTS. The skill skills/paseo-screen/SKILL.md has `name: paseo-screen`, so Claude Code already exposes it as /paseo-screen once skills are mounted. PLAN D7 sets that up as one symlink, ~/.claude/skills -> <repo>/skills, with no tool. The ~/.claude/commands/paseo-screen.md symlin… — claude/commands/paseo-screen.md (whole file); skills/paseo-screen/SKILL.md:2 (name: paseo-screen); docs/slim/PLAN.md section D row D7 (~/.claude/skills symlink); docs/slim/ledger.md:294; README.md:83
- vote 2: refuted=True (medium): The wrapper is 8 lines and only says "follow the mounted paseo-screen skill". The skill (skills/paseo-screen/SKILL.md) stays, and its frontmatter has name: paseo-screen. Claude Code exposes any skill with that name as /paseo-screen. PLAN D7 replaces skill-everywhere with a single symlink ~/.claude/skills -> <repo>/skills, so /paseo-screen keeps working without the wrapper. The only in-repo caller… — claude/commands/paseo-screen.md (8 lines); skills/paseo-screen/SKILL.md:2 (name: paseo-screen); README.md:83; docs/skills.md:41; docs/slim/PLAN.md D7 row (line ~226, ~/.claude/skills symlink); docs/s…
- vote 3: refuted=False (medium): I found no ruling that retires it. PLAN.md sections A2, B2, D and E and docs/slim/checkin-rulings.md never mention paseo-screen or the claude/commands wrappers. The /paseo-screen wrapper is a Claude Code slash command that points at skills/paseo-screen, and that skill is the Paseo-plugin screen-control tool. It is not a retired TUI, not herdr, Orca or BB, and not a second provider. README.md stil… — /home/user/djbclark-ade/claude/commands/paseo-screen.md (8 lines); docs/slim/ledger.md:294 (UNLISTED, KEEP); README.md:83 and :150; docs/slim/PLAN.md A2, B2, D1-D15 (no entry covers screen control or…

### `bin/context-watch:74 (FLEET = .../skills/session-finder/fleet.py) and :36,298 clean_text` (plan KEEP, E5, E3)

- vote 1: refuted=True (medium): The fleet.py coupling does not need to stay; context-watch does. It uses only two things from fleet.py: the PASEO_ID UUID regex (context-watch lines 188, 263, 284) and clean_text, a roughly 6-line control/ANSI/bidi-character stripper (fleet.py:706-711). PLAN E3 and E5 already rule that fleet.py goes once context-watch and load-watch attribution read `paseo ls -a -g --json`. The two helpers can be… — docs/slim/PLAN.md:293,306-307,338-339 (E3/E5); table D rows D4,D5 (context-watch kept, no fleet.py dependency); bin/context-watch:36,74,91-92,188,263,284,298-300,344; skills/session-finder/fleet.py:9…
- vote 2: refuted=True (medium): The row's evidence is a dependency that the plan has already ruled on. fleet.py is used by bin/context-watch only for `_fleet().PASEO_ID.fullmatch` (lines 188, 263, 284) and `clean_text` (lines 36, 298, 300). Plan E5 says context-watch is "rewritten to read `paseo ls -a -g --json` so `fleet.py` can go (E3)", and D5 lists `context-watch:74` among the four KEEP-code hits that must be cleared before… — docs/slim/PLAN.md:293,305-307,338-340 (D5/E5 rewrite so fleet.py can go); bin/context-watch:36,74,91-92,188,263,284,298-300; skills/session-finder/fleet.py:706-711 (clean_text); docs/slim/ledger.md:1…
- vote 3: refuted=True (high): PLAN.md already rules that the fleet.py dependency is temporary. Section E3 (around lines 306-307) says "`fleet.py` stays until `load-watch`'s attribution and `context-watch` read Paseo (`paseo ls -a -g --json`) instead, which is part of E5, then goes." The E5 text (around lines 338-339) says context-watch is rewritten to read `paseo ls -a -g --json` "so `fleet.py` can go (E3)". The ledger also m… — docs/slim/PLAN.md:306-307 (E3), :338-339 (E5), :827 (ledger: fleet.py SHIM with the E5 gate); bin/context-watch:74, :36, :298, :193 (paseo_agents)

### `bin/load-watch:266 (fleet.sessions()), 29 and 32 docstring` (plan KEEP, E5, D5, E3)

- vote 1: refuted=True (medium): The row is a dependency on session-finder's fleet.py and relay.py, not a capability that must stay. PLAN E5 and E3 already rule that fleet.py goes. load-watch's attribution is rewritten to read `paseo ls -a -g --json`, so the `import fleet` / `fleet.sessions()` at bin/load-watch:266 is replaced. A hot-path test is required, because the call at 1227-1233 is unguarded and a ModuleNotFoundError woul… — docs/slim/PLAN.md E5 (line 329 onward) and E3 (lines 276-290, 335-342): "load-watch's attribution ... rewritten to read `paseo ls -a -g --json` so `fleet.py` can go", with a hot-path test of cmd_samp…
- vote 2: refuted=True (high): The row cites no unreplaced interface. Line 266 (`import fleet; fleet.sessions()`) is a transitional dependency that PLAN E3 and E5 already rule away. E5 says `load-watch`'s attribution and `context-watch` are rewritten to read `paseo ls -a -g --json`, so `fleet.py` can go. E3 says `fleet.py` stays only until that rewrite. Moving the call to `paseo ls` also removes the unguarded `ModuleNotFoundEr… — docs/slim/PLAN.md E3 (lines 291-292, 306-308) and E5 (lines 338-342); D5 (line 227); bin/load-watch:266 and 1227-1233
- vote 3: refuted=True (high): Plan E3/E5 already rules that these lines are rewritten, not preserved. The `fleet.sessions()` import at line 266 is named as a blocker for deleting fleet.py. The plan's fix is to rewrite load-watch's attribution to read `paseo ls -a -g --json`, after which fleet.py goes, with a hot-path test of `cmd_sample` through attribution. D5 keeps the find-and-tell behaviour and `admit`, delivered by `pase… — docs/slim/PLAN.md: D5 row (line 227: "delete the pane-typing delivery"); E3 (lines 290-307: "`fleet.py` stays until `load-watch`'s attribution and `context-watch` read Paseo (`paseo ls -a -g --json`)…

### `skills/session-handoff/SKILL.md:137-148,170,185 (fleet.py --json; relay.py by absolute path)` (plan KEEP, E3, D3)

- vote 1: refuted=True (medium): The row is not a reason to keep session-finder. It is a path caller that PLAN E3 already schedules for rewriting, and each interface it uses has a named replacement or a retirement ruling. relay.py (SKILL.md:170,185, the live-owner question): D1 says REPLACE with native `paseo send`. E3 keeps a roughly 100-line shim for one cycle, then deletes it, so no real relay.py remains. fleet.py --json (:13… — docs/slim/PLAN.md D1 (line 223, REPLACE shim one cycle), D3 (line 225), E3 (lines 276-311: shim then delete; fleet.py stays only until E5, then goes; SKILL.md:137-148,170,185 listed as a path caller …
- vote 2: refuted=True (medium): The row's only caller is a doc: the references at skills/session-handoff/SKILL.md:137-148,170,185 point at fleet.py --json and relay.py by absolute path. The plan names these as path callers to be updated, not interfaces that stay. PLAN E3 (lines 297-307) says fleet.py stays only until load-watch's attribution and context-watch read `paseo ls -a -g --json`, which is E5, and then goes. relay.py be… — docs/slim/PLAN.md:276-310 (E3: fleet.py stays until E5, relay.py shim then delete, session-handoff:137-148,170,185 named as a path caller to update); docs/slim/PLAN.md:223 (D1 REPLACE relay.py with n…
- vote 3: refuted=True (high): The row says to keep the references, but PLAN E3 and D1 say the interfaces they call are not kept. `fleet.py` stays only until E5 rewrites `load-watch` attribution and `context-watch` to read `paseo ls -a -g --json`, and then it is deleted. `relay.py` becomes a roughly 100-line Paseo-only shim (`paseo send`), which is deleted in the follow-up PR after one live cycle. The same E3 paragraph names `… — docs/slim/PLAN.md E3 (lines ~276-306: "fleet.py stays until load-watch's attribution and context-watch read Paseo... then goes"; relay.py SHIM then delete; session-handoff:137-148,170,185 listed as a…

### `bin/route_agent.py:133 (path .../tools/acp-run/acp-run) and :39,43 docs` (plan KEEP, E7)

- vote 1: refuted=True (medium): The line-133 acp-run path and the docstring lines 39 and 43 are only the registry source: ACP_RUN is used at about line 1211 to run `acp-run --list`. PLAN E7 says to KEEP route_agent.py but switch its registry from `acp-run --list` to `paseo provider ls --json`. Once that lands, the ACP_RUN path and the docstring text are dead and get rewritten. `paseo provider ls --json` covers the one interface… — docs/slim/PLAN.md E7 (line ~395: registry switched from `acp-run --list` to `paseo provider ls --json`) and section D row D6 (line 228); the PLAN.md line ~378 ruling that E7's switch alone does not d…
- vote 2: refuted=True (high): The row is a reference inside a kept file, not a kept interface. bin/route_agent.py itself stays (E7 KEEP). Its lines 133 (the ACP_RUN path to tools/acp-run/acp-run) and 39,43 (the docstring "acp-run --list is the agent table") are the old registry source, and E7 explicitly replaces that registry with `paseo provider ls --json` (rearchitecture C2). So that code is rewritten in E7 and the docstrin… — docs/slim/PLAN.md E7 ("registry switched from `acp-run --list` to `paseo provider ls --json`") and E6 ("`acp-run` ... go with the shims in the follow-up PR after one live cycle"); docs/slim/ledger.md…
- vote 3: refuted=True (medium): A ruling already covers it. Those lines (the ACP_RUN path build at route_agent.py:133 and the docstring mentions of `acp-run --list` at :39,43) exist only because the registry is read from acp-run. PLAN E7 says route_agent.py is kept, but with its registry switched from `acp-run --list` to `paseo provider ls --json`. That switch removes the acp-run path and its docs. The replacement is `paseo pro… — docs/slim/PLAN.md E7 (line ~395-397: "registry switched from acp-run --list to paseo provider ls --json"); PLAN.md E6 (~376-381: acp-run stays only as launch interface for C3 consumers, deleted in Wa…

### `bin/failover.py (57 acp-run mentions)` (plan KEEP, E7)

- vote 1: refuted=True (high): failover.py has no kept consumer. Its only code importer is bin/skillopt-night (line 103, `import failover`), which PLAN D8/J4 and the later W1 ledger mark DELETE. route_agent.py and ade_gates.py mention failover only in comments. web-get, web-digest and change-hermes use the word "failover" generically and do not import it. The 57 acp-run mentions describe the route half, which E7 itself says is… — docs/slim/ledger.md:13 (ruling 1) and :35-39 (3 refute votes); docs/slim/PLAN.md:399 (E7), :230 (D8), :741 (J4), :827 (E7 amendment); bin/skillopt-night:103; bin/route_agent.py:2185 and bin/ade_gates…
- vote 2: refuted=True (high): bin/failover.py does not need to stay. Its only live importer is bin/skillopt-night, which is a DELETE target (J4, E10). The other mentions are comments or docs: route_agent.py, ade_gates.py, web-get and the acp-run comments and README. The ledger-rulings ruling 1 withdraws the plan's E7 "KEEP the model-chain half". It says no kept code consumes it, and it sends failover.md to docs/history. It al… — docs/slim/ledger-rulings.md:3 (ruling 1); docs/slim/PLAN.md:827 and :399; bin/skillopt-night:103 (`import failover`); docs/slim/PLAN.md:230 (skillopt-night deleted, J4)
- vote 3: refuted=True (high): An operator-level ruling already covers it. Ledger ruling 1 says: DELETE bin/failover.py together with skillopt-night in E10, move docs/failover.md to docs/history/, and rewrite AGENTS.md's "reuse it, never hand-roll a fallback" row to name `paseo run`'s model chain. The same ruling withdraws E7's "KEEP the model-chain half" because no kept code consumes it. PLAN.md line 827 repeats the withdrawa… — docs/slim/ledger-rulings.md:3 (ruling 1); docs/slim/PLAN.md:827 (W1 amendment); docs/slim/ledger.md:13,1014 (failover.py:59 'skillopt-night uses load_chain', :289 and :918 skillopt-only flags); PLAN.…

### `bin/load-watch acp-run mentions (18) and bin/ade-git-guard:18, bin/ade_claims.py:14 (W4 acp-run puts libexec/agent-bin on PATH)` (plan KEEP, E5, E8)

- vote 1: refuted=True (medium): The row is really about references to acp-run inside files that are themselves kept. Neither reference is a live interface that has no replacement. (1) The load-watch count of acp-run processes: PLAN E6 says count_agents() is ported to `paseo ls -a -g --json` before the shim ships, with a burst test against the 14-agent cap, and E5 rewrites load-watch's attribution to read the same command. So th… — docs/slim/PLAN.md:346-383 (E6: count_agents ported to `paseo ls -a -g --json`; acp-run removed in the Wave 6 follow-up PR), PLAN.md:329-343 (E5: load-watch attribution rewritten to read `paseo ls`), …
- vote 2: refuted=False (high): The row is not a deletion target. The evidence is just comments and an acp-run process count inside three files the plan keeps. load-watch is KEEP (D5): its `admit` pre-launch gate has no replacement, and the plan names it explicitly. Its callers `bg`, `acp-dispatch`, `local-review` and `deadline_wait.py` are KEEP or REPLACE-with-shim, and the E6 shim must retain the `admit` gate (exit 75). The a… — docs/slim/PLAN.md D5 (line 227), D9 (line 231), E6 (lines 345-380), E8 (line 424), Wave 6 (line 608); bin/load-watch:101-103, 1589-1614; bin/ade-git-guard:15-20; bin/ade_claims.py:14
- vote 3: refuted=True (high): The row mixes two things. The files (load-watch, ade-git-guard, ade_claims.py) stay, as D5 and D9 say. The acp-run mentions in them do not have to stay. PLAN E6 orders the live-agent count ported from `acp-run` processes to `paseo ls -a -g --json` before the shim ships, with a handoff test that a burst of launches still hits the 14-agent cap. E6 and Wave 6 then delete acp-run in a follow-up PR af… — docs/slim/PLAN.md E6 (lines ~346-383: count_agents ported to `paseo ls -a -g --json`; acp-run and tests/test_acp_run_* removed in the Wave 6 follow-up PR) and Wave 6 row (line ~608); D5 and D9 (lines…


## C. Rows whose proposed disposition differs from the plan

| Path | Plan (ref) | Proposed | Note |
|---|---|---|---|
| `bin/codex-env-policy-apply` | DELETE (E9) | DECIDE | Plan contradicts itself: Codex is on the E9 keep list; delete only when Codex retires. |
| `bin/paseo-set-model` | DELETE (E4) | DECIDE | Plan expects the audit to find nothing live; route_agent.py substrate (a KEEP file) needs it. Port or drop 'substrate' first. |
| `bin/paseo-set-model.mjs` | DELETE (E4) | DECIDE | Follows paseo-set-model. |
| `skills/btww` | DELETE (retired providers only) (E4) | KEEP | Trim the retired-TUI rows rather than delete; the plan's own wording says retired providers only. |
| `skills/create-hook` | DELETE (E9) | KEEP | E9 lists it as a retired-provider skill but it belongs to a surviving provider. Delete only if Codex retires. |
| `skills/fallback-chains` | REPLACE (E7 (folds into model-routing)…) | DECIDE | The model-chain half folds; the web-access half follows web-get's fate (E9). |
| `skills/hand` | DELETE (retired providers only) (E4, C2 (four hand links)) | DECIDE | Its purpose is omp's collision, so it stands or falls with omp in the Wave 1 pool audit; for Claude, Codex and Cursor it adds nothing. |
| `skills/loadwatch` | DELETE (E5, D5) | DECIDE | D5 keeps load-watch's find-and-tell, whose messages tell the receiving agent to read this skill. Delete it only with a load-watch reword (or fold the… |
| `skills/oc-go-key` | DELETE (E9 (opencode), J2 audit) | DECIDE | Hinges on the J2 pool audit; the test goes with it. |
| `skills/tell-chief-of-staff` | MOVE (E1 (Grok-bot skills) vs E6 (p…) | DECIDE | The plan contradicts itself between E1 and E6; the operator picks one. |
| `tests/test_acp_dispatch.py` | DELETE (E6, D6) | SHIM | bin/acp-dispatch exit-code and record contract plus base harness. Shim keeps exit 3/4/77/124 and the report/.done record (E6); plan gives the shim on… |
| `tests/test_acp_dispatch_brief_footer.py` | DELETE (E6, D6) | SHIM | acp-dispatch brief footer on re-dispatched -f files; E6 says the shim keeps the brief footer. |
| `tests/test_acp_dispatch_classify.py` | DELETE (E6, D6) | SHIM | acp-dispatch report classification (DONE plus verdict line is done, not partial); decides the .done status the shim keeps (E6). |
| `tests/test_acp_dispatch_cursor_cloud.py` | DELETE (E6, E9) | DECIDE | acp-dispatch cursor-cloud route plus route_agent registration; cursor-cloud goes only 'if Cursor goes' (E9, J2). |
| `tests/test_acp_dispatch_frontier_reason.py` | DELETE (E6, E7) | DECIDE | acp-dispatch --kind frontier admission plus ade_gates frontier half; E6 shim keeps the admission check, E7 keeps the frontier half. |
| `tests/test_acp_dispatch_load_gate.py` | DELETE (E6, D5) | SHIM | acp-dispatch load-watch admit gate (exit 75), agent cap, reservation; E6 shim keeps the admit gate and the 14-agent cap. |
| `tests/test_acp_dispatch_outcome.py` | DELETE (E6, C4) | SHIM | acp-dispatch outcome writes the fields route_agent.py calibrate reads; E6 and C4 keep that record. |
| `tests/test_acp_dispatch_routing.py` | DELETE (E6, E7) | DECIDE | acp-dispatch --kind eligibility, frontier advisor, estimate, reservation: mixes shim-kept frontier/reservation behaviour with deleted routing. |
| `tests/test_acp_run_deny.py` | DELETE (E6, D6) | REPLACE | acp-run --perm deny boundary. E6 says the shim must reproduce this boundary with tests before it ships: port these assertions to the review-launch/sh… |
| `tests/test_acp_run_read_only.py` | DELETE (E6, D6) | REPLACE | acp-run --perm read-only six-tool allowlist and tripwire; same boundary as test_acp_run_deny (E6, E8 review-launch). |
| `tests/test_acp_run_git_identity.py` | DELETE (E6, D6) | DECIDE | acp-run git-identity guard (reference-transaction hook via GIT_CONFIG_PARAMETERS); vanishes with acp-run unless ported; test_ade_git_hooks r11_f6 dep… |
| `tests/test_acp_run_go_installation.py` | DELETE (E6, E7, J2) | DECIDE | acp-run opencode Go-policy install; depends on the J2 opencode audit. |
| `tests/test_acp_run_grok_deny.py` | DELETE (E6, E9) | DECIDE | acp-run grok --perm deny: grok is on the keep list but J2 one-provider-per-plan may retire it; the zcode half is dead. |
| `tests/test_acp_run_strip.py` | DELETE (E6, D6) | DECIDE | acp-run --strip-user-config for opencode and agy: settings stripping is part of the E6 restricted-mode boundary but these cases cover opencode/agy. |
| `tests/test_acp_run_strip_perm_all.py` | DELETE (E6, D6) | DECIDE | acp-run --strip-user-config outside --perm deny: claude case is boundary-relevant, opencode/agy cases are not. |
| `tests/test_argon_frontier.py` | DELETE (E6, E7) | DECIDE | acp-dispatch frontier gates plus KEEP route_agent/failover; bin/route_agent.py:2186 names this test. |
| `tests/test_claude_quota_guard.py` | REPLACE (E7, D4) | DECIDE | State-producing half of claude-quota-guard is KEEP until frontier consumers read paseo usage (E7); quota_nudge.py KEEP only if plugins cannot nudge (… |
| `tests/test_codex_shell_env_policy.py` | DELETE (E9) | DECIDE | E9 lists codex-env-policy-apply under retired-provider helpers, yet codex is on E9's keep list; the file also covers acp-run and relay.py. |
| `tests/test_deadline_wrappers.py` | KEEP (E5, E6, E8) | DECIDE | Three subjects: pr-wait REPLACE, acp-dispatch-wait DELETE, load-watch admit KEEP. |
| `tests/test_failover.py` | KEEP (E7) | DECIDE | E7 keeps only the model-chain half of failover.py; the acp route half is paseo run. |
| `tests/test_gates.py` | REPLACE (E7, D4) | DECIDE | ade_gates Claude-quota half and gate-profile DELETE, frontier half KEEP, config/gates.toml shared. |
| `tests/test_relay_message_file.py` | DELETE (E3, D1) | SHIM | Shim keeps --message-file/--ack/--wait (E3; bin/deadline:446-451); this file and test_relay_verified are the source for the shim's one test. |
| `tests/test_relay_watchers_no_ack.py` | DELETE (E3, E5) | DECIDE | load-watch find-and-tell is KEEP (D5) while the other two watchers go. |
| `docs/agent-guard-contract.md` | MOVE (E11 (rest to history)) | KEEP | E11's generic 'rest to history' would dangle the agent_guard.py reference; KEEP while agent_guard.py lives |
| `docs/context-hygiene.md` | MOVE (E11 (rest to history)) | KEEP | four skills that survive link it; rewrite links before moving, else KEEP |
| `docs/deadline.md` | KEEP (E5 (deadline KEEP), E11) | KEEP | E11 keep list omits it but E5 keeps the tool; plan_disposition derived from E5 |
| `docs/dispatch-footer.md` | KEEP (E6 (brief footer kept)) | KEEP | E11 generic 'rest to history' would break acp-dispatch at runtime |
| `docs/failover.md` | KEEP (E7 (failover.py model-chain h…) | KEEP | trim the route half; E11 keep list silent |
| `docs/hand-alias.md` | MOVE (E4, E11) | KEEP | KEEP until the last hand link goes; then DELETE |
| `docs/mcp-servers.md` | MOVE (E11 (rest to history)) | KEEP | two KEEP docs link it; E11 does not name it |
| `docs/pr-policy.md` | KEEP (E5 (pr-policy KEEP)) | KEEP | E11 keep list silent; E5 keeps the tool |
| `docs/skill-everywhere.md` | MOVE (E10, E11) | KEEP | E11 would move it to history while the tool it documents stays; trim instead; .gitignore names it |
| `docs/upstream-issues.md` | MOVE (E11 (rest to history)) | KEEP | unfiled drafts are live; KEEP, prune entries for retired tools |
| `config/launchd/dev.herdr.server.plist -> ~/Library/LaunchAgents/dev.herdr.server.plist` | KEEP (AGENTS.md retirement box; E2 …) | DECIDE | PLAN E names neither file; AGENTS.md says they stay. DECIDE at the D4/D6 drain. |
| `~/.claude/settings.json hook: claude/hooks/prior_art_nudge.py (PostToolUse and UserPrompt…` | DELETE (E10, J4, C2) | DELETE | Template has three references (285, 307, 600) where C2 counts two; the operator edit must cover the template too. A hook on a deleted file fires on e… |
| `~/.claude/settings.json hook: skills/autorename/autorename_nudge.py (UserPromptSubmit)` | DELETE (E4) | DELETE | C2 omits this hook from its list of hook lines to remove; it must be added to the operator-edit list. |
| `~/.claude/settings.json hook: claude/hooks/relay_prose_nudge.py` | DELETE (E3) | DELETE | Not in C2's hook list. Goes only with the real relay.py, since its text matching depends on relay.py's footers (not the shim's). |
| `skills/session-finder/relay.py callers by path in skills: helm/lead.md:22, session-handof…` | REPLACE (E3, E4, E5) | SHIM | ade-paseo-handoff uses --transfer-expectations/--pending/--sweep/--expect-ack, outside the three-flag shim set in E3. |
| `skills/helm/helm.py:57 (import fleet) and skills/helm/lead.md:20,22` | REPLACE (E4, D2) | REPLACE | E3's import search missed helm.py; helm is deleted in E4, so fleet.py cannot go before E4. |
| `skills/autorename/autorename.py:95,123-125 (import claude_identity)` | DELETE (E4) | DELETE | If the claude_identity move to bin/ precedes E4, autorename's sys.path import breaks until E4 lands. |

## D. The ledger, by area

### D.bin (95 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `bin/acp-dispatch` | 5943 | SHIM (E6, D6) | SHIM |  |  | - | 18 | Shim must keep go_model_policy/agent_guard import paths valid or trim the opencode-go branch at :4787. |
| `bin/acp-dispatch-wait` | 131 | DELETE (E6, D6) | DELETE |  |  | - | 4 | Gate: C7 drain (no live waiters). |
| `bin/acp-dispatch:839-840 (import claude_identity; claude_identity.owner_session_id())` | 5943 | SHIM (E6, E3) | SHIM |  |  | - | 1 | The shim needs owner_session_id from the moved claude_identity. |
| `bin/ade-backup-stores` | 1899 | KEEP (E10) | KEEP |  |  | survives (3/3 keep) | 1 | Trim to surviving stores; credential exclusions stay (E9h Q4). |
| `bin/ade-git-guard` | 158 | KEEP (E8, D9) | KEEP |  |  | survives (3/3 keep) | 4 | E8 adds the real claim ls. |
| `bin/ade-retro` | 381 | UNLISTED (none) | KEEP |  |  | survives (3/3 keep) | 2 | Not in inventory section A (76 entries); bin/ has 82 tracked files. Read-only report tool; depends on changelog-fold staying. |
| `bin/ade-scan-state` | 2294 | DELETE (E2) | DELETE |  |  | - | 1 | docs/threat-model.md mentions it; reword in E11. |
| `bin/ade-scan-state-doc` | 1118 | DELETE (E2) | DELETE |  |  | - | 1 | Covered by the 'ade-scan-state*' glob. |
| `bin/ade-sched` | 150 | KEEP (E5, D8) | KEEP |  |  | survives (3/3 keep) | 1 | Not in inventory section A. |
| `bin/ade-template-check` | 516 | UNLISTED (none) | KEEP |  |  | survives (3/3 keep) | 1 | Shrinks with the agents/ templates E9 deletes; lives while any template remains. |
| `bin/ade-update` | 850 | KEEP (E10) | KEEP |  |  | survives (3/3 keep) | 4 | Plan: trim to pull + skill-everywhere --check (:24-37). |
| `bin/ade_claims.py` | 2334 | KEEP (E8, D9) | KEEP |  |  | survives (3/3 keep) | 4 | Update :1272 cow-pasture advice in the same slice as E2. |
| `bin/ade_claims.py (relay.py by text at 1480, 1854, 2025; claude_identity import at 434)` | 2334 | KEEP (E8, E3, C5) | KEEP |  |  | survives (3/3 keep) | 2 | Messages naming relay.py need rewording when the shim lands; the import needs the claude_identity move to bin/. |
| `bin/ade_gates.py` | 735 | KEEP (E7, D4) | KEEP |  |  | survives (3/3 keep) | 6 | KEEP only the frontier half; Claude-quota half goes after session-guard is live and the C3 gate. |
| `bin/ade_sched.py` | 1049 | KEEP (E5, D8) | KEEP |  |  | survives (3/3 keep) | 0 | Plan names 'ade-sched (PR 291)'; module is part of it. Not in inventory section A. |
| `bin/agent_guard.py` | 111 | KEEP (E6, B1d) | KEEP |  |  | survives (3/3 keep) | 1 | Mentions pi/omp/codex rules; trim with retired providers. |
| `bin/agent_guard.py (acp-run option allowlist, PR 275)` | 111 | KEEP (E6, B1d) | KEEP |  |  | survives (3/3 keep) | 2 | Tests: tests/test_acp_dispatch_identity.py, tests/test_omp_operator_gate.py; docs/agent-guard-contract.md. |
| `bin/agy-linux` | 69 | DELETE (E9) | DELETE |  |  | - | 0 |  |
| `bin/app-tamer-ab` | 68 | MOVE (E1) | MOVE |  | site-djbclark | - | 0 | Moves to site-djbclark after a secrets scan. |
| `bin/bm-lint` | 742 | KEEP (E10) | KEEP |  |  | survives (3/3 keep) | 0 |  |
| `bin/change-hermes` | 675 | MOVE (E1 (change-hermes*)) | MOVE |  | site-djbclark | - | 1 | Move together with the ssh-gate and both tests. |
| `bin/change-hermes-ssh-gate` | 14 | MOVE (E1 (change-hermes*)) | MOVE |  | site-djbclark | - | 1 |  |
| `bin/changelog-fold` | 288 | KEEP (E8) | KEEP |  |  | survives (3/3 keep) | 2 |  |
| `bin/claude-cost-mix` | 226 | KEEP (E7) | KEEP |  |  | survives (3/3 keep) | 0 |  |
| `bin/claude-cost-whatif` | 100 | DELETE (E7) | DELETE |  |  | - | 0 | E7 text puts it in a ';'-separated list before 'KEEP claude-cost-mix'; read as DELETE. |
| `bin/claude-fleet-governor` | 856 | DELETE (E7, D4) | DELETE | DELETE (E7) |  | - | 7 | Only after session-guard/usage-auto-resume verified live and C3 gate. |
| `bin/claude-quota-guard` | 912 | REPLACE (E7, D4) | REPLACE | KEEP check half until E7 reads paseo usage (R2-6) |  | - | 9 | The state-producing check half stays until frontier consumers read paseo usage --json. |
| `bin/claude-settings-env` | 107 | UNLISTED (none) | KEEP |  |  | survives (2/3 keep) | 1 | Fits the Claude-only direction. |
| `bin/codex-env-policy-apply` | 175 | DELETE (E9) | DECIDE ≠ | KEEP (ruling 9) |  | - | 1 | Plan contradicts itself: Codex is on the E9 keep list; delete only when Codex retires. |
| `bin/coding-bot` | 601 | MOVE (E6 (E9j)) | MOVE |  | peer-link | - | 1 | Code moves to peer-link's repo; pointer skill stays; operator repoints symlink and home-agents item 40. |
| `bin/codium-ai` | 59 | MOVE (E1) | MOVE |  | site-djbclark | - | 0 | Update AGENTS.md rule 3 in E11. |
| `bin/context-budget-check` | 484 | KEEP (E5, J3) | KEEP |  |  | survives (3/3 keep) | 2 | J3: plist and install/uninstall subcommands go, Paseo schedule replaces. |
| `bin/context-watch` | 377 | KEEP (E5, D4) | KEEP |  |  | survives (3/3 keep) | 0 | E5 rewrites attribution to paseo ls so fleet.py can go (E3 order dependency). |
| `bin/context-watch:74 (FLEET = .../skills/session-finder/fleet.py) and :36,298 clean_text` | 377 | KEEP (E5, E3) | KEEP |  |  | **REFUTED** (0/3 keep) | 1 | clean_text sanitiser must be copied or reimplemented when fleet.py goes. |
| `bin/cow-pasture` | 376 | DELETE (E2) | DELETE |  |  | - | 4 | AGENTS.md order 9 names cow pastures; E11 rewrites. |
| `bin/crush-context-check` | 138 | DELETE (E9) | DELETE |  |  | - | 0 |  |
| `bin/cursor-cloud` | 196 | DECIDE (E9 ('if Cursor goes')) | DECIDE | DECIDE J2 pool audit (R2-14) |  | - | 4 | Cursor-agent is on the keep list; J2 pool audit decides. |
| `bin/deadline` | 1583 | KEEP (E5) | KEEP |  |  | survives (3/3 keep) | 12 |  |
| `bin/deadline_wait.py` | 177 | KEEP (E5, E3) | KEEP |  |  | survives (3/3 keep) | 2 | pr-wait goes in E8; load-watch remains its caller. |
| `bin/failover.py` | 1403 | KEEP (E7) | KEEP | DELETE (E10, ruling 1) |  | **REFUTED** (0/3 keep) | 6 | Route half goes to paseo run. |
| `bin/failover.py (57 acp-run mentions)` | 1403 | KEEP (E7) | KEEP |  |  | **REFUTED** (0/3 keep) | 1 | Heaviest acp-run caller after load-watch; trim in E7. |
| `bin/firecrawl-router` | 790 | DECIDE (E9) | DECIDE |  |  | - | 3 | Plan: keep only while a small-context provider survives. Its main skill leaves with E1, so the surviving caller is a skill that folds. |
| `bin/fix-skill-frontmatter.py` | 113 | DELETE (E10, D7) | DELETE |  |  | - | 0 |  |
| `bin/gate-profile` | 502 | DELETE (E7, D4) | DELETE |  |  | - | 6 | Same gate as claude-fleet-governor. |
| `bin/git-commit-own` | 51 | KEEP (E8) | KEEP |  |  | survives (3/3 keep) | 2 | .pi/agents goes with pi retirement. |
| `bin/gnu-tools-check` | 326 | UNLISTED (none) | KEEP |  |  | survives (3/3 keep) | 2 | Low-value but self-contained; DELETE is also defensible. |
| `bin/go_model_policy.py` | 59 | DELETE (E7) | DELETE | SHIM (ruling 5) |  | - | 4 | Delete only once opencode retires (J2) and the two import sites and the CI line are trimmed first. |
| `bin/heavy-shim` | 46 | MOVE (E1) | MOVE |  | site-djbclark | - | 0 |  |
| `bin/herdr-server-run` | 28 | UNLISTED (none (AGENTS.md retirement bo…) | DECIDE | DECIDE at C7 (ruling 6) |  | - | 1 | Plan E never names it; operator ruling needed on the drain date. |
| `bin/instruction-lint` | 352 | KEEP (D13 (E5 J3)) | KEEP |  |  | survives (3/3 keep) | 3 | Not in inventory section A. Update the stale-name list as names retire. |
| `bin/instruction-lint:28-29,70 (retired-term list includes relay.py and acp-run)` | 352 | KEEP (D13) | KEEP |  |  | survives (3/3 keep) | 0 | Self-referential match; after deletion the term list needs a prune. |
| `bin/jev` | 528 | DELETE (E2, J4) | DELETE |  |  | - | 5 | Remove route_agent.py JEV and shadow_kind in the same slice. |
| `bin/jev-eval` | 515 | DELETE (E2) | DELETE |  |  | - | 0 |  |
| `bin/load-watch` | 2188 | KEEP (E5, D5) | KEEP |  |  | survives (3/3 keep) | 12 | E5 must port attribution to paseo ls before E3 deletes fleet.py. |
| `bin/load-watch acp-run mentions (18) and bin/ade-git-guard:18, bin/ade_claims.py:14 (W4 acp-run put…` |  | KEEP (E5, E8) | KEEP |  |  | **REFUTED** (1/3 keep) | 1 | W3/W4 are documented as NOT wired yet, so no runtime dependency from the claim tools. |
| `bin/load-watch:266 (fleet.sessions()), 29 and 32 docstring` | 2188 | KEEP (E5, D5, E3) | KEEP |  |  | **REFUTED** (0/3 keep) | 2 | Hot path: a ModuleNotFoundError would disable runaway-load response (PLAN E5). |
| `bin/local-review` | 685 | REPLACE (E8, D10) | REPLACE |  |  | - | 5 | Delete only after review-launch carries every isolation check as a test. |
| `bin/npm_metadata.py` | 22 | UNLISTED (none) | DELETE | DELETE (E10, R2-26) |  | - | 0 | Orphan; delete with its test. |
| `bin/opencode-plugin-guard` | 141 | DELETE (E9 (opencode-*)) | DECIDE |  |  | - | 1 | E9 also says opencode survives only if a paid plan is reachable solely through it (J2 pool audit). |
| `bin/opencode-self-compact` | 53 | DELETE (E9 (opencode-*)) | DECIDE |  |  | - | 1 | Goes with self-slash at the latest. |
| `bin/ops-post-checkout-guard` | 77 | KEEP (E8) | KEEP |  |  | survives (3/3 keep) | 0 |  |
| `bin/paseo-bypass-watch` | 362 | DELETE (E4) | DELETE |  |  | - | 2 |  |
| `bin/paseo-new-seat` | 215 | DELETE (E4) | DELETE |  |  | - | 5 | skills/handoff and AGENTS.md (E11) must stop naming it first; plan: delete after audit confirms paseo run covers it. |
| `bin/paseo-new-seat.mjs` | 168 | DELETE (E4) | DELETE |  |  | - | 1 | Companion file not named by the plan. |
| `bin/paseo-self` | 239 | DELETE (E4) | DELETE |  |  | - | 1 | Replace by PASEO_AGENT_ID per plan. |
| `bin/paseo-set-model` | 89 | DELETE (E4) | DECIDE ≠ |  |  | - | 4 | Plan expects the audit to find nothing live; route_agent.py substrate (a KEEP file) needs it. Port or drop 'substrate' first. |
| `bin/paseo-set-model.mjs` | 150 | DELETE (E4) | DECIDE ≠ |  |  | - | 1 | Follows paseo-set-model. |
| `bin/pi-skill-dedup` | 427 | DELETE (E9) | DELETE |  |  | - | 1 | Goes with pi, which folds into omp. |
| `bin/post-edit-check` | 296 | UNLISTED (none) | KEEP |  |  | survives (3/3 keep) | 1 | Not in inventory section A. |
| `bin/pr-policy` | 515 | KEEP (E5) | KEEP |  |  | survives (3/3 keep) | 2 | Run 'pr-policy uninstall' before moving. |
| `bin/pr-wait` | 2320 | REPLACE (E8, D10) | REPLACE |  |  | - | 5 |  |
| `bin/proc-cpu-watch` | 394 | DELETE (E5, D5) | DELETE |  |  | - | 1 | Delete plist with it (not in E5's plist list, which names rumination-watch, session-history-update, context-budget, routing-recalibrate). |
| `bin/pytest` | 47 | UNLISTED (none) | KEEP | KEEP (ruling 1) |  | **REFUTED** (0/3 keep) | 4 |  |
| `bin/render-secret-deny` | 290 | UNLISTED (none) | KEEP |  |  | survives (3/3 keep) | 3 | B8d: tied to agents/claude/settings.json.tmpl path; E11 keeps docs/secret-deny.md. |
| `bin/route_agent.py` | 2798 | KEEP (E7, D5) | KEEP |  |  | survives (3/3 keep) | 10 | Trim jev, paseo-set-model substrate, go_model_policy references in the same slice as their deletions. |
| `bin/route_agent.py:133 (path .../tools/acp-run/acp-run) and :39,43 docs` | 2798 | KEEP (E7) | KEEP |  |  | **REFUTED** (0/3 keep) | 1 | Registry switch removes this caller. |
| `bin/routing-recalibrate` | 181 | DELETE (E7, E5, D8) | DELETE |  |  | - | 2 | May return as a Paseo schedule. |
| `bin/rumination-watch` | 2188 | DELETE (E5) | DELETE |  |  | - | 4 |  |
| `bin/rumination-watch (mentions relay.py :26, fleet.py :272; plist)` | 2188 | DELETE (E5) | DELETE |  |  | - | 2 | None. |
| `bin/seat-name` | 308 | DELETE (E2) | DELETE |  |  | - | 0 | AGENTS.md retirement box lists it as live until the D4/D6 drain. |
| `bin/self-slash` | 1471 | DELETE (E4, C3) | DELETE |  |  | - | 11 | context_size_nudge.py hook text must change first. |
| `bin/self-slash:801 (loads relay.py via python) and :72, :95, :346 (acp-run)` | 1471 | DELETE (E4) | DELETE |  |  | - | 3 | prompt_line.py (190 lines) is shared by relay.py and self-slash; goes with them. |
| `bin/session-load-watch` | 100 | DELETE (E5, D5) | DELETE |  |  | - | 3 |  |
| `bin/session-load-watch:21 (RELAY = .../session-finder/relay.py)` | 100 | DELETE (E5) | DELETE |  |  | - | 1 | None. |
| `bin/skill-everywhere` | 308 | KEEP (E10, D7) | KEEP |  |  | survives (3/3 keep) | 4 | E1 adds the site-djbclark root; E10 trims targets. |
| `bin/skill-get` | 135 | DELETE (E10, D7) | DELETE |  |  | - | 0 |  |
| `bin/skillopt-night` | 1043 | DELETE (E10, J4) | DELETE |  |  | - | 4 | Plan E5 says plist is E10's. |
| `bin/skillopt-night, bin/claude-quota-guard:195, bin/agy-linux:22, bin/coding-bot, bin/self-slash (a…` |  | DELETE (E10, E7, E9, E6, E4) | DELETE |  |  | - | 1 | Only skillopt-night is a functional caller; the others are text. |
| `bin/skillopt_sources.py` | 1033 | DELETE (E10) | DELETE |  |  | - | 3 | crush.py adapter is session-finder (E3). |
| `bin/wait-file` | 63 | KEEP (E5) | KEEP |  |  | survives (3/3 keep) | 0 |  |
| `bin/watch` | 1067 | DELETE (E5, C1) | DELETE |  |  | - | 4 | Gate: C3 per-file gate; fleet-watch home unverified. |
| `bin/web-digest` | 267 | DECIDE (E9) | DECIDE |  |  | - | 1 | Docstring of web-digest-mcp scopes it to Crush on small-context models (crush retires). |
| `bin/web-digest-mcp` | 96 | UNLISTED (E9 (web-digest*)) | DELETE | DECIDE with web-digest (ruling 13) |  | - | 0 | Crush is on the E9 retire list; the glob 'web-digest*' covers it. |
| `bin/web-get` | 1765 | DECIDE (E9) | DECIDE |  |  | - | 6 | skills/research is KEEP only after a 1-hour port (E6). |
| `bin/zcode-key-auth` | 150 | DELETE (E9 (E5)) | DELETE |  |  | - | 3 | Plan E5 and E9 both list the plist; E9 owns it. |

### D.skills (79 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `skills/_shared` | 99 | UNLISTED (none (E1 deletes siyuan* only)) | DELETE |  |  | - | 4 | Goes in the same slice as the four siyuan* dirs; E1 should name it. |
| `skills/ade-paseo` | 181 | UNLISTED (none) | KEEP | REPLACE, Wave 3 E10 (R2-2) |  | **REFUTED** (0/3 keep) | 4 | Paseo is the only harness, so the six ade-paseo* skills are the core that survives. |
| `skills/ade-paseo-advisor` | 63 | UNLISTED (none) | KEEP |  |  | survives (2/3 keep) | 1 | Description text mentions 'acp-run/dialogue' as the non-Paseo alternative; reword when E6 shims acp-run. |
| `skills/ade-paseo-committee` | 46 | UNLISTED (none) | KEEP |  |  | survives (2/3 keep) | 1 | Reword the dialogue/acp-run pointer in E6. |
| `skills/ade-paseo-handoff` | 142 | UNLISTED (none (E3/E4 do not name it)) | KEEP |  |  | survives (2/3 keep) | 3 | Plan gap: E3 must rewrite this skill's relay.py steps for the shim (send + read exit status) in the same slice, or the Paseo-only handoff s… |
| `skills/ade-paseo-help` | 92 | UNLISTED (none) | KEEP |  |  | survives (3/3 keep) | 1 |  |
| `skills/ade-paseo-plugin` | 735 | UNLISTED (none) | KEEP |  |  | **REFUTED** (1/3 keep) | 1 |  |
| `skills/ade-update` | 50 | KEEP (E10, D7) | KEEP |  |  | survives (3/3 keep) | 4 | Edit the skills-everywhere reference in E10. |
| `skills/autorename` | 3021 | DELETE (E4 (after C3 gate), C3, B10) | DELETE |  |  | - | 8 | Plan gap: the autorename_nudge.py hook line is missing from C2's list of operator-edited hook lines. pi-bridge.ts and omp-bridge.ts only ma… |
| `skills/autorename/autorename.py:95,123-125 (import claude_identity)` | 1177 | DELETE (E4) | DELETE ≠ |  |  | - | 1 | If the claude_identity move to bin/ precedes E4, autorename's sys.path import breaks until E4 lands. |
| `skills/aws-rules` | 108 | MOVE (E1, J2a) | MOVE |  | site-djbclark | - | 2 | J2a question: public or private site-djbclark. |
| `skills/barnowl` | 1112 | MOVE (E1, J2a) | MOVE |  | site-djbclark | - | 3 | Move the test and fixtures with it. |
| `skills/baton` | 129 | REPLACE (D3, E3 (claude_identity path …) | REPLACE |  |  | - | 7 | Do not delete until the plugin is live on the Mac; the Tier 1 resume reader is what the operator reads. |
| `skills/bigteam` | 1065 | DELETE (E6, D6, E9 (merge-ready line)) | DELETE |  |  | - | 5 | Plan says a one-page replacement skill is written; claude/agents/adversary.md:13 comment cites the file. |
| `skills/book-to-kb` | 148 | MOVE (E1, J2a) | MOVE |  | site-djbclark | - | 2 |  |
| `skills/bottom-config` | 373 | MOVE (E1) | MOVE |  | site-djbclark | - | 2 |  |
| `skills/btww` | 52 | DELETE (retired providers only) (E4) | KEEP ≠ |  |  | survives (3/3 keep) | 4 | Trim the retired-TUI rows rather than delete; the plan's own wording says retired providers only. |
| `skills/cfenginewatch` | 108 | DELETE (E5 (after C3 gate), C3, I4b) | DELETE |  |  | - | 3 | C1: the paused fleet-watch registration depends on bin/watch. |
| `skills/coderabbit-feeder` | 111 | MOVE (E1) | MOVE |  | site-djbclark | - | 4 |  |
| `skills/cow-workspaces` | 132 | DELETE (E2) | DELETE |  |  | - | 4 | Exempt from the zero-reference rule until E11 because of AGENTS.md. |
| `skills/create-hook` | 396 | DELETE (E9) | KEEP ≠ |  |  | survives (3/3 keep) | 3 | E9 lists it as a retired-provider skill but it belongs to a surviving provider. Delete only if Codex retires. |
| `skills/dialogue` | 2901 | DECIDE (E6 (KEEP only if it runs with…) | DECIDE | DECIDE E6 port (R2-16) |  | - | 4 | One headless-route seam (dialogue.py:751) is the whole port; 1390-line script untested. |
| `skills/dialogue/scripts/dialogue.py:751 (subprocess ["acp-run", ...]) and skills/research, skills/l…` | 1390 | DECIDE (E6, E2) | DECIDE | DECIDE E6 port (R2-16) |  | - | 1 | skills/loose is unlisted in the plan's E text for this area. |
| `skills/diskfree` | 1127 | MOVE (E1) | MOVE |  | site-djbclark | - | 2 | Move tests/test_bigteam_prune.py with it, or delete both. |
| `skills/effort-routing` | 168 | REPLACE (E7 (folds into model-routing)) | DELETE | REPLACE fold into model-routing (E7, R2-10) |  | - | 4 | After the fold, drop the skillOverrides entry too. |
| `skills/fallback-chains` | 946 | REPLACE (E7 (folds into model-routing)…) | DECIDE ≠ | REPLACE fold into model-routing; web half with web-get (E7,… |  | - | 4 | The model-chain half folds; the web-access half follows web-get's fate (E9). |
| `skills/firecrawl` | 585 | MOVE (E1, E9 (web-get/firecrawl-rou…) | MOVE |  | site-djbclark | - | 4 |  |
| `skills/forgejo` |  | MOVE (E1 (unlink)) | DELETE | UNLINK (E1) | site-djbclark | - | 1 | Unlink; the real skill lives in sipb-agent-skills. Operator relinks via the third skill-everywhere root. |
| `skills/forgejo-ci` |  | MOVE (E1 (unlink)) | DELETE | UNLINK (E1) | site-djbclark | - | 2 | The load-watch:538 docstring will name an unlinked path; reword in E5. |
| `skills/gmail-search` | 60 | MOVE (E1) | MOVE |  | site-djbclark | - | 2 |  |
| `skills/graft` | 164 | KEEP (E10, E11 (graft build last)) | KEEP |  |  | survives (3/3 keep) | 4 |  |
| `skills/greptile` | 198 | MOVE (E1) | MOVE |  | site-djbclark | - | 2 |  |
| `skills/hand` | 27 | DELETE (retired providers only) (E4, C2 (four hand links)) | DECIDE ≠ |  |  | - | 7 | Its purpose is omp's collision, so it stands or falls with omp in the Wave 1 pool audit; for Claude, Codex and Cursor it adds nothing. |
| `skills/handoff` | 480 | REPLACE (D3 (live-agent case), E3, E4) | KEEP |  |  | survives (3/3 keep) | 6 | The Tier 2 document half has no replacement in D3; keep and trim the self-slash/launch/herdr steps. E3 and E4 must list this file. |
| `skills/handoff/SKILL.md:90 and skills/baton/SKILL.md:90 (claude_identity.py path calls)` |  | KEEP (E3 (path callers), D3) | KEEP |  |  | survives (3/3 keep) | 1 | PLAN E3 also names session-handoff/SKILL.md:137-148,170,185. |
| `skills/helm` | 1700 | REPLACE (E4, D2) | REPLACE |  |  | - | 7 | Delete only after native paseo permit / asks / questions-please is live (D2). |
| `skills/helm/helm.py:57 (import fleet) and skills/helm/lead.md:20,22` | 839 | REPLACE (E4, D2) | REPLACE ≠ |  |  | - | 2 | E3's import search missed helm.py; helm is deleted in E4, so fleet.py cannot go before E4. |
| `skills/hyades-docker` |  | MOVE (E1 (unlink)) | DELETE | UNLINK (E1) | site-djbclark | - | 2 | Unlink. |
| `skills/jevlike` |  | DELETE (E2) | DELETE | UNLINK (E2) |  | - | 0 | Unlink only; the target repo keeps the skill. |
| `skills/loadwatch` | 226 | DELETE (E5, D5) | DECIDE ≠ | DELETE (E5, R2-11) |  | - | 6 | D5 keeps load-watch's find-and-tell, whose messages tell the receiving agent to read this skill. Delete it only with a load-watch reword (o… |
| `skills/loose` | 328 | UNLISTED (none) | KEEP |  |  | survives (3/3 keep) | 2 | Needs the self-slash and herdr text trimmed when E4 lands. |
| `skills/model-routing` | 1031 | KEEP (E7, G (rewritten)) | KEEP |  |  | survives (3/3 keep) | 5 | route_agent.py policy output (line 541) is generated from POLICY_PATH, not parsed from this SKILL.md. |
| `skills/oc-go-key` | 397 | DELETE (E9 (opencode), J2 audit) | DECIDE ≠ |  |  | - | 1 | Hinges on the J2 pool audit; the test goes with it. |
| `skills/ovhcloud-api` | 924 | MOVE (E1, J2a) | MOVE |  | site-djbclark | - | 2 | Secrets scan before the move (E1). |
| `skills/paseo-screen` | 106 | UNLISTED (none) | KEEP |  |  | survives (3/3 keep) | 3 |  |
| `skills/paseowatch` | 81 | DELETE (E5 (after C3 gate), I4c) | DELETE |  |  | - | 3 |  |
| `skills/peer-relay` | 118 | DELETE (E3 (after import and path sea…) | DELETE |  |  | - | 4 | Goes after the shim; ade-paseo-handoff and helm/lead.md must stop citing it first. |
| `skills/ralph-tui-orchestration` | 274 | DELETE (E2) | DELETE |  |  | - | 3 | Remove the five ralph-tui-* skillOverrides lines from the template. |
| `skills/report` | 364 | MOVE (E1) | MOVE |  | site-djbclark | - | 3 | dialogue and research resolve it by name, so the site-djbclark root must be linked first. |
| `skills/research` | 1269 | DECIDE (E6 (KEEP only if it runs with…) | DECIDE | DECIDE E6 port (R2-16) |  | - | 3 | The checker script is portable; only SKILL.md text drives acp-run. |
| `skills/retro` | 24 | UNLISTED (none (also absent from invent…) | KEEP |  |  | survives (3/3 keep) | 3 | Added 2026-11-06 19:52 locally; check it is committed on the branch. |
| `skills/session-finder` | 11490 | SHIM (E3, D1, B2, I3) | SHIM |  |  | - | 13 | deadline's flag set must be preserved; the shim must also cover the flags ade-paseo-handoff uses (--expect-ack, --pending, --sweep, --trans… |
| `skills/session-finder/claude_identity.py` | 146 | KEEP (E3 (moves to bin/, stub for o…) | MOVE |  | bin/ | survives (3/3 keep) | 6 | Row for the sub-path because the plan splits it from the directory. nativeid.py (49 lines) has no importer outside session-finder; move onl… |
| `skills/session-finder/fleet.py` | 1970 | KEEP (E3, E5 (until load-watch and …) | KEEP | SHIM until E5 (R2-7) |  | **REFUTED** (0/3 keep) | 9 | Deleting early breaks the runaway-load response; E5 must land first. |
| `skills/session-finder/launch.py:63 (import fleet) and :65 ACP_RUN` | 1105 | DELETE (E3) | DELETE |  |  | - | 2 | In-repo callers of launch.py to check before deletion: helm and self-slash (not rechecked here). |
| `skills/session-finder/nativeid.py` | 49 | MOVE (E3) | DECIDE |  | ? | - | 1 | No KEEP-code caller found; goes with session-find.py unless claude_identity imports it (not rechecked). |
| `skills/session-finder/relay.py` | 4901 | REPLACE (E3, D1) | SHIM |  |  | - | 14 | Most shared dependency (I3). Hung or timed out for four agents. |
| `skills/session-finder/relay.py caller: bin/deadline:456` | 1583 | REPLACE (E3, D1) | SHIM |  |  | - | 1 | Shim flag set is fixed by this call. |
| `skills/session-finder/relay.py callers by path in skills: helm/lead.md:22, session-handoff/SKILL.md…` |  | REPLACE (E3, E4, E5) | SHIM ≠ |  |  | - | 8 | ade-paseo-handoff uses --transfer-expectations/--pending/--sweep/--expect-ack, outside the three-flag shim set in E3. |
| `skills/session-finder/session-find.py:29-30,193,215 (from nativeid import ...; import claude_identi…` | 308 | UNLISTED (none (E3 names session-finder…) | DECIDE |  |  | - | 3 | E3 does not name session-find.py; if claude_identity/fleet move or go it breaks. |
| `skills/session-handoff` | 370 | KEEP (D3, E3, C3) | KEEP |  |  | survives (3/3 keep) | 5 |  |
| `skills/session-handoff/SKILL.md:137-148,170,185 (fleet.py --json; relay.py by absolute path)` |  | KEEP (E3, D3) | KEEP |  |  | **REFUTED** (0/3 keep) | 3 | Needs a Paseo-based replacement for fleet.py --json before fleet.py goes. |
| `skills/setup-modern-cli` | 445 | MOVE (E1) | MOVE |  | site-djbclark | - | 3 | Move the .gnu-tools-check-ignore line with it. |
| `skills/sipb-llm-bench` |  | MOVE (E1 (unlink)) | DELETE | UNLINK (E1) | site-djbclark | - | 1 | Unlink. |
| `skills/siyuan` | 1361 | DELETE (E1) | DELETE |  |  | - | 3 | Four siyuan* skillOverrides lines to drop from the template. |
| `skills/siyuan-article-import` | 1475 | DELETE (E1 (siyuan*)) | DELETE |  |  | - | 2 | Covered by the siyuan* glob. |
| `skills/siyuan-excalidraw` | 784 | DELETE (E1 (siyuan*)) | DELETE |  |  | - | 2 |  |
| `skills/siyuan-markdown` | 611 | DELETE (E1 (siyuan*)) | DELETE |  |  | - | 1 |  |
| `skills/skillopt-sleep` | 126 | DELETE (E10, J4) | DELETE |  |  | - | 6 | Delete with its wrapper, tests, plist and .gitignore line. |
| `skills/skillopt-sleep-learned` | 31 | DELETE (E2, J4) | DELETE |  |  | - | 2 | E2 and E10 both delete skillopt-sleep material; one slice each. |
| `skills/skills-everywhere` | 111 | DELETE (E10) | DELETE |  |  | - | 2 |  |
| `skills/steps` | 277 | UNLISTED (none) | KEEP |  |  | survives (3/3 keep) | 3 |  |
| `skills/sudo-secretspec` |  | MOVE (E1 (unlink)) | DELETE | UNLINK (E1) | site-djbclark | - | 3 | Unlink; threat-model.md:29 needs a pointer to the new location. |
| `skills/teach` | 265 | MOVE (E1) | MOVE |  | site-djbclark | - | 2 | E1 does not name the wrapper; move or delete it with the skill. |
| `skills/tell-chief-of-staff` | 40 | MOVE (E1 (Grok-bot skills) vs E6 (p…) | DECIDE ≠ |  | site-djbclark | - | 1 | The plan contradicts itself between E1 and E6; the operator picks one. |
| `skills/tell-coding-bot` | 85 | KEEP (E1, E6, E9j, J2a) | KEEP |  |  | survives (3/3 keep) | 3 | Repoint lines 8, 51 and 61 when the code moves to peer-link's repo. |
| `skills/terminus-kira` | 120 | MOVE (E1) | MOVE |  | site-djbclark | - | 1 |  |
| `skills/todo` | 121 | MOVE (E1) | MOVE |  | site-djbclark | - | 1 | 'todo' is a common word, so bin/ hits (ade_claims.py, load-watch) are noise. |
| `skills/watch` | 133 | DELETE (E5 (after C3 gate), C1) | DELETE |  |  | - | 3 | Goes with bin/watch, after load-watch's loadwatch pointer is reworded. |

### D.claude (25 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `claude/commands/helm-all.md` | 9 | UNLISTED (none (E4 REPLACE for helm and…) | REPLACE |  |  | - | 2 | E4 names the command in prose, not the file. |
| `claude/commands/paseo-screen.md` | 8 | UNLISTED (none) | KEEP | DELETE (E10, R2-2) |  | **REFUTED** (1/3 keep) | 1 |  |
| `claude/commands/resume.md` | 9 | UNLISTED (none (follows baton, D3)) | REPLACE |  |  | - | 1 | Goes with baton, not before. |
| `claude/commands/retro.md` | 11 | UNLISTED (none) | KEEP | DELETE (E10, R2-2) |  | survives (2/3 keep) | 1 |  |
| `claude/commands/session-finder-all.md` | 10 | UNLISTED (none (follows E3)) | DELETE |  |  | - | 1 | Section 1.6 goes with E3's non-Paseo routes. |
| `claude/commands/skillopt-sleep.md` | 9 | UNLISTED (none (follows E10 DELETE)) | DELETE | DELETE (E10, J4) |  | - | 1 |  |
| `claude/commands/steps.md` | 16 | UNLISTED (none) | KEEP | DELETE (E10, R2-2) |  | survives (2/3 keep) | 1 |  |
| `claude/commands/teach.md` | 14 | UNLISTED (none (follows E1 MOVE of teac…) | MOVE | MOVE site-djbclark (E1) | site-djbclark | - | 1 |  |
| `claude/hooks/agent_footer_gate.py` | 94 | UNLISTED (none) | KEEP |  |  | survives (3/3 keep) | 1 | If E6's shim drops `acp-dispatch footer`, this hook breaks. |
| `claude/hooks/bash_habits_gate.py` | 379 | UNLISTED (none) | KEEP |  |  | survives (3/3 keep) | 2 |  |
| `claude/hooks/bg_test_gate.py` | 99 | UNLISTED (none) | KEEP |  |  | survives (3/3 keep) | 3 |  |
| `claude/hooks/context_size_nudge.py` | 933 | UNLISTED (none (D4: context-watch KEEP)) | KEEP |  |  | survives (3/3 keep) | 5 | Two copies of its test, in tests/ and handoff-tools/tests/. |
| `claude/hooks/cswap_quota_context.sh` | 133 | UNLISTED (none (D4 touches quota displa…) | DECIDE | DECIDE after session-guard verified (R2-18) |  | - | 1 | Decide with D4 (session-guard/usage-auto-resume). |
| `claude/hooks/frontier_agent_gate.py` | 234 | UNLISTED (none (E7 keeps the frontier h…) | KEEP |  |  | survives (3/3 keep) | 3 | Not in C2's hook list but a missing target blocks every Agent/Task call; E7's ade_gates trim must keep what it imports. |
| `claude/hooks/graft_grep_nudge.py` | 58 | UNLISTED (none (graft KEEP, E10)) | KEEP |  |  | survives (3/3 keep) | 1 |  |
| `claude/hooks/graft_mcp_alwaysload.py` | 36 | UNLISTED (none) | DELETE |  |  | - | 0 | Dead file. |
| `claude/hooks/handoff-tools` | 1960 | KEEP (D3, C3 (session_log.py)) | KEEP |  |  | survives (3/3 keep) | 5 | The two context_size_nudge tests are dupes of tests/test_context_size_nudge.py. |
| `claude/hooks/jev_effort_hook.py` | 120 | DELETE (E2, C2) | DELETE |  |  | - | 2 | Template line 618 must go in the same slice. |
| `claude/hooks/precompact_handoff.py` | 190 | UNLISTED (none (D3 keeps the Tier 1 for…) | KEEP |  |  | survives (3/3 keep) | 3 |  |
| `claude/hooks/prior_art_nudge.py` | 1251 | DELETE (E10, J4, C2) | DELETE |  |  | - | 1 | C2 says two hook lines; the template wires it at three places. tests/test_hook_deadline_timeouts.py also uses quota_nudge, so edit rather t… |
| `claude/hooks/quota_nudge.py` | 275 | DECIDE (D4, C2) | DECIDE | DECIDE after session-guard verified (R2-18) |  | - | 4 | Goes with the Claude-quota half (E7). |
| `claude/hooks/relay_prose_nudge.py` | 335 | DELETE (E3 (relay.py routes and hooks…) | DELETE |  |  | - | 2 | Plan gap: C2 omits this hook line from the operator's pre-merge edit list. |
| `claude/hooks/relay_prose_nudge.py (copies URL_RE/asks_for_reply from relay.py, :101)` | 335 | DELETE (E3) | DELETE |  |  | - | 1 | Text coupling only; no import. |
| `claude/hooks/rtk_hook.py` | 37 | UNLISTED (none) | KEEP |  |  | survives (3/3 keep) | 1 |  |
| `claude/hooks/secret_read_gate.py` | 1243 | UNLISTED (none (PR 289)) | KEEP |  |  | survives (3/3 keep) | 3 |  |

### D.libexec (3 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `libexec/agent-bin/git` |  | KEEP (E8, D9) | KEEP |  |  | survives (3/3 keep) | 1 | Symlink target changes if ade-git-guard moves. |
| `libexec/git-hooks/pre-push` | 43 | KEEP (E8, D9) | KEEP |  |  | survives (3/3 keep) | 2 | Trim ACP_RUN_AGENT/OMPCODE tests with acp-run and omp. |
| `libexec/git-hooks/reference-transaction` | 52 | KEEP (E8, D9) | KEEP |  |  | survives (3/3 keep) | 2 |  |

### D.tools (3 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `tools/acp-run/ (acp-run 5169 lines, README.md, zcode-denylist-shim.cjs)` | 5169 | DELETE (E6, D6) | SHIM |  |  | - | 8 | Disposition SHIM then delete; four per-file C3 gates. |
| `tools/acp-run/acp-run` | 5169 | SHIM (E6, D6) | SHIM |  |  | - | 14 | Stays as launch interface until each C3 file is migrated or waived; goes in the follow-up PR. |
| `tools/acp-run/zcode-denylist-shim.cjs` | 73 | UNLISTED (none (E9 zcode)) | DELETE |  |  | - | 1 | Trim with acp-run's dead adapters before the shim follow-up. |

### D.plugins (1 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `plugins/herdr-sleeper` | 4399 | DELETE (E2, D14, C2, C7) | DELETE |  |  | - | 5 | AGENTS.md says it stays until the D4/D6 drain; the delete is gated on C7 output in docs/slim/log.md. |

### D.config (14 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `config/context-budget.toml` | 23 | KEEP (E5, J3) | KEEP |  |  | survives (3/3 keep) | 1 |  |
| `config/gates.toml` | 155 | KEEP (E7 (frontier half)) | KEEP |  |  | survives (3/3 keep) | 5 | trim to [frontier] |
| `config/go-model-policy.json` | 15 | DELETE (E7, J2 (go_model_policy.py on…) | DELETE | SHIM (ruling 5) |  | - | 4 | route_agent.py references must go in the same slice |
| `config/launchd/com.djbclark.deadline-sweep.plist` | 24 | KEEP (E5, C1) | KEEP |  |  | survives (3/3 keep) | 2 |  |
| `config/launchd/com.djbclark.pr-policy.plist` | 26 | KEEP (E5, C1) | KEEP |  |  | survives (3/3 keep) | 2 |  |
| `config/launchd/com.djbclark.quota-surplus.plist and oc-go-key drain plist (templates, not loaded)` |  | DECIDE (E7 (PR 270 PARKED), B11b) | DELETE |  |  | - | 0 | Not present on this branch; lives in PR 270 (and the oc-go-key skill is E9's). |
| `config/launchd/dev.herdr.server.plist` | 18 | UNLISTED (none (AGENTS.md retirement bo…) | KEEP | DECIDE at C7 (ruling 6) |  | survives (3/3 keep) | 4 | DELETE at D6 with herdr-server-run and the REFUSE entry |
| `config/launchd/dev.herdr.server.plist -> ~/Library/LaunchAgents/dev.herdr.server.plist` | 28 | KEEP (AGENTS.md retirement box; E2 …) | DECIDE ≠ |  |  | survives (3/3 keep) | 2 | PLAN E names neither file; AGENTS.md says they stay. DECIDE at the D4/D6 drain. |
| `config/pr-policy.toml` | 22 | KEEP (E5) | KEEP |  |  | survives (3/3 keep) | 2 |  |
| `config/routing.toml` | 551 | KEEP (E7) | KEEP |  |  | survives (3/3 keep) | 3 | trim retired providers |
| `config/secret-deny.toml` | 76 | KEEP (E11 (secret-deny.md, PR 289)) | KEEP |  |  | survives (3/3 keep) | 2 | plan_disposition inferred from E11 keeping secret-deny.md |
| `config/secret_deny_policy.json` | 51 | KEEP (E11 (secret-deny.md, PR 289)) | KEEP |  |  | survives (3/3 keep) | 2 |  |
| `config/sudoers.d/acp-dispatch-pmset` | 3 | DELETE (E6 (auto-resume jobs go)) | DELETE |  |  | - | 2 | plan does not name the file; inferred from E6 |
| `config/watch.toml` | 66 | DELETE (E5 (bin/watch, skills/watch)) | DELETE |  |  | - | 4 | plan does not name the file; follows bin/watch |

### D.launchd (9 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `launchd/com.djbclark.acp-dispatch-reap.plist` | 31 | DELETE (E6) | DELETE |  |  | - | 3 | goes with acp-dispatch shim |
| `launchd/com.djbclark.context-budget.plist` | 33 | DELETE (E5, J3) | DELETE | REPLACE Paseo schedule (J3, R2-5) |  | - | 2 | test must drop the install/uninstall cases |
| `launchd/com.djbclark.load-watch.plist` | 28 | KEEP (E5, C1) | KEEP |  |  | survives (3/3 keep) | 2 |  |
| `launchd/com.djbclark.proc-cpu-watch.plist` | 28 | DELETE (E5 (proc-cpu-watch)) | DELETE |  |  | - | 3 | plist not named by PLAN; follows E5's DELETE of proc-cpu-watch; SUBST keys in the test can be trimmed |
| `launchd/com.djbclark.routing-recalibrate.plist` | 33 | DELETE (E5 line, E7) | DELETE |  |  | - | 2 | PLAN lists it in E5's plist set and in E7: one deleting slice must be chosen |
| `launchd/com.djbclark.rumination-watch.plist` | 48 | DELETE (E5) | DELETE |  |  | - | 3 | check relay.py/self-slash references before delete |
| `launchd/com.djbclark.session-history-update.plist` | 35 | DELETE (E5 plist list) | DELETE | DELETE (E5, R2-4) |  | - | 2 | flag: plan deletes the plist but is silent on session-history.py |
| `launchd/com.djbclark.skillopt-sleep.plist` | 31 | DELETE (E10, J4) | DELETE |  |  | - | 1 |  |
| `launchd/com.djbclark.zcode-key-auth.plist` | 30 | DELETE (E9) | DELETE |  |  | - | 1 |  |

### D.agents (5 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `agents/README.md` | 130 | UNLISTED (none) | KEEP |  |  | survives (3/3 keep) | 4 |  |
| `agents/claude/settings.json.tmpl` | 761 | UNLISTED (none (E9 covers templates of …) | KEEP |  |  | survives (3/3 keep) | 5 | Plan gap: no E slice owns trimming this template; E11 touches only .claude/settings.json. |
| `agents/codex/config.toml.tmpl` | 385 | KEEP (E9 (surviving providers keep …) | KEEP |  |  | survives (3/3 keep) | 4 | E9's helper list and its keep-list disagree about codex-env-policy-apply. |
| `agents/hermes/config.yaml.tmpl` | 393 | KEEP (E9 (hermes survives)) | KEEP |  |  | survives (3/3 keep) | 3 |  |
| `agents/opencode/opencode.json.tmpl` | 114 | DELETE (E9 (opencode conditional), J2) | DECIDE |  |  | - | 2 | Hinges on the J2 audit; bin/ade-template-check's mapping table must change with it. |

### D.pi (2 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `pi/extensions/subagent` | 3436 | DELETE (E9 (pi retire), B8b, I4f) | DECIDE |  |  | - | 4 | Hinges on the J2 pool audit: pi retires, but the omp port is conditional on omp surviving. CI step goes with the dir. |
| `pi/prompts/hand.md` | 6 | DELETE (E9, E4, C2) | DECIDE |  |  | - | 2 | Pi retires in every plan scenario (folds into omp); DELETE is safe once the pi track is accepted. |

### D.omp (1 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `omp/commands` | 15 | DELETE (E9 (omp conditional), E4, C2) | DECIDE |  |  | - | 4 | omp survives only if a paid plan (Claude API-credit grant) is reachable solely through it (J2). |

### D.opencode (1 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `opencode/commands/hand.md` | 5 | DELETE (E9 (opencode conditional), C2) | DECIDE |  |  | - | 2 | Hinges on opencode surviving the J2 audit. |

### D.opencode-plugins (4 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `opencode-plugins/bg-cargo-gate.js` | 152 | DELETE (E9 (opencode conditional)) | DECIDE |  |  | - | 3 | Hinges on opencode; delete the .md and both tests with it. |
| `opencode-plugins/bg-cargo-gate.md` | 40 | DELETE (E9 (opencode conditional)) | DECIDE |  |  | - | 0 | Follows bg-cargo-gate.js. |
| `opencode-plugins/go-context` | 991 | DELETE (E9 (opencode conditional), E7…) | DECIDE |  |  | - | 4 | Trim the acp-run reference in the same step; go_model_policy.py and config/go-model-policy.json follow opencode (E7). |
| `opencode-plugins/rtk.ts` | 21 | DELETE (E9 (opencode conditional)) | DECIDE |  |  | - | 2 |  |

### D.zcode (1 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `zcode/commands` | 136 | DELETE (E9 (zcode retire; Q1 waits fo…) | DECIDE |  |  | - | 4 | Retires in every scenario unless opencode/zcode keep a paid plan; dangling wrappers either way once the skills go. |

### D.scripts (1 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `scripts/github-ci-run` | 171 | UNLISTED (none) | DECIDE | DECIDE E5 (R2-23) |  | - | 1 | no in-repo caller after E5; operator to say whether site-djbclark still uses it |

### D.vendor (3 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `vendor/README.md` | 49 | KEEP (E2 (vendor entries to retired…) | KEEP |  |  | - | 1 | trim rows for gate-scripts; helm pointer follows E4 |
| `vendor/gate-scripts` | 616 | DELETE (E2 (vendor/ entries pointing …) | DELETE |  |  | - | 4 | remove routing.toml rows at 539-547 in E7/E9 first |
| `vendor/hermes/claude-collaboration.SKILL.md` | 77 | UNLISTED (none) | KEEP |  |  | - | 2 | text may name acp-dispatch/relay: check at E3/E6 |

### D.bench (1 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `bench/firecrawl` | 1225 | MOVE (E1) | MOVE |  | site-djbclark | - | 1 | secrets scan before move (E1); result JSON may hold endpoints |

### D.tests (190 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `tests/conftest.py` | 115 | UNLISTED (none) | KEEP |  |  | - | 0 | Trim env pins as their subjects are deleted. |
| `tests/fixtures` | 30 | UNLISTED (none) | DECIDE |  |  | - | 0 | Each file follows its test: barnowl MOVE, context-now KEEP, fake-tool-calls with read_only REPLACE, rtk with the opencode DECIDE. |
| `tests/soak_plugin_herdr.sh` | 320 | UNLISTED (none) | DELETE |  |  | - | 0 | plugins/herdr-sleeper is deleted in E2 (D14). |
| `tests/test_acp_dispatch.py` | 1484 | DELETE (E6, D6) | SHIM ≠ |  |  | - | 0 | bin/acp-dispatch exit-code and record contract plus base harness. Shim keeps exit 3/4/77/124 and the report/.done record (E6); plan gives t… |
| `tests/test_acp_dispatch_auto_resume.py` | 630 | DELETE (E6, D6) | DELETE |  |  | - | 0 | acp-dispatch auto-resume launchd jobs; deleted with the C7 drain. |
| `tests/test_acp_dispatch_brief_footer.py` | 251 | DELETE (E6, D6) | SHIM ≠ |  |  | - | 0 | acp-dispatch brief footer on re-dispatched -f files; E6 says the shim keeps the brief footer. |
| `tests/test_acp_dispatch_classify.py` | 76 | DELETE (E6, D6) | SHIM ≠ |  |  | - | 0 | acp-dispatch report classification (DONE plus verdict line is done, not partial); decides the .done status the shim keeps (E6). |
| `tests/test_acp_dispatch_credit_refusal.py` | 323 | DELETE (E6, D6) | DELETE |  |  | - | 0 | acp-dispatch credit-balance classification for omp. |
| `tests/test_acp_dispatch_cursor_cloud.py` | 833 | DELETE (E6, E9) | DECIDE ≠ |  |  | - | 0 | acp-dispatch cursor-cloud route plus route_agent registration; cursor-cloud goes only 'if Cursor goes' (E9, J2). |
| `tests/test_acp_dispatch_effort.py` | 125 | DELETE (E6, D6) | DELETE |  |  | - | 0 | acp-dispatch --effort/--context. |
| `tests/test_acp_dispatch_frontier_reason.py` | 219 | DELETE (E6, E7) | DECIDE ≠ |  |  | - | 0 | acp-dispatch --kind frontier admission plus ade_gates frontier half; E6 shim keeps the admission check, E7 keeps the frontier half. |
| `tests/test_acp_dispatch_gate.py` | 55 | DELETE (E6, D6) | DELETE |  |  | - | 0 | old overload gate; the kept gate is load-watch admit (D5). |
| `tests/test_acp_dispatch_git_identity.py` | 51 | DELETE (E6, D6) | DELETE |  |  | - | 0 | acp-dispatch git-identity warning. |
| `tests/test_acp_dispatch_identity.py` | 236 | KEEP (E6) | KEEP |  |  | - | 0 | bin/agent_guard.py table vs acp-run agents. E6 and checkins B1d: agent_guard.py and this test stay; its helpers (run, LoadGate) must move w… |
| `tests/test_acp_dispatch_load_gate.py` | 957 | DELETE (E6, D5) | SHIM ≠ |  |  | - | 0 | acp-dispatch load-watch admit gate (exit 75), agent cap, reservation; E6 shim keeps the admit gate and the 14-agent cap. |
| `tests/test_acp_dispatch_outcome.py` | 59 | DELETE (E6, C4) | SHIM ≠ |  |  | - | 0 | acp-dispatch outcome writes the fields route_agent.py calibrate reads; E6 and C4 keep that record. |
| `tests/test_acp_dispatch_pool_map.py` | 57 | DELETE (E6, D6) | DELETE |  |  | - | 0 | acp-dispatch map_agent_to_provider. |
| `tests/test_acp_dispatch_quota_d2.py` | 764 | DELETE (E6, D6) | DELETE |  |  | - | 0 | acp-dispatch quota-stop handling and escalation. |
| `tests/test_acp_dispatch_reap.py` | 692 | DELETE (E6, D6) | DELETE |  |  | - | 0 | acp-dispatch reap and launchd/com.djbclark.acp-dispatch-reap.plist; both deleted in E6. |
| `tests/test_acp_dispatch_refused_resume.py` | 129 | DELETE (E6, D6) | DELETE |  |  | - | 0 | acp-dispatch resume. |
| `tests/test_acp_dispatch_routing.py` | 679 | DELETE (E6, E7) | DECIDE ≠ |  |  | - | 0 | acp-dispatch --kind eligibility, frontier advisor, estimate, reservation: mixes shim-kept frontier/reservation behaviour with deleted routi… |
| `tests/test_acp_dispatch_tell.py` | 237 | DELETE (E6, D6) | DELETE |  |  | - | 0 | acp-dispatch tell (inbox into a running slice); replaced by paseo send (D1). |
| `tests/test_acp_dispatch_transient_quota.py` | 158 | DELETE (E6, D6) | DELETE |  |  | - | 0 | acp-dispatch transient-as-quota classification. |
| `tests/test_acp_dispatch_waiter.py` | 289 | DELETE (E6, D6) | DELETE |  |  | - | 0 | bin/acp-dispatch-wait; deadline_wait.py is a separate KEEP. |
| `tests/test_acp_not_installed.py` | 355 | DELETE (E6, D6) | DELETE |  |  | - | 0 | acp-dispatch and acp-run not-installed preflight state. |
| `tests/test_acp_run_agy_server.py` | 85 | DELETE (E6, D6) | DELETE | SHIM (ruling 3) |  | - | 0 | acp-run ACP_RUN_AGY_SERVER override; agy retired by J2/E9, delete now. |
| `tests/test_acp_run_alias.py` | 62 | DELETE (E6, D6) | DELETE | SHIM (ruling 3) |  | - | 0 | acp-run family-alias model resolution; Wave 6 with acp-run. |
| `tests/test_acp_run_classify.py` | 75 | DELETE (E6, D6) | DELETE | SHIM (ruling 3) |  | - | 0 | acp-run FAILURE_CLASSES; Wave 6. |
| `tests/test_acp_run_crush.py` | 529 | DELETE (E6, D6) | DELETE | SHIM (ruling 3) |  | - | 0 | acp-run --perm deny for crush; crush retired (E9), delete now. |
| `tests/test_acp_run_deadline.py` | 198 | DELETE (E6, D6) | DELETE | SHIM (ruling 3) |  | - | 0 | acp-run deadline controls with a fake ACP connection; Wave 6. |
| `tests/test_acp_run_deny.py` | 319 | DELETE (E6, D6) | REPLACE ≠ | SHIM (ruling 3) |  | - | 0 | acp-run --perm deny boundary. E6 says the shim must reproduce this boundary with tests before it ships: port these assertions to the review… |
| `tests/test_acp_run_effort_context.py` | 614 | DELETE (E6, D6) | DELETE | SHIM (ruling 3) |  | - | 0 | acp-run effort/context/launch_tweaks per agent; Wave 6, dead-adapter cases trimmed earlier (E6). |
| `tests/test_acp_run_failure.py` | 188 | DELETE (E6, D6) | DELETE | SHIM (ruling 3) |  | - | 0 | acp-run reply_failure delivery checks; Wave 6. |
| `tests/test_acp_run_git_identity.py` | 463 | DELETE (E6, D6) | DECIDE ≠ | SHIM (ruling 3) |  | - | 0 | acp-run git-identity guard (reference-transaction hook via GIT_CONFIG_PARAMETERS); vanishes with acp-run unless ported; test_ade_git_hooks … |
| `tests/test_acp_run_go_installation.py` | 416 | DELETE (E6, E7, J2) | DECIDE ≠ | SHIM (ruling 3) |  | - | 0 | acp-run opencode Go-policy install; depends on the J2 opencode audit. |
| `tests/test_acp_run_grok_deny.py` | 423 | DELETE (E6, E9) | DECIDE ≠ | SHIM (ruling 3) |  | - | 0 | acp-run grok --perm deny: grok is on the keep list but J2 one-provider-per-plan may retire it; the zcode half is dead. |
| `tests/test_acp_run_kiro.py` | 85 | DELETE (E6, D6) | DELETE | SHIM (ruling 3) |  | - | 0 | acp-run kiro plus route_agent discovery; kiro-cli retired (E9). |
| `tests/test_acp_run_pi.py` | 30 | DELETE (E6, D6) | DELETE | SHIM (ruling 3) |  | - | 0 | acp-run pi table entries (AST check); pi retired (E9), delete now. |
| `tests/test_acp_run_race.py` | 312 | DELETE (E6, D6) | DELETE | SHIM (ruling 3) |  | - | 0 | acp-run end_turn/124 race and transient classes; Wave 6. |
| `tests/test_acp_run_read_only.py` | 274 | DELETE (E6, D6) | REPLACE ≠ | SHIM (ruling 3) |  | - | 0 | acp-run --perm read-only six-tool allowlist and tripwire; same boundary as test_acp_run_deny (E6, E8 review-launch). |
| `tests/test_acp_run_resume_hint.py` | 51 | DELETE (E6, D6) | DELETE | SHIM (ruling 3) |  | - | 0 | acp-run quota-stop resume hint; Wave 6. |
| `tests/test_acp_run_resume_order.py` | 227 | DELETE (E6, D6) | DELETE | SHIM (ruling 3) |  | - | 0 | acp-run resume/add_dir order; Wave 6. |
| `tests/test_acp_run_session_seed.py` | 181 | DELETE (E6, D6) | DELETE | SHIM (ruling 3) |  | - | 0 | acp-run --session-id seed and add_dir; Wave 6. |
| `tests/test_acp_run_strip.py` | 786 | DELETE (E6, D6) | DECIDE ≠ | SHIM (ruling 3) |  | - | 0 | acp-run --strip-user-config for opencode and agy: settings stripping is part of the E6 restricted-mode boundary but these cases cover openc… |
| `tests/test_acp_run_strip_perm_all.py` | 569 | DELETE (E6, D6) | DECIDE ≠ | SHIM (ruling 3) |  | - | 0 | acp-run --strip-user-config outside --perm deny: claude case is boundary-relevant, opencode/agy cases are not. |
| `tests/test_acp_run_verify.py` | 240 | DELETE (E6, D6) | DELETE | SHIM (ruling 3) |  | - | 0 | acp-run --verify loop (the AGENTS.md shell=True exception); Wave 6. |
| `tests/test_acp_run_wrapup.py` | 153 | DELETE (E6, D6) | DELETE | SHIM (ruling 3) |  | - | 0 | acp-run wrap-up turn after --timeout cancel; Wave 6. |
| `tests/test_acp_run_zcode_tools.py` | 195 | DELETE (E6, D6) | DELETE | SHIM (ruling 3) |  | - | 0 | acp-run zcode denylist shim; zcode retired (E9), delete now. |
| `tests/test_ade_backup_stores.py` | 2575 | KEEP (E10) | KEEP |  |  | - | 0 | bin/ade-backup-stores; KEEP trimmed to surviving stores (E10, E9h Q4), store rows for retired TUIs trim. |
| `tests/test_ade_claims_quote.py` | 29 | KEEP (E8, D9) | KEEP |  |  | - | 0 | bin/ade_claims.py. |
| `tests/test_ade_git_guard.py` | 1540 | KEEP (E8, D9) | KEEP |  |  | - | 0 | bin/ade-git-guard, bin/ade_claims.py, libexec/agent-bin/git shim; E8 adds a real claim ls (C5). |
| `tests/test_ade_git_hooks.py` | 935 | KEEP (E8, D9) | KEEP |  |  | - | 0 | libexec/git-hooks via ade-git-guard; the r11_f6 case (acp-run GIT_CONFIG pairs) changes when acp-run goes. |
| `tests/test_ade_retro.py` | 284 | UNLISTED (none) | KEEP |  |  | - | 0 | bin/ade-retro (PR 289); Wave 3/D8 decides whether it runs as a Paseo schedule. |
| `tests/test_ade_scan_state.py` | 5657 | DELETE (E2) | DELETE |  |  | - | 0 | bin/ade-scan-state and -doc; 5657 lines go with the tool (E2). |
| `tests/test_ade_sched.py` | 703 | KEEP (E5, D8) | KEEP |  |  | - | 0 | bin/ade_sched.py and ade-sched (PR 291); plist parametrisation shrinks as E5/E6/E9 delete plists. |
| `tests/test_ade_template_check.py` | 546 | UNLISTED (none) | KEEP |  |  | - | 1 | bin/ade-template-check over agents/ templates; E9 keeps surviving providers' templates, retired providers' fixtures trim. |
| `tests/test_ade_update.py` | 1366 | KEEP (E10) | KEEP |  |  | - | 0 | bin/ade-update, KEEP trimmed (E10). |
| `tests/test_agent_footer_gate.py` | 67 | UNLISTED (none) | DECIDE |  |  | - | 0 | Agent-tool delivery footer hook; the footer contract is acp-dispatch/bigteam's (E6 deletes bigteam), so keep-or-drop is a call. |
| `tests/test_argon_frontier.py` | 903 | DELETE (E6, E7) | DECIDE ≠ |  |  | - | 1 | acp-dispatch frontier gates plus KEEP route_agent/failover; bin/route_agent.py:2186 names this test. |
| `tests/test_autorename_claude_session_id.py` | 245 | DELETE (E4) | DELETE |  |  | - | 0 | skills/autorename; PR 259 stale-session-id fix (I5). E4 gate: C3 per-file gate. |
| `tests/test_autorename_paseo_herdr.py` | 65 | DELETE (E4) | DELETE |  |  | - | 0 | skills/autorename herdr label nudge; E4 C3 gate. |
| `tests/test_autorename_paseo_tab.py` | 210 | DELETE (E4) | DELETE |  |  | - | 0 | skills/autorename Paseo tab renaming; E4 C3 gate. |
| `tests/test_autorename_paseo_workspace.py` | 91 | DELETE (E4) | DELETE |  |  | - | 0 | skills/autorename workspace rename; E4 may keep a 20-line paseo workspace rename helper. |
| `tests/test_autorename_tab_label.py` | 92 | DELETE (E4) | DELETE |  |  | - | 1 | skills/autorename herdr tab label. |
| `tests/test_barnowl_skill.py` | 523 | MOVE (E1, J2a) | MOVE |  | site-djbclark | - | 0 | skills/barnowl; fixtures barnowl-1.10 and barnowl-master move with it. |
| `tests/test_bash_habits_gate.py` | 278 | UNLISTED (none) | KEEP |  |  | - | 0 | bash_habits_gate hook; no E slice touches it. |
| `tests/test_bg_cargo_gate.py` | 101 | DECIDE (E9, J2) | DECIDE |  |  | - | 0 | opencode-plugins/ goes only if opencode retires after the J2 audit. |
| `tests/test_bg_cargo_gate_native.py` | 80 | DECIDE (E9, J2) | DECIDE |  |  | - | 0 | opencode native permission proof; same condition as test_bg_cargo_gate. |
| `tests/test_bigteam_prune.py` | 1203 | DELETE (E6) | DELETE | MOVE site-djbclark (E1, R2-8) |  | - | 0 | bigteam prune script (bigteam deleted in E6); diskfree moves in E1. |
| `tests/test_bin_modes.py` | 45 | UNLISTED (none) | KEEP |  |  | - | 0 | every tracked file with a shebang is 100755; subject-agnostic. |
| `tests/test_bin_pytest.py` | 32 | UNLISTED (none) | KEEP |  |  | - | 1 | bin/pytest deps vs .github/workflows/test.yml; update if E6 drops agent-client-protocol from CI. |
| `tests/test_bm_lint.py` | 844 | KEEP (E10) | KEEP |  |  | - | 0 | bin/bm-lint. |
| `tests/test_change_hermes_auto.py` | 46 | MOVE (E1, J2a) | MOVE |  | site-djbclark | - | 0 | bin/change-hermes goes to site-djbclark (J2a answered). |
| `tests/test_change_hermes_lock.py` | 103 | MOVE (E1, J2a) | MOVE |  | site-djbclark | - | 0 | bin/change-hermes; moves with test_change_hermes_auto. |
| `tests/test_changelog_fold.py` | 212 | KEEP (E8) | KEEP |  |  | - | 0 | bin/changelog-fold. |
| `tests/test_claude_cost_mix.py` | 88 | KEEP (E7) | KEEP |  |  | - | 0 | bin/claude-cost-mix. |
| `tests/test_claude_fleet_governor.py` | 1359 | DELETE (E7, D4) | DELETE |  |  | - | 0 | bin/claude-fleet-governor; after session-guard/usage-auto-resume verified live and the C3 gate. |
| `tests/test_claude_identity.py` | 234 | KEEP (E3, E8) | KEEP |  |  | - | 0 | claude_identity.py (moves to bin/, E3) and ade_claims owner: fixes C5/I5. Its harness comes from two relay tests E3 deletes, so port the ha… |
| `tests/test_claude_quota_guard.py` | 2082 | REPLACE (E7, D4) | DECIDE ≠ |  |  | - | 0 | State-producing half of claude-quota-guard is KEEP until frontier consumers read paseo usage (E7); quota_nudge.py KEEP only if plugins cann… |
| `tests/test_claude_settings_env.py` | 75 | UNLISTED (none) | KEEP |  |  | - | 0 | bin/claude-settings-env. |
| `tests/test_codex_shell_env_policy.py` | 647 | DELETE (E9) | DECIDE ≠ | KEEP (ruling 9) |  | - | 1 | E9 lists codex-env-policy-apply under retired-provider helpers, yet codex is on E9's keep list; the file also covers acp-run and relay.py. |
| `tests/test_coding_bot.py` | 615 | MOVE (E6, E9j) | MOVE |  | peer-link | - | 0 | bin/coding-bot code moves to peer-link's repo; pointer skill stays. |
| `tests/test_context_budget_check.py` | 348 | KEEP (E5, J3) | KEEP |  |  | - | 0 | Becomes a Paseo schedule; install/uninstall subcommands go with the context-budget plist. |
| `tests/test_context_size_nudge.py` | 624 | UNLISTED (none) | KEEP |  |  | - | 0 | context_size_nudge hook; no E slice names it. |
| `tests/test_context_watch.py` | 434 | KEEP (E5, E3) | KEEP |  |  | - | 0 | bin/context-watch; rewritten to read paseo ls -a -g --json so fleet.py can go. |
| `tests/test_cow_pasture.py` | 32 | DELETE (E2) | DELETE |  |  | - | 0 | bin/cow-pasture replaced by Paseo worktrees. |
| `tests/test_cow_pasture_deps.py` | 226 | DELETE (E2) | DELETE |  |  | - | 0 | bin/cow-pasture. |
| `tests/test_cow_pasture_untrust.py` | 47 | DELETE (E2) | DELETE |  |  | - | 0 | bin/cow-pasture untrust. |
| `tests/test_crush_context_check.py` | 76 | DELETE (E9) | DELETE |  |  | - | 0 | crush retired. |
| `tests/test_cursor_cloud.py` | 465 | DECIDE (E9) | DECIDE |  |  | - | 0 | E9: cursor-cloud goes 'if Cursor goes'. |
| `tests/test_deadline.py` | 1236 | KEEP (E5) | KEEP |  |  | - | 0 | bin/deadline; independent of relay.py. Plist config/launchd/com.djbclark.deadline-sweep.plist. |
| `tests/test_deadline_wrappers.py` | 314 | KEEP (E5, E6, E8) | DECIDE ≠ |  |  | - | 0 | Three subjects: pr-wait REPLACE, acp-dispatch-wait DELETE, load-watch admit KEEP. |
| `tests/test_failover.py` | 1220 | KEEP (E7) | DECIDE ≠ | DELETE (E10, ruling 1) |  | - | 0 | E7 keeps only the model-chain half of failover.py; the acp route half is paseo run. |
| `tests/test_firecrawl_router.py` | 793 | DECIDE (E9) | DECIDE |  |  | - | 1 | bin/firecrawl-router: KEEP only while a small-context provider survives (E9); skill firecrawl moves in E1. |
| `tests/test_fleet_conflicts_self.py` | 15 | DELETE (E3) | DELETE | SHIM until E5 (R2-7) |  | - | 0 | fleet.py goes after E5 rewrites bin/load-watch:266 and bin/context-watch:74. |
| `tests/test_fleet_launch_state.py` | 108 | DELETE (E3, E4) | DELETE | SHIM until E5 (R2-7) |  | - | 0 | fleet.launch_state plus helm. |
| `tests/test_fleet_messaging.py` | 67 | DELETE (E3) | DELETE | SHIM until E5 (R2-7) |  | - | 0 | fleet.py messaging_warning. |
| `tests/test_fleet_orca_handle.py` | 203 | DELETE (E3) | DELETE | SHIM until E5 (R2-7) |  | - | 0 | fleet.py Orca handle; Orca retired 2026-10-31. |
| `tests/test_fleet_paseo_rows.py` | 356 | DELETE (E3, E4) | DELETE | SHIM until E5 (R2-7) |  | - | 0 | fleet.py Paseo rows plus helm; the Paseo-native read moves to paseo ls in E5. |
| `tests/test_fleet_pi.py` | 156 | DELETE (E3, E9) | DELETE | SHIM until E5 (R2-7) |  | - | 0 | fleet.py pi detection; pi retired. |
| `tests/test_fleet_tidy.py` | 308 | DELETE (E3, E4) | DELETE | SHIM until E5 (R2-7) |  | - | 0 | fleet.py and helm.py safe-close. |
| `tests/test_frontier_agent_gate.py` | 498 | UNLISTED (none) | KEEP |  |  | - | 0 | Frontier half of ade_gates is KEEP (E7); relocate close_frontier_baseline if test_gates is trimmed. |
| `tests/test_gates.py` | 1435 | REPLACE (E7, D4) | DECIDE ≠ |  |  | - | 0 | ade_gates Claude-quota half and gate-profile DELETE, frontier half KEEP, config/gates.toml shared. |
| `tests/test_git_commit_own.py` | 89 | KEEP (E8) | KEEP |  |  | - | 0 | bin/git-commit-own. |
| `tests/test_gnu_tools_check.py` | 137 | UNLISTED (none) | KEEP |  |  | - | 0 | bin/gnu-tools-check. |
| `tests/test_go_context_plugin.py` | 13 | DECIDE (E9, J2) | DECIDE |  |  | - | 1 | opencode-plugins/ deleted only if opencode retires. |
| `tests/test_go_model_policy.py` | 112 | DECIDE (E7, J2) | DECIDE | SHIM (ruling 5) |  | - | 1 | E7: DELETE 'once opencode is retired'. |
| `tests/test_helm_question_status.py` | 35 | REPLACE (E4, D2) | REPLACE |  |  | - | 0 | skills/helm/helm.py replaced by native paseo permit/inbox. |
| `tests/test_helm_send_unknown.py` | 391 | REPLACE (E4, D2) | REPLACE |  |  | - | 0 | skills/helm/helm.py send path. |
| `tests/test_herdr_server_run.py` | 39 | UNLISTED (none) | KEEP | DECIDE at C7 (ruling 6) |  | - | 0 | Stays for the installed server and the two bridges until the D4/D6 drain. |
| `tests/test_hook_deadline_timeouts.py` | 45 | UNLISTED (none) | KEEP |  |  | - | 0 | 6 or 7 of the 10 wrapped hooks belong to deleted subjects (prior_art_nudge x3, relay_prose_nudge, autorename_nudge, jev_effort_hook, maybe … |
| `tests/test_instruction_lint.py` | 212 | KEEP (D13) | KEEP |  |  | - | 1 | bin/instruction-lint (PR 289). |
| `tests/test_jev.py` | 320 | DELETE (E2) | DELETE |  |  | - | 0 | bin/jev and jev_effort_hook. |
| `tests/test_jev_eval.py` | 215 | DELETE (E2) | DELETE |  |  | - | 0 | bin/jev-eval. |
| `tests/test_launch_dispatch.py` | 192 | DELETE (E3) | DELETE |  |  | - | 0 | launch.py (--host retires in D6). |
| `tests/test_launch_model.py` | 100 | DELETE (E3) | DELETE |  |  | - | 0 | launch.py model handling. |
| `tests/test_launch_orca_close.py` | 153 | DELETE (E3) | DELETE |  |  | - | 0 | launch.py Orca close; Orca retired. |
| `tests/test_launch_successor.py` | 238 | DELETE (E3, E4) | DELETE |  |  | - | 0 | launch.py successor path. |
| `tests/test_launch_turns.py` | 303 | DELETE (E3) | DELETE |  |  | - | 0 | launch.py turns plus acp-dispatch. |
| `tests/test_load_watch.py` | 634 | KEEP (E5, D5) | KEEP |  |  | - | 0 | bin/load-watch; the relay-channel delivery tests re-point to paseo send (D5). |
| `tests/test_load_watch_admit.py` | 932 | KEEP (E5, D5) | KEEP |  |  | - | 0 | load-watch admit (exit 75). |
| `tests/test_load_watch_chrome_alert.py` | 80 | KEEP (E5, D5) | KEEP |  |  | - | 0 | load-watch chrome alert. |
| `tests/test_load_watch_churn.py` | 226 | KEEP (E5, D5) | KEEP |  |  | - | 0 | load-watch compressor-churn sample. |
| `tests/test_local_review.py` | 686 | REPLACE (E8, D10) | REPLACE |  |  | - | 0 | E8 requires every isolation check kept as tests for bin/review-launch before local-review is deleted. |
| `tests/test_nested_pty.py` | 171 | DELETE (E3) | DELETE |  |  | - | 0 | nested_pty.py named in E3. |
| `tests/test_npm_metadata.py` | 46 | UNLISTED (none) | DECIDE | DELETE (E10, R2-26) |  | - | 0 | Orphan helper: confirm the owner before deleting. |
| `tests/test_oc_go_skill_status.py` | 355 | DELETE (E9) | DELETE |  |  | - | 0 | oc-go-key named in E9. |
| `tests/test_omp_history_hygiene.py` | 248 | DELETE (E3) | DELETE |  |  | - | 0 | Adapters are named in E3; session-history.py is not named, its plist goes in E5. |
| `tests/test_omp_operator_gate.py` | 157 | KEEP (E6) | KEEP |  |  | - | 0 | Operator gate (hermes, cline refused); stays with agent_guard.py (E6, checkins B1d). |
| `tests/test_opencode_self_compact.py` | 113 | DECIDE (E4, E9) | DECIDE |  |  | - | 1 | self-slash DELETE, opencode-* conditional on the J2 audit. |
| `tests/test_ops_post_checkout_guard.py` | 49 | KEEP (E8) | KEEP |  |  | - | 1 | bin/ops-post-checkout-guard. |
| `tests/test_paseo_bypass_watch.py` | 635 | DELETE (E4) | DELETE |  |  | - | 0 | Delete after the audit confirms paseo run plus paseo agent mode cover it (E4). |
| `tests/test_paseo_new_seat_mode.py` | 106 | DELETE (E4) | DELETE |  |  | - | 0 | bin/paseo-new-seat; E4 audit gate. |
| `tests/test_paseo_new_seat_probe.py` | 86 | DELETE (E4) | DELETE |  |  | - | 0 | bin/paseo-new-seat --probe; E4 audit gate. |
| `tests/test_paseo_set_model.py` | 236 | DELETE (E4) | DELETE |  |  | - | 0 | bin/paseo-set-model; E4 audit gate. |
| `tests/test_pi_dispatch_admission.py` | 334 | DELETE (E9) | DELETE |  |  | - | 0 | acp-dispatch pi admission; pi retired. |
| `tests/test_pi_history_identity.py` | 284 | DELETE (E9) | DELETE |  |  | - | 0 | session-finder nativeid/session-history for pi; pi retired. |
| `tests/test_pi_native_controls.py` | 457 | DELETE (E4, E9) | DELETE |  |  | - | 1 | autorename pi_native plus self-slash for pi. |
| `tests/test_pi_skill_dedup.py` | 559 | DELETE (E9) | DELETE |  |  | - | 0 | pi-skill-dedup named in E9. |
| `tests/test_pi_subagent_invocation.py` | 39 | DELETE (E9) | DELETE |  |  | - | 1 | Operator removes the symlink and the CI npm ci line together with the extension. |
| `tests/test_post_edit_check.py` | 176 | UNLISTED (none) | KEEP |  |  | - | 0 | checkin-rulings R2: strip Codex paths only if Codex retires. |
| `tests/test_pr_policy.py` | 508 | KEEP (E5) | KEEP |  |  | - | 0 | bin/pr-policy. |
| `tests/test_pr_wait.py` | 2929 | REPLACE (E8, D10) | REPLACE |  |  | - | 0 | E8: the Action ports pr-wait's marker tests unchanged; port before deleting. |
| `tests/test_prior_art_nudge.py` | 1210 | DELETE (E10) | DELETE |  |  | - | 0 | J4 answered. |
| `tests/test_proc_cpu_watch.py` | 394 | DELETE (E5) | DELETE |  |  | - | 0 | bin/proc-cpu-watch and its plist. |
| `tests/test_prompt_line.py` | 131 | DELETE (E3) | DELETE |  |  | - | 0 | prompt_line.py is also imported by test_relay_fallback and test_self_slash_codex (both DELETE). |
| `tests/test_relay_card_alert.py` | 393 | DELETE (E3, D1) | DELETE |  |  | - | 0 | relay.py card alerts. |
| `tests/test_relay_fallback.py` | 4178 | DELETE (E3, D1) | DELETE |  |  | - | 0 | relay.py plus fleet.py; its fb.Harness is the base of the other relay tests and of test_claude_identity. |
| `tests/test_relay_message_file.py` | 130 | DELETE (E3, D1) | SHIM ≠ |  |  | - | 0 | Shim keeps --message-file/--ack/--wait (E3; bin/deadline:446-451); this file and test_relay_verified are the source for the shim's one test. |
| `tests/test_relay_omp_hygiene.py` | 120 | DELETE (E3) | DELETE |  |  | - | 0 | relay.py omp process matching. |
| `tests/test_relay_paseo.py` | 1121 | DELETE (E3, D1) | DELETE |  |  | - | 0 | relay.py Paseo route becomes paseo send in the shim. |
| `tests/test_relay_prose_nudge.py` | 801 | DELETE (E3) | DELETE |  |  | - | 0 | relay_prose_nudge.py plus relay.py. |
| `tests/test_relay_refuse_unknown.py` | 184 | DELETE (E3) | DELETE |  |  | - | 0 | The shim refuses non-Paseo targets itself (E3). |
| `tests/test_relay_requeue.py` | 246 | DELETE (E3) | DELETE |  |  | - | 0 | relay.py requeue. |
| `tests/test_relay_retire.py` | 261 | DELETE (E3) | DELETE |  |  | - | 0 | relay.py retired routes. |
| `tests/test_relay_sender_header.py` | 596 | DELETE (E3, E8) | DELETE |  |  | - | 0 | relay.py sender header; port the subclassed case before deleting. |
| `tests/test_relay_status.py` | 828 | DELETE (E3, D1) | DELETE |  |  | - | 0 | relay.py status words (delivered/queued/unverified). |
| `tests/test_relay_verified.py` | 2099 | DELETE (E3, D1) | DELETE |  |  | - | 0 | relay.py verified delivery, --wait/--ack; source for the shim test. |
| `tests/test_relay_watchers_no_ack.py` | 56 | DELETE (E3, E5) | DECIDE ≠ |  |  | - | 0 | load-watch find-and-tell is KEEP (D5) while the other two watchers go. |
| `tests/test_render_secret_deny.py` | 229 | UNLISTED (none) | KEEP |  |  | - | 0 | PR 289; docs/secret-deny.md is kept (E11). |
| `tests/test_route_agent.py` | 2588 | KEEP (E7, D6) | KEEP |  |  | - | 1 | Registry switches to paseo provider ls; retired-provider rows trim. |
| `tests/test_route_agent_calibrate.py` | 246 | KEEP (E7) | KEEP |  |  | - | 0 | route_agent calibrate; reads the outcome records the shim keeps. |
| `tests/test_route_agent_disabled.py` | 41 | KEEP (E7) | KEEP |  |  | - | 0 | route_agent disabled providers. |
| `tests/test_route_agent_pace.py` | 193 | KEEP (E7) | KEEP |  |  | - | 0 | route_agent pace. |
| `tests/test_routing_recalibrate.py` | 98 | DELETE (E7, D8) | DELETE |  |  | - | 0 | routing-recalibrate and its plist; a Paseo schedule if wanted. |
| `tests/test_rtk_opencode_plugin.py` | 184 | DECIDE (E9, J2) | DECIDE |  |  | - | 0 | opencode plugin, conditional on the J2 audit. |
| `tests/test_rumination_watch_auto_seat.py` | 1448 | DELETE (E5) | DELETE |  |  | - | 0 | bin/rumination-watch and its plist. |
| `tests/test_rumination_watch_deploy.py` | 374 | DELETE (E5) | DELETE |  |  | - | 0 | bin/rumination-watch and its plist. |
| `tests/test_rumination_watch_next_move.py` | 396 | DELETE (E5) | DELETE |  |  | - | 0 | bin/rumination-watch. |
| `tests/test_rumination_watch_pending.py` | 250 | DELETE (E5) | DELETE |  |  | - | 0 | bin/rumination-watch. |
| `tests/test_rumination_watch_stale.py` | 256 | DELETE (E5) | DELETE |  |  | - | 0 | bin/rumination-watch. |
| `tests/test_rumination_watch_target.py` | 1133 | DELETE (E5) | DELETE |  |  | - | 0 | bin/rumination-watch. |
| `tests/test_secret_deny_repo.py` | 43 | UNLISTED (none) | KEEP |  |  | - | 0 | Moves together with agents/ templates (checkin-rulings R2). |
| `tests/test_secret_read_gate.py` | 1130 | UNLISTED (none) | KEEP |  |  | - | 0 | R2: three bypasses must be fixed before PR 289 lands; Codex apply_patch paths strip only if Codex retires. |
| `tests/test_self_slash.py` | 1381 | DELETE (E4) | DELETE |  |  | - | 0 | bin/self-slash after the C3 gate. |
| `tests/test_self_slash_codex.py` | 433 | DELETE (E4) | DELETE |  |  | - | 0 | self-slash codex waiter. |
| `tests/test_self_slash_prompt_wait.py` | 251 | DELETE (E4) | DELETE |  |  | - | 0 | self-slash herdr prompt detection (herdr retired). |
| `tests/test_session_history_adapters.py` | 676 | DELETE (E3) | DELETE |  |  | - | 0 | Adapters named in E3. |
| `tests/test_session_relay.py` | 367 | DELETE (E3) | DELETE |  |  | - | 0 | fleet.py plus relay.py reach to Claude sessions. |
| `tests/test_skill_everywhere_all.py` | 143 | KEEP (E10, D7) | KEEP |  |  | - | 0 | The pi target case trims with pi. |
| `tests/test_skill_frontmatter.py` | 36 | UNLISTED (none) | KEEP |  |  | - | 0 | Subject-agnostic lint; E10 deletes fix-skill-frontmatter.py but not this check. |
| `tests/test_skill_get.py` | 63 | DELETE (E10) | DELETE |  |  | - | 0 | skill-get named in E10. |
| `tests/test_skillopt_night.py` | 897 | DELETE (E10) | DELETE |  |  | - | 0 | J4 answered. |
| `tests/test_skillopt_sources.py` | 610 | DELETE (E10) | DELETE |  |  | - | 0 | J4 answered. |
| `tests/test_wait_file.py` | 72 | KEEP (E5) | KEEP |  |  | - | 0 | bin/wait-file. |
| `tests/test_watch.py` | 680 | DELETE (E5) | DELETE |  |  | - | 0 | bin/watch after the C3 per-file gate. |
| `tests/test_web_digest.py` | 99 | DECIDE (E9) | DECIDE |  |  | - | 0 | KEEP only while a small-context provider survives (E9). |
| `tests/test_web_get.py` | 1670 | DECIDE (E9) | DECIDE |  |  | - | 0 | Same condition as web-digest. |
| `tests/test_zcode_key_auth.py` | 85 | DELETE (E9) | DELETE |  |  | - | 0 | zcode-key-auth and its plist named in E9. |
| `tests/test_zz_relay_real_state_untouched.py` | 32 | DELETE (E3) | DELETE |  |  | - | 0 | Guards the relay defer queue; goes with relay.py. |

### D.docs (137 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `docs/ade-everywhere-codex-review-2026-10-19.md` | 353 | MOVE (E2, E11) | MOVE |  | site-djbclark | - | 2 | history record |
| `docs/ade-everywhere-inventory-2026-10-19.md` | 282 | MOVE (E2, E11) | MOVE |  | site-djbclark | - | 2 | bin/ade-scan-state-doc goes with it |
| `docs/ade-everywhere-inventory-2026-10-20-stores.md` | 251 | MOVE (E2, E11) | MOVE |  | site-djbclark | - | 5 | update the path in ade-backup-stores and ade-template-check comments when moved (they are KEEP) |
| `docs/ade-everywhere-phase0-scan-2026-10-20.md` | 387 | MOVE (E2, E11) | MOVE |  | site-djbclark | - | 3 |  |
| `docs/ade-everywhere-prior-art-2026-10-19.md` | 98 | MOVE (E2, E11) | MOVE |  | site-djbclark | - | 1 |  |
| `docs/ade-everywhere-proposal.md` | 1390 | MOVE (E2, E11) | MOVE |  | site-djbclark | - | 6 | fix dangling mentions in agents/README.md and bin/ade-backup-stores |
| `docs/ade-everywhere-review-evaluation-2026-10-19.md` | 98 | MOVE (E2, E11) | MOVE |  | site-djbclark | - | 0 |  |
| `docs/ade-everywhere-review-evaluation-v21-2026-10-19.md` | 230 | MOVE (E2, E11) | MOVE |  | site-djbclark | - | 0 |  |
| `docs/ade-everywhere-v21-review-codex-2026-10-19.md` | 272 | MOVE (E2, E11) | MOVE |  | site-djbclark | - | 0 |  |
| `docs/ade-everywhere-v21-review-fable-2026-10-19.md` | 117 | MOVE (E2, E11) | MOVE |  | site-djbclark | - | 0 |  |
| `docs/agent-guard-contract.md` | 52 | MOVE (E11 (rest to history)) | KEEP ≠ |  | site-djbclark | - | 5 | E11's generic 'rest to history' would dangle the agent_guard.py reference; KEEP while agent_guard.py lives |
| `docs/agent-sleep.md` | 215 | DELETE (E2, D14) | DELETE |  |  | - | 3 | gated on the C7 drain (sleeper list/journal empty) |
| `docs/ai-memory-landscape.md` | 378 | MOVE (E11 (rest to history)) | MOVE |  | site-djbclark | - | 3 |  |
| `docs/apply-toolchain-prompt.md` | 1760 | MOVE (E2) | MOVE |  | docs/history | - | 4 | .gnu-tools-check-ignore line must follow the move |
| `docs/checkins` | 1604 | KEEP (C6) | KEEP |  |  | - | 0 | directory row |
| `docs/checkpoint.md` | 148 | KEEP (E11, C6) | KEEP |  |  | - | 3 | B12b: move F and G with whatever keeps the Paseo plan |
| `docs/claude-cache-cost-research-report.md` | 121 | MOVE (E11 (rest to history)) | MOVE |  | site-djbclark | - | 1 |  |
| `docs/coding-factory.md` | 316 | MOVE (E11 (rest to history)) | MOVE |  | site-djbclark | - | 3 | AGENTS.md row removed in E11 |
| `docs/context-hygiene.md` | 218 | MOVE (E11 (rest to history)) | KEEP ≠ |  | site-djbclark | - | 5 | four skills that survive link it; rewrite links before moving, else KEEP |
| `docs/deadline.md` | 209 | KEEP (E5 (deadline KEEP), E11) | KEEP ≠ |  |  | - | 7 | E11 keep list omits it but E5 keeps the tool; plan_disposition derived from E5 |
| `docs/disabled-skills.md` | 295 | MOVE (E11 (rest to history)) | MOVE |  | site-djbclark | - | 2 | skills.md section must be rewritten or dropped with it |
| `docs/dispatch-footer.md` | 25 | KEEP (E6 (brief footer kept)) | KEEP ≠ |  |  | - | 5 | E11 generic 'rest to history' would break acp-dispatch at runtime |
| `docs/failover.md` | 224 | KEEP (E7 (failover.py model-chain h…) | KEEP ≠ | MOVE docs/history (ruling 1) |  | - | 3 | trim the route half; E11 keep list silent |
| `docs/firecrawl-commercial-vs-selfhosted-2026-10-14.md` | 6 | UNLISTED (none) | DELETE |  |  | - | 2 | stub; firecrawl skill moves to site-djbclark (E1) |
| `docs/gates.md` | 259 | KEEP (E7) | KEEP |  |  | - | 5 | trim to frontier half |
| `docs/git-guard.md` | 242 | KEEP (E11, E8) | KEEP |  |  | - | 4 | C5: document the real claim ls |
| `docs/hand-alias.md` | 26 | MOVE (E4, E11) | KEEP ≠ |  | site-djbclark | - | 2 | KEEP until the last hand link goes; then DELETE |
| `docs/handoffs` | 7561 | KEEP (C6) | KEEP |  |  | - | 4 | directory row; never move |
| `docs/helm.md` | 211 | REPLACE (E4, D2) | REPLACE |  |  | - | 4 | history after replacement verified live |
| `docs/hindsight-restructure-execution.md` | 3 | UNLISTED (none) | DELETE |  |  | - | 0 |  |
| `docs/history` | 65 | KEEP (E11) | KEEP |  |  | - | 1 | barnowl moves to site-djbclark (E1): its review history may follow |
| `docs/jev.md` | 360 | DELETE (E2, J4) | DELETE |  |  | - | 4 |  |
| `docs/mcp-servers.md` | 267 | MOVE (E11 (rest to history)) | KEEP ≠ |  | site-djbclark | - | 4 | two KEEP docs link it; E11 does not name it |
| `docs/model-routing.md` | 628 | KEEP (E7) | KEEP |  |  | - | 3 | trim; E11 keep list silent but E7 names it |
| `docs/model-tiers-design.md` | 510 | MOVE (E11 (rest to history)) | MOVE |  | site-djbclark | - | 3 | fix the three code comments |
| `docs/opencode-plugin-v2.md` | 163 | UNLISTED (E9 (opencode-plugins/ dir)) | DECIDE |  |  | - | 1 | follows opencode-plugins/ fate (J2 audit) |
| `docs/orchestration-practices.md` | 198 | KEEP (E11 (rewritten)) | KEEP |  |  | - | 4 |  |
| `docs/paseo-only-rearchitecture.md` | 633 | KEEP (E11) | KEEP |  |  | - | 5 |  |
| `docs/paseo-plugins-scan-2026-10-19.md` | 233 | MOVE (E11 (rest to history)) | MOVE |  | site-djbclark | - | 1 |  |
| `docs/pi-agent-profiles.md` | 14 | DELETE (E9) | DELETE |  |  | - | 2 | gated on the J2 audit |
| `docs/pi-skills.md` | 177 | DELETE (E9) | DELETE |  |  | - | 4 | docs/skill-everywhere.md mention must be edited |
| `docs/pi-subagent.md` | 62 | DELETE (E9) | DELETE |  |  | - | 2 |  |
| `docs/post-edit-check.md` | 44 | UNLISTED (none) | KEEP |  |  | - | 1 | E11 keep list is missing it; add |
| `docs/pr-policy.md` | 92 | KEEP (E5 (pr-policy KEEP)) | KEEP ≠ |  |  | - | 3 | E11 keep list silent; E5 keeps the tool |
| `docs/queue.md` | 2120 | KEEP (E11, J5) | KEEP |  |  | - | 4 | 83 H2/H3 entries rowed below; headings now reach line 2110, file is longer than 2,079 |
| `docs/queue.md:1 (preamble)` | 5 | KEEP (E11, J5) | KEEP |  |  | - | 0 | class=keep |
| `docs/queue.md:1012 Buy a Jev plan before the merge gate goes live` | 6 | KEEP (E11, E2, J4) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:1018 Paseo Telegram plugin replaces Hermes's relay` | 7 | KEEP (E11) | KEEP |  |  | - | 0 | class=carried, one line |
| `docs/queue.md:1025 Telegram for 2fado, Herald, web searches: talk first` | 10 | KEEP (E11) | KEEP |  |  | - | 0 | class=carried, one line |
| `docs/queue.md:1035 ade-git-guard (PR 59): redesign O2 adopted` | 14 | KEEP (E11, E8) | MOVE |  | site-djbclark | - | 1 | class=done |
| `docs/queue.md:1049 ade-git-guard O2 built; what is left` | 24 | KEEP (E11, E8) | KEEP |  |  | - | 1 | class=carried; prune items 3,4 for deleted callers |
| `docs/queue.md:1073 acp-dispatch launchd label with slash: lows` | 9 | KEEP (E11, E6) | DELETE |  |  | - | 1 | class=closed |
| `docs/queue.md:1082 Verified peer messaging (2026-10-25)` | 33 | KEEP (E11, E3) | DELETE |  |  | - | 1 | class=closed |
| `docs/queue.md:1115 Software factory, Phase F` | 7 | KEEP (E11) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:1122 Read-only codex advisor ends on first refused escalation` | 12 | KEEP (E11, E6) | KEEP |  |  | - | 1 | class=carried, one line (E6 brief input) |
| `docs/queue.md:1134 self-slash cannot drive omp` | 14 | KEEP (E11, E4) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:1148 Ralph on OpenCode v2: postponed` | 19 | KEEP (E11, E2) | DELETE |  |  | - | 1 | class=closed |
| `docs/queue.md:1167 Resurface 2026-10-14: first SkillOpt-Sleep night` | 67 | KEEP (E11, E10, J4) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:118 Port Linux suite to uutils` | 8 | KEEP (E11) | MOVE |  | site-djbclark | - | 1 | class=done (CHANGELOG has it per handoff uutils PR 105) |
| `docs/queue.md:1234 Crush under --perm deny: adversary findings` | 16 | KEEP (E11, E9) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:1250 acp-run --perm deny: user-config strip still lets through` | 15 | KEEP (E11, E6) | KEEP |  |  | - | 1 | class=carried, one line (E6 brief input) |
| `docs/queue.md:126 frontier_agent_gate._guard_state own reader` | 6 | KEEP (E11, E7) | KEEP |  |  | - | 1 | class=carried |
| `docs/queue.md:1265 acp-run: classify quota and outage failures at the source` | 13 | KEEP (E11, E6, E9) | DELETE |  |  | - | 1 | class=closed |
| `docs/queue.md:1278 SkillOpt-Sleep phase 2` | 12 | KEEP (E11, E10) | DELETE |  |  | - | 1 | class=closed |
| `docs/queue.md:1290 Research checker: namespace-aware citations` | 21 | KEEP (E11, E6) | DECIDE |  |  | - | 1 | class=carried pending the E6 research decision |
| `docs/queue.md:1311 Watch Orca upstream for reorg verbs` | 8 | KEEP (E11) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:1319 Quota-aware automatic cross-vendor subagent routing` | 39 | KEEP (E11, D4, J2) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:132 Verified peer messaging, round 2` | 37 | KEEP (E11, E3) | DELETE |  |  | - | 1 | class=closed |
| `docs/queue.md:1358 Dynamic self-adjustment of model version and effort` | 25 | KEEP (E11, G) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:1383 S1 Phase B: foundation landed, adapters next` | 22 | KEEP (E11) | DECIDE |  |  | - | 0 | class=carried, belongs in site-djbclark's backlog |
| `docs/queue.md:1405 Implement cow: DONE 2026-08-23` | 182 | KEEP (E11) | MOVE |  | site-djbclark | - | 1 | class=done; H3s 1505 Original decision record, 1509 Baseline measured, 1558 Rationale go with it |
| `docs/queue.md:1587 Completed 2026-08-23 (kept briefly)` | 31 | KEEP (E11) | MOVE |  | site-djbclark | - | 0 | class=done |
| `docs/queue.md:1618 Ingest web-interface AI conversations into memory` | 68 | KEEP (E11) | KEEP |  |  | - | 0 | class=carried, one line (H3 1633 VESTI assessed folds in) |
| `docs/queue.md:1686 Token-cost hygiene (video analysis)` | 54 | KEEP (E11) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:169 Research: relay/self-slash blocking on picklists` | 13 | KEEP (E11, E3, E4) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:1740 Review the Copilot subscription ($29/mo)` | 20 | KEEP (E11, E9) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:1760 Monthly plans that work with Hermes` | 29 | KEEP (E11, J2) | KEEP |  |  | - | 0 | class=carried, one line |
| `docs/queue.md:1789 Also outstanding (raised, not formally queued)` | 48 | KEEP (E11) | KEEP |  |  | - | 0 | class=carried for hindsight/upstream-issues bullets; cow/Orca/launch.py bullets closed |
| `docs/queue.md:182 Research: web prior art, Python over bash, Kiro/LSP` | 19 | KEEP (E11, J4) | DELETE |  |  | - | 1 | class=closed (Python-over-bash item: one carried line if wanted) |
| `docs/queue.md:1837 Re-check Context7 use` | 9 | KEEP (E11) | KEEP |  |  | - | 1 | class=carried, one line (overdue) |
| `docs/queue.md:1846 Orca's short PostCompact hook` | 10 | KEEP (E11) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:1856 Jev-vs-GLiDE dual review: DONE 2026-10-25` | 17 | KEEP (E11, E2) | MOVE |  | site-djbclark | - | 1 | class=done |
| `docs/queue.md:1873 Why the sed edit failed twice: DONE 2026-10-14` | 9 | KEEP (E11) | MOVE |  | site-djbclark | - | 0 | class=done |
| `docs/queue.md:1882 Flaky MockWebServer tests on the SIPB runner: DONE 2026-10-14` | 20 | KEEP (E11) | MOVE |  | site-djbclark | - | 0 | class=done |
| `docs/queue.md:1902 Loopback shim default on forgejo.mit.edu, then ask SIPB` | 61 | KEEP (E11, E1) | MOVE |  | site-djbclark | - | 0 | class=carried, but it belongs with the forgejo skills in site-djbclark's backlog |
| `docs/queue.md:1963 hermes route in relay.py` | 44 | KEEP (E11, E3) | DELETE |  |  | - | 1 | class=closed (hermes target would need a paseo-side answer if wanted) |
| `docs/queue.md:2007 relay.py pane route: lows after adversary round 9` | 31 | KEEP (E11, E3) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:201 Follow-ups after PR 73 and PR 74` | 10 | KEEP (E11, E3) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:2038 Paseo agents in fleet.py and relay.py: lows` | 14 | KEEP (E11, E3, E5) | DELETE |  |  | - | 1 | class=closed |
| `docs/queue.md:2052 Queued lows branch: adversary BLOCK and repair` | 14 | KEEP (E11, E3) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:2066 Queued lows branch: round 2, APPROVE at 98f3d61` | 36 | KEEP (E11, E3) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:2102 An absolute 'all work in a worktree' commandment?` | 8 | KEEP (E11) | MOVE |  | site-djbclark | - | 1 | class=done |
| `docs/queue.md:211 relay.py deferred send and Paseo sender label` | 26 | KEEP (E11, E3) | DELETE |  |  | - | 0 | class=closed; note load-watch --no-defer use disappears with it |
| `docs/queue.md:2110 deadline registry follow-ups (PR 223)` | 12 | KEEP (E11, E5) | KEEP |  |  | - | 2 | class=carried, one line (item 2 may be closed by ade-sched) |
| `docs/queue.md:237 tuios support: do it LAST` | 31 | KEEP (E11) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:268 bm-lint (PR 55) and pr-wait (PR 58) follow-ups` | 9 | KEEP (E11, E8) | KEEP |  |  | - | 1 | class=carried for bm-lint lines only; pr-wait item closed |
| `docs/queue.md:277 ade-scan-state follow-up 3 after PR 47` | 4 | KEEP (E11, E2) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:281 ade-scan-state follow-up 2 after PR 39` | 8 | KEEP (E11, E2) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:289 Consider: drop brew Paseo, run our fork` | 9 | KEEP (E11) | KEEP |  |  | - | 0 | class=carried |
| `docs/queue.md:298 Paseo connected hosts` | 29 | KEEP (E11, D1) | KEEP |  |  | - | 0 | class=carried |
| `docs/queue.md:327 Phase 0 scan of bigteam and Orca checkouts` | 10 | KEEP (E11, E2) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:337 Make better use of Basic Memory` | 32 | KEEP (E11) | KEEP |  |  | - | 1 | class=carried |
| `docs/queue.md:369 Heavier use of Hermes worktrees and cow pastures` | 25 | KEEP (E11, E2) | DELETE |  |  | - | 1 | class=closed |
| `docs/queue.md:394 Paseo tabs, -pt naming, autorename for tabs` | 32 | KEEP (E11, E4) | DELETE |  |  | - | 1 | class=closed |
| `docs/queue.md:41 Interruption recovery architecture` | 8 | KEEP (E11, D11, J9) | KEEP |  |  | - | 1 | class=carried |
| `docs/queue.md:426 Full use of podman, kev, laya, hyades-docker microVMs` | 31 | KEEP (E11) | KEEP |  |  | - | 0 | class=carried |
| `docs/queue.md:457 Orchestration rules from the load watcher` | 34 | KEEP (E11) | KEEP |  |  | - | 1 | class=carried until folded into the rewrite |
| `docs/queue.md:49 relay: card-blocked records fail fast` | 8 | KEEP (E11, D1) | DELETE |  |  | - | 0 | class=closed (subject replaced) |
| `docs/queue.md:491 PR 31 claude-fleet-governor and quota emergency` | 32 | KEEP (E11, E7) | DELETE |  |  | - | 1 | class=closed |
| `docs/queue.md:523 Follow-ups from PRs 29 and 30 and the exhaustion post-mortem` | 109 | KEEP (E11, E7) | DELETE |  |  | - | 0 | class=closed; carry items 6 and 7 as one line each |
| `docs/queue.md:57 relay.py: tell what a message did / stuck queue` | 31 | KEEP (E11, D1) | DELETE |  |  | - | 0 | class=closed (built, then superseded by E3) |
| `docs/queue.md:6 Issue 284 follow-ups: NDC Oslo ideas` | 35 | KEEP (E11, J5) | KEEP |  |  | - | 2 | class=carried |
| `docs/queue.md:632 Follow-ups from the 2026-10-20 reviews` | 130 | KEEP (E11) | KEEP |  |  | - | 1 | class=carried, reduce to the dated items |
| `docs/queue.md:762 Paseo workspace names after a handoff` | 23 | KEEP (E11, E4) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:785 load-watch send_to relay round-1 exposure` | 19 | KEEP (E11, D5) | KEEP |  |  | - | 1 | class=carried, one line |
| `docs/queue.md:804 ADE-everywhere Phase 0, preserve and classify` | 129 | KEEP (E11, E2) | DELETE |  |  | - | 1 | class=closed; ade-backup-stores stays KEEP trimmed (E10) |
| `docs/queue.md:88 Build model tiers as data` | 7 | KEEP (E11, E7) | KEEP |  |  | - | 1 | class=carried, one line; re-check inventory against E7 code |
| `docs/queue.md:933 Keep every machine current, and a changelog` | 35 | KEEP (E11, E10) | MOVE |  | site-djbclark | - | 1 | class=done |
| `docs/queue.md:95 paseo-bypass-watch launchd install` | 4 | KEEP (E11, E4) | DELETE |  |  | - | 0 | class=closed |
| `docs/queue.md:968 Cloud-agent readiness: Codex Cloud env, Cursor API key` | 27 | KEEP (E11) | KEEP |  |  | - | 0 | class=carried |
| `docs/queue.md:99 Context visibility and compact/handoff discipline` | 19 | KEEP (E11) | KEEP |  |  | - | 1 | class=carried |
| `docs/queue.md:995 The Claude API credits (omp): finish the wiring` | 17 | KEEP (E11, E9, J2) | DECIDE |  |  | - | 0 | class=carried pending audit |
| `docs/scheduling.md` | 174 | KEEP (E11 (PR 291)) | KEEP |  |  | - | 4 | drop mentions of deleted plists (acp-dispatch-reap, proc-cpu-watch, rumination-watch, session-history-update) |
| `docs/secret-deny.md` | 201 | KEEP (E11 (PR 289)) | KEEP |  |  | - | 4 | test asserts the path: do not move |
| `docs/skill-everywhere.md` | 179 | MOVE (E10, E11) | KEEP ≠ |  | site-djbclark | - | 4 | E11 would move it to history while the tool it documents stays; trim instead; .gitignore names it |
| `docs/skillopt-preferences.md` | 38 | DELETE (E10, J4) | DELETE |  |  | - | 2 |  |
| `docs/skillopt-sleep-config.example.json` |  | DELETE (E10, J4) | DELETE |  |  | - | 1 | non-markdown; not in inventory D |
| `docs/skillopt-sleep-night.example.json` |  | DELETE (E10, J4) | DELETE |  |  | - | 1 | non-markdown |
| `docs/skillopt-sleep.md` | 491 | DELETE (E10, J4) | DELETE |  |  | - | 5 |  |
| `docs/skills.md` | 130 | KEEP (E, E11 (shared file: lead edi…) | KEEP |  |  | - | 3 | rewrite from skills/ at E11; lines 33-43 describe retired Orca/herdr state |
| `docs/slim` | 2147 | UNLISTED (none) | KEEP |  |  | - | 0 | KEEP through the slim-down; at the end move to docs/history/ dated, keeping evidence-paseo-recovery-F.md |
| `docs/software-factory-design.md` | 817 | MOVE (E11 (rest to history)) | MOVE |  | site-djbclark | - | 1 |  |
| `docs/software-factory-research-digest-2026-10-19.md` | 254 | MOVE (E11 (rest to history)) | MOVE |  | site-djbclark | - | 1 |  |
| `docs/software-factory-reviews` | 969 | MOVE (E11 (rest to history)) | MOVE |  | site-djbclark | - | 0 | directory row; move as a unit with software-factory-design |
| `docs/threat-model.md` | 355 | KEEP (E11) | KEEP |  |  | - | 2 | mentions load-watch runaway response, acp-run, relay: update for the replaced pieces |
| `docs/tui-lessons-learned.md` | 417 | KEEP (E11, B12a) | KEEP |  |  | - | 1 |  |
| `docs/upstream-issues.md` | 1285 | MOVE (E11 (rest to history)) | KEEP ≠ |  | site-djbclark | - | 4 | unfiled drafts are live; KEEP, prune entries for retired tools |

### D.root (9 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `CFEngine repo: cfenginewatch, watch, fleet-watch (I4b)` | 1067 | DELETE (E5, C3, I4b) | DECIDE |  |  | - | 5 | Registration is paused; watchers become Paseo schedules. |
| `Paseo upstream fleet-watch registration `watch paseo 1j` (paseowatch)` |  | DELETE (E5, C3, I4c) | DECIDE |  |  | - | 4 | Paused; unpause only after the schedule exists. |
| `README.md` | 435 | KEEP (E11 (under 150 lines, generat…) | KEEP |  |  | - | 3 | E11 rewrite; check three tests that read README.md before shrinking it |
| `changelog.d` | 266 | UNLISTED (E header (changelog.d/slim-20…) | KEEP |  |  | - | 3 | directory row; fold at E11; add one slim fragment per rule 10 |
| `fleet-watch (outside the repo; home unverified)` |  | UNLISTED (C3 (audit (e) probes it)) | DECIDE |  |  | - | 3 | AGENTS.md row links a file that does not exist here; fix in E11 after the audit probes the home. |
| `launchd template com.djbclark.@TARGET@-cpu-watch (proc-cpu-watch)` |  | DELETE (E5, D5) | DELETE |  |  | - | 2 | The plist file is not named in E5's plist brace list; it goes with the script. |
| `nix2cf AGENTS.md: same names as tendcf (acp-dispatch --kind frontier, acp-run, relay.py, route_agen…` |  | DECIDE (C3, I4a, B1c) | DECIDE |  |  | - | 8 | Quota-gate names here block E7 deleting the Claude-quota half of ade_gates (PLAN E7, B9b). |
| `stash prwait-wip2 (stash@{0} on prwait-adversary-gate) and report F items F1-F12` |  | DECIDE (C4, F) | DECIDE |  |  | - | 2 | Unowned items; none may be deleted on this branch's authority (order 9, F). |
| `tendcf AGENTS.md: `acp-dispatch --kind frontier`, acp-run, relay.py, route_agent, quota gates, load…` |  | DECIDE (C3, I4a, B1c) | DECIDE |  |  | - | 9 | Per-file C3 gate for E3, E5, E6, E7; slim lead has merge decisions for these five repos per J2b. |

### D.outside (36 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `~/.claude/settings.json hook: bin/post-edit-check --hook (PostToolUse)` |  | UNLISTED (none) | KEEP |  |  | - | 1 | Hook on a repo path; fires on every edit, so it must not be deleted without an operator edit. |
| `~/.claude/settings.json hook: claude/hooks/context_size_nudge.py` |  | UNLISTED (none) | KEEP |  |  | - | 2 | Not in PLAN E or C2; the context-watch/context-budget decision (E5) may affect it. |
| `~/.claude/settings.json hook: claude/hooks/jev_effort_hook.py (UserPromptSubmit)` | 120 | DELETE (E2, C2) | DELETE |  |  | - | 2 | Template runs the ~/.claude/hooks copy; confirm on the Mac whether that is a symlink into the repo. |
| `~/.claude/settings.json hook: claude/hooks/prior_art_nudge.py (PostToolUse and UserPromptSubmit)` | 1251 | DELETE (E10, J4, C2) | DELETE ≠ |  |  | - | 2 | Template has three references (285, 307, 600) where C2 counts two; the operator edit must cover the template too. A hook on a deleted file … |
| `~/.claude/settings.json hook: claude/hooks/quota_nudge.py (UserPromptSubmit)` | 275 | DECIDE (D4, C2) | DECIDE |  |  | - | 2 | Depends on the claude-quota-guard state half that E7 keeps for the frontier gate. |
| `~/.claude/settings.json hook: claude/hooks/relay_prose_nudge.py` | 335 | DELETE (E3) | DELETE ≠ |  |  | - | 2 | Not in C2's hook list. Goes only with the real relay.py, since its text matching depends on relay.py's footers (not the shim's). |
| `~/.claude/settings.json hook: skills/autorename/autorename_nudge.py (UserPromptSubmit)` | 228 | DELETE (E4) | DELETE ≠ |  |  | - | 2 | C2 omits this hook from its list of hook lines to remove; it must be added to the operator-edit list. |
| `~/.config/aiuse/config.toml `[analysis.excluded_pools] "opencode-go"`` |  | DECIDE (C3, B9c) | DELETE |  |  | - | 2 | Operator edit after PR 260 and J2 audit. |
| `~/.local/bin/acp-run (installed link) and ~/ops/site-private/bin/acp-run fallback` | 5169 | DELETE (E6 (follow-up PR, Wave 6), C3) | SHIM |  |  | - | 2 | Disposition is SHIM-then-delete in PLAN; plan_disposition recorded as the end state. |
| `~/.local/bin/coding-bot (symlink -> ~/src/djbclark-ade/bin/coding-bot)` | 601 | MOVE (E6 (code moves to peer-link's…) | MOVE |  | peer-link | - | 2 | Repoint the symlink and home-agents.md item 40 on the move; the live Coding link does not depend on this repo (B8a). |
| `~/.local/bin/herdr-sleeper (symlink, may dangle)` |  | DELETE (C2, D14, E2) | DELETE |  |  | - | 1 | Operator removes; gate C7 requires `herdr-sleeper list` and journal empty before E2 merges. |
| `~/.local/state/ade/claims (about 20 active claims, incl. fleet-migrate-1103, cfengine-6424-prep-202…` |  | KEEP (C4, D9, E8) | KEEP |  |  | - | 3 | I1: `ade-git-guard claim ls` does not exist; listing is `bin/ade_claims.py list` (E8 fixes). |
| `~/.local/state/bigteam/*/jobs/*.json (outcome records)` |  | KEEP (C4, E6) | KEEP |  |  | - | 2 | Shim must write the same record shape for one cycle. |
| `~/.local/state/bigteam/adhoc-2026-11-02/jobs/adversary-pr254f.json (launchd label acp-dispatch.adho…` |  | UNLISTED (none) | DECIDE |  |  | - | 2 | Operator confirms the round exited (C7 drain). C7 requires no acp-dispatch record resumable or scheduled auto-resume. |
| `~/.local/state/bigteam/deepseek-review-2026-10-30/lander3.py and feeder.py` |  | DELETE (J11, B1f) | DELETE |  |  | - | 9 | Outside the repo; becomes dead with the lander retirement. |
| `~/.local/state/bigteam/{tendcf-s5-20261103,fork-cmdb-closed-20261103,tendcf-q10-policy-20261106}/jo…` |  | KEEP (C1 (J1 answered: all three ex…) | KEEP |  |  | - | 3 | Gate cleared per J1; records stay as calibration data (C4). |
| `~/.local/state/load-watch/watcher.json` |  | KEEP (C4, D5) | KEEP |  |  | - | 1 | State, not code. E5 trim must keep the file format readable or provide a clear step. |
| `~/.local/state/pr-policy/ and ~/.local/state/load-watch/ and deadline records (state)` |  | KEEP (C4, E5) | KEEP |  |  | - | 3 | F9: clean the stale admit-wait-257 deadline record by the normal tool. |
| `~/.local/state/relay pending expectations (relay.py --pending: 8 queued unverified acks)` |  | KEEP (C7, E3) | KEEP |  |  | - | 1 | Drain gate, operator pastes output into docs/slim/log.md. |
| `~/.local/state/session-finder (calibration/record root)` |  | KEEP (E3 (read-only state path)) | KEEP |  |  | - | 2 | launch.py deleted in E3 must not orphan the records route_agent reads. |
| `~/.omp/agent/commands/hand.md, ~/.pi/agent/prompts/hand.md, ~/.zcode/commands/hand.md, ~/.config/op…` |  | DELETE (E4 (retired providers only), …) | DELETE |  |  | - | 1 | Per-link: delete the link of each retired provider when that provider retires. |
| `~/.pi/agent/extensions/subagent (symlink -> pi/extensions/subagent)` |  | DECIDE (C2, E9 (J2 provider rule), I4f) | DECIDE |  |  | - | 1 | Hold until the aiuse pools audit settles omp/pi survival; pi->omp port only if omp survives. |
| `~/Library/LaunchAgents plists for fleet-watch and the paused upstream watchers` |  | UNLISTED (C1, C3) | DECIDE |  |  | - | 3 | Cannot see the Mac; path unknown. |
| `~/Library/LaunchAgents/com.djbclark.acp-dispatch-reap.plist and per-run acp-dispatch.* labels and `…` |  | DELETE (E6, C7) | DELETE |  |  | - | 2 | Gate: C7 drain first. The in-repo template is listed in neither C nor E5 by name beyond the E6 'reap plist' mention. |
| `~/Library/LaunchAgents/com.djbclark.ade-lander.plist and com.djbclark.ade-feeder.plist (booted out)` |  | DELETE (J11 (answered), C1) | DELETE |  |  | - | 0 | Operator removes the plists; no in-repo target found in launchd/ listing. |
| `~/Library/LaunchAgents/com.djbclark.context-budget.plist` | 484 | DELETE (E5, J3) | REPLACE |  |  | - | 2 | Script stays; its launchd job is replaced by a Paseo schedule. |
| `~/Library/LaunchAgents/com.djbclark.deadline-sweep.plist (60 s sweep)` | 1583 | KEEP (E5, C1) | KEEP |  |  | - | 3 | The sweep depends on the E3 relay shim keeping --message-file, --ack, --wait (PLAN E3). Reinstall if bin/deadline path changes. |
| `~/Library/LaunchAgents/com.djbclark.load-watch.plist (runs /Users/djbclark/src/djbclark-ade/bin/loa…` | 2188 | KEEP (E5, D5, C1) | KEEP |  |  | - | 3 | If bin/load-watch moves, update plist and skills/loadwatch together (B4a). E5 rewrites attribution to paseo ls before fleet.py can go. |
| `~/Library/LaunchAgents/com.djbclark.pr-policy.plist (600 s)` | 515 | KEEP (E5, C1) | KEEP |  |  | - | 2 | Plist fails every 10 min if path breaks (B6a). |
| `~/Library/LaunchAgents/com.djbclark.routing-recalibrate.plist` | 181 | DELETE (E5 (plist list), E7) | DELETE |  |  | - | 2 | Two slices name this plist (E5 and E7); the merger assigns one deleting slice. |
| `~/Library/LaunchAgents/com.djbclark.rumination-watch.plist` |  | DELETE (E5) | DELETE |  |  | - | 2 | Report does not say whether it is loaded on the Mac; operator checks `launchctl list`. |
| `~/Library/LaunchAgents/com.djbclark.session-history-update.plist` |  | DELETE (E5) | DECIDE |  |  | - | 2 | E5 deletes the plist while E3 does not name session-history.py; decide whether the script goes too. |
| `~/Library/LaunchAgents/com.djbclark.skillopt-sleep.plist` |  | DELETE (E10, J4) | DELETE |  |  | - | 2 | skillopt-night is an acp-run client; deleting it removes one acp-run caller. |
| `~/Library/LaunchAgents/com.djbclark.watchdogd.plist (runs ~/ops/site-public-djbclark/bin/apple_daem…` |  | UNLISTED (none (report B11a)) | KEEP |  |  | - | 0 | No dependency on this repo; listed to record that it is not a candidate. |
| `~/Library/LaunchAgents/com.djbclark.zcode-key-auth.plist` |  | DELETE (E9 (retired-provider bin help…) | DELETE |  |  | - | 2 | Gated on J2's provider audit before machine-side zcode uninstall (PLAN E9). |
| `~/ops/site-public-djbclark/home-agents.md item 40 (coding-bot)` |  | MOVE (C3, E6) | MOVE |  | peer-link | - | 1 | Doc edit in another repo; proposal only unless site-public is among the J2b five. |

### D.Plektra (~ (1 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `Plektra (~/src/plektra-djbclark): acp-dispatch, relay.py, autorename, self-slash (I4d)` |  | DECIDE (C3, E4, I4d) | DECIDE |  |  | - | 4 | Report F11: repo has ` M .gitignore` and `?? .codex/` from before; do not touch. |

### D.Wave 1 (1 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `Wave 1/E-slice outside gate: com.djbclark.* mentions in ~/AGENTS.md item 15 (copy / copy-colors mea…` |  | UNLISTED (none (report G9)) | KEEP |  |  | - | 0 | Instruction-file upkeep, order 11(b); no repo target. |

### D.herdr plugin registration `herdr plugin link plugins (1 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `herdr plugin registration `herdr plugin link plugins/herdr-sleeper`` |  | DELETE (C2, E2, D14) | DELETE |  |  | - | 2 | Unlink in herdr before the directory is deleted. |

### D.machine state from dsh (w20:p0): ~ (1 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `machine state from dsh (w20:p0): ~/.local/bin/dsh, ~/.local/lib/dsh/bin/dsh-bin, ~/.dsh/profiles/we…` |  | UNLISTED (none (report B8f)) | DECIDE |  |  | - | 0 | Not a dependent of this repo's code; outside-the-repo cleanup owned by the operator. |

### D.paseo4herdr (~ (1 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `paseo4herdr (~/src/paseo4herdr): acp-dispatch, relay.py, self-slash (I4e)` |  | DECIDE (C3, E4, I4e) | DECIDE |  |  | - | 3 | Report G4 has a pending operator check on the live plugin swap. |

### D.skill-everywhere links in ~ (1 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `skill-everywhere links in ~/.claude/skills, ~/.agents/skills, Hermes external dir, grokbot copy, si…` |  | KEEP (E10, D7, C2) | KEEP |  |  | - | 2 | Each slice that deletes a skill must list its links for the operator (PLAN E preamble). |

### D.sudo-secretspec, aiuse, paseo-runner: relay.py and acp-dispatch (1 rows)

| Path | Lines | Plan (ref) | Proposed | Lead | Target | Refute | Callers | Note |
|---|---|---|---|---|---|---|---|---|
| `sudo-secretspec, aiuse, paseo-runner: relay.py and acp-dispatch/acp-run as clients (I4g)` |  | DECIDE (C3, I4g, E3) | DECIDE |  |  | - | 3 | Wave 3 gate for E3 per PLAN. |


## E. Paths the plan never names (readers' `unlisted_paths`)

- bin: bin/ade-retro
- bin: bin/ade-template-check
- bin: bin/claude-settings-env
- bin: bin/gnu-tools-check
- bin: bin/herdr-server-run
- bin: bin/npm_metadata.py
- bin: bin/post-edit-check
- bin: bin/pytest
- bin: bin/render-secret-deny
- bin: bin/paseo-new-seat.mjs
- bin: bin/paseo-set-model.mjs
- bin: bin/web-digest-mcp
- bin: bin/ade_sched.py
- bin: tools/acp-run/zcode-denylist-shim.cjs
- bin: tools/acp-run/README.md
- bin: tools/acp-run/LICENSE
- skills: skills/_shared/
- skills: skills/ade-paseo/
- skills: skills/ade-paseo-advisor/
- skills: skills/ade-paseo-committee/
- skills: skills/ade-paseo-handoff/
- skills: skills/ade-paseo-help/
- skills: skills/ade-paseo-plugin/
- skills: skills/loose/
- skills: skills/paseo-screen/
- skills: skills/retro/ (tracked, absent from inventory B)
- skills: skills/steps/
- skills: claude/commands/helm-all.md
- skills: claude/commands/paseo-screen.md
- skills: claude/commands/resume.md
- skills: claude/commands/retro.md
- skills: claude/commands/session-finder-all.md
- skills: claude/commands/skillopt-sleep.md
- skills: claude/commands/steps.md
- skills: claude/commands/teach.md
- skills: claude/hooks/agent_footer_gate.py
- skills: claude/hooks/bash_habits_gate.py
- skills: claude/hooks/bg_test_gate.py
- skills: claude/hooks/context_size_nudge.py
- skills: claude/hooks/cswap_quota_context.sh
- skills: claude/hooks/frontier_agent_gate.py
- skills: claude/hooks/graft_grep_nudge.py
- skills: claude/hooks/graft_mcp_alwaysload.py
- skills: claude/hooks/precompact_handoff.py
- skills: claude/hooks/rtk_hook.py
- skills: claude/hooks/secret_read_gate.py
- skills: agents/claude/settings.json.tmpl (trim not owned by any E slice)
- skills: agents/README.md
- tests: tests/test_ade_retro.py
- tests: tests/test_ade_template_check.py
- tests: tests/test_agent_footer_gate.py
- tests: tests/test_bash_habits_gate.py
- tests: tests/test_bin_modes.py
- tests: tests/test_bin_pytest.py
- tests: tests/test_claude_settings_env.py
- tests: tests/test_context_size_nudge.py
- tests: tests/test_frontier_agent_gate.py
- tests: tests/test_gnu_tools_check.py
- tests: tests/test_herdr_server_run.py
- tests: tests/test_hook_deadline_timeouts.py
- tests: tests/test_npm_metadata.py
- tests: tests/test_post_edit_check.py
- tests: tests/test_render_secret_deny.py
- tests: tests/test_secret_deny_repo.py
- tests: tests/test_secret_read_gate.py
- tests: tests/test_skill_frontmatter.py
- tests: tests/conftest.py
- tests: tests/fixtures/
- tests: tests/soak_plugin_herdr.sh
- docs: docs/agent-guard-contract.md
- docs: docs/ai-memory-landscape.md
- docs: docs/claude-cache-cost-research-report.md
- docs: docs/coding-factory.md
- docs: docs/context-hygiene.md
- docs: docs/deadline.md
- docs: docs/disabled-skills.md
- docs: docs/dispatch-footer.md
- docs: docs/failover.md
- docs: docs/firecrawl-commercial-vs-selfhosted-2026-10-14.md
- docs: docs/hindsight-restructure-execution.md
- docs: docs/mcp-servers.md
- docs: docs/model-tiers-design.md
- docs: docs/opencode-plugin-v2.md
- docs: docs/paseo-plugins-scan-2026-10-19.md
- docs: docs/post-edit-check.md
- docs: docs/pr-policy.md
- docs: docs/skill-everywhere.md
- docs: docs/software-factory-design.md
- docs: docs/software-factory-research-digest-2026-10-19.md
- docs: docs/software-factory-reviews/
- docs: docs/upstream-issues.md
- docs: docs/hand-alias.md
- docs: docs/helm.md
- docs: docs/slim/
- docs: changelog.d/
- docs: vendor/hermes/claude-collaboration.SKILL.md
- docs: scripts/github-ci-run
- docs: config/launchd/dev.herdr.server.plist
- docs: config/sudoers.d/acp-dispatch-pmset
- docs: config/watch.toml
- docs: config/secret-deny.toml
- docs: config/secret_deny_policy.json
- docs: launchd/com.djbclark.proc-cpu-watch.plist
- docs: launchd/com.djbclark.session-history-update.plist
- docs: launchd/com.djbclark.zcode-key-auth.plist
- docs: launchd/com.djbclark.load-watch.plist
- outside: ~/Library/LaunchAgents/com.djbclark.watchdogd.plist
- outside: ~/.claude/settings.json hook claude/hooks/context_size_nudge.py
- outside: ~/.claude/settings.json hook bin/post-edit-check --hook
- outside: ~/.claude/settings.json hook skills/autorename/autorename_nudge.py (absent from C2's hook list)
- outside: ~/.claude/settings.json hook claude/hooks/relay_prose_nudge.py (absent from C2's hook list)
- outside: skills/session-finder/session-find.py
- outside: skills/helm/helm.py import fleet (absent from E3's import-search list)
- outside: skills/autorename/autorename.py import claude_identity (absent from E3's list)
- outside: machine dsh state (report B8f)
- outside: stash prwait-wip2 and report F items
- outside: config/launchd/dev.herdr.server.plist and bin/herdr-server-run (AGENTS.md keeps; PLAN E silent)
- outside: launchd/com.djbclark.proc-cpu-watch.plist (template, not in E5's plist list)
- outside: launchd/com.djbclark.acp-dispatch-reap.plist (named only as 'the reap plist' in E6)

## F. Critic (Opus 5.5 high)

### F1. Paths with no row

1. Coverage of inventory A (82 bin/), B (66 skills/), C (188 tests/) and D (146 docs/) is complete: every entry has its own row, or for docs/checkins, docs/handoffs, docs/history, docs/slim and docs/software-factory-reviews a directory row. Checked mechanically against docs/slim/inventory.md and git ls-files on 2026-11-06. Every gap is in the sub-files and in inventory E.
2. Inventory E entries with no row at all: AGENTS.md, CLAUDE.md, GEMINI.md, CHANGELOG.md, LICENSE, opencode.json, skills-lock.json, .mcp.json, .gitignore, .ignore, .gnu-tools-check-ignore, .adal/skills/graft, .agents/skills/graft, .claude/ (settings.json, helpers/graft-*.cjs, skills/fastino-glide, skills/graft, workflows/graph-audit.js), .claude-plugin/marketplace.json, .codex/ (config.toml, hooks.json), .cursor/ (hooks, mcp.json, rules/graft.mdc), .gemini/settings.json, .kiro/ (settings, steering), .windsurf/rules/graft.md, .pi/agents/ (astra-worker.md, frontier-astra.md). Ruling 15 defers thes…
3. .github/workflows/test.yml has no row. It is a caller in at least six rows (go_model_policy.py, instruction-lint, pytest, pi/extensions/subagent, handoff-tools, and tests at :105/:119/:120/:122), and ruling 8 makes it a serial-merger shared file.
4. claude/agents/ (adversary.md, backend.md, fable-deep.md, ux.md) has no row. adversary.md is a listed caller of acp-dispatch, claude-quota-guard, pr-wait, bigteam and ade-backup-stores.
5. tools/acp-run/README.md and tools/acp-run/LICENSE are covered only by the descriptive 'tools/acp-run/ (...)' row. Neither has a file row, unlike acp-run and zcode-denylist-shim.cjs.
6. skills/session-finder sub-files with no file row: adapters/ (18 files; bin/skillopt_sources.py names adapters/crush.py), where.py, nested_pty.py, prompt_line.py (bin/self-slash and relay.py share it), session-history.py (the script behind the session-history-update plist, which has two rows), jsonl_session.py, SKILL.md, .gitignore. launch.py and session-find.py have only line rows, not file rows.
7. skills/autorename sub-files with no row: workspace-layout.md (AGENTS.md:60 points readers there; ruling 12 moves it to docs/workspace-layout.md, which also has no row), autorename_nudge.py (only the settings.json hook row), herdr_place.py, relocate-pane.sh, pi_native.py, pi-bridge.ts, omp-bridge.ts, pi-native-controls.md.
8. New files that PLAN C/E/K2 creates or requires, with no row: bin/review-launch and its boundary tests (E8, permanent); .github/workflows/adversary-marker.yml (E8); the ~100-line relay.py shim and its one test (E3); the acp-dispatch shim test (E6); the hot-path test for load-watch cmd_sample attribution (E5); changelog.d/slim-2026-11.md (E preamble); bin/open-clean (E1, PR 256); a committed .worktreeinclude (E2 precondition, K2); docs/workspace-layout.md (ruling 12); the one-page skill that replaces bigteam (E6); the optional 20-line paseo workspace-rename helper (E4).
9. bin/fleet-watch: AGENTS.md:64 links it and it does not exist. Only the 'fleet-watch (home unverified)' DECIDE row touches it; no row covers the AGENTS.md link fix.
10. The 'Grok-bot skills' that E1 sends to site-djbclark are not named anywhere, so they have no row.
11. graft/ (rebuilt last in E11) has no row. Whether it is tracked is unverified.

### F2. Inconsistencies

1. The ledger does not carry PLAN K2 or ledger-rulings.md, though K2 says the rulings are applied in the ledger. Rows still show the pre-ruling verdicts: bin/failover.py KEEP (ruling 1 says DELETE with skillopt-night), docs/failover.md KEEP (ruling 1 sends it to history), skills/session-finder/fleet.py KEEP (K2 says SHIM with the E5 gate), 27 tests/test_acp_run_* rows DELETE (ruling 3 says SHIM), go_model_policy.py and config/go-model-policy.json DELETE (ruling 5 says SHIM), codex-env-policy-apply and test_codex_shell_env_policy.py DECIDE (ruling 9 says KEEP), forgejo/forgejo-ci/hyades-docker/si…
2. KEEP rows whose refutation is unresolved (survives:false): bin/failover.py (3 refutations), bin/pytest (3), skills/ade-paseo (3), skills/ade-paseo-plugin (2), claude/commands/paseo-screen.md (2), skills/session-finder/fleet.py (3), and the line rows bin/context-watch:74, bin/load-watch:266, skills/session-handoff/SKILL.md:137-148, bin/route_agent.py:133, 'bin/failover.py (57 acp-run mentions)' and 'bin/load-watch acp-run mentions' (2-3 each). Ruling 1 covers only failover.py and pytest; the ade-paseo pair and paseo-screen.md have no verdict.
3. The herdr server pieces are split across four rows: bin/herdr-server-run DECIDE, config/launchd/dev.herdr.server.plist KEEP, tests/test_herdr_server_run.py KEEP, and the installed-plist row DECIDE. Ruling 6 says one DECIDE covers all four. tests/test_ade_sched.py (KEEP) also reads dev.herdr.server.plist at :650.
4. The session-history-update plist is DELETE in its launchd/ row and DECIDE in its ~/Library row. Its script session-history.py has no row, and tests/test_session_history_adapters.py is DELETE.
5. The context-budget plist is DELETE in its launchd/ row and REPLACE in its ~/Library row. J3 makes it a Paseo schedule.
6. KEEP tests that read files the ledger deletes, so they fail on deletion: tests/test_ade_sched.py:629 reads launchd/com.djbclark.proc-cpu-watch.plist (DELETE); tests/test_context_budget_check.py:285-292 reads launchd/com.djbclark.context-budget.plist (DELETE) and runs context-budget-check install/uninstall, which J3 removes.
7. Test rows whose disposition differs from their subject's: test_bigteam_prune.py DELETE, though it tests skills/diskfree/scripts/bigteam-prune.py and diskfree is MOVE; test_fleet_*.py (7 files) DELETE while fleet.py KEEP/SHIM is still imported by load-watch; test_paseo_set_model.py DELETE vs paseo-set-model DECIDE; test_pi_subagent_invocation.py DELETE vs pi/extensions/subagent DECIDE; test_oc_go_skill_status.py DELETE vs oc-go-key DECIDE; test_go_model_policy.py DECIDE vs go_model_policy.py DELETE; test_npm_metadata.py DECIDE vs npm_metadata.py DELETE; test_herdr_server_run.py KEEP vs herdr-s…
8. tests/test_acp_dispatch_* rows are mixed: SHIM (test_acp_dispatch.py, _brief_footer, _classify, _load_gate, _outcome), DECIDE (_cursor_cloud, _frontier_reason, _routing), KEEP (_identity), and DELETE for the rest. PLAN E6 says these tests go in-slice and the shim gets one new test; only _identity is excepted, by ruling 4.
9. test_relay_watchers_no_ack.py is DECIDE and test_relay_message_file.py is SHIM, while every other test_relay_* and test_session_relay.py is DELETE. E3 gives the shim one test.
10. DELETE rows whose only caller is a SHIM, or that a kept shim still loads: tools/acp-run/zcode-denylist-shim.cjs DELETE is loaded by acp-run (SHIM); go_model_policy.py and config/go-model-policy.json DELETE are loaded by acp-run :2313-2350 and by route_agent.py (KEEP), and opencode-plugins/go-context (DECIDE) reads the config.
11. KEEP rows whose callers are all non-KEEP: bin/agent_guard.py (only caller bin/acp-dispatch, SHIM; ruling 4 defers the decision to Wave 6); agents/codex/config.toml.tmpl (callers codex-env-policy-apply DECIDE, acp-run SHIM, and two DECIDE tests); vendor/README.md (only caller docs/helm.md, REPLACE); docs/history (only caller barnowl, MOVE); tests/test_route_agent.py (listed caller bin/routing-recalibrate:80, DELETE).
12. KEEP files that name DELETE rows and so need edits. The deleting slice owns these per ruling 11, but the ledger names no owner. bin/deadline_wait.py:3 and skills/ade-paseo/SKILL.md:103 name acp-dispatch-wait. bin/ade_gates.py, bin/route_agent.py, config/gates.toml and docs/gates.md name claude-fleet-governor and gate-profile. bin/ade_claims.py and bin/ade-git-guard name cow-pasture. bin/route_agent.py names jev, routing-recalibrate and bin/watch. bin/load-watch names bin/watch, config/watch.toml, session-load-watch, rumination-watch, the proc-cpu-watch and rumination-watch plists, and skills/…
13. agents/claude/settings.json.tmpl (KEEP) still carries hook lines for DELETE files: jev_effort_hook.py, prior_art_nudge.py (three lines in the template, two live per C2), relay_prose_nudge.py and autorename_nudge.py. It also carries a herdr hook (~/.claude/hooks/herdr-agent-state.sh) and skill entries for DELETE skills (siyuan*, ralph-tui-orchestration, skillopt-sleep*, effort-routing, autorename).
14. skills/effort-routing is DELETE and skills/fallback-chains is DECIDE, though E7 gives both the same instruction ('fold into model-routing', plan REPLACE). DELETE loses the fold.
15. skills/loadwatch is DECIDE, but E5 deletes it outright. Its note says load-watch's kept find-and-tell messages point agents to it, so either E5 or the load-watch wording must change.
16. Ruling 10 holds the existence of create-hook, btww and hand for the same J2 omp/opencode answer, yet create-hook and btww are KEEP and hand is DECIDE. E9 lists create-hook among the retired providers' skills.
17. skills/handoff is KEEP against the plan's REPLACE (D3); its file references four DELETE tools. skills/ade-paseo-committee and ade-paseo-advisor (KEEP) route to dialogue (DECIDE) and acp-run (SHIM). skills/loose (KEEP) calls acp-run (DECIDE row). bin/ade-retro (KEEP) hands its output to skills/report (MOVE).
18. MOVE carries several meanings: site-djbclark (E1), bin/ (claude_identity.py), docs/history (the ade-everywhere series, apply-toolchain-prompt.md), peer-link (coding-bot), and 'closed/done' (queue.md entries). Ruling 2 adds a Target column, but these rows do not carry it.
19. skills/session-finder/nativeid.py is DECIDE (plan MOVE) and session-find.py is DECIDE, while the parent skills/session-finder row is SHIM. E3 says session-finder sub-files inherit the parent's row.
20. The ~/.local/bin/acp-run row is SHIM (plan DELETE) while tools/acp-run/acp-run is SHIM (plan SHIM). The 'tools/acp-run/ (...)' row is SHIM (plan DELETE) while its sub-file zcode-denylist-shim.cjs is DELETE.
21. The ~/.config/aiuse/config.toml opencode-go exclusion is proposed DELETE, but C3 says to drop it only after PR 260 is decided, and ruling 5 makes go_model_policy SHIM.
22. The UNLISTED list does not match the rows: it lists bin/ade_sched.py and bin/paseo-new-seat.mjs as unlisted, but their rows read plan KEEP and DELETE. It says skills/retro is absent from inventory B, but the regenerated inventory B lists it.
23. Stale outside notes on the acp-dispatch, acp-dispatch-wait and tools/acp-run rows still describe 'B1a live processes of the three slices'. C1/J1 records that all three slices exited.
24. The relay owner-notice call is cited as bin/deadline:456 (the row; that is where the relay argv sits) and as :446-451 (PLAN E3, the function). The two citations disagree.

### F3. Outside dependents without a row

1. `bg` (C1: calls `load-watch admit`; B5b: registers deadlines) has no row. Ruling 14 promises one, and its live path is still in question: site-djbclark bin/bg vs ~/ops/site-private/bin/bg, the latter named at claude/hooks/bg_test_gate.py:23.
2. Pi as a C3 repo (I4f: names pi/extensions/subagent, the hand links and agent_guard.py) has no row of its own the way Plektra and paseo4herdr do. It appears only inside the subagent-symlink and agent_guard rows.
3. The installed LaunchAgents ~/Library/LaunchAgents/com.djbclark.claude-quota-guard.plist and com.djbclark.claude-fleet-governor.plist have no row. They are written by the tools' `install` subcommands (bin/claude-quota-guard:95,869-892; bin/claude-fleet-governor:96). E7 keeps the quota-guard `check` job and deletes the governor.
4. ~/.local/state/ade/quota-guard.json has no row. E7 keeps the frontier gate reading it: judged_guard_block rejects state older than 30 min, and claude-quota-guard check produces the file.
5. skill-everywhere targets for retiring providers are absent from the skill-everywhere links row, which names only ~/.claude/skills, ~/.agents/skills, Hermes and grokbot. Missing: ~/.gemini/antigravity-cli/skills, ~/.copilot/skills, ~/.config/opencode/skills, ~/.qwen/skills, ~/.config/devin/skills, ~/.cline/skills, ~/.grok/skills, ~/.omp/agent/skills (bin/skill-everywhere:60-75). C2 requires every deletion to name the links it breaks.
6. Command-wrapper links beyond the four hand links have no row: ~/.omp/agent/commands/btww.md, and the links for the other 14 zcode/commands/*.md (autorename, baton, bigteam, helm, helm-all, session-finder*, skillopt-sleep, steps and the rest). The ~/.claude/skills/<name> links of each DELETE skill (bigteam, autorename, siyuan*, ...) are not named per row.
7. Outside hook commands in the template have no rows: ~/.claude/hooks/herdr-agent-state.sh (herdr, retired), ~/ops/site-private/bin/hook-deadline (wraps 10 hooks; tests/test_hook_deadline_timeouts.py KEEP), ~/ops/site-private/bin/claude-statusline, /opt/homebrew/bin/moshi-hook, and site-djbclark macos/graft-hook-timeout-fix/graft-hook-guard.sh.
8. C7 drain items with no row: the bigteam inboxes; the linked worktrees from `git worktree list` (~/src/djbclark-ade-route-scope-wt, -habits-subshell-wt, -dispatch-notice-wt, ~/src/tendcf-*-wt, ~/src/cfengine-core-cmdb-wt), which appear only as outside notes; and the cow-pasture listing (`bin/cow-pasture ls`).
9. C3's AGENTS.md:64 link to a nonexistent bin/fleet-watch has no owning row, because AGENTS.md has none.
10. E8 operator-side dependents have no rows: the GitHub App `ade-merge-gate`, the `merge-gate` environment secret with its master-only deployment policy, and the ruleset pinning the status source. E8 calls them operator steps before the ruleset switch.
11. E1 targets have no rows: site-djbclark branch `slim-intake/2026-11` and ~/ops/site-djbclark/skills as a new skill-everywhere root (only a generic mention on the skill-everywhere row). E9j's peer-link repo appears only as an outside note on tell-coding-bot.
12. E9 Mac-only inputs have no rows: brief-w3-{code,skills,docs}.md and wave3-owned.json (J2c), and the 147 memory notes moving to an archive folder.
13. /etc/sudoers.d/acp-dispatch-pmset (a Wave 4 removal step) appears only as an outside note on the config/sudoers.d row, with no row of its own.
14. ~/ops/site-djbclark bin/bg-offload, as a user of scripts/github-ci-run, appears only as an unverified outside note.

### F4. Questions (answered in section A)

1. 1. Re-issue the ledger with the K2/ledger-rulings applied (failover DELETE, fleet.py SHIM, test_acp_run_* SHIM, go_model_policy SHIM, codex-env-policy-apply KEEP, five skills UNLINK, herdr four-row DECIDE, web-digest-mcp DECIDE), or treat the rulings file as overriding the rows?
2. 2. skills/ade-paseo (3 refutations), skills/ade-paseo-plugin (2) and claude/commands/paseo-screen.md (2) are KEEP with survives:false: keep, trim, or delete?
3. 3. herdr server (herdr-server-run, both plists, its test, plus test_ade_sched.py:650): keep until the C7 drain shows no herdr pane and you confirm the bridges no longer need it?
4. 4. session-history.py and its plist: delete both in E5, or keep the script (E3 does not name it)?
5. 5. context-budget: confirm the plist and the install/uninstall subcommands go (J3), and that tests/test_context_budget_check.py:285-292 is rewritten in the same slice?
6. 6. claude-quota-guard: keep its installed com.djbclark.claude-quota-guard LaunchAgent (the `check` job feeding quota-guard.json) until the frontier gate reads `paseo usage --json`, and boot out com.djbclark.claude-fleet-governor with E7?
7. 7. tests/test_fleet_*.py (7 files): delete now, or keep until fleet.py goes in E5 (it stays imported by load-watch attribution)?
8. 8. tests/test_bigteam_prune.py: move with diskfree to site-djbclark (it tests diskfree's bigteam-prune.py), or delete?
9. 9. tests/test_acp_dispatch_* split: which of test_acp_dispatch.py, _brief_footer, _classify, _load_gate, _outcome, _cursor_cloud, _frontier_reason, _routing seed the shim's one test, and do the rest all go in E6?
10. 10. effort-routing and fallback-chains: fold both into model-routing (E7), or delete effort-routing outright as the ledger proposes?
11. 11. skills/loadwatch: delete in E5 and reword load-watch's find-and-tell message, or keep it trimmed as the message's target?
12. 12. create-hook, btww, hand: one shared DECIDE pending the J2 omp/opencode pool audit (needs `aiuse --json` from the Mac)?
13. 13. omp and opencode survival under J2 (Claude API-credit grant through omp; GLM/SIPB through opencode): this gates about 25 DECIDE rows (omp/, opencode/, opencode-plugins/, zcode/, pi/, agents/opencode, go-context, bg-cargo-gate, rtk.ts, their tests).
14. 14. Is Cursor kept? This gates bin/cursor-cloud, test_cursor_cloud.py and test_acp_dispatch_cursor_cloud.py.
15. 15. Does a small-context provider survive (keeping web-get, web-digest, web-digest-mcp, firecrawl-router and their tests)?
16. 16. dialogue and research: approve the 1-hour Claude-subagent port (dialogue.py:751 is the seam), or delete both?
17. 17. tell-chief-of-staff: E1 (move to site-djbclark) or E6/E9j (pointer skill stays, code to peer-link)?
18. 18. quota_nudge.py and cswap_quota_context.sh plus their live ~/.claude/settings.json lines: keep, or remove once session-guard is verified (D4)?
19. 19. agents/claude/settings.json.tmpl: confirm the lead trims the four DELETE hook lines, the herdr-agent-state.sh hook and the DELETE-skill entries at merge (ruling 8), and that you edit the live ~/.claude/settings.json for the four C2 hook files before the final merge.
20. 20. Which `bg` is live: ~/ops/site-private/bin/bg or ~/ops/site-public-djbclark/bin/bg (`ls -la` both on the Mac)?
21. 21. fleet-watch: where does it live on the Mac, and where are the LaunchAgents of the paused CFEngine and Paseo watchers (needed for the C3 gate and the AGENTS.md:64 fix)?
22. 22. Provider dot-dirs (.cursor, .codex, .kiro, .windsurf, .gemini, .adal, .agents, .claude-plugin) are graft-installed configs, and cursor and codex are kept: keep the kept providers' dirs and delete only the retired ones, rather than all 'with the provider'?
23. 23. scripts/github-ci-run: does site-djbclark bin/bg-offload still use it (keep or move), or delete?
24. 24. ~/.local/state/bigteam/adhoc-2026-11-02 adversary-pr254f record and its launchd label: confirm it exited, for the C7 drain.
25. 25. The aiuse opencode-go exclusion: decide PR 260 first (C3), then drop the exclusion only if opencode retires?
26. 26. tests/test_npm_metadata.py and bin/npm_metadata.py (0 refs): delete both, or name an owner?

