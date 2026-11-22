"""claude/hooks/bash_habits_gate.py: bare sed, a GNU-only option on a bare BSD tool and a filter's
status read as the command's are denied; `sudo -n` without `-k` gets a warning. Cases are the
2026-10-18 slips plus the forms this machine's agents use every day, which must keep passing."""
import json
import os
import subprocess
import sys
import time
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


@pytest.mark.parametrize("mode", ["--claude", "--codex", "--cursor"])
@pytest.mark.parametrize("command", ["echo earlier; sed -n 1p f", "echo earlier && grep -r x ."])
def test_denial_says_nothing_ran_and_whole_command_needs_rerun(mode, command):
    payload = ({"command": command} if mode == "--cursor" else
               {"tool_name": "Bash", "tool_input": {"command": command}})
    result = subprocess.run([sys.executable, str(HOOK), mode], input=json.dumps(payload),
                            capture_output=True, text=True, timeout=30)
    if mode == "--codex":
        assert result.returncode == 2
        message = result.stderr
    else:
        assert result.returncode == 0
        output = json.loads(result.stdout)
        if mode == "--cursor":
            assert output["permission"] == "deny"
            message = output["agent_message"]
            assert output["user_message"] == message
        else:
            assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
            message = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert "NOTHING in this command ran" in message
    assert "no earlier part executed" in message
    assert "re-run the whole command" in message


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
    "x=$(echo a,b | cut --delimiter=, -f1) && echo $x",     # inside the group still denied
    "gh api x $(echo a | cut --delimiter=, -f1):y --jq .z",
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
    # text after the `)` of a $(... | tool ...) group belongs to the outer command (2026-11-02)
    "gh api repos/o/r/compare/m...$(echo $r|cut -d/ -f1):master --jq .x",
    "git log $(git rev-parse HEAD | cut -c1-7)..HEAD --format=%H",
    "echo $(echo a | tr -d a) --version-sort",
    # a filter that ends a substitution is not the status `&&` reads (Codex review of PR 254)
    "echo $(printf x | cat) && echo done",
    "cat <(printf x | cat) && echo done",
    # a regex or extended-glob group is not a substitution: nothing after its `)` is trimmed (Codex review of PR 254, round 3)
    "[[ $tool =~ ^(awk|sed)$ ]] && echo recognized",
    "ls @(awk|sed)",
    # the substitution opens in one pipeline and closes in another
    "gh api x $(echo $r && echo a | cut -d/ -f1):master --jq .y",
    # an escaped `$` is not a substitution opener (Codex review of PR 254, round 4)
    "[[ $tool =~ \\$(awk|sed) ]] && echo recognized",
    # nested substitutions: each body is its own command, the outer keeps the text after the `)`
    "gh api x $(echo $(echo a | cut -d/ -f1) | cut -d/ -f1):master --jq .y",
    # an arithmetic expansion runs no command (Codex review of PR 254, round 5)
    "sed=2; echo $((sed + 1))",
    "echo $((stat -c))",
    "echo $(( (1 + 2) * 3 )) | cut -d/ -f1",
    "sed=2; echo $((1<(sed)))",
    # Escaped inner backticks execute only portable commands.
    r"x=$((`echo \`printf 1 | gsed -n 1p\`` + 1))",
    r"x=$((`echo \`printf 1\`` + 1))",
])
def test_gnu_flags_that_work_or_do_not_apply_pass(command):
    assert not denied(command)


@pytest.mark.parametrize("command", [
    # an escaped paren is argument content, not a subshell close, so the GNU option after it counts
    "echo x | cut -d\\) --complement -f1",
    "find . -name foo\\) -printf '%p\\n'",
    # a plain `(a | tail)` group still hands tail's status to `&&`
    "(git merge --ff-only x | tail -2) && git push",
    # the status check reads the whole outer pipeline, trimmed or not (Codex review of PR 254)
    "git merge --ff-only topic | tee $(printf /tmp/merge.log | cat -) && git push",
    "(x=$(false | tail -2)) && printf PUSHED",
    # an escaped paren after a regex group, and a plain pipe after a closed substitution, stay checked
    "echo x | grep -E '^(a|b)' | cut -d\\) --complement -f1",
    "x=$(echo a | cut -d, -f1) && ls | cut --complement -f1",
    # the outer command keeps its own options when a substitution sits among its arguments (Codex review of PR 254, round 4)
    "cut -d$(printf , | cut -c1) --complement -f1 f",
    "diff <(sort a | head -1) <(ls) --brief --ignore-matching-lines=x; stat --format=%a $(ls | head -1) f",
    # a GNU option inside any substitution body is denied, lone or nested
    "git log --since=$(date -d yesterday +%F)",
    "echo $(echo $(echo a | cut --complement -f1) | cut -d/ -f1)",
    "echo $(( $(date -d x +%s) + 1 ))",
    "x=$((`date -d yesterday +%s` + 1))",
    "x=$((sed -n 1p f); printf x)",
    # Escaped backticks belong to a nested command, not to the outer pair.
    r"x=$((`echo \`printf 1 | sed -n 1p\`` + 1))",
    r"x=$((`echo \`printf 1 | cut --complement -f1\`` + 1))",
    r"x=$((`echo \`date -d yesterday +%s\`` + 1))",
])
def test_escaped_parens_and_subshell_groups_stay_checked(command):
    assert denied(command)


def test_other_tools_and_the_off_switch_pass():
    assert run("sed -n 1p f", tool="Grep") is None
    assert run("sed -n 1p f", env=dict(os.environ, BASH_HABITS_GATE_OFF="1")) is None
    assert run("chmod --reference=a b", env=dict(os.environ, BASH_HABITS_GATE_OFF="1")) is None


