# GUI-hog dialog: design (2026-11-14, PR 3 of the load-gate retune)

Status: **PR 3a is built (2026-11-14): the data and a dry-run trigger, no window** (section M). **PR 3b is built (2026-11-14): the native window, Quit / Force Quit / Quit All, the trigger live** (section N says what it does, where it departs from this text, and the operator's H4 run, which has NOT been done: 3b must not merge without it). PR 3c (Freeze) is not started. The operator accepted K1-K7 (all recommended) on 2026-11-14. The rest of this document is the design. **PR 3c's Python side is built (2026-11-14, section O): Freeze, every thaw path and the escape hatch; its Swift row buttons and menu-bar item are added on top of PR 3b.** **2026-11-21 (section P): the operator amended B6, so apps on the `[freeze.auto]` list are frozen by the sampler while a build is held; a keep-running rule leaves CodexBar's HTTP server running; Chrome's native-messaging hosts no longer make it a build host; rapid Freeze clicks on several rows all get through.**
Rulings come from the operator's 2026-11-13 and 2026-11-14 `/steps` answers, recorded in the lead's memory note
`project_load_gate_retune_proposal_2026-11-13.md`. Items marked **DECIDE** are open forks. Each one has a
recommendation, and the build slices follow the recommendation unless the operator rules otherwise.

## A. What a native Swift GUI is, and when and why we chose it

A1. **In plain terms.** A native Swift GUI is a small Mac program, written in Swift and drawn with Apple's own window
kit (AppKit, with SwiftUI where it helps). It is the same kind of window Finder or Activity Monitor shows. `swiftc` is
Apple's command-line Swift compiler. It turns one or a few `.swift` source files into a normal Mac executable, with no
Xcode project and no App Store. The program opens a real window that can have any number of rows and buttons. It can
also ask macOS about running apps through `NSRunningApplication`, Apple's API for "this app with this pid": its name,
bundle id, launch date, and polite or forced quit.

A2. **When.** On 2026-11-13 the operator asked for a dialog that shows up when a build is held by `bg`'s load admission
and the cause is ordinary desktop apps, not builds (the "GUI-hog" case). That same day they ruled on the header, the
rows and the buttons (section B). A constraint check on 2026-11-13 found three things.
(a) AppleScript `display dialog`, which `sudo-ask` uses, allows **at most 3 buttons** and has **no per-row buttons**.
(b) **PyObjC is not installed** (`python3 -c "import objc"` fails with `ModuleNotFoundError`, re-checked 2026-11-14), so
Python cannot drive AppKit.
(c) **`swiftc` is installed** (Apple Swift 6.4, `arm64-apple-macosx27.2.0`, MacOSX27.2 SDK, re-checked 2026-11-14).
So the window is Swift.

A3. **Why Swift and not the alternatives.**

| Option | Why not |
|---|---|
| AppleScript `display dialog` (what `sudo-ask` is: a bash script, `~/ops/site-public-djbclark/bin/sudo-ask`, that runs `osascript`) | 3 buttons at most and no rows. One dialog per app would be a chain of modal pop-ups: that is nagging, which the operator rejects (`feedback_loadwatch_warn_only_if_abnormal`) |
| AppleScript `choose from list` | Picks items but has one action, no per-row buttons and no live numbers |
| Python + Tk | Tk is not reliably present in the system Python. Tk windows on macOS have poor focus and keyboard behaviour. Tk cannot call `NSRunningApplication`, so polite Quit would need AppleScript by bundle id, which hits every instance that shares a bundle id (three `com.github.Electron` apps were running on 2026-11-14) |
| Python + PyObjC | Not installed. Installing it adds a third-party binary dependency to the system Python. Order 5 of `~/CLAUDE.md` would allow it, but it gains nothing over Swift |
| A local web page | Needs a claimed port and a server (`~/CLAUDE.md` item 34). Browsers cannot signal processes, so a privileged local endpoint would be a new attack surface (section J) |
| A notification (`UNUserNotificationCenter`, `terminal-notifier`) | At most a couple of actions, no rows, and macOS may hide it under Focus |
| An existing tool | Activity Monitor has no "held build" context and no timed freeze. App Tamer did automatic throttling: it lost the 2026-10-24 A/B (load per core 1.09 vs 0.73, swap 9.4 vs 4.8 GB) and was uninstalled (`project_siriinferenced_disabled_apptamer_quit`). Shiny (theodorehq.com) and similar pausers freeze **automatically**, which the operator ruled out ("never automatic") |

A4. **What Swift costs.** (a) A build step. The binary is compiled once per source change by an install step, never on
every run (D2). (b) **No Linux CI for the GUI part.** GitHub's Linux runners have no AppKit. The macOS leg of
`.github/workflows/test.yml` runs only on manual dispatch (operator, 2026-10-29). So the Swift part is kept thin, and
all decision logic lives in stdlib Python that Linux CI tests (D1, H). (c) A second language in a Python and shell repo.
(d) The window cannot be screenshotted headlessly, so it gets a manual acceptance checklist (H4).

## B. What the operator asked for (rulings, condensed)

B1. **Trigger.** A build has waited 3 min under `bg`'s admission, and non-build GUI apps use >= 0.75 core (5-min
average) or >= 2 GB. The dialog shows at most once per 30 min. Ignore snoozes it for 60 min.

