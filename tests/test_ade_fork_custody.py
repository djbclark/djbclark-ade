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
        object_liability=5, generation=1, minimum_sequence=0, maximum_horizon=100000, transport_seconds=5)
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


def test_lost_accept_ack_requires_independent_terminal_read(env):
    c, a, st, clock = env
    prepared(env)
    st.fault = "cas-after"
    with pytest.raises(TimeoutError):
        c.accept()
    assert c.resolve_current().baseline == "ACCEPTED"
    st.change_observation(st.current().ref, hold="OFF")
    assert c.resolve_current().baseline == "HOLD"


def test_screening_revocation_holds_after_upload(env):
    c, a, st, clock = env
    prepared(env)
    a.denied.add("screened")
    assert c.resolve_current().candidate == "HOLD"
    with pytest.raises(m.Hold):
        c.accept()


@pytest.mark.parametrize("field", ["schema", "generation"])
def test_bool_is_not_control_integer_schema(env, field):
    c, a, st, clock = env
    prepared(env)
    st.corrupt_state(lambda s: s.update({field: True}))
    assert c.resolve_current().candidate == "HOLD"


def test_control_pool_stop_keeps_existing_ledger(env):
    c, a, st, clock = env
    c.reserve("t", packet(), 5000)
    st.corrupt_state(lambda s: s.update(mutations=a.p.max_mutations))
    before = st.state()
    with pytest.raises(m.Hold, match="pool exhausted"):
        c.incident("over-pool")
    assert st.state() == before


def test_real_sdk_slow_stream_deadline_closes_body(sdk, monkeypatch):
    from botocore.response import StreamingBody
    p, st, w, reader = sdk
    body = StreamingBody(io.BytesIO(b"x"), 1)
    reader.add_response("get_object", dict(Body=body, ContentLength=1, VersionId="v", ETag='"e"'),
                        request(p, p.ctrl_key))
    times = iter([0.0, 6.0])
    monkeypatch.setattr(m.time, "monotonic", lambda: next(times))
    with pytest.raises(m.Hold, match="transport deadline"):
        st.current()
    assert body._raw_stream.closed


def test_revocation_during_final_current_read_prevents_accept(env):
    c, a, st, clock = env
    closure = prepared(env)
    before = st.state()
    old, count = st.current, [0]
    def race():
        result = old()
        count[0] += 1
        if count[0] == 3:
            a.revoked.add(closure)
        return result
    st.current = race
    with pytest.raises(m.Hold, match="revocation"):
        c.accept()
    assert st.state() == before


def test_slow_verification_cannot_backdate_cycle_or_floor(env):
    c, a, st, clock = env
    prepared(env)
    old = st.read
    def slow(ref):
        result = old(ref)
        clock[0] += 25
        return result
    st.read = slow
    assert c.resolve_current().candidate == "HOLD"
    before = st.state()
    with pytest.raises(m.Hold):
        c.accept()
    assert st.state() == before


def test_reader_closure_revocation_during_final_current_read_holds(env):
    c, a, st, clock = env
    closure = prepared(env)
    old, count = st.current, [0]
    def race():
        result = old()
        count[0] += 1
        if count[0] == 3:
            a.revoked.add(closure)
        return result
    st.current = race
    assert c.resolve_current().candidate == "HOLD"


def test_real_sdk_custom_endpoint_and_unbounded_timeout_refused():
    import boto3
    from botocore.config import Config
    p = policy()
    writer, reader = clients(p)
    custom = boto3.client("s3", region_name=p.region, aws_access_key_id="offline-dummy",
        aws_secret_access_key="offline-dummy", endpoint_url="https://candidate.invalid",
        config=Config(retries={"total_max_attempts": 1}, connect_timeout=1, read_timeout=1))
    with pytest.raises(m.Hold, match="endpoint"):
        m.S3Store(p, writer, custom, writer_identity=p.writer, reader_identity=p.reader)
    custom.close()
    slow = boto3.client("s3", region_name=p.region, aws_access_key_id="offline-dummy",
        aws_secret_access_key="offline-dummy", config=Config(retries={"total_max_attempts": 1},
            connect_timeout=60, read_timeout=60, ignore_configured_endpoint_urls=True))
    with pytest.raises(m.Hold, match="timeout"):
        m.S3Store(p, writer, slow, writer_identity=p.writer, reader_identity=p.reader)
    slow.close()
    writer.close()
    reader.close()


