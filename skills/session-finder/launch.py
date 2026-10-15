#!/usr/bin/env python3
"""launch — start an agent session over ACP, hosted where the operator can see it. No model.

    launch.py --agent A --cwd DIR (-p TEXT | -f FILE) [--model M] [--name NAME] [--baton [--chain ID|PATH]]
              [--pane PANE] [--host auto|herdr|orca|none] [--timeout S] [--perm P] [--set K=V]... [--mark LABEL]
              [--dry-run] [--json]
    launch.py reply <id> "<text>"     next prompt: into the live session's inbox when it is interactive (acp-run
                                      --interactive keeps the ACP session open), else a new acp-run turn with the
                                      brief and the last reply as context. Refused when <id> was already continued
                                      (superseded) or another live launch holds its ACP session. The new turn keeps
                                      the original host (--host none stays detached), mode and mark.
    launch.py wait <id> [--timeout S] [--json]
                                      block until THAT launch's current or queued turn ends (follows superseded_by
                                      to the newest turn); exit 0 ended, 3 timed out, 1 no such launch
    launch.py audit <id> [--force]    send /loose (or the loose-skill text) as the session's next turn; a --mark'ed
                                      launch is refused (its owner audits it; `helm.py wait --auto-audit` skips it)
    launch.py list [--json]           every launch and its state
    launch.py close <id> [--keep-pane] /exit a live session, mark it closed, close its herdr tab or pane, or its Orca terminal

--mark LABEL (or SESSION_FINDER_MARK=LABEL): a test/trial launch its starter drives itself. Recorded on the launch and
  every later turn; `launch.py audit` refuses it, and fleet.sessions(include_marked=False) leaves it out.
--dry-run prints the record, the acp-run command and the runner script; it writes nothing and touches no pane.
Headless Claude launches get a seeded session id (acp-run --session-id, recorded as session_seed): the id the
  claude CLI runs as if acp-run falls back to it. Over ACP claude-agent-acp picks the id, logs it (new_session),
  and passes it to Claude as its own --session-id, so the logged id already is the exact conversation.

Route (djbclark 2026-10-08: "use ACP if possible … other methods have proven to be fragile"):
  1. The agent is driven over ACP by acp-run (typed permissions, exit codes, JSONL log). The call runs
     inside a visible terminal so it is a session the operator can look at: an Orca terminal when this
     runs from Orca, else a herdr tab in the workspace that already holds that repo (a new workspace
     when none fits), else detached with no terminal. The pane is reported to herdr as an agent
     (`pane report-agent`, source session-finder) so helm and fleet list it like any other.
  2. Agents with no ACP route (zcode, muse) get `herdr agent start --kind` + `agent prompt`.
  --pane: host in that herdr pane. If a finished Claude session still sits there idle, it is sent /exit
  first (what herdr-sleeper does); a pane with a draft in its input box is refused.
  --baton: the brief tells the session to follow the baton skill from the named Tier 1 chain
  (resolved from --chain, else the chain whose workspace is DIR), then do the instruction.
State: ~/.local/state/session-finder/launches.jsonl and launch-<id>/ (brief, log, out, runner).
Exit: 0 started, 1 refused or failed, 2 usage, 3 `wait` timed out.
"""
import argparse
import contextlib
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fleet  # noqa: E402

ACP_RUN = os.environ.get("ACP_RUN") or shutil.which("acp-run") or str(Path.home() / "ops/site-private/bin/acp-run")
# The headless (one turn and exit) path goes through acp-dispatch (bin/acp-dispatch, 2026-10-08): the
# shared delivery footer, <id>-report.md + .done + jobs record, and exit 3 "no report" / 4 "BLOCKED:".
ACP_DISPATCH = os.environ.get("ACP_DISPATCH") or shutil.which("acp-dispatch") or str(HERE.parent.parent / "bin" / "acp-dispatch")
ACP_AGENTS = {"claude", "codex", "copilot", "opencode", "cursor", "qwen", "cline", "hermes", "agy", "devin"}
HERDR_KINDS = {"claude", "codex", "cursor", "opencode", "copilot", "qwen", "cline", "hermes", "agy", "muse", "grok", "devin"}
EXCLUDED = {"grok"}   # operator exclusion 2026-10-06 (bigteam: Current exclusions)
SKILLS = Path.home() / "src/djbclark-ade/skills"
STATE = fleet.STATE_DIR
HERDR = fleet.HERDR


def die(msg, rc=1):
    print(f"launch: {msg}", file=sys.stderr)
    sys.exit(rc)


_ACP_I = {}


def acp_interactive():
    """Does the installed acp-run have --interactive (added 2026-10-08)?"""
    if "v" not in _ACP_I:
        try:
            _ACP_I["v"] = "--interactive" in Path(ACP_RUN).read_text(errors="replace")[:6000]
        except OSError:
            _ACP_I["v"] = False
    return _ACP_I["v"]


def acp_session_id_flag():
    """Does the installed acp-run take --session-id (claude CLI fallback seed, added 2026-10-11)?"""
    if "s" not in _ACP_I:
        try:
            _ACP_I["s"] = "--session-id" in Path(ACP_RUN).read_text(errors="replace")[:8000]
        except OSError:
            _ACP_I["s"] = False
    return _ACP_I["s"]


def inbox_send(d, text):
    """Hand TEXT to a live interactive session as its next prompt (no keys, no new process)."""
    inbox = Path(d.get("inbox") or "")
    if not inbox.is_dir():
        return False
    tmp = inbox / f".{int(time.time() * 1000)}.tmp"
    tmp.write_text(text if text.endswith("\n") else text + "\n")
    tmp.rename(inbox / f"{int(time.time() * 1000)}.txt")
    return True


AUDIT = {"claude": "/loose", "hermes": "/loose"}
AUDIT_OTHER = "Use the loose skill: audit this session for loose ends, then step me through them."


