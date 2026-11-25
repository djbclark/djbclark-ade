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

    if argv[:3] == ["event", "subscription", "list"]:
        log({"op": "sub_list", "argv": argv})
        err = cfg.get("list_error")
        if err:
            print(err["stderr"], file=sys.stderr)
            raise SystemExit(err.get("rc", 1))
        print(json.dumps(cfg.get("existing_subs", [])))
        raise SystemExit(0)

    if argv[:3] == ["event", "subscription", "create"]:
        log({"op": "sub_create", "argv": argv})
        if cfg.get("create_delay_s"):
            time.sleep(float(cfg["create_delay_s"]))
        err = cfg.get("create_error")
        if err:
            print(err["stderr"], file=sys.stderr)
            raise SystemExit(err.get("rc", 1))
        print(json.dumps({"id": cfg.get("created_sub_id", "sub_created_1")}))
        raise SystemExit(0)

    if argv[:3] == ["event", "subscription", "delete"]:
        # Enforce `--` before positional sub_id.
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
        node = {
            "url": resp.get("url"),
            "state": resp.get("state"),
            "mergedAt": resp.get("mergedAt"),
            "headRefOid": resp.get("headRefOid"),
            "reviews": {"nodes": resp.get("reviews", [])},
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
    # Verify safe option termination `--` before subscription id.
    assert "--" in ops[idx_delete]["argv"]


def test_concurrent_waiters_share_subscription_and_only_last_deletes(tmp_path):
    """I.1: Two interleaved concurrent waiters share one subscription; only the last exiting waiter deletes it."""
    shared_state = tmp_path / "shared_state"
    # Waiter A finishes quickly after 1 event; Waiter B stays alive until killed/signaled or later event.
    cfg_a = {
        "created_sub_id": "sub_shared_1",
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
    # Wait until Waiter A has attached and recorded its subscription in shared_state.
    dl = time.monotonic() + 5.0
    while time.monotonic() < dl:
        if any(e["op"] == "pr_view" for e in read_log(log_a)):
            break
        time.sleep(0.02)
    # Launch Waiter B with mixed case owner/repo while A is still running!
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
    # First waiter MUST NOT delete while second waiter holds the subscription; second waiter deletes it.
    assert res_a["subscription_deleted"] is False
    assert res_b["subscription_deleted"] is True
    assert not any(e["op"] == "sub_delete" for e in read_log(log_a))
    assert sum(1 for e in read_log(log_b) if e["op"] == "sub_delete") == 1
    assert not any(e["op"] == "sub_create" for e in read_log(log_b))
    # Verify state directory permissions are 0700.
    assert (shared_state.stat().st_mode & 0o777) == 0o700


def test_preexisting_external_subscription_case_insensitive_never_deleted(tmp_path):
    cfg = {
        "existing_subs": [
            {
                "id": "sub_ext_1",
                "resourceUrl": "https://github.com/DJBCLARK/Demo/pull/42",
                "eventTypes": [
                    "com.github.pull_request.check_suite.status.changed.v1",
                    "com.github.pull_request.state.changed.v1",
                    "com.github.pull_request.head.changed.v1",
                    "com.github.pull_request.merge_conflict.v1",
                ],
            }
        ],
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        ],
    }
    env, log_path = make_env(tmp_path, cfg)
    r = run_wait(["djbclark/demo#42", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["subscription_id"] == "sub_ext_1"
    assert out["subscription_deleted"] is False
    ops = read_log(log_path)
    assert not any(e["op"] in ("sub_create", "sub_delete") for e in ops)


def test_listener_ignoring_sigterm_escalates_to_sigkill_then_deletes(tmp_path):
    """I.2: Listener ignoring SIGTERM gets SIGKILLed, reaped, and only then subscription is deleted."""
    cfg = {
        "created_sub_id": "sub_kill_1",
        "ignore_sigterm": True,
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        ],
    }
    env, log_path = make_env(tmp_path, cfg, extra_env={"GH_PR_WAIT_TEST_STOP_TIMEOUT": "0.2"})
    r = run_wait(["djbclark/demo#42", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["subscription_deleted"] is True
    del_ev = next(e for e in read_log(log_path) if e["op"] == "sub_delete")
    assert del_ev["listen_alive"] is False


def test_unproven_reap_skips_subscription_delete(tmp_path, monkeypatch):
    """I.2: If proc.wait() times out after SIGKILL and poll() stays None, keep proc and SKIP delete."""
    mod = load_module()
    monkeypatch.setenv("GH_PR_WAIT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("GH_PR_WAIT_TEST_STOP_TIMEOUT", "0.05")
    deleted = []
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
            raise subprocess.TimeoutExpired(["gh"], timeout or 1.0)

    pr_ref = mod.PRRef(url="https://github.com/djbclark/demo/pull/42", host="github.com", owner="djbclark", repo="demo", number=42)
    coord = mod.SubscriptionCoord(pr_ref, mod.EVENTS_FOR["checks"])
    logs: list[str] = []
    session = mod.StreamSession(coord, keep_subscription=False, cancel=mod.CancelState(), log_fn=logs.append)
    session.sub_id = "sub_stuck_1"
    session.ownership_confirmed = True
    session.shared_external = False
    session.attach_proc(StuckProc())  # type: ignore[arg-type]

    assert session.close() is False
    assert session.listener_reaped is False
    assert session.proc is not None
    assert deleted == []
    assert any("skipping subscription deletion" in m for m in logs)


def test_cancellation_during_subscription_create_cleans_up(tmp_path):
    """I.2: SIGTERM arriving during subscription create still records ownership and deletes it."""
    cfg = {
        "created_sub_id": "sub_mid_create",
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
    env, log_path = make_env(tmp_path, cfg, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    r = run_wait(["djbclark/demo#42", "--no-deadline", "--json"], env)
    assert r.returncode == 1, r.stderr
    out = json.loads(r.stdout)
    assert out["ok"] is False and out["reason"] == "checks_failed" and out["subscription_deleted"] is True

    cfg2 = {
        "created_sub_id": "sub_closed_1",
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


def test_already_passing_and_keep_subscription_and_empty_checks(tmp_path):
    cfg = {
        "created_sub_id": "sub_keep_1",
        "pr_views": [pr_state(checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}])],
    }
    env, log_path = make_env(tmp_path / "keep", cfg)
    r = run_wait(["djbclark/demo#42", "--keep-subscription", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["subscription_deleted"] is False
    assert all(e["op"] != "sub_delete" for e in read_log(log_path))

    # Empty checks waits by default; --allow-empty-checks passes on genuine [].
    cfg_e = {
        "created_sub_id": "sub_empty_1",
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

    env_a, _ = make_env(tmp_path / "empty_allow", {"created_sub_id": "sub_e2", "pr_views": [pr_state(checks=[])]})
    ra = run_wait(["djbclark/demo#42", "--allow-empty-checks", "--no-deadline", "--json"], env_a)
    assert ra.returncode == 0 and json.loads(ra.stdout)["reason"] == "checks_empty_allowed"


def test_review_pending_draft_to_submitted_same_id_and_no_body_fetched(tmp_path):
    """I.3 & II.1: PENDING draft transitions to submitted with same ID; GraphQL query omits review body."""
    cfg = {
        "created_sub_id": "sub_rev_draft",
        "pr_views": [
            pr_state(reviews=[{"id": "PRR_1", "state": "PENDING", "submittedAt": None, "author": {"login": "bob"}}]),
            # Duplicate unchanged draft or count inflation with no new submitted review: still waits.
            pr_state(reviews=[
                {"id": "PRR_1", "state": "PENDING", "submittedAt": None},
                {"id": "PRR_2", "state": "PENDING", "submittedAt": None},
            ]),
            # Draft PRR_1 is now submitted with the SAME id!
            pr_state(reviews=[
                {"id": "PRR_1", "state": "APPROVED", "submittedAt": "2026-11-25T10:05:00Z", "author": {"login": "bob"}},
            ]),
        ],
        "listen_actions": [
            {"after_pr_views": 1, "kind": "event", "event": {"id": "ev_r1", "type": "com.github.pull_request.review.submitted.v1"}},
            {"after_pr_views": 2, "kind": "event", "event": {"id": "ev_r2", "type": "com.github.pull_request.review.submitted.v1"}},
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
        joined = " ".join(call["argv"])
        assert "body" not in joined


def test_review_count_inflation_duplicate_keys_does_not_false_trigger(tmp_path):
    """I.3: Count increase without a new submitted (id, state, submittedAt) key must not trigger."""
    rev1 = {"id": "R1", "state": "COMMENTED", "submittedAt": "2020-01-01T00:00:00Z"}
    rev2 = {"id": "R2", "state": "APPROVED", "submittedAt": "2026-11-25T12:00:00Z"}
    cfg = {
        "created_sub_id": "sub_rev_dup",
        "pr_views": [
            pr_state(reviews=[rev1]),
            pr_state(reviews=[rev1, rev1]),  # count 2 > 1, identical unique key -> must NOT trigger
            pr_state(reviews=[rev1, rev2]),
        ],
        "listen_actions": [
            {"after_pr_views": 1, "kind": "event", "event": {"id": "ev_1", "type": "com.github.pull_request.review.submitted.v1"}},
            {"after_pr_views": 2, "kind": "event", "event": {"id": "ev_2", "type": "com.github.pull_request.review.submitted.v1"}},
        ],
    }
    env, log_path = make_env(tmp_path, cfg, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    r = run_wait(["djbclark/demo#42", "--for", "review", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    assert len([e for e in read_log(log_path) if e["op"] == "pr_view"]) == 3


def test_review_stream_to_poll_fallback_preserves_baseline(tmp_path):
    """I.3 + Codex thread 4695862122: Baseline established in stream is preserved on fallback to polling."""
    rev1 = {"id": "R1", "state": "COMMENTED", "submittedAt": "2020-01-01T00:00:00Z"}
    rev2 = {"id": "R2", "state": "APPROVED", "submittedAt": "2026-11-25T12:00:00Z"}
    cfg = {
        "created_sub_id": "sub_fb_base",
        "pr_views": [
            pr_state(reviews=[rev1]),        # initial post-attach read in event-stream
            pr_state(reviews=[rev1]),        # EOF re-check before switching to polling
            pr_state(reviews=[rev1, rev2]),  # FIRST poll read after fallback -> must detect R2 immediately!
        ],
        "listen_actions": [
            {"after_pr_views": 1, "kind": "exit", "rc": 1},
        ],
    }
    env, _ = make_env(tmp_path, cfg, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    r = run_wait(["djbclark/demo#42", "--for", "review", "--fallback-interval", "0.02", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["mode"] == "poll-fallback"
    assert out["reason"] == "review_submitted"


def test_review_post_attach_window_reconciliation_and_stale_wakeup(tmp_path):
    """I.3: Post-attach review folded into initial snapshot reconciles on its queued event; stale pre-attach review does not."""
    # Case A: post-attach review (submittedAt >= attach_wall_dt) in initial snapshot + queued event -> exit 0.
    cfg_post = {
        "created_sub_id": "sub_rec_1",
        "pr_views": [
            pr_state(reviews=[{"id": "R_post", "state": "APPROVED", "submittedAt": "2099-01-01T00:00:00Z"}]),
        ],
        "listen_actions": [
            {"after_pr_views": 1, "kind": "event", "event": {"id": "ev_post", "type": "com.github.pull_request.review.submitted.v1"}},
        ],
    }
    env1, _ = make_env(tmp_path / "post", cfg_post, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    r1 = run_wait(["djbclark/demo#42", "--for", "review", "--no-deadline", "--json"], env1)
    assert r1.returncode == 0, r1.stderr
    assert json.loads(r1.stdout)["reason"] == "review_submitted"

    # Case B: old pre-attach review + stale review event -> wakeup only, times out (exit 8).
    cfg_stale = {
        "created_sub_id": "sub_rec_2",
        "pr_views": [
            pr_state(reviews=[{"id": "R_old", "state": "COMMENTED", "submittedAt": "2020-01-01T00:00:00Z"}]),
        ],
        "listen_actions": [
            {"after_pr_views": 1, "kind": "event", "event": {"id": "ev_stale", "type": "com.github.pull_request.review.submitted.v1"}},
        ],
    }
    env2, _ = make_env(tmp_path / "stale", cfg_stale, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    r2 = run_wait(["djbclark/demo#42", "--for", "review", "--timeout", "0.35s", "--no-deadline", "--json"], env2)
    assert r2.returncode == 8, r2.stderr


def test_for_merge_and_mode_specific_fields(tmp_path):
    """II.1: --for checks/merge/any never request `reviews`."""
    cfg = {
        "created_sub_id": "sub_m_1",
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
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["merged"] is True
    for ev in read_log(log_path):
        if ev["op"] == "pr_view":
            assert "reviews" not in ev["json"] and "statusCheckRollup" not in ev["json"]

    cfg_c = {
        "created_sub_id": "sub_m_2",
        "pr_views": [pr_state(state="OPEN"), pr_state(state="CLOSED")],
        "listen_actions": [
            {"after_pr_views": 1, "kind": "event", "event": {"id": "ev_c", "type": "com.github.pull_request.state.changed.v1"}},
        ],
    }
    env_c, _ = make_env(tmp_path / "closed", cfg_c, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    rc = run_wait(["djbclark/demo#42", "--for", "merge", "--no-deadline", "--json"], env_c)
    assert rc.returncode == 1 and json.loads(rc.stdout)["reason"] == "pr_closed"


def test_for_any_validates_cloudevent_and_poll_detects_check_swap(tmp_path):
    """II.2: --for any ignores non-CloudEvent JSON; poll fallback detects equal-count check swaps."""
    ev_valid = {"id": "ev_any_1", "type": "com.github.pull_request.head.changed.v1", "data": {}}
    cfg = {
        "created_sub_id": "sub_any_1",
        "pr_views": [pr_state(head="oldsha"), pr_state(head="newsha")],
        "listen_actions": [
            {"after_pr_views": 1, "kind": "stdout_raw", "text": '{"not_an_event": true}'},
            {"after_pr_views": 1, "delay_s": 0.05, "kind": "event", "event": ev_valid},
        ],
    }
    env, log_path = make_env(tmp_path / "stream", cfg, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    r = run_wait(["djbclark/demo#42", "--for", "any", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["event"] == ev_valid and out["events_received"] == 1
    for ev in read_log(log_path):
        if ev["op"] == "pr_view":
            assert "reviews" not in ev["json"]

    # Poll fallback equal-count check swap (ci-a PASS / ci-b FAIL -> ci-a FAIL / ci-b PASS).
    cfg_swap = {
        "pr_views": [
            pr_state(
                url="https://ghe.example.com/djbclark/demo/pull/42",
                checks=[
                    {"__typename": "CheckRun", "name": "ci-a", "status": "COMPLETED", "conclusion": "SUCCESS"},
                    {"__typename": "CheckRun", "name": "ci-b", "status": "COMPLETED", "conclusion": "FAILURE"},
                ],
            ),
            pr_state(
                url="https://ghe.example.com/djbclark/demo/pull/42",
                checks=[
                    {"__typename": "CheckRun", "name": "ci-a", "status": "COMPLETED", "conclusion": "FAILURE"},
                    {"__typename": "CheckRun", "name": "ci-b", "status": "COMPLETED", "conclusion": "SUCCESS"},
                ],
            ),
        ],
    }
    env_s, _ = make_env(tmp_path / "swap", cfg_swap, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.03"})
    rs = run_wait(
        ["https://ghe.example.com/djbclark/demo/pull/42", "--for", "any", "--fallback-interval", "0.03", "--no-deadline", "--json"],
        env_s,
    )
    assert rs.returncode == 0, rs.stderr
    assert json.loads(rs.stdout)["reason"] == "state_changed"


def test_malformed_pr_state_mergedat_and_rollup_fail_closed(tmp_path):
    """II.2: Invalid state, malformed mergedAt on OPEN PR, or malformed rollup never yields success."""
    # Case 1: OPEN PR with truthy malformed mergedAt in --for merge -> rejected as malformed, times out (exit 8).
    cfg_m = {
        "created_sub_id": "sub_bad_m",
        "pr_views": [pr_state(state="OPEN", merged_at="not-a-timestamp")],
    }
    env_m, _ = make_env(tmp_path / "bad_m", cfg_m, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.05"})
    rm = run_wait(["djbclark/demo#42", "--for", "merge", "--timeout", "0.25s", "--no-deadline", "--json"], env_m)
    assert rm.returncode == 8

    # Case 2: Non-list statusCheckRollup with --allow-empty-checks -> NEVER passes!
    bad_pr = pr_state(state="OPEN")
    bad_pr["statusCheckRollup"] = "corrupt"  # type: ignore[assignment]
    env_r, _ = make_env(tmp_path / "bad_r", {"created_sub_id": "sub_bad_r", "pr_views": [bad_pr]}, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.05"})
    rr = run_wait(["djbclark/demo#42", "--allow-empty-checks", "--timeout", "0.25s", "--no-deadline", "--json"], env_r)
    assert rr.returncode == 8

    # Case 3: Unknown PR state -> NEVER passes!
    env_s, _ = make_env(
        tmp_path / "bad_s",
        {"created_sub_id": "sub_bad_s", "pr_views": [pr_state(state="BOGUS", checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}])]},
        extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.05"},
    )
    rs = run_wait(["djbclark/demo#42", "--timeout", "0.25s", "--no-deadline", "--json"], env_s)
    assert rs.returncode == 8


def test_event_burst_dedup_rate_limit_and_safety_floor(tmp_path):
    """I.6: Duplicate event IDs & bursts coalesce to one read; rate limit backs off; safety interval clamps >= 30 s."""
    cfg = {
        "created_sub_id": "sub_burst_1",
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
    out = json.loads(r.stdout)
    # 4 lines emitted, 1 duplicate ID ignored -> 3 distinct events_received.
    assert out["events_received"] == 3
    assert "rate limit hit; backing off" in r.stderr
    assert len([e for e in read_log(log_path) if e["op"] == "pr_view"]) == 3

    # Safety interval floor >= 30 s without test seam.
    env_sf, _ = make_env(
        tmp_path / "floor",
        {"created_sub_id": "sub_sf", "pr_views": [pr_state(checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}])]},
    )
    rsf = run_wait(["djbclark/demo#42", "--safety-interval", "5", "--no-deadline", "--json"], env_sf)
    assert rsf.returncode == 0
    assert "clamping --safety-interval from 5s to 30s" in rsf.stderr


def test_strict_readiness_split_utf8_oversize_and_reconnect_heartbeat(tmp_path):
    """II.3: Substring readiness ignored, split UTF-8 and >1 MiB line handled, reconnect + heartbeat triggers re-read."""
    cfg = {
        "created_sub_id": "sub_io_1",
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

    # Split UTF-8 chunk boundary in --for any.
    ev_utf8 = {"id": "ev_u", "type": "com.github.pull_request.head.changed.v1", "data": {"note": "héllo 🚀"}}
    cfg_u = {
        "created_sub_id": "sub_utf8",
        "pr_views": [pr_state()],
        "listen_actions": [{"after_pr_views": 1, "kind": "split_utf8_event", "event": ev_utf8}],
    }
    env_u, _ = make_env(tmp_path / "utf8", cfg_u, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    ru = run_wait(["djbclark/demo#42", "--for", "any", "--no-deadline", "--json"], env_u)
    assert ru.returncode == 0, ru.stderr
    assert json.loads(ru.stdout)["event"] == ev_utf8


@pytest.mark.parametrize("case", ["403_list", "422_create", "unknown_event_cmd", "attach_timeout", "non_github"])
def test_fallback_to_polling(tmp_path, case):
    url = "https://ghe.example.com/djbclark/demo/pull/42" if case == "non_github" else "https://github.com/djbclark/demo/pull/42"
    cfg: dict = {
        "pr_views": [
            pr_state(url=url, checks=[{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": ""}]),
            pr_state(url=url, checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        ],
    }
    extra_args: list[str] = []
    if case == "403_list":
        cfg["list_error"] = {"rc": 1, "stderr": "HTTP 403: Event subscriptions are not enabled for this account"}
    elif case == "422_create":
        cfg["create_error"] = {"rc": 1, "stderr": "HTTP 422: Subscription limit exceeded"}
    elif case == "unknown_event_cmd":
        cfg["list_error"] = {"rc": 1, "stderr": 'unknown command "event" for "gh"'}
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


def test_polling_clamps_interval_to_60s_and_timeout_blocks_post_expiry_poll(tmp_path):
    """I.5 & I.6: Fallback clamps >= 60 s without test seam; expired timeout skips fallback query."""
    url = "https://ghe.example.com/djbclark/demo/pull/42"
    env, _ = make_env(tmp_path / "clamp", {"pr_views": [pr_state(url=url, checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}])]})
    r = run_wait([url, "--fallback-interval", "5", "--no-deadline", "--json"], env)
    assert r.returncode == 0 and "clamping --fallback-interval from 5s to 60s" in r.stderr

    # Attach hangs past entire timeout -> must exit 8 without ever running a fallback pr_view!
    cfg_exp = {
        "created_sub_id": "sub_exp_1",
        "listen_hang_before_attach": True,
        "pr_views": [pr_state(checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}])],
    }
    env_e, log_e = make_env(tmp_path / "exp", cfg_exp, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.02"})
    re = run_wait(["djbclark/demo#42", "--timeout", "0.25s", "--attach-timeout", "5", "--no-deadline", "--json"], env_e)
    assert re.returncode == 8
    assert not any(e["op"] == "pr_view" for e in read_log(log_e))


def test_safety_net_timer_catches_rest_status_context_with_zero_events(tmp_path):
    cfg = {
        "created_sub_id": "sub_safety_1",
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
    """I.4: Cleanup validates sub IDs and canonical PR URLs, verifies returned URL + explicit state, caches PR lookups."""
    subs = [
        {"id": "sub_merged", "resourceUrl": "https://github.com/o/r/pull/1", "eventTypes": ["a"]},
        {"id": "sub_closed_1", "resourceUrl": "https://github.com/o/r/pull/2", "eventTypes": ["a"]},
        {"id": "sub_closed_2", "resourceUrl": "https://github.com/O/R/pull/2", "eventTypes": ["b"]},  # duplicate PR -> cached!
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

    # 1. --dry-run
    env1, log1 = make_env(tmp_path / "dry", {"existing_subs": subs, "pr_views_by_url": pr_views_by_url})
    r1 = run_wait(["cleanup", "--dry-run", "--json"], env1)
    assert r1.returncode == 0, r1.stderr
    out1 = json.loads(r1.stdout)
    assert [x["id"] for x in out1["selected"]] == ["sub_merged", "sub_closed_1", "sub_closed_2"]
    assert out1["deleted"] == []
    assert all(e["op"] != "sub_delete" for e in read_log(log1))

    # 2. default cleanup: deletes merged + closed only, caches PR #2 lookup (1 pr_view, not 2!), rejects flag/bad/open/mismatch.
    env2, log2 = make_env(tmp_path / "run", {"existing_subs": subs, "pr_views_by_url": pr_views_by_url})
    r2 = run_wait(["cleanup", "--json"], env2)
    assert r2.returncode == 0, r2.stderr
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
    for ev in ops2:
        if ev["op"] == "sub_delete":
            assert "--" in ev["argv"]

    # 3. --all: still skips invalid flag-shaped ID `-flag-shaped`, deletes all valid IDs without calling pr_view.
    env3, log3 = make_env(tmp_path / "all", {"existing_subs": subs, "pr_views_by_url": pr_views_by_url})
    r3 = run_wait(["cleanup", "--all", "--json"], env3)
    assert r3.returncode == 0, r3.stderr
    out3 = json.loads(r3.stdout)
    assert len(out3["deleted"]) == 7
    assert [x["id"] for x in out3["skipped"]] == ["-flag-shaped"]
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


def test_supervised_bare_number_infers_url_only_once_and_deadline_args(tmp_path):
    """I.5: Bare PR number is resolved once before deadline supervision (never repeated in inner copy)."""
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
        "infer_url": "https://github.com/djbclark/inferred/pull/99",
        "pr_views": [
            pr_state(
                url="https://github.com/djbclark/inferred/pull/99",
                checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}],
            ),
        ],
    }
    env, log_path = make_env(tmp_path, cfg, extra_env={"DEADLINE_BIN": str(fake_deadline)})
    r = run_wait(["--timeout", "99", "99", "--safety-interval", "300", "--json"], env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["pr_url"] == "https://github.com/djbclark/inferred/pull/99"
    # URL inference happened ONCE (not repeated in supervised copy) and --timeout 99 was NOT rewritten!
    assert sum(1 for e in read_log(log_path) if e["op"] == "pr_view_url") == 1
    dl_argv = json.loads(record_path.read_text(encoding="utf-8"))
    assert dl_argv[0] == "run"
    assert dl_argv[dl_argv.index("--budget") + 1] == "159"
    assert dl_argv[dl_argv.index("--heartbeat") + 1] == "360"
    assert dl_argv[dl_argv.index("--on-expire") + 1] == "kill"
    inner = dl_argv[dl_argv.index("--") + 1:]
    assert "--timeout" in inner and inner[inner.index("--timeout") + 1] == "99"
    assert "https://github.com/djbclark/inferred/pull/99" in inner
