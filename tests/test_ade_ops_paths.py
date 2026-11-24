"""Unit tests for bin/ade_ops_paths.py (Queue #123 / tendcf #98 Stage 0 dual-read)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import ade_ops_paths as ops  # noqa: E402


# --- Slug grammar -------------------------------------------------------------------------

@pytest.mark.parametrize(
    "slug",
    [
        "a",
        "djbclark",
        "djbclark-lab",
        "org1-site2-prod3",
        "a" * 64,
        "wt",        # exact 'wt' does not end with '-wt'
        "my-wtx",
    ],
)
def test_valid_site_slugs(slug: str) -> None:
    assert ops.validate_site_slug(slug) == slug
    assert ops.is_valid_site_slug(slug) is True


@pytest.mark.parametrize(
    "slug",
    [
        "",
        "a" * 65,
        "foo-wt",
        "djbclark-lab-wt",
        "Djbclark",
        "DJBCLARK",
        "1site",
        "-foo",
        "foo-",
        "foo--bar",
        "foo_bar",
        "foo.bar",
        "foo/bar",
        "../foo",
        "..",
        "djbclark\n",
        "djbclark\r\n",
        "djbclark ",
        " djbclark",
        "djbclark\x00",
    ],
)
def test_invalid_site_slugs_rejected(slug: str) -> None:
    assert ops.is_valid_site_slug(slug) is False
    with pytest.raises(ops.OpsPathError):
        ops.validate_site_slug(slug)


# --- Ops root and XDG config precedence ---------------------------------------------------

def test_tendcf_ops_root_precedence_and_fail_closed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    base_env = {"HOME": str(home)}
    assert ops.tendcf_ops_root(base_env) == home / "tendcf-ops"

    env_override = {**base_env, "TENDCF_OPS_ROOT": str(tmp_path / "custom-ops")}
    assert ops.tendcf_ops_root(env_override) == tmp_path / "custom-ops"
    assert ops.tendcf_ops_root(env_override, ops_root=tmp_path / "arg-ops") == tmp_path / "arg-ops"
    assert ops.tendcf_ops_root({**base_env, "TENDCF_OPS_ROOT": "~/my-ops"}) == home / "my-ops"

    # Fail-closed on empty, relative, traversal, ~otheruser, ~//..., NUL.
    for bad in ("", "   ", "relative/ops", "~otheruser/ops", "~//ops", "/tmp/a/../b", "/tmp/a\x00b"):
        assert ops.tendcf_ops_root({**base_env, "TENDCF_OPS_ROOT": bad}) is None
        assert ops.tendcf_ops_root(base_env, ops_root=bad) is None


def test_xdg_active_site_config_path_ignores_relative_xdg(tmp_path: Path) -> None:
    home = tmp_path / "home"
    xdg = tmp_path / "xdg"
    assert ops.active_site_config_path({"HOME": str(home)}) == home / ".config/tendcf/active-site"
    assert ops.active_site_config_path({"HOME": str(home), "XDG_CONFIG_HOME": str(xdg)}) == xdg / "tendcf/active-site"
    # XDG spec: relative XDG_CONFIG_HOME must be ignored.
    assert ops.active_site_config_path({"HOME": str(home), "XDG_CONFIG_HOME": "relative/cfg"}) == home / ".config/tendcf/active-site"


def test_selector_precedence_and_fail_closed_no_fallthrough(tmp_path: Path) -> None:
    home = tmp_path / "home"
    xdg = tmp_path / "xdg"
    cfg_xdg = xdg / "tendcf" / "active-site"
    cfg_xdg.parent.mkdir(parents=True)
    cfg_xdg.write_text("# active site\nxdg-site\n", encoding="utf-8")

    cfg_home = home / ".config" / "tendcf" / "active-site"
    cfg_home.parent.mkdir(parents=True)
    cfg_home.write_text("home-site\n", encoding="utf-8")

    # Fallback to ~/.config/tendcf/active-site when XDG_CONFIG_HOME unset.
    assert ops.active_site_slug({"HOME": str(home)}) == "home-site"
    # XDG_CONFIG_HOME wins over ~/.config.
    assert ops.active_site_slug({"HOME": str(home), "XDG_CONFIG_HOME": str(xdg)}) == "xdg-site"
    # TENDCF_SITE wins over XDG active-site.
    env_both = {"HOME": str(home), "XDG_CONFIG_HOME": str(xdg), "TENDCF_SITE": "env-site"}
    assert ops.active_site_slug(env_both) == "env-site"
    # Explicit site_name wins over TENDCF_SITE and active-site.
    assert ops.active_site_slug(env_both, site_name="cli-site") == "cli-site"

    # Fail-closed: invalid higher-precedence selector NEVER falls through to lower-precedence ones.
    assert ops.active_site_slug(env_both, site_name="bad-wt") is None
    assert ops.active_site_slug({**env_both, "TENDCF_SITE": ""}) is None
    assert ops.active_site_slug({**env_both, "TENDCF_SITE": "UPPER"}) is None
    assert ops.active_site_slug({**env_both, "TENDCF_SITE": "foo-wt"}) is None


def test_read_active_site_file_edge_cases(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert ops.read_active_site_file(missing) is None

    ok = tmp_path / "ok"
    ok.write_text("# comment\n\n  djbclark-lab  \r\n# trailing\n", encoding="utf-8")
    assert ops.read_active_site_file(ok) == "djbclark-lab"

    # Symlink refused.
    link = tmp_path / "link"
    link.symlink_to(ok)
    with pytest.raises(ops.OpsPathError):
        ops.read_active_site_file(link)

    # Empty / comment-only refused.
    empty = tmp_path / "empty"
    empty.write_text("# only comments\n\n", encoding="utf-8")
    with pytest.raises(ops.OpsPathError):
        ops.read_active_site_file(empty)

    # Multi-line ambiguous refused.
    multi = tmp_path / "multi"
    multi.write_text("site-a\nsite-b\n", encoding="utf-8")
    with pytest.raises(ops.OpsPathError):
        ops.read_active_site_file(multi)

    # Bare CR refused.
    cr = tmp_path / "cr"
    cr.write_bytes(b"site-a\rsite-b")
    with pytest.raises(ops.OpsPathError):
        ops.read_active_site_file(cr)

    # NUL byte refused.
    nul = tmp_path / "nul"
    nul.write_bytes(b"site-a\x00")
    with pytest.raises(ops.OpsPathError):
        ops.read_active_site_file(nul)

    # Oversized (>4096 bytes) refused.
    big = tmp_path / "big"
    big.write_bytes(b"#" * 5000 + b"\nsite-a\n")
    with pytest.raises(ops.OpsPathError):
        ops.read_active_site_file(big)

    # Invalid slug inside file fails closed via active_site_slug -> None.
    home = tmp_path / "h"
    bad_cfg = home / ".config" / "tendcf" / "active-site"
    bad_cfg.parent.mkdir(parents=True)
    bad_cfg.write_text("bad-wt\n", encoding="utf-8")
    assert ops.active_site_slug({"HOME": str(home)}) is None


# --- Pair-bound resolution & NO sole-directory glob ---------------------------------------

def test_resolve_tendcf_site_pair_fail_closed_no_sole_dir_glob(tmp_path: Path) -> None:
    home = tmp_path / "home"
    troot = home / "tendcf-ops"
    priv = troot / "tendcf-private-djbclark"
    pub = troot / "tendcf-public-djbclark"
    priv.mkdir(parents=True)
    pub.mkdir(parents=True)

    env = {"HOME": str(home)}
    # NO selector set -> MUST return None even though only one site pair exists!
    assert ops.resolve_tendcf_site_pair(env) is None

    # With selector -> deterministic matched pair resolves.
    pair = ops.resolve_tendcf_site_pair({**env, "TENDCF_SITE": "djbclark"})
    assert pair is not None
    assert pair.slug == "djbclark"
    assert pair.private_dir == priv.resolve()
    assert pair.public_dir == pub.resolve()

    # Optional public_dir may be absent.
    pub.rmdir()
    pair_priv_only = ops.resolve_tendcf_site_pair({**env, "TENDCF_SITE": "djbclark"})
    assert pair_priv_only is not None
    assert pair_priv_only.private_dir == priv.resolve()
    assert pair_priv_only.public_dir is None

    # Missing private_dir fails closed even if public_dir exists.
    pub.mkdir()
    priv.rmdir()
    assert ops.resolve_tendcf_site_pair({**env, "TENDCF_SITE": "djbclark"}) is None

    # Symlinked private or public site repo fails closed.
    real_priv = tmp_path / "real-priv"
    real_priv.mkdir()
    priv.symlink_to(real_priv)
    assert ops.resolve_tendcf_site_pair({**env, "TENDCF_SITE": "djbclark"}) is None

    priv.unlink()
    priv.mkdir()
    pub.rmdir()
    real_pub = tmp_path / "real-pub"
    real_pub.mkdir()
    pub.symlink_to(real_pub)
    assert ops.resolve_tendcf_site_pair({**env, "TENDCF_SITE": "djbclark"}) is None


def test_check_site_repo_dir_rejects_sibling_symlink_and_mid_lookup_swap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Finding 4: sibling symlink under same ops_root and mid-lookup identity swap must fail closed."""
    ops_root = (tmp_path / "tendcf-ops").resolve()
    site_a = ops_root / "tendcf-private-alpha"
    site_b = ops_root / "tendcf-private-beta"
    site_b.mkdir(parents=True)

    # Direct sibling symlink under the same parent is refused.
    site_a.symlink_to(site_b)
    with pytest.raises(ops.OpsPathError):
        ops._check_site_repo_dir(ops_root, "tendcf-private-alpha", required=True)
    site_a.unlink()

    # Simulated race: real dir at scandir/open time, but Path.resolve returns sibling dir under same ops_root.
    site_a.mkdir()
    orig_resolve = Path.resolve

    def swapped_resolve(self: Path, strict: bool = False) -> Path:
        if self == site_a:
            return site_b
        return orig_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", swapped_resolve)
    with pytest.raises(ops.OpsPathError, match="unexpected target"):
        ops._check_site_repo_dir(ops_root, "tendcf-private-alpha", required=True)


