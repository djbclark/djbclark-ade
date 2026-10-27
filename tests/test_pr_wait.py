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


_MODULE_CACHE = None


def load_module():
    """The pr-wait module, loaded ONCE.

    Cached because exec'ing the 1,400-line script on every call is pure overhead: the module is
    stateless at import (main() is guarded), so one instance is correct. The first version of the
    adversary tests called this per test, which added ~18s of interpreter work to the suite and made
    the wall-clock-sensitive Codex tests (`--codex-stuck 1.5`, `--rerequest-after 0.5`) miss their
    polling windows - a flake that looked like a code regression and was not.
    """
    global _MODULE_CACHE
    if _MODULE_CACHE is None:
        ld = SourceFileLoader("pr_wait_mod", str(PR_WAIT))
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("pr_wait_mod", ld))
        ld.exec_module(mod)
        _MODULE_CACHE = mod
    return _MODULE_CACHE


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


@pytest.mark.parametrize("code_status", ["completed", "failed"])
def test_terminal_code_is_not_requested_again_while_security_runs(world: World, code_status: str) -> None:
    world.route(TIMELINE, ok([committed(HEAD)]))
    world.route(COMMENTS, NOMARK, ok([codex_comment(HEAD, code_status, security=sec_review(status="running"))]))
    result = world.run("--rerequest-after", "0.1", "--codex-stuck", "0.8", "--timeout", "5")
    assert result.returncode == 3, result.stdout + result.stderr  # security still gates completion
    assert world.posts() == 1, "a pending security review must not restart a terminal code review"
    summary = world.file("summary")
    assert summary["codex"]["status"] == code_status and summary["security_status"] == "running"
    assert summary["merge_ready"] is False
    assert "manual request is sometimes stuck" not in summary["codex_request_note"]


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


# ---- adversary verdict MARKER in the PR body ------------------------------------------------
#
# Rewritten 2026-10-25 for the MARKER design (Dann 5's ruling after two adversary rounds). The first
# version parsed English; round 1 found six false APPROVEs and five false MISSES, round 2 found
# fourteen NEW false APPROVEs including a BLOCK silently deleted by a prose filter. The prose parser
# and its heuristics are DELETED, not patched: correctness there would mean "no sentence anyone could
# write defeats it", which is unbounded.
#
# Every test below is one of Dann 5's six required properties, plus the regressions the review found.

ADV_HEAD = "a" * 40
OTHER_HEAD = "b" * 40


def marker(verdict: str, head: str = ADV_HEAD) -> str:
    return f'<!-- adversary-verdict:v1 {{"verdict":"{verdict}","head":"{head}"}} -->'


def adv(body: str, head: str = ADV_HEAD) -> dict:
    return load_module().adversary_verdict(body, head)


def passes(body: str, head: str = ADV_HEAD) -> bool:
    """The same predicate assess() uses: matched AND not a BLOCK."""
    r = adv(body, head)
    return bool(r["matches_head"]) and not str(r["verdict"] or "").upper().startswith("BLOCK")


# --- property 1: the :v1 suffix is part of the match -----------------------------------------

def test_a_marker_without_the_v1_suffix_is_not_this_marker() -> None:
    # Rule 9 records a waiter whose regex lacked :v1 seeing no state on PR 12 and running 30 minutes.
    body = '<!-- adversary-verdict {"verdict":"APPROVE","head":"' + ADV_HEAD + '"} -->'
    assert not adv(body)["present"]


def test_the_canonical_marker_approves_this_head() -> None:
    assert passes(marker("APPROVE"))


def test_the_canonical_marker_blocks_this_head() -> None:
    r = adv(marker("BLOCK"))
    assert r["present"] and r["matches_head"] and r["verdict"] == "BLOCK"
    assert not passes(marker("BLOCK"))


# --- property 2: a missing or unknown verdict value fails closed ------------------------------

def test_an_unknown_verdict_value_is_malformed_not_a_default() -> None:
    body = '<!-- adversary-verdict:v1 {"verdict":"LGTM","head":"' + ADV_HEAD + '"} -->'
    r = adv(body)
    assert not r["present"] and r["malformed"]
    assert "APPROVE or BLOCK" in r["detail"]


def test_a_missing_verdict_field_is_malformed() -> None:
    body = '<!-- adversary-verdict:v1 {"head":"' + ADV_HEAD + '"} -->'
    r = adv(body)
    assert not r["present"] and r["malformed"]


# --- property 3: head must be 40 hex and must equal the PR head -------------------------------

def test_a_marker_for_another_head_is_not_a_pass() -> None:
    r = adv(marker("APPROVE", OTHER_HEAD))
    assert r["present"] and not r["matches_head"]
    assert "NOT this head" in r["detail"]


def test_a_short_head_is_malformed() -> None:
    r = adv(marker("APPROVE", ADV_HEAD[:7]))
    assert not r["present"] and r["malformed"]
    assert "40-hex" in r["detail"]


# --- property 4: a malformed marker is its own outcome ---------------------------------------

def test_a_marker_that_is_not_json_is_malformed() -> None:
    r = adv('<!-- adversary-verdict:v1 {"verdict":"APPROVE","head": -->')
    assert not r["present"] and r["malformed"]
    assert "malformed" in r["detail"]


# --- property 5: never fall back to prose ----------------------------------------------------

