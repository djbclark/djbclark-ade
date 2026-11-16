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

HOME = "/h"
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
            "PostToolUse": [h("node /h/.claude/helpers/graft-hooks.cjs post-edit || exit 0"), h("paseo hooks x")],
        },
        "permissions": {"deny": ["Read(b)", "Read(live-only)"], "allow": ["x"]},
    }


def test_hook_dedupe_by_path_keeps_the_live_wrapper():
    m, added, _ = sa.merge(live(), tmpl(), HOME)
    cmds = [x["command"] for g in m["hooks"]["PostToolUse"] for x in g["hooks"]]
    assert sum("graft-hooks.cjs" in c for c in cmds) == 1 and any(c.endswith("|| exit 0") for c in cmds)
    assert any("post-edit-check" in c for c in cmds)  # the template-only ADE hook is added
    assert any("secret_read_gate.py" in x["command"] for g in m["hooks"]["PreToolUse"] for x in g["hooks"])
    assert m["hooks"]["PreToolUse"][0]["matcher"] == "Read"


def test_deny_is_a_union_and_never_loses_a_live_entry():
    m, _, _ = sa.merge(live(), tmpl(), HOME)
    assert m["permissions"]["deny"] == ["Read(b)", "Read(live-only)", "Read(a)"]
    assert m["permissions"]["allow"] == ["x"]


def test_absent_keys_added_present_values_never_overwritten_and_listed():
    m, added, skipped = sa.merge(live(), tmpl(), HOME)
    assert m["model"] == "opus" and m["plugins"] == {"keep": True}
    assert m["sandbox"] == tmpl()["sandbox"]
    assert any(x.startswith("/sandbox") for x in added)
    assert "/model (value differs)" in skipped


def test_non_ade_hook_of_the_template_is_listed_not_applied():
    t = tmpl()
    t["hooks"]["Stop"] = [h("paseo hooks stop")]
    m, _, skipped = sa.merge(live(), t, HOME)
    assert "Stop" not in m["hooks"] and any("/hooks/Stop" in x for x in skipped)


def test_second_run_is_idempotent():
    m, _, _ = sa.merge(live(), tmpl(), HOME)
    m2, added, _ = sa.merge(m, tmpl(), HOME)
    assert m2 == m and added == []


def test_refuses_when_a_live_key_would_disappear():
    assert sa.refuse_if_dropped({"a": {"b": 1}, "c": 1}, {"a": {}, "c": 1}) == ["/a/b"]
    assert sa.refuse_if_dropped(live(), sa.merge(live(), tmpl(), HOME)[0]) == []


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
    m, added, skipped = sa.merge(live(), t, HOME)
    assert "env" not in m and "enabledPlugins" not in m and m["modelSettings"] == {"m": {"a": 1}}
    assert any(x.startswith("/env") and "not on the add list" in x for x in skipped)


def test_sandbox_denyread_is_a_union_once_live_has_a_sandbox():
    lv = live()
    lv["sandbox"] = {"enabled": True, "filesystem": {"denyRead": ["~/mine"]}}
    m, added, _ = sa.merge(lv, tmpl(), HOME)
    assert m["sandbox"]["filesystem"]["denyRead"] == ["~/mine", "~/.ssh/x"] and m["sandbox"]["enabled"] is True


def test_ade_hook_that_differs_in_matcher_is_listed_and_live_kept():
    lv = live()
    lv["hooks"]["PreToolUse"] = [{"matcher": "Bash", **h("~/.claude/hooks/secret_read_gate.py")}]
    m, _, skipped = sa.merge(lv, tmpl(), HOME)
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
