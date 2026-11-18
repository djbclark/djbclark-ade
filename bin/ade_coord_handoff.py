"""Controlled local pilot retirement gate. No inferred remote process authority.

Native archive closes runtime by documented contract; explicit birth identities
and workspace census provide independent local exit evidence. Missing observables
block, never authorize takeover. Invoked by an external controller, not the dying
predecessor provider itself.
"""
from __future__ import annotations
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
from ade_coord import config, call, snapshot, metric, CoordinationError, _sibling
Resources = _sibling("ade_coord_resources").Resources
process_identity = _sibling("ade_coord_resources").process_identity
same_process = _sibling("ade_coord_resources").same_process
admission = _sibling("ade_coord_resources").admission

def native(*args):
    started = time.monotonic()
    try:
        argv = ["paseo", "daemon", "status", "--json"] if args == ("daemon-status",) else ["paseo", "agent", *args, "--json"]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=True)
        metric("native " + args[0], time.monotonic() - started, len(json.dumps(args)), len(result.stdout))
        return json.loads(result.stdout)
    except Exception:
        raise CoordinationError("NATIVE_RETIREMENT_UNKNOWN") from None

def census(path):
    try:
        result = subprocess.run(["lsof", "-t", "+D", path], capture_output=True, text=True, timeout=15)
        if result.returncode not in (0, 1) or result.stderr.strip():
            raise ValueError()
        return sorted({int(pid) for pid in result.stdout.split()})
    except Exception:
        raise CoordinationError("WORKSPACE_CENSUS_UNKNOWN") from None

def local_role_claims(role):
    module=_sibling("ade_claims");directory=module.claims_dir()
    if not directory.exists():return []
    try:
        if directory.is_symlink() or not directory.is_dir():raise ValueError()
        rows=[]
        for file in directory.iterdir():
            if file.suffix!=".json" or file.name.startswith("."):continue
            if file.is_symlink():raise ValueError()
            claim=module.read_claim(file.stem)
            if claim is None:raise ValueError()
            if "coordination" not in claim:continue
            marker=claim["coordination"]
            if not isinstance(marker,dict) or not isinstance(marker.get("role_id"),str) or not isinstance(marker.get("generation"),str):raise ValueError()
            if marker.get("role_id")==role and claim.get("state")=="active":rows.append(claim)
        return rows
    except Exception:
        raise CoordinationError("LOCAL_ROLE_CLAIM_CENSUS_UNKNOWN") from None


