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
skip = False
method, ep = "GET", None
for a in args[1:]:
    if skip:
        method, skip = a, False
    elif a == "-X":
        skip = True
    elif not a.startswith("-") and ep is None:
        ep = a.split("?")[0]
routes = json.load(open(os.path.join(d, "scenario.json")))["routes"]
key = ep if method == "GET" else method + " " + ep
if key not in routes:
    sys.stderr.write("fake gh: no route " + key + "\n"); sys.exit(1)
cf = os.path.join(d, "count-" + key.replace("/", "_").replace(" ", "_"))
n = int(open(cf).read()) if os.path.exists(cf) else 0
with open(cf + ".tmp.%d" % os.getpid(), "w") as f:
    f.write(str(n + 1))
os.replace(cf + ".tmp.%d" % os.getpid(), cf)
r = routes[key][min(n, len(routes[key]) - 1)]
import time
time.sleep(r.get("sleep", 0))
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


def sec_review(unresolved: bool | None = False, any_findings: bool | None = False, status: str = "completed",
               sha: str = HEAD) -> dict:
    sr: dict = {"commit_sha": sha, "status": status}
    if unresolved is not None:
        sr["has_unresolved_findings"] = unresolved
    if any_findings is not None:
        sr["has_any_findings"] = any_findings
    return sr


def codex_comment(sha: str, status: str, updated: str = "2026-10-23T10:00:00Z", unresolved: bool | None = False,
                  any_findings: bool | None = False, security: dict | None = ..., **who: object) -> dict:  # type: ignore[assignment]
    cr: dict = {"commit_sha": sha, "status": status}
    if unresolved is not None:
        cr["has_unresolved_findings"] = unresolved
    if any_findings is not None:
        cr["has_any_findings"] = any_findings
    state: dict = {"code_review": cr}
    if security is ...:
        security = sec_review(sha=sha)
    if security is not None:
        state["security_review"] = security
    body = ("<!-- codex-pull-request-review-summary -->\nCodex review\n"
            f"<!-- codex-review-state:v1 {json.dumps(state)} -->")
    return {"body": body, "created_at": "2026-10-23T09:00:00Z", "updated_at": updated, **(who or BOT_APP)}


def injected(sha: str, status: str, updated: str = "2026-10-23T12:00:00Z") -> dict:
    """A marker comment posted by anyone else (the repo is public)."""
    return codex_comment(sha, status, updated, user={"login": "mallory", "type": "User"},
                         performed_via_github_app=None)


def request(at: str) -> dict:
    return {"body": "@codex review", "created_at": at, "updated_at": at, "user": {"login": "djbclark", "type": "User"}}


# Issue-timeline items (REST `issues/N/timeline`). A `committed` item carries its commit's OWN author/committer
# date (GitHub orders it by that date) and is never a push time; only server stamps are: a check suite's
# `created_at` and a `head_ref_force_pushed` / `commented` item's `created_at`.
PUSH = "2026-10-24T10:00:00Z"  # the head's first check suite (the server-stamped push)
BEFORE = "2026-10-24T09:30:00Z"  # a request made before the head was pushed
AFTER = "2026-10-24T10:05:00Z"  # a request made after it


def committed(sha: str, date: str = "2026-10-24T09:00:00Z") -> dict:
    return {"event": "committed", "sha": sha, "author": {"date": date}, "committer": {"date": date}}


def forced(sha: str, at: str = PUSH) -> dict:
    return {"event": "head_ref_force_pushed", "commit_id": sha, "created_at": at}


def commented(body: str = "@codex review", login: str = "djbclark", at: str = AFTER, cid: int | None = None) -> dict:
    item = {"event": "commented", "body": body, "created_at": at, "user": {"login": login, "type": "User"}}
    return item if cid is None else {**item, "id": cid}


def suites(*created: str) -> dict:
    return ok({"total_count": len(created), "check_suites": [{"id": i, "created_at": t} for i, t in enumerate(created)]})


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
        self.route("graphql", gql())
        # the head was pushed (its check suite), then a request: so a missing marker alone never makes pr-wait post
        self.route(f"repos/{REPO}/commits/{HEAD}/check-suites", suites(PUSH))
        self.route(f"repos/{REPO}/issues/{PR}/timeline", ok([committed(HEAD), commented()]))
        self.route("user", ok({"login": "djbclark"}))
        self.route(f"POST repos/{REPO}/issues/{PR}/comments", ok({"id": 999, "body": "@codex review"}))

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

    def posts(self) -> int:
        cf = self.dir / f"count-POST_repos_{REPO}/issues/{PR}/comments".replace("/", "_")
        return int(cf.read_text()) if cf.exists() else 0

    def post_argvs(self) -> list[list[str]]:
        lines = (self.dir / "calls.log").read_text().splitlines()
        return [a for a in map(json.loads, lines) if "POST" in a]


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
    assert summary["ci"] == {"state": "done", "total": 2, "pass": 1, "success": 1, "fail": 1, "pending": 0}
    assert summary["merge_ready"] is False and summary["merge_blockers"] == ["ci-failed"]
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
    assert world.file("summary")["merge_ready"] is False


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


def thread(db: int, resolved: bool = False, outdated: bool = False, author: str = "chatgpt-codex-connector",
           path: str = "f.py", oid: str = OLD) -> dict:
    return {"isResolved": resolved, "isOutdated": outdated,
            "comments": {"nodes": [{"databaseId": db, "author": {"login": author}, "path": path,
                                    "originalCommit": {"oid": oid}}]}}


def gql(*threads: dict, has_next: bool = False, cursor: str = "CUR") -> dict:
    return ok({"data": {"repository": {"pullRequest": {"reviewThreads": {
        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor}, "nodes": list(threads)}}}}})


def old_finding(n: int = 50) -> dict:
    """A Codex finding left on an EARLIER head (OLD), as on PR 32 (2026-10-23)."""
    return finding(n, "2026-10-23T08:00:00Z", original=OLD, review=800)


def graphql_calls(world: World) -> list[list[str]]:
    lines = (world.dir / "calls.log").read_text().splitlines()
    return [a for a in map(json.loads, lines) if a[:2] == ["api", "graphql"]]


def test_all_clear_is_merge_ready(world: World) -> None:
    r = world.run()
    assert r.returncode == 0, r.stdout + r.stderr
    summary = world.file("summary")
    assert summary["merge_ready"] is True and summary["merge_blockers"] == []
    assert summary["open_findings"] == 0 and summary["findings_for_head"] == 0
    assert world.file("open-findings") == [] and "merge_ready: yes" in r.stdout


