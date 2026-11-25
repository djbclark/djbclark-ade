"""Hermetic tests for bin/gh-pr-wait (GitHub Event Streams waiter + polling fallback + cleanup).

Uses GH_BIN, DEADLINE_BIN, and GH_PR_WAIT_STATE_DIR explicit overrides (never modifies PATH, per code-review rule 2).
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "bin" / "gh-pr-wait"

FAKE_GH_SCRIPT = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import fcntl
    import json
    import os
    import signal
    import sys
    import time
    from pathlib import Path

    cfg = json.loads(Path(os.environ["FAKE_GH_CONFIG"]).read_text(encoding="utf-8"))
    log_path = Path(os.environ["FAKE_GH_LOG"])
    counter_path = Path(os.environ["FAKE_GH_COUNTER"])
    pid_path = Path(os.environ["FAKE_GH_LISTEN_PID"])

    def log(entry):
        entry = dict(entry)
        entry["t"] = time.monotonic()
        with log_path.open("a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(json.dumps(entry) + "\\n")
            f.flush()
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def next_count(key):
        lock_file = counter_path.with_suffix(".lock")
        with lock_file.open("a+", encoding="utf-8") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            data = {}
            if counter_path.exists():
                try:
                    data = json.loads(counter_path.read_text(encoding="utf-8"))
                except ValueError:
                    data = {}
            val = int(data.get(key, 0)) + 1
            data[key] = val
            tmp = counter_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, counter_path)
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
            return val

    def get_count(key):
        if not counter_path.exists():
            return 0
        try:
            return int(json.loads(counter_path.read_text(encoding="utf-8")).get(key, 0))
        except ValueError:
            return 0

    def pid_alive(pid):
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    argv = sys.argv[1:]

    # Authoritative REST subscription create: `gh api -i -X POST /event-subscriptions ...`
    if argv[:4] == ["api", "-i", "-X", "POST"] and "/event-subscriptions" in argv:
        call_no = next_count("sub_post")
        log({"op": "sub_create", "call": call_no, "argv": argv})
        if cfg.get("create_delay_s"):
            time.sleep(float(cfg["create_delay_s"]))
        err = cfg.get("create_error")
        if err:
            print(err["stderr"], file=sys.stderr)
            raise SystemExit(err.get("rc", 1))
        status = int(cfg.get("create_http_status", 201))
        statuses = cfg.get("create_http_statuses")
        if isinstance(statuses, list) and statuses:
            status = int(statuses[min(call_no - 1, len(statuses) - 1)])
        reason = "Created" if status == 201 else "OK"
        sub_id = cfg.get("created_sub_id", "sub_created_1")
        body = json.dumps({"id": sub_id})
        sys.stdout.write(f"HTTP/2.0 {status} {reason}\\r\\nContent-Type: application/json\\r\\n\\r\\n{body}\\n")
        sys.stdout.flush()
        raise SystemExit(0)

    if argv[:3] == ["event", "subscription", "list"]:
        log({"op": "sub_list", "argv": argv})
        err = cfg.get("list_error")
        if err:
            print(err["stderr"], file=sys.stderr)
            raise SystemExit(err.get("rc", 1))
        print(json.dumps(cfg.get("existing_subs", [])))
        raise SystemExit(0)

    if argv[:3] == ["event", "subscription", "delete"]:
        if "--" in argv[3:]:
            idx = argv.index("--", 3)
            sub_id = argv[idx + 1] if idx + 1 < len(argv) else ""
        else:
            sub_id = argv[3] if len(argv) > 3 else ""
        alive = False
        if pid_path.exists():
            try:
                lpid = int(pid_path.read_text(encoding="utf-8").strip())
                alive = pid_alive(lpid)
            except ValueError:
                alive = False
        log({"op": "sub_delete", "id": sub_id, "argv": argv, "listen_alive": alive})
        fail_ids = set(cfg.get("delete_fail_ids", []))
        if sub_id in fail_ids:
            print(f"HTTP 500 deleting {sub_id}", file=sys.stderr)
            raise SystemExit(1)
        raise SystemExit(0)

    if argv[:2] == ["event", "listen"]:
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
        log({"op": "listen_start", "pid": os.getpid(), "argv": argv})

        if cfg.get("ignore_sigterm"):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        else:
            def _on_term(signum, _frame):
                log({"op": "listen_exited", "signal": signum, "pid": os.getpid()})
                raise SystemExit(0)
            signal.signal(signal.SIGTERM, _on_term)
            signal.signal(signal.SIGINT, _on_term)

        if cfg.get("listen_fail_before_attach"):
            err = cfg["listen_fail_before_attach"]
            print(err.get("stderr", "403 Forbidden"), file=sys.stderr, flush=True)
            log({"op": "listen_exited", "rc": err.get("rc", 1)})
            raise SystemExit(err.get("rc", 1))

        if cfg.get("listen_hang_before_attach"):
            time.sleep(30)
            raise SystemExit(0)

        if cfg.get("attach_delay_s"):
            time.sleep(float(cfg["attach_delay_s"]))

        for pre_line in cfg.get("pre_attach_stderr", []):
            print(pre_line, file=sys.stderr, flush=True)

        log({"op": "listen_ready", "pid": os.getpid()})
        print("Listening for events.", file=sys.stderr, flush=True)

        for action in cfg.get("listen_actions", []):
            wait_views = action.get("after_pr_views")
            if wait_views is not None:
                deadline = time.monotonic() + 10.0
                while get_count("pr_view") < int(wait_views) and time.monotonic() < deadline:
                    time.sleep(0.02)
            delay = float(action.get("delay_s", 0.0))
            if delay > 0:
                time.sleep(delay)
            kind = action.get("kind")
            if kind == "event":
                ev = action["event"]
                log({"op": "listen_emit", "event_type": ev.get("type")})
                print(json.dumps(ev), flush=True)
            elif kind == "split_utf8_event":
                raw = (json.dumps(action["event"], ensure_ascii=False) + "\\n").encode("utf-8")
                mid = len(raw) // 2
                os.write(1, raw[:mid])
                time.sleep(0.03)
                os.write(1, raw[mid:])
                log({"op": "listen_emit_split"})
            elif kind == "oversize_line":
                chunk = b"x" * (1024 * 1024 + 256) + b"\\n"
                os.write(1, chunk)
                log({"op": "listen_oversize"})
            elif kind == "stderr":
                text = action["text"]
                log({"op": "listen_stderr", "text": text})
                print(text, file=sys.stderr, flush=True)
            elif kind == "stdout_raw":
                text = action["text"]
                log({"op": "listen_stdout_raw", "text": text})
                print(text, flush=True)
            elif kind == "exit":
                rc = int(action.get("rc", 0))
                log({"op": "listen_exited", "rc": rc})
                raise SystemExit(rc)

        end = time.monotonic() + float(cfg.get("listen_hold_s", 30.0))
        while time.monotonic() < end:
            time.sleep(0.05)
        log({"op": "listen_exited", "rc": 8})
        raise SystemExit(8)

    if argv[:2] == ["api", "graphql"]:
        call_no = next_count("pr_view")
        log({"op": "pr_view", "kind": "graphql", "call": call_no, "argv": argv})
        views = cfg.get("pr_views", [])
        if not views:
            print("no scripted pr_views", file=sys.stderr)
            raise SystemExit(1)
        idx = min(call_no - 1, len(views) - 1)
        resp = views[idx]
        if resp.get("error"):
            print(resp["error"], file=sys.stderr)
            raise SystemExit(resp.get("rc", 1))
        checks = resp.get("statusCheckRollup", [])
        if checks is None:
            scr_obj = None
        elif isinstance(checks, list):
            scr_obj = {"contexts": {"nodes": checks}}
        else:
            scr_obj = checks  # allow malformed rollup testing
        node = {
            "url": resp.get("url"),
            "state": resp.get("state"),
            "mergedAt": resp.get("mergedAt"),
            "headRefOid": resp.get("headRefOid"),
            "mergeable": resp.get("mergeable"),
            "reviews": {"nodes": resp.get("reviews", [])},
            "commits": {"nodes": [{"commit": {"statusCheckRollup": scr_obj}}]},
        }
        print(json.dumps({"data": {"repository": {"pullRequest": node}}}))
        raise SystemExit(0)

    if argv[:2] == ["pr", "view"]:
        json_arg = ""
        repo_arg = ""
        for a in argv[2:]:
            if a.startswith("--json="):
                json_arg = a.split("=", 1)[1]
            elif a.startswith("--repo="):
                repo_arg = a.split("=", 1)[1]
        if "--" in argv[2:]:
            target = argv[argv.index("--", 2) + 1]
        else:
            target = argv[2] if len(argv) > 2 else ""

        if json_arg == "url":
            log({"op": "pr_view_url", "target": target, "argv": argv})
            if cfg.get("infer_delay_s"):
                time.sleep(float(cfg["infer_delay_s"]))
            inferred = cfg.get("infer_url")
            if not inferred:
                print("no pull request found", file=sys.stderr)
                raise SystemExit(1)
            print(json.dumps({"url": inferred}))
            raise SystemExit(0)

        by_url = cfg.get("pr_views_by_url")
        if by_url is not None:
            key = f"https://github.com/{repo_arg}/pull/{target}" if repo_arg else target
            log({"op": "pr_view", "target": key, "argv": argv})
            resp = by_url.get(key)
            if resp is None or resp.get("error"):
                print((resp or {}).get("error", "HTTP 404 Not Found"), file=sys.stderr)
                raise SystemExit(1)
            print(json.dumps(resp))
            raise SystemExit(0)

        call_no = next_count("pr_view")
        log({"op": "pr_view", "kind": "pr_view", "call": call_no, "target": target, "json": json_arg, "argv": argv})
        views = cfg.get("pr_views", [])
        if not views:
            print("no scripted pr_views", file=sys.stderr)
            raise SystemExit(1)
        idx = min(call_no - 1, len(views) - 1)
        resp = views[idx]
        if resp.get("error"):
            print(resp["error"], file=sys.stderr)
            raise SystemExit(resp.get("rc", 1))
        print(json.dumps(resp))
        raise SystemExit(0)

    log({"op": "unknown", "argv": argv})
    print(f"unexpected gh argv: {argv}", file=sys.stderr)
    raise SystemExit(2)
    """
)


