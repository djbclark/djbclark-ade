#!/usr/bin/env python3
"""Finite storage-custody pilot. No enrollment, deployment or runtime authority.

ProtectedAuthority is an existing-controller trust boundary, NOT a JSON flag or
receipt authenticator. Importing this module never loads an AWS SDK or client.
The production S3 port is explicit; this module has no provisioning/apply CLI.
"""
from __future__ import annotations

import base64
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
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
        p = self.authority.current()
        require(type(p) is Policy, "unenrolled")
        p.validate()
        require(self.authority.permits(purpose, closure) is True, "current authority denies " + purpose)
        now = natural(self.clock(), "trusted clock")
        store = self.factory(p)
        obs = store.current()
        obs.protected(p, now, p.max_control_bytes)
        s = decode(obs.body)
        self._validate(s, p)
        return p, now, store, obs, s

    def _validate(self, s, p):
        require(type(s) is dict and set(s) == set(genesis(p, 0)), "CTRL schema")
        require(s["schema"] == 1 and s["identity"] == p.identity
                and s["generation"] == p.generation and s["policy"] == p.policy_digest
                and s["contract"] == p.contract_digest, "protected CTRL enrollment binding")
        for k in ("sequence", "mutations", "lifetime", "control_horizon"):
            natural(s[k], k)
        require(s["sequence"] >= p.minimum_sequence and s["mutations"] <= p.max_mutations,
                "rollback floor/control pool")
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

    def _stable(self, p, store, obs, purpose, closure=None):
        require(self.authority.current() == p and self.authority.permits(purpose, closure) is True,
                "authority/revocation changed")
        latest = store.current()
        latest.protected(p, obs.until, p.max_control_bytes)
        require(latest.ref == obs.ref and latest.etag == obs.etag, "current CTRL changed")

    def _commit(self, p, now, store, obs, s, purpose, operation, closure=None):
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
        self._validate(s, p)
        data = canonical(s)
        require(len(data) <= p.max_control_bytes, "bounded catalogue/control shard full; intake HOLD")
        # A lost reply has no refund/retry path. Refetch current CTRL on next invocation.
        store.cas(obs, data, s["control_horizon"])

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
        require(horizon >= now + p.floor_seconds, "admission floor")
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
        self._commit(p, now, st, ob, s, "intake", ticket, closure)
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
        self._commit(p, now, st, ob, s, "intake", "ready", q["closure"])

    def _verify_record(self, p, now, st, s, q, baseline=False):
        require(q is not None and q["phase"] == ("ACCEPTED" if baseline else "READY"), "phase pending/held")
        require(self.authority.permits("baseline" if baseline else "accept", q["closure"]) is True,
                "current closure revoked")
        c = q["cycles"][-1]
        require(baseline or c["t0"] <= now <= c["deadline"], "cycle expired/clock rollback")
        horizon = max(c["horizon"], now + p.floor_seconds)
        st.current().protected(p, horizon, p.max_control_bytes)
        if baseline:
            origin = st.read(Ref.parse(q["origin"]["frontier"], p))
            origin.protected(p, now, p.max_control_bytes)
            prior = decode(origin.body)
            self._validate(prior, p)
            expected = copy.deepcopy(q)
            expected["phase"], expected["origin"] = "READY", None
            require(prior["proposal"] == expected and c["t0"] <= q["origin"]["observed_at"] <= c["deadline"],
                    "accepted origin is not the protected READY frontier")
        require(sum(s["ledger"][a]["size"] for a in q["members"]) <= p.max_packet_bytes, "packet read cap")
        descriptors, bodies = [], []
        for atom in q["members"]:
            a = s["ledger"][atom]
            require(a["ref"] is not None, "unresolved closure atom")
            actual = st.read(Ref.parse(a["ref"], p)).protected(p, horizon, p.max_object_bytes)
            descriptors.append(dict(atom=atom, kind=a["kind"], sha256=a["sha256"], size=a["size"]))
            bodies.append((a["kind"], actual.body))
        require(closure_id(descriptors) == q["closure"], "exact closure")
        manifests = [decode(b) for kind, b in bodies if kind == "manifest"]
        expected = [d for d in descriptors if d["kind"] == "data"]
        require(len(manifests) == 1 and manifests[0] == {"schema": 1, "data": expected}, "data closure manifest")
        # Opaque data (including malformed negative fixtures) is hashed, never parsed/executed.
        for job in s["renewals"].values():
            require(job["done"] or now < job["due"], "missed original renewal deadline")
            if job["done"]:
                self._verify_census(job, s, p, st, now)
                require(0 < job["completed_at"] < job["due"], "late/unproved renewal completion")
                require(set(job["progress"]) == set(job["census"]), "raw done is not a complete census")
                for member in job["census"].values():
                    st.read(self._renew_ref(member, s, p)).protected(p, job["target"],
                            max(p.max_object_bytes, p.max_control_bytes))
        return q["closure"]

    def resolve_current(self):
        """Single reader for normal/recovery/terminal paths; failures are HOLD."""
        try:
            p, now, st, ob, s = self._open("read")
            outcomes = []
            reasons = []
            for baseline, record in ((True, s["baseline"]), (False, s["proposal"])):
                try:
                    self._verify_record(p, now, st, s, record, baseline)
                    outcomes.append("ACCEPTED" if baseline else "VERIFIED")
                except Exception as exc:
                    outcomes.append("HOLD")
                    reasons.append(str(exc))
            self._stable(p, st, ob, "read")
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
        closure = self._verify_record(p, now, st, s, q)
        self._stable(p, st, ob, "accept", closure)
        proof = VerifiedAcceptance(ob.ref.version, s["sequence"], closure, q["cycles"][-1]["id"], now, p.policy_digest)
        q["phase"] = "ACCEPTED"
        q["origin"] = dict(frontier=ob.ref.wire(), observed_at=now)
        s["baseline"] = copy.deepcopy(q)
        self._commit(p, now, st, ob, s, "accept", "accept", closure)
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
        self._commit(p, now, st, ob, s, "revalidate", cycle, q["closure"])

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
        self._validate(prior, p)
        expected = {"atom:" + a: dict(atom=a, ref=None) for a in prior["ledger"]}
        for r in prior["controls"] + [source_ref.wire()]:
            expected["ctrl:" + digest(canonical(r))] = dict(atom=None, ref=r)
        require(job["cutoff"] == prior["sequence"] and job["census"] == expected,
                "fixed census does not cover its exact protected source frontier")

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
        actual = st.read(ref).protected(p, now, cap)
        if actual.until < j["target"]:
            self._stable(p, st, ob, "preserve")
            st.extend(ref, j["target"])
        st.read(ref).protected(p, j["target"], cap)
        j["progress"][item] = now
        self._commit(p, now, st, ob, s, "preserve", "renew-progress")

    def renew_finish(self, renewal):
        p, now, st, ob, s = self._open("preserve")
        j = s["renewals"].get(renewal)
        require(j is not None and not j["done"] and now < j["due"], "renewal finish/date")
        self._verify_census(j, s, p, st, now)
        require(set(j["progress"]) == set(j["census"]), "incomplete fixed census")
        cap = max(p.max_object_bytes, p.max_control_bytes)
        for item, member in j["census"].items():
            require(0 <= now - j["progress"][item] <= p.proof_seconds, "expired census observation")
            st.read(self._renew_ref(member, s, p)).protected(p, j["target"], cap)
        # Latest CTRL carries complete issuance delta through this closing watermark.
        # Post-cutoff/newborn atoms retain their own immutable horizon and liability.
        for atom, a in s["ledger"].items():
            if "atom:" + atom not in j["census"]:
                require(a["horizon"] >= a["issued"] + p.floor_seconds, "newborn floor")
        j["done"] = True
        j["completed_at"] = now
        self._commit(p, now, st, ob, s, "preserve", "renew-finish")


