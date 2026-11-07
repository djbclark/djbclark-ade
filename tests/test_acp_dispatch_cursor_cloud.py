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
        # the waiter hint sits above `rearm:`, which stays the last line (2026-10-20)
        lines = res.stdout.strip().splitlines()
        self.assertTrue(lines[-1].startswith("rearm: "), res.stdout)
        self.assertIn("timeout 7200000", lines[-2])
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
    def on_origin(self, *names: str) -> None:
        """ls-remote answers from the second call on (after the run) include these cursor/* heads."""
        text = f"{self.head}\trefs/heads/feat/slice-base\n" + "".join(f"c0ffee\trefs/heads/{n}\n" for n in names)
        for n in (2, 3):
            (self.cc / f"ls-remote-{n}.txt").write_text(text)

    def test_branch_from_result_text_when_api_has_only_repo_url(self):
        self.on_origin("cursor/document-cursor-cloud-8526")
        self.run_json("run-1.json", "FINISHED", result=REAL_RESULT, git=REAL_BRANCHES)
        self.assertEqual(self.cloud().returncode, 0)
        lines = self.report().splitlines()
        self.assertIn("BRANCH: cursor/document-cursor-cloud-8526", lines)
        self.assertTrue(any(ln.startswith("BRANCH-SOURCE: result text, confirmed on origin") for ln in lines))

    def test_result_text_branch_absent_from_origin_is_not_accepted(self):
        self.run_json("run-1.json", "FINISHED", result=REAL_RESULT, git=REAL_BRANCHES)
        self.assertEqual(self.cloud().returncode, 0)
        lines = self.report().splitlines()
        self.assertNotIn("BRANCH: cursor/document-cursor-cloud-8526", lines)
        self.assertTrue(any(ln.startswith("BRANCH: unknown") for ln in lines))

    def test_branch_regex_ignores_paths_and_prefixed_words(self):
        mod = self.load_module()
        found = mod.CLOUD_BRANCH_RE.findall("see docs/cursor/x and ./cursor/y and mycursor/z and `cursor/real-1`.")
        self.assertEqual(found, ["cursor/real-1"])

    def test_ambiguous_ls_remote_candidates_are_unknown(self):
        (self.cc / "ls-remote-2.txt").write_text(
            f"{self.head}\trefs/heads/feat/slice-base\nd1\trefs/heads/cursor/one\nd2\trefs/heads/cursor/two\n")
        (self.cc / "fetch-ct").write_text("99999999999\n")
        self.run_json("run-1.json", "FINISHED", result="Done.", git=REAL_BRANCHES)
        self.assertEqual(self.cloud().returncode, 0)
        self.assertTrue(any(ln.startswith("BRANCH: unknown") for ln in self.report().splitlines()))

    def write_peer(self, finished: float | None) -> None:
        import time
        jobs = self.out / "jobs"
        jobs.mkdir(parents=True, exist_ok=True)
        (jobs / "peer.json").write_text(json.dumps({
            "name": "peer", "cloud_provider": "cursor", "cloud_repo": "https://github.com/djbclark/some-repo", "cloud_agent_id": "bc-peer",
            "launched_at": time.time() - 5, "started": time.time() - 5, "finished": finished,
            "status": "running" if finished is None else "done"}))

    def ls_remote_one_new(self) -> None:
        (self.cc / "ls-remote-2.txt").write_text(
            f"{self.head}\trefs/heads/feat/slice-base\nd1\trefs/heads/cursor/mine-or-theirs\n")
        (self.cc / "fetch-ct").write_text("99999999999\n")
        self.run_json("run-1.json", "FINISHED", result="Done.", git=REAL_BRANCHES)

    def test_ls_remote_fallback_unknown_while_another_cloud_slice_overlaps(self):
        self.ls_remote_one_new()
        self.write_peer(None)
        self.assertEqual(self.cloud().returncode, 0)
        self.assertTrue(any(ln.startswith("BRANCH: unknown") for ln in self.report().splitlines()))

    def test_ls_remote_fallback_ignores_a_peer_that_ended_before_the_launch(self):
        self.ls_remote_one_new()
        self.write_peer(1000.0)
        self.assertEqual(self.cloud().returncode, 0)
        self.assertIn("BRANCH: cursor/mine-or-theirs", self.report().splitlines())

    def load_module(self):
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader(
            "acpd_cc2", str(Path(__file__).resolve().parent.parent / "bin" / "acp-dispatch"))
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(mod)
        return mod

    def test_perm_read_only_and_deny_refused(self):
        for perm in ("read-only", "deny"):
            with self.subTest(perm=perm):
                res = self.cloud("--perm", perm, name=f"p-{perm}")
                self.assertEqual(res.returncode, 2, res.stderr)
                self.assertIn("cannot enforce --perm", res.stderr)
        self.assertEqual(self.calls(), [])

    def test_extend_takes_effect_in_a_running_poller(self):
        import time
        self.run_json("run-1.json", "RUNNING")
        res = self.cloud("--detach", "--no-wait", "--timeout", "2")
        self.assertEqual(res.returncode, 0, res.stderr)
        rec_path = self.out / "jobs" / "s1.json"
        script = Path(__file__).resolve().parent.parent / "bin" / "acp-dispatch"
        proc = subprocess.Popen([sys.executable, str(script), "execute", str(rec_path)],
                                env={**os.environ, **self.fenv(ACP_DISPATCH_CLOUD_POLL="0.2")},
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if json.loads(rec_path.read_text()).get("pid") == proc.pid:
                    break
                time.sleep(0.1)
            ext = run(["extend", str(rec_path), "600"], env=self.fenv())
            self.assertEqual(ext.returncode, 0, ext.stderr)
            time.sleep(4)                      # past the original 2 s limit
            self.assertIsNone(proc.poll(), "the poller stopped at the original limit")
        finally:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=30)

    def test_deadline_counts_from_the_launch_not_from_a_repoll(self):
        self.run_json("run-1.json", "RUNNING")
        res = self.cloud("--timeout", "1", env={"ACP_DISPATCH_CLOUD_POLL": "0.3"})
        self.assertEqual(res.returncode, 124, res.stderr)
        self.assertIn("acp-dispatch --timeout 1 s reached", self.report())

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
        self.on_origin("cursor/document-cursor-cloud-8526")
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

    def test_unknown_status_counts_as_running_until_the_deadline(self):
        self.run_json("run-1.json", "SOMETHING_NEW")
        res = self.cloud("--timeout", "1", env={"ACP_DISPATCH_CLOUD_POLL": "0.3"})
        self.assertEqual(res.returncode, 124, res.stderr)
        self.assertEqual(self.record()["cloud_last_status"], "SOMETHING_NEW")
        self.assertIn("may still be running in Cursor", self.report())

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

    # pass 4: Codex P2s and adversary lows S1 to S3
    def poll_in_process(self, rec_path: Path) -> list[float]:
        """Run cloud_poll in this process with cloud_call wrapped; the timeouts given to `run` polls."""
        from unittest import mock
        mod = self.load_module()
        seen: list[float] = []
        real = mod.cloud_call

        def spy(binp, *args, **kw):
            if args and args[0] == "run":
                seen.append(kw.get("timeout", 180))
            return real(binp, *args, **kw)
        with mock.patch.dict(os.environ, self.fenv(ACP_DISPATCH_CLOUD_POLL="0.3")), \
                mock.patch.object(mod, "cloud_call", spy):
            self.poll_rc = mod.cloud_poll(rec_path)
        return seen

    def test_each_poll_call_is_bounded_by_the_time_left(self):
        self.run_json("run-1.json", "RUNNING")
        rec_path = self.detached_record()
        rec = json.loads(rec_path.read_text())
        rec["timeout"] = 2
        rec_path.write_text(json.dumps(rec))
        seen = self.poll_in_process(rec_path)
        self.assertTrue(seen)
        self.assertTrue(all(t <= 2.01 for t in seen), seen)
        self.assertLess(min(seen), 2.0, seen)          # later polls get less than the first

    def test_cloud_limit_clamps_and_survives_junk(self):
        mod = self.load_module()
        cap = float(mod.CLOUD_MAX_SECONDS)
        self.assertEqual(mod.cloud_limit(30), 30.0)
        self.assertEqual(mod.cloud_limit(10 ** 9), cap)
        for junk in (0, None, "soon", [], -5, "nan-ish"):
            self.assertEqual(mod.cloud_limit(junk), cap, junk)

    def test_poller_with_a_non_numeric_or_huge_timeout_does_not_crash(self):
        self.run_json("run-1.json", "FINISHED", result="ok")
        rec_path = self.detached_record()
        rec = json.loads(rec_path.read_text())
        rec["timeout"] = "soon"
        rec_path.write_text(json.dumps(rec))
        self.poll_in_process(rec_path)
        self.assertEqual(self.poll_rc, 0)

    def test_resume_timeout_is_honored_for_a_cloud_record(self):
        self.run_json("run-1.json", "RUNNING")
        rec_path = self.detached_record()
        self.kill_poller(rec_path)
        res = run(["resume", str(rec_path), "--timeout", "77"], env=self.fenv())
        self.assertEqual(res.returncode, 0, res.stderr)
        rec = json.loads(rec_path.read_text())
        self.assertEqual(rec["timeout"], 77)
        self.assertGreater(rec["poll_base"], rec["launched_at"])
        self.assertEqual(self.repoll_submits(), 1)

    def test_resume_negative_timeout_is_refused(self):
        self.run_json("run-1.json", "RUNNING")
        rec_path = self.detached_record()
        self.kill_poller(rec_path)
        res = run(["resume", str(rec_path), "--timeout", "-3"], env=self.fenv())
        self.assertNotEqual(res.returncode, 0)
        self.assertEqual(self.repoll_submits(), 0)

    def test_without_launchctl_reap_and_resume_use_a_background_process(self):
        import time
        self.run_json("run-1.json", "RUNNING")
        rec_path = self.detached_record()
        self.kill_poller(rec_path)
        env = self.fenv(ACP_DISPATCH_LAUNCHCTL="/nonexistent/launchctl", ACP_DISPATCH_CLOUD_POLL="0.2")
        res = run(["reap", str(rec_path)], env=env)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.repoll_submits(), 0)       # nothing went to launchctl
        self.assertTrue((self.out / "s1-repoll1-run.sh").exists())
        self.assertEqual(json.loads(rec_path.read_text())["repolls"], 1)
        self.run_json("run-1.json", "FINISHED", result="ok", git=REAL_BRANCHES)
        for _ in range(150):                              # the background poller finalizes it
            # finalize writes the record, then touches .done: wait for the last of the two
            if json.loads(rec_path.read_text()).get("finished") and (self.out / "s1-report.md.done").exists():
                break
            time.sleep(0.2)
        rec = json.loads(rec_path.read_text())
        self.assertEqual(rec["status"], "done", rec)
        self.assertTrue((self.out / "s1-report.md.done").exists())

    def test_without_launchctl_detached_dispatch_still_starts(self):
        import time
        self.run_json("run-1.json", "FINISHED", result="ok", git=REAL_BRANCHES)
        res = self.cloud("--detach", "--no-wait",
                         env={"ACP_DISPATCH_LAUNCHCTL": "/nonexistent/launchctl"})
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        rec_path = self.out / "jobs" / "s1.json"
        for _ in range(150):
            if json.loads(rec_path.read_text()).get("finished"):
                break
            time.sleep(0.2)
        self.assertEqual(json.loads(rec_path.read_text())["status"], "done")

    def peer_rec(self, **over) -> dict:
        import time
        base = {"name": "peer", "cloud_provider": "cursor", "cloud_agent_id": "bc-peer",
                "cloud_repo": "https://github.com/djbclark/some-repo", "launched_at": time.time() - 5,
                "started": time.time() - 5, "finished": None, "status": "running", "timeout": 600}
        return {**base, **over}

    def overlapping(self, peer: dict) -> list[str]:
        import time
        mod = self.load_module()
        jobs = self.out / "jobs"
        jobs.mkdir(parents=True, exist_ok=True)
        (jobs / "peer.json").write_text(json.dumps(peer))
        me = {"name": "me", "cloud_provider": "cursor", "cloud_repo": peer["cloud_repo"],
              "launched_at": time.time() - 1, "started": time.time() - 1, "cloud_agent_id": "bc-me",
              "record": str(jobs / "me.json"), "out": str(self.out)}
        (jobs / "me.json").write_text(json.dumps(me))
        return mod.cloud_overlapping(me)

    def test_overlap_counts_a_live_peer_and_skips_the_unusable(self):
        self.assertEqual(self.overlapping(self.peer_rec()), ["peer"])
        self.assertEqual(self.overlapping(self.peer_rec(cloud_agent_id=None)), [])
        self.assertEqual(self.overlapping(self.peer_rec(cloud_agent_id="")), [])
        self.assertEqual(self.overlapping(self.peer_rec(launched_at=1000.0, started=1000.0)), [])
        for junk in ("soon", [1], {"a": 1}):
            with self.subTest(junk=junk):
                self.assertEqual(self.overlapping(self.peer_rec(launched_at=junk)), [])
                self.assertEqual(self.overlapping(self.peer_rec(finished=junk)), [])
        self.assertEqual(self.overlapping(self.peer_rec(timeout="soon")), ["peer"])   # junk timeout: the cap

    def test_result_text_branch_unchanged_since_launch_is_not_confirmed(self):
        # cursor/document-cursor-cloud-8526 already existed at the same head before the launch
        text = f"{self.head}\trefs/heads/feat/slice-base\nc0ffee\trefs/heads/cursor/document-cursor-cloud-8526\n"
        for n in (1, 2, 3):
            (self.cc / f"ls-remote-{n}.txt").write_text(text)
        self.run_json("run-1.json", "FINISHED", result=REAL_RESULT, git=REAL_BRANCHES)
        self.assertEqual(self.cloud().returncode, 0)
        self.assertTrue(any(ln.startswith("BRANCH: unknown") for ln in self.report().splitlines()),
                        self.report())

    def test_result_text_branch_moved_since_launch_is_confirmed(self):
        before = f"{self.head}\trefs/heads/feat/slice-base\nc0ffee\trefs/heads/cursor/document-cursor-cloud-8526\n"
        after = f"{self.head}\trefs/heads/feat/slice-base\nbeef01\trefs/heads/cursor/document-cursor-cloud-8526\n"
        (self.cc / "ls-remote-1.txt").write_text(before)
        for n in (2, 3):
            (self.cc / f"ls-remote-{n}.txt").write_text(after)
        self.run_json("run-1.json", "FINISHED", result=REAL_RESULT, git=REAL_BRANCHES)
        self.assertEqual(self.cloud().returncode, 0)
        self.assertIn("BRANCH: cursor/document-cursor-cloud-8526", self.report().splitlines())

    # pass 5: Codex P1 (same-name re-dispatch) and P2 (deadline before the call)
    def launches(self) -> int:
        return len([c for c in self.calls() if c and c[0] == "launch"])

    def test_redispatch_of_an_unfinished_cloud_record_is_refused_whatever_the_pid(self):
        self.run_json("run-1.json", "RUNNING")
        rec_path = self.detached_record()
        for label, pid in (("no pid yet", None), ("dead poller", 999999)):
            with self.subTest(label):
                rec = json.loads(rec_path.read_text())
                rec.update(pid=pid, pid_start=None)
                rec_path.write_text(json.dumps(rec))
                res = self.cloud("--detach", "--no-wait")
                self.assertNotEqual(res.returncode, 0, res.stdout)
                self.assertIn("resume", res.stderr)
                self.assertIn("bc-test1", res.stderr)
                self.assertEqual(self.launches(), 1)
                self.assertEqual(json.loads(rec_path.read_text())["cloud_agent_id"], "bc-test1")

    def test_redispatch_force_still_overrides_an_unfinished_cloud_record(self):
        self.run_json("run-1.json", "RUNNING")
        rec_path = self.detached_record()
        res = self.cloud("--detach", "--no-wait", "--force")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.launches(), 2)
        self.assertTrue(rec_path.exists())

    def test_a_finished_cloud_record_may_be_redispatched_with_force_only_for_done(self):
        # a record that ended (finished set) is not "unfinished": the .done rule applies, not the new refusal
        self.run_json("run-1.json", "FINISHED", result="ok", git=REAL_BRANCHES)
        self.assertEqual(self.cloud().returncode, 0)
        res = self.cloud()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("already finished", res.stderr)

    def test_no_poll_after_the_deadline_and_the_sleep_is_capped(self):
        import time
        self.run_json("run-1.json", "RUNNING")
        self.run_json("run-2.json", "FINISHED", result="late", git=REAL_BRANCHES)   # ends just after the limit
        t0 = time.time()
        res = self.cloud("--timeout", "1", env={"ACP_DISPATCH_CLOUD_POLL": "6"})
        self.assertEqual(res.returncode, 124, res.stdout + res.stderr)
        self.assertLess(time.time() - t0, 5.5)          # not a full 6 s interval
        self.assertEqual(len([c for c in self.calls() if c and c[0] == "run"]), 1)
        self.assertIn("acp-dispatch --timeout 1 s reached", self.report())


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
