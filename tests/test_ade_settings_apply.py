"""bin/ade_settings_apply.py: the narrow ADE-owned merge of the Claude settings template into live (st-apply, 2026-11-15)."""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))
import ade_settings_apply as sa  # noqa: E402

import tempfile

HOME = tempfile.mkdtemp(prefix="ade-sa-home-")
_ADE = Path(HOME) / "src" / "djbclark-ade"
(_ADE / "bin").mkdir(parents=True)
(_ADE / "claude" / "hooks").mkdir(parents=True)
(_ADE / "bin" / "post-edit-check").write_text("#!/bin/sh\n")
(_ADE / "claude" / "hooks" / "secret_read_gate.py").write_text("x")
(Path(HOME) / ".claude" / "hooks").mkdir(parents=True)
os.symlink(_ADE / "claude" / "hooks" / "secret_read_gate.py", Path(HOME) / ".claude" / "hooks" / "secret_read_gate.py")
os.symlink(Path(HOME) / "gone", Path(HOME) / ".claude" / "hooks" / "cswap_quota_context.sh")  # dangling, like the retired hook
(Path(HOME) / ".claude" / "hooks" / "plain.sh").write_text("x")  # a real file outside the tree
ROOTS = [_ADE]
_merge = sa.merge


def merge(live, tmpl, home):
    return _merge(live, tmpl, home, ROOTS)


sa.merge_default = _merge
GRAFT = '"$HOME/.claude/helpers/graft-hooks.cjs" post-edit'


def h(cmd):
    return {"hooks": [{"type": "command", "command": cmd}]}


def tmpl():
    return {
        "model": "sonnet",
        "hooks": {
            "PostToolUse": [h(f"node {GRAFT}"), h('"$HOME"/src/djbclark-ade/bin/post-edit-check --hook')],
            "PreToolUse": [{"matcher": "Read", **h('"$HOME/.claude/hooks/secret_read_gate.py"')}],
        },
        "permissions": {"deny": ["Read(a)", "Read(b)"]},
        "sandbox": {"filesystem": {"denyRead": ["~/.ssh/x"]}},
    }


def live():
    return {
        "model": "opus",
        "plugins": {"keep": True},
        "hooks": {
            "PostToolUse": [h("node " + HOME + "/.claude/helpers/graft-hooks.cjs post-edit || exit 0"), h("paseo hooks x")],
        },
        "permissions": {"deny": ["Read(b)", "Read(live-only)"], "allow": ["x"]},
    }


def test_hook_dedupe_by_path_keeps_the_live_wrapper():
    m, added, _ = merge(live(), tmpl(), HOME)
    cmds = [x["command"] for g in m["hooks"]["PostToolUse"] for x in g["hooks"]]
    assert sum("graft-hooks.cjs" in c for c in cmds) == 1 and any(c.endswith("|| exit 0") for c in cmds)
    assert any("post-edit-check" in c for c in cmds)  # the template-only ADE hook is added
    assert any("secret_read_gate.py" in x["command"] for g in m["hooks"]["PreToolUse"] for x in g["hooks"])
    assert m["hooks"]["PreToolUse"][0]["matcher"] == "Read"


def test_deny_is_a_union_and_never_loses_a_live_entry():
    m, _, _ = merge(live(), tmpl(), HOME)
    assert m["permissions"]["deny"] == ["Read(b)", "Read(live-only)", "Read(a)"]
    assert m["permissions"]["allow"] == ["x"]


def test_absent_keys_added_present_values_never_overwritten_and_listed():
    m, added, skipped = merge(live(), tmpl(), HOME)
    assert m["model"] == "opus" and m["plugins"] == {"keep": True}
    assert m["sandbox"] == tmpl()["sandbox"]
    assert any(x.startswith("/sandbox") for x in added)
    assert "/model (value differs)" in skipped


def test_non_ade_hook_of_the_template_is_listed_not_applied():
    t = tmpl()
    t["hooks"]["Stop"] = [h("paseo hooks stop")]
    m, _, skipped = merge(live(), t, HOME)
    assert "Stop" not in m["hooks"] and any("/hooks/Stop" in x for x in skipped)


