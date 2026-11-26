# Ref labels — referable post items and a script-issued Ref line

Operator directive (2026-11-17, via peer 74e4adbf): adopt the reply-label
convention from the operator's Grok Bot method. This page is the standing rule
for ADE-managed agents; it replaces the older A./B./A1 numbering convention
(`docs/queue.md` Carried 67 note, standing order 5's A./B./A1 form) for
operator-facing posts.

## Part A — item labels

1. **Sections.** A post with more than one section labels each with a bold
   uppercase Roman numeral: **I.**, **II.**, **III.** A single-section post has
   no Roman numerals.
2. **Major items.** Each starts with a bold-italic number at the left margin:
   `***1.*** text`. Numbering restarts inside each section.
3. **Sub-items.** Go in a Markdown quote block directly under their major item,
   each starting with a bold-italic lowercase letter: `> ***a.*** text`. Put a
   line containing only `>` between sub-items so long ones stay indented.
   - Skip `i` (reads like the Roman numeral one). Run a, b, c, d, e, f, g, h,
     j, k, ...; after `z` continue `aa`, `ab`, ...
4. **Third level.** Lowercase Roman numerals in a nested quote:
   `> > ***ii.*** text`.
5. **Never** use plain bullets or unlabeled lines for items the user may reply to.
6. **Citation.** A citation is the post's Ref, then section, item, letter and
   Roman numeral, e.g. `CHIEF-tt I.3b.ii`. In a reply to the latest post the Ref
   may be omitted (`I.3b`, `2a`). Question-card options keep plain numbering
   (`1.`, `2.`, ...) unless the source spec says otherwise.

## Part B — the `Ref:` line (script-issued)

**What a Ref is.** A unique, script-issued id for ONE operator-facing post. The
operator cites it (`CLAUDE-74 II.1`) to point at that exact post, and `ref lookup
74` says who issued it and when. It stores no content: it is not a summary, not a
commit hash, not a PR number and never text an agent types by hand. Format:
`<BOT>-<base36 global counter>`, short on purpose and growing slowly: one
character up to 35, two up to 1295, three characters from 1296 (`100`) on.

1. **Every** post to the operator ends with its own last line
   `Ref: <BOT>-<id>`, including one-line answers, questions, decisions and
   acknowledgements that end a turn. Exceptions: a tapback/emoji-only post; a
   short progress note under 200 chars with no question/decision when a later
   post in the same turn carries a Ref.
2. Get a fresh Ref per post by running `ref <BOT>` (one positional `<BOT>`
   argument only, e.g. `~/src/djbclark-ade/bin/ref ANTIGRAVITY`, or
   `ref-append <BOT> FILE`) and paste the output verbatim. Never pass a second
   argument, never append or substitute a Paseo UUID / agent ID after
   `Ref: <BOT>-`, and never invent, reuse or edit an id (`bin/ref` records
   your `PASEO_AGENT_ID` automatically as the agent hint in `issued.log`);
   re-posting an old message also needs a fresh Ref.
3. The id comes from one global counter shared by every bot, base 36 (0-9 a-z),
   never reset, file locked with `flock`. Every issued id is logged in
   `issued.log` (id, bot, time, agent hint); the bot prefix is normalized
   (uppercase, spaces/hyphens removed). `lookup` (any case) is reserved and cannot be a bot name.
4. `ref-append` adds the Ref line to a draft and refuses if it already ends with one.
5. **`ref lookup ID`** (`CLAUDE-74` or `74`) prints the bot, the issue time and
   the agent hint, read-only. Exit 1: never issued (or issued to a different bot
   than the one named); exit 2: not an id. That is all a Ref can tell you; the
   post's content lives in the transcript.
6. **The check is a hook, not a promise.** The Claude Code hook
   `claude/hooks/ref_integrity_gate.py` (registered in
   `agents/claude/settings.json.tmpl` under `Stop`, `SessionStart`, and
   `UserPromptSubmit`) reads the last non-blank line of the final post on `Stop`.
   When it starts with `Ref:` it must (a) read `Ref: <BOT>-<base36>`, (b) name
   an id in `issued.log`, (c) carry the bot prefix the log recorded and (d) not
   have ended an earlier post of the same transcript (grouped by `message.id` so
   multi-block streamed replies are judged as one post). Any failure — and any
   post of 200+ characters with no `Ref:` last line — blocks the stop once and
   auto-mints a fresh `Ref: <BOT>-<id>` (`ADE_REF_BOT` / `REF_BOT`, else
   `CLAUDE` for Claude Code) directly into the block reason via `bin/ref`
   (passing `--skip-id` when rejecting a syntactically valid Ref so this mint
   skips an immediate counter collision without registering the rejected id as
   issued; larger unreached ids remain eligible for later independent
   issuance), so the model can paste it verbatim without an extra Bash round
   (if `bin/ref` is unavailable, fails, or emits undecodable or unexpected
   output, the reason falls back to naming `ref CLAUDE` explicitly). A short
   progress note under 200 chars without a `Ref:` line is exempt (item 1). On
   `SessionStart` (which fires on `startup`, `resume`, `clear`, `compact`, and
   `fork`) and on `UserPromptSubmit` (once per compaction epoch, keyed by the
   latest main-thread `compact_boundary` identity and persisted atomically,
   preserving the known epoch on bounded tail scans or transient read
   failures), the hook injects a crisp one-line `additionalContext` reminder so
   auto-compaction cannot drop the rule. The hook never loops: it allows the
   stop when Claude Code reports `stop_hook_active`, blocks a given message
   once per session (recording its digest in `<session>.blocked` under a single
   permanent `.state.lock`), skips sub-agents (`agent_id`), makes no network
   call, fails open on an error (an `issued.log` that exists but cannot be read
   is allowed and logged; an absent one, or one without the id, is "never
   issued" and blocks) and is switched off with `REF_GATE_OFF=1`. Every
   in-scope top-level `Stop` decision (`allowed-empty`, `allowed-short`,
   `allowed-valid`, `allowed-unreadable-log`, `allowed-stop-hook-active`,
   `allowed-already-blocked`, `blocked-no-ref`, and `blocked`) writes a
   strictly categorical, content-free audit row (structured `ref_kind`,
   `post_len`, `stop_hook_active`, `session_id`, categorical `reason`/`problem`,
   and `minted_ref` only when a Ref was minted; no assistant-supplied reply or
   Ref text is ever persisted) to `~/.local/state/ade/ref-gate/decisions.log`
   (`0700` dir / `0600` files); sub-agents (`agent_id`), non-`Stop` events,
   unparseable stdin JSON, and `REF_GATE_OFF=1` are excluded. Other TUIs
   (Codex, Pi, Cursor, Hermes) have no such hook yet and rely on this page.
   Never end a post with any other `Ref:` line (a URL, `#861`): the hook blocks
   it as not of the form.
7. **If the hook blocks you**, its reason names the problem and already includes
   a freshly minted `Ref: <BOT>-<id>` line ready to paste. Send the post again
   with that exact line appended (on missing Ref) or replacing the bad last line
   (on invalid Ref), with no extra Bash call needed. Only if the reason says
   `bin/ref` was unavailable, run `ref CLAUDE` (or your named `<BOT>`) and paste
   its output verbatim. A retry that is still wrong is let through once, so
   never edit the minted id by hand.
8. **No `ref_audit.py`.** The older audit script named in earlier drafts was never
   in this repo and ran nowhere. It is dropped, not shipped: the hook checks
   every post when it is written, which is when a wrong Ref can still be
   replaced, and the only transcript loader it would need is the hook's own
   (Claude Code only). A retrospective audit over Codex, Pi and Hermes logs
   would need a loader per format that nothing consumes today; `ref lookup` and
   the decisions log cover the questions that come up. Write one when a second
   TUI gets enforcement.

## Paseo agent and tab references (operator rulings 2026-11-23, 2026-11-25, 2026-11-26)

Whenever referencing a Paseo agent or tab in replies or reports, **always** give
all four fields (see also [docs/agent-identity.md](agent-identity.md) and `bin/agent-id`):

1. **Tab-tooltip 7-char prefix + full agent ID** formatted as `<7-char> (<full-UUID>)`, e.g. `86df0a5 (86df0a5f-33ea-4365-999c-74ab63cc173a)` (matches the truncated 7-char ID shown in Paseo's tab tooltip while preserving the unambiguous full UUID; never a bare short ID alone)
2. **Workspace ID** (`wks_…`)
3. **Window name** (the Paseo workspace/window title, e.g. `WORKER djbclark-ade (post-hold)`)
4. **Tab name** (the agent tab title, e.g. `worker <slice> <lead-id> [wt: <worktree>]`)

**Human-interaction starts (operator ruling 2026-11-26, relayed via `bdd829df`):** whenever starting something that requires the human to interact — including existing/ordinary starts, not just handoffs — always include the exact Paseo designation `{<7-char-prefix> (<full-agent-UUID>) <project>/<window>/<tab>}` plus the workspace ID (`wks_…`) for the **actual** tab/window the human needs, and explicitly state **where the interaction occurs** (for example, phone overlay vs Paseo tab). Example:

`{d4ab1e4 (d4ab1e4f-4334-4056-b09e-b9480e3e1f70) plektra-djbclark/WORKER plektra-djbclark (workers)/worker HandQA Neon qualification}`, workspace `wks_b06299d82e6672e7` (interaction occurs in the phone overlay / Paseo tab).

## Install

- `bin/ref` (issues, with optional `--skip-id ID` to skip an excluded counter value during that issuance without recording it; `ref lookup ID` reads), `bin/ref-append` — the issuing scripts.
  `ade-update` reports a missing `~/.claude/hooks/` link with its `ln -sfn` fix (the template's
  `[ -f ] || exit 0` guard leaves an unlinked hook silently off); the `Stop`, `SessionStart`,
  and `UserPromptSubmit` entries of `agents/claude/settings.json.tmpl` wire
  `ref_integrity_gate.py` (run `ade-settings-apply` or add those hook blocks to
  `~/.claude/settings.json` for the compaction-proof reminder). Refs directory defaults to
  `~/.local/state/djbclark-ade/refs/` (`REFS_DIR` or `--dir` overrides; the flag
  wins). Agent hint comes from `REF_AGENT` / `PASEO_AGENT_ID` / `AGENT_ID` /
  `CURSOR_CONVERSATION_ID`.
- Test in a throwaway dir before going live: `REFS_DIR=$(mktemp -d) bin/ref TESTBOT`.

## Prefixes

Short uppercase prefix per bot; overrides where the normalized display name
differs. Proposed (operator to confirm; the many Paseo worker/peer agents derive
their prefix from the lead's prefix or a per-slice override):

| Bot | Prefix |
|---|---|
| ADE lead (b0b47ad8) | ADE |
| Antigravity TUI | ANTIGRAVITY |
| Pi TUI | PI |
| Codex TUI | CODEX |
| Claude TUI | CLAUDE |
| Hermes | HERMES |
| Grok Bot | GROK |

## Scope

This page covers ADE-managed agents. The operator's global instruction files
(`~/.claude/CLAUDE.md` item 8, `cursor/home-agents.mdc`) are edited only by
Claude Opus 5.5+, the newest Codex Astra (gpt-6-astra) or Gemini Neon (else Argon; operator
2026-11-22: "We can also change that rule gemini neon and argon are allowed with neon taking precidnce"); the 2026-11-17 migration to this
convention was applied by a Codex Astra agent, and `AGENTS.md` standing order 5
is migrated in PR #778 (merge after this PR).
