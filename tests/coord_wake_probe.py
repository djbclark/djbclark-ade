"""Real broker/SQLite with a synthetic native endpoint; never messages real agents."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bin"))
from ade_coord import config,CoordinationError
from ade_coord_wake import wake,reconcile
cfg=config();request=json.load(sys.stdin)
def native(argv):
    if argv[:2]==["daemon","status"]:return {"serverId":cfg["identity"]["server"]}
    if argv[:2]==["agent","inspect"]:return {"Id":argv[2],"Archived":False,"Status":"running" if request.get("mode")=="busy" else "idle","PendingPermissions":[]}
    if argv[0]=="send":
        with (Path(cfg["state_dir"])/"synthetic-wake-calls").open("a") as stream:stream.write(json.dumps({"target":argv[3],"mode":request.get("mode")})+"\n")
        if request.get("mode")=="unknown":raise CoordinationError("SYNTHETIC_UNKNOWN")
        return {"status":"queued"}
    raise AssertionError(argv)
result=reconcile(cfg,request) if request.get("command")=="reconcile" else wake(cfg,request["role_id"],native_call=native)
print(json.dumps({"ok":True,"result":result}))
