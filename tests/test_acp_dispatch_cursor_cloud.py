#!/usr/bin/env python3
"""acp-dispatch cursor-cloud: a slice sent to Cursor Cloud Agents (2026-10-20), and the
route_agent registration. No network: bin/cursor-cloud is replaced by a fake on CURSOR_CLOUD_BIN."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any, override
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import route_agent as r
from test_acp_dispatch import Base, run

# fake cursor-cloud: records every call's argv; `run` serves $CC/run-N.json (the last one repeats),
# `usage` serves $CC/usage.json, `launch` prints $CC/launch.json
FAKE_CC = textwrap.dedent("""\
    #!/bin/bash
    echo "$@" >> "$CC/calls"
    case "$1" in
      launch) cat "$CC/launch.json";;
      run)
        n=$(grep -c '^run' "$CC/calls")
        f="$CC/run-$n.json"; [ -f "$f" ] || f=$(ls "$CC"/run-*.json | sort -V | tail -1)
        cat "$f";;
      usage) [ -f "$CC/usage.json" ] && cat "$CC/usage.json" || { echo "no usage" >&2; exit 1; };;
      *) echo "unexpected $1" >&2; exit 1;;
    esac
""")


# fake git on PATH: ls-remote, fetch and `log ... FETCH_HEAD` are served from $CC (no network), the
# rest goes to the real git
FAKE_GIT = textwrap.dedent("""\
    #!/bin/bash
    for x in "$@"; do
      case "$x" in
        ls-remote)
          echo ls-remote >> "$CC/git-calls"; [ -f "$CC/ls-remote.fail" ] && exit 2
          n=$(grep -c '^ls-remote' "$CC/git-calls"); f="$CC/ls-remote-$n.txt"; [ -f "$f" ] || f="$CC/ls-remote.txt"
          cat "$f"; exit 0;;
        fetch) echo "fetch $*" >> "$CC/git-calls"; [ -f "$CC/fetch.fail" ] && exit 1; exit 0;;
        FETCH_HEAD) cat "$CC/fetch-ct"; exit 0;;
      esac
    done
    exec /usr/bin/git "$@"
