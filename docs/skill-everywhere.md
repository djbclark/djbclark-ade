# skill-everywhere — one skill, every local TUI

README for [`skill-everywhere`](../bin/skill-everywhere) (canonical script in
this repository; compatibility command `~/ops/site-private/bin/skill-everywhere`). It makes a local skill available to
every agent TUI on this machine (Claude Code, Codex, omp, Copilot, Cursor, opencode,
zcode, Grok, Qwen, Devin, Cline, Muse, Antigravity and Hermes) by
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

Editing the git copy updates every agent. Never copy: a
copy drifts silently. `~/.agents/skills/handoff` is a symlink to the git
copy. The stale copy is `~/.agents/skills/.trash/`. Grok walks that tree
and can advertise the trash skill under the live name. Hide it with
`[skills] ignore` in `~/.grok/config.toml`, and link Grok's own
`~/.grok/skills` at the git copy too.

## 1. Link it

```sh
~/src/djbclark-ade/bin/skill-everywhere <name>...          # link, idempotent
~/src/djbclark-ade/bin/skill-everywhere --check <name>...  # status only
~/src/djbclark-ade/bin/skill-everywhere --remove <name>... # undo
```

If the skill has no directory yet, create it first: public skills in
`~/src/djbclark-ade/skills/<name>/`, private ones (operator ruling required)
in `~/ops/site-private/skills/<name>/` plus a line in `.githooks/private-paths`
there. The script skips TUIs that aren't installed. If a path
already exists and isn't our link, the script leaves it alone and exits non-zero.
Report that rather than overwriting it. In link mode the script also
**collapses chains**: any existing link whose realpath equals the target but
whose readlink differs is replaced with the direct link.

**Retiring a skill:** run `--remove <name>` and re-point anything that loads
it by name (Hermes `skill-slash` handlers, Claude/zcode command wrappers)
before deleting its directory. `--remove` also works
after the directory is gone: it removes only links whose target is exactly
one of the two roots.

## 2. Where each TUI looks (verified 2026-10-03)