def raw(payload, *args):
    return subprocess.run([sys.executable, str(HOOK), *args], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("command", [
    # the real 2026-10-24 slip: a long peer message written via heredoc arrived cut off
    # mid-sentence (632 bytes of 3178) because the delimiter was never reached — bash wrote the
    # partial body, warned on stderr and exited 0, so nothing reported an error.
    "cat > /tmp/msg.md <<'EOF'\nline one\nline two, no delimiter ever\n",
    "cat <<EOF\ntext\n",
    "cat <<'A'\none\nA\ncat <<'B'\ntwo\n",                      # the SECOND one is unclosed
    "peer_mail.py send --text \"$(cat <<'EOF'\nbody\n)\"",      # unclosed inside a substitution
])
def test_unterminated_heredoc_is_denied(command):
    assert denied(command)


@pytest.mark.parametrize("command", [
    "cat > f <<'EOF'\nhello\nEOF\n",
    "cat > f <<EOF\nhello\nEOF\n",
    "cat > f <<'EOF'\nDanny's rule (really)\nEOF\n",            # apostrophes are fine when closed
    "cat <<'A'\none\nA\ncat <<'B'\ntwo\nB\n",                   # two, both closed
    "cat <<-'EOF'\n\tbody\n\tEOF\n",                            # tab-indented terminator
    "cat <<'EOF' | wc -l\nhello\nEOF\n",                        # in a pipeline
    "cat <<'EOF'\nsay EOF now\nEOF\n",                          # delimiter word inside the body
    "echo a \\<\\< b\n",                                        # an escaped << is a literal
    "rg -n '<<EOF' docs/\n",                                    # inside a quoted string
    "rg -n \"<<'EOF'\" docs/\n",
    "rg -n pattern /tmp/file\n",                                # no heredoc at all
])
def test_closed_or_non_heredocs_pass(command):
    assert not denied(command)


@pytest.mark.parametrize("command", [
    'echo "$(cat <<EOF\nbody\n)"',
    'echo "$(echo \"$(cat <<EOF\nbody\n)\")"',
    'echo "`cat <<EOF\nbody\n`"',
])
def test_unterminated_substitution_heredocs_still_deny(command):
    assert denied(command)


@pytest.mark.parametrize("command", [
    'echo "$(cat <<EOF\nbody\nEOF\n)"',
    "cat <<'OUTER'\nexample \"$(cat <<INNER\nbody\n)\"\nOUTER\n",
])
def test_closed_substitution_and_outer_heredoc_examples_pass(command):
    assert not denied(command)


@pytest.mark.parametrize("command", [
    "echo $(cat <<EOF\nbody\nEOF\n)",
    "echo $(cat <<'EOF'\nbody\nEOF\n)",
    "echo `cat <<EOF\nbody\nEOF\n`",
])
def test_verified_substitution_heredoc_terminators_survive_rescan(command):
    assert not denied(command)


@pytest.mark.parametrize("command", [
    "echo \"$(cat <<'EOF'\ntext )\nEOF\n)\"",
    "echo \"$(cat <<'EOF'\ntext ( )\nEOF\n)\"",
    "echo \"$(echo $(cat <<'EOF'\ntext )\nEOF\n))\"",
    "echo \"$(cat <<'A' <<'B'\n)\nA\n( )\nB\n)\"",
])
def test_parentheses_inside_substitution_heredoc_are_data(command):
    assert not denied(command)


@pytest.mark.parametrize("command", [
    "echo $((1 << 2))",
    "((mask = 1 << 3))",
    'echo "$((1 << 2))"',
    "echo $((mask << bits))",
    "((mask = mask << bits))",
    "echo $((1 <<\n2))",
    'echo "$((1 <<\n2))"',
])
def test_arithmetic_shifts_are_not_heredoc_redirections(command):
    assert not denied(command)


@pytest.mark.parametrize("command", [
    "echo $((1 + $(cat <<EOF\nbody\n)))",
    'echo "$((1 + $(cat <<EOF\nbody\n)))"',
    "echo $((1 + $(sed -n 1p file)))",
    "echo $((1 + `sed -n 1p file`))",
])
def test_arithmetic_still_checks_live_command_substitutions(command):
    assert denied(command)


@pytest.mark.parametrize("command", [
    'echo "$((true); gh run watch 123)"',
    'echo $((true); gh run watch 123)',
    'echo "$((cat <<\'EOF\'\ntext )\nEOF\n); gh run watch 123)"',
    'echo $((cat <<\'EOF\'\ntext )\nEOF\n); gh run watch 123)',
])
def test_subshell_form_substitutions_preserve_live_watcher_checks(command):
    assert denied(command)


@pytest.mark.parametrize("quoted", [False, True])
@pytest.mark.parametrize("tail,blocked", [
    ("gh run watch 123", True),
    ("gh run view 123", False),
    ("gh run watch 123 --interval 60", False),
])
def test_subshell_heredoc_watcher_decision_uses_live_tail(quoted, tail, blocked):
    body = f"$((cat <<'EOF'\ntext )\nEOF\n); {tail})"
    command = f'echo "{body}"' if quoted else f"echo {body}"
    out = run(command)
    if blocked:
        assert out and out.get("permissionDecision") == "deny"
        assert "watch" in out["permissionDecisionReason"]
        assert "unterminated" not in out["permissionDecisionReason"].lower()
    else:
        assert not out or out.get("permissionDecision") != "deny"


@pytest.mark.parametrize("operator,inner", [
    ("<<", "  PY"),
    ("<<", "\tPY"),
    ("<<", "PY "),
    ("<<-", "  PY"),
    ("<<-", "\t PY"),
    ("<<-", "PY\t"),
])
def test_delimiter_looking_python_data_does_not_escape_heredoc(operator, inner):
    command = (
        f"python3 - {operator}'PY'\n"
        'yaml = """\n'
        f"{inner}\n"
        "if: steps.assessment.outcome == 'success'\n"
        '"""\n'
        "PY\n"
    )
    assert not denied(command)
    # Blanking data must not hide a real zsh word after the exact terminator.
    assert denied(command + "echo ==\n")


@pytest.mark.parametrize("operator,terminator", [
    ("<<", "  PY"),
    ("<<", "\tPY"),
    ("<<", "PY "),
    ("<<-", "  PY"),
    ("<<-", "\t PY"),
    ("<<-", "PY\t"),
])
def test_indented_or_suffixed_data_is_not_a_heredoc_terminator(operator, terminator):
    out = run(f"cat {operator}'PY'\nbody\n{terminator}\n")
    assert out["permissionDecision"] == "deny"
    assert "Unterminated heredoc" in out["permissionDecisionReason"]


def test_tab_stripping_heredoc_ends_only_at_its_tab_stripped_delimiter():
    assert not denied("cat <<-'PY'\nbody\n\tPY\n")
    assert denied("cat <<-'PY'\nbody\n\tPY\necho ==\n")


@pytest.mark.parametrize("prefix", [
    "echo '<<true'",
    'echo "<<true"',
    r'echo "escaped \" <<true"',
    r"echo \<\<true",
    "echo text # <<true",
    "echo 'multiline\n<<true\ntext'",
])
@pytest.mark.parametrize("live", ["sed -n 1p f", "echo =="])
def test_quoted_or_escaped_heredoc_examples_do_not_hide_live_commands(prefix, live):
    assert denied(prefix + "\n  true\n" + live + "\n")


def test_two_heredocs_on_one_header_preserve_the_following_shell_command():
    command = "cat <<'A' <<'B'\n== data\nA\n== more data\nB\n"
    assert not denied(command)
    assert denied(command + "sed -n 1p f\n")


@pytest.mark.parametrize("command", [
    "open -a Quicksilver",                                  # the 2026-11-02 leak
    "open https://example.com",
    "/usr/bin/open -a 'Default Folder X'",
    "cd /tmp && open .",
    "make; open -R f",
    "echo go | open -f",
    "FOO=1 open x",
    "env FOO=1 open x",
    "env -u HOME open x",                                   # env without -i still leaks
    "sudo open x",
    "time open x",
    "nohup open -a Ghostty &",
    "ls | xargs open",
    "printf '%s\\n' https://example.com | xargs -n 1 open",  # Codex P2 on #522
    "ls | xargs -n1 open",
    "ls | xargs --max-args=1 open",
    "ls | xargs --max-args 1 open",
    "timeout 5 open x",
    "x=$(open -g y)",
    "(open x)",
])
def test_bare_open_is_denied(command):
    out = run(command)
    assert out and out.get("permissionDecision") == "deny"
    assert "bin/open-clean" in out["permissionDecisionReason"]


@pytest.mark.parametrize("command", [
    "~/src/djbclark-ade/bin/open-clean -a Quicksilver",
    "open-clean https://example.com",
    "env -i HOME=$HOME PATH=/usr/bin /usr/bin/open -a X",   # a scrubbed environment
    "env -i open x",
    "env --ignore-environment open x",
    "sudo env -i open x",
    "xdg-open https://example.com",
    "opencode run x",
    "openssl x509 -in c.pem",
    "cat open; ls open",                                    # a file named open
    "rg -n open src/",
    "git open",
    "echo 'open -a X' > note.txt",                          # inside quotes
    "echo \"open x\"",
    "cat <<'EOF' > f\nopen -a X\nEOF",                      # heredoc body
    "ls  # open x later",
    "./open x",
    "man open",
])
def test_clean_launches_and_other_open_words_pass(command):
    assert not denied(command)


def test_unterminated_heredoc_reason_names_the_consequence():
    """The reason must say bash does not fail, because that is the surprising part."""
    out = run("cat > /tmp/msg.md <<'EOF'\nno terminator\n")
    reason = out.get("permissionDecisionReason", "")
    assert "Unterminated heredoc" in reason
    assert "exits 0" in reason or "partial" in reason.lower()


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


# --- gh watchers (2026-11-14: four `gh run watch` at 3 s emptied the shared 5000/h quota) ---

@pytest.mark.parametrize("command", [
    "gh run watch 123",
    "gh run watch",
    "gh run watch 123 --exit-status",
    "gh run watch 123 -i 30",                           # below 60 s
    "gh run watch 123 --interval 59",
    "gh run watch 123 --interval=5",
    "gh run watch 123 --interval $SECS",                # not provably >= 60
    "gh pr checks 5 --watch",
    "gh pr checks --watch --required",
    "gh pr checks --watch 5 -R o/r",
    "gh pr checks 5 --watch --interval 10",
    "gh pr checks 5 --watch=true",
    "gh -R o/r run watch 123",
    "gh --repo o/r pr checks 5 --watch",
    "git push && gh run watch 9 --exit-status",
    "git push; gh run watch 9",
    "(gh run watch 9)",
    "gh run watch 9 &",
    "echo go | gh run watch 9",
    "x=$(gh run watch 9)",
    "gh run watch $(gh run list -L1 --json databaseId --jq '.[0].databaseId')",
    "timeout 600 gh run watch 9",
    "GH_TOKEN=x gh run watch 9",
    "env GH_PAGER= gh pr checks 5 --watch",
    "nohup gh run watch 9 > w.log 2>&1 &",
    "/opt/homebrew/bin/gh run watch 9",
    "~/ops/site-private-djbclark/bin/bgrun gh run watch 9",
    "~/ops/site-private-djbclark/bin/bg gh run watch 9",
    "rtk gh run watch 9",
    "if true; then gh run watch 9; fi",
    "while true; do gh pr checks 5 --watch; done",
    "bash -c 'gh run watch 9'",
    "bash -lc \"gh run watch 9 --exit-status\"",
    "timeout 9 sh -c 'sleep 1; gh pr checks 5 --watch'",
    "sudo bash -c 'bash -c \"gh run watch 9\"'",
    "ls | xargs -n1 gh run watch",
])
def test_gh_watchers_are_denied(command):
    out = run(command)
    assert out and out.get("permissionDecision") == "deny", command
    reason = out["permissionDecisionReason"]
    assert "item 20" in reason and "5000/h" in reason and "2026-11-14" in reason
    assert "gh run view RUN --json status,conclusion" in reason and "60 s" in reason


@pytest.mark.parametrize("command", [
    "gh run watch 9 --interval 60",                     # the lead's quota-safe single watcher
    "gh run watch 9 -i 120 --exit-status",
    "gh run watch 9 -i=90",
    "gh pr checks 5 --watch --required --interval 60",
    "gh pr checks 5 --watch -i 60",
    "gh run view 9 --json status,conclusion",           # the one-shot
    "gh run view 9 --exit-status",
    "gh run list -L 5",
    "gh pr checks 5",                                   # one-shot, no --watch
    "gh pr checks 5 --required --json name,state",
    "gh pr checks 5 --watch=false",
    "gh pr checks 5 --web",
    "gh pr view 5 --json statusCheckRollup",
    "gh api rate_limit --jq .resources.core",
    "gh workflow run ci.yml",                           # `run` here is not `gh run`
    "echo 'gh run watch 9' > note.txt",                 # quoted: documentation, not a command
    "echo \"gh pr checks 5 --watch\"",
    "cat <<'EOF' > f\ngh run watch 9\nEOF",             # heredoc body
    "cat <<EOF > f\nbash -c 'gh run watch 9'\nEOF",
    "rg -n 'gh run watch' docs/",
    "echo \"bash -c 'gh run watch 9'\"",
    "ls  # gh run watch 9 later",
    "git commit -m 'never gh run watch'",
    "echo gh-run-watch",
    "ghr run watch 9",                                  # another tool
    "bash -c 'gh run view 9 --json status'",
    "until gh run view 9 --json conclusion --jq .conclusion | rg -q .; do sleep 60; done",
])
def test_gh_one_shots_and_mentions_pass(command):
    assert not denied(command), command


def test_gh_watch_denial_is_one_rule_among_the_others_and_names_nothing_ran():
    out = run("echo earlier; gh run watch 9")
    assert out["permissionDecision"] == "deny"
    assert out["permissionDecisionReason"].startswith("NOTHING in this command ran")


@pytest.mark.parametrize("command", [
    "gh api repos/o/r/pulls --paginate | jq -r '.[].number' | xargs -P 6 -I{} gh api repos/o/r/pulls/{}",
    "printf '%s\\n' 1 2 3 | xargs -P4 -n1 gh pr view",
    "seq 300 | xargs --max-procs=8 -I{} gh api issues/{}",
    "seq 300 | xargs -P 0 -I{} sh -c 'gh api issues/{}'",
    "seq 300 | parallel -j6 gh api issues/{}",
])
def test_parallel_gh_fanout_warns_without_denying(command):
    out = run(command)
    assert out and "permissionDecision" not in out, command
    assert "rate_limit" in out["additionalContext"] and "remaining < 500" in out["additionalContext"]


@pytest.mark.parametrize("command", [
    "seq 3 | xargs -n1 gh api issues/1",                # serial
    "seq 3 | xargs -P 1 -I{} gh api issues/{}",
    "seq 3 | xargs -P 6 -I{} echo {}",                  # parallel, but no gh
    "gh api rate_limit",
    "cat <<'EOF' > f\nxargs -P 6 gh api x\nEOF",        # heredoc body
])
def test_serial_or_non_gh_xargs_gives_no_fanout_warning(command):
    out = run(command)
    assert not out or "rate_limit" not in out.get("additionalContext", ""), command


# adversary round 1 on PR 672 (docs paths, quoting, int parsing)

@pytest.mark.parametrize("command", [
    "deadline run --budget 20m --owner x -- gh pr checks 123 --watch --required",   # B1
    "deadline run --budget 20m -- gh run watch 9",
    "bin/gh-pr-checks 123 --watch --required",                                      # B2
    "~/src/djbclark-ade/bin/gh-pr-checks --budget 5m 123 --watch",
    "gh-pr-checks --no-deadline 123 --watch --interval 10",
    "gh run watch 9 --interval 060",                                                # octal in pflag
    "gh run watch 9 --interval 0x3c",
    "gh run watch 9 --interval " + "9" * 5000 + "x",                               # B5 fails closed
    "bin/gh-pr-checks -- 123 --watch",                                              # N2
    "bin/gh-pr-checks --budget 5m -- 123 --watch --required",
    "gh-pr-checks --no-deadline -- 5 --watch",
    "echo \"$(bash -c 'gh run watch 9')\"",                                         # N3
    "out=\"$(sh -c 'gh pr checks 5 --watch')\"",
    "echo it\\'s; bash -c 'gh run watch 9'",                                        # N4
    "# don't spam the API\nbash -c 'gh run watch 9'",
    "true;# don't spam\nbash -c 'gh run watch 9'",                                  # R2b
    "cat <<'EOF' | bash\ngh run watch 9\nEOF",                                      # N7
    "/bin/bash -c 'gh run watch 9'",                                                # B7a
    "bash -o pipefail -c 'gh run watch 9'",                                         # B7b
    "bash --norc -c 'gh run watch 9'",
    "ls | xargs -I{} sh -c 'gh run watch {}'",                                      # B7c
    "bash <<'EOF'\ngh run watch 9\nEOF",                                            # B7d
    "sh <<EOF\ngh pr checks 5 --watch\nEOF",
    "gh run watch 9 --interval \"30\"",
])
def test_adversary_round1_watchers_are_denied(command):
    assert denied(command), command


@pytest.mark.parametrize("command", [
    "deadline run --budget 20m --owner x -- gh pr checks 123 --watch --required --interval 60",
    "bin/gh-pr-checks 123 --watch --required --interval 60",
    "bin/gh-pr-checks 123 --required",
    "deadline start review-123 --budget 2h --owner x",
    "gh run watch 9 --interval \"60\"",                                             # B4
    "gh run watch 9 -i '120'",
    "gh run watch 9 --interval=\"90\"",
    "git commit -m \"deny watchers (bash -c 'gh run watch 9') too\"",              # B3
    "gh pr create --title x --body \"covers wrappers; sh -c 'gh pr checks 5 --watch'\"",
    "cat <<'EOF' > f\nbash <<X\ngh run watch 9\nX\nEOF",
    "bash <<'EOF'\ngh run view 9 --json status\nEOF",
    "gh pr create --title x --body \"Fixes \\`bin/gh-pr-checks\\`; (bash -c 'gh run watch 9') is denied\"",  # R1
    "git commit -m \"a \\$( b; bash -c 'gh run watch 9' c\"",
    "gh pr comment 5 --body \"Fixed in $(git rev-parse HEAD); bash -c 'gh run watch 9' is now denied\"",
])
def test_adversary_round1_false_positives_and_documented_forms_pass(command):
    assert not denied(command), command


def test_gh_watch_fixes_for_the_crash_and_the_backtracking_cases():
    import time
    for cmd in ("gh run watch 9 --interval " + "9" * 5000,            # int() limit: no crash
                "bash " + "--a " * 60 + "x",                           # SHELL_C must not backtrack
                "git commit -m \"; bash " + "--no-verify " * 60 + " done\""):
        t0 = time.monotonic()
        out = run(cmd)
        assert time.monotonic() - t0 < 5, cmd[:40]
        assert not out or out.get("permissionDecision") != "deny" or "gh run watch" in cmd


# gw-02: lead adversary on e7ce14b9 (substitutions, `)#`, timing, continuation, sudo -u)

@pytest.mark.parametrize("command", [
    "out=\"$(gh pr checks 5 --watch)\"",                                            # B1
    "echo \"status: $(gh run watch 9 --exit-status)\"",
    "echo \"`gh run watch 9`\"",
    "echo `gh run watch 9`",
    "echo `bash -c 'gh run watch 9'`",
    "echo \"\\` `bash -c 'gh run watch 9'`\"",
    "x=\"$(echo \"$(gh run watch 9)\")\"",                                           # nested
    "echo \"$(cd \"$d\"; bash -c 'gh run watch 9')\"",                              # R2a
    "echo $(true)#\"\n\" ; bash -c 'gh run watch 9'",                                # B2
    "cat <(true)#\"\n\" ; bash -c 'gh run watch 9'",
    "gh run \\\nwatch 9",                                                           # B5
    "gh pr checks 5 \\\n  --watch",
    "sudo -u x gh run watch 9",
    "sudo -n -u root -H gh pr checks 5 --watch",
    "x=\"$(echo \"it's\")$(gh run watch 9)\"",                                       # C1
    "echo \"$(echo \"it's\")\" && echo \"`gh run watch 9`\"",
    "echo \"$(printf \"%s'\" a) $(gh pr checks 5 --watch)\"",
    "x=\"$(:)\"" + "\"$(:)\"" * 150 + "\"$(gh run watch 9)\"",                       # C2: no cap
    "echo " + "`:`" * 150 + "`gh run watch 9`",
    ": \\\\\ngh run watch 9",                                                       # C3
    "echo done\\\\\ngh run watch 9",
    "cat <<'EOF'\nx \\\nEOF\ngh run watch 9",
    "x\n" + " \n" * 3000 + "bash -c 'gh run watch 9'",                              # C6a
    "echo \"it's done\"; gh run watch 9; echo 'ok'",                                 # F1
    "git commit -m \"fix: don't block\" && gh run watch 9 && echo 'merged'",
    "git push && echo \"PR's up\"\ngh pr checks 5 --watch\necho 'done'",
    "x=\"$(echo \"it's\")\"; gh run watch 9",                                        # G1
    "gh pr comment 5 --body \"$(printf \"Don't merge\")\"; gh run watch 9",
    "echo \"`echo \"it's\"`\"; gh run watch 9",
    "printf $'it\\'s\\n'; gh run watch 9",
    "x=\"$(echo \"it's\")\"; sed -i x f",
    "gh pr comment 5 --body \"$(printf \"Don't merge\")\"; grep -r x .",
    "printf $'it\\'s\\n'; sed -i x f",
    "# don't\ngh run watch 9\necho 'x'",
    "bash \\\n<<'EOF'\ngh run watch 9\nEOF",                                         # F2
    "bash -s \\\n  <<'EOF'\ngh run watch 9\nEOF",
    "cat <<'EOF' | \\\nbash\ngh run watch 9\nEOF",
])
def test_gw02_hidden_watchers_are_denied(command):
    assert denied(command), command


@pytest.mark.parametrize("command", [
    "echo \"\\$(gh run watch 9)\"",                                                 # escaped: text
    "echo \"\\`gh run watch 9\\`\"",
    "echo '$(gh run watch 9)'",
    "echo '`gh run watch 9`'",
    "echo $(true)#\" ; bash -c 'gh run watch 9' ; echo \"",                         # B2 reverse
    "# $(gh run watch 9)\necho hi",
    "out=\"$(gh run view 9 --json status)\"",
    "echo `gh run list -L 3`",
    "sudo -u x gh run view 9",
    "gh run \\\nview 9",
    "x=\"$(gh api rate_limit --jq .resources.core.remaining)\"",
    "git commit -m \"$(printf '%s\\n' 'gate: `gh run watch` denied')\"",              # C1 reverse
    "echo \"$(echo '$(gh run watch 9)')\"",
    "echo \"$(echo \"don't\") ok\"",
    "printf '%s\\n' \"it's\" '$(gh run watch 9)'",                                    # F1 reverse
    "git commit -m \"it's\" -m 'see $(gh run watch 9)'",
    "true;# see 'a | sed -i x f'",                                                      # G2
    "git merge x | tail -2;# $?",
])
def test_gw02_prose_and_one_shots_pass(command):
    assert not denied(command), command


@pytest.mark.parametrize("command", [
    "x\n" + "\n" * 20000 + "y",                      # quadratic in the newline run at 12f56273
    "x\n" + " \n" * 15000 + "y",
    "x=\"$(echo \"" * 50 + ")\"" * 50,               # deep nesting: bodies must not overlap
    "$(" * 100000,
    "echo \"" + "$(" * 100000,
    "echo \"" + "$(" * 4000 + "true" + ")" * 4000 + '"',
    "`" * 100001,
    "echo foo \\\n" * 20000 + "x",                                                  # F3
    "a\\\n" * 100000,
])
def test_long_newline_runs_stay_fast(command):
    r = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True, timeout=8,
                       input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}))
    assert r.returncode == 0, r.stderr


