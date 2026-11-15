// Model.swift: the pure logic of the GUI-hog dialog (docs/gui-hog-dialog.md D1, H3). No AppKit here: everything the window decides is a plain
// function over plain values, so `ade-gui-hog --self-test` checks it without a window. The Python core (bin/gui_hog.py) owns every decision about
// WHETHER an app may be touched (`gui-hog vet`); this file only displays the snapshot, builds argv lists and re-checks identity before acting.
import Foundation
import Darwin

// MARK: untrusted text (J3)

/// An app sets its own name, so every name, bundle id and caller label is untrusted: control, format (bidi, zero-width, TAG, soft hyphen),
/// surrogate, private-use and unassigned code points, line and paragraph separators, variation selectors and the invisible filler letters are
/// dropped, and the rest is clipped to `limit` grapheme clusters (`Character`s), never in the middle of one.
func sanitize(_ text: String, limit: Int = 60) -> String {
    let dropped: Set<Unicode.GeneralCategory> = [.control, .format, .surrogate, .privateUse, .unassigned, .lineSeparator, .paragraphSeparator]
    let fillers: Set<UInt32> = [0x034F, 0x115F, 0x1160, 0x3164, 0xFFA0, 0x17B4, 0x17B5, 0x180B, 0x180C, 0x180D, 0x180F, 0x2800]
    var out = String.UnicodeScalarView()
    for u in text.unicodeScalars {
        let v = u.value
        if dropped.contains(u.properties.generalCategory) || fillers.contains(v) { continue }
        if (0xFE00...0xFE0F).contains(v) || (0xE0100...0xE01EF).contains(v) { continue }
        out.append(u)
    }
    let s = String(out)
    return s.count <= limit ? s : String(s.prefix(limit)) + "…"
}

// MARK: the snapshot (D3)

struct Row {
    var appId: String
    var name: String
    var bundleId: String
    var bundlePath: String
    var rootPid: Int
    var rootStart: String
    var rootStartEpoch: Int?
    var cores5m: Double
    var cpuNow: Double
    var rssMb: Int
    var present: Bool
    var hostsBuild: Bool
    var frozen: Bool
}

struct Hold {
    var caller: String
    var heldS: Int
    var refused: [String]
}

struct Snapshot {
    var t: Int
    var load: [Double]?
    var ncpu: Int?
    var cpu5m: Double?
    var holds: [Hold]
    var rows: [Row]
    var more: Int
    var protectedHidden: Int
    var rssTrigger: Bool
    var freezeEnabled = false     // [freeze] enabled (PR 3c, I3): false (or missing) hides every Freeze button
    var freezeMinutes = 10        // [freeze] default_minutes: the timed button's length
}

private func num(_ v: Any?) -> Double? {
    guard let n = v as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID() else { return nil }
    let d = n.doubleValue
    return d.isFinite ? d : nil
}
private func int(_ v: Any?) -> Int? { num(v).flatMap { abs($0) < 1e15 ? Int($0) : nil } }
private func bool(_ v: Any?) -> Bool { (v as? NSNumber).map { CFGetTypeID($0) == CFBooleanGetTypeID() && $0.boolValue } ?? false }

/// The snapshot from its JSON bytes, or nil when it is not a version-1 object. Every text field is sanitized here, again (the file is data).
func parseSnapshot(_ data: Data) -> Snapshot? {
    guard let top = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any], int(top["v"]) == 1 else { return nil }
    let header = top["header"] as? [String: Any] ?? [:]
    let load = (header["load"] as? [Any]).map { $0.compactMap { num($0) } }.flatMap { $0.count == 3 ? $0 : nil }
    var holds: [Hold] = []
    for h in (top["holds"] as? [Any] ?? []).prefix(8) {
        guard let d = h as? [String: Any] else { continue }
        holds.append(Hold(caller: sanitize(d["caller"] as? String ?? "?", limit: 80), heldS: max(0, int(d["held_s"]) ?? 0),
                          refused: (d["refused"] as? [Any] ?? []).compactMap { $0 as? String }.prefix(12).map { sanitize($0, limit: 40) }))
    }
    var rows: [Row] = []
    for r in (top["rows"] as? [Any] ?? []).prefix(24) {
        guard let d = r as? [String: Any], let pid = int(d["root_pid"]) else { continue }
        rows.append(Row(appId: sanitize(d["app_id"] as? String ?? "", limit: 20), name: sanitize(d["name"] as? String ?? "?"),
                        bundleId: sanitize(d["bundle_id"] as? String ?? "", limit: 80), bundlePath: sanitize(d["bundle_path"] as? String ?? "", limit: 200),
                        rootPid: pid, rootStart: d["root_start"] as? String ?? "", rootStartEpoch: int(d["root_start_epoch"]),
                        cores5m: max(0, num(d["cores_5m"]) ?? 0), cpuNow: max(0, num(d["cpu_now"]) ?? 0), rssMb: max(0, int(d["rss_mb"]) ?? 0),
                        present: bool(d["present"]), hostsBuild: bool(d["hosts_build"]), frozen: bool(d["frozen"])))
    }
    let fz = top["freeze"] as? [String: Any] ?? [:]
    return Snapshot(t: int(top["t"]) ?? 0, load: load, ncpu: int(header["ncpu"]), cpu5m: num(header["cpu_5m"]), holds: holds, rows: rows,
                    more: max(0, int(top["more"]) ?? 0), protectedHidden: max(0, int(top["protected_hidden"]) ?? 0), rssTrigger: bool(top["rss_trigger"]),
                    freezeEnabled: bool(fz["enabled"]), freezeMinutes: min(1440, max(1, int(fz["default_minutes"]) ?? 10)))
}