def test_unresolved_earlier_head_finding_blocks_merge_ready(world: World) -> None:
    # PR 32: Codex's P1 sits on an earlier head, the marker for the new head says unresolved, head-only says 0
    world.route(f"repos/{REPO}/issues/{PR}/comments", ok([codex_comment(HEAD, "completed", unresolved=True,
                                                                         any_findings=True)]))
    world.route(f"repos/{REPO}/pulls/{PR}/comments", ok([old_finding()]))
    world.route("graphql", gql(thread(50)))
    r = world.run()
    assert r.returncode == 0, r.stdout + r.stderr
    summary = world.file("summary")
    assert summary["findings_for_head"] == 0 and summary["open_findings"] == 1
    assert summary["has_unresolved_findings"] is True and summary["findings_mismatch"] == []
    assert summary["merge_ready"] is False and summary["merge_blockers"] == ["open-findings"]
    (opened,) = world.file("open-findings")
    assert opened["id"] == 50 and opened["original_commit_id"] == OLD and opened["isOutdated"] is False
    assert opened["title"].startswith("finding 50") and opened["path"] == "f.py"
    assert "open Codex findings: 1 (1 code, 0 security; 0 outdated)" in r.stdout
    assert "merge_ready: no (open-findings)" in r.stdout
    assert opened["kind"] == "code"


def test_resolved_earlier_head_finding_does_not_block(world: World) -> None:
    world.route(f"repos/{REPO}/pulls/{PR}/comments", ok([old_finding()]))
    world.route("graphql", gql(thread(50, resolved=True)))
    r = world.run()
    assert r.returncode == 0, r.stdout + r.stderr
    summary = world.file("summary")
    assert summary["open_findings"] == 0 and summary["merge_ready"] is True
    assert world.file("open-findings") == []


def test_outdated_unresolved_finding_is_listed_and_still_blocks(world: World) -> None:
    world.route(f"repos/{REPO}/issues/{PR}/comments", ok([codex_comment(HEAD, "completed", unresolved=True)]))
    world.route(f"repos/{REPO}/pulls/{PR}/comments", ok([old_finding()]))
    world.route("graphql", gql(thread(50, outdated=True)))
    r = world.run()
    summary = world.file("summary")
    assert summary["open_findings"] == 1 and summary["open_findings_outdated"] == 1
    assert summary["merge_ready"] is False and "open-findings" in summary["merge_blockers"]
    assert world.file("open-findings")[0]["isOutdated"] is True
    assert "open Codex findings: 1 (1 code, 0 security; 1 outdated)" in r.stdout


def test_marker_and_threads_disagreeing_is_a_mismatch_never_a_clean_zero(world: World) -> None:
    # the marker says unresolved but no Codex thread is found
    world.route(f"repos/{REPO}/issues/{PR}/comments", ok([codex_comment(HEAD, "completed", unresolved=True,
                                                                         any_findings=True)]))
    world.route(f"repos/{REPO}/pulls/{PR}/comments", ok([old_finding()]))
    world.route("graphql", gql(thread(50, resolved=True), thread(51, author="mallory"), thread(52)))  # 52: no comment
    r = world.run()
    summary = world.file("summary")
    assert len(summary["findings_mismatch"]) == 1 and "has_unresolved_findings=true" in summary["findings_mismatch"][0]
    assert summary["merge_ready"] is False and "findings-mismatch" in summary["merge_blockers"]
    assert "FINDINGS-MISMATCH" in r.stdout and "open Codex findings: 0" in r.stdout
    # the reverse: the marker says nothing is unresolved but a Codex thread is open
    world.route(f"repos/{REPO}/issues/{PR}/comments", ok([codex_comment(HEAD, "completed", unresolved=False)]))
    world.route("graphql", gql(thread(50)))
    world.run()
    summary = world.file("summary")
    assert "has_unresolved_findings=false" in summary["findings_mismatch"][0] and summary["merge_ready"] is False
    # has_any_findings with no Codex finding comment anywhere
    world.route(f"repos/{REPO}/issues/{PR}/comments", ok([codex_comment(HEAD, "completed", any_findings=True)]))
    world.route(f"repos/{REPO}/pulls/{PR}/comments", ok([]))
    world.route("graphql", gql())
    world.run()
    assert "has_any_findings=true" in world.file("summary")["findings_mismatch"][0]


def test_marker_without_the_unresolved_flag_is_unverified(world: World) -> None:
    world.route(f"repos/{REPO}/issues/{PR}/comments", ok([codex_comment(HEAD, "completed", unresolved=None,
                                                                         any_findings=None)]))
    assert world.run().returncode == 0
    summary = world.file("summary")
    assert summary["merge_ready"] is False and summary["merge_blockers"] == ["marker-unverified"]


def test_codex_failed_or_ci_failing_or_skipped_is_not_merge_ready(world: World) -> None:
    world.route(f"repos/{REPO}/issues/{PR}/comments", ok([codex_comment(HEAD, "failed")]))
    world.run()
    assert world.file("summary")["merge_blockers"] == ["codex-failed"]
    world.happy()
    world.route(f"repos/{REPO}/commits/{HEAD}/check-runs", checks_page(run_obj("test", conclusion="failure")))
    world.run()
    assert world.file("summary")["merge_blockers"] == ["ci-failed"]
    world.happy()
    world.route(f"repos/{REPO}/commits/{HEAD}/check-runs", checks_page())
    world.run("--ci-grace", "0")
    assert world.file("summary")["merge_blockers"] == ["no-checks"]
    world.happy()
    world.run("--no-codex")
    assert world.file("summary")["merge_blockers"] == ["codex-skipped"]


def test_two_graphql_pages_are_read_by_cursor(world: World) -> None:
    world.route(f"repos/{REPO}/pulls/{PR}/comments", ok([old_finding(50), old_finding(51)]))
    world.route("graphql", gql(thread(50, resolved=True), has_next=True, cursor="CUR1"), gql(thread(51)))
    r = world.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert [t["id"] for t in world.file("open-findings")] == [51]
    first, second = graphql_calls(world)
    assert not any(x.startswith("cursor=") for x in first) and "cursor=CUR1" in second
    # variables are separate argv elements, never a shell string
    assert "owner=djbclark" in first and "name=djbclark-ade" in first and f"number={PR}" in first


def test_graphql_failure_is_unknown_not_done(world: World) -> None:
    world.route("graphql", fail(), ok(json.dumps({"errors": [{"message": "boom"}]})), gql())
    r = world.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(graphql_calls(world)) == 3  # two failures retried, never read as "no open findings"
    assert world.file("summary")["merge_ready"] is True
    # persistent: never done, never merge-ready
    world.route("graphql", fail("gh: HTTP 502"))
    r = world.run("--timeout", "1")
    assert r.returncode == 6, r.stdout + r.stderr
    summary = world.file("summary")
    assert summary["merge_ready"] is False and "findings-not-collected" in summary["merge_blockers"]
    assert world.file("open-findings") is None and "HTTP 502" in r.stdout


