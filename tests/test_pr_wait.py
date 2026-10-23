"""bin/pr-wait: one waiter per PR head for CI and Codex's review, against a fake `gh` on PATH."""

import importlib.util
import json
import os
import signal
import stat
import subprocess
import sys
import time
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

PR_WAIT = Path(__file__).resolve().parent.parent / "bin" / "pr-wait"
REPO = "djbclark/djbclark-ade"
PR = 7
HEAD = "a" * 40
OLD = "b" * 40
NEW = "c" * 40
CODEX_LOGIN = "chatgpt-codex-connector[bot]"

# Serves canned output by endpoint. scenario.json: {"routes": {endpoint: [{"out": str, "rc": int, "err": str}, ...]}};
# the Nth call to an endpoint gets the Nth entry, the last one repeats. Every argv is logged.
FAKE_GH = r"""#!/usr/bin/env python3
import json, os, sys
d = os.environ["FAKE_GH_DIR"]
args = sys.argv[1:]
with open(os.path.join(d, "calls.log"), "a") as f:
    f.write(json.dumps(args) + "\n")
if args[:1] != ["api"]:
    sys.stderr.write("fake gh: only `api` is served\n"); sys.exit(1)
ep = next(a for a in args[1:] if not a.startswith("-")).split("?")[0]
routes = json.load(open(os.path.join(d, "scenario.json")))["routes"]
if ep not in routes:
    sys.stderr.write("fake gh: no route " + ep + "\n"); sys.exit(1)
cf = os.path.join(d, "count-" + ep.replace("/", "_"))
n = int(open(cf).read()) if os.path.exists(cf) else 0
with open(cf + ".tmp.%d" % os.getpid(), "w") as f:
    f.write(str(n + 1))
os.replace(cf + ".tmp.%d" % os.getpid(), cf)
r = routes[ep][min(n, len(routes[ep]) - 1)]
sys.stdout.write(r.get("out", ""))
sys.stderr.write(r.get("err", ""))
sys.exit(r.get("rc", 0))
"""


def ok(out: object) -> dict:
    return {"out": out if isinstance(out, str) else json.dumps(out)}


def fail(err: str = "gh: connection reset", rc: int = 1) -> dict:
    return {"out": "", "err": err, "rc": rc}


def run_obj(name: str, status: str = "completed", conclusion: str | None = "success") -> dict:
    return {"name": name, "status": status, "conclusion": conclusion}


def checks_page(*runs: dict) -> dict:
    return ok({"total_count": len(runs), "check_runs": list(runs)})


BOT = {"login": CODEX_LOGIN, "type": "Bot"}
BOT_APP = {"user": BOT, "performed_via_github_app": {"slug": "chatgpt-codex-connector"}}


def codex_comment(sha: str, status: str, updated: str = "2026-10-23T10:00:00Z", **who: object) -> dict:
    state = {"code_review": {"commit_sha": sha, "status": status}, "security_review": {"status": "completed"}}
    body = ("<!-- codex-pull-request-review-summary -->\nCodex review\n"
            f"<!-- codex-review-state:v1 {json.dumps(state)} -->")
    return {"body": body, "created_at": "2026-10-23T09:00:00Z", "updated_at": updated, **(who or BOT_APP)}


def injected(sha: str, status: str, updated: str = "2026-10-23T12:00:00Z") -> dict:
    """A marker comment posted by anyone else (the repo is public)."""
    return codex_comment(sha, status, updated, user={"login": "mallory", "type": "User"},
                         performed_via_github_app=None)


def request(at: str) -> dict:
    return {"body": "@codex review", "created_at": at, "updated_at": at, "user": {"login": "djbclark", "type": "User"}}


def finding(n: int, at: str, original: str = HEAD, review: int | None = None, login: str = CODEX_LOGIN,
            type_: str = "Bot") -> dict:
    return {"id": n, "path": f"f{n}.py", "line": n, "created_at": at, "original_commit_id": original,
            "pull_request_review_id": review, "user": {"login": login, "type": type_},
            "body": f"finding {n}\n<!-- codex-code-review-finding:v1 -->"}


