# ADE-everywhere Phase 0, slice 1: installed agent session store inventory (2026-10-20)

Phase 0, slice 1 of `docs/ade-everywhere-proposal.md` §8 (preserve and classify). Written by a zcode GLM-5.3 research slice (`phase0-inventory-2`, 2026-10-20, read-only) from the brief in `~/.local/state/bigteam/ade-2026-10-20-phase0-queue/brief-phase0-inventory.md`; reviewed by the lead. It supersedes the store rows of §6 in [ade-everywhere-inventory-2026-10-19.md](ade-everywhere-inventory-2026-10-19.md) and feeds slice 2 (the `.backup` copies and exports) and slice 3 (the bigteam and Orca scan).

Read-only survey run 2026-10-20 02:48-03:10 EDT by the phase0-inventory-2 slice. Working dir `~`;
repo `~/src/djbclark-ade` (read-only). Every claim cites the path checked; commands are listed in
section 6. No file on disk was modified by this slice (the only writes were this report and its
`.done` marker).

## 1. Summary

- **Agents installed: 18.** Via `acp-run --list` (13 ok): claude, codex, copilot, opencode, cursor,
  qwen, cline, hermes, omp, zcode, agy, grok, crush. Without ACP: muse, gemini (Gemini CLI), paseo,
  orca, herdr. **devin is registered but not installed** (`--` in `acp-run --list`; no `~/.devin`,
  no `devin` on PATH).
- **Stores found: 52 session/config stores** (one per row of the section 2 table; 24 hold session content, the rest
  are config, index, scratch or duplicate stores belonging to the same tools).
- **Total bytes:** ~31 GB of session-bearing stores, plus ~61 GB `~/.local/state/bigteam` scratch,
  ~6.1 GB Orca (3.8 GB checkouts + 2.3 GB app data), ~0.5 GB derived indexes, ~28 MB Tier 1 handoffs.
- **Unique data at risk (no second copy anywhere):** every row in section 2 marked "synced: no" in
  the 2026-10-19 inventory is still single-copy — in particular `~/.hermes/state.db` (1.6 GB,
  canonical SQLite, only stale local `.bak` files), `~/.local/share/opencode/opencode.db` (946 MB),
  Cursor's per-session `store.db` files (2.2 GB tree), `~/.zcode/cli/db/db.sqlite` (105 MB),
  Antigravity conversations (582 MB + 781 MB + IDE copy), and
  `~/.local/state/handoffs` (3.0 MB, 215 `SESSION_LOG.md` — the most valuable small item).
  Syncthing was running with only an empty placeholder folder on 2026-10-19; not re-verified on 2026-10-20.
- **Changed versus the 2026-10-19 inventory (its section 6):** Cursor 1.1G→2.2G (266
  `acp-sessions` dirs are new-ish bulk); Claude Code 1.7G→2.2G, 553→563 project dirs; Qwen
  39M→488K (`~/.qwen/sessions` now empty; only `projects/*/chats/*.jsonl` remain); zcode db
  268M→105M; Grok 256M→176M; Orca checkouts ~14G→3.8G; bigteam 106G→61G (adhoc-2026-10-18 still
  55G); Hermes dir 24G→19G; handoffs 100 chains/2.9M→215 `SESSION_LOG.md`/3.0M; Muse unchanged
  (52M→53M) but its path is `~/.local/share/muse`, not `~/.muse`; herdr paths confirmed
  `~/.config/herdr` + `~/.local/state/herdr` (`~/.local/share/herdr` does not exist).

## 2. Store table

Sizes from `timeout 300 du -sh` unless a single file's `ls -la` is cited. "Newest" = newest
session-bearing item found (`fd … -x stat -f '%m %N' | gsort -rn | ghead -1`) or file mtime.

