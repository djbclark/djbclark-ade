#!/usr/bin/env python3
"""Finite storage-custody pilot. No enrollment, deployment or runtime authority.

ProtectedAuthority is an existing-controller trust boundary, NOT a JSON flag or
receipt authenticator. Importing this module never loads an AWS SDK or client.
The production S3 port is explicit; this module has no provisioning/apply CLI.
"""
from __future__ import annotations

import base64
import copy
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import fcntl
import os
from pathlib import Path
import stat
import tempfile
import threading
import json
import re
import time
from typing import Callable, Protocol


class Hold(ValueError):
    """Missing, stale, unknown or inconsistent custody evidence."""


class Conflict(Hold):
    """Caller must restart from the authoritative current CTRL."""


def require(ok, reason):
    if not ok:
        raise Hold(reason)


def natural(value, name, positive=False):
    require(type(value) is int and value >= (1 if positive else 0), name)
    return value


def token(value, name):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", value), name)
    return value


def sha(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "SHA256")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def decode(data):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, "duplicate control key")
            out[key] = value
        return out
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(Hold("nonfinite control")))
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise Hold("malformed control JSON") from exc


@dataclass(frozen=True)
class Policy:
    """All values are required protected enrollment choices, never paper defaults.

    Cash is integer microcurrency; quotes are operator-enrolled upper bounds,
    not provider prices. Control reserve covers the ENTIRE bounded control pool
    (including failed/orphan writes) before intake starts. No release/refund path.
    """
    identity: str
    account: str
    region: str
    bucket: str
    prefix: str
    writer: str
    reader: str
    policy_digest: str
    contract_digest: str
    max_object_bytes: int
    max_packet_bytes: int
    max_control_bytes: int
    max_members: int
    max_mutations: int
    max_cycles: int
    cycle_seconds: int
    floor_seconds: int
    proof_seconds: int
    control_reserve_bytes: int
    preservation_reserve_cash: int
    annual_cash: int
    lifetime_cash: int
    byte_liability: int
    object_liability: int
    generation: int
    minimum_sequence: int
    maximum_horizon: int
    transport_seconds: int

    def validate(self):
        for name in ("identity", "writer", "reader"):
            token(getattr(self, name), name)
        require(self.writer != self.reader, "distinct persistent principals required")
        require(re.fullmatch(r"[0-9]{12}", self.account or ""), "account")
        require(re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-[0-9]+", self.region or ""), "region")
        require(re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", self.bucket or "")
                and not self.bucket.endswith("--x-s3"), "general-purpose bucket")
        require(re.fullmatch(r"[a-z0-9][a-z0-9/-]{0,120}/", self.prefix or "")
                and "//" not in self.prefix and ".." not in self.prefix, "prefix")
        sha(self.policy_digest)
        sha(self.contract_digest)
        for name in self.__dataclass_fields__:
            if name not in {"identity", "account", "region", "bucket", "prefix", "writer", "reader",
                            "policy_digest", "contract_digest"}:
                natural(getattr(self, name), name, name != "minimum_sequence")
        require(self.max_object_bytes <= 5_000_000_000, "single PUT cap; split payloads first")
        require(self.max_object_bytes <= self.max_packet_bytes, "object/packet cap")
        require(self.control_reserve_bytes >= self.max_control_bytes * self.max_mutations,
                "all potential control versions must be reserved")
        require(self.preservation_reserve_cash >= self.control_reserve_bytes * self.byte_liability
                + self.max_mutations * self.object_liability, "control cash pool")
        require(self.preservation_reserve_cash < min(self.annual_cash, self.lifetime_cash), "intake cash pool")
        return self

    @property
    def ctrl_key(self):
        return self.prefix + "CTRL"


class ProtectedAuthority(Protocol):
    def current(self) -> Policy | None:
        """Authenticated existing enrollment and current revocations; None denies.

        Implementer binds persistent principals to supplied sessions out of band.
        Candidate data must NEVER implement this port. No implementation shipped.
        """

    def permits(self, purpose: str, closure: str | None) -> bool:
        """Current purpose-specific authorization/revocation, default deny."""


@dataclass(frozen=True)
class Ref:
    key: str
    version: str
    sha256: str
    size: int

    def validate(self, p):
        require(isinstance(self.key, str) and self.key.startswith(p.prefix)
                and ".." not in self.key and not any(c in self.key for c in "\x00\r\n")
                and len(self.key) <= 900, "object key")
        require(isinstance(self.version, str) and 0 < len(self.version) <= 1024
                and self.version != "null", "exact version required")
        sha(self.sha256)
        natural(self.size, "object length")
        return self

    def wire(self):
        return dict(key=self.key, version=self.version, sha256=self.sha256, size=self.size)

    @classmethod
    def parse(cls, value, p):
        require(type(value) is dict and set(value) == {"key", "version", "sha256", "size"}, "reference shape")
        return cls(**value).validate(p)


@dataclass(frozen=True)
class Observation:
    ref: Ref
    body: bytes
    mode: str
    hold: str
    until: int
    etag: str

    def protected(self, p, horizon, cap):
        self.ref.validate(p)
        require(type(self.body) is bytes and len(self.body) == self.ref.size <= cap
                and digest(self.body) == self.ref.sha256, "independent exact bytes")
        natural(self.until, "actual retain date")
        require(self.until <= p.maximum_horizon, "actual term exceeds enrolled liability bound")
        require(self.mode == "COMPLIANCE" and self.hold == "ON" and self.until >= horizon,
                "actual protection/date insufficient")
        require(isinstance(self.etag, str) and bool(self.etag), "ETag missing")
        return self


class Store(Protocol):
    def current(self) -> Observation: ...
    def read(self, ref: Ref) -> Observation: ...
    def latest(self, key: str, cap: int) -> Observation: ...
    def cas(self, previous: Observation, body: bytes, horizon: int) -> None: ...
    def put(self, key: str, body: bytes, horizon: int) -> None: ...
    def extend(self, ref: Ref, horizon: int) -> None: ...


@dataclass(frozen=True)
class Resolution:
    version: str
    sequence: int
    baseline: str
    candidate: str
    intake_allowed: bool
    preservation_allowed: bool
    reason: str
    # This is storage-only evidence, not native/runtime qualification.
    runtime_qualified: bool = False
    promotion_authority: bool = False


@dataclass(frozen=True)
class VerifiedAcceptance:
    version: str
    sequence: int
    closure: str
    cycle: str
    observed_at: int
    policy_digest: str


def genesis(p: Policy, now: int):
    """Offline/enrollment builder only. No API exists here to install a genesis."""
    p.validate()
    natural(now, "clock")
    return dict(schema=1, identity=p.identity, generation=p.generation, sequence=0,
                policy=p.policy_digest, contract=p.contract_digest, baseline=None,
                proposal=None, ledger={}, controls=[], renewals={}, incidents=[],
                annual={}, lifetime=0, mutations=0, last_operation="enrollment",
                control_horizon=now + p.floor_seconds)


def closure_id(members):
    return digest(canonical(members))


class Custody:
    """Serialized finite transitions. Store is actual S3 or authoritative offline model.

    Every method rereads authority/current CTRL. Mutations compare-and-swap the
    exact ETag. SDK failures propagate with previously reserved liability intact.
    No method accepts a deserialized VerifiedAcceptance as authorization.
    """
    def __init__(self, authority: ProtectedAuthority, store_factory: Callable[[Policy], Store],
                 clock: Callable[[], int]):
        self.authority, self.factory, self.clock = authority, store_factory, clock

    def _open(self, purpose, closure=None):
        begin = getattr(self.authority, "begin", None)
        if begin is not None:
            begin(purpose, closure)
        p = self.authority.current()
        require(type(p) is Policy, "unenrolled")
        p.validate()
        require(self.authority.permits(purpose, closure) is True, "current authority denies " + purpose)
        now = natural(self.clock(), "trusted clock")
        store = self.factory(p)
        obs = store.current()
        obs.protected(p, 0 if purpose == "preserve" else now, p.max_control_bytes)
        s = decode(obs.body)
        self._validate(s, p)
        return p, now, store, obs, s

    def _validate(self, s, p, *, current=True):
        require(type(s) is dict and type(s.get("schema")) is int and s["schema"] in (1, 2), "CTRL schema")
        expected = set(genesis(p, 0)) | ({"integration"} if s["schema"] == 2 else set())
        require(set(s) == expected, "CTRL schema fields")
        if s["schema"] == 2:
            validator = getattr(self.authority, "validate_integration", None)
            require(validator is not None, "schema2 needs protected integration authority")
            validator(s, current=current)
        require(s["identity"] == p.identity
                and type(s["generation"]) is int and s["generation"] == p.generation and s["policy"] == p.policy_digest
                and s["contract"] == p.contract_digest, "protected CTRL enrollment binding")
        for k in ("sequence", "mutations", "lifetime", "control_horizon"):
            natural(s[k], k)
        require(s["control_horizon"] <= p.maximum_horizon, "control term liability bound")
        if current:
            require(s["sequence"] >= p.minimum_sequence, "current rollback floor")
        require(s["mutations"] <= p.max_mutations, "control pool")
        require(type(s["ledger"]) is dict and len(s["ledger"]) <= p.max_members * p.max_cycles,
                "bounded issuance ledger")
        require(type(s["controls"]) is list and len(s["controls"]) <= p.max_mutations, "control census cap")
        for r in s["controls"]:
            Ref.parse(r, p)
        require(type(s["annual"]) is dict and type(s["renewals"]) is dict
                and type(s["incidents"]) is list, "ledger collections")
        charged, annual = 0, {}
        for atom, a in s["ledger"].items():
            token(atom, "atom")
            require(type(a) is dict and set(a) == {"key", "sha256", "size", "kind", "cohort", "horizon",
                    "issued", "charge", "year", "ref"}, "issuance shape")
            Ref(a["key"], "pending", a["sha256"], a["size"]).validate(p)
            for k in ("size", "horizon", "issued", "charge", "year"):
                natural(a[k], k)
            require(a["kind"] in ("data", "manifest") and a["size"] <= p.max_object_bytes,
                    "issuance member")
            require(a["horizon"] <= p.maximum_horizon, "issuance term liability bound")
            token(a["cohort"], "birth cohort")
            require(a["charge"] == a["size"] * p.byte_liability + p.object_liability, "liability quote")
            if a["ref"] is not None:
                r = Ref.parse(a["ref"], p)
                require((r.key, r.sha256, r.size) == (a["key"], a["sha256"], a["size"]), "outcome identity")
            charged += a["charge"]
            annual[str(a["year"])] = annual.get(str(a["year"]), 0) + a["charge"]
        require(s["lifetime"] == charged and s["annual"] == annual, "recomputable liability ledger")
        require(charged + p.preservation_reserve_cash <= p.lifetime_cash
                and all(v + p.preservation_reserve_cash <= p.annual_cash for v in annual.values()),
                "cash exhausted")
        for record in (s["proposal"], s["baseline"]):
            if record is None:
                continue
            require(type(record) is dict and set(record) == {"closure", "members", "cycles", "phase", "origin"},
                    "proposal/baseline shape")
            require(type(record["members"]) is list and 0 < len(record["members"]) <= p.max_members,
                    "bounded members")
            require(len(set(record["members"])) == len(record["members"])
                    and all(a in s["ledger"] for a in record["members"]), "member/ledger closure")
            require(record["phase"] in ("RESERVED", "READY", "HELD", "ACCEPTED"), "phase")
            sha(record["closure"])
            if record["phase"] == "ACCEPTED":
                require(type(record["origin"]) is dict and set(record["origin"]) == {"frontier", "observed_at"},
                        "accepted origin required")
                Ref.parse(record["origin"]["frontier"], p)
                natural(record["origin"]["observed_at"], "origin clock")
            else:
                require(record["origin"] is None, "pending origin")
            require(type(record["cycles"]) is list and 0 < len(record["cycles"]) <= p.max_cycles, "cycle count")
            previous_h = 0
            for i, c in enumerate(record["cycles"]):
                require(type(c) is dict and set(c) == {"id", "t0", "horizon", "deadline"}, "cycle shape")
                token(c["id"], "cycle")
                for k in ("t0", "horizon", "deadline"):
                    natural(c[k], k)
                require(c["deadline"] == c["t0"] + p.cycle_seconds and c["horizon"] >= previous_h
                        and c["horizon"] >= c["t0"] + p.floor_seconds, "immutable cycle dates")
                previous_h = c["horizon"]
            require(len({c["id"] for c in record["cycles"]}) == len(record["cycles"]), "unique cycles")
        for rid, job in s["renewals"].items():
            token(rid, "renewal")
            require(type(job) is dict and set(job) == {"census", "root", "cutoff", "target", "due", "progress", "done", "source", "completed_at"},
                    "renewal shape")
            require(type(job["census"]) is dict and digest(canonical(job["census"])) == job["root"], "census root")
            Ref.parse(job["source"], p)
            natural(job["completed_at"], "completion clock")
            natural(job["cutoff"], "cutoff")
            natural(job["target"], "target")
            require(job["target"] <= p.maximum_horizon, "renewal term liability bound")
            natural(job["due"], "due")
            require(type(job["progress"]) is dict and set(job["progress"]) <= set(job["census"])
                    and type(job["done"]) is bool, "renewal progress")
            for item, member in job["census"].items():
                require(type(member) is dict and set(member) == {"atom", "ref"}, "census member")
                if member["atom"] is not None:
                    require(member["atom"] in s["ledger"], "census issuance atom")
                else:
                    Ref.parse(member["ref"], p)
            for observed in job["progress"].values():
                natural(observed, "progress clock")

    def _authorized(self, p, purpose, closure):
        require(self.authority.current() == p and self.authority.permits(purpose, closure) is True,
                "authority/revocation changed")
        if closure is not None and purpose in {"intake", "upload", "accept", "revalidate"}:
            require(self.authority.permits("screened", closure) is True,
                    "exact-closure screening revoked")

    def _stable(self, p, store, obs, purpose, closure=None):
        self._authorized(p, purpose, closure)
        latest = store.current()
        latest.protected(p, obs.until, p.max_control_bytes)
        require(latest.ref == obs.ref and latest.etag == obs.etag, "current CTRL changed")
        self._validate(decode(latest.body), p)
        self._authorized(p, purpose, closure)

    def _commit(self, p, now, store, obs, s, purpose, operation, closure=None,
                final_check=None, before_serialize=None):
        self._stable(p, store, obs, purpose, closure)
        require(s["mutations"] < p.max_mutations, "control preservation pool exhausted")
        s["sequence"] += 1
        s["mutations"] += 1
        s["last_operation"] = token(operation, "operation")
        if obs.ref.wire() not in s["controls"]:
            s["controls"].append(obs.ref.wire())
        horizons = [s["control_horizon"], now + p.floor_seconds]
        for record in (s["baseline"], s["proposal"]):
            if record is not None:
                horizons.append(record["cycles"][-1]["horizon"])
        s["control_horizon"] = max(horizons)
        if before_serialize is not None:
            before_serialize()
        self._validate(s, p)
        data = canonical(s)
        require(len(data) <= p.max_control_bytes, "bounded catalogue/control shard full; intake HOLD")
        # A lost reply has no refund/retry path. Refetch current CTRL on next invocation.
        if final_check is not None:
            final_check()
        self._authorized(p, purpose, closure)
        def wire_check():
            self._authorized(p, purpose, closure)
            if final_check is not None:
                final_check()
        arm = getattr(store, "arm_write", None)
        if arm is not None:
            arm(wire_check)
        store.cas(obs, data, s["control_horizon"])

    def _cycle_boundary(self, p, cycle, started, horizon=None):
        actual = natural(self.clock(), "operation final clock")
        require(started <= actual <= cycle["deadline"], "cycle expired during final read")
        require((cycle["horizon"] if horizon is None else horizon) >= actual + p.floor_seconds,
                "operation final protection floor")

    def reserve(self, ticket, members, horizon):
        """PRE-upload screened exact-byte allowlist from protected caller, not paths.

        members: [(atom, kind, bytes)]. Screening approval is a separate protected
        authority purpose bound to the complete byte manifest; no silent redaction.
        """
        token(ticket, "ticket")
        require(type(members) is list and bool(members), "members")
        manifest = []
        for atom, kind, body in members:
            token(atom, "atom")
            require(kind in ("data", "manifest") and type(body) is bytes, "inert exact bytes")
            manifest.append(dict(atom=atom, kind=kind, sha256=digest(body), size=len(body)))
        closure = closure_id(manifest)
        p, now, st, ob, s = self._open("intake", closure)
        require(self.authority.permits("screened", closure) is True, "pre-upload privacy screening absent")
        require(s["proposal"] is None or s["proposal"]["phase"] == "ACCEPTED", "one durable intake lease")
        require(len(members) <= p.max_members and len({x[0] for x in members}) == len(members), "member cap/duplicates")
        require(sum(len(x[2]) for x in members) <= p.max_packet_bytes, "packet cap")
        natural(horizon, "horizon")
        require(now + p.floor_seconds <= horizon <= p.maximum_horizon, "admission floor/term ceiling")
        year = datetime.fromtimestamp(now, timezone.utc).year
        for atom, kind, body in members:
            require(atom not in s["ledger"] and len(body) <= p.max_object_bytes, "new bounded atom")
            charge = len(body) * p.byte_liability + p.object_liability
            s["ledger"][atom] = dict(key=p.prefix + "objects/" + digest(body) + "/" + atom,
                    sha256=digest(body), size=len(body), kind=kind, cohort=ticket,
                    horizon=horizon, issued=now, charge=charge, year=year, ref=None)
            s["lifetime"] += charge
            s["annual"][str(year)] = s["annual"].get(str(year), 0) + charge
        s["proposal"] = dict(closure=closure, members=[x[0] for x in members], phase="RESERVED",
                cycles=[dict(id=ticket, t0=now, horizon=horizon, deadline=now + p.cycle_seconds)], origin=None)
        self._commit(p, now, st, ob, s, "intake", ticket, closure,
                     final_check=lambda: self._cycle_boundary(p, s["proposal"]["cycles"][-1], now))
        return closure

    def upload(self, atom, body):
        """At most one API attempt; unknown outcomes stay reserved. Reconcile first."""
        p, now, st, ob, s = self._open("upload")
        a = s["ledger"].get(atom)
        require(a is not None and a["ref"] is None, "unresolved issuance required")
        q = s["proposal"]
        require(q is not None and atom in q["members"] and q["phase"] == "RESERVED", "active proposal")
        require(now <= q["cycles"][-1]["deadline"], "expired cycle")
        require(type(body) is bytes and len(body) == a["size"] and digest(body) == a["sha256"], "exact screened bytes")
        require(self.authority.permits("screened", q["closure"]) is True, "screening revoked")
        self._stable(p, st, ob, "upload", q["closure"])
        self._cycle_boundary(p, q["cycles"][-1], now, a["horizon"])
        self._authorized(p, "upload", q["closure"])
        def wire_check():
            self._authorized(p, "upload", q["closure"])
            self._cycle_boundary(p, q["cycles"][-1], now, a["horizon"])
        arm = getattr(st, "arm_write", None)
        if arm is not None:
            arm(wire_check)
        # Key is uniquely durably issued; IfNoneMatch suppresses duplicate writes.
        st.put(a["key"], body, a["horizon"])
        # Even a successful PUT response is not acceptance or a ledger refund.

    def reconcile(self, atom):
        p, now, st, ob, s = self._open("preserve")
        a = s["ledger"].get(atom)
        require(a is not None, "unknown atom")
        actual = st.read(Ref.parse(a["ref"], p)) if a["ref"] else st.latest(a["key"], p.max_object_bytes)
        actual.protected(p, a["horizon"], p.max_object_bytes)
        require((actual.ref.key, actual.ref.sha256, actual.ref.size) == (a["key"], a["sha256"], a["size"]), "exact outcome")
        a["ref"] = actual.ref.wire()
        self._commit(p, now, st, ob, s, "preserve", "reconcile:" + atom)

    def ready(self):
        p, now, st, ob, s = self._open("intake")
        q = s["proposal"]
        require(q is not None and q["phase"] == "RESERVED", "reserved proposal")
        require(all(s["ledger"][a]["ref"] is not None for a in q["members"]), "unresolved issuance")
        require(now <= q["cycles"][-1]["deadline"], "expired cycle")
        q["phase"] = "READY"
        self._commit(p, now, st, ob, s, "intake", "ready", q["closure"],
                     final_check=lambda: self._cycle_boundary(p, q["cycles"][-1], now))

    def _verify_record(self, p, now, st, s, q, baseline=False):
        require(q is not None and q["phase"] == ("ACCEPTED" if baseline else "READY"), "phase pending/held")
        require(self.authority.permits("baseline" if baseline else "accept", q["closure"]) is True,
                "current closure revoked")
        require(self.authority.permits("screened", q["closure"]) is True, "current screening revoked")
        c = q["cycles"][-1]
        require(baseline or c["t0"] <= now <= c["deadline"], "cycle expired/clock rollback")
        horizon = max(c["horizon"], now + p.floor_seconds)
        untils = [st.current().protected(p, horizon, p.max_control_bytes).until]
        if baseline:
            origin = st.read(Ref.parse(q["origin"]["frontier"], p))
            untils.append(origin.protected(p, horizon, p.max_control_bytes).until)
            prior = decode(origin.body)
            self._validate(prior, p, current=False)
            expected = copy.deepcopy(q)
            expected["phase"], expected["origin"] = "READY", None
            require(prior["proposal"] == expected and c["t0"] <= q["origin"]["observed_at"] <= min(c["deadline"], now),
                    "accepted origin is not the protected READY frontier")
        require(sum(s["ledger"][a]["size"] for a in q["members"]) <= p.max_packet_bytes, "packet read cap")
        descriptors, bodies = [], []
        for atom in q["members"]:
            a = s["ledger"][atom]
            require(a["ref"] is not None, "unresolved closure atom")
            actual = st.read(Ref.parse(a["ref"], p)).protected(p, horizon, p.max_object_bytes)
            untils.append(actual.until)
            descriptors.append(dict(atom=atom, kind=a["kind"], sha256=a["sha256"], size=a["size"]))
            bodies.append((a["kind"], actual.body))
        require(closure_id(descriptors) == q["closure"], "exact closure")
        manifests = [decode(b) for kind, b in bodies if kind == "manifest"]
        expected = [d for d in descriptors if d["kind"] == "data"]
        require(len(manifests) == 1 and type(manifests[0]) is dict
                and type(manifests[0].get("schema")) is int
                and manifests[0] == {"schema": 1, "data": expected}, "data closure manifest")
        # Opaque data (including malformed negative fixtures) is hashed, never parsed/executed.
        for job in s["renewals"].values():
            require(job["done"] or now < job["due"], "missed original renewal deadline")
            if job["done"]:
                self._verify_census(job, s, p, st, now)
                require(0 < job["completed_at"] < job["due"], "late/unproved renewal completion")
                require(set(job["progress"]) == set(job["census"]), "raw done is not a complete census")
                for member in job["census"].values():
                    untils.append(st.read(self._renew_ref(member, s, p)).protected(p, max(horizon, job["target"]),
                            max(p.max_object_bytes, p.max_control_bytes)).until)
        check = (now, None if baseline else c["deadline"], min(untils))
        self._fresh(p, check)
        return q["closure"], check

    def _fresh(self, p, check):
        started, deadline, until = check
        ended = natural(self.clock(), "trusted final clock")
        require(started <= ended <= started + p.proof_seconds, "expired verification observation")
        require(deadline is None or ended <= deadline, "cycle expired during verification")
        require(until >= ended + p.floor_seconds, "final admission floor")

    def resolve_current(self):
        """Single reader for normal/recovery/terminal paths; failures are HOLD."""
        try:
            p, now, st, ob, s = self._open("read")
            outcomes = []
            reasons, checks = [], []
            for baseline, record in ((True, s["baseline"]), (False, s["proposal"])):
                try:
                    _, check = self._verify_record(p, now, st, s, record, baseline)
                    checks.append((check, record["closure"], baseline))
                    outcomes.append("ACCEPTED" if baseline else "VERIFIED")
                except Exception as exc:
                    outcomes.append("HOLD")
                    reasons.append(str(exc))
            self._stable(p, st, ob, "read")
            for check, closure, baseline in checks:
                require(self.authority.permits("baseline" if baseline else "accept", closure) is True
                        and self.authority.permits("screened", closure) is True, "closure revoked during final read")
                self._fresh(p, check)
            return Resolution(ob.ref.version, s["sequence"], *outcomes,
                    self.authority.permits("intake", None) is True and
                    (s["proposal"] is None or s["proposal"]["phase"] == "ACCEPTED"),
                    self.authority.permits("preserve", None) is True, "; ".join(reasons))
        except Exception as exc:
            return Resolution("", -1, "HOLD", "HOLD", False, False, str(exc))

    def accept(self):
        """Recompute complete proof now; never consume caller-supplied READY/proof."""
        p, now, st, ob, s = self._open("accept")
        q = s["proposal"]
        closure, check = self._verify_record(p, now, st, s, q)
        self._stable(p, st, ob, "accept", closure)
        observed_at = natural(self.clock(), "acceptance clock")
        proof = VerifiedAcceptance(ob.ref.version, s["sequence"], closure, q["cycles"][-1]["id"], observed_at, p.policy_digest)
        q["phase"] = "ACCEPTED"
        q["origin"] = dict(frontier=ob.ref.wire(), observed_at=observed_at)
        s["baseline"] = copy.deepcopy(q)
        self._commit(p, now, st, ob, s, "accept", "accept", closure,
                     final_check=lambda: self._fresh(p, check))
        # Receipt binds the observed frontier, not the new terminal version itself.
        # Its consumer must resolve_current; it is NOT a self-authenticating grant.
        return proof

    def revalidate(self, cycle):
        p, now, st, ob, s = self._open("revalidate")
        q = s["proposal"]
        require(q is not None and q["phase"] != "ACCEPTED", "pending proposal")
        require(now > q["cycles"][-1]["deadline"] and len(q["cycles"]) < p.max_cycles, "bounded expired cycle")
        token(cycle, "cycle")
        require(cycle not in [c["id"] for c in q["cycles"]], "new cycle id")
        horizon = max(q["cycles"][-1]["horizon"], now + p.floor_seconds)
        q["cycles"].append(dict(id=cycle, t0=now, horizon=horizon, deadline=now + p.cycle_seconds))
        # Immutable old cycle and all liabilities retained; renewal supplies missing dates.
        self._commit(p, now, st, ob, s, "revalidate", cycle, q["closure"],
                     final_check=lambda: self._cycle_boundary(p, q["cycles"][-1], now))

    def incident(self, identifier):
        p, now, st, ob, s = self._open("preserve")
        token(identifier, "incident")
        require(len(s["incidents"]) < p.max_mutations, "incident cap")
        if identifier not in s["incidents"]:
            s["incidents"].append(identifier)
        self._commit(p, now, st, ob, s, "preserve", "incident")

    def renew_begin(self, renewal, horizon, due):
        p, now, st, ob, s = self._open("preserve")
        token(renewal, "renewal")
        require(renewal not in s["renewals"] and len(s["renewals"]) < p.max_cycles, "finite renewal jobs")
        require(type(horizon) is int and horizon >= now + p.floor_seconds
                and horizon <= p.maximum_horizon
                and type(due) is int and now < due <= s["control_horizon"], "renewal dates")
        census = {"atom:" + a: dict(atom=a, ref=None) for a in s["ledger"]}
        for r in s["controls"] + [ob.ref.wire()]:
            census["ctrl:" + digest(canonical(r))] = dict(atom=None, ref=r)
        s["renewals"][renewal] = dict(census=census, root=digest(canonical(census)), cutoff=s["sequence"],
                target=horizon, due=due, progress={}, done=False, source=ob.ref.wire(), completed_at=0)
        self._commit(p, now, st, ob, s, "preserve", "renew-begin")

    def _verify_census(self, job, s, p, st, now):
        source_ref = Ref.parse(job["source"], p)
        source = st.read(source_ref).protected(p, now, p.max_control_bytes)
        prior = decode(source.body)
        self._validate(prior, p, current=False)
        expected = {"atom:" + a: dict(atom=a, ref=None) for a in prior["ledger"]}
        for r in prior["controls"] + [source_ref.wire()]:
            expected["ctrl:" + digest(canonical(r))] = dict(atom=None, ref=r)
        require(job["cutoff"] == prior["sequence"] and job["census"] == expected,
                "fixed census does not cover its exact protected source frontier")
        return source.until

    def _renew_ref(self, member, s, p):
        if member["atom"] is None:
            return Ref.parse(member["ref"], p)
        a = s["ledger"][member["atom"]]
        require(a["ref"] is not None, "unresolved original census atom")
        return Ref.parse(a["ref"], p)

    def renew_item(self, renewal, item):
        p, now, st, ob, s = self._open("preserve")
        j = s["renewals"].get(renewal)
        require(j is not None and not j["done"] and item in j["census"], "renewal membership")
        require(now < j["due"], "original deadline missed")
        ref = self._renew_ref(j["census"][item], s, p)
        cap = max(p.max_object_bytes, p.max_control_bytes)
        actual = st.read(ref).protected(p, 0, cap)
        if actual.until < j["target"]:
            self._stable(p, st, ob, "preserve")
            def wire_check():
                self._authorized(p, "preserve", None)
                actual_time = natural(self.clock(), "renewal dispatch clock")
                require(now <= actual_time < j["due"], "renewal deadline at wire")
                require(j["target"] >= actual_time + p.floor_seconds, "renewal floor at wire")
            arm = getattr(st, "arm_write", None)
            if arm is not None:
                arm(wire_check)
            st.extend(ref, j["target"])
        st.read(ref).protected(p, j["target"], cap)
        j["progress"][item] = now
        self._commit(p, now, st, ob, s, "preserve", "renew-progress")

    def renew_finish(self, renewal):
        p, now, st, ob, s = self._open("preserve")
        j = s["renewals"].get(renewal)
        require(j is not None and not j["done"] and now < j["due"], "renewal finish/date")
        source_until = self._verify_census(j, s, p, st, now)
        require(set(j["progress"]) == set(j["census"]), "incomplete fixed census")
        cap = max(p.max_object_bytes, p.max_control_bytes)
        untils = [source_until, ob.until]
        for item, member in j["census"].items():
            require(0 <= now - j["progress"][item] <= p.proof_seconds, "expired census observation")
            untils.append(st.read(self._renew_ref(member, s, p)).protected(p, j["target"], cap).until)
        # Latest CTRL carries complete issuance delta through this closing watermark.
        # Post-cutoff/newborn atoms retain their own immutable horizon and liability.
        for atom, a in s["ledger"].items():
            if "atom:" + atom not in j["census"]:
                require(a["horizon"] >= a["issued"] + p.floor_seconds, "newborn floor")
        last_clock = [now]

        def check_finish_time():
            actual = natural(self.clock(), "renewal final clock")
            require(last_clock[0] <= actual, "renewal clock moved backwards")
            last_clock[0] = actual
            require(actual < j["due"], "original renewal deadline missed during verification")
            require(actual - now <= p.proof_seconds, "expired renewal verification")
            require(all(0 <= actual - t <= p.proof_seconds for t in j["progress"].values()),
                    "expired census observation")
            require(min(untils) >= actual + p.floor_seconds
                    and j["target"] >= actual + p.floor_seconds, "renewal final protection floor")
            return actual

        # Transport may cross the original due, proof age or protection floor.
        # Sample after member reads, after final-current transport, and at CAS.
        check_finish_time()
        j["done"] = True

        def record_completion():
            # This is the actual pre-CAS proof observation, not terminal commit time.
            j["completed_at"] = check_finish_time()

        self._commit(p, now, st, ob, s, "preserve", "renew-finish",
                     before_serialize=record_completion, final_check=check_finish_time)


class S3Store:
    """Real low-level S3 API port; caller provides separately enrolled clients.

    writer/reader clients MUST be bound to distinct persistent enrolled principals
    by the existing protected host. ExpectedBucketOwner checks destination, NOT
    caller identity. No STS/client/profile/default credential probing is performed.
    The supplied writer must have total_max_attempts=1: PUT uncertainty has no
    automatic retry. Use single-part bounded chunks, never managed multipart.
    """
    def __init__(self, policy: Policy, writer, reader, *, writer_identity, reader_identity, read_only=False):
        self.p = policy.validate()
        require(reader_identity == policy.reader, "enrolled reader binding")
        if read_only:
            require(writer is None and writer_identity is None, "read-only has no writer")
        else:
            require(writer_identity == policy.writer and writer is not reader, "enrolled independent client binding")
        for client in ((reader,) if read_only else (writer, reader)):
            require(client.meta.region_name == policy.region, "client region")
            endpoints = {"https://s3." + policy.region + ".amazonaws.com"}
            if policy.region == "us-east-1":
                endpoints.add("https://s3.amazonaws.com")
            require(client.meta.endpoint_url in endpoints, "enrolled AWS S3 endpoint required")
            require(client.meta.config.retries.get("total_max_attempts") == 1, "no hidden SDK retries")
            for seconds in (client.meta.config.connect_timeout, client.meta.config.read_timeout):
                require(type(seconds) in (int, float) and 0 < seconds <= policy.transport_seconds,
                        "bounded SDK connect/read timeout")
        self.writer, self.reader = writer, reader

    def _args(self, key, version=None):
        Ref(key, version or "pending", "0" * 64, 0).validate(self.p)
        args = dict(Bucket=self.p.bucket, Key=key, ExpectedBucketOwner=self.p.account)
        if version is not None:
            args["VersionId"] = version
        return args

    def _get(self, key, cap, version=None):
        deadline = time.monotonic() + self.p.transport_seconds
        response = self.reader.get_object(**self._args(key, version))
        body = response["Body"]
        try:
            length = natural(response.get("ContentLength"), "actual content length")
            require(length <= cap, "bounded transport")
            chunks, count = [], 0
            while True:
                require(time.monotonic() <= deadline, "transport deadline")
                chunk = body.read(min(1024 * 1024, cap - count + 1))
                require(time.monotonic() <= deadline, "transport deadline")
                if not chunk:
                    break
                count += len(chunk)
                require(count <= cap, "transport cap")
                chunks.append(chunk)
            data = b"".join(chunks)
            require(len(data) == length, "truncated transport")
        finally:
            body.close()
        ref = Ref(key, response.get("VersionId"), digest(data), len(data)).validate(self.p)
        require(version is None or ref.version == version, "returned version differs")
        args = self._args(key, ref.version)
        retention = self.reader.get_object_retention(**args).get("Retention", {})
        hold = self.reader.get_object_legal_hold(**args).get("LegalHold", {})
        until = retention.get("RetainUntilDate")
        require(isinstance(until, datetime) and until.tzinfo is not None, "retention timestamp")
        require(not response.get("DeleteMarker") and not response.get("Expiration"), "deleted/lifecycle expiry")
        return Observation(ref, data, retention.get("Mode"), hold.get("Status"), int(until.timestamp()),
                           response.get("ETag"))

    def current(self):
        return self._get(self.p.ctrl_key, self.p.max_control_bytes)

    def read(self, ref):
        ref.validate(self.p)
        require(ref.size <= max(self.p.max_object_bytes, self.p.max_control_bytes), "read cap")
        actual = self._get(ref.key, ref.size, ref.version)
        require(actual.ref == ref, "exact readback identity")
        return actual

    def latest(self, key, cap):
        require(0 <= cap <= max(self.p.max_object_bytes, self.p.max_control_bytes), "latest cap")
        return self._get(key, cap)

    def _put(self, key, body, horizon, condition):
        require(self.writer is not None, "read-only storage")
        require(type(body) is bytes and len(body) <= max(self.p.max_object_bytes, self.p.max_control_bytes), "PUT cap")
        natural(horizon, "retain horizon")
        self.writer.put_object(**self._args(key), Body=body, ContentLength=len(body),
                ChecksumSHA256=base64.b64encode(hashlib.sha256(body).digest()).decode("ascii"),
                ServerSideEncryption="AES256", StorageClass="STANDARD", ObjectLockMode="COMPLIANCE",
                ObjectLockRetainUntilDate=datetime.fromtimestamp(horizon, timezone.utc),
                ObjectLockLegalHoldStatus="ON", **condition)

    def cas(self, previous, body, horizon):
        require(previous.ref.key == self.p.ctrl_key, "CTRL CAS key")
        self._put(self.p.ctrl_key, body, horizon, dict(IfMatch=previous.etag))

    def put(self, key, body, horizon):
        require(key.startswith(self.p.prefix + "objects/"), "issued object namespace")
        self._put(key, body, horizon, dict(IfNoneMatch="*"))

    def extend(self, ref, horizon):
        require(self.writer is not None, "read-only storage")
        actual = self.read(ref)
        require(actual.mode == "COMPLIANCE" and actual.hold == "ON" and horizon >= actual.until,
                "monotone COMPLIANCE renewal only")
        self.writer.put_object_retention(**self._args(ref.key, ref.version),
                Retention=dict(Mode="COMPLIANCE", RetainUntilDate=datetime.fromtimestamp(horizon, timezone.utc)))



# Integration source. No installed enrollment, credentials resolver, account or
# runtime facade is supplied. These constructors are inert until explicitly used.
READ_METHODS = {"get_object", "get_object_retention", "get_object_legal_hold"}
WRITE_METHODS = {"put_object", "put_object_retention"}
RPC_METHODS = READ_METHODS | WRITE_METHODS | {"get_caller_identity"}


def shape(value, fields, reason):
    require(type(value) is dict and set(value) == set(fields.split()), reason)


def private_bytes(path, uid, cap):
    """No follow, bounded regular private file; never a candidate locator."""
    path = Path(path)
    require(path.is_absolute() and path.parent.resolve(strict=True) == path.parent, "protected absolute path")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == uid and info.st_nlink == 1
                and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= cap, "protected owner/mode/size")
        data = bytearray()
        while len(data) <= cap:
            chunk = os.read(fd, min(65536, cap - len(data) + 1))
            if not chunk:
                break
            data.extend(chunk)
        require(len(data) == info.st_size <= cap, "protected file changed/oversize")
        return bytes(data)
    finally:
        os.close(fd)


