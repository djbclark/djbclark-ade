# skill-everywhere — one skill, every local TUI

README for [`skill-everywhere`](../bin/skill-everywhere) (canonical script in
this repository; compatibility command `~/ops/site-private/bin/skill-everywhere`). It makes a local skill available to
every agent TUI on this machine (Claude Code, Codex, omp, Cursor, opencode,
Grok and Hermes; goose, Pi, Copilot, zcode, Qwen, Devin, Cline, Muse and Antigravity were dropped 2026-11-06) by
symlinking it into each one's skills dir (Grok Bot, on its own Linux box, gets
a rendered copy instead; see its row in section 2), and this page says how to prove each
TUI actually loads it. Until 2026-10-08 this was the `skill-everywhere` skill;
it was demoted to a README because it is needed only when adding a skill, and
its description cost listing budget in every session of every TUI.

The skill lives once, in git, and every TUI gets a **direct symlink** to it —
no hub, no chained symlinks (the old TUI → `site-private/skills` →
`site-djbclark/skills` → djbclark-ade chain was collapsed 2026-10-14; ops-repo
churn can no longer break skill loading):

- public skills: `~/src/djbclark-ade/skills/<name>/` — link target
  `~/src/djbclark-ade/skills/<name>`
- private skills: `~/ops/site-private/skills/<name>/` (real directory; only
  `1password` today) — link target `~/ops/site-private/skills/<name>`
- site skills (since 2026-11-06, the skills moved out of this repo by the
  slim-down): `~/ops/site-public-djbclark/skills/<name>/`, the Mac's checkout of
  the site-djbclark repo (default `${OPS_ROOT:-~/ops}/site-public-djbclark/skills`,
  `SKILL_EVERYWHERE_SITE` overrides it) — link target
  `~/ops/site-public-djbclark/skills/<name>`. A name in more than one root resolves
  public, then private, then site.

Editing the git copy updates every agent. Never copy: a
copy drifts silently. `~/.agents/skills/handoff` is a symlink to the git
copy. The stale copy is `~/.agents/skills/.trash/`. Grok walks that tree
and can advertise the trash skill under the live name. Hide it with
`[skills] ignore` in `~/.grok/config.toml`, and link Grok's own
`~/.grok/skills` at the git copy too.

## 1. Link it

After a new skill is linked, run `/reload-skills` in running Claude sessions (per-skill symlinks are the documented mechanism; a directory-level symlink is not, so none is used).

```sh
~/src/djbclark-ade/bin/skill-everywhere --all                # sync all shared skills
~/src/djbclark-ade/bin/skill-everywhere --check --all        # exit 1 for installed-target gaps
~/src/djbclark-ade/bin/skill-everywhere --dry-run --all      # preview all repairs
~/src/djbclark-ade/bin/skill-everywhere <name>...          # link, idempotent
~/src/djbclark-ade/bin/skill-everywhere --check <name>...  # status only
~/src/djbclark-ade/bin/skill-everywhere --remove <name>... # undo
```

`--all` (2026-10-25) discovers readable `*/SKILL.md` files directly under the
three shared roots (the site root added 2026-11-06), including linked directories. It deduplicates names with public
precedence and excludes hidden/helper directories. It cannot be combined with
names or `--remove`. The all-mode check returns 1 for missing, chained, stale or
conflicting installed targets; explicit-name check output/semantics remain
compatible with `ade-update`. Preserve foreign files/links and report conflicts.
`--check --all` prints one `warning: skill root <dir> does not exist` line per
absent root (2026-11-06; it does not change the exit code): an absent root's
skills are otherwise missing from the report without a word.

If the skill has no directory yet, create it first: public skills in
`~/src/djbclark-ade/skills/<name>/`, private ones (operator ruling required)
in `~/ops/site-private/skills/<name>/` plus a line in `.githooks/private-paths`
there. The script skips TUIs that aren't installed. If a path
already exists and isn't our link, the script leaves it alone and exits non-zero.
Report that rather than overwriting it. In link mode the script also
**collapses chains**: any existing link whose realpath equals the target but
whose readlink differs is replaced with the direct link.

**Retiring a skill:** run `--remove <name>` and re-point anything that loads
it by name (Hermes `skill-slash` handlers, Claude command wrappers)
before deleting its directory. `--remove` also works
after the directory is gone: it removes only links whose target is exactly
`<root>/<name>` for one of the three roots.

## 2. Where each TUI looks (verified 2026-10-03)

