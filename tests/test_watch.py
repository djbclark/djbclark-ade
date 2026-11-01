"""bin/watch: idempotent watcher launcher. Every external tool is a stub on a private directory
(paseo, paseo-new-seat, fleet-watch, route_agent.py); nothing here touches the real daemon, relay files or quota."""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WATCH = ROOT / "bin" / "watch"

PASEO_STUB = '''#!/usr/bin/env python3
import json, os, sys
d = os.environ["STUB_DIR"]; f = d + "/paseo.json"
s = json.load(open(f)) if os.path.exists(f) else {"agents": [], "ws": []}
a = sys.argv[1:]
def save(): json.dump(s, open(f, "w"))
if a[:3] == ["agent", "ls", "-g"]:
    assert a in (["agent", "ls", "-g", "--background", "--json"], ["agent", "ls", "-g", "-a", "--json"]), a
    if os.environ.get("STUB_LSA_FAIL" if "-a" in a else "STUB_LS_FAIL"): sys.exit(1)
    if "-a" in a:
        countfile = d + "/lsa-count"
        count = int(open(countfile).read()) + 1 if os.path.exists(countfile) else 1
        open(countfile, "w").write(str(count))
        if os.environ.get("STUB_LSA_FAIL_AFTER_FIRST") and count > 1: sys.exit(1)
    print(json.dumps([x for x in s["agents"] if ("-a" in a or not x.get("archived"))
                      and ("-a" in a or "--background" in a or not x.get("background"))]))
elif a[:2] == ["provider", "ls"]: print(json.dumps([{"provider": "omp", "status": "available"}, {"provider": "opencode", "status": "unavailable"}]))
elif a[:2] == ["provider", "models"]: print(json.dumps([{"id": "anthropic/claude-sonnet-5-5", "thinkingOptionIds": ["low", "medium", "high", "xhigh"]},
                                                      {"id": "anthropic/claude-sonnet-5-5[1m]", "thinkingOptionIds": ["low", "medium", "high"]}]))
elif a[:2] == ["workspace", "ls"]: print(json.dumps(s["ws"]))
elif a[:2] == ["workspace", "create"]:
    w = {"workspaceId": "wks_" + a[a.index("--title") + 1], "name": a[a.index("--title") + 1], "cwd": a[a.index("--path") + 1]}
    s["ws"].append(w); save(); print(json.dumps(w))
elif a[:2] == ["agent", "stop"]: pass
elif a[:2] == ["agent", "update"]:
    for x in s["agents"]:
        if x["id"] == a[2]: x["name"] = a[a.index("--name") + 1]
    save()
elif a[:2] == ["agent", "archive"]:
    for x in s["agents"]:
        if x["id"] == a[-1]: x["archived"] = True
    save()
else: sys.exit(9)
'''

SEAT_STUB = '''#!/usr/bin/env python3
import json, os, sys, time, uuid
d = os.environ["STUB_DIR"]; f = d + "/paseo.json"
time.sleep(float(os.environ.get("STUB_SEAT_SLEEP", "0")))
s = json.load(open(f)) if os.path.exists(f) else {"agents": [], "ws": []}
aid = str(uuid.uuid4())
s["agents"].append({"id": aid, "shortId": aid[:7], "name": sys.argv[sys.argv.index("--title") + 1], "status": "idle", "argv": sys.argv[1:]})
json.dump(s, open(f, "w"))
open(d + "/seat.log", "a").write(json.dumps(sys.argv[1:]) + "\\n")
if not os.environ.get("STUB_NO_REGISTER"):
    open(d + "/role", "w").write(aid + "\\nname: watch stub\\nsince: 2026-10-25 10:00:00\\n")
print(json.dumps({"id": aid, "shortId": aid[:8], "autoAccept": True}))
'''

FW_STUB = '''#!/usr/bin/env python3
import os, sys
d = os.environ["STUB_DIR"]; role = d + "/role"
a = sys.argv[1:]
cur = open(role).read().splitlines()[0] if os.path.exists(role) else ""
if "--relay-status" in a:
    if not cur: sys.exit(1)
    print(f"relay to {cur} (watch stub, set 2026-10-25 10:00:00)")
elif "--relay-test" in a:
    open(d + "/tests.log", "a").write(cur + "\\n")
    t = os.environ.get("STUB_TEST_FAIL"); sys.exit(1 if (t == "all" or t == cur or (t and len(cur) != 36)) or not cur else 0)
elif "--relay-off" in a:
    who = a[a.index("--relay-off") + 1]
    if who != cur: print("left it", file=sys.stderr); sys.exit(1)
    os.unlink(role)
else: sys.exit(9)
'''