def transfer(request, *, cfg=None, native_call=native, inspect=process_identity, users=census, protocol=call):
    cfg = cfg or config(); role = request["role_id"]
    settings = cfg["roles"].get(role, {})
    if settings.get("controlled_pilot") is not True:
        raise CoordinationError("CONTROLLED_PILOT_REQUIRED")
    next_owner = request["next_owner"]
    root = Path(cfg["state_dir"]); root.mkdir(parents=True, mode=0o700, exist_ok=True)
    # One machine writer per role. Never hold a SQLite transaction across network.
    lock_fd = os.open(root / "handoff.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    db = None
    barrier = None
    barrier_entered = False
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        barrier = admission(root)
        barrier.__enter__()
        barrier_entered = True
        file = root / "handoff.sqlite"
        fd = os.open(file, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600); os.close(fd)
        db = sqlite3.connect(file, timeout=10)
        db.executescript("""PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
          CREATE TABLE IF NOT EXISTS handoffs(role TEXT PRIMARY KEY, intent TEXT NOT NULL, checkpoint BLOB NOT NULL, evidence TEXT);
          CREATE TABLE IF NOT EXISTS handoff_attempts(role TEXT,attempt TEXT,prior_epoch INTEGER NOT NULL,intent TEXT NOT NULL,checkpoint BLOB NOT NULL,evidence TEXT,status TEXT NOT NULL,result TEXT,PRIMARY KEY(role,attempt));
          CREATE UNIQUE INDEX IF NOT EXISTS one_unfinished_handoff ON handoff_attempts(role) WHERE status!='complete';""")
        # Preserve the old journal intact and migrate each attempt conservatively;
        # authoritative transfer/projection is reconciled before marking complete.
        with db:
            for legacy_role,packed,blob,proof in db.execute("SELECT role,intent,checkpoint,evidence FROM handoffs").fetchall():
                legacy=json.loads(packed)
                db.execute("INSERT OR IGNORE INTO handoff_attempts VALUES (?,?,?,?,?,?,'pending',NULL)",(legacy_role,legacy["attempt_id"],legacy["initial"]["record"]["ownership_epoch"],packed,blob,proof))
        attempt=request["attempt_id"]
        old=db.execute("SELECT intent,checkpoint,evidence,status,result FROM handoff_attempts WHERE role=? AND attempt=?",(role,attempt)).fetchone()
        if old:
            intent=json.loads(old[0]);checkpoint=bytes(old[1]);evidence=json.loads(old[2]) if old[2] else {}
            if intent["next_owner"] != next_owner:
                raise CoordinationError("EXISTING_HANDOFF_REQUIRES_SAME_ATTEMPT")
            if old[3]=="complete":
                # Historical retry may observe a later epoch. Never re-project its
                # old target or re-run native retirement/ownership changes.
                live=protocol("role get",{"role_id":role},cfg=cfg)
                return {"status":"already-complete","role":live,"attempt_result":json.loads(old[4]),"historical":True}
        else:
            if db.execute("SELECT attempt FROM handoff_attempts WHERE role=? AND status!='complete'",(role,)).fetchone():
                raise CoordinationError("UNFINISHED_HANDOFF_MUST_RECONCILE_FIRST")
            if next_owner not in settings.get("successors",[]):
                raise CoordinationError("SUCCESSOR_NOT_EXPLICITLY_ENROLLED")
            initial=protocol("role get",{"role_id":role},cfg=cfg)
            if initial["record"]["state"]!="active":
                raise CoordinationError("UNJOURNALED_LIFECYCLE_UNKNOWN")
            resource_free=settings.get("resource_free") is True
            local_bindings={key:value for key,value in cfg["claims"].items() if value["role_id"]==role}
            marked=local_role_claims(role)
            if resource_free and (initial["record"]["bindings"] or local_bindings or marked):
                raise CoordinationError("RESOURCE_FREE_SCOPE_MISMATCH")
            remote=any(next_owner[key]!=initial["record"]["owner"][key] for key in ("host","server"))
            if remote and not resource_free:
                raise CoordinationError("REMOTE_RESOURCE_ADAPTER_REQUIRED")
            with Path(request["checkpoint_path"]).open("rb") as stream:
                checkpoint=stream.read(12*1024*1024+1);os.fsync(stream.fileno())
            if len(checkpoint)>12*1024*1024:raise CoordinationError("CHECKPOINT_TOO_LARGE")
            intent={"initial":initial,"next_owner":next_owner,"attempt_id":attempt,"checkpoint_digest":hashlib.sha256(checkpoint).hexdigest(),"runtime":settings.get("runtime"),"resources":sorted(initial["record"]["bindings"]),"resource_free":resource_free}
            evidence={}
            with db:
                db.execute("INSERT INTO handoff_attempts VALUES (?,?,?,?,?,NULL,'pending',NULL)",(role,attempt,initial["record"]["ownership_epoch"],json.dumps(intent,sort_keys=True),checkpoint))
        def finish(current):
            with db:
                db.execute("UPDATE handoff_attempts SET status='transferred',result=? WHERE role=? AND attempt=?",(json.dumps(current,sort_keys=True),role,attempt))
            result=project(current,cfg)
            with db:
                db.execute("UPDATE handoff_attempts SET status='complete' WHERE role=? AND attempt=?",(role,attempt))
            return result
        initial = intent["initial"]; prior = initial["record"]
        if prior["generation"] != cfg["generation"] or prior["owner"]["host"] != cfg["identity"]["host"] or prior["owner"]["server"] != cfg["identity"]["server"]:
            raise CoordinationError("REMOTE_OR_STALE_GENERATION_RETIREMENT_BLOCKED")
        def save():
            with db:
                db.execute("UPDATE handoff_attempts SET evidence=? WHERE role=? AND attempt=?", (json.dumps(evidence,sort_keys=True), role, attempt))
        current = protocol("role get", {"role_id": role}, cfg=cfg)
        if current["record"]["owner"] == next_owner and current["record"]["ownership_epoch"] == prior["ownership_epoch"] + 1:
            if current["record"].get("handoff",{}).get("checkpoint_digest") != intent["checkpoint_digest"]:
                raise CoordinationError("UNKNOWN_TRANSFER_PROVENANCE")
            return finish(current)
        runtime = intent["runtime"]
        if not runtime or runtime.get("owner") != prior["owner"] or runtime.get("ownership_epoch") != prior["ownership_epoch"]:
            raise CoordinationError("BOUND_PROVIDER_RETIREMENT_CONTRACT_REQUIRED")
        for identity in runtime.get("processes", []):
            if type(identity.get("pid")) is not int or identity["pid"] <= 0 or type(identity.get("pgid")) is not int or identity["pgid"] <= 0 or not isinstance(identity.get("birth"),str) or not identity["birth"] or not isinstance(identity.get("boot"),str) or not identity["boot"]:
                raise CoordinationError("BOUND_PROVIDER_IDENTITY_INVALID")
        codex_contract = runtime.get("codex_close_contract")
        if not runtime.get("processes") and not codex_contract:
            raise CoordinationError("BOUND_PROVIDER_BIRTH_IDENTITIES_OR_AUDITED_CLOSE_REQUIRED")
        if codex_contract:
            manifest = json.loads(Path(cfg["generation_manifest"]).read_text())
            live = native_call("daemon-status")
            if live.get("daemonVersion") != codex_contract.get("daemon_version") or live.get("serverId") != codex_contract.get("server"):
                raise CoordinationError("RUNNING_DAEMON_CONTRACT_MISMATCH")
            if manifest.get("retirement_contract") != codex_contract or codex_contract.get("server") != prior["owner"]["server"] or codex_contract.get("provider") != "codex" or codex_contract.get("verified") is not True:
                raise CoordinationError("LIVE_DAEMON_CLOSE_CONTRACT_NOT_VERIFIED")
        resource_free=intent.get("resource_free",False)
        if resource_free != (settings.get("resource_free") is True):
            raise CoordinationError("RESOURCE_SCOPE_CHANGED_DURING_HANDOFF")
        if (next_owner["host"] != prior["owner"]["host"] or next_owner["server"] != prior["owner"]["server"]) and not resource_free:
            raise CoordinationError("REMOTE_RESOURCE_ADAPTER_REQUIRED")
        # Alias/enrollment mapping must already retain both old and new agent IDs.
        if any(cfg["aliases"].get(agent) != role for agent in (prior["owner"]["agent"],next_owner["agent"])):
            raise CoordinationError("PERSISTED_ROLE_ALIASES_REQUIRED")
        if next_owner not in settings.get("successors",[]):
            raise CoordinationError("SUCCESSOR_NO_LONGER_ENROLLED")
        if current["record"]["owner"] != prior["owner"] or current["record"]["ownership_epoch"] != prior["ownership_epoch"]:
            raise CoordinationError("HANDOFF_AUTHORITY_CHANGED")
        if current["record"]["state"] == "active":
            if current != initial:
                raise CoordinationError("INITIAL_ROLE_REVISION_CHANGED")
            try:
                current = protocol("role transition", {"snapshot":current,"state":"draining"},cfg=cfg)
            except CoordinationError:
                current = protocol("role get", {"role_id":role},cfg=cfg)
                if current["record"]["state"] != "draining" or current["record"]["owner"] != prior["owner"] or current["record"]["ownership_epoch"] != prior["ownership_epoch"]:
                    raise
        if current["record"]["state"] == "draining":
            if evidence.get("draining_revision",current["revision"]) != current["revision"]:
                raise CoordinationError("DRAINING_REVISION_CHANGED")
            evidence["draining_revision"] = current["revision"]; save()
            read_claim = _sibling("ade_claims").read_claim
            bindings = {claim:binding for claim,binding in cfg["claims"].items() if binding["role_id"] == role}
            resources = sorted({path for binding in bindings.values() for path in binding["resources"]})
            if resource_free:
                marked=local_role_claims(role)
                if resources or bindings or marked or current["record"]["bindings"]:
                    raise CoordinationError("RESOURCE_FREE_SCOPE_MISMATCH")
            elif resources != intent["resources"] or not bindings:
                raise CoordinationError("ALL_BOUND_RESOURCES_REQUIRED")
            jobs = Resources(root / "jobs")
            try:
                for claim_id,binding in bindings.items():
                    claim = read_claim(claim_id)
                    if not claim or claim.get("coordination") != {"role_id":role,"generation":cfg["generation"]} or claim["owner"]["agent"] != prior["owner"]["agent"] or claim["path"] not in binding["resources"]:
                        raise CoordinationError("CLAIM_PROJECTION_MISMATCH")
                    if not jobs.quiescence(claim_id, prior)["jobs_stopped"]:
                        raise CoordinationError("TRACKED_JOBS_NOT_QUIESCENT")
            finally:
                jobs.close()
            operations = protocol("shared-operation list", {"role_id":role},cfg=cfg)
            if any(op["record"]["state"] == "UNKNOWN" for op in operations):
                raise CoordinationError("SHARED_OPERATION_UNKNOWN")
            source = native_call("inspect",prior["owner"]["agent"])
            if codex_contract and source.get("Provider") != "codex":
                raise CoordinationError("UNSUPPORTED_PROVIDER_CLOSE_CONTRACT")
            if source.get("Archived") is not True:
                if source.get("Status") != "idle" or source.get("PendingPermissions") != []:
                    raise CoordinationError("PREDECESSOR_NOT_READY_FOR_EXPLICIT_RETIREMENT")
                if evidence.get("archive_attempted") and not evidence.get("archive_completed"):
                    raise CoordinationError("ARCHIVE_OUTCOME_UNKNOWN_RECONCILE_ENDPOINT")
                evidence["archive_attempted"] = True; save()
                native_call("archive",prior["owner"]["agent"])
                evidence["archive_completed"] = True; save()
            retired = native_call("inspect",prior["owner"]["agent"])
            if retired.get("Archived") is not True:
                raise CoordinationError("RUNTIME_ARCHIVE_NOT_CONFIRMED")
            if codex_contract:
                if retired.get("Status") != "closed":
                    raise CoordinationError("PROVIDER_RUNTIME_NOT_CLOSED")
                if not evidence.get("archive_completed"):
                    proof = request.get("archive_reconciliation")
                    if not proof or proof.get("agent") != prior["owner"]["agent"] or proof.get("draining_revision") != current["revision"] or proof.get("completed") is not True or not proof.get("endpoint_evidence"):
                        raise CoordinationError("ARCHIVE_OUTCOME_UNKNOWN_RECONCILE_ENDPOINT")
                    evidence["archive_reconciliation"] = proof; save()
            for identity in runtime.get("processes",[]):
                if same_process(inspect(identity["pid"]), identity):
                    raise CoordinationError("PROVIDER_PROCESS_STILL_PRESENT")
            census_evidence = {}
            for path in resources:
                if not Path(path).is_absolute() or not Path(path).is_dir():
                    raise CoordinationError("RESOURCE_PATH_UNAVAILABLE")
                census_evidence[path] = users(path)
                if census_evidence[path]:
                    raise CoordinationError("WORKSPACE_PROCESS_USERS_REMAIN")
            artifact = protocol("artifact upload", {"base64":base64.b64encode(checkpoint).decode(),"media_type":"text/markdown"},cfg=cfg)
            if artifact["sha256"] != intent["checkpoint_digest"]:
                raise CoordinationError("CHECKPOINT_RETRIEVAL_DIGEST_MISMATCH")
            evidence.update({"census":census_evidence,"runtime":runtime,"checkpoint":artifact,"resource_manifest_digest":hashlib.sha256(json.dumps(resources,sort_keys=True).encode()).hexdigest()}); save()
            proof = {"prior_revision":current["revision"],"prior_epoch":prior["ownership_epoch"],"prior_owner":prior["owner"],"processes_stopped":True,"jobs_stopped":True,"operations_reconciled":True,"resource_manifest_digest":evidence["resource_manifest_digest"],"checkpoint_digest":intent["checkpoint_digest"]}
            current = protocol("role transition", {"snapshot":current,"state":"quiescent","quiescence":proof},cfg=cfg,_retirement_proof=True)
        if current["record"]["state"] in ("quiescent","checkpointed"):
            if not evidence.get("checkpoint") or current["record"].get("quiescence",{}).get("prior_revision") != evidence.get("draining_revision"):
                raise CoordinationError("PERSISTED_RETIREMENT_EVIDENCE_REQUIRED")
            # Recheck evidence at resumption; saved booleans do not hide a new
            # process, restored object, unknown operation or unclosed runtime.
            retired = native_call("inspect",prior["owner"]["agent"])
            if retired.get("Archived") is not True or (codex_contract and retired.get("Status") != "closed"):
                raise CoordinationError("RETIRED_RUNTIME_CHANGED")
            for identity in runtime.get("processes",[]):
                if same_process(inspect(identity["pid"]),identity):
                    raise CoordinationError("PROVIDER_PROCESS_STILL_PRESENT")
            if any(users(path) for path in intent["resources"]):
                raise CoordinationError("WORKSPACE_PROCESS_USERS_REMAIN")
            protocol("artifact read", {"artifact":evidence["checkpoint"]},cfg=cfg)
            if any(op["record"]["state"] == "UNKNOWN" for op in protocol("shared-operation list",{"role_id":role},cfg=cfg)):
                raise CoordinationError("SHARED_OPERATION_UNKNOWN")
            if current["record"]["state"] == "quiescent":
                current = protocol("role transition", {"snapshot":current,"state":"checkpointed","checkpoint_digest":intent["checkpoint_digest"]},cfg=cfg,_retirement_proof=True)
            try:
                current = protocol("role transfer", {"snapshot":current,"priorOwner":prior["owner"],"priorEpoch":prior["ownership_epoch"],"nextOwner":next_owner,"quiescence":current["record"]["quiescence"],"checkpoint_digest":intent["checkpoint_digest"]},cfg=cfg,_retirement_proof=True)
            except CoordinationError:
                current = protocol("role get", {"role_id":role},cfg=cfg)
                if current["record"]["owner"] != next_owner or current["record"]["ownership_epoch"] != prior["ownership_epoch"] + 1 or current["record"].get("handoff",{}).get("checkpoint_digest") != intent["checkpoint_digest"]:
                    raise
            return finish(current)
        raise CoordinationError("LIFECYCLE_RECONCILIATION_REQUIRED")
    finally:
        if db is not None: db.close()
        if barrier_entered: barrier.__exit__(None,None,None)
        os.close(lock_fd)

def project(current,cfg):
    read_claim = _sibling("ade_claims").read_claim
    update_claim = _sibling("ade_claims").update_claim
    role=current["record"]["role_id"]
    if cfg["roles"][role].get("resource_free") is True:
        marked=local_role_claims(role)
        if current["record"]["bindings"] or marked or any(binding["role_id"]==role for binding in cfg["claims"].values()):
            raise CoordinationError("RESOURCE_FREE_SCOPE_MISMATCH")
        return {"status":"transferred","role":current,"scope":"resource-free coordination role; no local projections"}
    for claim_id,binding in cfg["claims"].items():
        if binding["role_id"]!=role: continue
        claim=read_claim(claim_id)
        if not claim: raise CoordinationError("CLAIM_PROJECTION_MISSING_AFTER_TRANSFER")
        owner={**claim["owner"],"agent":current["record"]["owner"]["agent"],"record":current["record"]["owner"]["agent"],"session":None}
        update_claim(claim_id,owner=owner)
    return {"status":"transferred","role":current,"scope":"controlled local pilot resources only"}
