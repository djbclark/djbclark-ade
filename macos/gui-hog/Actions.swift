// Actions.swift: running `bin/gui-hog` and quitting apps (D4, G1-G4). Process with an executableURL and an arguments array only: no shell, no network,
// no listening socket (J2). The dialog quits and force-quits through NSRunningApplication (never AppleScript by bundle id, which hits every instance
// that shares it), and only after `gui-hog vet` exits 0 AND its own identity re-check passes on the very process it is about to signal.
import AppKit
import Foundation

struct Config {
    var stateDir = ""
    var python = "/usr/bin/python3"
    var guiHog = ""
    var demo = false
    var manual = false
}

struct VetResult {
    var code: Int32
    var reason: String
}

final class Runner {
    let cfg: Config
    init(_ cfg: Config) { self.cfg = cfg }

    /// Run `python3 bin/gui-hog ARGS` and wait (at most `timeout` s). Returns the exit status and stdout, or nil when it cannot be started.
    func gui(_ args: [String], timeout: TimeInterval = 20) -> (status: Int32, out: String)? {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: cfg.python)
        p.arguments = [cfg.guiHog] + args
        var env = ProcessInfo.processInfo.environment
        env["LW_STATE_DIR"] = cfg.stateDir
        p.environment = env
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = FileHandle.nullDevice
        p.standardInput = FileHandle.nullDevice
        do { try p.run() } catch { return nil }
        let deadline = Date().addingTimeInterval(timeout)
        while p.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.05) }
        if p.isRunning { p.terminate(); return nil }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        return (p.terminationStatus, String(decoding: data, as: UTF8.self))
    }

    /// The Python core's verdict on this row (D4a): 0 allowed, 3 protected or part of a build, 4 identity changed, 5 hosts a build or terminal, 6 gone or ps failed.
    func vet(_ r: Row) -> VetResult {
        if cfg.demo { return VetResult(code: 0, reason: "demo") }
        guard let res = gui(vetArgv(r), timeout: 45) else { return VetResult(code: 6, reason: "the check did not run") }
        var reason = ""
        if let d = res.out.data(using: .utf8), let o = (try? JSONSerialization.jsonObject(with: d)) as? [String: Any] { reason = sanitize(o["reason"] as? String ?? "", limit: 100) }
        return VetResult(code: res.status, reason: reason)
    }

    func log(_ event: String, _ r: Row?) { if !cfg.demo { _ = gui(logArgv(event, r), timeout: 5) } }
}

/// Reads the live process for a row: pid, kernel start time, bundle id and launch date. Main thread only (NSRunningApplication).
func liveProc(for r: Row) -> (app: NSRunningApplication?, live: LiveProc?) {
    guard let app = NSRunningApplication(processIdentifier: pid_t(r.rootPid)), !app.isTerminated else { return (nil, nil) }
    return (app, LiveProc(pid: Int(app.processIdentifier), startEpoch: liveStartEpoch(Int(app.processIdentifier)), bundleId: app.bundleIdentifier,
                          launchEpoch: app.launchDate?.timeIntervalSince1970))
}

enum QuitKind { case polite, force }

/// Quit one row. Order (D4): vet (the Python core, live) -> identity re-check on this very pid -> terminate() / forceTerminate(). Call on the main
/// thread, after `vet` returned 0 (the caller runs vet off the main thread). `app` is set when the request was sent, so the caller can watch it exit.
func performQuit(_ r: Row, kind: QuitKind, demo: Bool) -> (ok: Bool, text: String, app: NSRunningApplication?) {
    if demo { return (true, "demo: nothing was touched", nil) }
    let (app, live) = liveProc(for: r)
    let id = identityMatches(r, live)
    guard id.ok, let target = app else { return (false, "refused: " + id.why, nil) }
    let sent = kind == .polite ? target.terminate() : target.forceTerminate()
    return sent ? (true, kind == .polite ? "quitting…" : "force quit sent", target) : (false, "the app did not accept the request", nil)
}
