// StatusItem.swift: the menu-bar item of E5 (PR 3c), started by the sampler with `--status-only` while anything is frozen. No window: a status item
// titled "❄︎ N" whose menu lists each frozen app with a Resume item and one Resume All. It only ever resumes (it cannot freeze or quit anything), asks the
// Python core what is frozen (`gui-hog frozen --json`) every 5 s, and exits by itself when nothing is frozen any more (two empty reads in a row) or the
// core has not answered for a minute. Every name is cleaned text (J3).
import AppKit
import Foundation

final class StatusApp: NSObject, NSApplicationDelegate, NSMenuDelegate {
    let cfg: Config
    let runner: Runner
    var item: NSStatusItem!
    var entries: [FrozenEntry] = []
    var timer: Timer?
    var empty = 0
    var failed = 0
    var busy = false
    var note = ""
    var ticks = 0
    var thawing = false

    init(_ cfg: Config) { self.cfg = cfg; self.runner = Runner(cfg) }

    func applicationDidFinishLaunching(_ n: Notification) {
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.title = "❄︎"
        item.button?.toolTip = "ADE GUI Hog: frozen apps"
        rebuildMenu()
        thawDue()
        poll()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            self.ticks += 1
            if self.ticks % 4 == 0 { self.thawDue() }   // F5a: a second clock, every 20 s, independent of the sampler (F5f: a stopped sampler)
            self.poll()
        }
    }

    /// `gui-hog thaw --due --stale` off the main thread, never overlapping itself. Resumes what is due; the Python core owns every check.
    func thawDue() {
        if thawing { return }
        thawing = true
        DispatchQueue.global().async {
            self.runner.thawDue(by: "menubar")
            DispatchQueue.main.async { self.thawing = false; self.poll() }
        }
    }

    func poll() {
        if busy { return }
        busy = true
        DispatchQueue.global().async {
            let res = self.runner.frozen()
            DispatchQueue.main.async {
                self.busy = false
                if let r = res {
                    self.failed = 0
                    self.entries = r.entries
                    self.empty = r.entries.isEmpty ? self.empty + 1 : 0
                } else {
                    self.failed += 1
                }
                if self.empty >= 2 || self.failed >= 12 { exit(0) }
                self.rebuildMenu()
            }
        }
    }

    func rebuildMenu() {
        item.button?.title = entries.isEmpty ? "❄︎" : statusTitle(entries.count)
        let menu = NSMenu()
        let head = NSMenuItem(title: entries.isEmpty ? "Nothing is frozen" : "Frozen apps (stopped, not quit)", action: nil, keyEquivalent: "")
        head.isEnabled = false
        menu.addItem(head)
        let now = Int(Date().timeIntervalSince1970)
        for e in entries {
            let m = NSMenuItem(title: "Resume \(e.name): \(e.alive ? thawText(e, now: now) : "root is gone")", action: #selector(resumeOne(_:)), keyEquivalent: "")
            m.target = self
            m.representedObject = e.id   // the entry's id, not its index: a poll can replace `entries` while the menu is open (A7)
            menu.addItem(m)
        }
        if entries.count > 1 {
            menu.addItem(NSMenuItem.separator())
            let all = NSMenuItem(title: "Resume All", action: #selector(resumeAll(_:)), keyEquivalent: "")
            all.target = self
            menu.addItem(all)
        }
        if !note.isEmpty {
            menu.addItem(NSMenuItem.separator())
            let n = NSMenuItem(title: note, action: nil, keyEquivalent: "")
            n.isEnabled = false
            menu.addItem(n)
        }
        item.menu = menu
    }

    func run(_ id: String?) {
        note = "resuming…"
        rebuildMenu()
        DispatchQueue.global().async {
            let ok = self.runner.resume(id, by: "menubar")
            DispatchQueue.main.async {
                self.note = ok ? "" : "could not resume: run `gui-hog thaw --all`"
                self.poll()
            }
        }
    }

    @objc func resumeOne(_ sender: NSMenuItem) {
        guard let id = sender.representedObject as? String, !id.isEmpty else { return }
        run(id)
    }

    @objc func resumeAll(_ sender: NSMenuItem) { run(nil) }
}
