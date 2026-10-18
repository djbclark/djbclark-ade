"""claude/hooks/bash_habits_gate.py: bare sed and a filter's status read as the command's are
denied; `sudo -n` without `-k` gets a warning. Cases are the 2026-10-18 slips plus the forms
this machine's agents use every day, which must keep passing."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "claude" / "hooks" / "bash_habits_gate.py"


def run(command, tool="Bash", env=None):
    r = subprocess.run([sys.executable, str(HOOK)],
                       input=json.dumps({"tool_name": tool, "tool_input": {"command": command}}),
                       capture_output=True, text=True, timeout=30, env=env)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None


def denied(command):
    out = run(command)
    return bool(out) and out.get("permissionDecision") == "deny"


@pytest.mark.parametrize("command", [
    "sed -n 2134,2138p bin/acp-dispatch",                                   # 2026-10-18 slip 1
    "head -30 f.py; sed -n 1,20p f.py | gsed -n 1,20p >/dev/null",          # slip 2
    "rg -l x . | xargs sed -i 's/a/b/'",
    "FOO=1 sed -e s/a/b/ f",
    "cd /tmp && sudo sed -i '' f",
    "x=$(sed -n 1p f)",
])
def test_bare_sed_is_denied(command):
    assert denied(command)


@pytest.mark.parametrize("command", [
    "gsed -n 1,20p f",
    "/usr/bin/sed -n 1p f",                                # a deliberate BSD call
    "echo 'use sed here' && rg sed docs/",                 # words in quotes or as arguments
    "git commit -m \"sed is BSD\" -- f",
    "cat <<'EOF' > f\nsed -n 1p x\nEOF",                   # heredoc body
    "ls  # sed later",
])
def test_sed_mentions_and_gsed_pass(command):
    assert not denied(command)


@pytest.mark.parametrize("command", [
    # the 2026-10-18 slip: the refused merge's status was tail's, so push ran
    "git merge --ff-only b 2>&1 | tail -2 && git push -q origin master",
    "make 2>&1 | tail -5 || echo failed",
    "pytest -q | tail -3; echo \"rc=$?\"",
    "cmd | head -1\necho rc=$?",
    "x=$(git log | head -1) && echo $x",
    "cmd |& tee log && next",
])
def test_filter_status_read_as_the_commands_is_denied(command):
    assert denied(command)


@pytest.mark.parametrize("command", [
    "cmd > out.log 2>&1; echo \"rc=$?\" > out.rc; tail -5 out.log",   # the documented form
    "git rebase master 2>&1 | tail -5; git status --short",           # status not read
    "launchctl list | rg -q label && echo loaded",                    # rg's status is the point
    "ps ax | grep -q foo || start foo",
    "set -o pipefail; make 2>&1 | tail -5 && echo ok",
    "make | tail -3; echo ${PIPESTATUS[0]}",
    "a && b | tail -2",                                               # nothing reads tail's
    "cmd 2>&1 | tail -3",
    "echo 'x | tail && y'",
])
def test_status_safe_pipelines_pass(command):
    assert not denied(command)


def test_sudo_n_without_k_is_warned_not_denied():
    out = run("sudo -n /usr/bin/pmset -g")
    assert out and "permissionDecision" not in out and "sudo -k -n" in out["additionalContext"]


@pytest.mark.parametrize("command", ["sudo -k -n /usr/bin/true", "sudo -kn true", "sudo ls"])
def test_sudo_k_n_and_plain_sudo_are_quiet(command):
    assert run(command) is None


def test_other_tools_and_the_off_switch_pass():
    assert run("sed -n 1p f", tool="Grep") is None
    assert run("sed -n 1p f", env=dict(os.environ, BASH_HABITS_GATE_OFF="1")) is None


def raw(payload, *args):
    return subprocess.run([sys.executable, str(HOOK), *args], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=30)


def test_codex_mode_denies_with_exit_2_and_the_reason_on_stderr():
    r = raw({"tool_name": "Bash", "tool_input": {"command": "sed -n 1p f"}}, "--codex")
    assert r.returncode == 2 and "gsed" in r.stderr and r.stdout == ""
    r = raw({"tool_name": "Bash", "tool_input": {"command": ["bash", "-lc", "x | tail && y"]}},
            "--codex")
    assert r.returncode == 2
    assert raw({"tool_name": "Bash", "tool_input": {"command": "gsed -n 1p f"}},
               "--codex").returncode == 0


def test_cursor_mode_answers_permission():
    out = json.loads(raw({"command": "sed -n 1p f", "cwd": "/tmp"}, "--cursor").stdout)
    assert out["permission"] == "deny" and "gsed" in out["agent_message"]
    assert json.loads(raw({"command": "ls"}, "--cursor").stdout) == {"permission": "allow"}
    warn = json.loads(raw({"command": "sudo -n true"}, "--cursor").stdout)
    assert warn["permission"] == "allow" and "sudo -k -n" in warn["agent_message"]


def test_garbage_input_fails_open():
    r = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True,
                       text=True, timeout=30)
    assert (r.returncode, r.stdout) == (0, "")