def load_module():
    loader = importlib.machinery.SourceFileLoader("gh_pr_wait_mod", str(TOOL))
    spec = importlib.util.spec_from_loader("gh_pr_wait_mod", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    loader.exec_module(mod)
    return mod


def make_env(tmp_path: Path, cfg: dict, *, extra_env: dict[str, str] | None = None, state_dir: Path | None = None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    fake_gh = tmp_path / "fake_gh.py"
    fake_gh.write_text(FAKE_GH_SCRIPT, encoding="utf-8")
    fake_gh.chmod(0o755)
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    log_path = tmp_path / "events.jsonl"
    counter_path = tmp_path / "counter.json"
    pid_path = tmp_path / "listen.pid"
    sdir = state_dir if state_dir is not None else (tmp_path / "state")
    env = dict(os.environ)
    env.pop("DEADLINE_NAME", None)
    env.pop("GH_PR_WAIT_TEST_MIN_INTERVAL", None)
    env.pop("GH_PR_WAIT_TEST_STOP_TIMEOUT", None)
    env["GH_BIN"] = str(fake_gh)
    env["GH_PR_WAIT_STATE_DIR"] = str(sdir)
    env["FAKE_GH_CONFIG"] = str(cfg_path)
    env["FAKE_GH_LOG"] = str(log_path)
    env["FAKE_GH_COUNTER"] = str(counter_path)
    env["FAKE_GH_LISTEN_PID"] = str(pid_path)
    if extra_env:
        env.update(extra_env)
    return env, log_path


def read_log(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    return [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_wait(args: list[str], env: dict[str, str], timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(TOOL), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def pr_state(
    *,
    state: str = "OPEN",
    merged_at: str | None = None,
    head: str = "abc123def456",
    checks: list[dict] | None = None,
    reviews: list[dict] | None = None,
    mergeable: str = "MERGEABLE",
    url: str = "https://github.com/djbclark/demo/pull/42",
) -> dict:
    return {
        "url": url,
        "state": state,
        "mergedAt": merged_at,
        "headRefOid": head,
        "mergeable": mergeable,
        "statusCheckRollup": checks if checks is not None else [],
        "reviews": reviews if reviews is not None else [],
    }


def test_attach_then_read_ordering_and_instant_wake_pass(tmp_path):
    cfg = {
        "created_sub_id": "sub_pass_1",
        "create_http_status": 201,
        "attach_delay_s": 0.05,
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "name": "ci", "status": "IN_PROGRESS", "conclusion": ""}]),
            pr_state(checks=[
                {"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {"__typename": "CheckRun", "name": "opt", "status": "COMPLETED", "conclusion": "SKIPPED"},
                {"__typename": "CheckRun", "name": "info", "status": "COMPLETED", "conclusion": "NEUTRAL"},
            ]),
        ],
        "listen_actions": [
            {
                "after_pr_views": 1,
                "kind": "event",
                "event": {
                    "id": "ev_1",
                    "type": "com.github.pull_request.check_suite.status.changed.v1",
                    "data": {"conclusion": "success"},
                },
            }
        ],
    }
    env, log_path = make_env(tmp_path, cfg, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    r = run_wait(["https://github.com/djbclark/demo/pull/42", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["ok"] is True
    assert out["mode"] == "event-stream"
    assert out["reason"] == "checks_passed"
    assert out["events_received"] == 1
    assert out["subscription_id"] == "sub_pass_1"
    assert out["subscription_deleted"] is True
    assert out["checks_summary"] == {"total": 3, "passed": 3, "failed": 0, "pending": 0}

    ops = read_log(log_path)
    op_names = [e["op"] for e in ops]
    idx_ready = op_names.index("listen_ready")
    idx_first_view = op_names.index("pr_view")
    assert idx_ready < idx_first_view
    assert ops[idx_ready]["t"] <= ops[idx_first_view]["t"]
    idx_exited = op_names.index("listen_exited")
    idx_delete = op_names.index("sub_delete")
    assert idx_exited < idx_delete
    assert ops[idx_delete]["listen_alive"] is False
    assert "--" in ops[idx_delete]["argv"]


def test_http_200_reused_subscription_across_state_dirs_never_deleted(tmp_path):
    """I.1: HTTP 200 OK from POST /event-subscriptions proves server reuse -> NEVER deleted even with fresh state dir."""
    cfg = {
        "created_sub_id": "sub_remote_200",
        "create_http_status": 200,
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        ],
    }
    env, log_path = make_env(tmp_path / "other_host", cfg)
    r = run_wait(["djbclark/demo#42", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["subscription_id"] == "sub_remote_200"
    assert out["subscription_deleted"] is False
    assert not any(e["op"] == "sub_delete" for e in read_log(log_path))


def test_failed_refcount_write_on_tracked_subscription_falls_back_cleanly(tmp_path, monkeypatch):
    """I.1: When joining an existing tracked subscription, a failed refcount write falls back instead of attaching unregistered."""
    mod = load_module()
    sdir = tmp_path / "state"
    monkeypatch.setenv("GH_PR_WAIT_STATE_DIR", str(sdir))
    pr_ref = mod.PRRef(url="https://github.com/djbclark/demo/pull/42", host="github.com", owner="djbclark", repo="demo", number=42)
    coord = mod.SubscriptionCoord(pr_ref, mod.EVENTS_FOR["checks"])
    # Seed state with an active local waiter (current test process).
    coord._ensure_dir()
    assert coord._write_state({
        "sub_id": "sub_tracked_1",
        "shared_external": False,
        "keep_forever": False,
        "waiters": [coord._me_entry()],
    })
    # Force subsequent _write_state to fail.
    monkeypatch.setattr(coord, "_write_state", lambda data: False)
    logs: list[str] = []
    session = mod.StreamSession(coord, keep_subscription=False, cancel=mod.CancelState(), log_fn=logs.append)
    ok, fb = mod._acquire_subscription(
        pr_ref, mod.EVENTS_FOR["checks"], session, time.monotonic() + 5.0, mod.CancelState(), logs.append,
    )
    assert ok is False
    assert fb is not None and "falling back" in fb
    assert session.sub_id is None


def test_concurrent_waiters_share_subscription_and_only_last_deletes(tmp_path):
    """I.1: Two interleaved concurrent waiters share one 201 subscription; only the last exiting waiter deletes it."""
    shared_state = tmp_path / "shared_state"
    cfg_a = {
        "created_sub_id": "sub_shared_1",
        "create_http_status": 201,
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "name": "ci", "status": "IN_PROGRESS", "conclusion": ""}]),
            pr_state(checks=[{"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        ],
        "listen_actions": [
            {"after_pr_views": 1, "delay_s": 0.4, "kind": "event", "event": {"id": "ev_a", "type": "com.github.pull_request.check_suite.status.changed.v1"}},
        ],
    }
    cfg_b = {
        "created_sub_id": "sub_should_not_create",
        "create_http_status": 201,
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "name": "ci", "status": "IN_PROGRESS", "conclusion": ""}]),
            pr_state(checks=[{"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        ],
        "listen_actions": [
            {"after_pr_views": 1, "delay_s": 0.9, "kind": "event", "event": {"id": "ev_b", "type": "com.github.pull_request.check_suite.status.changed.v1"}},
        ],
    }
    env_a, log_a = make_env(tmp_path / "a", cfg_a, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"}, state_dir=shared_state)
    env_b, log_b = make_env(tmp_path / "b", cfg_b, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"}, state_dir=shared_state)

    pa = subprocess.Popen(
        [str(TOOL), "djbclark/demo#42", "--no-deadline", "--json"],
        env=env_a, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    dl = time.monotonic() + 5.0
    while time.monotonic() < dl:
        if any(e["op"] == "pr_view" for e in read_log(log_a)):
            break
        time.sleep(0.02)
    pb = subprocess.Popen(
        [str(TOOL), "DJBCLARK/DEMO#42", "--no-deadline", "--json"],
        env=env_b, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    out_a, err_a = pa.communicate(timeout=15)
    out_b, err_b = pb.communicate(timeout=15)
    assert pa.returncode == 0, err_a
    assert pb.returncode == 0, err_b
    res_a = json.loads(out_a)
    res_b = json.loads(out_b)
    assert res_a["subscription_id"] == "sub_shared_1"
    assert res_b["subscription_id"] == "sub_shared_1"
    assert res_a["subscription_deleted"] is False
    assert res_b["subscription_deleted"] is True
    assert not any(e["op"] == "sub_delete" for e in read_log(log_a))
    assert sum(1 for e in read_log(log_b) if e["op"] == "sub_delete") == 1
    assert not any(e["op"] == "sub_create" for e in read_log(log_b))
    assert (shared_state.stat().st_mode & 0o777) == 0o700


def test_durable_keep_forever_after_waiter_a_unproven_reap_blocks_waiter_b_delete(tmp_path, monkeypatch):
    """I.2: Waiter A fails to reap its listener -> writes durable keep_forever=True -> Waiter B closing cleanly skips delete!"""
    mod = load_module()
    sdir = tmp_path / "state"
    monkeypatch.setenv("GH_PR_WAIT_STATE_DIR", str(sdir))
    monkeypatch.setenv("GH_PR_WAIT_TEST_STOP_TIMEOUT", "0.05")
    deleted: list[list[str]] = []
    monkeypatch.setattr(mod, "run_gh", lambda args, **kw: (deleted.append(args) or (0, "", "")))

    class StuckProc:
        pid = 999999
        stdout = None
        stderr = None

        def poll(self):
            return None

        def terminate(self):
            pass

        def kill(self):
            pass

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(["gh"], timeout or 0.05)

    pr_ref = mod.PRRef(url="https://github.com/djbclark/demo/pull/42", host="github.com", owner="djbclark", repo="demo", number=42)
    coord_a = mod.SubscriptionCoord(pr_ref, mod.EVENTS_FOR["checks"])
    coord_b = mod.SubscriptionCoord(pr_ref, mod.EVENTS_FOR["checks"])
    # Simulate two distinct live waiters A and B sharing one 201-created subscription.
    coord_a._ensure_dir()
    me_a = coord_a._me_entry()
    assert me_a is not None
    coord_b.pid = os.getppid()
    coord_b.start_token = mod.proc_start_token(coord_b.pid)
    me_b = coord_b._me_entry()
    assert me_b is not None
    assert coord_a._write_state({
        "sub_id": "sub_shared_reap",
        "shared_external": False,
        "keep_forever": False,
        "waiters": [me_a, me_b],
    })

    logs_a: list[str] = []
    sess_a = mod.StreamSession(coord_a, keep_subscription=False, cancel=mod.CancelState(), log_fn=logs_a.append)
    sess_a.sub_id = "sub_shared_reap"
    sess_a.ownership_confirmed = True
    sess_a.shared_external = False
    sess_a.registered_in_coord = True
    sess_a.attach_proc(StuckProc())  # type: ignore[arg-type]

    # Waiter A closes with unproven reap -> skips delete AND persists keep_forever=True.
    assert sess_a.close() is False
    assert sess_a.listener_reaped is False
    assert sess_a.proc is not None
    st_after_a = coord_a._read_state()
    assert st_after_a["keep_forever"] is True
    assert deleted == []

    # Waiter B now closes cleanly with no remaining waiters -> MUST STILL SKIP DELETE!
    logs_b: list[str] = []
    sess_b = mod.StreamSession(coord_b, keep_subscription=False, cancel=mod.CancelState(), log_fn=logs_b.append)
    sess_b.sub_id = "sub_shared_reap"
    sess_b.ownership_confirmed = True
    sess_b.shared_external = False
    sess_b.registered_in_coord = True
    assert sess_b.close() is False
    assert deleted == []


def test_listener_ignoring_sigterm_escalates_to_sigkill_then_deletes(tmp_path):
    """I.2: Listener ignoring SIGTERM gets SIGKILLed, reaped, and only then subscription is deleted."""
    cfg = {
        "created_sub_id": "sub_kill_1",
        "create_http_status": 201,
        "ignore_sigterm": True,
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        ],
    }
    env, log_path = make_env(tmp_path, cfg, extra_env={"GH_PR_WAIT_TEST_STOP_TIMEOUT": "0.2"})
    r = run_wait(["djbclark/demo#42", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["subscription_deleted"] is True
    del_ev = next(e for e in read_log(log_path) if e["op"] == "sub_delete")
    assert del_ev["listen_alive"] is False


def test_cancellation_during_subscription_create_cleans_up(tmp_path):
    """I.2: SIGTERM arriving during subscription create still records ownership and deletes it."""
    cfg = {
        "created_sub_id": "sub_mid_create",
        "create_http_status": 201,
        "create_delay_s": 0.4,
        "pr_views": [pr_state(checks=[{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": ""}])],
    }
    env, log_path = make_env(tmp_path, cfg)
    proc = subprocess.Popen(
        [str(TOOL), "djbclark/demo#42", "--timeout", "30s", "--no-deadline"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        dl = time.monotonic() + 5.0
        while time.monotonic() < dl:
            if any(e["op"] == "sub_create" for e in read_log(log_path)):
                break
            time.sleep(0.02)
        else:
            pytest.fail("sub_create never started")
        proc.send_signal(signal.SIGTERM)
        rc = proc.wait(timeout=10.0)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert rc == 143
    assert any(e["op"] == "sub_delete" and e["id"] == "sub_mid_create" for e in read_log(log_path))


def test_sigterm_and_repeated_signals_clean_up_once(tmp_path):
    """I.2: Repeated SIGTERMs do not abort cleanup; stream exits before delete and exits 143."""
    cfg = {
        "created_sub_id": "sub_sig_1",
        "create_http_status": 201,
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": ""}]),
        ],
    }
    env, log_path = make_env(tmp_path, cfg)
    proc = subprocess.Popen(
        [str(TOOL), "djbclark/demo#42", "--timeout", "30s", "--no-deadline"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if any(e["op"] == "pr_view" for e in read_log(log_path)):
                break
            time.sleep(0.03)
        else:
            pytest.fail("timed out waiting for initial pr_view before SIGTERM")
        proc.send_signal(signal.SIGTERM)
        time.sleep(0.03)
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
        rc = proc.wait(timeout=10.0)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert rc == 143
    ops = read_log(log_path)
    op_names = [e["op"] for e in ops]
    assert op_names.index("listen_exited") < op_names.index("sub_delete")
    assert sum(1 for e in ops if e["op"] == "sub_delete") == 1
    assert ops[op_names.index("sub_delete")]["listen_alive"] is False


def test_instant_wake_check_failure_and_pr_closed(tmp_path):
    cfg = {
        "created_sub_id": "sub_fail_1",
        "create_http_status": 201,
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "name": "ci", "status": "QUEUED", "conclusion": ""}]),
            pr_state(checks=[
                {"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "FAILURE"},
                {"__typename": "CheckRun", "name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
            ]),
        ],
        "listen_actions": [
            {"after_pr_views": 1, "kind": "event", "event": {"id": "ev_fail", "type": "com.github.pull_request.check_suite.status.changed.v1"}},
        ],
    }
    env, _ = make_env(tmp_path, cfg, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    r = run_wait(["djbclark/demo#42", "--no-deadline", "--json"], env)
    assert r.returncode == 1, r.stderr
    out = json.loads(r.stdout)
    assert out["ok"] is False and out["reason"] == "checks_failed" and out["subscription_deleted"] is True

    cfg2 = {
        "created_sub_id": "sub_closed_1",
        "create_http_status": 201,
        "pr_views": [
            pr_state(state="OPEN", checks=[{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": ""}]),
            pr_state(state="CLOSED", checks=[{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": ""}]),
        ],
        "listen_actions": [
            {"after_pr_views": 1, "kind": "event", "event": {"id": "ev_c", "type": "com.github.pull_request.state.changed.v1"}},
        ],
    }
    env2, _ = make_env(tmp_path / "closed", cfg2, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    r2 = run_wait(["djbclark/demo#42", "--for", "checks", "--no-deadline", "--json"], env2)
    assert r2.returncode == 1 and json.loads(r2.stdout)["reason"] == "pr_closed"


def test_already_passing_keep_subscription_and_empty_checks(tmp_path):
    cfg = {
        "created_sub_id": "sub_keep_1",
        "create_http_status": 201,
        "pr_views": [pr_state(checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}])],
    }
    env, log_path = make_env(tmp_path / "keep", cfg)
    r = run_wait(["djbclark/demo#42", "--keep-subscription", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["subscription_deleted"] is False
    assert all(e["op"] != "sub_delete" for e in read_log(log_path))

    cfg_e = {
        "created_sub_id": "sub_empty_1",
        "create_http_status": 201,
        "pr_views": [
            pr_state(checks=[]),
            pr_state(checks=[{"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        ],
        "listen_actions": [
            {"after_pr_views": 1, "kind": "event", "event": {"id": "ev_e1", "type": "com.github.pull_request.check_suite.status.changed.v1"}},
        ],
    }
    env_e, _ = make_env(tmp_path / "empty_wait", cfg_e, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    re = run_wait(["djbclark/demo#42", "--no-deadline", "--json"], env_e)
    assert re.returncode == 0 and "checks_pending_empty" in re.stderr

    env_a, _ = make_env(tmp_path / "empty_allow", {"created_sub_id": "sub_e2", "create_http_status": 201, "pr_views": [pr_state(checks=[])]})
    ra = run_wait(["djbclark/demo#42", "--allow-empty-checks", "--no-deadline", "--json"], env_a)
    assert ra.returncode == 0 and json.loads(ra.stdout)["reason"] == "checks_empty_allowed"


def test_review_pending_to_submitted_and_dismissed_does_not_false_trigger(tmp_path):
    """I.3 & II.1: PENDING->submitted triggers; APPROVED->DISMISSED on existing review does NOT trigger; GraphQL omits body."""
    cfg = {
        "created_sub_id": "sub_rev_imm",
        "create_http_status": 201,
        "pr_views": [
            # Baseline: R_exist (APPROVED) + R_draft (PENDING, excluded)
            pr_state(reviews=[
                {"id": "PRR_exist", "databaseId": 1001, "state": "APPROVED", "submittedAt": "2026-11-25T10:00:00Z"},
                {"id": "PRR_draft", "databaseId": 1002, "state": "PENDING", "submittedAt": None},
            ]),
            # R_exist becomes DISMISSED (mutable state change, same (id, submittedAt)) -> MUST NOT trigger!
            pr_state(reviews=[
                {"id": "PRR_exist", "databaseId": 1001, "state": "DISMISSED", "submittedAt": "2026-11-25T10:00:00Z"},
                {"id": "PRR_draft", "databaseId": 1002, "state": "PENDING", "submittedAt": None},
            ]),
            # R_draft is finally submitted -> MUST trigger!
            pr_state(reviews=[
                {"id": "PRR_exist", "databaseId": 1001, "state": "DISMISSED", "submittedAt": "2026-11-25T10:00:00Z"},
                {"id": "PRR_draft", "databaseId": 1002, "state": "COMMENTED", "submittedAt": "2026-11-25T10:05:00Z"},
            ]),
        ],
        "listen_actions": [
            {"after_pr_views": 1, "kind": "event", "event": {"id": "ev_r1", "type": "com.github.pull_request.review.submitted.v1", "data": {"api_url": "https://api.github.com/repos/djbclark/demo/pulls/42/reviews/9999"}}},
            {"after_pr_views": 2, "kind": "event", "event": {"id": "ev_r2", "type": "com.github.pull_request.review.submitted.v1", "data": {"api_url": "https://api.github.com/repos/djbclark/demo/pulls/42/reviews/1002"}}},
        ],
    }
    env, log_path = make_env(tmp_path, cfg, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    r = run_wait(["djbclark/demo#42", "--for", "review", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["reason"] == "review_submitted"
    gql_calls = [e for e in read_log(log_path) if e["op"] == "pr_view"]
    assert len(gql_calls) == 3
    for call in gql_calls:
        assert call["kind"] == "graphql"
        assert "body" not in " ".join(call["argv"])


def test_review_exact_api_url_correlation_vs_unrelated_same_second_review(tmp_path):
    """I.3: Exact databaseId correlation from data.api_url reconciles post-attach review; unrelated event never matches pre-attach review."""
    # Case A: Pre-attach review (databaseId 1001, even in same wall-clock second!) + unrelated event for 9999 -> MUST NOT trigger!
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cfg_unrel = {
        "created_sub_id": "sub_unrel",
        "create_http_status": 201,
        "pr_views": [
            pr_state(reviews=[{"id": "PRR_1001", "databaseId": 1001, "state": "APPROVED", "submittedAt": now_iso}]),
        ],
        "listen_actions": [
            {"after_pr_views": 1, "kind": "event", "event": {"id": "ev_other", "type": "com.github.pull_request.review.submitted.v1", "data": {"api_url": "https://api.github.com/repos/djbclark/demo/pulls/42/reviews/9999"}}},
        ],
    }
    env_u, _ = make_env(tmp_path / "unrel", cfg_unrel, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    ru = run_wait(["djbclark/demo#42", "--for", "review", "--timeout", "0.35s", "--no-deadline", "--json"], env_u)
    assert ru.returncode == 8, ru.stderr

    # Case B: Post-attach review (databaseId 2002) folded into initial snapshot + exact matching api_url event -> triggers!
    cfg_match = {
        "created_sub_id": "sub_match",
        "create_http_status": 201,
        "pr_views": [
            pr_state(reviews=[{"id": "PRR_2002", "databaseId": 2002, "state": "APPROVED", "submittedAt": now_iso}]),
        ],
        "listen_actions": [
            {"after_pr_views": 1, "kind": "event", "event": {"id": "ev_2002", "type": "com.github.pull_request.review.submitted.v1", "data": {"api_url": "https://api.github.com/repos/djbclark/demo/pulls/42/reviews/2002"}}},
        ],
    }
    env_m, _ = make_env(tmp_path / "match", cfg_match, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    rm = run_wait(["djbclark/demo#42", "--for", "review", "--no-deadline", "--json"], env_m)
    assert rm.returncode == 0, rm.stderr
    assert json.loads(rm.stdout)["reason"] == "review_submitted"


def test_review_stream_to_poll_fallback_preserves_baseline(tmp_path):
    """I.3: Baseline established in stream is preserved on fallback to polling."""
    rev1 = {"id": "R1", "databaseId": 1, "state": "COMMENTED", "submittedAt": "2020-01-01T00:00:00Z"}
    rev2 = {"id": "R2", "databaseId": 2, "state": "APPROVED", "submittedAt": "2026-11-25T12:00:00Z"}
    cfg = {
        "created_sub_id": "sub_fb_base",
        "create_http_status": 201,
        "pr_views": [
            pr_state(reviews=[rev1]),
            pr_state(reviews=[rev1]),
            pr_state(reviews=[rev1, rev2]),
        ],
        "listen_actions": [{"after_pr_views": 1, "kind": "exit", "rc": 1}],
    }
    env, _ = make_env(tmp_path, cfg, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    r = run_wait(["djbclark/demo#42", "--for", "review", "--fallback-interval", "0.02", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["mode"] == "poll-fallback" and out["reason"] == "review_submitted"


def test_for_any_poll_fallback_detects_review_only_and_mergeable_only_deltas(tmp_path):
    """I.4: --for any poll fallback detects review-only and mergeability-only deltas without fetching review bodies."""
    rev1 = {"id": "R1", "databaseId": 1, "state": "COMMENTED", "submittedAt": "2020-01-01T00:00:00Z"}
    rev2 = {"id": "R2", "databaseId": 2, "state": "APPROVED", "submittedAt": "2026-11-25T12:00:00Z"}
    # Stream exits mid-wait -> poll fallback sees ONLY a new review (head/checks/state unchanged).
    cfg_rev = {
        "created_sub_id": "sub_any_rev",
        "create_http_status": 201,
        "pr_views": [
            pr_state(reviews=[rev1], mergeable="MERGEABLE"),
            pr_state(reviews=[rev1], mergeable="MERGEABLE"),
            pr_state(reviews=[rev1, rev2], mergeable="MERGEABLE"),
        ],
        "listen_actions": [{"after_pr_views": 1, "kind": "exit", "rc": 1}],
    }
    env_r, log_r = make_env(tmp_path / "any_rev", cfg_rev, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    rr = run_wait(["djbclark/demo#42", "--for", "any", "--fallback-interval", "0.02", "--no-deadline", "--json"], env_r)
    assert rr.returncode == 0, rr.stderr
    out_r = json.loads(rr.stdout)
    assert out_r["mode"] == "poll-fallback" and out_r["reason"] == "state_changed"
    for call in [e for e in read_log(log_r) if e["op"] == "pr_view"]:
        assert call["kind"] == "graphql"
        assert "body" not in " ".join(call["argv"])

    # Non-github host poll fallback detects mergeability-only delta (MERGEABLE -> CONFLICTING).
    ghe_url = "https://ghe.example.com/djbclark/demo/pull/42"
    cfg_m = {
        "pr_views": [
            pr_state(url=ghe_url, mergeable="MERGEABLE"),
            pr_state(url=ghe_url, mergeable="CONFLICTING"),
        ],
    }
    env_m, _ = make_env(tmp_path / "any_mergeable", cfg_m, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    rm = run_wait([ghe_url, "--for", "any", "--fallback-interval", "0.02", "--no-deadline", "--json"], env_m)
    assert rm.returncode == 0, rm.stderr
    assert json.loads(rm.stdout)["reason"] == "state_changed"


def test_for_any_requires_subscribed_type_and_nonempty_id_and_detects_check_swap(tmp_path):
    """II.2: --for any ignores missing id and unsubscribed types; poll detects equal-count check swap."""
    ev_valid = {"id": "ev_any_1", "type": "com.github.pull_request.head.changed.v1", "data": {}}
    cfg = {
        "created_sub_id": "sub_any_1",
        "create_http_status": 201,
        "pr_views": [pr_state(head="oldsha"), pr_state(head="newsha")],
        "listen_actions": [
            {"after_pr_views": 1, "kind": "stdout_raw", "text": '{"not_an_event": true}'},
            {"after_pr_views": 1, "kind": "stdout_raw", "text": '{"type": "com.github.pull_request.head.changed.v1"}'},  # missing id!
            {"after_pr_views": 1, "kind": "stdout_raw", "text": '{"id": "x", "type": "com.github.bogus.v1"}'},  # unsubscribed type!
            {"after_pr_views": 1, "delay_s": 0.05, "kind": "event", "event": ev_valid},
        ],
    }
    env, _ = make_env(tmp_path / "stream", cfg, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    r = run_wait(["djbclark/demo#42", "--for", "any", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["event"] == ev_valid and out["events_received"] == 1

    # Equal-count check swap on poll fallback.
    ghe_url = "https://ghe.example.com/djbclark/demo/pull/42"
    cfg_swap = {
        "pr_views": [
            pr_state(url=ghe_url, checks=[
                {"__typename": "CheckRun", "name": "ci-a", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {"__typename": "CheckRun", "name": "ci-b", "status": "COMPLETED", "conclusion": "FAILURE"},
            ]),
            pr_state(url=ghe_url, checks=[
                {"__typename": "CheckRun", "name": "ci-a", "status": "COMPLETED", "conclusion": "FAILURE"},
                {"__typename": "CheckRun", "name": "ci-b", "status": "COMPLETED", "conclusion": "SUCCESS"},
            ]),
        ],
    }
    env_s, _ = make_env(tmp_path / "swap", cfg_swap, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.03"})
    rs = run_wait([ghe_url, "--for", "any", "--fallback-interval", "0.03", "--no-deadline", "--json"], env_s)
    assert rs.returncode == 0 and json.loads(rs.stdout)["reason"] == "state_changed"


def test_for_merge_and_malformed_pr_state_fail_closed(tmp_path):
    cfg = {
        "created_sub_id": "sub_m_1",
        "create_http_status": 201,
        "pr_views": [
            pr_state(state="OPEN"),
            pr_state(state="MERGED", merged_at="2026-11-25T10:00:00Z"),
        ],
        "listen_actions": [
            {"after_pr_views": 1, "kind": "event", "event": {"id": "ev_m", "type": "com.github.pull_request.state.changed.v1"}},
        ],
    }
    env, log_path = make_env(tmp_path / "merged", cfg, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    r = run_wait(["djbclark/demo#42", "--for", "merge", "--no-deadline", "--json"], env)
    assert r.returncode == 0 and json.loads(r.stdout)["merged"] is True
    for ev in read_log(log_path):
        if ev["op"] == "pr_view":
            assert "reviews" not in ev["json"] and "statusCheckRollup" not in ev["json"]

    # OPEN PR with truthy malformed mergedAt -> rejected (timeout 8).
    env_m, _ = make_env(
        tmp_path / "bad_m",
        {"created_sub_id": "sub_bm", "create_http_status": 201, "pr_views": [pr_state(state="OPEN", merged_at="not-a-ts")]},
        extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.05"},
    )
    assert run_wait(["djbclark/demo#42", "--for", "merge", "--timeout", "0.25s", "--no-deadline", "--json"], env_m).returncode == 8

    # Non-list statusCheckRollup with --allow-empty-checks -> NEVER passes!
    bad_pr = pr_state(state="OPEN")
    bad_pr["statusCheckRollup"] = "corrupt"  # type: ignore[assignment]
    env_r, _ = make_env(
        tmp_path / "bad_r",
        {"created_sub_id": "sub_br", "create_http_status": 201, "pr_views": [bad_pr]},
        extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.05"},
    )
    assert run_wait(["djbclark/demo#42", "--allow-empty-checks", "--timeout", "0.25s", "--no-deadline", "--json"], env_r).returncode == 8


def test_event_burst_dedup_rate_limit_and_safety_floor(tmp_path):
    cfg = {
        "created_sub_id": "sub_burst_1",
        "create_http_status": 201,
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": ""}]),
            {"error": "HTTP 429 API rate limit exceeded", "rc": 1},
            pr_state(checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        ],
        "listen_actions": [
            {"after_pr_views": 1, "kind": "event", "event": {"id": "dup_1", "type": "com.github.pull_request.check_suite.status.changed.v1"}},
            {"after_pr_views": 1, "kind": "event", "event": {"id": "dup_1", "type": "com.github.pull_request.check_suite.status.changed.v1"}},
            {"after_pr_views": 1, "kind": "event", "event": {"id": "ev_2", "type": "com.github.pull_request.check_suite.status.changed.v1"}},
            {"after_pr_views": 2, "kind": "event", "event": {"id": "ev_3", "type": "com.github.pull_request.check_suite.status.changed.v1"}},
        ],
    }
    env, log_path = make_env(tmp_path / "burst", cfg, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.05"})
    r = run_wait(["djbclark/demo#42", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["events_received"] == 3
    assert "rate limit hit; backing off" in r.stderr
    assert len([e for e in read_log(log_path) if e["op"] == "pr_view"]) == 3

    env_sf, _ = make_env(
        tmp_path / "floor",
        {"created_sub_id": "sub_sf", "create_http_status": 201, "pr_views": [pr_state(checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}])]},
    )
    rsf = run_wait(["djbclark/demo#42", "--safety-interval", "5", "--no-deadline", "--json"], env_sf)
    assert rsf.returncode == 0 and "clamping --safety-interval from 5s to 30s" in rsf.stderr


def test_strict_readiness_split_utf8_oversize_and_reconnect_heartbeat(tmp_path):
    cfg = {
        "created_sub_id": "sub_io_1",
        "create_http_status": 201,
        "pre_attach_stderr": ["Almost Listening for events. not yet"],
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": ""}]),
            pr_state(checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        ],
        "listen_actions": [
            {"after_pr_views": 1, "kind": "oversize_line"},
            {"after_pr_views": 1, "kind": "stdout_raw", "text": ": keepalive"},
            {"after_pr_views": 1, "kind": "stderr", "text": "Listening for events."},
        ],
    }
    env, log_path = make_env(tmp_path / "io", cfg, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    r = run_wait(["djbclark/demo#42", "--no-deadline", "--safety-interval", "300"], env)
    assert r.returncode == 0, r.stderr
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1 and "gh-pr-wait: ok" in lines[0]
    assert len([e for e in read_log(log_path) if e["op"] == "pr_view"]) == 2

    ev_utf8 = {"id": "ev_u", "type": "com.github.pull_request.head.changed.v1", "data": {"note": "héllo 🚀"}}
    cfg_u = {
        "created_sub_id": "sub_utf8",
        "create_http_status": 201,
        "pr_views": [pr_state()],
        "listen_actions": [{"after_pr_views": 1, "kind": "split_utf8_event", "event": ev_utf8}],
    }
    env_u, _ = make_env(tmp_path / "utf8", cfg_u, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    ru = run_wait(["djbclark/demo#42", "--for", "any", "--no-deadline", "--json"], env_u)
    assert ru.returncode == 0, ru.stderr
    assert json.loads(ru.stdout)["event"] == ev_utf8


@pytest.mark.parametrize("case", ["403_create", "422_create", "unknown_event_cmd", "attach_timeout", "non_github"])
def test_fallback_to_polling(tmp_path, case):
    url = "https://ghe.example.com/djbclark/demo/pull/42" if case == "non_github" else "https://github.com/djbclark/demo/pull/42"
    cfg: dict = {
        "create_http_status": 201,
        "pr_views": [
            pr_state(url=url, checks=[{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": ""}]),
            pr_state(url=url, checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        ],
    }
    extra_args: list[str] = []
    if case == "403_create":
        cfg["create_error"] = {"rc": 1, "stderr": "HTTP 403: Event subscriptions are not enabled for this account"}
    elif case == "422_create":
        cfg["create_error"] = {"rc": 1, "stderr": "HTTP 422: Subscription limit exceeded"}
    elif case == "unknown_event_cmd":
        cfg["listen_fail_before_attach"] = {"rc": 1, "stderr": 'unknown command "event" for "gh"'}
    elif case == "attach_timeout":
        cfg["listen_hang_before_attach"] = True
        extra_args = ["--attach-timeout", "0.2"]

    env, log_path = make_env(tmp_path, cfg, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.03"})
    r = run_wait([url, "--fallback-interval", "0.03", "--no-deadline", "--json", *extra_args], env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["ok"] is True and out["mode"] == "poll-fallback" and out["subscription_id"] is None

    ops = read_log(log_path)
    if case == "non_github":
        assert not any(e["op"].startswith(("sub_", "listen_")) for e in ops)
    if case == "attach_timeout":
        op_names = [e["op"] for e in ops]
        assert op_names.index("listen_exited") < op_names.index("sub_delete")


def test_polling_clamp_and_timeout_guards(tmp_path):
    url = "https://ghe.example.com/djbclark/demo/pull/42"
    env, _ = make_env(tmp_path / "clamp", {"pr_views": [pr_state(url=url, checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}])]})
    r = run_wait([url, "--fallback-interval", "5", "--no-deadline", "--json"], env)
    assert r.returncode == 0 and "clamping --fallback-interval from 5s to 60s" in r.stderr

    # Attach hangs past entire timeout -> exits 8 without running fallback pr_view.
    cfg_exp = {
        "created_sub_id": "sub_exp_1",
        "create_http_status": 201,
        "listen_hang_before_attach": True,
        "pr_views": [pr_state(checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}])],
    }
    env_e, log_e = make_env(tmp_path / "exp", cfg_exp, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    assert run_wait(["djbclark/demo#42", "--timeout", "0.25s", "--attach-timeout", "5", "--no-deadline", "--json"], env_e).returncode == 8
    assert not any(e["op"] == "pr_view" for e in read_log(log_e))

    # Bare-number URL inference timeout maps cleanly to exit 8 (not exit 2!).
    cfg_inf = {"infer_delay_s": 0.5, "infer_url": "https://github.com/djbclark/demo/pull/42"}
    env_i, _ = make_env(tmp_path / "inf_to", cfg_inf)
    assert run_wait(["42", "--timeout", "0.15s", "--no-deadline"], env_i).returncode == 8


def test_safety_net_timer_catches_rest_status_context_with_zero_events(tmp_path):
    cfg = {
        "created_sub_id": "sub_safety_1",
        "create_http_status": 201,
        "pr_views": [
            pr_state(checks=[{"__typename": "StatusContext", "context": "ci/legacy", "state": "PENDING"}]),
            pr_state(checks=[{"__typename": "StatusContext", "context": "ci/legacy", "state": "SUCCESS"}]),
        ],
    }
    env, _ = make_env(tmp_path, cfg, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.05"})
    r = run_wait(["djbclark/demo#42", "--safety-interval", "0.1", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["ok"] is True and out["mode"] == "event-stream" and out["events_received"] == 0


def test_cleanup_validates_operands_caches_pr_and_rejects_malformed(tmp_path):
    subs = [
        {"id": "sub_merged", "resourceUrl": "https://github.com/o/r/pull/1", "eventTypes": ["a"]},
        {"id": "sub_closed_1", "resourceUrl": "https://github.com/o/r/pull/2", "eventTypes": ["a"]},
        {"id": "sub_closed_2", "resourceUrl": "https://github.com/O/R/pull/2", "eventTypes": ["b"]},
        {"id": "sub_open_bad_ts", "resourceUrl": "https://github.com/o/r/pull/3", "eventTypes": ["a"]},
        {"id": "sub_unreadable", "resourceUrl": "https://github.com/o/r/pull/4", "eventTypes": ["a"]},
        {"id": "sub_mismatch", "resourceUrl": "https://github.com/o/r/pull/5", "eventTypes": ["a"]},
        {"id": "-flag-shaped", "resourceUrl": "https://github.com/o/r/pull/1", "eventTypes": ["a"]},
        {"id": "sub_bad_url", "resourceUrl": "--help", "eventTypes": ["a"]},
    ]
    pr_views_by_url = {
        "https://github.com/o/r/pull/1": {"url": "https://github.com/o/r/pull/1", "state": "MERGED"},
        "https://github.com/o/r/pull/2": {"url": "https://github.com/o/r/pull/2", "state": "CLOSED"},
        "https://github.com/o/r/pull/3": {"url": "https://github.com/o/r/pull/3", "state": "OPEN", "mergedAt": "truthy-garbage"},
        "https://github.com/o/r/pull/4": {"error": "HTTP 404 Not Found"},
        "https://github.com/o/r/pull/5": {"url": "https://github.com/other/repo/pull/99", "state": "CLOSED"},
    }

    env1, log1 = make_env(tmp_path / "dry", {"existing_subs": subs, "pr_views_by_url": pr_views_by_url})
    r1 = run_wait(["cleanup", "--dry-run", "--json"], env1)
    assert r1.returncode == 0
    assert [x["id"] for x in json.loads(r1.stdout)["selected"]] == ["sub_merged", "sub_closed_1", "sub_closed_2"]
    assert all(e["op"] != "sub_delete" for e in read_log(log1))

    env2, log2 = make_env(tmp_path / "run", {"existing_subs": subs, "pr_views_by_url": pr_views_by_url})
    r2 = run_wait(["cleanup", "--json"], env2)
    assert r2.returncode == 0
    out2 = json.loads(r2.stdout)
    assert [x["id"] for x in out2["deleted"]] == ["sub_merged", "sub_closed_1", "sub_closed_2"]
    skip_reasons = {x["id"]: x["reason"] for x in out2["skipped"]}
    assert skip_reasons["sub_open_bad_ts"] == "pr_open"
    assert skip_reasons["sub_unreadable"] == "unreadable_pr"
    assert skip_reasons["sub_mismatch"] == "url_mismatch"
    assert skip_reasons["-flag-shaped"] == "invalid_subscription_id"
    assert skip_reasons["sub_bad_url"] == "invalid_resource_url"
    ops2 = read_log(log2)
    assert sum(1 for e in ops2 if e["op"] == "pr_view" and e["target"] == "https://github.com/o/r/pull/2") == 1

    env3, log3 = make_env(tmp_path / "all", {"existing_subs": subs, "pr_views_by_url": pr_views_by_url})
    r3 = run_wait(["cleanup", "--all", "--json"], env3)
    assert r3.returncode == 0
    out3 = json.loads(r3.stdout)
    assert len(out3["deleted"]) == 7 and [x["id"] for x in out3["skipped"]] == ["-flag-shaped"]
    assert all(e["op"] != "pr_view" for e in read_log(log3))


@pytest.mark.parametrize("bad_args", [
    [""],
    ["0"],
    ["-5"],
    ["not-a-pr"],
    ["owner/repo#abc"],
    ["https://github.com/owner/repo/issues/1"],
    ["https://github.com/owner/repo/pull/1/files"],
    ["https://github.com/owner/repo/pull/1?x=1"],
    ["http://github.com/owner/repo/pull/1"],
    ["owner/repo#1", "-R", "other/repo"],
    ["owner/repo#1", "--timeout", "0"],
    ["owner/repo#1", "--timeout", "notadur"],
    ["owner/repo#1", "--safety-interval", "-5"],
    ["owner/repo#1", "--fallback-interval", "0"],
    ["owner/repo#1", "--attach-timeout", "nan"],
])
def test_invalid_inputs_exit_2(tmp_path, bad_args):
    env, _ = make_env(tmp_path, {})
    r = run_wait([*bad_args, "--no-deadline"], env)
    assert r.returncode == 2, f"expected exit 2 for {bad_args}, got {r.returncode}: {r.stderr}"


def test_supervised_abbreviated_flag_and_single_url_inference(tmp_path):
    """II.3: Supervised inner argv built from parsed values handles abbreviated `--time 99 99` and infers URL once."""
    record_path = tmp_path / "deadline-argv.json"
    fake_deadline = tmp_path / "fake_deadline.py"
    fake_deadline.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            import json, os, subprocess, sys
            from pathlib import Path
            argv = sys.argv[1:]
            if argv and argv[0] == "beat":
                raise SystemExit(0)
            Path({str(record_path)!r}).write_text(json.dumps(argv), encoding="utf-8")
            name = argv[argv.index("--name") + 1]
            cmd = argv[argv.index("--") + 1:]
            env = dict(os.environ, DEADLINE_NAME=name)
            raise SystemExit(subprocess.call(cmd, env=env))
            """
        ),
        encoding="utf-8",
    )
    fake_deadline.chmod(0o755)
    cfg = {
        "created_sub_id": "sub_dl_1",
        "create_http_status": 201,
        "infer_url": "https://github.com/djbclark/inferred/pull/99",
        "pr_views": [
            pr_state(
                url="https://github.com/djbclark/inferred/pull/99",
                checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}],
            ),
        ],
    }
    env, log_path = make_env(tmp_path, cfg, extra_env={"DEADLINE_BIN": str(fake_deadline)})
    r = run_wait(["--time", "99", "99", "--safety-interval", "300", "--json"], env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["pr_url"] == "https://github.com/djbclark/inferred/pull/99"
    assert sum(1 for e in read_log(log_path) if e["op"] == "pr_view_url") == 1
    dl_argv = json.loads(record_path.read_text(encoding="utf-8"))
    inner = dl_argv[dl_argv.index("--") + 1:]
    assert inner[1] == "https://github.com/djbclark/inferred/pull/99"
    assert "--timeout" in inner
    assert inner[inner.index("--timeout") + 1].endswith("s")
