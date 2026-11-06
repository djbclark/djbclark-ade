# Wave 3 E4 report (helm, self-slash, autorename, paseo-* helpers)

Worktree `/home/user/djbclark-ade/.claude/worktrees/agent-a1901adc45a1860e6`, branch `worktree-agent-a1901adc45a1860e6` (base master `fb3b9de`; commits not pushed). 2026-11-06.

## A. Deleted

Net before this report: 54 files changed, 75 insertions, 12,649 deletions; 39 files removed.

- **A1 helm** (about 2,135 lines): `skills/helm/` (SKILL.md, helm.py, lead.md, auto.md), `claude/commands/helm-all.md`, `tests/test_helm_question_status.py`, `tests/test_helm_send_unknown.py`, `zcode/commands/helm-all.md`. `docs/helm.md` moved to `docs/history/helm.md` with a one-line header.
- **A2 self-slash** (about 4,070 lines): `bin/self-slash` (1,471), `bin/opencode-self-compact` (53), `bin/paseo-self` (239), `tests/test_self_slash.py`, `tests/test_self_slash_codex.py`, `tests/test_self_slash_prompt_wait.py`, `tests/test_prompt_line.py`, `tests/test_opencode_self_compact.py`, and `tests/test_pi_native_controls.py` (not named in the brief: its subject was `skills/autorename/pi_native.py` and `bin/self-slash`, so it cannot import).
- **A3 autorename** (about 3,380 lines): all of `skills/autorename/` (SKILL.md, autorename.py, autorename_nudge.py, herdr_place.py, pi_native.py, pi-bridge.ts, omp-bridge.ts, pi-native-controls.md, relocate-pane.sh, workspace-layout.md), `tests/test_autorename_*.py` (five files), `zcode/commands/autorename.md`.
- **A4 seat helpers** (about 1,570 lines): `bin/paseo-new-seat`, `bin/paseo-new-seat.mjs`, `bin/paseo-bypass-watch`, `tests/test_paseo_new_seat_mode.py`, `tests/test_paseo_new_seat_probe.py`, `tests/test_paseo_bypass_watch.py`.
- **A5 NOT deleted: `skills/session-finder/prompt_line.py`.** `grep -rn prompt_line` shows `skills/session-finder/relay.py` still imports it (also `tests/test_relay_fallback.py`, `tests/test_gnu_tools_check.py`). It goes with E3's relay shim; for the lead.
- **A6 NOT deleted: `bin/paseo-set-model`, `bin/paseo-set-model.mjs`, `tests/test_paseo_set_model.py`** (section C).

## B. workspace-layout move

`skills/autorename/workspace-layout.md` (20 KB, almost all herdr pass mechanics) became `docs/workspace-layout.md`, about 25 lines: the Paseo naming (`<topic>-pw` workspace, `<name>-pt` tabs, at most 17 characters, workers as sub-agent tabs, close archives) plus the two rename commands. The herdr `-t/-p` scheme, configured workspaces, sleeper cycling and the `/autorename all` procedure are gone (git history has them). "Only `self-slash --finish` closes one" became "archive it (`paseo agent archive ID`)". AGENTS.md's pointer is left for E11 (ruling 12).

## C. paseo-set-model finding: RUNTIME CALL, kept

- `bin/route_agent.py:2120` (`apply_substrate`, behind `route_agent.py substrate --apply AGENT`) runs `bin/paseo-set-model list --json` and `... set ID MODEL` with `subprocess.run`; exit codes 1/3/4 pass through from the helper. A runtime call, not text.
- A second runtime caller: `bin/claude-fleet-governor:148,553,653` (`set_model_bin()` defaults to `paseo-set-model` beside the script; every model move goes through it).
- Decision: KEEP both files and `tests/test_paseo_set_model.py`; route_agent.py not edited. E7 decides the port.

## D. Reference edits in KEEP files