def test_drop_if_stale_only_removes_a_file_that_is_there_and_not_live(tmp_path: Path) -> None:
    pw = load_module()
    lock = tmp_path / "lock-x"
    pw.drop_if_stale(lock)  # missing stays missing (a fresh lock another taker made must never be unlinked)
    assert not lock.exists()
    live = {"pid": os.getpid(), "start": pw.proc_start(os.getpid()), "out": "o"}
    lock.write_text(json.dumps(live))
    pw.drop_if_stale(lock)
    assert lock.exists()
    lock.write_text(json.dumps({"pid": 999999999, "start": "gone"}))
    pw.drop_if_stale(lock)
    assert not lock.exists()
    lock.write_text("not json")
    pw.drop_if_stale(lock)
    assert not lock.exists()


def test_the_lock_appears_with_its_content_in_one_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pw = load_module()
    lock = tmp_path / "lock-x"
    seen: list[tuple[bool, str]] = []
    real_link = os.link

    def spy(src: object, dst: object, **kw: object) -> None:
        seen.append((Path(str(dst)).exists(), Path(str(src)).read_text()))
        real_link(src, dst, **kw)

    monkeypatch.setattr(os, "link", spy)
    assert pw.create_exclusive(lock, {"pid": 1}) is True
    assert seen == [(False, json.dumps({"pid": 1}))], "the lock path is absent before, complete from the link on"
    assert json.loads(lock.read_text()) == {"pid": 1}
    assert pw.create_exclusive(lock, {"pid": 2}) is False and json.loads(lock.read_text()) == {"pid": 1}


def sec_finding(n: int = 60, **kw: object) -> dict:
    """A Codex SECURITY finding: its own mark, no code mark (PR 20 thread 4361214081)."""
    return {**old_finding(n), "body": f"security finding {n}\n<!-- codex-security-review-finding:v1 -->", **kw}


def test_open_security_thread_blocks_merge_ready_and_is_tagged_security(world: World) -> None:
    # PR 20 shape: the code marker is clean (false), the security marker says unresolved, the thread is a security one
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok([codex_comment(HEAD, "completed", security=sec_review(unresolved=True, any_findings=True))]))
    world.route(f"repos/{REPO}/pulls/{PR}/comments", ok([sec_finding(60)]))
    world.route("graphql", gql(thread(60)))
    r = world.run()
    assert r.returncode == 0, r.stdout + r.stderr
    summary = world.file("summary")
    assert summary["open_findings"] == 1 and summary["open_findings_by_kind"] == {"code": 0, "security": 1}
    assert summary["findings_mismatch"] == [] and summary["security_has_unresolved_findings"] is True
    assert summary["merge_ready"] is False and summary["merge_blockers"] == ["open-findings"]
    (opened,) = world.file("open-findings")
    assert opened["id"] == 60 and opened["kind"] == "security" and opened["title"].startswith("security finding 60")
    assert "1 security" in r.stdout and "(security completed)" in r.stdout


def test_security_head_findings_are_listed_with_their_kind(world: World) -> None:
    world.route(f"repos/{REPO}/pulls/{PR}/comments",
                ok([finding(1, "2026-10-23T09:45:00Z"), sec_finding(2, original_commit_id=HEAD)]))
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok([codex_comment(HEAD, "completed", unresolved=True, any_findings=True,
                                  security=sec_review(unresolved=True, any_findings=True))]))
    world.route("graphql", gql(thread(1), thread(2)))
    assert world.run().returncode == 0
    assert {f["id"]: f["kind"] for f in world.file("findings")} == {1: "code", 2: "security"}
    summary = world.file("summary")
    assert summary["findings_for_head_by_kind"] == {"code": 1, "security": 1}
    assert summary["open_findings_by_kind"] == {"code": 1, "security": 1} and summary["findings_mismatch"] == []


def test_security_marker_mismatch_both_ways(world: World) -> None:
    # security marker says unresolved, no security thread (a code thread must not satisfy it)
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok([codex_comment(HEAD, "completed", unresolved=True, any_findings=True,
                                  security=sec_review(unresolved=True, any_findings=False))]))
    world.route(f"repos/{REPO}/pulls/{PR}/comments", ok([old_finding(50)]))
    world.route("graphql", gql(thread(50)))
    world.run()
    mm = world.file("summary")["findings_mismatch"]
    assert len(mm) == 1 and mm[0].startswith("security:") and "has_unresolved_findings=true" in mm[0]
    # security marker says nothing unresolved, a security thread is open
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok([codex_comment(HEAD, "completed", security=sec_review(unresolved=False))]))
    world.route(f"repos/{REPO}/pulls/{PR}/comments", ok([sec_finding(60)]))
    world.route("graphql", gql(thread(60)))
    world.run()
    mm = world.file("summary")["findings_mismatch"]
    assert any(m.startswith("security:") and "false but 1 open" in m for m in mm)
    assert "findings-mismatch" in world.file("summary")["merge_blockers"]


def test_security_review_must_be_terminal_to_end_the_wait_and_completed_to_be_merge_ready(world: World) -> None:
    # code completed but the security review still running: not done yet (a security finding may still land)
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok([codex_comment(HEAD, "completed", security=sec_review(status="running"))]),
                ok([codex_comment(HEAD, "completed", security=sec_review(status="completed"))]))
    r = world.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert world.calls(f"issues/{PR}/comments") == 2 and world.file("summary")["merge_ready"] is True
    # security failed is terminal but not merge-ready
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok([codex_comment(HEAD, "completed", security=sec_review(status="failed"))]))
    assert world.run().returncode == 0
    assert world.file("summary")["merge_blockers"] == ["security-failed"]
    # security marker for another head: never done on it, and stuck rather than a false done
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok([codex_comment(HEAD, "completed", security=sec_review(sha=OLD))]))
    assert world.run("--codex-stuck", "0.3").returncode == 3
    # security marker without a boolean flag
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok([codex_comment(HEAD, "completed", security=sec_review(unresolved=None, any_findings=None))]))
    assert world.run().returncode == 0
    assert world.file("summary")["merge_blockers"] == ["security-marker-unverified"]


def test_a_marker_without_security_review_does_not_block_on_it(world: World) -> None:
    world.route(f"repos/{REPO}/issues/{PR}/comments", ok([codex_comment(HEAD, "completed", security=None)]))
    r = world.run()
    assert r.returncode == 0, r.stdout + r.stderr
    summary = world.file("summary")
    assert summary["security_status"] == "absent" and summary["merge_ready"] is True
    # ...but a security thread still gates
    world.route(f"repos/{REPO}/issues/{PR}/comments", ok([codex_comment(HEAD, "completed", security=None)]))
    world.route(f"repos/{REPO}/pulls/{PR}/comments", ok([sec_finding(60)]))
    world.route("graphql", gql(thread(60)))
    world.run()
    assert world.file("summary")["merge_blockers"] == ["open-findings"]


