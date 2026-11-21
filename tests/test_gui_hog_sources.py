"""Load sources: what actually uses the cores (docs/gui-hog-dialog.md Q2, operator ruling 2026-11-21). Pure data and a fake process table: nothing here
signals, stops or quits anything, and no live state file is touched."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import gui_hog as gh  # noqa: E402
import gui_hog_sources as gs  # noqa: E402

ME = os.getuid()
T0 = 1_800_000_000.0
NOLOCAL = Path("/nonexistent")
SLACK, GHOSTTY = "/Applications/Slack.app/Contents/MacOS/Slack", "/Applications/Ghostty.app/Contents/MacOS/ghostty"


def cfg():
    return gh.load_config(path=NOLOCAL, local=NOLOCAL)


def app(pid, name, members, **kw):
    a = {"id": str(pid), "name": name, "bundle_id": f"com.example.{name.lower()}", "member_pids": list(members), "kept_pids": [], "build_pids": [],
         "protected": None, "excluded": None, "hosts_build": False}
    a.update(kw)
    return a


def table():
    """launchd; Slack (10, 11); Ghostty (50) with a login shell tree inside (51 login, 52 zsh, 53 cargo); claude (20) with a bgrun build (21 -> 22 pytest -> 23 rustc)
    and an MCP server (24); kernel_task (30) and a mdworker child pair (31, 32); a held `admit` (40)."""
    rows = {1: (0, 0, 0.0, "/sbin/launchd"), 10: (1, ME, 0.5, SLACK), 11: (10, ME, 0.5, SLACK + " Helper"),
            50: (1, ME, 0.1, GHOSTTY), 51: (50, ME, 0.01, "login -fp djbclark"), 52: (51, ME, 0.01, "-zsh"), 53: (52, ME, 2.0, "cargo build --token SECRET-ARG"),
            20: (1, ME, 0.3, "node /opt/bin/claude --resume"), 21: (20, ME, 0.1, "/bin/bash /Users/x/ops/bin/bgrun bin/pytest tests/secretdir"),
            22: (21, ME, 1.5, "python3 -m pytest tests/secretdir"), 23: (22, ME, 3.0, "/Users/x/.cargo/bin/rustc --crate-name y"),
            24: (20, ME, 0.2, "node /opt/mcp/server.js"), 30: (1, 0, 0.8, "/usr/libexec/kernel_task"), 31: (1, ME, 0.1, "/usr/sbin/mdworker"),
            32: (31, ME, 0.1, "/usr/sbin/mdworker --child"), 40: (1, ME, 0.0, "/usr/bin/python3 /x/bin/load-watch admit --wait")}
    return {str(p): v for p, v in rows.items()}


def apps():
    return [app(10, "Slack", [10, 11]),
            app(50, "Ghostty", [50], protected="cfg:bundle-id", hosts_build=True, build_pids=[51, 52, 53])]


def sources(held=("40",)):
    t = table()
    return {s["key"]: s for s in gs.group_sources(t, {p: 1024 for p in t}, apps(), held_pids=held, agent_clis={"claude", "bg"})}


def test_every_process_lands_in_one_source_and_cores_add_up():
    t = table()
    src = sources()
    assert round(sum(s["cores"] for s in src.values()), 6) == round(sum(v[2] for v in t.values()), 6)
    assert sum(s["procs"] for s in src.values()) == len(t)


def test_a_build_tree_is_grouped_under_its_root_with_its_owning_agent():
    b = sources()["build:21"]
    assert (b["kind"], b["name"], b["procs"], b["owner"], b["owner_pid"]) == ("build", "bgrun", 3, "claude", 20)
    assert round(b["cores"], 2) == 4.6 and b["heaviest"] == "rustc" and round(b["heaviest_cores"], 2) == 3.0   # pytest and rustc joined the bgrun root
    ag = sources()["agent:20"]
    assert (ag["kind"], ag["name"], ag["procs"]) == ("agent", "claude", 2) and round(ag["cores"], 2) == 0.5   # the MCP server stays with the agent


def test_a_terminal_inside_a_protected_app_is_its_own_build_source_not_the_apps():
    s = sources()
    term = s["build:51"]
    assert term["kind"] == "build" and term["name"] == "terminal session (login)" and term["procs"] == 3 and round(term["cores"], 2) == 2.02
    g = s["app:50"]
    assert g["kind"] == "app" and round(g["cores"], 2) == 0.1 and g["protected"] and g["hosts_build"]   # its cores do not include the shell tree


def test_a_held_admit_is_a_waiting_build_and_unclaimed_processes_group_by_name():
    s = sources()
    assert s["build:40"]["waiting"] and s["build:40"]["name"] == "admit" and s["build:40"]["cores"] == 0.0
    assert not s["build:21"]["waiting"]
    assert s["system:mdworker"]["procs"] == 2 and round(s["system:mdworker"]["cores"], 2) == 0.2 and s["system:kernel_task"]["kind"] == "system"
    assert "build:40" not in sources(held=())   # without the hold registry it is just another python process


def test_no_command_line_argument_leaves_the_module():
    blob = json.dumps(list(sources().values()), default=str)
    for secret in ("SECRET-ARG", "secretdir", "--resume", "--wait", "crate-name"):
        assert secret not in blob


def test_only_an_unprotected_app_that_hosts_nothing_can_be_frozen():
    s, c = sources(), cfg()
    assert gs.can_freeze(s["app:10"], c) == (True, "")
    for key, why in (("build:21", "a build or test job"), ("agent:20", "an agent session"), ("system:kernel_task", "a system process"),
                     ("app:50", "protected app: never frozen"), ("build:51", "a build or test job")):
        ok, text = gs.can_freeze(s[key], c)
        assert not ok and text == why, key
    assert gs.can_freeze(dict(s["app:10"], hosts_build=True), c)[1] == "has a terminal or build inside: never frozen"
    assert gs.can_freeze(dict(s["app:10"], excluded="agent-ancestor"), c)[1] == "part of a build: never frozen"
    c["freeze"]["enabled"] = False
    assert gs.can_freeze(s["app:10"], c) == (False, "freeze is turned off")


def feed(gs_state, n, per_tick=None, t0=T0):
    """n samples 20 s apart of the whole table."""
    c = cfg()
    for i in range(n):
        srcs = gs.group_sources(table(), {p: 1024 for p in table()}, apps(), held_pids=("40",), agent_clis={"claude"})
        if per_tick:
            per_tick(i, srcs)
        gs.window_update(gs_state, t0 + i * 20, srcs, sum(v[2] for v in table().values()), c)
    return c


def test_the_window_mean_share_and_presence():
    st = {}
    c = feed(st, 3)
    means = {m["key"]: m for m in gs.window_means(st, T0 + 40, c)}
    b = means["build:21"]
    assert round(b["cores_5m"], 2) == 4.6 and b["present"] and b["owner"] == "claude" and b["kind"] == "build"
    assert round(b["share"], 3) == round(4.6 / sum(v[2] for v in table().values()), 3)
    # the build ends: a later sample without it keeps its mean over the window but marks it gone
    st2 = {}
    c = feed(st2, 2)
    gs.window_update(st2, T0 + 40, [s for s in gs.group_sources(table(), {}, apps(), agent_clis={"claude"}) if s["key"] != "build:21"], 8.0, c)
    m = {x["key"]: x for x in gs.window_means(st2, T0 + 40, c)}["build:21"]
    assert not m["present"] and m["rss_mb"] == 0 and m["cpu_now"] == 0.0 and round(m["cores_5m"], 2) == round(4.6 * 2 / 3, 2)


def test_a_corrupt_window_is_ignored_not_fatal():
    c = cfg()
    assert gs.window_means({"srcwin": "x", "srcmeta": [1]}, T0, c) == []
    st = {"srcwin": [{"t": T0, "cpu": 1, "s": {"build:1": [float("nan"), 5]}}, {"t": "bad"}, 7], "srcmeta": {"build:1": "junk"}}
    assert gs.window_means(st, T0, c) == []
    gs.window_update(st, T0 + 20, [], 0.0, c)   # heals


def test_snapshot_rows_carry_the_verdict_keep_waiting_builds_and_add_the_folder_only_for_builds_and_agents():
    st = {}
    c = feed(st, 2)
    rows, more = gs.snapshot_rows(gs.window_means(st, T0 + 20, c), c, limit=3, where={"21": "src/x-wt", "10": "never"})
    assert more > 0 and [r["name"] for r in rows][0] == "bgrun" and rows[0]["where"] == "src/x-wt" and not rows[0]["can_freeze"]
    allrows, _ = gs.snapshot_rows(gs.window_means(st, T0 + 20, c), c, limit=20, where={"21": "src/x-wt", "10": "never"})
    byname = {r["name"]: r for r in allrows}
    assert byname["Slack"]["can_freeze"] and "where" not in byname["Slack"]   # an app row never takes a folder
    assert byname["admit"]["waiting"] and byname["admit"]["cores_5m"] == 0.0   # a waiting build is listed at 0 cores
    assert not byname["Ghostty"]["can_freeze"] and byname["Ghostty"]["why"] == "protected app: never frozen"
    assert all(set(r) <= {"key", "kind", "name", "owner", "cores_5m", "cpu_now", "rss_mb", "share", "procs", "heaviest", "waiting", "can_freeze", "why",
                          "app_id", "where"} for r in allrows)


def test_proc_cwds_reads_lsof_output_and_survives_its_absence(monkeypatch):
    class R:
        stdout = "p21\nn/Users/x/src/djbclark-ade-wt\np22\nn/tmp\n"
    monkeypatch.setattr(gs.subprocess, "run", lambda *a, **k: R())
    assert gs.proc_cwds(["21", "22", "x"]) == {"21": "src/djbclark-ade-wt", "22": "/tmp"}
    monkeypatch.setattr(gs.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    assert gs.proc_cwds(["21"]) == {} and gs.proc_cwds([]) == {}


# ---- the tick: sources reach the snapshot, the history ring reaches disk ----------------------------------------------------------------------
def test_a_live_tick_puts_sources_in_the_snapshot_and_the_history_ring_on_disk(tmp_path, monkeypatch):
    import gui_hog_sources
    monkeypatch.setattr(gui_hog_sources, "proc_cwds", lambda pids: {"21": "src/x-wt"})
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    gh.hold_write(state, os.getpid(), "S", "bg", T0 - 400, ["pageins"], T0)
    t = table()
    ls = [{"name": "Slack", "bundle_id": "com.example.slack", "bundle_path": "/Applications/Slack.app", "exe": SLACK, "pid": 10, "type": "Foreground"}]
    st = {}
    for i in range(2):
        gh.tick(st, T0 + i * 20, t, {p: 1024 for p in t}, set(), state_dir=state, my_uid=ME, agent_clis={"claude"}, cfg=cfg(), lsapps=ls, dry=False,
                exe_of=lambda p: SLACK if str(p) in ("10", "11") else None, start_of=lambda p: "S", launch=False, gui_ok=False, load_avg=(1.0, 2.0, 3.0), ncpu=10,
                sysread={"load1": 3.0 + i, "compress": 1000 + 500 * i, "pageins": 10 * i, "swapins": 0})
    snap = json.loads((state / "gui-hog" / "snapshot.json").read_text())
    names = {r["name"]: r for r in snap["sources"]}
    assert names["bgrun"]["owner"] == "claude" and names["bgrun"]["where"] == "src/x-wt" and not names["bgrun"]["can_freeze"]
    assert all(not r["can_freeze"] for r in snap["sources"] if r["kind"] != "app")
    ring = json.loads((state / "gui-hog" / "sys-hist.json").read_text())["rows"]
    assert [r[1] for r in ring] == [3.0, 4.0] and ring[1][2] == 1500   # the ring is written while a build is held
    assert "SECRET" not in json.dumps(snap) and "secretdir" not in json.dumps(snap)


def test_a_tick_without_a_hold_or_a_frozen_app_writes_no_history_file(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    t = table()
    st = {}
    gh.tick(st, T0, t, {}, set(), state_dir=state, my_uid=ME, agent_clis={"claude"}, cfg=cfg(), lsapps=[], dry=False, exe_of=lambda p: None, start_of=lambda p: "S",
            launch=False, gui_ok=False, sysread={"load1": 1.0})
    assert not (state / "gui-hog" / "sys-hist.json").exists() and len(st["gui_hog"]["hist"]) == 1   # in memory (state.json) always, on disk only when needed


def test_a_fault_in_the_sources_never_stops_the_tick(tmp_path, monkeypatch):
    import gui_hog_sources
    monkeypatch.setattr(gui_hog_sources, "group_sources", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    out = []
    d = gh.tick({}, T0, table(), {}, set(), state_dir=state, my_uid=ME, cfg=cfg(), lsapps=[], dry=True, exe_of=lambda p: None, out=out.append)
    assert d is not None and any("load sources" in x and "boom" in x for x in out)


def test_status_lines_name_the_load_sources(tmp_path):
    st = {"gui_hog": {}}
    c = feed(st["gui_hog"], 2)
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    text = "\n".join(gh.status_lines(st, state, T0 + 20, c))
    assert "load sources" in text and "bgrun (owner: claude), heaviest rustc" in text and "a build or test job" in text and "can freeze" in text   # Slack


MARK = "/Contents/MacOS/"
REAL = "/Applications/Real.app" + MARK + "real-exe"   # what the kernel reports: differs from every word of the command lines below


def test_a_label_is_never_text_from_an_argument_with_or_without_a_kernel_path():   # adversary L1, L1r, L1r' of #872
    for cmd, want in (("/Applications/Xcode.app/Contents/Developer/usr/bin/clang -c a.c -DPASS=hunter2", "clang"),
                      ("/Applications/Foo.app" + MARK + "Foo -apiToken s3cr3tvalue", "Foo"),
                      ("/Applications/Foo.app" + MARK + "Foo /Users/me/secret/file.txt", "Foo"),
                      ("/Applications/Foo.app" + MARK + "Foo secretword", "Foo"),
                      ("/Applications/Google Chrome.app" + MARK + "Google Chrome --type=renderer --token=hunter2", "Google"),   # no kernel path: argv[0] only
                      ("/usr/bin/tool --path=/x" + MARK + "hunter2 -k", "tool"),
                      ("/usr/bin/tool SECRET" + MARK + "hunter2", "tool"),
                      ("/usr/bin/tool a b c" + MARK + "hunter2", "tool"),
                      ("/bin/cp Foo.app" + MARK + "hunter2 dest", "cp"),
                      ("/usr/bin/codesign -v /Applications/Foo.app" + MARK + "Foo", "codesign"),
                      ("/bin/sh -c cd /A.app" + MARK + " && ./Foo", "sh")):
        for exe_of in (None, lambda pid: None, lambda pid: (_ for _ in ()).throw(OSError("gone"))):   # no lookup, a process that exited, a lookup that raises
            label = gs._label(cmd, 7, exe_of)
            assert label == want, (cmd, label)
            assert not {"hunter2", "s3cr3tvalue", "secretword", "SECRET", "secret"} & set(label.replace("/", " ").split())


def test_the_kernel_executable_path_wins_over_argv_when_it_is_readable():   # kills `_label` ignoring exe_of (R1 of the #872 re-review)
    cmd = "/usr/bin/tool SECRET" + MARK + "hunter2"
    assert gs._label(cmd, 7, lambda pid: REAL) == "real-exe"
    assert gs._label(cmd, "7", lambda pid: REAL + "/") == "real-exe"
    assert gs._label(cmd, None, lambda pid: REAL) == "tool"   # no pid, no lookup
    assert gs._label("/usr/bin/plain --x", 7, lambda pid: REAL) == "plain"   # a command without the mark never asks the kernel
    asked = []
    gs._label("/usr/bin/plain", 7, lambda pid: asked.append(pid))
    assert asked == []


def test_group_sources_labels_system_heaviest_and_build_names_from_the_kernel_path():   # kills R3: every `_label` call site passes exe_of
    seen = []

    def exe_of(pid):
        seen.append(pid)
        return REAL
    rows = {"10": (1, ME, 2.0, "/usr/bin/tool SECRET" + MARK + "hunter2"),
            "20": (1, ME, 1.0, "/usr/bin/other SECRET" + MARK + "hunter2"), "21": (20, ME, 3.0, "/usr/bin/third SECRET" + MARK + "hunter2")}
    out = {s["key"]: s for s in gs.group_sources(rows, {p: 1024 for p in rows}, [], exe_of=exe_of)}
    assert out["system:real-exe"]["name"] == "real-exe" and out["system:real-exe"]["heaviest"] == "real-exe"   # the system key, its name and its heaviest
    assert "hunter2" not in json.dumps(list(out.values())) and seen
    held = {s["key"]: s for s in gs.group_sources(rows, {p: 1024 for p in rows}, [], held_pids=("10",), exe_of=exe_of)}
    assert held["build:10"]["name"] == "admit" and "hunter2" not in json.dumps(list(held.values()))
    plain = {s["key"]: s for s in gs.group_sources(rows, {p: 1024 for p in rows}, [])}
    assert "hunter2" not in json.dumps(list(plain.values())) and "system:tool" in plain   # no lookup: argv[0], never an argument


def test_a_terminal_subtree_inside_an_app_is_named_from_the_kernel_path_too():   # kills R3c: the third `_label` call site
    t = table()
    t["51"] = (50, ME, 0.01, "/usr/bin/login SECRET" + MARK + "hunter2")   # the top of the shell subtree inside Ghostty
    seen = {s["key"]: s for s in gs.group_sources(t, {p: 1024 for p in t}, apps(), exe_of=lambda pid: REAL if str(pid) == "51" else None, agent_clis={"claude"})}
    assert seen["build:51"]["name"] == "terminal session (real-exe)" and "hunter2" not in json.dumps(list(seen.values()))
    plain = {s["key"]: s for s in gs.group_sources(t, {p: 1024 for p in t}, apps(), agent_clis={"claude"})}
    assert plain["build:51"]["name"] == "terminal session (login)"


def test_the_tick_gives_the_sampler_s_exe_of_to_the_labels(tmp_path):   # kills R4: tick stops passing exe_of to group_sources
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    gh.hold_write(state, os.getpid(), "S", "bg", T0 - 400, ["pageins"], T0)
    t = table()
    t["60"] = (1, ME, 1.4, "/usr/bin/tool SECRET" + MARK + "hunter2")
    ls = [{"name": "Slack", "bundle_id": "com.example.slack", "bundle_path": "/Applications/Slack.app", "exe": SLACK, "pid": 10, "type": "Foreground"}]
    gh.tick({}, T0, t, {p: 1024 for p in t}, set(), state_dir=state, my_uid=ME, agent_clis={"claude"}, cfg=cfg(), lsapps=ls, dry=False,
            exe_of=lambda p: REAL if str(p) == "60" else (SLACK if str(p) in ("10", "11") else None), start_of=lambda p: "S", launch=False, gui_ok=False,
            load_avg=(1.0, 2.0, 3.0), ncpu=10)
    snap = json.loads((state / "gui-hog" / "snapshot.json").read_text())
    names = [r["name"] for r in snap["sources"]]
    assert "real-exe" in names and "tool" not in names and "hunter2" not in json.dumps(snap)