B2. **Header.** The 1/5/15 load triplet and a 5-minute sliding average (btm-mt's F8 window, `~/.config/bottom` `average
= "5m"`).

B3. **Rows.** One per app, with unnormalised cores (5-min average), CPU and RAM, and the buttons Quit, Force Quit,
timed Freeze (default 10 min, then it resumes by itself), indefinite Freeze and Resume.

B4. **Bottom row.** Wait (the default; it does nothing; leftmost; Enter and Esc do nothing), Ignore, Quit All. This is
the `sudo-ask` style.

B5. **Freeze is SIGSTOP**, with these safeguards:
(a) a persisted frozen list (pid plus process start time, checked before SIGCONT);
(b) SIGCONT on startup, after a crash and after a reboot;
(c) a visible frozen-apps list with Resume;
(d) the whole process tree is frozen (Chrome and Electron helpers);
(e) a protected list: Paseo, terminals, Finder, Hermes, VPN and proxy, the build itself, WindowServer, Dock and
loginwindow.

B6. **Automatic only for the operator's own list (amended 2026-11-21).** Every Quit and Force Quit, and every Freeze of an app that is
not on the list, is an operator click (2026-11-13 proposal). On 2026-11-21 the operator ruled that apps listed in `config/gui-hog.toml`
`[freeze.auto] order` may be frozen automatically while a build is held (section P1); `[protected]` and the hard floor still win, so a protected
app is never auto-frozen. *Resuming* is always automatic.

## C. The trigger: where it lives and how it is called

C1. **Today's data is not enough.** The sampler (`load-watch sample`, launchd every 20 s,
`launchd/com.djbclark.load-watch.plist`) keeps per-process samples **only while the load is hot**
(`bin/load-watch` ~1478-1496: `st["samples"]` is cleared when `load1/ncpu < LW_LOAD_PER_CORE`, 4.0). But a build is
often held by `pageins`, `swapins`, churn or the free-memory floor while the load is below 4/core (2026-11-13: the only
refusal measured was `pageins`). The samples also do not store RSS (`PSTATE` has it for the current sample only).
`admit` keeps no on-disk record of who is waiting *now*: `admit_log` writes one line when a call **ends**.

C2. **Hold registry (new, written by `admit --wait`).** On each poll in which a waiting `admit` is refused, it writes
`~/.local/state/load-watch/held/<pid>-<start>.json` atomically:
`{"v":1,"pid":N,"start":"<lstart UTC>","caller":"<admit_caller()>","refused_since":<epoch>,"refused":["pageins",...],"updated":<epoch>}`.
It removes the file in a `finally` when it returns. Like `admit_log`, the write and the removal sit in their own
`try` and can **never raise, change the verdict or change the exit code**. `gui_hog` is imported lazily, inside that
`try`. If the module breaks, `admit` still answers 0 or 75, and `bg` never falls back to its plain load check (`bg`
~695), which would lose the churn gate and the valve. `refused_since` goes through the follow-ups slice's
`parse_refused_since` rule before it is written, never a second rule. A non-integer or future value is ignored, and the
age is capped at `STARVE_REFUSED_SINCE_MAX_S`. A cross-chunk value from `bg` is legitimately older than this `admit`
process. A file whose `updated` is more than 60 s old, or whose pid and start
no longer match, is stale and gets swept. `refused_since` is the start of the unbroken refusal run. It comes from the
`--refused-since` argument when one is passed. The follow-ups slice (worker 6c092e3c) is adding that argument to
`load-watch`, and the 3-minute trigger uses the same clock. It spans `bg`'s 420 s chunks only once `bg`
(site-public-djbclark: the operator's yes, AGENTS.md order 11) passes it. Until then each chunk restarts the clock. The
trigger still fires 3 min into a chunk, but not across a chunk boundary. `admit` only **writes a file**.
Its docstring contract ("only ever decides; never kills, throttles or signals anything") stays true.

C3. **Always-on app window (new, in the sampler).** Every sample adds one compact entry to
`st["apps"]` (trimmed to the last 300 s, whatever the load). The entry holds the per-app sum of cores (`%cpu/100`) and
RSS, and the machine total of cores, which becomes the header's sliding average. "App" means the process tree under one
GUI app: a process with `lsappinfo` type `Foreground` or `UIElement` that owns an `.app` bundle path, plus its
descendants and any process whose executable sits inside that bundle (`X.app/Contents/Frameworks/X Helper
(Renderer).app/...`). Each app costs one `lsappinfo list` call per sample. That is a stock macOS command (checked
2026-11-14), so PyObjC is not needed. Size: about 15 samples × about 40 apps, a few KB of `state.json`.

C4. **Decision (one pure function, `gui_hog.should_show(held, apps, now, snooze, last_shown, cfg)`):**
(a) some held record has `now - refused_since >= 180 s` (`hold_s`);
(b) its refusals include at least one gate that desktop apps can relieve (`load`, `churn`, `pageins`, `swapins`,
`free_mb`). The agent cap and the reservation cap do not count, because quitting an app does not help them;
(c) the **sum** over non-build apps of their 5-min mean cores is >= 0.75 (`min_cores`), or their summed RSS is >= 2 GB
(`min_rss_mb` 2048);
(d) it is at least 30 min since the dialog was last shown (`rate_s` 1800), and Ignore's snooze (60 min) has expired.

"Non-build" excludes four kinds of tree. (a) Any app tree whose ancestry reaches a held caller's pid, a Paseo agent CLI
(`AGENT_CLIS`) or `bg`. That covers Playwright's Chrome for Testing. (b) **Build subtrees inside an app**: the walk down
an app's tree **stops** at five kinds of process: (1) a shell; (2) a pty-attached process; (3) `bg` or an agent CLI;
(4) a process holding an admit reservation; (5) **any descendant whose executable realpath lies outside the app's own
bundle**, such as a JDK `java` (an IDE's Gradle daemon through the tooling API), `/usr/bin` and Homebrew tools, or
toolchains. The cores of those subtrees never count towards the app. An app that has such a subtree gets no actions
(E2). So `make` in VS Code's terminal, or a Gradle daemon an IDE started, is a build and not a GUI hog. IDEs whose
toolchain sits **inside** their bundle defeat stop (5): Xcode (`com.apple.dt.Xcode`, whose `swift-frontend` and `clang`
run from `Xcode.app`) and IDEs that bundle a JDK (Android Studio and other JetBrains IDEs). These IDEs are protected by
bundle id by default (F6). (c) **Known** build GUIs that LaunchServices starts with ppid 1 (Simulator from `simctl` or
`xcodebuild`). Ancestry cannot see these, so they are protected by bundle id (F6). An arbitrary app opened through `open`
cannot be told apart from an app the operator opened, so it is not claimed. (d) Any protected app (F6) and the dialog itself.

C5. **Who calls it.** The sampler calls it on every tick (20 s). It runs as a launchd agent in the operator's `gui/$(id -u)`
domain, which is the Aqua session: exactly where a window can appear. When `should_show` is true and the dialog is not
already running (its single-instance lock, D5), the sampler launches it **detached** and records `last_shown`. The launch
is `subprocess.Popen` with an argv list, `start_new_session=True`, explicit `close_fds=True`, and stdio set to
`/dev/null` or a log file. It is never waited on. `bin/ade-job-run` makes its admission-lock fd inheritable, and a
long-lived dialog or status item that kept that fd would make `ade-sched reconcile` defer forever. **The build never waits on the dialog.**
Admission, the starvation valve and the CI offload run exactly as if the dialog did not exist.

C6. **DECIDE C6: the trigger lives in the sampler (recommended), not in `admit` or `bg`.** `bg` lives in
`site-public-djbclark`, which is another repo, so changing it needs the operator's yes (AGENTS.md order 11). A
trigger there would also miss every other `admit --wait` caller (the fan-out recipe). Spawning from `admit` would put a
GUI side effect inside a call that every dispatcher makes (`bg`, the fan-out recipe, up to `LW_MAX_AGENTS` launches), from SSH and CI-like contexts, where no GUI session may
exist. The sampler already runs in the right session, already samples `ps`, and has the state file.

C7. **DECIDE C7: is the 0.75-core / 2 GB threshold a sum or per app? Recommended: the sum.** The words "GUI apps use"
read as a sum. Rows still list every app above 0.05 cores or 200 MB, so the operator sees each one. RSS double-counts
pages that are shared between Electron helpers, so the 2 GB test tends to fire early. PR 3a's dry-run log (I1) measures
how often it would have fired before any window exists.

## D. Process model

D1. **Thin Swift view, stdlib-Python core (recommended; DECIDE D1).** The Python module
`bin/gui_hog.py` (CLI `bin/gui-hog`, imported by `load-watch`) owns every decision:
(a) the trigger;
(b) app grouping;
(c) the protected list;
(d) process identity;
(e) the frozen-list state machine;
(f) the SIGSTOP and SIGCONT calls;
(g) the event log.
The Swift binary `ade-gui-hog` only displays the snapshot and turns clicks into `bin/gui-hog` argv. The one action it
performs itself is Quit and Force Quit through `NSRunningApplication`, which Python cannot reach: AppleScript `quit` goes
by bundle id and hits every instance that shares it (A3). The alternative, all logic in Swift, would put the freeze state
machine where Linux CI cannot test it.

D2. **Source, build and install.** The source lives in `macos/gui-hog/*.swift` (new directory), plus a minimal
`Info.plist` (`LSUIElement` true, bundle id `com.djbclark.ade.gui-hog`). `bin/ade-gui-build` compiles it:
`swiftc -O -target arm64-apple-macosx15 -framework AppKit`, then wraps it in
`~/.local/libexec/djbclark-ade/ADE GUI Hog.app` and ad-hoc signs it (`codesign -s -`). It stamps the bundle with a
SHA-256 of the sources. `bin/ade-update` runs `ade-gui-build --if-stale` after its fast-forward, and on Linux or without
`swiftc` it is a no-op that says why. There is **never a build at trigger time**. A missing or stale bundle means no
dialog: one log line a day, and the build is unaffected. A bundle, not a bare executable, gives the dialog a stable bundle
id, so it can protect itself and macOS can activate its window normally.

D3. **Data in.** The sampler rewrites `~/.local/state/load-watch/gui-hog/snapshot.json` atomically (mode 0600) on every
tick while a hold is active or the dialog runs. The snapshot holds the header numbers, the held callers (caller label,
wait, refusals) and the rows (`app_id`, display name, bundle id, bundle path, root pid and start, member count, cores_5m,
cpu_now, rss_mb, frozen state). The dialog re-reads the file when its mtime changes (a 2 s check). There is no stdin
contract, because the window outlives one sample. **No command lines** go into the snapshot: they can carry tokens
(`admit_caller` already strips them).

D4. **Actions out.** Each click runs `bin/gui-hog` through `Process` with `executableURL` plus an `arguments` array:
(a) `vet --pid P --start S --bundle-id B` (exit 0 allowed, 3 protected, 4 identity changed, 5 hosts a build or
terminal subtree). `vet` re-walks the app's tree **live** using the C4b rule, never the snapshot's member list, which can
be about 22 s old. Swift honours exit 5 for `terminate()` and `forceTerminate()` as well as for Freeze;
(b) `freeze --pid P --start S --minutes 10|--indefinite`;
(c) `resume --entry ID`;
(d) `log --event ...`.
The bundle id, start and path on the argv are only **expected values**. `vet` and `freeze` read the bundle id, bundle
path, executable and start time from the **live pid** (F3). They refuse on any mismatch, and they check the protected
list against the live values, never the argv. `freeze` runs the `vet` checks itself, on the root and on every member it
is about to stop, so it never relies on Swift having called `vet`. Quit and Force Quit run `vet` first. Swift then
re-checks `NSRunningApplication(processIdentifier:)`: its bundle id against the snapshot, and its `launchDate` against
`start` (one-second tolerance). A nil `launchDate` means refuse. Only then does it call `terminate()` or
`forceTerminate()`.

D5. **Exit codes of `ade-gui-hog`.** The sampler is a one-shot process each tick (`StartInterval` 20 through
`ade-job-run`), so no later tick can read a detached child's exit status. The dialog therefore records its own outcome:
it writes `gui-hog/last-exit.json` atomically (`{"code":N,"at":epoch,"by":"dialog"}`), and Ignore runs
`bin/gui-hog snooze --minutes 60` itself, which writes `gui-hog/snooze.json` (`{"snooze_until":epoch}`). Both files are
written atomically through a unique temp name (`tempfile.mkstemp` in the same directory, then `os.replace`). The sampler
only **reads** them and never writes them, and the dialog never touches the sampler's `state.json`. The sampler's
`save_state` uses a fixed `state.json.tmp` with no lock (`bin/load-watch` ~250-254), so a second writer would clobber it
or lose the snooze. The codes still
matter for manual runs and tests (nothing blocks on them):

| Code | Meaning | Sampler does |
|---|---|---|
| 0 | closed by Wait, by the window's close button, or because the hold ended | nothing; the 30-min rate limit stands |
| 3 | Ignore | the dialog has already written `snooze_until = now + 3600` |
| 4 | closed after Quit All or row actions | logs the event; the rate limit stands |
| 69 | no window server (`NSApplication` could not connect) | logs `no-gui`, suppresses retries for 30 min |
| 70 | internal error | logs it with stderr; retries after the rate limit |
| 75 | another instance holds the single-instance lock | nothing |

D6. **No GUI session.** If the sampler finds no console user (`stat -f %Su /dev/console` is not the operator), runs on
Linux, has `LW_GUI_HOG=0` set, or cannot find a bundle, it records the decision in the dry-run log (I1) and shows
nothing. The build is never blocked or delayed by a missing GUI. `bg` over SSH still gets the normal admission, and the
valve still fires.

## E. The window

E1. **Header.** "Load 9.8 / 10.4 / 11.2 (10 cores) · CPU 5-min avg 7.9 cores". Below it, one line per held build:
"`bg`, held 4 min for pageins, swapins". The caller label is only what `admit_caller()` gives, a program name from its
`_CALLER_OK` set (`bin/load-watch` ~2541-2580), never a command line. It is untrusted text (J3).

E2. **Rows** (busiest first, up to 12, then "+N more"): name, then bundle id in small type, cores (5-min, e.g. `1.84`),
CPU now (top's units, `184%`) and RAM (`3.1 GB`, RSS sum). Each row's buttons, left to right: **Freeze 10 min**,
**Freeze**, **Quit**, **Force Quit…** (it opens a confirm sheet). A frozen row shows a "frozen until 3:42 PM" badge (or
"frozen") and only **Resume** and **Quit** (Quit resumes first, G3). Protected apps are not listed. A footer line counts
them ("4 protected apps hidden"). An app whose tree contains a build or terminal subtree (C4b), such as an IDE with a
running terminal, is listed greyed out: "has a terminal or build inside: no actions". It has no buttons, and Quit All
skips it, because freezing or quitting the IDE would stop or kill the build.

E3. **Bottom row**, left to right: **Wait** (it closes with no action, and it is the initial first responder), **Ignore
1 h**, **Quit All…**. No button has a key equivalent. The window swallows Return and Escape (`cancelOperation:` and
`performKeyEquivalent:` do nothing). With Full Keyboard Access, Space presses the focused button, and focus starts on
Wait, so a stray key can at most close the window with no action. This is the same reasoning `sudo-ask` records for its
2026-10-10 Enter-hit-Deny incident.

E4. **When nothing is held any more**, the header says "No build is waiting now". The window stays until it is clicked,
but it no longer refreshes rows. **DECIDE E4: close by itself 2 min after the hold ends if no app is frozen?
Recommended: yes**, as anti-nag.

E5. **Frozen-apps indicator.** While the frozen list is non-empty, a menu-bar item (`NSStatusItem`, "❄ 2") stays up
even after the dialog closes. Its menu lists each frozen app with its thaw time, plus Resume, Resume All, and "Show
dialog". The sampler relaunches it, in `--status-only` mode, whenever the list is non-empty and it is not running. It
quits when the list empties. This is the "visible frozen-apps list" of B5(c), and it stays quiet: no pop-ups.

E6. **Window frame.** Titled, closable (the red button is Wait) and miniaturizable (operator ruling 2026-11-14): the yellow button sends the window to the Dock, acts on nothing (no Wait, Ignore, snooze, quit or signal), and a minimized window still refreshes and ticks the thaw clock; the level stays `.floating`. Both the window and the menu-bar item hold a `ProcessInfo` activity (`.userInitiatedAllowingIdleSystemSleep`) while they run, so App Nap cannot slow the refresh or the 20 s thaw clock of a minimized window. A forgotten minimized manual window (`gui-hog show`) keeps `dialog.lock` until someone closes it: the sampler shows no other dialog meanwhile, and a manual window never closes itself.

## F. Freeze safety

F1. **State file.** `~/.local/state/load-watch/gui-hog/frozen.json` (mode 0600), schema v1:

```json
{"v": 1, "entries": [{
  "id": "f-20261114T204201Z-3f9a", "state": "freezing|frozen|thawing",
  "app": {"name": "Slack", "bundle_id": "com.tinyspeck.slackmacgap", "bundle_path": "/Applications/Slack.app"},
  "root": {"pid": 812, "start": "Fri Nov 14 18:02:11 2026", "uid": 502, "exe": "/Applications/Slack.app/Contents/MacOS/Slack"},
  "members": [{"pid": 845, "start": "...", "exe": "..."}],
  "mode": "timed|indefinite", "frozen_at": 1794768121, "thaw_at": 1794768721, "by": "dialog|cli"}]}
```

Writes use the temp file in the same directory, then `fsync`, then `os.replace` (atomic,
`~/CLAUDE.md` item 2). The previous good file is kept as `frozen.json.prev`. Every `freeze`, `resume` and `thaw` holds an
`fcntl.flock` on `frozen.lock` for the **whole operation**: the write-ahead record, the signals and the final rewrite.
A 5 s timeout applies to acquiring the lock. If it times out, no signal is sent and the error is shown in the row.

F2. **Write-ahead.** `freeze` writes the entry as `freezing`, with the root and the members it is about to stop, **before
it sends any SIGSTOP**. After the pass, it rewrites the entry as `frozen`. `resume` marks the entry `thawing`, sends the
SIGCONTs, then deletes the entry. A crash at any point therefore leaves a record that names every process that might be
stopped. Any entry still `freezing` or `thawing` after 60 s is resumed by the next sampler tick.

F3. **Process identity (pid-reuse defence).** A process is identified by four things: pid, start time, uid and
executable path. The executable path comes from the kernel, never from argv[0] or `ps comm`, which a process sets
itself: `proc_pidpath` from `libproc.dylib` through stdlib `ctypes` on macOS, and `/proc/PID/exe` on Linux. Start time
comes from `ps -o lstart= -p PID` under `LC_ALL=C TZ=UTC`, as in `bin/claude_identity.py`
and `bin/ade_install.py:2958`. On Linux CI it comes from `/proc/PID/stat`. Swift reads it with
`proc_pidinfo(PROC_PIDTBSDINFO)` (`pbi_start_tvsec`), the public libproc call that other macOS tools use for the same
check. Before **every** SIGSTOP, SIGCONT, terminate or forceTerminate, all four are re-read and must match. A mismatch
drops that member from the entry, logs it and sends no signal. A process that has exited is also dropped. `ps` reports a
stopped process with state `T`. `resume` checks that each member is still in `T` before it signals, and logs a member
that is no longer stopped, which means something else resumed it.

F4. **Whole-tree freeze and the fork race.** The order is:
(a) list the tree (descendants by ppid, plus processes whose executable sits inside the bundle). The walk stops at build
and terminal subtrees (C4b), and an app that has one is refused outright (E2);
(b) stop the **root first**, so it cannot spawn more helpers;
(c) stop each listed member, after recording it (F2);
(d) list the tree again and stop newcomers, at most 3 passes.
A helper forked by an unstopped child between passes is caught by the next pass. Anything still appearing after pass 3
is logged and left running. **Resume runs in reverse: children first, the root last**, so the browser process's
hang monitor never sees helpers that are still stopped and kills them as hung. XPC services that launchd starts for an
app (ppid 1, for example `com.apple.WebKit.WebContent` for Safari) are not in the tree and keep running. The row says
"some helpers kept running".

F5. **Every thaw path:**
(a) **timed**: the sampler runs `gui-hog thaw --due` **first** on every tick, in its own `try`, before `ps_table()`. A
`ps` timeout makes `cmd_sample` return early (`bin/load-watch` ~1484-1488), and this order keeps a thaw from waiting on
it. A due freeze resumes within one tick. That is normally 20 s, but launchd has run ticks 3-7 min apart under a
load-60 stall (`bin/load-watch` ~1477), so 20 s is not a guarantee. The `--status-only` menu item runs the same check on
its own 20 s timer, which gives two independent clocks. Under a stall, every identity read in a thaw is bounded:
each `ps -o lstart=` call has a 5 s `timeout` (`proc_pidpath` and `/proc` reads do not block), and a thaw pass has a
30 s total budget. Entries left over when the budget runs out wait for the next tick, and they are never signalled
without a completed identity check;
(b) **startup**: the dialog and the status item each run `thaw --due --stale` when they start;
(c) **crash**: (a) and F2 cover it;
(d) **reboot or logout**: the stopped processes are gone. The first tick after login drops every entry whose identity no
longer matches, and logs one line per entry;
(e) **sleep**: `thaw_at` is wall-clock time, so a freeze that came due during sleep resumes on the first tick after
wake;
(f) **load-watch uninstalled**: `load-watch uninstall` runs `gui-hog thaw --all` first, and refuses to go on if that
fails. `ade-sched uninstall` or `reconcile`, or a bare `launchctl bootout`, bypasses this. The status item's timer (a)
and the escape hatch (F7) cover that case. The PR 3c slice also adds the same thaw to `ade-sched`'s removal of this job.

F6. **Protected list.** Built-in defaults live in `config/gui-hog.toml` `[protected]`. Local additions go in
`~/.config/load-watch/gui-hog.toml`, which can **add**, never remove. Matching uses the **live** values (D4) and is by **bundle id**, by **bundle path prefix** or by **executable
realpath**, never by display name, which anyone can set (J3). Prefix matching compares realpath **components**: a rule
for `/Applications/Ghostty.app` matches `/Applications/Ghostty.app/Contents/...` but not `/Applications/Ghostty.app.x/`. A **hard floor** in code that
config cannot lift:
(a) pid 1, and any process whose uid is not the operator's;
(b) WindowServer, Dock (`com.apple.dock`), loginwindow (`com.apple.loginwindow`), Finder (`com.apple.finder`),
SystemUIServer (`com.apple.systemuiserver`), Control Center (`com.apple.controlcenter`), WindowManager
(`com.apple.WindowManager`), anything under `/System/` or `/usr/`;
(c) the dialog itself;
(d) load-watch and `bg`;
(e) every ancestor or descendant of a held caller or of a Paseo agent CLI (the build itself).
The configurable defaults are Paseo (`sh.paseo.desktop`, `sh.paseo.desktop.helper`), terminals (Ghostty, Terminal,
iTerm2, WezTerm, kitty), Hermes, VPN and proxy apps (`io.tailscale.ipn.macsys` was running on 2026-11-14; WireGuard),
Simulator and CoreSimulator (`com.apple.CoreSimulator.CoreSimulatorService` was running on 2026-11-14), IDEs whose
toolchain is inside their bundle (Xcode `com.apple.dt.Xcode`, Android Studio and other JetBrains IDEs that bundle a JDK;
C4b), Docker or container, password managers, and conferencing apps during a call. Bundle ids that were not
seen running get checked against `lsappinfo` or `mdls` when the config is written, so no id is guessed.

F7. **Manual escape hatch.** These do not depend on the dialog:
(a) `bin/gui-hog thaw --all`, which resumes every recorded entry after the identity checks;
(b) `bin/gui-hog frozen`, which lists the entries;
(c) `bin/gui-hog thaw --all --stopped-apps` for a lost or corrupt state file. It lists every process of the operator's
uid that is in state `T` and whose executable sits inside an `.app` bundle, asks for `yes`, then sends SIGCONT. It
cannot tell our freezes from a debugger's, which is why it asks;
(d) the last resort, which needs no tool: `kill -CONT <pid>` for each pid in `frozen.json`.
`gui_hog.py` is stdlib-only and does not import `load-watch`, so a broken `load-watch` cannot block a thaw.

F8. **Failure-mode table.**

| # | Failure | Effect | Defence |
|---|---|---|---|
| 1 | Dialog crashes while apps are frozen | timed apps still due | sampler `thaw --due` (F5a); the status item is relaunched (E5) |
| 2 | Sampler not loaded | timed freezes would not resume | `freeze` refuses unless `launchctl print gui/$(id -u)/com.djbclark.load-watch` shows the job loaded (the uid is read, never hard-coded); the status-item timer is the second clock |
| 3 | Crash between SIGSTOP and the record | an unrecorded stopped process | write-ahead `freezing` entry (F2); swept after 60 s |
| 4 | Pid reused after the app exits | SIGCONT or SIGSTOP hits a stranger | 4-part identity check before every signal (F3) |
| 5 | Reboot or logout | entries point at dead pids | pruned at the first tick (F5d) |
| 6 | A helper forks during the freeze | part of the tree keeps running | root stopped first, then up to 3 passes (F4) |
| 7 | The parent's watchdog kills children on resume | a tab or helper crashes | children resumed first, root last; accepted residual risk |
| 8 | A frozen app holds something the build needs (simulator, container, keychain prompt) | the build stalls | those are on the protected list; the held line names the refusal; one-click Resume |
| 9 | Freezing a system app | WindowServer, Dock or Finder hangs | hard floor (F6) |
| 10 | State file corrupt | entries unknown | `.prev` copy; `thaw --all --stopped-apps` (F7c) |
| 11 | No GUI (SSH, CI, Linux, locked screen) | no dialog | D6: logged; the build is never blocked |
| 12 | Bundle missing or stale | no dialog | D2: logged daily; fail open |
| 13 | Two dialogs | duplicate actions | single-instance `flock` in the dialog (exit 75); the sampler checks its pid file |
| 14 | Frozen app was in a call or playing audio | call drops, audio glitches | conferencing and audio apps are protected by default; Freeze has no confirm because Resume is one lossless click (**DECIDE F8-14: confirm before an indefinite Freeze? Recommended: no**) |
| 15 | Lock timeout or hang | no action | 5 s `flock` timeout; error shown in the row; no signal sent |
| 16 | An agent runs `gui-hog freeze` itself on an unlisted app | breaks "unlisted apps need a click" (B6) | rule in `skills/loadwatch/SKILL.md` and this doc; every event logs `by`; accepted because same-uid processes can already `kill -STOP` (J1) |
| 17 | An IDE (VS Code, JetBrains, Xcode) runs a build in its terminal, through a Gradle daemon, or with an in-bundle toolchain | Freeze or Quit would stop or kill the build; its compiler would count as a GUI hog | the tree walk stops at shells, ptys, `bg`, agent CLIs, reservation holders and out-of-bundle executables (C4b); IDEs with in-bundle toolchains are protected by bundle id (F6); `vet` re-walks the tree live and refuses with exit 5 (D4); such an app is listed without actions and skipped by Quit All (E2, G4) |

F9. **What freezing does not do.** SIGSTOP frees **CPU**, not RAM. A stopped app's pages only go cold, and the
compressor or swap may reclaim them over time. Resuming can then cause a burst of page-ins, which is the very gate that
holds builds today. When the trigger fired on the 2 GB RSS test, the dialog says "Quit frees memory; Freeze frees CPU".
A stopped app also looks hung to macOS (a spinning cursor over its windows, "not responding" in Force Quit). Its network
connections may time out, and its scheduled timers and notifications do not fire. Shiny's write-up, the prior art in L2,
lists the same risks.

## G. Quit, Force Quit and Quit All

G1. **Quit** is `NSRunningApplication.terminate()`. That sends the normal Quit Apple event, so an app with unsaved
documents shows its own save sheet, and nothing is lost. Apple documents that it can return before the app exits, so
the row shows "quitting…" while it watches `isTerminated`. After 30 s it says "still running (it may be asking to
save)". There is no automatic escalation.

G2. **Force Quit** is `forceTerminate()`, the same as Activity Monitor's Force Quit, and unsaved work is lost. It always
opens a **confirm sheet** whose default button is **Cancel** and which names the app and the loss. It is never part of
Quit All. Apple notes both calls fail from a sandboxed app. `ade-gui-hog` is not sandboxed. It is the operator's own
unsigned tool, ad-hoc signed only.

G3. **Quitting a frozen app.** A stopped app cannot answer the Quit event, so Quit runs `resume` first, then
`terminate()`.

G4. **Quit All** calls `terminate()` (graceful) on **only the rows shown** that are not frozen. A confirm sheet lists
them, Cancel is its default, and it never Force Quits. Protected apps are never rows. The build's own tree is never a
row either: a held build's ancestry is excluded, and an app with a build or terminal subtree inside it (an IDE running
`make` in its terminal) is listed without actions and skipped (C4, E2, F6). So Quit All cannot quit an app that hosts a
build. Another app's unsaved state cannot be read without Accessibility permission:
`NSRunningApplication` has no "dirty" property. So the safety comes from graceful terminate's own save sheet, not from
detection. **DECIDE G4: ask for Accessibility permission to pre-detect "Edited" windows? Recommended: no.** It adds a
TCC grant and adds nothing, because graceful quit already protects unsaved work.

## H. Testing without a GUI

H1. **Linux CI (pytest-linux, the required check) covers all Python:**
(a) `should_show` as a table test: hold time, which gates refused, sum versus threshold, rate limit, snooze, the
non-build exclusion;
(b) app grouping from fixture `ps` and `lsappinfo` text, with three fixtures: an IDE whose terminal runs `make`, an
IDE-started Gradle daemon (a JDK `java` outside the bundle with no shell above it), and Xcode with `swift-frontend`
children. In each, the build's cores are not counted, and the app is listed without actions or is protected;
(c) protected matching, including a spoofed display name, a config that tries to remove a hard-floor entry, and a
bundle-path prefix;
(d) the frozen-list state machine (freezing, frozen, thawing, gone), driven by a fake clock and a temp state directory;
(e) identity mismatch for each of the four fields;
(f) the hold registry's write, sweep and stale rules in `admit`, plus a test that a broken `gui_hog` import or a failing
write leaves `admit`'s verdict and exit code unchanged;
(g) `vet` and `freeze` refusing when the argv's expected bundle id or path differs from the live values.
H1a. **Real signals on Linux.** The freeze tests start a throwaway `sleep` parent with two children and SIGSTOP and
SIGCONT them for real: Linux `ps` state `T`, and `/proc` start times. That proves the tree order, the 3-pass rescan and
the write-ahead recovery with no Mac. They run as `bg bin/pytest -k gui_hog`, one tree at a time (footer rule 16). New
tests get mutation checks.

H2. **macOS-only Python paths** (`lsappinfo` parsing on a live table, `launchctl print` precheck, `ps -o lstart`): one
smoke test marked `macos` that is skipped on Linux, run locally through `bg` and on macOS CI only by dispatch.

H3. **Swift.** `swiftc -typecheck` and `ade-gui-hog --self-test` run under `bg` on the Mac. The self-test is pure logic
with no window: snapshot JSON parsing, number formatting, sanitising untrusted names, and the button-to-argv table. The
macOS CI leg runs them only when it is dispatched with `macos=true`, and PR checks get no macOS leg (`~/CLAUDE.md`
item 37).

H4. **Manual acceptance checklist (the operator, once per GUI PR):**
(a) `bin/gui-hog demo` shows the window from a fixture snapshot without a real hold;
(b) Return, Escape and Space-on-Wait take no action;
(c) Ignore suppresses the dialog for 60 min (check `snooze_until`);
(d) Quit on an app with an unsaved document shows that app's own save sheet (not TextEdit: it lives under /System/Applications, so the hard floor protects it and it is never listed);
(e) Force Quit opens a confirm sheet whose default is Cancel;
(f) Freeze 10 min on a test app: `ps` shows `T` for its tree, the menu-bar item appears, and the app resumes by itself
within 20 s of its time;
(g) killing the dialog with `kill -9` while an app is frozen: the sampler resumes the app when it is due;
(h) a protected app (Ghostty) never appears as a row;
(i) the window does not appear over SSH with no console user.
**DECIDE H4: add an offscreen `--render-png` mode later, for agent-checked layout? Recommended: not in PR 3**, because it
still needs the Aqua session.

## I. Phasing

I1. **PR 3a: data and trigger, no window. DONE 2026-11-14 (section M).** The hold registry in `admit` (C2), the always-on app window in the sampler
(C3), `gui_hog.py` with `should_show`, grouping and the protected list, and `gui-hog status`. The trigger logs "would show
dialog: …" to `~/.local/state/load-watch/gui-hog/dry-run.jsonl`, and `load-watch admit-log summary` gains a count of
those lines. The value: one week of evidence on how often the dialog would nag, before it exists. The tests are H1 (a),
(b), (c) and (f). Rollback: `LW_GUI_HOG=0` turns the trigger off; reverting the PR removes the held directory writer.

I2. **PR 3b: read-only and quit dialog. BUILT 2026-11-14 (section N).** `macos/gui-hog/`, `bin/ade-gui-build` and the `ade update` hook (D2), the
window (E1–E4), and Wait, Ignore, Quit, Force Quit with confirm, and Quit All with confirm. No Freeze buttons yet. The
trigger switches from dry-run to live. It also updates `docs/threat-model.md` (J5). Tests: H3 and H4 (a) through (e),
(h) and (i). Rollback: delete the bundle (fail open, D2) or set `LW_GUI_HOG=0`.

I3. **PR 3c: Freeze.** `frozen.json` with the lock and the write-ahead (F1, F2), the identity checks (F3), the tree freeze
(F4), every thaw path (F5), the escape hatch (F7), the menu-bar item (E5), the uninstall thaw, and the row buttons.
Tests: H1 (d) and (e), H1a, H4 (f) and (g). Rollback: `gui-hog thaw --all`, then `[freeze] enabled = false` in
`config/gui-hog.toml`, which hides the buttons, then revert.

I4. Each PR gets an `adversary` verdict on its exact head and a `changelog.d` fragment. 3b and 3c each need the operator's
H4 run before merge.

## J. Security and threat notes (for `docs/threat-model.md`)

J1. **Who can invoke it.** Any process running as the operator (uid 502) can run `bin/gui-hog freeze` or launch the
dialog. That gives nothing new: the same uid can already `kill -STOP` or `kill -9` its own processes. There is no
setuid, no sudo, no root helper and no listening socket. Processes of other uids are refused before any signal
(F6a), and the kernel would refuse them anyway (`EPERM`). Agents are trusted peers here (AGENTS.md Trust). "Unlisted apps need a click" (B6) is a rule plus an audit trail (`by`, `events.jsonl`), not a boundary.

J2. **No shell anywhere.** Swift uses `Process` with an `arguments` array. Python uses `subprocess` argv lists. No
`osascript` is used, and no name, bundle id or path is ever put into a command string.

J3. **Untrusted display text.** An app sets its own name, so names, bundle ids and caller labels are untrusted. They are
set as plain `NSTextField.stringValue` (never attributed or HTML), stripped of C0 and C1 control characters, bidi and
zero-width marks (U+061C, U+200B–U+200F, U+202A–U+202E, U+2066–U+2069) and line or paragraph separators (U+2028,
U+2029), and clipped to 60 grapheme clusters, never in the middle of one. Identity and protection never use the name. An app that
*claims* a protected bundle id becomes protected, which is the safe direction. A path match needs the realpath.

J4. **The snapshot is data.** The dialog never signals or quits anything because the snapshot says so. Every action
re-checks identity live (F3) and re-runs `vet` against the protected list, so a tampered snapshot can at worst show
wrong rows. The files are mode 0600 in the operator's state directory.

J5. **Threat-model entry.** PR 3b adds entry point "(f) `ade-gui-hog` plus `bin/gui-hog`: an operator-clicked local
window that can quit, force-quit or SIGSTOP same-uid GUI apps", with J1–J4 as its controls. It also adds a ranked
threat: a stuck freeze that stops a security or VPN app (control: F6 floor and defaults, F5 thaw paths, F7 escape
hatch).

## K. Open decisions (summary)

K1. C6: the trigger lives in the sampler, not in `bg` or `admit`. **Recommended.**

K2. C7: the thresholds are a sum over non-build apps. **Recommended.**

K3. D1: thin Swift view plus a stdlib-Python core. **Recommended.**

K4. E4: the window closes by itself 2 min after the hold ends if nothing is frozen. **Recommended.**

K5. F8-14: no confirm before Freeze, timed or indefinite. **Recommended**, as one-click Resume is lossless.

K6. G4: no Accessibility permission for detecting unsaved documents. **Recommended.**

K7. H4: no offscreen PNG render in PR 3. **Recommended.**

## L. Prior art and docs checked (2026-11-14, shared `mcp__firecrawl__*`)

L1. Apple, `NSRunningApplication.terminate()` and `forceTerminate()`
([terminate](https://developer.apple.com/documentation/appkit/nsrunningapplication/terminate%28%29),
[forceTerminate](https://developer.apple.com/documentation/appkit/nsrunningapplication/forceterminate())). Both can
return before the app exits (observe `isTerminated`). Both return false from a sandboxed caller.

L2. Shiny, ["The honest engineering of pausing background apps on macOS"](https://www.theodorehq.com/shiny/blog/pausing-background-apps)
(2026-04-29): SIGSTOP and SIGCONT preserve state. Risks: a stop in the middle of a write, delayed sync, missed timers
and notifications, audio and recording apps, system daemons. Mitigations: idle checks, exclusion lists, user apps only.
Shiny freezes automatically; we do not.

L3. Graceful versus forced quit in other tools ([tinycast launcher](https://github.com/conversun/tinycast-cn/blob/main/docs/features/launcher.md),
[openmacbattery](https://github.com/MuratDugan/openmacbattery)): the graceful `terminate()` keeps the app's own save
sheet; `forceTerminate()` can lose unsaved work. This matches G1 and G2.

L4. Pid-plus-start-time identity through `proc_pidinfo(PROC_PIDTBSDINFO)` `pbi_start_tvsec`: the public libproc API,
used for exactly this check ([memory_pilot audit](https://github.com/quangdang46/memory_pilot/blob/a8fe82a302fed144b9aa9ab27d0763b5c6022e30/docs/01-research/reference-audit-process-triage.md),
[btclib ai-agents-process PR 290](https://github.com/btclib-org/ai-agents-process/pull/290)). It matches F3.

L5. App Tamer 3 is in beta (St. Clair Software, r/macapps 2026-04). Our own A/B (2026-10-24) is the evidence against
automatic throttling. The `app-pauser` repository (an automatic SIGSTOP pauser) returned 404 when fetched on
2026-11-14, so it was not used.

## M. PR 3a as built (2026-11-14)

M1. **What shipped.** `bin/gui_hog.py` (stdlib; `load-watch` imports it lazily inside a `try`), `bin/gui-hog status [--json]`, `config/gui-hog.toml`,
the hold registry in `admit --wait` (C2), the always-on app window in the sampler (C3), the decision `should_show` (C4), and the dry-run log
`~/.local/state/load-watch/gui-hog/dry-run.jsonl` (I1). `load-watch admit-log summary` prints `gui-hog dry-run: N would-show lines in the last D days`.
`LW_GUI_HOG=0` removes the app window and the trigger (the hold files keep being written: they are only data). Nothing is signalled, quit or frozen, and no window exists.
Tests: `tests/test_gui_hog.py` (H1 a, b, c, f), fixture `tests/fixtures/gui_hog/lsappinfo.txt`.

M2. **Where it departs from the text above (all conservative).**
(a) The trigger decision is made in the sampler (K1) and the dry-run uses the **real** rate limit (`gui_hog.last_shown` in `state.json`) and the real snooze file,
so the count is how often the dialog would have shown, not how often its conditions held.
(b) Stop kind (4) of C4b, "a process holding an admit reservation", cannot be built: `agent-reservations.json` stores ids and expiry times, no pid. Held callers
(their pid, from the hold files) and agent-CLI or `bg` ancestors cover the same builds.
(c) `ps_table` gained the `tty=` column (`PTTY`, the pids with a controlling terminal), for the pty stop of C4b.
(d) An app's id in 3a is its root pid (no start time yet); 3b's snapshot adds the root start for the identity checks of F3.
(e) An app that hosts a build still counts toward the threshold **without** the build's cores (C4b says the subtree never counts towards the app); it is flagged
`hosts_build` and a later PR lists it without actions. A **protected** app, or one whose ancestry reaches a held caller or an agent CLI, never counts.
(f) The registry's `refused_since` goes through `parse_refused_since`; with `LW_STARVE_REFUSED_SINCE_MAX_S=0` (no credit for the valve) the registry uses the 3600 s default
cap, so turning the valve credit off never turns the trigger off. `read_holds` clamps the age again when it reads, and ignores a non-integer or future value.
(g) A hold file is stale after max(60 s, 2 polls + 15 s) without a refresh, or when its pid no longer has the recorded start time. The sampler sweeps; `gui-hog status` only reads.
(h) A helper's own `lsappinfo` entry (a Chrome or Slack helper `.app` inside the main bundle, or a second entry for the same bundle whose parent is already a root) is folded into
the outer app. If `lsappinfo` prints nothing parseable, apps come from the kernel executable path (`proc_pidpath` through `ctypes` on macOS, `/proc/PID/exe` on Linux) and the
bundle's `Info.plist`.
(i) The window stores an app at a sample when it uses 0.02 cores or holds 50 MB; smaller ones are dropped (they cannot reach a threshold unless there are dozens).
(j) The kernel executable path is also read for every process that could be a helper (`.app/` in its command): the pre-filter reads argv, so a process that hides `.app/`
from its command line can only be missed, never wrongly counted.
(k) Protected defaults are by bundle id or path where an app is installed (checked 2026-11-14 against `Info.plist` and `lsappinfo`): Paseo, Ghostty, Terminal, iTerm2, both Hermes apps,
Tailscale, CoreSimulator, Xcode, Android Studio, 1Password, Zoom, Tart and the Virtualization host; JetBrains by the `com.jetbrains.` namespace; apps that are not installed
(WezTerm, kitty, WireGuard, Docker, OrbStack, Simulator) by bundle path, never a guessed id.

(l) Hardening after the adversary's first review (2026-11-14). Every file the sampler or `admit` reads from `held/` and `gui-hog/` is opened with `O_NOFOLLOW|O_NONBLOCK`, must be a regular
file under a size cap, and sits in a real directory owned by this user (a FIFO or symlink there can no longer hang `admit` or the sampler, and the sweep never follows a symlinked directory);
a hold's pid is bounded, its `updated` must be finite and not in the future, and a failed `ps` start-time read is not pid reuse unless the process is also gone. `clean` drops every
control, format, surrogate, private-use and unassigned code point plus the invisible filler letters. Agent CLIs are recognised by their argv heads (`node /x/claude`, a version-named
binary), not only the kernel exe. A process running an app's own in-bundle binary under a shell, pty, held caller or agent CLI (headless Chrome under a test run) is a build, not the app.
A hold also records the caller's pid (`LW_ADMIT_CALLER_PID`, else the parent), so an app started under the real caller is excluded. Corrupt `state.json` sections heal on the next tick; a snooze
never outlasts `snooze_s` and a `last_shown` in the future is ignored. Round 2 added: variation selectors and a few more invisible fillers are dropped by `clean`; a window entry without a sample dict is dropped; a non-ASCII digit in `LW_ADMIT_CALLER_PID` is ignored.

M3. **Measured 2026-11-14 (M1 Pro, 10 cores).** `lsappinfo list` takes about 0.2 s of wall time with no CPU to speak of; a full `load-watch sample` ran in 0.65 s at load 57.
`state.json` with the app window was 4 KB with 8 apps stored.

M4. **Prior art checked (2026-11-14).** See section L (the starting point) and the report of this PR for the `lsappinfo` output-format and macOS process-group CPU accounting searches.

## N. PR 3b as built (2026-11-14)

N1. **What shipped.** `macos/gui-hog/` (`main.swift` entry, lock and exit codes; `Model.swift` pure logic; `Actions.swift` the `Process` calls and `NSRunningApplication`; `UI.swift` the
window; `SelfTest.swift`; `Info.plist`, bundle id `com.djbclark.ade.gui-hog`, `LSUIElement`), `bin/ade-gui-build` (D2; `--if-stale`, `--force`, `--status`, `--check`, `--self-test`, `--dest`),
step 3b of `bin/ade-update` (fails open), the sampler's live launch (`gui_hog.tick(launch=True)`), `gui-hog` subcommands `vet`, `snooze`, `record-exit`, `log`, `show [--all]`, `demo`, and
the dialog's snapshot (`gui-hog/snapshot.json`, D3). Buttons: per row **Quit** and **Force Quit…** (confirm sheet, default Cancel); bottom **Wait** (leftmost, initial first responder, only
closes; Return, keypad Enter and Escape are swallowed; no key equivalents), **Ignore 1 h**, **Quit All…** (confirm sheet, default Cancel; graceful only). No Freeze (3c): rows carry
`frozen: false` and the row builder is one function (`UI.swift` `rebuild`) where 3c adds buttons.

N2. **The quit sequence (D4, carry-over e).** `vet` (Python, live: identity by pid plus start time, bundle id and bundle path from the live executable; protected list by LIVE values; the C4b
build-subtree walk re-run now; exit 0 / 3 protected or part of a build / 4 identity changed / 5 hosts a build or terminal / 6 gone or `ps` failed) -> in Swift `NSRunningApplication(pid)` plus
`proc_pidinfo(PROC_PIDTBSDINFO).pbi_start_tvsec` against the snapshot's `root_start_epoch`, the bundle id and the launch date (`identityMatches`; a nil launch date or unknown start refuses) ->
`terminate()` or `forceTerminate()`. The row's `present` flag (in the newest sample) gates the buttons: an app that uses nothing also reads 0 MB, so `rss_mb == 0` is no sign of absence
(carry-over d).

N3. **Departures from the text above (all conservative).** (a) The snapshot row has no `members` count (the 300 s window does not store it); D3's list is otherwise followed, plus `present`,
`cpu_now`, `root_start_epoch`. (b) The launch date may differ from the process start by 3 s, not 1 s (D4 says one second): measured 2026-11-14 on 26 running apps, `launchDate - pbi_start_tvsec`
ranged from -0.003 s to +0.94 s, which is too close to 1 s for comfort; the pid start time, which is the strong check, keeps its one-second tolerance. (c) The dialog records its exit through
`gui-hog record-exit` (stdlib Python writes the file with a unique temp name) rather than writing JSON from Swift. (d) E4 is implemented in the dialog: it closes 2 minutes after the
snapshot shows no hold (K4); `--manual` (`gui-hog show`) and `--demo` never auto-close. (e) `gui-hog show` and `demo` are new (H4a needs a window without a hold; the operator's real-app
checks need real rows). While a `show` window is open the sampler leaves its snapshot alone. (f) K8 (JetBrains and Xcode-class apps listed with no actions): there is no K8 in this
document; those IDEs are protected by default (F6) and hidden, so nothing was built (the hosts-build row note covers an unprotected IDE). (g) A launch date tolerance and the
`launch` field of the dry-run line (`started`, `bundle-missing`, `bundle-stale`, `running`, `no-gui`, `off`) are new. (h) `tick` takes `launch=False` by default: only the sampler passes
`True`, so no test or `--dry-run` sample can start a window.

N4. **Carry-overs folded from the PR 3a reviews.** (a) `status` formats RSS as an int and `window_means` coerces it. (b) `argv_head_words` skips leading option words (a space-separated option
value is still taken for the script word, as in load-watch's own `cli_heads`). (c) a hold with pid 1 is refused (`1 < pid`). (d) `present`. (e) identity re-check before every signal
(N2). (f) `.hold-*.tmp` files older than 2 min are swept. (g) one `ps -o pid=,lstart= -p a,b,c` call per `read_holds`. (h) `gui/$(id -u)` in this document; nothing else in 3b hard-codes the uid.

N5. **Rollback.** Turn the trigger off: `launchctl setenv LW_GUI_HOG 0` (the next 20 s tick; undo with `launchctl unsetenv LW_GUI_HOG`). Remove the dialog: `rm -rf ~/.local/libexec/djbclark-ade/"ADE GUI Hog.app"`
(the sampler then logs `bundle-missing` once a day and shows nothing; `ADE_GUI_BUILD=0` stops `ade update` from rebuilding it). Reverting the PR removes the code.

N6. **The operator's H4 run (NOT DONE; 3b must not merge without it).** Use a scratch bundle so the live install is untouched: `cd /Users/djbclark/src/djbclark-ade-gui3b-wt`,
`export LW_GUI_HOG_BUNDLE="$HOME/gui-hog-test/ADE GUI Hog.app"`, `bin/ade-gui-build --force`, then in the same shell:
(a) `bin/gui-hog demo`: a window with the header `Load 9.8 / 10.4 / 11.2 (10 cores) · CPU 5-min avg 7.9 cores`, an orange DEMO line, `bg, held 4 min for pageins, swapins`, four made-up rows (the
second greyed with "has a terminal or build inside: no actions", the fourth "no longer running" and its name shown without the control and bidi characters), `+3 more · 4 protected apps hidden`; Quit on a
row says "demo: nothing was touched". (b) Press Return, keypad Enter and Escape: nothing happens. Wait is the only control that takes keyboard focus (round 1, N7): press Tab, then Space: the window closes (or click Wait); no other control ever shows a focus ring:
exit 0, `cat ~/.local/state/load-watch/gui-hog/last-exit.json` is not written by demo. (c) Ignore needs a real window: `bin/gui-hog status` (sampler running), then `bin/gui-hog show --all`, click
Ignore 1 h: the window closes; `cat ~/.local/state/load-watch/gui-hog/snooze.json` has `snooze_until` about an hour ahead and `last-exit.json` has code 3. (d) Open a harmless third-party app (Syncthing's tray app, Contexts; never a VPN, password manager, terminal or Quicksilver; TextEdit is protected by the hard floor and never listed),
let the sampler see it (a few ticks), `bin/gui-hog show --all`, click Quit on it: the app quits politely (an app with an unsaved document shows its own save sheet and nothing is lost); a row appears only if the sampler saw it.
(e) Click Force Quit… on any harmless app: a sheet naming the app and the loss, **Cancel highlighted**; Return and Escape both cancel; the app keeps running. (h) Ghostty (protected) never appears as a
row; the footer counts it under "N protected apps hidden". (i) The window is shown only by the sampler when the operator owns `/dev/console` (tested by `gui_ok=False` in pytest); over SSH from another
machine `bin/gui-hog show` has no window server: check that it does not hang and `last-exit.json` reads code 69. Rollback after the run: `unset LW_GUI_HOG_BUNDLE; rm -rf ~/gui-hog-test`.

N7. **Adversary round 1 (head f3abd9cd, BLOCK; repaired).** (a) *Medium: a click could land on another app.* The window re-sorted its rows on every 20 s snapshot and kept the bottom-left corner on a
resize, so a row could slide under the pointer. Now `mergeRows` keeps the first-seen order (a row that leaves the snapshot stays, marked "no longer running", with no actions; a new app is appended at the
bottom; 30 rows at most), a resize keeps the top-left corner, and a click within 0.7 s of a re-layout is ignored (`clickAllowed`; Wait is exempt). (b) *Medium: Tab then Space could press Ignore or a row's Quit* (Full Keyboard Access is on
on this Mac). Every button except Wait now has `refusesFirstResponder`; the sampler's window is shown with `orderFrontRegardless()` and does not activate the app, so it cannot take typed keys from another
program (only the operator's own `show` and `demo` activate). A click still works and activates it. (c) *Low, fixed:* `dialog.log` opens `O_NONBLOCK` and must be a regular file (else `launch` reads `log-unsafe`);
`last_shown` is set before the launch and the log line; option values are passed as `--app=NAME` so a name starting with `-` still logs; the stored bundle path is clipped at 200, not 120 (a longer one made `vet` refuse the
app); the vet timeout is 45 s (ps 15 s + lsappinfo 5 s + ps 2 s + start-up). (d) *Low, accepted and documented:* between `vet`'s live process walk and `terminate()` (seconds under load) a terminal or build started
inside the app is not seen again by the Swift re-check (which covers pid, start time, bundle id, launch date, not children); a Force Quit in that window kills it. The operator clicked on a named app and
confirmed; the window is short. (e) *Low, not changed:* the window keeps refreshing numbers after the hold ends (until it closes itself 2 min later, E4), which is harmless.

N8. **Adversary round 2 (head b243c9dc, BLOCK; repaired).** (a) *Medium: the rows still moved when a second build was held,* because the hold lines sat above them (the N7(a) wording "the rows above never
move" was too strong). Now one fixed header line sits above the rows; every row is a fixed 36 pt tall; the hold lines, the notice and the footer sit below the rows; the note and status labels have a fixed
width, so the window width never changes (a sheet no longer re-centres under the pointer). (b) *Low, fixed:* at the cap (16 rows, so the bottom buttons stay on screen) a new app takes the slot of an absent
row, else it is not shown; no row is removed from the middle. (c) *Low, fixed:* both confirm sheets set `buttons[1].refusesFirstResponder` and an initial first responder on Cancel, so Tab then Space cannot press
Force Quit or Quit N; add to N6(e): press Tab then Space in the sheet: it cancels. (d) *Low, kept on purpose:* the first click on the sampler's window only activates the app (the window never took focus, N7(b)),
which also protects a click aimed at another window that the dialog appears over; click again. Check in N6 that a click on Wait works within two clicks and that a window shown under the pointer does not act on
the first click. (e) *Info:* `mergeRows` matches by id and pid, not start time; the row shows what `vet` would check anyway.

N9. **Adversary round 3 (head 1c97da60, BLOCK; repaired).** (a) *Medium: a new app could take a running app's button position in one refresh.* At the cap a slot is now reused only if it was already absent in the
previous merge, never in the same merge that marks its row absent (the new app waits one refresh, 20 s). (b) *Low, fixed:* the root width is a required constraint (1010 pt, rows about 951 pt), so the main window
never changes width and a sheet never re-centres; each row clips to its 36 pt and has the lowest vertical clipping resistance, so an app name in a tall-fonted script cannot push or paint over a neighbour.
(c) *Info:* an app that only dropped out of the busiest-12 list shows "no longer running", as for one that quit; 16 rows plus 8 hold lines can be tall, and the red close button acts as Wait.

## O. PR 3c as built (2026-11-14)

O1. **What shipped (Python).** `bin/gui_hog_freeze.py` (stdlib; it imports `gui_hog`, never `load-watch`) and the CLI `gui-hog freeze | resume | thaw | frozen`
(`bin/gui-hog`). Freeze (F1-F4): `vet_app` re-reads the **live** pid (start time, uid, kernel executable, bundle id and path from the executable's `.app` and its
`Info.plist`; the argv values are only expected values, a difference is exit 4), applies the protected list (F6) to the root **and every member**, refuses an app that hosts a
build or terminal (exit 5), an app under a held caller or agent CLI (exit 3), and the tool's own process and ancestors (exit 3). `freeze` takes `frozen.lock`, writes the entry
as `freezing` (root and every member) **before the first SIGSTOP**, stops the root first, then the members, rescans up to 3 times (a newcomer is written into the entry
before it is stopped; a protected newcomer or a new build subtree rolls the whole freeze back), then writes `frozen`. A failed signal rolls back what was stopped.
Thaw (F5, F7): `thaw_due` (timed due, orphaned `freezing`/`thawing`, and a prune of entries whose processes are gone or changed: a reboot, an exit), `resume --entry|--all`,
`thaw --all`, `thaw --all --stopped-apps` (asks for `yes`; `--yes` skips it), the sampler's tick (it runs `thaw_due` **first**, before `ps_table`, in its own `try`, even
with `LW_GUI_HOG=0`) and the removal of load-watch's job (`ade_sched.thaw_gui_hog_before_removal`, in `uninstall` and `remove_launchd_locked`; a failure refuses the removal).
Resume order is children first, the root last (F4). `config/gui-hog.toml [freeze]`: `enabled`, `default_minutes` 10, `max_minutes` 1440, `passes` 3, `lock_timeout_s` 5.
`enabled = false` refuses `freeze` (exit 6) and leaves every thaw path working. Exit codes: 0 ok, 2 usage, 3 protected, 4 identity, 5 hosts a build, 6 disabled, 7 lock
timeout, 8 sampler job not loaded (F8-2), 9 refused (state unusable, already frozen or stopped, a signal failed).

O2. **Where it departs from the text above (all conservative).**
(a) An orphaned `freezing` or `thawing` entry is resumed **at once** under the lock, not after 60 s: a live operation holds the lock for its whole run, so an entry seen
under the lock is the leftover of a crashed one. `thaw --stale` is accepted and always on.
(b) A pid is only ever signalled when the entry's **four** fields match the live process (F3); SIGCONT also needs state `T` ("not-stopped" is logged, no signal), and SIGSTOP refuses a process
already stopped by someone else. An entry's pid must be an int in 2..2**31-1 (0 and -1 are process groups to `kill`), its timed `thaw_at` is clamped to 24 h after `frozen_at`.
(c) The state directory is opened through directory fds with `O_NOFOLLOW` and owner and mode checks: a symlinked `state_dir`, `gui-hog` or state file is refused (exit 9), never
followed; writes use a unique temp name and `os.replace`, never a write through a link (a symlinked `frozen.json` with no usable `.prev` is unreadable, so `freeze` refuses before it writes). `gui-hog/` must be mode 0700-like (no group or world write);
its parent only not world-writable. A corrupt `frozen.json` falls back to `frozen.json.prev`; with neither usable, `freeze` and `thaw --all` refuse and the message names
`thaw --all --stopped-apps`.
(d) Members are listed parents before children (sorted by depth, then pid), so the reverse order is always children first. A partly finished thaw keeps only the unfinished
processes, the last of them taking the root's place.
(e) `group_apps` gained the additive key `member_pids`. `vet`, as a separate subcommand for Quit and Force Quit, is PR 3b's: `freeze` runs the same checks itself (D4).
(f) Every event (`freeze`, `thaw`, `drop`, `refuse`, `not-stopped`, `exe-changed`, `late-helpers`) goes to `gui-hog/events.jsonl` (0600, rotated at 1 MB) with `by`: `dialog`, `cli`, `sampler`,
`uninstall`, `recovery` or `menubar`.
(g) **After the first adversary round (2026-11-14):** SIGCONT needs pid, start time, uid and state T but **not** the executable path (a bundle replaced or moved while frozen, an update or the Trash, must never leave
the app stopped; the event `exe-changed` is logged); SIGSTOP still needs all four. A root that is gone or changed does not delete the entry: the entry is resumed (each member that is still the recorded process gets SIGCONT)
and counts as `dropped` only when nothing could be signalled. `thaw --all --stopped-apps` also lists stopped processes whose path is unreadable. A full or read-only disk never blocks a resume (the signals go out first; the CLI turns any
`OSError` into exit 9). `gui-hog freeze` rolls back on SIGTERM (the dialog's timeout is 120 s; a timeout reads "no answer in time: check the Frozen list"). A second instance of the same bundle (a member with the root's own
executable) and a launchd-started helper that hosts a shell (`group_apps` now walks the subtree under such a helper) both refuse the freeze with exit 5. A `frozen_at` in the future (a wrong clock, a hand edit) counts as due.
Entry ids start with a letter or digit, and the Swift side passes `--entry=ID`. The dialog (at start) and the menu-bar item (at start and every 20 s) run `gui-hog thaw --due --stale` themselves: the second clock of F5a, b, f.
(h) **Known limits, deferred on purpose:** a thaw runs one `ps -p` per process (a 80-helper browser under a multi-second `ps` stall can span several ticks; resume order stays children first); a freeze clicked in the
milliseconds between `ade_sched uninstall`'s thaw and its bootout is resumed by `gui-hog thaw --all` (and by the menu-bar item's clock, but only when the sampler started the item before it went away: nothing else starts it).
(i) **Round 2 (APPROVE at 4ce980ca, five lows):** fixed: a build-stop child already seen by the outer loop still sets `hosts_build` (ps order); the frozen list keeps a replaced bundle "alive"; a `ps` killed by a signal is an error (never an empty answer); the Swift timeout is carried in the result (no shared flag); code 5 shows the reason. Left open on purpose: a SIGTERM that lands inside `load_entries` (a broad `except` can swallow the handler's exception there; only an external SIGTERM in the first seconds, the dialog's 120 s timeout cannot reach it) — `gui-hog thaw --all --stopped-apps` still finds such an app (the Frozen list does not: its entry is gone).

(j) **Round 4 (APPROVE at d1fa1a44 after the 3b merge; two lows, fixed).** After a successful Freeze the row is marked frozen at once (it no longer waits for the Frozen-list poll), so Quit, Force Quit and Freeze vanish immediately; the freeze command joins each value to its option (`--bundle-id=-y` works); Resume has the same click-grace guard as the other buttons. Not fixed on purpose: `gui_hog.vet` (the Quit path) does not read `frozen.json` (a Force Quit on a stopped app SIGKILLs only that root and the next tick resumes the helpers). The window is now 1190 pt wide with a 1158 pt row area (3b: 1010 and 951 in N9 (b)) to fit the Freeze buttons; the separators use the row-area width. Folded in from 3b's deferred round-4 LOW (operator, 2026-11-14): at the 16-row cap a free slot must be absent in `old` AND still absent after the merge, so an app that returns in the same refresh keeps its slot and a new app does not overwrite it (self-test case "an absent app that returns keeps its slot").

(k) **Operator H4 run, 2026-11-14 (a real Freeze worked): the resume time is a clock time.** The frozen line used to read "resumes in 10 min" and never counted down. It now reads "resumes at 9:52 PM" in America/New_York, 12-hour AM/PM, with a 3-letter day name when the time is not today ("resumes at Sat 9:52 PM"); an indefinite freeze reads "until you Resume". The text depends on the entry's due time only, so there is no per-second redraw; the menu-bar item uses the same `thawText`, and `gui-hog frozen` prints the same clock time (`gui_hog_freeze.clock_text`; a zone that cannot load falls back to UTC, marked). Both formatters take the zone as an argument and are tested with it. The Freeze N min button label is unchanged. Left open (cosmetic): the dialog's own process can show in the app list under another app's helper name (e.g. `QuickLookUIService (DocumentPopoverViewService (TextEdit))` for `com.djbclark.ade.gui-hog`); it is excluded by its exe name regardless.

(l) **Operator H4 run, 2026-11-14: a timed freeze that nothing resumed (fixed).** A dialog opened by hand (`gui-hog show --all`) froze Syncthing for 10 min; the sampler in that test was master's 3b load-watch (no `thaw --due` tick) and nobody had started a menu-bar item, so after 20 minutes the process was still stopped until `gui-hog thaw --all`. Cause: the dialog ran `thaw --due` once at start (F5b) and had no clock of its own, and the only thing that started the menu-bar item (the second clock, F5a) was the new sampler's tick (O2 h named this gap as accepted; the run showed it is reachable). Fix: (1) `gui-hog freeze` itself starts the menu-bar item after every successful freeze (`ensure_status_item`, one instance by its flock, never fails the freeze; the JSON reports `status_item`), so a freeze has its own 20 s clock whoever opened the dialog and whichever load-watch is loaded; (2) the open dialog re-runs `thaw --due` every 10th 2 s tick (`thawDueTick`). With the merged load-watch the sampler's tick is a third clock. Worst case after the fix: a sampler that has no thaw tick (an old one), no menu-bar item (no GUI session, or a missing or stale bundle) and no open dialog: a timed freeze then stays stopped until someone runs `gui-hog thaw --all` or presses Resume (a freeze needs a loaded sampler, exit 8, so an unloaded one cannot happen). With a GUI session and a good bundle the item resumes it within about 20 s of the due time (longer only under the load stall F5a describes). **The same run, the window's view:** a manual window (`gui-hog show`) is a one-shot snapshot by design (3b: the sampler leaves a manual snapshot alone for 30 min so a test on a small app is not overwritten), so its rows and header Load do not refresh; the Frozen list does (every 2 s, from `gui-hog frozen`) and the window now ticks the thaw clock (above). The row label "frozen" set by a Freeze click used to stay forever; it is now dropped when the app is no longer frozen (`clearStaleFrozen`). A click on a stale row is safe because the Python core decides on live data: a Freeze click re-reads start time, uid, exe, bundle and the protected list, refuses a root that already has an entry (9) or is already stopped, and on a running, unfrozen app simply freezes it again (that is what the click asks for).

O3. **Tests (H1 d, e, g, H1a, H4 f and g, Python side).** `tests/test_gui_hog_freeze.py`: the state machine on a fake clock and fake process table, the four identity fields, a reused pid,
protected root and protected member, hard-floor names, a crash at each signal, a crash while thawing, a hand-edited `frozen.json`, symlinked directories and files, the lock, disabled,
sampler-not-loaded, the rescan limit, the sampler and uninstall wiring, and **real** SIGSTOP/SIGCONT on disposable trees the test starts itself (a copy of `dash` with two `sleep` helpers
inside a fake `.app`; macOS needs `codesign --force -s -` on the copies, the fixture does it). Mutation checks (2026-11-14, one mutant at a time): `mismatch` always None, exe not compared,
start not compared, no protected check on members, the write-ahead saved after the first signal, SIGCONT without the stopped check, a pid guard that accepts 0, a followed symlink, and
the resume order reversed: all nine killed.

O3a. **Prior art checked (2026-11-14, shared `mcp__firecrawl__*`, section L is the starting point).** Searches: SIGSTOP/SIGCONT of a macOS app's process tree with Chrome/Electron helpers and App Nap, Chromium's hang and stall handling after a stopped process resumes, and a developer-index search for process suspend tools. The web search returned mostly generic pages. The developer index found Procopticon's `suspend` (it filters out its own process, which F6's own-ancestor refusal matches) and macOS-only SIGSTOP/SIGCONT wrappers in microsoft/ox-tools PR 332. Chromium's stability notes (`docs/stability.md`) describe hung or unresponsive renderers as the browser's to detect, which is why the resume order is children first, the root last (F4). No tool was found that combines a write-ahead record, a four-field identity check and a thaw on every path, so the design stands.

O4. **The Swift side (built on PR 3b's `macos/gui-hog/`).** The view stays thin: it calls `bin/gui-hog` through `Process` and decides nothing about whether an app may be frozen.
(a) Row buttons: **Freeze N min** (N is `[freeze] default_minutes`, carried in the snapshot's new `freeze` block) and **Freeze…** (indefinite; a confirm sheet whose default is Cancel). Both appear only
on a row that offers Quit (present in the newest sample, no build or terminal inside, identity known, not frozen) and only when the snapshot says `freeze.enabled`; a snapshot without the block hides them.
The press runs `gui-hog freeze … --by dialog` off the main thread; exit 3, 4, 5, 6, 8 and 9 each have a plain refusal text. (b) A row whose root pid is a frozen entry's root is marked frozen from
`gui-hog frozen --json` (polled every 2 s, off the main thread): no Quit, Force Quit, Freeze or Quit All for it ("frozen: use Resume below"). (c) A **Frozen** section lists every entry with the time left
and a **Resume** button (`gui-hog resume --entry ID --by dialog`); Resume is offered even when Freeze is off. (d) The **menu-bar item** (E5): the app started with `--status-only`, its own lock
`gui-hog/status.lock`, no window; the title is `❄︎ N`, the menu has one Resume item per entry and Resume All. It only resumes, polls `gui-hog frozen --json` every 5 s, and exits by itself after two empty reads
or a minute without an answer. The sampler starts it (`gui_hog_freeze.ensure_status_item`, after `thaw_due`, in a GUI session with a fresh bundle, never waited on and never built) while anything is frozen.
(e) `by` gained `menubar`. Self-test (`bin/ade-gui-build --self-test`): the Freeze buttons' conditions (absent row, build host, frozen row, disabled), the argv lists, the frozen list and its sanitizing.

O5. **Not done by the author.** The operator's H4 run (f), (g) with the real window and a real freeze is **not done**; the PR must not merge without it. The runbook is in the PR body (its test app is a harmless third-party one such as Syncthing or Contexts: TextEdit is under /System/Applications, protected by the hard floor, and never listed; the first H4 run, 2026-11-14, showed that).

## P. Auto-freeze list, keep-running rule, Chrome and button handling (2026-11-21)

Operator request (2026-11-21, verbatim): "Add a config file or config file stanza that lists, in order of preferred first to last, what can automatically be
freezed by the 'A build is waiting' system. For us, we can always freeze CodexBar (as long as I am correct that doing so won't disrupt aiuse operations - eg
that that is just the UI and the http server will keep running), Beeper, and Grok Bot. Make sure we are still on the path to making Chrome freezable. Also, I
think we need better button handling; if I quickly hit freeze for multiple rows, only the first button press gets through."

P1. **The auto-freeze list (B6 amended).** `config/gui-hog.toml` `[freeze.auto]`: `order` (bundle ids, preferred first: CodexBar `com.steipete.codexbar`, Beeper
`com.automattic.beeper.desktop`, Grok Bot `com.anysphere.sand`), `enabled`, `minutes` (default `[freeze] default_minutes`), `min_cores` 0.05, `refreeze_s` 3600.
The sampler's tick (`gui_hog.tick(auto_freeze=True)`, only `load-watch` passes it) calls `gui_hog_freeze.auto_freeze_step`: when `hold_active` says a build
has been refused for `hold_s` on a gate desktop apps can relieve (the first two conditions of C4, shared with the dialog), it freezes the **first** listed app
that is running, not protected, not part of a build, not hosting one, not frozen by us within `refreeze_s`, and using at least `min_cores` of *freeable*
cores (a kept helper's cores do not count). **One app per tick** (20 s), so the build's next admission poll sees the relief before the next app goes; the
list ends when the hold ends or no listed app is left. The freeze is the same call as a click (`freeze(... by="auto", check_sampler=False)`: the sampler is
the caller): timed, write-ahead entry, four-field identity, every thaw path (F5), the menu-bar item. Events carry `by: "auto"`; the Frozen list says "frozen
automatically". A refused auto-freeze is retried after 120 s. `refreeze_s` makes an operator's Resume stick: the same app is not auto-frozen again for an hour.
**Where the list lives:** in the repo file, not the overlay: the operator named these apps for this machine, and `[protected]` already carries machine-specific
apps. `~/.config/load-watch/gui-hog.toml` may set `[freeze.auto]` and add to `[freeze.keep_running]`; it cannot change `[freeze] enabled`, `max_minutes`,
`passes` or the lock timeout, and it cannot remove a protected entry. Switches: `[freeze.auto] enabled = false`, `LW_GUI_HOG_AUTO=0` (this only), `LW_GUI_HOG=0`
(everything), `[freeze] enabled = false` (all freezes). `load-watch sample --dry-run` prints "would auto-freeze" without signalling.

P2. **Keep-running (CodexBar's server).** CodexBar is the main process `Contents/MacOS/CodexBar` plus a child `Contents/Helpers/CodexBarCLI serve --host 127.0.0.1
--port 10546` (aiuse's `[collectors.codexbar] http_url`). Until now `group_apps` made the helper a member, so a freeze stopped the server too (`events.jsonl`
2026-11-21 13:03:43Z: both pids stopped, `/health` timed out). `[freeze.keep_running]` maps a bundle id to paths that a freeze never stops; a path is relative to the
bundle (`Contents/Helpers/CodexBarCLI`) or absolute (`~` is the home directory). `group_apps` matches a member's **kernel executable** path (never argv: a process
sets its own), keeps the matching processes and every descendant of one, never the root, and ignores a rule with a `..`. The kept pids leave `member_pids`, so
`vet_app`, the rescan and the signals never see them; the entry records their names (`kept`), `gui-hog frozen --json` and the freeze result report them, the
event log lists them, and the dialog's Frozen line says "keeps running: CodexBarCLI". Applies to manual and auto freezes alike. **Measured (the lead, 2026-11-21
~13:15Z, live):** with only CodexBar's main pid SIGSTOPped and the helper running, `/health` answered 200 in 0.002 s and `/usage?provider=clinepass` 200 in 0.18 s
with live data: the server does not need the UI process, so CodexBar is first in the default list. (A freeze still stops `CodexBarClaudeWatchdog`, a second helper
not named by the rule; add it if it must run.)

P3. **Chrome (Carried 116).** `bin/gui-hog status` showed "Google Chrome ... has a build or terminal inside: no actions". The probe (read-only, 2026-11-21):
`hosts_build` came from **three children of the Chrome main process whose kernel executable is outside Chrome's bundle**: two
`/Applications/1Password.app/.../1Password-BrowserSupport` and `~/.local/share/chrome-use/ChromeUse.app/.../chrome-use __nm-host chrome-extension://...`. They
are **native-messaging hosts** (stdio bridges Chrome starts for extensions), not builds; stop (5) of C4b ("a descendant whose executable lies outside the app's
bundle") flagged them. **Done:** an absolute keep-running path lifts exactly that stop for exactly that process (`config/gui-hog.toml`
`[freeze.keep_running] "com.google.Chrome"`), the process is left running (a stopped Chrome simply stops reading its stdio) and Chrome reads `hosts_build: false`
with 30 members and 3 kept. A pty, a shell or a held caller on that very process is still a build (tested). **Not done, on purpose:** Chrome is not on the auto
list, and a freeze of it has **not been exercised live** (nothing live was signalled). Remaining path: (a) the operator clicks Freeze on Chrome once (H4 run) and
checks that the windows come back on Resume and that an agent using `chrome-use` waits, not fails; (b) a Chrome that really hosts a terminal or a
Playwright-for-Testing child stays a build host, as it should; (c) only then consider listing it. Other apps that start helpers from outside their bundle
(Velja and OnlySwitch run `/usr/bin/shortcuts`) take the same rule if the operator wants them freezable.

P4. **Button handling.** Cause (Swift, `UI.swift`): `freeze()` called `rebuild()` at once to show "freezing...", and every `rebuild()` set one window-wide
`lastLayout`; every click is ignored for 0.7 s after it (`clickAllowed`, N7 a: a button must not move under the pointer). So the click on row 1 itself restarted
the grace of rows 2 and 3, and a second Freeze within 0.7 s was swallowed. Two smaller faults sat behind it: a rebuild that changed nothing still destroyed
every button (a click straddling it was lost), and two freezes at once would contend for `frozen.lock` (5 s timeout). **Fix:** (a) `ClickGrace` keeps the
grace **per control group** (a row, a Frozen entry, the bottom bar) and restarts it only when that group's own layout signature changes (its index, its
note, which buttons exist; for the bottom bar the window's height): a status text has a fixed-width label and changes no layout, so one row's change never
delays another row's click. The protection of N7 stays for every real layout change. (b) Each row has its own in-flight state: while an action on it is queued,
checking or freezing its four buttons are disabled and a repeat click is ignored; other rows are not touched. (c) Freezes run **one after another** on a serial
queue (the row says "queued..." until its turn, then "freezing..."), so none is lost to the lock timeout. (d) `rebuild()` is skipped when what it would draw
is identical to the last draw. Self-test cases cover the per-row grace, an unchanged layout, a changed layout, a forgotten group, the signature and the new
`kept` and `by` fields.

P5. **Verification.** Python: `tests/test_gui_hog_auto.py` (config and overlay, the keep rule on kernel paths, the helper never signalled, Chrome with and
without the rule and the build cases that stay builds, the auto step: order, one per tick, hold conditions, protected and hard floor, hosted build, idle,
not running, Resume sticking, retry, switches, dry run, the tick wiring and kill switches). Swift: **compiled locally**
(`bin/ade-gui-build --self-test` through `bgrun`: `swiftc` build plus `ade-gui-hog --self-test`), because Linux CI has no AppKit and the macOS CI leg has no
step that builds the dialog; PR 849 shipped Swift that had never been compiled, so this one was. **Not done by the author:** the operator's H4 run of the new
behaviour with the real window (two quick Freeze clicks on two rows; "frozen automatically"; "keeps running: CodexBarCLI"); no dialog bundle was installed and
no live state file was touched.
