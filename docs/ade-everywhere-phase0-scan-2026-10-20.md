# Phase 0 scan: bigteam task dirs and Orca / cow checkouts (2026-10-20)

Inside the tool: `du -sk <dir>`; `rg -l -F -w --no-messages -g '!<exclude>' -- <task> <roots>`; per checkout `git -C <path>` (in the run as executed, with `GIT_OPTIONAL_LOCKS=0` and the caller's other `GIT_*` variables; now `git --no-optional-locks -c core.fsmonitor=false -c core.hooksPath=/dev/null -c protocol.ext.allow=never` with every `GIT_*` variable dropped, preceded by `config --list --show-scope --includes -z`): `rev-parse --abbrev-ref HEAD`, `status --porcelain`, `rev-parse --abbrev-ref --symbolic-full-name @{u}`, `rev-list --count @{u}..HEAD`, `rev-list --count HEAD --not --remotes=origin`, `stash list`, `remote get-url origin`, `ls-remote --heads origin` (now `ls-remote --heads -- <url>` from an empty directory outside any repository), `rev-list --count HEAD --not --remotes=origin <tip>`, `fetch --quiet origin <branch>` (only when the tip's objects are missing). `bin/ade-scan-state ... --markdown` prints the raw tables; this document's tables and prose come from `bin/ade-scan-state-doc`. Before the run: `ls -la ~/orca/projects`, `ls -A ~/orca/workspaces/*`, `fd -H .git -d 4 ~/orca/workspaces`, `git -C ~/src/one-offs remote -v` (no output: no remote), and `du -sk ~/.local/state/bigteam/adhoc-2026-10-18/hm-promo-rehearsal/*` for 1.1. **Regeneration note (2026-10-20):** the JSON of the run above (`scan.json`, 04:38:17) was overwritten by mistake in the scratch dir while this document was being revised and is not recoverable, so the tables here are the text rendered from it, committed as written; `bin/ade-scan-state-doc` was checked against the slice's earlier JSON from 04:31:38 (same layout, different numbers) and the prose revised in this commit was edited into the document to match its output.

Phase 0, slice 3 of [ade-everywhere-proposal.md](ade-everywhere-proposal.md) §8 item 1 (djbclark, 2026-10-20: "Scan `~/.local/state/bigteam` and the Orca checkouts for unique reports, dirty trees, untracked files and unpushed commits and capture them. Nothing is deleted."). Nothing was moved, committed, stashed, checked out or deleted outside this pasture. The network calls were `git ls-remote --heads origin` and, only where an origin tip could not be compared with HEAD, `git fetch origin <branch>`: that run used the first version of `--fetch`, which downloaded the branch's objects but also rewrote `FETCH_HEAD`, may have updated `refs/remotes/origin/<branch>` and may have run auto-maintenance in that checkout (the tool now writes no refs, section 5). The first version also ran git inside each checkout with that checkout's own config in force, so a `core.fsmonitor` or `remote.*.uploadpack` line there would have run (the tool now skips such a checkout, section 5); whether any scanned checkout carried one was not checked (section 4). Numbers below come from one real run of [`bin/ade-scan-state`](../bin/ade-scan-state) at 2026-10-20T04:38:17-0400 (commands in section 5); rerun it for a fresh scan. This document is rendered from that run's JSON by [`bin/ade-scan-state-doc`](../bin/ade-scan-state-doc). Slice 1 context: [ade-everywhere-inventory-2026-10-20-stores.md](ade-everywhere-inventory-2026-10-20-stores.md) §2 rows for bigteam and Orca, and the Orca section of [ade-everywhere-inventory-2026-10-19.md](ade-everywhere-inventory-2026-10-19.md).

## 0. Summary

| Measure | Value |
|---|---|
| bigteam task dirs scanned | 134 (59.9G by `du -sk`) |
| verdict `unique` | 29 dirs, 45.6 MiB whole-dir |
| verdict `mixed` | 12 dirs, 771 MiB whole-dir |
| verdict `scratch` | 93 dirs, 59.1 GiB whole-dir |
| bytes `unique` (report files no other document references) | 1,295,049 B (1.24 MiB) |
| bytes `scratch` (everything else under bigteam) | 64,340,081,975 B (59.9 GiB) |
| job records with no `closed` key | 75 in 29 task dirs |
| git checkouts scanned | 23 |
| checkouts, verdict `clean and pushed` | 5 |
| checkouts, verdict `unpushed commits` | 1 |
| checkouts, verdict `orphan branch` | 6 |
| checkouts, verdict `dirty` | 11 |
| checkouts with unpushed work (unpushed commits or orphan branch) | **7** |
| checkouts with untracked non-ignored paths | 12 |
| checkouts with a stash | 1 |

The three items that most need a human decision:

1. **`~/src/one-offs` has no `origin` remote at all** and 37 commits (plus the Orca worktree `~/orca/workspaces/one-offs/Hermes`, 2 commits, same repo). Nothing outside this Mac holds them; the only copy is this disk. Decide where it is hosted (a new repo needs the where-does-it-go question, rule 23) or take a bundle (section 3).
2. **Where the 41 `unique`/`mixed` bigteam report sets are preserved** (1.2 MiB of report markdown; the rest of those dirs is logs and worktrees). One destination answers all of them; two dirs (`emufix`, `wdfollow`) and several `unique` ones have an open `CLAIM`, so a session may still be writing there.
3. **Five more checkouts hold commits that exist on no origin branch** (`you-can-compact-yourself` 2, `aiuse-integration` 2, `crush-merge-v0981` 8, `opencode-v2` 1, `clinepass-pr44379` 2 plus a stash). Pushing a branch is outward-facing, so djbclark picks push or bundle per repo (section 3).

A fourth finding that is not a decision yet: **54.5 GiB of the 60 GiB is one scratch tree**, `adhoc-2026-10-18/hm-promo-rehearsal/` (Hermes promotion rehearsal homes and snapshots). Deleting it is a later cleanup decision, not part of Phase 0.

## 1. bigteam (`~/.local/state/bigteam/<task>/`)

**Method.** One row per task dir. *Size* is `du -sk`; *newest* is the newest mtime within two levels; *CLAIM* is `DONE` when the last non-blank line of `CLAIM` starts with `DONE`, `open` when a `CLAIM` exists without it, `no CLAIM` otherwise; *reports* are `*report*.md` files within three levels (not inside a git checkout) and whether `<file>.done` exists; *open jobs* counts `jobs/*.json` records with no `closed` key (a record written by `acp-dispatch` before it is reaped or closed; most are finished slices nobody closed, so this is a loose end, not lost data). Verdicts: `unique` = at least one report file and no document under `~/src/djbclark-ade/docs`, `~/ops/site-private/memory` or `~/.local/state/handoffs` mentions the task name (whole word, `rg -l -F -w`), and the dir is at most 5 MiB; `mixed` = the same but the dir is larger (logs, worktrees, caches around the reports); `scratch` = no report file, or every report's task name is already referenced elsewhere. **A reference proves a mention, not a copy**, and a short common task name can match by accident, so `scratch` for a dir that has reports means "cited somewhere", not "safe to delete"; the 93 scratch dirs have not been read.

