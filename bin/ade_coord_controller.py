#!/usr/bin/env python3
"""One bounded machine inbox pass. Scheduling belongs to optional plugin/controller."""
import argparse
import json
from ade_coord import pump, remember_enrollment, CoordinationError
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