| Provider | Store (resolved path) | Format | Size | Newest item | Class | Readable export | Lossless backup | Native resume | Import | Remote |
|---|---|---|---|---|---|---|---|---|---|---|
| Claude Code | `~/.claude/projects/<slug>/*.jsonl` (563 dirs, 2405 jsonl) | jsonl per session; first-line keys `customTitle,sessionId,type` | 2.2G (`~/.claude` total) | 2026-10-20 02:51 | canonical files | the jsonl itself | manifested generation (6.3) | `--resume`, `--continue`, `--fork-session` | copy into the project dir (target cwd must exist) | cloud sessions; SDK `SessionStore` mirror |
| Claude Code | `~/.claude/history.jsonl` | jsonl prompt history | 2.9M | 2026-10-19 22:46 | derived index | the jsonl itself | copy | n/a | none | none |
| Claude Code | sidecars: `~/.claude/file-history` (185), `session-env` (1580), `sessions` (session-server `.key`/`.json`), `tasks` (784), `teams` (36) | mixed files | within the 2.2G | 2026-10-20 02:48 (dirs) | mixed (sidecars of the canonical tree) | none verified | clone with `projects/`, excluding `sessions/*.key` (live session-server keys, 5.5) | n/a | none | none |
| Claude Code | `~/.claude.json` + `~/.claude/settings.json` (52K) + `settings.local.json` (6.9K) | json | 236K + 52K + 6.9K | 2026-10-20 | config | themselves | copy the two `settings*.json`; `~/.claude.json` holds account credentials: exclude or vault (5.5) | n/a | n/a | n/a |
| Codex | `~/.codex/sessions` → `~/ops/site-private/.codex-runtime/sessions` (`readlink -f`; a symlinked root, followed by `ade-backup-stores` and recorded under `root_symlinks`), `YYYY/MM/DD/rollout-*.jsonl`, 840 files | jsonl rollouts; first-line keys `ordinal,payload,timestamp,type` | 1.1G (runtime tree total, incl 73M `logs_2.sqlite`) | 2026-10-20 02:51 | canonical files plus derived index | the rollout | copy after completion | `codex resume`, `codex fork`, `exec resume` | `/import` from Claude Code and Cursor; no first-party rollout import | remote connections continue a chat on its host |
| Codex | `~/.codex/session_index.jsonl` → runtime copy (a symlink into `~/ops/site-private/.codex-runtime/`, followed as a store root by `ade-backup-stores`; 4,441 B, 35 rows; keys `id,thread_name,updated_at`) | jsonl index | 4.4K | 2026-10-19 19:59 | derived index | the jsonl itself | copy | (feeds resume picker) | n/a | n/a |
| Codex | `~/.codex/state_5.sqlite` → runtime `state_5.sqlite` (WAL) + `logs_2.sqlite` 73M + `memories_1.sqlite` 389K + `goals_1.sqlite` 32K + `memories-git/` (git) | sqlite (WAL; header 18-19 = 2,2) | ~74M | 2026-10-20 02:54 (wal) | derived index (tables `_sqlx_migrations`, `rollout_migration_*`, `thread_attachments`, `external_agent_session_imports`); role of `thread_*` tables not fully classified | none verified | backup API | (index of rollouts) | n/a | n/a |
| Codex | `~/.codex/config.toml` (0600) + `auth.json` (contains a credential; not opened) | toml | 15K | 2026-10-19 19:58 | config | itself | copy, minus the 5.5 credential file | n/a | n/a | n/a |
| Gemini CLI | `~/.gemini/tmp/<project-name>/chats/session-<ts>-<id>.jsonl` (4 files; keys `kind,lastUpdated,projectHash,sessionId,startTime`) | jsonl per session, keyed by project-name dir with `projectHash` inside | <1M | 2026-10-20 02:46 | canonical files | `/export-session <path>` (v0.43.0, per proposal 6.1) | export | `--session-file` | `--session-file` | none |
| Gemini CLI | `~/.gemini/settings.json` 2.3K; `oauth_creds.json` (credential, not opened); `~/.gemini/config/mcp_config.json` (plaintext MCP keys, not opened); `history/<name>/` | json | 2.3K | 2026-10-20 | config | itself | copy `settings.json` and `history/`; `oauth_creds.json` and `mcp_config.json` are 5.5 credential files: exclude or vault | n/a | n/a | n/a |
| Antigravity (agy CLI) | `~/.gemini/antigravity-cli/`: `conversations/<uuid>.db` (582M, per-conversation SQLite WAL; tables `steps`, `trajectory_meta`, `parent_references`, …) + `conversation_summaries.db` 295K + `brain/` 299M + `history.jsonl` 568K | sqlite per conversation + summary index | 936M | 2026-10-20 02:48 (summaries db) | canonical SQLite (one db per conversation) plus derived index | none verified | backup API per db (WAL); clone `brain/` (one dir per conversation, section 3 item 3) | yes (in-tool) | none verified | none |
| Antigravity (IDE) | `~/.gemini/antigravity/`: `conversations/`, `conversation_summaries.db` (+shm/wal), `brain/` 72M (15 dirs), `antigravity_state.pbtxt` | sqlite per conversation + protobuf state | 147M | 2026-10-18 (dir mtimes) | canonical SQLite (second, IDE-local store) | none verified | backup API per db; clone `brain/` | yes (in-tool) | none verified | none |
| Antigravity (ACP) | `~/.gemini/antigravity-acp/`: `conversations/` 781M (+ a `.meta` sidecar per db, 268), `brain/` 270M (173 dirs), `acp_token.json` (credential, not opened) | sqlite per conversation | 1.0G | 2026-10-09 (dir mtime) | canonical SQLite (third, ACP-local store) | none verified | backup API per db with its `.meta`; clone `brain/` | yes (in-tool) | none verified | none |
| Antigravity | `~/.gemini/antigravity-ide/` 15M (updater artifacts) and `~/.local/share/agy-acp-server/1.4.1/` 383M (the `agy_acp_server.par` program) | program files | 398M | 2026-10-17 | config (not sessions) | n/a | none needed | n/a | n/a | n/a |
| OpenCode | `~/.local/share/opencode/opencode.db` (+`-shm`/`-wal`; `PRAGMA journal_mode` = wal) | sqlite; tables `session`, `session_v2`, `message`, `part`, `session_message`, … | 946M (991,563,776 B) | 2026-10-20 02:12 (db), 02:45 (shm) | canonical SQLite | `opencode session export <id> [--sanitize]` (proposal 6.1, C49) | online backup API plus export | yes | `opencode session import <file> --directory` | none |
| OpenCode | `~/.config/opencode/opencode.json` 2.7K (plaintext MCP keys, not opened; + `.jsonc`, plugins, skills); `~/.local/share/opencode/auth.json` (credential, not opened) | json | 2.7K | 2026-10-18 | config | itself | copy `.jsonc`, plugins and skills; `opencode.json` and `auth.json` are 5.5 credential files: exclude or vault | n/a | n/a | n/a |
| Copilot CLI | `~/.copilot/session-state/<uuid>/{workspace.yaml,events.jsonl,checkpoints,files,research}` (313 dirs; `events.jsonl` is the transcript the session-finder adapter reads, present in 71 of them on 2026-10-20) + `session-store.db` 2.5M + `-wal` 4.1M (tables `sessions`, `session_files`, `session_refs`, `turns`, `checkpoints`, `search_index` FTS) | files per session plus sqlite index | 58M (`~/.copilot` total) | 2026-10-20 02:39 (`session-store.db-shm`) | mixed | `/share file\|html\|gist`, `--remote-export` (6.1) | copy plus backup API | `--resume`, `--remote --resume` | none | account-bound |
| Copilot CLI | `data.db` 1.2M (accounts, app_state) + `config.json` 812B + `mcp-config.json` 156B + `settings.json` | sqlite + json | 1.2M + ~1K | 2026-10-20 | config/app state | itself | `data.db` holds account credentials (`accounts`): exclude or vault (5.5); copy the json | n/a | n/a | n/a |
| Cursor | `~/.cursor/chats/<md5-workspace>/<uuid>/{meta.json,store.db}` (39 workspace hashes); `store.db` tables `blobs, meta` | sqlite per session (WAL, live shm/wal) | 2.2G (`~/.cursor` total) | 2026-10-20 02:41 (`store.db-shm`) | canonical SQLite (fragmented per session) | none verified (third-party exporters only, 6.1) | backup API per db | `--resume`, `ls`, `resume` (6.1) | none | `worker` (private cloud) |
| Cursor | `~/.cursor/acp-sessions/<uuid>/{meta.json,store.db}` (266 dirs, same `blobs, meta` schema) | sqlite per session | within the 2.2G | 2026-10-20 02:41 | canonical SQLite (ACP-launched chats) | none verified | backup API per db | yes (via agent CLI) | none | as above |
| Cursor | `~/.cursor/projects/<slug>/{agent-transcripts,canvases,terminals,…}` (128 dirs on a 2026-10-20 recount, 140 earlier the same day, cause unknown: back up before whatever prunes them runs; `agent-transcripts/*/*.jsonl` = 108 IDE conversations in 39 dirs) | files | within the 2.2G | 2026-10-20 02:12 | mixed (canonical IDE transcripts + sidecars) | the jsonl | clone (section 3 item 3) | n/a | none | n/a |
| Cursor | `~/.cursor/mcp.json` 867B (plaintext MCP keys, not opened) + `cli-config.json` 9.7K + `hooks.json` 6.6K | json | ~17K | 2026-10-18/20 | config | themselves | copy `cli-config.json` and `hooks.json`; `mcp.json` is a 5.5 credential file: exclude or vault | n/a | n/a | n/a |
| Qwen | `~/.qwen/projects/<slug>/chats/<uuid>.jsonl` (+ `.runtime.json`); keys `cwd,message,parentUuid,provenance,sessionId,timestamp,type,uuid,version` (id and cwd inside) | jsonl per session | 488K (`~/.qwen` total; `sessions/` empty) | 2026-10-20 00:35 | canonical files | the jsonl itself | copy | in-tool session picker (not verified) | none verified | none |
| Qwen | `~/.qwen/settings.json` 47K + `usage_record.jsonl` + `memories/` | json | 47K+ | 2026-10-20 | config + usage log | itself | copy | n/a | n/a | n/a |
| Cline | `~/.cline/data/sessions/<ts>_<id>/<id>.json` + `<id>.messages.json` (38 task dirs) | json per task (not jsonl) | 263M (`~/.cline/data` incl `checkpoint-scratch`) | 2026-10-19 22:25 | canonical files | the json itself | copy | in-tool task resume (not verified) | none verified | none |
| Cline | `~/.cline/data/db/*.db` (`connectors`, `cron`, `hub-events-hub-production`, `hub-runs-hub-production`, all +shm/wal) | sqlite | within the 263M | 2026-10-20 | config/app state | n/a | backup API | n/a | n/a | n/a |
| Cline | `~/.cline/data/settings/{global-settings.json, cline_mcp_settings.json, providers.json}` — `providers.json` may contain a credential; not opened | json | ~3 files | 2026-10-20 | config | itself | copy, minus the 5.5 credential file | n/a | n/a | n/a |
| Hermes | `~/.hermes/state.db` 1,694,011,392 B + `-shm` + `-wal` (2.3M); `PRAGMA journal_mode` = wal; tables incl `messages_fts_*` (FTS) | sqlite | 1.6G | 2026-10-20 02:44 | canonical SQLite | `hermes sessions export` (JSONL, `--redact`; refused above `max_export_messages` 20,000, 6.1 C41) | backup API (also fallback for oversized sessions) plus nightly export | yes | import restores archived history, not live context | Telegram gateway |
| Hermes | `~/.hermes/gmail_index_v2.db` 937M; `state.db.bak-20260815` 984M, `state.db.bak-20260921` 1.1G; `sessions/` request dumps 21M; `config.yaml` 9.7K (30+ `.bak`s); `~/.hermes` is a **git repo, dirty** (`config.yaml` modified, hindsight scripts deleted) | sqlite + json + yaml | ~2.9G extra | 2026-10-20 02:53 | derived index + duplicate + scratch + config | n/a | index rebuildable; `.bak`s are stale duplicates | n/a | n/a | n/a |
| Hermes | `~/hermes-memory` 92K markdown (memory pool per 6.1) | markdown | 92K | not checked | canonical files | themselves | copy/git | n/a | n/a | n/a |
| omp | `~/.omp/agent/sessions/<cwd-slug>/<ts>_<uuid>.jsonl` (19 cwd dirs, 83 files; first-line keys `pad,title,type,updatedAt,v`) | jsonl per session | 53M (`~/.omp/agent`) | 2026-10-20 02:38 | canonical files | the jsonl | manifested generation | yes (in-tool) | none | none |
| omp | `~/.omp/agent/history.db` (tables `history`, `history_fts`, `session_recaps`, `session_titles`) 90K + `agent.db` 500K (tables incl `auth_credential_blocks` — contains credentials; not opened) + `models.db` 8.4M; `natives/` 100M binaries | sqlite (WAL, shm present) | ~9M | 2026-10-20 02:38 | derived index (history.db) + config/state (agent.db) | none | backup API | n/a | n/a | n/a |
| zcode | `~/.zcode/cli/db/db.sqlite` 105,381,888 B + `-shm`/`-wal` (4.1M); tables `message`, `part`, `session_*`, `workflow_*`, `dwf_*` | sqlite (WAL) | 105M | 2026-10-20 02:51 | canonical SQLite | third-party or none (6.1) | backup API | yes | none | none |
| zcode | `~/.zcode/cli/rollout/model-io-sess_<uuid>.jsonl` (3 files) + `v2/tasks-index.sqlite` 700K WAL (`automations`, `task_groups`, `tasks`) + `v2/acp-lazy-sessions.json` 57K; `cli/artifacts/` 34M (58), `cli/memories/` 208K, `cli/log/` 16M, `cli/exec/` 2.4M | jsonl sidecars + sqlite index + session output | ~55M | 2026-10-20 02:47 | mixed (sidecar transcripts, session output, derived index) | the jsonl, `artifacts/`, `memories/` | copy + backup API (section 3 item 3; `log/`, `exec/` derived) | n/a | n/a | n/a |
| zcode | `~/.zcode/cli/setting.json` 2.1K, `cli/config.json` 4.1K, `v2/config.json` 8.3K; `v2/credentials.json` (credential, not opened); `cli/setting.json.bak-2026-10-18-mcp-trim` matched key patterns (count only, not opened) and was vaulted on 2026-10-20 (5.5); `cli/config.json.bak` matched none | json | ~15K | 2026-10-18 | config | themselves | copy, minus the 5.5 credential files | n/a | n/a | n/a |
| Crush (ACP) | `~/.local/share/crush-acp/crush.db` 978,944 B + shm/wal; tables `sessions, messages, files, read_files, mcp_*` (the ACP instance: `CRUSH_GLOBAL_DATA` per `acp-run --list`) | sqlite (WAL) | 2.0M | 2026-10-14 13:37 (db), 2026-10-20 02:39 (shm) | canonical SQLite | third-party or none (6.1) | backup API | yes | none | none |
| Crush (TUI) | `~/.config/crush/.crush/crush.db` 2,789,376 B + shm (live 2026-10-20 02:42)/wal | sqlite (WAL) | 2.8M | 2026-10-20 02:42 | canonical SQLite (second, default-XDG store) | none | backup API | yes | none | none |
| Crush | `~/src/djbclark-ade/.crush` exists (repo-local instance; not opened); `~/.local/share/crush/` holds `crush.json` (0600: the provider API key and OAuth access and refresh tokens, found by the adversary 2026-10-20; excluded), `projects.json`, `providers.json` (563K catalog) and `hyper.json` (a Charm Hyper login: exclude or vault, 5.5) | mixed | 584K | 2026-10-19 | config / repo-local sessions db (`crush.db` + wal/shm, `-shm` touched 2026-10-20) | n/a | `.crush/crush.db` via backup API (section 3 item 1); copy `projects.json` only (`crush.json`, `hyper.json` and `providers.json` are excluded) | n/a | n/a | n/a |
| Grok | `~/.grok/sessions/<urlencoded-cwd>/<uuid>/{chat_history.jsonl, events.jsonl, updates.jsonl, summary.json, prompt_context.json, system_prompt.txt}`; `chat_history` keys `content,type` | jsonl per session + sidecars | 176M (`~/.grok`) | 2026-10-20 02:12 | canonical files | the jsonl | copy | in-tool (not verified) | none verified | none |
| Grok | `~/.grok/worktrees.db` 40K WAL (`meta, worktrees`), `memory-v2/`, `memtrace/` (162 dirs), `config.toml` 953B | sqlite + files | within 176M | 2026-10-20 01:36 | config + memory/traces | n/a | copy (ade-backup-stores: `worktrees.db` by backup API, `memory-v2/` and `memtrace/` as file roots; `config.toml` is config, not copied) | n/a | n/a | n/a |
| Muse | `~/.local/share/muse/sessions/YYYY/MM/DD/<uuid>/session.jsonl` (newest 2026/10/04) + `session-index.db` 168K WAL (`rewind_catalog_*`, `sessions`) + `tui-history.jsonl` 10K | jsonl per session + sqlite rewind index | 53M | 2026-10-04 06:49 | canonical files plus derived index | the jsonl | copy + backup API for the index | in-tool (not verified) | none verified | none |
| Paseo | `~/.paseo/agents/<workspace-slug>/<uuid>.json` (6 slugs, small json per agent session) | json per agent session | ~50K | 2026-10-20 02:55 | mixed: titles, parent links and labels exist only here | history search, Import session (Claude, Codex, omp) (6.1) | copy | n/a | yes | per-host history only |
| Paseo | `agent-requests/*.json` (81), `projects/{projects,workspaces}.json`, `runtime/managed-processes`, `creations/` (452), `config.json` 4.4K, `models/` 984M voice models, `daemon-keypair.json` + `local-credential` (credentials, not opened) | json + assets | 1.0G total | 2026-10-20 02:49 | config + state + assets | n/a | copy (agents/, projects/, agent-requests/ only) | n/a | n/a | n/a |
| Orca | `~/orca/workspaces` (8 checkouts: Graft, aiuse, djbclark-ade, …) + `~/orca/projects` | git worktrees | 3.8G | 2026-10-06 | duplicate (of the repos) | n/a | nothing extra (repos are remote-backed) | n/a | n/a | n/a |
| Orca | `~/.orca` (`jira-sites.json` 0600, `jira-tokens/`, `agent-hooks/`, `claude-agent-teams-bin/`) | config + credentials | 76K | 2026-10-20 | config | n/a | copy `agent-hooks/` only; `jira-tokens/` and `jira-sites.json` are credentials (5.5) | n/a | n/a | n/a |
| Orca | `~/Library/Application Support/Orca` (IndexedDB, Session Storage, Local Storage, Cookies, DIPS; Electron) | Electron app data | 2.3G | 2026-10-18 | mixed (app state; which part holds DAG state could not be classified) | none verified | clone dir with app stopped, minus `Cookies` (5.5) | n/a | n/a | n/a |
| herdr | `~/.config/herdr/{session.json 2.1K, session-history.json 39K, session-snapshots/session-<epoch>-*.json (50), sessions/sleeper-plugin-lab}` + `config.toml` 11K | json snapshots + toml | 9.8M | 2026-10-20 02:44 | canonical files (snapshots) + config | the json | copy | n/a (snapshots are post-hoc) | n/a | n/a |
| herdr | `~/.local/state/herdr` (agent-detection, client-shell, plugins) 704K; `~/.herdr/worktrees` 84M | state + worktrees | 85M | 2026-10-17 | config/duplicate | n/a | copy (state dir) | n/a | n/a | n/a |
| ADE toolchain | `~/.local/state/bigteam` — 61G scratch (adhoc-2026-10-18 = 55G, plektra-* ≈ 2.7G) | mixed scratch | 61G | 2026-10-20 02:49 | scratch (unique reports live here — Phase 0 scans before any cleanup) | reports are markdown | capture unique reports (Phase 0) | n/a | n/a | n/a |
| ADE toolchain | `~/.local/state/acp-dispatch` (`preflight/` 50) 96K; `~/.local/state/self-slash.log` 313K; `~/.local/state/session-finder` 28M (launch logs); `~/.local/state/acp-run` 53M (per-run jsonl) | state/logs | ~81M | 2026-10-20 | config + scratch logs | themselves | copy (small) | n/a | n/a | n/a |
| ADE toolchain | `~/.local/state/handoffs` — 215 `SESSION_LOG.md`, `chains/` 103 dirs (Tier 1 pointers) | markdown | 3.0M | 2026-10-20 02:38 | canonical files | themselves | copy/sync (most valuable small item) | n/a | n/a | n/a |
| ADE toolchain | `~/.local/state/session-index/history.v2.sqlite` (FTS5: `files, msgs, msgs_*`) + shm 32K | sqlite | 142M | 2026-10-20 02:49 | derived index (rebuildable) | n/a | rebuild, don't back up | n/a | n/a | n/a |