# gw-03: lead review Lows on #672 (rtk proxy, env/nice options)

@pytest.mark.parametrize("command", [
    "sudo -u gh gh run watch 9",                                # option value named gh (adv8 R1)
    "sudo -D /x/gh gh run watch 9",
    "env -u gh gh run watch 9",
    "env -C /opt/gh gh run watch 9",
    "env --chdir /opt/gh gh run watch 9",
    "nice -n 5 env -C /x/gh gh run watch 9",
    "sudo -u gh env -i gh run watch 9",
    "bash -c 'env -u gh gh run watch 9'",
    "deadline run gh --budget 10m -- env -i gh run watch 9",
    "sudo -u me gh-pr-checks 5 --watch",                        # wrapper options before bin/gh-pr-checks (adv8 R2)
    "env -i bin/gh-pr-checks 5 --watch",
    "nice -n 5 bin/gh-pr-checks 5 --watch",
    "env -u X ~/src/djbclark-ade/bin/gh-pr-checks 5 --watch",
])
def test_gw03_option_value_named_gh_and_wrapped_gh_pr_checks(command):
    assert denied(command), command


@pytest.mark.parametrize("command", [
    "sudo -u gh gh run watch 9 -i 60",
    "env -C /opt/gh gh run watch 9 --interval 60",
    "sudo -u me gh-pr-checks 5 --watch --interval 60",
    "sudo -u gh gh run view 9",
])
def test_gw03_option_value_named_gh_compliant_passes(command):
    assert not denied(command), command


