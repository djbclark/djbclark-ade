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
        assert argv[:3] == ["fj", "api", "--base"]
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
    )
    by = {f.setting: f for f in findings}
    assert by["has_wiki"].status == "drift"
    assert by["has_projects"].status == "ok"
    assert seen[0][3] == "https://forgejo.example.test"


def test_forgejo_unreachable_is_unknown_not_drift(tmp_path):
    cfg = _cfg(tmp_path)

    def runner(argv):
        return _completed(argv, rc=1, stderr="connection refused\n")

    findings = cov.observe_forgejo_repo(
        cfg, _repo_row(), runner=runner, base_url="https://forgejo.example.test"
    )
    assert len(findings) == 1
    assert findings[0].status == "unknown"


def test_forgejo_base_url_must_be_https(tmp_path):
    with pytest.raises(ah.HardenError, match="base_url"):
        _cfg(tmp_path, extra='[hardening.forgejo]\nbase_url = "http://insecure"\n')


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
        ah.DriftFinding("c", "s", "w", None, "deferred"),
    ]
    text = cov.render_notification(findings)
    assert "1 finding" in text
    assert "b s" in text and "just harden s" in text
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
        if argv[:1] == ["fj"]:
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
        cfg, network=True, runner=runner, now=NOW, canary_runner=canary_runner
    )
    by = {(f.target, f.setting): f for f in findings}
    assert by[("forgejo:djbclark/djbclark-ade", "has_wiki")].status == "ok"
    assert by[("s5a", "canary.benign")].status == "ok"
    assert by[("s5a", "canary.injection")].status == "ok"
    # `unknown` probes do not fail the check; only drift/missing/uncovered/error do.
    assert rc == 0
