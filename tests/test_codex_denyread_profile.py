#!/usr/bin/env python3
"""Pin the Codex ade-secret-deny filesystem deny-read profile in agents/codex/config.toml.tmpl (2026-11-09).

Carried #1 residual beyond hooks (#390) and Claude denyRead (#405): in-repo template only. Live ~/.codex is
not written (order 11). openai/codex#22179 tracked early deny-glob docs that did not enforce — do not claim it landed.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "agents" / "codex" / "config.toml.tmpl"
POLICY = REPO / "config" / "secret-deny.toml"
BEGIN = "# BEGIN ade-secret-deny (managed by bin/render-secret-deny; do not edit by hand)"
END = "# END ade-secret-deny"
PROFILE = "ade-secret-deny"

EXPECTED_WORKSPACE = {
    "**/.env", "**/*.key", "**/*.p12", "**/*.pfx", "**/*-key.pem", "**/*.key.pem", "**/privkey*.pem",
    "**/id_rsa", "**/id_ecdsa", "**/id_ed25519",
}
EXPECTED_HOME_SUFFIXES = {
    "/.ssh/id_rsa", "/.ssh/id_ecdsa", "/.ssh/id_ed25519",
    "/.aws/credentials", "/.netrc", "/.config/gh/hosts.yml", "/.docker/config.json", "/.kube/config",
}


def _rendered() -> dict:
    text = TEMPLATE.read_text()
    text = re.sub(r"\{\{\s*\.home\s*\}\}", "/home/x", text)
    text = re.sub(r"\{\{\s*secret\s+\"[A-Za-z0-9_]+\"\s*\}\}", "SECRET", text)
    text = re.sub(r"\{\{\s*\.[A-Za-z_][A-Za-z0-9_]*\s*\}\}", "x", text)
    return tomllib.loads(text)


def test_markers_present_and_managed():
    text = TEMPLATE.read_text()
    assert BEGIN in text and END in text
    assert text.index(BEGIN) < text.index(END)
    assert "bin/render-secret-deny" in text[text.index(BEGIN):text.index(END)]
    assert "22179" in text[text.index(BEGIN):text.index(END)]
    assert "Do not claim #22179 landed" in text[text.index(BEGIN):text.index(END)]


def test_profile_inactive_and_extends_workspace():
    data = _rendered()
    assert data.get("default_permissions") != PROFILE
    assert "default_permissions" not in data or data["default_permissions"] != PROFILE
    assert data["sandbox_mode"] == "danger-full-access"
    profile = data["permissions"][PROFILE]
    assert profile["extends"] == ":workspace"


def test_deny_maps_match_codex_static_exception_free_paths():
    data = _rendered()
    fs = data["permissions"][PROFILE]["filesystem"]
    roots = fs[":workspace_roots"]
    assert set(roots) == EXPECTED_WORKSPACE
    assert all(v == "deny" for v in roots.values())
    exact = {k: v for k, v in fs.items() if k != ":workspace_roots"}
    assert all(v == "deny" for v in exact.values())
    suffixes = {k[len("/home/x"):] if k.startswith("/home/x") else k for k in exact}
    assert suffixes == EXPECTED_HOME_SUFFIXES
    # hook-only patterns with allow exceptions stay out of the profile
    joined = " ".join(roots) + " " + " ".join(exact)
    assert ".env.*" not in joined
    assert "/.ssh/**" not in joined and "~/.ssh/**" not in joined
    assert "*.pem" not in joined or "*-key.pem" in joined  # only named private-key forms


def test_policy_toml_lists_codex_static():
    pol = tomllib.loads(POLICY.read_text())
    assert "codex" in pol and isinstance(pol["codex"]["static"], list)
    assert ".env" in pol["codex"]["static"]
    assert ".env.*" not in pol["codex"]["static"]
    assert "~/.ssh/**" not in pol["codex"]["static"]


def test_template_still_parses_for_ade_template_check_shape():
    # smoke: every {{ }} sits in a quoted scalar (basic check used by other Codex tests)
    text = TEMPLATE.read_text()
    for m in re.finditer(r"\{\{.*?\}\}", text):
        # find the opening quote before the tag on the same line
        line_start = text.rfind("\n", 0, m.start()) + 1
        prefix = text[line_start:m.start()]
        assert '"' in prefix or "'" in prefix, f"unquoted placeholder near {text[m.start():m.end()]!r}"