134 dirs; 1 loose files at the root (.radar-reap-stamp).

### 1.1 The ten largest dirs and what fills them

| # | task | size | verdict | largest children |
|---|---|---|---|---|
| 1 | adhoc-2026-10-18 | 54.5G | scratch | `hm-promo-rehearsal/` 54.3G, `plektra-ci-wt/` 91.9M, `plektra-cert-check2/` 83.8M, `plektra-cert-check/` 14.2M |
| 2 | plektra-small-issues | 941.8M | scratch | `wt/` 911.5M, `scratch-rereview/` 5.2M, `ctrl-latch.jsonl` 1.9M, `s2b-led.jsonl` 1.7M |
| 3 | plektra-rebase | 845.7M | scratch | `plektra-djb-da27a141-stable-debug.apk` 98.1M, `plektra-djb-afa1734b-stable-debug.apk` 98.1M, `plektra-djb-04171bc9-stable-debug.apk` 98.1M, `plektra-djb-8b8a5ef-stable-debug.apk` 91.1M |
| 4 | plektra-port | 716.0M | scratch | `pastiera-djb-main-d5420ca.apk` 130.1M, `pastiera-djb-main-3ed8bac.apk` 130.1M, `pastiera-djb-main-670a730.apk` 130.1M, `pastiera-djb-main-178feaa.apk` 123.1M |
| 5 | upbatt | 494.5M | scratch | `wt/` 488.6M, `upbatt.jsonl` 5.5M, `lint.log` 44.0K, `recheck-assemble.log` 36.0K |
| 6 | acp-context | 481.1M | scratch | `graft-wt/` 455.4M, `docs-reconcile.jsonl` 10.7M, `impl/` 7.4M, `docs-context.jsonl` 6.7M |
| 7 | uptestsetup | 322.4M | scratch | `wt/` 322.3M, `lint.log` 44.0K, `run-dupasset.log` 24.0K, `run.log` 24.0K |
| 8 | wdup | 313.2M | mixed | `wt/` 300.0M, `wdup.jsonl` 3.5M, `wdup-r4-log.jsonl` 3.5M, `wdup-r3-log.jsonl` 3.0M |
| 9 | wedge-grants | 228.5M | scratch | `emuroot/` 79.4M, `apk/` 76.6M, `devtest7/` 14.5M, `devtest4/` 11.0M |
| 10 | emufix | 164.7M | mixed | `dev/` 91.8M, `wdogdev/` 70.9M, `phantom.jsonl` 832.0K, `cgroup.jsonl` 724.0K |

`adhoc-2026-10-18` is 91% of the total: `hm-promo-rehearsal/` holds the rehearsal copies `homeB`, `homeC`, `home`, `snap-step1`, `backups-C` and `tmp` (a few GiB each, all derived from a Hermes home). The `plektra-*` dirs are Android `*.apk` builds and git worktrees (`wt/`, `graft-wt/`); every one of them is reproducible from its repo.

### 1.2 `unique` and `mixed` dirs (the preservation list)

| task | verdict | size | newest | CLAIM | reports (.done?) | report bytes | open jobs |
|---|---|---|---|---|---|---|---|
| aiuse-pace-headline | unique | 4.5M | 2026-10-12 | DONE | chat-report.md, code2-report.md, docs-report.md +4 | 36,293 | 7 |
| caam-grok-login | unique | 4.3M | 2026-10-18 | no CLAIM | caam-grok-fix-report.md, caam-grok-fix2-report.md, caam-grok-refresh-report.md | 265 | 3 |
| mdns | unique | 3.9M | 2026-10-13 | DONE | mdns-r1-report.md (no .done), mdns-report.md, mdns2-report.md +4 | 79,935 | 0 |
| vendor40 | unique | 3.2M | 2026-10-12 | DONE | vendor40-report.md | 9,054 | 0 |
| quotafix | unique | 3.0M | 2026-10-18 | open | ab-report.md, adddir-report.md, c-report.md | 6,388 | 0 |
| emu39 | unique | 3.0M | 2026-10-13 | open | emu39-report.md | 6,963 | 0 |
| adbcert | unique | 2.9M | 2026-10-13 | DONE | adbcert-report.md | 15,132 | 0 |
| usvc | unique | 2.5M | 2026-10-13 | DONE | usvc-report.md, usvc2-report.md | 8,876 | 0 |
| adhoc-2026-10-15 | unique | 2.2M | 2026-10-18 | no CLAIM | crush-check2-report.md, policy-docs2-report.md, policy-review-report.md +3 | 13,779 | 7 |
| hermes-post-promo-2026-10-19 | unique | 2.1M | 2026-10-19 | DONE | patch-watch-report.md, playbook-67-report.md, venv-migrate-report.md | 21,398 | 0 |
| neofinder-launcher-research | unique | 1.8M | 2026-10-18 | DONE | qs-report.md, sc-report.md | 31,319 | 0 |
| upstream-opencode-v2 | unique | 1.4M | 2026-10-18 | no CLAIM | openusage-opencode-v2-report.md, rtk-opencode-v2-report.md, rtk-opencode-v2b-report.md +1 | 21,468 | 4 |
| aiusegpt | unique | 1.2M | 2026-10-18 | open | aiusegpt-report.md | 10,405 | 0 |
| jev-shadow | unique | 1.0M | 2026-10-18 | open | jev-report.md, jev2-report.md | 3,770 | 2 |
| secretspec-trigger-race | unique | 1.0M | 2026-10-18 | no CLAIM | trigger-race-report.md | 5,028 | 0 |
| mdnsresearch | unique | 992.0K | 2026-10-13 | no CLAIM | mdns-r1-report.md (no .done), mdnsrev-report.md (no .done), research-report.md | 47,043 | 0 |
| ralph-acp-plugin | unique | 992.0K | 2026-10-18 | open | acp-report.md, acp2-report.md | 8,536 | 2 |
| afs-tokens-2026-10-18 | unique | 748.0K | 2026-10-18 | open | research-report.md | 28,648 | 1 |
| caam-aiuse | unique | 744.0K | 2026-10-18 | DONE | collector-report.md | 9,868 | 1 |
| 44379-ci-fix | unique | 572.0K | 2026-10-18 | no CLAIM | clinepass-docs-report.md, rust-upstream-check-report.md | 8,840 | 2 |
| harness2 | unique | 572.0K | 2026-10-18 | DONE | harness2-report.md | 1,952 | 0 |
| vendorbatt | unique | 556.0K | 2026-10-12 | no CLAIM | vendorbatt-report.md | 24,327 | 0 |
| ci-green-2026-10-19 | unique | 540.0K | 2026-10-19 | DONE | ci-green-report.md | 4,154 | 0 |
| ralph-acp-smoke | unique | 524.0K | 2026-10-18 | no CLAIM | smoke-report.md | 3,627 | 1 |
| vendor40rev | unique | 424.0K | 2026-10-12 | no CLAIM | vendor40rev-r1-report.md (no .done), vendor40rev-report.md | 22,432 | 0 |
| opencode-plugin-durability | unique | 388.0K | 2026-10-18 | no CLAIM | opencode-plugin-durability-report.md | 10,615 | 1 |
| orca-handle-fix | unique | 360.0K | 2026-10-08 | DONE | report.md (no .done) | 3,061 | 0 |
| aiuse-display-names | unique | 204.0K | 2026-10-18 | no CLAIM | aiuse-service-display-names-report.md | 962 | 1 |
| upstream-583 | unique | 40.0K | 2026-10-10 | no CLAIM | port583-report.md | 14,454 | 0 |
| wdup | mixed | 313.2M | 2026-10-13 | DONE | wdup-r1-report.md (no .done), wdup-r2-report.md (no .done), wdup-r3-report.md (no .done) +4 | 48,845 | 0 |
| emufix | mixed | 164.7M | 2026-10-18 | open | cgroup-report.agy-quota.md (no .done), cgroup-report.md, emufixdev-report.md +7 | 89,666 | 0 |
| research-brain-emulation-agent-teams | mixed | 87.6M | 2026-10-18 | no CLAIM | adjudicate-grok-report.md, apply-review-fable-report.md, brain-modules-agy-report.md +19 | 431,270 | 0 |
| wdemu | mixed | 41.3M | 2026-10-11 | DONE | wdemu-r1-report.md (no .done), wdemu-r2-report.md (no .done), wdemu-report.md | 17,246 | 0 |
| emu40 | mixed | 34.5M | 2026-10-12 | no CLAIM | emu40-report-codex-partial.md (no .done), emu40b-report.md | 5,150 | 0 |
| spotlight-store-re | mixed | 33.6M | 2026-10-18 | no CLAIM | agy-re-report.md, agy-re2-report.md | 20,429 | 0 |
| emu40fu | mixed | 30.4M | 2026-10-13 | DONE | emu40fu-report.md | 6,019 | 0 |
| gnu-normalize | mixed | 17.6M | 2026-10-18 | no CLAIM | gnu-ade-report.md, gnu-site-report.md, gnu-stay-report.md | 39,125 | 3 |
| batt | mixed | 15.3M | 2026-10-13 | DONE | batt-report.md, batt2-r1-report.md (no .done), batt2-r2-report.md (no .done) +4 | 44,964 | 0 |
| wdfollow | mixed | 12.6M | 2026-10-18 | open | wdfix-report.md, wdfix2-report.md, wdfix3-report.md +3 | 45,276 | 0 |
| liveact | mixed | 11.9M | 2026-10-13 | DONE | liveact-r1-report.md (no .done), liveact-r2-report.md (no .done), liveact-report.md +1 | 27,512 | 0 |
| acp-auto-resume | mixed | 8.3M | 2026-10-18 | no CLAIM | auto-resume-r1-report.md (no .done), auto-resume-r2-report.md (no .done), auto-resume-report.md +5 | 60,955 | 0 |