# Exact366d adversary repairs: independent mutable purposes, fresh renewal time,
# and historical dependencies versus current anti-rollback authority.
def read_phase(store, phase, change):
    original, calls = store.current, [0]
    def current():
        result = original()
        calls[0] += 1
        if calls[0] == phase:
            change()
        return result
    store.current = current
    return calls


def staged_operation(env, operation):
    c, a, st, clock = env
    if operation == "reserve":
        members = packet()
        closure = m.closure_id([dict(atom=atom, kind=kind, sha256=m.digest(body), size=len(body))
                               for atom, kind, body in members])
        return closure, lambda: c.reserve("t", members, 5000)
    if operation == "upload":
        c.reserve("t", packet(), 5000)
        return st.state()["proposal"]["closure"], lambda: c.upload("data", packet()[0][2])
    if operation == "ready":
        c.reserve("t", packet(), 5000)
        for atom, _, data in packet():
            c.upload(atom, data)
            c.reconcile(atom)
        return st.state()["proposal"]["closure"], c.ready
    closure = prepared(env)
    if operation == "revalidate":
        clock[0] += 25
        return closure, lambda: c.revalidate("new-cycle")
    assert operation == "accept"
    return closure, c.accept


@pytest.mark.parametrize("operation,phase", [("reserve", 2), ("upload", 2), ("ready", 2),
    ("accept", 3), ("accept", 4), ("revalidate", 2)])
def test_screened_only_revocation_at_exact_final_read_no_new_write(env, operation, phase):
    c, a, st, clock = env
    closure, perform = staged_operation(env, operation)
    # Only this closure's SCREENED purpose changes. Ordinary write authority and
    # Policy stay valid, unlike the older whole-closure revocation regression.
    allowed = a.permits
    revoked = [False]
    a.permits = lambda purpose, target: allowed(purpose, target) and not (
        revoked[0] and purpose == "screened" and target == closure)
    before, version = st.state(), st.current().ref
    puts, cases = st.calls.count("put"), st.calls.count("cas")
    reads = read_phase(st, phase, lambda: revoked.__setitem__(0, True))
    with pytest.raises(m.Hold, match="screening"):
        perform()
    assert reads[0] == phase and a.current() == policy()
    assert a.permits("upload", closure) and a.permits("accept", closure)
    assert st.calls.count("put") == puts and st.calls.count("cas") == cases
    assert st.state() == before and st.current().ref == version


def test_unrelated_screening_revocation_does_not_block_exact_authorized_packet(env):
    c, a, st, clock = env
    closure, perform = staged_operation(env, "upload")
    allowed = a.permits
    revoked = [False]
    a.permits = lambda purpose, target: allowed(purpose, target) and not (
        revoked[0] and purpose == "screened" and target == "c" * 64)
    read_phase(st, 2, lambda: revoked.__setitem__(0, True))
    puts = st.calls.count("put")
    perform()
    assert st.calls.count("put") == puts + 1 and a.permits("screened", closure)


@pytest.mark.parametrize("operation", ["reserve", "upload", "ready"])
def test_cycle_expires_during_final_read_without_new_write(env, operation):
    c, a, st, clock = env
    _, perform = staged_operation(env, operation)
    before = st.state()
    puts, cases = st.calls.count("put"), st.calls.count("cas")
    read_phase(st, 2, lambda: clock.__setitem__(0, clock[0] + 25))
    with pytest.raises(m.Hold, match="cycle expired"):
        perform()
    assert st.state() == before
    assert st.calls.count("put") == puts and st.calls.count("cas") == cases


def progressed_renewal(env, at=1000, target=6000):
    c, a, st, clock = env
    prepared(env)
    c.accept()
    c.renew_begin("r", target, 1050)
    clock[0] = at
    for item in st.state()["renewals"]["r"]["census"]:
        c.renew_item("r", item)
    return copy.deepcopy(st.state()["renewals"]["r"])


