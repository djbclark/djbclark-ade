# Phase 0 data decisions — inventory card (2026-11-10)

Queue Carried #21. Smallest useful advance on the open Phase 0 preserve decisions from the 2026-10-20 scan: confirm the **41** unreferenced bigteam report sets, list them, and put the operator choices on one page. **No capture, move, push, bundle or delete was run.** The scanner (`bin/ade-scan-state`) was removed in slim-down E2; this card re-reads the frozen scan, it does not re-probe the Mac.

**Source:** [ade-everywhere-phase0-scan-2026-10-20.md](ade-everywhere-phase0-scan-2026-10-20.md) §0–§1.2 and §3 (scan at 2026-10-20T04:38:17-0400). Related store context: [ade-everywhere-inventory-2026-10-20-stores.md](ade-everywhere-inventory-2026-10-20-stores.md).

**Live probe (2026-11-10, this Cloud Agent VM):** `~/.local/state/bigteam` is absent here. Paths below are the Mac host paths from the scan. A fresh count needs a read on that host (or a restored copy of those dirs); until then treat the 41 as the last verified inventory.

## 0. Verdict on the count

| Measure (scan 2026-10-20) | Value |
|---|---|
| `unique` bigteam task dirs | **29** |
| `mixed` bigteam task dirs | **12** |
| **Unreferenced report sets (`unique` + `mixed`)** | **41** |
| Report markdown bytes in those sets | 1,295,049 B (~1.24 MiB) |
| Whole-dir size of those 41 | ~45.6 MiB unique + ~771 MiB mixed (mostly logs/worktrees) |
| Root path | `~/.local/state/bigteam/<task>/` |

`unique` / `mixed` means: at least one `*report*.md` under the task dir, and no whole-word mention of the task name in `~/src/djbclark-ade/docs`, `~/ops/site-private/memory` or `~/.local/state/handoffs` at scan time. A mention is not a copy; `scratch` was never opened for content. See the scan §1 method.

## 1. Operator decision — the 41 report sets (one answer for all)

