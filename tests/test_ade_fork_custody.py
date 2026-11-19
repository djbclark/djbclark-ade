"""Offline authoritative versioned model and real botocore parameter validation.

No actual S3, retained evidence, native/runtime qualification or cloud identity
claim follows from these tests. Network is forbidden even with dummy credentials.
"""
import base64
import copy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
from pathlib import Path
import socket
import sys
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location("ade_fork_custody", Path(__file__).resolve().parents[1] / "bin/ade_fork_custody.py")
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("offline custody suite attempted a network connection")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "offline-dummy")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "offline-dummy")
    monkeypatch.delenv("AWS_PROFILE", raising=False)


def policy(**changes):
    fields = dict(identity="synthetic-enrollment", account="123456789012", region="us-east-1",
        bucket="offline-example", prefix="custody/", writer="writer-enrolled", reader="reader-enrolled",
        policy_digest="a" * 64, contract_digest="b" * 64, max_object_bytes=10000,
        max_packet_bytes=20000, max_control_bytes=1000000, max_members=12,
        max_mutations=120, max_cycles=4, cycle_seconds=24, floor_seconds=100,
        proof_seconds=10, control_reserve_bytes=120000000, preservation_reserve_cash=121000000,
        annual_cash=200000000, lifetime_cash=300000000, byte_liability=1,
        object_liability=5, generation=1, minimum_sequence=0, maximum_horizon=100000)
    fields.update(changes)
    return m.Policy(**fields)


class Authority:
    def __init__(self, p):
        self.p, self.denied, self.revoked = p, set(), set()
    def current(self):
        return self.p
    def permits(self, purpose, closure):
        return purpose not in self.denied and closure not in self.revoked


class Model:
    """Strong per-key CAS model; exact immutable versions, legal-hold/protection state.

    Fault points distinguish no commit from commit with lost acknowledgment.
    No mock production adapter is substituted in the S3 parameter tests below.
    """
    def __init__(self, p, now):
        self.p, self.versions, self.heads = p, {}, {}
        self.counter, self.calls = 0, []
        self.fault, self.before_cas, self.on_current = None, None, None
        self._new(p.ctrl_key, m.canonical(m.genesis(p, now)), now + 10000)
    def _new(self, key, data, until):
        self.counter += 1
        ref = m.Ref(key, str(self.counter), m.digest(data), len(data))
        ob = m.Observation(ref, data, "COMPLIANCE", "ON", until, '"' + str(self.counter) + '"')
        self.versions[(key, ref.version)] = ob
        self.heads[key] = ob
        return ob
    def current(self):
        self.calls.append("current")
        if self.on_current:
            f, self.on_current = self.on_current, None
            f()
        return self.heads[self.p.ctrl_key]
    def read(self, ref):
        self.calls.append(("read", ref.key, ref.version))
        ob = self.versions[(ref.key, ref.version)]
        assert ob.ref == ref
        return ob
    def latest(self, key, cap):
        self.calls.append(("latest", key))
        if key not in self.heads:
            raise FileNotFoundError("404 is not no-commit/quiescence proof")
        return self.heads[key]
    def cas(self, previous, body, horizon):
        self.calls.append("cas")
        if self.before_cas:
            f, self.before_cas = self.before_cas, None
            f()
        if self.heads[self.p.ctrl_key].etag != previous.etag:
            raise m.Conflict("CAS loser")
        if self.fault == "cas-before":
            self.fault = None
            raise TimeoutError("unknown CAS before model commit")
        self._new(self.p.ctrl_key, body, horizon)
        if self.fault == "cas-after":
            self.fault = None
            raise TimeoutError("committed CAS lost acknowledgment")
    def put(self, key, data, horizon):
        self.calls.append("put")
        if self.fault == "put-before":
            self.fault = None
            raise TimeoutError("unknown PUT")
        if key in self.heads:
            raise m.Conflict("IfNoneMatch prevents duplicate version")
        self._new(key, data, horizon)
        if self.fault == "put-after":
            self.fault = None
            raise TimeoutError("committed PUT lost acknowledgment")
    def extend(self, ref, horizon):
        self.calls.append(("extend", ref.version))
        old = self.read(ref)
        assert horizon >= old.until
        ob = replace(old, until=horizon)
        self.versions[(ref.key, ref.version)] = ob
        if self.heads[ref.key].ref == ref:
            self.heads[ref.key] = ob
        if self.fault == "extend-after":
            self.fault = None
            raise TimeoutError("extension lost acknowledgment")
    def state(self):
        return m.decode(self.heads[self.p.ctrl_key].body)
    def corrupt_state(self, change):
        s = self.state()
        change(s)
        return self._new(self.p.ctrl_key, m.canonical(s), 100000)
    def change_observation(self, ref, **fields):
        ob = replace(self.read(ref), **fields)
        self.versions[(ref.key, ref.version)] = ob
        if self.heads[ref.key].ref == ref:
            self.heads[ref.key] = ob


