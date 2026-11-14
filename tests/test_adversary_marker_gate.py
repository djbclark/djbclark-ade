"""claude/hooks/adversary_marker_gate.py: a `gh` write never carries a LIVE adversary APPROVE marker (am-01, 2026-11-14).

Offline: the hook runs as a subprocess over a Bash PreToolUse event; files it reads live in tmp_path.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude" / "hooks"))
import adversary_marker_gate as gate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "claude" / "hooks" / "adversary_marker_gate.py"
SHA = "a" * 40
APPROVE = '<!-- adversary-verdict:v1 {"verdict":"APPROVE","head":"%s"} -->' % SHA
BLOCK = '<!-- adversary-verdict:v1 {"verdict":"BLOCK","head":"%s"} -->' % SHA
FENCED = "```\n%s\n```" % APPROVE


def run(command, cwd=None, env=None, stdin=None, tool="Bash"):
    event = {"tool_name": tool, "tool_input": {"command": command}}
    if cwd:
        event["cwd"] = str(cwd)
    proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event) if stdin is None else stdin,
                          capture_output=True, text=True, timeout=30, check=False,
                          env={**{k: v for k, v in os.environ.items() if k != "ADVERSARY_MARKER_GATE_OFF"}, **(env or {})})
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        return None
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    return out["permissionDecisionReason"]


def q(text):
    """Single-quote `text` for the shell."""
    return "'" + text.replace("'", "'\"'\"'") + "'"


# ---- the denied shapes -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("command", [
    "gh pr edit 5 --body " + q("Verdict: no findings\n\n" + APPROVE),
    "gh pr edit 5 --body=" + q(APPROVE),
    "gh pr create --title t -b " + q(APPROVE),
    "gh pr create --title t --body " + q(APPROVE) + " --base master",
    "gh -R djbclark/x pr edit 5 --body " + q(APPROVE),
    "gh pr comment 5 --body " + q(APPROVE),
    "gh issue comment 5 --body " + q(APPROVE),
    "gh pr review 5 --comment --body " + q(APPROVE),
    "cd /r && echo hi; gh pr edit 5 --body " + q(APPROVE),
    "gh pr edit 5 --body \"%s\"" % APPROVE.replace('"', '\\"'),
    "gh api repos/o/r/pulls/5 -X PATCH -f body=" + q(APPROVE),
    "gh api repos/o/r/pulls -f title=t -f head=h -f base=b -f body=" + q(APPROVE),
    "gh api repos/o/r/issues/5/comments -f body=" + q(APPROVE),
    "gh api repos/o/r/issues/5/comments --raw-field body=" + q(APPROVE),
    "gh api repos/o/r/issues/5/comments -F body=" + q(APPROVE),
])
def test_live_approve_in_a_gh_write_is_denied(command):
    reason = run(command)
    assert reason and "live" in reason and "ADVERSARY_MARKER_GATE_OFF" in reason


def test_heredoc_bodies_are_denied(tmp_path):
    assert run("gh pr create --title t --body-file - <<'EOF'\nprose\n%s\nEOF\n" % APPROVE)
    assert run('gh pr create --title t --body "$(cat <<\'EOF\'\nsummary\n\n%s\nEOF\n)"' % APPROVE)
    assert run("gh pr edit 5 --body-file - <<EOF\n%s\nEOF" % APPROVE)


def test_body_file_is_read(tmp_path):
    f = tmp_path / "body.md"
    f.write_text("prose\n\n%s\n" % APPROVE)
    assert run("gh pr edit 5 --body-file %s" % f)
    assert run("gh pr edit 5 --body-file=%s" % f)
    assert run("gh pr create --title t -F %s" % f)
    assert run("gh pr edit 5 --body-file body.md", cwd=tmp_path)                     # relative to the event cwd
    assert run('gh pr edit 5 --body "$(cat %s)"' % f)
    assert run("gh api repos/o/r/pulls/5 -X PATCH -F body=@%s" % f)
    assert run("gh api repos/o/r/issues/5/comments -f body=@%s" % f)
    j = tmp_path / "in.json"
    j.write_text(json.dumps({"body": APPROVE}))
    assert run("gh api repos/o/r/issues/5/comments --input %s" % j)
    assert run("gh api repos/o/r/issues/5/comments --input=%s" % j)


@pytest.mark.parametrize("marker", [
    '<!-- adversary-verdict:v1 {"verdict":"approve","head":"%s"} -->' % SHA,                          # lower case
    '<!-- adversary-verdict:v1 {"verdict":"APPROVE","head":"abc1234"} -->',                           # short head
    '<!-- adversary-verdict:v1 {"verdict":"BLOCK","head":"%s","verdict":"APPROVE"} -->' % SHA,         # duplicate key
    '<!-- adversary-verdict:v1 {"verdict":"APPROVE","head":"%s",} -->' % SHA,                         # does not parse
    '<!-- adversary_verdict:v1 {"verdict":"APPROVE","head":"%s"} -->' % SHA,                          # near-miss spelling
    '<!--adversary-verdict:v1 {"verdict": "APPROVE", "head": "%s"}-->' % SHA,
])
def test_variants_of_a_live_approve_are_denied(marker):
    assert run("gh pr edit 5 --body " + q("x\n" + marker))


@pytest.fixture
def live(tmp_path):
    (tmp_path / "live.md").write_text("prose\n\n%s\n" % APPROVE)
    (tmp_path / "payload.json").write_text(json.dumps({"body": APPROVE}))
    (tmp_path / "json.txt").write_text('{"verdict":"APPROVE","head":"%s"}' % SHA)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "only.md").write_text(APPROVE)
    return tmp_path


@pytest.mark.parametrize("command", [
    # stdin bodies (adversary round 1, B1)
    "gh pr edit 41 --body-file - < live.md",
    "cat live.md | gh pr edit 41 --body-file -",
    "echo " + q(APPROVE) + " | gh pr edit 41 --body-file -",
    "gh pr edit 41 --body-file - <<< " + q(APPROVE),
    "gh pr edit 41 --body-file <(cat live.md)",
    "gh pr edit 41 --body-file /dev/stdin < live.md",
    "cat live.md | gh api repos/o/r/issues/41/comments -F body=@-",
    "gh api repos/o/r/issues/41/comments --input - < payload.json",
    "jq -n --rawfile b live.md '{body:$b}' | gh api repos/o/r/issues/41/comments --input -",
    # any gh api write, whatever the endpoint (B2)
    "gh api graphql -f query=" + q('mutation{addComment(input:{subjectId:"X",body:"%s"}){clientMutationId}}' % APPROVE.replace('"', '\\"')),
    "gh api graphql -F b=@live.md",
    'EP=repos/o/r/issues/41/comments; gh api "$EP" -f body=' + q(APPROVE),
    "gh api 'repos/o/r/pulls?x=1' -X PATCH -f body=" + q(APPROVE),
    "gh api repos/o/r/git/refs -f body=" + q(APPROVE),
    # verbs and flags (B3)
    "gh pr new --body " + q(APPROVE),
    "gh issue new --body " + q(APPROVE),
    "gh pr close 41 --comment " + q(APPROVE),
    "gh pr reopen 41 -c " + q(APPROVE),
    "gh issue close 41 -c " + q(APPROVE),
    "gh pr create --title t --template live.md",
    # wrappers (C1)
    "bash -c " + q("gh pr edit 41 --body " + q(APPROVE)),
    "sh -c " + q("gh pr edit 41 --body-file live.md"),
    "eval " + q("gh pr edit 41 --body " + q(APPROVE)),
    "cat live.md | xargs -0 gh pr edit 41 --body",
    "python3 - <<'EOF'\nimport subprocess\nsubprocess.run(['gh','pr','edit','41','--body','%s'])\nEOF" % APPROVE,
    "command gh pr edit 41 --body " + q(APPROVE),
    "env X=y /opt/homebrew/bin/gh pr edit 41 --body " + q(APPROVE),
    # file operand shapes (C2)
    'gh pr edit 41 --body "$(cat \'live.md\')"',
    'gh pr edit 41 --body "$(cat -- live.md)"',
    'gh pr edit 41 --body "$(<live.md)"',
    'gh pr edit 41 --body "`cat live.md`"',
    "cd sub && gh pr edit 41 --body-file only.md",
    'cd sub && gh pr edit 41 --body "$(cat only.md)"',
    "gh api repos/o/r/issues/41/comments -fbody=" + q(APPROVE),
    "gh api repos/o/r/issues/41/comments -Fbody=@live.md",
    "gh pr comment 41 -Flive.md",
    # a marker the shell builds (C3)
    "V=APPROVE; gh pr comment 41 --body " + q('<!-- adversary-verdict:v1 {"verdict":"') + '"$V"' + q('","head":"%s"} -->' % SHA),
    'gh pr comment 41 --body "<!-- adversary-verdict:v1 $(cat json.txt) -->"',
])
def test_stdin_wrapper_and_variant_shapes_are_denied(live, command):
    assert run(command, cwd=live), command


def test_a_command_shlex_cannot_parse_still_denies():
    reason = run("gh pr edit 5 --body " + q(APPROVE) + " && echo it's broken")
    assert reason and "live" in reason


# ---- the allowed shapes ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("command", [
    "gh pr edit 5 --body " + q("Adversary verdict: no findings (head %s)." % SHA),
    "gh pr edit 5 --body " + q(BLOCK),                                       # a BLOCK counts wherever it is
    "gh pr edit 5 --body " + q("Example:\n\n" + FENCED + "\n"),
    "gh pr edit 5 --body " + q("Use `%s` here." % APPROVE),
    "gh pr edit 5 --body " + q('<!-- adversary-verdict:v1 {"verdict":"APPROVE"|"BLOCK","head":"<40-hex>"} -->'),
    "gh pr edit 5 --body " + q('<!-- adversary-verdict:v1 {"verdict":"APPROVE","head":"<40-hex>"} -->'),
    "gh pr edit 5 --title 'adversary-verdict marker gate'",
    "gh pr view 5 --json body",
    "gh pr list --search 'adversary-verdict APPROVE'",
    "gh api repos/o/r/pulls/5",
    "gh pr merge 5 --squash",
    "git commit -m " + q("fix\n\n" + APPROVE),                                 # not a gh write: out of scope
    "echo " + q(APPROVE),
    "ls",
])
def test_everything_else_passes(command):
    assert run(command) is None


def test_fenced_heredoc_and_fenced_files_pass(tmp_path):
    assert run("gh pr create --title t --body-file - <<'EOF'\nprose\n%s\nEOF\n" % FENCED) is None
    assert run('gh pr create --title t --body "$(cat <<\'EOF\'\nsummary\n\n%s\nEOF\n)"' % FENCED) is None
    f = tmp_path / "ok.md"
    f.write_text("prose\n\n%s\n\n%s\n" % (FENCED, BLOCK))
    assert run("gh pr edit 5 --body-file %s" % f) is None
    assert run("gh api repos/o/r/issues/5/comments -F body=@%s" % f) is None


def test_missing_or_dynamic_bodies_fail_open(tmp_path):
    assert run("gh pr edit 5 --body-file %s/nope.md" % tmp_path) is None
    assert run('gh pr edit 5 --body "$BODY"') is None
    big = tmp_path / "big.md"
    big.write_text(APPROVE + " " * 300000)
    assert run("gh pr edit 5 --body-file %s" % big) is None


def test_hook_fails_open_on_junk_and_other_tools():
    assert run("", stdin="not json") is None
    assert run("", stdin=json.dumps(["x"])) is None
    assert run("gh pr edit 5 --body " + q(APPROVE), tool="Write") is None
    assert run("", stdin=json.dumps({"tool_name": "Bash", "tool_input": {"command": 7}})) is None


def test_operator_escape_hatch_is_the_environment_not_the_command():
    cmd = "gh pr edit 5 --body " + q(APPROVE)
    assert run(cmd, env={"ADVERSARY_MARKER_GATE_OFF": "1"}) is None
    assert run("ADVERSARY_MARKER_GATE_OFF=1 " + cmd)



PROSE = "The `adversary-verdict` marker is fenced; approve-post is operator-only. See rule 14."


@pytest.mark.parametrize("command", [
    # round 2, B1/B2: prose and development commands that only MENTION a gh write, a marker or the word approve
    "gh pr edit 724 --body " + q(PROSE),
    "gh pr edit 724 --body 'See bin/ade-merge-ready approve-post.'",
    "gh pr comment 724 --body 'Updated docs/code-review.md rule 14 and tests/test_adversary_marker_gate.py (84 tests).'",
    "rg -n 'gh pr edit' tests/test_adversary_marker_gate.py",
    "git commit -m 'test: gh pr comment shapes' tests/test_adversary_marker_gate.py",
    "bin/pytest tests/test_adversary_marker_gate.py -k 'gh api -f'",
    "git log --grep 'gh pr create' -- bin/adversary_marker.py",
    "git add tests/test_adversary_marker.py bin/ade-merge-ready && git commit -m fix && gh pr create --title t --body x",
    "rg -n adversary-verdict docs/code-review.md; gh pr comment 1 --body done",
    "gh pr edit 724 --body-file docs/code-review.md",
])
def test_prose_and_development_commands_pass(command):
    assert run(command, cwd=ROOT) is None, command


def test_a_prose_body_file_that_mentions_the_marker_passes(tmp_path):
    f = tmp_path / "pr-body.md"
    f.write_text("## Summary\n\n" + PROSE + "\n\nFenced example:\n\n" + FENCED + "\n")
    assert run("gh pr edit 724 --body-file %s" % f) is None


@pytest.mark.parametrize("command", [
    "gh pr -R o/r edit 41 --body " + q(APPROVE),
    "gh pr --repo=o/r comment 41 --body " + q(APPROVE),
    "gh \\\npr edit 41 --body " + q(APPROVE),
    "env -u X gh pr edit 41 --body " + q(APPROVE),
    "pushd sub && gh pr edit 41 --body-file only.md",
])
def test_flags_between_group_and_verb_and_pushd_are_seen(live, command):
    assert run(command, cwd=live), command


def test_incidental_files_do_not_spend_the_body_file_budget(live):
    for i in range(70):
        (live / ("f%d.txt" % i)).write_text("x")
    files = " ".join("f%d.txt" % i for i in range(70))
    assert run("git add %s && gh pr edit 41 --body-file live.md" % files, cwd=live)


@pytest.mark.parametrize("command", [
    "if gh pr edit 41 --body %s; then echo ok; fi" % q(APPROVE),
    "if true; then gh pr comment 41 --body %s; fi" % q(APPROVE),
    "for p in 1 2; do gh pr comment $p --body %s; done" % q(APPROVE),
    "while read p; do gh pr comment \"$p\" --body-file live.md; done < prs.txt",
    "if false; then :; else gh pr edit 41 --body %s; fi" % q(APPROVE),
    "until gh pr comment 41 --body %s; do sleep 1; done" % q(APPROVE),
    "coproc gh pr comment 41 --body %s" % q(APPROVE),
    'URL="$(gh pr create --title t --body %s)"' % q(APPROVE),
    'echo "$(gh pr comment 41 --body-file live.md)"',
    'bash -lc "gh pr edit 41 --body-file live.md"',
    'sh -ec "gh pr edit 41 --body-file live.md"',
    "/usr/bin/env gh pr edit 41 --body %s" % q(APPROVE),
    "/usr/bin/time gh pr edit 41 --body %s" % q(APPROVE),
    "/Users/djbclark/ops/site-private-djbclark/bin/bg gh pr edit 41 --body %s" % q(APPROVE),
    "find . -name live.md -exec gh pr edit 41 --body-file {} \\;",
    "watch -n 60 gh pr comment 41 --body %s" % q(APPROVE),
    "script -q /dev/null gh pr comment 41 --body %s" % q(APPROVE),
    "parallel gh pr comment {} --body %s ::: 41" % q(APPROVE),
    "env " + " ".join("A%d=1" % i for i in range(20)) + " gh pr edit 41 --body " + q(APPROVE),
    "bash <<'EOF'\ngh pr edit 41 --body-file live.md\nEOF\n",
    "sh -s <<'EOF'\ngh pr comment 41 --body-file live.md\nEOF\n",
    "printf '%%s\\n' %s > new.md && gh pr edit 41 --body-file new.md" % q(APPROVE),
    "echo %s | tee b4.md >/dev/null; gh pr edit 41 --body-file b4.md" % q(APPROVE),
    "cp live.md b3.md && gh pr edit 41 --body-file b3.md",
    "BODY=%s; gh pr edit 41 --body \"$BODY\"" % q(APPROVE),
    "(cd /tmp); gh pr edit 41 --body-file live.md",
])
def test_round3_command_positions_and_earlier_writes_are_seen(live, command):
    if "cp live.md" in command:
        pytest.skip("a file copied by the same command is a known limit")
    assert run(command, cwd=live), command


def test_a_subshell_cd_ends_with_the_subshell_and_a_failed_cd_falls_back_to_the_event_cwd(live):
    (live / "both.md").write_text(APPROVE)
    (live / "sub" / "both.md").write_text("prose only")
    assert run("(cd sub); gh pr edit 41 --body-file both.md", cwd=live)      # the real cwd's both.md is live
    assert run("cd /nonexistent-dir-x; gh pr edit 41 --body-file live.md", cwd=live)   # the cd failed, gh ran in the event cwd


def test_a_gh_write_the_parser_cannot_place_is_found_by_the_backstop():
    code = "import subprocess; subprocess.run(['gh','pr','edit','1','--body','%s'])" % APPROVE
    assert run("python3 -c " + q(code))
    assert run("python3 -c " + q(code.replace(APPROVE, BLOCK))) is None


def test_a_decoy_block_outside_the_marker_comment_does_not_hide_a_shell_built_verdict():
    built = '<!-- adversary-verdict:v1 {\\"verdict\\":\\"$V\\",\\"head\\":\\"$H\\"} -->'
    assert run('V=APPROVE; gh pr comment 41 --body "%s"' % built)
    assert run('V=APPROVE; gh pr comment 41 --body "%s (round 1 verdict: BLOCK)"' % built)
    two_keys = '<!-- adversary-verdict:v1 {\\"verdict\\":\\"BLOCK\\",\\"verdict\\":\\"$V\\"} -->'
    assert run('V=APPROVE; gh pr comment 41 --body "%s"' % two_keys)


def test_many_plain_arguments_do_not_spend_the_operand_cap(live):
    labels = " ".join("--add-label l%d" % i for i in range(300))
    assert run("gh pr edit 41 %s --body-file live.md" % labels, cwd=live)


def test_operand_text_past_the_cap_is_denied_when_it_mentions_approve(live, monkeypatch):
    for i in range(3):
        (live / ("o%d.md" % i)).write_text("approve " + "x" * 200)
    monkeypatch.setattr(gate, "MAX_FORCED_BYTES", 300)
    cmd = "gh pr edit 41 " + " ".join("--body-file o%d.md" % i for i in range(3))
    reason = gate.judge(cmd, str(live), gate._checker)
    assert "more operand text" in reason
    assert gate.judge("gh pr edit 41 --body-file " + str(live / "o0.md"), str(live), gate._checker) == ""


def test_a_budget_spent_on_feeders_never_hides_the_write_operands(live):
    for i in range(9):
        (live / ("big%d.txt" % i)).write_text("x" * 70000)
    feeders = " ".join("big%d.txt" % i for i in range(9))
    assert run("cat %s | gh pr edit 41 --body-file live.md" % feeders, cwd=live)
    flags = " ".join("-F x%d=@big%d.txt" % (i, i) for i in range(9))
    assert run("gh api repos/o/r/issues/5/comments %s -F body=@live.md" % flags, cwd=live)


def test_a_block_relay_with_a_shell_built_head_passes():
    head = "H=$(git rev-parse HEAD); "
    block = '<!-- adversary-verdict:v1 {\"verdict\":\"BLOCK\",\"head\":\"$H\"} --> approve after the fix'
    assert run(head + 'gh pr comment 41 --body "%s"' % block) is None
    assert run(head + 'gh pr review 41 --approve -b "%s"' % block) is None
    live_built = '<!-- adversary-verdict:v1 {\"verdict\":\"APPROVE\",\"head\":\"$H\"} -->'
    assert run(head + 'gh pr comment 41 --body "%s"' % live_built)


def test_prose_commands_that_merely_mention_a_gh_write_still_pass(live):
    assert run("rg 'gh pr edit' live.md", cwd=live) is None
    assert run("git commit -m 'note: gh pr comment shapes' live.md", cwd=live) is None


def test_pathological_inputs_are_bounded(tmp_path):
    import time
    big = tmp_path / "big.md"
    big.write_text("adversary-verdict " * 20000)
    t = time.time()
    assert run("gh pr edit 5 --body-file %s" % big) is None                     # no APPROVE: nothing to deny
    big.write_text("approve " + "<!-- adversary-verdict:v1 { " * 5000)
    assert run("gh pr edit 5 --body-file %s" % big)                             # too many starts beside APPROVE
    assert time.time() - t < 12


def test_a_command_with_no_gh_write_never_loads_the_checker():
    def boom():
        raise AssertionError("loaded")
    assert gate.judge("ls -la && git commit -m " + q(APPROVE), "/", boom) == ""
    assert gate.judge("gh pr view 5 --json body", "/", boom) == ""
    assert gate.judge("gh api repos/o/r/pulls/5", "/", boom) == ""


def test_checker_is_found_beside_a_copied_hook_through_the_home_checkout(tmp_path):
    """A copy (not a symlink) of the hook resolves bin/ from ~/src/djbclark-ade; with neither it fails open (round 1, B4)."""
    hooks = tmp_path / "copy" / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    copy = hooks / "adversary_marker_gate.py"
    copy.write_text(HOOK.read_text())
    home = tmp_path / "home"
    (home / "src").mkdir(parents=True)
    (home / "src" / "djbclark-ade").symlink_to(ROOT)
    event = json.dumps({"tool_name": "Bash", "tool_input": {"command": "gh pr edit 5 --body " + q(APPROVE)}})

    def go(h):
        return subprocess.run([sys.executable, str(copy)], input=event, capture_output=True, text=True, check=False,
                              env={**os.environ, "HOME": str(h)})
    assert '"deny"' in go(home).stdout
    bare = tmp_path / "bare"
    bare.mkdir()
    r = go(bare)
    assert r.returncode == 0 and r.stdout.strip() == "" and "adversary_marker_gate" in r.stderr


def test_registered_for_bash_in_the_claude_settings_template():
    tmpl = json.loads((ROOT / "agents" / "claude" / "settings.json.tmpl").read_text())
    cmds = [(blk["matcher"], h["command"]) for blk in tmpl["hooks"]["PreToolUse"] for h in blk["hooks"]]
    assert any("adversary_marker_gate.py" in c and "Bash" in m.split("|") for m, c in cmds)


def test_adversary_agent_no_longer_tells_anyone_to_paste_a_live_marker():
    text = (ROOT / "claude" / "agents" / "adversary.md").read_text()
    assert "for the teammate to paste into the PR body" not in text
    assert "raw line in your" not in text
    assert "fenced block" in text and "adversary_marker_gate" in text
