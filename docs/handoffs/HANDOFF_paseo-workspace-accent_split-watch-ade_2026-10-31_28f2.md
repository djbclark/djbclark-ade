---
schema_version: 1
handoff_id: 28f2
parent_handoff_ids: []
lineage: none
chain: [paseo-workspace-accent]
repo: djbclark-ade
workspace: djbclark-ade-watch-transfer-wt
branch: docs/watch-split-handoff
head_sha: dff2c96d4dc8f849533b354037211f2a335d165e
created_at: 2026-10-31T18:42:29.062607-04:00
writer: codex
---
# Handoff — Split Paseo watcher and ADE hardening

## Task
Split continuation authorized by djbclark on 2026-10-31: new Paseo watch tab in workspace watch, separate ADE tab in the existing watcher-hardening worktree. Predecessor c7f647a8-ca10-4552-96c7-31dede86d602 retires ONLY after both top-level successors answer and accept peer-notice duties. The roles are durable addresses; IDs are instances.

## Context and current state
Original excessive watcher churn fixed and activated by merged PR https://github.com/djbclark/djbclark-ade/pull/192 (2c009ed8d8094f44c50323b5b24729de37c5ef4e). Installed Paseo collects idle runtimes after 60 minutes, leaving nonarchived status closed and the persisted provider conversation. Closed is retained; a real relay resumes it. No recurring model probes. Full Linux suite 6840 passed, 26 skipped, 1626 subtests; original focused134, review clean.
User /loose decisions: A1 schedule one-shot real collection/retention/relay-resume validation; A2 fix three hardening cases; A3 append audit errata preserving original report and partial status. A3 DONE in /Users/djbclark/.local/state/bigteam/watch-idle-recovery-20261031/investigate-reroute-1-report.md. Original agy quota stops were explicitly approved for reroute; rerouted work completed and old resume timers canceled. Do not rerun paid results.
A2 implemented, PR https://github.com/djbclark/djbclark-ade/pull/195 OPEN at dfc045be542a88d9ad7587d3564759dae4fcec3d; branch fix/watch-hardening; clean worktree /Users/djbclark/src/djbclark-ade-watch-hardening-wt. Primary reference checkout /Users/djbclark/src/djbclark-ade was clean master dff2c96d4dc8f849533b354037211f2a335d165e at snapshot; other sessions can advance it. Never edit it. No unresolved writer in hardening worktree. Claim watch-hardening-20261031 currently owned by predecessor; wait for release and reclaim under own ID before any edit/test/commit.

## Relevant files and evidence
Hardening scratch /Users/djbclark/.local/state/bigteam/watch-hardening-20261031: build-report.md, adversary-report.md (round4 APPROVE exact dfc head), pr-body.md, pr195-final-summary.json (not yet present), pr195-final-* waiter outputs. Local review /Users/djbclark/.local/state/local-review/djbclark__djbclark-ade-pr195-dfc045be542a88d9ad7587d3564759dae4fcec3d.json CLEAN zero P0-P3. PR body already includes exact-head adversary marker and local summary. 60 full watcher tests passed, then four parametrized no-title real/dry-run cases passed (62 unique total). Linux full CI pending; inspect live. Changed bin/watch, tests/test_watch.py, skills/watch/SKILL.md, skills/bigteam/SKILL.md, CHANGELOG.md. Generated startup config rewrites saved privately in startup-config-changes.patch, restored before commits. Do not stage these incidental files.
Three cases: reuse lifecycle probe and fail unknown; protect forced replaced holder when old-only probe fails; include background nonarchived agents. Adversary additionally fixed unreadable title-list generation reuse (memo successful snapshot, otherwise refuse without allocation) and next_tag's dry-run caller. Exhaustive callers, GNU/Python excerpts, checking prep exits, one-shot launchd semantics added to bigteam instructions.
Audit /Users/djbclark/.local/state/bigteam/watch-idle-recovery-20261031/loose-audit-20261031.md and loose-decisions.json. Live installed-collector proof live-collector-evidence.txt. Errata appended because stale ~/src/paseo source falsely suggested no collector; retained partial research status intentionally, no rerun.

## Watcher responsibilities
Read /Users/djbclark/src/djbclark-ade/skills/paseowatch/SKILL.md section1; register OWN PASEO_AGENT_ID under assigned watch paseo generation; channel test; adopt chain paseo-workspace-accent at /Users/djbclark/.local/state/handoffs/chains/paseo-workspace-accent/SESSION_LOG.md (pointer /Users/djbclark/.local/state/handoffs/paseo/main/SESSION_LOG.md). Preserve watch ownership and upstream state, transfer ADE work to ADE peer, no cross-chain pointer theft. Work cwd is shared reference ADE, Paseo domain uses absolute /Users/djbclark/src/paseo and git -C. Never edit shared checkouts. New upstream events handled through /bigteam, prepare drafts only, exact text approval required before posting upstream. No pending upstream decision was authorized for posting. Never restart daemon6767, never full Paseo suite.
A1 old one-shot target predecessor: label com.djbclark.paseo-soak.c7f647a8, directory /Users/djbclark/.local/state/bigteam/watch-idle-recovery-20261031/soak, observe.py/spec.json/report.json/plist. Last report waiting-for-collection, probe_attempts0. On role transfer it should exit inconclusive-role-transferred. Preserve it; cleanup loaded job only after exit. Start fresh six-hour one-shot against OWN id/provider persisted conversation, unique token and separate output directory, copying observe.py and adjusting spec. Wait for true daemon-log collection AFTER baseline plus closed; run watch up paseo to prove same holder/sequence/provider and still closed; exactly ONE private relay probe; write atomic receipt on request. Do not read timeline/logs RPC before collection because it hydrates. Inspect is okay. No /loop or CronCreate. Existing script does all checks. Use launchctl bootstrap explicit RunAtLoad=true KeepAlive=false plist with no intervals; launchctl submit would restart the job repeatedly. Verify no keepalive. Final evidence must distinguish passed, failed and inconclusive. Once scheduled, stop and wait for real events.

