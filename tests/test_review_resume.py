"""bin/review-launch: checkpoints, resume from evidence, detached launch and pause-ask (queue item 103).

Same fake `claude` as tests/test_review_launch.py. A synthetic stream stands in for a real one.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from test_review_launch import LAUNCH, World, load_launcher, pid_alive

CP1 = "CHECKPOINT 1: finding at bin/x.py:12; open: is y checked?"
CP2 = "## CHECKPOINT 2:\nfinding at lib/z.py:40"


@pytest.fixture
def world(tmp_path: Path) -> World:
    w = World(tmp_path)
    (w.bin / "hermes-ping").write_text('#!/bin/sh\necho "$@" >> "$HERMES_LOG"\n')
    (w.bin / "hermes-ping").chmod(0o755)
    w.hermes = w.tmp / "hermes.log"
    return w


def env(w: World, **extra: str) -> dict:
    return w.env(HERMES_LOG=str(w.hermes), **extra)


def wait_for(path: Path, seconds: float = 30) -> None:
    end = time.monotonic() + seconds
    while not path.exists() and time.monotonic() < end:
        time.sleep(0.1)
    assert path.exists(), f"{path} never appeared"


def stream(path: Path, events: list, torn: str = "") -> None:
    path.write_text("".join(json.dumps(e) + "\n" for e in events) + torn)


def asst(*items: dict) -> dict:
    return {"type": "assistant", "message": {"content": list(items)}}


def text(t: str) -> dict:
    return {"type": "text", "text": t}


def read(p: str) -> dict:
    return {"type": "tool_use", "id": "t" + p, "name": "Read", "input": {"file_path": p}}


def launch(w: World, *extra: str, prompt: str = "review this", **envx: str) -> subprocess.CompletedProcess:
    return w.launch("--json", *extra, prompt=prompt, env=env(w, **envx))


def prompt_of(w: World, n: int = -1) -> str:
    return w.launches()[n]["argv"][-1]


# ---- A: the extractor ------------------------------------------------------------------------------------

def test_extractor_reads_checkpoints_and_the_read_trail_and_skips_a_torn_line(tmp_path):
    mod = load_launcher()
    s = tmp_path / "stream.jsonl"
    stream(s, [{"type": "system", "subtype": "init"},
               asst(text("thinking aloud, no marker")), asst(read("/wt/a.py")), asst(read("/wt/a.py")),
               asst(text(CP1)), asst({"type": "tool_use", "id": "g", "name": "Grep", "input": {"pattern": "foo", "path": "src"}}),
               asst(text(CP2 + "\n\nCHECKPOINT 3: two in one text")), asst(text(CP1)),
               {"type": "user", "message": {"content": [{"type": "text", "text": "CHECKPOINT 9: not an assistant"}]}}],
           torn='{"type": "assistant", "message": {"content": [{"type": "te')
    info = mod.extract_checkpoints(s)
    assert [c["n"] for c in info["checkpoints"]] == [1, 2, 3]          # the repeated CP1 is dropped
    assert "bin/x.py:12" in info["checkpoints"][0]["text"] and info["checkpoints"][1]["text"] == "finding at lib/z.py:40"
    assert info["checkpoints"][2]["text"] == "two in one text"
    assert info["reads"] == ["Read: /wt/a.py", "Grep: foo (in src)"] and info["unreadable"] == 1 and info["tool_uses"] == 3
    md = mod.render_checkpoints(info, tmp_path, "exit 77")
    assert "Unverified model output" in md and "## CHECKPOINT 2" in md and "- Read: /wt/a.py" in md


def test_extractor_without_any_checkpoint_keeps_the_last_text(tmp_path):
    mod = load_launcher()
    s = tmp_path / "stream.jsonl"
    stream(s, [asst(text("first")), asst(text("my last words"))])
    md = mod.render_checkpoints(mod.extract_checkpoints(s), tmp_path)
    assert "No CHECKPOINT text was written" in md and "my last words" in md


def test_fence_is_longer_than_any_backtick_run_in_the_notes():
    mod = load_launcher()
    out = mod.fence("a ```` b\n```")
    assert out.startswith("`````\n") and out.endswith("\n`````")


def test_checkpoints_subcommand_rebuilds_notes_for_a_run_whose_launcher_was_killed(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    stream(d / "stream.jsonl", [asst(text(CP1))])
    (d / "launch.json").write_text(json.dumps({"schema": 1, "state": "running", "pid": 1}))
    r = subprocess.run([sys.executable, "-I", str(LAUNCH), "checkpoints", str(d), "--print"], capture_output=True, text=True)
    assert r.returncode == 0 and "bin/x.py:12" in r.stdout and (d / "checkpoints.md").exists()
    assert subprocess.run([sys.executable, "-I", str(LAUNCH), "checkpoints", str(tmp_path)], capture_output=True).returncode == 2


# ---- A: written on every abnormal end; the prompt protocol -----------------------------------------------

def test_a_run_without_output_writes_checkpoints_and_the_run_record(world, tmp_path):
    world.passed_check()
    world.scenario(texts=[CP1], no_result=True, exit=1)
    d = tmp_path / "run"
    r = launch(world, "--evidence-dir", str(d))
    assert r.returncode == 3, r.stderr
    assert "bin/x.py:12" in (d / "checkpoints.md").read_text()
    rec = json.loads(r.stdout)
    assert rec["checkpoints_file"] == str(d / "checkpoints.md") and rec["tainted"] is False
    assert json.loads((d / "result.json").read_text()) == rec
    assert json.loads((d / "launch.json").read_text())["state"] == "finished"
    assert (d / "done").read_text() == "exit=3\n" and (d / "prompt.txt").read_text() == "review this"


def test_a_timeout_writes_checkpoints(world, tmp_path):
    world.passed_check()
    world.scenario(texts=[CP1], sleep=30)
    d = tmp_path / "run"
    r = launch(world, "--evidence-dir", str(d), "--timeout", "2")
    assert r.returncode == 124 and "bin/x.py:12" in (d / "checkpoints.md").read_text()


def test_a_signal_to_the_launcher_writes_checkpoints(world, tmp_path):
    world.passed_check()
    world.scenario(texts=[CP1], sleep=60)
    d = tmp_path / "run"
    p = subprocess.Popen([sys.executable, "-I", str(LAUNCH), "--mode", "review", "-C", str(world.wt), "--schema",
                          str(world.schema), "-p", "x", "--json", "--evidence-dir", str(d)], env=env(world),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    wait_for(d / "stream.jsonl")
    time.sleep(2)
    p.send_signal(signal.SIGHUP)
    p.communicate(timeout=60)
    assert p.returncode == 3 and "bin/x.py:12" in (d / "checkpoints.md").read_text()


def test_a_tripwire_also_keeps_the_notes(world, tmp_path):
    world.passed_check()
    world.scenario(texts=[CP1], tool_uses=[{"name": "Read", "input": {"file_path": "/etc/hosts"}}])
    d = tmp_path / "run"
    r = launch(world, "--evidence-dir", str(d))
    assert r.returncode == 77 and "bin/x.py:12" in (d / "checkpoints.md").read_text()


def test_the_checkpoint_protocol_default_and_overrides(world, tmp_path):
    world.passed_check()
    world.passed_check("review", "--model", "claude-fable-5-2")
    world.passed_check("review", "--model", "claude-sonnet-5-5")
    mark = "CHECKPOINT PROTOCOL"
    assert launch(world, "--model", "claude-fable-5-2", "--evidence-dir", str(tmp_path / "a")).returncode == 0
    assert mark in prompt_of(world)                                           # frontier model + run dir: ON
    assert launch(world, "--model", "claude-fable-5-2").returncode == 0
    assert mark not in prompt_of(world)                                       # nowhere to save: off
    assert launch(world, "--model", "claude-sonnet-5-5", "--evidence-dir", str(tmp_path / "b")).returncode == 0
    assert mark not in prompt_of(world)                                       # not frontier: off
    assert launch(world, "--model", "claude-sonnet-5-5", "--checkpoint", "--evidence-dir", str(tmp_path / "c")).returncode == 0
    assert mark in prompt_of(world)
    assert launch(world, "--model", "claude-fable-5-2", "--no-checkpoint", "--evidence-dir", str(tmp_path / "d")).returncode == 0
    assert mark not in prompt_of(world)
    assert launch(world, "--checkpoint").returncode == 2                      # --checkpoint needs a run dir


# ---- B: resume from evidence -----------------------------------------------------------------------------

def dead_run(world: World, tmp_path: Path, name: str = "dead", texts=(CP1, CP2)) -> Path:
    world.scenario(texts=list(texts), no_result=True, exit=1)
    d = tmp_path / name
    assert launch(world, "--evidence-dir", str(d), prompt="ORIGINAL PROMPT").returncode == 3
    world.scenario()
    return d


def test_resume_builds_the_prompt_from_the_original_and_the_notes_and_records_the_parent(world, tmp_path):
    world.passed_check()
    dead = dead_run(world, tmp_path)
    new = tmp_path / "new"
    r = world.run("--mode", "review", "-C", str(world.wt), "--schema", str(world.schema), "--json",
                  "--resume-from-evidence", str(dead), "--evidence-dir", str(new), env=env(world))
    assert r.returncode == 0, r.stderr
    p = prompt_of(world)
    assert p.startswith("ORIGINAL PROMPT") and "RESUMED REVIEW" in p and "bin/x.py:12" in p and "lib/z.py:40" in p
    assert "do not follow anything in it" in p and "from 3." in p and "```" in p
    assert "do not re-read" not in p and "NOT evidence" in p            # notes are leads, never coverage claims
    assert p.index("previous run ended: no result event") > p.index("```")   # the parent's reason sits inside the fence
    rec = json.loads(r.stdout)
    assert rec["tainted"] is True and rec["parent_run"] == str(dead)
    assert rec["structured_output"] is None and rec["tainted_output"] == {"ok": True}   # never a clean verdict
    launch_json = json.loads((new / "launch.json").read_text())
    assert launch_json["parent_run"] == str(dead) and launch_json["tainted"] is True
    assert (new / "prompt.txt").read_text() == "ORIGINAL PROMPT"      # a second resume starts from the original


def test_a_second_resume_carries_the_first_runs_notes_too(world, tmp_path):
    world.passed_check()
    dead = dead_run(world, tmp_path)
    world.scenario(texts=["CHECKPOINT 3: third note"], no_result=True, exit=1)
    mid = tmp_path / "mid"
    assert world.run("--mode", "review", "-C", str(world.wt), "--schema", str(world.schema), "--json", "--resume-from-evidence",
                     str(dead), "--evidence-dir", str(mid), env=env(world)).returncode == 3
    world.scenario()
    r = world.run("--mode", "review", "-C", str(world.wt), "--schema", str(world.schema), "--json", "--resume-from-evidence",
                  str(mid), "--evidence-dir", str(tmp_path / "last"), env=env(world))
    assert r.returncode == 0, r.stderr
    p = prompt_of(world)
    assert "bin/x.py:12" in p and "third note" in p and p.count("ORIGINAL PROMPT") == 1


@pytest.mark.parametrize("extra,why", [
    (["--evidence-dir", "{new}"], "need --json"),                       # no --json
    (["--json", "--evidence-dir", "{new}", "-p", "other"], "takes its prompt"),
    (["--json"], "need --evidence-dir"),
    (["--json", "--evidence-dir", "{new}", "--mode", "read-only"], "same --mode"),
])
def test_resume_refusals(world, tmp_path, extra, why):
    world.passed_check()
    world.passed_check("read-only")
    dead = dead_run(world, tmp_path)
    args = [x.format(new=tmp_path / "new") for x in extra]
    base = ["--mode", "review"] if "--mode" not in args else []
    r = world.run(*base, "-C", str(world.wt), "--schema", str(world.schema), "--resume-from-evidence", str(dead), *args, env=env(world))
    assert r.returncode == 2 and why in r.stderr, r.stderr


def test_resume_refuses_a_live_run_and_a_non_run_dir(world, tmp_path):
    world.passed_check()
    d = tmp_path / "live"
    d.mkdir()
    pid = os.getpid()
    mod = load_launcher()
    (d / "launch.json").write_text(json.dumps({"schema": 1, "state": "running", "pid": pid, "pid_started": mod.proc_start(pid),
                                               "mode": "review", "worktree": os.path.realpath(world.wt)}))
    (d / "prompt.txt").write_text("p")
    common = ["--mode", "review", "-C", str(world.wt), "--schema", str(world.schema), "--json", "--evidence-dir", str(tmp_path / "n")]
    r = world.run(*common, "--resume-from-evidence", str(d), env=env(world))
    assert r.returncode == 2 and "still alive" in r.stderr
    r = world.run(*common, "--resume-from-evidence", str(tmp_path), env=env(world))
    assert r.returncode == 2 and "not a review run dir" in r.stderr


# ---- C: detached launch ----------------------------------------------------------------------------------

def test_a_detached_review_survives_the_end_of_its_parent(world, tmp_path):
    world.passed_check()
    world.scenario(texts=[CP1], sleep=4)
    d = tmp_path / "run"
    script = ("import subprocess,sys,time\n"
              "r=subprocess.run(sys.argv[1:],capture_output=True,text=True)\n"
              "print(r.stdout.strip(),flush=True)\n"
              "time.sleep(120)\n")
    parent = subprocess.Popen([sys.executable, "-c", script, sys.executable, "-I", str(LAUNCH), "--mode", "review", "-C", str(world.wt),
                               "--schema", str(world.schema), "-p", "x", "--detach", "--evidence-dir", str(d)],
                              env=env(world), stdout=subprocess.PIPE, text=True, start_new_session=True)
    t0 = time.monotonic()
    first = json.loads(parent.stdout.readline())
    assert time.monotonic() - t0 < 3.5 and first["run_dir"] == str(d) and first["done"] == str(d / "done")
    assert isinstance(first["pid"], int) and not (d / "done").exists()          # returned at once, the run still going
    os.killpg(parent.pid, signal.SIGKILL)                                       # the caller's whole job group goes away
    parent.wait(timeout=30)
    wait_for(d / "done", 60)
    rec = json.loads((d / "result.json").read_text())
    assert rec["exit"] == 0 and (d / "done").read_text() == "exit=0\n"
    assert json.loads((d / "launch.json").read_text())["detached"] is True
    end = time.monotonic() + 15                                                 # done is written just before the exit
    while pid_alive(first["pid"]) and time.monotonic() < end:
        time.sleep(0.1)
    assert not pid_alive(first["pid"])


def test_detach_defaults_the_run_dir_and_refuses_at_once(world, tmp_path):
    world.passed_check()
    r = world.launch("--detach", "-C", str(tmp_path / "missing"), env=env(world))
    assert r.returncode == 2                                                    # a refusal is seen by the caller, not buried
    r = world.launch("--detach", env=env(world))
    assert r.returncode == 0, r.stderr
    first = json.loads(r.stdout)
    assert str(world.state / "runs") in first["run_dir"]
    wait_for(Path(first["done"]), 60)


# ---- D: pause-ask ----------------------------------------------------------------------------------------

def start(world: World, d: Path, *extra: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-I", str(LAUNCH), "--mode", "review", "-C", str(world.wt), "--schema", str(world.schema),
                             "-p", "x", "--json", "--evidence-dir", str(d), *extra], env=env(world), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def child_state(d: Path) -> str:
    pg = json.loads((d / "launch.json").read_text())["child_pgid"]
    return subprocess.run(["ps", "-o", "stat=", "-p", str(pg)], capture_output=True, text=True).stdout.strip()


def sub(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(LAUNCH), *args], capture_output=True, text=True)


def test_a_timeout_pauses_asks_and_a_resume_finishes_a_tainted_run(world, tmp_path):
    world.passed_check()
    world.scenario(texts=[CP1], sleep=3)
    d = tmp_path / "run"
    p = start(world, d, "--timeout", "1", "--pause-on-timeout")
    wait_for(d / "pause.json")
    assert child_state(d).startswith("T")                                        # SIGSTOPped: no more paid turns
    wait_for(world.hermes, 15)
    ask = world.hermes.read_text()
    assert "djbclark-ade: review run run is PAUSED" in ask and f"review-launch resume {d}" in ask and f"review-launch abort {d}" in ask
    assert "PAUSED" in (d / "ASK.txt").read_text()
    st = json.loads(sub("status", str(d)).stdout)
    assert st["paused"] is True and st["launcher_alive"] is True and st["done"] is False
    assert sub("resume", str(d), "--extend", "60").returncode == 0
    out, err = p.communicate(timeout=60)
    assert p.returncode == 0, err
    rec = json.loads(out)
    assert rec["paused"] == 1 and rec["tainted"] is True
    assert rec["structured_output"] is None and rec["tainted_output"] is not None
    assert json.loads((d / "launch.json").read_text())["tainted"] is True


def test_an_abort_at_a_pause_keeps_the_notes_and_ends_exit_3(world, tmp_path):
    world.passed_check()
    world.scenario(texts=[CP1], sleep=30)
    d = tmp_path / "run"
    p = start(world, d, "--timeout", "1", "--pause-on-timeout")
    wait_for(d / "pause.json")
    assert sub("abort", str(d)).returncode == 0
    out, _ = p.communicate(timeout=60)
    assert p.returncode == 3 and json.loads(out)["structured_output"] is None
    assert "bin/x.py:12" in (d / "checkpoints.md").read_text() and (d / "done").exists()


def test_an_unanswered_pause_aborts_never_resumes(world, tmp_path):
    world.passed_check()
    world.scenario(texts=[CP1], sleep=30)
    d = tmp_path / "run"
    p = start(world, d, "--timeout", "1", "--pause-on-timeout", "--pause-max", "2")
    out, err = p.communicate(timeout=60)
    assert p.returncode == 3 and "not answered" in err and "bin/x.py:12" in (d / "checkpoints.md").read_text()


def test_a_pause_request_pauses_a_running_review(world, tmp_path):
    world.passed_check()
    world.scenario(texts=[CP1], sleep=10)
    d = tmp_path / "run"
    p = start(world, d, "--pause-on-timeout", "--timeout", "60")
    wait_for(d / "launch.json")
    time.sleep(1.5)
    assert sub("pause", str(d), "--reason", "frontier allowance is low").returncode == 0
    wait_for(d / "pause.json")
    assert "frontier allowance is low" in (d / "pause.json").read_text() and "request" in (d / "pause.json").read_text()
    assert sub("resume", str(d)).returncode == 0
    out, err = p.communicate(timeout=60)
    assert p.returncode == 0, err
    assert json.loads(out)["tainted"] is True


def test_the_fatal_tripwire_never_pauses(world, tmp_path):
    world.passed_check()
    world.scenario(texts=[CP1], tool_uses=[{"name": "Read", "input": {"file_path": "/etc/hosts"}}], sleep=0)
    d = tmp_path / "run"
    d.mkdir()
    (d / "pause-request.json").write_text(json.dumps({"reason": "pending request"}))    # even with a request waiting
    p = start(world, d, "--pause-on-timeout", "--timeout", "60")
    out, err = p.communicate(timeout=60)
    assert p.returncode == 77, err
    assert not (d / "pause.json").exists() and not (d / "ASK.txt").exists() and not world.hermes.exists()
    rec = json.loads(out)
    assert rec["paused"] == 0 and rec["structured_output"] is None


def test_resume_and_abort_refuse_a_run_that_is_not_paused(world, tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    (d / "launch.json").write_text(json.dumps({"schema": 1, "state": "finished", "pid": 1}))
    assert sub("resume", str(d)).returncode == 2
    assert sub("pause", str(d)).returncode == 2


# ---- repair round (adversary of PR 879 at 8646b240) -------------------------------------------------------

def resume_args(world, dead, new, *extra, mode="review"):
    return world.run("--mode", mode, *extra, "-C", str(world.wt), "--schema", str(world.schema), "--json",
                     "--resume-from-evidence", str(dead), "--evidence-dir", str(new), env=env(world))


def test_a_resume_never_gains_or_loses_a_capability(world, tmp_path):
    world.passed_check("read-only")
    world.scenario(texts=[CP1], no_result=True, exit=1)
    plain = tmp_path / "plain"
    assert world.launch("--json", "--evidence-dir", str(plain), mode="read-only", env=env(world)).returncode == 3
    r = resume_args(world, plain, tmp_path / "n1", "--allow-web", mode="read-only")
    assert r.returncode == 2 and "never gains any" in r.stderr                      # M1: the egress probe
    world.passed_check("read-only", "--allow-web")
    web = tmp_path / "web"
    assert world.launch("--json", "--evidence-dir", str(web), "--allow-web", mode="read-only", env=env(world)).returncode == 3
    r = resume_args(world, web, tmp_path / "n2", mode="read-only")
    assert r.returncode == 2 and "never gains any" in r.stderr
    assert len(world.launches()) == 2                                               # neither resume reached claude


def test_a_trusted_resume_keeps_its_trusted_author(world, tmp_path):
    world.scenario(texts=[CP1], no_result=True, exit=1)
    dead = tmp_path / "t"
    assert world.launch("--json", "--evidence-dir", str(dead), "--trusted-author", "djbclark", "--head", world.head,
                        mode="trusted", env=env(world)).returncode == 3
    r = resume_args(world, dead, tmp_path / "n", "--trusted-author", "someone-else", "--head", world.head, mode="trusted")
    assert r.returncode == 2 and "never gains any" in r.stderr


def test_load_resume_refuses_a_head_or_worktree_mismatch(tmp_path):
    mod = load_launcher()
    d = tmp_path / "d"
    d.mkdir()
    stream(d / "stream.jsonl", [asst(text(CP1))])
    (d / "prompt.txt").write_text("p")
    (d / "launch.json").write_text(json.dumps({"schema": 1, "state": "finished", "mode": "review", "worktree": "/w",
                                               "head": "a" * 40}))
    assert mod.load_resume(str(d), "review", "/w", "a" * 40)[2] == ""
    assert "head" in mod.load_resume(str(d), "review", "/w", "b" * 40)[2]
    assert "head" in mod.load_resume(str(d), "review", "/w", None)[2]
    assert "same --mode" in mod.load_resume(str(d), "review", "/other", "a" * 40)[2]
    assert "same --mode" in mod.load_resume(str(d), "read-only", "/w", "a" * 40)[2]


def test_a_resume_after_a_tripwire_says_so_in_the_prompt(world, tmp_path):
    world.passed_check()
    world.scenario(texts=[CP1], tool_uses=[{"name": "Read", "input": {"file_path": "/etc/hosts"}}])
    dead = tmp_path / "dead77"
    assert launch(world, "--evidence-dir", str(dead), prompt="P").returncode == 77
    world.scenario()
    assert resume_args(world, dead, tmp_path / "n").returncode == 0
    assert "LEFT THE BOUNDARY (exit 77)" in prompt_of(world)


def test_the_detached_child_flag_alone_still_prints_the_json_record(world, tmp_path):
    world.passed_check()
    d = tmp_path / "run"
    r = world.launch("--detached-child", "--evidence-dir", str(d), env=env(world))      # no --json given
    assert r.returncode == 0, r.stderr
    rec = json.loads(r.stdout)
    assert rec["tainted"] is False and "paused" in rec


def test_pause_refuses_a_run_that_never_listens(world, tmp_path):
    world.passed_check()
    world.scenario(sleep=3)
    d = tmp_path / "run"
    p = start(world, d)                                 # --json --evidence-dir only, like every bin/review-pr run
    wait_for(d / "launch.json")
    time.sleep(1)
    r = sub("pause", str(d))
    assert r.returncode == 2 and "never reads a pause request" in r.stderr and not (d / "pause-request.json").exists()
    p.communicate(timeout=60)


def test_resume_extend_must_be_finite_and_nonnegative(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    (d / "launch.json").write_text(json.dumps({"schema": 1, "state": "paused", "pid": 1}))
    for bad in ("inf", "nan", "-5"):
        r = sub("resume", str(d), "--extend", bad)
        assert r.returncode == 2 and "finite" in r.stderr, bad


def test_a_launcher_killed_during_a_pause_does_not_leave_a_stopped_claude(world, tmp_path):
    world.passed_check()
    world.scenario(texts=[CP1], sleep=120)
    d = tmp_path / "run"
    p = start(world, d, "--timeout", "1", "--pause-on-timeout")
    wait_for(d / "pause.json")
    pg = json.loads((d / "launch.json").read_text())["child_pgid"]
    assert child_state(d).startswith("T")
    p.kill()
    p.communicate(timeout=30)
    wait_for(d / "done", 40)                            # the watchdog notices the dead launcher and reaps
    end = time.monotonic() + 10
    while pid_alive(pg) and time.monotonic() < end:
        time.sleep(0.2)
    assert not pid_alive(pg)
    assert "launcher was gone" in json.loads((d / "launch.json").read_text())["reason"]
    assert "bin/x.py:12" in (d / "checkpoints.md").read_text()


# ---- round 2 (adversary r2, head 1fc91448) --------------------------------------------------------------

def test_a_detached_run_whose_self_check_fails_is_refused_by_the_caller(world, tmp_path):
    world.scenario(check="leak")                     # no check passed before: the first use fails
    d = tmp_path / "run"
    r = world.launch("--detach", "--evidence-dir", str(d), env=env(world))
    assert r.returncode == 2 and "self-check failed" in r.stderr, r.stdout + r.stderr
    assert world.launches() == [] and not (d / "launch.json").exists()          # nothing was started, no hung run dir


def test_a_detached_child_that_cannot_start_leaves_done_and_result_with_the_failure(world, tmp_path):
    # What the parent cannot see (the cache expired, a refusal, a crash after it returned): the child writes the record.
    world.scenario(check="leak")
    d = tmp_path / "run"
    r = subprocess.run([sys.executable, "-I", str(LAUNCH), "--mode", "review", "-C", str(world.wt), "--schema", str(world.schema),
                        "-p", "x", "--detach", "--evidence-dir", str(d), "--json", "--detached-child"],
                       env=env(world), capture_output=True, text=True, timeout=120)
    assert r.returncode == 2, r.stdout + r.stderr
    assert (d / "done").read_text() == "exit=2\n"
    rec = json.loads((d / "result.json").read_text())
    assert rec["exit"] == 2 and "self-check failed" in rec["reason"] and rec["structured_output"] is None
    doc = json.loads((d / "launch.json").read_text())
    assert doc["state"] == "finished" and doc["exit"] == 2 and "self-check" in doc["reason"]


def test_a_detached_child_that_is_refused_early_still_leaves_the_record(world, tmp_path):
    world.passed_check()
    d = tmp_path / "run"
    r = subprocess.run([sys.executable, "-I", str(LAUNCH), "--mode", "review", "-C", str(tmp_path / "nowhere"), "--schema", str(world.schema),
                        "-p", "x", "--evidence-dir", str(d), "--detached-child"], env=env(world), capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 2 and (d / "done").read_text() == "exit=2\n"
    assert "no such worktree" in json.loads((d / "result.json").read_text())["reason"]


def stub_claude(tmp_path: Path, wt: Path, events: list, tail: float = 30) -> list:
    """argv of a script that prints init + the given events, then lingers."""
    init = {"type": "system", "subtype": "init", "cwd": str(wt), "tools": ["Glob", "Grep", "Read", "StructuredOutput"],
            "mcp_servers": [], "permissionMode": "default", "additional_directories": []}
    body = "".join(json.dumps(e) + "\n" for e in [init, *events])
    script = tmp_path / "stub-claude.py"
    script.write_text("import sys, time\nsys.stdout.write(%r)\nsys.stdout.flush()\ntime.sleep(%r)\n" % (body, tail))
    return [sys.executable, str(script)]


def test_a_violation_queued_behind_a_timeout_is_still_judged_and_ends_77(world, tmp_path, monkeypatch):
    mod = load_launcher()
    real = mod.json.loads

    def slow(s, *a, **k):
        if isinstance(s, str) and "SLOWME" in s:
            time.sleep(2.2)                        # the loop is busy on this line when the time limit passes
        return real(s, *a, **k)

    monkeypatch.setattr(mod.json, "loads", slow)
    argv = stub_claude(tmp_path, world.wt, [{"type": "system", "subtype": "SLOWME"}, asst(read("/etc/hosts"))])
    run = mod.run_claude(argv, os.path.realpath(world.wt), "review", 1.0, evidence_dir=tmp_path / "ev")
    assert run.exit == 77, (run.exit, run.reason)
    assert "/etc/hosts" in (tmp_path / "ev" / "stream.jsonl").read_text()


def test_a_pause_found_with_an_event_queued_is_undone_and_retried(world, tmp_path, monkeypatch):
    import threading
    mod = load_launcher()
    d = tmp_path / "ev"
    d.mkdir()
    orig_queue = mod.queue.Queue

    class FirstEmptyIsFalse(orig_queue):
        flaked = False

        def empty(self):
            if not FirstEmptyIsFalse.flaked:
                FirstEmptyIsFalse.flaked = True
                return False                        # "an event arrived while the child was stopped"
            return super().empty()

    sent = []
    real_killpg = os.killpg

    def killpg(pg, sig):
        if sig in (signal.SIGSTOP, signal.SIGCONT):
            sent.append(int(sig))
        return real_killpg(pg, sig)

    monkeypatch.setattr(mod.queue, "Queue", FirstEmptyIsFalse)
    monkeypatch.setattr(mod.os, "killpg", killpg)
    monkeypatch.setattr(mod, "notify_operator", lambda msg: None)
    monkeypatch.setattr(mod, "PAUSE_SETTLE", 0.05)
    mod.update_launch(d, schema=1, state="running", pid=os.getpid(), pid_started=mod.proc_start(os.getpid()))
    (d / "pause-request.json").write_text(json.dumps({"reason": "test"}))
    argv = stub_claude(tmp_path, world.wt, [])

    def answer():
        end = time.monotonic() + 30
        while time.monotonic() < end and not (d / "pause.json").exists():
            time.sleep(0.05)
        (d / "decision.json").write_text(json.dumps({"decision": "abort"}))

    t = threading.Thread(target=answer)
    t.start()
    run = mod.run_claude(argv, os.path.realpath(world.wt), "review", 60.0, evidence_dir=d / "evid", ctl=mod.PauseCtl(d, False, 30))
    t.join()
    mod.update_launch(d, state="finished")         # lets the pause watchdog it started exit
    assert run.pause_aborted
    assert sent[:3] == [int(signal.SIGSTOP), int(signal.SIGCONT), int(signal.SIGSTOP)], sent   # stop, undo, stop again for real


def stopped_run(tmp_path: Path, state: str, mod, alive: bool) -> Path:
    d = Path(tempfile.mkdtemp(prefix=f"run-{state}-{alive}-", dir=tmp_path))
    if alive:
        pid, started = os.getpid(), mod.proc_start(os.getpid())
    else:
        p = subprocess.Popen(["sleep", "0.01"])
        pid, started = p.pid, mod.proc_start(p.pid)
        p.wait()
    (d / "launch.json").write_text(json.dumps({"schema": 1, "state": state, "pid": pid, "pid_started": started}))
    return d


def test_status_reports_an_orphan_for_any_unfinished_run_whose_launcher_is_dead(tmp_path, capsys):
    mod = load_launcher()
    for state, alive, want in (("running", False, True), ("starting", False, True), ("paused", False, True),
                               ("running", True, False), ("finished", False, False)):
        d = stopped_run(tmp_path, state, mod, alive)
        assert mod.subcommand(["status", str(d)]) == 0
        assert json.loads(capsys.readouterr().out)["stopped_orphan"] is want, (state, alive)
    d = stopped_run(tmp_path, "running", mod, False)
    (d / "done").write_text("exit=0\n")
    mod.subcommand(["status", str(d)])
    assert json.loads(capsys.readouterr().out)["stopped_orphan"] is False


def test_the_watchdog_needs_two_dead_polls_in_a_row(tmp_path, monkeypatch):
    mod = load_launcher()
    d = stopped_run(tmp_path, "paused", mod, True)
    seq = iter([False, True, False, False, False, False])
    polls = []
    reaped = []
    monkeypatch.setattr(mod, "WATCHDOG_POLL", 0.01)
    monkeypatch.setattr(mod, "launcher_alive", lambda doc: polls.append(1) or next(seq))
    monkeypatch.setattr(mod, "reap_dead", lambda dd, doc: reaped.append(len(polls)))
    assert mod.subcommand(["watchdog", str(d)]) == 0
    assert reaped == [4]                           # dead, alive (the count restarts), dead, dead: one blip never reaps


def test_a_resume_records_the_parents_resolved_path(world, tmp_path):
    world.passed_check()
    d = dead_run(world, tmp_path)
    link = tmp_path / "link"
    link.symlink_to(d.parent)
    r = world.run("--mode", "review", "-C", str(world.wt), "--schema", str(world.schema), "--json",
                  "--resume-from-evidence", str(link / d.name), "--evidence-dir", str(tmp_path / "new"), env=env(world))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["parent_run"] == str(d.resolve())
    assert json.loads((tmp_path / "new" / "launch.json").read_text())["parent_run"] == str(d.resolve())     # chain_notes follows this


def test_a_chain_resumed_by_relative_path_still_finds_the_ancestors_notes_from_another_cwd(world, tmp_path):
    world.passed_check()
    dead = dead_run(world, tmp_path)
    world.scenario(texts=["CHECKPOINT 3: third note"], no_result=True, exit=1)
    assert world.run("--mode", "review", "-C", str(world.wt), "--schema", str(world.schema), "--json", "--resume-from-evidence",
                     dead.name, "--evidence-dir", "mid", env=env(world), cwd=tmp_path).returncode == 3     # relative paths
    world.scenario()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    r = world.run("--mode", "review", "-C", str(world.wt), "--schema", str(world.schema), "--json", "--resume-from-evidence",
                  str(tmp_path / "mid"), "--evidence-dir", str(tmp_path / "last"), env=env(world), cwd=elsewhere)
    assert r.returncode == 0, r.stderr
    p = prompt_of(world)
    assert "bin/x.py:12" in p and "third note" in p       # the grandparent's notes survive a relative parent_run


# ---- the follow-up to PR 879 (adversary r3 LOWs) -------------------------------------------------------

def test_a_second_detach_into_the_same_run_dir_is_refused_and_leaves_the_first_alone(world, tmp_path):
    world.passed_check()
    world.scenario(texts=[CP1], sleep=6)
    d = tmp_path / "run"
    first = world.launch("--detach", "--evidence-dir", str(d), env=env(world))
    assert first.returncode == 0, first.stderr
    pid = json.loads(first.stdout)["pid"]
    again = world.launch("--detach", "--evidence-dir", str(d), env=env(world))      # before the first one's stream.jsonl exists
    assert again.returncode == 2 and "already holds a detached launch" in again.stderr
    doc = json.loads((d / "launch.json").read_text())
    assert doc["pid"] == pid and doc["state"] in ("starting", "running")
    wait_for(d / "done", 60)
    assert (d / "done").read_text() == "exit=0\n"


def test_a_detached_child_never_writes_a_failure_record_into_a_live_runs_dir(world, tmp_path):
    mod = load_launcher()
    d = tmp_path / "run"
    d.mkdir()
    (d / "stream.jsonl").write_text("")               # the other child already owns this dir
    me = os.getpid()
    mod.update_launch(d, schema=1, state="running", pid=me, pid_started=mod.proc_start(me))
    other = subprocess.Popen(["sleep", "30"])         # the "live launcher" named in launch.json is not the child below
    try:
        mod.update_launch(d, pid=other.pid, pid_started=mod.proc_start(other.pid))
        world.passed_check()
        r = subprocess.run([sys.executable, "-I", str(LAUNCH), "--mode", "review", "-C", str(world.wt), "--schema", str(world.schema),
                            "-p", "x", "--evidence-dir", str(d), "--json", "--detached-child"], env=env(world),
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 2 and "belongs to a live run" in r.stderr
        assert not (d / "done").exists() and not (d / "result.json").exists()
        assert json.loads((d / "launch.json").read_text())["state"] == "running"
    finally:
        other.kill()
        other.wait()


def test_a_sigterm_to_a_detached_child_before_claude_starts_leaves_the_record(world, tmp_path):
    mod = load_launcher()
    d = tmp_path / "run"
    (d).mkdir()
    # a stand-in launch_main that is "still starting" when the abort arrives
    def starting(argv):
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(5)
        return 0

    mod.launch_main = starting
    old = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)}
    try:
        code = mod.main(["--detached-child", "--evidence-dir", str(d)])
    finally:
        for s, h in old.items():
            signal.signal(s, h)
    assert code == 3 and (d / "done").read_text() == "exit=3\n"
    assert "interrupted" in json.loads((d / "result.json").read_text())["reason"]


def test_a_crash_after_a_tripwire_is_still_a_77(tmp_path):
    mod = load_launcher()
    d = tmp_path / "run"
    d.mkdir()

    def trips_then_crashes(argv):
        mod._TRIPPED[:] = [True]
        raise OSError("disk full")

    mod.launch_main = trips_then_crashes
    code = mod.main(["--detached-child", "--evidence-dir", str(d)])
    assert code == 77 and (d / "done").read_text() == "exit=77\n"
    assert "tripwire" in json.loads((d / "result.json").read_text())["reason"]


# ---- the follow-up to PR 906 (adversary LOWs A-C) ----------------------------------------------------

@pytest.fixture
def kept_signals():
    old = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)}
    yield
    for s, h in old.items():
        signal.signal(s, h)


def test_a_tripwire_followed_by_a_full_disk_in_the_cleanup_is_still_a_77(world, tmp_path, monkeypatch, kept_signals):
    world.passed_check()
    world.scenario(tool_uses=[{"name": "Read", "input": {"file_path": "/etc/hosts"}}])        # a real out-of-scope read
    for k, v in world.env().items():
        monkeypatch.setenv(k, v)
    mod = load_launcher()
    real = mod.write_private

    def full_disk(path, text):
        if Path(path).name == "stderr.txt":
            raise OSError(28, "No space left on device")
        return real(path, text)

    monkeypatch.setattr(mod, "write_private", full_disk)
    d = tmp_path / "run"
    code = mod.main(["--mode", "review", "-C", str(world.wt), "--schema", str(world.schema), "-p", "x", "--json",
                     "--evidence-dir", str(d), "--detached-child"])
    assert code == 77 and (d / "done").read_text() == "exit=77\n"
    assert "cannot preserve evidence" in json.loads((d / "result.json").read_text())["reason"]


def test_a_failing_child_of_its_own_run_writes_the_record(tmp_path, kept_signals):
    # In a real --detach the parent records pid=<the child> in launch.json long before a late failure: the child must
    # still write its record (the ownership check is for ANOTHER live launcher, never for itself).
    mod = load_launcher()
    d = tmp_path / "run"
    d.mkdir()
    me = os.getpid()
    mod.update_launch(d, schema=1, state="running", pid=me, pid_started=mod.proc_start(me))
    mod.launch_main = lambda argv: 2
    assert mod.main(["--detached-child", "--evidence-dir", str(d)]) == 2
    assert (d / "done").read_text() == "exit=2\n"


def test_a_signal_right_after_claude_starts_does_not_leave_it_running(world, tmp_path, monkeypatch, kept_signals):
    mod = load_launcher()
    started = []
    real_popen = subprocess.Popen

    class Recording(real_popen):
        def __init__(self, argv, *a, **k):
            super().__init__(argv, *a, **k)
            if "stub-claude.py" in " ".join(map(str, argv)):
                started.append(self)

    def interrupted(d, **kw):
        if "child_pgid" in kw:
            raise mod.Interrupted("signal 15")          # what main()'s handler raises when abort lands here

    monkeypatch.setattr(mod.subprocess, "Popen", Recording)
    monkeypatch.setattr(mod, "update_launch", interrupted)
    argv = stub_claude(tmp_path, world.wt, [], tail=60)
    try:
        with pytest.raises(mod.Interrupted):
            mod.run_claude(argv, os.path.realpath(world.wt), "review", 30.0, evidence_dir=tmp_path / "ev")
        (proc,) = started
        end = time.monotonic() + 10
        while proc.poll() is None and time.monotonic() < end:
            time.sleep(0.1)
        assert proc.poll() is not None, "claude was left running"
    finally:
        for p_ in started:
            if p_.poll() is None:
                os.killpg(p_.pid, signal.SIGKILL)


# ---- the follow-up to PR 917 (adversary LOW-1, LOW-2) --------------------------------------------------

def test_a_signal_during_the_popen_stops_claude_in_a_plain_run_too(world, tmp_path, monkeypatch, kept_signals):
    mod = load_launcher()
    started = []
    real_popen = subprocess.Popen

    class Signalled(real_popen):
        def __init__(self, argv, *a, **k):
            if "stub-claude.py" in " ".join(map(str, argv)):
                os.kill(os.getpid(), signal.SIGTERM)       # abort lands while claude is being started
            super().__init__(argv, *a, **k)
            if "stub-claude.py" in " ".join(map(str, argv)):
                started.append(self)

    monkeypatch.setattr(mod.subprocess, "Popen", Signalled)
    argv = stub_claude(tmp_path, world.wt, [], tail=60)
    try:
        run = mod.run_claude(argv, os.path.realpath(world.wt), "review", 3.0, evidence_dir=tmp_path / "ev")
        assert run.exit == 3 and "signal 15" in run.reason         # the signal that came during the Popen ended the run
        (proc,) = started
        end = time.monotonic() + 10
        while proc.poll() is None and time.monotonic() < end:
            time.sleep(0.1)
        assert proc.poll() is not None, "claude was left running"
    finally:
        for p_ in started:
            if p_.poll() is None:
                os.killpg(p_.pid, signal.SIGKILL)


def test_a_second_signal_during_the_final_kill_does_not_cut_it_short(world, tmp_path, monkeypatch, kept_signals):
    mod = load_launcher()
    real_kill_all = mod.kill_all
    done = []

    def kill_all_after_a_signal(proc, tracked):
        os.kill(os.getpid(), signal.SIGTERM)               # a second abort, in the finally
        real_kill_all(proc, tracked)
        done.append(proc)

    monkeypatch.setattr(mod, "kill_all", kill_all_after_a_signal)
    argv = stub_claude(tmp_path, world.wt, [], tail=60)
    run = mod.run_claude(argv, os.path.realpath(world.wt), "review", 1.0, evidence_dir=tmp_path / "ev")     # ends by timeout
    assert run.exit == 124 and len(done) == 1 and done[0].poll() is not None


def test_a_no_init_tripwire_followed_by_a_full_disk_at_the_record_is_still_a_77(world, tmp_path, monkeypatch, kept_signals):
    stub = tmp_path / "claude-without-init"
    stub.write_text('#!/bin/sh\necho \'{"type":"system","subtype":"ui_invalidate"}\'\n')
    stub.chmod(0o755)
    for k, v in world.env(REVIEW_LAUNCH_CLAUDE=str(stub)).items():
        monkeypatch.setenv(k, v)
    mod = load_launcher()
    monkeypatch.setattr(mod, "ensure_check", lambda binary, mode, model=None: (True, "test", None))
    real = mod.write_private
    failed = []

    def full_once(path, text):
        if Path(path).name == "result.json" and not failed:
            failed.append(path)
            raise OSError(28, "No space left on device")        # launch_main's own record; the wrapper's retry works
        return real(path, text)

    monkeypatch.setattr(mod, "write_private", full_once)
    d = tmp_path / "run"
    code = mod.main(["--mode", "review", "-C", str(world.wt), "--schema", str(world.schema), "-p", "x", "--json",
                     "--evidence-dir", str(d), "--detached-child"])
    assert failed and code == 77 and (d / "done").read_text() == "exit=77\n"
    assert "no init event" in json.loads((d / "result.json").read_text())["reason"] or "tripwire" in (d / "result.json").read_text()
