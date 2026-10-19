STATUS: done

# ADE everywhere v2.1: digest of the Fable 5.1 and Codex gpt-6-astra reviews, for v2.2 (2026-10-19)

Method: claims were checked against primary sources: upstream code and docs snapshots under `v21-review/evidence/` (chezmoi, CASS v0.10.0 plus franken-agent-detection 0.3.3, Paseo v0.12.0), live web fetches, local CLIs (`codex` 0.163.0, `claude`, `paseo` 0.12.0), `gh` and PyPI. Verdicts: **holds**, **partly**, **refuted**.

Fable caveat: its §4 citation IDs and §3 decision numbers do not match v2.1 (its "C49" and "C58" are other footnotes; chezmoi is Q4, CASS Q12). Read its substance, not its IDs; Codex's IDs match.

## A. Merged findings (most severe first)

**G1 (blocker). The companion "overlay" is not a chezmoi mechanism.** Fable F1, Codex F2.
- (a) Claim: §4.4 says "`.chezmoiexternal` pulls the companion's `home/` overlay so private files win where both define a path". §12 F16 cites an `overlay.toml` that is never defined.
- (b) Holds. chezmoi's `sourcestate.go` raises `InconsistentStateError` for any target that has more than one source entry; only directories coalesce. The maintainer says so in #3131. Externals name targets: archive members land as literal target names (no `dot_`/`modify_`/`.tmpl` interpretation), and `git-repo` externals are delegated to git. There is one source directory per config.
- (c) Accept with change.
- (d) In §4.4, Phase 1 and §12:
  1. `.chezmoiroot`=`home` is the single source state.
  2. `ade` clones the companion to a fixed path before apply.
  3. Public templates read companion data with `stat`-guarded `include`/`fromToml`.
  4. Private-only files go either into templates, or into a second chezmoi instance (`--source`/`--config`) restricted to disjoint targets, with `ade doctor` checking that the two `chezmoi managed` sets do not intersect.
  5. Delete "private wins". Write the precedence, keyed-merge and unknown-key contract that `overlay.toml` claims.
- (e) https://github.com/twpayne/chezmoi/issues/3131 , https://www.chezmoi.io/reference/special-files/chezmoiexternal-format/

**G2 (blocker for any mutating Phase 0 step). chezmoi keeps no originals.** Codex F1, Fable F4.
- (a) Claim: T1 says "chezmoi keeps the originals it replaced"; §4.4 says the same.
- (b) Holds. In #4657 the maintainer says apply on a new machine "should continue to overwrite dotfiles without any warning". `targetstateentry.go` writes new contents and keeps no journal.
- (c) Accept.
- (d) T1 and §4.4: before the first apply, `ade` takes an adoption snapshot of every target `chezmoi managed` lists: bytes, mode, symlink target and absence records, stored privately with a restore command. Phase 0 link fixes wait for it; classification and backups do not. Add a restore test to the Phase 1 gate.
- (e) https://github.com/twpayne/chezmoi/discussions/4657

**G3 (blocker for Phase 2/3 routing). The blind peer is given plaintext work.** Fable F2, Codex F9.
- (a) Claim: §8 Phase 3, §11.2 ("the index runs on the Linux peer") and §11.3 send index builds, the initial Syncthing scan and the Hermes export to "the Linux peer". Q2 and principle 6 make vps-primary receive-encrypted.
- (b) Holds. An untrusted device holds encrypted names and contents, so CASS cannot read it. Hermes and its `state.db` live on the Mac.
- (c) Accept.
- (d) In §11.3, split the work into three kinds: source-local capture and export (always on the origin), ciphertext storage and scan (vps-primary), and plaintext indexing (the Mac off-hours via `bg`, unless the operator names a trusted Linux worker; see D1). Fix §8 Phase 3 and §11.2 to match.
- (e) https://docs.syncthing.net/users/untrusted.html

