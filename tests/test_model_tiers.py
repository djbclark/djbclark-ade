"""config/model-tiers.toml + bin/model_tiers.py + bin/ade-model-tiers (2026-11-09).

S2 loader + promote core from docs/history/model-tiers-design.md. No network, no secrets.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
sys.path.insert(0, str(BIN))
import model_tiers as mt  # noqa: E402

CLI = BIN / "ade-model-tiers"


@pytest.fixture(autouse=True)
def _clear_tiers_cache():
    # Promotion tests reload the router. Its runtime tier snapshot now stays
    # fixed until an explicit reload, so restore it as well as the file cache.
    router = sys.modules.get("route_agent")
    previous = None
    if router is not None:
        previous = (router.POLICY, router.POLICY_PATH, router.POLICY_PROVENANCE,
                    router.MODEL_TIERS, router.SUBLIMIT_FAMILIES)
    mt.clear_cache()
    yield
    mt.clear_cache()
    if previous is not None:
        policy, path, provenance, tiers, families = previous
        router.POLICY_PATH = path
        router.apply_policy(policy)
        router.POLICY_PROVENANCE = provenance
        router.MODEL_TIERS, router.SUBLIMIT_FAMILIES = tiers, families


def test_shipped_file_matches_defaults():
    drift = mt.defaults_match_file(REPO / "config" / "model-tiers.toml")
    assert drift == [], drift


def test_load_shipped_file_is_source_file():
    tiers = mt.load(REPO / "config" / "model-tiers.toml", use_cache=False)
    assert tiers.source == "file" and tiers.error is None
    assert tiers.role_id("claude", "frontier") == "claude-fable-5-1"
    assert tiers.role_id("codex", "frontier") == "gpt-6-astra"


def test_missing_file_falls_back_to_defaults(tmp_path, monkeypatch):
    missing = tmp_path / "nope.toml"
    monkeypatch.setenv("MODEL_TIERS_TOML", str(missing))
    mt.clear_cache()
    tiers = mt.load(missing, use_cache=False)
    assert tiers.source == "code" and tiers.error
    assert tiers.role_id("claude", "judgment") == "claude-opus-5-5"


def test_classify_aliases_prefixes_and_former():
    tiers = mt.load(REPO / "config" / "model-tiers.toml", use_cache=False)
    assert mt.classify("fable", tiers) == ("claude", "frontier", "current")
    assert mt.classify("opus --effort high", tiers) == ("claude", "judgment", "current")
    assert mt.classify("anthropic/claude-opus-5-5", tiers) == ("claude", "judgment", "current")
    assert mt.classify("claude-fable-5-1[1m]", tiers) == ("claude", "frontier", "current")
    assert mt.classify("gpt-6-astra", tiers) == ("codex", "frontier", "current")
    assert mt.classify("minimax-m3", tiers) == (None, None, "untiered")
    # Unknown in-family → frontier (fail closed / strictest).
    assert mt.classify("claude-fable-9-9", tiers) == ("claude", "frontier", "unknown")


def test_resolve_spellings():
    tiers = mt.load(REPO / "config" / "model-tiers.toml", use_cache=False)
    assert mt.resolve("claude", "judgment", "claude", tiers) == "opus"
    assert mt.resolve("claude", "judgment", "omp", tiers) == "anthropic/claude-opus-5-5"
    assert mt.resolve("claude", "everyday", "copilot", tiers) == "claude-sonnet-5.5"
    assert mt.resolve("codex", "frontier", "codex", tiers) == "gpt-6-astra"


def test_id_dotted_preserves_name_prefix():
    """Copilot {id_dotted}: only the numeric version suffix becomes dotted."""
    assert mt._id_dotted("claude-opus-5-5") == "claude-opus-5.5"
    assert mt._id_dotted("claude-fable-5-1") == "claude-fable-5.1"
    assert mt._id_dotted("claude-haiku-5-5") == "claude-haiku-5.5"
    assert mt._id_dotted("claude-fable-6") == "claude-fable-6"
    assert mt._id_dotted("gpt-6-astra") == "gpt-6-astra"
    tiers = mt.load(REPO / "config" / "model-tiers.toml", use_cache=False)
    # No per-model override → generated spelling, not claude.opus.5-5.
    assert mt.resolve("claude", "judgment", "copilot", tiers) == "claude-opus-5.5"
    assert mt.resolve("claude", "frontier", "copilot", tiers) == "claude-fable-5.1"
    assert mt.resolve("claude", "bulk", "copilot", tiers) == "claude-haiku-5.5"


def test_frontier_tokens_and_sublimit_families():
    tiers = mt.load(REPO / "config" / "model-tiers.toml", use_cache=False)
    toks = {t.lower() for t in mt.frontier_tokens(tiers)}
    assert "fable" in toks and "claude-fable-5-1" in toks and "gpt-6-astra" in toks
    assert mt.sublimit_families(tiers) == ("fable",)


def test_promote_cascade_2_claude(tmp_path):
    src = (REPO / "config" / "model-tiers.toml").read_text()
    path = tmp_path / "model-tiers.toml"
    path.write_text(src)
    result = mt.promote(
        vendor="claude",
        new_id="claude-fable-6",
        reason="test promote",
        alias="fable",
        display_name="Fable 6",
        path=path,
        dry_run=False,
        today="2026-11-09",
    )
    assert result.changed and not result.dry_run
    after = result.after["vendor"]["claude"]["roles"]
    assert after["frontier"] == "claude-fable-6"
    assert after["judgment"] == "claude-fable-5-1"
    assert after["everyday"] == "claude-sonnet-5-5"
    assert after["bulk"] == "claude-haiku-5-5"
    assert result.after["former"]["claude-opus-5-5"]["last_role"] == "judgment"
    # Reloaded file matches.
    reloaded = mt.load(path, use_cache=False)
    assert reloaded.source == "file"
    assert reloaded.role_id("claude", "frontier") == "claude-fable-6"
    assert mt.classify("claude-opus-5-5", reloaded)[2] == "former"
    # Shared alias "fable": frontier keeps it; displaced judgment uses canonical id
    # so suggest_model judgment fallback does not re-select the new frontier.
    assert mt.resolve("claude", "frontier", "claude", reloaded) == "fable"
    assert mt.resolve("claude", "judgment", "claude", reloaded) == "claude-fable-5-1"
    assert mt.resolve("claude", "judgment", "claude-code", reloaded) == "claude-fable-5-1"
    assert mt.resolve("claude", "judgment", "omp", reloaded) == "anthropic/claude-fable-5-1"


def test_promote_dry_run_does_not_write(tmp_path):
    src = (REPO / "config" / "model-tiers.toml").read_text()
    path = tmp_path / "model-tiers.toml"
    path.write_text(src)
    before = path.read_text()
    result = mt.promote(
        vendor="codex",
        new_id="gpt-7-nova",
        reason="dry",
        path=path,
        dry_run=True,
        today="2026-11-09",
    )
    assert result.changed and result.dry_run
    assert path.read_text() == before
    assert result.after["vendor"]["codex"]["roles"]["frontier"] == "gpt-7-nova"
    assert result.after["vendor"]["codex"]["roles"]["judgment"] == "gpt-6-astra"


def test_promote_rejects_family_mismatch(tmp_path):
    path = tmp_path / "model-tiers.toml"
    path.write_text((REPO / "config" / "model-tiers.toml").read_text())
    with pytest.raises(mt.TiersError, match="family"):
        mt.promote(
            vendor="claude",
            new_id="gpt-7-nova",
            reason="bad",
            path=path,
            dry_run=True,
        )


def test_cli_show_validate_promote_dry_run(tmp_path):
    path = tmp_path / "model-tiers.toml"
    path.write_text((REPO / "config" / "model-tiers.toml").read_text())
    env = {**os.environ, "MODEL_TIERS_TOML": str(path)}

    r = subprocess.run(
        [sys.executable, "-I", str(CLI), "--root", str(tmp_path), "validate"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr

    r = subprocess.run(
        [sys.executable, "-I", str(CLI), "--root", str(tmp_path), "show", "--json"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["vendor"]["claude"]["roles"]["frontier"] == "claude-fable-5-1"

    r = subprocess.run(
        [
            sys.executable, "-I", str(CLI), "--root", str(tmp_path),
            "promote", "--vendor", "claude", "--new", "claude-fable-6",
            "--reason", "cli dry", "--dry-run", "--json",
        ],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["dry_run"] is True and out["changed"] is True
    assert out["after_roles"]["frontier"] == "claude-fable-6"
    assert path.read_text().startswith("# Model tiers")


def test_route_agent_reads_tiers():
    sys.path.insert(0, str(BIN))
    import route_agent as ra  # noqa: E402
    assert "fable" in {t.lower() for t in ra.frontier_model_tokens()}
    assert ra.is_frontier_model("claude-fable-5-1 --effort high")
    assert ra.SUBLIMIT_FAMILIES == ("fable",)
    pub = ra.policy_public()
    assert pub["model_tiers"]["vendor"]["claude"]["roles"]["frontier"] == "claude-fable-5-1"
    # Judgment fallback when the frontier pool is short.
    svc = next(s for s in ra.SERVICES if s.name == "claude")
    out = ra.suggest_model(svc, "frontier", {"sublimits": {"fable": 0.0}})
    assert out.startswith("opus")


def test_suggest_model_after_promote_shared_alias(tmp_path, monkeypatch):
    """Judgment fallback must not return the new frontier alias after promote."""
    path = tmp_path / "model-tiers.toml"
    path.write_text((REPO / "config" / "model-tiers.toml").read_text())
    mt.promote(
        vendor="claude",
        new_id="claude-fable-6",
        reason="shared alias fallback",
        alias="fable",
        path=path,
        today="2026-11-09",
    )
    monkeypatch.setenv("MODEL_TIERS_TOML", str(path))
    mt.clear_cache()
    sys.path.insert(0, str(BIN))
    import importlib
    import route_agent as ra  # noqa: E402
    importlib.reload(ra)
    svc = next(s for s in ra.SERVICES if s.name == "claude")
    out = ra.suggest_model(svc, "frontier", {"sublimits": {"fable": 0.0}})
    assert out.startswith("claude-fable-5-1"), out
    assert not out.startswith("fable"), out


def test_load_effective_projects_model_tiers(tmp_path, monkeypatch):
    import ade_config as ac  # noqa: E402
    # Point at this checkout's config via --root semantics.
    effective = ac.load_effective(root=REPO, home=tmp_path, include_local=False)
    mt_pub = effective.data.get("model_tiers") or {}
    assert mt_pub.get("vendor", {}).get("claude", {}).get("roles", {}).get("frontier") == "claude-fable-5-1"
    assert effective.provenance.get("model_tiers_source")
    assert any(
        m["legacy_file"] == "config/model-tiers.toml"
        for m in effective.provenance.get("mapping") or []
    )


# --- W16 (2026-11-12): pathless readers accept config/ade.toml before any writer does ---------


def _unified_root(tmp_path, monkeypatch):
    import re
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    text = (REPO / "config/model-tiers.toml").read_text()
    text = re.sub(r"^\[(meta|rank|vendor|model|former)", r"[model_tiers.\1", text, flags=re.M)
    (root / "config/ade.toml").write_text("schema_version = 1\n" + text)
    monkeypatch.delenv("MODEL_TIERS_TOML", raising=False)
    monkeypatch.setattr(mt, "repo_root_from_here", lambda: root)
    mt.clear_cache()
    return root


def test_pathless_load_reads_unified_tiers(tmp_path, monkeypatch):
    root = _unified_root(tmp_path, monkeypatch)
    tiers = mt.load(use_cache=False)
    assert tiers.source == "file" and tiers.path == root / "config/ade.toml"
    assert mt.public_dict(tiers)["rank"] == mt.public_dict(mt.load(REPO / "config/model-tiers.toml", use_cache=False))["rank"]


def test_legacy_writers_refuse_when_unified_carries_tiers(tmp_path, monkeypatch):
    root = _unified_root(tmp_path, monkeypatch)
    before = (root / "config/ade.toml").read_bytes()
    with pytest.raises(mt.TiersError, match="legacy tier writer"):
        mt.set_role(vendor="claude", role="everyday", new_id="claude-sonnet-5-5", reason="test")
    with pytest.raises(mt.TiersError, match="legacy tier writer"):
        mt.promote(vendor="claude", new_id="claude-opus-5-5", reason="test")
    assert (root / "config/ade.toml").read_bytes() == before


def test_env_override_and_explicit_path_ignore_unified(tmp_path, monkeypatch):
    root = _unified_root(tmp_path, monkeypatch)
    monkeypatch.setenv("MODEL_TIERS_TOML", str(tmp_path / "missing.toml"))
    assert mt.unified_source() is None
    assert mt.load(tmp_path / "missing.toml", use_cache=False).source == "code"
