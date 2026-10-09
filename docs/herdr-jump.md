# herdr-jump — move to a Herdr address from the keyboard

`bin/herdr-jump` gives Herdr the tmux `prefix+:`-style jump it lacks: press
`prefix+colon` (`ctrl+a :` here), type `w22:t4`, Enter, and that tab is
focused (workspace switched too). Verified 2026-10-08 on herdr
0.9.1-preview (2026-09-21) against the source at `~/src/herdr` (e2e7ed0a).

## Why a script

1. **No built-in address prompt.** Herdr's keybind actions
   (`src/config/keybinds.rs:315-369`) take no text; `prefix+1..9`,
   `prefix+shift+1..9` and navigate-mode digits jump by *sidebar position*
   (`src/app/actions.rs:438-446`), so `prefix+shift+2` is "second workspace
   row", never `w2` or `w22`. There is no command line or runnable palette:
   `prefix+?` is a read-only keybind help.
2. **The Goto picker half-covers it.** `prefix+g`, `/`, then `w23:p7` finds a
   *pane* by id (pane ids joined the search haystack in e0507237, 2026-09-19;
   `src/client/shell/aggregate_navigation.rs:390-400`). Tab ids and
   workspace ids are not in the haystack (only labels, `:337-347`).
3. **Upstream will not add one.** Command-palette and address-jump requests
   are all closed or parked: PRs herdrdev/herdr#2299 and #2777 (closed
   unmerged, 2026-08), issue #4134 (closed not-planned 2026-09-14), discussions
   #1624 ("expose client actions over the socket", 6 upvotes) and #2283 (5)
   open in Ideas. Maintainer policy routes every such request to Ideas.
4. **The server-side focus calls exist.** `herdr tab focus w22:t4`
   (`src/app/api/tabs.rs:132-136`, switches workspace) and
   `herdr workspace focus w22` take ids. Panes: the CLI has only
   `herdr pane focus --direction` and `herdr agent focus <pane>` (agent panes
   only); any pane is focused by the socket method `pane.focus`
   (`src/api/schema.rs:186`, `src/app/api/panes.rs:484-500`), newline-delimited
   JSON on `~/.config/herdr/herdr.sock`. The script wraps those three.

## Setup

In `~/.config/herdr/config.toml` (added 2026-10-08; `colon` is a named key,
`src/config/keybinds.rs:1278`):

```toml
[[keys.command]]
key = "prefix+colon"
type = "popup"
command = "~/src/djbclark-ade/bin/herdr-jump"
description = "jump to a w / w:t / w:p address (herdr-jump)"
width = 48
height = 3
```

Then `herdr server reload-config`. Popup commands receive `HERDR_BIN_PATH`
and `HERDR_SOCKET_PATH`; from a plain shell the script falls back to `herdr`
on PATH and `~/.config/herdr/herdr.sock`.

## Use

1. `ctrl+a :` then `w22:t4` Enter — focus tab 4 of workspace 22.
2. `ctrl+a :` then `w23:p7` Enter — focus pane 7 (shell or agent pane).
3. `ctrl+a :` then `w22` Enter — focus workspace 22.
4. From any shell: `herdr-jump w22:t4` (same forms). Case and the leading
   `w` are optional (`2e:T1` works; workspace ids are uppercase hex).
5. An unknown id prints Herdr's error in the popup for 1.5 s and exits 1.

## Third-party pickers

Fuzzy navigators exist as plugins (`thanhdat77/herdr-navigator`,
`mr04vv/herdr-pane-navigator`, `beyondlex/herdr-recent-navigator`,
`JanTvrdik/herdr-command-palette`); the 2026-10-08 evaluation of which one
ranks an exact `w22:t4` first is recorded below this line when done.