@pytest.mark.parametrize("phase", ["member", "final-current", "commit"])
@pytest.mark.parametrize("boundary", ["due", "progress-age", "floor", "backward"])
def test_renew_finish_resamples_all_temporal_predicates_no_progress_or_q_loss(env, monkeypatch, phase, boundary):
    c, a, st, clock = env
    start, late, target = {
        "due": (1049, 1051, 6000),
        "progress-age": (1000, 1011, 6000),
        "floor": (1009, 1011, 1110),
        "backward": (1000, 999, 6000),
    }[boundary]
    progressed_renewal(env, start, target)
    before, version = st.state(), st.current().ref
    cases = st.calls.count("cas")
    if phase == "member":
        original, reads = st.read, [0]
        def read(ref):
            result = original(ref)
            reads[0] += 1
            if reads[0] == 2:  # fixed source first, then a genuine census member
                clock[0] = late
            return result
        st.read = read
    elif phase == "final-current":
        read_phase(st, 2, lambda: clock.__setitem__(0, late))
    else:
        original = m.canonical
        def serialize(value):
            result = original(value)
            if type(value) is dict and value.get("renewals", {}).get("r", {}).get("done") is True:
                clock[0] = late
            return result
        monkeypatch.setattr(m, "canonical", serialize)
    with pytest.raises(m.Hold):
        c.renew_finish("r")
    assert st.state() == before and st.current().ref == version
    assert st.calls.count("cas") == cases
    assert not st.state()["renewals"]["r"]["done"]
    assert st.state()["renewals"]["r"]["due"] == 1050


@pytest.mark.parametrize("phase", ["member", "final-current"])
def test_timely_renewal_records_actual_post_transport_completion(env, phase):
    c, a, st, clock = env
    original_job = progressed_renewal(env)
    if phase == "member":
        original, reads = st.read, [0]
        def read(ref):
            result = original(ref)
            reads[0] += 1
            if reads[0] == 2:
                clock[0] = 1001
            return result
        st.read = read
    else:
        read_phase(st, 2, lambda: clock.__setitem__(0, 1001))
    c.renew_finish("r")
    job = st.state()["renewals"]["r"]
    assert job["done"] and job["completed_at"] == 1001
    assert (job["root"], job["cutoff"], job["due"], job["progress"]) == (
        original_job["root"], original_job["cutoff"], original_job["due"], original_job["progress"])
    assert c.resolve_current().baseline == "ACCEPTED"


def test_advanced_current_floor_preserves_exact_historical_ready_origin(env):
    c, a, st, clock = env
    prepared(env)
    c.accept()
    before = st.state()
    origin = m.Ref.parse(before["baseline"]["origin"]["frontier"], a.p)
    assert m.decode(st.read(origin).body)["sequence"] < before["sequence"]
    a.p = replace(a.p, minimum_sequence=before["sequence"])
    assert c.resolve_current().baseline == "ACCEPTED"
    assert st.state() == before
    # The same historical object is still NOT an acceptable CURRENT frontier.
    st.heads[a.p.ctrl_key] = st.read(origin)
    assert c.resolve_current().baseline == "HOLD"
    with pytest.raises(m.Hold, match="current rollback floor"):
        c.incident("stale-current")


def test_advanced_current_floor_allows_existing_fixed_census_completion(env):
    c, a, st, clock = env
    prepared(env)
    c.accept()
    c.renew_begin("r", 6000, 1050)
    before = copy.deepcopy(st.state()["renewals"]["r"])
    a.p = replace(a.p, minimum_sequence=st.state()["sequence"])
    assert before["cutoff"] < a.p.minimum_sequence
    for item in before["census"]:
        c.renew_item("r", item)
    c.renew_finish("r")
    job = st.state()["renewals"]["r"]
    assert job["done"] and (job["source"], job["root"], job["cutoff"]) == (
        before["source"], before["root"], before["cutoff"])
    assert c.resolve_current().baseline == "ACCEPTED"


@pytest.mark.parametrize("historical", ["origin", "census"])
@pytest.mark.parametrize("field,value", [("identity", "wrong-enrollment"), ("generation", 2),
    ("contract", "e" * 64), ("policy", "f" * 64)])