""")


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


class CloudBase(Base):
    cc: Path = Path()

    @override
    def setUp(self) -> None:
        super().setUp()
        self.cc = self.tmp / "cc"
        self.cc.mkdir()
        fake = self.tmp / "cursor-cloud"
        fake.write_text(FAKE_CC)
        fake.chmod(0o755)
        self.fake_cc = fake
        (self.cc / "launch.json").write_text(json.dumps({"agent": {"id": "bc-test1"}}))
        # real shape (2026-10-20, /tmp/cursor-issue6-usage.json)
        (self.cc / "usage.json").write_text(json.dumps({
            "totalUsage": {"totalTokens": 772782},
            "cost": {"rawCostCents": 104.49472, "chargedCents": 104.49472}}))
        self.fakebin = self.tmp / "fakebin"
        self.fakebin.mkdir()
        fg = self.fakebin / "git"
        fg.write_text(FAKE_GIT)
        fg.chmod(0o755)
        git(self.repo.parent, "init", "-q", str(self.repo))
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "t")
        (self.repo / "README").write_text("x\n")
        git(self.repo, "add", "README")
        git(self.repo, "commit", "-q", "-m", "i")
        git(self.repo, "checkout", "-q", "-b", "feat/slice-base")
        self.set_origin("git@github.com:djbclark/some-repo.git")
        self.head = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True,
                                   text=True, check=True).stdout.strip()
        self.ls_remote(f"{self.head}\trefs/heads/feat/slice-base\n")

    def ls_remote(self, text: str) -> None:
        (self.cc / "ls-remote.txt").write_text(text)

    def set_origin(self, url: str) -> None:
        subprocess.run(["git", "-C", str(self.repo), "remote", "remove", "origin"], check=False, capture_output=True)
        git(self.repo, "remote", "add", "origin", url)

    def run_json(self, name: str, status: str, **extra: Any) -> None:
        (self.cc / name).write_text(json.dumps({"status": status, **extra}))

    def calls(self) -> list[list[str]]:
        f = self.cc / "calls"
        return [ln.split() for ln in f.read_text().splitlines()] if f.exists() else []

    def cloud(self, *extra: str, model: str = "claude-sonnet-5-5", name: str = "s1",
              env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        e = self.base_env("writes", **{"CC": str(self.cc), "CURSOR_CLOUD_BIN": str(self.fake_cc),
                                       "ACP_DISPATCH_CLOUD_POLL": "0",
                                       "PATH": f"{self.fakebin}:{os.environ['PATH']}", **(env or {})})
        kind = [] if "--kind" in extra else ["--kind", "code"]
        # no --acp-run, no model check: a cloud slice never touches acp-run
        return run(["cursor-cloud", "--model", model, "--name", name, "-p", "do the thing",
                    "-C", str(self.repo), "--out", str(self.out), *kind, *extra], env=e)

    def report(self, name: str = "s1") -> str:
        return (self.out / f"{name}-report.md").read_text()


class TestLaunch(CloudBase):
    def test_launch_argv_prompt_file_and_record(self):
        self.run_json("run-1.json", "FINISHED", result="all done", git={"branches": ["cursor/slice-1"]})
        res = self.cloud()
        self.assertEqual(res.returncode, 0, res.stderr)
        launch = self.calls()[0]
        self.assertEqual(launch[0], "launch")
        flag = dict(zip(launch[1::2], launch[2::2], strict=False))
        self.assertEqual(flag["--repo"], "https://github.com/djbclark/some-repo")
        self.assertEqual(flag["--ref"], "feat/slice-base")
        self.assertEqual(flag["--model"], "claude-sonnet-5-5")
        self.assertEqual(flag["--name"], "s1")
        self.assertEqual(Path(flag["--prompt-file"]).resolve(), (self.out / "s1-brief.md").resolve())
        self.assertNotIn("autoCreatePR", " ".join(launch))
        self.assertNotIn("--work-on-branch", launch)
        brief = (self.out / "s1-brief.md").read_text()
        self.assertTrue(brief.startswith("do the thing"))
        self.assertIn("Delivery contract", brief)        # the shared footer
        self.assertIn("Cursor's cloud", brief)           # the cloud note
        rec = self.record()
        self.assertEqual(rec["cloud_provider"], "cursor")
        self.assertEqual(rec["cloud_agent_id"], "bc-test1")
        self.assertEqual(rec["cloud_repo"], "https://github.com/djbclark/some-repo")
        self.assertEqual(rec["cloud_ref"], "feat/slice-base")
        self.assertEqual(rec["agent"], "cursor-cloud")
        self.assertEqual(rec["service"], "cursor-cloud")
        self.assertEqual(rec["kind"], "code")

    def test_repo_url_normalisation(self):
        cases = {
            "git@github.com:o/r.git": "https://github.com/o/r",
            "ssh://git@github.com/o/r.git": "https://github.com/o/r",
            "https://github.com/o/r.git": "https://github.com/o/r",
            "https://github.com/o/r": "https://github.com/o/r",
            "https://x-access-token:tok@github.com/o/r.git": "https://github.com/o/r",
        }
        for origin, want in cases.items():
            with self.subTest(origin=origin):
                self.set_origin(origin)
                res = self.cloud("--dry-run", "--json")
                self.assertEqual(res.returncode, 0, res.stderr)
                self.assertEqual(json.loads(res.stdout)["cloud_repo"], want)
        self.assertEqual(self.calls(), [])               # dry-run launches nothing

    def test_non_github_origin_refused(self):
        self.set_origin("https://forgejo.mit.edu/djbclark/x.git")
        res = self.cloud()
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertIn("not a github.com repository", res.stderr)
        self.assertEqual(self.calls(), [])

    def test_detached_head_refused(self):
        sha = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True,
                             text=True, check=True).stdout.strip()
        git(self.repo, "checkout", "-q", "--detach", sha)
        res = self.cloud()
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertIn("detached HEAD", res.stderr)

    def test_launch_without_agent_id_fails_and_writes_no_record(self):
        (self.cc / "launch.json").write_text("{}")
        res = self.cloud()
        self.assertEqual(res.returncode, 1, res.stderr)
        # the record exists before the launch (a timed-out launch may still have made an agent)
        rec = self.record()
        self.assertIsNone(rec["cloud_agent_id"])
        self.assertEqual(rec["status"], "no-report")
        self.assertIn("cursor-cloud list", self.report())

    def test_no_local_gates_and_no_acp_run(self):
        # an in-flight cap of 0 refuses every local slice; a cloud slice runs off the Mac
        self.run_json("run-1.json", "FINISHED", result="ok")
        res = self.cloud(env={"ACP_DISPATCH_INFLIGHT": "cursor-cloud=0",
                              "PATH": f"{self.fakebin}:/usr/bin:/bin"})
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIsNone(self.record().get("gate"))

    def test_frontier_and_judgment_refused(self):
        for kind in ("frontier", "judgment"):
            with self.subTest(kind=kind):
                res = self.cloud("--kind", kind, name=f"x-{kind}")
                self.assertEqual(res.returncode, 2, res.stderr)
                self.assertEqual(self.calls(), [])

    def test_model_required(self):
        e = self.base_env("writes", CC=str(self.cc), CURSOR_CLOUD_BIN=str(self.fake_cc))
        res = run(["cursor-cloud", "--name", "s1", "-p", "x", "-C", str(self.repo), "--out", str(self.out),
                   "--kind", "code"], env=e)
        self.assertEqual(res.returncode, 2, res.stderr)


class TestOutcome(CloudBase):
    def test_finished_report_exit_zero_and_check(self):
        self.run_json("run-1.json", "RUNNING")
        self.run_json("run-2.json", "RUNNING")
        self.run_json("run-3.json", "FINISHED", result="Built the thing.\nTests pass.",
                      git={"branches": [{"name": "cursor/a"}, "cursor/b"]})
        res = self.cloud()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(len([c for c in self.calls() if c[0] == "run"]), 3)
        text = self.report()
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("STATUS: cursor cloud run FINISHED"))
        self.assertIn("Built the thing.", text)
        self.assertIn("BRANCH: cursor/a", lines)
        self.assertIn("BRANCH: cursor/b", lines)
        self.assertIn("COST: $1.04 (104.49 cents charged; 772782 tokens)", lines)
        self.assertIn("BRANCH-SOURCE: api", lines)
        self.assertEqual(lines[-1], "DONE")
        self.assertTrue((self.out / "s1-report.md.done").exists())
        rec = self.record()
        self.assertEqual(rec["exit"], 0)
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["cloud_status"], "FINISHED")
        chk = run(["check", str(self.out / "jobs" / "s1.json")])
        self.assertEqual(chk.returncode, 0, chk.stdout + chk.stderr)
        self.assertTrue(chk.stdout.startswith("done"))
        wait = run(["wait", str(self.out / "jobs" / "s1.json")])
        self.assertEqual(wait.returncode, 0, wait.stderr)

    def test_error_report_exit_one_no_done_line(self):
        self.run_json("run-1.json", "ERROR", result="the build broke")
        res = self.cloud()
        self.assertEqual(res.returncode, 3, res.stderr)     # dispatch exit: no-report
        text = self.report()
        self.assertIn("the build broke", text)
        self.assertNotIn("\nDONE", text)
        self.assertTrue(text.splitlines()[-1].startswith("NO-REPORT: cursor-cloud run error"))
        rec = self.record()
        self.assertEqual(rec["exit"], 1)                   # the runner's exit code
        self.assertEqual(rec["status"], "no-report")
        self.assertTrue((self.out / "s1-report.md.done").exists())
        chk = run(["check", str(self.out / "jobs" / "s1.json")])
        self.assertEqual(chk.returncode, 3, chk.stdout)

    def test_cancelled_and_expired_exit_one(self):
        for st in ("CANCELLED", "EXPIRED"):
            with self.subTest(status=st):
                self.run_json("run-1.json", st, result="")
                res = self.cloud(name=f"s-{st.lower()}")
                self.assertNotEqual(res.returncode, 0)
                self.assertEqual(self.record(f"s-{st.lower()}")["exit"], 1)

    def test_usage_failure_still_writes_report(self):
        (self.cc / "usage.json").unlink()
        self.run_json("run-1.json", "FINISHED", result="ok")
        res = self.cloud()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("COST: unavailable", self.report())

    def test_repeated_poll_failures_end_in_error(self):
        # `run` prints no JSON: the poller gives up after CLOUD_MAX_POLL_FAILURES
        (self.cc / "run-1.json").write_text("not json")
        res = self.cloud()
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertIn("polling failed", self.report())
        self.assertEqual(self.record()["exit"], 1)

    def test_detached_submits_the_ordinary_runner(self):
        self.run_json("run-1.json", "FINISHED", result="ok")
        res = self.cloud("--detach", "--no-wait")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(any(c.startswith("submit") for c in self.launchctl()), self.launchctl())
        rec = self.record()
        self.assertTrue((self.out / "s1-run.sh").exists())
        self.assertIn("execute", rec["cmd"])
        self.assertEqual(rec["cloud_agent_id"], "bc-test1")
        # what the launchd job runs: `execute RECORD` polls, then finalize
        ex = run(["execute", str(self.out / "jobs" / "s1.json")],
                 env=self.base_env("writes", CC=str(self.cc), CURSOR_CLOUD_BIN=str(self.fake_cc),
                                   ACP_DISPATCH_CLOUD_POLL="0", PATH=f"{self.fakebin}:{os.environ['PATH']}"))
        self.assertEqual(ex.returncode, 0, ex.stderr)
        self.assertEqual(self.report().splitlines()[-1], "DONE")


REAL_RESULT = ("Documented `bin/cursor-cloud` on `cursor/document-cursor-cloud-8526` (from latest `master`) "
               "and pushed `0fb87bc`. No pull request.")
REAL_BRANCHES = {"branches": [{"repoUrl": "github.com/djbclark/djbclark-ade"}]}   # no branch name


class TestAdversaryFindings(CloudBase):
    def fenv(self, **extra: str) -> dict[str, str]:
        return self.base_env("writes", **{"CC": str(self.cc), "CURSOR_CLOUD_BIN": str(self.fake_cc),
                                          "ACP_DISPATCH_CLOUD_POLL": "0",
                                          "PATH": f"{self.fakebin}:{os.environ['PATH']}", **extra})

    # 1. BLOCKED
    def test_blocked_result_checks_as_blocked_exit_4(self):
        self.run_json("run-1.json", "FINISHED", result="Started on it.\nBLOCKED: which repo do you mean?\nmore",
                      git=REAL_BRANCHES)
        res = self.cloud()
        self.assertEqual(res.returncode, 4, res.stdout + res.stderr)
        self.assertEqual(self.report().splitlines()[0], "BLOCKED: which repo do you mean?")
        chk = run(["check", str(self.out / "jobs" / "s1.json")])
        self.assertEqual(chk.returncode, 4, chk.stdout)
        self.assertTrue(chk.stdout.startswith("blocked"))

    # 2. branch name
    def test_branch_from_result_text_when_api_has_only_repo_url(self):
        self.run_json("run-1.json", "FINISHED", result=REAL_RESULT, git=REAL_BRANCHES)
        self.assertEqual(self.cloud().returncode, 0)
        lines = self.report().splitlines()
        self.assertIn("BRANCH: cursor/document-cursor-cloud-8526", lines)
        self.assertTrue(any(ln.startswith("BRANCH-SOURCE: result text") for ln in lines))

    def test_branch_from_ls_remote_when_result_names_none(self):
        self.ls_remote(f"{self.head}\trefs/heads/feat/slice-base\nabc\trefs/heads/cursor/old-one\n")
        (self.cc / "ls-remote-2.txt").write_text(
            f"{self.head}\trefs/heads/feat/slice-base\nabc\trefs/heads/cursor/old-one\n"
            "def\trefs/heads/cursor/new-one\n")
        (self.cc / "fetch-ct").write_text("99999999999\n")
        self.run_json("run-1.json", "FINISHED", result="Done, pushed.", git=REAL_BRANCHES)
        self.assertEqual(self.cloud().returncode, 0)
        lines = self.report().splitlines()
        self.assertIn("BRANCH: cursor/new-one", lines)
        self.assertTrue(any(ln.startswith("BRANCH-SOURCE: ls-remote") for ln in lines))
        self.assertNotIn("BRANCH: cursor/old-one", lines)

    def test_ls_remote_head_older_than_the_launch_is_not_picked(self):
        (self.cc / "ls-remote-2.txt").write_text(
            f"{self.head}\trefs/heads/feat/slice-base\ndef\trefs/heads/cursor/stale\n")
        (self.cc / "fetch-ct").write_text("1000\n")
        self.run_json("run-1.json", "FINISHED", result="Done.", git=REAL_BRANCHES)
        self.assertEqual(self.cloud().returncode, 0)
        lines = self.report().splitlines()
        self.assertTrue(any(ln.startswith("BRANCH: unknown (check git ls-remote") for ln in lines), lines)

    def test_branch_line_is_never_missing(self):
        self.run_json("run-1.json", "FINISHED", result="Done.", git=REAL_BRANCHES)
        self.assertEqual(self.cloud().returncode, 0)
        self.assertTrue(any(ln.startswith("BRANCH: unknown") for ln in self.report().splitlines()))

    # 3. dead poller
    def detached_record(self) -> Path:
        res = self.cloud("--detach", "--no-wait")
        self.assertEqual(res.returncode, 0, res.stderr)
        return self.out / "jobs" / "s1.json"

    def kill_poller(self, rec_path: Path) -> None:
        rec = json.loads(rec_path.read_text())
        rec.update(pid=999999, pid_start=None)
        rec_path.write_text(json.dumps(rec))

    def repoll_submits(self) -> int:
        return len([c for c in self.launchctl() if "repoll" in c])

    def test_reap_with_run_still_running_repolls_and_stays_running(self):
        self.run_json("run-1.json", "RUNNING")
        rec_path = self.detached_record()
        self.kill_poller(rec_path)
        res = run(["reap", str(rec_path)], env=self.fenv())
        self.assertEqual(res.returncode, 0, res.stderr)
        rec = json.loads(rec_path.read_text())
        self.assertIsNone(rec["finished"])
        self.assertEqual(rec["status"], "running")
        self.assertEqual(rec["repolls"], 1)
        self.assertEqual(self.repoll_submits(), 1)
        self.assertTrue((self.out / "s1-repoll1-run.sh").exists())
        self.assertFalse((self.out / "s1-report.md.done").exists())
        # a second sweep right after must not submit another poller
        run(["reap", str(rec_path)], env=self.fenv())
        chk = run(["check", str(rec_path)], env=self.fenv())
        self.assertEqual(self.repoll_submits(), 1)
        self.assertFalse(chk.stdout.startswith("no-report"), chk.stdout)

    def test_reap_with_run_finished_finalizes_from_real_status(self):
        self.run_json("run-1.json", "RUNNING")
        rec_path = self.detached_record()
        self.kill_poller(rec_path)
        self.run_json("run-1.json", "FINISHED", result=REAL_RESULT, git=REAL_BRANCHES)
        res = run(["reap", str(rec_path)], env=self.fenv())
        self.assertEqual(res.returncode, 0, res.stderr)
        rec = json.loads(rec_path.read_text())
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["exit"], 0)
        self.assertTrue((self.out / "s1-report.md.done").exists())
        self.assertIn("BRANCH: cursor/document-cursor-cloud-8526", self.report().splitlines())
        self.assertEqual(self.repoll_submits(), 0)

    def test_check_on_dead_poller_with_finished_run_says_done(self):
        self.run_json("run-1.json", "RUNNING")
        rec_path = self.detached_record()
        self.kill_poller(rec_path)
        self.run_json("run-1.json", "FINISHED", result="ok", git=REAL_BRANCHES)
        chk = run(["check", str(rec_path)], env=self.fenv())
        self.assertEqual(chk.returncode, 0, chk.stdout + chk.stderr)
        self.assertTrue(chk.stdout.startswith("done"))

    def test_sigterm_report_names_agent_and_resume_repolls(self):
        import time
        self.run_json("run-1.json", "RUNNING")
        rec_path = self.detached_record()
        script = Path(__file__).resolve().parent.parent / "bin" / "acp-dispatch"
        proc = subprocess.Popen([sys.executable, str(script), "execute", str(rec_path)],
                                env={**os.environ, **self.fenv(ACP_DISPATCH_CLOUD_POLL="0.2")},
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        for _ in range(100):
            if json.loads(rec_path.read_text()).get("pid") == proc.pid:
                break
            time.sleep(0.1)
        time.sleep(0.5)
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(proc.wait(timeout=30), 128 + signal.SIGTERM)
        text = self.report()
        self.assertIn("bc-test1", text)
        self.assertIn("may still be running", text)
        self.assertIn("acp-dispatch resume", text)
        # resume with the run still active: a new poller, record stays running
        res = run(["resume", str(rec_path)], env=self.fenv())
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.repoll_submits(), 1)
        self.assertIsNone(json.loads(rec_path.read_text())["finished"])

    # lows
    def test_cost_line_parses_real_usage_and_falls_back(self):
        self.assertEqual(self.run_cost({"cost": {"chargedCents": 250.0}}), "COST: $2.50 (250.00 cents charged)")
        self.assertTrue(self.run_cost({"other": 1}).startswith("COST: usage {"))

    def run_cost(self, usage: dict) -> str:
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader(
            "acpd_cc", str(Path(__file__).resolve().parent.parent / "bin" / "acp-dispatch"))
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(mod)
        return mod.cloud_cost_line(usage)

    def test_run_id_from_launch_is_pinned(self):
        (self.cc / "launch.json").write_text(json.dumps({"agent": {"id": "bc-test1", "latestRunId": "run-0"},
                                                         "run": {"id": "run-9"}}))
        self.run_json("run-1.json", "FINISHED", result="ok")
        self.assertEqual(self.cloud().returncode, 0)
        self.assertEqual(self.record()["cloud_run_id"], "run-9")
        self.assertIn(["run", "bc-test1", "run-9"], self.calls())

    def test_unknown_status_ends_as_error_and_says_agent_may_run(self):
        self.run_json("run-1.json", "SOMETHING_NEW")
        res = self.cloud()
        self.assertEqual(res.returncode, 3, res.stderr)
        text = self.report()
        self.assertIn("unexpected run status 'SOMETHING_NEW'", text)
        self.assertIn("may still be running in Cursor", text)

    def test_unpushed_branch_refused_unless_allowed(self):
        self.ls_remote("deadbeef\trefs/heads/feat/slice-base\n")
        res = self.cloud()
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertIn("push it first", res.stderr)
        self.assertEqual(self.calls(), [])
        self.run_json("run-1.json", "FINISHED", result="ok")
        self.assertEqual(self.cloud("--allow-unpushed", name="s2").returncode, 0)

    def test_ls_remote_failure_refuses(self):
        (self.cc / "ls-remote.fail").write_text("")
        res = self.cloud()
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertIn("git ls-remote failed", res.stderr)

    def test_non_github_origin_error_hides_credentials(self):
        self.set_origin("https://oauth2:SECRETTOKEN@forgejo.example/o/r.git")
        res = self.cloud()
        self.assertEqual(res.returncode, 2)
        self.assertNotIn("SECRETTOKEN", res.stderr)
        self.assertIn("forgejo.example/o/r.git", res.stderr)


class TestRouteRegistration(unittest.TestCase):
    def test_registered_for_code_bulk_mechanical_only(self):
        svc = r.BY_NAME["cursor-cloud"]
        for kind in ("code", "bulk", "mechanical"):
            self.assertTrue(svc.eligible(kind), kind)
        for kind in ("frontier", "judgment", "github", "api-only"):
            self.assertFalse(svc.eligible(kind), kind)
        self.assertEqual(svc.acp_agent, "cursor-cloud")
        self.assertEqual(svc.shares_pool, "cursor")

    def test_never_the_default_for_a_kind(self):
        q = {**{k: {"remaining": 100.0} for k in r.BY_NAME}}
        for kind in ("code", "bulk", "mechanical"):
            c = r.route(kind, quota=q)
            self.assertNotEqual(c.service.name, "cursor-cloud", kind)
            for local in ("cursor", "cursor-auto"):
                if r.BY_NAME[local].eligible(kind):
                    self.assertLess(r.BY_NAME[local].rank_for(kind), r.BY_NAME["cursor-cloud"].rank_for(kind))

    def test_eligible_when_local_agents_are_exhausted(self):
        q = {k: {"remaining": 0.0} for k in r.BY_NAME}
        q["cursor-cloud"] = {"remaining": 80.0}
        for kind in ("bulk", "mechanical"):
            c = r.route(kind, quota=q)
            self.assertEqual(c.service.name, "cursor-cloud", kind)
            self.assertTrue(c.dispatch.startswith("acp-dispatch cursor-cloud --model "), c.dispatch)
            self.assertTrue(c.dispatch.endswith(f"--kind {kind}"), c.dispatch)

    def test_reads_the_cursor_aiuse_row(self):
        accounts = [{"provider": "cursor", "windows": [
            {"label": "third-party", "pool_family": "third_party", "remaining_percent": 31.0,
             "headroom_percent": 31.0, "state": "ok"}]}]
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "latest.json"
            snap.write_text(json.dumps({"collected_at": r.datetime.now(r.UTC).isoformat(),
                                        "snapshot": {"accounts": accounts}}))
            with mock.patch.object(r, "SNAPSHOT", snap):
                q = r.load_snapshot()[0]
        self.assertEqual(q["cursor"]["remaining"], 31.0)
        self.assertEqual(q["cursor-cloud"]["remaining"], 31.0)

    def test_dispatch_maps_cursor_cloud_to_its_own_service(self):
        self.assertEqual(r.dispatch_service_name("cursor-cloud", "claude-sonnet-5-5"), "cursor-cloud")


if __name__ == "__main__":
    unittest.main()