class S3Store:
    """Real low-level S3 API port; caller provides separately enrolled clients.

    writer/reader clients MUST be bound to distinct persistent enrolled principals
    by the existing protected host. ExpectedBucketOwner checks destination, NOT
    caller identity. No STS/client/profile/default credential probing is performed.
    The supplied writer must have total_max_attempts=1: PUT uncertainty has no
    automatic retry. Use single-part bounded chunks, never managed multipart.
    """
    def __init__(self, policy: Policy, writer, reader, *, writer_identity, reader_identity):
        self.p = policy.validate()
        require(writer_identity == policy.writer and reader_identity == policy.reader
                and writer is not reader, "enrolled independent client binding")
        for client in (writer, reader):
            require(client.meta.region_name == policy.region, "client region")
            require(client.meta.config.retries.get("total_max_attempts") == 1, "no hidden SDK retries")
        self.writer, self.reader = writer, reader

    def _args(self, key, version=None):
        Ref(key, version or "pending", "0" * 64, 0).validate(self.p)
        args = dict(Bucket=self.p.bucket, Key=key, ExpectedBucketOwner=self.p.account)
        if version is not None:
            args["VersionId"] = version
        return args

    def _get(self, key, cap, version=None):
        response = self.reader.get_object(**self._args(key, version))
        body = response["Body"]
        try:
            length = natural(response.get("ContentLength"), "actual content length")
            require(length <= cap, "bounded transport")
            chunks, count = [], 0
            while True:
                chunk = body.read(min(1024 * 1024, cap - count + 1))
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
        actual = self.read(ref)
        require(actual.mode == "COMPLIANCE" and actual.hold == "ON" and horizon >= actual.until,
                "monotone COMPLIANCE renewal only")
        self.writer.put_object_retention(**self._args(ref.key, ref.version),
                Retention=dict(Mode="COMPLIANCE", RetainUntilDate=datetime.fromtimestamp(horizon, timezone.utc)))


def main():
    print("HOLD: custody source pilot; protected enrollment and controller integration unavailable")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