def test_floor_exception_keeps_historical_enrollment_generation_and_contract_strict(env, historical, field, value):
    c, a, st, clock = env
    prepared(env)
    c.accept()
    if historical == "census":
        c.renew_begin("r", 6000, 1050)
    state = st.state()
    pinned = state["baseline"]["origin"]["frontier"] if historical == "origin" else state["renewals"]["r"]["source"]
    prior = m.decode(st.read(m.Ref.parse(pinned, a.p)).body)
    prior[field] = value
    # Create independently exact/protected bytes; shape/binding must still reject.
    wrong = st._new(a.p.ctrl_key, m.canonical(prior), 10000).ref.wire()
    if historical == "origin":
        state["baseline"]["origin"]["frontier"] = wrong
    else:
        state["renewals"]["r"]["source"] = wrong
    st._new(a.p.ctrl_key, m.canonical(state), 10000)
    a.p = replace(a.p, minimum_sequence=state["sequence"])
    if historical == "origin":
        assert c.resolve_current().baseline == "HOLD"
    else:
        with pytest.raises(m.Hold, match="enrollment binding"):
            c.renew_finish("r")


def test_floor_exception_never_substitutes_wrong_exact_history_bytes(env):
    c, a, st, clock = env
    progressed_renewal(env)
    a.p = replace(a.p, minimum_sequence=st.state()["sequence"])
    source = m.Ref.parse(st.state()["renewals"]["r"]["source"], a.p)
    st.change_observation(source, body=b"different bytes")
    before = st.state()
    with pytest.raises(m.Hold, match="exact bytes"):
        c.renew_finish("r")
    assert st.state() == before


# Stage3 integration: synthetic protected enrollment and authoritative offline
# API model. Actual STS/S3 SDK Stubber parameter tests are separate below.
import os


class ModelSDK:
    def __init__(self, service, role, factory):
        self.service, self.role, self.f = service, role, factory
        self.meta = SimpleNamespace(region_name=factory.p.region,
            endpoint_url="https://" + service + "." + factory.p.region + ".amazonaws.com",
            config=SimpleNamespace(retries={"total_max_attempts": 1}, connect_timeout=1, read_timeout=1))
        self.closed = False
    def close(self):
        self.closed = True
    def get_caller_identity(self):
        self.f.wires.append((self.role, "get_caller_identity"))
        if self.role in self.f.identities:
            return self.f.identities[self.role]
        expected = self.f.anchor.data["principals"][self.role]
        session = expected["sessions"][0]
        return dict(Account=self.f.p.account, UserId=expected["unique_id"] + ":" + session,
            Arn="arn:aws:sts::" + self.f.p.account + ":assumed-role/" + self.role + "/" + session)
    def _ob(self, args):
        assert args["Bucket"] == self.f.p.bucket and args["ExpectedBucketOwner"] == self.f.p.account
        if "VersionId" in args:
            return self.f.model.versions[(args["Key"], args["VersionId"])]
        return self.f.model.heads[args["Key"]]
    def get_object(self, **args):
        from botocore.response import StreamingBody
        self.f.wires.append((self.role, "get_object"))
        ob = self._ob(args)
        return dict(Body=StreamingBody(io.BytesIO(ob.body), len(ob.body)), ContentLength=len(ob.body),
                    VersionId=ob.ref.version, ETag=ob.etag)
    def get_object_retention(self, **args):
        self.f.wires.append((self.role, "get_object_retention"))
        ob = self._ob(args)
        return dict(Retention=dict(Mode=ob.mode, RetainUntilDate=datetime.fromtimestamp(ob.until, timezone.utc)))
    def get_object_legal_hold(self, **args):
        self.f.wires.append((self.role, "get_object_legal_hold"))
        return dict(LegalHold=dict(Status=self._ob(args).hold))
    def put_object(self, **args):
        self.f.wires.append((self.role, "put_object"))
        assert args["ChecksumSHA256"] == base64.b64encode(hashlib.sha256(args["Body"]).digest()).decode()
        assert args["ObjectLockMode"] == "COMPLIANCE" and args["ObjectLockLegalHoldStatus"] == "ON"
        until = int(args["ObjectLockRetainUntilDate"].timestamp())
        if args["Key"] == self.f.p.ctrl_key:
            previous = self.f.model.heads[args["Key"]]
            assert args["IfMatch"] == previous.etag
            self.f.model.cas(previous, args["Body"], until)
        else:
            assert args["IfNoneMatch"] == "*"
            self.f.model.put(args["Key"], args["Body"], until)
        return dict(VersionId=self.f.model.heads[args["Key"]].ref.version)
    def put_object_retention(self, **args):
        self.f.wires.append((self.role, "put_object_retention"))
        ob = self._ob(args)
        self.f.model.extend(ob.ref, int(args["Retention"]["RetainUntilDate"].timestamp()))
        return {}


