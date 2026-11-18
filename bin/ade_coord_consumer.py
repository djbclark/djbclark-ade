#!/usr/bin/env python3
"""Managed-consumer hop: retain only this consumer's credential and safe runtime env."""
import json
import os
import sys
allowed={"PATH","HOME","XDG_CONFIG_HOME","LANG","LC_ALL","LC_CTYPE","TMPDIR","TMP","TEMP","ADE_NATS_URL","ADE_NATS_TOKEN"}
env={key:value for key,value in os.environ.items() if key in allowed}
if not env.get("ADE_NATS_TOKEN"):
    print(json.dumps({"ok":False,"error":{"code":"MANAGED_CREDENTIAL_MISSING"}}))
    raise SystemExit(1)
if len(sys.argv)<2:
    raise SystemExit(2)
os.execvpe(sys.argv[1],sys.argv[1:],env)