| TUI (binary) | How it gets the skill |
|---|---|
| Claude Code (`claude`) | `~/.claude/skills` |
| Codex (`codex`) | `~/.agents/skills` |
| opencode (`opencode`) | `~/.config/opencode/skills` |
| Hermes (`hermes`) | `~/.local/share/skill-everywhere/skills`, which Hermes put in its own `skills.external_dirs` |
| Cursor (`cursor-agent`) | already read `~/.claude/skills`; no extra link |
| Grok (`grok`, including Grok Build) | `~/.grok/skills`. It also scans `~/.claude/skills` and `~/.agents/skills` and dedups by name. Verified 2026-10-04: a same-named `SKILL.md` under `~/.agents/skills/.trash` was the copy this session was offered, so `~/.grok/config.toml` ignores that trash dir and this script links the live skill here. |
| omp / oh-my-pi (`omp`) | `~/.omp/agent/skills` (native, highest skill priority; added 2026-10-13). omp also reads `~/.agents/skills`, but de-duplicates by `realpath`, so the second link does not list a skill twice. omp ignores `~/.claude/skills` unless `claude` is in its `enabledProviders`. Prove it with `omp -p --no-title "<step 3 prompt>"` from a scratch dir. |
| Grok Bot (`grokbot`, no binary; present when `~/agent-data/workflows` exists) | **Copy, not link** (added 2026-10-23): Grok Bot runs on its own Linux box (`HOME=/home/box`) and reads `~/agent-data/workflows/<slug>/SKILL.md` as plain files, so no link into a Mac checkout could resolve. The script renders `ade-<name>/`: symlinks dereferenced (only a link to a regular file inside the skill; a skill holding any other link, one that leaves the skill, dangles or names a directory or special file, is refused: `--check` reports `unsafe source symlink`; link mode copies nothing, leaves any existing copy alone and exits 1; 2026-10-23),  a "managed copy" banner after the front matter (Mac-only paths, Grok Bot's approval rules win; its link and the marker's `source=` name the root the skill came from, djbclark-ade, site-djbclark or site-private, since 2026-11-06), and a `.skill-everywhere` marker. Only a dir with that marker is updated or removed; `--check` reports `copied`, `stale copy`, `missing` or `not ours`. `SKILL_EVERYWHERE_NO_COPY=1` skips this target (`ade-update` sets it for a non-canonical `--repo`, which is report-only and may be an untrusted PR branch), so a report-only run prints no `grokbot` row and renders nothing. On the box run it with `SKILL_EVERYWHERE_ONLY=grokbot`, or the box's own claude, agy, cline and hermes get links too. The box's nightly driver is `/home/box/agent-data/shared/skills-sync/sync.sh` (fetches `origin/master`, picks which skills suit Grok Bot, keeps a manifest, runs this script). |
| `/btww` (side question, 2026-11-01) | Skill `btww` **names the TUI's native side-question command, or says it has none; it never answers the question** (a skill is an ordinary turn, so it cannot be non-interrupting or off-transcript). Native: Claude `/btw`, Codex `/side`, agy `/btw`, Cursor `/btw`, Grok `/btw`, omp `/btw`, Hermes `/btw`, Copilot `/btw` (alias `/ask`), opencode `/btw`, Qwen `/btw`, Muse `/side` (alias `/btw`); none in zcode, Cline, goose or Grok Bot; Devin not installed. All first-party: the third-party `copilot-btw` and `opencode-btw` plugins are not needed. Real aliases: omp `omp/commands/btww.md` (`side: true`, linked to `~/.omp/agent/commands/btww.md`), Hermes CLI `quick_commands.btww` alias to `btw` (`~/.hermes/config.yaml`, template `agents/hermes/config.yaml.tmpl`). zcode: `zcode/commands/btww.md`. Claude cannot alias a built-in. Details: `skills/btww/SKILL.md`. |

`aiuse --json` providers with no TUI of their own (alibaba, deepseek,
openrouter, litellm, opencode-zen, clinepass, grok; antigravity, copilot, zai and devin since 2026-11-06) are API pools behind the
TUIs above, so they need nothing.

**Hermes owns `~/.hermes/`; never edit it yourself.** If the script warns that
the external dir has gone, ask Hermes to re-add it:
`hermes chat -Q -q "<request>" </dev/null`, and have it read the config back.

## 3. Prove it loaded

Configured is not the same as working. After linking a skill, or after changing
the table, ask each TUI from an empty scratch dir with stdin closed:

