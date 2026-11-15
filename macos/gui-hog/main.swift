// main.swift: argument parsing, the single-instance lock (D5: exit 75), the window-server check (exit 69) and the run loop.
// Exit codes (D5): 0 Wait / close / hold ended, 3 Ignore, 4 closed after actions, 69 no window server, 70 internal error, 75 another instance.
import AppKit
import CoreGraphics
import Foundation

var cfg = Config()
let argv = Array(CommandLine.arguments.dropFirst())
var ai = 0
func nextArg() -> String { ai += 1; return ai < argv.count ? argv[ai] : "" }
while ai < argv.count {
    switch argv[ai] {
    case "--self-test": exit(runSelfTest())
    case "--state-dir": cfg.stateDir = nextArg()
    case "--python": cfg.python = nextArg()
    case "--gui-hog": cfg.guiHog = nextArg()
    case "--demo": cfg.demo = true
    case "--manual": cfg.manual = true
    default: FileHandle.standardError.write(Data("ade-gui-hog: unknown argument\n".utf8)); exit(70)
    }
    ai += 1
}
if cfg.stateDir.isEmpty || (!cfg.demo && cfg.guiHog.isEmpty) { FileHandle.standardError.write(Data("ade-gui-hog: --state-dir and --gui-hog are required\n".utf8)); exit(70) }

let runner = Runner(cfg)

// One dialog at a time: flock gui-hog/dialog.lock for the whole life of this process (F8-13). A flock dies with the process, so a crash leaves nothing behind.
let dir = cfg.stateDir + "/gui-hog"
mkdir(dir, 0o700)
let lockFd = open(dir + "/dialog.lock", O_RDWR | O_CREAT | O_NOFOLLOW, 0o600)
if lockFd < 0 || flock(lockFd, LOCK_EX | LOCK_NB) != 0 { exit(75) }

// No window server (SSH, no console user): say so and leave (D6).
if CGSessionCopyCurrentDictionary() == nil {
    if !cfg.demo { _ = runner.gui(exitArgv(69), timeout: 5) }
    exit(69)
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let dialog = Dialog(cfg)
app.delegate = dialog
app.run()
