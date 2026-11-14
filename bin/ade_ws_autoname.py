#!/usr/bin/env python3
"""Automatic window (Paseo workspace) naming: decide the `<KIND> <repo> (<work>)` name for a new window, or leave it alone.

Called by the `ade-window-name` Paseo plugin (plugins/ade-window-name, hooks `agent.create.after` and `agent.turn.after`)
so every new window on this host gets a scheme name without any agent having to remember (operator, 2026-11-14: "Some
projects are still starting new workspaces without our MAIN/WORKERS/etc repo-name scheme"). The plugin gathers facts from
the daemon and passes them as one JSON object on stdin; this module decides and prints one JSON object on stdout. All naming
rules live here, in Python, on top of `ade_ws_names` (the one builder/parser `bin/ade-worker-run` and `bin/ade-tidy` also
use), so there is no second copy of the format.

    echo '{"cwd": "...", "windowTitle": null, "firstAgent": true, "agent": {...}}' | python3 bin/ade_ws_autoname.py

Input keys (all but `cwd` optional):
  cwd            the new agent's working directory (repo = the main checkout's name via git, else the directory's basename)
  windowTitle    the window's raw title (the plugin sends null for Paseo's prompt pre-title too): null or blank = Paseo's default name (derived from branch/directory); anything else
                 was named on purpose (a human, an agent, `ade-worker-run`, or Paseo's own generator) and is never touched
  firstAgent     true when this is the window's first live, non-background agent; false = skip
  background     true = a hidden helper window/agent: skip
  agent          {title, parentAgentId, labels}: `title` is the work text source (a tab name `worker <slice> <lead id>` and a
                 `LEAD <repo> <work>` / `MAIN <repo> <work>` tab each reduce to their slice / work)

Output: {"action": "rename", "name", "kind", "repo", "work"} or {"action": "skip", "reason", "retry"} (retry true: ask again on
a later event, the agent had no title yet). Exit 0 either way; exit 2 on
unreadable input (the plugin treats any non-zero exit as "leave the window alone").

KIND rules (docs/workspace-layout.md):
  WORKERS  the agent has a parent (`parentAgentId`) or an `ade.lead` label, or `ade.placement=workers`
  USER     only by an explicit `ade.placement=user` label: USER is what a lead connects the operator's agents into (the tidy
           skill moves them); a first agent the operator started is MAIN
  MAIN     everything else (an operator-started first agent, a lead's own window); `ade.placement=main` says so explicitly

"Paseo default name" means the window's own title is null (Paseo's `title` field is the user-set override; null means the name
is derived from the branch or directory, e.g. `master`). A title that already reads `MAIN repo (work)` is a title, so it is
left alone like any other.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import ade_ws_names as names  # noqa: E402

WORK_LIMIT = 50  # characters of work text; the whole name stays under ade_ws_names.NAME_LIMIT
_UUID = names.UUID_RE
_WORKER_TAB_RE = re.compile(rf"^worker\s+(.+?)\s+{_UUID}$")
_LEAD_TAB_RE = re.compile(r"^(?:LEAD|MAIN)\s+(.+)$")  # the tab names `LEAD <repo> <work>`; an ordinary "Lead the migration" stays
PLACEMENT_KINDS = {"main": "MAIN", "workers": "WORKERS", "user": "USER"}


def skip(reason: str, retry: bool = False) -> dict:
    """`retry` true = a later event may succeed (the agent has no title yet); false = this window will never be named from here."""
    return {"action": "skip", "reason": reason, "retry": retry}


def kind_for(agent: dict) -> str:
    """WORKERS for an agent with a parent or lead; USER/MAIN/WORKERS only as the explicit `ade.placement` label says; else MAIN."""
    labels = agent.get("labels") if isinstance(agent.get("labels"), dict) else {}
    placement = PLACEMENT_KINDS.get(str(labels.get("ade.placement") or "").strip().lower())
    if placement:
        return placement
    if agent.get("parentAgentId") or str(labels.get("ade.lead") or "").strip():
        return "WORKERS"
    return "MAIN"


def work_from_title(title: object, repo: str) -> str | None:
    """A short single-line work text from an agent tab title, or None when nothing usable is left."""
    if not isinstance(title, str):
        return None
    text = " ".join(title.split())  # one line, single spaces, no control characters
    text = "".join(ch for ch in text if ch.isprintable())
    m = _WORKER_TAB_RE.match(text)
    if m:
        text = m.group(1)
    else:
        m = _LEAD_TAB_RE.match(text)
        if m:
            text = m.group(1)
    if text.startswith(repo + " "):
        text = text[len(repo) + 1:]
    text = text.replace("(", "[").replace(")", "]").strip(" -:")  # a work text is read back by a `(.+)$` parser
    if len(text) > WORK_LIMIT:
        cut = text[:WORK_LIMIT].rsplit(" ", 1)[0] or text[:WORK_LIMIT]
        text = cut.rstrip(" -:,;")
    return text if text and text != repo else None


def decide(info: dict) -> dict:
    if not isinstance(info, dict):
        return skip("input is not an object")
    if info.get("background"):
        return skip("background window or agent")
    window_title = info.get("windowTitle")
    if window_title is not None and not isinstance(window_title, str):
        return skip("windowTitle is neither null nor a string")
    if window_title and window_title.strip():
        return skip("window already has a title (named on purpose)")  # a blank string is no title, as Paseo itself reads it
    if info.get("firstAgent") is not True:
        return skip("not the window's first agent", retry=True)  # the first agent may still be unnamed, or archived later
    cwd = info.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        return skip("no cwd")
    agent = info.get("agent") if isinstance(info.get("agent"), dict) else {}
    labels = agent.get("labels") if isinstance(agent.get("labels"), dict) else {}
    if labels.get("slice") and labels.get("ade.lead"):
        return skip("a bin/ade-worker-run launch (slice + ade.lead labels): it names its own window")
    repo = names.repo_of(cwd)
    try:
        names.check_repo(repo)
    except ValueError:
        return skip(f"repo name {repo!r} is not a valid window-name part")
    work = work_from_title(agent.get("title"), repo)
    if not work:
        return skip("no agent title yet to take the work text from", retry=True)
    kind = kind_for(agent)
    try:
        name = names.build(kind, repo, work)
    except ValueError as e:
        return skip(str(e))
    return {"action": "rename", "name": name, "kind": kind, "repo": repo, "work": work}


def main() -> int:
    try:
        info = json.load(sys.stdin)
    except (OSError, ValueError) as e:
        print(f"ade_ws_autoname: unreadable input: {e}", file=sys.stderr)
        return 2
    json.dump(decide(info), sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