@pytest.mark.parametrize("command", [
    "rtk proxy gh run watch 9",
    "rtk proxy gh pr checks 5 --watch",
    "env -i HOME=$HOME PATH=$PATH gh run watch 9",
    "env -u FOO gh run watch 9",
    "env -i -u FOO BAR=1 gh pr checks 5 --watch",
    "nice -n 10 gh run watch 9",
    "nice -10 gh run watch 9",
    "gh pr checks fix-env --watch --required",                  # branch named like a wrapper
    "gh pr checks env --watch",
    "gh run watch 9 -R o/sudo",
    "sudo env -i HOME=$HOME gh run watch 9",
])
def test_gw03_wrapper_options_do_not_hide_a_watcher(command):
    assert denied(command), command


@pytest.mark.parametrize("command", [
    "rtk proxy gh run view 9 --json status",
    "env -i HOME=$HOME gh run view 9",
    "env -u FOO gh run watch 9 --interval 60",
    "nice -n 10 gh run list -L 3",
    "echo env -i gh run watch 9",
    "echo 'rtk proxy gh run watch 9'",
    "gh run watch 9 -R o/env -i 60",                            # compliant watcher, repo named env
    "gh run watch 9 -R o/nice -i 60",
    "gh pr checks nice --watch -i 60",
])
def test_gw03_wrapper_one_shots_and_prose_pass(command):
    assert not denied(command), command


# ---- gw-04: lows from the lead review of #684 ----

@pytest.mark.parametrize("command", [
    'env -i "PATH=$PATH" gh run watch 9',                       # B1: quoted assignment after env
    "env -i 'HOME=/x' gh run watch 9",
    'sudo "FOO=1" gh run watch 9',
    'env -i "A=1" "B=2" gh pr checks 5 --watch',
    "env -iu FOO gh run watch 9",                               # B2: combined short options ending in a value option
    "sudo -Hu me gh run watch 9",
    "sudo -iu me gh run watch 9",
    "nice --adjustment 5 gh run watch 9",
    "command -p gh run watch 9",                                # B3
    "exec -a x gh run watch 9",
    "gh>log run watch 9",                                       # B4: redirection glued to the command word
    "env -i gh>log run watch 9",
    "gh >log run watch 9",
    "gh 2>/dev/null run watch 9",
    "gh > log run watch 9",                                     # operator and target are separate words
    "gh 2> err run watch 9",
    "X=/gh Y=/gh Z=/gh env -i gh run watch 9",                  # B5: the real gh is the 4th candidate
    "env -C /a/gh -C /b/gh -C /c/gh env -i gh run watch 9",
    'env -i A=1 "B=$X" gh run watch 9',                         # lw-01: an unquoted assignment before a quoted one
    'sudo A=1 "B=2" gh run watch 9',
    'env -i HOME=$HOME "PATH=$PATH" gh run watch 9',
    "gh <in run watch 9",                                       # lw-01: input redirection forms of REDIRECT_WORD
    "gh<in run watch 9",
    "gh <<<x run watch 9",
    "gh <&3 run watch 9",
])
def test_gw04_lead_review_lows_are_denied(command):
    assert denied(command), command