def test_all_skipped_or_all_neutral_ci_is_not_merge_ready(world: World) -> None:
    world.route(f"repos/{REPO}/commits/{HEAD}/check-runs",
                checks_page(run_obj("a", conclusion="skipped"), run_obj("b", conclusion="neutral")))
    assert world.run().returncode == 0
    summary = world.file("summary")
    assert summary["ci"]["pass"] == 2 and summary["ci"]["success"] == 0 and summary["ci"]["fail"] == 0
    assert summary["merge_ready"] is False and summary["merge_blockers"] == ["ci-none-succeeded"]
    # beside one real success, skipped and neutral are fine
    world.route(f"repos/{REPO}/commits/{HEAD}/check-runs",
                checks_page(run_obj("a", conclusion="skipped"), run_obj("b", conclusion="neutral"), run_obj("c")))
    assert world.run().returncode == 0
    assert world.file("summary")["merge_ready"] is True and world.file("summary")["ci"]["success"] == 1


def test_a_codex_finding_that_is_a_reply_in_a_human_thread_is_open(world: World) -> None:
    world.route(f"repos/{REPO}/issues/{PR}/comments",
                ok([codex_comment(HEAD, "completed", unresolved=True, any_findings=True)]))
    world.route(f"repos/{REPO}/pulls/{PR}/comments", ok([old_finding(50)]))
    human_first = thread(7, author="djbclark")
    human_first["comments"]["nodes"].append(thread(50)["comments"]["nodes"][0])
    world.route("graphql", gql(human_first))
    assert world.run().returncode == 0
    summary = world.file("summary")
    assert summary["open_findings"] == 1 and summary["merge_blockers"] == ["open-findings"]
    assert world.file("open-findings")[0]["id"] == 50
    # the query asks for the whole thread, not only its first comment
    assert "comments(first:100)" in next(x for x in graphql_calls(world)[0] if x.startswith("query="))


def test_script_defers_annotations_so_stock_macos_python_3_9_can_load_it() -> None:
    # `X | None` in a signature raises TypeError on Python < 3.10 unless annotations are deferred (adversary D1, PR 34).
    import ast

    tree = ast.parse(PR_WAIT.read_text())
    assert any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
               and any(a.name == "annotations" for a in n.names) for n in tree.body)
    stock = Path("/usr/bin/python3")
    if not stock.exists():
        return
    version = subprocess.run([str(stock), "-c", "import sys; print(sys.version_info[1])"],
                             capture_output=True, text=True).stdout.strip()
    if version.isdigit() and int(version) < 10:
        run = subprocess.run([str(stock), "-I", str(PR_WAIT), "--help"], capture_output=True, text=True)
        assert run.returncode == 0, run.stderr


# ---- requesting the Codex review (2026-10-24) --------------------------------------------------------

COMMENTS = f"repos/{REPO}/issues/{PR}/comments"
TIMELINE = f"repos/{REPO}/issues/{PR}/timeline"
POST_ARGV = ["api", "-X", "POST", COMMENTS, "-f", "body=@codex review"]
NOMARK = ok([])


def test_posts_one_request_when_the_head_has_no_marker_and_none_was_requested(world: World) -> None:
    world.route(TIMELINE, ok([committed(OLD), committed(HEAD)]))
    world.route(COMMENTS, NOMARK, NOMARK, NOMARK, ok([codex_comment(HEAD, "completed")]))
    r = world.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert world.posts() == 1, "one post, however many polls found no marker afterwards"
    assert world.post_argvs() == [POST_ARGV]  # an argv list; the body goes through -f
    summary = world.file("summary")
    assert summary["codex_requested"] == 1 and "posted @codex review (comment 999)" in summary["codex_request_note"]
    assert "@codex review requested 1x" in r.stdout
    state = json.loads(next(world.state.glob("request-*.json")).read_text())
    assert state["own"] == 1 and state["ids"] == [999] and isinstance(state["last_at"], float)


@pytest.mark.parametrize("status", ["running", "completed", "failed"])
def test_no_post_when_a_marker_for_the_head_exists_whatever_its_status(world: World, status: str) -> None:
    world.route(TIMELINE, ok([committed(HEAD)]))  # nobody has asked: only the marker keeps pr-wait quiet
    world.route(COMMENTS, ok([codex_comment(HEAD, status)]))
    r = world.run("--codex-stuck", "0.5", "--timeout", "5")
    assert r.returncode == (3 if status == "running" else 0), r.stdout + r.stderr
    assert world.posts() == 0 and world.calls("issues/7/timeline") == 0
    summary = world.file("summary")
    assert summary["codex_requested"] == 0 and "no request needed" in summary["codex_request_note"]


@pytest.mark.parametrize("flag", ["--no-codex", "--no-request"])
def test_no_post_with_no_codex_or_no_request(world: World, flag: str) -> None:
    world.route(TIMELINE, ok([committed(HEAD)]))
    world.route(COMMENTS, NOMARK)
    r = world.run(flag, "--codex-stuck", "0.5", "--timeout", "5")
    assert r.returncode == (0 if flag == "--no-codex" else 3), r.stdout + r.stderr
    assert world.posts() == 0 and world.calls("issues/7/timeline") == 0
    summary = world.file("summary")
    assert summary["codex_requested"] == 0
    if flag == "--no-request":
        assert "disabled" in summary["codex_request_note"]


@pytest.mark.parametrize("author,pr_author,me", [
    ("djbclark", None, "djbclark"),  # the authenticated gh user
    ("alice", "alice", "ci-bot"),  # the PR author
    ("djbclark", None, "ci-bot"),  # the repo owner (the OWNER of --repo)
])
def test_no_post_when_a_request_exists_since_the_push(world: World, author: str, pr_author: str | None,
                                                      me: str) -> None:
    world.route(f"repos/{REPO}/pulls/{PR}", ok({"head": {"sha": HEAD}, "user": {"login": pr_author}}))
    world.route("user", ok({"login": me}))
    world.route(TIMELINE, ok([committed(HEAD), commented("@codex review\n", author)]))  # a stripped body counts
    world.route(COMMENTS, NOMARK)
    r = world.run("--codex-stuck", "0.5", "--timeout", "5")
    assert r.returncode == 3, r.stdout + r.stderr
    assert world.posts() == 0
    assert "already exists (1)" in world.file("summary")["codex_request_note"]


