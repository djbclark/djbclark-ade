# Outside-repository migration proposals — NOT applied, NOT approved waivers

Snapshot: **2026-11-10**, bigmac (mirrored into the ADE repo from the Mac
evidence archive so a successor does not need the tarball). All C3 probes ran
against actual local paths. No outside source/configuration changed. Keep
historical handoffs and transcript/log readers.

1. **tendcf and nix2cf:** update active `AGENTS.md` shim/frontier teachings to
   current native ADE routing. Preserve frontier allowance, headroom and
   reservation checks; do not translate to unguarded bare Paseo. Prepare
   separate claimed-worktree PRs after confirming current upstream heads. Do
   not blanket waive active launch instructions.
2. **cfengine:** `cfengine-core` probe is clean, but `cfengine-all` contains
   `AGENTS.md` and dated handoff references to
   `cfenginewatch`/`fleet-watch`/`bin/watch`. Separate active
   registration/monitor commands from historical notes. Propose a reviewed
   active-instruction migration; preserve handoffs. A historical-only waiver
   can be considered only after that classification.
3. **paseo4herdr:** all observed matches are dated `docs/handoffs` artifacts.
   Proposed operator line (**NOT granted**):
   `2026-11-10: waive Wave 6 C3 paseo4herdr for immutable dated handoff references; do not rewrite those records or reinstall retired tools.`
4. **sudo_secretspec:** two observed matches are dated `docs/handoffs`
   artifacts. Proposed operator line (**NOT granted**):
   `2026-11-10: waive Wave 6 C3 sudo_secretspec for preserved dated handoff references; new runtime callers use native Paseo.`
5. **aiuse:** source still imports `collectors.acp_usage` and passively reads
   historical `acp-run` logs in `usage_sources`/`quota_refusals`. Preserve
   archived history/accounting. Propose updating live instructions/client
   suggestions and explicitly deciding whether to waive the retained passive
   log format. Never delete old logs or merge API/subscription pools to clear
   the regex.
6. **site_public_home_agents:** active `home-agents.md` lines 6,53,57,64 still
   teach `acp-dispatch`/`coding-bot`. Needs the normal Opus-only
   instruction-file upkeep, in the source repo's authorized workspace;
   preserve frontier rules and all active references. Not edited by the Mac
   probe.
7. **Additional outside dependency:**
   `~/ops/site-private-djbclark/bin/fleet-watch` still defines `UPSTREAM_RELAY`
   and invokes it via `runb 60 "$UPSTREAM_RELAY"`. One transient fleet-watch
   process carried `relay.py` in argv; it ended before the follow-up capture.
   Propose a reviewed migration to native Paseo sends with real receipt
   semantics. The absence of a process at a later instant does not remove the
   source dependency.
8. **Dispatch metadata:** native lead
   `0cc34651-d6e5-4d88-b4cd-8166038da11e` is still listed under
   `ade.via=acp-dispatch`. No shim OS processes or launchd jobs were found;
   check showed a terminal done record. Do not clear a live session's label or
   stop it from cloud. Confirm retirement of this inherited label/session
   after its work ends before asserting the B2 empty/drained gate.
9. **Early deletion:** 2026-11-10 precedes 2026-11-20. No `--allow-early` or
   deletion PR was attempted. Operator confirmation is still required after
   genuine C3 and Mac completion.

The table's escaped vertical bars under-match with ripgrep. Exact specified
probes and corrected intended-ERE probes are both retained in the archive;
in-repo teaching was corrected in #533.