def test_prose_verdicts_with_no_marker_are_simply_missing() -> None:
    for body in (f"> **APPROVE, no findings** (head {ADV_HEAD})",
                 f"VERDICT: APPROVE {ADV_HEAD}",
                 f"Adversary: APPROVE (head {ADV_HEAD})",
                 f"**Codex verdict:** APPROVE at {ADV_HEAD}"):
        r = adv(body)
        assert not r["present"], body
        assert "marker" in r["detail"], body


def test_an_empty_body_reports_no_verdict() -> None:
    r = adv("")
    assert not r["present"] and r["detail"] == "no PR body"


# --- property 6: a BLOCK is never downgraded (the rule is asymmetric) -------------------------



def test_a_block_beats_an_approve_for_the_same_head() -> None:
    body = marker("APPROVE") + "\n\n" + marker("BLOCK")
    r = adv(body)
    assert r["verdict"] == "BLOCK" and r["conflict"] and r["matches_head"]
    assert not passes(body)
    assert "BOTH" in r["detail"]


def test_an_approve_for_another_head_does_not_block_the_block_for_this_head() -> None:
    body = marker("APPROVE", OTHER_HEAD) + "\n\n" + marker("BLOCK")
    assert not passes(body)


def test_a_malformed_marker_beside_a_good_one_still_reports_the_verdict() -> None:
    body = '<!-- adversary-verdict:v1 {broken -->' + "\n\n" + marker("APPROVE")
    r = adv(body)
    assert r["present"] and r["matches_head"] and r["malformed"]


def gate(body: str, required: bool = True, head: str = ADV_HEAD) -> tuple[bool, list[str]]:
    """Run the REAL gate (`assess`), not a copy of its predicate.

    The first version of these tests only called `adversary_verdict` / a copied predicate, so the
    gate itself (the blocker names, the report-only default, `malformed` handling) was untested —
    which is how a malformed BLOCK beside a valid APPROVE reached `merge_ready: true`.
    """
    mod = load_module()
    adv = mod.adversary_verdict(body, head)
    adv["required_by_label"] = False
    cr = {"has_any_findings": False, "has_unresolved_findings": False}
    counts = {"total": 1, "success": 1, "fail": 0, "pending": 0, "skipped": 0, "neutral": 0}
    review = {"for_head": [], "open": [], "finding_comments": {"code": 0, "security": 0}}
    r = mod.assess(False, "done", counts, "completed", cr, None, head, review, adv, required)
    return r["merge_ready"], r["adversary_warnings"]


def test_the_gate_blocks_a_malformed_marker_beside_a_valid_approve() -> None:
    # The A1 finding: `assess()` ignored `malformed`, so a typo in a BLOCK let the PR through.
    # A BLOCK whose head is a PREFIX of this head is not a typo any more: it is a BLOCK for this head
    # (adversary review of 4a56c01, B1) and is covered by its own test below.
    for broken in ('{"verdict":"BLOCKED","head":"' + ADV_HEAD + '"}',
                   '{"verdict":"BLOCK","head":"b50521a"}',
                   '{"verdict":"BLOCK","head":"' + ADV_HEAD + '"}'):  # the third is unclosed below
        body = marker("APPROVE") + "\n<!-- adversary-verdict:v1 " + broken
        ready, warnings = gate(body)
        assert not ready, body
        assert warnings == ["adversary-malformed"], warnings


def test_the_gate_reports_malformed_as_its_own_warning_not_as_missing() -> None:
    ready, warnings = gate('<!-- adversary-verdict:v1 {broken -->')
    assert not ready
    assert warnings == ["adversary-malformed"]


def test_the_gate_passes_a_good_approve() -> None:
    ready, warnings = gate(marker("APPROVE"))
    assert ready and warnings == []


def test_the_gate_blocks_a_block() -> None:
    ready, warnings = gate(marker("BLOCK"))
    assert not ready and warnings == ["adversary-stale-or-blocked"]


def test_the_gate_is_report_only_by_default() -> None:
    ready, warnings = gate(marker("BLOCK"), required=False)
    assert ready, "a missing/stale verdict must not block without opt-in"
    assert warnings == ["adversary-stale-or-blocked"], "but it must still be REPORTED"


def test_a_pr_documenting_the_format_does_not_trip_its_own_gate() -> None:
    # B1: PR 66's own body quotes the template, and reading it as a live marker made every PR that
    # documents the format unmergeable (malformed blocks by default).
    documented = (
        "The marker is:\n\n"
        "```\n"
        '<!-- adversary-verdict:v1 {"verdict":"APPROVE"|"BLOCK","head":"<40-hex>"} -->\n'
        "```\n\n"
        "and inline: `<!-- adversary-verdict:v1 {\"verdict\":\"APPROVE\",\"head\":\"<40-hex>\"} -->`\n"
    )
    r = adv(documented)
    assert not r["malformed"], r["detail"]
    assert not r["present"], "documentation is not a verdict"


def test_a_placeholder_head_alone_is_documentation_not_malformed() -> None:
    body = '<!-- adversary-verdict:v1 {"verdict":"APPROVE","head":"<40-hex>"} -->'
    r = adv(body)
    assert not r["malformed"] and not r["present"]
    assert "placeholder" in r["detail"]


def test_a_real_marker_inside_a_fence_is_ignored() -> None:
    # The review's argument: the body is author-controlled, so reading fences protects nothing and
    # only creates false blocks. A quoted marker is text, not a claim.
    assert not adv("```\n" + marker("APPROVE") + "\n```")["present"]


