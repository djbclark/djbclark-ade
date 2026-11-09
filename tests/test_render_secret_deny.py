#!/usr/bin/env python3
"""bin/render-secret-deny: the secret-deny policy rendered into the hook JSON and the Claude template (2026-11-04).

Every render runs on copies in tmp_path (of the real template and policy), never on the tracked files."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RENDER = ROOT / "bin" / "render-secret-deny"
TOML = ROOT / "config" / "secret-deny.toml"
POLICY_JSON = ROOT / "config" / "secret_deny_policy.json"
TMPL = ROOT / "agents" / "claude" / "settings.json.tmpl"
TAG = re.compile(r"\{\{.*?\}\}")

EXPECTED_STATIC = [
    "**/.env", "**/*.key", "**/*.p12", "**/*.pfx", "**/*-key.pem", "**/*.key.pem", "**/privkey*.pem",
    "**/id_rsa", "**/id_ecdsa", "**/id_ed25519", "~/.ssh/id_rsa", "~/.ssh/id_ecdsa", "~/.ssh/id_ed25519",
    "~/.aws/credentials", "~/.netrc", "~/.config/gh/hosts.yml", "~/.docker/config.json", "~/.kube/config",
]


@pytest.fixture
def fx(tmp_path):
    shutil.copy(TOML, tmp_path / "policy.toml")
    shutil.copy(TMPL, tmp_path / "settings.json.tmpl")
    return tmp_path


def render(fx, *extra, policy=None, tmpl=None, out=None):
    args = [sys.executable, str(RENDER),
            "--policy", str(policy or fx / "policy.toml"),
            "--policy-json", str(out or fx / "policy.json"),
            "--claude-template", str(tmpl or fx / "settings.json.tmpl"), *extra]
    return subprocess.run(args, capture_output=True, text=True, timeout=60)


def masked(path: Path) -> dict:
    return json.loads(TAG.sub("x", path.read_text()))


def managed(entry: str) -> bool:
    return entry.startswith(("Read(", "Edit("))


def test_render_writes_the_expected_static_entries(fx):
    r = render(fx)
    assert r.returncode == 0, r.stderr
    deny = masked(fx / "settings.json.tmpl")["permissions"]["deny"]
    got = [e for e in deny if managed(e)]
    assert got == [f"Read({p})" for p in EXPECTED_STATIC] + [f"Edit({p})" for p in EXPECTED_STATIC]
    assert not any(e.startswith(("Read(!", "Edit(!")) for e in deny)


def test_static_entries_avoid_every_allow_exception(fx):
    render(fx)
    text = " ".join(e for e in masked(fx / "settings.json.tmpl")["permissions"]["deny"] if managed(e))
    for hook_only in ("(**/.env.*)", "(~/.ssh/**)", "(~/.ssh/id_*)", "(**/*.pem)"):
        assert hook_only not in text


def test_render_is_idempotent_and_check_is_clean(fx):
    assert render(fx).returncode == 0
    first = (fx / "settings.json.tmpl").read_text(), (fx / "policy.json").read_text()
    r = render(fx)
    assert r.returncode == 0 and "already up to date" in r.stdout
    assert ((fx / "settings.json.tmpl").read_text(), (fx / "policy.json").read_text()) == first
    assert render(fx, "--check").returncode == 0


def test_tags_and_other_entries_survive(fx):
    before = TMPL.read_text()
    render(fx)
    after = (fx / "settings.json.tmpl").read_text()
    assert TAG.findall(after) == TAG.findall(before)
    old, new = masked(TMPL), masked(fx / "settings.json.tmpl")
    assert [e for e in new["permissions"]["deny"] if not managed(e)] == \
        [e for e in old["permissions"]["deny"] if not managed(e)]
    old["permissions"]["deny"] = new["permissions"]["deny"]
    assert old == new
    # only the deny block's lines changed
    changed = [ln for ln in after.splitlines() if ln not in before.splitlines()]
    assert all(re.search(r'"(Read|Edit)\(', ln) or ln.strip().rstrip(",").startswith('"') for ln in changed)


def test_check_reports_template_drift_with_a_diff(fx):
    render(fx)
    t = fx / "settings.json.tmpl"
    text = t.read_text().replace('      "Read(~/.netrc)",\n', "")
    t.write_text(text)
    r = render(fx, "--check")
    assert r.returncode == 1
    assert "+" in r.stdout and "Read(~/.netrc)" in r.stdout
    assert t.read_text() == text            # --check writes nothing


def test_check_reports_policy_json_drift(fx):
    render(fx)
    j = fx / "policy.json"
    j.write_text(j.read_text().replace('"~/.netrc",\n', ""))
    assert render(fx, "--check").returncode == 1
    j.unlink()
    assert render(fx, "--check").returncode == 1


def test_hand_added_read_entry_is_replaced_and_other_entries_keep_their_order(fx):
    t = fx / "settings.json.tmpl"
    t.write_text(t.read_text().replace('      "Artifact",\n', '      "Read(foo)",\n      "Artifact",\n', 1))
    assert render(fx).returncode == 0
    deny = masked(t)["permissions"]["deny"]
    assert "Read(foo)" not in deny
    assert deny[:5] == ["Artifact", "ScheduleWakeup", "SendFeedback", "Workflow", "mcp__basic-memory__delete_project"]


def test_inline_empty_deny_list(fx):
    t = fx / "tiny.json.tmpl"
    t.write_text('{\n  "env": {"H": "{{ .home }}"},\n  "permissions": {\n    "allow": [],\n    "deny": [],\n'
                 '    "defaultMode": "x"\n  }\n}\n')
    assert render(fx, tmpl=t).returncode == 0
    data = masked(t)
    assert data["permissions"]["deny"][0] == "Read(**/.env)"
    assert data["env"] == {"H": "x"} and data["permissions"]["defaultMode"] == "x"
    assert render(fx, "--check", tmpl=t).returncode == 0


def test_committed_policy_json_equals_a_fresh_render(fx):
    r = render(fx, policy=TOML)
    assert r.returncode == 0, r.stderr
    assert (fx / "policy.json").read_text() == POLICY_JSON.read_text()


def test_policy_json_shape(fx):
    render(fx)
    data = json.loads((fx / "policy.json").read_text())
    assert data["version"] == 1
    assert ".env" in data["deny"] and ".env.example" in data["allow"]
    assert "*.pem" not in data["deny"]


# ---- refusals: exit 2, nothing written -------------------------------------------------------------------------------
def write_policy(fx, deny, allow, static):
    def arr(xs):
        return "[" + ", ".join(json.dumps(x) for x in xs) + "]"
    (fx / "policy.toml").write_text(f"version = 1\ndeny = {arr(deny)}\nallow = {arr(allow)}\n[claude]\nstatic = {arr(static)}\n")


@pytest.mark.parametrize("deny,allow,static", [
    ([".env", "~/.ssh/**"], ["*.pub"], ["~/.ssh/**"]),          # static overlaps an allow exception
    ([".env.*"], [".env.example"], [".env.*"]),                  # same
    ([".env"], [], ["*.key"]),                                    # static not inside the deny list
    (["[ab].env"], [], []),                                       # character classes refused
    (["secrets/x"], [], []),                                      # relative with a slash refused
    (["a**b"], [], []),                                           # ** not a whole segment
    (["!x"], [], []),
    (["x y"], [], []),
    (["foo/"], [], []),
    ([], [], []),                                                 # empty deny
])
def test_bad_policy_is_refused(fx, deny, allow, static):
    write_policy(fx, deny, allow, static)
    before = (fx / "settings.json.tmpl").read_text()
    r = render(fx)
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert (fx / "settings.json.tmpl").read_text() == before
    assert not (fx / "policy.json").exists()


def test_narrower_static_inside_a_wider_deny_is_accepted(fx):
    write_policy(fx, ["~/.ssh/**", "id_rsa"], ["*.pub", "~/.ssh/config"], ["~/.ssh/id_rsa", "id_rsa"])
    assert render(fx).returncode == 0


def test_bad_toml_is_refused(fx):
    (fx / "policy.toml").write_text("version = 1\ndeny = [\n")
    assert render(fx).returncode == 2


def test_wrong_version_is_refused(fx):
    (fx / "policy.toml").write_text('version = 2\ndeny = [".env"]\nallow = []\n')
    assert render(fx).returncode == 2


def test_missing_anchor_is_refused(fx):
    t = fx / "no-perm.json.tmpl"
    t.write_text('{\n  "env": {}\n}\n')
    assert render(fx, tmpl=t).returncode == 2
    t.write_text('{\n  "permissions": {\n    "allow": []\n  }\n}\n')
    assert render(fx, tmpl=t).returncode == 2


def test_deny_entry_on_a_shared_line_is_refused(fx):
    t = fx / "odd.json.tmpl"
    t.write_text('{\n  "permissions": {\n    "deny": [\n      "A", "B"\n    ]\n  }\n}\n')
    assert render(fx, tmpl=t).returncode == 2


def test_usage_error_is_2(fx):
    r = subprocess.run([sys.executable, str(RENDER), "--bogus"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2


def test_template_mode_is_kept(fx):
    t = fx / "settings.json.tmpl"
    t.chmod(0o600)
    render(fx)
    assert t.stat().st_mode & 0o777 == 0o600


def test_rendered_template_passes_ade_template_check(fx):
    render(fx)
    root = fx / "root"
    (root / "agents" / "claude").mkdir(parents=True)
    shutil.copy(fx / "settings.json.tmpl", root / "agents" / "claude" / "settings.json.tmpl")
    shutil.copy(ROOT / "agents" / "README.md", root / "agents" / "README.md")
    r = subprocess.run([sys.executable, str(ROOT / "bin" / "ade-template-check"), "--root", str(root),
                        str(root / "agents" / "claude" / "settings.json.tmpl")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


def test_executable_with_env_shebang():
    assert RENDER.read_text().startswith("#!/usr/bin/env python3\n")
    assert RENDER.stat().st_mode & 0o100


def _load_render():
    import importlib.machinery
    import importlib.util

    loader = importlib.machinery.SourceFileLoader("render_secret_deny", str(RENDER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_default_load_policy_uses_load_effective(tmp_path, monkeypatch):
    """S1: no --policy path → effective secret_deny (legacy file when ade.toml absent)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    mod = _load_render()
    via_path, src_path = mod.load_policy(TOML)
    via_eff, src_eff = mod.load_policy(root=ROOT, home=home, environ={})
    assert via_eff == via_path
    assert via_eff["deny"]
    assert "secret-deny.toml" in src_eff or "secret-deny.toml" in src_path


def test_secret_deny_toml_env_reaches_load_policy(tmp_path, monkeypatch):
    import os

    home = tmp_path / "home"
    home.mkdir()
    selected = tmp_path / "override.toml"
    selected.write_text(
        'version = 1\ndeny = [".only"]\nallow = []\n[claude]\nstatic = [".only"]\n'
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SECRET_DENY_TOML", str(selected))
    mod = _load_render()
    pol, _ = mod.load_policy(root=ROOT, home=home, environ=dict(os.environ))
    assert pol["deny"] == [".only"]
    assert pol["static"] == [".only"]
