#!/usr/bin/env python3
"""One bounded machine inbox pass. Scheduling belongs to optional plugin/controller."""
import argparse
import json
from pathlib import Path
def _coord():
    """Load only our trusted absolute sibling; valid after temporary -I paths restore."""
    import importlib.util
    import sys
    path = Path(__file__).resolve().with_name("ade_coord.py")
    name = "ade_coord"
    found = sys.modules.get(name)
    if found is not None and Path(found.__file__).resolve() == path:
        return found
    key = name if found is None else "_ade_coord_" + str(path)
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(key, None)
        raise
    return module


pump = _coord().pump
remember_enrollment = _coord().remember_enrollment
CoordinationError = _coord().CoordinationError
parser=argparse.ArgumentParser()
parser.add_argument("--role")
parser.add_argument("--enroll",action="store_true")
args=parser.parse_args()
try:
    if args.enroll:
        result=remember_enrollment()
    elif args.role:
        result=pump(args.role)
    else:
        raise CoordinationError("ROLE_REQUIRED")
    print(json.dumps({"ok":True,"result":result}))
except Exception as error:
    print(json.dumps({"ok":False,"error":{"code":str(error) if isinstance(error,CoordinationError) else "UNKNOWN"}}))
    raise SystemExit(1)