@dataclass(frozen=True)
class Enrollment:
    path: str
    sha256: str
    owner: int
    executor: str
    data: dict = field(repr=False)
    policy: Policy

    @classmethod
    def load(cls, path, *, expected_digest, expected_owner, expected_executor):
        # All three expectations must come from the existing protected host,
        # never from this file, candidate data, environment or a CLI fallback.
        sha(expected_digest)
        natural(expected_owner, "selected owner UID")
        require(os.getuid() == expected_owner, "selected executor OS owner")
        token(expected_executor, "selected executor")
        raw = private_bytes(path, expected_owner, 131072)
        require(digest(raw) == expected_digest, "protected anchor digest")
        d = decode(raw)
        shape(d, "schema expires policy principals grants screening executors rpc seeds migration", "enrollment fields")
        require(type(d["schema"]) is int and d["schema"] == 1, "enrollment version")
        require(type(d["executors"]) is dict and expected_executor in d["executors"], "selected enrolled executor")
        for executor, item in d["executors"].items():
            token(executor, "executor ID")
            shape(item, "owner journal", "executor fields")
            natural(item["owner"], "executor owner")
            shape(item["journal"], "path id max_bytes device inode", "selected durable journal")
            token(item["journal"]["id"], "journal ID")
            for name in ("max_bytes", "device", "inode"):
                natural(item["journal"][name], "journal " + name, True)
            require(Path(item["journal"]["path"]).is_absolute(), "selected journal path")
        require(d["executors"][expected_executor]["owner"] == expected_owner, "enrolled executor owner")
        natural(d["expires"], "enrollment expiry", True)
        require(type(d["policy"]) is dict and set(d["policy"]) == set(Policy.__dataclass_fields__), "complete selected Policy")
        p = Policy(**d["policy"]).validate()
        sha(d["screening"])
        shape(d["principals"], "reader writer", "selected principals")
        for role, identity in d["principals"].items():
            shape(identity, "kind arn unique_id sessions", "principal fields")
            require(identity["kind"] in {"user", "role"}, "unsupported principal kind")
            token(identity["unique_id"], "stable principal ID")
            require(type(identity["sessions"]) is list and len(identity["sessions"]) <= 64,
                    "bounded exact session names")
            for session in identity["sessions"]:
                token(session, "session name")
            resource = "user/" if identity["kind"] == "user" else "role/"
            require(isinstance(identity["arn"], str) and identity["arn"].startswith(
                    "arn:aws:iam::" + p.account + ":" + resource) and "*" not in identity["arn"]
                    and len(identity["arn"]) <= 512, "exact commercial IAM principal ARN")
            require(bool(identity["sessions"]) == (identity["kind"] == "role"), "role sessions/user binding")
        require(d["principals"]["reader"]["unique_id"] != d["principals"]["writer"]["unique_id"],
                "distinct persistent principals, not role sessions")
        require(type(d["grants"]) is dict and len(d["grants"]) <= 32, "standing grants")
        for purpose, closures in d["grants"].items():
            token(purpose, "purpose")
            require(type(closures) is list and len(closures) <= p.max_members * p.max_cycles + 2, "grant scope")
            for closure in closures:
                if closure not in (None, "*"):
                    sha(closure)
        shape(d["rpc"], "max_wallets max_attempts max_response_bytes request_quote byte_quote max_cash", "selected RPC limits")
        for name, value in d["rpc"].items():
            natural(value, "selected RPC " + name, True)
        require(type(d["seeds"]) is dict and bool(d["seeds"]), "explicit prepaid discovery seeds")
        anchor = cls(str(Path(path)), expected_digest, expected_owner, expected_executor, d, p)
        for wid, wallet in d["seeds"].items():
            anchor.wallet(wid, wallet)
        anchor.cash(d["seeds"], 0, {})
        if d["migration"] is not None:
            shape(d["migration"], "source authority_digest", "explicit migration consent")
            Ref.parse(d["migration"]["source"], p)
            sha(d["migration"]["authority_digest"])
        return anchor

    @property
    def journal(self):
        return self.data["executors"][self.executor]["journal"]

    def live(self, now):
        require(natural(now, "trusted clock") < self.data["expires"], "enrollment expired")
        raw = private_bytes(self.path, self.owner, 131072)
        require(os.getuid() == self.owner and digest(raw) == self.sha256, "anchor/owner changed")

    def wallet(self, wid, w):
        token(wid, "wallet ID")
        shape(w, "parent executor principal fence expires attempts response_bytes charge year methods purposes", "wallet shape")
        require(w["executor"] in self.data["executors"] and w["principal"] in {"reader", "writer"}, "wallet executor/principal")
        require(w["parent"] is None or isinstance(w["parent"], str), "wallet parent")
        if w["parent"] is not None:
            token(w["parent"], "wallet parent")
        for name in ("fence", "expires", "attempts", "response_bytes", "charge", "year"):
            natural(w[name], "wallet " + name, True)
        require(w["expires"] <= self.data["expires"] and w["attempts"] <= self.data["rpc"]["max_attempts"]
                and w["response_bytes"] <= self.data["rpc"]["max_response_bytes"], "wallet caps/term")
        quote = self.data["rpc"]
        require(w["charge"] == w["attempts"] * (quote["request_quote"] +
                w["response_bytes"] * quote["byte_quote"]), "full wallet escrow quote")
        require(type(w["methods"]) is list and bool(w["methods"]) and set(w["methods"]) <= RPC_METHODS,
                "wallet method scope")
        require(type(w["purposes"]) is list and bool(w["purposes"]), "wallet purpose scope")
        for purpose in w["purposes"]:
            token(purpose, "wallet purpose")
        return w

    def cash(self, wallets, payload, annual):
        require(type(wallets) is dict and len(wallets) <= self.data["rpc"]["max_wallets"], "bounded wallet ledger")
        total, years = 0, {}
        for wid, w in wallets.items():
            self.wallet(wid, w)
            total += w["charge"]
            years[str(w["year"])] = years.get(str(w["year"]), 0) + w["charge"]
            require(w["parent"] is None and wid in self.data["seeds"] or w["parent"] in wallets,
                    "funded parent/seed required")
            require(w["parent"] != wid, "wallet cannot fund itself")
            seen, parent = {wid}, w["parent"]
            while parent is not None:
                require(parent not in seen, "wallet ancestry cycle")
                seen.add(parent)
                parent = wallets[parent]["parent"]
        require(total <= self.data["rpc"]["max_cash"], "RPC cash cap")
        p = self.policy
        require(total + payload + p.preservation_reserve_cash <= p.lifetime_cash, "combined lifetime cash")
        for year in set(years) | set(annual):
            require(years.get(year, 0) + annual.get(year, 0) + p.preservation_reserve_cash <= p.annual_cash,
                    "combined original-year cash")


