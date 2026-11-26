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
  WORKER   the agent has a parent (`parentAgentId`) or an `ade.lead` label, or `ade.placement=worker` (`workers`)
  OTHER    only by an explicit `ade.placement=other` (`user`) label: OTHER is what a lead puts probes, side tasks and the
           operator's connected agents into; a first agent the operator started is LEAD
  LEAD     everything else (an operator-started first agent, a lead's own window); `ade.placement=lead` (`main`) says so explicitly
(The 2026-11-13 kinds MAIN, WORKERS and USER became LEAD, WORKER and OTHER on 2026-11-14; the old label values still work.)

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
# Display-text tidying ONLY (never authoritative metadata, 2026-11-25 ruling): strip redundant tab prefixes when
# falling back to an agent's title because structured `labels.slice` is absent.
_LEGACY_WORKER_TAB_RE = re.compile(rf"^(?:worker|other)\s+(.+?)\s+{_UUID}(?:\s+\[wt: [^\]]*\])?$")
_CONCISE_WORKER_TAB_RE = re.compile(r"^(?:worker|other)\s+([A-Za-z0-9][A-Za-z0-9._-]*)(?:\s+\[wt: [^\]]*\])?$")
_LEAD_TAB_RE = re.compile(r"^(?:LEAD|MAIN)\s+(.+)$")  # the tab names `LEAD <repo> <work>`; an ordinary "Lead the migration" stays
PLACEMENT_KINDS = {"lead": "LEAD", "main": "LEAD", "worker": "WORKER", "workers": "WORKER", "other": "OTHER", "user": "OTHER"}


def skip(reason: str, retry: bool = False) -> dict:
    """`retry` true = a later event may succeed (the agent has no title yet); false = this window will never be named from here."""
    return {"action": "skip", "reason": reason, "retry": retry}


def kind_for(agent: dict) -> str:
    """Decide LEAD/WORKER/OTHER strictly from structured agent metadata (never from display titles).

    Priority: `ade.box` label -> `ade.placement` label -> `parentAgentId` or `ade.lead` label -> LEAD.
    """
    labels = agent.get("labels") if isinstance(agent.get("labels"), dict) else {}
    raw_box = str(labels.get("ade.box") or "").strip().upper()
    if raw_box in names.BOX_OF:
        return names.BOX_OF[raw_box]
    placement = PLACEMENT_KINDS.get(str(labels.get("ade.placement") or "").strip().lower())
    if placement:
        return placement
    if agent.get("parentAgentId") or str(labels.get("ade.lead") or "").strip():
        return "WORKER"
    return "LEAD"


def _clean_work_text(raw: str, repo: str) -> str | None:
    text = " ".join(raw.split())  # one line, single spaces, no control characters
    text = "".join(ch for ch in text if ch.isprintable())
    if text.startswith(repo + " "):
        text = text[len(repo) + 1:]
    text = text.replace("(", "[").replace(")", "]").strip(" -:")  # a work text is formatted inside `(...)`
    if len(text) > WORK_LIMIT:
        cut = text[:WORK_LIMIT].rsplit(" ", 1)[0] or text[:WORK_LIMIT]
        text = cut.rstrip(" -:,;")
    return text if text and text != repo else None


def work_from_title(title: object, repo: str) -> str | None:
    """A short single-line work text from an agent display title, or None when nothing usable is left."""
    if not isinstance(title, str):
        return None
    text = " ".join(title.split())
    text = "".join(ch for ch in text if ch.isprintable())
    m = _LEGACY_WORKER_TAB_RE.match(text) or _CONCISE_WORKER_TAB_RE.match(text)
    if m:
        text = m.group(1)
    else:
        m = _LEAD_TAB_RE.match(text)
        if m:
            text = m.group(1)
    return _clean_work_text(text, repo)


def work_for_agent(agent: dict, repo: str) -> str | None:
    """Derive `<work>` from structured labels first (`slice`), falling back to display title text."""
    labels = agent.get("labels") if isinstance(agent.get("labels"), dict) else {}
    raw_slice = labels.get("slice")
    if isinstance(raw_slice, str) and raw_slice.strip():
        cleaned = _clean_work_text(raw_slice, repo)
        if cleaned:
            return cleaned
    return work_from_title(agent.get("title"), repo)


def repo_for_agent(agent: dict, cwd: str) -> str:
    """Prefer structured `ade.repo` label when valid, else inspect git/cwd via `ade_ws_names.repo_of`."""
    labels = agent.get("labels") if isinstance(agent.get("labels"), dict) else {}
    raw_repo = labels.get("ade.repo")
    if isinstance(raw_repo, str) and names.REPO_RE.fullmatch(raw_repo.strip()):
        return raw_repo.strip()
    return names.repo_of(cwd)


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
    repo = repo_for_agent(agent, cwd)
    try:
        names.check_repo(repo)
    except ValueError:
        return skip(f"repo name {repo!r} is not a valid window-name part")
    work = work_for_agent(agent, repo)
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