> Do not use any tools or read any files. If a skill named exactly '<name>' is
> available to you, reply with the first eight words of its description,
> verbatim; otherwise reply NOSKILL.

Use the recipes in `memory/feedback_headless_tui_invocation.md`. On 2026-10-03,
`cursor-agent` needed `--trust` in a scratch dir. Offline check:
`hermes skills list`. A NOSKILL from a model can be
wrong. When in doubt, ask it to list every skill name it has: that is how Cursor
turned out to be fine.

Codex was verified the same day: `codex exec -s read-only` quoted the
`steps` description verbatim from `~/.agents/skills`.

A check can fail for reasons that have nothing to do with where the skill was
put: a usage limit, an expired login, or no provider configured. Report those
TUIs as unverified, not as broken, and re-check once the account works.

Hermes Telegram `/name` is a **slash command**, not a skill lookup. Linking
via this tool puts the skill in `skills.external_dirs`. A skill whose name
does not collide with a core command (including `/steps`) is native skill
slash: the gateway injects `SKILL.md` and the agent runs. Do not also
register that name in `~/.hermes/plugins/skill-slash`. A plugin handler
return is a user reply, so it dumps the skill markdown and the agent never
calls `clarify`. Do not register `/helm` or `/baton` there either: native
skill slash already owns them. The plugin still registers `/helm-all` and
`/skill <name>` (those names are not native skill commands; `/session-finder`
and `/session-finder-all` went with the skill, 2026-11-06, docs/slim E3). Enable `skill-slash`
in `plugins.enabled`. Since 2026-10-06 `skill-everywhere` auto-nudges the
running gateway (`reload-plugins` control socket) so a plugin command like
`/helm-all` dispatches immediately —
no manual gateway restart. The Telegram pull-up `/` menu is only republished
at adapter (re)connect, so a just-added command may not autocomplete until the
next restart, but typing it still works and `/commands` lists it. If you cannot
run `skill-everywhere` (e.g. changing the plugin without a skill), ask Hermes
to run `reload-plugins` the same way. Claude Code slash wrappers live in
`~/src/djbclark-ade/claude/commands/` and are symlinked directly into
`~/.claude/commands/`.

## 3a. Paseo's skill sync and Paseo's own skills (2026-10-23, rewritten 2026-11-06)

**The six vendored copies (`ade-paseo`, `ade-paseo-advisor`, `ade-paseo-committee`, `ade-paseo-handoff`,
`ade-paseo-help`, `ade-paseo-plugin`) were deleted 2026-11-06** (slim-down R2-2, Wave 3b); Paseo's own shipped skills
replace them: `paseo`, `paseo-advisor`, `paseo-committee`, `paseo-handoff`, `paseo-help`, `paseo-plugin`. Paseo owns
those names: every name in its bundle is compared in `~/.agents/skills/<name>` and `~/.claude/skills/<name>` with its
bundled copy, and the daemon's startup sync and any skills install, update or save rewrite a difference. That is
harmless now that no entry of those names is a link into this repo (it was not before 2026-11-02: the unprefixed
links were overwritten, getpaseo/paseo#7700, and the repo copies were renamed `ade-*` for that reason).

1. **Operator step (final-merge batch)**: install Paseo's bundle with `npx skills add getpaseo/paseo`, or switch each
   Paseo home's `agents.skills.selection` in `~/.paseo/config.json` from `{"mode":"custom","skills":[]}` to the bundle
   (`{"mode":"all"}` is the default; the persisted path is `agents.skills.selection`, a top-level `"skills"` key is
   rejected by `paseo reload`). Remove any leftover `~/.agents/skills/ade-paseo*` and `~/.claude/skills/ade-paseo*`
   links that now dangle.
2. Their broad triggers ("handoff", "second opinion", "stuck") compete with this repo's `handoff` skill until D3
   (native-resume trial) and E6 (`dialogue`) land; if they steal requests, narrow the selection to `paseo`,
   `paseo-help` and `paseo-plugin` rather than editing a copy.
3. No re-vendoring: the three local patches of the old `skills/ade-paseo/UPSTREAM.md` (narrowed triggers, an interim
   worktree-isolation line, the `ade-` prefix) are gone with it (version control has it).

## 4. When the table is wrong

Fix [`skill-everywhere`](skill-everywhere) and the table above together, then re-run step 3
for the TUIs you changed. When a new TUI shows up in `aiuse --json` or under
`~/.local/bin`, find its skills dir from its docs or its binary, add a row, and
verify it.