def test_a_real_marker_in_an_inline_code_span_is_ignored() -> None:
    assert not adv("the previous marker was `" + marker("APPROVE") + "`")["present"]


def test_a_genuinely_malformed_marker_still_fails_closed() -> None:
    r = adv('<!-- adversary-verdict:v1 {"verdict":"BLOCKED","head":"' + ADV_HEAD + '"} -->')
    assert r["malformed"] and not r["present"]


def test_a_shortened_sha_block_is_not_reclassified_as_documentation() -> None:
    # R3a: `"..." in sha` also matched `b50521af22b1…`, so a real BLOCK typed with an ellipsis was
    # silently turned into "no verdict" and stopped blocking. Only the TEMPLATE's placeholder skips.
    for head in ("b50521af22b1…", "<sha>", "b50521af22b1..."):
        body = '<!-- adversary-verdict:v1 {"verdict":"BLOCK","head":"' + head + '"} -->'
        r = adv(body)
        assert r["malformed"] and not r["present"], head


def test_a_shortened_sha_block_beside_a_valid_approve_still_blocks() -> None:
    body = (marker("APPROVE") + "\n"
            '<!-- adversary-verdict:v1 {"verdict":"BLOCK","head":"b50521af22b1…"} -->')
    ready, warnings = gate(body)
    assert not ready, "a BLOCK typed with an ellipsis must not pass"
    assert warnings == ["adversary-malformed"], warnings


def test_a_block_inside_a_broken_fence_still_blocks() -> None:
    # R3b: _strip_code can over-strip on an unterminated fence or a stray backtick pair, which used to
    # let a live BLOCK be hidden beside a live APPROVE. A BLOCK naming THIS head is now read from the
    # RAW body, so no strip bug can hide it.
    fence = chr(96) * 3
    for body in (marker("APPROVE") + "\n" + fence + "\n" + marker("BLOCK"),
                 marker("APPROVE") + "\n" + fence + "py" + fence + " is a span\n" + marker("BLOCK"),
                 marker("APPROVE") + "\n    " + fence + "\n" + marker("BLOCK")):
        r = adv(body)
        assert r["verdict"] == "BLOCK" and r["matches_head"], body
        assert not passes(body)


def test_a_block_in_a_clean_fence_is_still_read_from_the_raw_body() -> None:
    # The asymmetry: an APPROVE must be live, a BLOCK counts wherever it names this head.
    fence = chr(96) * 3
    body = marker("APPROVE") + "\n" + fence + "\n" + marker("BLOCK") + "\n" + fence
    assert adv(body)["verdict"] == "BLOCK"


# ---- adversary review of 4a56c01 (2026-10-27): B1-B6 ------------------------------------------
#
# The blocker: `_strip_code` toggled on every line whose `lstrip()` began with ``` or ~~~, so an ODD
# number of fence-looking lines left `in_fence` true to the end of the body and blanked a live marker.
# Paired with a raw-body rescue that took only a FULL 40-hex sha, that hid a BLOCK typed with a
# shortened sha beside a valid APPROVE: `merge_ready: true`, reproduced through `main()` with
# `--adversary-required` as well. Two independent fixes, because either alone leaves the class open:
# the raw-body pass takes a shortened sha by PREFIX (so no strip bug can lose a BLOCK), and
# `_strip_code` follows CommonMark (so the class stops arising). Pinned at each layer.

TICK = chr(96)
FENCE3 = TICK * 3


def strip(body: str) -> str:
    return load_module()._strip_code(body)


def test_strip_a_fence_opens_only_at_an_indent_of_three_spaces_or_less() -> None:
    # B1c: `line.lstrip()` treated a 4-space-indented fence line as a fence; CommonMark does not.
    for spaces in (0, 1, 2, 3):
        body = " " * spaces + FENCE3 + "\nSECRET\n" + " " * spaces + FENCE3
        assert "SECRET" not in strip(body), f"{spaces} spaces"
    for spaces in (4, 5):
        body = " " * spaces + FENCE3 + "\nSECRET\n"
        assert "SECRET" in strip(body), f"{spaces} spaces"
    assert "SECRET" in strip("\t" + FENCE3 + "\nSECRET\n"), "a tab expands to four spaces"


def test_strip_a_fence_remembers_its_character_and_length() -> None:
    four = TICK * 4
    # B1a: an inner 3-backtick line does not close a 4-backtick fence.
    assert "SECRET" not in strip(four + "md\n" + FENCE3 + "sh\nSECRET\n" + four + "\nAFTER\n")
    # B1b: a ``` line does not close a ~~~ fence.
    assert "SECRET" not in strip("~~~md\n" + FENCE3 + "\nSECRET\n~~~\nAFTER\n")
    # A LONGER closing fence does close it.
    assert "SECRET" not in strip(four + "\nSECRET\n" + TICK * 5 + "\nAFTER\n")
    assert "AFTER" in strip(four + "\nSECRET\n" + TICK * 5 + "\nAFTER\n")


def test_strip_a_fence_line_may_carry_an_info_string_but_a_closing_fence_must_be_bare() -> None:
    assert "SECRET" not in strip(FENCE3 + "sh\nSECRET\n" + FENCE3)
    body = FENCE3 + "md\n" + FENCE3 + " trailing\nSECRET\n" + FENCE3 + "\nAFTER\n"
    assert "SECRET" not in strip(body) and "AFTER" in strip(body)


