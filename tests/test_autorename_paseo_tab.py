"""autorename: Paseo tab names (design-tabs 2.2/2.3/3, 2026-10-24): `-pt`, at most 17 characters, deterministic;
`--auto` keeps an agent name that already follows the convention."""

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

# design-tabs-report.md 2.3, rows 1-16: (title, context words dropped, tab name)
TABLE = [
    ("Load watcher", [], "loadwatch-pt"),
    ("Adversary round 3 on PR 31", [], "adv-r3-pr31-pt"),
    ("PR 27 autopilot loop", [], "pr27-autopilot-pt"),
    ("djbclark-ade rework lead", [], "ade-rwk-lead-pt"),
    ("Phase0 queue scan", [], "p0-queue-scan-pt"),
    ("Paseo skill sync overwrite fix", ["paseo"], "skill-sync-ovw-pt"),
    ("Relay route ladder with fallback", [], "relay-route-fb-pt"),
    ("Hermes model fallback", ["hermes"], "model-fb-pt"),
    ("CFEngine upstream PR watch relay", ["cfengine"], "up-pr-watch-pt"),
    ("Session-finder Paseo workspace names", [], "sfind-paseo-ws-pt"),
    ("Codex review wait for PR 12", [], "codex-rev-pr12-pt"),
    ("Bigteam coordinator", [], "bigteam-coord-pt"),
    ("Herdr tidy idle panes", [], "tidy-idle-pt"),
    ("Backup stores schema check", [], "bkp-stores-pt"),
    ("Paseo lifecycle handoff and baton", [], "paseo-life-pt"),
    ("Adversary round 18 backup tool against real HOME", [], "adv-r18-bkp-pt"),
]


@pytest.mark.parametrize(("title", "context", "expected"), TABLE, ids=[str(i + 1) for i in range(len(TABLE))])
def test_worked_table(title: str, context: list[str], expected: str) -> None:
    assert ar.paseo_tab_name(title, context, []) == expected


@pytest.mark.parametrize(("title", "context", "expected"), TABLE, ids=[str(i + 1) for i in range(len(TABLE))])
def test_own_workspace_name_is_not_context(title: str, context: list[str], expected: str) -> None:
    # `paseo_set_name` names the workspace from this same title; a re-run must not drop the title's own words
    own = ar.paseo_workspace_name(title)[:-3]
    assert ar.paseo_tab_name(title, [own]) == ar.paseo_tab_name(title, [])
    assert ar.paseo_tab_name(title, [own + "-pw"]) == ar.paseo_tab_name(title, [])
    assert ar.paseo_tab_name(title, context + [own]) == expected


def test_collisions_use_taken_and_keep_the_limit() -> None:
    assert ar.paseo_tab_name("Adversary round 3 on PR 31", [], ["adv-r3-pr31"]) == "adv-r3-pr31-2-pt"
    assert ar.paseo_tab_name("Load watcher", [], ["loadwatch", "loadwatch-2"]) == "loadwatch-3-pt"
    # taken as real agent names (with the suffix), case-insensitive
    assert ar.paseo_tab_name("Load watcher", [], ["LoadWatch-PT"]) == "loadwatch-2-pt"
    # a full-width base is cut so base + '-N' still fits 14
    name = ar.paseo_tab_name("Relay route fallback", [], ["relay-route-fb"])
    assert name == "relay-route-2-pt" or (name.endswith("-2-pt") and len(name) <= ar.TAB_MAX)
    assert name == "relay-route-2-pt"
    assert ar.paseo_tab_name("Load watcher", [], [f"loadwatch-{n}" for n in range(2, 10)] + ["loadwatch"]) == \
        "loadwatch-10-pt"


@pytest.mark.parametrize("title", [
    "", "   ", "2026-10-24", "the of a", "Antidisestablishmentarianism", "Supercalifragilistic extra long words",
    "PR 1234567890123456", "round 3 round 4 round 5 issue 1 phase 2", "ÄÖÜ ñ 日本語", "x" * 200, "a-b-c-d-e-f-g-h-i-j",
])
def test_shape_for_any_title(title: str) -> None:
    name = ar.paseo_tab_name(title)
    assert name.endswith("-pt") and len(name) <= 17
    base = name[:-3]
    assert base and base == base.lower() and all(p.isalnum() and p.isascii() for p in base.split("-"))


def test_degenerate_titles() -> None:
    assert ar.paseo_tab_name("") == "tab-pt"
    assert ar.paseo_tab_name("2026-10-24") == "tab-pt"
    assert ar.paseo_tab_name("Antidisestablishmentarianism") == "antidisestabli-pt"   # first token cut to 14
    assert ar.paseo_tab_name("Paseo", ["paseo"]) == "paseo-pt"                        # all dropped: first token