def journal_genesis(anchor):
    """Pure enrollment artifact builder; never installs or resets a journal."""
    return canonical(dict(schema=1, enrollment=anchor.sha256, executor=anchor.executor,
                          journal=anchor.journal["id"], wallets=anchor.data["seeds"], attempts={}))


class AttemptJournal:
    """Fully escrowed local consumption WAL. Missing/restored journals need recovery.

    No automatic initialization or old-counter restoration exists here. The
    protected executor must not roll this file back; a cold recovery burns old
    wallets and uses a separately surviving enrolled journal/seed.
    """
    def __init__(self, anchor):
        self.anchor = anchor
        self.path = Path(anchor.journal["path"])
        parent = self.path.parent
        info = parent.stat()
        require(parent.resolve(strict=True) == parent and info.st_uid == anchor.owner
                and stat.S_IMODE(info.st_mode) == 0o700 and info.st_dev == anchor.journal["device"]
                and info.st_ino == anchor.journal["inode"], "protected journal directory/device/inode")
        self._read()  # Never create a missing journal from a copied anchor.

    def _read(self):
        d = decode(private_bytes(self.path, self.anchor.owner, self.anchor.journal["max_bytes"]))
        shape(d, "schema enrollment executor journal wallets attempts", "journal schema")
        require(type(d["schema"]) is int and d["schema"] == 1 and d["enrollment"] == self.anchor.sha256
                and d["executor"] == self.anchor.executor and d["journal"] == self.anchor.journal["id"],
                "journal protected binding")
        self.anchor.cash(d["wallets"], 0, {})
        require(all(d["wallets"].get(wid) == w for wid, w in self.anchor.data["seeds"].items()), "journal seed binding")
        require(type(d["attempts"]) is dict, "journal attempts")
        for wid, records in d["attempts"].items():
            require(wid in d["wallets"] and type(records) is list
                    and len(records) <= d["wallets"][wid]["attempts"], "spent wallet count")
            for rec in records:
                shape(rec, "request state details", "attempt record")
                sha(rec["request"])
                require(rec["details"] is None or type(rec["details"]) is dict, "safe attempt details")
                if rec["details"] is not None:
                    require(digest(canonical(rec["details"])) == rec["request"], "attempt detail digest")
                require(rec["state"] in {"ATTEMPTING", "RETURNED", "UNKNOWN"}, "attempt state")
        return d

    def _locked(self, action):
        lock = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(lock)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == self.anchor.owner
                    and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1, "journal lock binding")
            fcntl.flock(lock, fcntl.LOCK_EX)
            d = self._read()
            result = action(d)
            data = canonical(d)
            require(len(data) <= self.anchor.journal["max_bytes"], "journal full, no send")
            fd, temp = tempfile.mkstemp(prefix=".custody-", dir=self.path.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp, self.path)
                directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            return result
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            os.close(lock)

    def register(self, authority, wid):
        # A wallet can only be learned from a verified CURRENT CTRL, not caller JSON.
        pending, parent = {}, wid
        while parent is not None:
            w = copy.deepcopy(authority.wallet(parent))
            require(parent not in pending, "wallet parent cycle")
            pending[parent] = w
            parent = w["parent"]
        def change(d):
            for key, w in pending.items():
                require(key not in d["wallets"] or d["wallets"][key] == w, "wallet immutable")
                d["wallets"][key] = w
        self._locked(change)

    def available(self, wid, wallet):
        d = self._read()
        require(wallet["executor"] == self.anchor.executor and d["wallets"].get(wid) == wallet,
                "selected executor registered wallet")
        require(len(d["attempts"].get(wid, [])) < wallet["attempts"], "wallet exhausted before client")

    def claim(self, wid, wallet, request):
        def consume(d):
            require(wallet["executor"] == self.anchor.executor and d["wallets"].get(wid) == wallet,
                    "wallet not durably registered for this executor")
            records = d["attempts"].setdefault(wid, [])
            require(len(records) < wallet["attempts"], "wallet exhausted")
            details = copy.deepcopy(request) if type(request) is dict else None
            request_digest = digest(canonical(details)) if details is not None else sha(request)
            records.append(dict(request=request_digest, state="ATTEMPTING", details=details))
            return len(records) - 1
        return self._locked(consume)

    def finish(self, wid, index, state):
        require(state in {"RETURNED", "UNKNOWN"}, "outcome")
        def update(d):
            d["attempts"][wid][index]["state"] = state
        self._locked(update)