def test_strip_an_unterminated_fence_runs_to_the_end_of_the_body() -> None:
    # B1e: CommonMark agrees (everything after a fence with no closer is code), which is exactly why
    # the raw-body pass, not the stripper, is the guarantee for a BLOCK.
    assert "SECRET" not in strip(FENCE3 + "md\nSECRET\n")


def test_strip_an_inline_span_does_not_cross_a_line() -> None:
    # B1d: the `` … `` regex used DOTALL, so a span crossed lines and swallowed the marker after it. A
    # span cannot cross the HTML block that `<!--` starts.
    body = "use ``x here\nand `` there\n" + marker("BLOCK")
    assert marker("BLOCK") in strip(body)


def test_head_matches_takes_a_full_sha_and_any_shortened_prefix_of_this_head() -> None:
    m = load_module()
    for sha in (ADV_HEAD, ADV_HEAD.upper(), ADV_HEAD[:7], ADV_HEAD[:12],
                ADV_HEAD[:12] + "\u2026", ADV_HEAD[:12] + "...", " " + ADV_HEAD[:12] + " "):
        assert m._head_matches(sha, ADV_HEAD), sha


def test_head_matches_rejects_another_commit_a_placeholder_and_a_non_prefix() -> None:
    m = load_module()
    other = "b" * 40
    for sha in (other, other[:12] + "\u2026", "<40-hex>", "<sha>", "\u2026", "...",
                ADV_HEAD[:6], ADV_HEAD + "0", None, 42, ""):
        assert not m._head_matches(sha, ADV_HEAD), sha


def test_b1_an_ordinary_markdown_structure_cannot_hide_a_shortened_block() -> None:
    # B1a-B1c and B1e, each reproduced at 4a56c01 as merge_ready: true. A BLOCK naming this head by a
    # SHORTENED sha must survive every one of them, because it is read from the raw body.
    short = marker("BLOCK", ADV_HEAD[:12] + "\u2026")
    shapes = {
        "indented fence line (B1c)": "    " + FENCE3 + "\n",
        "four-backtick fence, odd inner (B1a)": TICK * 4 + "md\n" + FENCE3 + "sh\n" + TICK * 4 + "\n",
        "tilde fence holding a backtick line (B1b)": "~~~md\n" + FENCE3 + "sh\n~~~\n",
        "unterminated fence (B1e)": FENCE3 + "md\n",
    }
    for label, structure in shapes.items():
        body = marker("APPROVE") + "\n\n" + structure + "\n" + short
        r = adv(body)
        assert r["verdict"] == "BLOCK" and r["matches_head"], (label, r)
        ready, warnings = gate(body)
        assert not ready and warnings == ["adversary-stale-or-blocked"], (label, warnings)
        # Report-only by default is the DESIGN, so the gate must still report the BLOCK.
        assert gate(body, required=False)[1] == ["adversary-stale-or-blocked"], label


def test_b1_a_shortened_block_is_read_as_a_block_not_as_malformed() -> None:
    short = marker("BLOCK", ADV_HEAD[:12] + "\u2026")
    alone = adv(short)
    assert alone["verdict"] == "BLOCK" and not alone["malformed"] and not alone["conflict"]
    assert "shortened sha" in alone["detail"] and "raw body" in alone["detail"]
    beside = adv(marker("APPROVE") + "\n\n" + short)
    assert beside["verdict"] == "BLOCK" and beside["conflict"]


def test_b1_the_two_shapes_that_stayed_malformed_still_block() -> None:
    # The two shapes the review listed that did NOT reach merge_ready at 4a56c01: the shortened BLOCK
    # survived long enough to be read as malformed, and malformed always blocks. Pin that too, now
    # that the stripper no longer over-strips them.
    short = marker("BLOCK", ADV_HEAD[:12] + "\u2026")
    for label, structure in {
        "stray double backtick (B1d)": "use ``x here\nand `` there\n\n",
        "balanced four-backtick fence": TICK * 4 + "md\n" + FENCE3 + "sh\necho\n" + FENCE3 + "\n" + TICK * 4 + "\n\n",
    }.items():
        body = marker("APPROVE") + "\n\n" + structure + short
        assert adv(body)["verdict"] == "BLOCK", label
        ready, warnings = gate(body)
        assert not ready, label


def test_a_near_miss_spelling_beside_a_valid_approve_is_malformed_not_ignored() -> None:
    # B2: a `:`-anchored start regex missed `adversary-verdict {...}` and `adversary_verdict:v1 ...`,
    # so a typo'd BLOCK beside a valid APPROVE read as approved and merge-ready.
    for start in ("adversary-verdict", "adversary_verdict:v1", "Adversary-Verdict:v1",
                  "adversary verdict:v1"):
        body = (marker("APPROVE") + "\n<!-- " + start
                + ' {"verdict":"BLOCK","head":"' + ADV_HEAD + '"} -->')
        assert adv(body)["malformed"], start
        ready, warnings = gate(body)
        assert not ready and warnings == ["adversary-malformed"], (start, warnings)


def test_a_near_miss_spelling_names_the_wrong_spelling_not_an_unclosed_comment() -> None:
    # B3: every unparseable start was reported as "no closing -->", which defeats "a typo reads as a
    # typo" - the two mistakes are different.
    wrong = adv('<!-- adversary-verdict:v2 {"verdict":"APPROVE","head":"' + ADV_HEAD + '"} -->')
    assert wrong["malformed"] and "no closing" not in wrong["detail"]
    assert "exact, lowercase" in wrong["detail"]
    unclosed = adv('<!-- adversary-verdict:v1 {"verdict":"APPROVE","head":"' + ADV_HEAD + '"')
    assert unclosed["malformed"] and "no closing" in unclosed["detail"]
    assert "exact, lowercase" not in unclosed["detail"]