### 1.3 Every task dir

| task | size | newest | CLAIM | report files | open jobs | verdict |
|---|---|---|---|---|---|---|
| adhoc-2026-10-18 | 54.5G | 2026-10-20 | no CLAIM | 28 | 8 | scratch |
| plektra-small-issues | 941.8M | 2026-10-20 | no CLAIM | 57 | 3 | scratch |
| plektra-rebase | 845.7M | 2026-10-17 | open | 32 | 0 | scratch |
| plektra-port | 716.0M | 2026-10-12 | no CLAIM | 0 | 0 | scratch |
| upbatt | 494.5M | 2026-10-13 | DONE | 2 | 0 | scratch |
| acp-context | 481.1M | 2026-10-16 | no CLAIM | 10 | 0 | scratch |
| uptestsetup | 322.4M | 2026-10-13 | DONE | 0 | 0 | scratch |
| wdup | 313.2M | 2026-10-13 | DONE | 7 | 0 | mixed |
| wedge-grants | 228.5M | 2026-10-18 | open | 50 | 0 | scratch |
| emufix | 164.7M | 2026-10-18 | open | 10 | 0 | mixed |
| neofinder-spotlight-batch | 154.3M | 2026-10-18 | open | 9 | 0 | scratch |
| sipb-bench | 105.6M | 2026-10-12 | DONE | 3 | 3 | scratch |
| shizuku-harness | 94.6M | 2026-10-06 | no CLAIM | 0 | 0 | scratch |
| research-brain-emulation-agent-teams | 87.6M | 2026-10-18 | no CLAIM | 22 | 0 | mixed |
| stayturgid-af6b | 86.0M | 2026-10-18 | DONE | 7 | 0 | scratch |
| routing-overhaul | 72.3M | 2026-10-18 | no CLAIM | 12 | 0 | scratch |
| ade-2026-10-20-phase0-queue | 60.7M | 2026-10-20 | open | 31 | 10 | scratch |
| wdemu | 41.3M | 2026-10-11 | DONE | 3 | 0 | mixed |
| research-ai-heaven | 37.1M | 2026-10-18 | no CLAIM | 19 | 0 | scratch |
| emu40 | 34.5M | 2026-10-12 | no CLAIM | 2 | 0 | mixed |
| spotlight-store-re | 33.6M | 2026-10-18 | no CLAIM | 2 | 0 | mixed |
| emu40fu | 30.4M | 2026-10-13 | DONE | 1 | 0 | mixed |
| gnu-normalize | 17.6M | 2026-10-18 | no CLAIM | 3 | 3 | mixed |
| batt | 15.3M | 2026-10-13 | DONE | 7 | 0 | mixed |
| sleeper-restore-flags | 14.7M | 2026-10-08 | open | 7 | 0 | scratch |
| certpin | 14.3M | 2026-10-13 | DONE | 11 | 0 | scratch |
| wdfollow | 12.6M | 2026-10-18 | open | 6 | 0 | mixed |
| liveact | 11.9M | 2026-10-13 | DONE | 4 | 0 | mixed |
| research-soul-md-autonomy | 11.4M | 2026-10-18 | no CLAIM | 10 | 0 | scratch |
| mit-forgejo-move | 10.1M | 2026-10-16 | no CLAIM | 8 | 0 | scratch |
| acp-auto-resume | 8.3M | 2026-10-18 | no CLAIM | 8 | 0 | mixed |
| aiuse-pace-headline | 4.5M | 2026-10-12 | DONE | 7 | 7 | unique |
| caam-grok-login | 4.3M | 2026-10-18 | no CLAIM | 3 | 3 | unique |
| mdns | 3.9M | 2026-10-13 | DONE | 7 | 0 | unique |
| vendor40 | 3.2M | 2026-10-12 | DONE | 1 | 0 | unique |
| quotafix | 3.0M | 2026-10-18 | open | 3 | 0 | unique |
| emu39 | 3.0M | 2026-10-13 | open | 1 | 0 | unique |
| s1-cas | 3.0M | 2026-10-13 | no CLAIM | 1 | 1 | scratch |
| adbcert | 2.9M | 2026-10-13 | DONE | 1 | 0 | unique |
| s1-adapters | 2.8M | 2026-10-12 | no CLAIM | 3 | 3 | scratch |
| usvc | 2.5M | 2026-10-13 | DONE | 2 | 0 | unique |
| plektra-trackpad-nav | 2.4M | 2026-10-18 | no CLAIM | 1 | 0 | scratch |
| adhoc-2026-10-15 | 2.2M | 2026-10-18 | no CLAIM | 6 | 7 | unique |
| hermes-post-promo-2026-10-19 | 2.1M | 2026-10-19 | DONE | 3 | 0 | unique |
| s1-cursor-ide | 1.9M | 2026-10-13 | no CLAIM | 1 | 1 | scratch |
| neofinder-launcher-research | 1.8M | 2026-10-18 | DONE | 2 | 0 | unique |
| herdr-ai-cmd | 1.7M | 2026-10-08 | open | 4 | 0 | scratch |
| s1-ztext | 1.7M | 2026-10-13 | no CLAIM | 1 | 1 | scratch |
| s1-agy | 1.7M | 2026-10-13 | no CLAIM | 1 | 1 | scratch |
| upstream-opencode-v2 | 1.4M | 2026-10-18 | no CLAIM | 4 | 4 | unique |
| s1-crush | 1.4M | 2026-10-13 | no CLAIM | 1 | 1 | scratch |
| s1-qwen-cline | 1.2M | 2026-10-13 | no CLAIM | 1 | 1 | scratch |
| aiusegpt | 1.2M | 2026-10-18 | open | 1 | 0 | unique |
| home-agents-trim | 1.1M | 2026-10-18 | no CLAIM | 1 | 1 | scratch |
| jev-shadow | 1.0M | 2026-10-18 | open | 2 | 2 | unique |
| secretspec-trigger-race | 1.0M | 2026-10-18 | no CLAIM | 1 | 0 | unique |
| jev-eval | 996.0K | 2026-10-18 | no CLAIM | 1 | 1 | scratch |
| job-records | 992.0K | 2026-10-08 | DONE | 1 | 0 | scratch |
| mdnsresearch | 992.0K | 2026-10-13 | no CLAIM | 3 | 0 | unique |
| ralph-acp-plugin | 992.0K | 2026-10-18 | open | 2 | 2 | unique |
| sipb-collector | 940.0K | 2026-10-18 | no CLAIM | 1 | 1 | scratch |
| graft-worktrees-sync | 916.0K | 2026-10-18 | DONE | 2 | 2 | scratch |
| s1-cursor-rest | 876.0K | 2026-10-13 | no CLAIM | 2 | 2 | scratch |
| afs-tokens-2026-10-18 | 748.0K | 2026-10-18 | open | 1 | 1 | unique |
| caam-aiuse | 744.0K | 2026-10-18 | DONE | 1 | 1 | unique |
| 44379-ci-fix | 572.0K | 2026-10-18 | no CLAIM | 2 | 2 | unique |
| harness2 | 572.0K | 2026-10-18 | DONE | 1 | 0 | unique |
| vendorbatt | 556.0K | 2026-10-12 | no CLAIM | 1 | 0 | unique |
| ci-green-2026-10-19 | 540.0K | 2026-10-19 | DONE | 1 | 0 | unique |
| ralph-acp-smoke | 524.0K | 2026-10-18 | no CLAIM | 1 | 1 | unique |
| vendor40rev | 424.0K | 2026-10-12 | no CLAIM | 2 | 0 | unique |
| opencode-plugin-durability | 388.0K | 2026-10-18 | no CLAIM | 1 | 1 | unique |
| orca-handle-fix | 360.0K | 2026-10-08 | DONE | 1 | 0 | unique |
| acp-resume-hardening | 328.0K | 2026-10-18 | DONE | 1 | 0 | scratch |
| orca-aiuse | 264.0K | 2026-10-18 | DONE | 6 | 0 | scratch |
| upstream-pr | 260.0K | 2026-10-17 | no CLAIM | 1 | 0 | scratch |
| herdr-safe-close | 244.0K | 2026-10-08 | DONE | 1 | 0 | scratch |
| n40 | 224.0K | 2026-10-12 | DONE | 0 | 0 | scratch |
| aiuse-display-names | 204.0K | 2026-10-18 | no CLAIM | 1 | 1 | unique |
| review-b-dry | 80.0K | 2026-10-18 | no CLAIM | 0 | 0 | scratch |
| slotreview | 60.0K | 2026-10-13 | no CLAIM | 0 | 0 | scratch |
| ade-skill-overlap | 40.0K | 2026-10-08 | no CLAIM | 1 | 0 | scratch |
| upstream-583 | 40.0K | 2026-10-10 | no CLAIM | 1 | 0 | unique |
| site-private-migration | 32.0K | 2026-10-08 | no CLAIM | 0 | 0 | scratch |
| ade-public-review | 20.0K | 2026-10-08 | no CLAIM | 1 | 0 | scratch |
| bg-ci-first | 12.0K | 2026-10-18 | DONE | 0 | 0 | scratch |
| upstream | 12.0K | 2026-10-06 | no CLAIM | 0 | 0 | scratch |
| acp-run-interactive | 8.0K | 2026-10-08 | no CLAIM | 0 | 0 | scratch |
| ade-consolidation | 8.0K | 2026-10-08 | no CLAIM | 0 | 0 | scratch |
| ade-skill-merge | 8.0K | 2026-10-08 | no CLAIM | 0 | 0 | scratch |
| orca-tidy-feasibility | 8.0K | 2026-10-08 | no CLAIM | 1 | 0 | scratch |
| acpd-probe | 4.0K | 2026-10-08 | no CLAIM | 0 | 0 | scratch |
| herdr-discussion | 4.0K | 2026-10-08 | no CLAIM | 0 | 0 | scratch |
| sf-20261008-092730-claude-0121 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-092902-claude-2219 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-093217-claude-6919 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-093852-claude-6971 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-104324-claude-5166 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-104325-claude-5262 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-104455-claude-8257 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-105007-claude-7942 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-105850-claude-7983 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-111653-claude-6026 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-112018-claude-1910 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-113857-claude-0751 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-113903-claude-0955 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-120402-claude-0610 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-120916-claude-9532 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-125752-claude-3287 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-144523-claude-5301 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-144706-claude-8286 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-145750-claude-2517 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-150123-claude-9964 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-150515-claude-8573 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-150534-claude-9431 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-150847-claude-7155 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-152104-claude-7745 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-152436-claude-4837 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261008-161855-claude-8159 | 4.0K | 2026-10-08 | DONE | 0 | 0 | scratch |
| sf-20261010-195507-opencode-8321 | 4.0K | 2026-10-10 | DONE | 0 | 0 | scratch |
| sf-20261010-195708-opencode-3991 | 4.0K | 2026-10-10 | DONE | 0 | 0 | scratch |
| sf-20261011-121116-claude-7085 | 4.0K | 2026-10-11 | DONE | 0 | 0 | scratch |
| sf-20261011-121201-claude-9304 | 4.0K | 2026-10-11 | DONE | 0 | 0 | scratch |
| sf-20261011-121217-claude-0114 | 4.0K | 2026-10-11 | DONE | 0 | 0 | scratch |
| sf-20261011-124527-claude-9285 | 4.0K | 2026-10-11 | DONE | 0 | 0 | scratch |
| sf-20261017-075234-claude-5334 | 4.0K | 2026-10-17 | DONE | 0 | 0 | scratch |
| sf-20261017-101949-claude-3975 | 4.0K | 2026-10-17 | DONE | 0 | 0 | scratch |
| sf-20261017-192751-hermes-0765 | 4.0K | 2026-10-17 | DONE | 0 | 0 | scratch |
| sf-20261017-192817-hermes-1590 | 4.0K | 2026-10-17 | DONE | 0 | 0 | scratch |
| sf-20261017-192941-hermes-4521 | 4.0K | 2026-10-17 | DONE | 0 | 0 | scratch |
| sf-20261017-193305-hermes-0842 | 4.0K | 2026-10-17 | DONE | 0 | 0 | scratch |
| sf-20261017-194719-hermes-3620 | 4.0K | 2026-10-17 | DONE | 0 | 0 | scratch |
| sf-20261017-225948-hermes-5741 | 4.0K | 2026-10-18 | DONE | 0 | 0 | scratch |
| routing-recalibrate | 0B | 2026-10-18 | no CLAIM | 0 | 0 | scratch |