def test_second_run_is_idempotent():
    m, _, _ = merge(live(), tmpl(), HOME)
    m2, added, _ = merge(m, tmpl(), HOME)
    assert m2 == m and added == []


def test_refuses_when_a_live_key_would_disappear():
    assert sa.refuse_if_dropped({"a": {"b": 1}, "c": 1}, {"a": {}, "c": 1}) == ["/a/b"]
    assert sa.refuse_if_dropped(live(), merge(live(), tmpl(), HOME)[0]) == []


def cli(tmp_path, *args):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    lp = home / ".claude" / "settings.json"
    if not lp.exists():
        lp.write_text(json.dumps(live(), indent=2) + "\n")
        lp.chmod(0o600)
        (tmp_path / "t.tmpl").write_text(json.dumps(tmpl()))
    r = subprocess.run([sys.executable, str(BIN / "ade-settings-apply"), "--home", str(home), "--live", str(lp),
                        "--template", str(tmp_path / "t.tmpl"), *args], capture_output=True, text=True, timeout=60)
    return r, lp


def test_dry_run_changes_nothing_and_prints_the_sandbox(tmp_path):
    r, lp = cli(tmp_path)
    before = lp.read_text()
    assert r.returncode == 0 and "would add" in r.stdout and "the /sandbox block added" in r.stdout and "~/.ssh/x" in r.stdout
    assert lp.read_text() == before and not list(lp.parent.glob("settings.json.bak-*"))


def test_apply_backs_up_keeps_mode_and_is_idempotent(tmp_path):
    r, lp = cli(tmp_path, "--apply")
    assert r.returncode == 0 and "applied" in r.stdout
    baks = list(lp.parent.glob("settings.json.bak-*"))
    assert len(baks) == 1 and json.loads(baks[0].read_text()) == live()
    assert stat.S_IMODE(os.stat(lp).st_mode) == 0o600 and stat.S_IMODE(os.stat(baks[0]).st_mode) == 0o600
    out = json.loads(lp.read_text())
    assert out["permissions"]["deny"][-1] == "Read(a)" and out["model"] == "opus"
    r2, _ = cli(tmp_path, "--apply")
    assert "nothing to add" in r2.stdout and len(list(lp.parent.glob("settings.json.bak-*"))) == 1


def test_unreadable_live_exits_2_and_writes_nothing(tmp_path):
    lp = tmp_path / "s.json"
    lp.write_text("{not json")
    tp = tmp_path / "t.tmpl"
    tp.write_text("{}")
    r = subprocess.run([sys.executable, str(BIN / "ade-settings-apply"), "--live", str(lp), "--template", str(tp), "--apply"],
                       capture_output=True, text=True)
    assert r.returncode == 2 and lp.read_text() == "{not json"


def test_write_is_via_replace_not_in_place(tmp_path, monkeypatch):
    lp = tmp_path / "s.json"
    lp.write_text("{}")
    seen = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: (seen.append((a, b)), real(a, b))[1])
    sa.write_atomic(lp, {"a": 1})
    assert len(seen) == 1 and Path(seen[0][0]).parent == tmp_path and json.loads(lp.read_text()) == {"a": 1}


def test_only_the_add_list_is_added_env_and_plugins_are_listed():
    t = tmpl()
    t["env"] = {"ANTHROPIC_BASE_URL": "x"}
    t["enabledPlugins"] = {"p@m": True}
    t["modelSettings"] = {"m": {"a": 1}}
    m, added, skipped = merge(live(), t, HOME)
    assert "env" not in m and "enabledPlugins" not in m and m["modelSettings"] == {"m": {"a": 1}}
    assert any(x.startswith("/env") and "not on the add list" in x for x in skipped)


