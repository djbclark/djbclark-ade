
Source: Opus sub-agent digest of the Codex review, written for proposal v2 (session ee9e515d). Each finding was re-verified against its primary source on 2026-10-19 unless marked review-only.
# Codex review of ADE everywhere v1: accept/reject digest (2026-10-19)

Baseline: Paseo **0.12.0** is now installed (coordinator update), so F13 uses 0.12.0. "Verified" means I opened the primary source today. "Review-only" means I relied on the review's evidence without re-checking it.


## Findings

1. **F1 lease safety: ACCEPT.** (a) A Syncthing `<id>.lease` file cannot give mutual exclusion. (b) This holds. Syncthing reconciles changes asynchronously. When two devices write concurrently, it renames the older-mtime file to `.sync-conflict-*` and never refuses a write, so two offline hosts can both write a lease and both resume. Time-based leases also depend on clock skew and laptop sleep. (c) For v2: (1) the lease becomes advisory only; (2) continuing on another host after the origin went quiet *forks* a new session ID that records its parent, and that is the default; (3) exclusive same-ID continuation needs an online handshake in which the origin acknowledges it has stopped, for example over Tailscale SSH; (4) a stable device ID (Syncthing's device ID) replaces the hostname; (5) delete the claim that "resuming on two machines is the only conflict". (d) https://docs.syncthing.net/users/syncing.html

2. **F2 Hermes state.db: ACCEPT. This is the most important correction.** Verified: Hermes documents `~/.hermes/state.db` as the "canonical store for all session messages", and it also holds the `gateway_routing` table; `sessions.json` is only a legacy mirror. `hermes sessions export` (JSONL is the default) writes "full session metadata and every stored message", including compacted and rewound turns. Importing that file restores the rows as archived history, not as live context. `--redact` exists for sharing. v1 §5.1 called the 1.6 G database rebuildable, which is wrong. Change: (1) classify every store as canonical, derived or cache; (2) for Hermes, keep a nightly `hermes sessions export` JSONL in the archive, plus a `sqlite3 .backup` copy (never a live file copy); (3) only the Gmail index and the installs are true caches; (4) note that a backup export needs each session under `max_export_messages`. https://hermes-agent.nousresearch.com/docs/user-guide/sessions/ , https://www.sqlite.org/backup.html

3. **F3 the T4 durability claim: ACCEPT.** Verified: Syncthing's untrusted-device encryption is still labelled "beta / testing only", and recovery needs both the password and the folder ID. Syncthing is synchronisation, not backup, and deletions propagate. Change: (1) restate T4 with a stated RPO, meaning loss since the last collection is acceptable; (2) treat "cold tier on one peer" as a single copy, and require two retained copies before any origin deletion; (3) add file versioning or a separate backup outside delete propagation; (4) store the folder ID and password in 1Password; (5) add a restore-from-ciphertext drill. Inference, not verified: making an untrusted peer the *introducer* lets it add devices to trusted machines, so drop "acts as introducer". https://docs.syncthing.net/users/untrusted.html

4. **F4 collector protocol: ACCEPT.** Hardlinks share the inode (not an archive), "grown only" misses rewrites, sidecars skew; `SessionEnd` is time-bounded and skipped on kill (review-only). Change: copy/APFS-clone, never hardlink; capture generations with size, sha256 and a completion marker written last; trim partial last line; `SessionEnd` only enqueues; periodic plus on-wake reconcile. https://code.claude.com/docs/en/hooks

5. **F5 Claude's stable project key: ACCEPT WITH CHANGE.** Verified on the sessions page. `CLAUDE_CODE_PROJECT_DIR_NAME` (v2.1.234 or later, 1 to 64 characters from `[A-Za-z0-9_-]`) names the project directory. It is honoured **only together with `CLAUDE_CONFIG_DIR`**, must be set in the launching shell (a settings `env` block does not work), and without it every project would merge into one directory. The page frames it for hosts that give each session its own config dir. Also verified: `--resume <id>` searches the current project and its worktrees first, then every other project, and reports not-found when **more than one other** project holds that ID. That is narrower than v1's rule. Change: (1) a new managed launch (`launch.py`, Paseo profile) may set a per-project `CLAUDE_CONFIG_DIR` plus the key, but only after testing how credentials, plugins and settings behave in a split config root (prototype, do not make it the default yet); (2) existing sessions need no rewrite for the transcript directory if the paths match; (3) v1's path rewriting is limited to cwd fields; (4) a `/Users`→`/home` round trip is an acceptance test. https://code.claude.com/docs/en/sessions

6. **F6 secrets trust model: ACCEPT.** Verified in the fork's AI-GUIDANCE: "not per-secret confidentiality among callers sharing the authorized operator identity", and client-family labels are "correlation metadata, not authenticated principals". So v1's "which process may read them" is wrong. The point that the 1Password SSH agent needs the desktop app, while headless hosts need a service account, is review-only but correct in substance. Change: (1) state the same-user trust model; (2) define separate auth paths for laptop, headless Linux and CI; (3) mark Linux support for sudo-secretspec as unverified; (4) put a backend interface in front of 1Password, age or none, so T6 works without 1Password. https://github.com/frdminc/sudo-secretspec/blob/sudo-main/sudo-secretspec/AI-GUIDANCE.md

7. **F7 service scopes: ACCEPT.** README line 67: `acp-dispatch reap` recovers *local* slices, so per-host, not singleton; collection is per-origin, only downstream ingest is singleton; Telegram ownership is per bot token. Change: scopes per-host / per-account-or-bot / fleet-coordinator; manual disable-then-enable handover, no auto-failover; synced Paseo schedules never auto-enable everywhere; quota caches advisory. https://core.telegram.org/bots/api#getupdates

8. **F8 workspace state: ACCEPT WITH CHANGE.** A transcript cannot restore unpushed or dirty work; the 106 G bigteam and 14 G Orca figures measure size, not disposability. Change: T3 split into readable history / native continuation / exact workspace; Phase 0 deletion becomes "scan for unpushed, dirty and unique reports, then delete"; add a WIP-transfer command (`git bundle` or wip branch). https://git-scm.com/docs/git-bundle

9. **F9 memory concurrency: ACCEPT WITH CHANGE.** Clean merges are not semantic consistency and start-of-session pull misses long or offline sessions, but an observation/consolidation pipeline is over-engineering for one operator. Change: local lock around git mutations; commit+push per write with fetch/rebase retry; conflicts surfaced via `hermes-ping`; tombstones for deletes; Tier 1 chains authoritative in the archive, Tier 2 in git. https://git-scm.com/docs/git-rebase

10. **F10 provider survey: ACCEPT. v1 is stale.** Verified per provider:

    | Provider | Finding |
    |---|---|
    | Gemini | `/export-session <path>` and `gemini --session-file` (PR 26514, merged 2026-05-08) shipped in v0.43.0 (2026-05-22). |
    | OpenCode | The v2 command is `opencode session export <id> [--sanitize]` / `session import <file|url> --directory`, not v1's top-level `export`. |
    | Codex | Has `codex resume`, `codex fork` and `exec resume`, plus `/import` from Claude Code and Cursor (changelog). Remote connections continue a chat *on the host*; they do not move it. I found no first-party rollout export/import. Issue 51934 shows `state_5.sqlite` records `rollout_path` through symlinks, so copied rollouts depend on resume's fallback by ID. That matters here, because `~/.codex` sessions live behind the `site-private/.codex-runtime` link. |
    | Copilot | `--remote-export` (read-only copy to GitHub.com), `/share file|html|gist`, and `--remote --resume` of remote tasks. All of it depends on the account. |
    | Cursor | Docs list only `--resume`, `ls`, `resume`, and `worker` (a private cloud worker). No export/import verified. |
    | Hermes | See item 2. |

    Change: replace v1 §6.1 with a capability matrix of {readable export, lossless backup, native resume, import, remote control}, prefer vendor commands, and pin adapters to versions. https://geminicli.com/docs/changelogs/ , https://dev.opencode.ai/v2/docs/cli/commands/ , https://developers.openai.com/codex/changelog , https://github.com/openai/codex/issues/51934

11. **F11 CASS: ACCEPT WITH CHANGE.** Verified (README): "Remote Sources (Multi-Machine Search)" over SSH/rsync; `cass sources setup` reads `~/.ssh/config`, probes hosts, can install remotely; `sources add/sync/doctor`, per-agent path mappings, per-source provenance, `cass schedule install`, chunked snapshots, JSON robot API with schemas. Covers 20+ agents incl. Claude, Codex, Gemini, Cursor, OpenCode, Copilot CLI, Crush, Hermes, Qwen, Cline, omp. Maturity (GitHub API): created 2025-11, ~1,190 stars, v0.10.0 2026-10-02, active. Caveats: (1) **license is MIT plus a rider granting no rights to Anthropic, OpenAI or anyone acting "on behalf of" them**, "use" including indexing into automated pipelines: djbclark decides (not legal advice); (2) README finds OpenCode via `.opencode/` dirs, ours is `~/.local/share/opencode/opencode.db`; (3) pull-over-SSH, so offline hosts are unsearchable. Change: Phase-1 spike on this corpus before building an index; `session-finder` keeps live sessions and claims. https://github.com/Dicklesworthstone/coding_agent_session_search

12. **F12 orchestration parity: ACCEPT.** Worktrees give no DAG persistence, file claims, quota-reset resume or crash recovery. 0.12.0 itself fixes parents "told a child finished when its task was stopped" and permits "reporting success over SSH while the request stayed pending": exactly the needed acceptance tests. Change: a Paseo adapter contract (idempotent start, question/permit response, cancel, report, resume); `acp-dispatch` owns its processes; herdr stays the plain-terminal fallback; drop sleeper/DAG retirement claims from §7.2. https://github.com/getpaseo/paseo/blob/main/CHANGELOG.md

13. **F13 Paseo already has usage, attention and history: ACCEPT. It is stronger than the review says.** Verified in the changelog, with the baseline now 0.12.0:
    1. The **Usage** dialog, pinned usage summaries and **usage sources in the plugin SDK** shipped in **0.11.0** (2026-10-07), with `providers.listUsage()` earlier still.
    2. 0.12.0 adds `paseo usage` (CLI quotas and reset times).
    3. History search and **Import session** (Claude, Codex, omp and others) have existed since 0.9 or earlier.
    4. In the registry, Agents Dash List shows workspaces from every host ordered by attention (multi-host needs 0.8 or later; its state is per host).
    5. Herald lists waiting questions, permissions and plan approvals, but each item is a sentence written by an LLM (Haiku by default), and child agents are off by default.
    6. Agents History searches archived conversations only for file-backed providers on *that* daemon (Claude, Codex, omp, Pi).

    Change: (1) the plugin becomes an `aiuse` usage source plus a routing pill; (2) the Helm panel extends Dash List or Herald-style events with verbatim questions, ranking and request IDs; (3) the search panel targets the CASS-or-archive backend. https://paseo.sh/plugins/panrafal/agents-dash-list , https://paseo.sh/plugins/gpambrozio/herald , https://paseo.sh/plugins/panrafal/agents-history

14. **F14 config ownership: ACCEPT.** Verified: 0.12.0 fixes Paseo "replacing a symlinked `config.json` with a regular file" and a schema rejecting `agentProfiles`, so v1's symlinked Paseo config would silently break. Change: merge owned keys (`daemon.agentProfiles`, plugins), never symlink; generate profiles from `route_agent.py policy`; pin daemon, client and plugins together. https://github.com/getpaseo/paseo/blob/main/CHANGELOG.md

15. **F15 CLI vs provisioner: ACCEPT WITH CHANGE.** Right that "one fewer config language" is weak and that ownership, adoption, diff and rollback are the costly parts; but chezmoi on top of Ansible plus our manifests risks two owners per file. v2: one Python `ade` entry point with TOML for ADE concepts; packages and services delegated to existing Ansible roles; `ade link` stays a narrow symlink-and-merge engine with `plan`/diff, back-up-then-adopt, idempotent reapply and `unlink`; chezmoi recorded as the switch-to if templating needs grow; mise for runtimes (item 17). https://www.chezmoi.io/user-guide/include-files-from-elsewhere/

16. **F16 overlay contract: ACCEPT.** Change: precedence public < private < role < machine, keyed merges for hooks/plugins/profiles, unknown-key validation; works with no companion and any git remote (Forgejo included); defer the rename until consumers are mapped (Q1 becomes "later"); one services schema. https://github.com/ithinkihaveacat/dotfiles/

17. **F17 Linux and root of trust: ACCEPT.** Inventory §5: node/npm come from `~/.hermes/node/bin`; user units need `loginctl enable-linger`; a container cannot test keychain, OAuth or suspend. Change: pinned uv/Python/Node acquisition (mise or vendor installers); a real Linux user plus reboot in the first slice; container CI is a fast check, not the gate. https://www.freedesktop.org/software/systemd/man/latest/loginctl.html

18. **F18 retention and privacy: ACCEPT WITH CHANGE.** Indexes, plugin indexes and exports are further plaintext copies; device removal does not erase existing copies. Change: one short section on full-fidelity backup vs `--redact`/`--sanitize` exports, index permissions, lost-device procedure (revoke device, rotate folder password), deletion scope stated as future-access-only unless djbclark wants more, and a deny-list from `operator.toml`/`machines/` instead of grepping the login. https://github.com/getsops/sops

19. **F19 phase order: ACCEPT.** v1 deletes first and proves portability last. v2 phases become gates: (1) preserve and classify (back up Hermes, Orca workspaces and bigteam reports; no deletion yet); (2) a thin vertical slice: Mac plus a real Linux user with an empty companion and one Claude and one Codex route, through apply, reapply and doctor; (3) a sessions spike: CASS evaluation, a capture protocol, a cross-home resume test, and the fork-by-default continuation from item 1; (4) a Paseo pilot running one real delegated workflow, including questions, permits, quota resume and rollback; (5) broaden to the other providers, services and memory; (6) only then retire tools, delete scratch, and run the newcomer test. Durations become estimates. https://github.com/getpaseo/paseo/blob/main/CHANGELOG.md

20. **F20 "no central node": ACCEPT.** Tailscale coordination, 1Password and vendor auth are outside dependencies; restate as "no single indispensable *user* machine". Mobile needs direct tailnet or relay (review-only). Citations: see B.

## A. Missed alternatives worth adopting

**Adopt in v2:**

1. **A1 CASS:** the first spike for multi-host search, since it already does SSH collection, provenance and path maps. The licence rider needs djbclark's decision. https://github.com/Dicklesworthstone/coding_agent_session_search
2. **A13 / F13 Paseo's own Usage, History, Import session and registry plugins:** build only the delta on top of them. https://paseo.sh/plugins/panrafal/agents-dash-list
3. **A14 / A15 keep Orca and herdr during the pilot:** they are the baseline and the fallback for arbitrary TUIs. https://herdr.dev/docs/agent-automation/
4. **A23 mise:** owns the runtimes and removes the Hermes-owned Node. https://mise.jdx.dev/dev-tools/
5. **A2 git-annex numcopies / preferred content:** the right policy layer for the cold tier, enforcing "two copies before deletion". https://git-annex.branchable.com/git-annex-numcopies/
6. **A20 chezmoi:** recorded as the named fallback in item 15, not adopted now. https://www.chezmoi.io/user-guide/setup/

**Drop:** A3 Mutagen and A4 rclone bisync (pairwise, no ownership answer); A5 Perkeep (weight); A6 clync (Claude-only, merge picks between divergent runs; comparison only); A7 Dolt, A8 Turso Sync, A9 sqlite-sync (need app integration, cannot sit under vendor stores; sqlite-sync is Elastic License); A10 Litestream/LiteFS (reject on topology, not "discontinued"); A11 SessionStore (only if ADE owns SDK launches); A12 Taildrive; A16-A19 Superset, OpenChamber, Happy, Conductor (weaker independence or one-harness lock-in); A22 Nix (not now for Macs); A24 devbox (per-project); A25 sops-nix/agenix (vps-primary only).

## B. Citation fixes

1. **C10 LiteFS (confirmed wrong).** Ben Johnson, 2025-01-28, in the cited thread: "LiteFS hasn't been discontinued but we've refocused effort … limited updates." Corrected claim: LiteFS has limited maintenance and a single primary writer. https://community.fly.io/t/litefs-discontinued/23682 , https://fly.io/docs/litefs/
2. **C4 issue 57920 (confirmed wrong).** The issue is "`claude --resume <id>` cannot find intact transcript after original worktree path is removed"; recreating the directory fixes it. Move the duplicate-ID rule to C1, which states it verbatim. Keep 57920 for a different, real point: `ade sessions pull` must create the target cwd before resuming. https://github.com/anthropics/claude-code/issues/57920 , https://code.claude.com/docs/en/sessions
3. **C7 OpenCode (partly).** v2 is `opencode session export|import`, with `--sanitize` and `--directory`. https://dev.opencode.ai/v2/docs/cli/commands/
4. **C1 Claude sessions (holds, incomplete).** Add `CLAUDE_CODE_PROJECT_DIR_NAME` and the narrower "more than one other project" lookup rule. https://code.claude.com/docs/en/sessions
5. **C20b Syncthing untrusted devices (partly).** Add "beta / testing only" and the requirement to keep both password and folder ID. https://docs.syncthing.net/users/untrusted.html
6. **C23 CASS (partly).** It does SSH multi-machine collection, so prior-art line 71's "none sync" is wrong. https://github.com/Dicklesworthstone/coding_agent_session_search
7. **C20 Syncthing configuration (partly).** For conflict behaviour cite the "Understanding Synchronization" page, which does not support leases. https://docs.syncthing.net/users/syncing.html
8. **New citation for §6.1, Gemini.** Export/import exists; cite v0.43.0 and PR 26514 alongside C36. https://geminicli.com/docs/changelogs/ , https://github.com/google-gemini/gemini-cli/pull/26514
9. Review-only, not re-checked: C6 clync also has folder/S3/encryption; C11 cr-sqlite issue 444 notes a maintained fork; C18b sqlite-sync has no successor lineage (Elastic License); C15 cite chezmoi's password-manager page; C26/C28/C30 mobile needs direct or relay, orchestration MCP is host-local, Docker mounts all of `/home/paseo`.
10. **Prior-art doc.** Line 54 (sops-nix), line 66 (rclone has bisync) and line 71 (CASS) all need correcting before it is reused.

## Unverifiable / open

CASS rider applicability (legal, djbclark's call); Cursor native export; sudo-secretspec Linux parity; untrusted Syncthing peer as introducer (inferred unsafe, untested).