class EnrollmentAuthority:
    def __init__(self, anchor, clock):
        self.anchor, self.clock = anchor, clock
        self.observation, self.state = None, None
        self.local = threading.local()
        self.last_time = 0

    def now(self):
        t = natural(self.clock(), "trusted integration clock")
        require(t >= self.last_time, "integration clock rollback")
        self.last_time = t
        self.anchor.live(t)
        return t

    def begin(self, purpose, closure=None):
        self.local.purpose, self.local.closure = purpose, closure

    def context(self):
        return getattr(self.local, "purpose", "discover"), getattr(self.local, "closure", None)

    def current(self):
        try:
            now = self.now()
            require(self.state is not None and now < self.state["integration"]["expires"], "current authority absent/expired")
            return replace(self.anchor.policy, minimum_sequence=max(self.anchor.policy.minimum_sequence,
                           self.state["integration"]["floor"]))
        except (Hold, OSError):
            return None

    def permits(self, purpose, closure):
        if self.current() is None:
            return False
        h = self.state["integration"]
        scope = self.anchor.data["grants"].get(purpose, [])
        if closure not in scope and "*" not in scope:
            return False
        if any(r["purpose"] in {purpose, "*"} and r["closure"] in {closure, "*"} for r in h["revoked"]):
            return False
        if purpose == "screened":
            proof = h["screened"].get(closure)
            return proof is not None and proof["policy"] == self.anchor.data["screening"] and self.now() < proof["expires"]
        return True

    def validate_integration(self, s, *, current=True):
        h = s["integration"]
        shape(h, "enrollment fence expires floor revoked screened wallets", "integration schema")
        require(h["enrollment"] == self.anchor.sha256, "protected enrollment root")
        for name in ("fence", "expires", "floor"):
            natural(h[name], "authority " + name, name != "floor")
        require(h["expires"] <= self.anchor.data["expires"] and h["floor"] <= s["sequence"], "authority limits")
        require(type(h["revoked"]) is list and len(h["revoked"]) <= self.anchor.policy.max_mutations,
                "bounded revocation list")
        for item in h["revoked"]:
            shape(item, "purpose closure", "revocation shape")
            token(item["purpose"], "revocation purpose")
            if item["closure"] not in (None, "*"):
                sha(item["closure"])
        require(type(h["screened"]) is dict and len(h["screened"]) <= self.anchor.policy.max_members * self.anchor.policy.max_cycles,
                "bounded exact screening")
        for closure, proof in h["screened"].items():
            sha(closure)
            shape(proof, "policy expires", "screening proof")
            require(proof["policy"] == self.anchor.data["screening"], "selected privacy policy")
            natural(proof["expires"], "screening expiry", True)
        self.anchor.cash(h["wallets"], s["lifetime"], s["annual"])
        for wid, w in self.anchor.data["seeds"].items():
            require(h["wallets"].get(wid) == w, "seed escrow cannot disappear/change")
        if current:
            require(s["sequence"] >= max(self.anchor.policy.minimum_sequence, h["floor"]), "CURRENT authority rollback")
            if self.state is not None:
                require(h["fence"] >= self.state["integration"]["fence"] and h["floor"] >= self.state["integration"]["floor"],
                        "observed fence/floor rollback")

    def ingest(self, observation):
        p, now = self.anchor.policy, self.now()
        observation.protected(p, now + p.floor_seconds, p.max_control_bytes)
        require(observation.ref.key == p.ctrl_key, "fixed CURRENT locator")
        s = decode(observation.body)
        require(s.get("schema") == 2 and type(s.get("schema")) is int, "explicit schema1 migration required")
        Custody(self, lambda _: None, self.clock)._validate(s, p)
        self.observation, self.state = observation, s

    def wallet(self, wid):
        require(self.state is not None and wid in self.state["integration"]["wallets"], "unverified wallet")
        return self.state["integration"]["wallets"][wid]


