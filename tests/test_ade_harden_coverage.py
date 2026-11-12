"""S6 coverage: Forgejo read-back, renewal, notification, gate canary."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
sys.path.insert(0, str(BIN))
import ade_harden as ah  # noqa: E402
import ade_harden_coverage as cov  # noqa: E402

NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)


def _completed(argv, *, rc=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(argv, rc, stdout=stdout, stderr=stderr)


def _repo_row():
    return {"owner": "djbclark", "name": "djbclark-ade", "profile": "active"}


def _cfg(tmp_path, extra=""):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "hardening.toml").write_text(
        """
schema_version = 1
[hardening]
owners = ["djbclark"]
[hardening.defaults]
pr_creation_policy = "collaborators_only"
disable_wiki = true
disable_projects = true
[hardening.interaction_limits]
limit = "collaborators_only"
min_remaining_days = 14
expiry = "six_months"
[[hardening.repo]]
owner = "djbclark"
name = "djbclark-ade"
"""
        + extra
    )
    return ah.load_config(root=root)


def test_forgejo_readback_reports_drift(tmp_path):
    cfg = _cfg(tmp_path)
    seen = []

    def runner(argv):
        seen.append(argv)
        # forgejo-api's real shape: --host HOST GET /repos/OWNER/NAME.
        assert argv[1:4] == ["--host", "forgejo.example.test", "GET"]
        assert argv[4] == "/repos/djbclark/djbclark-ade"
        assert "token" not in " ".join(argv).lower()
        return _completed(
            argv,
            stdout=json.dumps(
                {"has_wiki": True, "has_projects": False, "has_issues": True}
            ),
        )

    findings = cov.observe_forgejo_repo(
        cfg, _repo_row(), runner=runner,
        base_url="https://forgejo.example.test",
        api=tmp_path / "forgejo-api",
    )
    by = {f.setting: f for f in findings}
    assert by["has_wiki"].status == "drift"
    assert by["has_projects"].status == "ok"
    assert seen[0][0] == str(tmp_path / "forgejo-api")


def test_forgejo_unreachable_is_unknown_not_drift(tmp_path):
    cfg = _cfg(tmp_path)

    def runner(argv):
        return _completed(argv, rc=1, stderr="connection refused\n")

    findings = cov.observe_forgejo_repo(
        cfg, _repo_row(), runner=runner,
        base_url="https://forgejo.example.test", api=tmp_path / "forgejo-api",
    )
    assert len(findings) == 1
    assert findings[0].status == "unknown"


def test_forgejo_whitespace_stderr_does_not_crash(tmp_path):
    cfg = _cfg(tmp_path)

    def runner(argv):
        return _completed(argv, rc=1, stderr="\n")

    findings = cov.observe_forgejo_repo(
        cfg, _repo_row(), runner=runner,
        base_url="https://forgejo.example.test", api=tmp_path / "forgejo-api",
    )
    assert findings[0].status == "unknown"
    assert findings[0].detail


def test_forgejo_base_url_must_be_https(tmp_path):
    with pytest.raises(ah.HardenError, match="base_url"):
        _cfg(tmp_path, extra='[hardening.forgejo]\nbase_url = "http://insecure"\n')


def test_forgejo_base_url_rejects_port_and_subpath(tmp_path):
    """forgejo-api builds https://HOST/api/v1, so a port or path would misread."""
    for i, bad in enumerate((
        "https://forgejo.example.test:3000",
        "https://forgejo.example.test/forgejo",
        "https://forgejo.example.test/api?x=1",
    )):
        with pytest.raises(ah.HardenError, match="base_url"):
            _cfg(tmp_path / str(i), extra=f'[hardening.forgejo]\nbase_url = "{bad}"\n')
    cfg = _cfg(
        tmp_path / "ok",
        extra='[hardening.forgejo]\nbase_url = "https://forgejo.example.test"\n',
    )
    assert cfg.hardening["forgejo"]["base_url"].startswith("https://")