# ---- the same properties through main(), against the fake gh -----------------------------------
#
# B6: these regressions each bit once and none had an end-to-end test. `serve()` replaces the happy
# fixture's `pulls/{pr}` document, which is where the body and the labels come from.

def serve(world: World, body: str, labels: list | None = None, n: int = 1) -> None:
    doc = ok({"head": {"sha": HEAD}, "body": body, "labels": labels or []})
    world.route(f"repos/{REPO}/pulls/{PR}", *([doc] * n))


def test_main_reads_an_approve_out_of_the_pr_body(world: World) -> None:
    serve(world, marker("APPROVE", HEAD))
    r = world.run("--head", HEAD)
    assert r.returncode == 0, r.stderr
    s = world.file("summary")
    assert s["adversary"]["verdict"] == "APPROVE" and s["adversary_warnings"] == []
    assert s["merge_ready"] is True and s["merge_blockers"] == []
    assert "adversary: APPROVE at this head" in r.stdout


def test_main_reports_a_missing_marker_without_blocking(world: World) -> None:
    serve(world, "nothing machine-readable here")
    r = world.run("--head", HEAD)
    s = world.file("summary")
    assert s["adversary_warnings"] == ["adversary-missing"] and s["merge_ready"] is True
    assert "adversary: missing" in r.stdout


def test_main_blocks_a_malformed_marker_without_being_asked(world: World) -> None:
    serve(world, '<!-- adversary-verdict:v1 {broken -->')
    r = world.run("--head", HEAD)
    s = world.file("summary")
    assert s["adversary_warnings"] == ["adversary-malformed"]
    assert s["merge_ready"] is False and s["merge_blockers"] == ["adversary-malformed"]
    # B4: the human line names the outcome instead of saying "missing".
    assert "adversary: malformed" in r.stdout


def test_main_reports_a_block_without_blocking_by_default(world: World) -> None:
    serve(world, marker("BLOCK", HEAD))
    r = world.run("--head", HEAD)
    s = world.file("summary")
    assert s["adversary_warnings"] == ["adversary-stale-or-blocked"]
    assert s["merge_ready"] is True, "a BLOCK is report-only unless the gate is opted in"
    assert "adversary: BLOCK at this head" in r.stdout


def test_main_blocks_a_block_when_opted_in(world: World) -> None:
    serve(world, marker("BLOCK", HEAD))
    world.run("--head", HEAD, "--adversary-required")
    s = world.file("summary")
    assert s["merge_ready"] is False and s["merge_blockers"] == ["adversary-stale-or-blocked"]


def test_main_names_an_other_head_verdict_in_the_human_line(world: World) -> None:
    serve(world, marker("APPROVE", OTHER_HEAD))
    r = world.run("--head", HEAD)
    s = world.file("summary")
    assert s["adversary_warnings"] == ["adversary-stale-or-blocked"] and s["merge_ready"] is True
    assert "adversary: other head" in r.stdout


def test_main_names_a_failed_body_fetch_and_blocks(world: World) -> None:
    # `pulls/{PR}` failing is not only "no verdict": with no document nothing about the PR can be
    # judged, so the run cannot be called ready either. The adversary warning must NAME the failure
    # and must block, rather than leave `adversary_warnings` empty (the F5 class).
    world.route(f"repos/{REPO}/pulls/{PR}", fail())
    r = world.run("--head", HEAD, "--timeout", "1")
    s = world.file("summary")
    assert s["adversary"]["fetch_failed"] is True
    assert s["adversary_warnings"] == ["adversary-fetch-failed"]
    assert s["merge_ready"] is False and "adversary-fetch-failed" in s["merge_blockers"]
    assert "adversary: FETCH FAILED" in r.stdout


def test_main_reports_the_verdict_on_a_timeout_not_only_on_done(world: World) -> None:
    # B4b: `collect_adversary` used to run only on the `done` path, so a timed-out run reported
    # `adversary: null` and `adversary_warnings: []` - an uncollected verdict read as no finding.
    serve(world, marker("BLOCK", HEAD), n=99)
    world.route(f"repos/{REPO}/commits/{HEAD}/check-runs",
                *([checks_page(run_obj("test", "in_progress", None))] * 99))
    r = world.run("--head", HEAD, "--timeout", "1")
    s = world.file("summary")
    assert s["result"] == "timeout"
    assert s["adversary"]["verdict"] == "BLOCK" and s["adversary"]["matches_head"]
    assert s["adversary_warnings"] == ["adversary-stale-or-blocked"]
    assert "adversary: BLOCK at this head" in r.stdout


def edited_body_run(world: World, *extra: str) -> dict:
    """One body edit mid-wait: the PR document says APPROVE, then BLOCK, and CI finishes on the next poll."""
    world.route(f"repos/{REPO}/commits/{HEAD}/check-runs",
                checks_page(run_obj("test", "in_progress", None)),
                checks_page(run_obj("test")),
                checks_page(run_obj("test")))
    world.route(f"repos/{REPO}/pulls/{PR}",
                ok({"head": {"sha": HEAD}, "body": marker("APPROVE", HEAD), "labels": []}),
                ok({"head": {"sha": HEAD}, "body": marker("BLOCK", HEAD), "labels": []}),
                ok({"head": {"sha": HEAD}, "body": marker("BLOCK", HEAD), "labels": []}))
    r = world.run(*extra)
    assert r.returncode == 0, r.stderr
    return world.file("summary")


