"""bin/ade-theme: every theme names every role; NO_COLOR wins; a pipe gets no escapes unless asked."""

import json
import os
import subprocess
import sys
from pathlib import Path

THEME = Path(__file__).resolve().parents[1] / "bin" / "ade-theme"
ROLES = ("ok", "warn", "error", "info", "accent", "dim")


def run(*args, env=None):
    e = {k: v for k, v in os.environ.items() if k != "NO_COLOR"}
    e.pop("ADE_THEME", None)
    e.update(env or {})
    return subprocess.run([sys.executable, str(THEME), *args], capture_output=True, text=True, env=e)


def test_every_theme_covers_every_role():
    out = run("export", "touhou", "--format", "json").stdout
    doc = json.loads(out)
    assert doc["theme"] == "touhou"
    assert set(doc["roles"]) == set(ROLES)
    for name in ("default", "gruvbox", "solarized-dark", "mono", "touhou"):
        roles = json.loads(run("export", name, "--format", "json").stdout)["roles"]
        assert set(roles) == set(ROLES), f"{name} is missing a role"


def test_touhou_has_its_own_palette():
    doc = json.loads(run("export", "touhou", "--format", "json").stdout)["roles"]
    assert doc["error"] == 196 and doc["info"] == 51 and doc["ok"] == 71 and doc["warn"] == 220
    default = json.loads(run("export", "default", "--format", "json").stdout)["roles"]
    assert doc != default


def test_show_paints_with_the_theme_palette():
    out = run("show", "touhou", "--color").stdout
    assert "\033[38;5;196m" in out and "Reimu" in out


def test_a_pipe_gets_no_escapes_unless_it_asks():
    assert "\033[" not in run("show", "touhou").stdout
    assert "\033[" in run("show", "touhou", "--color").stdout


def test_unknown_subcommand_is_status_3():
    r = run("frob")
    assert r.returncode == 3 and "unknown subcommand" in r.stderr


def test_no_color_flag_strips_escapes():
    out = run("show", "touhou", "--color", "--no-color").stdout
    assert "\033[" not in out
    assert "[error] error" in out


def test_no_color_environment_variable_wins():
    out = run("show", "touhou", "--color", env={"NO_COLOR": "1"}).stdout
    assert "\033[" not in out


def test_mono_never_emits_escapes():
    out = run("show", "mono").stdout
    assert "\033[" not in out


def test_unknown_theme_is_usage():
    r = run("show", "gensokyo-undefined")
    assert r.returncode == 2 and "unknown theme" in r.stderr and "touhou" in r.stderr


def test_shell_export_names_every_role():
    out = run("export", "gruvbox", "--format", "sh").stdout
    for role in ROLES:
        assert f"ADE_COLOR_{role.upper()}=" in out


def test_list_names_every_theme():
    out = run("list").stdout
    for name in ("default", "gruvbox", "solarized-dark", "mono", "touhou"):
        assert name in out
