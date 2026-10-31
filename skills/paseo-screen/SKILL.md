---
name: paseo-screen
description: >-
  The route for controlling or looking at the Mac's GUI: any visible window, the
  desktop, a native app, a screenshot, a click, a key chord, "drive the app",
  "verify it in the desktop app", "computer use". Uses the Paseo plugin
  `paseo-screen` (viewer "Screen · mac" in the Paseo sidebar; RPCs
  `screen.status`, `screen.frame`, `screen.input`). Replaces the retired Orca
  `orca computer` / `computer-use` route (2026-10-31). Read its safety rules
  before the first click or keystroke.
---

# paseo-screen — look at and drive the host's screen through Paseo

`paseo-screen` (https://github.com/kevguy/paseo-screen, MIT; listing
https://paseo.cafe/plugins/paseo-screen) streams the host Mac's display into a Paseo
viewer and sends mouse and keyboard events back. **It is the one screen-control tool**
(operator ruling, 2026-10-31); Orca's `orca computer` and the `computer-use` stub are retired from djbclark-ade (Orca itself stays installed, untouched), never
start Orca for a GUI task. **It stays enabled when idle** (operator's choice, 2026-10-31).

## Install and state

```sh
paseo plugin add kevguy/screen        # plugin id: paseo-screen
```

Installed 2026-10-30 from registry pin `1df9050d3721d927aa73655ad2cb4b4b53f42db9`, `running`, enabled. It
compiles a Swift helper (ScreenCaptureKit for frames, CGEvent for input); the server code has no network,
no listening sockets and no runtime dependencies (read before install, 2026-10-30). Paseo already holds
macOS Screen Recording and Accessibility, so there was no permission prompt. Check with `paseo plugin ls`
that `paseo-screen` is `running` before relying on it.

## Two ways in

1. **The viewer.** Open "Screen · mac" in the Paseo sidebar (desktop app or a paired client). It shows the
   live host desktop and a key bar. A human uses it directly.
2. **The RPCs**, for an agent: `client.invokePluginRpc("paseo-screen", METHOD, INPUT)` through the daemon,
   which is what the plugin's own `scripts/rpc-probe.mjs` does
   (`node scripts/rpc-probe.mjs <extracted Paseo app.asar dir> <method> '<json>'`). Schemas are in the
   plugin's `shared/rpc.ts` (checkout under `~/.paseo/plugins/paseo-screen/<id>/checkout/`):

| RPC | Input | Returns |
|---|---|---|
| `screen.status` | `{}` | `supported`, `error`, `screenRecording`, `accessibility`, `locked`, `displays[]` (id, x, y, width, height in points, pixel size, main, builtin, name), `preferredDisplay` |
| `screen.frame` | `{maxWidth 320-8192, quality 0.1-1, display?, since?, wake?}` | `jpeg` (base64), `imageWidth`, `imageHeight`, `hash`, `display`, `locked`; with `since` an unchanged frame comes back with `unchanged: true` and no image; a sleeping host replies only `asleep` and `locked` unless `wake: true` |
| `screen.input` | `{display?, events[] (max 200)}` | `handled`, `pointerDisplay` |

`screen.input` events: `move`, `down`, `up`, `click` (`button` left/right/middle, `count` 1-3), `scroll`,
`key` (`keyCode` macOS virtual key or `char`; `down` omitted = press and release), `text`, `paste` (sets the
host clipboard, then Cmd+V). Mouse `x`,`y` are fractions 0-1 of the chosen display (drag points may leave it).
`modifiers` is any of `cmd shift alt ctrl fn`. The plugin also has `screen.request-permissions`,
`screen.clipboard` and `screen.choose-display`.

**Look first:** call `screen.status` (locked? which displays?), then `screen.frame` and read the image before
sending any input. Pass `since: <hash>` when polling.

## What was verified (2026-10-30) and what was not

Verified 2026-10-30: the viewer showed the live host desktop at about 10 fps, and a Cmd+K chord sent
through it reached the host Paseo window and opened the Command Center. Cmd+Shift+U was also sent, but
that tests the next-question plugin, whose first default shortcut did not work in djbclark's desktop app
(cause not found; its default is now Cmd+Shift+.), so it proves nothing about input delivery.
**Not verified:** mouse clicks, drags, the clipboard (`paste`, `screen.clipboard`), and multiple displays.
Test those on a throwaway target before depending on them, and say so in a report that relies on them.

## Driving the viewer without hurting anything (the method that worked)

1. Open the viewer in a **headless browser** (not the human's desktop window).
2. **Focus the viewer's stage element from JavaScript** (`div[tabindex=0]`, about 1080 x 675) instead of
   clicking it: a click on the stage lands on the real, live desktop.
3. Send keys as browser key events. A Paseo plugin of your own loaded in the same page swallows a chord
   first: rebind or disable it in that page.
4. Chords the Paseo app handles first (Cmd+Tab, Cmd+Space, Cmd+W, Cmd+Q) do not pass through key events;
   use the viewer's **key bar** buttons.

## Safety rules (they bind every agent)

1. **Never click or type into a live window you have not looked at.** Take a frame, read it, then act; take
   another frame to confirm. The pointer and keyboard are the human's real ones.
2. **Check the human is not mid-typing** (recent activity, a focused field with a half-written message)
   before sending input; wait or ask rather than steal focus.
3. **Never send `Cmd+Q`, `Cmd+W`, delete, send or purchase actions**, or touch password, 1Password or lock
   screens, without the operator's explicit yes for that action. A `locked: true` host is not yours to unlock.
4. **Exposure:** anyone paired with the host can see and control its screen while the plugin is enabled, and
   the viewer's "view only" switch is per viewer, not a lock. The off switch is
   `paseo plugin disable paseo-screen` (upstream README, Security); use it only when the operator asks, since
   staying enabled when idle is the operator's accepted risk. A viewer's Pause button only stops that viewer's
   frames and is not a lock (client/screen.tsx at the pin); a host-wide Pause on the sidebar row was reported
   but is untested, so never rely on it.
5. Report every input you sent (events and target window) and what the next frame showed; never claim a
   click landed from the event count alone (`handled` is not proof).

## Not this skill

Terminal-only or headless-browser work needs no screen control: use the `paseo` skill, a browser tool, or
plain shell. Orca, `orca computer` and `computer-use` are retired.
