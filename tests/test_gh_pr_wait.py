"""Hermetic tests for bin/gh-pr-wait (GitHub Event Streams waiter + polling fallback + cleanup).

Uses GH_BIN and DEADLINE_BIN explicit binary overrides (never modifies PATH, per code-review rule 2).
"""
from __future__ import annotations

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
            f.write(json.dumps(entry) + "\\n")
            f.flush()

    def next_count(key):
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
        err = cfg.get("create_error")
        if err:
            print(err["stderr"], file=sys.stderr)
            raise SystemExit(err.get("rc", 1))
        print(json.dumps({"id": cfg.get("created_sub_id", "sub_created_1")}))
        raise SystemExit(0)

    if argv[:3] == ["event", "subscription", "delete"]:
        sub_id = argv[3] if len(argv) > 3 else ""
        alive = False
        if pid_path.exists():
            try:
                lpid = int(pid_path.read_text(encoding="utf-8").strip())
                alive = pid_alive(lpid)
            except ValueError:
                alive = False
        log({"op": "sub_delete", "id": sub_id, "listen_alive": alive})
        fail_ids = set(cfg.get("delete_fail_ids", []))
        if sub_id in fail_ids:
            print(f"HTTP 500 deleting {sub_id}", file=sys.stderr)
            raise SystemExit(1)
        raise SystemExit(0)

    if argv[:2] == ["event", "listen"]:
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
        log({"op": "listen_start", "pid": os.getpid(), "argv": argv})

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

        # Stay alive until terminated by gh-pr-wait.
        end = time.monotonic() + float(cfg.get("listen_hold_s", 30.0))
        while time.monotonic() < end:
            time.sleep(0.05)
        log({"op": "listen_exited", "rc": 8})
        raise SystemExit(8)

    if argv[:2] == ["pr", "view"]:
        target = argv[2] if len(argv) > 2 else ""
        if "--json" in argv and argv[argv.index("--json") + 1] == "url":
            log({"op": "pr_view_url", "target": target})
            inferred = cfg.get("infer_url")
            if not inferred:
                print("no pull request found", file=sys.stderr)
                raise SystemExit(1)
            print(json.dumps({"url": inferred}))
            raise SystemExit(0)

        # Cleanup mode or wait mode `pr view`
        by_url = cfg.get("pr_views_by_url")
        if by_url is not None:
            log({"op": "pr_view", "target": target})
            resp = by_url.get(target)
            if resp is None or resp.get("error"):
                print((resp or {}).get("error", "HTTP 404 Not Found"), file=sys.stderr)
                raise SystemExit(1)
            print(json.dumps(resp))
            raise SystemExit(0)

        call_no = next_count("pr_view")
        log({"op": "pr_view", "call": call_no, "target": target})
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


def make_env(tmp_path: Path, cfg: dict, *, extra_env: dict[str, str] | None = None):
    fake_gh = tmp_path / "fake_gh.py"
    fake_gh.write_text(FAKE_GH_SCRIPT, encoding="utf-8")
    fake_gh.chmod(0o755)
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    log_path = tmp_path / "events.jsonl"
    counter_path = tmp_path / "counter.json"
    pid_path = tmp_path / "listen.pid"
    env = dict(os.environ)
    env.pop("DEADLINE_NAME", None)
    env.pop("GH_PR_WAIT_TEST_MIN_INTERVAL", None)
    env["GH_BIN"] = str(fake_gh)
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
                    "data": {"conclusion": "success", "api_url": "https://api.github.com/repos/djbclark/demo/check-suites/1"},
                },
            }
        ],
    }
    env, log_path = make_env(tmp_path, cfg)
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
    # Attach-then-read proof: listen_ready strictly precedes first pr_view.
    idx_ready = op_names.index("listen_ready")
    idx_first_view = op_names.index("pr_view")
    assert idx_ready < idx_first_view
    assert ops[idx_ready]["t"] <= ops[idx_first_view]["t"]
    # Stop-before-delete proof: listen_exited precedes sub_delete and listen_alive is False.
    idx_exited = op_names.index("listen_exited")
    idx_delete = op_names.index("sub_delete")
    assert idx_exited < idx_delete
    assert ops[idx_delete]["listen_alive"] is False