def new_id(agent):
    return time.strftime("%Y%m%d-%H%M%S") + f"-{agent}-{os.getpid() % 10000:04d}"


def record(d):
    STATE.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE, 0o700)
    with fleet.LAUNCHES.open("a") as fh:
        fh.write(json.dumps(d, ensure_ascii=False) + "\n")


@contextlib.contextmanager
def turn_lock(timeout=120):
    """Serialise the check-then-start of a next turn (reply, audit) across processes, so two callers
    (helm's auto-audit and an agent's reply, 2026-10-11 hcom trial) cannot both continue one launch."""
    STATE.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE, 0o700)
    with (STATE / ".turn.lock").open("a") as fh:
        deadline = time.time() + timeout
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() > deadline:
                    die("another reply/audit holds the launch turn lock; try again")
                time.sleep(0.5)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def newest(lid, by_id):
    """Follow superseded_by from LID to the newest turn: (that launch, [ids walked])."""
    walked, d = [lid], by_id.get(lid)
    while d and d.get("superseded_by") and d["superseded_by"] in by_id and d["superseded_by"] not in walked:
        walked.append(d["superseded_by"])
        d = by_id[d["superseded_by"]]
    return d, walked


def session_holders(old, all_launches):
    """Other launches that are not closed and still hold OLD's ACP session (loaded it, or were loaded
    into it): starting another session/load of it would put two instances on one transcript."""
    sess = old.get("acp_session") or old.get("resumed")
    if not sess:
        return []
    out = []
    for d in all_launches:
        if d["id"] == old["id"] or d.get("closed"):
            continue
        status, _final, result = fleet.launch_state(d)
        if d.get("pid") and not fleet.alive(d["pid"]):
            continue    # a detached runner that is gone without writing its exit line
        if sess in (d.get("acp_session"), d.get("resumed")) and (result is None and d.get("exit") is None):
            out.append((d["id"], status))
    return out


def inbox_pending(d):
    """Prompts queued in an interactive launch's inbox that acp-run has not taken yet."""
    inbox = Path(d.get("inbox") or "")
    if not d.get("inbox") or not inbox.is_dir():
        return 0
    return sum(1 for f in inbox.iterdir() if f.suffix in (".txt", ".md") and not f.name.startswith("."))


def default_mark():
    return os.environ.get("SESSION_FINDER_MARK") or None


# ---- chains (for --baton) -------------------------------------------------------------------

def find_chain(cwd, want=None):
    top = fleet.toplevel(cwd)
    if want:
        p = Path(want)
        if p.is_file():
            return p
        p = fleet.HANDOFFS / "chains" / want / "SESSION_LOG.md"
        if p.is_file():
            return p
        die(f"no chain {want!r} under {fleet.HANDOFFS / 'chains'}")
    hits = [c for c in fleet._chain_logs(days=120) if top in {fleet.toplevel(d) for d in c["dirs"]}]
    if not hits:
        hits = [c for c in fleet._chain_logs(days=120) if any(d.startswith(top + "/") or top.startswith(d.rstrip("/") + "/")
                                                                for d in c["dirs"])]
    if not hits:
        die(f"no handoff chain lists {top}; pass --chain <id|path> (fleet.py ended lists candidates)")
    hits.sort(key=lambda c: -c["updated"])
    if len(hits) > 1 and hits[0]["updated"] - hits[1]["updated"] < 3600:
        print("launch: several chains for this directory, taking the newest: " +
              ", ".join(f"{c['chain']} ({fleet.ago(c['updated'])} ago)" for c in hits[:4]), file=sys.stderr)
    return Path(hits[0]["path"])


def baton_brief(cwd, chain_path, instruction, model=None):
    chain = chain_path.parent.name
    return f"""You are a fresh session that session-finder's launcher started in {cwd}, to continue work a previous session handed off. Work unattended: do not wait for confirmation on anything you can decide yourself.

1. Follow the `baton` skill ({SKILLS}/baton/SKILL.md -> the `session-handoff` skill's Reader protocol). If the Skill tool is not available to you, read those two SKILL.md files directly. Your Tier 1 canonical log is {chain_path} (chain {chain}): read it first, then the Tier 2 handoff it names in `latest_handoff` (under ~/ops/site-private/memory/handoffs/), then run the staleness check against the real HEAD of each workspace it lists. State the resume plan in one short paragraph and continue; do not ask the operator for anything the log already answers.
2. Then do this: {instruction}
3. Rules: read the repo's AGENTS.md first and follow it. This is a shared checkout: stage by path, never `git add -A`; commit small and push when the repo's rules say so. Do not start other agents or sessions. Work through blockers yourself (search the web before trial and error); only stop for a decision that is genuinely the operator's.
4. End your reply with one of `DONE: <what changed, commit shas>` or `BLOCKED: <what you need>`, and update the Tier 1 log through the session-handoff Writer protocol before you finish.
"""


# ---- hosts ----------------------------------------------------------------------------------

def herdr_up():
    return bool(fleet.herdr_json("workspace", "list"))


def pane_shell_ready(pane, tries=12):
    """True once the pane shows a shell prompt on its last line."""
    for _ in range(tries):
        out = fleet.run(HERDR, "pane", "read", pane, "--source", "visible", "--lines", "6")[1]
        last = next((ln.rstrip() for ln in reversed(out.splitlines()) if ln.strip()), "")
        if re.search(r"(\$|%|❯|>)\s*$", last) and "Resume this session" not in last:
            return True
        time.sleep(1)
    return False


def pane_draft(pane):
    out = fleet.run(HERDR, "pane", "read", pane, "--source", "visible", "--lines", "14")[1]
    for ln in reversed(out.splitlines()):
        if ln.startswith("❯"):
            return ln[1:].strip()
    return ""


