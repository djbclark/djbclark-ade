"""Adapter policy regressions; broker correctness is separately tested in Node CI."""
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
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

    def test_reclaim_cannot_publish_legacy_record_over_enrolled_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); workspace = root / "workspace"; workspace.mkdir()
            cfg = {"generation":"g", "claims":{"original":{"role_id":"r","resources":[str(workspace)]}},
                   "identity":{"host":"h","server":"s"}}
            current = {"record":{"owner":{"host":"h","server":"s","agent":"a"},"bindings":[str(workspace)]}}
            def claim(cid):
                return ade_claims.make_claim(id=cid,path=workspace,branch="pilot",base_sha="a"*40,owner_record="same-owner",owner_agent="a")
            with patch.dict(os.environ,{"ADE_STATE_DIR":str(root/"registry")}), patch.object(coord,"config",return_value=cfg), patch.object(coord,"snapshot",return_value=current):
                original = ade_claims.create_claim(claim("original"))
                saved = original.read_bytes()
                # No workspace pointer: this exercises the fallback registry path
                # that previously selected the newly published unmarked claim.
                for label, claims_config in [("configured",cfg["claims"]),("missing-binding",{})]:
                    with self.subTest(label=label), patch.dict(cfg,{"claims":claims_config}):
                        with self.assertRaises(coord.CoordinationError):
                            ade_claims.create_claim(claim("replacement"))
                        self.assertFalse(ade_claims.claim_file("replacement").exists())
                        self.assertEqual(original.read_bytes(),saved)
                        self.assertEqual([c["id"] for c in ade_claims.list_claims("active")],["original"])

    def test_legacy_claim_cannot_overlap_enrolled_resource_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bound=root/"resource"; bound.mkdir()
            alias=root/"alias";alias.symlink_to(bound,target_is_directory=True)
            cfg={"claims":{"bound":{"role_id":"r","resources":[str(bound)]}}}
            with patch.object(coord,"config",return_value=cfg):
                for path in [bound,alias,bound/"child",root]:
                    with self.subTest(path=str(path)),self.assertRaises(coord.CoordinationError):
                        coord.authorize_claim({"id":"legacy","path":str(path)})
                self.assertIsNone(coord.authorize_claim({"id":"legacy","path":str(root/"unrelated")}))

    def test_cli_request_errors_are_actionable_without_network_or_config(self):
        driver = Path(__file__).resolve().parents[1]/"bin/ade-coord"
        cases = [("role", "get", "", "INVALID_JSON_REQUEST"),
                 ("role", "get", "[]", "JSON_OBJECT_REQUIRED"),
                 ("role", "get", "{}", "ROLE_ID_REQUIRED"),
                 ("inbox", "list", '{"snapshot":{"role_id":"r","revision":1},"authority":{}}', "SNAPSHOT_RECORD_AND_REVISION_REQUIRED"),
                 ("inbox", "list", '{"snapshot":{"record":{},"revision":1}}', "AUTHORITY_REQUIRED")]
        for group,command,payload,code in cases:
            with self.subTest(code=code):
                result = subprocess.run([sys.executable,"-I",str(driver),group,command],input=payload,capture_output=True,text=True)
                self.assertEqual(result.returncode,1)
                self.assertEqual(json.loads(result.stdout),{"ok":False,"error":{"code":code}})

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

    def test_isolated_sibling_callbacks_survive_temporary_path_restoration(self):
        bin_dir=Path(__file__).resolve().parents[1]/"bin"
        with tempfile.TemporaryDirectory() as tmp:
            env={**os.environ,"ADE_COORD_CONFIG":"","ADE_COORD_ENROLLMENT_MARKER":str(Path(tmp)/"absent")}
            for name in ("ade_claims.py","ade_lead_succession.py","ade_send_guard.py","ade_self_session.py","completion-notice"):
                code="import sys,importlib.util,importlib.machinery;from pathlib import Path;folder=Path(sys.argv[1]);original=list(sys.path);sys.path.insert(0,str(folder));loader=importlib.machinery.SourceFileLoader('probe',str(folder/sys.argv[2]));spec=importlib.util.spec_from_loader('probe',loader);module=importlib.util.module_from_spec(spec);sys.modules['probe']=module;loader.exec_module(module);sys.path[:]=original;coord=module._coord();assert coord.config() is None;coord._sibling('ade_coord_resources');assert sys.path==original"
                result=subprocess.run([sys.executable,"-I","-c",code,str(bin_dir),name],env=env,capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr)
            for name,args in (("ade-coord",["outbox","status"]),("ade_coord_controller.py",["--role","unenrolled"])):
                result=subprocess.run([sys.executable,"-I",str(bin_dir/name),*args],input="{}",env=env,capture_output=True,text=True,timeout=20)
                self.assertNotIn("ModuleNotFoundError",result.stderr)
                self.assertFalse(json.loads(result.stdout)["ok"])

    def test_managed_boundary_real_child_receives_only_selected_fresh_credential(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);boundary=root/"boundary"
            boundary.write_text("#!/usr/bin/env python3\nimport os,sys\na=sys.argv[sys.argv.index('--')+1:]\nenv={**os.environ,'ADE_NATS_TOKEN':'fresh-fixture','UNRELATED_MANAGED_SECRET':'do-not-propagate'}\nos.execvpe(a[0],a,env)\n");boundary.chmod(0o700)
            consumer=Path(__file__).resolve().parents[1]/"bin/ade_coord_consumer.py"
            code="import os,json;print(json.dumps({'fresh':os.environ.get('ADE_NATS_TOKEN')=='fresh-fixture','unrelated_absent':'UNRELATED_MANAGED_SECRET' not in os.environ,'node_options_absent':'NODE_OPTIONS' not in os.environ}))"
            result=subprocess.run([str(boundary),"run","--reason","fixture","--",sys.executable,"-I",str(consumer),sys.executable,"-I","-c",code],env={**os.environ,"ADE_NATS_TOKEN":"stale-fixture","NODE_OPTIONS":"must-not-propagate"},capture_output=True,text=True,timeout=20,check=True)
            self.assertEqual(json.loads(result.stdout),{'fresh':True,'unrelated_absent':True,'node_options_absent':True})
            self.assertNotIn('fresh-fixture',result.stdout)

if __name__=="__main__":unittest.main()
