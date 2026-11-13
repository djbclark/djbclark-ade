---
name: paseo-screen
description: >-
  DEPRECATED (2026-11-13): the Paseo plugin `paseo-screen` is disabled ("super-buggy").
  Route for checking Paseo's own GUI: headless Playwright Chromium against the daemon
  web UI at http://127.0.0.1:7263/. Use for "verify it in the Paseo UI", plugin screens,
  settings switches. Host-desktop control is not available to CLI sessions (Claude
  computer-use tools exist only inside the Claude desktop app). Read the safety rules first.
---

# paseo-screen — DEPRECATED plugin; headless Playwright is the route for Paseo GUI checks

**Status (2026-11-13): the `paseo-screen` plugin is DISABLED.** Operator ruling, relayed by agent 5fd0bef1:
"paseo-screen is super-buggy". It is no longer "THE screen-control tool" (the 2026-10-31 ruling) and no longer
"stays enabled when idle". Do not re-enable, reinstall or call its RPCs (`screen.*`); only the operator
re-enables it. The plugin sections below are kept as history and for that case.

## The working route: headless Playwright against the daemon web UI

For a Paseo GUI check (plugin screens, plugin settings, switch state, chat and workspace views):

1. Launch headless Chromium (browsers stay headless, operator rule) and open the daemon web UI,
   `http://127.0.0.1:7263/` (no pairing needed; plugin screens and plugin settings render).
2. Wait a few seconds after `domcontentloaded`, then click and read through Playwright locators.
3. Read state from the ARIA snapshot (`page.locator("body").aria_snapshot()`): it shows switch state
   (on/off), which a screenshot can hide. Also save a screenshot and read it.
4. Report every action taken and what the next snapshot showed.

Example scripts (read them, cite their paths, never copy secrets from them):
`~/.local/state/bigteam/paseo4herdr-adapters/trial-2026-11-13/pwlib.py` (launch, `start()`, `snap()` helpers) and
`b4.py` in the same directory (plugin settings page walk-through); `trial-report.md` there records the trial.

This reaches Paseo's own UI only. A native app or the host desktop is out of reach: Claude computer-use tools
exist only inside the Claude desktop app, not in CLI sessions.

## Safety rules that still apply

1. Read before you act: snapshot or screenshot, then click; snapshot again to confirm. Never claim an action landed
   from the call returning.
2. The web UI is the operator's live daemon: never delete, archive, send, pair a client, change plugin settings or
   switch a plugin on or off without the operator's explicit yes for that action.