def test_instant_wake_check_failure_and_stop_before_delete(tmp_path):
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
            {
                "after_pr_views": 1,
                "kind": "event",
                "event": {
                    "id": "ev_fail",
                    "type": "com.github.pull_request.check_suite.status.changed.v1",
                    "data": {"conclusion": "failure"},
                },
            }
        ],
    }
    env, log_path = make_env(tmp_path, cfg)
    r = run_wait(["djbclark/demo#42", "--no-deadline", "--json"], env)
    assert r.returncode == 1, r.stderr
    out = json.loads(r.stdout)
    assert out["ok"] is False
    assert out["reason"] == "checks_failed"
    assert out["subscription_deleted"] is True
    assert out["checks_summary"] == {"total": 2, "passed": 1, "failed": 1, "pending": 0}

    ops = read_log(log_path)
    op_names = [e["op"] for e in ops]
    assert op_names.index("listen_exited") < op_names.index("sub_delete")
    assert ops[op_names.index("sub_delete")]["listen_alive"] is False


def test_checks_fail_when_pr_closed_before_checks_finish(tmp_path):
    cfg = {
        "created_sub_id": "sub_closed_1",
        "pr_views": [
            pr_state(state="OPEN", checks=[{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": ""}]),
            pr_state(state="CLOSED", checks=[{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": ""}]),
        ],
        "listen_actions": [
            {
                "after_pr_views": 1,
                "kind": "event",
                "event": {"id": "ev_c", "type": "com.github.pull_request.state.changed.v1", "data": {}},
            }
        ],
    }
    env, _ = make_env(tmp_path, cfg)
    r = run_wait(["djbclark/demo#42", "--for", "checks", "--no-deadline", "--json"], env)
    assert r.returncode == 1
    out = json.loads(r.stdout)
    assert out["ok"] is False
    assert out["reason"] == "pr_closed"


def test_already_passing_on_post_attach_read_closes_before_delete(tmp_path):
    cfg = {
        "created_sub_id": "sub_already_1",
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        ],
    }
    env, log_path = make_env(tmp_path, cfg)
    r = run_wait(["djbclark/demo#42", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["ok"] is True
    assert out["events_received"] == 0
    assert out["subscription_deleted"] is True

    ops = read_log(log_path)
    op_names = [e["op"] for e in ops]
    assert op_names.index("listen_ready") < op_names.index("pr_view")
    assert op_names.index("listen_exited") < op_names.index("sub_delete")
    assert ops[op_names.index("sub_delete")]["listen_alive"] is False


def test_empty_checks_waits_by_default_and_passes_with_allow_empty(tmp_path):
    cfg = {
        "created_sub_id": "sub_empty_1",
        "pr_views": [
            pr_state(checks=[]),
            pr_state(checks=[{"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        ],
        "listen_actions": [
            {
                "after_pr_views": 1,
                "kind": "event",
                "event": {"id": "ev_e1", "type": "com.github.pull_request.check_suite.status.changed.v1", "data": {"conclusion": "success"}},
            }
        ],
    }
    env, _ = make_env(tmp_path, cfg)
    r = run_wait(["djbclark/demo#42", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    assert "checks_pending_empty" in r.stderr
    assert json.loads(r.stdout)["events_received"] == 1

    # With --allow-empty-checks: exits 0 immediately on initial empty rollup.
    allow_dir = tmp_path / "allow"
    allow_dir.mkdir(exist_ok=True)
    cfg2 = {"created_sub_id": "sub_empty_2", "pr_views": [pr_state(checks=[])]}
    env2, _ = make_env(allow_dir, cfg2)
    r2 = run_wait(["djbclark/demo#42", "--allow-empty-checks", "--no-deadline", "--json"], env2)
    assert r2.returncode == 0, r2.stderr
    assert json.loads(r2.stdout)["reason"] == "checks_empty_allowed"


def test_reused_preexisting_subscription_is_not_deleted(tmp_path):
    cfg = {
        "existing_subs": [
            {
                "id": "sub_pre_1",
                "resourceUrl": "https://github.com/djbclark/demo/pull/42",
                "eventTypes": [
                    "com.github.pull_request.check_suite.status.changed.v1",
                    "com.github.pull_request.state.changed.v1",
                    "com.github.pull_request.head.changed.v1",
                    "com.github.pull_request.merge_conflict.v1",
                ],
            }
        ],
        "created_sub_id": "sub_pre_1",
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        ],
    }
    env, log_path = make_env(tmp_path, cfg)
    r = run_wait(["djbclark/demo#42", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["subscription_id"] == "sub_pre_1"
    assert out["subscription_deleted"] is False
    assert all(e["op"] != "sub_delete" for e in read_log(log_path))


def test_keep_subscription_flag_prevents_deletion(tmp_path):
    cfg = {
        "created_sub_id": "sub_keep_1",
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        ],
    }
    env, log_path = make_env(tmp_path, cfg)
    r = run_wait(["djbclark/demo#42", "--keep-subscription", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["subscription_id"] == "sub_keep_1"
    assert out["subscription_deleted"] is False
    assert all(e["op"] != "sub_delete" for e in read_log(log_path))


def test_for_review_new_review_and_closed_first(tmp_path):
    cfg = {
        "created_sub_id": "sub_rev_1",
        "pr_views": [
            pr_state(reviews=[{"id": "R1", "state": "COMMENTED", "submittedAt": "2026-11-24T00:00:00Z"}]),
            pr_state(reviews=[
                {"id": "R1", "state": "COMMENTED", "submittedAt": "2026-11-24T00:00:00Z"},
                {"id": "R2", "state": "APPROVED", "submittedAt": "2026-11-24T00:05:00Z"},
            ]),
        ],
        "listen_actions": [
            {
                "after_pr_views": 1,
                "kind": "event",
                "event": {"id": "ev_r", "type": "com.github.pull_request.review.submitted.v1", "data": {}},
            }
        ],
    }
    env, _ = make_env(tmp_path, cfg)
    r = run_wait(["djbclark/demo#42", "--for", "review", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["reason"] == "review_submitted"

    sub_dir = tmp_path / "closed"
    sub_dir.mkdir()
    cfg2 = {
        "created_sub_id": "sub_rev_2",
        "pr_views": [
            pr_state(reviews=[{"id": "R1"}]),
            pr_state(state="CLOSED", reviews=[{"id": "R1"}]),
        ],
        "listen_actions": [
            {
                "after_pr_views": 1,
                "kind": "event",
                "event": {"id": "ev_s", "type": "com.github.pull_request.state.changed.v1", "data": {}},
            }
        ],
    }
    env2, _ = make_env(sub_dir, cfg2)
    r2 = run_wait(["djbclark/demo#42", "--for", "review", "--no-deadline", "--json"], env2)
    assert r2.returncode == 1
    assert json.loads(r2.stdout)["reason"] == "pr_closed"


def test_for_merge_merged_exits_0_and_closed_exits_1(tmp_path):
    cfg = {
        "created_sub_id": "sub_m_1",
        "pr_views": [
            pr_state(state="OPEN"),
            pr_state(state="MERGED", merged_at="2026-11-25T10:00:00Z"),
        ],
        "listen_actions": [
            {
                "after_pr_views": 1,
                "kind": "event",
                "event": {"id": "ev_m", "type": "com.github.pull_request.state.changed.v1", "data": {}},
            }
        ],
    }
    env, _ = make_env(tmp_path, cfg)
    r = run_wait(["djbclark/demo#42", "--for", "merge", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["merged"] is True and out["reason"] == "pr_merged"

    d2 = tmp_path / "closed"
    d2.mkdir()
    cfg2 = {
        "created_sub_id": "sub_m_2",
        "pr_views": [pr_state(state="OPEN"), pr_state(state="CLOSED")],
        "listen_actions": [
            {
                "after_pr_views": 1,
                "kind": "event",
                "event": {"id": "ev_c", "type": "com.github.pull_request.state.changed.v1", "data": {}},
            }
        ],
    }
    env2, _ = make_env(d2, cfg2)
    r2 = run_wait(["djbclark/demo#42", "--for", "merge", "--no-deadline", "--json"], env2)
    assert r2.returncode == 1
    out2 = json.loads(r2.stdout)
    assert out2["merged"] is False and out2["reason"] == "pr_closed"


def test_for_any_exits_on_first_event_with_snapshot(tmp_path):
    ev_payload = {
        "id": "ev_any_1",
        "type": "com.github.pull_request.head.changed.v1",
        "data": {"api_url": "https://api.github.com/repos/djbclark/demo/pulls/42"},
    }
    cfg = {
        "created_sub_id": "sub_any_1",
        "pr_views": [
            pr_state(head="oldsha"),
            pr_state(head="newsha"),
        ],
        "listen_actions": [
            {"after_pr_views": 1, "kind": "event", "event": ev_payload},
        ],
    }
    env, log_path = make_env(tmp_path, cfg)
    r = run_wait(["djbclark/demo#42", "--for", "any", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["reason"] == "event_received"
    assert out["events_received"] == 1
    assert out["event"] == ev_payload
    assert out["head"] == "newsha"
    # Verify all 5 event types were requested in subscription create.
    create_entry = next(e for e in read_log(log_path) if e["op"] == "sub_create")
    ev_csv = create_entry["argv"][create_entry["argv"].index("--event") + 1]
    assert len(ev_csv.split(",")) == 5


def test_reconnect_stderr_triggers_fresh_pr_view(tmp_path):
    cfg = {
        "created_sub_id": "sub_reconn_1",
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": ""}]),
            pr_state(checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        ],
        "listen_actions": [
            {"after_pr_views": 1, "kind": "stderr", "text": "Reconnecting..."},
            {"after_pr_views": 1, "kind": "stderr", "text": "Listening for events."},
        ],
    }
    env, log_path = make_env(tmp_path, cfg)
    r = run_wait(["djbclark/demo#42", "--no-deadline", "--safety-interval", "300", "--json"], env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["mode"] == "event-stream"
    assert out["events_received"] == 0
    assert out["reason"] == "checks_passed"
    pr_views = [e for e in read_log(log_path) if e["op"] == "pr_view"]
    assert len(pr_views) == 2


@pytest.mark.parametrize("case", ["403_list", "422_create", "unknown_event_cmd", "attach_timeout", "non_github"])
def test_fallback_to_polling(tmp_path, case):
    cfg: dict = {
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": ""}]),
            pr_state(checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        ],
    }
    ref = "https://github.com/djbclark/demo/pull/42"
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
    elif case == "non_github":
        ref = "https://ghe.example.com/djbclark/demo/pull/42"

    env, log_path = make_env(tmp_path, cfg, extra_env={"GH_PR_WAIT_TEST_MIN_INTERVAL": "0.05"})
    r = run_wait([ref, "--fallback-interval", "0.05", "--no-deadline", "--json", *extra_args], env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["ok"] is True
    assert out["mode"] == "poll-fallback"
    assert out["events_received"] == 0
    assert out["subscription_id"] is None

    ops = read_log(log_path)
    if case == "non_github":
        assert not any(e["op"].startswith(("sub_", "listen_")) for e in ops)
    if case == "attach_timeout":
        # Created subscription must be cleaned up before falling back to polling!
        op_names = [e["op"] for e in ops]
        assert op_names.index("listen_exited") < op_names.index("sub_delete")


def test_polling_clamps_interval_to_60s_without_test_seam(tmp_path):
    cfg = {
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        ]
    }
    env, _ = make_env(tmp_path, cfg)
    r = run_wait(
        ["https://ghe.example.com/djbclark/demo/pull/42", "--fallback-interval", "5", "--no-deadline", "--json"],
        env,
    )
    assert r.returncode == 0, r.stderr
    assert "clamping --fallback-interval from 5s to 60s" in r.stderr


def test_safety_net_timer_catches_rest_status_context_with_zero_events(tmp_path):
    cfg = {
        "created_sub_id": "sub_safety_1",
        "pr_views": [
            pr_state(checks=[{"__typename": "StatusContext", "context": "ci/legacy", "state": "PENDING"}]),
            pr_state(checks=[{"__typename": "StatusContext", "context": "ci/legacy", "state": "SUCCESS"}]),
        ],
    }
    env, _ = make_env(tmp_path, cfg)
    r = run_wait(["djbclark/demo#42", "--safety-interval", "0.15", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["ok"] is True
    assert out["mode"] == "event-stream"
    assert out["events_received"] == 0
    assert out["reason"] == "checks_passed"


def test_timeout_exits_8_and_cleans_up(tmp_path):
    cfg = {
        "created_sub_id": "sub_to_1",
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": ""}]),
        ],
    }
    env, log_path = make_env(tmp_path, cfg)
    r = run_wait(["djbclark/demo#42", "--timeout", "0.4s", "--safety-interval", "300", "--no-deadline", "--json"], env)
    assert r.returncode == 8, r.stderr
    out = json.loads(r.stdout)
    assert out["ok"] is False
    assert out["reason"] == "timeout"
    assert out["subscription_deleted"] is True

    ops = read_log(log_path)
    op_names = [e["op"] for e in ops]
    assert op_names.index("listen_exited") < op_names.index("sub_delete")
    assert ops[op_names.index("sub_delete")]["listen_alive"] is False


def test_sigterm_terminates_stream_before_delete_and_exits_143(tmp_path):
    cfg = {
        "created_sub_id": "sub_sig_1",
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": ""}]),
        ],
    }
    env, log_path = make_env(tmp_path, cfg)
    proc = subprocess.Popen(
        [str(TOOL), "djbclark/demo#42", "--timeout", "30s", "--no-deadline"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
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
        rc = proc.wait(timeout=10.0)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert rc == 143
    ops = read_log(log_path)
    op_names = [e["op"] for e in ops]
    assert op_names.index("listen_exited") < op_names.index("sub_delete")
    assert ops[op_names.index("sub_delete")]["listen_alive"] is False


def test_cleanup_dry_run_default_and_all(tmp_path):
    subs = [
        {"id": "sub_merged", "resourceUrl": "https://github.com/o/r/pull/1", "eventTypes": ["a"], "expiresAt": "2026-11-26T00:00:00Z"},
        {"id": "sub_closed", "resourceUrl": "https://github.com/o/r/pull/2", "eventTypes": ["a"], "expiresAt": "2026-11-26T00:00:00Z"},
        {"id": "sub_open", "resourceUrl": "https://github.com/o/r/pull/3", "eventTypes": ["a"], "expiresAt": "2026-11-26T00:00:00Z"},
        {"id": "sub_unreadable", "resourceUrl": "https://github.com/o/r/pull/4", "eventTypes": ["a"], "expiresAt": "2026-11-26T00:00:00Z"},
    ]
    pr_views_by_url = {
        "https://github.com/o/r/pull/1": {"state": "MERGED", "mergedAt": "2026-11-25T00:00:00Z"},
        "https://github.com/o/r/pull/2": {"state": "CLOSED", "mergedAt": None},
        "https://github.com/o/r/pull/3": {"state": "OPEN", "mergedAt": None},
        "https://github.com/o/r/pull/4": {"error": "HTTP 404 Not Found"},
    }

    # 1. --dry-run
    d1 = tmp_path / "dry"
    d1.mkdir()
    env1, log1 = make_env(d1, {"existing_subs": subs, "pr_views_by_url": pr_views_by_url})
    r1 = run_wait(["cleanup", "--dry-run", "--json"], env1)
    assert r1.returncode == 0, r1.stderr
    out1 = json.loads(r1.stdout)
    assert [x["id"] for x in out1["selected"]] == ["sub_merged", "sub_closed"]
    assert out1["deleted"] == []
    assert {x["id"] for x in out1["skipped"]} == {"sub_open", "sub_unreadable"}
    assert all(e["op"] != "sub_delete" for e in read_log(log1))

    # 2. default cleanup (deletes merged/closed only, fail-closed skips open + unreadable)
    d2 = tmp_path / "run"
    d2.mkdir()
    env2, log2 = make_env(d2, {"existing_subs": subs, "pr_views_by_url": pr_views_by_url})
    r2 = run_wait(["cleanup", "--json"], env2)
    assert r2.returncode == 0, r2.stderr
    out2 = json.loads(r2.stdout)
    assert [x["id"] for x in out2["deleted"]] == ["sub_merged", "sub_closed"]
    assert [e["id"] for e in read_log(log2) if e["op"] == "sub_delete"] == ["sub_merged", "sub_closed"]

    # 3. --all (deletes every subscription without calling pr view)
    d3 = tmp_path / "all"
    d3.mkdir()
    env3, log3 = make_env(d3, {"existing_subs": subs, "pr_views_by_url": pr_views_by_url})
    r3 = run_wait(["cleanup", "--all", "--json"], env3)
    assert r3.returncode == 0, r3.stderr
    out3 = json.loads(r3.stdout)
    assert len(out3["deleted"]) == 4
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


def test_bare_pr_number_with_repo_flag_and_inferred_url(tmp_path):
    cfg = {
        "created_sub_id": "sub_num_1",
        "infer_url": "https://github.com/djbclark/inferred/pull/99",
        "pr_views": [
            pr_state(
                url="https://github.com/djbclark/inferred/pull/99",
                checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}],
            ),
        ],
    }
    env, _ = make_env(tmp_path, cfg)
    r = run_wait(["99", "--no-deadline", "--json"], env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["pr_url"] == "https://github.com/djbclark/inferred/pull/99"

    d2 = tmp_path / "with_r"
    d2.mkdir()
    env2, _ = make_env(d2, cfg)
    r2 = run_wait(["99", "-R", "djbclark/explicit", "--no-deadline", "--json"], env2)
    assert r2.returncode == 0, r2.stderr
    assert json.loads(r2.stdout)["pr_url"] == "https://github.com/djbclark/explicit/pull/99"


def test_deadline_self_supervision_uses_deadline_bin(tmp_path):
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
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        ],
    }
    env, _ = make_env(tmp_path, cfg, extra_env={"DEADLINE_BIN": str(fake_deadline)})
    r = run_wait(["djbclark/demo#42", "--timeout", "10m", "--safety-interval", "300", "--json"], env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["ok"] is True
    dl_argv = json.loads(record_path.read_text(encoding="utf-8"))
    assert dl_argv[0] == "run"
    assert dl_argv[dl_argv.index("--budget") + 1] == "660"
    assert dl_argv[dl_argv.index("--heartbeat") + 1] == "360"
    assert dl_argv[dl_argv.index("--on-expire") + 1] == "kill"


def test_reconnect_with_concurrent_sse_heartbeat_still_rereads_and_human_output(tmp_path):
    cfg = {
        "created_sub_id": "sub_hb_1",
        "pr_views": [
            pr_state(checks=[{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": ""}]),
            pr_state(checks=[{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        ],
        "listen_actions": [
            {"after_pr_views": 1, "kind": "stdout_raw", "text": ": keepalive"},
            {"after_pr_views": 1, "kind": "stderr", "text": "Listening for events."},
        ],
    }
    env, _ = make_env(tmp_path, cfg)
    r = run_wait(["djbclark/demo#42", "--no-deadline", "--safety-interval", "300"], env)
    assert r.returncode == 0, r.stderr
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert "gh-pr-wait: ok" in lines[0] and "reason=checks_passed" in lines[0]