class World:
    """A fake gh on PATH plus the pr-wait invocation environment."""

    def __init__(self, tmp: Path) -> None:
        self.dir = tmp / "gh"
        self.dir.mkdir()
        gh = self.dir / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        self.state = tmp / "state"
        self.out = tmp / "out" / "w"
        self.routes: dict[str, list[dict]] = {}
        self.env = {**os.environ, "PATH": f"{self.dir}{os.pathsep}{os.environ['PATH']}",
                    "FAKE_GH_DIR": str(self.dir), "PR_WAIT_STATE_DIR": str(self.state)}
        self.happy()

    def route(self, ep: str, *responses: dict) -> None:
        self.routes[ep] = list(responses)
        (self.dir / "scenario.json").write_text(json.dumps({"routes": self.routes}))

    def happy(self) -> None:
        """Head HEAD, one passing check, a completed Codex review for HEAD, no findings."""
        self.route(f"repos/{REPO}/pulls/{PR}", ok({"head": {"sha": HEAD}}))
        self.route(f"repos/{REPO}/commits/{HEAD}/check-runs", checks_page(run_obj("test")))
        self.route(f"repos/{REPO}/commits/{HEAD}/status", ok({"state": "pending", "statuses": []}))
        self.route(f"repos/{REPO}/issues/{PR}/comments",
                   ok([request("2026-10-23T09:30:00Z"), codex_comment(HEAD, "completed")]))
        self.route(f"repos/{REPO}/pulls/{PR}/reviews", ok([]))
        self.route(f"repos/{REPO}/pulls/{PR}/comments", ok([]))

    def argv(self, *extra: str) -> list[str]:
        return [sys.executable, "-I", str(PR_WAIT), str(PR), "--interval", "0.1", "--timeout", "15",
                "--out", str(self.out), *extra]

    def run(self, *extra: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        return subprocess.run(self.argv(*extra), check=False, capture_output=True, text=True,
                              timeout=timeout, env=self.env)

    def file(self, name: str) -> object:
        return json.loads(Path(f"{self.out}-{name}.json").read_text())

    def calls(self, ep: str) -> int:
        cf = self.dir / ("count-" + f"repos/{REPO}/{ep}".replace("/", "_"))
        return int(cf.read_text()) if cf.exists() else 0


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_ci_and_codex_both_complete(world: World) -> None:
    # CI pending then done; Codex running then completed: the waiter wakes once, when both are done
    world.route(f"repos/{REPO}/commits/{HEAD}/check-runs",
                checks_page(run_obj("test", "in_progress", None)),
                checks_page(run_obj("test"), run_obj("lint", conclusion="failure")))
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok([request("2026-10-23T09:30:00Z"), codex_comment(HEAD, "running")]),
                ok([request("2026-10-23T09:30:00Z"), codex_comment(HEAD, "completed")]))
    r = world.run()
    assert r.returncode == 0, r.stderr
    assert len(r.stdout.strip().splitlines()) == 1
    assert "CI done (1 pass, 1 fail, 0 pending)" in r.stdout and "codex completed" in r.stdout
    assert world.calls(f"commits/{HEAD}/check-runs") == 2
    summary = world.file("summary")
    assert summary["result"] == "done" and summary["head"] == HEAD
    assert summary["ci"] == {"state": "done", "total": 2, "pass": 1, "fail": 1, "pending": 0}
    assert summary["codex"]["status"] == "completed" and summary["since_source"] is None
    assert world.file("codex")["code_review"]["commit_sha"] == HEAD
    assert {c["name"] for c in world.file("checks")} == {"test", "lint"}
    assert world.file("findings") == []
    assert not list(world.state.glob("lock-*")), "the lock is released at exit"


def test_codex_failed_is_terminal(world: World) -> None:
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok([request("2026-10-23T09:30:00Z"), codex_comment(HEAD, "failed")]))
    r = world.run("--timeout", "5")
    assert r.returncode == 0, r.stderr
    assert "codex failed" in r.stdout
    assert world.file("summary")["codex"]["status"] == "failed"
    assert world.file("findings") == []