| TUI (binary) | How it gets the skill |
|---|---|
| Claude Code (`claude`) | `~/.claude/skills` |
| Codex (`codex`) | `~/.agents/skills` |
| Copilot (`copilot`) | `~/.copilot/skills` |
| opencode (`opencode`) | `~/.config/opencode/skills` |
| Qwen Code (`qwen`) | `~/.qwen/skills` |
| Devin (`devin`) | `~/.config/devin/skills` |
| Cline (`cline`) | `~/.cline/skills` |
| Hermes (`hermes`) | `~/.local/share/skill-everywhere/skills`, which Hermes put in its own `skills.external_dirs` |
| Cursor (`cursor-agent`), Muse (`muse`) | already read `~/.claude/skills`; no extra link |
| Grok (`grok`, including Grok Build) | `~/.grok/skills`. It also scans `~/.claude/skills` and `~/.agents/skills` and dedups by name. Verified 2026-10-04: a same-named `SKILL.md` under `~/.agents/skills/.trash` was the copy this session was offered, so `~/.grok/config.toml` ignores that trash dir and this script links the live skill here. |
| zcode (`zcode`) | already reads `~/.agents/skills`; an extra link listed it twice. **Loaded ≠ slash-invocable:** zcode's typed `/` surface resolves only built-ins, plugins and `~/.zcode/commands/*.md`; a user skill needs a command wrapper there (`skills: <name>` frontmatter auto-mounts it). Wrappers for the universal set (baton, resume, handoff, loose, steps, helm, helm-all, session-finder, session-finder-all, herdr-tidy, orca-tidy, skillopt-sleep, bigteam, autorename, hyades-docker) live in `~/src/djbclark-ade/zcode/commands/`, symlinked directly into `~/.zcode/commands/`; add one there when adding a slash-shaped skill. Until the TUI restarts it won't see new wrappers; in a running session the built-in `/skill <name>` reaches any loaded skill without one. |
| Antigravity (`agy`) | `~/.gemini/antigravity-cli/skills` (agy CLI 1.2.16; links are followed). Verified with `/skills` in interactive agy. Headless `agy -p` answers never mention user skills, not even the installer's bailian ones, so check agy interactively. `~/.gemini/config/skills` and `~/.gemini/antigravity/skills` are not read by the CLI |
| omp / oh-my-pi (`omp`) | `~/.omp/agent/skills` (native, highest skill priority; added 2026-10-13). omp also reads `~/.agents/skills`, but de-duplicates by `realpath`, so the second link does not list a skill twice. omp ignores `~/.claude/skills` unless `claude` is in its `enabledProviders`. Prove it with `omp -p --no-title "<step 3 prompt>"` from a scratch dir. |
| Grok Bot (`grokbot`, no binary; present when `~/agent-data/workflows` exists) | **Copy, not link** (added 2026-10-23): Grok Bot runs on its own Linux box (`HOME=/home/box`) and reads `~/agent-data/workflows/<slug>/SKILL.md` as plain files, so no link into a Mac checkout could resolve. The script renders `ade-<name>/`: symlinks dereferenced, a "managed copy" banner after the front matter (Mac-only paths, Grok Bot's approval rules win), and a `.skill-everywhere` marker. Only a dir with that marker is updated or removed; `--check` reports `copied`, `stale copy`, `missing` or `not ours`. On the box run it with `SKILL_EVERYWHERE_ONLY=grokbot`, or the box's own claude, agy, cline and hermes get links too. The box's nightly driver is `/home/box/agent-data/shared/skills-sync/sync.sh` (fetches `origin/master`, picks which skills suit Grok Bot, keeps a manifest, runs this script). |

`aiuse --json` providers with no TUI of their own (alibaba, deepseek,
openrouter, litellm, opencode-zen, clinepass, grok) are API pools behind the
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
`cursor-agent` needed `--trust` and `devin` needed
`--respect-workspace-trust false` in a scratch dir. Offline checks:
`muse skills list` and `hermes skills list`; for agy, `/skills` in an interactive session. A NOSKILL from a model can be
wrong. When in doubt, ask it to list every skill name it has: that is how Cursor
turned out to be fine.

Codex was verified the same day: `codex exec -s read-only` quoted the
`steps` description verbatim from `~/.agents/skills`.

**agy: probe it at most once, never in a loop.** The rules and the 2026-10-03
lockout are in the `model-routing` skill ("agy has a burst limit"). For this
check: the offline proof is `skill-everywhere --check <name>` (the link exists)
plus one interactive `/skills`, which makes no generation request; if a headless
probe is unavoidable, run exactly one with `--print-timeout 60s`, batch every
skill name into that one prompt ("list every skill name you have") and reuse the
answer. It has to be the CLI, not `acp-run agy`, only because the ACP server's
shadow GEMINI_HOME (`~/.local/share/agy-acp-home`) reads different skill
directories, so an ACP answer cannot prove what the CLI sees.

A check can fail for reasons that have nothing to do with where the skill was
put: a usage limit, an expired login, or no provider configured. Report those
TUIs as unverified, not as broken, and re-check once the account works.

Hermes Telegram `/name` is a **slash command**, not a skill lookup. Linking
via this tool puts the skill in `skills.external_dirs`; it does **not**
register `/steps`. That lives in `~/.hermes/plugins/skill-slash` (`/steps`,
`/helm`, `/helm-all`, `/session-finder-all`, `/baton`, `/skill <name>`). Enable `skill-slash` in `plugins.enabled`. Since 2026-10-06
`skill-everywhere` auto-nudges the running gateway (`reload-plugins` control
socket) so a plugin command like `/helm` or `/steps` dispatches immediately —
no manual gateway restart. The Telegram pull-up `/` menu is only republished
at adapter (re)connect, so a just-added command may not autocomplete until the
next restart, but typing it still works and `/commands` lists it. If you cannot
run `skill-everywhere` (e.g. changing the plugin without a skill), ask Hermes
to run `reload-plugins` the same way. Claude Code slash wrappers live in
`~/src/djbclark-ade/claude/commands/` and are symlinked directly into
`~/.claude/commands/`.

## 3a. Paseo overwrites its six skills unless told not to (2026-10-23)

Paseo's daemon syncs its bundled skills (`paseo`, `paseo-advisor`, `paseo-committee`, `paseo-handoff`,
`paseo-help`, `paseo-plugin`) into `~/.claude/skills` and `~/.agents/skills` at **every start**
(`orchestrationSkills.autoUpdate()`), overwriting whatever it finds. Those two paths are directory links into this
repo, so the write landed here: our narrowed descriptions (`skills/paseo/UPSTREAM.md`) were replaced by upstream's,
with a `.paseo-managed-files.json` beside each (markers dated 2026-10-19 12:16, the daemon start).

**The fix is Paseo's own skill selection, not a different link layout.** `~/.paseo/config.json` carries
`agents.skills.selection = {"mode": "custom", "skills": []}` (set 2026-10-23, applied with `paseo reload`; backup
`~/.local/state/paseo-backups/config-2026-10-23-pre-skill-selection.json`). With nothing selected, the start-up
sync only plans deletions and never applies them, so it writes nothing; with `{"mode": "all"}` (the default) it
overwrites. Checked with the shipped `operations.js` against the real directories, not by a daemon restart (a restart
would end this machine's Paseo agents).

1. Paseo's settings screen now shows the six skills as drift ("to be removed"). Do not save the selection there and
   never confirm the removal: it deletes our directory links (not the repo files). Re-link with
   `skill-everywhere paseo paseo-advisor paseo-committee paseo-handoff paseo-help paseo-plugin`.
2. A key set with `"skills"` at the top level of `config.json` is rejected by `paseo reload` (and would stop a
   restart): the persisted path is `agents.skills.selection`.
3. Re-vendoring a newer Paseo bundle is done by hand (`skills/paseo/UPSTREAM.md`).
4. Tried and dropped: a real directory holding per-file symlinks makes Paseo's sync throw before writing (verified),
   but Cursor's loader rejects a `SKILL.md` symlink that resolves outside its skills root (codex `gpt-6-astra`
   review, 2026-10-23, verified in the installed Cursor source) and Cursor reads `~/.claude/skills` here; a settings
   save also stages deletions before it reaches the guard.
5. Upstream: [getpaseo/paseo#7700](https://github.com/getpaseo/paseo/issues/7700), `docs/upstream-issues.md` item 10.

## 4. When the table is wrong

Fix [`skill-everywhere`](skill-everywhere) and the table above together, then re-run step 3
for the TUIs you changed. When a new TUI shows up in `aiuse --json` or under
`~/.local/bin`, find its skills dir from its docs or its binary, add a row, and
verify it.
