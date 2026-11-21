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
2. Get a fresh Ref per post by running `ref <BOT>` (or
   `ref-append <BOT> FILE`) and paste the output verbatim. Never invent, reuse
   or edit an id; re-posting an old message also needs a fresh Ref.
3. The id comes from one global counter shared by every bot, base 36 (0-9 a-z),
   never reset, file locked with `flock`. Every issued id is logged in
   `issued.log` (id, bot, time, agent hint); the bot prefix is normalized
   (uppercase, spaces/hyphens removed). `lookup` is reserved and cannot be a bot name.
4. `ref-append` adds the Ref line to a draft and refuses if it already ends with one.
5. **`ref lookup ID`** (`CLAUDE-74` or `74`) prints the bot, the issue time and
   the agent hint, read-only. Exit 1: never issued (or issued to a different bot
   than the one named); exit 2: not an id. That is all a Ref can tell you; the
   post's content lives in the transcript.
6. **The check is a hook, not a promise.** The Claude Code Stop hook
   `claude/hooks/ref_integrity_gate.py` (registered in
   `agents/claude/settings.json.tmpl`) reads the last non-blank line of the final
   post. When it starts with `Ref:` it must (a) read `Ref: <BOT>-<base36>`,
   (b) name an id in `issued.log`, (c) carry the bot prefix the log recorded and
   (d) not have ended an earlier post of the same transcript. Any failure blocks
   the stop. A post with no Ref line gets only a non-blocking note, and none when
   it is a short progress note (item 1). The hook never loops: it allows the stop
   when Claude Code reports `stop_hook_active`, blocks a given message once per
   session, skips sub-agents, makes no network call, fails open on an error and is
   switched off with `REF_GATE_OFF=1`. Its decisions go to
   `~/.local/state/ade/ref-gate/decisions.log`. Other TUIs (Codex, Pi, Cursor,
   Hermes) have no such hook yet and rely on this page.
7. **If the hook blocks you**, its reason names the problem. Run `ref <BOT>`, then
   send the post again with its last line replaced by the exact line the script
   printed (do not edit it, and do not fix it by hand: that is the failure the
   hook exists to catch). A retry that is still wrong is let through once, so
   check it yourself with `ref lookup`.
8. **No `ref_audit.py`.** The older audit script named in earlier drafts was never
   in this repo and ran nowhere. It is dropped, not shipped: the hook checks
   every post when it is written, which is when a wrong Ref can still be
   replaced, and the only transcript loader it would need is the hook's own
   (Claude Code only). A retrospective audit over Codex, Pi and Hermes logs
   would need a loader per format that nothing consumes today; `ref lookup` and
   the decisions log cover the questions that come up. Write one when a second
   TUI gets enforcement.

## Install

- `bin/ref` (issues; `ref lookup ID` reads), `bin/ref-append` — the issuing scripts.
  The hook is linked into `~/.claude/hooks/` by `ade-update` and wired by the
  `Stop` entry of the settings template. Refs directory defaults to
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