@pytest.fixture
def env():
    p = policy()
    clock = [1000]
    a, st = Authority(p), Model(p, clock[0])
    c = m.Custody(a, lambda actual: st, lambda: clock[0])
    return c, a, st, clock


def packet(suffix=""):
    atom = "data" + suffix
    data = b"malformed fixture: \x00 ../../bin/sh $(never-execute)"
    descriptor = dict(atom=atom, kind="data", sha256=m.digest(data), size=len(data))
    manifest = m.canonical(dict(schema=1, data=[descriptor]))
    return [(atom, "data", data), ("manifest" + suffix, "manifest", manifest)]


def prepared(env, suffix=""):
    c, a, st, clock = env
    members = packet(suffix)
    c.reserve("ticket" + suffix, members, 5000)
    for atom, _, data in members:
        c.upload(atom, data)
        c.reconcile(atom)
    c.ready()
    return st.state()["proposal"]["closure"]


def test_import_and_unenrolled_do_not_create_client(env):
    c, a, st, clock = env
    a.p = None
    c.factory = lambda _: pytest.fail("client constructed without enrollment")
    assert c.resolve_current().candidate == "HOLD"
    with pytest.raises(m.Hold, match="unenrolled"):
        c.reserve("t", packet(), 5000)
    assert "boto3" not in m.__dict__


def test_actual_ready_verification_and_baseline_do_not_grant_runtime(env):
    c, a, st, clock = env
    prepared(env)
    assert c.resolve_current().candidate == "VERIFIED"
    proof = c.accept()
    assert proof.version != st.current().ref.version
    r = c.resolve_current()
    assert r.baseline == "ACCEPTED" and not r.runtime_qualified and not r.promotion_authority
    clock[0] += a.p.cycle_seconds + 1
    assert c.resolve_current().baseline == "ACCEPTED"  # A does not inherit P's 24h cutoff.


def test_raw_ready_and_raw_accepted_never_suffice(env):
    c, a, st, clock = env
    c.reserve("t", packet(), 5000)
    st.corrupt_state(lambda s: s["proposal"].update(phase="READY"))
    assert c.resolve_current().candidate == "HOLD"
    st.corrupt_state(lambda s: s.update(baseline=dict(s["proposal"], phase="ACCEPTED")))
    assert c.resolve_current().baseline == "HOLD"


@pytest.mark.parametrize("fault", ["put-before", "put-after"])
def test_unknown_put_keeps_full_liability_and_404_cannot_free(env, fault):
    c, a, st, clock = env
    c.reserve("t", packet(), 5000)
    before = st.state()
    st.fault = fault
    with pytest.raises(TimeoutError):
        c.upload("data", packet()[0][2])
    assert st.state() == before
    if fault == "put-before":
        with pytest.raises(FileNotFoundError):
            c.reconcile("data")
        assert st.state() == before
    else:
        c.reconcile("data")
        assert st.state()["ledger"]["data"]["ref"] is not None
        assert st.state()["lifetime"] == before["lifetime"]
    c.incident("unknown-put")
    assert st.state()["lifetime"] == before["lifetime"]