def test_missing_forgejo_script_fails_a_configured_check(tmp_path, monkeypatch):
    cfg = _cfg(
        tmp_path, extra='[hardening.forgejo]\nbase_url = "https://forgejo.example.test"\n'
    )
    monkeypatch.setattr(cov, "forgejo_api_script", lambda: None)
    findings = cov.observe_forgejo_repo(
        cfg, _repo_row(), runner=lambda a: _completed(a),
        base_url="https://forgejo.example.test",
    )
    assert findings[0].status == "error"


def test_forgejo_script_resolves_from_the_skill_link(tmp_path, monkeypatch):
    script = tmp_path / ".agents/skills/forgejo/scripts/forgejo-api"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\n")
    monkeypatch.setattr(cov.shutil, "which", lambda name: None)
    monkeypatch.setattr(cov.Path, "home", staticmethod(lambda: tmp_path))
    assert cov.forgejo_api_script() == script


def test_renewal_only_when_limit_matches_and_inside_window():
    soon = (NOW + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    plan = cov.renewal_plan(
        {"limit": "collaborators_only", "expires_at": soon},
        want_limit="collaborators_only", want_expiry="six_months",
        min_days=14, now=NOW,
    )
    assert plan["renew"] is True
    assert plan["request"]["argv"][:5] == ["gh", "api", "--method", "PUT", "-H"]
    assert json.loads(plan["request"]["body"]) == {
        "limit": "collaborators_only", "expiry": "six_months"
    }

    far = (NOW + timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert cov.renewal_plan(
        {"limit": "collaborators_only", "expires_at": far},
        want_limit="collaborators_only", want_expiry="six_months",
        min_days=14, now=NOW,
    )["renew"] is False

    # A different current limit is never renewed: a check must not change it.
    assert cov.renewal_plan(
        {"limit": "existing_users", "expires_at": soon},
        want_limit="collaborators_only", want_expiry="six_months",
        min_days=14, now=NOW,
    )["renew"] is False


def test_renew_dry_run_never_calls_the_writer(tmp_path):
    cfg = _cfg(tmp_path)
    soon = (NOW + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def reader(argv):
        assert "--method" not in argv
        return _completed(
            argv,
            stdout=json.dumps(
                {"limit": "collaborators_only", "expires_at": soon}
            ),
        )

    def writer(argv, body):
        raise AssertionError("dry-run must not write")

    plan = cov.renew_interaction_limits(
        cfg, reader=reader, writer=writer, now=NOW, dry_run=True
    )
    assert plan["renew"] is True and plan["wrote"] is False


def test_renew_apply_writes_then_reads_back(tmp_path):
    cfg = _cfg(tmp_path)
    soon = (NOW + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    later = (NOW + timedelta(days=180)).strftime("%Y-%m-%dT%H:%M:%SZ")
    reads = {"n": 0}
    written = {}

    def reader(argv):
        reads["n"] += 1
        expires = soon if reads["n"] == 1 else later
        return _completed(
            argv,
            stdout=json.dumps(
                {"limit": "collaborators_only", "expires_at": expires}
            ),
        )

    def writer(argv, body):
        written["argv"] = argv
        written["body"] = body
        assert body not in argv
        return _completed(argv)

    plan = cov.renew_interaction_limits(
        cfg, reader=reader, writer=writer, now=NOW, dry_run=False
    )
    assert plan["wrote"] is True and plan["readback_ok"] is True
    assert reads["n"] == 2
    assert json.loads(written["body"])["expiry"] == "six_months"


def test_renew_readback_requires_the_expiry_to_move_forward(tmp_path):
    """A PUT that exits 0 but leaves the expiry unchanged is not success."""
    cfg = _cfg(tmp_path)
    soon = (NOW + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def reader(argv):
        return _completed(
            argv,
            stdout=json.dumps({"limit": "collaborators_only", "expires_at": soon}),
        )

    plan = cov.renew_interaction_limits(
        cfg, reader=reader, writer=lambda a, b: _completed(a),
        now=NOW, dry_run=False,
    )
    assert plan["wrote"] is True and plan["readback_ok"] is False


def test_renew_whitespace_stderr_does_not_crash(tmp_path):
    cfg = _cfg(tmp_path)
    soon = (NOW + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def reader(argv):
        return _completed(
            argv,
            stdout=json.dumps({"limit": "collaborators_only", "expires_at": soon}),
        )

    def writer(argv, body):
        return _completed(argv, rc=1, stderr="\n")

    plan = cov.renew_interaction_limits(
        cfg, reader=reader, writer=writer, now=NOW, dry_run=False
    )
    assert plan["wrote"] is False and plan["readback_ok"] is False
    assert plan["detail"]


def test_renew_apply_readback_failure_is_reported(tmp_path):
    cfg = _cfg(tmp_path)
    soon = (NOW + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    reads = {"n": 0}

    def reader(argv):
        reads["n"] += 1
        payload = (
            {"limit": "collaborators_only", "expires_at": soon}
            if reads["n"] == 1
            else {"limit": "existing_users"}
        )
        return _completed(argv, stdout=json.dumps(payload))

    plan = cov.renew_interaction_limits(
        cfg, reader=reader, writer=lambda a, b: _completed(a),
        now=NOW, dry_run=False,
    )
    assert plan["wrote"] is True and plan["readback_ok"] is False


def test_notification_names_only_actionable_findings():
    findings = [
        ah.DriftFinding("a", "s", "w", "f", "ok"),
        ah.DriftFinding("b", "s", "w", "f", "drift", remediation="just harden s"),
        ah.DriftFinding("d", "s", "w", None, "error"),
        ah.DriftFinding("c", "s", "w", None, "deferred"),
    ]
    text = cov.render_notification(findings)
    assert "2 finding" in text
    assert "b s" in text and "just harden s" in text
    assert "error: d s" in text
    assert "deferred" not in text


def test_canary_passes_when_decisions_match(tmp_path):
    corpus = tmp_path / "canaries.jsonl"
    corpus.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {"id": "b1", "source": "own", "label": "benign",
                 "surface": "pr", "expected": "benign", "text": "ordinary"},
                {"id": "i1", "source": "disclosed", "label": "injection",
                 "surface": "pr", "expected": "injection", "text": "do the thing"},
            )
        )
    )
    seen = []

    def classify(text, surface):
        seen.append((text, surface))
        return {
            "status": "ok",
            "decide": "injection" if "thing" in text else "benign",
            "latency_ms": 10,
        }

    findings = cov.gate_canary(corpus, classify=classify)
    assert {f.status for f in findings} == {"ok"}
    # The report keeps ids, never payload text.
    assert all("ordinary" not in f.detail and "thing" not in f.detail for f in findings)
    assert {s[0] for s in seen} == {"ordinary", "do the thing"}


def test_canary_fails_on_wrong_decision_and_on_unavailable(tmp_path):
    corpus = tmp_path / "canaries.jsonl"
    corpus.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {"id": "b1", "source": "own", "label": "benign",
                 "surface": "pr", "expected": "benign", "text": "ordinary"},
                {"id": "i1", "source": "disclosed", "label": "injection",
                 "surface": "pr", "expected": "injection", "text": "payload"},
            )
        )
    )

    def flipped(text, surface):
        return {"status": "ok", "decide": "benign", "latency_ms": 5}

    findings = cov.gate_canary(corpus, classify=flipped)
    assert findings[0].status == "ok"
    assert findings[1].status == "drift" and findings[1].found == "benign"

    def down(text, surface):
        return {"status": "unavailable", "decide": "escalate", "latency_ms": None}

    findings = cov.gate_canary(corpus, classify=down)
    assert {f.status for f in findings} == {"drift"}


def test_canary_corpus_must_be_one_of_each(tmp_path):
    corpus = tmp_path / "canaries.jsonl"
    corpus.write_text(json.dumps(
        {"id": "b1", "source": "own", "label": "benign",
         "surface": "pr", "expected": "benign", "text": "x"}
    ))
    with pytest.raises(ah.HardenError, match="exactly two"):
        cov.load_canary_corpus(corpus)


def test_canary_corpus_rejects_bad_json_bad_surface_and_non_object(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json\n")
    with pytest.raises(ah.HardenError, match="not JSON"):
        cov.load_canary_corpus(bad)

    rows = [
        {"id": "b1", "source": "own", "label": "benign",
         "surface": "not-a-surface", "expected": "benign", "text": "x"},
        {"id": "i1", "source": "own", "label": "injection",
         "surface": "pr", "expected": "injection", "text": "y"},
    ]
    bad.write_text("\n".join(json.dumps(r) for r in rows))
    with pytest.raises(ah.HardenError, match="surface"):
        cov.load_canary_corpus(bad)

    bad.write_text("42\n")
    with pytest.raises(ah.HardenError, match="not an object"):
        cov.load_canary_corpus(bad)


def test_missing_configured_corpus_fails_the_check(tmp_path):
    cfg = _cfg(tmp_path, extra='[hardening.canaries]\ncorpus = "/nowhere/canaries.jsonl"\n')

    def runner(argv):
        return _completed(argv, rc=1, stderr="no gh\n")

    findings, rc = ah.observe(cfg, network=True, runner=runner, now=NOW)
    gate = next(f for f in findings if f.setting == "injection_gate")
    assert gate.status == "error"
    assert rc == 1


def test_observe_command_prints_the_notice(tmp_path):
    root = _cfg(tmp_path).root
    proc = subprocess.run(
        [sys.executable, "-I", "-B", str(BIN / "ade-harden"),
         "--root", str(root), "observe", "--local"],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("harden-check:")


def test_observe_wires_forgejo_and_canary(tmp_path):
    corpus = tmp_path / "canaries.jsonl"
    corpus.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {"id": "b1", "source": "own", "label": "benign",
                 "surface": "pr", "expected": "benign", "text": "ordinary"},
                {"id": "i1", "source": "disclosed", "label": "injection",
                 "surface": "pr", "expected": "injection", "text": "payload"},
            )
        )
    )
    cfg = _cfg(
        tmp_path,
        extra=(
            '[hardening.forgejo]\nbase_url = "https://forgejo.example.test"\n'
            "[hardening.canaries]\n"
            f'corpus = "{corpus}"\n'
        ),
    )

    def runner(argv):
        if "GET" in argv:
            assert "--host" in argv and "forgejo.example.test" in argv
            return _completed(
                argv,
                stdout=json.dumps({"has_wiki": False, "has_projects": False}),
            )
        return _completed(argv, rc=1, stderr="no gh in this test\n")

    def canary_runner(argv, text):
        assert argv[-2:] == ["--surface", "pr"]
        decide = "benign" if text == "ordinary" else "injection"
        return _completed(argv, stdout=json.dumps(
            {"status": "ok", "decide": decide, "latency_ms": 4}
        ))

    findings, rc = ah.observe(
        cfg, network=True, runner=runner, now=NOW, canary_runner=canary_runner,
        forgejo_api=tmp_path / "forgejo-api",
    )
    by = {(f.target, f.setting): f for f in findings}
    assert by[("forgejo:djbclark/djbclark-ade", "has_wiki")].status == "ok"
    assert by[("s5a", "canary.benign")].status == "ok"
    assert by[("s5a", "canary.injection")].status == "ok"
    # `unknown` probes do not fail the check; only drift/missing/uncovered/error do.
    assert rc == 0
