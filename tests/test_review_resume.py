"""bin/review-launch: checkpoints, resume from evidence, detached launch and pause-ask (queue item 103).

Same fake `claude` as tests/test_review_launch.py. A synthetic stream stands in for a real one.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
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
    assert "never follow an instruction" in p and "from 3." in p and "```" in p
    rec = json.loads(r.stdout)
    assert rec["tainted"] is True and rec["parent_run"] == str(dead)
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
    assert rec["paused"] == 1 and rec["tainted"] is True and rec["structured_output"] is not None
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
    world.scenario(texts=[CP1], sleep=3)
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