@pytest.mark.parametrize("command", [
    'env -i "PATH=$PATH" gh run watch 9 -i 60',
    'env -i "PATH=$PATH" gh run view 9',
    'env -i "PATH=$PATH" echo gh run watch 9',
    "env -iu FOO gh run view 9",
    "sudo -Hu me gh run watch 9 --interval 60",
    "nice --adjustment 5 gh run list -L 3",
    "command -v gh",
    "command -p gh run list",
    "exec -a x gh run view 9",
    "gh>log run view 9",
    "gh run view 9 2>&1 >out",
    "gh > log run view 9",
    'env -i A=1 "B=$X" gh run watch 9 -i 60',                   # lw-01
    'env -i A=1 "B=$X" gh run view 9',
    "gh run view 9 <in",
    "gh <in run view 9",
])
def test_gw04_lead_review_lows_compliant_and_one_shots_pass(command):
    assert not denied(command), command


# --- gs-02 (2026-11-14): an unquoted `=word` (zsh `=cmd` expansion) and backticks / `$(` in a double-quoted `paseo send` argument ---
@pytest.mark.parametrize("command", [
    "echo ===",
    "echo ====; echo next",
    "echo a; echo ==; echo b",
    "echo ==",
    "echo =b",
    'echo ="x"',
    "echo ==$e",
    "print -r -- ===",
    'printf "%s\\n" ===',
    "ls =nonexist",
    "[ a == a ] && echo ok",
    "test a == a",
    "echo a | cat; echo === | cat",
    "x=1 echo ===",
    "echo $(echo ===)",
    "bash -c 'true'; echo ===",
    "(( (a+(b)) == 2 )) && echo ===",              # nested arithmetic parentheses are matched by depth
    "echo a;===",                                   # glued to the operator
    "true&&==x",
    "echo a|===",
])
def test_gs02_unquoted_equals_word_is_denied(command):
    assert denied(command), command
    assert "starts with `=`" in run(command)["permissionDecisionReason"]


@pytest.mark.parametrize("command", [
    "echo =",
    "echo '==='",
    'echo "==="',
    "echo \\===",
    "echo a=b --x=y c==d",
    "x==y",
    "echo =(true)",
    "[[ a == a ]] && echo ok",
    "[[ a == a && b == b ]]; echo ok",
    "(( (a+(b)) == 2 )) && echo ok",
    "[[ a == b ]] || [[ c == d ]]; echo ok",
    "(( 1 == 1 )) && echo ok",
    "echo $((1==1))",
    "if [[ $x =~ ^a ]]; then echo y; fi",
    "echo hi # ===",
    "cat <<'EOF'\n===\n====\nEOF",
    "git diff --stat -- a=b",
    "echo '---'; echo --- ; echo -=-",
    "[ a = a ]",
])
def test_gs02_equals_lookalikes_pass(command):
    assert not denied(command), command


SEND_DENY = [
    'paseo send --json --no-wait ab "see `foo` call"',
    'paseo send ab "x $(date)"',
    'paseo send --json ab "x `y`" --no-wait',
    'paseo agent send ab "run $(x)"',
    'paseo --json send ab "`z`"',
    'env -u A -u B paseo send ab "`z`"',
    'ADE_ALLOW_ARCHIVED_SEND=ab paseo send ab "fix `x`"',
    'r=$(paseo send --json --no-wait ab "the `foo` call")',    # a send inside a substitution body
    'echo $(paseo send ab "`foo`")',
    'cat <(paseo send ab "`foo`")',
    'r="$(paseo send ab "the `foo` call")"',
    'r=$(echo $(paseo send ab "`x`"))',                           # nested bodies: only the worklist reaches the inner send
    'x=`paseo send ab "$(date)"`',
    'echo "`paseo send ab "$(date)"`"',                          # a backtick body inside double quotes
    'paseo send ab "$(echo $(paseo send c "`z`"))"',
    'paseo send ${LEAD} "the `foo` call"',                     # an unquoted ${..} / $(..) target must not end the command
    'paseo send --json --no-wait $(cat id) "the `foo` call"',
    'paseo send $(cat "id file") "the `foo` call"',
    'paseo send `cat id` "the `foo` call"',
    'paseo send $(cat id ) "the `foo` call"',                    # `)` at the start of a word inside the target
    'paseo send ${X:-a } "the `foo` call"',
    'paseo send `echo a; echo b` "the `foo` call"',            # a separator inside the target
    'paseo send ab{c,d} "the `foo` call"',                       # a brace inside a word
    'paseo send ab "n is $(( $(date +%s) + 1 ))"',                # arithmetic holding a real substitution
    'echo hi; paseo send ab "text `x` more"; echo done',
    'paseo send ab "nested $(echo "$(date)") text"',
    'paseo send ab "a" "b `c`"',
    'bg paseo send ab "`x`"',
    'reply="$(paseo send --json ab "see `foo` call")"',          # Codex P2 r4575540753: a quoted substitution is read
    'paseo send --json {} "x `y`"',                                # a `{}` placeholder is a word, not a group brace
    'paseo send ab{} "x `y`"',
    '{ paseo send ab "`x`"; }',                                    # a real group still separates
    'if paseo send ab "`x`"; then true; fi',                       # after a shell keyword
    'timeout 600 paseo send ab "`x`"',                             # after a wrapper and its option value
    'sudo -u me paseo send ab "`x`"',
    'deadline run --max 60 -- paseo send ab "`x`"',
    'A=1 B=2 paseo send ab "`x`"',
    'case $a in x) paseo send ab "`y`";; esac',                    # gs-03: a case arm (first arm shares the `case` command)
    'case $a in (x) paseo send ab "`y`";; esac',
    'case $a in a) true;; x) paseo send ab "`y`";; esac',          # a later arm starts with the pattern word `x)`
    'ssh host paseo send ab "`x`"',                                # the LOCAL shell runs the backtick before ssh starts
    'gtimeout 600 paseo send ab "`x`"',
    'noglob paseo send ab "`x`"',
    'builtin command paseo send ab "`x`"',
    'flock /tmp/f paseo send ab "`x`"',
    'watch -n 60 paseo send ab "`x`"',
    'direnv exec . paseo send ab "`x`"',
    'op run -- paseo send ab "`x`"',
    '{paseo send ab "`x`";}',                                      # no space: zsh reads `{paseo` as the command word
    'nocorrect paseo send ab "`x`"',
    'coproc paseo send ab "`x`"',
    'script -q /dev/null paseo send ab "`x`"',
    'secretspec run -- paseo send ab "`x`"',
    'sudo-secretspec run -- paseo send ab "`x`"',
    'doas paseo send ab "`x`"',
    'gnohup paseo send ab "`x`" &',
    'gnice -n 5 paseo send ab "`x`"',
    'unbuffer paseo send ab "`x`"',
    'uv run paseo send ab "`x`"',
    'genv paseo send ab "`x`"',                                    # gs-04: the four wrappers rv-733 found without a deny row
    'gstdbuf -o L paseo send ab "`x`"',
    'chronic paseo send ab "`x`"',
    'mosh host -- paseo send ab "`x`"',
]


@pytest.mark.parametrize("command", SEND_DENY)
def test_gs02_backtick_or_dollar_paren_in_a_double_quoted_send_argument_is_denied(command):
    assert denied(command), command
    assert "BEFORE paseo starts" in run(command)["permissionDecisionReason"]


@pytest.mark.parametrize("command", [
    "paseo send ab 'see `foo` call'",
    "paseo send ab 'x $(date)'",
    'paseo send ab "plain text, no substitution"',
    'paseo send ab "$LEAD"',
    'paseo send ab "price is \\$5 and \\`quoted\\`"',
    'paseo send ab "\\$(not run)"',
    'paseo send ab "it\'s fine"',
    'echo "`date`"; paseo send ab ok',
    'echo "paseo send `x`"',
    'git commit -m "paseo send `x`"',
    'rg "paseo send `x`" docs',
    "paseo send ab --prompt-file /tmp/m.txt",
    'paseo send ab "retry in $((n*2)) s"',                       # arithmetic runs no command
    'paseo send ab "$(( (a+(b)) * 2 ))"',
    'echo paseo send "$(date)"',                                  # only prints text
    'printf "%s\\n" paseo send "`x`"',
    'paseo send ${LEAD} ok; echo "`date`"',
    'r=$(paseo send --json ab ok); echo "`date`"',
    'echo $(echo send "`x`")',
    '(paseo send ab ok)',
    'paseo agent inspect "$(cat /tmp/id)" --json',
    'paseo run "`x`" --name a',
    "cat > /tmp/m.txt <<'EOF'\nsee `foo` and $(bar)\nEOF\npaseo send ab --prompt-file /tmp/m.txt",
    "# paseo send ab \"`x`\"\necho ok",
    'echo "unterminated paseo send ab "`x`',
    'paseo run --name send "`x`"',                  # `send` appears, but the verb is `run`
    'X="$(date)" paseo send ab ok',                  # before the verb: not an argument of the send
    "cat <<'EOF'\npaseo send ab \"`x`\"\nEOF",        # a heredoc body is data
    'paseo send ab ok; echo "`date`"',               # the substitution belongs to the next command
    'paseo send ab ok && echo "$(date)"',
    'paseo send ab ok | cat "`x`"',
    '(paseo send ab ok) ; echo "`x`"',
    'ls paseo send "$(date)"',                      # Codex P2 r4575540749: `paseo` is data for `ls`, not the command word
    "printf '%s\\n' paseo send \"$(date)\"",
    'rg -e relay.py "$(printf pattern)" docs',
    'cmd paseo send "`x`"',
    'A=1 ls paseo send "`x`"',
    'echo {a,b} "`x`"; paseo send ab ok',           # a brace word is not a group
    'echo x) paseo send "`y`"',                     # gs-03: `echo` is not a sender, whatever follows
    'f) paseo send ab ok',                          # a case-arm pattern word, nothing to run
    'ssh host ls paseo "`x`"',                      # no `send` verb
    '{paseo} ls "`x`"',
])
def test_gs02_send_lookalikes_pass(command):
    assert not denied(command), command