def test_codex_running_too_long_is_stuck(world: World) -> None:
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok([request("2026-10-23T09:30:00Z"), codex_comment(HEAD, "running")]))
    r = world.run("--codex-stuck", "0.5")
    assert r.returncode == 3, r.stdout + r.stderr
    assert "codex-stuck" in r.stdout and "codex running" in r.stdout
    assert world.file("summary")["result"] == "codex-stuck"
    assert world.file("findings") is None  # not collected: Codex never finished


def test_findings_are_selected_by_head_author_and_mark_not_by_time(world: World) -> None:
    # PR 12 shape (2026-10-20): the finding for the head, then Codex's own receipt quoting `@codex review`
    # after it, then a human reply quoting it: no later comment may hide the finding
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok([request("2026-10-23T09:30:00Z"), codex_comment(HEAD, "completed"),
                    {**request("2026-10-23T10:05:00Z"), **BOT_APP, "body": 'About Codex: Comment "@codex review".'},
                    {**request("2026-10-23T11:00:00Z"), "user": {"login": "mallory", "type": "User"},
                     "body": "> @codex review\nlgtm"}]))
    world.route(f"repos/{REPO}/pulls/{PR}/reviews",
                ok([{"id": 900, "commit_id": HEAD}, {"id": 800, "commit_id": OLD}]))
    world.route(f"repos/{REPO}/pulls/{PR}/comments",
                ok([finding(1, "2026-10-23T09:45:00Z"),  # original_commit_id is the head
                    finding(2, "2026-10-23T09:46:00Z", original=OLD, review=900),  # review of the head
                    finding(3, "2026-10-23T09:00:00Z", original=OLD, review=800),  # an earlier head's
                    finding(4, "2026-10-23T09:47:00Z", login="mallory", type_="User"),  # not Codex
                    {**finding(5, "2026-10-23T09:48:00Z"), "body": "a Codex reply, no mark"},
                    {**finding(6, "2026-10-23T09:49:00Z"), "user": {"login": CODEX_LOGIN, "type": "User"}}]))
    r = world.run()
    assert r.returncode == 0, r.stderr
    assert [f["id"] for f in world.file("findings")] == [1, 2]
    assert "findings for the head: 2" in r.stdout
    summary = world.file("summary")
    assert summary["since"] is None and summary["since_source"] is None


def test_since_is_an_optional_extra_lower_bound(world: World) -> None:
    world.route(f"repos/{REPO}/pulls/{PR}/comments",
                ok([finding(1, "2026-10-23T09:00:00Z"), finding(2, "2026-10-23T09:45:00Z")]))
    assert world.run("--since", "2026-10-23T09:30:00+00:00").returncode == 0
    assert [f["id"] for f in world.file("findings")] == [2]
    assert world.file("summary")["since_source"] == "--since"
    assert world.run().returncode == 0
    assert [f["id"] for f in world.file("findings")] == [1, 2]


def test_two_page_paginated_responses(world: World) -> None:
    # gh --paginate prints one JSON document per page, concatenated
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok(json.dumps([request("2026-10-23T09:30:00Z")]) + json.dumps([codex_comment(HEAD, "completed")])))
    world.route(f"repos/{REPO}/pulls/{PR}/comments",
                ok(json.dumps([finding(1, "2026-10-23T09:40:00Z")]) + "\n" + json.dumps([finding(2, "2026-10-23T09:41:00Z")])))
    world.route(f"repos/{REPO}/commits/{HEAD}/check-runs",
                ok(json.dumps({"total_count": 2, "check_runs": [run_obj("a")]})
                   + json.dumps({"total_count": 2, "check_runs": [run_obj("b", "queued", None)]})),
                checks_page(run_obj("a"), run_obj("b")))
    r = world.run()
    assert r.returncode == 0, r.stderr
    assert [f["id"] for f in world.file("findings")] == [1, 2]
    assert world.calls(f"commits/{HEAD}/check-runs") == 2  # page 2's queued check kept CI pending
    assert world.file("summary")["codex"]["status"] == "completed"


