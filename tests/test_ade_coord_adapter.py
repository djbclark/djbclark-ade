"""Adapter policy regressions; broker correctness is separately tested in Node CI."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bin"))
import ade_coord as coord
import ade_claims

class AdapterTests(unittest.TestCase):
    def test_enrolled_marker_cannot_silently_fall_back_without_config(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{"ADE_COORD_CONFIG":"","ADE_COORD_ENROLLMENT_MARKER":str(Path(tmp)/"marker")}):
            self.assertIsNone(coord.authorize_claim({"id":"legacy"}))
            with self.assertRaises(coord.CoordinationError):
                coord.authorize_claim({"id":"enrolled","coordination":{"role_id":"r","generation":"g"}})
            with self.assertRaises(coord.CoordinationError):
                coord.authorize_claim({"id":"enrolled","coordination":None})
            self.assertFalse(ade_claims.is_expired({"coordination":{},"expires_at":"2000-01-01T00:00:00Z"}))

    def test_generation_manifest_mismatch_is_closed_and_errors_do_not_echo_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest=root/"generation";cfg=root/"cfg"
            manifest.write_text(json.dumps({"generation":"older","reconciled":True}))
            cfg.write_text(json.dumps({"generation":"current","generation_manifest":str(manifest),"secret":"DO_NOT_EMIT"}))
            with patch.dict(os.environ,{"ADE_COORD_CONFIG":str(cfg)}):
                with self.assertRaises(coord.CoordinationError) as error:coord.config()
                self.assertNotIn("DO_NOT_EMIT",str(error.exception))

    def test_offline_claim_is_never_new_authority_and_assignment_survives_recipient_epoch(self):
        cfg={"generation":"g","claims":{"c":{"role_id":"r","resources":["/resource"]}},"roles":{"r":{}},"identity":{"host":"h","server":"s"},"assignments":{"worker":{"id":"stable","recipient_role":"r"}}}
        claim={"id":"c","path":"/resource","owner":{"agent":"a"},"coordination":{"role_id":"r","generation":"g"}}
        with patch.object(coord,"config",return_value=cfg),patch.object(coord,"snapshot",side_effect=coord.CoordinationError("offline")):
            with self.assertRaises(coord.CoordinationError):coord.authorize_claim(claim)
        report={"role_id":"r","producer_assignment":cfg["assignments"]["worker"],"payload":{"sender":"worker"}}
        coord.validate_assignment(report,cfg)
        report["producer_assignment"]={"id":"different","recipient_role":"r"}
        with self.assertRaises(coord.CoordinationError):coord.validate_assignment(report,cfg)

    def test_raw_adapter_transfer_cannot_bypass_retirement_gate(self):
        with self.assertRaises(coord.CoordinationError):
            coord.call("role transfer",{},cfg={"generation":"g"})

    def test_remembered_enrollment_missing_file_is_not_unenrollment(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker=Path(tmp)/"marker";marker.write_text(json.dumps({"config":str(Path(tmp)/"missing")}))
            with patch.dict(os.environ,{"ADE_COORD_CONFIG":"","ADE_COORD_ENROLLMENT_MARKER":str(marker)}):
                with self.assertRaises(coord.CoordinationError):coord.current_role("old")

    def test_archived_flag_after_unknown_codex_archive_does_not_prove_retirement(self):
        # Policy test only. Real broker CAS/transfer is covered in Node integration.
        import hashlib
        from ade_coord_handoff import transfer
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);resource=root/"workspace";resource.mkdir();checkpoint=root/"checkpoint";checkpoint.write_bytes(b"checkpoint")
            owner={"host":"h","server":"s","agent":"old"};next_owner={**owner,"agent":"new"}
            contract={"server":"s","provider":"codex","daemon_version":"verified-test","verified":True}
            manifest=root/"manifest";manifest.write_text(json.dumps({"retirement_contract":contract}))
            role={"revision":1,"record":{"role_id":"r","owner":owner,"ownership_epoch":1,"generation":"g","state":"active","bindings":[str(resource)]}}
            cfg={"generation":"g","generation_manifest":str(manifest),"state_dir":str(root/"state"),"identity":{"host":"h","server":"s"},"roles":{"r":{"controlled_pilot":True,"successors":[next_owner],"runtime":{"owner":owner,"ownership_epoch":1,"codex_close_contract":contract}}},"claims":{"c":{"role_id":"r","resources":[str(resource)]}},"aliases":{"old":"r","new":"r"}}
            request={"role_id":"r","next_owner":next_owner,"attempt_id":"a","checkpoint_path":str(checkpoint)}
            archives=[]
            def native(*args):
                if args[0]=="daemon-status":return {"daemonVersion":"verified-test","serverId":"s"}
                if args[0]=="inspect":return {"Provider":"codex","Archived":bool(archives),"Status":"closed" if archives else "idle","PendingPermissions":[]}
                archives.append(True);raise coord.CoordinationError("UNKNOWN_ARCHIVE")
            def protocol(command,body,**kwargs):
                nonlocal role
                if command=="role get":return json.loads(json.dumps(role))
                if command=="shared-operation list":return []
                if command=="artifact upload":return {"sha256":hashlib.sha256(b"checkpoint").hexdigest()}
                if command=="artifact read":return {}
                if command=="role transition":
                    role={"revision":role["revision"]+1,"record":{**role["record"],"state":body["state"]}}
                    if "quiescence" in body:role["record"]["quiescence"]=body["quiescence"]
                    return role
                if command=="role transfer":
                    role={"revision":role["revision"]+1,"record":{**role["record"],"state":"active","owner":next_owner,"ownership_epoch":2}}
                    return role
                raise AssertionError(command)
            projection={"id":"c","path":str(resource),"coordination":{"role_id":"r","generation":"g"},"owner":{"agent":"old"}}
            with patch.object(ade_claims,"read_claim",return_value=projection),patch.object(ade_claims,"update_claim"):
                with self.assertRaisesRegex(coord.CoordinationError,"UNKNOWN_ARCHIVE"):
                    transfer(request,cfg=cfg,native_call=native,protocol=protocol,users=lambda _:[])
                with self.assertRaisesRegex(coord.CoordinationError,"ARCHIVE_OUTCOME_UNKNOWN"):
                    transfer(request,cfg=cfg,native_call=native,protocol=protocol,users=lambda _:[])
                self.assertEqual(len(archives),1)
                request["archive_reconciliation"]={"agent":"old","draining_revision":2,"completed":True,"endpoint_evidence":"verified endpoint exit event"}
                result=transfer(request,cfg=cfg,native_call=native,protocol=protocol,users=lambda _:[])
                self.assertEqual(result["status"],"transferred")

if __name__=="__main__":unittest.main()
