"""Real-broker deterministic managed-launch admission pause fixture (Linux CI)."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bin"))
from ade_coord import config,call,authority
from ade_coord_resources import Resources,run_job
cfg=config();root=Path(cfg["state_dir"])
current=call("role get",{"role_id":"gate"},cfg=cfg)
state=Resources(root/"jobs",admission_directory=root)
def authorize(*_):
    fresh=call("role get",{"role_id":"gate"},cfg=cfg)
    assert fresh==current
    print("AUTHORIZED",flush=True)
    assert sys.stdin.readline().strip()=="GO"
try:
    run_job(state,job="paused-admission",claim="gateClaim",authority=authority(current),authorize=authorize,
            argv=[sys.executable,"-c","import pathlib,sys,time;p=pathlib.Path(sys.argv[1]);\nwhile not p.exists():time.sleep(.02)",str(root/"finish-admitted-job")])
finally:state.close()