def test_main_sees_a_body_edited_from_approve_to_block_mid_wait(world: World) -> None:
    assert edited_body_run(world)["adversary"]["verdict"] == "BLOCK"


def test_main_sees_that_edit_with_an_explicit_head_too(world: World) -> None:
    # `--head` used to leave `pr_doc` None, so the body was never read at all.
    assert edited_body_run(world, "--head", HEAD)["adversary"]["verdict"] == "BLOCK"


def test_main_honours_an_adversary_required_label_added_mid_wait(world: World) -> None:
    world.route(f"repos/{REPO}/commits/{HEAD}/check-runs",
                checks_page(run_obj("test", "in_progress", None)),
                checks_page(run_obj("test")),
                checks_page(run_obj("test")))
    world.route(f"repos/{REPO}/pulls/{PR}",
                ok({"head": {"sha": HEAD}, "body": "", "labels": []}),
                ok({"head": {"sha": HEAD}, "body": "",
                    "labels": [{"name": "adversary-required"}]}),
                ok({"head": {"sha": HEAD}, "body": "",
                    "labels": [{"name": "adversary-required"}]}))
    world.run("--head", HEAD)
    s = world.file("summary")
    assert s["adversary_required"] is True
    assert s["merge_ready"] is False and s["merge_blockers"] == ["adversary-missing"]


def test_main_fetches_the_pr_document_once_per_poll_plus_the_resolve(world: World) -> None:
    serve(world, marker("APPROVE", HEAD))
    world.run()
    assert world.calls(f"pulls/{PR}") == 2, "one resolve, one poll"


# ---- the bundled adversary review of 66/67: C1-C5 ---------------------------------------------
#
# Two of three re-reviewers found the SAME class again: the raw-body/strip interaction still failed
# open, and every finding below reached `merge_ready: true` from a body that merely QUOTED a marker
# or mistyped one. Each fix is pinned through `adv()` and, where the failure was reached through
# `assess()`, through the real gate: a property that holds only inside `adversary_verdict` is not the
# property the gate promises.

def test_c1_an_unclosed_marker_start_quoted_in_code_cannot_swallow_a_block() -> None:
    # MARKER_RE was non-greedy but unbounded, so the unclosed start below ran to the NEXT `-->` - the
    # fenced BLOCK's own - and the JSON parse failed, `continue` skipped it, `findall` resumed AFTER
    # the BLOCK, and the body read as a live APPROVE with the full sha. PR 67's subject is exactly
    # this kind of quoting, so the doc-writing PR could approve itself.
    body = (marker("APPROVE") + "\nEvery marker begins `<!-- adversary-verdict:v1`.\n"
            + FENCE3 + "\n" + marker("BLOCK") + "\n" + FENCE3 + "\n")
    r = adv(body)
    assert r["verdict"] == "BLOCK" and r["matches_head"] and r["conflict"], r
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-stale-or-blocked"], warnings


def test_c1_an_unclosed_start_in_plain_prose_blocks_and_is_reported_malformed() -> None:
    # The same shape without backticks: the BLOCK must survive, and the stray start is a typo that is
    # REPORTED as well - "a BLOCK beside a typo" is not the same body as "a BLOCK".
    body = (marker("APPROVE") + "\nEvery marker begins <!-- adversary-verdict:v1\n"
            + FENCE3 + "\n" + marker("BLOCK") + "\n" + FENCE3 + "\n")
    r = adv(body)
    assert r["verdict"] == "BLOCK" and r["matches_head"] and r["malformed"], r
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-malformed"], warnings


def test_c2_a_double_backtick_span_holding_one_backtick_is_still_code() -> None:
    # CommonMark 6.1: a span opens with n backticks and closes at the next run of EXACTLY n, so
    # ``literal `<marker>` `` is ONE span. The old pair of fixed regexes could not see it, matched from
    # the INNER backtick, and left the marker live: a quoted APPROVE read as a real one.
    body = "``literal `" + marker("APPROVE") + "``\n"
    assert not adv(body)["present"]
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-missing"], warnings
    # Outside the span the same marker is a verdict, so the fix is the span and not a blanket refusal.
    assert passes(body + "\n" + marker("APPROVE"))


def test_c2_the_strip_never_repairs_invalid_json_into_a_different_marker() -> None:
    # Spans used to be replaced with "" - DELETION concatenates the text on either side, so an author's
    # typo could be closed up into valid JSON that was never written. Every replacement is now a run of
    # spaces of the same width.
    broken = marker("APPROVE").replace('"} -->', '","unexpected"} -->')
    assert broken != marker("APPROVE")
    assert adv(broken)["malformed"], "the unquoted typo is a typo"
    quoted = "``literal `" + broken + "``"
    r = adv(quoted)
    assert not r["present"] and not r["malformed"], r


def test_c3_a_backtick_in_an_info_string_is_not_a_fence() -> None:
    # CommonMark 4.5: a backtick fence's info string may not contain a backtick. A line like ```a`b is
    # therefore INLINE CODE, not a fence - and treating it as one blanked the rest of the body, which
    # hid the malformed marker below and let the APPROVE read clean.
    body = (marker("APPROVE") + "\n" + FENCE3 + "a`b\n"
            + '<!-- adversary-verdict:v1 {"verdict":"APPROVE"}\n')
    r = adv(body)
    assert r["verdict"] == "APPROVE" and r["matches_head"] and r["malformed"], r
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-malformed"], warnings


