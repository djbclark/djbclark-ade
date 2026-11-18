"""Opt-in, at-most-once machine wakes. A wake never implies ADE/model processing."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
import uuid
from ade_coord import call, CoordinationError, authority, _sibling, metric

def native(argv):
    try:
        result=subprocess.run(["paseo",*argv],capture_output=True,text=True,timeout=10)
        data=json.loads(result.stdout)
        if result.returncode not in (0,5):raise ValueError()
        return data
    except Exception:
        raise CoordinationError("WAKE_NATIVE_OUTCOME_UNKNOWN") from None

def database(cfg):
    root=Path(cfg["state_dir"]);root.mkdir(parents=True,mode=0o700,exist_ok=True)
    path=root/"wakes.sqlite"
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600);os.close(fd)
    db=sqlite3.connect(path,timeout=10)
    db.executescript("""PRAGMA journal_mode=WAL;PRAGMA synchronous=FULL;
      CREATE TABLE IF NOT EXISTS wakes(id TEXT PRIMARY KEY,role TEXT,generation TEXT,epoch INTEGER,owner TEXT,highwater INTEGER,attempt INTEGER,status TEXT,intent TEXT,result TEXT);
      CREATE UNIQUE INDEX IF NOT EXISTS wake_batch_attempt ON wakes(role,generation,epoch,owner,highwater,attempt);""")
    return db

def _rows(db,role):
    db.row_factory=sqlite3.Row
    return [dict(row) for row in db.execute("SELECT * FROM wakes WHERE role=? ORDER BY epoch,highwater,attempt",(role,))]

def status(cfg,role):
    db=database(cfg)
    try:return _rows(db,role)
    finally:db.close()

def blockers(cfg,role,epoch):
    return [row["id"] for row in status(cfg,role) if row["epoch"]==epoch and row["status"] in ("RESERVED","UNKNOWN","ACCEPTED_UNCONFIRMED")]

def wake(cfg,role,*,protocol=call,native_call=native):
    if cfg["roles"].get(role,{}).get("wake") is not True:
        return {"status":"disabled","processed":False}
    admission=_sibling("ade_coord_resources").admission
    with admission(Path(cfg["state_dir"])):
        current=protocol("role get",{"role_id":role},cfg=cfg);record=current["record"]
        if record["state"]!="active":return {"status":"deferred-role","processed":False}
        if record["owner"]["host"]!=cfg["identity"]["host"] or record["owner"]["server"]!=cfg["identity"]["server"]:
            return {"status":"refused-remote","processed":False}
        pending=protocol("inbox list",{"snapshot":current,"authority":authority(current)},cfg=cfg)
        if not pending:return {"status":"empty","processed":False}
        highwater=max(row["revision"] for row in pending)
        owner=json.dumps(record["owner"],sort_keys=True,separators=(",",":"));epoch=record["ownership_epoch"]
        db=database(cfg)
        try:
            rows=[row for row in _rows(db,role) if row["generation"]==cfg["generation"] and row["epoch"]==epoch and row["owner"]==owner]
            prior=max((row["highwater"] for row in rows if row["status"]!="REARMED_NOT_APPLIED"),default=0)
            if highwater<=prior:return {"status":"coalesced","processed":False}
            host=native_call(["daemon","status","--json"])
            if host.get("serverId")!=record["owner"]["server"]:return {"status":"refused-daemon","processed":False}
            target=record["owner"]["agent"]
            agent=native_call(["agent","inspect",target,"--json"])
            if agent.get("Id")!=target or agent.get("Archived") is not False:return {"status":"refused-target","processed":False}
            if agent.get("Status") not in ("idle","closed") or agent.get("PendingPermissions")!=[]:
                return {"status":"deferred-busy","processed":False}
            attempt=1+max((row["attempt"] for row in rows if row["highwater"]==highwater),default=-1)
            key=json.dumps([role,cfg["generation"],epoch,owner,highwater,attempt],separators=(",",":"))
            wake_id="wake_"+hashlib.sha256(key.encode()).hexdigest()
            intent={"kind":"ADE-inbox-wake","role_id":role,"owner":record["owner"],"ownership_epoch":epoch,"highwater":highwater,"reports":sorted(row["record"]["report"]["message_id"] for row in pending),"nonce":uuid.uuid4().hex}
            # Persist before any native send or authoritative external-operation intent.
            with db:
                db.execute("INSERT INTO wakes VALUES (?,?,?,?,?,?,?,'RESERVED',?,NULL)",(wake_id,role,cfg["generation"],epoch,owner,highwater,attempt,json.dumps(intent,sort_keys=True)))
            existing=protocol("shared-operation inspect",{"role_id":role,"id":wake_id},cfg=cfg)
            if existing:
                operation=existing["record"]
                adopted={"SUCCEEDED":"ACCEPTED","NOT_APPLIED":"NOT_APPLIED"}.get(operation["state"],"UNKNOWN")
                with db:db.execute("UPDATE wakes SET status=?,intent=?,result=? WHERE id=?",(adopted,json.dumps(operation["intent"],sort_keys=True),json.dumps(operation.get("resolution")),wake_id))
                return {"status":"unknown-no-retry" if adopted=="UNKNOWN" else "coalesced-authoritative","wake_id":wake_id,"processed":False}
            protocol("shared-operation intent",{"snapshot":current,"id":wake_id,"intent":intent},cfg=cfg)
            with db:db.execute("UPDATE wakes SET status='UNKNOWN' WHERE id=?",(wake_id,))
            fresh=protocol("role get",{"role_id":role},cfg=cfg)
            if fresh!=current:
                # Definitely no native send. Resolve only the operation ledger;
                # this is not an automatic retry or a role grant.
                protocol("shared-operation reconcile",{"snapshot":fresh,"id":wake_id,"state":"NOT_APPLIED","result":None,"evidence":{"before_send":"role changed"}},cfg=cfg)
                with db:db.execute("UPDATE wakes SET status='NOT_APPLIED' WHERE id=?",(wake_id,))
                return {"status":"refused-replaced","wake_id":wake_id,"processed":False}
            prompt=f"ADE durable inbox changed for role {role}. Read the inbox under current authority. This wake is not intake, understanding or processed proof."
            started=time.monotonic()
            try:
                answer=native_call(["send","--json","--no-wait",target,"--prompt",prompt])
                if answer.get("status") not in ("queued","sent","completed"):raise CoordinationError("WAKE_NATIVE_OUTCOME_UNKNOWN")
            except Exception:
                return {"status":"unknown-no-retry","wake_id":wake_id,"processed":False}
            receipt={"native_status":answer["status"]}
            with db:db.execute("UPDATE wakes SET status='ACCEPTED_UNCONFIRMED',result=? WHERE id=?",(json.dumps(receipt),wake_id))
            metric("inbox wake",time.monotonic()-started,len(prompt.encode()),0,wake_calls=1)
            try:
                protocol("shared-operation reconcile",{"snapshot":current,"id":wake_id,"state":"SUCCEEDED","result":receipt,"evidence":{"native_acceptance":answer["status"],"wake_id":wake_id}},cfg=cfg)
            except Exception:return {"status":"accepted-ledger-unknown","wake_id":wake_id,"processed":False}
            with db:db.execute("UPDATE wakes SET status='ACCEPTED' WHERE id=?",(wake_id,))
            return {"status":"accepted","wake_id":wake_id,"native_status":answer["status"],"processed":False}
        finally:db.close()

def reconcile(cfg,request,*,protocol=call):
    if request.get("state") not in ("SUCCEEDED","NOT_APPLIED") or not request.get("evidence"):
        raise CoordinationError("WAKE_ENDPOINT_EVIDENCE_REQUIRED")
    with _sibling("ade_coord_resources").admission(Path(cfg["state_dir"])):
        db=database(cfg)
        try:
            db.row_factory=sqlite3.Row
            found=db.execute("SELECT * FROM wakes WHERE id=?",(request["wake_id"],)).fetchone()
            if not found:raise CoordinationError("UNKNOWN_WAKE_ID")
            row=dict(found);current=protocol("role get",{"role_id":row["role"]},cfg=cfg)
            owner=current["record"]["owner"]
            if owner["host"]!=cfg["identity"]["host"] or owner["server"]!=cfg["identity"]["server"]:
                raise CoordinationError("REMOTE_WAKE_RECONCILIATION_REQUIRED")
            if os.environ.get("PASEO_AGENT_ID") and owner["agent"]!=os.environ["PASEO_AGENT_ID"]:
                raise CoordinationError("CURRENT_WAKE_RECONCILIATION_OWNER_REQUIRED")
            existing=protocol("shared-operation inspect",{"role_id":row["role"],"id":row["id"]},cfg=cfg)
            if existing:
                if existing["record"]["state"]!="UNKNOWN":
                    if existing["record"]["state"]!=request["state"]:
                        raise CoordinationError("IMMUTABLE_WAKE_ENDPOINT_RESULT")
                    request={**request,"result":existing["record"]["resolution"]["result"],"evidence":existing["record"]["resolution"]["evidence"]}
                else:
                    protocol("shared-operation reconcile",{"snapshot":current,"id":row["id"],"state":request["state"],"result":request.get("result"),"evidence":request["evidence"]},cfg=cfg)
            elif row["status"]!="RESERVED" or request["state"]!="NOT_APPLIED":
                raise CoordinationError("WAKE_AUTHORITATIVE_INTENT_MISSING")
            state="ACCEPTED" if request["state"]=="SUCCEEDED" else ("REARMED_NOT_APPLIED" if request.get("rearm") is True else "NOT_APPLIED")
            with db:db.execute("UPDATE wakes SET status=?,result=? WHERE id=?",(state,json.dumps({"result":request.get("result"),"evidence":request["evidence"]}),row["id"]))
            return {"wake_id":row["id"],"status":state,"processed":False}
        finally:db.close()