ROUTE_STUB = '''#!/usr/bin/env python3
import json, os, sys
d = os.environ["STUB_DIR"]
a = sys.argv[1:]
if a[0] == "calibrate": print(json.dumps({"groups": json.loads(os.environ.get("STUB_CALIB", "[]"))})); sys.exit(0)
kind = a[a.index("--kinds") + 1]
open(d + "/route.log", "a").write(kind + " " + " ".join(a) + "\\n")
if os.environ.get("STUB_NO_ROUTE"):
    sl = {"kind": kind, "service": None, "why": "everything excluded"}
else:
    sl = {"kind": kind, "service": "svc-" + kind, "agent": "omp", "model": os.environ.get("STUB_MODEL", "anthropic/claude-sonnet-5-5 --effort high"), "why": "stub", "remaining": 80}
print(json.dumps({"snapshot_age_s": 1, "stale": False, "quota_source": {"source": "aiuse"}, "governor_hold": None, "slices": [sl]}))
'''

REGISTRY = """
[defaults]
window_days = 14
register_timeout_s = 2
poll_s = 0.2
workspace_cwd = "{cwd}"

[domain.alpha]
skill = "/alphawatch"
cwd = "{cwd}"
chain = "chain-alpha"
kind = "code"
kind_idle = "bulk"
needs_model = true
holder_cmd = ["{{fleet_watch}}", "upstream", "--relay-status"]
holder_parse = "fleet-watch-relay"
test_cmd = ["{{fleet_watch}}", "upstream", "--relay-test"]
off_cmd = ["{{fleet_watch}}", "upstream", "--relay-off", "{{agent}}"]
signals = {{ kind = "fleet-watch", base = "upstream-alpha" }}
"""


@pytest.fixture
def env(tmp_path):
    bindir = tmp_path / "stubs"
    bindir.mkdir()
    for name, body in (("paseo", PASEO_STUB), ("paseo-new-seat", SEAT_STUB), ("fleet-watch", FW_STUB), ("route_agent.py", ROUTE_STUB)):
        p = bindir / name
        p.write_text(body)
        p.chmod(0o755)
    work = tmp_path / "work"
    work.mkdir()
    (tmp_path / "registry.toml").write_text(REGISTRY.format(cwd=work))
    (tmp_path / "fwstate").mkdir()
    e = dict(os.environ)
    e.update(STUB_DIR=str(tmp_path), WATCH_REGISTRY=str(tmp_path / "registry.toml"), WATCH_STATE=str(tmp_path / "state"),
             WATCH_FLEET_STATE=str(tmp_path / "fwstate"), WATCH_HANDOFFS=str(tmp_path / "handoffs"),
             WATCH_LOAD_STATE=str(tmp_path / "lwstate"), WATCH_PASEO=str(bindir / "paseo"), WATCH_NEW_SEAT=str(bindir / "paseo-new-seat"),
             WATCH_ROUTE_AGENT=str(bindir / "route_agent.py"), WATCH_FLEET_WATCH=str(bindir / "fleet-watch"), HOME=str(tmp_path))
    for k in ("PASEO_AGENT_ID", "STUB_NO_REGISTER", "STUB_TEST_FAIL", "STUB_NO_ROUTE", "STUB_SEAT_SLEEP", "STUB_MODEL", "STUB_CALIB",
              "STUB_LS_FAIL", "STUB_LSA_FAIL", "STUB_LSA_FAIL_AFTER_FIRST"):
        e.pop(k, None)
    e["_tmp"] = str(tmp_path)
    return e