class ModelFactory:
    def __init__(self, anchor, model):
        self.anchor, self.p, self.model = anchor, anchor.policy, model
        self.created, self.wires, self.identities = [], [], {}
    def __call__(self, service, bundle, policy):
        assert policy == self.p
        role = "reader" if bundle.access_key == "dummy-reader" else "writer"
        obj = ModelSDK(service, role, self)
        self.created.append((service, role, bundle, obj))
        return obj


def integration_fixture(tmp_path, *, schema2=True, change=None, baseline=False):
    tmp_path.chmod(0o700)
    p = policy(annual_cash=1_000_000_000_000, lifetime_cash=2_000_000_000_000)
    model, clock = Model(p, 1000), [1000]
    old_closure = None
    if baseline:
        old_authority = Authority(p)
        old_custody = m.Custody(old_authority, lambda _: model, lambda: clock[0])
        old_closure = prepared((old_custody, old_authority, model, clock))
        old_custody.accept()
    methods = sorted(m.RPC_METHODS)
    purposes = ["identity", "discover", "read", "intake", "upload", "accept", "baseline", "revalidate",
                "preserve", "screened", "migrate", "fund-wallet", "refence"]
    seeds = {}
    for role in ("reader", "writer"):
        seeds["seed-" + role] = dict(parent=None, executor="executor-one", principal=role, fence=1,
            expires=8000, attempts=512, response_bytes=p.max_control_bytes,
            charge=512 * (1 + p.max_control_bytes), year=1970, methods=methods, purposes=purposes)
    inode = tmp_path.stat()
    template = dict(fence=1, expires=8000, floor=0, revoked=[], screened={}, wallets=seeds)
    if old_closure:
        template["screened"][old_closure] = dict(policy="c" * 64, expires=7000)
    d = dict(schema=1, expires=9000, policy={name: getattr(p, name) for name in p.__dataclass_fields__},
        principals={role: dict(kind="role", arn="arn:aws:iam::" + p.account + ":role/" + role,
            unique_id="stable-" + role, sessions=["session-" + role]) for role in ("reader", "writer")},
        grants={purpose: ["*"] for purpose in purposes}, screening="c" * 64,
        executors={"executor-one": dict(owner=os.getuid(), journal=dict(path=str(tmp_path / "attempts.json"),
            id="journal-one", max_bytes=2000000, device=inode.st_dev, inode=inode.st_ino))},
        rpc=dict(max_wallets=8, max_attempts=2048, max_response_bytes=p.max_control_bytes,
            request_quote=1, byte_quote=1, max_cash=100_000_000_000), seeds=seeds,
        migration=dict(source=model.current().ref.wire(), authority_digest=m.digest(m.canonical(template))))
    if change:
        change(d, template)
    path = tmp_path / "enrollment.json"
    raw = m.canonical(d)
    path.write_bytes(raw)
    path.chmod(0o600)
    anchor = m.Enrollment.load(path, expected_digest=m.digest(raw), expected_owner=os.getuid(),
                               expected_executor="executor-one")
    journal_path = Path(anchor.journal["path"])
    journal_path.write_bytes(m.journal_genesis(anchor))
    journal_path.chmod(0o600)
    journal = m.AttemptJournal(anchor)
    if schema2:
        body = m.prepare_schema2(anchor, model.current(), template)
        model._new(p.ctrl_key, body, 7000)
    factory = ModelFactory(anchor, model)
    bundles = {role: m.CredentialBundle("dummy-" + role, "dummy-secret", "dummy-session", 7500)
               for role in ("reader", "writer")}
    return SimpleNamespace(anchor=anchor, journal=journal, template=template, model=model,
        clock=clock, factory=factory, bundles=bundles)


def runtime(e):
    return m.CustodyRuntime(e.anchor, e.journal, lambda: e.clock[0],
        dict(reader="seed-reader", writer="seed-writer"), e.bundles, client_factory=e.factory)