@pytest.mark.parametrize("fault", ["cas-before", "cas-after"])
def test_lost_ready_cas_and_resume_frontier(env, fault):
    c, a, st, clock = env
    c.reserve("t", packet(), 5000)
    for atom, _, data in packet():
        c.upload(atom, data)
        c.reconcile(atom)
    before = st.state()
    st.fault = fault
    with pytest.raises(TimeoutError):
        c.ready()
    current = st.state()
    assert current["lifetime"] == before["lifetime"]
    assert current["proposal"]["phase"] == ("READY" if fault == "cas-after" else "RESERVED")
    if fault == "cas-after":
        assert c.resolve_current().candidate == "VERIFIED"


def test_two_publishers_cas_loser_preserves_winner_and_liability(env):
    c, a, st, clock = env
    c.reserve("t", packet(), 5000)
    st.before_cas = lambda: st.corrupt_state(lambda s: s["incidents"].append("winner"))
    with pytest.raises(m.Conflict):
        c.incident("loser")
    assert st.state()["incidents"] == ["winner"]
    assert st.state()["proposal"]["phase"] == "RESERVED"


def test_revocation_race_denies_final_accept_without_erasing_q(env):
    c, a, st, clock = env
    closure = prepared(env)
    # Stable reread invokes revoker after _verify_record but before CAS.
    old_read = st.read
    def revoke_after_read(ref):
        out = old_read(ref)
        a.revoked.add(closure)
        return out
    st.read = revoke_after_read
    before = st.state()
    with pytest.raises(m.Hold):
        c.accept()
    assert st.state() == before
    assert c.resolve_current().candidate == "HOLD"


def test_current_changes_during_reader_is_hold(env):
    c, a, st, clock = env
    prepared(env)
    old_read = st.read
    def race(ref):
        out = old_read(ref)
        st.corrupt_state(lambda s: s["incidents"].append("concurrent"))
        return out
    st.read = race
    assert c.resolve_current().candidate == "HOLD"


@pytest.mark.parametrize("field,value", [("hold", "OFF"), ("mode", "GOVERNANCE"), ("until", 4999), ("body", b"different")])
def test_exact_version_protection_and_bytes_required(env, field, value):
    c, a, st, clock = env
    prepared(env)
    ref = m.Ref.parse(st.state()["ledger"]["data"]["ref"], a.p)
    st.change_observation(ref, **{field: value})
    assert c.resolve_current().candidate == "HOLD"
    with pytest.raises(m.Hold):
        c.accept()


def test_terminal_ctrl_itself_requires_common_horizon(env):
    c, a, st, clock = env
    prepared(env)
    st.change_observation(st.current().ref, until=2000)
    assert c.resolve_current().candidate == "HOLD"


def test_revalidate_appends_cycle_and_never_resets_original_dates_or_q(env):
    c, a, st, clock = env
    prepared(env)
    before = st.state()
    clock[0] += 25
    assert c.resolve_current().candidate == "HOLD"
    c.revalidate("cycle2")
    after = st.state()
    assert after["proposal"]["cycles"][0] == before["proposal"]["cycles"][0]
    assert after["proposal"]["cycles"][1]["t0"] == clock[0]
    assert after["lifetime"] == before["lifetime"] and after["ledger"] == before["ledger"]
    assert c.resolve_current().candidate == "VERIFIED"
    with pytest.raises(m.Hold):
        c.revalidate("cycle2")


def test_preservation_remains_available_while_intake_denied_unknown_q(env):
    c, a, st, clock = env
    c.reserve("t", packet(), 5000)
    a.denied.add("intake")
    c.incident("retained-unknown")
    c.renew_begin("r", 6000, 1050)
    assert st.state()["ledger"]["data"]["ref"] is None
    with pytest.raises(m.Hold):
        c.renew_item("r", "atom:data")
    assert not st.state()["renewals"]["r"]["done"]