def test_gh_failure_is_unknown_not_done(world: World) -> None:
    # a failing check-runs call used to read as "no pending line, so done"
    world.route(f"repos/{REPO}/commits/{HEAD}/check-runs", fail(), fail(), checks_page(run_obj("test")))
    r = world.run()
    assert r.returncode == 0, r.stderr
    assert world.calls(f"commits/{HEAD}/check-runs") == 3
    assert world.file("summary")["ci"]["total"] == 1


def test_persistent_gh_failure_is_reported_at_the_deadline(world: World) -> None:
    world.route(f"repos/{REPO}/issues/{PR}/comments", fail("gh: HTTP 502 Bad Gateway"))
    r = world.run("--timeout", "1")
    assert r.returncode == 6, r.stdout + r.stderr
    assert "HTTP 502" in r.stdout
    summary = world.file("summary")
    assert summary["result"] == "timeout" and "HTTP 502" in summary["errors"][-1]


def test_plain_timeout_is_exit_1(world: World) -> None:
    world.route(f"repos/{REPO}/commits/{HEAD}/check-runs", checks_page(run_obj("test", "queued", None)))
    r = world.run("--timeout", "1")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "CI pending (0 pass, 0 fail, 1 pending)" in r.stdout


def test_no_checks_yet_is_pending_during_the_grace(world: World) -> None:
    world.route(f"repos/{REPO}/commits/{HEAD}/check-runs", checks_page())
    assert world.run("--timeout", "1", "--ci-grace", "100").returncode == 1
    r = world.run("--ci-grace", "0")
    assert r.returncode == 0 and world.file("summary")["ci"]["state"] == "no-checks"


def test_commit_statuses_count_as_checks(world: World) -> None:
    world.route(f"repos/{REPO}/commits/{HEAD}/status",
                ok({"state": "pending", "statuses": [{"context": "ci/x", "state": "pending"}]}),
                ok({"state": "failure", "statuses": [{"context": "ci/x", "state": "failure"}]}))
    r = world.run()
    assert r.returncode == 0, r.stderr
    assert world.calls(f"commits/{HEAD}/status") == 2
    assert world.file("summary")["ci"]["fail"] == 1


def test_head_moved_ends_the_wait(world: World) -> None:
    world.route(f"repos/{REPO}/commits/{HEAD}/check-runs", checks_page(run_obj("test", "queued", None)))
    world.route(f"repos/{REPO}/pulls/{PR}", ok({"head": {"sha": HEAD}}), ok({"head": {"sha": NEW}}))
    r = world.run("--head", HEAD)
    assert r.returncode == 5, r.stdout + r.stderr
    assert f"new head {NEW[:12]}" in r.stdout
    summary = world.file("summary")
    assert summary["result"] == "head-moved" and summary["new_head"] == NEW and summary["head"] == HEAD


def test_marker_for_another_head_is_not_a_match(world: World) -> None:
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok([request("2026-10-23T09:30:00Z"), codex_comment(OLD, "completed")]))
    r = world.run("--timeout", "1")
    assert r.returncode == 1, r.stdout + r.stderr
    summary = world.file("summary")
    assert summary["codex"]["status"] == "other-head" and summary["codex"]["newest_seen_commit_sha"] == OLD
    assert world.file("findings") is None
    # the marker for the head wins over an older head's, whatever their order
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok([codex_comment(HEAD, "completed", "2026-10-23T10:00:00Z"),
                    codex_comment(OLD, "running", "2026-10-23T11:00:00Z")]))
    assert world.run().returncode == 0
    assert world.file("summary")["codex"]["commit_sha"] == HEAD


def test_no_codex_waits_for_ci_only(world: World) -> None:
    world.route(f"repos/{REPO}/issues/{PR}/comments", fail("must not be asked"))
    r = world.run("--no-codex", "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["codex"] == {"status": "skipped"}
    assert world.file("findings") is None and world.calls(f"issues/{PR}/comments") == 0


def test_no_such_pr_is_a_usage_error(world: World) -> None:
    world.route(f"repos/{REPO}/pulls/{PR}", fail("gh: Not Found (HTTP 404)"))
    r = world.run()
    assert r.returncode == 2 and "no such PR" in r.stderr


def test_bad_usage(world: World) -> None:
    assert world.run("--timeout", "soon").returncode == 2
    assert world.run("--head", "abc123").returncode == 2
    assert world.run("--since", "yesterday").returncode == 2
    assert world.run("--repo", "nonsense").returncode == 2


def load_module():
    ld = SourceFileLoader("pr_wait_mod", str(PR_WAIT))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("pr_wait_mod", ld))
    ld.exec_module(mod)
    return mod