- `claude/hooks/context_size_nudge.py`: removed the self-slash host machinery (`_which`, `_self_slash_host`, `_paseo_cli`, `_can_self_slash`, `_paseo_finish_note`, `_step9_text`, `_successor_note`, `_session_successor`) and the Fable/quota-guard successor form (`QUOTA_GUARD_PATH`, `FABLE_MODEL`, `SUCCESSOR_*`, `_guard_level`, `_successor_target`), which existed only to build `self-slash --finish --successor`. One ask message remains; its in-context path now reads "run /compact yourself now, with a focus line"; the boundary message says "run the `handoff` skill and then tell the operator /new is ready". It does not claim `paseo send` runs a slash command. `_last_assistant_model` stays: `bin/context-watch:238` calls it. Behavior change to flag: a Fable session no longer gets a "successor" instruction.
- `claude/hooks/handoff-tools/tests/test_context_size_nudge.py` (the CI one) and `tests/test_context_size_nudge.py`: dropped the self-slash, host, finish-note and successor tests (about 450 lines) and their fixture lines; added `test_the_in_context_path_says_to_run_compact_yourself`.
- `skills/handoff/SKILL.md:345,348,459-464`: `paseo-new-seat` became `paseo run --no-wait --title ... --workspace ... "<prompt>"`; the "exit 4 modeApplied" note (a paseo-new-seat behavior) became "check with `paseo agent inspect` / `paseo agent mode ID --list`". Handoff's other self-slash and autorename lines are D3's (Wave 3b), untouched.
- `bin/claude-quota-guard:125-131,176,189-194` and `tests/test_claude_quota_guard.py:210,222-226`: the advice named `self-slash --finish --successor`; it now names `paseo run --no-wait --provider P --model M --thinking high --workspace "$PASEO_WORKSPACE_ID" "/baton <handoff path>"` then `paseo agent archive "$PASEO_AGENT_ID"`; "herdr or Orca" became "outside Paseo". Reference-only (ruling 11); the command is composed from the CLI source, not run against a daemon.
- `bin/claude-fleet-governor:620-625` (steer text) and `tests/test_claude_fleet_governor.py:396`: same replacement.
- `tests/test_fleet_launch_state.py`, `tests/test_fleet_paseo_rows.py`, `tests/test_fleet_tidy.py` (E3b's files): removed `import helm` and the 14 tests that exercised `helm.classify`/`render`/`cmd_keys` (collection failed once helm went); the remaining fleet tests pass. E3b deletes these files anyway.
- `tests/test_claude_identity.py`: dropped `test_autorename_uses_the_same_helper`.
- `bin/watch:85-88,100-104,758-780` and `tests/test_watch.py` (follow-up, coordinator order): `NEW_SEAT` is now a launcher prefix, default `[paseo, "run", "--no-wait"]` (`WATCH_NEW_SEAT` still replaces it with one program taking the same flags). Mapping: `--title`, `--provider`, `--model`, `--cwd`, `--workspace`, `--label`, `--json`, `--thinking`, `--mode` pass through unchanged; `--prompt P` became the trailing positional prompt; the JSON id is read from `agentId` (falling back to `id`). Not mappable: paseo-new-seat's `auto_accept` feature. claude now gets `--mode bypassPermissions` (added to `YOLO_MODE`, with codex `full-access`); other providers (omp) get no mode and the launch log carries a note naming `paseo agent mode ID --list`; the record field `auto_accept_verified` became `yolo_mode_set`. `--model` is omitted when the plan has none. Tests: the stub is unchanged, assertions read the prompt from `argv[-1]`; `bin/pytest -q tests/test_watch.py` 62 passed.
- `vendor/README.md`: helm row removed (2b).

## E. Merger's lines (not touched)

- **E1 README.md**: lines 50 (`bin/paseo-new-seat`), 54-61 and 173 (helm, `/helm-all`, `helm.py imports fleet`), 83 (`/helm-all` wrapper), 113 (helm row), 114 (autorename row), 246 (`docs/helm.md` link, now `docs/history/helm.md`).
- **E2 docs/skills.md**: lines 37 (autorename joined), 40 (`/helm-all`), 50 (autorename row), 64 (helm row); the `loose`, `handoff`, `watch` rows still mention self-slash.
- **E3 agents/claude/settings.json.tmpl:591**: the `autorename_nudge.py` UserPromptSubmit hook line. No skillOverrides or `skills/helm` entries exist in the template.
- **E4 .github/workflows/test.yml:118**: `tests/test_opencode_self_compact.py` in the `context-policy` job is now a missing file and will fail that job; remove it.
- **E5 AGENTS.md** (E11): the retirement box and Machine context name `self-slash` host branches, `autorename`'s herdr half (`herdr_place.py`, `/autorename all`), `skills/autorename/workspace-layout.md`, `skills/helm`, `paseo-new-seat`, `bin/paseo-self`; the `docs/helm.md` table row.
- **E6 live references to removed things in other slices' files**: `skills/watch/SKILL.md:8,21,73-78` (helm lead.md, paseo-new-seat, paseo-bypass-watch), `skills/session-handoff/SKILL.md`, `skills/baton/SKILL.md`, `skills/bigteam/SKILL.md:1057-1060`, `skills/loose/SKILL.md`, `skills/steps/SKILL.md`, `skills/teach/SKILL.md`, `skills/model-routing/SKILL.md`, `skills/effort-routing/SKILL.md`, `skills/session-finder/{SKILL.md,launch.py,relay.py,fleet.py,claude_identity.py}` (E3), `bin/seat-name:157`, `bin/load-watch:653`, `bin/rumination-watch`, `bin/skill-everywhere:264`, `tools/acp-run/acp-run:497-501,1154-1156,4400` (comments; the grok `autorename.json` sandbox deny and `tests/test_acp_run_grok_deny.py` are harmless), `tests/conftest.py:98-108` (scrubs identity env, sets `AUTORENAME_STATE_DIR`; harmless), `tests/test_launch_successor.py` (E3 deletes), and the D7 doc sweep (context-hygiene, model-routing, paseo-only-rearchitecture, tui-lessons-learned, upstream-issues, others).

## F. Operator steps (the Mac; not done)

- **F1 live hook line**: remove the `autorename_nudge.py` UserPromptSubmit entry from `~/.claude/settings.json` (C2 list, now four files). Until then each prompt runs a missing script under `hook-deadline`.
- **F2 dangling symlinks**: any of `~/.local/bin/{self-slash,paseo-self,paseo-new-seat,paseo-bypass-watch,opencode-self-compact}` and `skills/commands` links for `helm`, `helm-all`, `autorename` that `skill-everywhere` created under `~/.claude`, `~/.codex`, `~/.pi`, zcode and grok.
- **F3 lead's J2b edits**: Plektra (I4d) names `acp-dispatch, relay.py, autorename, self-slash`; paseo4herdr (I4e) names `acp-dispatch, relay.py, self-slash`. Replacement: self-slash becomes "`paseo run --provider P --model M --workspace ...` for a successor, `paseo agent archive $PASEO_AGENT_ID` to end, and a session runs its own `/compact`"; autorename becomes "`paseo agent update $PASEO_AGENT_ID --name N` and `paseo workspace rename $PASEO_WORKSPACE_ID N`".
- **F4**: install asks / questions-please and run them a day before the helm deletion merges (the brief's merge gate).

## G. Replacement sentences

- **helm**: `paseo permit ls` lists pending permissions; the asks or questions-please plugin is the operator's inbox; `/helm` and `/helm-all` are gone.
- **self-slash**: a Claude session issues its own `/compact`; the operator types `/new` after a handoff; a successor is `paseo run ...` then `paseo agent archive "$PASEO_AGENT_ID"`; `$PASEO_AGENT_ID` replaces `bin/paseo-self`.
- **autorename**: `paseo workspace rename "$PASEO_WORKSPACE_ID" "<name>"`. **Correction to research item 5: an agent-title rename exists**: `paseo agent update ID --name "<name>"` (also `--label`, `--thinking`), read in `packages/cli/src/commands/agent/index.ts` and `update.ts` of the Paseo 0.15.3 clone at `/tmp/claude-0/ps/src`; verified from source, not run against a daemon. The 20-line helper was not written.
- **paseo-new-seat**: `paseo run --provider P --model M --title T [--thinking X] [--mode M] [--workspace ID] "<prompt>"`.
- **paseo-bypass-watch**: `paseo agent mode ID --list`, `paseo agent mode ID bypass|plan`.
- **PR 294's stagger rule, for E11's orchestration-practices rewrite** (from the deleted `skills/helm/lead.md`, section 5): keep sends to a working Claude Paseo agent to one at a time, each gated in the relay call itself (`--idle 1800`, run in the background), because Paseo replaces the agent's current turn when a steer is declined, for example during compaction; an `--idle` timeout sent nothing, so retry next round.

## H. Tests and baseline diff

- Targeted: `tests/test_context_size_nudge.py` + `tests/test_context_watch.py` + `tests/test_bin_modes.py` 172 passed; `claude/hooks/handoff-tools/tests/test_context_size_nudge.py` 49 passed (run separately, as CI does: the shared basename collides in one pytest run and breaks a bare `bin/pytest -q` with no path); `tests/test_claude_quota_guard.py` 282 passed; quota guard + fleet governor together 376 passed, 2 skipped; the four fleet files 76 passed.
- Full: `bin/pytest -q -p no:cacheprovider tests` (31 min): **92 failed, 10,128 passed, 52 skipped**, against the baseline 166 failed, 10,141 passed. Compared by test id with `docs/slim/baseline.md`: 90 are baseline failures (the self-slash and helm/autorename rows are gone with their files). Two are not in the baseline: `tests/test_relay_card_alert.py::TestCardAlert::test_a_message_that_waited_past_the_threshold_pings_once_naming_target_card_sender_and_message` and `::test_a_new_card_beside_one_already_told_is_told_once`; both pass when the file is run alone, so they are load/timing flakes in a full run (the file touches nothing deleted here). The baseline list was matched from its bulleted rows (135 ids for 166 failures).

## I. Lost on purpose

- helm: the single-window triage view, ranking by work unlocked, `/helm lead` and `/watch lead`, the `helm.py keys` press-a-key path.
- self-slash: queued `/compact`, `/new`, `/clear`, `/rename` into another host's input; `--finish --successor` archive-and-restart in one call; the reset-gap guard; `/baton` queued into the fresh session automatically.
- context_size_nudge: the Fable/quota-guard successor instruction; herdr/Orca/Paseo host-specific wording.
- autorename: automatic session titling and tab placement (`autorename_nudge.py`), `/autorename`, the Pi/omp/OpenCode/zcode/grok title bridges, the herdr placement pass, `relocate-pane.sh`.
- paseo-new-seat: the auto-accept-from-first-tool-call guarantee and its probe; the `modeApplied` exit-4 report.
- paseo-bypass-watch: the watcher that re-armed bypass on seats that lost it (now manual `paseo agent mode ID bypass`).
- opencode-self-compact, paseo-self: wrappers with no remaining caller.