def test_gs02_unclosed_test_blocks_are_linear():
    import time
    from importlib import util
    spec = util.spec_from_file_location("bhg", HOOK)
    mod = util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for blob in ("[[ " * 200000, "(( " * 20000):
        t0 = time.monotonic()
        mod.drop_test_blocks(blob + " echo ok")
        assert time.monotonic() - t0 < 2, blob[:3]



@pytest.mark.parametrize("command", [
    "python3 wait_check.py > out 2>&1 &",
    "sleep 5 &",
    "sleep 5 & echo next",
    "sleep 5 &\necho next",
    "nohup sleep 5 &",
    "setsid sleep 5 > log 2>&1 &",
    "( sleep 5 & )",
    "{ sleep 5 & }",
    "echo $(sleep 5 &)",
    "curl http://h/x?a=1&b=2",
    "echo a && sleep 5 &",
    "sleep 1 & wait; sleep 5 &",
    "job > log 2>&1 & wait-file --timeout 600 log",
    "sleep 1 & wait.sh",
    "sleep 1 & wait-for x",
    "sleep 1 &\nsleep 5 &\nwait\nsleep 9 &",
])
def test_job_control_background_is_denied(command):
    out = run(command)
    assert out and out["permissionDecision"] == "deny", command
    assert "run_in_background" in out["permissionDecisionReason"]
    assert "Nothing ran" in out["permissionDecisionReason"]


@pytest.mark.parametrize("command", [
    "a && b",
    "make 2>&1 | tail -3",
    "echo x >&2",
    "cmd &>file",
    "cmd &>>file",
    "a |& b",
    "cat <&3",
    "x=${y//&/z}; echo $x",
    "[[ a == a && b == b ]] && echo ok",
    "echo 'a & b'",
    'echo "a & b"',
    "echo $'a & b'",
    "curl 'http://h/x?a=1&b=2'",
    "cat <<'EOF'\nsleep 5 &\nEOF",
    "echo hi # sleep 5 &",
    "echo kill %1 and disown",
    "echo 'disown; sleep 5 &'",
    "echo a\\&b",
    "echo $((6 & 3))",
    "sleep 1 & sleep 2 & wait",
    "for n in 1 2; do sleep $n & done\nwait",
    "sleep 1 &\nwait $!",
    "sleep 1 & wait",
    "sleep 1 & wait; echo done",
    "(sleep 1 & wait)",
    "case $x in a) echo a;& b) echo b;; esac",
    "case $x in a) echo a;;& b) echo b;; esac",
])
def test_non_background_ampersands_pass(command):
    assert not denied(command), command


def test_specific_reason_wins_over_background_deny():
    out = run("open x &")
    assert out and "bin/open-clean" in out["permissionDecisionReason"]


def test_background_reason_names_timeout_and_long_job_routes():
    reason = run("sleep 5 &")["permissionDecisionReason"]
    assert "7200000" in reason and "bin/ade-sched" in reason


# zsh reads `$NAME:x` as a history modifier (2026-11-21: `$C:refs/heads/x` pushed `<sha>efs/heads/x`). Every case below is one
# rule branch of `zsh_modifier_word`, probed against /bin/zsh -f; each is its own command, so a mutant that drops one branch
# fails exactly the cases that need it (PR 909 review L4: packed commands let one surviving match satisfy a whole case).
def _assert_zsh_modifier_denied(command):
    out = run(command)
    assert out and out["permissionDecision"] == "deny", command
    assert "${NAME}:" in out["permissionDecisionReason"]


@pytest.mark.parametrize("command", [
    "C=abc1234; git push origin $C:refs/heads/ci/x",
    'git show "$h:c..."',
    "scp $HOST:tmp/x .",                    # `$HOST:t` strips to the tail; `:path` is NOT a modifier (p is not applied)
    "docker pull $IMG:latest",              # `:l`
    "docker tag x $IMG:frontend",           # `:fr` (f is a repeat prefix, then r)
    "echo ok; echo \"a $x:t\" 'b'",
    "cat <<EOF >/dev/null\nplain\nEOF\necho $C:r",
])
def test_zsh_history_modifier_on_bare_variable_is_denied(command):
    _assert_zsh_modifier_denied(command)


@pytest.mark.parametrize("letter", list("aAcehlPqQrstu"))
def test_zsh_modifier_each_letter_is_denied(letter):
    _assert_zsh_modifier_denied(f"echo $C:{letter}" + ("/a/b/" if letter == "s" else ""))


def test_zsh_modifier_ampersand_is_denied_in_double_quotes():
    _assert_zsh_modifier_denied('echo "$C:&"')            # unquoted `&` is the background operator (denied anyway)


@pytest.mark.parametrize("command", [
    "echo $@:t", "echo $*:t", "echo $#:t", "echo $?:t", "echo $$:t", "echo $!:t", "echo $-:t",   # special parameters
    "echo $1:h", "echo $0:t", "echo $10:h",                                                       # positionals
])
def test_zsh_modifier_special_parameters_and_positionals_are_denied(command):
    _assert_zsh_modifier_denied(command)


@pytest.mark.parametrize("command", [
    "echo $C:gr", "echo $C:wr", "echo $C:fr", "echo $C:Fr", "echo $C:gwr", "echo $C:fgr", "echo $C:F:2:r", "echo $C:F::r",
    "echo $C:F:2:fr", "echo $C:gs/a/b/", "echo $C:s/a/b/ $C:s:x:y:",
    "echo $C:W:x:r", "echo $C:W:/:t", "echo $C:F:1:W:x:t",                    # W:sep: and F:expr: take an argument
    "echo $C:F/2/r", "echo $C:F,2,r", "echo $C:F{2}r", "echo $C:F[2]r", "echo $C:W/x/r", "echo $C:W,x,t", "echo $C:W[x]t",
    "echo $C:W(x)t",
])
def test_zsh_modifier_prefixes_f_g_w_and_F_are_denied(command):
    _assert_zsh_modifier_denied(command)


@pytest.mark.parametrize("command", [                 # zsh reads the character after F or W as the delimiter (PR 918 review L-A)
    "echo $C:F-2-r", "echo $C:F.2.r", "echo $C:F_2_r", "echo $C:F@2@r", "echo $C:F%2%r", "echo $C:F=2=r", "echo $C:F+2+r",
    "echo $C:Fx2xr", "echo $C:W.x.t", "echo $C:Wrxrt", "echo $C:Wxxt", "echo $C:F323r", "echo $C:F<2>r", "echo $C:W<x>t",
    "echo $C:F)2)r", "echo $C:F]2]r", "echo $C:F}2}r", "echo $C:F>2>r",         # a closing bracket is an ordinary delimiter
    "echo \"$C:F|2|r\"", "echo \"$C:F;2;r\"", "echo \"$C:F#2#r\"", "echo \"$C:F!2!r\"", "echo \"$C:F*2*r\"",
    "echo $C:F-1-W.x.t", "echo $C:FW.x.t", "echo $C:Fre",                       # prefixes chain; `F` with no closer is bare
])
def test_zsh_modifier_any_delimiter_after_f_and_w_is_denied(command):
    _assert_zsh_modifier_denied(command)


@pytest.mark.parametrize("command", [
    "echo $C[1]:r", "echo $C[1,3]:u", "echo $C[-1]:l", "echo $C[(r)B]:r", "echo $@[1]:t", 'echo "$C[1]:r"',
    "echo $=C:t", "echo $~C:t", "echo $^C:t", "echo $^^C:t", "echo $+C:t", "echo $#C:t",
])
def test_zsh_modifier_subscripts_and_parameter_flags_are_denied(command):
    _assert_zsh_modifier_denied(command)


