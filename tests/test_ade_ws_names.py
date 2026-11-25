"""Offline tests for bin/ade_ws_names.py: the `<KIND> <repo> (<work>)` builder/parser and the legacy forms."""
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import ade_ws_names as wsn  # noqa: E402

LEAD = "8cd86203-d33b-49db-abde-9baba52bcf61"


@pytest.mark.parametrize("kind", ["LEAD", "WORKER", "OTHER"])
def test_build_and_parse_round_trip(kind):
    name = wsn.build(kind, "djbclark-ade", "Wave 7")
    assert name == f"{kind} djbclark-ade (Wave 7)"
    assert wsn.parse(name) == (kind, "djbclark-ade", "Wave 7")
    assert wsn.parse(name).box == kind and wsn.parse(name).current is True


@pytest.mark.parametrize("kind,box", [("MAIN", "LEAD"), ("WORKERS", "WORKER"), ("USER", "OTHER")])
def test_parse_still_reads_the_2026_11_13_kinds_as_their_box(kind, box):
    n = wsn.parse(f"{kind} djbclark-ade (Wave 7)")
    assert n == (kind, "djbclark-ade", "Wave 7")
    assert n.box == box and n.current is False
    assert wsn.current_name(n) == f"{box} djbclark-ade (Wave 7)"
    assert wsn.BOX_OF[kind] == box


@pytest.mark.parametrize("kind", ["MAIN", "WORKERS", "USER"])
def test_build_refuses_the_old_kinds(kind):
    with pytest.raises(ValueError):
        wsn.build(kind, "r", "w")


def test_current_name_leaves_a_current_name_alone():
    assert wsn.current_name(wsn.parse("WORKER r (w (x))")) == "WORKER r (w (x))"
    assert wsn.current_name(wsn.parse("MAIN r (fix (a) and (b))")) == "LEAD r (fix (a) and (b))"


def test_kind_tables_agree():
    assert wsn.KINDS == ("LEAD", "WORKER", "OTHER") and wsn.LEGACY_KINDS == ("MAIN", "WORKERS", "USER")
    assert set(wsn.BOX_OF) == set(wsn.KINDS) | set(wsn.LEGACY_KINDS)
    assert set(wsn.BOX_OF.values()) == set(wsn.KINDS)


def test_work_may_contain_parentheses():
    assert wsn.parse("LEAD r (fix (a) and (b))") == ("LEAD", "r", "fix (a) and (b)")


@pytest.mark.parametrize("bad", [("BOGUS", "r", "w"), ("LEAD", "bad repo", "w"), ("LEAD", "r", ""), ("LEAD", "r", " w"),
                                 ("LEAD", "r", "a\nb"), ("LEAD", "", "w"), ("LEAD", "r", "x" * 100)])
def test_build_refuses_bad_parts(bad):
    with pytest.raises(ValueError):
        wsn.build(*bad)


@pytest.mark.parametrize("name", ["main r (w)", "Workers r (w)", "lead r (w)", "Worker r (w)", "MAIN r w", "LEAD r (w) x", "MAIN  r (w)",
                                  "MAIN (w)", "OTHERS r (w)", f"workers m {LEAD}", "MAIN m", "", "WORKERS r ()", "WORKER r ()"])
def test_parse_rejects_everything_else(name):
    assert wsn.parse(name) is None


def test_parse_legacy_recognises_exactly_the_old_forms():
    assert wsn.parse_legacy(f"workers djbclark-ade Wave 7 {LEAD}") == ("WORKERS", "djbclark-ade Wave 7", LEAD)
    assert wsn.parse_legacy(f"WORKERS djbclark-ade Wave 7 {LEAD}") == ("WORKERS", "djbclark-ade Wave 7", LEAD)
    assert wsn.parse_legacy("MAIN djbclark-ade Wave 7") == ("MAIN", "djbclark-ade Wave 7", None)
    for name in ["MAIN djbclark-ade (Wave 7)", "WORKERS djbclark-ade (Wave 7)", f"Workers m {LEAD}", f"workers  {LEAD}",
                 "workers m not-a-uuid", "MAIN ", "master"]:
        assert wsn.parse_legacy(name) is None, name


def test_migrated_name_folds_a_repo_prefixed_middle():
    leg = wsn.parse_legacy(f"workers djbclark-ade Wave 7 {LEAD}")
    assert wsn.migrated_name(leg, "djbclark-ade") == "WORKER djbclark-ade (Wave 7)"
    assert wsn.migrated_name(leg, "other") == "WORKER other (djbclark-ade Wave 7)"
    assert wsn.migrated_name(wsn.parse_legacy("MAIN djbclark-ade Wave 7"), "djbclark-ade") == "LEAD djbclark-ade (Wave 7)"
    assert wsn.normalize_work("repo ", "repo") == "repo"  # nothing left after the prefix: keep the (stripped) middle


