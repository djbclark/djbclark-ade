#!/usr/bin/env python3
"""Offer to move this session's herdr tab out of a generic workspace.

Part of /autorename: after the session is titled, a tab sitting in a workspace
called "shells", "src", "~", "6" or similar should probably live with related
work. This script gathers the facts; the agent asks the operator; this script
does the move.

    herdr_place.py check [--auto]                 # JSON facts for the agent
    herdr_place.py move --workspace W --tab-label L
    herdr_place.py move --new-workspace NAME --tab-label L
    herdr_place.py label [L | --from-title] [--force]   # label THIS tab (a bare number otherwise)
    HERDR_PANE_ID=<other pane> CLAUDE_CODE_SESSION_ID=<its session> \
        herdr_place.py move ... --no-focus        # sort another session's tab
    herdr_place.py decline                        # remember "leave it", no re-ask

herdr has no tab-to-workspace move, so `move` moves every pane of the current
tab: this pane into a new tab in the target (`herdr pane move --new-tab` or
`--new-workspace`), the
rest split into that tab. The old pane id stays valid as an alias, so the
running session's HERDR_PANE_ID keeps working.

`check --auto` (the nudge-hook path) reports `"ask": false` when
the operator already answered for this session. Exit 0 always for `check`
(`"in_herdr": false` outside herdr); `move` exits 1 on a herdr error.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

GENERIC = {
    "", "~", "home", "shell", "shells", "src", "source", "tmp", "temp", "misc",
    "scratch", "default", "main", "untitled", "unnamed", "new", "workspace",
    "bash", "zsh", "fish", "terminal", "term", "agents", "work",
}


def herdr(*args: str) -> dict[str, Any]:
    out = subprocess.run(["herdr", *args], capture_output=True, text=True, timeout=15)
    try:
        data = json.loads(out.stdout)
    except ValueError:
        raise RuntimeError(f"herdr {' '.join(args)}: {(out.stderr or out.stdout).strip()}")
    if "error" in data:
        raise RuntimeError(f"herdr {' '.join(args)}: {data['error']}")
    return data["result"]


def generic_reason(label: str) -> str | None:
    norm = label.strip().lower()
    if norm in GENERIC or norm == Path.home().name.lower():
        return f"label {label!r} is a catch-all name" if norm else "workspace has no label"
    if re.fullmatch(r"(workspace|ws|tab)?\s*#?\d+", norm):
        return f"label {label!r} is just a number"
    return None


def state_path(sid: str) -> Path:
    return Path.home() / ".local/state/autorename" / f"{sid}.placement"


def check(auto: bool) -> int:
    pane_id = os.environ.get("HERDR_PANE_ID")
    if os.environ.get("HERDR_ENV") != "1" or not pane_id:
        print(json.dumps({"in_herdr": False}))
        return 0
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    try:
        pane = herdr("pane", "get", pane_id)["pane"]
        workspaces = herdr("workspace", "list")["workspaces"]
        here = next(w for w in workspaces if w["workspace_id"] == pane["workspace_id"])
        tabs = herdr("tab", "list", "--workspace", here["workspace_id"])["tabs"]
        tab = next(t for t in tabs if t["tab_id"] == pane["tab_id"])
        others = []
        for w in workspaces:
            if w["workspace_id"] == here["workspace_id"]:
                continue
            labels = [t["label"] for t in herdr("tab", "list", "--workspace", w["workspace_id"])["tabs"]]
            others.append({"workspace_id": w["workspace_id"], "label": w["label"],
                           "generic": generic_reason(w["label"]) is not None, "tab_labels": labels})
    except (RuntimeError, StopIteration, KeyError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"in_herdr": True, "error": str(exc), "ask": False}))
        return 0

    reason = generic_reason(here["label"])
    answered = bool(sid) and state_path(sid).exists()
    print(json.dumps({
        "in_herdr": True,
        "pane_id": pane["pane_id"],
        "cwd": pane.get("cwd"),
        "tab": {"tab_id": tab["tab_id"], "label": tab["label"], "pane_count": tab["pane_count"]},
        "workspace": {"workspace_id": here["workspace_id"], "label": here["label"],
                      "generic": reason is not None, "reason": reason},
        "other_workspaces": others,
        "already_answered": answered,
        "ask": reason is not None and not (auto and answered),
    }, indent=1))
    return 0


def remember(answer: str) -> None:
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if sid:
        path = state_path(sid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(answer + "\n", encoding="utf-8")


def move(workspace: str | None, new_workspace: str | None, tab_label: str, focus: bool = True) -> int:
    pane_id = os.environ.get("HERDR_PANE_ID")
    if not pane_id:
        print("herdr_place: not in a herdr pane", file=sys.stderr)
        return 1
    try:
        pane = herdr("pane", "get", pane_id)["pane"]
        siblings = [p["pane_id"] for p in herdr("pane", "list", "--workspace", pane["workspace_id"])["panes"]
                    if p["tab_id"] == pane["tab_id"] and p["pane_id"] != pane["pane_id"]]
        if workspace:
            dest = ["--new-tab", "--workspace", workspace, "--label", tab_label]
        else:
            dest = ["--new-workspace", "--label", new_workspace or "", "--tab-label", tab_label]
        result = herdr("pane", "move", pane["pane_id"], *dest,
                       "--focus" if focus else "--no-focus")["move_result"]
        new_tab = result["pane"]["tab_id"]
        for sib in siblings:
            herdr("pane", "move", sib, "--tab", new_tab, "--split", "right", "--no-focus")
    except (RuntimeError, KeyError, subprocess.TimeoutExpired) as exc:
        print(f"herdr_place: {exc}", file=sys.stderr)
        return 1
    ws_label = (result.get("created_workspace") or {}).get("label")
    if not ws_label:
        try:
            ws_label = herdr("workspace", "get", str(workspace))["workspace"]["label"]
        except (RuntimeError, KeyError, subprocess.TimeoutExpired):
            ws_label = workspace
    remember(f"moved {new_tab}")
    print(f"moved: tab {tab_label!r} ({1 + len(siblings)} pane(s)) -> workspace {ws_label!r} as {new_tab}")
    return 0


def slug_from_title(title: str, max_len: int = 28) -> str:
    """'ClaudeHelm night run 2026-10-09 + Collie 1.18.1' -> 'claudehelm-night-run-collie-t'."""
    import re
    words = [w for w in re.sub(r"[^a-z0-9]+", " ", title.lower()).split() if not re.fullmatch(r"[0-9.-]+", w)]
    out = ""
    for w in words:
        cand = f"{out}-{w}" if out else w
        if len(cand) > max_len:
            break
        out = cand
    return (out or "session") + "-t"


def label(text: str | None, from_title: bool, force: bool) -> int:
    """Rename this pane's herdr tab. /rename and autorename.py set the session title and the
    terminal title only; the sidebar tab keeps its default number until this runs."""
    pane_id = os.environ.get("HERDR_PANE_ID")
    if os.environ.get("HERDR_ENV") != "1" or not pane_id:
        print("skipped: not in a herdr pane")
        return 0
    if from_title:
        from autorename import current_title, find_transcript  # same directory
        sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
        transcript = find_transcript(sid) if sid else None
        title = current_title(transcript) if transcript else None
        if not title:
            print("skipped: the session has no custom title yet (run autorename.py first)", file=sys.stderr)
            return 2
        text = slug_from_title(title)
    if not text:
        print("a label or --from-title is required", file=sys.stderr)
        return 2
    try:
        pane = herdr("pane", "get", pane_id)["pane"]
        tabs = herdr("tab", "list", "--workspace", pane["workspace_id"])["tabs"]
        tab = next(t for t in tabs if t["tab_id"] == pane["tab_id"])
        if tab["label"] == text:
            print(f"unchanged: tab {tab['tab_id']} already {text!r}")
            return 0
        if not force and generic_reason(tab["label"]) is None:
            print(f"kept: tab {tab['tab_id']} already has a real label {tab['label']!r} (--force to replace)")
            return 0
        herdr("tab", "rename", tab["tab_id"], text)
    except (RuntimeError, StopIteration, KeyError, subprocess.TimeoutExpired) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"labelled: tab {tab['tab_id']} {tab['label']!r} -> {text!r}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--auto", action="store_true", help="don't re-ask once answered this session")
    m = sub.add_parser("move")
    g = m.add_mutually_exclusive_group(required=True)
    g.add_argument("--workspace", help="existing workspace id, e.g. w22")
    g.add_argument("--new-workspace", metavar="NAME")
    m.add_argument("--tab-label", required=True)
    m.add_argument("--no-focus", action="store_true",
                   help="don't follow the tab (moving another session's pane via HERDR_PANE_ID=...)")
    lb = sub.add_parser("label", help="label this pane's tab (sidebar); generic labels only unless --force")
    lb.add_argument("text", nargs="?", help="the label, kebab-case with a -t suffix")
    lb.add_argument("--from-title", action="store_true", help="derive it from the session's custom title")
    lb.add_argument("--force", action="store_true", help="replace a non-generic label too")
    sub.add_parser("decline")
    args = ap.parse_args()

    if args.cmd == "check":
        return check(args.auto)
    if args.cmd == "label":
        return label(args.text, args.from_title, args.force)
    if args.cmd == "move":
        return move(args.workspace, args.new_workspace, args.tab_label, not args.no_focus)
    remember("declined")
    print("declined: tab stays where it is")
    return 0


if __name__ == "__main__":
    sys.exit(main())
