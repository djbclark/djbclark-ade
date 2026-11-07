# Test baseline (Wave 0 B4), 2026-11-06

Run in the slim-down lead's cloud container (Linux, no `g*` wrappers, no Mac state) at master `da6b2e7d` plus the docs-only slim branch, with `uv run --with pytest --with pytest-timeout --with pyyaml --with 'agent-client-protocol>=0.9,<1.0' python -m pytest tests/ -q --timeout=120`.

Result: **166 failed, 10,141 passed, 54 skipped, 2,106 subtests passed, 3,029 s (50 min 29 s)**, rc=1.

These failures predate every slim-down change. A slice that deletes a test file below removes its row; a slice must not be blamed for a failure listed here, and must not "fix" one by deletion unless the file is a DELETE target.

## Known flakes (added 2026-11-06 by the lead)

- `tests/test_relay_card_alert.py`: intermittent under load at base fb3b9de (5 of 6 runs in a clean worktree, three different tests: `TestBusyAlert::test_a_message_past_the_threshold_gets_one_notice_and_one_ping_however_many_looks` among them). Deleted by E3 (Wave 3). A failure here is not a regression.

## Failures by test file

| Test file | Failed | First failing test |
|---|---|---|
| `tests/test_ade_git_hooks.py` | 45 | `test_ref_guard_is_argv_independent[fetch` |
| `tests/test_self_slash_prompt_wait.py` | 15 | `PromptWaitTests::test_a_blocked_pane_with_a_stale_prompt_row_gets_nothing_typed` |
| `tests/test_self_slash.py` | 14 | `SelfSlashPaseoTests::test_archive_refusal_is_logged_and_never_forced` |
| `tests/test_self_slash_codex.py` | 12 | `CodexWaiterTests::test_a_fresh_session_after_new_is_read_from_its_own_rollout` |
| `tests/test_ade_git_guard.py` | 10 | `test_reset_by_creation_cannot_overwrite_a_claimed_branch[worktree` |
| `tests/test_bigteam_prune.py` | 8 | `test_ordinary_network_remotes_do_not_keep_a_clone[https://github.com/o/r.git]` |
| `tests/test_local_review.py` | 6 | `test_a_child_started_just_before_codex_exits_is_killed_without_lsof_or_a_snapshot` |
| `tests/test_acp_dispatch.py` | 6 | `TestDispatch::test_happy_path_writes_brief_record_done_and_exits_0` |
| `tests/test_wait_file.py` | 3 | `test_ready_when_non_empty` |
| `tests/test_acp_run_git_identity.py` | 3 | `TestGitIdentityGuard::test_foreign_local_identity_is_refused_even_with_no_verify` |
| `tests/test_session_relay.py` | 2 | `TestRelayRules::test_queue_hint_is_not_delivery_while_the_text_is_still_in_the_box` |
| `tests/test_deadline_wrappers.py` | 2 | `test_wait_registers_beats_and_deregisters_on_a_normal_end[dispatch]` |
| `tests/test_ade_scan_state.py` | 2 | `test_an_edited_tracked_file_in_a_readable_but_unsearchable_directory_is_not_clean` |
| `tests/test_acp_dispatch_quota_d2.py` | 2 | `TestExit0Quota::test_a_done_report_never_auto_resumes` |
| `tests/test_web_get.py` | 1 | `test_crwl_gets_js_delay` |
| `tests/test_prior_art_nudge.py` | 1 | `test_unwritable_state_dir_is_silent` |
| `tests/test_launch_turns.py` | 1 | `TestDetachedInteractive::test_detached_session_survives_turn_one_and_ends_on_exit` |
| `tests/test_failover.py` | 1 | `test_ask_acp_runs_in_empty_dir` |
| `tests/test_acp_dispatch_reap.py` | 1 | `TestReap::test_done_report_with_marker_finalizes_as_done` |

## Full list