def test_second_waiter_for_the_same_head_is_refused(world: World) -> None:
    world.route(f"repos/{REPO}/commits/{HEAD}/check-runs", checks_page(run_obj("test", "queued", None)))
    first = subprocess.Popen(world.argv("--timeout", "60"), env=world.env, stdout=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 15
        while not list(world.state.glob("lock-*")) and time.monotonic() < deadline:
            time.sleep(0.05)
        second = world.run("--out", str(world.out) + "-second")
        assert second.returncode == 4, second.stdout + second.stderr
        assert f"pid {first.pid}" in second.stderr and f"output prefix {world.out}" in second.stderr
        assert not Path(f"{world.out}-second-summary.json").exists()
    finally:
        first.send_signal(signal.SIGTERM)
        first.wait(timeout=10)
    assert first.returncode == 143
    assert not list(world.state.glob("lock-*")), "SIGTERM releases the lock"


def test_stale_lock_is_taken_over(world: World) -> None:
    world.state.mkdir()
    lock = world.state / f"lock-{REPO.replace('/', '__')}-{PR}-{HEAD}"
    dead = subprocess.Popen(["true"])
    dead.wait()
    lock.write_text(json.dumps({"pid": dead.pid, "start": "Thu Jan  1 00:00:00 1970", "out": "/nowhere"}))
    r = world.run()
    assert r.returncode == 0, r.stdout + r.stderr  # dead pid: stale

    # a live pid whose start time differs is pid reuse: also stale
    lock.write_text(json.dumps({"pid": os.getpid(), "start": "Thu Jan  1 00:00:00 1970", "out": "/nowhere"}))
    r = world.run()
    assert r.returncode == 0, r.stdout + r.stderr

    # a live pid with its real start time is a live waiter
    lock.write_text(json.dumps({"pid": os.getpid(), "start": load_module().proc_start(os.getpid()),
                                "out": "/somewhere"}))
    r = world.run()
    assert r.returncode == 4 and f"pid {os.getpid()}" in r.stderr and "/somewhere" in r.stderr
    assert lock.exists(), "a refused waiter leaves the live holder's lock alone"

    # an unreadable lock is stale too
    lock.write_text("not json")
    assert world.run().returncode == 0


def test_orphan_takeover_guard_is_broken_by_liveness(tmp_path: Path) -> None:
    pw = load_module()
    dead = subprocess.Popen(["true"])
    dead.wait()
    lock = tmp_path / "lock-x"
    lock.write_text(json.dumps({"pid": dead.pid, "start": "gone", "out": "o"}))
    # a taker SIGKILLed inside the guard: a fresh orphan guard must not make the starter report a dead holder
    Path(f"{lock}.takeover").write_text(json.dumps({"pid": dead.pid, "start": "gone"}))
    me = {"pid": os.getpid(), "start": pw.proc_start(os.getpid()), "out": "mine"}
    assert pw.acquire_lock(lock, me) is None
    assert json.loads(lock.read_text())["out"] == "mine"
    assert not Path(f"{lock}.takeover").exists()
    # a live holder is reported, whatever stale guard lies around
    Path(f"{lock}.takeover").write_text(json.dumps({"pid": dead.pid, "start": "gone"}))
    other = {"pid": dead.pid, "start": "x", "out": "theirs"}
    assert pw.acquire_lock(lock, other) == me


RACER = r"""
import os, sys, time
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
ld = SourceFileLoader("pw", sys.argv[1])
m = importlib.util.module_from_spec(importlib.util.spec_from_loader("pw", ld))
ld.exec_module(m)
lock, go, done = Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
me = os.getpid()
info = {"pid": me, "start": m.proc_start(me), "out": "o%d" % me}
print("READY", flush=True)
while not go.exists():
    time.sleep(0.001)
held = m.acquire_lock(lock, info)
print("WON" if held is None else "HELD", flush=True)
t = time.time()
while not done.exists() and time.time() - t < 60:
    time.sleep(0.05)
"""


@pytest.mark.parametrize("stale_first", [False, True])
def test_simultaneous_starters_yield_exactly_one_holder(tmp_path: Path, stale_first: bool) -> None:
    racer = tmp_path / "racer.py"
    racer.write_text(RACER)
    lock, go, done = tmp_path / "lock-x", tmp_path / "go", tmp_path / "done"
    if stale_first:
        lock.write_text(json.dumps({"pid": 999999999, "start": "gone", "out": "o"}))
    procs = [subprocess.Popen([sys.executable, str(racer), str(PR_WAIT), str(lock), str(go), str(done)],
                              stdout=subprocess.PIPE, text=True) for _ in range(8)]
    try:
        for p in procs:
            assert p.stdout.readline().strip() == "READY"
        go.touch()
        answers = [p.stdout.readline().strip() for p in procs]
    finally:
        done.touch()
        for p in procs:
            p.wait(timeout=30)
    assert sorted(answers) == ["HELD"] * 7 + ["WON"]


def test_parse_proc_stat_starttime_with_parens_in_comm() -> None:
    pw = load_module()
    fields = ["S"] + ["1"] * 18 + ["424242"] + ["0"] * 5  # state, then fields 4..21, starttime = field 22
    assert pw.parse_proc_stat("123 (a) b (c)) " + " ".join(fields)) == "proc:424242"
    assert pw.parse_proc_stat("123 (short)") is None


def test_marker_from_anyone_but_the_codex_app_is_not_believed(world: World) -> None:
    # an injected `completed` marker must not end the wait while the real review still runs
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok([codex_comment(HEAD, "running"), injected(HEAD, "completed")]))
    r = world.run("--timeout", "1")
    assert r.returncode == 1, r.stdout + r.stderr
    assert world.file("summary")["codex"]["status"] == "running"
    # the bot's login without the app is not the Codex app's summary comment either
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok([codex_comment(HEAD, "completed", user=BOT, performed_via_github_app=None)]))
    r = world.run("--timeout", "1")
    assert r.returncode == 1 and world.file("summary")["codex"]["status"] == "absent"
    # a user named like the bot but of type User is not it
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok([codex_comment(HEAD, "completed", user={"login": CODEX_LOGIN, "type": "User"},
                                  performed_via_github_app={"slug": "chatgpt-codex-connector"})]))
    assert world.run("--timeout", "1").returncode == 1


