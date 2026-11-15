# GUI-hog dialog: design (2026-11-14, PR 3 of the load-gate retune)

Status: **PR 3a is built (2026-11-14): the data and a dry-run trigger, no window** (section M says what it does and where it departs from this text). PR 3b (the window) and 3c (Freeze) are not started. The operator accepted K1-K7 (all recommended) on 2026-11-14. The rest of this document is the design.
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

B6. **Never automatic.** Every Quit, Force Quit or Freeze is an operator click (2026-11-13 proposal). Only *resuming* is
ever automatic.

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

C5. **Who calls it.** The sampler calls it on every tick (20 s). It runs as a launchd agent in the operator's `gui/502`
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
| 16 | An agent runs `gui-hog freeze` itself | breaks "never automatic" | rule in `skills/loadwatch/SKILL.md` and this doc; every event logs `by`; accepted because same-uid processes can already `kill -STOP` (J1) |
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
(d) Quit on TextEdit with an unsaved document shows TextEdit's save sheet;
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

I2. **PR 3b: read-only and quit dialog.** `macos/gui-hog/`, `bin/ade-gui-build` and the `ade update` hook (D2), the
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
(F6a), and the kernel would refuse them anyway (`EPERM`). Agents are trusted peers here (AGENTS.md Trust). "Never
automatic" (B6) is a rule plus an audit trail (`by`, `events.jsonl`), not a boundary.

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