def watch(env, *args, wait=True, extra=None):
    e = {**env, **(extra or {})}
    p = subprocess.Popen([sys.executable, str(WATCH), *args], env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if not wait:
        return p
    out, err = p.communicate(timeout=60)
    return p.returncode, out + err


def agents(env):
    f = Path(env["_tmp"]) / "paseo.json"
    return [a for a in json.loads(f.read_text())["agents"] if not a.get("archived")] if f.exists() else []


def seat_calls(env):
    f = Path(env["_tmp"]) / "seat.log"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def set_role(env, target):
    (Path(env["_tmp"]) / "role").write_text(f"{target}\nname: someone\nsince: 2026-10-25 09:00:00\n")


def add_agent(env, status="idle", name=None):
    f = Path(env["_tmp"]) / "paseo.json"
    s = json.loads(f.read_text()) if f.exists() else {"agents": [], "ws": []}
    aid = str(uuid.uuid4())
    s["agents"].append({"id": aid, "shortId": aid[:7], "status": status, "name": name})
    f.write_text(json.dumps(s))
    return aid


def test_second_up_launches_nothing(env):
    rc, out = watch(env, "up")
    assert rc == 0 and "registered: holder" in out, out
    assert len(agents(env)) == 1 and len(seat_calls(env)) == 1
    rc, out = watch(env, "up")
    assert rc == 0 and "already watched by watch stub" in out, out
    assert len(agents(env)) == 1 and len(seat_calls(env)) == 1


def test_concurrent_up_one_wins_one_claims(env):
    slow = {"STUB_SEAT_SLEEP": "1.5"}
    a = watch(env, "up", wait=False, extra=slow)
    time.sleep(0.6)
    rc_b, out_b = watch(env, "up", extra=slow)
    out_a, err_a = a.communicate(timeout=60)
    assert a.returncode == 0 and rc_b == 0, (out_a, out_b)
    assert "claimed: another `watch up` is launching" in out_b, out_b
    assert len(agents(env)) == 1 and len(seat_calls(env)) == 1


def test_stale_record_is_dropped_and_relaunched(env):
    state = Path(env["_tmp"]) / "state"
    state.mkdir()
    (state / "alpha.json").write_text(json.dumps({"domain": "alpha", "agent_id": str(uuid.uuid4()), "state": "registered",
                                                  "started_epoch": time.time() - 100}))
    rc, out = watch(env, "up")
    assert rc == 0 and "dropped stale record" in out and "registered:" in out, out
    assert len(agents(env)) == 1
    assert json.loads((state / "alpha.json").read_text())["agent_id"] == agents(env)[0]["id"]


def test_live_holder_is_not_replaced_without_force(env):
    old = add_agent(env)
    set_role(env, old)
    rc, out = watch(env, "up")
    assert rc == 0 and "already watched by watch stub" in out, out
    assert seat_calls(env) == [] and [a["id"] for a in agents(env)] == [old]
    rc, out = watch(env, "up", "--force")
    assert rc == 0 and "--force: replacing live holder" in out, out
    assert len(seat_calls(env)) == 1
    assert old in [a["id"] for a in agents(env)], "force must not stop an agent watch did not start"


def test_unreachable_holder_is_replaced(env):
    set_role(env, str(uuid.uuid4()))   # holder is a Paseo id that is not in `paseo ls`
    rc, out = watch(env, "up")
    assert rc == 0 and "is unreachable" in out and "registered:" in out, out
    assert len(seat_calls(env)) == 1


def test_non_paseo_holder_needs_a_passing_channel_test(env):
    set_role(env, "herdr-pane-w1:p3")
    rc, out = watch(env, "up", extra={"STUB_TEST_FAIL": "1"})
    assert rc == 0 and "is unreachable" in out and "channel test failed" in out, out
    assert len(seat_calls(env)) == 1


def test_launch_that_never_registers_is_reported_and_not_repeated(env):
    rc, out = watch(env, "up", extra={"STUB_NO_REGISTER": "1"})
    assert rc == 1 and "not registered: role still unheld" in out, out
    aid = agents(env)[0]["id"]
    rec = json.loads((Path(env["_tmp"]) / "state" / "alpha.json").read_text())
    assert rec["state"] == "unregistered" and rec["agent_id"] == aid and "registered_at" not in rec
    rc, out = watch(env, "up", extra={"STUB_NO_REGISTER": "1"})
    assert rc == 1 and "never registered" in out and "not starting another" in out, out
    assert [a["id"] for a in agents(env)] == [aid] and len(seat_calls(env)) == 1


def test_registered_but_channel_test_fails_is_not_success(env):
    rc, out = watch(env, "up", extra={"STUB_TEST_FAIL": "all"})
    assert rc == 1 and "registered but the channel test failed" in out, out


def test_no_eligible_route_launches_nothing(env):
    rc, out = watch(env, "up", extra={"STUB_NO_ROUTE": "1"})
    assert rc == 3 and "no eligible route" in out and "everything excluded" in out, out
    assert seat_calls(env) == []


def test_fable_is_refused_even_when_routed(env):
    rc, out = watch(env, "up", extra={"STUB_MODEL": "anthropic/claude-fable-5-1 --effort high"})
    assert rc == 3 and "Fable" in out and seat_calls(env) == [], out


def test_dry_run_has_no_side_effects(env):
    rc, out = watch(env, "up", "--dry-run")
    assert rc == 0 and "would launch: omp / anthropic/claude-sonnet-5-5" in out, out
    assert agents(env) == [] and not (Path(env["_tmp"]) / "state").exists()


def test_idle_domain_uses_cheap_kind_busy_domain_uses_high_effort(env):
    rc, out = watch(env, "up", "--dry-run")
    assert "level idle" in out and "kind bulk" in out and "thinking medium" in out, out
    (Path(env["_tmp"]) / "fwstate" / "upstream-alpha.json").write_text(json.dumps({"pending": [{"n": 1}], "threads": {}}))
    rc, out = watch(env, "up", "--dry-run")
    assert "level busy" in out and "kind code" in out and "thinking high" in out, out


def test_effort_never_exceeds_route_agents_own_effort(env):
    (Path(env["_tmp"]) / "fwstate" / "upstream-alpha.json").write_text(json.dumps({"pending": [{"n": 1}], "threads": {}}))
    rc, out = watch(env, "up", "--dry-run", extra={"STUB_MODEL": "anthropic/claude-sonnet-5-5 --effort low"})
    assert "level busy" in out and "thinking low" in out, out


def test_provider_paseo_cannot_launch_is_skipped_via_exclude(env):
    # the stub plan always says omp; an unavailable provider makes the engine re-plan with the service excluded
    s = Path(env["_tmp"]) / "stubs" / "route_agent.py"
    s.write_text(ROUTE_STUB.replace('"agent": "omp"', '"agent": "opencode" if "--exclude" not in a else "omp"'))
    rc, out = watch(env, "up", "--dry-run")
    assert "would launch: omp /" in out and "Paseo provider 'opencode' is unavailable" in out, out


def test_launch_passes_yolo_workspace_label_and_skill_prompt(env):
    rc, out = watch(env, "up")
    assert rc == 0, out
    argv = seat_calls(env)[0]
    assert argv[argv.index("--workspace") + 1] == "wks_watch"
    assert argv[argv.index("--title") + 1] == "watch alpha 1"
    assert "name it \"watch alpha 1\"" in argv[argv.index("--prompt") + 1]
    assert argv[argv.index("--label") + 1] == "watch=alpha"
    assert "--mode" not in argv, "omp's yolo is the auto_accept feature, not a mode"
    assert argv[argv.index("--prompt") + 1].startswith("/alphawatch\n")
    # a second domain row-name run reuses the workspace rather than creating another
    watch(env, "up", "--force")
    ws = json.loads((Path(env["_tmp"]) / "paseo.json").read_text())["ws"]
    assert len(ws) == 1


def test_codex_watcher_is_created_in_full_access_mode(env):
    stubs = Path(env["_tmp"]) / "stubs"
    (stubs / "paseo").write_text(PASEO_STUB.replace('{"provider": "omp", "status": "available"}',
                                                    '{"provider": "omp", "status": "available"}, {"provider": "codex", "status": "available"}'))
    (stubs / "route_agent.py").write_text(ROUTE_STUB.replace('"agent": "omp"', '"agent": "codex"'))
    rc, out = watch(env, "up")
    assert rc == 0, out
    argv = seat_calls(env)[0]
    assert argv[argv.index("--provider") + 1] == "codex" and argv[argv.index("--mode") + 1] == "full-access"


def titles(env):
    return {a["id"]: a["name"] for a in agents(env)}


def test_each_new_watcher_gets_the_next_base36_number_and_the_old_one_is_retired(env):
    rc, out = watch(env, "up")
    assert rc == 0, out
    (first,) = titles(env)
    assert titles(env) == {first: "watch alpha 1"}
    rc, out = watch(env, "up", "--force")
    assert rc == 0 and "retired:" in out, out
    t = titles(env)
    assert t[first] == "x watch alpha 1", (out, t)   # --force renames the replaced holder and never archives it
    assert "watch alpha 2" in t.values()
    # past 9 the number goes a, b, ... z, 10: a stale seq file at 9 makes the next launch `a`
    (Path(env["_tmp"]) / "state" / "alpha.seq").write_text("9\n")
    rc, out = watch(env, "up", "--force")
    assert rc == 0 and "watch alpha a" in titles(env).values(), (out, titles(env))
    (Path(env["_tmp"]) / "state" / "alpha.seq").write_text("z\n")
    rc, out = watch(env, "up", "--force")
    assert rc == 0 and "watch alpha 10" in titles(env).values(), (out, titles(env))


def test_replacing_a_holder_not_started_by_watch_renames_it_and_leaves_it_running(env):
    old = add_agent(env, name="watch alpha")      # legacy unnumbered title = generation 0
    set_role(env, old)
    rc, out = watch(env, "up", "--force")
    assert rc == 0, out
    t = titles(env)
    assert t[old] == "x watch alpha"   # renamed, kept as a tab, never archived
    assert sorted(t.values()) == ["watch alpha 1", "x watch alpha"]


def test_a_retired_watcher_with_a_turn_in_flight_is_kept_and_archived_once_idle(env):
    holder = add_agent(env, name="watch alpha 2")
    set_role(env, holder)
    old = add_agent(env, name="watch alpha 1", status="running")   # an older generation, not the role holder
    rc, out = watch(env, "up", "--force")
    assert rc == 0, out
    assert titles(env)[old] == "x watch alpha 1" and "left running" in out, (out, titles(env))
    f = Path(env["_tmp"]) / "paseo.json"
    s = json.loads(f.read_text())
    for a in s["agents"]:
        if a["id"] == old:
            a["status"] = "idle"
    f.write_text(json.dumps(s))
    rc, out = watch(env, "up")
    assert rc == 0 and old not in titles(env), (out, titles(env))
    assert titles(env)[holder] == "x watch alpha 2"   # the force-replaced holder is never archived


def test_a_launch_that_never_registers_retires_nothing(env):
    old = add_agent(env, name="watch alpha 3")
    set_role(env, old)
    rc, out = watch(env, "up", "--force", extra={"STUB_NO_REGISTER": "1"})
    assert rc == 1 and "not registered" in out, out
    assert titles(env)[old] == "watch alpha 3"
    assert "watch alpha 4" in titles(env).values()


def test_numbers_continue_past_titles_that_are_already_retired(env):
    add_agent(env, name="x watch alpha 7")
    rc, out = watch(env, "up")
    assert rc == 0 and "watch alpha 8" in titles(env).values(), (out, titles(env))


def test_down_stops_only_the_agent_it_started(env):
    rc, out = watch(env, "down", "alpha")
    assert rc == 0 and "no agent started by watch is recorded" in out
    other = add_agent(env)
    set_role(env, other)
    rc, out = watch(env, "down", "alpha")
    assert [a["id"] for a in agents(env)] == [other] and (Path(env["_tmp"]) / "role").exists()
    set_role(env, str(uuid.uuid4()))
    (Path(env["_tmp"]) / "role").unlink()
    rc, out = watch(env, "up")
    assert rc == 0, out
    ours = [a["id"] for a in agents(env) if a["id"] != other][0]
    rc, out = watch(env, "down", "alpha")
    assert rc == 0 and "archived" in out, out
    assert [a["id"] for a in agents(env)] == [other] and ours not in [a["id"] for a in agents(env)]
    assert not (Path(env["_tmp"]) / "role").exists() and not (Path(env["_tmp"]) / "state" / "alpha.json").exists()


def test_status_sends_nothing_and_starts_nothing(env):
    set_role(env, "herdr-pane-w1:p3")
    rc, out = watch(env, "status")
    assert rc == 0 and "unknown (needs a channel test line" in out, out
    assert not (Path(env["_tmp"]) / "tests.log").exists() and seat_calls(env) == []


def test_one_million_context_only_when_the_briefs_need_it(env):
    rc, out = watch(env, "up", "--dry-run")
    assert "context standard" in out, out
    chain = Path(env["_tmp"]) / "handoffs" / "chain-alpha"
    chain.mkdir(parents=True)
    (chain / "SESSION_LOG.md").write_text("x" * 600_000)
    rc, out = watch(env, "up", "--dry-run")
    assert "claude-sonnet-5-5[1m]" in out and "context 1m" in out, out


def test_any_idle_x_titled_agent_is_archived_and_a_busy_one_waits(env):
    idle = add_agent(env, name="x Dann 5")
    busy = add_agent(env, name="x Dann 6", status="running")
    plain = add_agent(env, name="Dann 7")
    rc, out = watch(env, "up")
    assert rc == 0, out
    t = titles(env)
    assert idle not in t and t[busy] == "x Dann 6" and t[plain] == "Dann 7", (out, t)


def test_a_force_replaced_non_watch_holder_survives_the_other_sweep(env):
    old = add_agent(env, name="Dann main")
    set_role(env, old)
    rc, out = watch(env, "up", "--force")
    assert rc == 0, out
    assert titles(env)[old] == "x Dann main", (out, titles(env))
    rc, out = watch(env, "up")
    assert rc == 0 and titles(env)[old] == "x Dann main", (out, titles(env))


def test_an_unreadable_kept_file_archives_nothing_and_is_not_overwritten(env):
    idle = add_agent(env, name="x Dann 5")
    kept = Path(env["_tmp"]) / "state" / "kept.json"
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text("{not json")
    rc, out = watch(env, "up")
    assert rc == 0, out
    assert idle in titles(env) and "unreadable" in out, (out, titles(env))
    holder = add_agent(env, name="watch alpha 1")
    set_role(env, holder)
    rc, out = watch(env, "up", "--force")
    assert titles(env)[holder] == "watch alpha 1", (out, titles(env))   # not renamed: it could not be protected
    assert kept.read_text() == "{not json"


def test_kept_ids_accumulate_across_force_replacements(env):
    rc, out = watch(env, "up")
    assert rc == 0, out
    (first,) = titles(env)
    for _ in range(2):
        rc, out = watch(env, "up", "--force")
        assert rc == 0, out
    kept = json.loads((Path(env["_tmp"]) / "state" / "kept.json").read_text())
    assert first in kept and len(kept) == 2, kept


def test_concurrent_keep_id_calls_lose_no_id(env):
    state = Path(env["_tmp"]) / "state"
    code = ("import sys, importlib.machinery as m, importlib.util as u\n"
            "l = m.SourceFileLoader('watch_mod', sys.argv[1]); sp = u.spec_from_loader('watch_mod', l)\n"
            "mod = u.module_from_spec(sp); l.exec_module(mod)\n"
            "assert mod.keep_id(sys.argv[2])\n")
    procs = [subprocess.Popen([sys.executable, "-c", code, str(WATCH), f"id-{i}"], env={**os.environ, "WATCH_STATE": str(state)})
             for i in range(32)]
    assert [p.wait() for p in procs] == [0] * 32
    assert sorted(json.loads((state / "kept.json").read_text())) == sorted(f"id-{i}" for i in range(32))


# ---- a holder whose idle runtime Paseo collected (status `closed`, un-archived, session persisted) -------------------
# Found 2026-10-31: watcher 09e51ac1 was collected at 14:56:18 and `watch up` replaced it 98 s later.
def set_agent(env, aid, **kw):
    f = Path(env["_tmp"]) / "paseo.json"
    s = json.loads(f.read_text())
    for a in s["agents"]:
        if a["id"] == aid:
            a.update(kw)
    f.write_text(json.dumps(s))


def channel_test_calls(env):
    f = Path(env["_tmp"]) / "tests.log"
    return f.read_text().splitlines() if f.exists() else []


def test_collected_holder_is_kept_without_waking_it(env):
    old = add_agent(env, status="closed", name="watch alpha 1f")
    set_role(env, old)
    for _ in range(2):   # every tick: nothing launched, renamed or sent, so the model never wakes
        rc, out = watch(env, "up")
        assert rc == 0 and "already watched by watch stub" in out and "collected" in out, out
    assert seat_calls(env) == [] and channel_test_calls(env) == []
    assert titles(env) == {old: "watch alpha 1f"}
    rc, out = watch(env, "status")
    assert rc == 0 and "reachable: yes" in out and "collected" in out and channel_test_calls(env) == [], out


def test_collected_holders_record_is_not_dropped(env):
    old = add_agent(env, status="closed", name="watch alpha 1")
    set_role(env, old)
    state = Path(env["_tmp"]) / "state"
    state.mkdir()
    (state / "alpha.json").write_text(json.dumps({"domain": "alpha", "agent_id": old, "state": "registered", "started_epoch": time.time() - 9999}))
    rc, out = watch(env, "up")
    assert rc == 0 and "dropped stale record" not in out and "already watched" in out, out
    assert json.loads((state / "alpha.json").read_text())["agent_id"] == old and seat_calls(env) == []


def test_collected_agent_that_lost_the_role_is_not_duplicated_and_says_why(env):
    old = add_agent(env, status="closed", name="watch alpha 1")
    state = Path(env["_tmp"]) / "state"
    state.mkdir()
    (state / "alpha.json").write_text(json.dumps({"domain": "alpha", "agent_id": old, "state": "registered", "started_epoch": time.time() - 9999}))
    rc, out = watch(env, "up")
    assert rc == 1 and "registered earlier but no longer holds the role" in out and "never registered" not in out, out
    assert seat_calls(env) == []


@pytest.mark.parametrize("how", ["archived", "error", "gone"])
def test_dead_holder_is_still_replaced(env, how):
    old = add_agent(env, name="watch alpha 1")
    if how == "archived":
        set_agent(env, old, archived=True)
    elif how == "error":
        set_agent(env, old, status="error")
    else:
        old = str(uuid.uuid4())
    set_role(env, old)
    rc, out = watch(env, "up")
    assert rc == 0 and "is unreachable" in out and "registered:" in out, out
    assert len(seat_calls(env)) == 1


def test_archived_holder_is_reported_as_archived_not_collected(env):
    old = add_agent(env, status="closed", name="watch alpha 1")
    set_agent(env, old, archived=True)
    set_role(env, old)
    rc, out = watch(env, "up", "--dry-run")
    assert rc == 0 and "is archived" in out and "collected" not in out, out


@pytest.mark.parametrize("knob,extra_args", [("STUB_LS_FAIL", []), ("STUB_LS_FAIL", ["--force"]), ("STUB_LS_FAIL", ["--probe"]),
                                             ("STUB_LS_FAIL", ["--dry-run"]), ("STUB_LSA_FAIL", [])])
def test_unanswered_daemon_never_launches_a_second_watcher(env, knob, extra_args):
    # STUB_LSA_FAIL: the live list answers without the holder, so only `-a` could say archived or gone
    old = add_agent(env, status="idle" if knob == "STUB_LS_FAIL" else "closed", name="watch alpha 1")
    if knob == "STUB_LSA_FAIL":
        set_agent(env, old, archived=True)
    set_role(env, old)
    rc, out = watch(env, "up", *extra_args, extra={knob: "1"})
    assert rc == 1 and "not launching blind" in out, out
    assert seat_calls(env) == [] and channel_test_calls(env) == [] and titles(env).get(old) in (None, "watch alpha 1")


def test_a_passing_probe_wakes_a_collected_holder_and_keeps_it(env):
    old = add_agent(env, status="closed", name="watch alpha 1")
    set_role(env, old)
    rc, out = watch(env, "up", "--probe")
    assert rc == 0 and "channel test ok" in out and channel_test_calls(env) == [old], out
    assert seat_calls(env) == []


def test_a_failed_probe_of_a_collected_holder_starts_no_duplicate_unless_forced(env):
    old = add_agent(env, status="closed", name="watch alpha 1")
    set_role(env, old)
    rc, out = watch(env, "up", "--probe", extra={"STUB_TEST_FAIL": "all"})
    assert rc == 1 and "resume probe failed" in out and "not starting a duplicate" in out, out
    assert seat_calls(env) == []
    rc, out = watch(env, "up", "--probe", "--force")
    assert rc == 0 and "replacing live holder" in out and len(seat_calls(env)) == 1, out
    assert titles(env)[old] == "x watch alpha 1"


def test_a_retired_collected_watcher_is_archived_but_the_collected_holder_is_not(env):
    holder = add_agent(env, status="closed", name="watch alpha 2")
    set_role(env, holder)
    retired = add_agent(env, status="closed", name="x watch alpha 1")
    rc, out = watch(env, "up")
    assert rc == 0 and "already watched" in out, out
    assert list(titles(env)) == [holder] and retired not in titles(env)


def test_down_archives_a_collected_agent_it_started(env):
    rc, out = watch(env, "up")
    assert rc == 0, out
    (ours,) = titles(env)
    set_agent(env, ours, status="closed")
    rc, out = watch(env, "down", "alpha")
    assert rc == 0 and "archived" in out and titles(env) == {}, out
    assert not (Path(env["_tmp"]) / "state" / "alpha.json").exists()


def test_down_with_an_unanswered_daemon_keeps_the_record(env):
    rc, out = watch(env, "up")
    assert rc == 0, out
    assert len(titles(env)) == 1
    rc, out = watch(env, "down", "alpha", extra={"STUB_LS_FAIL": "1"})
    assert rc == 1 and "still listed after stop+archive" in out, out   # not "gone": the daemon never answered
    assert (Path(env["_tmp"]) / "state" / "alpha.json").exists()


@pytest.mark.parametrize("status", ["idle", "running", "closed"])
@pytest.mark.parametrize("background", [False, True])
def test_forced_live_holder_is_kept_when_its_probe_fails(env, status, background):
    old = add_agent(env, status=status, name="watch alpha 1")
    set_agent(env, old, background=background)
    set_role(env, old)
    rc, out = watch(env, "up", "--force", "--probe", extra={"STUB_TEST_FAIL": old})
    assert rc == 0 and "registered:" in out, out
    assert len(seat_calls(env)) == 1
    assert titles(env)[old] == "x watch alpha 1"
    assert old in json.loads((Path(env["_tmp"]) / "state" / "kept.json").read_text())
    assert old in {a["id"] for a in agents(env)}    # still listed: never archived by the sweep


@pytest.mark.parametrize("status", ["idle", "closed", "running"])
def test_background_holder_is_preserved_without_a_turn_or_generation(env, status):
    old = add_agent(env, status=status, name="watch alpha 1f")
    set_agent(env, old, background=True)
    set_role(env, old)
    for command in ("up", "status", "up"):
        rc, out = watch(env, command)
        assert rc == 0 and ("already watched" in out or "reachable: yes" in out), out
    assert seat_calls(env) == [] and channel_test_calls(env) == []
    assert titles(env) == {old: "watch alpha 1f"}
    assert not (Path(env["_tmp"]) / "state" / "alpha.seq").exists()


def test_background_archived_holder_is_dead_and_number_is_not_reused(env):
    old = add_agent(env, status="closed", name="watch alpha z")
    set_agent(env, old, background=True, archived=True)
    set_role(env, old)
    rc, out = watch(env, "up")
    assert rc == 0 and "is archived" in out and "registered:" in out, out
    assert "watch alpha 10" in titles(env).values()
    assert next(a for a in json.loads((Path(env["_tmp"]) / "paseo.json").read_text())["agents"] if a["id"] == old)["archived"]


def test_second_archived_query_failure_cannot_override_known_dead_holder(env):
    old = add_agent(env, status="closed", name="watch alpha 1")
    set_agent(env, old, archived=True)
    set_role(env, old)
    rc, out = watch(env, "up", extra={"STUB_LSA_FAIL_AFTER_FIRST": "1"})
    assert rc == 0 and "is archived" in out and "registered:" in out, out
    assert "already watched" not in out and len(seat_calls(env)) == 1
    assert "watch alpha 2" in titles(env).values()
    assert "watch alpha 1" not in titles(env).values()


def test_background_retirement_sweeps_preserve_busy_and_other_workspaces(env):
    quiet = add_agent(env, status="closed", name="watch alpha z")
    busy = add_agent(env, status="running", name="x watch alpha y")
    unrelated = add_agent(env, status="idle", name="other workspace task")
    other_retired = add_agent(env, status="idle", name="x other task")
    for aid in (quiet, busy, unrelated, other_retired):
        set_agent(env, aid, background=True)
    rc, out = watch(env, "up")
    assert rc == 0 and "registered:" in out, out
    t = titles(env)
    assert quiet not in t and other_retired not in t
    assert t[busy] == "x watch alpha y" and t[unrelated] == "other workspace task"
    assert "watch alpha 10" in t.values()


@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize("dry", [False, True])
def test_no_title_snapshot_refuses_launch_without_allocating_generation(env, force, dry):
    if force:
        old = add_agent(env, status="idle", name="watch alpha z")
        set_role(env, old)
    args = (["--force"] if force else []) + (["--dry-run"] if dry else [])
    rc, out = watch(env, "up", *args, extra={"STUB_LSA_FAIL": "1"})
    assert rc == 1 and "cannot list existing watcher titles" in out and "watch alpha None" not in out, out
    assert seat_calls(env) == []
    assert not (Path(env["_tmp"]) / "state" / "alpha.seq").exists()
    if force:
        assert titles(env)[old] == "watch alpha z"