def pane_exists(pane):
    return bool(fleet.herdr_json("pane", "get", pane).get("pane"))


def free_pane(pane):
    """Make sure PANE is at a shell prompt: a finished agent there is asked to /exit first."""
    a = fleet.herdr_json("agent", "get", pane).get("agent") or {}
    if a.get("agent"):
        if a.get("agent_status") not in ("idle", "done", None):
            die(f"pane {pane} runs a {a['agent']} agent that is {a.get('agent_status')}; not touching it")
        if pane_draft(pane):
            die(f"pane {pane} has an unsent draft in its input box; not touching it")
        if fleet.run(HERDR, "agent", "prompt", pane, "/exit", timeout=20)[0] != 0:
            die(f"could not send /exit to the agent in {pane}")
        time.sleep(2)
    if not pane_shell_ready(pane):
        die(f"pane {pane} did not reach a shell prompt")


def pick_workspace(cwd):
    top = fleet.toplevel(cwd)
    panes = fleet.herdr_json("pane", "list").get("panes") or []
    score = {}
    for p in panes:
        if p.get("cwd") and fleet.toplevel(p["cwd"]) == top:
            score[p["workspace_id"]] = score.get(p["workspace_id"], 0) + 1
    if score:
        return max(score, key=score.get), False
    for w in fleet.herdr_json("workspace", "list").get("workspaces") or []:
        if (w.get("label") or "").lower() == os.path.basename(top).lower() and w.get("workspace_id"):
            return w["workspace_id"], False
    if os.environ.get("HERDR_WORKSPACE_ID"):
        return os.environ["HERDR_WORKSPACE_ID"], False
    r = fleet.herdr_json("workspace", "create", "--cwd", cwd, "--label", os.path.basename(top), "--no-focus")
    wid = (r.get("workspace") or {}).get("workspace_id") or r.get("workspace_id")
    if not wid:
        die("could not create a herdr workspace")
    return wid, True


def first_pane(wid, name):
    """A workspace `workspace create` just opened already has one tab with a shell in the right
    cwd: use it (labelled), rather than adding a second tab and leaving the first one empty."""
    for _ in range(10):
        panes = fleet.herdr_json("pane", "list", "--workspace", wid).get("panes") or []
        if panes:
            break
        time.sleep(0.5)
    if len(panes) != 1:
        return None
    pane, tab = panes[0]["pane_id"], panes[0]["tab_id"]
    if not pane_shell_ready(pane):
        return None
    fleet.run(HERDR, "tab", "rename", tab, name[:24])
    return pane, tab


def new_herdr_pane(cwd, name, wid):
    r = fleet.herdr_json("tab", "create", "--workspace", wid, "--cwd", cwd, "--label", name[:24], "--no-focus")
    tab = (r.get("tab") or {}).get("tab_id") or r.get("tab_id")
    pane = (r.get("pane") or {}).get("pane_id") or r.get("pane_id")
    if tab and not pane:
        for _ in range(10):
            for p in fleet.herdr_json("pane", "list", "--workspace", wid).get("panes") or []:
                if p.get("tab_id") == tab:
                    pane = p["pane_id"]
            if pane:
                break
            time.sleep(0.5)
    if not pane:
        die(f"herdr tab create returned no pane: {json.dumps(r)[:300]}")
    if not pane_shell_ready(pane):
        die(f"new pane {pane} never showed a shell prompt")
    return pane, tab


def pane_tab(pane):
    p = fleet.herdr_json("pane", "get", pane).get("pane") or {}
    return p.get("tab_id", ""), p.get("workspace_id", "")


def report(pane, agent, state, lid, name="", message=""):
    args = [HERDR, "pane", "report-agent", pane, "--source", "session-finder", "--agent", agent, "--state", state,
            "--agent-session-id", lid]
    if message:
        args += ["--message", message]
    fleet.run(*args)
    if name:
        fleet.run(HERDR, "pane", "report-metadata", pane, "--source", "session-finder", "--title", name[:60],
                  "--display-agent", f"{agent} (acp)")


# ---- the run ---------------------------------------------------------------------------------

def runner_script(d, acp_cmd, pane=None):
    """A bash script the host runs: acp-run in the foreground, exit status kept, state reported.

    A detached interactive launch (--host none) has no terminal: its stdin would be /dev/null, and
    acp-run --interactive ends the session at stdin EOF, so it got exactly one turn (hcom trial 6c,
    2026-10-11). It reads a FIFO opened read-write instead: no EOF ever arrives, the inbox feeds the
    prompts, and /exit (launch.py close) ends it."""
    q = lambda s: "'" + str(s).replace("'", "'\\''") + "'"  # noqa: E731
    lines = ["#!/usr/bin/env bash", 'export PATH="/opt/homebrew/bin:$PATH"', "set -o pipefail", f"echo 'launch {d['id']}: {d['agent']} in {d['cwd']} (acp)'"]
    if pane:
        lines.append(f"{q(HERDR)} pane report-agent {q(pane)} --source session-finder --agent {q(d['agent'])} "
                     f"--state working --agent-session-id {q(d['id'])} >/dev/null 2>&1")
    stdin = f" 0<> {q(d['stdin'])}" if d.get("stdin") else ""
    # PYTHONUNBUFFERED: stdout is a pipe (tee), and the pane must show the agent as it streams
    lines.append("PYTHONUNBUFFERED=1 " + " ".join(q(c) for c in acp_cmd) + stdin +
                 f" 2> >(gtee {q(d['err'])} >&2) | gtee {q(d['out'])}")
    lines.append("rc=${PIPESTATUS[0]}")
    if d.get("stdin"):
        lines.append(f"rm -f {q(d['stdin'])}")
    lines.append(f"printf '%s\\n' \"{{\\\"id\\\": \\\"{d['id']}\\\", \\\"exit\\\": $rc, \\\"ended\\\": $(gdate +%s)}}\" >> {q(fleet.LAUNCHES)}")
    if d.get("claim"):
        lines.append(f"printf 'DONE %s\\n' \"$(gdate +%Y-%m-%dT%H:%M:%S)\" >> {q(d['claim'])}")
    if pane:
        lines.append(f"{q(HERDR)} pane report-agent {q(pane)} --source session-finder --agent {q(d['agent'])} "
                     f"--state idle --agent-session-id {q(d['id'])} --message \"exit $rc\" >/dev/null 2>&1")
    lines.append(f"echo \"launch {d['id']} exit=$rc  log: {d['log']}\"")
    return "\n".join(lines) + "\n"