def test_fake_newer_running_marker_cannot_cause_codex_stuck(world: World) -> None:
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok([codex_comment(HEAD, "completed"), injected(HEAD, "running")]))
    r = world.run("--codex-stuck", "0.2")
    assert r.returncode == 0, r.stdout + r.stderr
    assert world.file("summary")["codex"]["status"] == "completed"
    assert world.file("codex")["code_review"]["status"] == "completed"


def test_empty_gh_output_is_unknown_not_no_checks(world: World) -> None:
    world.route(f"repos/{REPO}/commits/{HEAD}/check-runs", ok(""))
    r = world.run("--timeout", "1", "--ci-grace", "0")
    assert r.returncode == 6, r.stdout + r.stderr
    assert "empty gh output" in r.stdout


def test_a_check_registered_after_ci_finished_keeps_the_wait_open(world: World) -> None:
    # poll 1: CI passes but Codex still runs; poll 2: Codex completes but a new check appeared; poll 3: both hold
    world.route(f"repos/{REPO}/commits/{HEAD}/check-runs",
                checks_page(run_obj("test")),
                checks_page(run_obj("test"), run_obj("late", "queued", None)),
                checks_page(run_obj("test"), run_obj("late")))
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok([codex_comment(HEAD, "running")]), ok([codex_comment(HEAD, "completed")]))
    r = world.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert world.calls(f"commits/{HEAD}/check-runs") == 3
    assert {c["name"] for c in world.file("checks")} == {"test", "late"}
    assert world.file("summary")["ci"]["pending"] == 0
