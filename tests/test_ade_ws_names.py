"""Offline tests for bin/ade_ws_names.py: the `<KIND> <repo> (<work>)` builder/parser and the legacy forms."""
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import ade_ws_names as wsn  # noqa: E402

LEAD = "8cd86203-d33b-49db-abde-9baba52bcf61"


@pytest.mark.parametrize("kind", ["MAIN", "WORKERS", "USER"])
def test_build_and_parse_round_trip(kind):
    name = wsn.build(kind, "djbclark-ade", "Wave 7")
    assert name == f"{kind} djbclark-ade (Wave 7)"
    assert wsn.parse(name) == (kind, "djbclark-ade", "Wave 7")


def test_work_may_contain_parentheses():
    assert wsn.parse("MAIN r (fix (a) and (b))") == ("MAIN", "r", "fix (a) and (b)")


@pytest.mark.parametrize("bad", [("OTHER", "r", "w"), ("MAIN", "bad repo", "w"), ("MAIN", "r", ""), ("MAIN", "r", " w"),
                                 ("MAIN", "r", "a\nb"), ("MAIN", "", "w"), ("MAIN", "r", "x" * 100)])
def test_build_refuses_bad_parts(bad):
    with pytest.raises(ValueError):
        wsn.build(*bad)


@pytest.mark.parametrize("name", ["main r (w)", "Workers r (w)", "MAIN r w", "MAIN r (w) x", "MAIN  r (w)", "MAIN (w)",
                                  f"workers m {LEAD}", "MAIN m", "", "WORKERS r ()"])
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
    assert wsn.migrated_name(leg, "djbclark-ade") == "WORKERS djbclark-ade (Wave 7)"
    assert wsn.migrated_name(leg, "other") == "WORKERS other (djbclark-ade Wave 7)"
    assert wsn.migrated_name(wsn.parse_legacy("MAIN djbclark-ade Wave 7"), "djbclark-ade") == "MAIN djbclark-ade (Wave 7)"
    assert wsn.normalize_work("repo ", "repo") == "repo "  # nothing left after the prefix: keep it


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