## 3. Backup plan per store (feeds Phase 0 slice 2)

2026-10-20: `bin/ade-backup-stores` implements this section (PR #24): `--dry-run` first, then a run into
`~/.local/state/ade/backups/<UTC>/` with a `MANIFEST.json` (sha256 per file, exclusions, errors) and the Hermes export
(`hermes-export/`; sessions above `max_export_messages` are listed in the manifest, not exported, and are whole in the
`hermes-state/` copy). Config-only rows (section 2 rows of class config) are not copied by it.
The tool scrubs OpenCode's credential tables from the copy and refuses (as an error entry, the copy is dropped)
any backed-up database with another credential-looking table or column name (`--check-schemas`, 2026-10-20: 0
unexplained across all live databases; 20 token-metric, account-id and lease-marker names are allowlisted with
reasons in the script). Opening a source `mode=ro` can create zero-length `-wal`/`-shm` files beside a quiet database; no
data in a source changes. A configured store or path that does not exist (a partly provisioned machine) is
`"status": "missing"` in the manifest and on stderr, exit 0; `--strict-stores` makes it exit 1. Transcript content is copied as it is and can hold pasted secrets: a generation is
secret-bearing.

**Two rules for slice 2 (adversary review, 2026-10-20).** (a) Every path in section 5 item 5 is excluded from
every backup generation: a backup that carries a live key or account blob puts the credential in more places
than docs/threat-model.md allows once a generation syncs or leaves the Mac. (b) Cursor `acp-sessions` and the
handoffs `chains/` shrank within an hour on 2026-10-20 (266 → 264 dirs, 103 → 101): something prunes them, so
back them up before the pruning runs.

**Every live database found is WAL** (`PRAGMA journal_mode` = wal, or header bytes 18-19 = `2,2`
when a plain `-readonly` open was refused): a bare `cp` of the main file silently misses `-wal`
commits, and four DBs (`~/.zcode/v2/tasks-index.sqlite`, `~/.local/share/muse/session-index.db`,
`~/.grok/worktrees.db`, `~/.local/state/session-index/history.v2.sqlite`) cannot even be opened
`-readonly` without their `-shm`. **Use the SQLite backup API, never a live copy.**

1. **Single canonical SQLite — `.backup` API copy each:**
   `~/.hermes/state.db`, `~/.local/share/opencode/opencode.db`, `~/.zcode/cli/db/db.sqlite`,
   `~/.local/share/crush-acp/crush.db`, `~/.config/crush/.crush/crush.db`, the repo-local
   `~/src/djbclark-ade/.crush/crush.db` (0700 dir, gitignored, `-shm` touched 2026-10-20; row 79), Codex
   `state_5.sqlite`/`logs_2.sqlite`/`memories_1.sqlite`/`goals_1.sqlite`, `~/.copilot/session-store.db`.
   Form: Python `sqlite3.connect(src).backup(sqlite3.connect(dest))` with both paths as arguments (the
   documented SQLite online backup; runs while the writer lives). Not the `sqlite3 <db> ".backup '<dest>'"`
   dot-command: a `'` or a space in the path (`~/Library/Application Support`) breaks it.
2. **Per-conversation / per-session SQLite trees — walk and `.backup` each db (or copy db+wal+shm
   with the tool stopped):** Antigravity `~/.gemini/antigravity-cli/conversations/*.db` (582M),
   `~/.gemini/antigravity/conversations/`, `~/.gemini/antigravity-acp/conversations/` (781M), plus
   each `conversation_summaries.db` and, for the ACP store, the `conversations/<uuid>.meta` sidecar beside each db
   (268 files, some 0600, not opened); Cursor `~/.cursor/chats/<md5>/<uuid>/store.db` and
   `~/.cursor/acp-sessions/<uuid>/store.db`, each with its `meta.json` sidecar copied beside the backup (the
   resume picker reads it, skills/autorename/SKILL.md; a db without it is not a lossless copy: the tool lists a session whose `meta.json` does not exist under `sidecar_missing` and warns on stderr (db copied, store `ok`; 14 of 101 chat sessions never had one, 2026-10-20; an error under `--strict-stores`), and reports one whose `meta.json` is a symlink,
   excluded or gone during the copy as an error naming the session directory and marks the store `partial`, 2026-10-20).
3. **File stores — clone the directory:** `~/.claude/projects` (+ sidecar dirs `file-history`,
   `session-env`, `tasks`, `teams`; `sessions` only without its `*.key` files), Codex runtime `sessions/` tree
   (`~/.codex/sessions` and `~/.codex/session_index.jsonl` are symlinks into `~/ops/site-private/.codex-runtime/`; the tool
   follows a configured store root that is a link when it resolves under `$HOME` and is no credential path, records it as
   `root_symlinks`, and errors on a dangling, outside-`$HOME` or excluded one, 2026-10-20),
   `~/.qwen/projects/*/chats`, `~/.cline/data/sessions`, `~/.grok/{sessions,memory-v2,memtrace}`, `~/.gemini/tmp/*/chats`,
   `~/.omp/agent/sessions` (+ `history.db` via backup API), `~/.local/share/muse/sessions`,
   `~/.paseo/{agents,projects,agent-requests}`, `~/.config/herdr/{session.json,session-history.json,session-snapshots}`,
   `~/.copilot/session-state` (whole tree: `events.jsonl` transcripts, `workspace.yaml`, checkpoints, files; `session-store.db`
   alone is only the index), `~/.cursor/projects` (whole tree: `*/agent-transcripts/*/*.jsonl` are IDE conversations the
   session-finder adapter counts as sessions when their id is not in `chats`, skills/session-finder/adapters/cursor.py:88-94;
   108 files under 39 project dirs on 2026-10-20), zcode `~/.zcode/cli/rollout/model-io-sess_*.jsonl` (the raw transcript
   sidecars of `db.sqlite`; 3 files) with `~/.zcode/cli/{artifacts,memories}` (34M and 208K of session output, not
   rebuildable; `log/` and `exec/` are derived and may be skipped), Antigravity `brain/` under each of
   `~/.gemini/antigravity-cli` (299M, 265 dirs), `~/.gemini/antigravity-acp` (270M, 173 dirs) and `~/.gemini/antigravity`
   (IDE, 72M, 15 dirs): one dir per conversation db, holding `.user_uploaded/`, `.system_generated/logs/` and `scratch/`
   (a `.backup` of the db alone drops ~641M of uploads, logs and artifacts; `.system_generated/worktrees/` inside them are
   git checkouts of the item 5 duplicate class and may be skipped), plus antigravity-cli `history.jsonl`,
   `annotations/`, `implicit/`, `jetbox_summaries_proto.pb` and the IDE's `agyhub_summaries_proto.pb` and
   `antigravity_state.pbtxt` (small; copy rather than classify), `~/hermes-memory`, `~/.local/state/handoffs` (whole dir).
   **Items 1-3 name the canonical transcript stores and their sidecars; every other row (indexes, config, app state)
   is backed up per its own Lossless-backup cell** (added 2026-10-20, adversary round 9).
4. **Exporters verified to exist in docs on disk (none run):** `opencode session export <id>
   [--sanitize]` / `opencode session import <file> --directory`; `hermes sessions export` (JSONL,
   `--redact`, capped by `max_export_messages` = 20,000 stored rows — oversized sessions need the
   backup-API copy instead); Gemini CLI `/export-session <path>` (v0.43.0). Source:
   `~/src/djbclark-ade/docs/ade-everywhere-proposal.md` §6.1 (re-verified 2026-10-19). No first-party
   exporter found on disk for Cursor, zcode, Crush, Qwen, Cline, Grok, Muse, Antigravity.
5. **Duplicates/scratch to exclude from backup:** Hermes `state.db.bak-*` (2 stale ~1G copies),
   `gmail_index_v2.db` (rebuildable index), `~/.hermes/sessions` request dumps, Orca worktrees and
   `~/.herdr/worktrees` (git duplicates), `models/` voice assets, `natives/` binaries,
   `history.v2.sqlite` (rebuildable FTS5).
6. **Git-tracked already:** `~/.hermes` (but it is **dirty**: `config.yaml` modified, hindsight
   scripts deleted — commit or snapshot before relying on it), Codex `memories-git`.

## 4. Differences from the 6.1 table (live machine vs proposal)

1. **omp** — table says "canonical files"; live: JSONL sessions **plus** derived SQLite
   (`history.db`: `history`, `history_fts`, `session_recaps`, `session_titles`) and an `agent.db`
   holding credential blocks. Class should be "canonical files plus derived index".
2. **Codex index** — table: "the index records `rollout_path`"; live
   `~/.codex/session_index.jsonl` rows have keys `id,thread_name,updated_at` only, 35 rows against
   840 rollouts, and `state_5.sqlite` carries `rollout_migration_*` tables: the index role has
   moved into SQLite (or the jsonl is now a stub).
3. **Cursor** — table: one "SQLite" store; live: many per-session `store.db` (schema `blobs, meta`)
   under `chats/<md5-workspace>/<uuid>/` and `acp-sessions/<uuid>/`, 266 of the latter. Backup and
   CASS ingestion must walk directories, not open one file.
4. **Gemini CLI** — table: "path-hash keyed store"; live: dirs keyed by project *name*
   (`tmp/aiuse`, `tmp/djbclark`, …) with `projectHash` a field inside each record; only 4 session
   jsonl files exist on disk (short on-disk retention).
5. **zcode** — table: "SQLite"; live: canonical `db.sqlite` **plus** `cli/rollout/model-io-*.jsonl`
   transcript sidecars and a `v2/tasks-index.sqlite`. Crush likewise has **two** live dbs
   (`~/.local/share/crush-acp` for ACP via `CRUSH_GLOBAL_DATA`, `~/.config/crush/.crush` default)
   plus a repo-local `~/src/djbclark-ade/.crush`.
6. **Antigravity (not yet in table, as the table notes):** three separate conversation stores
   (cli 582M, IDE, ACP 781M), each one SQLite db per conversation plus a shared
   `conversation_summaries.db` — closest class: "canonical SQLite (per-conversation) plus derived
   summaries index".
7. **Qwen, Cline, Grok, Muse (not yet in table):** all four are **canonical files** (jsonl/json per
   session; Cline json-not-jsonl, Grok adds sidecars, Muse adds a rewind index) — Qwen's jsonl even
   carries `cwd` and `sessionId` per row, Claude-Code-like.

## 5. Not installed / could not classify

1. **devin** — not installed: `--` status in `acp-run --list`, no `~/.devin`, no `devin` binary.
2. **`~/.muse`, `~/.local/share/herdr`** — do not exist; Muse lives at `~/.local/share/muse`,
   herdr at `~/.config/herdr` + `~/.local/state/herdr` (the 2026-10-19 inventory already said so).
3. **Orca's durable DAG/session state** — could not classify beyond "Electron app data" (2.3G of
   IndexedDB/Session Storage/Local Storage under `~/Library/Application Support/Orca`); which
   database holds Orca's workflow state needs Orca running or its docs; worktrees themselves are
   git duplicates.