def test_sandbox_denyread_is_a_union_once_live_has_a_sandbox():
    lv = live()
    lv["sandbox"] = {"enabled": True, "filesystem": {"denyRead": ["~/mine"]}}
    m, added, _ = merge(lv, tmpl(), HOME)
    assert m["sandbox"]["filesystem"]["denyRead"] == ["~/mine", "~/.ssh/x"] and m["sandbox"]["enabled"] is True


def test_ade_hook_that_differs_in_matcher_is_listed_and_live_kept():
    lv = live()
    lv["hooks"]["PreToolUse"] = [{"matcher": "Bash", **h("~/.claude/hooks/secret_read_gate.py")}]
    m, _, skipped = merge(lv, tmpl(), HOME)
    assert m["hooks"]["PreToolUse"] == lv["hooks"]["PreToolUse"] and any("differs in matcher" in x for x in skipped)


def test_refusal_covers_list_elements_and_values():
    assert sa.refuse_if_dropped({"l": [1, 2]}, {"l": [1]}) == ["/l (list element)"]
    assert sa.refuse_if_dropped({"v": 1}, {"v": 2}) == ["/v (value)"]
    assert sa.refuse_if_dropped({"l": [1]}, {"l": [1, 2]}) == []


def test_backup_never_overwrites_an_earlier_one(tmp_path):
    lp = tmp_path / "s.json"
    lp.write_text("{}")
    lp.chmod(0o600)
    bk = tmp_path / "s.json.bak-X"
    a = sa.write_backup(lp, b"one", bk)
    b = sa.write_backup(lp, b"two", bk)
    assert a != b and a.read_bytes() == b"one" and b.read_bytes() == b"two" and stat.S_IMODE(os.stat(b).st_mode) == 0o600


def test_missing_or_foreign_script_is_never_added():
    t = tmpl()
    t["hooks"]["SessionStart"] = [h('"$HOME"/.claude/hooks/cswap_quota_context.sh'), h("bash '$HOME/.claude/hooks/plain.sh' session")]
    m, added, skipped = merge(live(), t, HOME)
    assert "SessionStart" not in m["hooks"]
    assert sum("not added (script missing or not in the djbclark-ade tree)" in x for x in skipped) == 2


def test_dedupe_key_is_the_script_path_alone():
    def k(c):
        return sa.hook_key(c, HOME)
    base = k('python3 "$HOME/.claude/hooks/x.py"')
    assert k('python3 "$HOME/.claude/hooks/x.py" 2>/dev/null') == base
    assert k('python3 "$HOME/.claude/hooks/x.py" --mode a') == base
    assert k('f="$HOME/.claude/hooks/x.py"; [ -f "$f" ] || exit 0; exec python3 "$f"') == base
    assert k("node $HOME/.claude/helpers/graft-hooks.cjs stop || exit 0") != k("node $HOME/.claude/helpers/graft-hooks.cjs start")