@pytest.mark.parametrize("command", [
    'echo "$C:r"',                                   # double quotes expand it too
    'echo "it\'s" $C:r',                             # an apostrophe inside double quotes is not a quote
    'echo "a # $C:r"',                               # `#` inside double quotes is not a comment
    "echo $'it\\'s' $C:r",                           # ANSI-C string: `\'` does not end it, the next `$C:r` is live
    "echo \\' $C:r",                                 # an escaped apostrophe opens no quote
    "echo a#b $C:r",                                 # `#` inside a word is not a comment
    "echo a # c\necho $C:r",                         # a comment ends at the newline
    "echo \\\\$C:r",                                 # `\\` is an escaped backslash, the `$C:r` is live
    "echo $$$C:r",                                   # `$$` (pid) then a live `$C:r`
    "echo 'a' $C:r 'b'",
    "echo \\\"$C:r\\\" | cat",                   # `\"` is an escaped quote: the `$C:r` is outside any quote
    "echo \"`echo \\\"it's\\\" $C:r`\"",               # backtick body in double quotes: `\"` unescapes to a real double quote
    "echo $C:r # not this one",
])
def test_zsh_modifier_quote_and_comment_tracking_denies_live_text(command):
    _assert_zsh_modifier_denied(command)


@pytest.mark.parametrize("command", [
    "cat <<EOF\n$C:r\nEOF",                          # an unquoted heredoc body is expanded by the shell (PR 909 review L1)
    "cat <<-EOF\n\t$C:r\n\tEOF",
    "bash <<EOF\ngit push origin $C:refs/heads/x\nEOF",
    "ssh host <<EOF\ngit push origin $C:refs/heads/x\nEOF",
    "cat <<EOF\n'$C:r' \"$C:r\"\nEOF",               # quotes are literal in a body
    "cat <<EOF\n# $C:r\nEOF",                        # and so is `#`
    "cat <<EOF\n'$C:r'\nEOF",                        # a single-quoted `$C:r` in a body is still expanded
    "cat <<EOF\na \"b $C:t\nEOF",
    "cat <<EOF\n\\\\$C:r\nEOF",                      # `\\` then a live `$C:r`
    "cat <<A <<B\n$C:r\nA\n$C:t\nB",
    "cat <<A <<'B'\n$C:r\nA\nplain\nB",
    "cat <<'A' <<B\nplain\nA\n$C:t\nB",
    "cat <<EOF\n$(echo $C:r)\nEOF",                  # `$(...)` in a body runs
    "cat <<EOF\nplain\nEOF\necho $C:r",
])
def test_zsh_modifier_in_unquoted_heredoc_body_is_denied(command):
    _assert_zsh_modifier_denied(command)


@pytest.mark.parametrize("command", [
    'echo "$(echo "it\'s")" $C:r',                   # nested quotes: the inner apostrophe is inside a real double quote (L3)
    'echo "$(echo "x $C:r")"',
    "echo \"a `echo \"it's\"` $C:r\"",
    "echo \"a `echo \\$C:r` b\"",                    # backtick body: `\$` is a live `$`
    "echo $(echo $C:r)",
    'echo "$(echo "$(echo $C:r)")"',
    "echo \"$((1+2)) $C:r\"",
    "echo $(( ${#C} + 1 )) $C:r",
])
def test_zsh_modifier_follows_command_substitution_inside_double_quotes(command):
    _assert_zsh_modifier_denied(command)


@pytest.mark.parametrize("command", [
    "git push origin ${C}:refs/heads/x",
    "echo '$C:r'",
    "echo ${C:-def} ${C:t} ${C:1:2}",
    "echo $C/:r",
    'echo "$C" :r',
    "echo $C:",
    "echo $C::x $C:/y $C:-x $C:x $C:p $C:S $C:1 $a:b:c",
    "echo $C:f $C:F $C:ff $C:g $C:gp $C:Fx $C:FZ $C:F:r $C:F:2 $C:fx",    # a prefix with no modifier after it is plain
    "echo $C:Fxt $C:F2t $C:Wr $C:W:x $C:W:x: $C:g:o:r $C:g:e:r",
    "echo $C:Feature $C:Ftest $C:F-2- $C:Wxx $C:F(2(r $C:W(x]t $C:F[2}r",       # `e`/`t` is a delimiter whose closer is followed by no modifier
    "echo \\$C:r",
    "echo \"${C}:r\" \"x:$C\"",
    "echo $PATH:/usr/bin $HOST:8080 scp $HOST:path .",
    "echo ok # $C:r",
    "echo x;# $C:r",                                 # `#` starts a comment at the start, after whitespace and after `; & | (`
    "# $C:r\necho a",
    "echo a\n# $C:r\necho b",
    "echo a &&# $C:r\necho b",
    "echo a |# $C:r\ncat",
    "(# $C:r\necho a)",
    "echo $$C:r",                                    # `$$` is the pid; `C:r` after it is plain text
    "echo ${C}[1]:r $1[1]:r $C[1]x:r",               # `${C}` braces end the name; `$1[1]` is a glob; text sits before `:r`
    "echo $C[1]",
    "cat <<'EOF'\n$C:r\nEOF",
    'cat <<"EOF"\n$C:r\nEOF',
    "cat <<'EOF' > f\ngit push origin $C:refs/heads/x\nEOF",
    "cat <<EOF\n\\$C:r\nEOF",                        # an escaped `$` in an unquoted body is literal
    "cat <<EOF\n${C}:r $C: $C/:r\nEOF",
    "cat <<EOF\n$(echo '$C:r')\nEOF",                # a single quote inside `$(...)` in a body is a real quote
    "cat <<EOF\n`echo '$C:r'`\nEOF",
    "cat <<'A' <<'B'\n$C:r\nA\n$C:t\nB",
    "echo $'\\' $C:r'",                              # ANSI-C string holds `\'` and the `$C:r`
    "echo $'$C:r'",
    'echo "$(echo \'$C:r\')"',                       # single quotes inside `$(...)` inside double quotes are real (L3)
    'echo "`echo \'$C:r\'`"',
    'echo "$(echo "$(echo \'$C:r\')")"',
    "echo \"a `echo '$C:r'` b\"",
    'cat <<EOF\n"`echo \\"\'$C:r\'\\"`"\nEOF',                    # in a heredoc body `"` is literal: this `$C:r` stays inside single quotes (L-B)
])
def test_zsh_modifier_lookalikes_and_safe_forms_pass(command):
    assert not denied(command), command


@pytest.mark.parametrize("command", [
    "echo " + "$(" * 5000,
    "echo " + "$(echo " * 200 + "$C:r",
    "echo \"" + "`" * 5001,
    "echo " + "$" * 20000 + ":r",
    "echo '" + "\\" * 10001,
    "cat <<EOF\n" + "$(" * 3000 + "\nEOF",
    "echo " + "$(echo $C) " * 3000,
    "echo " + '$(echo "$(" ) ' * 500,
])
def test_zsh_modifier_scan_survives_pathological_input(command):
    run(command)                                      # `run` asserts exit 0 and a 30 s ceiling; the verdict may be either


def test_zsh_modifier_scan_is_linear_on_unbalanced_substitutions_in_quotes():
    """PR 918 review M-A: an unbalanced `$(` inside double quotes, repeated in sibling `$(...)`, made `_closing_paren` read to
    the end of the command each time (quadratic: 68 s at 140 KB, past the 60 s hook timeout, so the gate failed open)."""
    command = "echo " + '$(echo "$(" ) ' * 10000      # about 140 KB
    assert len(command) > 130_000
    started = time.monotonic()
    run(command)
    assert time.monotonic() - started < 5, "the zsh modifier scan is no longer linear"


@pytest.mark.parametrize("command", [
    "echo " + "$C:F<" * 40000,                        # an opener with no closer: each `$` used to scan to the end of its word (PR 918 review M-B)
    "echo \"" + "$C:F(" * 40000 + "\"",
    "echo " + "$C:F[" * 40000,
    "echo " + "$C:F{" * 40000,
    "echo " + "$C:W<" * 40000,
    "echo " + "$C[" * 70000,                          # a subscript with no `]` scanned to the end of the line
    "echo " + "$C:W." * 40000,
    "echo " + "$C:F." * 40000,
    "echo $C:" + "Ff$C:f" * 34000 + "; git push origin $C:refs/heads/x",   # the prefix chain: each `$` chained to the end of the word (r3 M-1)
    "echo $C:" + "Wf$C:f" * 34000,
], ids=["F<", "F(", "F[", "F{", "W<", "C[", "W.", "F.", "Ff-chain", "Wf-chain"])
def test_zsh_modifier_regex_is_linear_on_unclosed_delimiters_and_subscripts(command):
    assert len(command) >= 195_000
    started = time.monotonic()
    run(command)
    assert time.monotonic() - started < 5, "the zsh modifier regex is no longer linear"