def test_extra_identifiers_beyond_two_are_ordinary_words() -> None:
    assert ar.paseo_tab_name("PR 1 PR 2 PR 3") == "pr1-pr2-pr3-pt"


def test_context_words_are_dropped_and_phrases_apply_to_context() -> None:
    assert ar.paseo_tab_name("Load watcher service", ["load watcher"]) == "service-pt"
    assert ar.paseo_tab_name("plektra queue scan", ["plektra-djbclark"]) == "queue-scan-pt"


def test_pure_and_does_not_consume_inputs() -> None:
    taken = ["a", "b"]
    context = ["paseo"]
    first = ar.paseo_tab_name("Paseo skill sync overwrite fix", context, taken)
    assert first == ar.paseo_tab_name("Paseo skill sync overwrite fix", iter(context), iter(taken))
    assert taken == ["a", "b"] and context == ["paseo"]


# --- paseo_set_name: the --auto agent-name guard ------------------------------------------------------

def setup_paseo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, current: str, extra: bool = False,
                terminals: str = "[]", ws_title: str = "plektra-pw",
                ls: str = '[{"workspaceId": "wks_1", "name": "old-work-pw"}]', ls_rc: int = 0) -> Path:
    home = tmp_path / "home"
    agents = home / "agents" / "Users-x-src-y"
    agents.mkdir(parents=True)
    (agents / "abc.json").write_text(json.dumps({"id": "abc", "workspaceId": "wks_1", "title": current}))
    if extra:
        (agents / "other.json").write_text(json.dumps({"id": "other", "workspaceId": "wks_1", "title": "loadwatch-pt"}))
        (agents / "old.json").write_text(json.dumps(
            {"id": "old", "workspaceId": "wks_1", "title": "loadwatch-2-pt", "archivedAt": "2026-10-24T00:00:00Z"}))
        (agents / "elsewhere.json").write_text(json.dumps({"id": "e", "workspaceId": "wks_2", "title": "x"}))
    (home / "projects").mkdir()
    (home / "projects" / "workspaces.json").write_text(json.dumps(
        [{"workspaceId": "wks_1", "projectId": "prj_1", "title": ws_title}]))
    (home / "projects" / "projects.json").write_text(json.dumps([{"projectId": "prj_1", "displayName": "plektra-djbclark"}]))
    log = tmp_path / "calls.log"
    cli = tmp_path / "paseo"
    cli.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> {log}\n'
        'if [ "$1 $2" = "workspace ls" ]; then\n'
        f"  echo '{ls}'\n"
        f"  exit {ls_rc}\n"
        'elif [ "$1 $2" = "terminal ls" ]; then\n'
        f"  echo '{terminals}'\n"
        "fi\n")
    cli.chmod(0o755)
    monkeypatch.setenv("PASEO_HOME", str(home))
    monkeypatch.setenv("PASEO_AGENT_ID", "abc")
    monkeypatch.setenv("PASEO_CLI", str(cli))
    return log


def agent_updates(log: Path) -> list[str]:
    return [ln for ln in log.read_text().splitlines() if ln.startswith("agent update")]


@pytest.mark.parametrize(("auto", "current", "renamed"), [
    (True, "loadwatch-pt", False),     # --auto keeps a name that follows the convention (0.4.4 overwrite bug)
    (True, "My hand-made name", True),  # fallback: no suffix, the store cannot explain it, so it is replaced
    (False, "loadwatch-pt", True),     # an operator-asked /autorename always renames
    (True, "", True),
])
def test_auto_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, auto: bool, current: str, renamed: bool) -> None:
    log = setup_paseo(tmp_path, monkeypatch, current)
    out = ar.paseo_set_name("Plektra queue scan", auto=auto)
    ups = agent_updates(log)
    if renamed:
        assert ups == ["agent update abc --name queue-scan-pt --json"]   # 'plektra' is workspace/project context
        assert "(paseo tab queue-scan-pt)" in out
    else:
        assert ups == []
        assert "paseo tab kept: loadwatch-pt" in out and "names store unavailable" in out
    if renamed:
        assert ("names store unavailable" in out) is auto   # --auto replaces without a store to explain the name


def test_tab_name_avoids_live_agents_of_the_same_workspace_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = setup_paseo(tmp_path, monkeypatch, "", extra=True)
    ar.paseo_set_name("Load watcher")
    # 'loadwatch' is held by the live sibling; the archived 'loadwatch-2' and the other workspace's agent do not count
    assert agent_updates(log) == ["agent update abc --name loadwatch-2-pt --json"]


