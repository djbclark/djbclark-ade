"""route_agent.py rd-01 (2026-11-14): `plan` / `adjust` print `ade-worker-run` dispatch lines, never a bare `paseo run`.

A bare `paseo run ... --no-wait` line has no workspace, and Paseo ignores `--cwd` (getpaseo/paseo#9699, duplicate of
getpaseo/paseo#4125), so a worker launched from a plan line landed in the caller's own workspace (agent 91e12a13, 2026-11-14).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
sys.path.insert(0, str(ROOT / "tests"))

import route_agent as r  # noqa: E402
from test_route_agent import IDLE  # noqa: E402

LEAD = "6302bea5-9b20-4134-bcc7-7726c403eea5"
LAUNCHER = os.path.expanduser(r.WORKER_RUN)      # the emitted launcher path is absolute
WINDOW = "/Users/x/src/repo"                    # the WORKERS window's directory (the checkout), not a slice worktree
OLD_KEYS = {"kind", "service", "cli", "agent", "model", "dispatch", "remaining", "why"}


def _unset(env):
    """A context that removes every variable whose value in `env` is None (genuinely unset, not empty)."""
    import os as _os
    saved = {k: _os.environ[k] for k, v in env.items() if v is None and k in _os.environ}
    class Ctx:
        def __enter__(self):
            for k, v in env.items():
                if v is None:
                    _os.environ.pop(k, None)
        def __exit__(self, *exc):
            _os.environ.update(saved)
    return Ctx()


def _run(*argv, env=None):
    """Run `route_agent.main(argv)` on the idle quota fixture; return (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    env = {"PASEO_AGENT_ID": ""} if env is None else env
    with mock.patch.object(r, "load_snapshot", return_value=(IDLE, 60.0)), \
            mock.patch.object(r, "operator_disabled", return_value=set()), \
            mock.patch.dict("os.environ", {k: v for k, v in env.items() if v is not None}), \
            mock.patch.dict("os.environ", {}) if all(v is not None for v in env.values()) else _unset(env), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = r.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def _slices(*argv, env=None):
    code, out, err = _run(*argv, "--json", env=env)
    assert code == 0, err
    return json.loads(out)["slices"], err


def test_every_kind_dispatches_through_ade_worker_run():
    kinds = [k for k in r.KINDS]
    slices, _ = _slices("plan", "--kinds", ",".join(kinds), *[a for i, _k in enumerate(kinds) for a in ("--slice", f"s{i}")],
                        "--lead", LEAD, "--cwd", WINDOW)
    routed = [s for s in slices if s["dispatch"] and s["agent"] != "cursor-cloud"]
    assert len(routed) >= 3
    for i, s in enumerate(slices):
        if not s["dispatch"]:
            continue
        if s["agent"] == "cursor-cloud":        # a cloud agent: no Paseo workspace to place
            assert s["dispatch"].startswith("cursor-cloud launch ") and s["dispatch_warnings"] == []
            continue
        argv = shlex.split(s["dispatch"])
        assert argv[0] == LAUNCHER and not argv[0].startswith("~"), s["dispatch"]
        assert argv[1:5] == ["--lead", LEAD, "--slice", f"s{i}"], s["dispatch"]
        assert argv[5:7] == ["--cwd", WINDOW]
        assert argv[7] == "--" and argv[8] == "--provider", s["dispatch"]
        assert argv[-1] == "--no-wait"
        assert "paseo" not in argv and "run" not in argv[:8]
        assert s["dispatch_warnings"] == []


def test_a_complete_placement_has_no_warning_and_no_bare_paseo_run():
    slices, err = _slices("plan", "--kinds", "frontier", "--slice", "review", "--lead", LEAD, "--cwd", WINDOW,
                          "--window-middle", "tendcf-review", "--worker-repo", "tendcf")
    d = slices[0]["dispatch"]
    assert d.startswith(f"{LAUNCHER} --lead {LEAD} --slice review --window-middle tendcf-review --repo tendcf "
                        "--cwd /Users/x/src/repo -- --provider ")
    assert not d.startswith("paseo run")
    assert slices[0]["dispatch_warnings"] == []
    assert "WARNING: slice" not in err


def test_missing_placement_warns_in_json_and_on_stderr_and_keeps_placeholders():
    slices, err = _slices("plan", "--kinds", "frontier")
    s = slices[0]
    assert s["dispatch"].startswith(f"{LAUNCHER} --lead '<lead>' --slice '<slice>' -- --provider ")
    assert not s["dispatch"].startswith("paseo run")
    joined = " ".join(s["dispatch_warnings"])
    assert "no lead id" in joined and "no slice name" in joined and "no --cwd" in joined
    for w in s["dispatch_warnings"]:
        assert f"WARNING: slice 1 (frontier): {w}" in err


def test_lead_defaults_to_the_callers_agent_id_and_a_flag_overrides_it():
    slices, _ = _slices("plan", "--kinds", "code", "--slice", "a", "--cwd", "/tmp/w", env={"PASEO_AGENT_ID": LEAD})
    assert f"--lead {LEAD} " in slices[0]["dispatch"]
    other = "0a371c1b-648d-483e-97af-d0b8bea8f731"
    slices, _ = _slices("plan", "--kinds", "code", "--slice", "a", "--cwd", "/tmp/w", "--lead", other,
                        env={"PASEO_AGENT_ID": LEAD})
    assert f"--lead {other} " in slices[0]["dispatch"]


def test_a_cwd_with_a_space_is_quoted_as_one_argument():
    slices, _ = _slices("plan", "--kinds", "code", "--slice", "a", "--lead", LEAD, "--cwd", "/tmp/my wt")
    argv = shlex.split(slices[0]["dispatch"])
    assert argv[argv.index("--cwd") + 1] == "/tmp/my wt"


def test_slice_count_must_match_kinds():
    with pytest.raises(SystemExit) as e:
        _run("plan", "--kinds", "code,code", "--slice", "only-one")
    assert e.value.code == 2


def test_old_json_keys_are_unchanged_and_the_new_key_is_additive():
    slices, _ = _slices("plan", "--kinds", "code,research", "--slice", "a", "--slice", "b", "--lead", LEAD, "--cwd", "/w")
    for s in slices:
        assert OLD_KEYS <= set(s)
        assert set(s) - OLD_KEYS == {"dispatch_warnings", "skipped", "model_note"}
        assert s["service"] and s["agent"] and s["model"] is not None and isinstance(s["why"], str)


def test_text_plan_prints_the_worker_run_line_and_the_warning():
    code, out, err = _run("plan", "--kinds", "code")
    assert code == 0
    assert f"  {LAUNCHER} --lead '<lead>' --slice '<slice>' -- --provider " in out
    assert "WARNING: slice 1 (code): no lead id" in err


def test_route_keeps_the_bare_template_and_says_so_in_json():
    code, out, err = _run("route", "--kind", "code", "--json")
    assert code == 0
    data = json.loads(out)
    assert data["dispatch"].startswith("paseo run --provider ")
    assert any("bare `paseo run` template" in w and "ade-worker-run" in w for w in data["dispatch_warnings"])
    assert "WARNING" not in err        # pr-radar reads route's stdout; it places its own agents


def test_adjust_dispatches_through_ade_worker_run_too():
    with mock.patch.dict("os.environ", {"ADE_ROUTE_ADJUST_DIR": "/nonexistent-rd01"}), \
            mock.patch("route_adjust.state_dir", return_value=Path("/nonexistent-rd01")):
        slices, err = _slices("adjust", "--kinds", "code", "--dry-run", "--slice", "a", "--lead", LEAD, "--cwd", "/w")
    assert slices[0]["dispatch"].startswith(f"{LAUNCHER} --lead {LEAD} --slice a --cwd /w -- --provider ")
    assert slices[0]["dispatch_warnings"] == []


def test_pi_template_and_cursor_cloud_lines():
    pi = r.Choice(r.BY_NAME["zai"] if "zai" in r.BY_NAME else next(s for s in r.SERVICES if s.acp_agent == "pi"),
                  80, 1, model="zai/glm-5.3-flash", kind="code")
    assert pi.service.acp_agent == "pi"
    bare = pi.dispatch
    assert bare.startswith("paseo run --provider pi/zai/glm-5.3-flash")
    pi.placement = r.Placement(lead=LEAD, slice="s", cwd="/w")
    assert pi.dispatch == f"{LAUNCHER} --lead {LEAD} --slice s --cwd /w -- " + bare[len("paseo run "):]
    cc = r.Choice(r.BY_NAME["cursor-cloud"], 50, 1, model="composer-2.5", kind="code",
                  placement=r.Placement(lead=LEAD, slice="s", cwd="/w"))
    assert cc.dispatch.startswith("cursor-cloud launch ") and WORKER_RUN_NOT_IN(cc.dispatch)
    assert cc.dispatch_warnings == []


def WORKER_RUN_NOT_IN(line):
    return "ade-worker-run" not in line


def test_a_modelless_template_keeps_its_placeholder_inside_the_placed_line():
    c = r.Choice(r.BY_NAME["codex"], 80, 1, kind="code", placement=r.Placement(lead=LEAD, slice="s", cwd="/w"))
    assert c.dispatch.startswith(f"{LAUNCHER} --lead {LEAD} --slice s --cwd /w -- --provider 'codex/<id from: ")
    assert c.dispatch.endswith("--no-wait")


def test_a_modelless_placed_line_is_a_parsable_shell_command_and_warns():
    """Lead review of PR 727 (B1): an unquoted `<id from: ...>` is an input redirection; bash must read the line as one command."""
    import subprocess
    c = r.Choice(r.BY_NAME["codex"], 80, 1, kind="code", placement=r.Placement(lead=LEAD, slice="s", cwd="/w"))
    argv = shlex.split(c.dispatch)
    assert argv[argv.index("--provider") + 1] == "codex/<id from: paseo provider models codex>"
    assert subprocess.run(["bash", "-n", "-c", c.dispatch], capture_output=True).returncode == 0
    assert any("no model profile" in w and "paseo provider models codex" in w for w in c.dispatch_warnings)
    # a bare route template (placement None) is unchanged: pr-radar-route parses it
    bare = r.Choice(r.BY_NAME["codex"], 80, 1, kind="code").dispatch
    assert bare.startswith("paseo run --provider codex/<id from: paseo provider models codex> ")
    ok = r.Choice(r.BY_NAME["claude"], 80, 1, model="sonnet --effort high", kind="code",
                  placement=r.Placement(lead=LEAD, slice="s", cwd="/w"))
    assert not any("no model profile" in w for w in ok.dispatch_warnings)


def test_every_placed_line_of_a_plan_parses_in_bash():
    import subprocess
    slices, _ = _slices("plan", "--kinds", "code,research,frontier,bulk", "--lead", LEAD, "--cwd", WINDOW,
                        *[a for n in "abcd" for a in ("--slice", n)])
    for s in slices:
        if s["dispatch"] and s["agent"] != "cursor-cloud":
            assert subprocess.run(["bash", "-n", "-c", s["dispatch"]], capture_output=True).returncode == 0, s["dispatch"]


def test_a_lead_that_is_not_the_callers_own_id_is_warned_about():
    other = "0a371c1b-648d-483e-97af-d0b8bea8f731"
    slices, _ = _slices("plan", "--kinds", "code", "--lead", other, "--slice", "a", "--cwd", WINDOW,
                        env={"PASEO_AGENT_ID": LEAD})
    assert any("not the caller's own id" in w and "--on-behalf-of-lead" in w for w in slices[0]["dispatch_warnings"])
    slices, _ = _slices("plan", "--kinds", "code", "--lead", LEAD, "--slice", "a", "--cwd", WINDOW, env={"PASEO_AGENT_ID": LEAD})
    assert slices[0]["dispatch_warnings"] == []
    slices, _ = _slices("plan", "--kinds", "code", "--lead", other, "--slice", "a", "--cwd", WINDOW, env={"PASEO_AGENT_ID": ""})
    assert slices[0]["dispatch_warnings"] == []      # no caller id to compare with (not running inside a Paseo agent)


def test_placeholders_are_quoted_literals_a_shell_cannot_redirect_or_expand():
    slices, _ = _slices("plan", "--kinds", "code")
    d = slices[0]["dispatch"]
    assert f"--lead '<lead>' --slice '<slice>' -- " in d, d
    assert r.LEAD_PLACEHOLDER == "<lead>" and r.SLICE_PLACEHOLDER == "<slice>"
    assert "~" not in d.split(" -- ")[0]


def test_every_user_value_is_one_shell_token():
    slices, _ = _slices("plan", "--kinds", "code", "--lead", LEAD, "--slice", "a b", "--cwd", "/x/my dir",
                        "--window-middle", "Wave 7", "--worker-repo", "re po")
    argv = shlex.split(slices[0]["dispatch"])
    assert argv[argv.index("--slice") + 1] == "a b"
    assert argv[argv.index("--window-middle") + 1] == "Wave 7"
    assert argv[argv.index("--repo") + 1] == "re po"
    assert argv[argv.index("--cwd") + 1] == "/x/my dir"
    d = slices[0]["dispatch"]
    assert "'a b'" in d and "'Wave 7'" in d and "'re po'" in d and "'/x/my dir'" in d
    for hostile in ("$(touch x)", "a;b", "`id`"):
        slices, _ = _slices("plan", "--kinds", "code", "--lead", LEAD, "--slice", hostile)
        assert shlex.split(slices[0]["dispatch"])[4] == hostile


@pytest.mark.parametrize("flag,needle", [("--lead", "no lead id"), ("--slice", "no slice name"), ("--cwd", "no --cwd")])
def test_each_missing_input_alone_is_named(flag, needle):
    full = {"--lead": LEAD, "--slice": "a", "--cwd": WINDOW}
    argv = ["plan", "--kinds", "code"] + [x for k, v in full.items() if k != flag for x in (k, v)]
    slices, err = _slices(*argv)
    warnings = slices[0]["dispatch_warnings"]
    assert len(warnings) == 1 and needle in warnings[0]
    assert f"WARNING: slice 1 (code): {warnings[0]}" in err


def test_an_unset_caller_id_is_a_warning_not_a_fake_lead():
    slices, _ = _slices("plan", "--kinds", "code", "--slice", "a", "--cwd", WINDOW, env={"PASEO_AGENT_ID": None})
    assert "--lead '<lead>'" in slices[0]["dispatch"]
    assert any("no lead id" in w for w in slices[0]["dispatch_warnings"])


def test_a_lead_or_slice_the_launcher_would_refuse_is_flagged_at_plan_time():
    slices, _ = _slices("plan", "--kinds", "code", "--lead", "not-an-id", "--slice=-bad", "--cwd", WINDOW)
    joined = " ".join(slices[0]["dispatch_warnings"])
    assert "not an agent id" in joined and "not a valid slice name" in joined


def test_empty_values_are_not_emitted_and_count_as_missing():
    slices, _ = _slices("plan", "--kinds", "code", "--lead", LEAD, "--slice", "a", "--cwd", "", "--window-middle", "",
                        "--worker-repo", "")
    d = slices[0]["dispatch"]
    assert "--cwd" not in d and "--window-middle" not in d and "--repo" not in d.split(" -- ")[0]
    assert any("no --cwd" in w for w in slices[0]["dispatch_warnings"])


def test_more_slice_names_than_kinds_is_a_usage_error():
    with pytest.raises(SystemExit) as e:
        _run("plan", "--kinds", "code", "--slice", "a", "--slice", "b")
    assert e.value.code == 2


def test_adjust_warns_on_stderr_and_a_slice_count_mismatch_writes_no_state(tmp_path):
    with mock.patch("route_adjust.state_dir", return_value=tmp_path):
        slices, err = _slices("adjust", "--kinds", "code", "--dry-run")
        assert "WARNING: slice 1 (code): no slice name" in err
        with pytest.raises(SystemExit) as e:
            _run("adjust", "--kinds", "code,code", "--slice", "only-one")
        assert e.value.code == 2
    assert list(tmp_path.iterdir()) == []      # exited before any hold/restore state or change log was written
