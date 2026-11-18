"""Synthetic native wake transport; real broker fencing is covered in Node CI."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bin"))
from ade_coord import CoordinationError
from ade_coord_wake import wake,reconcile,status,blockers

class WakeTests(unittest.TestCase):
    def fixture(self,root):
        cfg={"generation":"g","state_dir":str(root),"identity":{"host":"h","server":"s"},"roles":{"r":{"wake":True}}}
        state={"role":{"revision":1,"record":{"role_id":"r","generation":"g","state":"active","owner":{"host":"h","server":"s","agent":"a"},"ownership_epoch":1}},"pending":[{"revision":10,"record":{"report":{"message_id":"one"}}}],"ops":{},"mode":"busy","calls":0,"delivered":0,"gets":0}
        def protocol(command,request,**kwargs):
            if command=="role get":
                state["gets"]+=1
                return copy.deepcopy(state["role"])
            if command=="inbox list":return copy.deepcopy(state["pending"])
            if command=="shared-operation inspect":return copy.deepcopy(state["ops"].get(request["id"]))
            if command=="shared-operation intent":
                state["ops"][request["id"]]={"revision":20,"record":{"state":"UNKNOWN","intent":request["intent"]}};return state["ops"][request["id"]]
            if command=="shared-operation reconcile":
                row=state["ops"][request["id"]];row["record"].update(state=request["state"],resolution={"result":request["result"],"evidence":request["evidence"]});return row
            raise AssertionError(command)
        def native(argv):
            if argv[:2]==["daemon","status"]:return {"serverId":"wrong" if state["mode"]=="wrong-server" else "s"}
            if argv[:2]==["agent","inspect"]:return {"Id":state["role"]["record"]["owner"]["agent"],"Archived":state["mode"]=="archived","Status":"running" if state["mode"]=="busy" else "idle","PendingPermissions":[]}
            if argv[0]=="send":
                state["calls"]+=1
                if state["mode"]=="unknown":raise CoordinationError("UNKNOWN")
                state["delivered"]+=1;return {"status":"queued"}
            raise AssertionError(argv)
        return cfg,state,protocol,native

    def test_busy_delays_restart_coalesces_deletions_do_not_wake_and_epoch_resets(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg,state,protocol,native=self.fixture(Path(tmp))
            self.assertEqual(wake(cfg,"r",protocol=protocol,native_call=native)["status"],"deferred-busy")
            state["mode"]="idle";self.assertEqual(wake(cfg,"r",protocol=protocol,native_call=native)["status"],"accepted")
            self.assertEqual(wake(cfg,"r",protocol=protocol,native_call=native)["status"],"coalesced");self.assertEqual(state["calls"],1)
            state["pending"]=[{"revision":9,"record":{"report":{"message_id":"older"}}}]
            self.assertEqual(wake(cfg,"r",protocol=protocol,native_call=native)["status"],"coalesced")
            state["role"]["record"]["ownership_epoch"]=2;state["role"]["record"]["owner"]["agent"]="b"
            self.assertEqual(wake(cfg,"r",protocol=protocol,native_call=native)["status"],"accepted");self.assertEqual(state["calls"],2)
            state["pending"]=[{"revision":11,"record":{"report":{"message_id":"new"}}}]
            state["mode"]="archived";self.assertEqual(wake(cfg,"r",protocol=protocol,native_call=native)["status"],"refused-target")
            state["mode"]="wrong-server";self.assertEqual(wake(cfg,"r",protocol=protocol,native_call=native)["status"],"refused-daemon");self.assertEqual(state["calls"],2)

    def test_unknown_does_not_retry_and_blocks_handoff_until_endpoint_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg,state,protocol,native=self.fixture(Path(tmp));state["mode"]="unknown"
            result=wake(cfg,"r",protocol=protocol,native_call=native);self.assertEqual(result["status"],"unknown-no-retry")
            self.assertEqual(blockers(cfg,"r",1),[result["wake_id"]]);state["mode"]="idle"
            self.assertEqual(wake(cfg,"r",protocol=protocol,native_call=native)["status"],"coalesced");self.assertEqual(state["calls"],1)
            reconcile(cfg,{"wake_id":result["wake_id"],"state":"SUCCEEDED","result":{"native_status":"queued"},"evidence":{"endpoint":"confirmed enqueue"}},protocol=protocol)
            self.assertEqual(blockers(cfg,"r",1),[])
            with self.assertRaises(CoordinationError):reconcile(cfg,{"wake_id":result["wake_id"],"state":"NOT_APPLIED","evidence":{"endpoint":"contradiction"}},protocol=protocol)
            self.assertEqual(state["calls"],1)

    def test_explicit_not_applied_rearm_preserves_history_and_one_actual_notification(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg,state,protocol,native=self.fixture(Path(tmp));state["mode"]="unknown"
            first=wake(cfg,"r",protocol=protocol,native_call=native)
            reconcile(cfg,{"wake_id":first["wake_id"],"state":"NOT_APPLIED","result":None,"evidence":{"endpoint":"verified no enqueue"},"rearm":True},protocol=protocol)
            state["mode"]="idle";second=wake(cfg,"r",protocol=protocol,native_call=native)
            self.assertNotEqual(first["wake_id"],second["wake_id"]);self.assertEqual(state["delivered"],1);self.assertEqual(len(status(cfg,"r")),2)

    def test_replaced_owner_before_send_is_fenced_without_notification(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg,state,protocol,native=self.fixture(Path(tmp));state["mode"]="idle"
            def replaced(command,request,**kwargs):
                if command=="role get" and state["gets"]==1:
                    state["role"]["revision"]=2;state["role"]["record"]["ownership_epoch"]=2;state["role"]["record"]["owner"]["agent"]="b"
                return protocol(command,request,**kwargs)
            self.assertEqual(wake(cfg,"r",protocol=replaced,native_call=native)["status"],"refused-replaced");self.assertEqual(state["calls"],0)

if __name__=="__main__":unittest.main()
