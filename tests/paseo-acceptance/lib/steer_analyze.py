#!/usr/bin/env python3
"""steer_analyze.py: timeline analysis for d1-01-steer.sh (plan T4). Stdlib only.

`paseo logs ID --json` prints the timeline as plain text (checked 2026-11-02, CLI 0.15.0-beta.1, omp): one block per
entry, each starting with `[Tag] text` (`[User]`, `[Shell]`, `[Thought]`, `[Wait]`, ...); assistant text is the untagged
lines. Commands:
  intool FILE                       exit 0 when a tool block that mentions `sleep` is on the timeline (the turn is inside the sleep)
  settled FILE MARKER               exit 0 when the marker is in assistant text (the steered input has been answered)
  verdict PROVIDER EVDIR MARKER RC  print one JSON line {provider, verdict, steers, queues, interrupts, evidence}
  matrix ROWS.jsonl OUT.json BASE   merge the rows plus versions and the skipped providers into OUT.json (atomic)
verdict is one of: steers (marker is a user entry BEFORE the first answer, turn finished, marker answered),
queues (marker is a user entry AFTER the first answer, i.e. the next turn, and answered), interrupts (the first
answer never came or an interrupt/cancel entry exists), lost (no user entry carries the marker), no-tool (the agent never
reached the sleep, nothing was sent), unanswered (marker delivered but never answered, turn survived).
"""
import json
import os
import re
import subprocess
import sys
import time

TAG = re.compile(r"^\[([A-Za-z][A-Za-z ]{0,30})\](?: (.*))?$")
INTERRUPT = re.compile(r"interrupt|cancel+ed|abort|killed|stopped by user", re.I)
FINAL = "FIRST"


def blocks(path):
    """[(tag, text)]; tag is '' for assistant (untagged) text."""
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        m = TAG.match(ln)
        if m:
            out.append([m.group(1), m.group(2) or ""])
        elif out and out[-1][0] == "":
            out[-1][1] += "\n" + ln
        elif ln.strip():
            # untagged text is assistant text, also straight after a [User] entry (the probe's prompts are single-line)
            out.append(["", ln])
    return [(t, x) for t, x in out]


def intool(path):
    return any(t not in ("User", "Thought", "") and "sleep" in x.lower() for t, x in blocks(path))


def assistant_text(bl):
    return "\n".join(x for t, x in bl if t == "")


def analyze(path, marker):
    bl = blocks(path)
    user_idx = [i for i, (t, x) in enumerate(bl) if t == "User" and marker in x]
    ans_idx = [i for i, (t, x) in enumerate(bl) if t == "" and re.search(r"(?m)^\s*" + FINAL + r"\b", x)]
    marker_ans = [i for i, (t, x) in enumerate(bl) if t == "" and marker in x]
    intr = [(t, x[:120]) for t, x in bl if t not in ("User", "Thought", "") and INTERRUPT.search(x)]
    return {
        "blocks": len(bl),
        "markerUserEntry": bool(user_idx),
        "markerBeforeFirstAnswer": bool(user_idx and ans_idx and user_idx[0] < ans_idx[0]),
        "firstAnswered": bool(ans_idx),
        "markerAnswered": bool(marker_ans),
        "interruptEntries": intr,
        "sleepToolEntries": (lambda ts: ts.count(ts[0]) if ts else 0)(
            [t for t, x in bl if t not in ("User", "Thought", "") and "sleep" in x.lower()]),
        "providerError": next((x[:160] for t, x in bl if t in ("", "Error") and x.strip()), None),
        "tags": sorted({t for t, _ in bl if t}),
    }


def verdict_of(a, sent_rc):
    if sent_rc == "no-tool":
        # the turn never reached the sleep: a provider-side error (quota, auth) is not a steer verdict at all
        return "provider-error" if a.get("providerError") else "no-tool"
    if not a["markerUserEntry"]:
        return "lost"
    if a["interruptEntries"] or not a["firstAnswered"]:
        return "interrupts"
    if not a["markerAnswered"]:
        return "unanswered"
    return "steers" if a["markerBeforeFirstAnswer"] else "queues"


def read_json(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return {}


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "intool":
        return 0 if intool(argv[2]) else 1
    if cmd == "settled":
        return 0 if analyze(argv[2], argv[3])["markerAnswered"] else 1
    if cmd == "verdict":
        p, ev, marker, rc = argv[2:6]
        a = analyze(os.path.join(ev, "post.json"), marker)
        v = verdict_of(a, rc)
        insp = read_json(os.path.join(ev, "inspect.json"))
        insp = insp if isinstance(insp, dict) else {}
        print(json.dumps({"provider": p, "verdict": v, "steers": v == "steers", "queues": v == "queues",
                          "interrupts": v == "interrupts", "toolRestarted": a["sleepToolEntries"] > 1,
                          "sendRc": rc, "agentStatus": insp.get("Status"),
                          "model": insp.get("Model"), "mode": insp.get("Mode"),
                          "availableModes": [m.get("id") for m in insp.get("AvailableModes") or []],
                          "costUsd": (insp.get("LastUsage") or {}).get("CostUsd"),
                          "evidence": {"dir": ev, "analysis": a}}, sort_keys=True))
        return 0
    if cmd == "matrix":
        rows, out, base = argv[2:5]
        provs = {}
        for ln in open(rows):
            ln = ln.strip()
            if ln:
                r = json.loads(ln)
                provs[r["provider"]] = {k: v for k, v in r.items() if k != "provider"}
        vers = {}
        try:
            vers = json.load(open(os.path.join(base, "status.json")))
        except (OSError, ValueError):
            pass
        cli = subprocess.run(["paseo", "-v"], capture_output=True, text=True).stdout.strip()
        doc = {"probe": "d1-01-steer", "date": time.strftime("%Y-%m-%d", time.gmtime()), "cliVersion": cli,
               "daemonVersion": vers.get("version") or vers.get("daemonVersion"), "providers": provs,
               "skipped": {"claude": "skipped: claude pool protected (djbclark 2026-11-02)",
                           "cline": "skipped: cline/clinepass pool protected (djbclark 2026-11-02)",
                           "opencode": "skipped: opencode-go pool protected (djbclark 2026-11-02)",
                           "antigravity": "no steering (recorded without a probe, plan T4)"}}
        tmp = out + ".tmp"
        with open(tmp, "w") as f:
            json.dump(doc, f, indent=2, sort_keys=True)
        os.replace(tmp, out)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
