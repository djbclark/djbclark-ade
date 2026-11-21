### Added

- GUI-hog auto-freeze list: `config/gui-hog.toml` `[freeze.auto] order` (shipped: Grok Bot) names the apps the load-watch sampler freezes, first listed first and one per 20 s tick, while a build has been held for 3 min on a gate desktop apps can relieve. The freeze is timed with the usual thaw paths and logged `by: "auto"`; protected apps are never auto-frozen, an operator's Resume sticks for an hour (`refreeze_s`), and `LW_GUI_HOG_AUTO=0` or `[freeze.auto] enabled = false` turns it off. Design rule B6 ("never automatic") is amended for the listed apps only. The user overlay may set `[freeze.auto]`. (#859)
- GUI-hog `[freeze.keep_running]`: paths inside an app's bundle (or absolute) that a freeze never stops, matched on the kernel executable path; the entry, `gui-hog frozen --json`, the event log and the dialog's Frozen line record them. CodexBar's `CodexBarCLI` HTTP server (aiuse's collector) now keeps running when CodexBar is frozen. (#859)

### Changed

- GUI-hog `[freeze.auto] skip`: apps never frozen automatically, even if listed in `order` (shipped: Beeper Desktop, whose MCP API hangs while frozen and which uses almost no CPU, and CodexBar, whose freeze stops the aiuse quota readings); a manual Freeze stays possible, the overlay can add to the list but not remove from it. Docs: `docs/gui-hog-dialog.md` P7, and a "Deep freeze (open question)" section (P8). (#859)
- GUI-hog: Chrome's native-messaging hosts (1Password-BrowserSupport, chrome-use) run from outside its bundle and made Chrome read as hosting a build ("no actions"); they are now kept running by an absolute keep-running rule, so Chrome offers actions again (not yet exercised live). Docs: section P of `docs/gui-hog-dialog.md`. (#859)

### Fixed

- GUI-hog auto-freeze (adversary round 1): it now requires launchd's sampler job to be loaded (a hand-run `load-watch sample` could leave a timed freeze that nothing thawed), "Ignore 1 h" pauses it, `[freeze.auto]` values are type-checked (the overlay can only switch it off), the app's start time is read in the tick, keep-running rules must name an exact executable inside a bundle, and an `OSError` is a refusal retried after 120 s. (#859)
- GUI-hog dialog: a quick second Freeze click on another row was swallowed because every redraw restarted one window-wide 0.7 s click grace. The grace is now per row, a row has its own in-flight state, freezes queue one after another, and a redraw that changes nothing is skipped. (#859)
