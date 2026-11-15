// UI.swift: the window (E1-E4). Plain NSTextField.stringValue for every untrusted string (J3), NSStackView layout, no key equivalents anywhere on the
// main window, Return/Escape swallowed. Buttons: per row Quit and Force Quit… (a confirm sheet whose default is Cancel); bottom Wait (leftmost, the
// initial first responder, does nothing), Ignore 1 h, Quit All… (a confirm sheet, Cancel default). No Freeze here (PR 3c).
import AppKit
import Foundation

final class GuardedWindow: NSWindow {
    override func performKeyEquivalent(with event: NSEvent) -> Bool {
        if event.type == .keyDown && swallowsKey(event.keyCode) { return true }
        return super.performKeyEquivalent(with: event)
    }
    override func keyDown(with event: NSEvent) {
        if swallowsKey(event.keyCode) { return }
        super.keyDown(with: event)
    }
    override func cancelOperation(_ sender: Any?) {}
}

final class Dialog: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let cfg: Config
    let runner: Runner
    var window: GuardedWindow!
    var root = NSStackView()
    var waitButton: NSButton?
    var snap = Snapshot(t: 0, load: nil, ncpu: nil, cpu5m: nil, holds: [], rows: [], more: 0, protectedHidden: 0, rssTrigger: false)
    var rows: [Row] = []        // the rows on screen: first-seen order, never re-sorted (mergeRows)
    var lastLayout = Date()     // when the buttons were last laid out (clickAllowed)
    var lastBytes = Data()
    var status: [String: String] = [:]
    var acted = false
    var noHoldSince: Date?
    var timer: Timer?
    let autoCloseS = 120.0            // E4 (K4): close 2 min after the hold ends
    let rowHeight: CGFloat = 36       // every row is this tall, whatever it shows
    let statusWidth: CGFloat = 260    // the note or status label never changes the window width
    let rootWidth: CGFloat = 1010     // the window width is fixed (required constraint): a sheet never re-centres under the pointer
    let rowAreaWidth: CGFloat = 978   // inner width of the lines below and above the rows

    init(_ cfg: Config) { self.cfg = cfg; self.runner = Runner(cfg) }

    func applicationDidFinishLaunching(_ n: Notification) {
        window = GuardedWindow(contentRect: NSRect(x: 0, y: 0, width: 760, height: 300), styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = cfg.demo ? "ADE GUI Hog (demo)" : "A build is waiting: desktop apps are busy"
        window.level = .floating
        window.isReleasedWhenClosed = false
        window.delegate = self
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = 8
        root.edgeInsets = NSEdgeInsets(top: 16, left: 16, bottom: 16, right: 16)
        root.widthAnchor.constraint(equalToConstant: rootWidth).isActive = true   // required priority: the window never grows or shrinks sideways
        window.contentView = root
        refresh(force: true)
        window.center()
        // A window the sampler opens must not take the keyboard from whatever the operator is typing into (adversary round 1, finding 2):
        // it is shown at the floating level without activating the app. A click on it activates it. The operator's own `show`/`demo` activates.
        if cfg.manual || cfg.demo {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            if let w = waitButton { window.makeFirstResponder(w) }
        } else {
            window.orderFrontRegardless()
        }
        timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in self?.refresh(force: false) }
    }

    // The red close button is Wait: it leaves with no action of its own.
    func windowShouldClose(_ sender: NSWindow) -> Bool { finish(0); return false }

    // MARK: snapshot refresh (D3, E4)

    func refresh(force: Bool) {
        let url = URL(fileURLWithPath: cfg.stateDir).appendingPathComponent("gui-hog/snapshot.json")
        if let h = try? FileHandle(forReadingFrom: url) {
            let data = (try? h.read(upToCount: 1_000_000)) ?? Data()
            try? h.close()
            if (force || data != lastBytes), let s = parseSnapshot(data) { snap = s; rows = mergeRows(old: rows, new: s.rows); lastBytes = data; rebuild() }
        }
        if snap.holds.isEmpty && !cfg.manual && !cfg.demo {
            if noHoldSince == nil { noHoldSince = Date(); rebuild() }
            if let t = noHoldSince, Date().timeIntervalSince(t) >= autoCloseS { finish(0) }
        } else if noHoldSince != nil { noHoldSince = nil; rebuild() }
    }

    // MARK: layout (E1-E3)

    func label(_ text: String, size: CGFloat = 13, weight: NSFont.Weight = .regular, color: NSColor = .labelColor, width: CGFloat? = nil, align: NSTextAlignment = .left) -> NSTextField {
        let l = NSTextField(labelWithString: text)   // plain stringValue: never attributed or HTML (J3)
        l.font = .systemFont(ofSize: size, weight: weight)
        l.textColor = color
        l.alignment = align
        l.lineBreakMode = .byTruncatingTail
        l.maximumNumberOfLines = 1
        if let w = width { l.widthAnchor.constraint(equalToConstant: w).isActive = true }
        return l
    }

    func button(_ title: String, tag: Int, action: Selector, enabled: Bool = true) -> NSButton {
        let b = NSButton(title: title, target: self, action: action)
        b.tag = tag
        b.keyEquivalent = ""
        b.isEnabled = enabled
        b.refusesFirstResponder = true   // only Wait takes focus (buttonRefusesFocus): Tab then Space can press nothing else
        return b
    }

    func rebuild() {
        for v in root.arrangedSubviews { root.removeArrangedSubview(v); v.removeFromSuperview() }
        // Everything above the rows is one fixed line, and every row has a fixed height: nothing a click could be aimed at ever moves when a build
        // is held or released (adversary round 2, finding 1). The hold lines and notices sit BELOW the rows.
        root.addArrangedSubview(label(headerLine(snap), size: 14, weight: .semibold, width: rowAreaWidth))
        root.addArrangedSubview(NSBox.separator())
        let head = NSStackView(views: [label("App", size: 11, color: .secondaryLabelColor, width: 250), label("cores (5 min)", size: 11, color: .secondaryLabelColor, width: 85, align: .right),
                                       label("CPU now", size: 11, color: .secondaryLabelColor, width: 70, align: .right), label("RAM", size: 11, color: .secondaryLabelColor, width: 70, align: .right)])
        head.spacing = 10
        root.addArrangedSubview(head)
        for (i, r) in rows.enumerated() {
            let note = rowNote(r)
            let dim: NSColor = note == nil ? .labelColor : .tertiaryLabelColor
            let nameBox = NSStackView(views: [label(r.name, weight: .medium, color: dim), label(r.bundleId.isEmpty ? "no bundle id" : r.bundleId, size: 10, color: .secondaryLabelColor)])
            nameBox.orientation = .vertical
            nameBox.alignment = .leading
            nameBox.spacing = 0
            nameBox.widthAnchor.constraint(equalToConstant: 250).isActive = true
            var views: [NSView] = [nameBox, label(fmtCores(r.cores5m), color: dim, width: 85, align: .right), label(fmtCPU(r.cpuNow), color: dim, width: 70, align: .right),
                                   label(fmtRAM(r.rssMb), color: dim, width: 70, align: .right)]
            if let n = note {
                views.append(label(n, size: 11, color: .secondaryLabelColor, width: statusWidth))
            } else {
                views.append(button("Quit", tag: i, action: #selector(quitPressed(_:))))
                views.append(button("Force Quit…", tag: i, action: #selector(forcePressed(_:))))
                views.append(label(status[r.appId] ?? "", size: 11, color: .secondaryLabelColor, width: statusWidth))
            }
            let line = NSStackView(views: views)
            line.spacing = 10
            line.alignment = .centerY
            line.heightAnchor.constraint(equalToConstant: rowHeight).isActive = true
            line.clipsToBounds = true   // an app-controlled name in a tall-fonted script can never draw over, or push, a neighbouring row
            line.setClippingResistancePriority(.defaultLow, for: .vertical)
            root.addArrangedSubview(line)
        }
        var foot: [String] = []
        if snap.more > 0 { foot.append("+\(snap.more) more") }
        if snap.protectedHidden > 0 { foot.append("\(snap.protectedHidden) protected apps hidden") }
        if !foot.isEmpty { root.addArrangedSubview(label(foot.joined(separator: " · "), size: 11, color: .secondaryLabelColor, width: rowAreaWidth)) }
        root.addArrangedSubview(NSBox.separator())
        if cfg.demo {
            root.addArrangedSubview(label("DEMO: these apps are made up; no button touches anything.", color: .systemOrange, width: rowAreaWidth))
        } else if snap.holds.isEmpty {
            root.addArrangedSubview(label(cfg.manual ? "Opened by hand: no build is waiting." : "No build is waiting now.", color: .secondaryLabelColor, width: rowAreaWidth))
        }
        for h in snap.holds { root.addArrangedSubview(label(holdLine(h), color: .secondaryLabelColor, width: rowAreaWidth)) }
        var bottom: [NSView] = []
        for (i, spec) in bottomButtons.enumerated() {
            let b = button(spec.title, tag: i, action: #selector(bottomPressed(_:)), enabled: !(spec.action == .quitAll && quitAllTargets(rows).isEmpty))
            b.keyEquivalent = spec.keyEquivalent
            b.refusesFirstResponder = buttonRefusesFocus(spec.action)
            if spec.action == .wait { waitButton = b }
            bottom.append(b)
        }
        let bar = NSStackView(views: bottom)
        bar.spacing = 12
        root.addArrangedSubview(bar)
        window?.layoutIfNeeded()
        if let w = window, let c = w.contentView {
            let topLeft = NSPoint(x: w.frame.minX, y: w.frame.maxY)   // a resize keeps the TOP-left fixed, so the rows above never move
            w.setContentSize(c.fittingSize)
            if w.isVisible { w.setFrameTopLeftPoint(topLeft) }
        }
        if let w = waitButton, window?.isKeyWindow == true { window?.makeFirstResponder(w) }
        lastLayout = Date()
    }

    // MARK: actions

    func finish(_ requested: Int32) {
        timer?.invalidate()
        var code = requested
        if code == 0 && acted { code = 4 }   // D5: closed after Quit All or row actions
        if !cfg.demo { _ = runner.gui(exitArgv(code), timeout: 5) }
        exit(code)
    }

    @objc func bottomPressed(_ sender: NSButton) {
        guard sender.tag >= 0 && sender.tag < bottomButtons.count else { return }
        if bottomButtons[sender.tag].action != .wait && !clickAllowed(lastLayout: lastLayout.timeIntervalSince1970, now: Date().timeIntervalSince1970) { return }
        for e in effects(for: bottomButtons[sender.tag].action) {
            switch e {
            case .close(let c): finish(c)
            case .run(let argv): if !cfg.demo { _ = runner.gui(argv, timeout: 10) }
            case .confirmQuitAll: confirmQuitAll()
            }
        }
    }

    func refusal(_ v: VetResult) -> String {
        switch v.code {
        case 3: return "protected or part of a build: no actions"
        case 4: return "refused: the app changed since this window was drawn"
        case 5: return "has a terminal or build inside: no actions"
        default: return "refused: could not check it" + (v.reason.isEmpty ? "" : " (\(v.reason))")
        }
    }

    /// vet (off the main thread) -> identity re-check and terminate (main thread). `done` runs on the main thread when this row is finished.
    func quit(_ r: Row, kind: QuitKind, done: @escaping () -> Void) {
        status[r.appId] = "checking…"
        rebuild()
        DispatchQueue.global().async {
            let v = self.runner.vet(r)
            DispatchQueue.main.async {
                if v.code != 0 { self.status[r.appId] = self.refusal(v) } else {
                    let res = performQuit(r, kind: kind, demo: self.cfg.demo)
                    self.status[r.appId] = res.text
                    if res.ok {
                        self.acted = true
                        self.runner.log(kind == .polite ? "quit" : "force-quit", r)
                        if kind == .polite, let app = res.app { self.watch(r, app) }
                    }
                }
                self.rebuild()
                done()
            }
        }
    }

    /// G1: terminate() can return before the app exits: watch isTerminated; after 30 s say it may be asking to save. No escalation.
    func watch(_ r: Row, _ app: NSRunningApplication) {
        var ticks = 0
        Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { t in
            ticks += 1
            if app.isTerminated { self.status[r.appId] = "quit"; t.invalidate(); self.rebuild() }
            else if ticks >= 30 { self.status[r.appId] = "still running (it may be asking to save)"; t.invalidate(); self.rebuild() }
        }
    }

    @objc func quitPressed(_ sender: NSButton) {
        guard sender.tag >= 0 && sender.tag < rows.count, clickAllowed(lastLayout: lastLayout.timeIntervalSince1970, now: Date().timeIntervalSince1970) else { return }
        let r = rows[sender.tag]
        guard rowActionsAllowed(r) else { return }
        quit(r, kind: .polite) {}
    }

    @objc func forcePressed(_ sender: NSButton) {
        guard sender.tag >= 0 && sender.tag < rows.count, clickAllowed(lastLayout: lastLayout.timeIntervalSince1970, now: Date().timeIntervalSince1970) else { return }
        let r = rows[sender.tag]
        guard rowActionsAllowed(r) else { return }
        let a = NSAlert()
        a.alertStyle = .warning
        a.messageText = "Force Quit \(r.name)?"
        a.informativeText = "Any unsaved work in \(r.name) is lost. This is the same as Force Quit in Activity Monitor."
        a.addButton(withTitle: "Cancel")          // first button = the default (Return); Escape also means Cancel
        a.addButton(withTitle: "Force Quit")
        a.buttons[1].hasDestructiveAction = true
        a.buttons[1].refusesFirstResponder = true   // Tab then Space cannot reach Force Quit
        a.window.initialFirstResponder = a.buttons[0]
        a.beginSheetModal(for: window) { resp in
            if resp == .alertSecondButtonReturn { self.quit(r, kind: .force) {} }
        }
    }

    func confirmQuitAll() {
        let targets = quitAllTargets(rows)
        guard !targets.isEmpty else { return }
        let a = NSAlert()
        a.alertStyle = .warning
        a.messageText = "Quit \(targets.count) app\(targets.count == 1 ? "" : "s")?"
        a.informativeText = targets.map { "• " + $0.name }.joined(separator: "\n") + "\n\nEach app is asked to quit normally and may show its own save sheet. Nothing is force quit."
        a.addButton(withTitle: "Cancel")          // the default
        a.addButton(withTitle: "Quit \(targets.count)")
        a.buttons[1].refusesFirstResponder = true
        a.window.initialFirstResponder = a.buttons[0]
        a.beginSheetModal(for: window) { resp in
            guard resp == .alertSecondButtonReturn else { return }
            var rest = targets
            func next() { if rest.isEmpty { return }; let r = rest.removeFirst(); self.quit(r, kind: .polite) { next() } }
            next()
        }
    }
}

extension NSBox {
    static func separator() -> NSBox {
        let b = NSBox()
        b.boxType = .separator
        b.widthAnchor.constraint(equalToConstant: 978).isActive = true
        return b
    }
}