def test_fixed_renewal_census_and_loss_after_extension_idempotent(env):
    c, a, st, clock = env
    prepared(env)
    c.accept()
    c.renew_begin("r", 6000, 1050)
    job = copy.deepcopy(st.state()["renewals"]["r"])
    st.fault = "extend-after"
    with pytest.raises(TimeoutError):
        c.renew_item("r", "atom:data")
    assert st.state()["renewals"]["r"]["progress"] == {}
    before = sum(isinstance(x, tuple) and x[0] == "extend" for x in st.calls)
    c.renew_item("r", "atom:data")
    assert sum(isinstance(x, tuple) and x[0] == "extend" for x in st.calls) == before
    for item in job["census"]:
        c.renew_item("r", item)
    now_job = st.state()["renewals"]["r"]
    assert (now_job["census"], now_job["root"], now_job["cutoff"], now_job["due"]) == (
        job["census"], job["root"], job["cutoff"], job["due"])
    assert len(st.state()["controls"]) > len(job["census"]) - 2
    c.renew_finish("r")
    assert st.state()["renewals"]["r"]["done"]
    assert c.resolve_current().baseline == "ACCEPTED"


def test_newborn_intake_not_moving_old_renewal_finishline(env):
    c, a, st, clock = env
    prepared(env)
    c.accept()
    c.renew_begin("r", 6000, 1050)
    original = copy.deepcopy(st.state()["renewals"]["r"])
    c.reserve("new", packet("2"), 5000)
    for item in original["census"]:
        c.renew_item("r", item)
    c.renew_finish("r")
    state = st.state()
    assert state["renewals"]["r"]["census"] == original["census"]
    assert state["ledger"]["data2"]["ref"] is None
    assert state["baseline"]["closure"] != state["proposal"]["closure"]
    assert c.resolve_current().baseline == "ACCEPTED"


def test_no_empty_forged_census_or_raw_done(env):
    c, a, st, clock = env
    prepared(env)
    c.renew_begin("r", 6000, 1050)
    def forge(s):
        j = s["renewals"]["r"]
        j.update(census={}, root=m.digest(m.canonical({})), progress={}, done=True, completed_at=1000)
    st.corrupt_state(forge)
    assert c.resolve_current().candidate == "HOLD"


def test_expired_progress_does_not_reset_due(env):
    c, a, st, clock = env
    prepared(env)
    c.renew_begin("r", 6000, 1050)
    for item in st.state()["renewals"]["r"]["census"]:
        c.renew_item("r", item)
    clock[0] += 11
    with pytest.raises(m.Hold, match="expired census"):
        c.renew_finish("r")
    assert st.state()["renewals"]["r"]["due"] == 1050
    clock[0] = 1050
    with pytest.raises(m.Hold):
        c.renew_finish("r")


@pytest.mark.parametrize("changes", [dict(max_packet_bytes=1), dict(annual_cash=121000001),
    dict(lifetime_cash=121000001), dict(max_object_bytes=1), dict(max_members=1)])
def test_caps_and_cash_stop_before_issuance(env, changes):
    c, a, st, clock = env
    a.p = policy(**changes)
    with pytest.raises(m.Hold):
        c.reserve("t", packet(), 5000)
    assert not any(x in ("cas", "put") for x in st.calls)


@pytest.mark.parametrize("changes", [dict(writer="reader-enrolled"), dict(max_cycles=True),
    dict(control_reserve_bytes=1), dict(account="../other"), dict(prefix="../"),
    dict(bucket="bad--x-s3"), dict(max_object_bytes=5000000001)])
def test_malformed_enrollment_never_constructs_store(env, changes):
    c, a, st, clock = env
    a.p = policy(**changes)
    c.factory = lambda p: pytest.fail("bad policy constructed store")
    assert c.resolve_current().candidate == "HOLD"


def test_ledger_corruption_and_rollback_floor_hold(env):
    c, a, st, clock = env
    prepared(env)
    st.corrupt_state(lambda s: s.update(lifetime=0))
    assert c.resolve_current().candidate == "HOLD"
    a.p = policy(minimum_sequence=1000)
    assert c.resolve_current().baseline == "HOLD"


def test_duplicate_control_keys_nonfinite_and_malformed_bytes():
    for data in [b'{"a":1,"a":2}', b'{"x":NaN}', b'\xff', b'{} trailing']:
        with pytest.raises(m.Hold):
            m.decode(data)