## 2. Orca and cow checkouts

**Method.** A checkout is a directory holding `.git` (file or directory) found up to two levels under `~/orca/workspaces`, `~/orca/projects` and `~/.cow/pastures`; in this run symlinks were followed, resolved and deduplicated (`~/orca/projects/djbclark-ade` and `one-offs` are links to `~/src/...`, so they appear under `~/src`); the tool no longer follows symlinks under a root, so a fresh scan names `--git-root ~/src/djbclark-ade --git-root ~/src/one-offs` itself. `~/orca/workspaces/{aiuse,mobile,wristchess,.orca-preparing}` are empty dirs. *Modified* and *untracked* count `git status --porcelain` lines (`??` = untracked, non-ignored; an untracked directory counts once). *Unpushed* is `git rev-list --count @{u}..HEAD`, or `no upstream`. *Ahead of origin* is commits reachable from HEAD and from no `origin/*` ref (with a check that the branch tip on origin does not already contain HEAD, because the local remote refs can be stale; `--fetch` downloads that branch's objects when they are missing, writing no refs). *On origin* comes from `git ls-remote --heads origin`. Verdict precedence: `unpushed commits`, `orphan branch` (branch not on origin and commits origin lacks), `dirty`, `clean and pushed`; the *also* column lists the other flags.

| path | branch | mod | untr | unpushed | ahead of origin | stash | on origin | verdict | also |
|---|---|---|---|---|---|---|---|---|---|
| ~/orca/workspaces/Graft/rudderfish | djbclark/rudderfish | 0 | 0 | no upstream | 0 | 0 | False | **clean and pushed** |  |
| ~/orca/workspaces/djbclark-ade/you-can-compact-yourself | djbclark/you-can-compact-yourself | 0 | 0 | no upstream | 2 | 0 | False | **orphan branch** |  |
| ~/orca/workspaces/one-offs/Hermes | Hermes | 0 | 0 | no upstream | 2 | 0 | False | **orphan branch** | no origin remote |
| ~/orca/workspaces/orca/aiuse-integration | djbclark/aiuse-integration | 0 | 0 | no upstream | 2 | 0 | False | **orphan branch** |  |
| ~/orca/workspaces/site-djbclark/small-fixes | djbclark/small-fixes | 0 | 0 | no upstream | 0 | 0 | False | **clean and pushed** |  |
| ~/orca/workspaces/superbrain/barnacle | djbclark/count-watch-later-videos | 3 | 1 | no upstream | 0 | 0 | False | **dirty** |  |
| ~/orca/workspaces/superbrain/wearos-investigation | djbclark/wearos-investigation | 0 | 2 | no upstream | 0 | 0 | False | **dirty** |  |
| ~/src/djbclark-ade | master | 13 | 7 | 0 | 0 | 0 | True | **dirty** |  |
| ~/src/one-offs | master | 0 | 0 | no upstream | 37 | 0 | False | **orphan branch** | no origin remote |
| ~/.cow/pastures/aiuse/probe-orca-dispatch | probe-orca-dispatch | 0 | 0 | no upstream | 0 | 0 | False | **clean and pushed** |  |
| ~/.cow/pastures/crush/crush-merge-v0981 | merge/upstream-v0.98.1 | 0 | 0 | no upstream | 8 | 0 | False | **orphan branch** |  |
| ~/.cow/pastures/djbclark-ade/ade-update | ade-update-2026-10-20 | 4 | 7 | 0 | 0 | 0 | True | **dirty** |  |
| ~/.cow/pastures/djbclark-ade/paseo-lifecycle | paseo-lifecycle-2026-10-20 | 6 | 7 | 0 | 0 | 0 | True | **dirty** |  |
| ~/.cow/pastures/djbclark-ade/phase0-backups | phase0-backups-2026-10-20 | 4 | 7 | 0 | 0 | 0 | True | **dirty** |  |
| ~/.cow/pastures/djbclark-ade/phase0-scan | phase0-scan-2026-10-20 | 7 | 10 | no upstream | 0 | 0 | False | **dirty** |  |
| ~/.cow/pastures/djbclark-ade/phase0-templates | phase0-templates-2026-10-20 | 4 | 7 | 0 | 0 | 0 | True | **dirty** |  |
| ~/.cow/pastures/djbclark-ade/relay-paseo | relay-paseo-2026-10-20 | 4 | 7 | no upstream | 0 | 0 | False | **dirty** |  |
| ~/.cow/pastures/forgejo-ci-2026-10/gh-ci-2026-10 | ci/base | 0 | 3 | no upstream | 0 | 0 | True | **dirty** |  |
| ~/.cow/pastures/hermes-agent/agent-1 | fix/aiuse-slash-timeout | 0 | 0 | no upstream | 0 | 0 | True | **clean and pushed** |  |
| ~/.cow/pastures/hermes-agent/forgejo-ci-2026-10 | forgejo-ci-2026-10 | 0 | 3 | no upstream | 0 | 0 | False | **dirty** |  |
| ~/.cow/pastures/janekbaraniewski_openusage/opencode-v2 | fix/opencode-telemetry-v2 | 0 | 0 | 0 | 1 | 0 | False | **orphan branch** |  |
| ~/.cow/pastures/litellm/clinepass-pr44379 | clinepass-upstream | 0 | 2 | 2 | 0 | 1 | True | **unpushed commits** | dirty, stash |
| ~/.cow/pastures/superbrain/sb-usage-storm | fix/usage-events-storm | 0 | 0 | no upstream | 0 | 0 | False | **clean and pushed** |  |

**What the dirt is.** The seven `djbclark-ade` rows (the primary checkout and six pastures) show the same 7 untracked paths and about 4 modified ones (6 in `paseo-lifecycle`, 13 in the primary, which other agents kept editing during the scan) because `cow` copies the working tree, dirt included: `skills/graft/SKILL.md` and `skills/paseo-*/SKILL.md` (modified), and `.agents/skills/fastino-glide/`, `bin/graft/`, `docs/handoffs/HANDOFF_standalone-32c0_...`, `skills/paseo*/.paseo-managed-files.json` (untracked). They belong to other agents' in-flight work in the primary checkout; this scan does not touch them. The two `forgejo-ci-2026-10` rows likewise share `.forgejo/`, `apps/desktop/release-new/` and `scripts/forgejo-test-ref`. Untracked `graft/` directories are the reproducible graft index (`graft build`), not work. The `phase0-scan` pasture itself is dirty with this slice's own files while the scan ran, and is left out of 3.2.

## 3. Capture (how each item would be preserved; none of this was run)

### 3.1 `unique` and `mixed` bigteam dirs

Proposed rule for all of them: copy the report files (not the dir) to one destination, `<DEST>/<task>/`, preserving names. `<DEST>` is the one decision (the repo question, rule 23; `~/ops/site-private` is private and fits unreviewed AI reports). Per item the file set is below; `needs decision` is `yes` only where a session may still be writing (open `CLAIM`, an unclosed job record with status running) or the dir is `mixed` (the logs next to the report may matter).

| task | copy | needs decision |
|---|---|---|
| aiuse-pace-headline | `cp ~/.local/state/bigteam/aiuse-pace-headline/` `chat-report.md`, `code2-report.md`, `docs-report.md`, `early-report.md` +3 more -> `<DEST>/aiuse-pace-headline/` | no (only DEST) |
| caam-grok-login | `cp ~/.local/state/bigteam/caam-grok-login/` `caam-grok-fix-report.md`, `caam-grok-fix2-report.md`, `caam-grok-refresh-report.md` -> `<DEST>/caam-grok-login/` | no (only DEST) |
| mdns | `cp ~/.local/state/bigteam/mdns/` `mdns-r1-report.md`, `mdns-report.md`, `mdns2-report.md`, `mdns3-report.md` +3 more -> `<DEST>/mdns/` | no (only DEST) |
| vendor40 | `cp ~/.local/state/bigteam/vendor40/` `vendor40-report.md` -> `<DEST>/vendor40/` | no (only DEST) |
| quotafix | `cp ~/.local/state/bigteam/quotafix/` `ab-report.md`, `adddir-report.md`, `c-report.md` -> `<DEST>/quotafix/` | yes: CLAIM open: confirm the session is finished |
| emu39 | `cp ~/.local/state/bigteam/emu39/` `emu39-report.md` -> `<DEST>/emu39/` | yes: CLAIM open: confirm the session is finished |
| adbcert | `cp ~/.local/state/bigteam/adbcert/` `adbcert-report.md` -> `<DEST>/adbcert/` | no (only DEST) |
| usvc | `cp ~/.local/state/bigteam/usvc/` `usvc-report.md`, `usvc2-report.md` -> `<DEST>/usvc/` | no (only DEST) |
| adhoc-2026-10-15 | `cp ~/.local/state/bigteam/adhoc-2026-10-15/` `crush-check2-report.md`, `policy-docs2-report.md`, `policy-review-report.md`, `policy-review2-report.md` +2 more -> `<DEST>/adhoc-2026-10-15/` | no (only DEST) |
| hermes-post-promo-2026-10-19 | `cp ~/.local/state/bigteam/hermes-post-promo-2026-10-19/` `patch-watch-report.md`, `playbook-67-report.md`, `venv-migrate-report.md` -> `<DEST>/hermes-post-promo-2026-10-19/` | no (only DEST) |
| neofinder-launcher-research | `cp ~/.local/state/bigteam/neofinder-launcher-research/` `qs-report.md`, `sc-report.md` -> `<DEST>/neofinder-launcher-research/` | no (only DEST) |
| upstream-opencode-v2 | `cp ~/.local/state/bigteam/upstream-opencode-v2/` `openusage-opencode-v2-report.md`, `rtk-opencode-v2-report.md`, `rtk-opencode-v2b-report.md`, `rtk-opencode-v2c-report.md` -> `<DEST>/upstream-opencode-v2/` | no (only DEST) |
| aiusegpt | `cp ~/.local/state/bigteam/aiusegpt/` `aiusegpt-report.md` -> `<DEST>/aiusegpt/` | yes: CLAIM open: confirm the session is finished |
| jev-shadow | `cp ~/.local/state/bigteam/jev-shadow/` `jev-report.md`, `jev2-report.md` -> `<DEST>/jev-shadow/` | yes: CLAIM open: confirm the session is finished; 2 job record(s) unclosed |
| secretspec-trigger-race | `cp ~/.local/state/bigteam/secretspec-trigger-race/` `trigger-race-report.md` -> `<DEST>/secretspec-trigger-race/` | no (only DEST) |
| mdnsresearch | `cp ~/.local/state/bigteam/mdnsresearch/` `.acp-dispatch/mdns-r1-report.md`, `.acp-dispatch/mdnsrev-report.md`, `research-report.md` -> `<DEST>/mdnsresearch/` | no (only DEST) |
| ralph-acp-plugin | `cp ~/.local/state/bigteam/ralph-acp-plugin/` `acp-report.md`, `acp2-report.md` -> `<DEST>/ralph-acp-plugin/` | yes: CLAIM open: confirm the session is finished; 2 job record(s) unclosed |
| afs-tokens-2026-10-18 | `cp ~/.local/state/bigteam/afs-tokens-2026-10-18/` `research-report.md` -> `<DEST>/afs-tokens-2026-10-18/` | yes: CLAIM open: confirm the session is finished; 1 job record(s) unclosed |
| caam-aiuse | `cp ~/.local/state/bigteam/caam-aiuse/` `collector-report.md` -> `<DEST>/caam-aiuse/` | no (only DEST) |
| 44379-ci-fix | `cp ~/.local/state/bigteam/44379-ci-fix/` `clinepass-docs-report.md`, `rust-upstream-check-report.md` -> `<DEST>/44379-ci-fix/` | no (only DEST) |
| harness2 | `cp ~/.local/state/bigteam/harness2/` `harness2-report.md` -> `<DEST>/harness2/` | no (only DEST) |
| vendorbatt | `cp ~/.local/state/bigteam/vendorbatt/` `vendorbatt-report.md` -> `<DEST>/vendorbatt/` | no (only DEST) |
| ci-green-2026-10-19 | `cp ~/.local/state/bigteam/ci-green-2026-10-19/` `ci-green-report.md` -> `<DEST>/ci-green-2026-10-19/` | no (only DEST) |
| ralph-acp-smoke | `cp ~/.local/state/bigteam/ralph-acp-smoke/` `smoke-report.md` -> `<DEST>/ralph-acp-smoke/` | no (only DEST) |
| vendor40rev | `cp ~/.local/state/bigteam/vendor40rev/` `vendor40rev-r1-report.md`, `vendor40rev-report.md` -> `<DEST>/vendor40rev/` | no (only DEST) |
| opencode-plugin-durability | `cp ~/.local/state/bigteam/opencode-plugin-durability/` `opencode-plugin-durability-report.md` -> `<DEST>/opencode-plugin-durability/` | no (only DEST) |
| orca-handle-fix | `cp ~/.local/state/bigteam/orca-handle-fix/` `report.md` -> `<DEST>/orca-handle-fix/` | no (only DEST) |
| aiuse-display-names | `cp ~/.local/state/bigteam/aiuse-display-names/` `aiuse-service-display-names-report.md` -> `<DEST>/aiuse-display-names/` | no (only DEST) |
| upstream-583 | `cp ~/.local/state/bigteam/upstream-583/` `port583-report.md` -> `<DEST>/upstream-583/` | no (only DEST) |
| wdup | `cp ~/.local/state/bigteam/wdup/` `wdup-r1-report.md`, `wdup-r2-report.md`, `wdup-r3-report.md`, `wdup-r4-report.md` +3 more -> `<DEST>/wdup/` | yes: mixed: say whether the logs/worktrees beside it matter |
| emufix | `cp ~/.local/state/bigteam/emufix/` `cgroup-report.agy-quota.md`, `cgroup-report.md`, `emufixdev-report.md`, `phantom-report.agy-quota.md` +6 more -> `<DEST>/emufix/` | yes: CLAIM open: confirm the session is finished; mixed: say whether the logs/worktrees beside it matter |
| research-brain-emulation-agent-teams | `cp ~/.local/state/bigteam/research-brain-emulation-agent-teams/` `adjudicate-grok-report.md`, `apply-review-fable-report.md`, `brain-modules-agy-report.md`, `brain-modules-astra-report.md` +18 more -> `<DEST>/research-brain-emulation-agent-teams/` | yes: mixed: say whether the logs/worktrees beside it matter |
| wdemu | `cp ~/.local/state/bigteam/wdemu/` `wdemu-r1-report.md`, `wdemu-r2-report.md`, `wdemu-report.md` -> `<DEST>/wdemu/` | yes: mixed: say whether the logs/worktrees beside it matter |
| emu40 | `cp ~/.local/state/bigteam/emu40/` `emu40-report-codex-partial.md`, `emu40b-report.md` -> `<DEST>/emu40/` | yes: mixed: say whether the logs/worktrees beside it matter |
| spotlight-store-re | `cp ~/.local/state/bigteam/spotlight-store-re/` `agy-re-report.md`, `agy-re2-report.md` -> `<DEST>/spotlight-store-re/` | yes: mixed: say whether the logs/worktrees beside it matter |
| emu40fu | `cp ~/.local/state/bigteam/emu40fu/` `emu40fu-report.md` -> `<DEST>/emu40fu/` | yes: mixed: say whether the logs/worktrees beside it matter |
| gnu-normalize | `cp ~/.local/state/bigteam/gnu-normalize/` `gnu-ade-report.md`, `gnu-site-report.md`, `gnu-stay-report.md` -> `<DEST>/gnu-normalize/` | yes: mixed: say whether the logs/worktrees beside it matter; 3 job record(s) unclosed |
| batt | `cp ~/.local/state/bigteam/batt/` `batt-report.md`, `batt2-r1-report.md`, `batt2-r2-report.md`, `batt2-report.md` +3 more -> `<DEST>/batt/` | yes: mixed: say whether the logs/worktrees beside it matter |
| wdfollow | `cp ~/.local/state/bigteam/wdfollow/` `wdfix-report.md`, `wdfix2-report.md`, `wdfix3-report.md`, `wdfix4-report.md` +2 more -> `<DEST>/wdfollow/` | yes: CLAIM open: confirm the session is finished; mixed: say whether the logs/worktrees beside it matter |
| liveact | `cp ~/.local/state/bigteam/liveact/` `liveact-r1-report.md`, `liveact-r2-report.md`, `liveact-report.md`, `liveactrev-report.md` -> `<DEST>/liveact/` | yes: mixed: say whether the logs/worktrees beside it matter |
| acp-auto-resume | `cp ~/.local/state/bigteam/acp-auto-resume/` `auto-resume-r1-report.md`, `auto-resume-r2-report.md`, `auto-resume-report.md`, `auto-resume-report.part1.md` +4 more -> `<DEST>/acp-auto-resume/` | yes: mixed: say whether the logs/worktrees beside it matter |

The two open-claim `mixed` dirs and `research-brain-emulation-agent-teams` (22 reports, 88 MiB with no CLAIM) are the ones to read first.

### 3.2 Checkouts with unpushed commits or untracked non-ignored files

| checkout | what is not preserved | command | needs decision |
|---|---|---|---|
| ~/orca/workspaces/djbclark-ade/you-can-compact-yourself | 2 commit(s) on `djbclark/you-can-compact-yourself` | `git -C ~/orca/workspaces/djbclark-ade/you-can-compact-yourself push -u origin djbclark/you-can-compact-yourself` or `git -C ~/orca/workspaces/djbclark-ade/you-can-compact-yourself bundle create <DEST>/you-can-compact-yourself-djbclark_you-can-compact-yourself.bundle djbclark/you-can-compact-yourself` | yes: pushing a branch publishes it; pick push or bundle |
| ~/orca/workspaces/one-offs/Hermes | 2 commits on branch `Hermes` (no remote) | same repo as `~/src/one-offs`: its `--all` bundle (the `~/src/one-offs` row below) includes branch `Hermes` | **yes**: see `~/src/one-offs` |
| ~/orca/workspaces/orca/aiuse-integration | 2 commit(s) on `djbclark/aiuse-integration` | `git -C ~/orca/workspaces/orca/aiuse-integration push -u origin djbclark/aiuse-integration` or `git -C ~/orca/workspaces/orca/aiuse-integration bundle create <DEST>/aiuse-integration-djbclark_aiuse-integration.bundle djbclark/aiuse-integration` | yes: pushing a branch publishes it; pick push or bundle |
| ~/orca/workspaces/superbrain/barnacle | 3 modified tracked file(s) | `git -C ~/orca/workspaces/superbrain/barnacle diff > <DEST>/barnacle-modified.patch` | yes: decide whether they are work |
| ~/orca/workspaces/superbrain/wearos-investigation | 1 untracked (`superbrain-wear/`) | copy the paths to `<DEST>/wearos-investigation-untracked/` (`cp -R`), or `git -C ~/orca/workspaces/superbrain/wearos-investigation add` them on a branch and push | yes: decide whether they are work |
| ~/src/djbclark-ade | 13 modified tracked file(s); 7 untracked (`.agents/skills/fastino-glide/`, `bin/graft/`, `docs/handoffs/HANDOFF_standalone-32c0_quota-reset-recovery_2026-10-18_quota.md`, ...) | same modified files as the primary checkout (cow copy; other agents' edits): preserved there; same paths as the primary / sibling checkout (cow copy): preserve once there | no |
| ~/src/one-offs | all 37 commits (no remote) | `git -C ~/src/one-offs bundle create ~/ops/site-private/bundles/one-offs.bundle --all` or add a remote and `git push -u origin <branch>` | **yes**: only copy; hosting or bundle destination |
| ~/.cow/pastures/crush/crush-merge-v0981 | 8 commit(s) on `merge/upstream-v0.98.1` | `git -C ~/.cow/pastures/crush/crush-merge-v0981 push -u origin merge/upstream-v0.98.1` or `git -C ~/.cow/pastures/crush/crush-merge-v0981 bundle create <DEST>/crush-merge-v0981-merge_upstream-v0.98.1.bundle merge/upstream-v0.98.1` | yes: pushing a branch publishes it; pick push or bundle |
| ~/.cow/pastures/djbclark-ade/ade-update | 4 modified tracked file(s); 7 untracked (`.agents/skills/fastino-glide/`, `bin/graft/`, `docs/handoffs/HANDOFF_standalone-32c0_quota-reset-recovery_2026-10-18_quota.md`, ...) | same modified files as the primary checkout (cow copy; other agents' edits): preserved there; same paths as the primary / sibling checkout (cow copy): preserve once there | no |
| ~/.cow/pastures/djbclark-ade/paseo-lifecycle | 6 modified tracked file(s); 7 untracked (`.agents/skills/fastino-glide/`, `bin/graft/`, `docs/handoffs/HANDOFF_standalone-32c0_quota-reset-recovery_2026-10-18_quota.md`, ...) | same modified files as the primary checkout (cow copy; other agents' edits): preserved there; same paths as the primary / sibling checkout (cow copy): preserve once there | no |
| ~/.cow/pastures/djbclark-ade/phase0-backups | 4 modified tracked file(s); 7 untracked (`.agents/skills/fastino-glide/`, `bin/graft/`, `docs/handoffs/HANDOFF_standalone-32c0_quota-reset-recovery_2026-10-18_quota.md`, ...) | same modified files as the primary checkout (cow copy; other agents' edits): preserved there; same paths as the primary / sibling checkout (cow copy): preserve once there | no |
| ~/.cow/pastures/djbclark-ade/phase0-templates | 4 modified tracked file(s); 7 untracked (`.agents/skills/fastino-glide/`, `bin/graft/`, `docs/handoffs/HANDOFF_standalone-32c0_quota-reset-recovery_2026-10-18_quota.md`, ...) | same modified files as the primary checkout (cow copy; other agents' edits): preserved there; same paths as the primary / sibling checkout (cow copy): preserve once there | no |
| ~/.cow/pastures/djbclark-ade/relay-paseo | 4 modified tracked file(s); 7 untracked (`.agents/skills/fastino-glide/`, `bin/graft/`, `docs/handoffs/HANDOFF_standalone-32c0_quota-reset-recovery_2026-10-18_quota.md`, ...) | same modified files as the primary checkout (cow copy; other agents' edits): preserved there; same paths as the primary / sibling checkout (cow copy): preserve once there | no |
| ~/.cow/pastures/forgejo-ci-2026-10/gh-ci-2026-10 | 3 untracked (`.forgejo/`, `apps/desktop/release-new/`, `scripts/forgejo-test-ref`) | same paths as the primary / sibling checkout (cow copy): preserve once there | no |
| ~/.cow/pastures/hermes-agent/forgejo-ci-2026-10 | 3 untracked (`.forgejo/`, `apps/desktop/release-new/`, `scripts/forgejo-test-ref`) | same paths as the primary / sibling checkout (cow copy): preserve once there | no |
| ~/.cow/pastures/janekbaraniewski_openusage/opencode-v2 | 1 commit(s) on `fix/opencode-telemetry-v2` | `git -C ~/.cow/pastures/janekbaraniewski_openusage/opencode-v2 push -u origin fix/opencode-telemetry-v2` or `git -C ~/.cow/pastures/janekbaraniewski_openusage/opencode-v2 bundle create <DEST>/opencode-v2-fix_opencode-telemetry-v2.bundle fix/opencode-telemetry-v2` | yes: pushing a branch publishes it; pick push or bundle |
| ~/.cow/pastures/litellm/clinepass-pr44379 | 2 commit(s) on `clinepass-upstream`; 1 stash; 1 untracked (`.ignore`) | `git -C ~/.cow/pastures/litellm/clinepass-pr44379 push -u origin clinepass-upstream` or `git -C ~/.cow/pastures/litellm/clinepass-pr44379 bundle create <DEST>/clinepass-pr44379-clinepass-upstream.bundle clinepass-upstream`; `git -C ~/.cow/pastures/litellm/clinepass-pr44379 stash show -p stash@{0} > <DEST>/clinepass-pr44379-stash0.patch`; copy the paths to `<DEST>/clinepass-pr44379-untracked/` (`cp -R`), or `git -C ~/.cow/pastures/litellm/clinepass-pr44379 add` them on a branch and push | yes: pushing a branch publishes it; pick push or bundle |

Checkouts not listed are `clean and pushed` (branch on origin or no commits origin lacks) or hold only the reproducible `graft/` index.

## 4. Limits of this scan

1. Bigteam `unique` means "no document under three roots mentions the task name"; it does not read the reports. A mention in `site-private/memory` is counted as preserved even if the report itself is only here.
2. Directories are classified by name, not content: the 93 `scratch` dirs were not opened, so a decision note in a file not named `*report*.md` (for example `findings.md`, `decision.md`, `out.txt`, `final.txt`) is not detected. Count of such files was not measured.
3. `du` totals ~64 GB here against ~61 GB in the slice 1 inventory: a different tool and a later moment (sessions kept writing during both).
4. `ls-remote` needs the remote to answer; a checkout whose origin refused would show `on origin: unknown`. None did in this run.
5. A pasture that was clean when created can become dirty or ahead later; this is a snapshot at 2026-10-20T04:38:17-0400.
6. The scan ran with the first version of the tool, which did not look at a checkout's own config before running git there. The config of the scanned checkouts was not read afterwards for command-naming keys (`core.fsmonitor`, `core.sshCommand`, `remote.*.uploadpack`, `filter.*`, `credential.*`, `core.hooksPath`, `include.*`), so this document cannot say none of them ran something. The current tool lists such a checkout as `skipped: repo config runs commands`.
7. The run's `--fetch` could have moved `refs/remotes/origin/<branch>` and `FETCH_HEAD` in the checkouts where it fetched; which ones it touched was not recorded.

## 5. Commands run

`W` is the slice's scratch dir under `~/.local/state/bigteam/ade-2026-10-20-phase0-queue/phase0-scan-work`. Besides writing `W`, the run's only effects outside this pasture were the `fetch` calls described above.

```sh
python3 -I bin/ade-scan-state --json \
  --bigteam ~/.local/state/bigteam \
  --ref-root ~/src/djbclark-ade/docs --ref-root ~/ops/site-private/memory \
  --ref-root ~/.local/state/handoffs --exclude 'ade-everywhere-phase0-scan-*.md' \
  --git-root ~/orca/workspaces --git-root ~/orca/projects --git-root ~/.cow/pastures \
  --remote --fetch > $W/scan.json 2> $W/scan.err; echo rc=$? > $W/scan.rc
python3 -I bin/ade-scan-state-doc $W/scan.json docs/ade-everywhere-phase0-scan-2026-10-20.md
```

The first command is the run as executed. With the current tool the same scan adds `--git-root ~/src/djbclark-ade --git-root ~/src/one-offs` (symlinks under a root are not followed), its `--fetch` is `git -c maintenance.auto=false -c gc.auto=0 fetch --no-auto-maintenance --no-write-fetch-head --no-tags --refmap= origin refs/heads/<branch>`, and a checkout whose config names a command is listed as skipped.