# (timeline, check-suite stamps, posts expected). A `committed` item's own date is irrelevant: only the server's
# check-suite / force-push stamps date the push, and a request counts only when it is LATER than that push.
@pytest.mark.parametrize("timeline,stamps,posts", [
    # A1: committed locally at 09:00, asked for the PREVIOUS head at 09:30, pushed (suite) at 10:00: GitHub
    # places the commit by its own date, i.e. before the request, but the request is not for this head
    ([committed(OLD), committed(HEAD, "2026-10-24T09:00:00Z"), commented(at=BEFORE)], [PUSH], 1),
    ([committed(HEAD, "2001-01-01T00:00:00Z"), commented(at=BEFORE)], [PUSH], 1),  # a far-past commit date
    ([commented(at=AFTER), committed(HEAD, "2099-01-01T00:00:00Z")], [PUSH], 0),  # a future commit date, placed after it
    ([committed(HEAD), commented(at=AFTER)], [PUSH], 0),  # asked after the push
    ([committed(HEAD), commented(at=AFTER)], ["2026-10-24T10:20:00Z", PUSH], 0),  # the EARLIEST suite is the push
    ([committed(HEAD), commented(at=AFTER), forced(HEAD, "2026-10-24T10:10:00Z")], [PUSH], 1),  # force-push later
    ([committed(HEAD), commented(at="2026-10-24T10:15:00Z"), forced(HEAD, "2026-10-24T10:10:00Z")], [PUSH], 0),
    ([committed(HEAD), commented(at="2026-10-24T09:30:00Z"), forced(HEAD, "2026-10-24T09:00:00Z")], [PUSH], 1),
    ([commented(at=AFTER), forced(OLD, "2026-10-24T11:00:00Z")], [PUSH], 0),  # another sha's force-push
], ids=["A1-commit-before-request-pushed-after", "far-past-commit-date", "future-commit-date", "asked-after-push",
        "earliest-suite", "force-push-stamp-later-than-suite", "asked-after-force-push",
        "suite-later-than-force-push", "force-push-of-another-sha"])
def test_a_request_counts_only_when_later_than_the_server_stamped_push(world: World, timeline: list[dict],
                                                                      stamps: list[str], posts: int) -> None:
    world.route(f"repos/{REPO}/commits/{HEAD}/check-suites", suites(*stamps))
    world.route(TIMELINE, ok(timeline))
    world.route(COMMENTS, NOMARK, ok([codex_comment(HEAD, "completed")]))
    assert world.run().returncode == 0
    assert world.posts() == posts


def test_with_no_server_push_stamp_it_leans_toward_posting_capped_at_two(world: World) -> None:
    world.route(f"repos/{REPO}/commits/{HEAD}/check-suites", ok({"total_count": 0, "check_suites": []}))
    world.route(TIMELINE, ok([committed(HEAD), commented()]))  # undatable: not counted
    world.route(COMMENTS, NOMARK, ok([codex_comment(HEAD, "running")]))
    r = world.run("--rerequest-after", "1", "--codex-stuck", "3", "--timeout", "20")
    assert r.returncode == 3, r.stdout + r.stderr
    assert world.posts() == 2, "posted, re-requested once, never a third"
    assert world.file("summary")["codex_requested"] == 2


def test_a_post_that_errored_but_landed_is_recorded_as_ours_so_the_re_request_is_not_lost(world: World) -> None:
    world.route(TIMELINE, ok([committed(HEAD)]), ok([committed(HEAD), commented()]))  # the request shows up later
    world.route(f"POST {COMMENTS}", fail("gh: timeout after the server accepted it"), ok({"id": 1000}))
    world.route(COMMENTS, NOMARK, NOMARK, ok([codex_comment(HEAD, "running")]))
    r = world.run("--rerequest-after", "1", "--codex-stuck", "4", "--timeout", "20")
    assert r.returncode == 3, r.stdout + r.stderr
    assert world.posts() == 2, "the errored first POST, then the one re-request"
    summary = world.file("summary")
    assert summary["codex_requested"] == 2 and "errored but landed" in summary["codex_request_note"]


def test_codex_receipts_and_quotes_of_the_phrase_are_not_requests(world: World) -> None:
    # AGENTS.md rule 9 (PR 12, PR 10): Codex's own comments quote `@codex review`
    world.route(TIMELINE, ok([committed(HEAD),
                              commented("@codex review", CODEX_LOGIN),
                              commented('About Codex: Comment "@codex review".', CODEX_LOGIN),
                              commented("> @codex review\nlgtm"),  # a quote by the right author
                              commented("@codex review please"),
                              commented("@codex review", "mallory")]))  # exact body, wrong author
    world.route(COMMENTS, NOMARK, ok([codex_comment(HEAD, "completed")]))
    assert world.run().returncode == 0
    assert world.posts() == 1


@pytest.mark.parametrize("what", ["check-suites-fail", "timeline-fails", "user-fails"])
def test_undecidable_means_no_post_and_says_so(world: World, what: str) -> None:
    if what == "check-suites-fail":
        world.route(f"repos/{REPO}/commits/{HEAD}/check-suites", fail("gh: HTTP 502 Bad Gateway"))
    elif what == "timeline-fails":
        world.route(TIMELINE, fail("gh: HTTP 502 Bad Gateway"))
    else:
        world.route("user", fail("gh: HTTP 401"))
    world.route(COMMENTS, NOMARK)
    r = world.run("--codex-stuck", "0.5", "--timeout", "5")
    assert r.returncode == 3, r.stdout + r.stderr  # a failed decision never turns into exit 6
    assert world.posts() == 0
    summary = world.file("summary")
    assert summary["codex_requested"] == 0 and "undecidable, nothing posted" in summary["codex_request_note"]


def test_a_failed_check_suites_call_is_retried_and_decides_on_a_later_poll(world: World) -> None:
    suites_ep = f"repos/{REPO}/commits/{HEAD}/check-suites"
    world.route(suites_ep, fail("gh: HTTP 502"), fail("gh: HTTP 502"), suites(PUSH))
    world.route(TIMELINE, ok([committed(HEAD)]))
    world.route(COMMENTS, NOMARK, NOMARK, NOMARK, ok([codex_comment(HEAD, "completed")]))
    r = world.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert world.calls(f"commits/{HEAD}/check-suites") == 3
    assert world.posts() == 1 and world.file("summary")["codex_requested"] == 1


def test_a_failed_post_is_not_recorded_and_is_rechecked_before_the_next(world: World) -> None:
    world.route(TIMELINE, ok([committed(HEAD)]))
    world.route(f"POST {COMMENTS}", fail("gh: HTTP 500"), ok({"id": 1000}))
    world.route(COMMENTS, NOMARK, NOMARK, ok([codex_comment(HEAD, "completed")]))
    assert world.run().returncode == 0
    assert world.posts() == 2 and world.file("summary")["codex_requested"] == 1
    assert world.calls("issues/7/timeline") == 2  # the timeline was read again before the second attempt


def test_a_review_stuck_running_is_requested_once_more_never_a_third_time(world: World) -> None:
    world.route(TIMELINE, ok([committed(HEAD)]))  # a lagging timeline never shows pr-wait's own comments
    world.route(COMMENTS, NOMARK, ok([codex_comment(HEAD, "running")]))
    r = world.run("--rerequest-after", "1", "--codex-stuck", "3", "--timeout", "20")
    assert r.returncode == 3, r.stdout + r.stderr
    assert world.posts() == 2, "the first request, one re-request after the Running window, never a third"
    summary = world.file("summary")
    assert summary["codex_requested"] == 2
    note = summary["codex_request_note"]
    assert "posted @codex review" in note and "re-requested" in note and "openai/codex#55890" in note