4. **Codex `state_5.sqlite` exact role** — `.tables` shows migration/thread tables (listed in
   section 2) but classifying which tables are canonical thread data vs derived index was out of
   scope for a read-only pass; treat as "derived index until proven otherwise".
5. **Credentials never opened** (existence recorded only; every path here is excluded from the section 3
   backups): `~/.claude/.credentials.json`, `~/.claude.json` (account), `~/.claude/sessions/*.key`,
   `~/.codex/auth.json`, `~/.gemini/oauth_creds.json`, `~/.local/share/opencode/auth.json`,
   `~/.grok/auth.json`, `~/.zcode/v2/credentials.json`, `~/.paseo/{daemon-keypair.json,local-credential}`,
   `~/.gemini/antigravity-acp/acp_token.json`, `~/.hermes/.env`, `~/.cline/data/settings/providers.json`,
   `~/.omp/agent/agent.db` (`auth_credential_blocks` table), `~/.local/share/crush/hyper.json`, `~/.local/share/crush/crush.json`,
   `~/.copilot/data.db` (`accounts`), Orca `Cookies` (Electron dir), `~/.orca/jira-tokens/`, `~/.orca/jira-sites.json`,
   the credential tables inside `~/.local/share/opencode/opencode.db` (not only `auth.json`; found by the adversary
   review of `bin/ade-backup-stores`, 2026-10-20: `credential` held 4 rows with API keys and an OAuth refresh/access
   token; `account`, `control_account` (`access_token`, `refresh_token`, `token_expiry`) and `account_state` were
   empty, `session_share.secret` was empty), scrubbed from the backup copy rather than excluded as a file,
   `mcp-auth.json` under `~/.cursor/projects/<slug>/` (68 files on 2026-10-20: MCP dynamic-client-registration
   records, 36 of them with a non-empty `client_secret`; the 12 `mcp_auth.json` files are tool descriptors and are copied),
   and the three MCP configs that hold plaintext Jina and Exa keys (skills/fallback-chains/references/web-access.md
   5.3 and 5.6.2) with every dated `.bak` copy beside them (3-5 each, 2026-10-12 to 10-18, same keys):
   `~/.config/opencode/opencode.json`, `opencode.json.bak*` and `opencode.bak` (not `opencode.jsonc`, which row 2
   copies), `~/.cursor/mcp.json` and `mcp.json.bak*`, `~/.gemini/config/mcp_config.json` and `mcp_config.json.bak*`;
   On 2026-10-20 (djbclark, /steps item 5) the 13 dated `.bak` copies were moved to `~/.local/state/ade/credential-bak/`
   (0700, files 0600, `MANIFEST-2026-10-20.txt` with the original paths; delete after 2026-11-19), joined later that day
   by `~/.zcode/cli/setting.json.bak-2026-10-18-mcp-trim` (14 copies plus the manifest; it matched key patterns by count); `opencode.bak` is a
   directory from 2026-07-30 and stays excluded. Slice 2 excludes that vault directory too.
   and `~/.config/crush/crushrc*` (the SIPB provider key, tools/acp-run/README.md; two `.bak` copies).
