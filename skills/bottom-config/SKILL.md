---
name: bottom-config
description: >-
  Edit, validate and preview the config of bottom (the `btm` process monitor)
  and its fork build `btm-mt` with the middle-truncated Command column
  (`processes.truncate_cmd_middle`). Use when changing ~/.config/bottom/bottom.toml,
  tuning columns, layout, colors or process options, or when btm-mt needs a rebuild.
---

# bottom-config

djbclark runs two binaries from the same config, `~/.config/bottom/bottom.toml`:

1. `btm`: Homebrew's stock bottom (`/opt/homebrew/bin/btm`).
2. `btm-mt`: the fork `djbclark/bottom`, branch `middle-truncate-command`, checkout
   `~/src/bottom`. It adds `[processes] truncate_cmd_middle = true`: a command too
   wide for its column keeps its start and end around `[...]`. Stock `btm` ignores that key.

## The trap: typos are silent

bottom ignores unknown config keys in release builds (checked 2026-11-01: a config with
`truncate_cmd_midle` and `process_comand` started normally, showing names). The published
schema does not forbid them either. So after EVERY edit run the strict validator:

```sh
~/src/djbclark-ade/skills/bottom-config/scripts/validate.py            # the live config
~/src/djbclark-ade/skills/bottom-config/scripts/validate.py FILE       # another file
```

It adds `additionalProperties: false` to the fork's `schema/nightly/bottom.json`, names the
unknown key with a "did you mean", and reports wrong types by path. Exit 0 = valid, 1 =
problems, 2 = unreadable input. It needs `uv` (it carries its own `jsonschema` dependency).

## Workflow

1. Find the option: `~/src/bottom/docs/content/configuration/config-file/*.md` (one page
   per area: `processes`, `flags`, `layout`, `styling`, the graphs and tables) and the
   commented sample `~/src/bottom/sample_configs/default_config.toml`. Read those; do not
   guess key names or values.
2. Edit `~/.config/bottom/bottom.toml` (keep the comments; they say which binary knows a key).
3. Validate (above).
4. See it, without touching the user's terminal:
   ```sh
   scripts/preview.py                           # live config, 140x30, process widget
   scripts/preview.py --config /tmp/try.toml --width 100 --keys t   # a draft; `t` = tree
   ```
   It runs `btm-mt` in a throwaway tmux session and prints the screen. Use a draft file for
   experiments; copy it over the live config only when it looks right. Keys in the process
   table: `P` name/command, `t` or `F5` tree, `e` expand widget; more in
   `~/src/bottom/docs/content/usage/widgets/process.md`.
5. Config that only `btm-mt` understands goes under a comment saying so; stock `btm` must
   still start with the file (it does: unknown keys are ignored).

## Rebuilding btm-mt (never build locally)

Builds go to CI (standing rule, `memory/feedback_macos_ci_on_request_only.md`). Work in
`~/src/bottom` on `middle-truncate-command`, push to the fork (`origin` = `djbclark/bottom`);
`.github/workflows/fork-build.yml` runs fmt, clippy and tests, and on a push (not a PR)
builds the macOS arm64 binary as artifact `btm-macos-arm64`:

```sh
gh run list -R djbclark/bottom --branch middle-truncate-command --limit 3
gh run download RUN_ID -R djbclark/bottom -n btm-macos-arm64 -D /tmp/btm-mt
tar xzf /tmp/btm-mt/btm-macos-arm64.tar.gz -C /tmp/btm-mt && xattr -c /tmp/btm-mt/btm
cp /tmp/btm-mt/btm ~/.local/bin/.btm-mt.tmp && chmod 755 ~/.local/bin/.btm-mt.tmp \
  && mv -f ~/.local/bin/.btm-mt.tmp ~/.local/bin/btm-mt     # atomic replace
```

To follow upstream: `git fetch upstream && git rebase upstream/main` in `~/src/bottom`
(the conflict hot spot is `src/widgets/process_table/process_data.rs`), push with
`--force-with-lease`, wait for CI, reinstall. Do not file anything upstream: its
`AI_POLICY.md` requires human-written issue and PR text.

## Where the change lives

`truncate_middle()` in `src/utils/strings.rs`; applied in `Id::to_cell_string` and
`ProcWidgetData::to_cell_text` (`process_data.rs`); option read in `src/options.rs`.
Under 7 columns it falls back to the stock end-cut. Sorting and search still use the full
command; only the drawn cell changes.
