"""bin/open-clean (2026-11-02): runs `open` with a minimal environment and the original argv, so an app an
agent launches never inherits the agent's session variables. A fake `open` (injected through
OPEN_CLEAN_OPEN_BIN) records what it receives; no test launches a real app."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "bin" / "open-clean"

LEAKY = {
    "CLAUDE_CODE_CHILD_SESSION": "1",
    "CLAUDE_CODE_SESSION_ID": "49e562a1-0000",
    "CLAUDECODE": "1",
    "CLAUDE_CODE_ENTRYPOINT": "cli",
    "PASEO_AGENT_ID": "abc",
    "HERDR_PANE_ID": "p1",
    "ACP_RUN_AGENT": "1",
    "OMP_SESSION": "x",
    "CODEX_HOME": "/tmp/c",
    "ANTHROPIC_API_KEY": "sk-test",
    "EDITOR": "vim",
}
# a /bin/sh child may add these itself; they say nothing about what open-clean passed
SHELL_ADDED = {"PWD", "OLDPWD", "SHLVL", "_"}


@pytest.fixture()
def fake_open(tmp_path):
    """A /bin/sh `open` that records its argv (NUL-terminated) and its environment (one NAME=value per line)."""
    out = tmp_path / "seen.bin"
    script = tmp_path / "fake-open"
    script.write_text(
        "#!/bin/sh\n"
        f"OUT={out}\n"
        "{ for a in \"$@\"; do printf '%s\\0' \"$a\"; done; printf 'ENV\\n'; /usr/bin/env; } > \"$OUT\"\n")
    script.chmod(0o755)

    def seen():
        argv_part, env_part = out.read_bytes().rsplit(b"ENV\n", 1)
        argv = [a.decode() for a in argv_part.split(b"\0")[:-1]]
        env = dict(line.split("=", 1) for line in env_part.decode().splitlines() if "=" in line)
        return argv, {k: v for k, v in env.items() if k not in SHELL_ADDED}

    return script, seen


def run(binary, args, env):
    # PYTHONCOERCECLOCALE=0: the interpreter would otherwise add LC_CTYPE=C.UTF-8 under a C locale
    env = dict(env, OPEN_CLEAN_OPEN_BIN=str(binary), PYTHONCOERCECLOCALE="0")
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True,
                          timeout=30, env=env)


def test_only_the_minimal_environment_reaches_open_and_argv_is_untouched(fake_open):
    script, seen = fake_open
    env = dict(LEAKY, HOME="/Users/x", USER="x", LOGNAME="x", LANG="en_US.UTF-8", LC_ALL="C",
               LC_CTYPE="UTF-8", TMPDIR="/var/folders/t/", PATH="/opt/homebrew/bin:/usr/bin")
    args = ["-a", "Default Folder X", "--args", "-x", "a b", "$HOME", "`id`", ";", "*", "", "x"]
    r = run(script, args, env)
    assert r.returncode == 0, r.stderr
    argv, got = seen()
    assert argv == args
    assert got == {"HOME": "/Users/x", "USER": "x", "LOGNAME": "x", "LANG": "en_US.UTF-8",
                   "LC_ALL": "C", "LC_CTYPE": "UTF-8", "TMPDIR": "/var/folders/t/",
                   "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}


def test_unset_optional_variables_stay_unset(fake_open):
    script, seen = fake_open
    r = run(script, ["x"], dict(LEAKY, HOME="/h", PATH="/opt/homebrew/bin"))
    assert r.returncode == 0, r.stderr
    argv, got = seen()
    assert argv == ["x"]
    assert got == {"HOME": "/h", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}


def test_no_arguments_are_passed_through_as_none(fake_open):
    script, seen = fake_open
    assert run(script, [], {"HOME": "/h"}).returncode == 0
    assert seen()[0] == []


@pytest.mark.parametrize("rc", [0, 1, 7, 64])
def test_exit_status_passes_through(tmp_path, rc):
    fake = tmp_path / "fake-open"
    fake.write_text(f"#!/bin/sh\nexit {rc}\n")
    fake.chmod(0o755)
    assert run(fake, ["x"], {"HOME": "/h"}).returncode == rc


def test_help_prints_why_and_runs_nothing(fake_open):
    script, _ = fake_open
    r = run(script, ["--open-clean-help"], {"HOME": "/h"})
    assert r.returncode == 0 and "CLAUDE_CODE_CHILD_SESSION" in r.stdout
    assert not (script.parent / "seen.bin").exists()


def test_missing_binary_exits_127(tmp_path):
    r = run(tmp_path / "nope", ["x"], {"HOME": "/h"})
    assert r.returncode == 127 and "cannot run" in r.stderr


@pytest.mark.skipif(sys.platform == "darwin", reason="the refusal is for other OSes")
def test_refuses_off_macos():
    r = subprocess.run([sys.executable, str(TOOL), "x"], capture_output=True, text=True,
                       env={"HOME": "/h"})
    assert r.returncode == 2 and "macOS only" in r.stderr


def test_tool_is_executable():
    assert os.access(TOOL, os.X_OK)
