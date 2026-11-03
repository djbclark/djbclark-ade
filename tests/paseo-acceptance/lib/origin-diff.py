#!/usr/bin/env python3
"""origin-diff.py LOG TITLE=PATH ... : summarise the origin-probe hook log per create path (plan T11).

For each title: the agent.create.before payload (matched by request.config.title), the agent.open.before payload with
reason "create" (matched by title), and the agent.create.after agent record. Prints ONE JSON object:
  paths.<path>: {createBeforeKeys, createConfigKeys, createBeforeRequestKeys, openKeys, openReason, openLabels,
                 openLabelKeys, createAfterParentAgentId, createAfterKeys, found}
  originFieldsPeers: the same, over the paths WITHOUT a caller agent (names not ending in "-sub").
  originFields: every field (hook.field or hook.labels.KEY) whose presence or value differs between paths, after
  dropping the fields that are expected to differ (ids, title, cwd, workspaceId).
Variable fields are masked before comparing so only structural/semantic differences remain."""
import json
import sys

VARIABLE = {"id", "agentId", "title", "cwd", "workspaceId", "turnId", "at", "parentAgentId"}


def load(path):
    out = []
    for line in open(path):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def flat(value, prefix=""):
    """Flatten nested dicts to {dotted.key: value}; lists stay values."""
    out = {}
    if isinstance(value, dict):
        for k, v in value.items():
            out.update(flat(v, f"{prefix}{k}."))
    else:
        out[prefix[:-1]] = value
    return out


def main():
    log, specs = sys.argv[1], sys.argv[2:]
    events = load(log)
    paths = {}
    for spec in specs:
        name, title = spec.split("=", 1)
        cb = next((e["payload"]["request"] for e in events if e.get("hook") == "agent.create.before"
                   and e["payload"]["request"].get("config", {}).get("title") == title), None)
        ob = next((e["payload"]["request"] for e in events if e.get("hook") == "agent.open.before"
                   and e["payload"]["request"].get("title") == title and e["payload"]["request"].get("reason") == "create"), None)
        ca = next((e["payload"]["agent"] for e in events if e.get("hook") == "agent.create.after"
                   and e["payload"]["agent"].get("title") == title), None)
        paths[name] = {
            "found": {"create.before": cb is not None, "open.before": ob is not None, "create.after": ca is not None},
            "createBeforeRequestKeys": sorted(cb) if cb else None,
            "createConfigKeys": sorted(cb.get("config", {})) if cb else None,
            "openKeys": sorted(ob) if ob else None,
            "openReason": ob.get("reason") if ob else None,
            "openLabels": ob.get("labels") if ob else None,
            "createAfterKeys": sorted(ca) if ca else None,
            "createAfterParentAgentId": (ca.get("parentAgentId") if ca else None),
            "_flat": {"agent.create.before": flat(cb or {}), "agent.open.before": flat(ob or {}), "agent.create.after": flat(ca or {})},
        }
    def differing(include):
        origin = {}
        for hook in ("agent.create.before", "agent.open.before", "agent.create.after"):
            names = [n for n in paths if include(n) and paths[n]["found"][hook.split(".", 1)[1]]]
            keys = set()
            for n in names:
                keys |= set(paths[n]["_flat"][hook])
            for k in sorted(keys):
                if k.split(".")[-1] in VARIABLE or k.endswith(".__keys"):
                    continue
                vals = {n: paths[n]["_flat"][hook].get(k, "<absent>") for n in names}
                if len({json.dumps(v, sort_keys=True) for v in vals.values()}) > 1:
                    origin[f"{hook}:{k}"] = vals
            # a parentAgentId set on some paths is an origin signal too (it was masked as variable above)
            pv = {n: paths[n]["_flat"][hook].get("parentAgentId", "<absent>") for n in names}
            if any(v not in (None, "<absent>") for v in pv.values()):
                origin[f"{hook}:parentAgentId(set-or-null)"] = {n: ("set" if v not in (None, "<absent>") else v) for n, v in pv.items()}
        return origin

    origin = differing(lambda n: True)
    # peers: the paths that have no caller agent (cli, mcp-top, sdk); "sub" paths carry a parent by construction
    peers = differing(lambda n: not n.endswith("-sub"))
    for p in paths.values():
        p.pop("_flat")
    print(json.dumps({"paths": paths, "originFields": origin, "originFieldsPeers": peers}, sort_keys=True))


main()