3. Never approve a pairing request; never touch password, 1Password or lock screens.
4. Headless only; claim no port (the daemon's 7263 is read-only use).

---

## Historical: the plugin (disabled 2026-11-13)


`paseo-screen` (https://github.com/kevguy/paseo-screen, MIT; listing
https://paseo.cafe/plugins/paseo-screen) streams the host Mac's display into a Paseo
viewer and sends mouse and keyboard events back. **It was the one screen-control tool**
(operator ruling, 2026-10-31; superseded 2026-11-13); Orca's `orca computer` and the `computer-use` stub are retired from djbclark-ade (Orca itself stays installed, untouched), never
start Orca for a GUI task. It was left enabled when idle (operator's choice, 2026-10-31) until disabled 2026-11-13.

## Install and state

```sh
paseo plugin add kevguy/screen        # plugin id: paseo-screen; operator only (rule 4)
```

Installed 2026-10-30 from the Paseo plugin registry, tracking whatever it lists: no version pin (djbclark, 2026-10-31:
nothing is version-pinned). After an install, `paseo plugin ls` must show `paseo-screen` `running`. It compiles a Swift helper (ScreenCaptureKit for frames,
CGEvent for input); the server code has no network, no listening sockets and no runtime dependencies (read
before install, 2026-10-30). Paseo already holds macOS Screen Recording and Accessibility, so there was no
permission prompt.

## Two ways in

1. **The viewer.** Open "Screen · mac" in the Paseo sidebar (desktop app or a paired client). It shows the
   live host desktop and a key bar. A human uses it directly.
2. **The RPCs**, for an agent: `client.invokePluginRpc("paseo-screen", METHOD, INPUT)` through the daemon,
   which is what the plugin's own `scripts/rpc-probe.mjs` does
   (`node scripts/rpc-probe.mjs <extracted Paseo app.asar dir> <method> '<json>'`; it saves a frame to
   `build/probe-frame.jpg` under the CURRENT directory and fails if `build/` is missing, so run it from the
   plugin checkout after `mkdir -p build`). Schemas are in the
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
that tests the questions-please plugin (then named next-question), whose first default shortcut did not work in djbclark's desktop app
(cause not found; its default is now Cmd+Shift+.), so it proves nothing about input delivery.
**Not verified:** mouse clicks, drags, the clipboard (`paste`, `screen.clipboard`), and multiple displays.
Test those on a throwaway target before depending on them, and say so in a report that relies on them.

## Driving the viewer without hurting anything (the method used on 2026-10-30)

1. Open the viewer in a **headless browser** (not the human's desktop window).
2. **Focus the viewer's stage element from JavaScript** (`div[tabindex=0]`, about 1080 x 675) instead of
   clicking it: a click on the stage lands on the real, live desktop.
3. Send keys as browser key events. A Paseo plugin of your own loaded in the same page swallows a chord
   first: rebind or disable it in that page.
4. Chords the Paseo app handles first (Cmd+Tab, Cmd+Space, Cmd+W, Cmd+Q) do not pass through key events;
   use the viewer's **key bar** buttons (reported 2026-10-30, not tested; the buttons exist in the plugin's
   client/screen.tsx at the pin).

## Safety rules (they bind every agent)

0. **Before the first `screen.*` RPC in a stretch, including a frame request**, give the operator about 30 seconds
   notice; no approval question is needed. After the last RPC, explicitly say **done using the screen**. This notice
   applies to the current session's verified Paseo UI too (operator, 2026-11-07); permission to operate that UI does
   not waive the notification.
1. **Never click or type into a live window you have not looked at.** Take a frame, read it, then act; take
   another frame to confirm. The pointer and keyboard are the human's real ones.
2. **Check the human is not mid-typing** (recent activity, a focused field with a half-written message)
   before sending input; wait or ask rather than steal focus.
3. **Never send `Cmd+Q`, `Cmd+W`, delete, send or purchase actions**, or touch password, 1Password or lock
   screens, without the operator's explicit yes for that action. A `locked: true` host is not yours to unlock.
4. **Exposure (the operator's accepted risk, 2026-10-31):** the plugin has no host-side authorization. While it
   is enabled, **every paired Paseo client and any local caller of the daemon's plugin RPC (so any agent on this
   Mac, whatever it has read; inferred from the daemon's local RPC, not tested; upstream's README says only "anyone paired") can see the screen and drive its mouse, keyboard, paste and clipboard** with the
   Screen Recording and Accessibility grants Paseo holds. The viewer's "view only" switch is per viewer, not a
   lock, and a viewer's Pause button only stops that viewer's frames (client/screen.tsx at the pin); a host-wide
   Pause on the sidebar row was reported but is untested, so never rely on it. A host-side authorization check
   would be an upstream (kevguy/paseo-screen) feature; none exists. Rules that follow from this, binding every agent:
   - **Never pair a new client** to the host, and never approve or accept a pairing request.
   - **Never enable, re-enable, reinstall, update, reconfigure or change the settings of the plugin.** Only the
     operator does.
   - **`paseo plugin disable paseo-screen` only on the operator's word.** It is the off switch (upstream README,
     Security), but it cuts the screen RPCs and the viewer for every other session mid-task, and staying enabled
     when idle is the operator's choice.
5. Report every input you sent (events and target window) and what the next frame showed; never claim a
   click landed from the event count alone (`handled` is not proof).

## Not this skill

Terminal-only or headless-browser work needs no screen control: use Paseo's own `paseo` skill, a browser tool, or
plain shell. Orca, `orca computer` and `computer-use` are retired.
