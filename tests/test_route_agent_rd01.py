"""route_agent.py rd-01 (2026-11-14): `plan` / `adjust` print `ade-worker-run` dispatch lines, never a bare `paseo run`.

A bare `paseo run ... --no-wait` line has no workspace, and Paseo ignores `--cwd` (getpaseo/paseo#9699, duplicate of
getpaseo/paseo#4125), so a worker launched from a plan line landed in the caller's own workspace (agent 91e12a13, 2026-11-14).
"""
from __future__ import annotations

import contextlib
import io
import json
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
OLD_KEYS = {"kind", "service", "cli", "agent", "model", "dispatch", "remaining", "why"}


def _run(*argv, env=None):
    """Run `route_agent.main(argv)` on the idle quota fixture; return (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    env = {"PASEO_AGENT_ID": ""} if env is None else env
    with mock.patch.object(r, "load_snapshot", return_value=(IDLE, 60.0)), \
            mock.patch.object(r, "operator_disabled", return_value=set()), \
            mock.patch.dict("os.environ", env), \
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
                        "--lead", LEAD, "--cwd", "/tmp/x-wt")
    routed = [s for s in slices if s["dispatch"] and s["agent"] != "cursor-cloud"]
    assert len(routed) >= 3
    for i, s in enumerate(slices):
        if not s["dispatch"]:
            continue
        if s["agent"] == "cursor-cloud":        # a cloud agent: no Paseo workspace to place
            assert s["dispatch"].startswith("cursor-cloud launch ") and s["dispatch_warnings"] == []
            continue
        argv = shlex.split(s["dispatch"].replace("~", "HOME", 1))
        assert argv[0] == "HOME" + r.WORKER_RUN[1:], s["dispatch"]
        assert argv[1:5] == ["--lead", LEAD, "--slice", f"s{i}"], s["dispatch"]
        assert argv[5:7] == ["--cwd", "/tmp/x-wt"]
        assert argv[7] == "--" and argv[8] == "--provider", s["dispatch"]
        assert argv[-1] == "--no-wait"
        assert "paseo" not in argv and "run" not in argv[:8]
        assert s["dispatch_warnings"] == []


def test_a_complete_placement_has_no_warning_and_no_bare_paseo_run():
    slices, err = _slices("plan", "--kinds", "frontier", "--slice", "review", "--lead", LEAD, "--cwd", "/tmp/x-wt",
                          "--window-middle", "tendcf-review", "--worker-repo", "tendcf")
    d = slices[0]["dispatch"]
    assert d.startswith(f"{r.WORKER_RUN} --lead {LEAD} --slice review --window-middle tendcf-review --repo tendcf "
                        "--cwd /tmp/x-wt -- --provider ")
    assert not d.startswith("paseo run")
    assert slices[0]["dispatch_warnings"] == []
    assert "WARNING: slice" not in err


def test_missing_placement_warns_in_json_and_on_stderr_and_keeps_placeholders():
    slices, err = _slices("plan", "--kinds", "frontier")
    s = slices[0]
    assert s["dispatch"].startswith(f"{r.WORKER_RUN} --lead {r.LEAD_PLACEHOLDER} --slice {r.SLICE_PLACEHOLDER} -- --provider ")
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
        assert set(s) - OLD_KEYS == {"dispatch_warnings"}
        assert s["service"] and s["agent"] and s["model"] is not None and isinstance(s["why"], str)


def test_text_plan_prints_the_worker_run_line_and_the_warning():
    code, out, err = _run("plan", "--kinds", "code")
    assert code == 0
    assert f"  {r.WORKER_RUN} --lead {r.LEAD_PLACEHOLDER} --slice {r.SLICE_PLACEHOLDER} -- --provider " in out
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
    assert slices[0]["dispatch"].startswith(f"{r.WORKER_RUN} --lead {LEAD} --slice a --cwd /w -- --provider ")
    assert slices[0]["dispatch_warnings"] == []


def test_pi_template_and_cursor_cloud_lines():
    pi = r.Choice(r.BY_NAME["zai"] if "zai" in r.BY_NAME else next(s for s in r.SERVICES if s.acp_agent == "pi"),
                  80, 1, model="zai/glm-5.3-flash", kind="code")
    assert pi.service.acp_agent == "pi"
    bare = pi.dispatch
    assert bare.startswith("paseo run --provider pi/zai/glm-5.3-flash")
    pi.placement = r.Placement(lead=LEAD, slice="s", cwd="/w")
    assert pi.dispatch == f"{r.WORKER_RUN} --lead {LEAD} --slice s --cwd /w -- " + bare[len("paseo run "):]
    cc = r.Choice(r.BY_NAME["cursor-cloud"], 50, 1, model="composer-2.5", kind="code",
                  placement=r.Placement(lead=LEAD, slice="s", cwd="/w"))
    assert cc.dispatch.startswith("cursor-cloud launch ") and WORKER_RUN_NOT_IN(cc.dispatch)
    assert cc.dispatch_warnings == []


def WORKER_RUN_NOT_IN(line):
    return "ade-worker-run" not in line


def test_a_modelless_template_keeps_its_placeholder_inside_the_placed_line():
    c = r.Choice(r.BY_NAME["codex"], 80, 1, kind="code", placement=r.Placement(lead=LEAD, slice="s", cwd="/w"))
    assert c.dispatch.startswith(f"{r.WORKER_RUN} --lead {LEAD} --slice s --cwd /w -- --provider codex/<id from: ")
    assert c.dispatch.endswith("--no-wait")
