# bottom-config uncapped Command column (#227 demanual, 2026-11-10)

## Why this note

Open tip [#227](https://github.com/djbclark/djbclark-ade/pull/227)
(`bottom-config-uncapped-command`) documents two fork facts for
`skills/bottom-config`:

1. Pane-size guidance when previewing `btm-mt` from an agent shell.
2. The second fork change (`djbclark/bottom` `118088d4`): the process
   Command column has **no width cap**, so put `command` last in
   `[processes] columns`.

That tip's tree still re-adds `skills/bottom-config/` into
**djbclark-ade**. Slim-down E1 (2026-11-07, #297) **moved** that skill to
[site-djbclark](https://github.com/djbclark/site-djbclark)
(`skills/bottom-config/`). Re-adding it here would undo the move.
Master's roster correctly omits the skill; changelog fragments for
#221/#234 remain historical.

## Probe (2026-11-10)

| Check | Result |
|---|---|
| `skills/bottom-config/` on `origin/master` (djbclark-ade) | absent (deleted in #297) |
| Skill on `djbclark/site-djbclark` `master` | present (`SKILL.md` + `scripts/`) |
| site-djbclark `SKILL.md` has uncapped / pane-size paragraphs | **no** (still the pre-#227 text) |
| Fork commit | `118088d45b3b6d40de523b540b81b16ff0b2571a` — "process Command column has no width cap…" |

## Disposition

- **Close #227** after the superseding hygiene PR merges; do **not** rebase
  it onto master (it would restore a moved skill).
- **Land the doc delta in site-djbclark** (order 11: needs an explicit yes
  before editing that repo). Until then, the paragraphs below are the
  demanual of #227's meaningful tip.

## Proposed site-djbclark patch

Apply to `skills/bottom-config/SKILL.md` on site-djbclark `master`.

### A. After the process-widget keys sentence in Workflow step 4

Replace any herdr-based size tip (retired 2026-10-31) with:

```markdown
   "This size terminal"? An agent shell has no tty (`stty`/`tput` fail or say 80x24).
   Pass `--width` / `--height` to `preview.py` for the pane you care about (count
   characters on a visible line, not bytes). `preview.py` always expands the
   process widget (`-e`), so it cannot show the whole layout. For that, start
   `btm-mt -C FILE` in your own private `tmux -S` server.
```

### B. End of "Where the change lives"

Append:

```markdown

Second fork change (`make_column` and `toggle_command` in `src/widgets/process_table.rs`): the
Command column has no width cap (stock: 30% of the table, 50% after `P`). It takes whatever the
columns before it leave, so put `command` LAST in `[processes] columns`; fewer narrow columns
means a wider command. Stock `btm` still caps it and spreads the spare width evenly.
```

(Fork evidence: `djbclark/bottom@118088d4`, 2026-11-01.)