6. **Exporter claims** for tools other than OpenCode/Hermes/Gemini rest on the proposal's §6.1
   (verified 2026-10-19), not on a fresh `--help` run (avoided per the no-`--help`-on-live-CLIs rule).

## 6. Commands run (for re-verification)

`ls -la` over every store dir listed in section 2; `readlink -f ~/.codex/sessions`;
`timeout 300 du -sh` per store (plus `du -h -d 1` on `~/.local/state/bigteam`,
`~/.gemini/antigravity-cli/*`, `~/.omp/*`, `~/.gemini/antigravity-acp/conversations`);
`fd` (`-e jsonl`, `-g 'rollout-*.jsonl'`, `-g 'session-*.jsonl'`, `-g 'session_index*'`,
`-g 'SESSION_LOG.md'`, `-d N`) with `-x stat -f '%m %N' | gsort -rn | ghead` for counts/newest;
`file`-class checks via `od -An -tu1 -j18 -N2` (WAL header) where sqlite refused; `sqlite3 -readonly
<db> ".tables"` / `"PRAGMA journal_mode;"` / `"PRAGMA user_version;"`, retried as
`sqlite3 "file:<db>?immutable=1" ".tables"` for the four shm-less WAL dbs; `head -n1 <jsonl> | jq -r
'keys|join(",")'` for schemas; `date -r <epoch>` to humanize mtimes; `~/.local/bin/acp-run --list`;
`git -C ~/.hermes log --oneline -1` and `git -C ~/.hermes status --porcelain` (read-only git);
`rg -n '^## '` and `rg -l 'session(s)? export|export-session'` in `~/src/djbclark-ade`;
`command -v devin`. Post-write check: the credential-pattern scan from the slice's acceptance
clause was run over this report and found nothing (exit 1).