@pytest.mark.parametrize("mutation", ["mode", "hold", "until", "identity"])
def test_baseline_rechecks_current_actual_state(env, mutation):
    c, a, st, clock = env
    closure = prepared(env)
    c.accept()
    if mutation == "identity":
        a.revoked.add(closure)
    else:
        ref = m.Ref.parse(st.state()["ledger"]["data"]["ref"], a.p)
        st.change_observation(ref, **{mutation: {"mode": "GOVERNANCE", "hold": "OFF", "until": 1000}[mutation]})
    assert c.resolve_current().baseline == "HOLD"


def test_prior_baseline_survives_pending_unknown_new_proposal(env):
    c, a, st, clock = env
    old = prepared(env)
    c.accept()
    c.reserve("new", packet("2"), 5000)
    r = c.resolve_current()
    assert r.baseline == "ACCEPTED" and r.candidate == "HOLD"
    assert st.state()["baseline"]["closure"] == old


def clients(p):
    import boto3
    from botocore.config import Config
    config = Config(region_name=p.region, retries={"mode": "standard", "total_max_attempts": 1},
                    connect_timeout=1, read_timeout=1, ignore_configured_endpoint_urls=True)
    # Dummy explicit creds plus global socket guard. This code runs ONLY in CI.
    return [boto3.client("s3", region_name=p.region, aws_access_key_id="offline-dummy",
            aws_secret_access_key="offline-dummy", config=config) for _ in range(2)]


@pytest.fixture
def sdk():
    from botocore.stub import Stubber
    p = policy()
    writer, reader = clients(p)
    with Stubber(writer) as w, Stubber(reader) as r:
        store = m.S3Store(p, writer, reader, writer_identity=p.writer, reader_identity=p.reader)
        yield p, store, w, r
        w.assert_no_pending_responses()
        r.assert_no_pending_responses()
    writer.close()
    reader.close()


def request(p, key, version=None):
    out = dict(Bucket=p.bucket, Key=key, ExpectedBucketOwner=p.account)
    if version is not None:
        out["VersionId"] = version
    return out


def stub_read(r, p, ref, data, horizon=5000, latest=False, **changes):
    from botocore.response import StreamingBody
    response = dict(Body=StreamingBody(io.BytesIO(data), len(data)), ContentLength=len(data),
                    ETag='"opaque-not-sha"', VersionId=ref.version)
    response.update(changes)
    r.add_response("get_object", response, request(p, ref.key, None if latest else ref.version))
    if changes.get("ContentLength", len(data)) <= max(p.max_control_bytes, p.max_object_bytes):
        r.add_response("get_object_retention", {"Retention": {"Mode": "COMPLIANCE",
            "RetainUntilDate": datetime.fromtimestamp(horizon, timezone.utc)}}, request(p, ref.key, ref.version))
        r.add_response("get_object_legal_hold", {"LegalHold": {"Status": "ON"}}, request(p, ref.key, ref.version))
    return response["Body"]


def test_real_sdk_exact_read_version_retention_hold_and_checksum(sdk):
    p, st, w, r = sdk
    data = b"exact archive chunk"
    ref = m.Ref(p.prefix + "objects/chunk", "version-1", m.digest(data), len(data))
    body = stub_read(r, p, ref, data)
    ob = st.read(ref).protected(p, 5000, 10000)
    assert ob.ref == ref and ob.etag != ref.sha256 and body._raw_stream.closed


def test_real_sdk_current_discovery_uses_actual_version_for_protection(sdk):
    p, st, w, r = sdk
    data = b"{}"
    ref = m.Ref(p.ctrl_key, "actual-version", m.digest(data), len(data))
    stub_read(r, p, ref, data, latest=True)
    assert st.current().ref.version == "actual-version"


