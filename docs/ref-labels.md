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

1. **Every** post to the operator ends with its own last line
   `Ref: <BOT>-<id>`, including one-line answers, questions, decisions and
   acknowledgements that end a turn. Exceptions: a tapback/emoji-only post; a
   short progress note under 200 chars with no question/decision when a later
   post in the same turn carries a Ref.
2. Get a fresh Ref per post by running `ref <BOT>` (or
   `ref-append <BOT> FILE`) and paste the output verbatim. Never invent, reuse
   or edit an id; re-posting an old message also needs a fresh Ref.
3. The id comes from one global counter shared by every bot, base 36 (0-9 a-z),
   never reset, file locked with `flock`. Every issued id is logged in
   `issued.log`; the bot prefix is normalized (uppercase, spaces/hyphens removed).
4. `ref-append` adds the Ref line to a draft and refuses if it already ends with one.
5. `ref_audit.py` (deterministic, read-only) flags missing/wrong-prefix/duplicate
   Refs. **Not yet wired to a transcript store on this Mac** (Paseo transcripts
   are JSONL/daemon logs, not the reference's single SQLite message index), so the
   audit is installed-but-skipped until a loader is written; see `docs/queue.md`.

## Install

- `bin/ref`, `bin/ref-append` — the issuing scripts. Refs directory defaults to
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
| Pi TUI | PI |
| Codex TUI | CODEX |
| Claude TUI | CLAUDE |
| Hermes | HERMES |
| Grok Bot | GROK |

## Scope

This page covers ADE-managed agents. The operator's global instruction files
(`~/.claude/CLAUDE.md` item 8, `cursor/home-agents.mdc`) are edited only by
Claude Opus 5.5+ or Codex Astra (gpt-6-astra); the 2026-11-17 migration to this
convention was applied by a Codex Astra agent, and `AGENTS.md` standing order 5
is migrated in PR #778 (merge after this PR).
