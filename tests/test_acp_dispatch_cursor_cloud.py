#!/usr/bin/env python3
"""acp-dispatch cursor-cloud: a slice sent to Cursor Cloud Agents (2026-10-20), and the
route_agent registration. No network: bin/cursor-cloud is replaced by a fake on CURSOR_CLOUD_BIN."""
from __future__ import annotations

import json
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
        (self.cc / "usage.json").write_text(json.dumps({"totalCostUsd": 0.42, "tokens": 1234}))
        git(self.repo.parent, "init", "-q", str(self.repo))
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "t")
        (self.repo / "README").write_text("x\n")
        git(self.repo, "add", "README")
        git(self.repo, "commit", "-q", "-m", "i")
        git(self.repo, "checkout", "-q", "-b", "feat/slice-base")
        self.set_origin("git@github.com:djbclark/some-repo.git")

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
        e = self.base_env("writes", CC=str(self.cc), CURSOR_CLOUD_BIN=str(self.fake_cc),
                          ACP_DISPATCH_CLOUD_POLL="0", **(env or {}))
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
        self.assertFalse((self.out / "jobs" / "s1.json").exists())

    def test_no_local_gates_and_no_acp_run(self):
        # an in-flight cap of 0 refuses every local slice; a cloud slice runs off the Mac
        self.run_json("run-1.json", "FINISHED", result="ok")
        res = self.cloud(env={"ACP_DISPATCH_INFLIGHT": "cursor-cloud=0",
                              "PATH": f"{self.tmp / 'nobin'}:/usr/bin:/bin"})
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
        self.assertTrue(any(ln.startswith("COST: 0.42") for ln in lines), text)
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
                                   ACP_DISPATCH_CLOUD_POLL="0"))
        self.assertEqual(ex.returncode, 0, ex.stderr)
        self.assertEqual(self.report().splitlines()[-1], "DONE")


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
