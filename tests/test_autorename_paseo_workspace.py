"""autorename: Paseo workspace slugs (djbclark, 2026-10-23: lower case, hyphens, whole words, `-pw` suffix), which the
tab shortener still uses to recognise a workspace named from the same title; autorename never renames a workspace
(djbclark, 2026-10-30)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

SKILL = Path(__file__).resolve().parent.parent / "skills/autorename"


def load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, SKILL / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ar = load("autorename")


def test_workspace_name_is_lower_hyphen_pw() -> None:
    assert ar.paseo_workspace_name("Paseo skill sync overwrite fix") == "paseo-skill-sync-overwrite-fix-pw"


def test_dates_and_versions_are_dropped_and_words_stay_whole() -> None:
    name = ar.paseo_workspace_name("ClaudeHelm night run 2026-10-09 + Collie 1.18.1 and many more extra words here")
    assert name.endswith("-pw") and name == name.lower() and " " not in name
    assert "2026" not in name and "1.18" not in name
    assert len(name) <= ar.PASEO_WORKSPACE_SLUG_MAX + len("-pw")
    assert all(w.isalnum() for w in name[: -len("-pw")].split("-"))


def test_empty_title_still_gets_a_valid_name() -> None:
    assert ar.paseo_workspace_name("2026-10-23") == "session-pw"


def test_herdr_tab_label_keeps_t_suffix_and_24_char_cap() -> None:
    hp = load("herdr_place")
    import sys
    sys.path.insert(0, str(SKILL))
    try:
        assert hp.slug_from_title("ClaudeHelm night run 2026-10-09 + Collie 1.18.1") == "claudehelm-night-run-t"
    finally:
        sys.path.remove(str(SKILL))


def test_workspace_id_comes_from_the_agent_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rec = tmp_path / "agents" / "Users-x-src-y"
    rec.mkdir(parents=True)
    (rec / "abc.json").write_text(json.dumps({"workspaceId": "wks_1"}))
    monkeypatch.setenv("PASEO_HOME", str(tmp_path))
    assert ar.paseo_workspace_id("abc") == "wks_1"
    assert ar.paseo_workspace_id("missing") is None


def fake_cli(tmp_path: Path, current: str) -> tuple[Path, Path]:
    log = tmp_path / "calls.log"
    cli = tmp_path / "paseo"
    cli.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> {log}\n'
        'if [ "$1 $2" = "workspace ls" ]; then\n'
        f"  echo '[{{\"workspaceId\": \"wks_1\", \"name\": \"{current}\"}}]'\n"
        "fi\n")
    cli.chmod(0o755)
    return cli, log


@pytest.mark.parametrize("auto", [False, True])
def test_set_name_names_the_tab_and_never_touches_the_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                auto: bool) -> None:
    # djbclark, 2026-10-30: /autorename renames only the agent's own tab; the -pw workspace rename is gone.
    rec = tmp_path / "agents" / "Users-x-src-y"
    rec.mkdir(parents=True)
    (rec / "abc.json").write_text(json.dumps({"workspaceId": "wks_1"}))
    cli, log = fake_cli(tmp_path, "tmp-p")
    monkeypatch.setenv("PASEO_HOME", str(tmp_path))
    monkeypatch.setenv("PASEO_AGENT_ID", "abc")
    monkeypatch.setenv("PASEO_CLI", str(cli))
    out = ar.paseo_set_name("Paseo skill sync overwrite fix", auto=auto)
    calls = log.read_text().splitlines()
    assert "agent update abc --name paseo-skill-pt --json" in calls
    assert not [c for c in calls if c.startswith("workspace ")]
    assert "workspace" not in out