def release_launch_claim(d):
    """Append DONE to a launch's bigteam claim unless the runner already did, so it stops blocking the repo."""
    c = Path(d.get("claim") or "")
    if d.get("claim") and c.is_file() and "\nDONE " not in "\n" + c.read_text():
        with c.open("a") as fh:
            fh.write(f"DONE {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n")


def abort_start(d, msg):
    """A start that failed after its record and claim were written: close both, then exit."""
    record({"id": d["id"], "closed": True, "closed_at": time.time(), "error": msg[:300]})
    release_launch_claim(d)
    die(msg)


def orca_created_handle(out):
    """The new terminal's handle from `orca terminal create --json`, or None.

    The live CLI nests it as result.terminal.handle (verified 2026-10-10); the bare shapes are kept as fallbacks."""
    try:
        j = json.loads(out)
    except ValueError:
        return None
    if not isinstance(j, dict):
        return None
    for t in ((j.get("result") or {}).get("terminal"), j.get("terminal"), j):
        if isinstance(t, dict) and t.get("handle"):
            return t["handle"]
    return None


def start(a, brief_text, parent=None):
    agent = a.agent
    if agent in EXCLUDED:
        die(f"{agent} is excluded by operator rule (bigteam: Current exclusions)")
    cwd = str(Path(a.cwd).expanduser().resolve())
    if not Path(cwd).is_dir():
        die(f"no such directory {cwd}")
    lid = new_id(agent)
    # conflicts (operator 2026-10-08: never collide with another session's work)
    c = fleet.conflicts(cwd)
    if c["blocking"] and not a.force:
        die("another session is working in this repo; message it instead (session-finder) or pass --force:\n"
            + fleet.render_conflicts(c))
    own = []
    if parent:
        # a reply turn: files the parent launch (this chain) modified since it started are its own work
        pd = next((x for x in fleet.launches() if x["id"] == parent), None)
        if pd:
            root = c["repo"]
            for f in list(c["dirty"]):
                try:
                    if os.path.getmtime(os.path.join(root, f)) >= pd.get("ts", 0):
                        own.append(f)
                        c["dirty"].remove(f)
                except OSError:
                    pass
    guard = ""
    if own:
        guard += f"\n\nFiles your previous turn(s) left modified or staged — yours to finish: {', '.join(own)}."
    if c["dirty"] or c["claims"] or c["idle"]:
        guard += "\n\nOther sessions share this checkout. " + (
            f"Files already modified in the worktree belong to someone else — read them, never edit, stage or revert them: "
            f"{', '.join(c['dirty'])}. " if c["dirty"] else "") + (
            "Files owned by live bigteam claims are off limits: " + "; ".join(
                f"{cl['task']}: {', '.join(cl['files']) or 'unspecified'}" for cl in c["claims"]) + ". " if c["claims"] else "") + (
            "Idle sessions here: " + ", ".join(f"{s['agent']} {s.get('name') or s['id']}" for s in c["idle"]) +
            " — if your task overlaps theirs, stop and say so rather than duplicating it. " if c["idle"] else "") + \
            "Stage by path and commit only what you changed."
        brief_text += guard
    d = {"id": lid, "ts": time.time(), "agent": agent, "cwd": cwd, "name": a.name or os.path.basename(cwd),
         "model": a.model, "parent": parent, "chain": getattr(a, "_chain", None),
         "claim": None if a.dry_run else fleet.write_claim(f"sf-{lid}", f"launch {lid}", c["repo"], a.files or [],
                                                           f"brief: {a.name or ''}")}
    mark = getattr(a, "mark", None)
    if mark:
        d["mark"] = mark
    ldir = STATE / f"launch-{lid}"
    if not a.dry_run:          # a dry run writes nothing (hcom trial 6d: it left brief.md/run.sh/inbox behind)
        ldir.mkdir(parents=True, exist_ok=True)
    d.update(brief=str(ldir / "brief.md"), log=str(ldir / "acp.jsonl"), out=str(ldir / "out.txt"),
             err=str(ldir / "err.txt"), runner=str(ldir / "run.sh"), prompt_head=" ".join(brief_text.split())[:200])
    if not a.dry_run:
        Path(d["brief"]).write_text(brief_text)

    host = a.host or "auto"
    if host == "auto":
        host = "orca" if os.environ.get("ORCA_TERMINAL_HANDLE") or os.environ.get("TERM_PROGRAM") == "Orca" else (
            "herdr" if herdr_up() else "none")
    if agent not in ACP_AGENTS:
        return start_tui(a, d, brief_text, host)

    interactive = bool(getattr(a, "interactive", True) and acp_interactive())
    if interactive:
        # A live session the operator talks to: acp-run directly. The pane shows the agent and takes
        # the next prompt from the keyboard or the inbox. It is not a report-producing sub-agent, so
        # the delivery footer and report machinery do not apply.
        acp_cmd = [ACP_RUN, agent, "-C", cwd, "-f", d["brief"], "--timeout", str(a.timeout), "--log", d["log"]]
        if getattr(a, "resume", None):
            acp_cmd += ["--resume", a.resume]   # session/load: the agent replays its own history
            d["resumed"] = a.resume
        d["interactive"], d["inbox"] = True, str(ldir / "inbox")
        if host == "none":
            d["stdin"] = str(ldir / "stdin.fifo")    # see runner_script: no terminal, so no stdin EOF either
        if not a.dry_run:
            Path(d["inbox"]).mkdir(exist_ok=True)
            if d.get("stdin"):
                os.mkfifo(d["stdin"], 0o600)
        acp_cmd += ["--interactive", "--inbox", d["inbox"]]
        if a.model:
            acp_cmd += ["--model", a.model]
        if a.perm:
            acp_cmd += ["--perm", a.perm]
        for kv in a.set or []:
            acp_cmd += ["--set", kv]
        if not a.model:
            print("launch: no --model; acp-run will use the agent's default (for claude that is the expensive settings model)",
                  file=sys.stderr)
    else:
        # One turn and exit: a headless slice, so it is dispatched like any other. acp-dispatch appends
        # docs/dispatch-footer.md to its own copy of the brief, writes <id>-report.md, its .done marker and
        # jobs/<id>.json under this launch's dir, and exits 3 when the turn ended with no report, 4 when
        # the report starts "BLOCKED:" (launches.jsonl records that exit). --tee keeps the pane live.
        if not a.model:
            die("--model is required for a headless launch (acp-dispatch refuses to run without it)")
        acp_cmd = [ACP_DISPATCH, agent, "--model", a.model, "--name", lid, "--out", str(ldir), "-C", cwd,
                   "-f", d["brief"], "--timeout", str(a.timeout), "--tee", "--acp-run", ACP_RUN, "--force"]
        if a.perm:
            acp_cmd += ["--perm", a.perm]
        if getattr(a, "resume", None):
            acp_cmd += ["--acp-arg=--resume", f"--acp-arg={a.resume}"]
            d["resumed"] = a.resume
        elif agent == "claude" and acp_session_id_flag():
            # Seed the conversation id (uam's idea, hcom trial 2026-10-11): a headless turn whose ACP
            # handshake hangs falls back to `claude -p`, which then runs as exactly this id, and acp-run logs
            # it as new_session, so reply/resume land in that conversation. Over ACP claude-agent-acp picks
            # the id itself (and gives it to Claude as --session-id); its new_session record wins.
            d["session_seed"] = str(uuid.uuid4())
            acp_cmd += ["--acp-arg=--session-id", f"--acp-arg={d['session_seed']}"]
        for kv in a.set or []:
            acp_cmd += ["--acp-arg=--set", f"--acp-arg={kv}"]
        d.update(dispatch=True, report=str(ldir / f"{lid}-report.md"), done=str(ldir / f"{lid}-report.md.done"),
                 job=str(ldir / "jobs" / f"{lid}.json"), log=str(ldir / f"{lid}.jsonl"))

    pane = tab = None
    if host == "herdr":
        if a.pane and not pane_exists(a.pane):
            print(f"launch: pane {a.pane} is gone; opening a new tab instead", file=sys.stderr)
            a.pane = None
        if a.pane:
            if not a.dry_run:
                free_pane(a.pane)      # sends /exit to a finished agent there: never on a dry run
            pane = a.pane
            tab, wid = pane_tab(pane)
        elif a.dry_run:
            wid, pane, tab = os.environ.get("HERDR_WORKSPACE_ID", "?"), "(new pane)", "(new tab)"
        else:
            wid, created = pick_workspace(cwd)
            pane, tab = (first_pane(wid, d["name"]) if created else None) or new_herdr_pane(cwd, d["name"], wid)
        d["host"] = {"kind": "herdr", "pane": pane, "tab": tab, "workspace": wid}
    elif host == "orca":
        d["host"] = {"kind": "orca"}
    else:
        d["host"] = {"kind": "none"}
    script = runner_script(d, acp_cmd, None if a.dry_run else pane)
    if a.dry_run:
        print(json.dumps({**d, "acp_cmd": acp_cmd, "runner_script": script,
                          "dry_run": "nothing was written: no launch dir, tab, claim or record"}, indent=1))
        return d
    Path(d["runner"]).write_text(script)
    os.chmod(d["runner"], 0o700)
    record(d)

    if host == "herdr":
        report(pane, agent, "working", lid, d["name"])
        rc, out = fleet.run(HERDR, "pane", "run", pane, "bash", d["runner"], timeout=20)
        if rc != 0 or '"error"' in out:
            abort_start(d, f"herdr pane run failed: {out[:300]}")
    elif host == "orca":
        rc, out = fleet.run("orca", "terminal", "create", "--worktree", f"path:{cwd}", "--title", d["name"][:40],
                            "--command", f"bash {d['runner']}", "--json", timeout=30)
        handle = orca_created_handle(out)
        if rc != 0 or not handle:
            abort_start(d, f"orca terminal create failed: {out[:300]}")
        d["host"]["terminal"] = handle
        record({"id": lid, "host": d["host"]})
    else:
        p = subprocess.Popen(["bash", d["runner"]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        record({"id": lid, "pid": p.pid})
    return d


def start_tui(a, d, brief_text, host):
    """No ACP route: an interactive TUI in a herdr pane, prompted by key presses (the fragile way)."""
    if host != "herdr" or a.agent not in HERDR_KINDS:
        die(f"{a.agent} has no ACP route and no herdr kind; run it by hand: see model-routing's headless table")
    if a.dry_run:     # before any pane is freed or created
        pane, tab, wid = a.pane or "(new pane)", "(new tab)", os.environ.get("HERDR_WORKSPACE_ID", "?")
        d["host"] = {"kind": "herdr-tui", "pane": pane, "tab": tab, "workspace": wid}
        print(json.dumps({**d, "dry_run": "nothing was written: no launch dir, tab, claim or record"}, indent=1))
        return d
    if a.pane:
        free_pane(a.pane)
        pane, (tab, wid) = a.pane, pane_tab(a.pane)
    else:
        wid, _ = pick_workspace(d["cwd"])
        pane, tab = new_herdr_pane(d["cwd"], d["name"], wid)
    d["host"] = {"kind": "herdr-tui", "pane": pane, "tab": tab, "workspace": wid}
    record(d)
    args = [HERDR, "agent", "start", f"sf-{d['id'][-8:]}", "--kind", a.agent, "--pane", pane, "--timeout", "60000"]
    rc, out = fleet.run(*args, timeout=70)
    if rc != 0 or '"error"' in out:
        die(f"herdr agent start failed: {out[:300]}")
    rc, out = fleet.run(HERDR, "agent", "prompt", pane, brief_text, timeout=30)
    if rc != 0 or '"error"' in out:
        die(f"herdr agent prompt failed: {out[:300]}")
    print(f"started {a.agent} TUI in {pane} (herdr tab focus {tab}); prompt submitted by keys, verify in the pane")
    return d


# ---- commands --------------------------------------------------------------------------------

def cmd_start(a):
    if a.prompt is None and a.prompt_file is None:
        die("give -p TEXT or -f FILE", 2)
    text = a.prompt if a.prompt is not None else Path(a.prompt_file).read_text()
    if a.baton:
        chain = find_chain(a.cwd, a.chain)
        a._chain = str(chain)
        text = baton_brief(str(Path(a.cwd).expanduser().resolve()), chain, text.strip(), a.model)
    d = start(a, text)
    if a.dry_run:
        return 0
    h = d["host"]
    where = {"herdr": f"herdr tab focus {h.get('tab')}", "herdr-tui": f"herdr tab focus {h.get('tab')}",
             "orca": f"orca terminal switch --terminal {h.get('terminal')}", "none": "no terminal"}[h["kind"]]
    msg = {"id": d["id"], "agent": d["agent"], "cwd": d["cwd"], "name": d["name"], "model": d["model"], "host": h,
           "focus": where, "log": d["log"], "brief": d["brief"], "chain": d.get("chain")}
    print(json.dumps(msg) if a.json else
          f"started {d['id']}: {d['agent']} in {fleet.short(d['cwd'])} as \"{d['name']}\"\n  focus: {where}\n  log: {d['log']}\n"
          f"  watch: fleet.py show {d['id']}   (helm lists it when it stops or asks)")
    return 0


HOST_OF = {"herdr": "herdr", "herdr-tui": "herdr", "orca": "orca", "none": "none"}


def cmd_reply(a):
    # The check (superseded? session held?) and the start are one step under a lock: helm's auto-audit and an
    # agent's reply both continued launch 7085 into two session/loads of one ACP session (hcom trial 6a).
    with turn_lock():
        return _reply(a)


def reply_refusal(lid):
    """Why a next turn of launch LID must not start, or None. Two refusals (hcom trial 6a, 2026-10-11):
    LID was already continued (superseded_by), or another launch that is still open holds its ACP session."""
    every = fleet.launches()
    by_id = {d["id"]: d for d in every}
    old = by_id.get(lid)
    if not old:
        return f"no launch {lid}"
    if old.get("superseded_by"):
        last, walked = newest(lid, by_id)
        st = "closed" if last.get("closed") else fleet.launch_state(last)[0]
        return (f"{lid} was already continued as {old['superseded_by']} (newest turn {walked[-1]}: {st}); a second "
                f"turn from {lid} would load its session twice. Reply to the newest turn: "
                f"launch.py reply {walked[-1]} \"<text>\"")
    _status, _final, result = fleet.launch_state(old)
    held = session_holders(old, every)
    if held and not (old.get("interactive") and result is None):
        return (f"launch {', '.join(f'{i} ({s})' for i, s in held)} already holds ACP session "
                f"{(old.get('acp_session') or old.get('resumed') or '')[:8]}; reply to it instead "
                "(or `launch.py close <id>` it first if it is dead)")
    return None


def _reply(a):
    refusal = reply_refusal(a.id)
    if refusal:
        die(refusal)
    old = next(d for d in fleet.launches() if d["id"] == a.id)
    status, final, result = fleet.launch_state(old)
    if old.get("interactive") and result is None:
        # the session is alive: queue the prompt in its inbox (acp-run picks it up when idle)
        if not inbox_send(old, a.text):
            die(f"{a.id} is interactive but its inbox {old.get('inbox')} is gone")
        print(f"queued for [{a.id}] ({'now' if status != 'working' else 'after its current turn'}): {fleet.clip(a.text, 80)}")
        return 0
    if status == "working":
        die(f"{a.id} is still working; wait for its result first")
    resume = old.get("acp_session") if old.get("load_session") and acp_interactive() else None
    if resume:
        text = a.text        # session/load brings the whole conversation back; just the new prompt
    else:
        brief = Path(old["brief"]).read_text() if Path(old.get("brief", "")).exists() else old.get("prompt_head", "")
        text = (f"This continues an earlier turn in {old['cwd']}. The brief for that turn was:\n\n{brief}\n\n"
                f"Your reply to it ended:\n\n{final[-3000:]}\n\nThe operator now says: {a.text}\n\n"
                "Continue from there; re-read the files you changed before editing them again.")
    # The next turn runs where the first one did (hcom trial 6b: a --host none launch's reply opened a herdr
    # tab), in the same mode (interactive or headless) and with the same mark, unless the caller overrides.
    old_host = (old.get("host") or {}).get("kind")
    host = a.host or HOST_OF.get(old_host, "auto")
    ns = argparse.Namespace(agent=old["agent"], cwd=old["cwd"], model=a.model or old.get("model"), name=old.get("name"),
                            resume=resume, interactive=not old.get("dispatch"),
                            host=host, pane=(old.get("host") or {}).get("pane") if host in ("herdr", "auto") else None,
                            timeout=a.timeout, perm=a.perm, set=a.set, dry_run=a.dry_run, json=a.json, prompt=None,
                            prompt_file=None, baton=False, chain=None, files=old.get("files") or [], force=True,
                            mark=getattr(a, "mark", None) or old.get("mark"))
    if ns.pane and not str(ns.pane).startswith("("):
        ag = fleet.herdr_json("agent", "get", ns.pane).get("agent") or {}
        if (ag.get("agent_status") or "idle") not in ("idle", "done"):
            ns.pane = None   # busy pane: open a new tab instead
    else:
        ns.pane = None
    d = start(ns, text, parent=a.id)
    if not a.dry_run:
        record({"id": a.id, "closed": True, "superseded_by": d["id"]})
        if resume:
            record({"id": d["id"], "audited_turn": old.get("audited_turn")} if old.get("audited_turn") is not None else {"id": d["id"]})
        h = d.get("host") or {}
        where = {"herdr": f"herdr tab focus {h.get('tab', '?')}", "orca": f"orca terminal {h.get('terminal', '?')}",
                 "none": "no terminal (detached)"}.get(h.get("kind"), h.get("kind") or "?")
        print(f"started {d['id']} as the next turn of {a.id} ({'session/load of ' + resume[:8] if resume else 'new ACP session'}; "
              f"focus: {where}; wait: launch.py wait {d['id']})")
    return 0


def cmd_list(a):
    rows = []
    for d in fleet.launches():
        status, final, result = fleet.launch_state(d)
        rows.append({"id": d["id"], "agent": d.get("agent"), "cwd": fleet.short(d.get("cwd", "")), "name": d.get("name"),
                     "status": "closed" if d.get("closed") else status, "exit": (result or {}).get("exit", d.get("exit")),
                     "host": d.get("host"), "last": fleet.clip(final, 160), "ts": d.get("ts"), "mark": d.get("mark"),
                     "superseded_by": d.get("superseded_by")})
    if a.json:
        print(json.dumps(rows, ensure_ascii=False))
    else:
        for r in rows:
            mark = f"  mark={r['mark']}" if r["mark"] else ""
            nxt = f"  -> {r['superseded_by']}" if r["superseded_by"] else ""
            print(f"[{r['id']}] {r['agent']} {r['status']}  {r['cwd']}  \"{r['name']}\"  exit={r['exit']}{mark}{nxt}")
            if r["last"]:
                print(f"    last: {r['last']}")
    return 0 if rows else 1


WAIT_POLL = 2


def cmd_wait(a):
    """Block until launch ID's turn ends: the one running now, or the one its inbox still holds. Per-id, unlike
    `helm.py wait`, which returns the first fresh item of any session (hcom trial 2.2e). Follows superseded_by,
    so `wait <id>` on a launch that `reply` continued waits for the newest turn."""
    deadline = time.time() + a.timeout if a.timeout else None
    need = None          # turn count that ends the wait when input was queued at the start
    first = True
    while True:
        by_id = {d["id"]: d for d in fleet.launches()}
        if a.id not in by_id:
            die(f"no launch {a.id}")
        d, walked = newest(a.id, by_id)
        status, final, result = fleet.launch_state(d)
        turns, pending = d.get("turns", 0), inbox_pending(d) if result is None else 0
        if first:
            # Input queued but not yet taken (acp-run polls the inbox each second) means the turn we want has not
            # started; the state is still the previous turn's, so wait for one more turn record.
            need = turns + 1 if pending else None
            first = False
        ended = result is not None or d.get("exit") is not None or bool(d.get("closed"))
        if ended or (status != "working" and not pending and (need is None or turns >= need)):
            out = {"id": d["id"], "asked": a.id, "followed": walked[1:], "status": "closed" if d.get("closed") else status,
                   "alive": not ended, "turns": turns, "exit": (result or {}).get("exit", d.get("exit")),
                   "final": final, "mark": d.get("mark"),
                   "next": f"launch.py reply {d['id']} \"<text>\"", "log": d.get("log")}
            if a.json:
                print(json.dumps(out, ensure_ascii=False))
            else:
                via = f" (via {' -> '.join(walked)})" if len(walked) > 1 else ""
                print(f"[{d['id']}]{via} {out['status']}{'' if out['alive'] else ' (exited, exit=' + str(out['exit']) + ')'}"
                      f" after turn {turns}\n{final.strip()}\n  next: {out['next']}")
            return 0
        if deadline and time.time() > deadline:
            if not a.json:
                print(f"launch: [{d['id']}] still {status} after {a.timeout}s", file=sys.stderr)
            return 3
        time.sleep(WAIT_POLL)


def cmd_audit(a):
    """Send the loose-ends audit as the session's next turn (operator 2026-10-08: /loose on the
    ACP window when done, then close it)."""
    with turn_lock():
        return _audit(a)


def _audit(a):
    d = next((x for x in fleet.launches() if x["id"] == a.id), None)
    if not d:
        die(f"no launch {a.id}")
    status, final, result = fleet.launch_state(d)
    if d.get("closed"):
        die(f"{a.id} is closed" + (f" (continued as {d['superseded_by']})" if d.get("superseded_by") else ""))
    if d.get("mark") and not getattr(a, "force", False):
        # hcom trial 6g: the operator's standing `helm.py wait --auto-audit` audited a trial launch and took it
        # over. A marked launch belongs to whoever started it: they audit and close it (--force to do it anyway).
        die(f"{a.id} is marked {d['mark']!r}: its starter drives it; not audited (launch.py audit {a.id} --force)")
    text = AUDIT.get(d.get("agent"), AUDIT_OTHER)
    if d.get("interactive") and result is None:
        if not inbox_send(d, text):
            die("inbox gone")
        record({"id": a.id, "audited_turn": d.get("turns", 0), "audit_sent": time.time()})
        print(f"audit queued for [{a.id}] as turn {d.get('turns', 0) + 1}")
        return 0
    if status == "working":
        die(f"{a.id} is still working")
    refusal = reply_refusal(a.id)
    if refusal:
        die(refusal)
    record({"id": a.id, "audited_turn": d.get("turns", 0), "audit_sent": time.time()})
    ns = argparse.Namespace(id=a.id, text=text, model=None, host=None, timeout=1800, perm=None, set=None,
                            dry_run=False, json=False)
    return _reply(ns)


def close_orca_terminal(handle):
    """Close an Orca terminal a launch was hosted in. Returns a message for the operator.

    Never closes the caller's own terminal (ORCA_TERMINAL_HANDLE, or the live handle its stable
    ORCA_PANE_KEY resolves to), and skips a handle Orca no longer lists (restarted runtime, closed by hand)."""
    _, live = fleet._orca_terminals()
    own = {os.environ.get("ORCA_TERMINAL_HANDLE")}
    chan = fleet._orca_chan(dict(os.environ))
    if chan:
        own.add(chan[1])
    if handle in own:
        return f"left Orca terminal {handle} open: it is this session's own terminal"
    if handle not in live:
        return f"Orca terminal {handle} is already gone"
    rc, out = fleet.run("orca", "terminal", "close", "--terminal", handle, "--json", timeout=20)
    if rc != 0:
        return f"orca terminal close {handle} failed: {out[:200]}"
    return f"closed its Orca terminal {handle}"


def cmd_close(a):
    """Mark closed and, by default, close the herdr tab or Orca terminal that hosted it so tabs do not pile up.
    A live interactive session is asked to /exit first; a working one is refused unless --force."""
    d = next((x for x in fleet.launches() if x["id"] == a.id), None)
    if not d:
        die(f"no launch {a.id}")
    status, final, result = fleet.launch_state(d)
    host = d.get("host") or {}
    if status == "working" and result is None and not a.force:
        die(f"{a.id} is still working; wait, or --force")
    if d.get("interactive") and result is None and d.get("exit") is None:
        inbox_send(d, "/exit")
        for _ in range(30):
            time.sleep(1)
            if any(x.get("exit") is not None for x in fleet.launches() if x["id"] == a.id):
                break
    record({"id": a.id, "closed": True, "closed_at": time.time()})
    release_launch_claim(d)
    if host.get("kind") in ("herdr", "herdr-tui") and host.get("pane") and not a.keep_pane:
        if pane_exists(host["pane"]):
            ag = fleet.herdr_json("agent", "get", host["pane"]).get("agent") or {}
            if ag.get("agent") and ag.get("agent_status") == "working" and not a.force:
                die(f"closed {a.id} but pane {host['pane']} still runs a working {ag['agent']}; not closing it")
            tab = host.get("tab")
            panes = [p for p in (fleet.herdr_json("pane", "list").get("panes") or []) if p.get("tab_id") == tab]
            if tab and len(panes) == 1:
                fleet.run(HERDR, "tab", "close", tab)
            else:
                fleet.run(HERDR, "pane", "close", host["pane"])
            print(f"closed {a.id} and its herdr {'tab ' + tab if tab and len(panes) == 1 else 'pane ' + host['pane']}")
            return 0
    if host.get("kind") == "orca" and host.get("terminal") and not a.keep_pane:
        print(f"closed {a.id}; {close_orca_terminal(host['terminal'])}")
        return 0
    print(f"closed {a.id}")
    return 0


def main():
    ap = argparse.ArgumentParser(prog="launch.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    def common(p, host_default="auto"):
        p.add_argument("--model")
        p.add_argument("--host", choices=["auto", "herdr", "orca", "none"], default=host_default,
                       help=None if host_default else "default: where the launch being continued ran")
        p.add_argument("--mark", default=default_mark(),
                       help="test/trial label (or SESSION_FINDER_MARK): audit refuses it, helm leaves it alone")
        p.add_argument("--timeout", type=int, default=14400,
                       help="seconds per turn (default 4 h: a 1 h limit cut a real deploy short on 2026-10-08)")
        p.add_argument("--perm")
        p.add_argument("--set", action="append")
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("start")
    p.add_argument("--agent", required=True)
    p.add_argument("--cwd", required=True)
    p.add_argument("-p", "--prompt")
    p.add_argument("-f", "--prompt-file")
    p.add_argument("--name")
    p.add_argument("--baton", action="store_true")
    p.add_argument("--chain")
    p.add_argument("--pane")
    p.add_argument("--files", nargs="*", help="paths this session will own (written to its bigteam claim)")
    p.add_argument("--force", action="store_true", help="start even though another session works in that repo")
    p.add_argument("--no-interactive", dest="interactive", action="store_false",
                   help="one turn and exit (default: keep the ACP session open; the pane shows it and takes input)")
    common(p)
    p.set_defaults(fn=cmd_start)
    p = sub.add_parser("reply")
    p.add_argument("id")
    p.add_argument("text")
    common(p, host_default=None)
    p.set_defaults(fn=cmd_reply)
    p = sub.add_parser("list")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("wait")
    p.add_argument("id")
    p.add_argument("--timeout", type=int, default=0, help="seconds (default 0: no limit); exit 3 on timeout")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_wait)
    p = sub.add_parser("audit")
    p.add_argument("id")
    p.add_argument("--force", action="store_true", help="audit a --mark'ed launch anyway")
    p.set_defaults(fn=cmd_audit)
    p = sub.add_parser("close")
    p.add_argument("id")
    p.add_argument("--keep-pane", action="store_true", help="mark closed but leave the herdr tab/pane or Orca terminal")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_close)
    argv = sys.argv[1:]
    if argv and argv[0].startswith("-"):
        argv = ["start"] + argv     # `launch.py --agent …` is the common form
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_usage(sys.stderr)
        return 2
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