def test_render_template_refuses_a_secret_and_never_prints_it(tmp_path):
    lp = tmp_path / "s.json"
    lp.write_text(json.dumps({"env": {"GITHUB_TOKEN": "ghp_" + "a" * 30}}))
    tp = tmp_path / "t.tmpl"
    tp.write_text("{}")
    r = subprocess.run([sys.executable, str(BIN / "ade-settings-apply"), "--live", str(lp), "--template", str(tp), "--render-template"],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "/env/GITHUB_TOKEN" in r.stderr and "ghp_" not in r.stdout + r.stderr and r.stdout == ""


def test_unrender_only_replaces_a_whole_home_prefix():
    assert sa.unrender('"/Users/me/.x" "/Users/meX/y"', "/Users/me") == '"{{ .home }}/.x" "/Users/meX/y"'


def _patched_main(tmp_path, monkeypatch, fn):
    lp = tmp_path / "s.json"
    lp.write_text(json.dumps(live(), indent=2) + "\n")
    tp = tmp_path / "t.tmpl"
    tp.write_text("{}")
    monkeypatch.setattr(sa, "merge", fn)
    rc = sa.main(["--home", HOME, "--live", str(lp), "--template", str(tp), "--apply"])
    return rc, lp


def test_main_refuses_and_writes_nothing_when_a_live_key_would_vanish(tmp_path, monkeypatch):
    rc, lp = _patched_main(tmp_path, monkeypatch, lambda lv, t, h, roots=None, **kw: ({"model": "opus"}, ["x"], []))
    assert rc == 1 and json.loads(lp.read_text()) == live() and not list(tmp_path.glob("*.bak-*"))


def test_main_aborts_when_live_changed_while_merging(tmp_path, monkeypatch):
    def fn(lv, t, h, roots=None, **kw):
        (tmp_path / "s.json").write_text('{"changed": true}')
        return dict(lv, sandbox={"x": 1}), ["/sandbox"], []
    rc, lp = _patched_main(tmp_path, monkeypatch, fn)
    assert rc == 1 and json.loads(lp.read_text()) == {"changed": True} and not list(tmp_path.glob("*.bak-*"))


def test_write_atomic_keeps_a_non_default_mode(tmp_path):
    lp = tmp_path / "s.json"
    lp.write_text("{}")
    lp.chmod(0o640)
    sa.write_atomic(lp, {"a": 1})
    assert stat.S_IMODE(os.stat(lp).st_mode) == 0o640


def test_dangling_link_into_the_ade_tree_is_never_added_but_an_existing_one_is(tmp_path):
    root = tmp_path / "ade"
    (root / "claude" / "hooks").mkdir(parents=True)
    (root / "claude" / "hooks" / "real.sh").write_text("x")
    home = tmp_path / "home"
    (home / ".claude" / "hooks").mkdir(parents=True)
    os.symlink(root / "claude" / "hooks" / "gone.sh", home / ".claude" / "hooks" / "gone.sh")  # target inside the tree, absent
    os.symlink(root / "claude" / "hooks" / "real.sh", home / ".claude" / "hooks" / "real.sh")
    (home / ".claude" / "hooks" / "outside.sh").write_text("x")
    t = {"hooks": {"SessionStart": [h("$HOME/.claude/hooks/gone.sh"), h("$HOME/.claude/hooks/real.sh"),
                                    h("$HOME/.claude/hooks/outside.sh"), h("$HOME/src/djbclark-ade/bin/nope")]}}
    m, added, skipped = _merge({}, t, str(home), [root])
    cmds = [x["command"] for g in m["hooks"]["SessionStart"] for x in g["hooks"]]
    assert cmds == ["$HOME/.claude/hooks/real.sh"]
    assert sum("not added" in x for x in skipped) == 3


def test_a_secret_inside_a_list_or_a_newer_token_shape_is_refused():
    assert sa.secret_paths({"a": ["x", "ghp_" + "a" * 30]}) == ["/a[1]"]
    assert sa.secret_paths({"url": "https://h/mcp?api_key=abc123"}) == ["/url"]
    assert sa.secret_paths({"c": "FOO_SECRET=abc run"}) == ["/c"]
    assert sa.secret_paths({"ok": "post-edit-check --hook"}) == []


def test_allow_env_flags_add_and_remove_only_named_keys():
    """--allow-env-add names keys that may be added, --allow-env-remove keys that may be removed (separate, so adding
    from an older template cannot silently remove). Everything else stays (adversary A1)."""
    lv = {"env": {"AGENT_TEAMS": "1", "KEEP": "x"}}
    t = {"env": {"CODE_MODE": "1", "KEEP": "x"}}
    m, added, skipped = _merge(lv, t, HOME, ROOTS)  # nothing named: nothing added or removed
    assert m["env"] == lv["env"]
    rm = []
    m, added, skipped = _merge(lv, t, HOME, ROOTS, allow_env_add={"CODE_MODE"}, allow_env_remove={"AGENT_TEAMS"}, removed=rm)
    assert m["env"] == {"CODE_MODE": "1", "KEEP": "x"}
    assert rm == ["/env/AGENT_TEAMS"]
    assert any(x.startswith("/env/AGENT_TEAMS") and "removed" in x for x in added)
    assert any(x.startswith("/env/CODE_MODE") and "absent" in x for x in added)
    # add alone never removes; remove alone never adds
    m, _, _ = _merge(lv, t, HOME, ROOTS, allow_env_add={"CODE_MODE", "AGENT_TEAMS"})
    assert m["env"] == {"AGENT_TEAMS": "1", "KEEP": "x", "CODE_MODE": "1"}
    rm = []
    m, _, _ = _merge(lv, t, HOME, ROOTS, allow_env_remove={"AGENT_TEAMS", "CODE_MODE"}, removed=rm)
    assert m["env"] == {"KEEP": "x"} and rm == ["/env/AGENT_TEAMS"]


def test_a_named_removal_needs_the_template_to_have_dropped_the_key():
    """A stale or wrong template that still carries the key removes nothing, and never changes its value."""
    lv = {"env": {"FLAG": "0"}}
    m, added, skipped = _merge(lv, {"env": {"FLAG": "1"}}, HOME, ROOTS, allow_env_remove={"FLAG"}, allow_env_add={"FLAG"})
    assert m == lv and added == [] and "/env/FLAG (value differs)" in skipped


def test_allow_env_add_with_no_live_env_block_adds_only_named_keys():
    m, added, skipped = _merge({"model": "x"}, {"env": {"CODE_MODE": "1", "OTHER": "2"}}, HOME, ROOTS, allow_env_add={"CODE_MODE"})
    assert m["env"] == {"CODE_MODE": "1"}
    assert "/env/CODE_MODE (key absent from live)" in added
    assert any(x.startswith("/env/OTHER") for x in skipped)
    # nothing named: no env block is created (A1), and a named key the template lacks creates no empty one
    m, _, skipped = _merge({"model": "x"}, {"env": {"CODE_MODE": "1"}}, HOME, ROOTS)
    assert "env" not in m and any(x.startswith("/env ") for x in skipped)
    m, _, _ = _merge({"model": "x"}, {"env": {"CODE_MODE": "1"}}, HOME, ROOTS, allow_env_add={"NOPE"})
    assert "env" not in m


def test_a_template_without_any_env_block_still_removes_only_the_named_key():
    rm = []
    m, _, _ = _merge({"env": {"A": "1", "B": "2"}}, {"model": "x"}, HOME, ROOTS, allow_env_remove={"A"}, removed=rm)
    assert m["env"] == {"B": "2"} and rm == ["/env/A"]


def test_refuse_if_dropped_exempts_exactly_the_named_paths():
    lv = {"env": {"A": "1", "B": "2"}, "model": "x"}
    assert sa.refuse_if_dropped(lv, {"env": {"B": "2"}, "model": "x"}, ["/env/A"]) == []
    assert sa.refuse_if_dropped(lv, {"env": {"B": "2"}, "model": "x"}) == ["/env/A"]
    # an exemption never covers a different path
    assert sa.refuse_if_dropped(lv, {"env": {}, "model": "x"}, ["/env/A"]) == ["/env/B"]
    assert sa.refuse_if_dropped(lv, {"env": {"A": "1", "B": "2"}}, ["/env/A"]) == ["/model"]


SECRETISH = "sk-" + "a1b2c3d4e5f6a7b8c9d0e1f2"


def _end_to_end(tmp_path, live_obj, tmpl_obj, *flags):
    lp = tmp_path / "s.json"
    lp.write_text(json.dumps(live_obj, indent=2) + "\n")
    lp.chmod(0o640)
    tp = tmp_path / "t.tmpl"
    tp.write_text(json.dumps(tmpl_obj))
    r = subprocess.run([sys.executable, str(BIN / "ade-settings-apply"), "--home", HOME, "--live", str(lp), "--template", str(tp), *flags],
                       capture_output=True, text=True)
    return r, lp


def test_main_end_to_end_the_844_case_drops_agent_teams_and_adds_code_mode(tmp_path):
    """The #844 case through the real CLI: drop AGENT_TEAMS, add CODE_MODE, keep everything else, one backup, no values printed."""
    lv = {"model": "opus", "env": {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": SECRETISH, "KEEP": "keepval"}}
    t = {"model": "opus", "env": {"CLAUDE_CODE_EXPERIMENTAL_CODE_MODE": "codemodeval", "KEEP": "keepval"}}
    flags = ["--allow-env-remove", "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "--allow-env-add", "CLAUDE_CODE_EXPERIMENTAL_CODE_MODE"]
    r, lp = _end_to_end(tmp_path, lv, t, *flags)  # dry-run first: reports, writes nothing
    assert r.returncode == 0, r.stderr
    assert json.loads(lp.read_text()) == lv and not list(tmp_path.glob("*.bak-*"))
    assert "/env/CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" in r.stdout and "/env/CLAUDE_CODE_EXPERIMENTAL_CODE_MODE" in r.stdout
    r, lp = _end_to_end(tmp_path, lv, t, *flags, "--apply", "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(lp.read_text()) == {"model": "opus", "env": {"CLAUDE_CODE_EXPERIMENTAL_CODE_MODE": "codemodeval", "KEEP": "keepval"}}
    baks = list(tmp_path.glob("s.json.bak-*"))
    assert len(baks) == 1 and json.loads(baks[0].read_text()) == lv
    assert stat.S_IMODE(os.stat(lp).st_mode) == 0o640 and stat.S_IMODE(os.stat(baks[0]).st_mode) == 0o640
    rep = json.loads(r.stdout)
    assert rep["applied"] is True and rep["dropped"] == [] and rep["removed"] == ["/env/CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"]
    assert SECRETISH not in r.stdout + r.stderr and "codemodeval" not in r.stdout + r.stderr and "keepval" not in r.stdout + r.stderr


def test_main_add_alone_leaves_the_stale_key_in_place(tmp_path):
    lv = {"env": {"AGENT_TEAMS": "1", "KEEP": "x"}}
    t = {"env": {"CODE_MODE": "1", "KEEP": "x"}}
    r, lp = _end_to_end(tmp_path, lv, t, "--allow-env-add", "CODE_MODE", "--apply")
    assert r.returncode == 0, r.stderr  # an add alone leaves AGENT_TEAMS in place, so nothing disappears
    assert json.loads(lp.read_text())["env"] == {"AGENT_TEAMS": "1", "KEEP": "x", "CODE_MODE": "1"}


def test_main_refuses_a_removal_with_an_older_template_that_still_has_the_key(tmp_path):
    lv = {"env": {"AGENT_TEAMS": "1"}}
    r, lp = _end_to_end(tmp_path, lv, {"env": {"AGENT_TEAMS": "1"}}, "--allow-env-remove", "AGENT_TEAMS", "--apply")
    assert r.returncode == 0 and json.loads(lp.read_text()) == lv and not list(tmp_path.glob("*.bak-*"))


def test_main_end_to_end_adds_into_a_live_file_with_no_env_block(tmp_path):
    r, lp = _end_to_end(tmp_path, {"model": "x"}, {"model": "x", "env": {"CODE_MODE": "1", "OTHER": "2"}}, "--allow-env-add", "CODE_MODE", "--apply")
    assert r.returncode == 0, r.stderr
    assert json.loads(lp.read_text()) == {"model": "x", "env": {"CODE_MODE": "1"}}


def test_main_still_refuses_any_other_disappearing_key_even_with_a_remove_flag(tmp_path, monkeypatch):
    lv = {"env": {"A": "1", "B": "2"}}
    lp = tmp_path / "s.json"
    lp.write_text(json.dumps(lv))
    tp = tmp_path / "t.tmpl"
    tp.write_text("{}")
    monkeypatch.setattr(sa, "merge", lambda live, t, h, roots=None, **kw: (kw["removed"].append("/env/A") or {"env": {}}, ["x"], []))
    rc = sa.main(["--home", HOME, "--live", str(lp), "--template", str(tp), "--apply", "--allow-env-remove", "A"])
    assert rc == 1 and json.loads(lp.read_text()) == lv and not list(tmp_path.glob("*.bak-*"))