def test_find_trusted_bgrun_ignores_caller_env_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Finding 1: Touch ID ticket authority ignores TENDCF_OPS_ROOT, TENDCF_SITE, OPS_ROOT, XDG_CONFIG_HOME."""
    home = tmp_path / "home"
    evil_ops = tmp_path / "evil-ops"
    (evil_ops / "tendcf-private-evil").mkdir(parents=True)
    _mk_exec(evil_ops / "tendcf-public-evil" / "bin" / "bgrun")
    _mk_exec(tmp_path / "evil-legacy" / "site-private-djbclark" / "bin" / "bgrun")
    evil_xdg = tmp_path / "evil-xdg" / "tendcf" / "active-site"
    evil_xdg.parent.mkdir(parents=True)
    evil_xdg.write_text("evil\n", encoding="utf-8")

    # Even with all caller env vars poisoned, trusted lookup finds nothing when home has no install.
    monkeypatch.setenv("TENDCF_OPS_ROOT", str(evil_ops))
    monkeypatch.setenv("TENDCF_SITE", "evil")
    monkeypatch.setenv("OPS_ROOT", str(tmp_path / "evil-legacy"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "evil-xdg"))
    assert ops.find_trusted_bgrun(home=home) is None

    # Adding a real installation under home/tendcf-ops STILL does not match until home/.config/tendcf/active-site names it.
    (home / "tendcf-ops" / "tendcf-private-acme").mkdir(parents=True)
    trusted_pub = _mk_exec(home / "tendcf-ops" / "tendcf-public-acme" / "bin" / "bgrun")
    assert ops.find_trusted_bgrun(home=home) is None

    trusted_cfg = home / ".config" / "tendcf" / "active-site"
    trusted_cfg.parent.mkdir(parents=True)
    trusted_cfg.write_text("acme\n", encoding="utf-8")
    assert ops.find_trusted_bgrun(home=home) == trusted_pub.resolve()

    # ~/.local/bin/bgrun under home takes top precedence.
    local_bin = _mk_exec(home / ".local" / "bin" / "bgrun")
    assert ops.find_trusted_bgrun(home=home) == local_bin


def test_real_account_home_and_trusted_bgrun_immune_to_spoofed_home_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Round 3 HIGH #1: spoofing $HOME cannot redirect real_account_home() or find_trusted_bgrun()."""
    import pwd

    expected_pw_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    evil_home = tmp_path / "evil-home"
    _mk_exec(evil_home / ".local" / "bin" / "bgrun")
    _mk_exec(evil_home / "ops" / "site-private-djbclark" / "bin" / "bgrun")
    (evil_home / "tendcf-ops" / "tendcf-private-evil").mkdir(parents=True)
    _mk_exec(evil_home / "tendcf-ops" / "tendcf-public-evil" / "bin" / "bgrun")
    evil_cfg = evil_home / ".config" / "tendcf" / "active-site"
    evil_cfg.parent.mkdir(parents=True)
    evil_cfg.write_text("evil\n", encoding="utf-8")

    monkeypatch.setenv("HOME", str(evil_home))
    assert ops.real_account_home() == expected_pw_home
    trusted_paths = ops.trusted_bgrun_paths()
    assert all(not str(p).startswith(str(evil_home)) for p in trusted_paths)
    found = ops.find_trusted_bgrun()
    assert found is None or not str(found).startswith(str(evil_home))