def test_repo_of_uses_the_main_checkout_and_falls_back_to_the_basename(tmp_path):
    main = tmp_path / "proj"
    main.mkdir()
    git = lambda *a: subprocess.run(["git", "-C", str(main), *a], check=True, capture_output=True)  # noqa: E731
    git("init", "-q")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
    (main / "sub").mkdir()
    git("worktree", "add", "-q", "-b", "b", str(tmp_path / "proj-b-wt"))
    assert wsn.repo_of(str(main)) == "proj" and wsn.repo_of(str(main / "sub")) == "proj"
    assert wsn.repo_of(str(tmp_path / "proj-b-wt")) == "proj"
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert wsn.repo_of(str(plain)) == "not-a-repo" and wsn.repo_of(str(tmp_path / "missing")) == "missing"


def test_repo_of_ignores_inherited_git_environment(tmp_path, monkeypatch):  # F6
    main = tmp_path / "real-repo"
    main.mkdir()
    subprocess.run(["git", "-C", str(main), "init", "-q"], check=True, capture_output=True)
    other = tmp_path / "plain"
    other.mkdir()
    monkeypatch.setenv("GIT_DIR", str(main / ".git"))
    monkeypatch.setenv("GIT_COMMON_DIR", str(main / ".git"))
    assert wsn.repo_of(str(other)) == "plain"


def test_normalize_work_strips_what_the_repo_prefix_leaves():  # F8
    assert wsn.normalize_work("repo  Wave 7", "repo") == "Wave 7"
    assert wsn.migrated_name(wsn.parse_legacy("MAIN repo  Wave 7"), "repo") == "LEAD repo (Wave 7)"


def test_tab_name_has_no_worktree_part_without_a_worktree():
    # Operator ruling 2026-11-25: lead ownership lives in `ade.lead` label, not the tab title.
    assert wsn.tab_name("WORKER", "s", LEAD) == "worker s"
    assert wsn.tab_name("WORKER", "s") == "worker s"
    assert wsn.tab_name("LEAD", "s", LEAD) == "worker s"  # a worker in the lead's window is still `worker ...`
    assert wsn.tab_name("OTHER", "s", LEAD) == "other s"
    assert wsn.tab_name("WORKER", "s", LEAD, None) == wsn.tab_name("WORKER", "s", LEAD, "")
    assert set(wsn.TAB_PREFIX) == set(wsn.KINDS)


def test_tab_name_names_the_worktree_directory():
    assert wsn.tab_name("WORKER", "s", LEAD, "/x/djbclark-ade-foo-wt") == "worker s [wt: djbclark-ade-foo-wt]"
    assert wsn.tab_name("WORKER", "s", LEAD, "/x/djbclark-ade-foo-wt/") == "worker s [wt: djbclark-ade-foo-wt]"
    assert wsn.tab_name("OTHER", "s", LEAD, "/x/y-wt") == "other s [wt: y-wt]"


def test_tab_name_shortens_an_overlong_worktree_name_with_a_tilde():
    name = wsn.tab_name("WORKER", "s", LEAD, "/x/" + "w" * 200)
    assert len(name) == wsn.NAME_LIMIT and name.endswith("~]") and name.startswith("worker s [wt: www")
    # a worktree name that only just fits is not shortened
    base = "worker s"
    room = wsn.NAME_LIMIT - len(base) - len(" [wt: ]")
    fits = "d" * room
    assert wsn.tab_name("WORKER", "s", LEAD, f"/x/{fits}") == f"{base} [wt: {fits}]"
    assert len(wsn.tab_name("WORKER", "s", LEAD, f"/x/{fits}d")) == wsn.NAME_LIMIT


def test_tab_name_drops_the_worktree_part_when_there_is_no_room_and_strips_brackets():
    long_slice = "s" * (wsn.NAME_LIMIT - len("worker ") - 3)  # leaves too little room for any `[wt: x]`
    assert wsn.tab_name("WORKER", long_slice, LEAD, "/x/dir") == f"worker {long_slice}"
    assert wsn.tab_name("WORKER", "s", LEAD, "/x/a[b]c") == "worker s [wt: abc]"


def test_window_registry_roundtrip_and_backward_compatibility(tmp_path):
    p = tmp_path / f"{LEAD}.windows.json"
    # Missing file -> empty
    assert wsn.read_window_registry(p) == (set(), {})
    # Legacy format without `entries` still loads cleanly
    p.write_text('{"windows": ["wks_old1"]}', encoding="utf-8")
    assert wsn.read_window_registry(p) == ({"wks_old1"}, {})
    # New format stores both `"windows"` and structured `"entries"` atomically
    wsn.write_window_registry(
        p,
        {"wks_w1", "wks_o1"},
        {
            "wks_w1": {"windowId": "wks_w1", "box": "WORKER", "repo": "djbclark-ade", "lead": LEAD, "work": "Wave 9"},
            "wks_o1": {"windowId": "wks_o1", "box": "OTHER", "repo": "tendcf", "lead": LEAD},
            "wks_dropped": {"windowId": "wks_dropped", "box": "WORKER"},
        },
    )
    ids, entries = wsn.read_window_registry(p)
    assert ids == {"wks_w1", "wks_o1"}
    assert entries["wks_w1"]["box"] == "WORKER" and entries["wks_w1"]["repo"] == "djbclark-ade"
    assert entries["wks_o1"]["box"] == "OTHER" and "wks_dropped" not in entries
    all_reg = wsn.all_registered_windows(tmp_path)
    assert all_reg["wks_w1"]["box"] == "WORKER" and all_reg["wks_w1"]["lead"] == LEAD