// MARK: frozen apps (PR 3c: E2 Resume rows, E5 menu-bar item)

/// One entry of `gui-hog frozen --json`. The Python core owns the truth (frozen.json); this is only what the window shows.
struct FrozenEntry: Equatable {
    var id: String
    var name: String
    var state: String
    var thawAt: Int?        // nil: frozen until someone resumes it
    var members: Int
    var alive: Bool
}

/// The entries from `gui-hog frozen --json` output, or nil when it is not a version-1 object. Every text field is sanitized (J3).
func parseFrozen(_ data: Data) -> [FrozenEntry]? {
    guard let top = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any], int(top["v"]) == 1 else { return nil }
    var out: [FrozenEntry] = []
    for e in (top["entries"] as? [Any] ?? []).prefix(24) {
        guard let d = e as? [String: Any], let id = d["id"] as? String, !id.isEmpty else { continue }
        let app = d["app"] as? [String: Any] ?? [:]
        out.append(FrozenEntry(id: sanitize(id, limit: 40), name: sanitize(app["name"] as? String ?? "?"), state: sanitize(d["state"] as? String ?? "", limit: 20),
                               thawAt: int(d["thaw_at"]), members: max(1, int(d["members"]) ?? 1), alive: bool(d["alive"])))
    }
    return out
}

/// A row whose root pid is a frozen entry's root is shown as frozen: no Quit, no Force Quit, no second Freeze. `rootPids` come from the frozen entries'
/// `root_pid` (the same list); the flag is set and cleared with the list; a pid match alone never lets an action through, it only takes actions away.
func markFrozen(_ rows: [Row], rootPids: Set<Int>) -> [Row] {
    rows.map { r in var c = r; c.frozen = rootPids.contains(r.rootPid); return c }
}

func parseFrozenRoots(_ data: Data) -> Set<Int> {
    guard let top = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any], int(top["v"]) == 1 else { return [] }
    return Set((top["entries"] as? [Any] ?? []).compactMap { ($0 as? [String: Any]).flatMap { int($0["root_pid"]) } })
}

/// Freeze is offered on a row that offers Quit (present, not hosting a build, not frozen, identity known) when the config allows it. A row whose app
/// is absent from the newest sample gets no button (carry-over from the 3a reviews).
func rowFreezeAllowed(_ r: Row, _ s: Snapshot) -> Bool { s.freezeEnabled && rowActionsAllowed(r) }

/// The resume time as a clock time in New York (operator ruling 2026-11-14): "resumes at 9:52 PM", with a 3-letter day name when it is not today
/// ("resumes at Sun 9:52 PM"). No countdown, so the text never changes between refreshes. `zone` is a parameter so the self-test is timezone-independent.
func thawText(_ e: FrozenEntry, now: Int, zone: TimeZone = TimeZone(identifier: "America/New_York") ?? TimeZone(identifier: "UTC")!) -> String {
    guard let t = e.thawAt else { return "until you Resume" }
    var cal = Calendar(identifier: .gregorian)
    cal.timeZone = zone
    let when = Date(timeIntervalSince1970: TimeInterval(t)), today = Date(timeIntervalSince1970: TimeInterval(now))
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_US_POSIX")
    f.timeZone = zone
    f.dateFormat = cal.isDate(when, inSameDayAs: today) ? "h:mm a" : "EEE h:mm a"
    return "resumes at " + f.string(from: when)
}

func statusTitle(_ n: Int) -> String { n == 0 ? "" : "❄︎ \(n)" }

// MARK: formatting (E1, E2)