def test_c4_a_full_sha_with_a_trailing_ellipsis_is_a_block_not_a_typo() -> None:
    # The property is documented as "full 40-hex, OR a 7+ hex prefix with or without a trailing …".
    # `[0-9a-f]{7,39}` could not match a full sha carrying an ellipsis, so a legitimate BLOCK read as
    # malformed: report-only by default, which means it silently stopped blocking in the opt-in case
    # that matters. At equal length `startswith` is equality, so the cap can go to 40 safely.
    for tail in ("\u2026", "..."):
        r = adv(marker("BLOCK", ADV_HEAD + tail))
        assert r["verdict"] == "BLOCK" and not r["malformed"] and r["matches_head"], (tail, r)
        ready, warnings = gate(marker("BLOCK", ADV_HEAD + tail))
        assert not ready and warnings == ["adversary-stale-or-blocked"], (tail, warnings)
    # Widening the cap must not make another commit match. An ellipsized sha of a DIFFERENT commit is
    # not a prefix of this head, so it does not match; it also is not 40-hex, so it stays a malformed
    # head rather than a stale verdict - the fail-closed direction, unchanged here.
    other = adv(marker("BLOCK", OTHER_HEAD + "\u2026"))
    assert not other["matches_head"] and other["malformed"], other


def test_c5_a_raw_body_block_cannot_report_a_clean_verdict_beside_a_live_typo() -> None:
    # The raw-body rescue returned `malformed: False` unconditionally, so a BLOCK beside a LIVE
    # malformed marker reported a clean block: the typo vanished from the summary and the body looked
    # like one assertable verdict. Validation now runs first and the rescue carries its result.
    body = ('<!-- adversary-verdict:v2 {"verdict":"APPROVE","head":"' + ADV_HEAD + '"} -->\n'
            + marker("BLOCK"))
    r = adv(body)
    assert r["verdict"] == "BLOCK" and r["matches_head"] and r["malformed"], r
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-malformed"], warnings


def test_c5_a_shortened_block_beside_a_live_typo_is_malformed_too() -> None:
    # The shortened-sha rescue is the one that always said "clean", so it laundered a BLOCK beside a
    # typo. The prefix BLOCK is NOT itself a problem - it is the shape the rescue exists for - but the
    # broken marker beside it still reports.
    short = marker("BLOCK", ADV_HEAD[:12] + "\u2026")
    body = '<!-- adversary-verdict:v1 {broken -->\n' + short
    r = adv(body)
    assert r["verdict"] == "BLOCK" and r["malformed"], r
    assert "shortened sha" in r["detail"] and "raw body" in r["detail"]
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-malformed"], warnings


def test_strip_code_masks_with_spaces_and_never_changes_a_line() -> None:
    # The invariant every fail-open shape above depends on: stripping may only REPLACE characters with
    # spaces. A line's length never changes, no line is added or removed, and every surviving non-space
    # character is the original one at the same position - so no marker can be repaired into another.
    body = "\n".join([
        "plain text  ",
        "\tindented with a tab ",
        FENCE3 + "sh",
        "in the fence ",
        FENCE3,
        "a `span` and ``a `span` with a tick`` end",
        "    " + FENCE3 + " (four spaces: indented code, not a fence)",
        FENCE3 + "a`b (not a fence: a backtick in the info string)",
        "",
    ])
    src = body.splitlines()
    dst = load_module()._strip_code(body).splitlines()
    assert len(dst) == len(src)
    for line_in, line_out in zip(src, dst):
        assert len(line_in) == len(line_out), (line_in, line_out)
        for a, b in zip(line_in, line_out):
            assert b == " " or b == a, (line_in, line_out)
    assert dst[0] == src[0] and dst[1] == src[1], "live lines are untouched"
    assert not dst[2].strip() and not dst[3].strip() and not dst[4].strip(), "the fence is masked"
    assert "span" not in dst[5] and dst[5].startswith("a ") and dst[5].endswith(" end")
    assert dst[6] == src[6] and dst[7] == src[7], "neither line is a fence"


# ---- the lead's re-review of 6083bcb: C1' (regression) and C2' ---------------------------------
#
# C1 was fixed by TEMPERING the marker regex so it could not cross another `<!--`. That closed the
# prose-swallow and opened the mirror: the SAME regex drove the raw-body BLOCK rescue, and extra JSON
# fields are accepted (no schema check), so a BLOCK whose `note` quoted the delimiter became invisible
# to the rescue. A fail-open in the one direction this gate promises never to fail open. The boundary
# is now a JSON-aware scanner (`_marker_spans`), shared by the live path and the rescue, and BOTH
# directions are pinned here: the tempered capture survives as the FALLBACK, for starts whose JSON
# does not balance.

def _marker_with_note(verdict: str, note: str, head: str = ADV_HEAD) -> str:
    """A valid marker carrying an EXTRA field - which the gate accepts, by design."""
    return (f'<!-- adversary-verdict:v1 {{"verdict":"{verdict}","head":"{head}",'
            f'"note":"{note}"}} -->')