def test_no_re_request_before_the_running_window_ends(world: World) -> None:
    world.route(TIMELINE, ok([committed(HEAD)]))
    world.route(COMMENTS, NOMARK, ok([codex_comment(HEAD, "running")]))
    r = world.run("--rerequest-after", "600", "--codex-stuck", "1.5", "--timeout", "20")
    assert r.returncode == 3, r.stdout + r.stderr
    assert world.posts() == 1
    assert "openai/codex#55890" in world.file("summary")["codex_request_note"]


def test_a_human_request_beside_pr_waits_own_blocks_the_re_request(world: World) -> None:
    # two requests since the push already (one is pr-wait's): never a third
    world.route(TIMELINE, ok([committed(HEAD)]), ok([committed(HEAD), commented(), commented()]))
    world.route(COMMENTS, NOMARK, ok([codex_comment(HEAD, "running")]))
    r = world.run("--rerequest-after", "0.5", "--codex-stuck", "2", "--timeout", "20")
    assert r.returncode == 3, r.stdout + r.stderr
    assert world.posts() == 1


def test_a_second_run_on_the_same_head_does_not_post_again(world: World) -> None:
    # the timeline lags (never shows pr-wait's own comment): only the persisted state can stop a second post
    world.route(TIMELINE, ok([committed(HEAD)]))
    world.route(COMMENTS, NOMARK)
    assert world.run("--codex-stuck", "0.5", "--timeout", "5").returncode == 3
    assert world.posts() == 1
    r = world.run("--codex-stuck", "0.5", "--timeout", "5")
    assert r.returncode == 3, r.stdout + r.stderr
    assert world.posts() == 1
    summary = world.file("summary")
    assert summary["codex_requested"] == 1 and "earlier run" in summary["codex_request_note"]


def test_requests_per_head_are_capped_at_two_across_runs(world: World) -> None:
    world.route(TIMELINE, ok([committed(HEAD)]))
    world.route(COMMENTS, NOMARK)
    assert world.run("--codex-stuck", "0.5", "--timeout", "5").returncode == 3  # request 1
    world.route(COMMENTS, ok([codex_comment(HEAD, "running")]))
    for _ in range(2):  # request 2, then none
        assert world.run("--rerequest-after", "0", "--codex-stuck", "0.5", "--timeout", "5").returncode == 3
    assert world.posts() == 2
    assert world.file("summary")["codex_requested"] == 2
    # another head starts afresh
    assert json.loads(next(world.state.glob(f"request-*-{HEAD}.json")).read_text())["own"] == 2


def test_push_time_and_request_counting_use_server_stamps_as_datetimes() -> None:
    pw = load_module()
    allowed = {"djbclark"}
    at = lambda s: pw.parse_ts(s)  # noqa: E731
    ps = pw.push_stamp
    assert ps([{"created_at": "2026-10-24T10:20:00Z"}, {"created_at": PUSH}], [], HEAD) == at(PUSH)  # the EARLIEST suite
    assert ps([], [], HEAD) is None  # no server stamp at all
    assert ps([{"created_at": PUSH}], [forced(HEAD, "2026-10-24T10:10:00Z"), forced(HEAD, "2026-10-24T10:07:00Z")],
              HEAD) == at("2026-10-24T10:10:00Z")  # a force-push: the LATEST stamp wins over the suite
    assert ps([{"created_at": PUSH}], [forced(HEAD, "2026-10-24T09:00:00Z")], HEAD) == at(PUSH)  # later of the two
    assert ps([{"created_at": PUSH}], [forced(OLD, "2026-10-24T11:00:00Z"), committed(HEAD, "2099-01-01T00:00:00Z")],
              HEAD) == at(PUSH)  # another sha's force-push and a commit's own date are not push stamps
    assert ps([{"created_at": "junk"}, "x", {}], ["y", {"event": "head_ref_force_pushed"}], HEAD) is None
    f, pushed = pw.requests_since_push, at(PUSH)
    tl = [commented(), commented("@codex review", "DJBCLARK"), commented(at=BEFORE), commented(at=PUSH)]
    assert f(tl, allowed, pushed) == 2  # login case is not significant; before the push and AT it do not count
    # datetimes, not strings: 12:00+02:00 is 10:00Z (not after the push) though its text sorts after "10:00:00Z"
    assert f([commented(at="2026-10-24T12:00:00+02:00")], allowed, pushed) == 0
    assert f([commented(at="2026-10-24T12:06:00+02:00")], allowed, pushed) == 1
    assert f([{"event": "reviewed", "body": "@codex review", "created_at": AFTER, "user": {"login": "djbclark"}},
              "junk", {"event": "commented", "body": None, "created_at": AFTER},
              {**commented(), "created_at": None}, {**commented(), "created_at": "soon"}], allowed, pushed) == 0
    assert f([commented()], allowed, None) == 0  # no push stamp: nothing can be dated, the caller leans to posting


def test_request_state_fields_are_read_with_get_clamped_and_finite(tmp_path: Path) -> None:
    pw = load_module()
    p = tmp_path / "request-x.json"
    blank = {"own": 0, "attempts": 0, "last_at": None, "attempt_at": None, "ids": [], "adopted_ids": []}
    assert pw.load_request_state(p) == blank  # missing file
    for text in ["not json", "[]", "{}", '{"own": "1"}', '{"own": true}', '{"own": -4}', '{"own": NaN}']:
        p.write_text(text)
        assert pw.load_request_state(p)["own"] == 0, text
    p.write_text('{"own": 7}')
    assert pw.load_request_state(p)["own"] == 2  # clamped to MAX_REQUESTS, never reset below it
    p.write_text('{"own": 1}')  # an older record without the later fields
    assert pw.load_request_state(p) == {**blank, "own": 1, "attempts": 1}
    p.write_text('{"own": 2, "last_at": 5, "attempt_at": 6.5, "ids": [1, 2], "adopted_ids": [1, 2]}')
    assert pw.load_request_state(p) == {"own": 2, "attempts": 2, "last_at": 5.0, "attempt_at": 6.5, "ids": [1, 2],
                                        "adopted_ids": [1, 2]}
    # adopted_ids: plain ints only (no bool, string, float), at most MAX_IDS, the newest kept; not a list is none
    p.write_text(json.dumps({"adopted_ids": [True, "5", 1.5, None, *range(20, 40)]}))
    assert pw.load_request_state(p)["adopted_ids"] == list(range(40 - pw.MAX_IDS, 40))
    for text in ['{"adopted_ids": 7}', '{"adopted_ids": "x"}', '{"adopted_ids": {"1": 2}}']:
        p.write_text(text)
        assert pw.load_request_state(p)["adopted_ids"] == [], text
    for bad in ["NaN", "Infinity", "-Infinity", "1e999", "true", '"7"']:  # a hostile time must not fire a re-request
        p.write_text('{"own": 1, "last_at": %s, "attempt_at": %s}' % (bad, bad))
        st = pw.load_request_state(p)
        assert st["last_at"] is None and st["attempt_at"] is None and st["own"] == 1, bad
    # the POST-attempt count: garbage is none, a huge one is the cap, and it never reads below `own`
    for text in ['{"attempts": "1"}', '{"attempts": true}', '{"attempts": -4}', '{"attempts": NaN}', '{"attempts": 1.5}']:
        p.write_text(text)
        assert pw.load_request_state(p)["attempts"] == 0, text
    for text, want in [('{"attempts": 1}', 1), ('{"attempts": 99}', 2), ('{"attempts": 1e999}', 0),
                       ('{"own": 2}', 2), ('{"own": 1, "attempts": 0}', 1), ('{"own": 1, "attempts": 2}', 2)]:
        p.write_text(text)
        assert pw.load_request_state(p)["attempts"] == want, text