- `tests/test_acp_dispatch.py::TestDispatch::test_happy_path_writes_brief_record_done_and_exits_0`
- `tests/test_acp_dispatch.py::TestDispatch::test_partial_report_exits_1`
- `tests/test_acp_dispatch.py::TestFailureNote::test_rearm_waiter_exits_with_the_check_verdict`
- `tests/test_acp_dispatch.py::TestSliceControls::test_session_id_is_saved_while_fake_agent_is_running`
- `tests/test_acp_dispatch.py::TestSliceControls::test_wrapup_report_is_delivered_but_not_a_clean_success`
- `tests/test_acp_dispatch.py::TestAiuseNoteExhausted::test_quota_checkpointed_vs_plain_no_report`
- `tests/test_acp_dispatch_quota_d2.py::TestExit0Quota::test_a_done_report_never_auto_resumes`
- `tests/test_acp_dispatch_quota_d2.py::TestEscalation::test_partial_records_get_the_hint_too_but_quota_ones_do_not`
- `tests/test_acp_dispatch_reap.py::TestReap::test_done_report_with_marker_finalizes_as_done`
- `tests/test_acp_run_git_identity.py::TestGitIdentityGuard::test_foreign_local_identity_is_refused_even_with_no_verify`
- `tests/test_acp_run_git_identity.py::TestGitIdentityGuard::test_hook_path_with_an_apostrophe_still_runs`
- `tests/test_acp_run_git_identity.py::TestGitIdentityGuard::test_nested_launch_repairs_stripped_parameters`
- `tests/test_ade_git_guard.py::test_reset_by_creation_cannot_overwrite_a_claimed_branch[worktree add -B cbr {W3}]`
- `tests/test_ade_git_guard.py::test_reset_by_creation_cannot_overwrite_a_claimed_branch[worktree add -Bcbr {W3}]`
- `tests/test_ade_git_guard.py::test_reset_by_creation_cannot_overwrite_a_claimed_branch[checkout -B cbr]`
- `tests/test_ade_git_guard.py::test_reset_by_creation_cannot_overwrite_a_claimed_branch[checkout -B cbr main]`
- `tests/test_ade_git_guard.py::test_reset_by_creation_cannot_overwrite_a_claimed_branch[checkout -Bcbr]`
- `tests/test_ade_git_guard.py::test_reset_by_creation_cannot_overwrite_a_claimed_branch[switch -C cbr]`
- `tests/test_ade_git_guard.py::test_reset_by_creation_cannot_overwrite_a_claimed_branch[switch -Ccbr main]`
- `tests/test_ade_git_guard.py::test_reset_by_creation_cannot_overwrite_a_claimed_branch[switch --force-create cbr]`
- `tests/test_ade_git_guard.py::test_reset_by_creation_cannot_overwrite_a_claimed_branch[switch --force-create=cbr]`
- `tests/test_ade_git_guard.py::test_reset_by_creation_cannot_overwrite_a_claimed_branch[switch --force-c cbr main]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[fetch . main:heads/cb]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[fetch . main:cb]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[fetch --multiple --no-multiple . main:cb]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[pull --no-rebase . main:cb]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[remote -v update up]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[-c fetch.parallel=4 fetch --all]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[--attr-source HEAD branch -f cb main]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[--shallow-file /dev/null fetch origin +main:cb]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[update-ref refs/heads/cb main]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[update-ref -d refs/heads/cb]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[update-ref --stdin]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[branch -D cb]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[branch -f cb main]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[branch -m cb cb9]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[branch -M cb cb9]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[symbolic-ref refs/heads/cb refs/heads/main]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[push . main:cb]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[push origin main:cb]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[checkout -B cb main]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[switch -C cb main]`
- `tests/test_ade_git_hooks.py::test_ref_guard_is_argv_independent[worktree add -B cb ../wtx main]`
- `tests/test_ade_git_hooks.py::test_refusal_names_owner_claim_and_alternative_and_is_logged`
- `tests/test_ade_git_hooks.py::test_a_harness_marker_without_a_claim_may_write_nothing_claimed[marker0]`
- `tests/test_ade_git_hooks.py::test_a_harness_marker_without_a_claim_may_write_nothing_claimed[marker1]`
- `tests/test_ade_git_hooks.py::test_a_harness_marker_without_a_claim_may_write_nothing_claimed[marker2]`
- `tests/test_ade_git_hooks.py::test_python_exit_77_is_the_only_refusal`
- `tests/test_ade_git_hooks.py::test_head_and_branch_moves_in_a_foreign_claimed_worktree_are_refused`
- `tests/test_ade_git_hooks.py::test_stash_in_a_linked_worktree_is_refused_even_for_its_owner_but_not_in_the_primary`
- `tests/test_ade_git_hooks.py::test_a_branch_checked_out_in_a_claimed_workspace_is_refused_by_name`
- `tests/test_ade_git_hooks.py::test_pack_refs_and_gc_beside_someone_elses_claim_are_not_refused`
- `tests/test_ade_git_hooks.py::test_install_keeps_an_existing_hook_as_pre_ade_and_runs_it_after_ours`
- `tests/test_ade_git_hooks.py::test_r10_f4_only_exit_77_refuses_and_the_pre_ade_chain_survives_a_crash`
- `tests/test_ade_git_hooks.py::test_r10_f3_a_forged_argv0_does_not_pass_for_pack_refs`
- `tests/test_ade_git_hooks.py::test_r10_f6_origin_is_what_git_says_whatever_its_spelling_in_the_config[comment]`
- `tests/test_ade_git_hooks.py::test_r10_f6_origin_is_what_git_says_whatever_its_spelling_in_the_config[quoted]`
- `tests/test_ade_git_hooks.py::test_r10_f6_origin_is_what_git_says_whatever_its_spelling_in_the_config[quoted-comment]`
- `tests/test_ade_git_hooks.py::test_r10_f6_origin_is_what_git_says_whatever_its_spelling_in_the_config[included]`
- `tests/test_ade_git_hooks.py::test_r11_f1_a_callers_config_never_rewrites_the_origin_the_claim_is_matched_against[dash-c]`
- `tests/test_ade_git_hooks.py::test_r11_f1_a_callers_config_never_rewrites_the_origin_the_claim_is_matched_against[count-env]`
- `tests/test_ade_git_hooks.py::test_r11_f1_a_callers_config_never_rewrites_the_origin_the_claim_is_matched_against[parameters-env]`
- `tests/test_ade_git_hooks.py::test_r11_f1_a_callers_config_never_rewrites_the_origin_the_claim_is_matched_against[global-file]`
- `tests/test_ade_git_hooks.py::test_r11_f2_an_origin_question_that_fails_only_for_the_hook_does_not_switch_the_claim_rule_off`
- `tests/test_ade_git_hooks.py::test_r11_f3_an_empty_argv0_does_not_shift_the_parse_into_a_pack_refs_exemption`
- `tests/test_ade_git_hooks.py::test_r11_f6_the_two_config_pairs_acp_run_puts_in_every_agents_environment_are_allowed`
- `tests/test_ade_git_hooks.py::test_acp_parameter_transport_is_allowed_but_extra_hooks_and_cli_copies_are_not`
- `tests/test_ade_scan_state.py::test_an_edited_tracked_file_in_a_readable_but_unsearchable_directory_is_not_clean`
- `tests/test_ade_scan_state.py::test_an_unreadable_directory_under_an_untracked_one_makes_the_embedded_search_incomplete`
- `tests/test_bigteam_prune.py::test_ordinary_network_remotes_do_not_keep_a_clone[https://github.com/o/r.git]`
- `tests/test_bigteam_prune.py::test_https_remote_is_not_affected_by_the_ssh_override`
- `tests/test_bigteam_prune.py::test_http_address_or_proxy_override_keeps_a_network_remote[http.curloptResolve-example.org:8080:127.0.0.1]`
- `tests/test_bigteam_prune.py::test_http_address_or_proxy_override_keeps_a_network_remote[http.https://example.org/.curloptResolve-example.org:443:127.0.0.1]`
- `tests/test_bigteam_prune.py::test_http_address_or_proxy_override_keeps_a_network_remote[http.proxy-http://127.0.0.1:3128]`
- `tests/test_bigteam_prune.py::test_http_address_or_proxy_override_keeps_a_network_remote[remote.web.proxy-http://127.0.0.1:3128]`
- `tests/test_bigteam_prune.py::test_http_address_or_proxy_override_keeps_a_network_remote[core.gitProxy-nc]`
- `tests/test_bigteam_prune.py::test_unrelated_http_config_does_not_keep_a_network_remote`
- `tests/test_deadline_wrappers.py::test_wait_registers_beats_and_deregisters_on_a_normal_end[dispatch]`
- `tests/test_deadline_wrappers.py::test_expiry_kills_the_waiters_own_group_with_its_own_exit_code[dispatch]`
- `tests/test_failover.py::test_ask_acp_runs_in_empty_dir`
- `tests/test_launch_turns.py::TestDetachedInteractive::test_detached_session_survives_turn_one_and_ends_on_exit`
- `tests/test_local_review.py::test_a_child_started_just_before_codex_exits_is_killed_without_lsof_or_a_snapshot`
- `tests/test_local_review.py::test_a_hung_codex_is_killed_with_its_group_and_the_run_is_failed`
- `tests/test_local_review.py::test_a_child_that_outlives_a_codex_that_exited_is_killed_too`
- `tests/test_local_review.py::test_a_tool_command_in_a_session_of_its_own_is_killed_too`
- `tests/test_local_review.py::test_a_detached_tool_working_outside_the_worktree_is_found_while_codex_is_alive_and_killed`
- `tests/test_local_review.py::test_a_run_that_is_terminated_files_failed_removes_its_worktree_and_kills_codex`
- `tests/test_prior_art_nudge.py::test_unwritable_state_dir_is_silent`
- `tests/test_self_slash.py::SelfSlashPaseoTests::test_archive_refusal_is_logged_and_never_forced`
- `tests/test_self_slash.py::SelfSlashPaseoTests::test_finish_and_quit_are_refused_for_a_watch_holder`
- `tests/test_self_slash.py::SelfSlashPaseoTests::test_holder_prefix_matches_like_bin_watch`
- `tests/test_self_slash.py::SelfSlashPaseoTests::test_l4_control_characters_cannot_forge_a_log_line`
- `tests/test_self_slash.py::SelfSlashPaseoTests::test_l6_only_idle_running_initializing_pass_and_late_errors_are_seen`
- `tests/test_self_slash.py::SelfSlashPaseoTests::test_live_lock_refuses_a_second_lifecycle`
- `tests/test_self_slash.py::SelfSlashPaseoTests::test_lock_covers_the_whole_clear_then_baton_chain`
- `tests/test_self_slash.py::SelfSlashPaseoTests::test_lock_naming_a_live_pid_that_is_not_self_slash_is_stale`
- `tests/test_self_slash.py::SelfSlashPaseoTests::test_lock_with_a_different_start_time_is_stale`
- `tests/test_self_slash.py::SelfSlashPaseoTests::test_quit_and_exit_take_the_lifecycle_lock_on_orca`
- `tests/test_self_slash.py::SelfSlashPaseoTests::test_r2_l2_an_inspect_failing_after_a_good_look_is_exit_11`
- `tests/test_self_slash.py::SelfSlashPaseoTests::test_stale_lock_is_cleared`
- `tests/test_self_slash.py::SelfSlashPaseoTests::test_successor_run_failure_exits_11_and_archives_nothing`
- `tests/test_self_slash.py::SelfSlashPaseoTests::test_successor_takes_the_lifecycle_lock`
- `tests/test_self_slash_codex.py::CodexWaiterTests::test_a_fresh_session_after_new_is_read_from_its_own_rollout`
- `tests/test_self_slash_codex.py::CodexWaiterTests::test_a_working_status_after_the_submit_is_expected_and_still_a_receipt`
- `tests/test_self_slash_codex.py::CodexWaiterTests::test_an_identical_older_message_in_a_session_that_appears_after_the_submit_is_not_a_receipt`
- `tests/test_self_slash_codex.py::CodexWaiterTests::test_claude_keeps_slash_baton_and_refuses_the_codex_skill_syntax`
- `tests/test_self_slash_codex.py::CodexWaiterTests::test_detached_waiter_has_its_own_process_session`
- `tests/test_self_slash_codex.py::CodexWaiterTests::test_exact_user_message_in_the_rollout_is_the_receipt`
- `tests/test_self_slash_codex.py::CodexWaiterTests::test_explicit_literal_dollar_baton_works_in_parent_and_detached_child`
- `tests/test_self_slash_codex.py::CodexWaiterTests::test_legacy_slash_baton_is_rewritten_once_keeping_every_suffix_byte`
- `tests/test_self_slash_codex.py::CodexWaiterTests::test_new_then_default_followup_is_one_dollar_baton_receipted_in_the_rollout`
- `tests/test_self_slash_codex.py::CodexWaiterTests::test_only_the_exact_baton_command_name_is_rewritten_and_other_dollar_words_are_refused`
- `tests/test_self_slash_codex.py::CodexWaiterTests::test_the_receipt_is_the_whole_text_byte_for_byte_so_a_path_with_runs_of_spaces_is_not_folded`
- `tests/test_self_slash_codex.py::CodexWaiterTests::test_waiter_normalization_is_idempotent_and_takes_the_text_form_too`
- `tests/test_self_slash_prompt_wait.py::PromptWaitTests::test_a_blocked_pane_with_a_stale_prompt_row_gets_nothing_typed`
- `tests/test_self_slash_prompt_wait.py::PromptWaitTests::test_a_busy_pane_that_never_shows_a_prompt_ends_at_the_wait_limit_sending_nothing`
- `tests/test_self_slash_prompt_wait.py::PromptWaitTests::test_a_live_prompt_more_than_12_rows_above_the_bottom_is_found`
- `tests/test_self_slash_prompt_wait.py::PromptWaitTests::test_a_pane_busy_for_longer_than_the_idle_polls_is_waited_for`
- `tests/test_self_slash_prompt_wait.py::PromptWaitTests::test_a_pane_the_herdr_status_calls_working_is_waited_for`
- `tests/test_self_slash_prompt_wait.py::PromptWaitTests::test_a_slash_menu_row_is_not_an_empty_prompt`
- `tests/test_self_slash_prompt_wait.py::PromptWaitTests::test_a_spinner_more_than_12_rows_up_does_not_make_an_unreadable_status_pane_busy`
- `tests/test_self_slash_prompt_wait.py::PromptWaitTests::test_a_stale_empty_prompt_above_a_shell_prompt_is_never_typed_into`
- `tests/test_self_slash_prompt_wait.py::PromptWaitTests::test_an_answer_option_row_is_not_an_empty_prompt`
- `tests/test_self_slash_prompt_wait.py::PromptWaitTests::test_an_empty_marker_row_without_its_box_far_above_is_not_the_prompt`
- `tests/test_self_slash_prompt_wait.py::PromptWaitTests::test_an_idle_pane_with_no_prompt_gives_up_after_a_few_polls_sending_nothing`
- `tests/test_self_slash_prompt_wait.py::PromptWaitTests::test_an_idle_pane_with_spinner_text_in_its_last_rows_is_not_busy_either`
- `tests/test_self_slash_prompt_wait.py::PromptWaitTests::test_spinner_text_in_the_scrollback_of_an_idle_pane_does_not_hold_it`
- `tests/test_self_slash_prompt_wait.py::PromptWaitTests::test_the_busy_budget_is_wall_clock_time_not_five_seconds_a_loop`
- `tests/test_self_slash_prompt_wait.py::PromptWaitTests::test_the_wide_window_follows_self_slash_read_lines`
- `tests/test_session_relay.py::TestRelayRules::test_queue_hint_is_not_delivery_while_the_text_is_still_in_the_box`
- `tests/test_session_relay.py::TestRelayRules::test_text_left_in_the_box_gets_another_enter`
- `tests/test_wait_file.py::test_ready_when_non_empty`
- `tests/test_wait_file.py::test_match_waits_for_line`
- `tests/test_wait_file.py::test_empty_done_marker_is_ready`
- `tests/test_web_get.py::test_crwl_gets_js_delay`
