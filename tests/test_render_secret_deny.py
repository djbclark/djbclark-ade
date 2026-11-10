#!/usr/bin/env python3
"""bin/render-secret-deny: the secret-deny policy rendered into the hook JSON, Claude template, and Codex profile (2026-11-04; Codex 2026-11-09/10).

Every render runs on copies in tmp_path (of the real templates and policy), never on the tracked files.
sandbox.filesystem.denyRead coverage added 2026-11-09 (queue Carried #1 / issue #284 C3)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RENDER = ROOT / "bin" / "render-secret-deny"
TOML = ROOT / "config" / "secret-deny.toml"
POLICY_JSON = ROOT / "config" / "secret_deny_policy.json"
TMPL = ROOT / "agents" / "claude" / "settings.json.tmpl"
CODEX_TMPL = ROOT / "agents" / "codex" / "config.toml.tmpl"
CODEX_BEGIN = "# BEGIN ade-secret-deny (managed by bin/render-secret-deny; do not edit by hand)"
TAG = re.compile(r"\{\{.*?\}\}")

EXPECTED_STATIC = [
    "**/.env", "**/*.key", "**/*.p12", "**/*.pfx", "**/*-key.pem", "**/*.key.pem", "**/privkey*.pem",
    "**/id_rsa", "**/id_ecdsa", "**/id_ed25519", "~/.ssh/id_rsa", "~/.ssh/id_ecdsa", "~/.ssh/id_ed25519",
    "~/.aws/credentials", "~/.netrc", "~/.config/gh/hosts.yml", "~/.docker/config.json", "~/.kube/config",
]
# Sandbox form: bare/`**/` names are home-anchored (`~/**/…`); exact `~/…` paths stay.
EXPECTED_SANDBOX_DENY_READ = [
    "~/**/.env", "~/**/*.key", "~/**/*.p12", "~/**/*.pfx", "~/**/*-key.pem", "~/**/*.key.pem",
    "~/**/privkey*.pem", "~/**/id_rsa", "~/**/id_ecdsa", "~/**/id_ed25519",
    "~/.ssh/id_rsa", "~/.ssh/id_ecdsa", "~/.ssh/id_ed25519",
    "~/.aws/credentials", "~/.netrc", "~/.config/gh/hosts.yml", "~/.docker/config.json", "~/.kube/config",
]
EXPECTED_CODEX_ROOTS = [
    "**/.env", "**/*.key", "**/*.p12", "**/*.pfx", "**/*-key.pem", "**/*.key.pem", "**/privkey*.pem",
    "**/id_rsa", "**/id_ecdsa", "**/id_ed25519",
]


@pytest.fixture
def fx(tmp_path):
    shutil.copy(TOML, tmp_path / "policy.toml")
    shutil.copy(TMPL, tmp_path / "settings.json.tmpl")
    shutil.copy(CODEX_TMPL, tmp_path / "config.toml.tmpl")
    return tmp_path


def render(fx, *extra, policy=None, tmpl=None, codex=None, out=None):
    args = [sys.executable, str(RENDER),
            "--policy", str(policy or fx / "policy.toml"),
            "--policy-json", str(out or fx / "policy.json"),
            "--claude-template", str(tmpl or fx / "settings.json.tmpl"),
            "--codex-template", str(codex or fx / "config.toml.tmpl"), *extra]
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


def test_render_writes_sandbox_filesystem_deny_read(fx):
    r = render(fx)
    assert r.returncode == 0, r.stderr
    data = masked(fx / "settings.json.tmpl")
    sb = data["sandbox"]
    assert sb["filesystem"]["denyRead"] == EXPECTED_SANDBOX_DENY_READ
    assert "enabled" not in sb, "render must not enable the sandbox; live apply is order 11"


def test_static_entries_avoid_every_allow_exception(fx):
    render(fx)
    text = " ".join(e for e in masked(fx / "settings.json.tmpl")["permissions"]["deny"] if managed(e))
    for hook_only in ("(**/.env.*)", "(~/.ssh/**)", "(~/.ssh/id_*)", "(**/*.pem)"):
        assert hook_only not in text
    deny_read = " ".join(masked(fx / "settings.json.tmpl")["sandbox"]["filesystem"]["denyRead"])
    for hook_only in ("~/**/.env.*", "~/.ssh/**", "~/**/*.pem"):
        assert hook_only not in deny_read


def test_render_is_idempotent_and_check_is_clean(fx):
    assert render(fx).returncode == 0
    first = ((fx / "settings.json.tmpl").read_text(), (fx / "policy.json").read_text(),
             (fx / "config.toml.tmpl").read_text())
    r = render(fx)
    assert r.returncode == 0 and "already up to date" in r.stdout
    assert ((fx / "settings.json.tmpl").read_text(), (fx / "policy.json").read_text(),
            (fx / "config.toml.tmpl").read_text()) == first
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
    # committed template already carries denyRead; sync it for the equality check
    old.setdefault("sandbox", {}).setdefault("filesystem", {})["denyRead"] = \
        new["sandbox"]["filesystem"]["denyRead"]
    assert old == new
    changed = [ln for ln in after.splitlines() if ln not in before.splitlines()]
    assert all(
        re.search(r'"(Read|Edit)\(', ln)
        or '"denyRead"' in ln
        or '"sandbox"' in ln
        or '"filesystem"' in ln
        or ln.strip().rstrip(",").startswith('"')
        or ln.strip() in ("{", "}", "},", "],", "]")
        for ln in changed
    )


def test_check_reports_template_drift_with_a_diff(fx):
    render(fx)
    t = fx / "settings.json.tmpl"
    text = t.read_text().replace('      "Read(~/.netrc)",\n', "")
    t.write_text(text)
    r = render(fx, "--check")
    assert r.returncode == 1
    assert "+" in r.stdout and "Read(~/.netrc)" in r.stdout
    assert t.read_text() == text            # --check writes nothing


def test_check_reports_sandbox_deny_read_drift(fx):
    render(fx)
    t = fx / "settings.json.tmpl"
    text = t.read_text().replace('        "~/.netrc",\n', "", 1)
    t.write_text(text)
    r = render(fx, "--check")
    assert r.returncode == 1
    assert "~/.netrc" in r.stdout and "+" in r.stdout
    assert t.read_text() == text


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


def test_hand_added_sandbox_deny_read_is_replaced_other_sandbox_keys_kept(fx):
    t = fx / "settings.json.tmpl"
    data = masked(t)
    # seed a sandbox with enabled + a foreign denyRead path, then re-render
    seeded = {
        **{k: v for k, v in data.items() if k != "sandbox"},
        "sandbox": {
            "enabled": True,
            "filesystem": {
                "allowWrite": ["/tmp/build"],
                "denyRead": ["~/custom-secret"],
            },
            "network": {"allowedDomains": ["github.com"]},
        },
    }
    # write with tags restored for home placeholders that were masked to x in unrelated strings only;
    # the fixture copy still has real tags — rebuild from the rendered text by splicing keys.
    text = t.read_text()
    # replace the existing sandbox block with a richer one
    import re as _re
    rich = (
        '  "sandbox": {\n'
        '    "enabled": true,\n'
        '    "filesystem": {\n'
        '      "allowWrite": ["/tmp/build"],\n'
        '      "denyRead": [\n'
        '        "~/custom-secret"\n'
        '      ]\n'
        '    },\n'
        '    "network": {"allowedDomains": ["github.com"]}\n'
        '  },\n'
    )
    text2, n = _re.subn(
        r'  "sandbox": \{.*?\n  \},?\n',
        rich,
        text,
        count=1,
        flags=_re.S,
    )
    assert n == 1
    t.write_text(text2)
    assert render(fx, tmpl=t).returncode == 0, render(fx, tmpl=t).stderr
    sb = masked(t)["sandbox"]
    assert sb["enabled"] is True
    assert sb["filesystem"]["allowWrite"] == ["/tmp/build"]
    assert sb["network"] == {"allowedDomains": ["github.com"]}
    assert sb["filesystem"]["denyRead"] == EXPECTED_SANDBOX_DENY_READ
    assert "~/custom-secret" not in sb["filesystem"]["denyRead"]


def test_inline_empty_deny_list(fx):
    t = fx / "tiny.json.tmpl"
    t.write_text('{\n  "env": {"H": "{{ .home }}"},\n  "permissions": {\n    "allow": [],\n    "deny": [],\n'
                 '    "defaultMode": "x"\n  }\n}\n')
    assert render(fx, tmpl=t).returncode == 0
    data = masked(t)
    assert data["permissions"]["deny"][0] == "Read(**/.env)"
    assert data["sandbox"]["filesystem"]["denyRead"] == EXPECTED_SANDBOX_DENY_READ
    assert "enabled" not in data["sandbox"]
    assert data["env"] == {"H": "x"} and data["permissions"]["defaultMode"] == "x"
    assert render(fx, "--check", tmpl=t).returncode == 0


def test_inline_empty_sandbox_object(fx):
    """`"sandbox": {}` on one line must expand before insert (Codex P2 on fb2918d2)."""
    t = fx / "inline-sandbox.json.tmpl"
    t.write_text(
        '{\n  "env": {"H": "{{ .home }}"},\n  "permissions": {\n    "allow": [],\n    "deny": [],\n'
        '    "defaultMode": "x"\n  },\n  "sandbox": {}\n}\n'
    )
    r = render(fx, tmpl=t)
    assert r.returncode == 0, r.stderr
    data = masked(t)
    assert data["sandbox"]["filesystem"]["denyRead"] == EXPECTED_SANDBOX_DENY_READ
    assert "enabled" not in data["sandbox"]
    assert data["env"] == {"H": "x"} and data["permissions"]["defaultMode"] == "x"
    assert render(fx, "--check", tmpl=t).returncode == 0


def test_inline_empty_filesystem_object(fx):
    """`"filesystem": {}` on one line inside sandbox must expand before insert (Codex P2 on fb2918d2)."""
    t = fx / "inline-filesystem.json.tmpl"
    t.write_text(
        '{\n  "env": {"H": "{{ .home }}"},\n  "permissions": {\n    "allow": [],\n    "deny": [],\n'
        '    "defaultMode": "x"\n  },\n  "sandbox": {\n    "filesystem": {}\n  }\n}\n'
    )
    r = render(fx, tmpl=t)
    assert r.returncode == 0, r.stderr
    data = masked(t)
    assert data["sandbox"]["filesystem"]["denyRead"] == EXPECTED_SANDBOX_DENY_READ
    assert "enabled" not in data["sandbox"]
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
    assert ".env" in data["codex_static"]
    assert data["codex_static"] == data["claude_static"]


# ---- refusals: exit 2, nothing written -------------------------------------------------------------------------------
def write_policy(fx, deny, allow, static, codex_static=None):
    def arr(xs):
        return "[" + ", ".join(json.dumps(x) for x in xs) + "]"
    cs = static if codex_static is None else codex_static
    (fx / "policy.toml").write_text(
        f"version = 1\ndeny = {arr(deny)}\nallow = {arr(allow)}\n"
        f"[claude]\nstatic = {arr(static)}\n[codex]\nstatic = {arr(cs)}\n")


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
    before_codex = (fx / "config.toml.tmpl").read_text()
    r = render(fx)
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert (fx / "settings.json.tmpl").read_text() == before
    assert (fx / "config.toml.tmpl").read_text() == before_codex
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



def test_render_writes_codex_ade_secret_deny_profile(fx):
    r = render(fx)
    assert r.returncode == 0, r.stderr
    text = (fx / "config.toml.tmpl").read_text()
    assert CODEX_BEGIN in text and "# END ade-secret-deny" in text
    assert not re.search(r'(?m)^default_permissions\s*=\s*"ade-secret-deny"\s*$', text)
    masked_txt = TAG.sub("x", text)
    data = tomllib.loads(masked_txt)
    assert data.get("default_permissions") != "ade-secret-deny"
    assert data["sandbox_mode"] == "danger-full-access"
    profile = data["permissions"]["ade-secret-deny"]
    assert profile["extends"] == ":workspace"
    roots = profile["filesystem"][":workspace_roots"]
    assert list(roots) == EXPECTED_CODEX_ROOTS
    assert all(v == "deny" for v in roots.values())
    exact = {k: v for k, v in profile["filesystem"].items() if k != ":workspace_roots"}
    assert all(v == "deny" for v in exact.values())
    assert any(k.endswith("/.aws/credentials") for k in exact)
    assert "22179" in text and "Do not claim #22179 landed" in text


def test_check_reports_codex_profile_drift(fx):
    render(fx)
    t = fx / "config.toml.tmpl"
    text = t.read_text().replace('"**/.env" = "deny"\n', "", 1)
    t.write_text(text)
    r = render(fx, "--check")
    assert r.returncode == 1
    assert "**/.env" in r.stdout
    assert t.read_text() == text


def test_bad_codex_static_is_refused_independently(fx):
    write_policy(fx, [".env", "~/.ssh/**"], ["*.pub"], [".env"], codex_static=["~/.ssh/**"])
    before = (fx / "config.toml.tmpl").read_text()
    r = render(fx)
    assert r.returncode == 2, r.stderr
    assert "codex.static" in r.stderr
    assert (fx / "config.toml.tmpl").read_text() == before


def test_missing_codex_static_section_is_refused(fx):
    (fx / "policy.toml").write_text('version = 1\ndeny = [".env"]\nallow = []\n[claude]\nstatic = [".env"]\n')
    assert render(fx).returncode == 2


def test_executable_with_env_shebang():
    assert RENDER.read_text().startswith("#!/usr/bin/env python3\n")
    assert RENDER.stat().st_mode & 0o100