@dataclass(frozen=True)
class CredentialBundle:
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    session_token: str | None = field(repr=False)
    expires: int

    def valid(self, now):
        require(isinstance(self.access_key, str) and bool(self.access_key)
                and isinstance(self.secret_key, str) and bool(self.secret_key)
                and (self.session_token is None or isinstance(self.session_token, str)), "explicit credential bundle")
        require(natural(self.expires, "credential expiry", True) > now, "credential bundle expired")


def boto_client(service, bundle, policy):
    """Lazy actual SDK source. Explicit material only; no provider hook or chain."""
    require(service in {"sts", "s3"}, "service")
    import boto3
    from botocore.config import Config
    session = boto3.Session(aws_access_key_id=bundle.access_key, aws_secret_access_key=bundle.secret_key,
                            aws_session_token=bundle.session_token, region_name=policy.region)
    return session.client(service, region_name=policy.region, endpoint_url="https://" + service + "." + policy.region + ".amazonaws.com",
            verify=True, config=Config(signature_version="s3v4" if service == "s3" else "v4",
                connect_timeout=policy.transport_seconds, read_timeout=policy.transport_seconds,
                retries={"mode": "standard", "total_max_attempts": 1}, ignore_configured_endpoint_urls=True,
                proxies={}))


class AttemptGate:
    """Every SDK invocation consumes a durable, wholly prepaid slot first."""
    def __init__(self, authority, journal, wallets):
        self.authority, self.journal, self.wallet_ids = authority, journal, dict(wallets)
        require(set(wallets) <= {"reader", "writer"}, "explicit per-principal wallets")
        self.bindings, self.guards = {}, threading.local()
        self.response_versions = set()
        self.migration = None

    def arm_write(self, guard):
        require(callable(guard), "write predicate")
        self.guards.write = guard

    def _wallet(self, role):
        require(role in self.wallet_ids, "principal wallet unavailable")
        wid = self.wallet_ids[role]
        if self.authority.state is None:
            w = self.authority.anchor.data["seeds"].get(wid)
            require(w is not None, "no prepaid discovery seed")
        else:
            w = self.authority.wallet(wid)
        require(w["principal"] == role and w["executor"] == self.authority.anchor.executor, "wallet principal/executor")
        return wid, w

    def _guard(self, role, method, params, bundle):
        a, p = self.authority, self.authority.anchor.policy
        now = a.now()
        bundle.valid(now)
        wid, w = self._wallet(role)
        require(now < w["expires"] and method in w["methods"], "wallet expiry/method")
        purpose, closure = ("identity", None) if method == "get_caller_identity" else a.context()
        require(purpose in w["purposes"], "wallet purpose")
        if method == "get_caller_identity":
            require(not params, "identity request parameters")
            require(None in a.anchor.data["grants"].get("identity", []) or "*" in a.anchor.data["grants"].get("identity", []),
                    "selected identity discovery grant")
            require(a.state is None or a.permits("identity", None), "current identity revoked")
            return wid, w
        base = {"Bucket", "Key", "ExpectedBucketOwner"}
        allowed = base | ({"VersionId"} if method in READ_METHODS else
                {"Body", "ContentLength", "ChecksumSHA256", "ServerSideEncryption", "StorageClass",
                 "ObjectLockMode", "ObjectLockRetainUntilDate", "ObjectLockLegalHoldStatus", "IfMatch", "IfNoneMatch"}
                if method == "put_object" else {"VersionId", "Retention"})
        require(base <= set(params) <= allowed, "SDK parameter allowlist")
        if method in {"get_object_retention", "get_object_legal_hold", "put_object_retention"}:
            require(isinstance(params.get("VersionId"), str), "exact protection version")
        if method == "put_object":
            body = params.get("Body")
            require(type(body) is bytes and params.get("ContentLength") == len(body)
                    and params.get("ChecksumSHA256") == base64.b64encode(hashlib.sha256(body).digest()).decode("ascii")
                    and params.get("ServerSideEncryption") == "AES256" and params.get("StorageClass") == "STANDARD"
                    and params.get("ObjectLockMode") == "COMPLIANCE" and params.get("ObjectLockLegalHoldStatus") == "ON",
                    "exact protected PUT parameters")
        if method == "put_object_retention":
            shape(params["Retention"], "Mode RetainUntilDate", "renewal parameter allowlist")
            require(params["Retention"]["Mode"] == "COMPLIANCE", "COMPLIANCE renewal")
        require(role in self.bindings and self.bindings[role] is bundle, "unbound/replaced credential material")
        require(params.get("Bucket") == p.bucket and params.get("ExpectedBucketOwner") == p.account,
                "fixed destination/owner")
        key = params.get("Key")
        Ref(key, params.get("VersionId", "pending"), "0" * 64, 0).validate(p)
        migration_write = a.state is None and method == "put_object" and purpose == "migrate"
        if a.state is None:
            require(None in a.anchor.data["grants"].get(purpose, []) or "*" in a.anchor.data["grants"].get(purpose, []),
                    "selected bootstrap purpose grant")
            if migration_write:
                require(role == "writer" and self.migration is not None and key == p.ctrl_key
                        and (None in a.anchor.data["grants"].get("migrate", []) or "*" in a.anchor.data["grants"].get("migrate", [])),
                        "explicit migration bootstrap grant")
                source, body = self.migration
                require(params.get("IfMatch") == source.etag and params.get("Body") == body,
                        "exact consented migration CAS only")
            else:
                require(purpose == "discover" and method in READ_METHODS and key == p.ctrl_key,
                        "bootstrap only fixed read discovery")
                require(params.get("VersionId") is None or (key, params["VersionId"]) in self.response_versions,
                        "actual discovery response version")
        else:
            require(a.permits(purpose, closure), "current operation revoked")
            if key == p.ctrl_key and params.get("VersionId") is not None:
                known = a.state["controls"] + [a.observation.ref.wire()]
                require(any(r["version"] == params["VersionId"] and r["key"] == key for r in known)
                        or (key, params["VersionId"]) in self.response_versions, "registered CTRL version")
            if key != p.ctrl_key:
                issued = [x for x in a.state["ledger"].values() if x["key"] == key]
                refs = a.state["controls"] + [a.state["baseline"]["origin"]["frontier"]] if a.state["baseline"] else a.state["controls"]
                exact = any(r["key"] == key and r["version"] == params.get("VersionId") for r in refs)
                exact |= (key, params.get("VersionId")) in self.response_versions
                require(bool(issued) or exact, "unregistered object/reference")
                if params.get("VersionId") is not None and issued:
                    require(any(x["ref"] is not None and x["ref"]["version"] == params["VersionId"] for x in issued)
                            or (key, params["VersionId"]) in self.response_versions, "exact registered version")
        if method in WRITE_METHODS and migration_write:
            require(callable(getattr(self.guards, "write", None)), "migration write not armed")
            self.guards.write()
        elif method in WRITE_METHODS:
            require(role == "writer" and a.state is not None and w["fence"] == a.state["integration"]["fence"],
                    "current writer fence")
            require(purpose != "discover" and callable(getattr(self.guards, "write", None)), "write not armed")
            if closure is not None and purpose in {"intake", "upload", "accept", "revalidate"}:
                require(a.permits("screened", closure), "screening revoked at wire")
            self.guards.write()
            if method == "put_object":
                body = params.get("Body")
                require(type(body) is bytes, "exact bytes only")
                if key == p.ctrl_key:
                    require(params.get("IfMatch") == a.observation.etag, "current CAS ETag")
                    candidate = decode(body)
                    require(candidate.get("schema") == 2 and candidate["sequence"] == a.state["sequence"] + 1,
                            "explicit schema2 current transition")
                    Custody(a, lambda _: None, a.clock)._validate(candidate, p)
                    if purpose == "fund-wallet":
                        old, new = a.state["integration"], candidate["integration"]
                        require(all(new[k] == old[k] for k in old if k not in {"wallets", "fence"}),
                                "funding cannot change authority/screening")
                        require(set(new["wallets"]) > set(old["wallets"]) and len(new["wallets"]) == len(old["wallets"]) + 1
                                and all(new["wallets"][k] == v for k, v in old["wallets"].items()), "immutable wallet append")
                    else:
                        require(candidate["integration"] == a.state["integration"], "custody cannot grant authority")
                else:
                    require(params.get("IfNoneMatch") == "*" and any(x["key"] == key and x["sha256"] == digest(body)
                            and x["size"] == len(body) for x in a.state["ledger"].values()), "issued exact PUT")
        return wid, w

    def call(self, role, client, method, params, bundle):
        require(method in RPC_METHODS, "SDK operation not enrolled")
        wid, w = self._guard(role, method, params, bundle)
        safe = {k: (dict(sha256=digest(v), size=len(v)) if k == "Body" and type(v) is bytes
                else v.isoformat() if isinstance(v, datetime) else v) for k, v in params.items()}
        purpose, closure = ("identity", None) if method == "get_caller_identity" else self.authority.context()
        intended = {}
        if method == "put_object" and purpose == "fund-wallet":
            proposed = decode(params["Body"])["integration"]["wallets"]
            intended = {k: v for k, v in proposed.items() if k not in self.authority.state["integration"]["wallets"]}
        request = dict(method=method, role=role, params=safe, purpose=purpose, closure=closure,
                       fence=w["fence"], wallets=intended)
        index = self.journal.claim(wid, w, request)  # fsync BEFORE wire, including identity/discovery
        try:
            self._guard(role, method, params, bundle)  # revocation/time/refence during fsync
            result = getattr(client, method)(**params)
            if method == "get_object":
                size = result.get("ContentLength")
                if type(size) is not int or not 0 <= size <= w["response_bytes"]:
                    if "Body" in result:
                        result["Body"].close()
                    raise Hold("wallet response cap")
        except BaseException:
            # Even KeyboardInterrupt/SystemExit after durable issue cannot refund.
            self.journal.finish(wid, index, "UNKNOWN")
            raise
        finally:
            if method in WRITE_METHODS:
                self.guards.write = None
        if method == "get_object" and isinstance(result.get("VersionId"), str):
            self.response_versions.add((params["Key"], result["VersionId"]))
        try:
            self.journal.finish(wid, index, "RETURNED")
        except BaseException:
            if method == "get_object" and "Body" in result:
                result["Body"].close()
            raise
        return result


