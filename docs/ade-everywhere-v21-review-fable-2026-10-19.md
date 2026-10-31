# ADE everywhere v2.1 — advisory review (Claude Fable 5.1), 2026-10-19

Read-only. Inputs: `docs/ade-everywhere-proposal.md` (894 lines, §9 = 17 decisions, §12 = response to the first review), `docs/ade-everywhere-codex-review-2026-10-19.md`, `docs/ade-everywhere-review-evaluation-2026-10-19.md`, `docs/ade-everywhere-inventory-2026-10-19.md`, `AGENTS.md`, `README.md`, `tools/acp-run/README.md` ("What it adds", "Dispatch slice controls"). Local probes: `paseo --version` = 0.12.0; `~/.paseo/config.json` keys (`version, daemon{listen,hostnames,cors,relay}, app, agents, features`); `~/.local/share/opencode/opencode.db` 945.6 MB; `~/.hermes/state.db` 1.6 GB; `~/.codex/sessions -> ~/ops/site-private/.codex-runtime/sessions`; 554 Claude project dirs / 1435 top-level transcripts; repo `LICENSE` = MIT; `cass`, `chezmoi`, `syncthing` not on PATH. Web verification URLs are inline. Findings the v2 response already applied (§12) are not repeated; where a v2 fix was applied incompletely it is called out as a new finding.

## 1. Verdict

v2.1 is a coherent plan with the right shape (public kit + private companion, chezmoi for `$HOME`, Paseo as the front end over an acp-run engine, sessions as an append-only synced archive), and the §12 responses to the Codex review mostly land. It is **not yet executable as written in three places**. (1) The chezmoi "externals overlay" in §4.4 is specified as a mechanism chezmoi does not have: externals are not source state, a target defined by both the public source and an external is an *inconsistent state* error, not "private wins", and `git-repo` externals are opaque to `diff`/`dump`/`managed`. Phase 0/1 will stall on this unless the overlay is re-specified (recommended: companion as a submodule or a fixed clone that the public templates `include`, plus a templated `.chezmoiignore`). (2) The compute routing in §8 Phase 3, §11.2 and §11.3 sends "archive index builds, Syncthing initial scan, Hermes export" to "the Linux peer", but Q2 and principle 6 make that peer *receive-encrypted and blind*; it cannot index what it cannot read and does not run Hermes. (3) CASS "pointed at the archive" works only if the archive is laid out in each provider's native shape under a `type = "local"` source; the proposal's `<provider>/<device-id>/<project-slug>/<session-id>/<generation>.jsonl` layout is not recognisable by any connector, and per-session generation files will index as duplicates. Smaller but real: "chezmoi keeps the originals it replaced" is false; Homebrew's supported install is itself a curl-pipe, so the root-of-trust rule needs an exception or the `.pkg`; the Paseo route has no `--profile` on `run`, no cross-host parentage, no equivalent of acp-run's effort/context/read-only flags; several v2 edits left stale references (`ade link` ×3, `overlay.toml`, §11.2 phase numbers). The product framing (Q17) adds naming (PyPI `ade` is taken), licence, release and test-matrix work that §8 does not schedule. None of this changes the architecture; all of it should be fixed in the text before Phase 0 starts, because Phase 0–1 build directly on items (1) and (3).

## 2. Findings (most severe first)