Pick **one** destination policy for every set (the scan's `<DEST>`). Per-set exceptions only if marked in §2.

| Option | Meaning | Fits when |
|---|---|---|
| **host** | Copy report markdown (not whole dirs) into a durable private tree that is itself backed up or git-tracked — scan suggested `~/ops/site-private/…/<task>/` (rule 23 / private unreviewed AI text). | Reports should stay searchable and individually readable. |
| **bundle** | One archive of the report files (e.g. `tar` of `<task>/*report*.md` for all 41) into a backup location; no live tree. | Preserve once, rarely open; keep out of day-to-day trees. |
| **delete** | Do not preserve; remove or leave to later scratch cleanup after operator confirms nothing unique remains. | Operator has already absorbed the content elsewhere, or accepts loss. |

**Default capture shape (if host or bundle; from scan §3.1, not run):** copy only `*report*.md` files into `<DEST>/<task>/`, preserving names. Do **not** copy worktrees, APKs, or jsonl logs unless a `mixed` row below is marked "logs matter".

**Open before acting:** several dirs had an open `CLAIM` or unclosed job records on 2026-10-20 (column below). Re-check CLAIM / job freshness on the Mac before copy or delete.

**Operator pick (blank until decided):** `________` (host / bundle / delete)  
**`<DEST>` if host or bundle:** `________`  
**Mixed-dir logs/worktrees:** keep with reports / reports only / per-task (circle one)

## 2. The 41 sets

Path for each row: `~/.local/state/bigteam/<task>/`. Size and CLAIM are whole-dir / CLAIM-file state from the scan, not a 2026-11-10 re-read. Report bytes are the sum of `*report*.md` under that task.

### 2.1 `unique` (29) — reports ≤5 MiB dir

| # | task | size | CLAIM | report bytes | notes from scan §3.1 |
|---|---|---|---|---|---|
| 1 | aiuse-pace-headline | 4.5M | DONE | 36,293 | DEST only |
| 2 | caam-grok-login | 4.3M | no CLAIM | 265 | DEST only |
| 3 | mdns | 3.9M | DONE | 79,935 | DEST only |
| 4 | vendor40 | 3.2M | DONE | 9,054 | DEST only |
| 5 | quotafix | 3.0M | open | 6,388 | confirm session finished |
| 6 | emu39 | 3.0M | open | 6,963 | confirm session finished |
| 7 | adbcert | 2.9M | DONE | 15,132 | DEST only |
| 8 | usvc | 2.5M | DONE | 8,876 | DEST only |
| 9 | adhoc-2026-10-15 | 2.2M | no CLAIM | 13,779 | DEST only |
| 10 | hermes-post-promo-2026-10-19 | 2.1M | DONE | 21,398 | DEST only |
| 11 | neofinder-launcher-research | 1.8M | DONE | 31,319 | DEST only |
| 12 | upstream-opencode-v2 | 1.4M | no CLAIM | 21,468 | DEST only |
| 13 | aiusegpt | 1.2M | open | 10,405 | confirm session finished |
| 14 | jev-shadow | 1.0M | open | 3,770 | CLAIM open; 2 jobs unclosed |
| 15 | secretspec-trigger-race | 1.0M | no CLAIM | 5,028 | DEST only |
| 16 | mdnsresearch | 992.0K | no CLAIM | 47,043 | DEST only |
| 17 | ralph-acp-plugin | 992.0K | open | 8,536 | CLAIM open; 2 jobs unclosed |
| 18 | afs-tokens-2026-10-18 | 748.0K | open | 28,648 | CLAIM open; 1 job unclosed |
| 19 | caam-aiuse | 744.0K | DONE | 9,868 | DEST only |
| 20 | 44379-ci-fix | 572.0K | no CLAIM | 8,840 | DEST only |
| 21 | harness2 | 572.0K | DONE | 1,952 | DEST only |
| 22 | vendorbatt | 556.0K | no CLAIM | 24,327 | DEST only |
| 23 | ci-green-2026-10-19 | 540.0K | DONE | 4,154 | DEST only |
| 24 | ralph-acp-smoke | 524.0K | no CLAIM | 3,627 | DEST only |
| 25 | vendor40rev | 424.0K | no CLAIM | 22,432 | DEST only |
| 26 | opencode-plugin-durability | 388.0K | no CLAIM | 10,615 | DEST only |
| 27 | orca-handle-fix | 360.0K | DONE | 3,061 | DEST only |
| 28 | aiuse-display-names | 204.0K | no CLAIM | 962 | DEST only |
| 29 | upstream-583 | 40.0K | no CLAIM | 14,454 | DEST only |

### 2.2 `mixed` (12) — reports plus large sibling trees

| # | task | size | CLAIM | report bytes | notes from scan §3.1 |
|---|---|---|---|---|---|
| 30 | wdup | 313.2M | DONE | 48,845 | say whether logs/worktrees matter |
| 31 | emufix | 164.7M | open | 89,666 | CLAIM open; logs/worktrees? |
| 32 | research-brain-emulation-agent-teams | 87.6M | no CLAIM | 431,270 | 22 reports; read first |
| 33 | wdemu | 41.3M | DONE | 17,246 | logs/worktrees? |
| 34 | emu40 | 34.5M | no CLAIM | 5,150 | logs/worktrees? |
| 35 | spotlight-store-re | 33.6M | no CLAIM | 20,429 | logs/worktrees? |
| 36 | emu40fu | 30.4M | DONE | 6,019 | logs/worktrees? |
| 37 | gnu-normalize | 17.6M | no CLAIM | 39,125 | logs/worktrees?; 3 jobs unclosed |
| 38 | batt | 15.3M | DONE | 44,964 | logs/worktrees? |
| 39 | wdfollow | 12.6M | open | 45,276 | CLAIM open; logs/worktrees? |
| 40 | liveact | 11.9M | DONE | 27,512 | logs/worktrees? |
| 41 | acp-auto-resume | 8.3M | no CLAIM | 60,955 | logs/worktrees? |

Scan priority to read first: `emufix`, `wdfollow`, `research-brain-emulation-agent-teams`.

## 3. Sibling Phase 0 decisions (same queue item)

Same card so Carried #21 has one place to land answers. Detail and proposed commands: scan §0 items 1 and 3, §3.2 (commands were never run; generator later changed — re-plan before capture).

### 3.1 `~/src/one-offs` (no `origin`)

37 commits on disk only (plus Orca worktree `~/orca/workspaces/one-offs/Hermes`, branch `Hermes`, 2 commits, same repo).

| Option | Meaning |
|---|---|
| **host** | Add a remote and push (where-does-it-go / rule 23). |
| **bundle** | `git bundle create … --all` into a private backup path (scan example: `~/ops/site-private/bundles/one-offs.bundle`). |
| **delete** | Not offered here without a separate confirm: sole copy of the history. |

**Operator pick:** `________` (host / bundle) · **remote or bundle path:** `________`

### 3.2 Branches with commits on no origin

Scan named: `you-can-compact-yourself` (2), `aiuse-integration` (2), `crush-merge-v0981` (8), `opencode-v2` (1), `clinepass-pr44379` (2 + stash). Push publishes; bundle keeps private.

| Option | Meaning |
|---|---|
| **host** | `git push -u origin <branch>` per checkout. |
| **bundle** | `git bundle create <DEST>/….bundle <branch>` per checkout. |
| **delete / drop** | Abandon the local-only commits (explicit per repo). |

**Operator pick (global or per-repo):** `________`

## 4. Out of scope for this card

- The **54.5 GiB** `adhoc-2026-10-18/hm-promo-rehearsal/` scratch tree (scan §0 item 4): later cleanup, not Phase 0 preserve.
- The 93 `scratch` bigteam dirs: not inventoried for unique non-`*report*` notes.
- Re-running a scan: tool gone (E2); a one-off `find`/`du` on the Mac can refresh sizes if dirs still exist.

## 5. Next step after the operator fills §1 (and §3)

1. On the Mac, confirm the 41 dirs still exist (or note which are already gone).
2. For any still-open CLAIM / jobs, wait or close before copy/delete.
3. Apply the chosen policy once; record the filled picks and the PR that executed them back into `docs/queue.md` (move #21 to Done or Closed with the destination).
