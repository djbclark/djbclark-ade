"""Owner-reviewed tendcf eligibility checks; no pin, archive or deployment writes.

Authority callbacks are protected in-process adapters, never flags deserialized
from a build report. All default to refusal. Current owner contract is missing.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable

from ade_fork_release import ContractError, Receipt, canonical, digest, validate


@dataclass(frozen=True)
class Authorities:
    contract: Callable[[str], bool] = lambda identity: False
    receipt: Callable[[Receipt], bool] = lambda receipt: False
    build_proof: Callable[[str], bool] = lambda identity: False
    retention: Callable[[str], bool] = lambda artifact_digest: False


@dataclass(frozen=True)
class Eligibility:
    eligible: bool
    holds: tuple[str, ...]
    deployment_authorized: bool = False
    pin_authorized: bool = False


def assess(*, contract: dict | None, bindings: dict, policy: dict,
           receipt: Receipt | None, proof: dict | None,
           payload: bytes | None, authority: Authorities | None = None) -> Eligibility:
    """Check independently authenticated facts against protected expectations.

    No subprocesses, filesystem access or callbacks that mutate state belong
    here. An approved contract is not evidence that a particular build passed.
    """
    authority = authority or Authorities()
    holds = []
    def hold(reason):
        if reason not in holds:
            holds.append(reason)

    def authorized(callback, value):
        try:
            return callback(value) is True
        except Exception:
            return False

    if not isinstance(contract, dict):
        return Eligibility(False, ("missing-full-fork-contract",))
    try:
        canonical(contract)
        approved = authorized(authority.contract, digest(contract))
        if (contract.get("schema_version") != 1
                or type(contract.get("schema_version")) is not int
                or contract.get("complete") is not True
                or not approved):
            hold("missing-full-fork-contract")
        if contract.get("consumer_repo") != "frdminc/tendcf":
            hold("consumer-identity-mismatch")
        features = contract.get("features")
        if not isinstance(features, dict) or not features:
            hold("missing-full-fork-contract")
            features = {}
        for feature, definition in features.items():
            if (not isinstance(feature, str) or not isinstance(definition, dict)
                    or definition.get("disposition") not in {"required", "retired-patch", "platform-inapplicable"}
                    or not isinstance(definition.get("requirement"), str)
                    or not definition["requirement"]
                    or not isinstance(definition.get("evidence_ids"), list)
                    or not definition["evidence_ids"]):
                hold("incomplete-feature-disposition")
        if contract.get("overlay_equivalent_to_full_fork") is not False:
            hold("overlay-full-fork-conflation")
        if (not isinstance(policy, dict)
                or policy.get("features") != features
                or policy.get("compatibility_group") != "cfengine-libntech"):
            hold("feature-policy-mismatch")
        if (receipt is None or payload is None
                or not authorized(authority.receipt, receipt)):
            hold("unauthenticated-build-receipt")
        else:
            try:
                validate(receipt, bindings, policy, artifact=payload)
            except ContractError:
                hold("release-receipt-mismatch")
        if not isinstance(proof, dict):
            hold("missing-coupled-build-evidence")
            return Eligibility(False, tuple(holds))
        canonical(proof)
        # Digest binds the COMPLETE proof, including suite results and attempts.
        if not authorized(authority.build_proof, digest(proof)):
            hold("unauthenticated-coupled-build-evidence")
        expected = contract.get("inputs")
        if not isinstance(expected, dict) or not expected:
            hold("missing-coupled-input-expectations")
            expected = {}
        measured = proof.get("inputs")
        if not isinstance(measured, dict) or measured != expected:
            hold("coupled-input-mismatch")
        keys = {"consumer_commit", "core_repo", "core_commit", "libntech_repo",
                "libntech_commit", "libntech_gitlink_mode", "overlay_digest",
                "workflow_digest", "recipe_digest", "platform"}
        if set(expected) != keys or expected.get("libntech_gitlink_mode") != "160000":
            hold("missing-exact-coupled-inputs")
        for key in ("consumer_commit", "core_commit", "libntech_commit"):
            if not isinstance(expected.get(key), str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", expected[key]):
                hold("missing-exact-coupled-inputs")
        for key in ("overlay_digest", "workflow_digest", "recipe_digest"):
            if not isinstance(expected.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", expected[key]):
                hold("missing-exact-coupled-inputs")
        # The recipe consumes the gitlink from THIS core tree, not .gitmodules
        # provenance or a separately advanced libntech integration branch.
        if (bindings.get("fork_commit") != expected.get("core_commit")
                or bindings.get("recipe_revision") != expected.get("consumer_commit")
                or bindings.get("patch_manifest_digest") != expected.get("overlay_digest")
                or bindings.get("platform") != expected.get("platform")
                or bindings.get("dependencies") != {
                    "libntech:" + str(expected.get("libntech_repo")): expected.get("libntech_commit")}
                or expected.get("core_repo") != contract.get("core_repo")
                or expected.get("libntech_repo") != contract.get("libntech_repo")):
            hold("receipt-coupling-mismatch")
        attempt = proof.get("attempt")
        if (not isinstance(attempt, dict)
                or set(attempt) != {"repository", "run_id", "run_attempt", "consumer_commit"}
                or attempt.get("repository") != contract.get("consumer_repo")
                or attempt.get("consumer_commit") != expected.get("consumer_commit")
                or type(attempt.get("run_id")) is not int or attempt["run_id"] <= 0
                or type(attempt.get("run_attempt")) is not int or attempt["run_attempt"] <= 0):
            hold("invalid-attempt-provenance")
        suites = contract.get("evidence")
        observed = proof.get("evidence")
        if not isinstance(suites, dict) or not suites or not isinstance(observed, dict):
            hold("missing-suite-evidence")
            suites, observed = {}, {}
        if set(observed) != set(suites):
            hold("suite-evidence-mismatch")
        for definition in features.values():
            if not isinstance(definition, dict):
                continue
            ids = definition.get("evidence_ids", [])
            if not isinstance(ids, list) or any(not isinstance(i, str) or i not in suites for i in ids):
                hold("feature-evidence-unmapped")
        for name, suite in suites.items():
            result = observed.get(name)
            if (not isinstance(suite, dict) or not isinstance(result, dict)
                    or not isinstance(suite.get("job"), str) or not suite["job"]
                    or not isinstance(suite.get("platform"), str) or not suite["platform"]
                    or suite.get("scope") not in {"full-fork", "overlay", "static", "platform-inapplicable"}
                    or result.get("definition_digest") != digest(suite)
                    or result.get("attempt") != attempt
                    or result.get("job") != suite.get("job")
                    or result.get("platform") != suite.get("platform")
                    or result.get("scope") != suite.get("scope")
                    or result.get("status") != "passed"
                    or type(result.get("exit_code")) is not int or result["exit_code"] != 0
                    or any(type(result.get(k)) is not int or result[k] != 0
                           for k in ("failed", "errors", "unexpected_skips", "xpass"))):
                hold("suite-not-qualified")
        # Full-fork feature evidence must actually be from that coupled tree.
        for definition in features.values():
            if isinstance(definition, dict) and definition.get("disposition") == "required":
                ids = definition.get("evidence_ids", [])
                if (not isinstance(ids, list) or not ids
                        or any(not isinstance(i, str) or suites.get(i, {}).get("scope") != "full-fork" for i in ids)):
                    hold("overlay-evidence-is-not-full-fork-proof")
        if (proof.get("artifact_sha256") != bindings.get("artifact_sha256")
                or proof.get("artifact_name") != "cfengine-fork-debian13"
                or proof.get("revision") != expected.get("consumer_commit")
                or proof.get("coupling_proof") not in {"embedded-receipt", "authenticated-job-receipt"}):
            hold("artifact-coupled-receipt-missing-or-mismatched")
        if not authorized(authority.retention, str(bindings.get("artifact_sha256"))):
            hold("permanent-retention-not-approved-or-proven")
        return Eligibility(not holds, tuple(holds))
    except (ContractError, TypeError, ValueError, KeyError, AttributeError):
        return Eligibility(False, ("malformed-contract-or-evidence",))