# --- bgrun dual-read discovery & path validation ------------------------------------------

def _mk_exec(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_find_bgrun_precedence_and_legacy_fallback(tmp_path: Path) -> None:
    home = tmp_path / "home"
    troot = home / "tendcf-ops"
    (troot / "tendcf-private-acme").mkdir(parents=True)
    (troot / "tendcf-public-acme").mkdir(parents=True)
    legacy = _mk_exec(home / "ops" / "site-private-djbclark" / "bin" / "bgrun")
    tendcf_priv = _mk_exec(troot / "tendcf-private-acme" / "bin" / "bgrun")
    tendcf_pub = _mk_exec(troot / "tendcf-public-acme" / "bin" / "bgrun")

    # Without a selector, tendcf-ops is NOT globbed -> falls back to legacy ~/ops.
    assert ops.find_bgrun({"HOME": str(home)}) == legacy

    # With TENDCF_SITE=acme, tendcf-public-<slug>/bin/bgrun wins over private and legacy.
    env_acme = {"HOME": str(home), "TENDCF_SITE": "acme"}
    assert ops.find_bgrun(env_acme) == tendcf_pub.resolve()

    # Without public bgrun, tendcf-private-<slug>/bin/bgrun wins over legacy.
    tendcf_pub.unlink()
    assert ops.find_bgrun(env_acme) == tendcf_priv.resolve()

    # ~/.local/bin/bgrun symlink wins over all site-local paths.
    local_bin = home / ".local" / "bin" / "bgrun"
    local_bin.parent.mkdir(parents=True, exist_ok=True)
    local_bin.symlink_to(tendcf_priv)
    assert ops.find_bgrun(env_acme) == local_bin


@pytest.mark.parametrize(
    "token",
    [
        "~/.local/bin/bgrun",
        "~/.local/bin/bg",
        "$HOME/.local/bin/bgrun",
        "${HOME}/.local/bin/bgrun",
        "/Users/djbclark/.local/bin/bgrun",
        "~/tendcf-ops/tendcf-public-djbclark/bin/bgrun",
        "~/tendcf-ops/tendcf-private-djbclark/bin/bgrun",
        "~/tendcf-ops/tendcf-public-djbclark-lab/bin/bg",
        "$HOME/tendcf-ops/tendcf-public-djbclark/bin/bgrun",
        "${HOME}/tendcf-ops/tendcf-private-djbclark/bin/bgrun",
        "/Users/djbclark/tendcf-ops/tendcf-public-djbclark/bin/bgrun",
        "/Users/djbclark/tendcf-ops/tendcf-private-djbclark/bin/bg",
        "~/ops/site-private/bin/bgrun",
        "~/ops/site-private/bin/bg",
        "~/ops/site-private-djbclark/bin/bgrun",
        "~/ops/site-public-djbclark/bin/bgrun",
        "~/ops/site-djbclark/bin/bgrun",
        "/Users/djbclark/ops/site-private-djbclark/bin/bgrun",
    ],
)
def test_is_bgrun_path_accepts_stage0_locations(token: str) -> None:
    assert ops.is_bgrun_path(token, env={"HOME": "/Users/djbclark"}, allow_bg=True) is True


@pytest.mark.parametrize(
    "token",
    [
        "",
        "bgrun",
        "bg",
        "/tmp/bgrun",
        "other/bin/bgrun",
        "~/.local/bin/bgrunner",
        "~/ops/site-private/bin/bgrunner",
        "~/tendcf-ops/tendcf-public-djbclark/bin/bgrunner",
        "~/tendcf-ops/tendcf-public-foo-wt/bin/bgrun",
        "~/tendcf-ops/tendcf-private-foo-wt/bin/bgrun",
        "/Users/djbclark/tendcf-ops/tendcf-public-foo-wt/bin/bgrun",
        "~/tendcf-ops/tendcf-private/bin/bgrun",
        "~/tendcf-ops/tendcf-public/bin/bgrun",
        "~/tendcf-ops/tendcf-public-Foo/bin/bgrun",
        "~/tendcf-ops/tendcf-public-" + ("a" * 65) + "/bin/bgrun",
        "~/tendcf-ops/site-private/bin/bgrun",
        "~/tendcf-ops/tendcf-public-a/../tendcf-public-b/bin/bgrun",
        "~/ops/site-private-wt/bin/bgrun",
        "~/ops/site-private/../other/bin/bgrun",
        "~otheruser/.local/bin/bgrun",
        "~//.local/bin/bgrun",
        "/Users/djbclark//tendcf-ops/tendcf-public-djbclark/bin/bgrun",
        "/tmp/evil/.local/bin/bgrun",
        "/tmp/evil/ops/site-private/bin/bgrun",
        "/tmp/evil/tendcf-ops/tendcf-public-djbclark/bin/bgrun",
        "/Users/someone-else/.local/bin/bgrun",
        "/Users/someone-else/ops/site-private/bin/bgrun",
        "/Users/someone-else/tendcf-ops/tendcf-public-djbclark/bin/bgrun",
        "/home/box/.local/bin/bg",
    ],
)
def test_is_bgrun_path_rejects_lookalikes_and_invalid_paths(token: str) -> None:
    assert ops.is_bgrun_path(token, env={"HOME": "/Users/djbclark"}, allow_bg=True) is False


def test_is_bgrun_path_accepts_linux_home_when_anchored() -> None:
    assert ops.is_bgrun_path("/home/box/.local/bin/bg", env={"HOME": "/home/box"}, allow_bg=True) is True
    assert ops.is_bgrun_path("/home/box/tendcf-ops/tendcf-public-box/bin/bgrun", env={"HOME": "/home/box"}) is True


def test_is_bgrun_path_honors_custom_tendcf_ops_root_and_allow_bg_flag(tmp_path: Path) -> None:
    custom = tmp_path / "my-tendcf-workspace"
    env = {"HOME": str(tmp_path / "home"), "TENDCF_OPS_ROOT": str(custom)}
    assert ops.is_bgrun_path(f"{custom}/tendcf-public-acme/bin/bgrun", env=env) is True
    assert ops.is_bgrun_path(f"{custom}/tendcf-public-acme-wt/bin/bgrun", env=env) is False
    assert ops.is_bgrun_path("~/.local/bin/bg", env=env, allow_bg=False) is False
    assert ops.is_bgrun_path("~/.local/bin/bgrun", env=env, allow_bg=False) is True


def test_resolve_default_bm_store_and_skill_roots_and_checkout_names(tmp_path: Path) -> None:
    home = tmp_path / "home"
    troot = home / "tendcf-ops"
    priv = troot / "tendcf-private-acme"
    pub = troot / "tendcf-public-acme"
    (priv / "memory").mkdir(parents=True)
    (priv / "skills").mkdir(parents=True)
    (pub / "skills").mkdir(parents=True)
    (troot / ".worktrees" / "wt1").mkdir(parents=True)
    (troot / "tendcf-private-acme-wt").mkdir(parents=True)
    (home / "ops" / "site-private" / "memory").mkdir(parents=True)

    env_none = {"HOME": str(home)}
    # Fail-closed without selector -> legacy paths.
    assert ops.resolve_default_bm_store(env_none) == home / "ops" / "site-private" / "memory"
    assert ops.resolve_skill_roots(env_none) == (
        home / "ops" / "site-private" / "skills",
        home / "ops" / "site-public-djbclark" / "skills",
    )

    # Active selector -> tendcf site pair.
    env_acme = {"HOME": str(home), "TENDCF_SITE": "acme"}
    assert ops.resolve_default_bm_store(env_acme) == (priv / "memory").resolve()
    assert ops.resolve_skill_roots(env_acme) == ((priv / "skills").resolve(), (pub / "skills").resolve())

    # Checkout recognition skips .worktrees and *-wt.
    assert ops.resolve_ops_checkout_name(priv, env_none) == "tendcf-private-acme"
    assert ops.resolve_ops_checkout_name(pub / "skills", env_none) == "tendcf-public-acme"
    assert ops.resolve_ops_checkout_name(troot / ".worktrees" / "wt1", env_none) is None
    assert ops.resolve_ops_checkout_name(troot / "tendcf-private-acme-wt", env_none) is None
    assert ops.resolve_ops_checkout_name(home / "ops" / "site-private", env_none) == "site-private"