def test_c1_prime_a_fenced_block_that_quotes_the_delimiter_is_not_hidden() -> None:
    # At 6083bcb this body read as a clean APPROVE (parent 838413b read BLOCK): the fenced BLOCK's
    # `note` holds `<!--`, the tempered group stopped there, the JSON failed to parse, and the rescue
    # that exists to read a fenced BLOCK skipped it.
    body = (marker("APPROVE") + "\n" + FENCE3 + "\n"
            + _marker_with_note("BLOCK", "literal <!-- x") + "\n" + FENCE3 + "\n")
    r = adv(body)
    assert r["verdict"] == "BLOCK" and r["matches_head"] and r["conflict"], r
    assert not r["malformed"], r
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-stale-or-blocked"], warnings


def test_c1_prime_a_live_block_that_quotes_the_delimiter_is_a_block_not_a_typo() -> None:
    # Same body without the fence: the marker is LIVE, so the tempered group's truncation made valid
    # JSON look malformed (6083bcb: APPROVE + malformed). A delimiter inside a JSON string is CONTENT.
    body = marker("APPROVE") + "\n" + _marker_with_note("BLOCK", "literal <!-- x")
    r = adv(body)
    assert r["verdict"] == "BLOCK" and r["matches_head"] and r["conflict"], r
    assert not r["malformed"], r
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-stale-or-blocked"], warnings


def test_c1_prime_a_near_miss_start_that_quotes_the_delimiter_never_becomes_a_marker() -> None:
    # The scanner must not widen what COUNTS as a marker. A near-miss spelling is a start for
    # `_classify_starts` only, however valid its JSON, so it is reported as a typo and never parsed
    # into a verdict - a typo may not block, and it may not approve either.
    body = ('<!-- adversary-verdict {"verdict":"BLOCK","head":"' + ADV_HEAD
            + '","note":"literal <!-- x"} -->\n' + marker("APPROVE"))
    r = adv(body)
    assert r["verdict"] == "APPROVE" and r["matches_head"] and r["malformed"], r
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-malformed"], warnings


def test_c2_prime_masking_may_not_repair_json_at_a_structural_boundary() -> None:
    # PRE-EXISTING (the lead found it at both revisions), and still wrong: `_strip_code` replaces code
    # with SPACES, so a span sitting where JSON expects whitespace left the punctuation intact -
    # {"verdict":"APPROVE", `junk` "head":"…"} parsed as valid JSON nobody wrote, and read clean-
    # APPROVE. The live slice of the RAW body at the same offsets says what was actually written, so a
    # marker whose JSON differs between the two is `malformed`, never approved.
    body = ('<!-- adversary-verdict:v1 {"verdict":"APPROVE", `junk` "head":"' + ADV_HEAD + '"} -->')
    r = adv(body)
    assert not r["present"] and r["malformed"], r
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-malformed"], warnings
    # Outside code the same JSON is a real verdict: the fix is the repair, not a blanket refusal.
    assert passes(body.replace("`junk`", ""))


def test_strip_code_preserves_every_offset_including_crlf_and_a_trailing_newline() -> None:
    # The C2' check compares slices by INDEX, so `_strip_code` may not change the length by one byte.
    # `splitlines()` dropped a trailing newline and rewrote `\r\n` as `\n`, shifting every offset
    # after the first such line - which turned a clean APPROVE on a CRLF body into `malformed`.
    strip = load_module()._strip_code
    for body in ("text `span` and " + marker("APPROVE") + "\n",
                 "text `span`\r\n\r\n" + marker("APPROVE") + "\r\n",
                 "trailing\n\n",
                 ""):
        out = strip(body)
        assert len(out) == len(body), (body, out)
        # Same line structure: every line terminator survives byte for byte.
        assert out[len(out.rstrip("\r\n")):] == body[len(body.rstrip("\r\n")):], (body, out)
    crlf = "Intro\r\n\r\n" + marker("APPROVE") + "\r\n"
    assert strip(crlf).endswith("\r\n") and len(strip(crlf)) == len(crlf)
    r = adv(crlf)
    assert r["verdict"] == "APPROVE" and r["matches_head"] and not r["malformed"], r


def test_c1_prime_a_note_that_documents_the_marker_is_content_not_a_second_start() -> None:
    # The JSON-aware scanner accepts the WHOLE marker, so a `note` quoting the format is inside that
    # marker's JSON. Counting the quoted start as a second start made a CORRECT body `malformed`, which
    # is the same fail-closed-but-wrong direction as C1 in the other guise. `_classify_starts` skips a
    # start inside an accepted marker, and the scanner resumes after that marker's `-->`.
    quoted_start = 'see <!-- adversary-verdict:v1 in the docs'
    r = adv(_marker_with_note("APPROVE", quoted_start))
    assert r["verdict"] == "APPROVE" and r["matches_head"], r
    assert not r["malformed"], r
    # The same shape with a WHOLE marker nested in the note, escaped as JSON requires.
    nested = json.dumps({"verdict": "APPROVE", "head": ADV_HEAD})
    note = "like <!-- adversary-verdict:v1 " + nested + " --> ok"
    body = ('<!-- adversary-verdict:v1 '
            + json.dumps({"verdict": "APPROVE", "head": ADV_HEAD, "note": note})
            + ' -->')
    r = adv(body)
    assert r["verdict"] == "APPROVE" and r["matches_head"] and not r["malformed"], r
    # And two REAL markers are still two: the skip must not spill past the accepted marker.
    assert adv(body + "\n" + marker("BLOCK"))["verdict"] == "BLOCK"