def test_repo_slug_case_does_not_split_the_request_state(world: World) -> None:
    up = REPO.upper()
    world.route(TIMELINE, ok([committed(HEAD)]))
    world.route(COMMENTS, NOMARK, NOMARK, ok([codex_comment(HEAD, "completed")]))
    routes, world.routes = dict(world.routes), {}
    for ep, responses in routes.items():
        world.route(ep.replace(REPO, up), *responses)
    r = world.run("--repo", up)
    assert r.returncode == 0, r.stdout + r.stderr
    assert world.file("summary")["codex_requested"] == 1
    assert [p.name for p in world.state.glob("request-*")] == [f"request-{REPO.replace('/', '__')}-{PR}-{HEAD}.json"]


def test_waiters_for_the_same_repo_in_another_case_share_one_lock(world: World) -> None:
    # APFS is case-insensitive, so the lock's NAME is asserted, not just the refusal (Linux would differ)
    first = subprocess.Popen(world.argv("--repo", REPO.upper(), "--head", HEAD, "--timeout", "60"), env=world.env,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)  # gh fails: it just waits
    try:
        deadline = time.monotonic() + 15
        while not list(world.state.glob("lock-*")) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert [p.name for p in world.state.glob("lock-*")] == [f"lock-{REPO.replace('/', '__')}-{PR}-{HEAD}"]
        second = world.run("--repo", REPO, "--head", HEAD, "--out", str(world.out) + "-second")
        assert second.returncode == 4, second.stdout + second.stderr
    finally:
        first.send_signal(signal.SIGTERM)
        first.wait(timeout=10)


def test_a_state_write_failure_after_the_post_is_a_warning_not_a_crash(world: World) -> None:
    world.state.mkdir(parents=True)
    (world.state / f"request-{REPO.replace('/', '__')}-{PR}-{HEAD}.json").mkdir()  # os.replace onto it fails
    world.route(TIMELINE, ok([committed(HEAD)]))
    world.route(COMMENTS, NOMARK, NOMARK, ok([codex_comment(HEAD, "completed")]))
    r = world.run()
    assert r.returncode == 0, r.stdout + r.stderr  # never 1 (the timeout code), and the summary is written
    assert world.posts() == 1, "the in-memory count still stops a second post in this run"
    note = world.file("summary")["codex_request_note"]
    assert "posted @codex review" in note and "could not write request-" in note
    assert not list(world.state.glob("*.tmp.*")), "a failed replace leaves no temp file"


# ---- POST attempts, errored POSTs and clock skew (PR 58 round 2, Codex P2) ----------------------------


