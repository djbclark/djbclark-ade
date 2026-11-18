"""Linux integration fixture: real broker/OS child, synthetic native API only."""
import json
import os
from pathlib import Path
import signal
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bin"))
from ade_coord import config, call, CoordinationError
from ade_coord_handoff import transfer
from ade_coord_resources import process_identity, same_process
cfg=config(); request=json.load(sys.stdin)
marker=Path(cfg["state_dir"])/"native-closed"
runtime=cfg["roles"][request["role_id"]]["runtime"]

def native(*args):
    if args[0]=="inspect":
        return {"Archived":marker.exists(),"Status":"closed" if marker.exists() else "idle","Provider":"test-fixture","PendingPermissions":[]}
    if args[0]=="archive":
        for identity in runtime["processes"]:
            if same_process(process_identity(identity["pid"]),identity):
                os.kill(identity["pid"],signal.SIGTERM)
            until=time.monotonic()+5
            while same_process(process_identity(identity["pid"]),identity):
                if time.monotonic()>until: raise CoordinationError("TEST_CHILD_DID_NOT_EXIT")
                time.sleep(.02)
        marker.write_text("closed")
        return {}
    raise AssertionError(args)

def protocol(command,body,**kwargs):
    value=call(command,body,**kwargs)
    # A real committed state change whose client response is lost.
    if command in ("role transition","role transfer"):
        lost=Path(cfg["state_dir"])/("lost-"+command.replace(" ","-"))
        if not lost.exists():
            lost.write_text("injected after actual commit")
            raise CoordinationError("UNKNOWN")
    return value

try:
    result=transfer(request,cfg=cfg,native_call=native,protocol=protocol)
    print(json.dumps({"ok":True,"result":result}))
except CoordinationError as error:
    print(json.dumps({"ok":False,"error":str(error)}));sys.exit(1)