## ADE responsibilities and next action
FIRST inspect live PR195 checks and exact-head local/adversary results. Existing model-free pr-wait may still be running (old tool session25479), summary path above. It is not promised to survive retirement; if necessary rearm bin/pr-wait 195 --repo djbclark/djbclark-ade --head dfc045be542a88d9ad7587d3564759dae4fcec3d --local-codex --adversary-required --out /Users/djbclark/.local/state/bigteam/watch-hardening-20261031/pr195-final --timeout 2400 --json after confirming no writer. Do not rerun completed reviews.
CI completion notifier label com.djbclark.watch-hardening-ready.pr195: verification-wake.py, verification-wake.json, verification-wake-result.json, plist in hardening scratch. Currently waits on summary/local files, reads CURRENT watcher as destination. Predecessor will retarget to ADE successor; verify target/record. Marker verification-wake-attempted forbids duplicate sends. If retargeting needed, preserve head/deadline/results, stop/restart only cheap notifier BEFORE attempted marker; no paid run cancellation. KeepAlive false explicit bootstrap.
If summary merge_ready true and head still matches, gh pr merge 195 --repo djbclark/djbclark-ade --squash --match-head-commit dfc045be542a88d9ad7587d3564759dae4fcec3d. Operator authorized completion/merge/activation via fix request and standing ADE rule. Then fetch origin, serialize clean primary master ff-only to published master containing squash commit; do not overwrite other edits or require primary still at old base. Verify watch dry-run/activation. Cleanup merged worktree only when no processes/writers and release/mark claim merged; refresh src aliases with just -f /Users/djbclark/s/justfile. If CI/review finds problems, fix under claimed task workspace, focused tests through bg/bin/pytest, Linux CI and exact-head independent/adversary review, proper marker. Do not broaden scope.
ADE create own chain watch-hardening-20261031 with worktree primary and ADE reference as SIDE; do not steal paseo/main or ADE/root pointers. Read session-handoff writer protocol. This handoff documentation branch docs/watch-split-handoff is separate from reviewed PR195 to preserve head. It is pushed; ADE successor can open documentation-only PR with required reviews if useful, or retain published branch; don't silently discard durable handoff. Documentation workspace /Users/djbclark/src/djbclark-ade-watch-transfer-wt claim watch-transfer-20261031 belongs predecessor until released.

## Durable peer list and receipt duty
Predecessor ID c7f647a8-ca10-4552-96c7-31dede86d602, title watch paseo 1g (may be renamed x), workspace wks_9061125847f43414/watch. New watcher and new ADE peer IDs will be published atomically in /Users/djbclark/.local/state/bigteam/watch-transfer-20261031/seats.json. Successors must read it after launch, accept peer-notice duty by named acknowledgment to predecessor through skills/session-finder/relay.py; use own real identity. Each successor tells the other its role, ID, title, workspace, task dir and chain, that it supersedes predecessor for that role; ask a named ack and verify delivered or ack. Predecessor sends no external location notices. No other still-running child/sibling owns unfinished work; original build/review slices finished with reports. Do not transfer all machine expectations: predecessor is non-Claude Paseo and lacks finished evidence, transfer-expectations refuses. Carry any exact owned outstanding receipts in runtime seats record; do not hand-edit relay expectation records, do not resend queued/unverified messages. First-contact delivery proof and returned ack required.

## Acceptance and constraints
Both successors top-level ParentAgentId:null, intended cwd/provider/model/mode, answered at least one turn. Watcher role/channel and Tier1 new owner verified. ADE owns separate continuation and sole-writer claim. CI notice routes ADE; real-soak restarted on new watcher; old result explicitly inconclusive. Peer duties accepted. Only then predecessor agent archived (never workspace); user intentionally requested this split. No recurring model wakes, no /loop/CronCreate, no unapproved upstream posts, no secret/config-value output, no lost reports. Use existing ADE tooling/graft before discovery. Commit/push own changes using git-commit-own explicit pathspecs; master only via PR squash exact reviewed head. All code edits/tests in claimed worktree. Hermes ping once per completion/needs-user event. Return concise labelled updates.

## Decisions

- [ruling] "start 2 new tabs, one in this workspace to be the new watch paseo xx tab, and the other in the appropriate other workspace to do the other things" (djbclark, 2026-10-31).
- [decision] Separate watcher and ADE continuation; rejected: keeping both roles in the old watcher; because operator requested two successors.
- [decision] Restart the one-shot with a fresh successor baseline; rejected: counting an agent replacement as retention; because the proof requires one unchanged conversation.

## Relations

No deterministic Tier 2 parent for this split. Existing Paseo contribution handoff remains referenced by its owned Tier1 chain.

## Detached jobs

No unfinished paid model slices. Two explicit non-keepalive launchd jobs described above persist independently. Existing pr-wait process is not promised to survive; rearm only the model-free waiter as needed. CI stays running.

## Validation

Exact source states, tests, review head, dirty state and failed approaches are recorded above. This handoff itself is documentation only; no tests run for it. No credential values included. Next action: launch and verify the two successors, then transfer the role and claims.