def external_authority_update(e, runtime, change):
    # A synthetic protected authority publishes a new actual version, then its
    # authenticated observation is delivered to the authority port.
    s = e.model.state()
    change(s["integration"])
    s["sequence"] += 1
    s["mutations"] += 1
    e.model._new(e.anchor.policy.ctrl_key, m.canonical(s), 7000)
    runtime.authority.ingest(e.model.current())


def integrated_packet(e, r):
    packet_data = packet()
    closure = m.closure_id([dict(atom=a, kind=k, sha256=m.digest(b), size=len(b)) for a, k, b in packet_data])
    external_authority_update(e, r, lambda h: h["screened"].update({closure: dict(policy=e.anchor.data["screening"], expires=7000)}))
    return closure, packet_data


def test_stage3_main_and_unselected_anchor_have_zero_clients(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "boto_client", lambda *a: pytest.fail("SDK before enrollment"))
    assert m.main() == 2
    with pytest.raises(m.Hold):
        m.Enrollment.load(tmp_path / "missing", expected_digest=None,
                          expected_owner=os.getuid(), expected_executor="executor-one")


@pytest.mark.parametrize("bad", ["digest", "owner", "executor", "mode", "symlink", "policy-field", "same-role"])
def test_anchor_refuses_exact_protection_mismatch_before_client(tmp_path, bad):
    if bad in {"policy-field", "same-role"}:
        def change(d, template):
            if bad == "policy-field":
                del d["policy"]["annual_cash"]
            else:
                d["principals"]["writer"]["unique_id"] = d["principals"]["reader"]["unique_id"]
        with pytest.raises(m.Hold):
            integration_fixture(tmp_path, change=change)
        return
    e = integration_fixture(tmp_path)
    path, expected, owner, executor = Path(e.anchor.path), e.anchor.sha256, os.getuid(), e.anchor.executor
    if bad == "digest":
        expected = "0" * 64
    elif bad == "owner":
        owner += 1
    elif bad == "executor":
        executor = "other-executor"
    elif bad == "mode":
        path.chmod(0o644)
    else:
        alias = tmp_path / "alias"
        alias.symlink_to(path)
        path = alias
    with pytest.raises((m.Hold, OSError)):
        m.Enrollment.load(path, expected_digest=expected, expected_owner=owner, expected_executor=executor)
    assert e.factory.created == []


@pytest.mark.parametrize("field,value", [("Account", "999999999999"), ("UserId", "same-name-recreated:session-reader"),
    ("Arn", "arn:aws:sts::123456789012:assumed-role/other/session-reader")])
def test_actual_identity_mismatch_burns_attempt_no_s3_client(tmp_path, field, value):
    e = integration_fixture(tmp_path)
    correct = dict(Account=e.anchor.policy.account, UserId="stable-reader:session-reader",
        Arn="arn:aws:sts::123456789012:assumed-role/reader/session-reader")
    correct[field] = value
    e.factory.identities["reader"] = correct
    with pytest.raises(m.Hold, match="mismatch"):
        runtime(e)
    assert [x[0] for x in e.factory.created] == ["sts"]
    d = e.journal._read()
    assert len(d["attempts"]["seed-reader"]) == 1
    assert d["wallets"] == e.anchor.data["seeds"]


def test_missing_expired_exhausted_or_wrong_executor_wallet_zero_client(tmp_path):
    e = integration_fixture(tmp_path)
    w = e.anchor.data["seeds"]["seed-reader"]
    for i in range(w["attempts"]):
        e.journal.claim("seed-reader", w, "d" * 64)
    with pytest.raises(m.Hold, match="exhausted"):
        runtime(e)
    assert not e.factory.created and not e.factory.wires


def test_cold_same_resolver_and_source_only_flags(tmp_path):
    e = integration_fixture(tmp_path)
    r = runtime(e)
    result = r.cold_recover()
    assert result.version == e.model.current().ref.version and result.intake_allowed
    assert not result.runtime_qualified and not result.promotion_authority
    assert e.factory.created[0][2] is e.factory.created[1][2] is e.bundles["reader"]
    assert all(role == "reader" for service, role, bundle, client in e.factory.created)
    r.close()


