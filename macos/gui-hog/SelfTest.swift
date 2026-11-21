// SelfTest.swift: `ade-gui-hog --self-test` (H3). Pure logic only, no window, no process is touched. Exit 0 when every check passes, 1 otherwise.
import AppKit
import Foundation

func runSelfTest() -> Int32 {
    var failed: [String] = []
    var n = 0
    func check(_ ok: Bool, _ what: String) { n += 1; if !ok { failed.append(what) } }

    // sanitize (J3)
    check(sanitize("Mail\u{202E}gnp.exe") == "Mailgnp.exe", "bidi override is dropped")
    check(sanitize("a\u{200B}b\u{FEFF}c\u{2060}d") == "abcd", "zero-width characters are dropped")
    check(sanitize("a\u{07}b\nc\td\u{85}e") == "abcde", "C0 and C1 controls are dropped")
    check(sanitize("a\u{2028}b\u{2029}c") == "abc", "line and paragraph separators are dropped")
    check(sanitize("a\u{E0041}b\u{FE0F}c\u{3164}d\u{2800}e") == "abcde", "TAG characters, variation selectors and fillers are dropped")
    check(sanitize(String(repeating: "x", count: 100)) == String(repeating: "x", count: 60) + "…", "a long name is clipped to 60")
    let e = "e\u{301}"   // e + combining acute: one grapheme
    check(sanitize(String(repeating: e, count: 70)) == String(repeating: e, count: 60) + "…", "the clip never splits a grapheme cluster")
    check(sanitize("") == "", "empty stays empty")

    // snapshot parsing
    let json = """
    {"v":1,"t":100,"header":{"load":[9.8,10.4,11.2],"ncpu":10,"cpu_5m":7.94},
     "holds":[{"caller":"b\\u202eg","held_s":240,"refused":["pageins","swapins"]}],
     "rows":[{"app_id":"812","name":"Sl\\u200back","bundle_id":"com.tinyspeck.slackmacgap","bundle_path":"/Applications/Slack.app","root_pid":812,
              "root_start":"Fri Nov 14 18:02:11 2026","root_start_epoch":1794765731,"cores_5m":1.84,"cpu_now":1.9,"rss_mb":3170,"present":true,"hosts_build":false,"frozen":false},
             {"app_id":"9","name":"Gone","bundle_id":"x","bundle_path":"/Applications/Gone.app","root_pid":9,"root_start":"","root_start_epoch":null,"cores_5m":0.3,"cpu_now":0,"rss_mb":0,"present":false,"hosts_build":false,"frozen":false},
             {"app_id":"7","name":"IDE","bundle_id":"y","bundle_path":"/Applications/IDE.app","root_pid":7,"root_start":"s","root_start_epoch":5,"cores_5m":0.3,"cpu_now":0,"rss_mb":900,"present":true,"hosts_build":true,"frozen":false}],
     "more":3,"protected_hidden":4,"rss_trigger":true}
    """
    let snap = parseSnapshot(Data(json.utf8))
    check(snap != nil, "a version-1 snapshot parses")
    if let s = snap {
        check(s.rows.count == 3 && s.rows[0].name == "Slack", "row name is sanitized")
        check(s.holds.first?.caller == "bg", "caller label is sanitized")
        check(s.rows[0].rootStartEpoch == 1794765731 && s.rows[1].rootStartEpoch == nil, "start epoch parses, null stays nil")
        check(rowActionsAllowed(s.rows[0]), "a present row with an identity has actions")
        check(!rowActionsAllowed(s.rows[1]), "an absent row has no actions (carry-over d)")
        check(!rowActionsAllowed(s.rows[2]), "a build-hosting row has no actions")
        check(rowNote(s.rows[1]) == "no longer running" && rowNote(s.rows[2]) == "has a terminal or build inside: no actions", "row notes")
        check(quitAllTargets(s.rows).map { $0.rootPid } == [812], "Quit All targets only rows with actions")
        check(headerLine(s) == "Load 9.8 / 10.4 / 11.2 (10 cores) · CPU 5-min avg 7.9 cores", "header line")
        check(holdLine(s.holds[0]) == "bg, held 4 min for pageins, swapins", "hold line")
    }
    check(parseSnapshot(Data("{\"v\":2}".utf8)) == nil, "another version is refused")
    check(parseSnapshot(Data("nonsense".utf8)) == nil, "garbage is refused")
    check(parseSnapshot(Data("{\"v\":1,\"rows\":[{\"root_pid\":\"x\"}]}".utf8))?.rows.isEmpty == true, "a row without a numeric pid is dropped")

    // formatting
    check(fmtCores(1.839) == "1.84" && fmtCPU(1.84) == "184%" && fmtRAM(3170) == "3.1 GB" && fmtRAM(960) == "960 MB", "number formatting")
    check(holdLine(Hold(caller: "bg", heldS: 45, refused: [])) == "bg, held 45 s", "short hold in seconds")

    // argv tables (J2: arrays)
    let row = Row(appId: "812", name: "Slack", bundleId: "com.tinyspeck.slackmacgap", bundlePath: "/Applications/Slack.app", rootPid: 812,
                  rootStart: "Fri Nov 14 18:02:11 2026", rootStartEpoch: 1794765731, cores5m: 1, cpuNow: 1, rssMb: 1, present: true, hostsBuild: false, frozen: false)
    check(vetArgv(row) == ["vet", "--pid=812", "--start=Fri Nov 14 18:02:11 2026", "--bundle-id=com.tinyspeck.slackmacgap", "--bundle-path=/Applications/Slack.app"], "vet argv")
    check(snoozeArgv() == ["snooze", "--minutes", "60"] && exitArgv(4) == ["record-exit", "--code", "4"], "snooze and exit argv")
    check(logArgv("quit", row).contains("--app=Slack") && logArgv("ignore", nil) == ["log", "--event=ignore", "--by", "dialog"], "log argv")
    var dash = row; dash.name = "-x"; dash.bundleId = "-y"
    check(logArgv("quit", dash).contains("--app=-x") && logArgv("quit", dash).contains("--bundle-id=-y") && vetArgv(dash).contains("--bundle-id=-y"), "a value that starts with a dash stays one argument with its option")

    // the bottom row: Wait is leftmost, the default, and does nothing (E3, B4)
    check(bottomButtons.map { $0.title } == ["Wait", "Ignore 1 h", "Quit All…"], "bottom buttons are Wait, Ignore, Quit All in that order")
    check(bottomButtons[0].action == .wait, "Wait is the leftmost (the initial first responder)")
    check(bottomButtons.allSatisfy { $0.keyEquivalent.isEmpty }, "no bottom button has a key equivalent")
    check(effects(for: .wait) == [.close(0)], "Wait only closes: no argv, no quit, no signal")
    check(effects(for: .ignore) == [.run(["snooze", "--minutes", "60"]), .close(3)], "Ignore snoozes then leaves with code 3")
    check(effects(for: .quitAll) == [.confirmQuitAll], "Quit All asks first")
    check(swallowsKey(36) && swallowsKey(76) && swallowsKey(53) && !swallowsKey(49), "Return, Enter and Escape are swallowed; Space is not")

    // a stable window: rows keep first-seen order, buttons never move under the pointer, only Wait takes focus (adversary round 1, findings 1 and 2)
    func mk(_ id: String, _ pid: Int, cores: Double, present: Bool = true) -> Row {
        Row(appId: id, name: "App" + id, bundleId: "b" + id, bundlePath: "/Applications/" + id + ".app", rootPid: pid, rootStart: "s", rootStartEpoch: 5,
            cores5m: cores, cpuNow: 1, rssMb: 1, present: present, hostsBuild: false, frozen: false)
    }
    let first = mergeRows(old: [], new: [mk("1", 1001, cores: 2), mk("2", 1002, cores: 1.5), mk("3", 1003, cores: 1)])
    check(first.map { $0.appId } == ["1", "2", "3"], "the first snapshot sets the order")
    let swapped = mergeRows(old: first, new: [mk("2", 1002, cores: 3), mk("1", 1001, cores: 1.4), mk("3", 1003, cores: 1)])
    check(swapped.map { $0.appId } == ["1", "2", "3"], "a new sort order never reorders the rows on screen")
    check(swapped[1].cores5m == 3 && swapped[0].cores5m == 1.4, "the numbers are refreshed in place")
    let dropped = mergeRows(old: first, new: [mk("1", 1001, cores: 2), mk("3", 1003, cores: 1)])
    check(dropped.map { $0.appId } == ["1", "2", "3"] && !dropped[1].present && dropped[1].cpuNow == 0, "a row that left the snapshot stays, marked absent, so the rows below do not move")
    check(!rowActionsAllowed(dropped[1]), "an absent row offers no actions")
    let grown = mergeRows(old: first, new: [mk("4", 1004, cores: 9), mk("1", 1001, cores: 2), mk("2", 1002, cores: 1.5), mk("3", 1003, cores: 1)])
    check(grown.map { $0.appId } == ["1", "2", "3", "4"], "a new app is appended at the bottom, never inserted above a row")
    let reused = mergeRows(old: first, new: [mk("1", 7777, cores: 2)])
    check(reused[0].rootPid == 1001 && !reused[0].present, "an id that now has another pid never takes over the old row")
    var many: [Row] = []
    for i in 0..<40 { many.append(mk(String(i + 10), 2000 + i, cores: 1)) }
    check(mergeRows(old: [], new: many).count == maxWindowRows, "the window is capped")
    let full = mergeRows(old: [], new: Array(many.prefix(maxWindowRows)))
    let still = mergeRows(old: full, new: Array(many.prefix(maxWindowRows)) + [mk("99", 3099, cores: 5)])
    check(still.map { $0.appId } == full.map { $0.appId }, "at the cap a new app takes no live row's place and no row moves")
    let drop = Array(many.prefix(maxWindowRows)).filter { $0.appId != "12" } + [mk("99", 3099, cores: 5)]
    let gap = mergeRows(old: full, new: drop)
    check(gap.map { $0.appId } == full.map { $0.appId } && !gap[2].present, "at the cap, a row that just went absent keeps its slot (the new app is not shown yet): its button cannot turn into another app's")
    let gap2 = mergeRows(old: gap, new: drop)
    check(gap2.count == maxWindowRows && gap2[2].appId == "99" && gap2[3].appId == full[3].appId, "on the next refresh the new app takes the slot that was already absent; the rows around it stay")
    let back = mergeRows(old: gap, new: Array(many.prefix(maxWindowRows)) + [mk("99", 3099, cores: 5)])
    check(back.count == maxWindowRows && back[2].appId == "12" && back[2].present && !back.contains(where: { $0.appId == "99" }), "at the cap, an absent app that returns keeps its slot: a new app in the same refresh does not overwrite it")
    check(!clickAllowed(lastLayout: 100.0, now: 100.3) && clickAllowed(lastLayout: 100.0, now: 100.8), "a click right after a re-layout is ignored")
    check(!buttonRefusesFocus(.wait) && buttonRefusesFocus(.ignore) && buttonRefusesFocus(.quitAll) && buttonRefusesFocus(nil), "only Wait may take keyboard focus; row buttons never")

    // Freeze (PR 3c): the buttons, the argv lists, the frozen list
    let fzJson = """
    {"v":1,"t":100,"header":{},"holds":[],"more":0,"protected_hidden":0,"rss_trigger":false,"freeze":{"enabled":true,"default_minutes":15},
     "rows":[{"app_id":"812","name":"Slack","bundle_id":"com.tinyspeck.slackmacgap","bundle_path":"/Applications/Slack.app","root_pid":812,"root_start":"Fri Nov 14 18:02:11 2026","root_start_epoch":1794765731,"cores_5m":1.8,"cpu_now":1.9,"rss_mb":3170,"present":true,"hosts_build":false,"frozen":false},
             {"app_id":"9","name":"Gone","bundle_id":"x","bundle_path":"/Applications/Gone.app","root_pid":9,"root_start":"","root_start_epoch":null,"cores_5m":0.3,"cpu_now":0,"rss_mb":0,"present":false,"hosts_build":false,"frozen":false},
             {"app_id":"7","name":"IDE","bundle_id":"y","bundle_path":"/Applications/IDE.app","root_pid":7,"root_start":"s","root_start_epoch":5,"cores_5m":0.3,"cpu_now":0,"rss_mb":900,"present":true,"hosts_build":true,"frozen":false}]}
    """
    if let fs = parseSnapshot(Data(fzJson.utf8)) {
        check(fs.freezeEnabled && fs.freezeMinutes == 15, "the snapshot carries [freeze] enabled and default_minutes")
        check(rowFreezeAllowed(fs.rows[0], fs), "a present, idle-identity row offers Freeze")
        check(!rowFreezeAllowed(fs.rows[1], fs), "a row absent from the newest sample gets no Freeze button (carry-over d)")
        check(!rowFreezeAllowed(fs.rows[2], fs), "a build-hosting row gets no Freeze button")
        var off = fs; off.freezeEnabled = false
        check(!rowFreezeAllowed(off.rows[0], off), "[freeze] enabled = false hides the Freeze buttons")
        let marked = markFrozen(fs.rows, rootPids: [812])
        check(marked[0].frozen && !marked[1].frozen && !rowActionsAllowed(marked[0]) && !rowFreezeAllowed(marked[0], fs), "a frozen row offers no Quit, Force Quit or Freeze")
        check(rowNote(marked[0]) == "frozen: use Resume below", "a frozen row says so")
        check(quitAllTargets(marked).isEmpty, "Quit All never targets a frozen row")
    } else { check(false, "the freeze snapshot parses") }
    check(parseSnapshot(Data("{\"v\":1,\"rows\":[]}".utf8))?.freezeEnabled == false, "a snapshot without a freeze block hides Freeze")
    check(freezeArgv(row, minutes: 10) == ["freeze", "--pid=812", "--start=Fri Nov 14 18:02:11 2026", "--bundle-id=com.tinyspeck.slackmacgap", "--bundle-path=/Applications/Slack.app", "--minutes=10", "--by", "dialog"], "timed freeze argv")
    check(freezeArgv(row, minutes: nil).contains("--indefinite") && !freezeArgv(row, minutes: nil).contains(where: { $0.hasPrefix("--minutes") }), "indefinite freeze argv")
    check(resumeArgv("e1", by: "menubar") == ["resume", "--entry=e1", "--by", "menubar"] && thawDueArgv(by: "menubar") == ["thaw", "--due", "--stale", "--by", "menubar"] && resumeAllArgv(by: "menubar") == ["resume", "--all", "--by", "menubar"] && frozenArgv() == ["frozen", "--json"], "resume and frozen argv")
    let frozenJson = """
    {"v":1,"notes":[],"entries":[{"id":"a1","state":"frozen","app":{"name":"Sl\\u200back","bundle_id":"c"},"mode":"timed","by":"dialog","frozen_at":1,"thaw_at":1000,"root_pid":812,"members":5,"alive":true,"kept_running":0},
                                 {"id":"","state":"frozen","app":{},"root_pid":3},
                                 {"id":"b2","state":"frozen","app":{"name":"X"},"mode":"indefinite","thaw_at":null,"root_pid":900,"members":1,"alive":false}]}
    """
    let fe = parseFrozen(Data(frozenJson.utf8))
    check(fe?.count == 2 && fe?[0].name == "Slack" && fe?[0].thawAt == 1000 && fe?[1].thawAt == nil && fe?[1].alive == false, "the frozen list parses, drops an entry without an id and sanitizes names")
    check(parseFrozenRoots(Data(frozenJson.utf8)) == [812, 3, 900], "the frozen root pids parse")
    check(parseFrozen(Data("{\"v\":2}".utf8)) == nil && parseFrozen(Data("nope".utf8)) == nil, "another version or garbage is refused")
    if let f0 = fe?.first, let f1 = fe?.last {
        check(thawText(f1, now: 0) == "until you Resume", "an indefinite freeze says until you Resume")
    }
    // The resume time is a clock time (no countdown), New York 12-hour AM/PM, a 3-letter day name when not today; the zone is passed so the check never depends on this Mac's zone.
    let clockJson = "{\"v\":1,\"entries\":[{\"id\":\"c1\",\"state\":\"frozen\",\"app\":{\"name\":\"X\"},\"mode\":\"timed\",\"thaw_at\":1794711120,\"root_pid\":5,\"members\":1,\"alive\":true}]}"
    if let c = parseFrozen(Data(clockJson.utf8))?.first, let ny = TimeZone(identifier: "America/New_York"), let utc = TimeZone(identifier: "UTC") {
        check(thawText(c, now: 1794704400, zone: ny) == "resumes at 9:52 PM", "same day in New York: no day name")
        check(thawText(c, now: 1794582000, zone: ny) == "resumes at Sat 9:52 PM", "another day in New York: a 3-letter day name")
        check(thawText(c, now: 1794704400, zone: utc) == "resumes at 2:52 AM" && thawText(c, now: 1794582000, zone: utc) == "resumes at Sun 2:52 AM", "the zone is the parameter, never this Mac's")
        check(thawText(c, now: 1794704400, zone: ny) == thawText(c, now: 1794704460, zone: ny), "no countdown: the text does not change between refreshes")
        let far = parseFrozen(Data(clockJson.replacingOccurrences(of: "1794711120", with: "999999999999999").utf8))?.first
        let edge = { (secs: Int) -> String? in parseFrozen(Data(clockJson.replacingOccurrences(of: "1794711120", with: String(1794704400 + secs)).utf8))?.first.map { thawText($0, now: 1794704400, zone: ny) } }
        check(edge(clockSpanS) != "resumes at ?" && edge(clockSpanS + 1) == "resumes at ?" && edge(-clockSpanS) != "resumes at ?" && edge(-clockSpanS - 1) == "resumes at ?", "the 7-day guard: exactly 7 days shows a time, one second more shows ?")
        check(far.map { thawText($0, now: 1794704400, zone: ny) == "resumes at ?" } == true, "a far-off resume time shows ?, never a made-up clock time or an empty one")
    } else { check(false, "the clock-time entry parses") }
    let stRows = markFrozen(mergeRows(old: [], new: [mk("1", 1001, cores: 2), mk("2", 1002, cores: 1)]), rootPids: [1001])
    let stKept = clearStaleFrozen(["1": "frozen", "2": "frozen", "3": "frozen", "9": "quitting…"], rows: stRows)
    check(stKept["1"] == "frozen" && stKept["2"] == nil && stKept["3"] == nil && stKept["9"] == "quitting…", "a stale 'frozen' label is dropped once the row is not frozen; other labels stay")
    check(dialogStyleMask.contains(.miniaturizable) && dialogStyleMask.contains(.closable) && dialogStyleMask.contains(.titled) && dialogWindowLevel == .floating, "the window can be minimized and closed and floats")
    check(!thawDueTick(0) && !thawDueTick(9) && thawDueTick(10) && !thawDueTick(11) && thawDueTick(20), "the dialog re-runs thaw --due every 10th 2 s tick")
    check(statusTitle(0) == "" && statusTitle(2) == "❄︎ 2", "menu-bar title")

    // identity (D4, F3)
    let ok = LiveProc(pid: 812, startEpoch: 1794765731, bundleId: "com.tinyspeck.slackmacgap", launchEpoch: 1794765732)
    check(identityMatches(row, ok).ok, "the same process matches")
    check(!identityMatches(row, nil).ok, "a gone process does not match")
    var bad = ok; bad.pid = 813
    check(!identityMatches(row, bad).ok, "another pid does not match")
    bad = ok; bad.startEpoch = 1794765731 + 60
    check(!identityMatches(row, bad).ok, "a reused pid (other start time) does not match")
    bad = ok; bad.startEpoch = 1794765732
    check(identityMatches(row, bad).ok, "one second of start-time slack is allowed")
    bad = ok; bad.startEpoch = nil
    check(!identityMatches(row, bad).ok, "an unknown start time refuses")
    bad = ok; bad.bundleId = "com.evil.app"
    check(!identityMatches(row, bad).ok, "another bundle id does not match")
    bad = ok; bad.launchEpoch = nil
    check(!identityMatches(row, bad).ok, "a nil launch date refuses")
    bad = ok; bad.launchEpoch = 1794765731 + 600
    check(!identityMatches(row, bad).ok, "a launch date far from the start refuses")
    var noEpoch = row; noEpoch.rootStartEpoch = nil
    check(!identityMatches(noEpoch, ok).ok, "a row without a start epoch never matches")
    check(liveStartEpoch(Int(getpid())) != nil, "proc_pidinfo reads this process's start time")

    // Button handling (2026-11-21): rapid Freeze clicks on several rows. One window-wide grace clock swallowed every click after the first (the click's own
    // rebuild restarted it); the grace is now per control group and restarts only when that group's own layout changes.
    var g = ClickGrace()
    let snap0 = Snapshot(t: 0, load: nil, ncpu: nil, cpu5m: nil, holds: [], rows: [], more: 0, protectedHidden: 0, rssTrigger: false)
    for (i, id) in ["a", "b", "c"].enumerated() { g.note("row:" + id, sig: "\(i)|-|true", now: 100.0) }
    check(!g.allowed("row:a", now: 100.3) && !g.allowed("row:b", now: 100.3), "a click right after the first layout is ignored, per row")
    check(g.allowed("row:a", now: 100.8) && g.allowed("row:b", now: 100.8) && g.allowed("row:c", now: 100.8), "after the grace every row accepts a click")
    g.note("row:a", sig: "0|-|true", now: 101.0)   // row a's click made the window redraw "freezing…": the same layout
    check(g.allowed("row:b", now: 101.1) && g.allowed("row:c", now: 101.1) && g.allowed("row:a", now: 101.1), "a redraw with the same layout restarts nobody's grace: the second and third Freeze clicks get through")
    g.note("row:a", sig: "0|frozen: use Resume below|false", now: 102.0)   // row a became frozen: its buttons are gone, its layout changed
    check(!g.allowed("row:a", now: 102.2) && g.allowed("row:b", now: 102.2), "a row whose own layout changed has a fresh grace; the other rows are unaffected")
    check(!g.allowed("row:never-drawn", now: 200.0), "a key that was never laid out is never allowed")
    g.keepOnly(["row:b"])
    check(g.allowed("row:b", now: 200.0) && !g.allowed("row:a", now: 200.0), "a group that left the screen is forgotten")
    check(rowLayoutSig(row, index: 2, snap0) == rowLayoutSig(row, index: 2, snap0) && rowLayoutSig(row, index: 2, snap0) != rowLayoutSig(row, index: 3, snap0), "a row's layout signature changes with its position")
    let keptJson = """
    {"v":1,"entries":[{"id":"k1","state":"frozen","app":{"name":"CodexBar"},"mode":"timed","by":"auto","thaw_at":1000,"root_pid":5,"members":1,"alive":true,"kept":["CodexBarCLI","x\\u202ey"]},
                      {"id":"k2","state":"frozen","app":{"name":"Plain"},"mode":"timed","by":"dialog","thaw_at":1000,"root_pid":6,"members":1,"alive":true}]}
    """
    let ke = parseFrozen(Data(keptJson.utf8))
    check(ke?.first?.by == "auto" && ke?.first?.kept == ["CodexBarCLI", "xy"], "the frozen list carries who froze it and the processes the keep-running rule left running (sanitized)")
    check(ke.flatMap { frozenKeptText($0[0]) } == "frozen automatically · keeps running: CodexBarCLI, xy" && ke.flatMap { frozenKeptText($0[1]) } == nil, "the Frozen line says so, and says nothing for a plain click freeze")

    if failed.isEmpty { print("ade-gui-hog self-test: ok (\(n) checks)"); return 0 }
    for f in failed { print("FAIL: \(f)") }
    print("ade-gui-hog self-test: \(failed.count) of \(n) failed")
    return 1
}