### F1 — blocker — The §4.4 externals overlay is not a chezmoi mechanism
**Claim** (§4.4, lines ~224–283): the companion is pulled in as a `.chezmoiexternal` entry and "private files win where both define a path"; `chezmoi diff`/`managed` show the merged result.
**Verified**: chezmoi reference, *Special files → `.chezmoiexternal.<format>`* and *`external_` prefix* (https://www.chezmoi.io/reference/special-files/chezmoiexternal-format/, https://www.chezmoi.io/reference/source-state-attributes/): for `git-repo` externals "chezmoi cannot manage any other files in that directory", the contents are "not manifested in `chezmoi diff` or `chezmoi dump`" and are listed by `chezmoi unmanaged`. For `archive`/`archive-file` externals and for submodules, a target present in both the source directory and the external is reported as an inconsistent state (twpayne/chezmoi#3131, maintainer: "chezmoi does not attempt to merge its state", https://github.com/twpayne/chezmoi/issues/3131). There is no precedence rule; there is no "overlay". Externals also give no way to authenticate to a private repo beyond what `git`/the archive URL carries: `archive` externals from a private Forgejo/GitHub repo would need a token in the URL or a `.chezmoiexternal.tmpl` that reads one (https://www.chezmoi.io/user-guide/include-files-from-elsewhere/).
**Recommended change**: pick one of two supported shapes and write it into §4.4 and Phase 1. (a) **Fixed clone + templates**: `ade clone` checks out the companion to `~/.local/share/ade/private` (or a chezmoi `.chezmoidata`-named path); public templates use `{{ if stat "<path>" }}{{ include "<path>" }}{{ end }}` or `{{ .private.* }}` data loaded via `.chezmoidata/` + `.chezmoitemplates`; a templated `.chezmoiignore` drops any public target the companion declares. Precedence is then explicit (template logic), `diff`/`managed` are complete, and auth is plain git over the tailnet. (b) **Companion as a git submodule inside `home/private/`** with non-colliding targets (`private_dot_config/...` only for paths the public tree does not define) and `exact_` avoided on shared directories. (a) is recommended: it is the only shape that gives "private wins" semantics. Either way, replace the sentence "private files win where both define a path" with the actual rule, and add a Phase 1 test: `chezmoi verify` + `chezmoi managed | diff` against the inventory's path list.

### F2 — blocker — The "Linux peer" is routed for work it cannot do
**Claim**: §8 Phase 3 ("initial Syncthing scan and the first full index build run on the Linux peer"), §11.2 row "2 sessions spike … the index runs on the Linux peer", §11.3 ("archive index builds (CASS or FTS5), Syncthing initial scan, Hermes export | the Linux peer").
**Verified against the proposal itself**: §3 principle 6 (lines ~122–124) and Q2 (§9) make vps-primary the *receive-encrypted, non-introducer* Syncthing peer that holds ciphertext only. Syncthing docs: an untrusted/receive-encrypted device "stores the data encrypted" and cannot read or serve plaintext (https://docs.syncthing.net/users/untrusted.html). Hermes runs on the Mac (`~/.hermes/state.db`, inventory §6), not on vps-primary. So the three heaviest jobs are routed to a host that (a) cannot read the archive and (b) does not have the Hermes store.
**Recommended change**: either (i) add a *trusted* Linux peer (a Hyades CI runner or a second VPS with the folder key) and name it as the index host, or (ii) run index builds on the Mac via `bg` with the CI-first check, and move "Hermes export" to the Mac unconditionally. Update §8 Phase 3, §11.2 and §11.3 consistently. If (i), schedule the trust decision in Phase 2 (it changes the Syncthing topology and the threat model in Q2).

### F3 — major — CASS "pointed at the archive" needs a native-shaped layout, or it is a fork
**Claim** (§6.3 item 4, line ~420): CASS is "pointed at the archive instead of at remote hosts, with a per-provider path map per device"; §6.2 CASS row; Q10.
**Verified** (README, https://raw.githubusercontent.com/Dicklesworthstone/coding_agent_session_search/main/README.md): `sources.toml` supports `type = "ssh"` **and `type = "local"`** with `paths`, so a local mirror *can* be a source — that part of the claim holds. But: `path_mappings` "rewrite remote paths to local equivalents" *inside* sessions (workspace paths), they do not change how a connector discovers files; the mirror is scanned by the normal connectors, which expect each provider's native shape (`~/.claude/projects/<slug>/<id>.jsonl`, `$CODEX_HOME/sessions/YYYY/MM/DD/*.jsonl`, OpenCode `opencode.db`, Hermes `state.db`). The proposal's `<provider>/<device-id>/<project-slug>/<session-id>/<generation>.jsonl` is not any of those; and one directory per session with several generation files would be seen as several transcripts (duplicates), with the incremental lexical index known to miss appended documents (open issue #466, https://github.com/Dicklesworthstone/coding_agent_session_search/issues/466). Also stale: the proposal says CASS cannot read OpenCode's new store; v0.10.0 (2026-10-02) indexes `opencode.db` (issue #504) with `OPENCODE_STORAGE_ROOT`; and `~/.hermes/state.db` is a supported connector now, so the "export feed for stores CASS cannot read" list in §6.3 is one shorter. Rebuild cost: a v0.10.0 upgrade forces a full rebuild; closed issues #372 (6.5 h OpenCode index) and #366 (large-corpus rebuild abort) are the realistic scale for ~10 GB. Raw-mirror chunking (256 KiB chunks for JSONL ≥256 KiB) means growing files are cheap for the *mirror*; the *index* side is #466.
**Recommended change**: (a) make the archive layout **native per device**: `~/ade-sessions/<device-id>/claude/projects/<slug>/<id>.jsonl`, `<device-id>/codex/sessions/...`, `<device-id>/opencode/opencode.db`, each registered as a `type = "local"` source named by device; (b) drop per-session generation *files* from the indexed tree — keep generations as Syncthing versioning + git-annex history, and expose one current file per session to CASS; (c) correct the OpenCode and Hermes adapter sentences and cite the README env table; (d) schedule in Phase 3 a one-off measurement (`cass index --full` wall-clock on the Mac over the real 10 GB) before deciding CASS vs FTS5, and record #466 as the risk that decides it. (e) The licence rider (Restricted Parties = OpenAI/Anthropic and anyone "acting … on behalf of" them; "use" includes indexing) is fine for the operator but belongs in Phase 7 product docs as a caveat for third parties.

### F4 — major — "chezmoi keeps the originals it replaced" is false
**Claim** (T1, lines ~34–38; repeated in §4.3 bootstrap).
**Verified**: twpayne/chezmoi discussion #4657 (maintainer): on a new machine `chezmoi apply` overwrites existing targets without warning; it only prompts/diffs for targets it previously wrote (https://github.com/twpayne/chezmoi/discussions/4657). `chezmoi apply` has no backup mode.
**Recommended change**: `ade bootstrap` runs `chezmoi managed --path-style absolute | gxargs gtar …` (or `chezmoi archive` of the *current* `$HOME` targets) into `~/.local/state/ade/backup-<date>.tar` before the first `apply`, and the doc says so. Add to Phase 1 acceptance.

### F5 — major — The `--via paseo` route cannot express several things acp-run promises today
**Claim** (§7.2 table line ~520 "`--via paseo`" row; §6.3 item 6; Q15/Q16).
**Verified** (CLI reference https://raw.githubusercontent.com/getpaseo/paseo/main/public-docs/cli.md; SDK agents/orchestration docs; Paseo 0.12.0 installed): `paseo run` takes `--provider`, `--cwd`, `--env`, `--label`, `--title`, `--wait-timeout`, `--no-wait`, `--output-schema` (not with `--no-wait`), `--workspace`/`--new-workspace`, worktree flags; `paseo wait <id> --timeout`, `send`, `stop`, `permit allow|deny`, `agent mode <id> bypass|plan`, `agent detach`; global `--host`. There is **no `--profile`** on `run` — profiles are per-daemon objects; `PASEO_AGENT_ID` parentage only resolves on the same daemon ("Without explicit placement, the new agent becomes its subagent in the same workspace"), so cross-host dispatch via `--host` loses the parent link. `~/.paseo/config.json` on this Mac has no `daemon.agentProfiles` key today. Not expressible as first-class options: acp-run's `--effort`, `--context 200k|1m`, `--set fast=on`, `--perm deny` read-only (only `mode plan|bypass`), per-vendor `--agent-env`; `acp-dispatch resume RECORD` after a quota stop (Paseo agent ids are not ACP session ids); exit codes 3/4/124 and the `BLOCKED:` contract; the report-file footer. `waitForFinish()` timeout does not cancel the agent.
**Recommended change**: in §7.2 add a column "expressible via Paseo today / needs plugin / stays acp-run-only", and state the fallback: `--via paseo` is a *placement* choice (workspace, visibility, Helm row) and the engine keeps calling `acp-run` for anything that needs effort/context/perm. Cross-host: record the parent id yourself in `labels` (the CLI has `--label`) and have the ADE plugin draw the edge. Schedule a Phase 4 spike that maps every acp-dispatch flag to a Paseo option or to "not available" before the Helm panel is built on it.

### F6 — major — Root of trust: Homebrew's supported install is a curl-pipe
**Claim** (§4.4, ~line 270: "never curl-pipes an installer, chezmoi's own included"; §9 Q3).
**Verified**: Homebrew's only supported installer is `/bin/bash -c "$(curl -fsSL …/install.sh)"` (https://brew.sh, https://docs.brew.sh/Installation); the alternatives are the `.pkg` on https://github.com/Homebrew/brew/releases (macOS) or an "unsupported" git-clone/tarball install into `/opt/homebrew`. chezmoi's releases ship a cosign-signed `checksums.txt` (https://www.chezmoi.io/install/#verify-the-signature), so chezmoi can be installed without curl-pipe; CASS's `install.sh` is curl-pipe (it has `packaging/homebrew` as the alternative).
**Recommended change**: the rule should read "no curl-pipe *except* the Homebrew `.pkg` (checked against its GitHub release checksum) on a fresh Mac; on Linux, distro packages or cosign-verified release archives". Put the verification commands in `ade doctor --bootstrap`. This is Phase 0 material (the first new Mac is the test).

### F7 — major — Fork semantics should use the native fork, not a custom first record
**Claim** (§6.3 item 5): fork-by-default writes "a new id whose first record names the parent id and device".
**Verified**: Claude Code `claude --resume <id|name|path> --fork-session` creates a new session id continuing the transcript (https://code.claude.com/docs/en/cli-reference); the native transcript keeps the lineage. Codex has `codex resume` and `/import` (changelog); a `fork` subcommand was not found in the pages fetched — treat Codex fork as "resume into a new rollout" until verified. If `ade sessions pull` writes a custom first record, the native TUIs will either ignore it or reject the file.
**Recommended change**: `ade sessions continue` shells out to the provider's own fork (`claude --resume … --fork-session`, `codex resume`) and records parentage in the archive's sidecar manifest, not in the transcript. Note also Claude's cross-project resolution rule ("resolves the ID only when exactly one other project holds a transcript") matches the proposal's refusal rule — fine.

### F8 — major — Stale references survive the v2 edits
**Verified in the proposal text**: `ade link` still appears at §4.3 line ~221 ("deleted once `ade link` owns every path"), §7.2 line ~525 ("`ade link` owns the links") and §7.3 line ~529 ("installed on every daemon by `ade link`") although Q4 removed the command; `overlay.toml` is named in §12's F16 row but does not exist in §4.3; §11.2's phase labels ("2 sessions spike", "3 …") do not match §8's numbering; §6.2 and §6.3 still say CASS cannot read OpenCode (see F3).
**Recommended change**: one pass with `rg -n 'ade link|overlay.toml' docs/ade-everywhere-proposal.md`, and renumber §11.2 from §8.

### F9 — major — Product framing (Q17) has unscheduled consequences
**Verified**: PyPI `ade` is taken (Edwin A. Suominen, Apache); `ade-cli` returns 200 on PyPI (also taken or squatted — check); the repo `LICENSE` is MIT while the proposal's dependency table lists Apache-2.0 for Paseo (holds: https://raw.githubusercontent.com/getpaseo/paseo/main/README.md "License Apache-2.0") and CASS carries the MIT+rider; §8 has no phase that produces a release (tags, checksums, `brew` tap or `uv tool install` name), a test matrix (macOS arm64 + NixOS + Linux-x86 CI runner + the three headless agents), or a public-safety review of the kit for leaked private paths (the inventory lists 5 broken rules links and 4 untracked configs that would ship).
**Recommended change**: add "Phase 7a release" with: CLI name decision (`ade` on PyPI is out; `ade-kit`/`kool-ade` on PyPI + `ade` as the installed binary name is fine), signed tags, a GitHub Actions matrix, a `ade doctor --public` leak check, and the CASS-rider caveat in docs.

### F10 — minor — Sessions model edge cases
(a) Syncthing simple/staggered versioning only archives files *changed or deleted by remote devices* (https://docs.syncthing.net/users/versioning.html); local deletes on the Mac are not versioned on the Mac — only on peers. The proposal's "versioning covers accidental deletion" holds across devices but not for the single-device case; say so. (b) Receive-encrypted peers see a rename as delete+full upload; immutable generation files make this moot, but a `<generation>.jsonl` rename scheme would not. (c) Untrusted devices are still documented as beta (https://docs.syncthing.net/users/untrusted.html) — cite. (d) NixOS `services.syncthing.settings.folders.<name>.type = "receiveencrypted"` is supported. (e) Hermes export is bounded by `max_export_messages` in its config; the export job must page or raise it. (f) Codex's `~/.codex/sessions` on this Mac is a symlink into `site-private/.codex-runtime/sessions` (inventory) — the archive job must follow it and the companion must keep that symlink, or Codex sessions vanish from the archive silently. (g) Takeover handshake: the loss window is the Syncthing scan interval + the TUI's write latency; the proposal gives no bound; recommend `fsWatcherEnabled` + a `sessions push --now` before handing over.

### F11 — minor — Codex fork claim and `exec resume` not verified
§6.3 cites `codex fork`; the changelog pages fetched show `resume` and `/import` only. Mark as "verify on the installed Codex" rather than assert.

### F12 — minor — Paseo profile key
§7.2/§7.3 assume `daemon.agentProfiles` in `~/.paseo/config.json`; the installed 0.12.0 file has no such key (`daemon` = `listen, hostnames, cors, relay`). Profiles exist as daemon objects via UI/MCP; don't promise a file-level overlay for them until the key is confirmed in Paseo's config schema.

## 3. Decisions whose consequences are under-scheduled

| Decision (§9) | Consequence not in §8 | Phase it belongs in |
|---|---|---|
| Q1 chezmoi | overlay re-spec (F1); pre-apply backup (F4); Ansible/`$HOME` boundary test; `.chezmoiroot` and `chezmoi verify` in CI | 0–1 |
| Q2 receive-encrypted vps-primary | names a *trusted* index host or moves index work to the Mac (F2); Syncthing untrusted beta risk accepted explicitly | 2–3 |
| Q3 no curl-pipe | Homebrew exception/`.pkg` path (F6); cosign verification steps in `ade doctor` | 0 |
| Q4 drop `ade link` | three stale mentions (F8) | text now |
| Q10 CASS | native-shaped archive layout; generation files excluded from the index; 10 GB index timing spike; CASS-vs-FTS5 decision criterion (#466) | 3 |
| Q11 fork-by-default | native fork commands, sidecar parentage (F7); Codex fork verification (F11) | 3 |
| Q12 takeover handshake | loss-window bound and pre-handover push (F10g) | 3 |
| Q15/Q16 Paseo route | flag-mapping spike; cross-host parent via labels; profile key confirmation (F5, F12) | 4 |
| Q17 product framing | name, licence text, release pipeline, test matrix, public leak check (F9) | 7a (new) |
| Hermes export | runs on the Mac; `max_export_messages` paging (F2, F10e) | 3 |

## 4. Citation spot checks (of the 57)

| # | Claim | Result | Evidence |
|---|---|---|---|
| C1 | Claude Code CLI reference (`--resume`, `--fork-session`, `/cd`) | holds | https://code.claude.com/docs/en/cli-reference |
| C13 | git-annex `numcopies` semantics | holds | https://git-annex.branchable.com/git-annex-numcopies/ |
| C15 | `promptStringOnce` for first-run data | holds; the password-manager hook is a separate page | https://www.chezmoi.io/reference/templates/init-functions/promptStringOnce/ |
| C20b | Syncthing untrusted devices are beta | holds | https://docs.syncthing.net/users/untrusted.html |
| C23 | CASS remote sources / adapters | partly: remote and `local` sources hold; OpenCode "cannot read" is stale (v0.10.0, #504); Hermes is a connector | CASS README |
| C30 | Paseo Docker mounts `/home/paseo` | holds | Paseo README `docker run … -v "$PWD/paseo-home:/home/paseo"` |
| C33 | Paseo licence Apache-2.0 | holds | Paseo README "License Apache-2.0" |
| C36 | Syncthing versioning types | holds | https://docs.syncthing.net/users/versioning.html |
| C41 | mise runtime manager | holds | https://mise.jdx.dev |
| C42 | NixOS `receiveencrypted` folder type | holds | NixOS options `services.syncthing.settings.folders.*.type` |
| C45 | chezmoi `modify_` scripts | holds | https://www.chezmoi.io/reference/source-state-attributes/ |
| C46 | chezmoi `symlink_` attribute | holds | same |
| C47 | chezmoi `.chezmoiignore` templated | holds | https://www.chezmoi.io/reference/special-files/chezmoiignore/ |
| C48 | chezmoi `.chezmoiroot` | holds | https://www.chezmoi.io/reference/special-files/chezmoiroot/ |
| C49 | chezmoi externals merge with source | **wrong** — inconsistent-state error, not merge (F1) | twpayne/chezmoi#3131 |
| C50 | Codex `resume`/`fork`/`/import` | partly: `resume`, `/import` verified; `fork` not found (F11) | openai/codex CHANGELOG |
| C52 | Paseo 0.12.0 changelog features | unverified (fetch returned chrome); `paseo --version` = 0.12.0 locally | — |
| C56 | Tailscale SSH | holds | https://tailscale.com/kb/1193/tailscale-ssh |
| C57 | `git bundle` for carry-over | holds | https://git-scm.com/docs/git-bundle |
| C58 | Homebrew install methods | partly: proposal implies a non-curl path exists by default; it is the `.pkg` or an unsupported clone (F6) | https://docs.brew.sh/Installation |
| T1 | chezmoi keeps replaced originals | **wrong** (F4) | twpayne/chezmoi discussion #4657 |

Totals: 15 hold, 4 partly, 2 wrong, 1 unverified.

## 5. Questions only the operator can settle

5.1 Is a **trusted** Linux peer (holding the Syncthing folder key) acceptable, or must every Linux host stay blind? This decides F2: index on the Mac vs a new trusted host.
5.2 Companion overlay shape (F1): fixed clone + templates (recommended) or submodule with non-colliding paths?
5.3 Homebrew: accept the `.pkg` from GitHub releases as the one sanctioned curl-free path, or keep the curl-pipe for Homebrew only and document the exception?
5.4 Archive layout: may the archive be re-specified as native-per-device (F3), giving up the provider-neutral `<provider>/<device>/<project>/<session>/<generation>` tree?
5.5 CASS vs FTS5: is a 10 GB full-index timing spike on the Mac (via `bg`) acceptable in Phase 3, or should FTS5 be chosen now and CASS kept as optional?
5.6 Product name: `ade` is taken on PyPI — ship as `ade-kit` (binary `ade`), or keep `kool-ade` and no PyPI presence?
5.7 Is `--via paseo` allowed to silently fall back to plain acp-run when a flag is not expressible, or must it refuse (`BLOCKED:`) so the gap is visible?

DECIDED: none required; the review stayed read-only, no inbox messages arrived, no blocking questions.