def test_real_integrated_model_reaches_baseline_without_raw_ready_shortcut(tmp_path):
    e = integration_fixture(tmp_path)
    r = runtime(e)
    r.cold_recover()
    closure, members = integrated_packet(e, r)
    r.enable_writer(e.bundles["writer"])
    r.custody.reserve("packet1", members, 5000)
    assert r.cold_recover().candidate == "HOLD"
    for atom, _, body in members:
        r.custody.upload(atom, body)
        r.custody.reconcile(atom)
    r.custody.ready()
    assert r.cold_recover().candidate == "VERIFIED"
    r.custody.accept()
    assert r.cold_recover().baseline == "ACCEPTED"
    # Current floor advances without rewriting the exact schema2 READY origin.
    external_authority_update(e, r, lambda h: h.update(floor=e.model.state()["sequence"]))
    assert r.cold_recover().baseline == "ACCEPTED"
    assert e.model.state()["schema"] == 2
    r.close()


def test_schema1_migration_is_explicit_and_historical_bytes_untouched(tmp_path):
    e = integration_fixture(tmp_path, schema2=False)
    r = runtime(e)
    original = e.model.current()
    with pytest.raises(m.Hold, match="explicit schema1 migration"):
        r.cold_recover()
    assert e.model.current().ref == original.ref
    result = r.migrate_schema1(e.template, e.bundles["writer"])
    assert result.version == e.model.current().ref.version
    assert e.model.state()["schema"] == 2
    assert e.model.read(original.ref).body == original.body
    assert original.ref.wire() in e.model.state()["controls"]
    r.close()


def test_migration_requires_exact_source_and_nonrecursive_owner_consent(tmp_path):
    e = integration_fixture(tmp_path, schema2=False)
    wrong = copy.deepcopy(e.template)
    wrong["fence"] = 2
    with pytest.raises(m.Hold, match="template"):
        m.prepare_schema2(e.anchor, e.model.current(), wrong)
    e.model.corrupt_state(lambda s: s["incidents"].append("new-current"))
    with pytest.raises(m.Hold, match="exact-source"):
        m.prepare_schema2(e.anchor, e.model.current(), e.template)
    assert not e.factory.wires


def test_pre_send_fsync_failure_and_post_fsync_crash_never_refund(tmp_path, monkeypatch):
    e = integration_fixture(tmp_path)
    original = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("fsync fault")))
    with pytest.raises(OSError):
        runtime(e)
    assert not e.factory.wires
    monkeypatch.setattr(os, "fsync", original)
    # A durable claim before a crash with no send stays spent and cannot reset.
    w = e.anchor.data["seeds"]["seed-reader"]
    e.journal.claim("seed-reader", w, "e" * 64)
    j2 = m.AttemptJournal(e.anchor)
    assert len(j2._read()["attempts"]["seed-reader"]) == 1
    assert j2._read()["attempts"]["seed-reader"][0]["state"] == "ATTEMPTING"


@pytest.mark.parametrize("change", ["screened", "time", "fence"])
def test_post_fsync_last_guard_blocks_new_put_without_q_reset(tmp_path, monkeypatch, change):
    e = integration_fixture(tmp_path)
    r = runtime(e)
    r.cold_recover()
    closure, members = integrated_packet(e, r)
    r.enable_writer(e.bundles["writer"])
    r.custody.reserve("packet", members, 5000)
    before = copy.deepcopy(e.model.state())
    writes = e.factory.wires.count(("writer", "put_object"))
    original, fired = e.journal.claim, [False]
    def claim(wid, w, request):
        index = original(wid, w, request)
        if wid == "seed-writer" and not fired[0]:
            fired[0] = True
            if change == "screened":
                external_authority_update(e, r, lambda h: h["revoked"].append(dict(purpose="screened", closure=closure)))
            elif change == "time":
                e.clock[0] += 25
            else:
                external_authority_update(e, r, lambda h: h.update(fence=2))
        return index
    monkeypatch.setattr(e.journal, "claim", claim)
    with pytest.raises(m.Hold):
        r.custody.upload("data", members[0][2])
    assert fired[0] and e.factory.wires.count(("writer", "put_object")) == writes
    assert e.model.state()["ledger"] == before["ledger"] and e.model.state()["lifetime"] == before["lifetime"]
    assert e.journal._read()["attempts"]["seed-writer"][-1]["state"] == "UNKNOWN"
    r.close()