func fmtCores(_ c: Double) -> String { String(format: "%.2f", c) }
func fmtCPU(_ c: Double) -> String { "\(Int((c * 100).rounded()))%" }
func fmtRAM(_ mb: Int) -> String { mb >= 1024 ? String(format: "%.1f GB", Double(mb) / 1024) : "\(mb) MB" }

func headerLine(_ s: Snapshot) -> String {
    var parts: [String] = []
    if let l = s.load {
        parts.append("Load " + l.map { String(format: "%.1f", $0) }.joined(separator: " / ") + (s.ncpu.map { " (\($0) cores)" } ?? ""))
    }
    if let c = s.cpu5m { parts.append("CPU 5-min avg " + String(format: "%.1f", c) + " cores") }
    return parts.isEmpty ? "Load: no reading" : parts.joined(separator: " · ")
}

func holdLine(_ h: Hold) -> String {
    let held = h.heldS >= 60 ? "\(h.heldS / 60) min" : "\(h.heldS) s"
    return "\(h.caller), held \(held)" + (h.refused.isEmpty ? "" : " for " + h.refused.joined(separator: ", "))
}

// MARK: what a row may offer (E2, carry-over d)

/// Quit and Force Quit are offered only on a row that is in the newest sample, hosts no build or terminal, is not frozen (3c) and carries the
/// pid, the start time and the start epoch the identity checks need. A row without them has no actions at all.
func rowActionsAllowed(_ r: Row) -> Bool {
    r.present && !r.hostsBuild && !r.frozen && r.rootPid > 1 && !r.rootStart.isEmpty && r.rootStartEpoch != nil
}

func rowNote(_ r: Row) -> String? {
    if !r.present { return "no longer running" }
    if r.hostsBuild { return "has a terminal or build inside: no actions" }
    if r.frozen { return "frozen: use Resume below" }
    if !rowActionsAllowed(r) { return "identity unknown: no actions" }
    return nil
}

/// Quit All asks to quit exactly the rows that offer actions (never a frozen, absent or build-hosting row, never a protected one: the snapshot has none).
func quitAllTargets(_ rows: [Row]) -> [Row] { rows.filter(rowActionsAllowed) }

// MARK: argv lists for `bin/gui-hog` (D4, J2): arrays, never a shell string

// Option values are joined with `=` so a value that starts with `-` (an app named "-x") is never read by argparse as another option.
func vetArgv(_ r: Row) -> [String] {
    ["vet", "--pid=" + String(r.rootPid), "--start=" + r.rootStart, "--bundle-id=" + r.bundleId, "--bundle-path=" + r.bundlePath]
}
func snoozeArgv() -> [String] { ["snooze", "--minutes", "60"] }

/// Freeze one app: `minutes` is the timed length, nil is indefinite. The Python core re-checks everything live (identity, protected list, build hosts).
func freezeArgv(_ r: Row, minutes: Int?) -> [String] {
    ["freeze", "--pid=" + String(r.rootPid), "--start=" + r.rootStart, "--bundle-id=" + r.bundleId, "--bundle-path=" + r.bundlePath,
     minutes.map { "--minutes=\($0)" } ?? "--indefinite", "--by", "dialog"]
}
func resumeArgv(_ id: String, by: String) -> [String] { ["resume", "--entry=\(id)", "--by", by] }   // `--entry=ID`: an id is never read as an option
/// The belt and braces of F5a, b, f: the dialog and the menu-bar item resume what is due on their own clock too (the sampler is the first clock).
func thawDueArgv(by: String) -> [String] { ["thaw", "--due", "--stale", "--by", by] }
func resumeAllArgv(by: String) -> [String] { ["resume", "--all", "--by", by] }
func frozenArgv() -> [String] { ["frozen", "--json"] }
func exitArgv(_ code: Int32) -> [String] { ["record-exit", "--code", String(code)] }
func logArgv(_ event: String, _ r: Row?) -> [String] {
    ["log", "--event=" + event, "--by", "dialog"] + (r.map { ["--app=" + $0.name, "--bundle-id=" + $0.bundleId] } ?? [])
}

// MARK: a stable window (adversary round 1, finding 1)