class MeteredClient:
    def __init__(self, role, client, bundle, gate):
        self.role, self.client, self.bundle, self.gate = role, client, bundle, gate
        self.meta = client.meta

    def __getattr__(self, method):
        require(method in RPC_METHODS, "unsupported metered SDK method")
        return lambda **params: self.gate.call(self.role, self.client, method, params, self.bundle)


class CredentialBinder:
    def __init__(self, gate, client_factory=boto_client):
        self.gate, self.factory = gate, client_factory
        self.clients = []

    def bind(self, role, bundle):
        require(role in {"reader", "writer"} and type(bundle) is CredentialBundle, "selected explicit credential role")
        a, p = self.gate.authority, self.gate.authority.anchor.policy
        a.anchor.live(a.now())
        bundle.valid(a.now())
        wid, wallet = self.gate._wallet(role)
        require(self.gate.authority.now() < wallet["expires"] and "identity" in wallet["purposes"]
                and "get_caller_identity" in wallet["methods"], "identity allowance absent/expired")
        self.gate.journal.available(wid, wallet)  # no client if no enrolled prepaid allowance
        sts = self.factory("sts", bundle, p)
        self.clients.append(sts)
        require(sts.meta.region_name == p.region and sts.meta.endpoint_url == "https://sts." + p.region + ".amazonaws.com"
                and sts.meta.config.retries.get("total_max_attempts") == 1, "fixed no-retry identity endpoint")
        try:
            identity = self.gate.call(role, sts, "get_caller_identity", {}, bundle)
        finally:
            sts.close()
            self.clients.remove(sts)
        bundle.valid(a.now())
        self.gate._guard(role, "get_caller_identity", {}, bundle)
        self.gate.journal.available(wid, wallet)
        expected = a.anchor.data["principals"][role]
        require(type(identity) is dict and identity.get("Account") == p.account, "actual caller account mismatch")
        if expected["kind"] == "user":
            match = identity.get("Arn") == expected["arn"] and identity.get("UserId") == expected["unique_id"]
        else:
            role_name = expected["arn"].rsplit("/", 1)[-1]
            prefix = "arn:aws:sts::" + p.account + ":assumed-role/" + role_name + "/"
            arn, userid = identity.get("Arn"), identity.get("UserId")
            session = arn[len(prefix):] if isinstance(arn, str) and arn.startswith(prefix) else None
            match = session in expected["sessions"] and userid == expected["unique_id"] + ":" + session if session else False
        require(match, "actual stable principal/session mismatch")
        # Same immutable object is passed to STS and S3; refresh/default-chain substitution is forbidden.
        self.gate.bindings[role] = bundle
        s3 = self.factory("s3", bundle, p)
        self.clients.append(s3)
        return MeteredClient(role, s3, bundle, self.gate)

    def close(self):
        for client in self.clients:
            client.close()


