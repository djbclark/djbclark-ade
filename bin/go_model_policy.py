"""Shared Go cost policy for routing and ACP entry points; no provider calls.

The JSON is also consumed directly by the native OpenCode plugin. A low monthly
cap alone is not a cost classification: inexpensive Luna remains routine.
"""

import json
from pathlib import Path
import re


POLICY_PATH = Path(__file__).resolve().parents[1] / "config/go-model-policy.json"


def policy():
    data = json.loads(POLICY_PATH.read_text())
    routine, advisory = data["routine_models"], data["advisory_models"]
    if not isinstance(routine, list) or not isinstance(advisory, list) or set(routine) & set(advisory):
        raise ValueError("invalid or overlapping Go model classifications")
    return data


def classification(model):
    if not isinstance(model, str) or not model.lower().startswith("opencode-go/"):
        return None
    name = model.lower().split("/", 1)[1]
    data = policy()
    if name in data["routine_models"]:
        return "routine"
    if name in data["advisory_models"]:
        return "advisory"
    return "unclassified"


def context_tokens(value):
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([km]?)", str(value).lower())
    if not match:
        return None
    return float(match[1]) * {"": 1, "k": 1000, "m": 1000000}[match[2]]


def refusal(model, *, advisory=False, timeout=0, perm="all", context=None):
    category = classification(model)
    if category is None or category == "routine":
        return None
    if category == "unclassified":
        return f"Go model {model!r} is unclassified; classify its cost before using it"
    data = policy()
    if not advisory:
        return f"Go model {model!r} is advisory-only; use a routine Flash/MiniMax/Luna model for execution"
    if perm != "read-only":
        return "Go advisory use requires --perm read-only"
    if not 0 < timeout <= data["advisory_timeout_seconds"]:
        return f"Go advisory use requires 0 < --timeout <= {data['advisory_timeout_seconds']} seconds"
    if context is not None:
        tokens = context_tokens(context)
        if tokens is None or not 0 < tokens <= data["advisory_context_tokens"]:
            return f"Go advisory --context must be at most {data['advisory_context_tokens']} tokens"
    return None