def test_lost_allocation_ack_keeps_both_escrows_and_recovers_same_id(tmp_path):
    e = integration_fixture(tmp_path)
    r = runtime(e)
    r.cold_recover()
    r.enable_writer(e.bundles["writer"])
    w = copy.deepcopy(e.anchor.data["seeds"]["seed-writer"])
    w.update(parent="seed-writer", attempts=10)
    w["charge"] = w["attempts"] * (1 + w["response_bytes"])
    e.model.fault = "cas-after"
    with pytest.raises(TimeoutError):
        r.reserve_wallet("writer-next", w, new_fence=1)
    assert len(e.model.state()["integration"]["wallets"]) == 3
    assert "writer-next" not in e.journal._read()["wallets"]
    r.cold_recover()
    r.use_wallet("writer", "writer-next")
    assert r.gate.wallet_ids["writer"] == "writer-next"
    with pytest.raises(m.Hold):
        r.reserve_wallet("writer-next", w, new_fence=1)
    assert len(e.model.state()["integration"]["wallets"]) == 3
    r.close()


def test_missing_or_relocated_journal_never_reinitializes_from_anchor(tmp_path):
    e = integration_fixture(tmp_path)
    path = Path(e.anchor.journal["path"])
    path.unlink()
    with pytest.raises(FileNotFoundError):
        m.AttemptJournal(e.anchor)
    assert not path.exists() and not e.factory.created


def test_unregistered_history_and_payload_never_send(tmp_path):
    e = integration_fixture(tmp_path)
    r = runtime(e)
    r.cold_recover()
    before = len(e.factory.wires)
    with pytest.raises(m.Hold, match="registered"):
        r.store.read(m.Ref(e.anchor.policy.ctrl_key, "unregistered", "a" * 64, 1))
    with pytest.raises(m.Hold, match="unregistered"):
        r.store.latest(e.anchor.policy.prefix + "objects/unknown", 100)
    assert len(e.factory.wires) == before
    r.close()


def test_real_boto_lazy_explicit_sts_binding_with_stubber(tmp_path):
    from botocore.stub import Stubber
    e = integration_fixture(tmp_path)
    made, stubs = [], []
    def factory(service, bundle, p):
        client = m.boto_client(service, bundle, p)
        made.append((service, bundle, client))
        stub = Stubber(client)
        if service == "sts":
            stub.add_response("get_caller_identity", dict(Account=p.account,
                Arn="arn:aws:sts::123456789012:assumed-role/reader/session-reader",
                UserId="stable-reader:session-reader"), {})
        stub.activate()
        stubs.append(stub)
        return client
    r = m.CustodyRuntime(e.anchor, e.journal, lambda: e.clock[0], dict(reader="seed-reader"),
        dict(reader=e.bundles["reader"]), client_factory=factory)
    assert made[0][0] == "sts" and made[1][0] == "s3" and made[0][1] is made[1][1]
    for stub in stubs:
        stub.assert_no_pending_responses()
        stub.deactivate()
    r.close()


def test_explicit_migration_preserves_genuine_schema1_baseline_history(tmp_path):
    e = integration_fixture(tmp_path, schema2=False, baseline=True)
    old = e.model.state()["baseline"]
    origin = m.Ref.parse(old["origin"]["frontier"], e.anchor.policy)
    assert m.decode(e.model.read(origin).body)["schema"] == 1
    r = runtime(e)
    result = r.migrate_schema1(e.template, e.bundles["writer"])
    assert result.baseline == "ACCEPTED"
    assert e.model.state()["baseline"] == old
    assert m.decode(e.model.read(origin).body)["schema"] == 1
    r.close()


def test_unknown_sdk_parameters_never_enter_journal_or_wire(tmp_path):
    e = integration_fixture(tmp_path)
    r = runtime(e)
    r.cold_recover()
    before, wires = e.journal._read(), len(e.factory.wires)
    with pytest.raises(m.Hold, match="parameter allowlist"):
        r.reader.get_object(Bucket=e.anchor.policy.bucket, Key=e.anchor.policy.ctrl_key,
            ExpectedBucketOwner=e.anchor.policy.account, SSECustomerKey="must-never-be-journaled")
    assert e.journal._read() == before and len(e.factory.wires) == wires
    r.close()
