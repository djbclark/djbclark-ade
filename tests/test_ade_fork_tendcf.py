"""Synthetic adapter proof, not evidence for an actual CFEngine artifact."""
import hashlib
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from ade_fork_release import digest, make_receipt
from ade_fork_tendcf import Authorities, assess


def fixture():
    payload = b"synthetic fixture"
    inputs = {"consumer_commit": "a" * 40, "core_repo": "djbclark/core",
              "core_commit": "b" * 40, "libntech_repo": "djbclark/libntech",
              "libntech_commit": "c" * 40, "libntech_gitlink_mode": "160000",
              "overlay_digest": "d" * 64, "workflow_digest": "e" * 64,
              "recipe_digest": "f" * 64, "platform": "linux-x86_64"}
    features = {"strict-json": {"disposition": "required", "evidence_ids": ["json-unit"],
                                "requirement": "Reject duplicate members and trailing input through the opt-in strict API"}}
    evidence = {"json-unit": {"scope": "full-fork", "job": "debian-13",
                              "platform": inputs["platform"], "test": "json_test"}}
    policy = {"features": features, "compatibility_group": "cfengine-libntech"}
    contract = {"schema_version": 1, "complete": True,
                "consumer_repo": "frdminc/tendcf", "core_repo": "djbclark/core",
                "libntech_repo": "djbclark/libntech", "features": features,
                "inputs": inputs, "evidence": evidence, "overlay_equivalent_to_full_fork": False}
    bindings = {"schema_version": 1, "component": "cfengine-libntech",
                "upstream_commit": "1" * 40, "fork_commit": inputs["core_commit"],
                "dependencies": {"libntech:djbclark/libntech": inputs["libntech_commit"]},
                "patch_manifest_digest": inputs["overlay_digest"], "applied_patches": [],
                "recipe_revision": inputs["consumer_commit"], "platform": inputs["platform"],
                "toolchain": "synthetic-controlled-fixture", "authority": "synthetic",
                "evaluator": "synthetic", "artifact_sha256": hashlib.sha256(payload).hexdigest(),
                "policy_digest": digest(policy), "feature_contract_digest": digest(features)}
    receipt = make_receipt(bindings, policy, {key: {"contract_digest": digest(value), "status": "passed"}
                                            for key, value in features.items()})
    proof = {"inputs": dict(inputs), "attempt": {"repository": "frdminc/tendcf",
             "run_id": 10, "run_attempt": 2, "consumer_commit": inputs["consumer_commit"]},
             "artifact_sha256": bindings["artifact_sha256"], "artifact_name": "cfengine-fork-debian13",
             "revision": inputs["consumer_commit"], "coupling_proof": "authenticated-job-receipt"}
    proof["evidence"] = {name: {"definition_digest": digest(definition), "attempt": proof["attempt"],
                        "job": definition["job"], "platform": definition["platform"],
                        "scope": definition["scope"], "status": "passed", "exit_code": 0,
                        "failed": 0, "errors": 0, "unexpected_skips": 0, "xpass": 0}
                        for name, definition in evidence.items()}
    return dict(contract=contract, bindings=bindings, policy=policy, receipt=receipt,
                proof=proof, payload=payload,
                authority=Authorities(lambda value: value == digest(contract),
                                      lambda value: value == receipt,
                                      lambda value: value == digest(proof), lambda value: True))


def test_missing_contract_is_always_hold():
    args = fixture(); args["contract"] = None
    result = assess(**args)
    assert result.holds == ("missing-full-fork-contract",)
    assert not result.eligible and not result.deployment_authorized and not result.pin_authorized


def test_independently_authenticated_synthetic_proof_can_be_eligible_only():
    result = assess(**fixture())
    assert result.eligible, result.holds
    assert not result.deployment_authorized and not result.pin_authorized


@pytest.mark.parametrize("field", ["contract", "receipt", "build_proof", "retention"])
def test_no_report_flag_replaces_each_independent_authority(field):
    args = fixture()
    callbacks = {name: getattr(args["authority"], name)
                 for name in ["contract", "receipt", "build_proof", "retention"]}
    callbacks[field] = lambda value: False
    args["authority"] = Authorities(**callbacks)
    args["proof"].update(approved=True, authenticated=True, retained=True)
    assert not assess(**args).eligible


@pytest.mark.parametrize("change", [
    lambda a: a["contract"].update(complete=False),
    lambda a: a["proof"]["inputs"].update(libntech_commit="9" * 40),
    lambda a: a["proof"]["inputs"].update(libntech_gitlink_mode="100644"),
    lambda a: a["proof"]["attempt"].update(run_attempt=0),
    lambda a: a["proof"].update(revision="wrong"),
    lambda a: a["proof"].update(coupling_proof=None),
    lambda a: a.update(payload=b"substituted"),
])
def test_incomplete_mismatched_or_substituted_evidence_holds(change):
    args = fixture(); change(args)
    assert not assess(**args).eligible


def test_default_authorities_refuse_even_a_self_consistent_report():
    args = fixture(); args.pop("authority")
    assert not assess(**args).eligible


def test_authority_transport_failure_is_a_hold():
    args = fixture()
    def unavailable(value):
        raise OSError("unavailable")
    args["authority"] = Authorities(contract=unavailable)
    assert not assess(**args).eligible


@pytest.mark.parametrize("field,value", [("exit_code", 1), ("xpass", 1),
    ("unexpected_skips", 1), ("errors", 1), ("scope", "overlay"),
    ("job", "other"), ("platform", "other"), ("status", "skipped")])
def test_green_run_or_gate_done_cannot_substitute_for_suite_proof(field, value):
    args = fixture()
    args["proof"]["evidence"]["json-unit"][field] = value
    assert "suite-not-qualified" in assess(**args).holds


def test_overlay_suite_never_proves_required_full_fork_feature():
    args = fixture()
    args["contract"]["evidence"]["json-unit"]["scope"] = "overlay"
    assert "overlay-evidence-is-not-full-fork-proof" in assess(**args).holds


@pytest.mark.parametrize("field", ["job", "platform"])
def test_missing_pair_cannot_pass_by_none_equality(field):
    args = fixture()
    args["contract"]["evidence"]["json-unit"].pop(field)
    args["proof"]["evidence"]["json-unit"].pop(field)
    args["proof"]["evidence"]["json-unit"]["definition_digest"] = digest(args["contract"]["evidence"]["json-unit"])
    assert "suite-not-qualified" in assess(**args).holds