class IntegratedStore:
    def __init__(self, authority, gate, raw):
        self.authority, self.gate, self.raw = authority, gate, raw

    def current(self):
        observation = self.raw.current()
        self.authority.ingest(observation)
        return observation

    def read(self, ref):
        return self.raw.read(ref)

    def latest(self, key, cap):
        return self.raw.latest(key, cap)

    def arm_write(self, guard):
        self.gate.arm_write(guard)

    def cas(self, previous, body, horizon):
        return self.raw.cas(previous, body, horizon)

    def put(self, key, body, horizon):
        return self.raw.put(key, body, horizon)

    def extend(self, ref, horizon):
        return self.raw.extend(ref, horizon)


def prepare_schema2(anchor, source, integration):
    """Explicit exact-source migration builder. It does not send/install anything.

    Consent pins the source and integration WITHOUT the enrollment digest, avoiding
    a digest self-reference. The resulting full bytes are deterministic after the
    owner anchor is fixed. A runtime migration executor is deliberately not a CLI.
    """
    consent = anchor.data["migration"]
    require(consent is not None and Ref.parse(consent["source"], anchor.policy) == source.ref,
            "explicit exact-source migration consent required")
    require(type(integration) is dict and "enrollment" not in integration
            and digest(canonical(integration)) == consent["authority_digest"], "exact migration authority template")
    source.protected(anchor.policy, 0, anchor.policy.max_control_bytes)
    original = decode(source.body)
    require(original.get("schema") == 1, "schema1 migration source")
    validator = Custody(EnrollmentAuthority(anchor, lambda: 0), lambda _: None, lambda: 0)
    validator._validate(original, anchor.policy)
    migrated = copy.deepcopy(original)
    migrated.update(schema=2, integration=dict(copy.deepcopy(integration), enrollment=anchor.sha256))
    # Advancing the actual frontier is explicit; historical refs/bodies are untouched.
    migrated["sequence"] += 1
    migrated["mutations"] += 1
    migrated["controls"].append(source.ref.wire())
    migrated["last_operation"] = "explicit-schema2-migration"
    validator._validate(migrated, anchor.policy)
    data = canonical(migrated)
    require(len(data) <= anchor.policy.max_control_bytes, "migration control cap")
    return data