def test_own_current_name_is_not_a_collision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = setup_paseo(tmp_path, monkeypatch, "queue-scan-pt")
    ar.paseo_set_name("Plektra queue scan", auto=False)
    assert agent_updates(log) == ["agent update abc --name queue-scan-pt --json"]    # same name again, no '-2'


def test_terminal_names_count_as_taken(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = setup_paseo(tmp_path, monkeypatch, "", terminals='[{"name": "queue-scan-pt"}]')
    ar.paseo_set_name("Plektra queue scan")
    assert "terminal ls --workspace wks_1 --json" in log.read_text()
    assert agent_updates(log) == ["agent update abc --name queue-scan-2-pt --json"]


def test_rerun_with_workspace_named_from_the_same_title_gives_the_same_tab_name(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = setup_paseo(tmp_path, monkeypatch, "", ws_title="paseo-skill-sync-overwrite-fix-pw")
    ar.paseo_set_name("Paseo skill sync overwrite fix")
    assert agent_updates(log) == ["agent update abc --name paseo-skill-pt --json"]


@pytest.mark.parametrize("agent", ["*", "../abc", "a/b", "", "abc\n", "a b"])
def test_agent_id_must_be_a_plain_id_before_globbing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent: str) -> None:
    setup_paseo(tmp_path, monkeypatch, "kept")
    assert ar.paseo_agent_record("abc")["title"] == "kept"
    assert ar.paseo_agent_record(agent) == {}      # '*' would otherwise match abc.json
    assert ar.paseo_workspace_id(agent) is None


def test_tab_name_without_a_workspace_record_still_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "calls.log"
    cli = tmp_path / "paseo"
    cli.write_text(f'#!/bin/sh\necho "$@" >> {log}\n')
    cli.chmod(0o755)
    monkeypatch.setenv("PASEO_HOME", str(tmp_path / "empty"))
    monkeypatch.setenv("PASEO_AGENT_ID", "abc")
    monkeypatch.setenv("PASEO_CLI", str(cli))
    out = ar.paseo_set_name("Load watcher", auto=True)
    assert agent_updates(log) == ["agent update abc --name loadwatch-pt --json"]
    assert "paseo workspace: not found" in out


def test_rename_of_a_named_session_is_shortened_against_the_applied_workspace_name_not_the_old_title(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 'Adversary review' -> 'Adversary review fix': the call replaces the workspace title, so the old title's
    # words ('adversary', 'review') must not be dropped from the tab (the old behaviour gave "fix-pt").
    log = setup_paseo(tmp_path, monkeypatch, "adversary-review-pt", ws_title="adversary-review-pw")
    ar.paseo_set_name("Adversary review fix", auto=False)
    assert agent_updates(log) == ["agent update abc --name adv-rev-fix-pt --json"]
    assert "workspace rename wks_1 adversary-review-fix-pw" in log.read_text()


def test_kept_workspace_context_comes_from_the_workspace_ls_name_that_decided_the_keep(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # workspaces.json has no title, `workspace ls` says old-work-pw (the kept one): the tab drops 'old' and 'work'.
    log = setup_paseo(tmp_path, monkeypatch, "", ws_title="")
    out = ar.paseo_set_name("Old work fix", auto=True)
    assert agent_updates(log) == ["agent update abc --name fix-pt --json"]
    assert "(paseo workspace kept: old-work-pw)" in out


@pytest.mark.parametrize(("ls", "ls_rc"), [
    ('{"workspaces": []}', 0),            # an object, not a list
    ('[{"workspaceId": "wks_1", "name": "old-work-pw"}]', 1),   # failing command
    ('not json', 0),
])
def test_unusable_workspace_ls_output_is_reported_never_fatal(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ls: str, ls_rc: int) -> None:
    log = setup_paseo(tmp_path, monkeypatch, "", ls=ls, ls_rc=ls_rc)
    out = ar.paseo_set_name("Old work fix", auto=True)
    assert len(agent_updates(log)) == 1                       # the tab is still named
    assert "(paseo workspace: " in out and "workspace rename" not in log.read_text()


def test_workspace_ls_list_of_non_objects_does_not_crash_and_the_workspace_is_renamed(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = setup_paseo(tmp_path, monkeypatch, "", ls='["old-work-pw"]')
    out = ar.paseo_set_name("Old work fix", auto=True)
    assert "workspace rename wks_1 old-work-fix-pw" in log.read_text() and "(paseo workspace old-work-fix-pw)" in out