@pytest.mark.parametrize("command, denies", [          # an argument or subscript longer than 256 characters is not followed (accepted limit)
    ("echo $C:F<" + "a" * 256 + ">r", True), ("echo $C:F<" + "a" * 257 + ">r", False),
    ("echo $C:F-" + "a" * 256 + "-r", True), ("echo $C:F-" + "a" * 257 + "-r", False),
    ("echo $C[" + "a" * 256 + "]:r", True), ("echo $C[" + "a" * 257 + "]:r", False),
])
def test_zsh_modifier_argument_and_subscript_cap_is_256_characters(command, denies):
    assert denied(command) is denies


@pytest.mark.parametrize("command, denies", [          # more than 8 prefix items before the modifier letter are not followed (accepted limit)
    ("echo $C:" + "f" * 8 + "r", True), ("echo $C:" + "f" * 9 + "r", False),
    ("echo $C:" + "g" * 7 + "F:2:r", True), ("echo $C:" + "fg" * 4 + "r", True),
])
def test_zsh_modifier_prefix_chain_cap_is_8_items(command, denies):
    assert denied(command) is denies


def _budget_env(seconds):
    return dict(os.environ, BASH_HABITS_GATE_BUDGET=str(seconds))


def test_gate_fails_closed_when_it_exceeds_its_time_budget():
    """`$((` x 2000 takes the unbudgeted gate past 60 s (also on master): with the budget lowered it must end in a deny, fast."""
    command = "echo " + "$((" * 2000
    started = time.monotonic()
    out = run(command, env=_budget_env(2))
    elapsed = time.monotonic() - started
    assert out and out["permissionDecision"] == "deny", out
    assert "time budget" in out["permissionDecisionReason"] and "split or simplify" in out["permissionDecisionReason"]
    assert 1.5 < elapsed < 15, elapsed


def test_time_budget_deny_works_for_the_cursor_and_codex_forms_too():
    command = "echo " + "$((" * 2000
    cursor = subprocess.run([sys.executable, str(HOOK), "--cursor"], input=json.dumps({"command": command}),
                            capture_output=True, text=True, timeout=30, env=_budget_env(2))
    assert cursor.returncode == 0 and json.loads(cursor.stdout)["permission"] == "deny"
    codex = subprocess.run([sys.executable, str(HOOK), "--codex"],
                           input=json.dumps({"tool_name": "shell", "tool_input": {"command": command}}),
                           capture_output=True, text=True, timeout=30, env=_budget_env(2))
    assert codex.returncode == 2 and "time budget" in codex.stderr


@pytest.mark.parametrize("value", ["", "0", "-3", "abc", "nan", "-inf", "inf", "1e400", "1e12"])
def test_an_unusable_budget_value_falls_back_to_the_default(value):
    """`inf`, `1e400` and `1e12` used to crash the parent on every call (OverflowError in `select`): a crash lets the command run."""
    assert run("git status", env=_budget_env(value)) is None
    out = run("git push origin $C:refs/heads/x", env=_budget_env(value))
    assert out and out["permissionDecision"] == "deny" and "time budget" not in out["permissionDecisionReason"]


def _load_hook():
    from importlib import util
    spec = util.spec_from_file_location("bhg_budget", HOOK)
    mod = util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("value,expected", [
    ("", 20.0), ("0", 20.0), ("-3", 20.0), ("abc", 20.0), ("nan", 20.0), ("-inf", 20.0),
    ("0.5", 0.5), ("30", 30.0), ("45", 45.0), ("46", 45.0), ("100", 45.0), ("1e12", 45.0), ("inf", 45.0), ("1e400", 45.0),
])
def test_the_budget_is_clamped_below_the_hook_timeout(monkeypatch, value, expected):
    """A large value must not move the deadline past the old 60 s hook timeout (that would bring back the old fail-open)."""
    monkeypatch.setenv("BASH_HABITS_GATE_BUDGET", value)
    mod = _load_hook()
    assert mod._budget() == expected
    assert mod.BUDGET_MAX < 60


def test_a_budget_above_the_clamp_still_times_out_at_the_clamp_not_later(monkeypatch):
    monkeypatch.setenv("BASH_HABITS_GATE_BUDGET", "1e12")
    mod = _load_hook()
    monkeypatch.setattr(mod, "BUDGET_MAX", 1.0)           # keep the test fast: the clamp is what decides the deadline
    monkeypatch.setattr(mod, "check", lambda cmd: time.sleep(60))
    started = time.monotonic()
    reason, _ = mod.check_within_budget("echo x")
    assert reason and "time budget" in reason and time.monotonic() - started < 10


def test_the_forked_child_ends_itself_when_the_hook_parent_is_killed(tmp_path):
    """The hook parent can be killed from outside (a user interrupt, a shorter hook timeout in another TUI): the child it forked
    must not keep scanning as an orphan (adversary PR 918 r4 L-2). It arms SIGALRM at its default action: budget + 2 s."""
    import signal
    pidfile = tmp_path / "child.pid"
    driver = tmp_path / "driver.py"
    driver.write_text(
        "import importlib.util, os, time\n"
        f"spec = importlib.util.spec_from_file_location('bhg', {str(HOOK)!r})\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "def slow(cmd):\n"
        f"    open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
        "    time.sleep(120)\n"
        "mod.check = slow\n"
        "mod.check_within_budget('echo x')\n")
    parent = subprocess.Popen([sys.executable, str(driver)], env=_budget_env(3))
    child = None
    try:
        end = time.monotonic() + 10
        while time.monotonic() < end and not (pidfile.exists() and pidfile.read_text().strip()):
            time.sleep(0.02)
        child = int(pidfile.read_text())
        os.kill(parent.pid, signal.SIGKILL)               # killed well before its own 3 s deadline: nothing reaps the child
        parent.wait(timeout=10)

        def alive():
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                return False
            return True
        end = time.monotonic() + 15                       # alarm: ceil(3) + 2 = 5 s
        while alive() and time.monotonic() < end:
            time.sleep(0.1)
        assert not alive(), "the orphaned child is still running"
    finally:
        if parent.poll() is None:
            parent.kill()
        if child:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_a_child_killed_by_its_own_alarm_before_the_parents_deadline_is_denied_not_raised(monkeypatch):
    """A delayed parent (load, a stopped hook, a clock jump) can see the child's SIGALRM fire before its own deadline: the
    parent used to raise RuntimeError (hook exit 1, the command runs unchecked); it must deny (adversary PR 926 LOW-1)."""
    monkeypatch.setenv("BASH_HABITS_GATE_BUDGET", "3")
    mod = _load_hook()
    monkeypatch.setattr(mod, "CHILD_GRACE", -2)            # the alarm (ceil(3) - 2 = 1 s) fires well before the parent's 3 s deadline
    monkeypatch.setattr(mod, "check", lambda cmd: time.sleep(60))
    started = time.monotonic()
    reason, warn = mod.check_within_budget("echo x")
    assert reason and "time budget" in reason and warn is None
    assert time.monotonic() - started < 2.9                 # the child's alarm ended it, not the parent's deadline


def test_a_child_that_dies_without_a_result_is_denied_not_raised(monkeypatch):
    monkeypatch.setenv("BASH_HABITS_GATE_BUDGET", "5")
    mod = _load_hook()
    monkeypatch.setattr(mod, "check", lambda cmd: os._exit(3))
    reason, warn = mod.check_within_budget("echo x")
    assert reason and "could not finish checking" in reason and warn is None


@pytest.mark.parametrize("fork_is", ["missing", "failing"])
def test_without_a_usable_fork_the_check_error_still_passes_the_command_on_and_no_fd_leaks(monkeypatch, fork_is):
    """The in-process fallback keeps main()'s old guard (a scan error passes the command on, exit 0) and closes the pipe."""
    import re
    mod = _load_hook()
    pipes = []
    real_pipe = os.pipe

    def spy_pipe():
        fds = real_pipe()
        pipes.append(fds)
        return fds
    monkeypatch.setattr(mod.os, "pipe", spy_pipe)
    if fork_is == "missing":
        monkeypatch.delattr(mod.os, "fork")
    else:
        def no_fork():
            raise OSError("EAGAIN")
        monkeypatch.setattr(mod.os, "fork", no_fork)

    def broken(cmd):
        raise re.error("boom")
    monkeypatch.setattr(mod, "check", broken)
    assert mod.check_within_budget("echo x") == (None, None)
    for fds in pipes:
        for fd in fds:
            with pytest.raises(OSError):
                os.fstat(fd)                              # both ends are closed
    assert bool(pipes) is (fork_is == "failing")
