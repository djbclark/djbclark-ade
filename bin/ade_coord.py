"""Explicit enrolled-role adapter. No configuration means exact legacy behavior.

Config is trusted operator data, never auto-generated. A persisted claim marker
requires config even if the config file disappears. Broker errors fail closed.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import time

class CoordinationError(ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]

def _sibling(name):
    import importlib.util
    import sys
    if name not in {"ade_claims", "ade_coord_resources", "ade_coord_handoff", "ade_coord_wake"}:
        raise CoordinationError("UNSUPPORTED_SIBLING")
    path = Path(__file__).resolve().with_name(name + ".py")
    found = sys.modules.get(name)
    if found is not None and Path(found.__file__).resolve() == path:
        return found
    key = name if found is None else "_ade_sibling_" + str(path)
    if key in sys.modules: return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key,path)
    module = importlib.util.module_from_spec(spec);sys.modules[key]=module
    try: spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(key,None);raise
    return module


def config():
    path = os.environ.get("ADE_COORD_CONFIG")
    marker = Path(os.environ.get("ADE_COORD_ENROLLMENT_MARKER", str(Path.home() / ".local/state/ade-coord/enrollment.json")))
    if not path:
        if marker.exists():
            try:
                path = json.loads(marker.read_text())["config"]
            except Exception:
                raise CoordinationError("ENROLLMENT_MARKER_INVALID") from None
        else:
            return None
    try:
        value = json.loads(Path(path).read_text())
        generation = json.loads(Path(value["generation_manifest"]).read_text())
        if generation["generation"] != value["generation"] or generation.get("reconciled") is not True:
            raise ValueError()
        if not all(isinstance(value[k], dict) for k in ("roles", "claims", "aliases", "assignments")):
            raise ValueError()
        if not Path(value["state_dir"]).is_absolute() or not Path(value["generation_manifest"]).is_absolute() or set(value["identity"]) != {"host", "server"}:
            raise ValueError()
        for binding in value["claims"].values():
            if binding["role_id"] not in value["roles"] or not binding["resources"] or not all(isinstance(path,str) and Path(path).is_absolute() for path in binding["resources"]):
                raise ValueError()
        return value
    except Exception:
        raise CoordinationError("INVALID_ENROLLMENT_OR_GENERATION") from None

def metric(command, elapsed, request_bytes, response_bytes, **counts):
    path = os.environ.get("ADE_COORD_METRICS")
    if not path:
        return
    # No payloads, auth, paths or arbitrary labels in telemetry.
    value = {"command": command, "elapsed_ms": round(elapsed * 1000, 3), "request_bytes": request_bytes, "response_bytes": response_bytes, **counts}
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, (json.dumps(value) + "\n").encode())
    finally:
        os.close(fd)

def call(command, request, *, cfg=None, _retirement_proof=False):
    cfg = cfg or config()
    if not cfg:
        raise CoordinationError("ENROLLMENT_REQUIRED")
    marker = Path(os.environ.get("ADE_COORD_ENROLLMENT_MARKER", str(Path.home() / ".local/state/ade-coord/enrollment.json")))
    if not marker.is_file():
        raise CoordinationError("EXPLICIT_ENROLLMENT_CONFIRMATION_REQUIRED")
    if not _retirement_proof and (command == "role transfer" or (command == "role transition" and request.get("state") != "draining")):
        raise CoordinationError("RESOURCE_RETIREMENT_PROOF_REQUIRED")
    allowed = {"role get", "role create", "role transition", "role transfer", "report publish", "report buffer", "report flush", "report status", "inbox list", "inbox read", "inbox intake", "inbox dispose", "outbox status", "outbox reconcile", "operation intent", "operation inspect", "operation reconcile", "shared-operation intent", "shared-operation inspect", "shared-operation list", "shared-operation reconcile", "artifact read", "artifact upload", "doctor check", "broker provision"}
    if command not in allowed:
        raise CoordinationError("INVALID_COMMAND")
    offline={"report buffer","outbox status","operation intent","operation inspect","operation reconcile"}
    def invoke(action,body,network):
        payload=json.dumps({**body,"generation":cfg["generation"]},allow_nan=False).encode()
        argv=[os.environ.get("ADE_COORD_NODE","node"),str(ROOT/"lib/ade-coord/cli.js"),*action.split(),"--state-dir",cfg["state_dir"]]
        safe={key:value for key,value in os.environ.items() if key in {"PATH","HOME","XDG_CONFIG_HOME","LANG","LC_ALL","LC_CTYPE","TMPDIR","TMP","TEMP"}}
        if cfg.get("broker_url") or os.environ.get("ADE_NATS_URL"):
            safe["ADE_NATS_URL"]=cfg.get("broker_url") or os.environ["ADE_NATS_URL"]
        if cfg.get("broker_url"):
            # The managed boundary injects its default URL afresh. Preserve this
            # explicitly selected public target through the consumer hop too.
            safe["ADE_COORD_TARGET_URL"]=cfg["broker_url"]
        if network:
            boundary=cfg.get("credential_boundary") or shutil.which("sudo-secretspec")
            if not boundary or not Path(boundary).is_absolute():raise CoordinationError("MANAGED_BOUNDARY_UNAVAILABLE")
            argv=[boundary,"run","--reason","ADE coordination consumer","--",sys.executable,"-I",str(ROOT/"bin/ade_coord_consumer.py"),*argv]
        started=time.monotonic()
        try:
            result=subprocess.run(argv,input=payload,env=safe,capture_output=True,timeout=30,check=False)
            metric(action,time.monotonic()-started,len(payload),len(result.stdout))
            data=json.loads(result.stdout)
            if result.returncode or not data.get("ok"):
                raise CoordinationError(data.get("error",{}).get("code","UNKNOWN"))
            return data.get("result")
        except CoordinationError:raise
        except Exception:raise CoordinationError("UNKNOWN_COORDINATION_OUTCOME") from None
    if command=="report publish":
        # Canonical bytes are durable even when the current credential service is
        # unavailable. No network/boundary execution precedes this transaction.
        invoke("report buffer",request,False)
        return invoke("report flush",{"role_id":request["report"]["role_id"],"message_id":request["report"]["message_id"]},True)
    return invoke(command,request,command not in offline)


def role_for(identifier, *, cfg=None):
    cfg = cfg or config()
    if not cfg:
        return None
    if identifier in cfg["roles"]:
        return identifier
    role = cfg["aliases"].get(identifier)
    if role is not None and role not in cfg["roles"]:
        raise CoordinationError("UNBOUND_ROLE_ALIAS")
    return role


def agent_relationships(request, *, cfg=None):
    """Describe configured edges only; never establish current owner/contact authority."""
    agent = request.get("agent_id")
    if not isinstance(agent, str) or not agent.strip():
        raise CoordinationError("AGENT_ID_REQUIRED")
    cfg = config() if cfg is None else cfg
    cfg = {"roles": {}, "aliases": {}, "assignments": {}} if cfg is None else cfg
    if not all(isinstance(cfg.get(key), dict) for key in ("roles", "aliases", "assignments")):
        raise CoordinationError("INVALID_RELATIONSHIP_CONFIG")
    roles, aliases, assignments = (cfg[key] for key in ("roles", "aliases", "assignments"))
    owners = {}
    for role, settings in roles.items():
        runtime = settings.get("runtime") if isinstance(settings, dict) else None
        owner = runtime.get("owner") if isinstance(runtime, dict) else None
        if (isinstance(owner, dict) and set(owner) == {"host", "server", "agent"}
                and all(isinstance(value, str) and value.strip() for value in owner.values())
                and aliases.get(owner["agent"]) == role):
            owners[role] = {key: owner[key] for key in ("host", "server", "agent")}

    edges = {}
    for worker, assignment in assignments.items():
        if not isinstance(worker, str) or not worker.strip():
            continue
        role = assignment.get("recipient_role") if isinstance(assignment, dict) else None
        if not isinstance(role, str) or role not in roles:
            edges[worker] = {"status": "unknown", "reason": "recipient_role_missing"}
        elif role not in owners:
            edges[worker] = {"status": "unknown", "reason": "configured_owner_missing_or_inconsistent",
                             "recipient_role": role}
        else:
            edges[worker] = {"status": "known", "recipient_role": role,
                             "configured_owner": owners[role]}

    # A control cycle, including a self-assignment, cannot establish a lead.
    # Keep its explicit edge as evidence, but never select a controller from it.
    cyclic = set()
    for worker in edges:
        path, seen, current = [], set(), worker
        while edges.get(current, {}).get("status") == "known":
            if current in seen:
                cyclic.update(path)
                break
            seen.add(current)
            path.append(current)
            current = edges[current]["configured_owner"]["agent"]
    for worker in cyclic:
        edges[worker] = {**edges[worker], "status": "ambiguous", "reason": "control_cycle"}

    controller = edges.get(agent, {"status": "unknown", "reason": "no_explicit_assignment"})
    owned_roles = sorted(role for role, owner in owners.items() if owner["agent"] == agent)
    workers = [
        {"agent_id": worker, **edge}
        for worker, edge in sorted(edges.items())
        if edge.get("configured_owner", {}).get("agent") == agent
    ]
    alias = aliases.get(agent)
    return {
        "agent_id": agent,
        "evidence": "local_enrollment_config",
        "controller": controller,
        "configured_owned_roles": owned_roles,
        "alias_role": alias if isinstance(alias, str) and alias in roles else None,
        "workers": workers,
        "workers_complete": False,
        "current_owner_verified": False,
        "contact_authority": False,
        "requires_online_owner_revalidation": True,
    }


def snapshot(role, *, cfg=None, active=True):
    cfg = cfg or config()
    if not cfg or role not in cfg["roles"]:
        raise CoordinationError("ROLE_NOT_ENROLLED")
    current = call("role get", {"role_id": role}, cfg=cfg)
    if not current or current["record"]["generation"] != cfg["generation"]:
        raise CoordinationError("GENERATION_OR_ROLE_MISSING")
    if active and current["record"]["state"] != "active":
        raise CoordinationError("ROLE_NOT_ACTIVE")
    return current

def authority(current):
    r = current["record"]
    return {"owner": r["owner"], "ownership_epoch": r["ownership_epoch"], "generation": r["generation"], "revision": current["revision"]}

def current_role(identifier):
    cfg = config()
    role = role_for(identifier, cfg=cfg)
    if role is None:
        return None
    return snapshot(role, cfg=cfg)["record"]["owner"]["agent"]

def authorize_claim(claim, actor=None):
    cfg = config()
    marked = "coordination" in claim
    marker = claim.get("coordination")
    binding = cfg["claims"].get(claim["id"]) if cfg else None
    if not marked and binding is None:
        # Enrollment binds resources as well as claim IDs. A replacement ID
        # must not turn the same workspace (or an overlapping scope) legacy.
        if cfg and claim.get("path"):
            path = Path(claim["path"]).resolve()
            for enrolled in cfg["claims"].values():
                for resource in enrolled["resources"]:
                    bound = Path(resource).resolve()
                    if path == bound or path in bound.parents or bound in path.parents:
                        raise CoordinationError("ENROLLED_RESOURCE_REQUIRES_CONFIGURED_CLAIM")
        return None
    if not cfg or not binding or (marked and marker != {"role_id": binding["role_id"], "generation": cfg["generation"]}):
        raise CoordinationError("ENROLLED_CLAIM_CONFIG_MISSING_OR_CHANGED")
    current = snapshot(binding["role_id"], cfg=cfg)
    record = current["record"]
    path = str(Path(claim["path"]).resolve())
    if path not in binding["resources"] or not set(binding["resources"]).issubset(set(record["bindings"])):
        raise CoordinationError("CLAIM_RESOURCES_NOT_BOUND")
    expected = cfg["identity"]
    if record["owner"]["host"] != expected["host"] or record["owner"]["server"] != expected["server"] or record["owner"]["agent"] != (actor or claim["owner"]["agent"]):
        raise CoordinationError("STALE_CLAIM_OWNER")
    return {"role_id": binding["role_id"], "generation": cfg["generation"]}

def notice(requester, sender, *, title, detail, report, msg_id):
    cfg = config()
    role = role_for(requester, cfg=cfg)
    if role is None:
        return None
    assignment = cfg["assignments"].get(sender)
    if not assignment or assignment["recipient_role"] != role:
        raise CoordinationError("PRODUCER_ASSIGNMENT_REQUIRED")
    msg_id = msg_id or assignment.get("message_id")
    if not msg_id:
        raise CoordinationError("PERSISTED_MESSAGE_ID_REQUIRED")
    artifacts = []
    if report:
        artifacts = [{"base64": base64.b64encode(Path(report).read_bytes()).decode(), "media_type": "text/markdown"}]
    envelope = {"role_id": role, "message_id": msg_id, "producer_assignment": assignment, "payload": {"sender": sender, "title": title, "detail": detail}}
    try:
        accepted = call("report publish", {"report": envelope, "artifacts": artifacts}, cfg=cfg)
        return {"status": "broker-accepted", "msg_id": msg_id, "role_id": role, "revision": accepted["revision"]}
    except CoordinationError as error:
        if str(error) == "IMMUTABLE":
            raise
        # Verify durable buffering before reporting that claim; do not infer it
        # from a failed command or create another message identity.
        rows = call("outbox status", {}, cfg=cfg)
        found = next((r for r in rows if r["role"] == role and r["id"] == msg_id), None)
        if not found:
            raise
        return {"status": found["stage"], "msg_id": msg_id, "role_id": role, "error": found["error"] or "UNKNOWN"}

def intake(worker, message_id):
    started = time.monotonic()
    cfg = config(); actor = os.environ.get("PASEO_AGENT_ID", "")
    role = role_for(actor, cfg=cfg)
    if role is None:
        return None
    current = snapshot(role, cfg=cfg)
    if current["record"]["owner"] != {**cfg["identity"], "agent": actor}:
        raise CoordinationError("CURRENT_OWNER_REQUIRED")
    record = call("report status", {"role_id": role, "message_id": message_id}, cfg=cfg)
    if not record or record["record"]["report"]["payload"]["sender"] != worker:
        raise CoordinationError("REPORT_SENDER_MISMATCH")
    validate_assignment(record["record"]["report"], cfg)
    call("inbox intake", {"snapshot": current, "authority": authority(current), "message_id": message_id}, cfg=cfg)
    metric("inbox intake", time.monotonic() - started, 0, 0, prompt_ack_suppressed=1)
    return {"status": "ADE-inbox-recorded", "worker": worker, "msg_id": message_id, "routes": ["ADE-inbox"], "processed": False}


def remember_enrollment():
    cfg = config()
    if not cfg or not os.environ.get("ADE_COORD_CONFIG"):
        raise CoordinationError("EXPLICIT_CONFIG_REQUIRED")
    marker = Path(os.environ.get("ADE_COORD_ENROLLMENT_MARKER", str(Path.home() / ".local/state/ade-coord/enrollment.json")))
    marker.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    import tempfile
    fd, temp = tempfile.mkstemp(dir=marker.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump({"config": str(Path(os.environ["ADE_COORD_CONFIG"]).resolve())}, stream)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, marker)
    finally:
        if os.path.exists(temp): os.unlink(temp)
    return {"enrolled": True, "generation": cfg["generation"]}

def pump(role):
    cfg = config(); current = snapshot(role, cfg=cfg)
    expected = {**cfg["identity"], "agent": current["record"]["owner"]["agent"]}
    if current["record"]["owner"] != expected:
        raise CoordinationError("REMOTE_OWNER_REQUIRES_REMOTE_CONTROLLER")
    request = {"snapshot": current, "authority": authority(current)}
    reports = call("inbox list", request, cfg=cfg)
    count = 0
    for item in reports:
        validate_assignment(item["record"]["report"], cfg)
        call("inbox intake", {**request, "message_id": item["record"]["report"]["message_id"]}, cfg=cfg)
        count += 1
    notification = _sibling("ade_coord_wake").wake(cfg,role)
    return {"role_id": role, "ADE_inbox_recorded": count, "processed": False, "wake": notification}


def validate_assignment(report, cfg):
    sender = report.get("payload", {}).get("sender")
    assignment = cfg["assignments"].get(sender)
    if not assignment or report.get("producer_assignment") != assignment or assignment.get("recipient_role") != report["role_id"]:
        raise CoordinationError("REPORT_ASSIGNMENT_MISMATCH")


def run_managed(request):
    read_claim = _sibling("ade_claims").read_claim
    Resources = _sibling("ade_coord_resources").Resources
    run_job = _sibling("ade_coord_resources").run_job
    cfg = config(); claim = read_claim(request["claim"])
    if not claim:
        raise CoordinationError("BOUND_CLAIM_REQUIRED")
    marker = authorize_claim(claim, os.environ.get("PASEO_AGENT_ID"))
    if marker is None:
        raise CoordinationError("ENROLLED_CLAIM_REQUIRED")
    current = snapshot(marker["role_id"], cfg=cfg)
    resources = Resources(Path(cfg["state_dir"]) / "jobs", admission_directory=Path(cfg["state_dir"]))
    try:
        import re
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request["job_id"]):
            raise CoordinationError("INVALID_JOB_ID")
        log = Path(cfg["state_dir"]) / "jobs" / (request["job_id"] + ".log")
        fd = os.open(log, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        def online_authorize(*_):
            authorize_claim(claim, os.environ.get("PASEO_AGENT_ID"))
            fresh = snapshot(marker["role_id"], cfg=cfg)
            if authority(fresh) != authority(current):
                raise CoordinationError("LAUNCH_AUTHORITY_CHANGED")
        child_env = {**os.environ, "PATH": str(ROOT / "libexec/agent-bin") + os.pathsep + os.environ.get("PATH", ""), "ADE_CLAIM_ID": claim["id"], "ADE_COORD_ROLE": marker["role_id"]}
        with os.fdopen(fd, "wb") as output:
            code = run_job(resources, job=request["job_id"], claim=claim["id"], authority=authority(current), argv=request["argv"], authorize=online_authorize, output=output, env=child_env)
        return {"job_id": request["job_id"], "exit_code": code, "output": str(log)}
    finally:
        resources.close()


def job_status(request, command):
    Resources = _sibling("ade_coord_resources").Resources
    cfg = config()
    if not cfg:
        raise CoordinationError("ENROLLMENT_REQUIRED")
    resources = Resources(Path(cfg["state_dir"]) / "jobs", admission_directory=Path(cfg["state_dir"]))
    try:
        row = resources.get(request["job_id"])
        binding = cfg["claims"].get(row["claim"])
        if not binding:
            raise CoordinationError("BOUND_JOB_CLAIM_REQUIRED")
        if command != "job inspect":
            current = snapshot(binding["role_id"], cfg=cfg, active=False)
            if os.environ.get("PASEO_AGENT_ID") and current["record"]["owner"]["agent"] != os.environ["PASEO_AGENT_ID"]:
                raise CoordinationError("CURRENT_JOB_RECONCILIATION_OWNER_REQUIRED")
            if current["record"]["owner"]["host"] != cfg["identity"]["host"] or current["record"]["owner"]["server"] != cfg["identity"]["server"]:
                raise CoordinationError("REMOTE_JOB_RECONCILIATION_UNSUPPORTED")
            if command == "job reconcile":
                resources.reconcile_not_started(request["job_id"], request["evidence"])
            elif command == "job bind":
                if not request.get("evidence"):
                    raise CoordinationError("ENDPOINT_IDENTITY_EVIDENCE_REQUIRED")
                resources.spawned(request["job_id"], request["pid"])
            elif command == "job complete":
                resources.complete(request["job_id"], request["result"])
            else:
                raise CoordinationError("INVALID_JOB_COMMAND")
        return resources.get(request["job_id"])
    finally:
        resources.close()


def materialize(request):
    import re
    import tempfile
    cfg = config(); ref = request["artifact"]
    data = call("artifact read", {"artifact": ref}, cfg=cfg)
    content = base64.b64decode(data["base64"], validate=True)
    sha = hashlib.sha256(content).hexdigest()
    if not re.fullmatch(r"[a-f0-9]{64}", ref["sha256"]) or sha != ref["sha256"] or len(content) != ref["size"]:
        raise CoordinationError("ARTIFACT_DIGEST_MISMATCH")
    directory = Path(cfg["state_dir"]) / "artifacts"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink():
        raise CoordinationError("ARTIFACT_CACHE_MUST_BE_REAL_DIRECTORY")
    os.chmod(directory, 0o700)
    target = directory / sha
    if target.exists():
        if target.is_symlink() or target.read_bytes() != content:
            raise CoordinationError("IMMUTABLE_ARTIFACT_CACHE_CONFLICT")
    else:
        fd, temp = tempfile.mkstemp(dir=directory)
        try:
            with os.fdopen(fd,"wb") as output:
                output.write(content); output.flush(); os.fsync(output.fileno())
            try: os.link(temp,target)
            except FileExistsError:
                if target.is_symlink() or target.read_bytes() != content:
                    raise CoordinationError("IMMUTABLE_ARTIFACT_CACHE_CONFLICT")
        finally: os.unlink(temp)
    os.chmod(target, 0o600)
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(directory_fd)
    finally: os.close(directory_fd)
    return {"path":str(target),"sha256":sha,"size":len(content)}