def iso(offset: float = 0.0) -> str:
    """A server-style timestamp `offset` seconds from the real clock (attempt times are real wall-clock times)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset))


def no_push_stamp(world: World) -> None:
    world.route(f"repos/{REPO}/commits/{HEAD}/check-suites", ok({"total_count": 0, "check_suites": []}))


def request_state(world: World) -> dict:
    return json.loads(next(world.state.glob(f"request-*-{HEAD}.json")).read_text())


def test_no_stamp_repo_an_errored_post_that_landed_is_adopted_and_not_posted_twice(world: World) -> None:
    # a repo with no check suites: requests_since_push() is always 0, so only the attempt time can recognise it
    no_push_stamp(world)
    world.route(TIMELINE, ok([committed(HEAD)]), ok([committed(HEAD), commented(at=iso(0))]))
    world.route(f"POST {COMMENTS}", fail("gh: timeout after the server accepted it"), ok({"id": 1000}))
    world.route(COMMENTS, NOMARK, NOMARK, NOMARK, ok([codex_comment(HEAD, "completed")]))
    r = world.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert world.posts() == 1, "the errored POST landed: the next poll adopts it instead of posting again"
    summary = world.file("summary")
    assert summary["codex_requested"] == 1 and "errored but landed" in summary["codex_request_note"]
    state = request_state(world)
    assert state["own"] == 1 and state["attempts"] == 1 and state["attempt_at"] is None


def test_a_clock_running_ahead_of_the_server_still_adopts_the_landed_post(world: World) -> None:
    # the local clock is 100 s ahead: the server stamped the comment 100 s BEFORE the attempt time, inside the 120 s
    no_push_stamp(world)
    world.route(TIMELINE, ok([committed(HEAD)]), ok([committed(HEAD), commented(at=iso(-100))]))
    world.route(f"POST {COMMENTS}", fail("gh: timeout"), ok({"id": 1000}))
    world.route(COMMENTS, NOMARK, NOMARK, NOMARK, ok([codex_comment(HEAD, "completed")]))
    assert world.run().returncode == 0
    assert world.posts() == 1 and world.file("summary")["codex_requested"] == 1


def test_a_request_older_than_the_attempt_less_the_skew_is_not_adopted(world: World) -> None:
    no_push_stamp(world)
    world.route(TIMELINE, ok([committed(HEAD)]), ok([committed(HEAD), commented(at=iso(-300))]))  # an old human one
    world.route(f"POST {COMMENTS}", fail("gh: timeout"), ok({"id": 1000}))
    world.route(COMMENTS, NOMARK, NOMARK, NOMARK, ok([codex_comment(HEAD, "completed")]))
    assert world.run().returncode == 0
    assert world.posts() == 2, "the old comment is not the errored POST's: the retry is sent"
    summary = world.file("summary")
    assert summary["codex_requested"] == 1 and "errored but landed" not in summary["codex_request_note"]


def test_an_errored_post_that_never_lands_is_tried_at_most_twice_across_runs(world: World) -> None:
    no_push_stamp(world)
    world.route(TIMELINE, ok([committed(HEAD)]))  # the POSTs never show up
    world.route(f"POST {COMMENTS}", fail("gh: timeout"))
    world.route(COMMENTS, NOMARK)
    assert world.run("--codex-stuck", "1.5", "--timeout", "20").returncode == 3
    assert world.posts() == 2, "two attempts in one run, however many polls followed"
    assert request_state(world)["attempts"] == 2
    assert world.run("--codex-stuck", "1", "--timeout", "20").returncode == 3  # a restart reads the saved count
    assert world.posts() == 2
    summary = world.file("summary")
    assert summary["codex_requested"] == 0 and "POST attempts already" in summary["codex_request_note"]


def test_the_attempt_is_on_record_before_the_post_is_sent(world: World) -> None:
    # a POST that hangs and is killed (a gh timeout, a crash) leaves the attempt counted in the state file
    no_push_stamp(world)
    world.route(TIMELINE, ok([committed(HEAD)]))
    world.route(f"POST {COMMENTS}", {"out": json.dumps({"id": 1}), "sleep": 8})
    world.route(COMMENTS, NOMARK)
    proc = subprocess.Popen(world.argv(), env=world.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 15
        while not list(world.state.glob("request-*.json")) and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        proc.kill()
        proc.wait(timeout=10)
    state = request_state(world)
    assert state["attempts"] == 1 and state["own"] == 0 and isinstance(state["attempt_at"], float)


def test_a_pending_attempt_alone_triggers_adoption_and_keeps_the_attempt_time_as_last_at(world: World) -> None:
    # own is 0 and a marker already exists (so `first()` is false and no re-request is due): only `pending` looks
    no_push_stamp(world)
    t = time.time() - 10
    world.state.mkdir(parents=True)
    (world.state / f"request-{REPO.replace('/', '__')}-{PR}-{HEAD}.json").write_text(
        json.dumps({"own": 0, "attempts": 1, "last_at": None, "attempt_at": t, "ids": []}))
    world.route(TIMELINE, ok([committed(HEAD), commented(at=iso(-5))]))
    world.route(COMMENTS, ok([codex_comment(HEAD, "running")]))  # a terminal marker would end the step early
    assert world.run("--codex-stuck", "1", "--timeout", "20").returncode == 3
    assert world.posts() == 0
    state = request_state(world)
    assert state["own"] == 1 and state["last_at"] == t and state["attempt_at"] is None and state["attempts"] == 1
    assert world.file("summary")["codex_requested"] == 1


# ---- adoption never counts the previous head's request, never twice, never a person's later one (PR 58 round 3) ----


def test_with_a_push_stamp_a_request_for_the_previous_head_inside_the_skew_is_never_adopted(world: World) -> None:
    # head pushed 60 s ago; a request made 90 s ago was for the previous head (before the push, inside the 120 s
    # skew window of the errored POST). It is not ours: the retry for the new head must still be sent.
    world.route(f"repos/{REPO}/commits/{HEAD}/check-suites", suites(iso(-60)))
    world.route(TIMELINE, ok([committed(HEAD), commented(at=iso(-90), cid=77)]))
    world.route(f"POST {COMMENTS}", fail("gh: timeout"), ok({"id": 1000}))
    world.route(COMMENTS, NOMARK, NOMARK, ok([codex_comment(HEAD, "completed")]))
    r = world.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert world.posts() == 2, "the old head's request was adopted as ours, so nothing was posted for the new head"
    summary = world.file("summary")
    assert summary["codex_requested"] == 1 and "errored but landed" not in summary["codex_request_note"]
    assert request_state(world)["adopted_ids"] == [1000]


def test_a_skipped_re_request_after_an_errored_post_says_so(world: World) -> None:
    no_push_stamp(world)
    world.route(TIMELINE, ok([committed(HEAD)]))  # the errored POST never lands
    world.route(f"POST {COMMENTS}", fail("gh: timeout"), ok({"id": 1000}))
    world.route(COMMENTS, NOMARK, NOMARK, ok([codex_comment(HEAD, "running")]))
    r = world.run("--rerequest-after", "0.5", "--codex-stuck", "3", "--timeout", "20")
    assert r.returncode == 3, r.stdout + r.stderr
    assert world.posts() == 2
    note = world.file("summary")["codex_request_note"]
    assert "re-request skipped: 2 POST attempts already (one errored)" in note


def test_the_first_request_is_not_adopted_a_second_time_by_the_re_request_attempt(world: World) -> None:
    # --rerequest-after below the 120 s skew: the first request lies inside the re-request attempt's window
    no_push_stamp(world)
    world.route(TIMELINE, ok([committed(HEAD)]), ok([committed(HEAD), commented(at=iso(0), cid=999)]))
    world.route(f"POST {COMMENTS}", ok({"id": 999}), fail("gh: timeout"))
    world.route(COMMENTS, NOMARK, ok([codex_comment(HEAD, "running")]))
    r = world.run("--rerequest-after", "0.5", "--codex-stuck", "3", "--timeout", "20")
    assert r.returncode == 3, r.stdout + r.stderr
    assert world.posts() == 2
    state = request_state(world)
    assert state["own"] == 1 and state["adopted_ids"] == [999] and state["attempt_at"] is not None
    assert world.file("summary")["codex_requested"] == 1


@pytest.mark.parametrize("stamped", [False, True], ids=["no-stamp", "push-stamp"])
def test_a_persons_request_made_after_the_attempts_were_spent_is_not_adopted(world: World, stamped: bool) -> None:
    if stamped:
        world.route(f"repos/{REPO}/commits/{HEAD}/check-suites", suites(iso(-3600)))
    else:
        no_push_stamp(world)
    human = commented(at=iso(400), cid=5)  # far later than any POST of ours could have been created
    world.route(TIMELINE, ok([committed(HEAD)]), ok([committed(HEAD)]), ok([committed(HEAD), human]))
    world.route(f"POST {COMMENTS}", fail("gh: timeout"))
    world.route(COMMENTS, NOMARK)
    r = world.run("--codex-stuck", "1.5", "--timeout", "20")
    assert r.returncode == 3, r.stdout + r.stderr
    assert world.posts() == 2
    summary = world.file("summary")
    assert summary["codex_requested"] == 0 and "errored but landed" not in summary["codex_request_note"]
    state = request_state(world)
    assert state["own"] == 0 and state["adopted_ids"] == [] and state["attempt_at"] is not None


def test_an_adopted_comment_id_is_saved_in_the_state_file(world: World) -> None:
    no_push_stamp(world)
    world.route(TIMELINE, ok([committed(HEAD)]), ok([committed(HEAD), commented(at=iso(0), cid=42)]))
    world.route(f"POST {COMMENTS}", fail("gh: timeout"))
    world.route(COMMENTS, NOMARK, NOMARK, ok([codex_comment(HEAD, "completed")]))
    assert world.run().returncode == 0
    assert world.posts() == 1
    state = request_state(world)
    assert state["own"] == 1 and state["adopted_ids"] == [42]
