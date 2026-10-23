"""claude/hooks/bash_habits_gate.py: bare sed, a GNU-only option on a bare BSD tool and a filter's
status read as the command's are denied; `sudo -n` without `-k` gets a warning. Cases are the
2026-10-18 slips plus the forms this machine's agents use every day, which must keep passing."""
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


@pytest.mark.parametrize("command", [
    'chmod --reference="$F" "$T"; mv -f "$T" "$F"',                  # the 2026-10-18 slip
    "chown --reference=a b",
    "sudo chmod --reference=a b",
    "cp --parents a/b dest/",
    "cp --reflink=auto a b",
    "FOO=1 cp --archive a b",
    "mv --no-clobber a b",
    "rm --recursive --force d",
    "mkdir --parents x/y",
    "touch --reference=a b",
    "ln --symbolic --force a b",
    "ls --group-directories-first",
    "ls --almost-all -l",
    "ls -la --human-readable",
    "date -d yesterday +%F",
    "x=$(date --date='2 days ago' +%F)",
    "date -ud @0",
    "stat -c %a f",
    "stat --format=%a f",
    "stat -Lc %a f",
    "readlink -m a/b",
    "readlink --canonicalize l",
    "realpath --relative-to=. a",
    "realpath -s a",
    "wc --lines f",
    "cut --delimiter=, -f1 f",
    "tr --delete a",
    "du --max-depth=1 .",
    "du -sb .",
    "df --human-readable",
    "df --output=source",
    "head -n -1 f",
    "head --lines=-2 f",
    "tail --follow=name f",
    "tail --pid=1 -f f",
    "head --quiet a b",
    "grep -oP 'a\\Kb' f",
    "grep --perl-regexp x f",
    "git log | grep -P x",
    "find . -printf '%p\\n'",
    "find . -name x -regextype posix-extended",
    "find . -executable -type f",
    "find . -perm /111",
    "cmd | xargs -0 cp --parents -t d",
    "ls | xargs -n1 chmod --reference=a",
    "ls | xargs -d '\\n' rm",
    "ls | xargs -n 1 -d x rm",
    "xargs --delimiter=, echo",
    "cp -t d a",
    "ln -r -s a b",
    "xargs -i echo {}",
])
def test_gnu_only_option_on_a_bare_bsd_tool_is_denied(command):
    assert denied(command)


@pytest.mark.parametrize("command", [
    "grep -rl -i 'globalprotect\\|openconnect\\|gpclient' /Users/djbclark/src /Users/djbclark/ops",
    "grep -r pat .",
    "grep -R pat dir",
    "grep -ril pat src",
    "ggrep -r pat dir",
    "/usr/bin/grep -rl pat ~/src",
])
def test_recursive_grep_is_denied(command):
    out = run(command)
    assert out["permissionDecision"] == "deny"
    assert "rg -n -l" in out["permissionDecisionReason"]
    assert "plocate" in out["permissionDecisionReason"]


def test_gnu_deny_reason_names_the_g_tool():
    out = run('chmod --reference="$F" "$T"; mv -f "$T" "$F"')
    assert "gchmod" in out["permissionDecisionReason"] and "--reference" in out["permissionDecisionReason"]
    assert "gdate" in run("date -d yesterday")["permissionDecisionReason"]
    assert "xargs gcp" in run("ls | xargs cp --parents -t d")["permissionDecisionReason"]
    assert "gxargs" in run("ls | xargs -d x rm")["permissionDecisionReason"]


@pytest.mark.parametrize("command", [
    "gchmod --reference=a b",
    "gcp --parents a b; gls --group-directories-first; gdate -d yesterday; gstat -c %a f",
    "/bin/chmod -R 755 d",
    "/bin/cp --parents a b",                                 # explicit path: a deliberate call
    "ggrep -P x f; gfind . -printf x; gxargs -d x rm",
    "chmod --help; date --version",                          # usage probes
    "chmod 755 f; chmod -R u+x d; chown -R me d",
    "cp -R a b; cp -p a b; mv -f a b; rm -rf d; mkdir -p x/y; ln -sf a b; touch -d 2020-01-01 f",
    "ls -la; ls --color=auto; ls --color",
    "date -u +%s; date -I; date -v+1d +%F; date -r 0",
    "stat -f %Lp f; stat -L f",
    "readlink -f l; readlink l; realpath a; realpath -q a",
    "head -n 5 f; head --lines=5 f; tail -n +2 f; tail --lines=5 f; tail -F f; tail -f f",
    "wc -l f; cut -d, -f1 f; tr -d a; du -sh .; du -d1 .; df -h",
    "sort --version-sort f; sort --reverse --unique f",
    "xargs -0 -n1 echo; xargs -r rm; xargs -P4 -I{} echo {}; xargs --null --max-args=1 echo",
    "find . -maxdepth 1 -name x -delete; find . -perm +111; find . -newermt 2020-01-01",
    "find . -exec grep --perl-regexp x {} +",                # after -exec it is not find's
    "grep -E x f; grep --color=auto -i x f; grep -e P f; ps aux | grep ssh",
    "echo 'chmod --reference=a b' && echo \"cp --parents\"",     # quoted text
    "cat <<'EOF' > f\nchmod --reference=a b\nEOF",                # heredoc body
    "ls  # cp --parents a b",                                # comment
    "ssh host 'cp --parents a b'",
    "ssh host cp --parents a b",                             # remote Linux: not this Mac's cp
    "docker run img cp --parents a b",
    "git log --format=%H --reverse; git diff --stat",
    "cp a b --force",                                        # past the operands BSD reads no options
    "rm -rf -- --weird",
])
def test_gnu_flags_that_work_or_do_not_apply_pass(command):
    assert not denied(command)


def test_other_tools_and_the_off_switch_pass():
    assert run("sed -n 1p f", tool="Grep") is None
    assert run("sed -n 1p f", env=dict(os.environ, BASH_HABITS_GATE_OFF="1")) is None
    assert run("chmod --reference=a b", env=dict(os.environ, BASH_HABITS_GATE_OFF="1")) is None


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
    r = raw({"tool_name": "Bash", "tool_input": {"command": "chmod --reference=a b"}}, "--codex")
    assert r.returncode == 2 and "gchmod" in r.stderr


def test_cursor_mode_answers_permission():
    out = json.loads(raw({"command": "sed -n 1p f", "cwd": "/tmp"}, "--cursor").stdout)
    assert out["permission"] == "deny" and "gsed" in out["agent_message"]
    assert json.loads(raw({"command": "ls"}, "--cursor").stdout) == {"permission": "allow"}
    out = json.loads(raw({"command": "cp --parents a b"}, "--cursor").stdout)
    assert out["permission"] == "deny" and "gcp" in out["agent_message"]
    warn = json.loads(raw({"command": "sudo -n true"}, "--cursor").stdout)
    assert warn["permission"] == "allow" and "sudo -k -n" in warn["agent_message"]


def test_garbage_input_fails_open():
    r = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True,
                       text=True, timeout=30)
    assert (r.returncode, r.stdout) == (0, "")