**G4 (major). CASS needs a native-shaped, latest-only view, and a pinned build.** Fable F3, Codex F7 and F8.
- (a) Claim: §6.3.4 says CASS is "pointed at the archive … with a per-provider path map"; its OpenCode adapter "looks for `.opencode/`".
- (b) Holds:
  1. `path_mappings` rewrite workspace paths only.
  2. The Claude connector's `external_id` comes from the file's relative path, so every `<generation>.jsonl` indexes as a new conversation.
  3. The OpenCode connector reads `~/.local/share/opencode/opencode.db` and `OPENCODE_SQLITE_DB` (2.x tables fixed in v0.10.0, #504). Hermes reads `state.db` (`HERMES_SQLITE_DB`). So v2.1's adapter sentence is wrong.
  4. In #520, structural connectors (cursor, gemini and others) index nothing from wrapped layouts, and the Claude connector misattributed other providers' files. #522: raw-mirror growth. Both are fixed on main only; v0.10.0 is still the latest release.
  5. Refuted: Fable's "#466 open". It closed on 2026-10-03, fixed in v0.9.0.
- (c) Accept with change.
- (d) In §6.3.1/6.3.4 and Phase 2:
  1. A materialised view `<device>/<native layout>` with one current file per session, plus `.backup` SQLite copies fed through the env overrides.
  2. Generations stay outside CASS's roots.
  3. Pin a main commit or the next release.
  4. Measure a full rebuild (wall time, RSS, bytes).
  5. Search with `--no-maintenance` / `CASS_AUTO_REFRESH=0` during working hours.
- (e) https://github.com/Dicklesworthstone/coding_agent_session_search/issues/520 , https://github.com/Dicklesworthstone/coding_agent_session_search/issues/522

**G5 (major). The takeover handshake does not give exclusive ownership.** Codex F5; Fable F10g in part.
- (a) Claim: §6.3.6 "stopped at generation N".
- (b) Holds as protocol analysis; it was not run. Two recipients can both get "stopped". A former origin can still answer after a handover. acp-dispatch's auto-resume (README:68) can restart a session that was handed off.
- (c) Accept.
- (d) §6.3.6: a serialised transfer record holding owner, epoch, recipient, transfer id and final generation. Freeze the origin's reap and auto-resume for that id, then acknowledge one recipient. Limit the guarantee to ADE-managed launches (D3). An unreachable origin still means fork (Q14).
- (e) https://docs.syncthing.net/users/syncing.html

**G6 (major). "Completion marker written last" means nothing to a receiving device.** Codex F6.
- (a) Claim: §6.3 identity paragraph.
- (b) Holds. Syncthing's `order` defaults to `random`, and other orders sort only within a batch, so a marker can arrive before its transcript or sidecars.
- (c) Accept.
- (d) In §6.3 and the Phase 2 gate:
  1. A per-generation manifest listing every object with hash, size, format version and parent.
  2. Receivers validate the whole manifest before the generation becomes pullable or indexable.
  3. Tests for marker-first arrival, a missing sidecar, truncation, and compaction during capture.
- (e) https://docs.syncthing.net/users/config.html

**G7 (major). Fork with the native fork commands, not a custom first record.** Fable F7, Codex (Q6 row).
- (a) Claim: §6.3.5 "a new id whose first record names the parent id and device".
- (b) Holds. `claude --resume … --fork-session` and `codex fork` both exist (checked on installed codex-cli 0.163.0). Refuted: Fable F11 / C50 "fork not found".
- (c) Accept.
- (d) §6.3.5: `ade sessions pull` stages the generation, then calls the provider's own fork. Parentage goes in the archive sidecar; never write into native transcripts.
- (e) https://code.claude.com/docs/en/cli-reference

**G8 (major). The Paseo route has different contracts from acp-run.** Codex F12, Fable F5 and F12.
- (a) Claim: §7.2 dispatch row, `--via paseo`.
- (b) Mostly holds:
  1. `paseo run` has no `--profile`.
  2. `--output-schema` is rejected together with `--no-wait`.
  3. `PASEO_AGENT_ID` resolves only on the target daemon.
  4. Closing the SDK client does not stop agents.
  5. The local `daemon` config has no `agentProfiles` key.
  6. Partly refuted: Fable's "no effort equivalent". `run` has `--model`, `--thinking` and `--mode`. Context size, `--perm deny`/read-only, deadlines and inbox have no equivalent.
- (c) Accept with change.
- (d) In §7.2, add a column: "Paseo flag / plugin / acp-run only". Resolve profiles to explicit flags. Reject any flag that cannot be expressed before launch (no silent fallback). Keep host-qualified parent edges in ADE (`--label`). Write a reconciliation state machine before Phase 4.
- (e) https://github.com/getpaseo/paseo/blob/v0.12.0/public-docs/cli.md

**G9 (major). The DAG belongs to Orca, not acp-dispatch.** Codex F15.
- (a) Claim: §7.2 "DAG, claims and resume stay in `acp-dispatch`"; drop `fleet.py`'s herdr adapter after the pilot.
- (b) Holds. README:206 gives Run/Task/`--deps` to Orca; acp-dispatch only launches slices, resumes after a quota stop, and reaps. Herdr stays as the fallback, so its adapter must stay too.
- (c) Accept.
- (d) In §7.2 and Q5's consequences, name an owner for every capability. DAG persistence either migrates, with a restart/replay proof in Phase 4, or Orca's orchestration stays. Keep the herdr fleet adapter.
- (e) /Users/djbclark/src/djbclark-ade/README.md:206

**G10 (major). Bootstrap stage zero and the root of trust.** Codex F3, Fable F6.
- (a) Claim: §4.4 "only prerequisites are git and a shell", "never curl-pipes an installer", signed tags.
- (b) Holds:
  1. Ordering cycle: `chezmoi init --apply` runs before chezmoi, the companion or credentials exist.
  2. A signed tag from an unknown key proves nothing.
  3. Homebrew's documented one-liner is a curl-pipe; the `.pkg` is Apple-Silicon-only.
  4. chezmoi release checksums are cosign-signed.
- (c) Accept with change.
- (d) In §4.4 and Phase 1, a stage-zero contract:
  1. Platform prerequisites.
  2. A key fingerprint given out of band.
  3. A verified chezmoi binary (cosign).
  4. Homebrew `.pkg` on Apple Silicon; distro packages on Linux.
  5. Companion and credentials only after the public-only/`none` apply passes.
- (e) https://docs.brew.sh/Installation , https://www.chezmoi.io/install/

**G11 (major). Product contracts Phase 1 needs are scheduled in Phase 7.** Codex F16, Fable F9.
- (a) Claim: §8 Phase 7 holds schemas and the release process; Phase 1 already consumes manifests and signed tags.
- (b) Holds. PyPI `ade` is taken (Suominen, Apache-2.0, checked). The repo is MIT. The CASS rider does not pass to third parties.
- (c) Accept with change.
- (d) In §8:
  1. Phase 1 gets schema versions and namespaces, precedence and deletion rules, the signing mechanics and a minimum platform matrix.
  2. `doctor` reports pass, unsupported, disabled or untested.
  3. Phase 7 keeps the docs, walkthrough and polish, plus a dependency-notice and licence page that names the CASS rider.
  4. Choose a distribution name such as `ade-kit`.
- (e) https://pypi.org/project/ade/

**G12 (major). The loss window leaves out collected-but-unreplicated data.** Codex F10.
- (a) Claim: T4 and §6.5.4 "collected since its last sync".
- (b) Holds as a counterexample. A generation collected while offline is lost along with the uncollected tail.
- (c) Accept; this is wording within Q15.
- (d) T4 and §6.5.4: the recovery point is "the latest complete generation verified on a surviving device". `doctor` shows last-captured and last-replicated separately. Add a lost-origin drill to Phase 3.
- (e) https://docs.syncthing.net/users/syncing.html

**G13 (major). The cold-tier crypto, the copy floor and versioning are underspecified.** Codex F11, Fable F10a.
- (a) Claim: §6.5.1 `numcopies 2`; §6.3.3 versioning.
- (b) Holds:
  1. `mincopies` is the hard floor; `numcopies` can be breached by concurrent drops.
  2. `encryption=shared` stores the cipher unencrypted in git, so it is unsafe if the peer has the repo.
  3. Syncthing versions only changes received from other devices, and defaults to off. v2.1's cross-device recovery claim survives, but local edits are never versioned on the originating device.
- (c) Accept.
- (d) §6.5: a hybrid or pubkey special remote with the key off the peer; `numcopies 2` plus `mincopies`; a named versioning type and retention for each device.
- (e) https://git-annex.branchable.com/git-annex-mincopies/ , https://git-annex.branchable.com/encryption/

**G14 (major). `modify_` is read/modify/write, and HOME ownership contradicts itself.** Codex F4.
- (a) Claim: §4.4 calls owned-key merging "the only safe contract" and says "Ansible never touches `$HOME`", yet `ade install` calls Ansible roles that write HOME.
- (b) Holds. `modify_` templates (`.chezmoi.stdin` with `setValueAtPath`) offer no lock against Paseo's or Claude's writers.
- (c) Accept with change.
- (d) §4.4: an ownership table per path and per key. Merges must be idempotent and keep unowned keys. Quiesce the writer, or use the app's own API. Split package-only Ansible tasks from config writers.
- (e) https://www.chezmoi.io/user-guide/manage-different-types-of-file/

**G15 (major). The work bundle does not carry dirty workspaces faithfully.** Codex F13.
- (a) Claim: §6.3.7 "git bundle … and a patch of its dirty tree".
- (b) Holds. A bundle carries objects and refs only. It drops untracked files, the staged/unstaged split, binaries, submodules and LFS. On-request capture cannot help when the origin is lost.
- (c) Accept.
- (d) §6.3.7: a work manifest (base commit, refs, binary index and worktree diffs, an untracked-file policy that excludes secrets); restore into a fresh worktree. Phase 2 tests an untracked file, a binary edit and a staged/unstaged split. Scope is D4.
- (e) https://git-scm.com/docs/git-bundle

**G16 (major). The store table still misses canonical state.** Codex F14, Fable F10e/f.
- (a) Claim: §6.1 rows for Hermes, zcode/Crush/omp and Paseo.
- (b) Holds:
  1. Hermes refuses a JSONL backup of any session with more than `max_export_messages` stored rows (default 20,000, archived rows counted). The dashboard export streams instead.
  2. OMP stores JSONL under `~/.omp/agent/sessions`.
  3. Paseo holds titles, parent links and labels, so it is mixed state.
  4. `~/.codex/sessions` is a symlink into `site-private`.
- (c) Accept.
- (d) §6.1 and Phase 0: inventory each installed store (plus Cline, Qwen, Muse, Grok, Antigravity); Hermes falls back to the `.backup` copy; the collector follows the symlink.
- (e) https://hermes-agent.nousresearch.com/docs/user-guide/sessions/#oversized-transcript-guards

**G17 (minor). Stale text and overstatements.** Fable F8 and F12, Codex F17.
- (b) All hold:
  1. `ade link` remains at §4.3, §7.2 and §7.3.
  2. §11.2's phase labels do not match §8.
  3. §12 still calls chezmoi a "fallback".
  4. T7 says nothing runs on the Mac, but there is a Mac apply gate.
  5. §6.2 says an "offline laptop is unsearchable"; its mirrored history stays searchable.
  6. §4.4 says the `agentProfiles` "schema changed"; the changelog says the published schema wrongly rejected it.
  7. §7.1 cross-host MCP: the MCP tools are host-local; only the CLI crosses hosts.
  8. C4/57920 is closed as not planned on 2.1.138, so it is a precondition, not a vendor rule.
- (c) Accept.
- (d) One `rg` pass over the text.

## B. Where the reviewers press on §9 decisions

Both reviewers state they treat all seventeen decisions as constraints, and neither overturns one.

| # | Decision | Reviewer argument | Re-raise? |
|---|---|---|---|
| B1 | Q2 vps-primary, blind | Plaintext work needs a trusted host (G3) | **Yes**: the operator must choose between Mac-only indexing and a new trusted Linux worker. |
| B2 | Q14 fork default, live takeover | Same-ID takeover is safe only for ADE-managed launches (G5) | **Yes**: it narrows what "takeover" promises. |
| B3 | Q15 loss window | Unclear whether dirty or unpushed work is covered (G15) | **Yes**: the answer decides whether periodic work capture is needed. |
| B4 | Q12 adopt CASS | Fable asks whether to choose FTS5 now. The fixes needed (#520, #522) are main-only. | **No**: keep CASS and pin a main commit. The measurement in G4 decides; no new choice is needed. |
| B5 | Q10 full product, Phase 7 | Contracts move earlier (G11) | **No** for the decision; yes for the support boundary (D7). |
| B6 | Q4 chezmoi | Codex: two instances or a composed tree | **No**: this repairs the mechanism, not the choice. |
| B7 | Q7 cold tier vps-primary plus one Mac | Needs an encrypted special remote (G13) | **No**: it is consistent with the decision. |
| B8 | Q9 keep acp-run | Fable asks whether `--via paseo` may fall back silently | **No**: the lead can rule "refuse"; Codex already says reject before launch. |

## C. Citation spot checks (every item marked partly or wrong)

| Reviewer item | Corrected claim | My check |
|---|---|---|
| Codex C4 partly | 57920: missing cwd on 2.1.138, closed not-planned 2026-06-09 | Confirmed (`gh`). https://github.com/anthropics/claude-code/issues/57920 |
| Codex C15 partly | The setup page supports `promptStringOnce`, not overlay precedence or kept originals | Confirmed. https://www.chezmoi.io/user-guide/setup/ |
| Codex C52 partly / Fable C52 unverified | 0.12.0 fixed a published schema that rejected valid `agentProfiles`/`plugins`; the data shape did not change | Confirmed (changelog line 152). https://github.com/getpaseo/paseo/blob/v0.12.0/CHANGELOG.md |
| Codex C41 partly | Export is refused above `max_export_messages` (20,000) | Confirmed. https://hermes-agent.nousresearch.com/docs/user-guide/sessions/ |
| Codex C57 partly | A strict floor needs `mincopies` | Confirmed. https://git-annex.branchable.com/git-annex-mincopies/ |
| Codex C23 partly; Fable "C23" partly | Offline mirrored history stays searchable; OpenCode `opencode.db` and Hermes `state.db` are native connectors | Confirmed (connector source, #504). https://github.com/Dicklesworthstone/coding_agent_session_search |
| Codex C23-OpenCode wrong | The connector probes `~/.local/share/opencode/opencode.db` | Confirmed. https://docs.rs/crate/franken-agent-detection/0.3.3/source/src/connectors/opencode.rs |
| Codex C43 partly | SessionEnd has a 1.5 s budget, raisable to 60 s (`CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS`) | Budget confirmed. Unverified: "skipped on kill" is not on the page; keep enqueue-only. https://code.claude.com/docs/en/hooks |
| Codex C46 partly | A bundle carries refs and objects, not the worktree | Confirmed. https://git-scm.com/docs/git-bundle |
| Codex C28 partly | Cross-host works via the CLI; injected MCP tools act on their own host | Confirmed (orchestration doc lines 22, 33). https://github.com/getpaseo/paseo/blob/v0.12.0/public-docs/orchestration.md |
| Codex C30 partly | The image does not bundle agent CLIs | Confirmed (docker doc line 42). https://github.com/getpaseo/paseo/blob/v0.12.0/public-docs/docker.md |
| Codex C60 partly | No profile export command, but the SDK can read host config | Plausible; not independently checked. https://paseo.sh/docs/agent-profiles.md |
| Fable "C49" wrong (externals merge) | No citation backs the §4.4 overlay sentence; chezmoi errors on duplicate targets | Substance confirmed; the ID is mislabelled. https://github.com/twpayne/chezmoi/issues/3131 |
| Fable "T1" wrong | chezmoi overwrites and keeps no originals | Confirmed. https://github.com/twpayne/chezmoi/discussions/4657 |
| Fable C50 partly ("fork not found") | `codex fork` exists | **Refuted**: codex-cli 0.163.0 lists `fork`. v2.1's C50 holds. |
| Fable "C58" partly (Homebrew) | The default install is a curl-pipe; the `.pkg` is Apple-Silicon-only | Substance confirmed; ID mislabelled (v2.1's C58 is loginctl and holds). https://docs.brew.sh/Installation |
| Fable #466 "open" (in F3) | Closed 2026-10-03, fixed in v0.9.0/v0.10.0 | **Refuted**. https://github.com/Dicklesworthstone/coding_agent_session_search/issues/466 |
| Fable "256 KiB chunks" (F3) | The 256 KiB transcript chunking is on main only (#522); v0.10.0 captures transcripts under 8 MiB whole | Partly; released behaviour differs. |

## D. Operator questions (deduplicated)

- D1. May one Linux host be trusted with decrypted transcripts for indexing, or does all plaintext indexing stay on the Macs off-hours?
- D2. Is the companion delivered through template `include` plus an optional second chezmoi instance on disjoint paths, accepting that "private overrides any public file" is dropped?
- D3. Is same-ID takeover guaranteed only for ADE-managed launches, with direct provider launches always forking?
- D4. Does the last-collection loss window cover dirty and unpushed work on a lost machine (periodic work capture), or is `--with-work` a convenience that needs a live origin?
- D5. For a fresh Mac, accept the Apple-Silicon Homebrew `.pkg` as the one sanctioned installer, or allow the curl-pipe as a documented exception?
- D6. May CASS run from a pinned main commit (for the #520/#522 fixes) over a native-per-device view that gives up the provider-neutral generation tree for indexing?
- D7. Which OS and architecture combinations does the first public release promise, who holds the release-signing key, and what is the distribution name now that PyPI `ade` is taken?
- D8. What storage and transfer budget bounds the immutable generations kept for one year of hot history?

DECIDED: none; this digest is read-only and changes no decision. No inbox messages arrived.