class CustodyRuntime:
    """Explicit source factory, no credential acquisition or public runtime CLI."""
    def __init__(self, anchor, journal, clock, wallet_ids, bundles, *, client_factory=boto_client):
        require(type(anchor) is Enrollment and journal.anchor == anchor, "protected runtime enrollment")
        self.authority = EnrollmentAuthority(anchor, clock)
        self.authority.now()
        self.gate = AttemptGate(self.authority, journal, wallet_ids)
        self.binder = CredentialBinder(self.gate, client_factory)
        self.reader = self.binder.bind("reader", bundles["reader"])
        self.writer = None
        self.raw = S3Store(anchor.policy, None, self.reader, writer_identity=None,
                           reader_identity=anchor.policy.reader, read_only=True)
        self.store = IntegratedStore(self.authority, self.gate, self.raw)
        self.custody = Custody(self.authority, lambda _: self.store, clock)

    def migrate_schema1(self, integration, writer_bundle):
        """Explicit selected consent only; never called by cold recovery or main."""
        a, p = self.authority, self.authority.anchor.policy
        require(a.state is None, "migration only before schema2 binding")
        a.begin("discover")
        source = self.raw.current()
        data = prepare_schema2(a.anchor, source, integration)
        writer = self.binder.bind("writer", writer_bundle)
        raw = S3Store(p, writer, self.reader, writer_identity=p.writer, reader_identity=p.reader)
        # Fresh actual source reread BEFORE burning the final migration write slot.
        a.begin("discover")
        current = raw.current()
        require(current.ref == source.ref and current.etag == source.etag, "migration source no longer CURRENT")
        started = a.now()
        def final():
            now = a.now()
            require(started <= now <= started + p.proof_seconds, "migration proof expired")
            current.protected(p, now + p.floor_seconds, p.max_control_bytes)
        self.gate.migration = (source, data)
        a.begin("migrate")
        self.gate.arm_write(final)
        raw.cas(source, data, decode(data)["control_horizon"])
        self.writer, self.raw, self.store.raw = writer, raw, raw
        self.gate.migration = None
        return self.cold_recover()

    def cold_recover(self):
        self.authority.begin("discover")
        self.store.current()  # actual fixed CURRENT bytes/version/protection, never old checkpoint
        return self.custody.resolve_current()  # SAME current-floor/history/phase reader

    def enable_writer(self, bundle):
        require(self.authority.current() is not None, "recover CURRENT before writer binding")
        self.writer = self.binder.bind("writer", bundle)
        p = self.authority.anchor.policy
        self.raw = S3Store(p, self.writer, self.reader, writer_identity=p.writer, reader_identity=p.reader)
        self.store.raw = self.raw

    def reserve_wallet(self, wid, wallet, *, new_fence):
        """Fresh CAS paid by existing coordination slots; unknown ACK never refunds.

        No active slot/journal => no allocation. Caller supplies selected finite
        values; no new executor/principal or grant is enrolled by this operation.
        """
        c, a = self.custody, self.authority
        p, now, st, ob, s = c._open("fund-wallet")
        h = s["integration"]
        require(wid not in h["wallets"] and wallet["parent"] in h["wallets"], "new parent-funded wallet")
        parent = h["wallets"][wallet["parent"]]
        require(wallet["parent"] in self.gate.wallet_ids.values(), "active coordination parent")
        require(parent["fence"] == h["fence"] and now < parent["expires"], "current parent coordination authority")
        require(type(new_fence) is int and new_fence in {h["fence"], h["fence"] + 1}
                and wallet["fence"] == new_fence, "bounded explicit refence")
        if new_fence != h["fence"]:
            require(a.permits("refence", None), "separate current refence grant")
        a.anchor.wallet(wid, wallet)
        require(wallet["year"] == datetime.fromtimestamp(now, timezone.utc).year and now < wallet["expires"], "new wallet dates")
        h["wallets"][wid], h["fence"] = copy.deepcopy(wallet), new_fence
        def check():
            fresh = a.now()
            require(now <= fresh < min(parent["expires"], wallet["expires"]), "allocation time expired")
            if new_fence != a.state["integration"]["fence"]:
                require(a.permits("refence", None), "refence revoked")
        c._commit(p, now, st, ob, s, "fund-wallet", "reserve-wallet", final_check=check)
        # No registration from CAS reply. Exact current readback is mandatory.
        self.authority.begin("discover")
        self.store.current()
        self.gate.journal.register(a, wid)

    def use_wallet(self, role, wid):
        w = self.authority.wallet(wid)
        require(w["principal"] == role and w["executor"] == self.authority.anchor.executor, "selected wallet role/executor")
        self.gate.journal.register(self.authority, wid)
        self.gate.journal.available(wid, w)
        self.gate.wallet_ids[role] = wid

    def close(self):
        self.binder.close()

def main():
    print("HOLD: selected protected enrollment/executor and runtime facade required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