def test_real_sdk_put_condition_checksum_encryption_and_horizon(sdk):
    p, st, w, r = sdk
    data, horizon = b"screened", 5000
    key = p.prefix + "objects/sha/atom"
    args = dict(**request(p, key), Body=data, ContentLength=len(data),
        ChecksumSHA256=base64.b64encode(hashlib.sha256(data).digest()).decode("ascii"),
        ServerSideEncryption="AES256", StorageClass="STANDARD", ObjectLockMode="COMPLIANCE",
        ObjectLockRetainUntilDate=datetime.fromtimestamp(horizon, timezone.utc),
        ObjectLockLegalHoldStatus="ON", IfNoneMatch="*")
    w.add_response("put_object", {"VersionId": "new-version"}, args)
    st.put(key, data, horizon)
    previous = m.Observation(m.Ref(p.ctrl_key, "old", "a" * 64, 1), b"x", "COMPLIANCE", "ON", horizon, '"prior-etag"')
    args.update(Key=p.ctrl_key, IfMatch=previous.etag)
    del args["IfNoneMatch"]
    w.add_response("put_object", {"VersionId": "new-ctrl"}, args)
    st.cas(previous, data, horizon)


def test_real_sdk_renew_exact_version_without_governance_bypass(sdk):
    p, st, w, r = sdk
    data = b"chunk"
    ref = m.Ref(p.prefix + "objects/chunk", "v1", m.digest(data), len(data))
    stub_read(r, p, ref, data)
    w.add_response("put_object_retention", {}, dict(**request(p, ref.key, ref.version),
        Retention=dict(Mode="COMPLIANCE", RetainUntilDate=datetime.fromtimestamp(6000, timezone.utc))))
    st.extend(ref, 6000)


def test_real_sdk_412_and_404_propagate_no_retry_or_refund(sdk):
    from botocore.exceptions import ClientError
    p, st, w, r = sdk
    key = p.prefix + "objects/chunk"
    r.add_client_error("get_object", "NoSuchKey", http_status_code=404, expected_params=request(p, key))
    with pytest.raises(ClientError):
        st.latest(key, 10000)
    w.add_client_error("put_object", "PreconditionFailed", http_status_code=412)
    with pytest.raises(ClientError):
        st.put(key, b"x", 5000)


def test_real_sdk_oversize_closes_body_before_retention_calls(sdk):
    from botocore.response import StreamingBody
    p, st, w, r = sdk
    body = StreamingBody(io.BytesIO(b"oversize"), 8)
    r.add_response("get_object", dict(Body=body, ContentLength=p.max_control_bytes + 1,
        VersionId="v", ETag='"e"'), request(p, p.ctrl_key))
    with pytest.raises(m.Hold, match="bounded transport"):
        st.current()
    assert body._raw_stream.closed


def test_real_sdk_client_binding_and_no_hidden_retry_requirements():
    p = policy()
    writer, reader = clients(p)
    with pytest.raises(m.Hold):
        m.S3Store(p, writer, writer, writer_identity=p.writer, reader_identity=p.reader)
    with pytest.raises(m.Hold):
        m.S3Store(p, writer, reader, writer_identity="untrusted", reader_identity=p.reader)
    writer.close()
    reader.close()


def test_unquoted_unbounded_retention_term_cannot_spend_finite_grant(env):
    c, a, st, clock = env
    with pytest.raises(m.Hold, match="term ceiling"):
        c.reserve("t", packet(), a.p.maximum_horizon + 1)
    assert st.state()["ledger"] == {}


def test_authorized_preservation_can_repair_expired_compliance_with_hold_on(env):
    c, a, st, clock = env
    prepared(env)
    # Existing locked bytes and legal hold remain; intake cannot treat expired date as proof.
    old = st.current().ref
    st.change_observation(old, until=999)
    assert c.resolve_current().candidate == "HOLD"
    c.incident("expired-protection")
    assert st.state()["incidents"] == ["expired-protection"]
    assert st.current().until >= clock[0] + a.p.floor_seconds


def test_actual_term_beyond_enrolled_quote_stays_hold_with_liability(env):
    c, a, st, clock = env
    prepared(env)
    before = st.state()["lifetime"]
    ref = m.Ref.parse(st.state()["ledger"]["data"]["ref"], a.p)
    st.change_observation(ref, until=a.p.maximum_horizon + 1)
    assert c.resolve_current().candidate == "HOLD"
    assert st.state()["lifetime"] == before