/// The rows the window shows: the order they were first seen in, never re-sorted, so a Quit button never moves under the pointer. A row's numbers are
/// refreshed from the newest snapshot; a row the newest snapshot no longer lists stays, marked absent (no actions); an app seen for the first time is
/// appended at the bottom. At most `cap` rows (the window must fit the screen): when full, a new app takes the place of an absent row (which offers
/// no button, so nothing a click could hit moves; only a slot that was already absent before this refresh), else it is not shown. No row is ever removed from the middle.
func mergeRows(old: [Row], new: [Row], cap: Int = maxWindowRows) -> [Row] {
    var fresh: [String: Row] = [:]
    for r in new where !r.appId.isEmpty { fresh[r.appId] = r }
    var out: [Row] = old.prefix(cap).map { o in
        if let n = fresh[o.appId], n.rootPid == o.rootPid { return n }
        var gone = o
        gone.present = false
        gone.cpuNow = 0
        return gone
    }
    let known = Set(old.map { $0.appId })
    // A slot is reused only if it was ALREADY absent in `old` (so it had no button for a click to be aimed at): never in the same merge that marks its row absent.
    var free = old.prefix(cap).enumerated().filter { !$0.element.present && !out[$0.offset].present }.map { $0.offset }   // and still absent in `out`: a returning app keeps its slot
    for n in new where !known.contains(n.appId) {
        if out.count < cap { out.append(n) } else if !free.isEmpty { out[free.removeFirst()] = n }
    }
    return out
}

let maxWindowRows = 16

/// A click that lands within this many seconds of the last layout is ignored: the buttons may have moved since the pointer was aimed.
let clickGraceS = 0.7
func clickAllowed(lastLayout: Double, now: Double) -> Bool { now - lastLayout >= clickGraceS }

/// Only Wait may hold keyboard focus (so Return, Space and Tab never press Ignore, Quit All or a row's Quit). A click on any button still works.
func buttonRefusesFocus(_ a: BottomAction?) -> Bool { a != .wait }

// MARK: the bottom row (E3, B4)

enum BottomAction { case wait, ignore, quitAll }

struct ButtonSpec {
    let title: String
    let action: BottomAction
    let keyEquivalent: String
}

/// Wait first (leftmost, and the initial first responder), then Ignore, then Quit All. NO button has a key equivalent.
let bottomButtons: [ButtonSpec] = [
    ButtonSpec(title: "Wait", action: .wait, keyEquivalent: ""),
    ButtonSpec(title: "Ignore 1 h", action: .ignore, keyEquivalent: ""),
    ButtonSpec(title: "Quit All…", action: .quitAll, keyEquivalent: ""),
]

enum Effect: Equatable {
    case close(Int32)            // leave with this exit code (D5)
    case run([String])           // a `bin/gui-hog` call
    case confirmQuitAll          // a confirm sheet; Cancel is its default
}

/// What a bottom button does. Wait closes with exit code 0 and runs nothing: no argv, no signal, no quit.
func effects(for a: BottomAction) -> [Effect] {
    switch a {
    case .wait: return [.close(0)]
    case .ignore: return [.run(snoozeArgv()), .close(3)]
    case .quitAll: return [.confirmQuitAll]
    }
}

// Return (36), keypad Enter (76) and Escape (53) take no action in the main window: a stray key must never press a button.
let swallowedKeyCodes: Set<UInt16> = [36, 76, 53]
func swallowsKey(_ keyCode: UInt16) -> Bool { swallowedKeyCodes.contains(keyCode) }

// MARK: identity, checked again right before a signal (D4, F3)

struct LiveProc {
    var pid: Int
    var startEpoch: Int?        // proc_pidinfo(PROC_PIDTBSDINFO).pbi_start_tvsec
    var bundleId: String?       // NSRunningApplication.bundleIdentifier
    var launchEpoch: Double?    // NSRunningApplication.launchDate
}

/// How far an app's LaunchServices launch date may differ from its process start (seconds). Measured on this Mac, see docs/gui-hog-dialog.md section N.
let launchToleranceS = 3.0

/// The pid is still the process the row showed: same pid, kernel start time within one second of the snapshot's, same bundle id, and a launch date that
/// agrees with the start. A missing process, start time or launch date means refuse (a nil launchDate means refuse: D4).
func identityMatches(_ r: Row, _ live: LiveProc?) -> (ok: Bool, why: String) {
    guard let l = live else { return (false, "the app is gone") }
    guard l.pid == r.rootPid else { return (false, "pid changed") }
    guard let want = r.rootStartEpoch, let have = l.startEpoch else { return (false, "start time unknown") }
    if abs(want - have) > 1 { return (false, "pid now belongs to another process (start time differs)") }
    if (l.bundleId ?? "").lowercased() != r.bundleId.lowercased() { return (false, "bundle id differs") }
    guard let launched = l.launchEpoch else { return (false, "launch date unknown") }
    if abs(launched - Double(want)) > launchToleranceS { return (false, "launch date differs from the start time") }
    return (true, "")
}

func liveStartEpoch(_ pid: Int) -> Int? {
    var info = proc_bsdinfo()
    let size = Int32(MemoryLayout<proc_bsdinfo>.size)
    let n = proc_pidinfo(Int32(pid), PROC_PIDTBSDINFO, 0, &info, size)
    return n == size ? Int(info.pbi_start_tvsec) : nil
}
