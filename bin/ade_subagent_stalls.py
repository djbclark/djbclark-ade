"""Detect Agent-tool sub-agents that died mid-run, and notify (never act). Module behind `bin/ade-subagent-stalls`.

Why (2026-11-22, docs/subagent-stalls.md): a background Claude Code sub-agent (the Agent tool) was killed mid-run while its parent
sat idle, and nothing noticed for about 14 hours; one SendMessage resumed it from its transcript and lost nothing. This module is the
detector the evidence file proposed ("fix 1"): a zero-token scan the machine's watcher (fleet-watch) calls.

A STUB is an agent-report file `<reports>/<session>/<name>-report.md` whose first line is `STATUS: working` and that has no
`<report>.done` (the delivery footer, docs/dispatch-footer.md, makes every sub-agent write one first). A stub is STALLED when the
transcript that writes it (`<projects>/<proj>/<session>/subagents/agent-<id>.jsonl`) has not been written for more than `stale_min`
minutes AND its last message record is not a final assistant message. Stubs older than `max_age_h` are skipped.

Linking a stub to its transcript, never guessing (agent_footer_gate.py derives the report path from the launch):
  1. the transcript's FIRST record (the sub-agent's prompt, which carries the filled footer) names the stub's absolute path as ITS OWN
     report (the footer's delivery line, a `Report path:` / `Report:` label, or the only `*-report.md` path in the prompt);
  2. else, only when that prompt names no `*-report.md` path at all, the transcript sits in the stub's session directory and its
     `description` (the `.meta.json` next to it) slugs to the stub's name, which is how the hook builds a path it derived itself.
  A stub no transcript links to is `unlinked` (a `paseo run` worker's stub, or a transcript that is gone); it is reported, never
  matched by luck. Several transcripts for one stub (a resumed or relaunched agent): the stub is stalled only when EVERY one of them is.

A pending tool call is not a stall: when the last message is an assistant `tool_use` the tool may still be running (a 25-minute
`bgrun` test run, a `wait-file --timeout 1500`), so that case waits `tool_grace_min` (default 35: just over the 30-minute foreground
cap) or the call's own `timeout` plus 5 minutes, whichever is longer.

Notify mode only pings (`hermes-ping`) and, for a parent that is a live IDLE Paseo agent, `paseo send --json --no-wait` it the resume
instruction. It never resumes, restarts, archives or kills anything. Per stall, each action repeats at most once per `repeat_h` (6 h);
the state is `<state>/seen.json`, written atomically under a lock. Both tools are called by the absolute paths in `Config`: nothing
here looks at PATH, and no function reads the real home unless `Config.home` is it.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STUB_FIRST_LINE = "STATUS: working"
FINAL_STOP_REASONS = frozenset({"end_turn", "stop_sequence"})
TOOL_CALL_DEFAULT_GRACE_MIN = 35.0
TOOL_TIMEOUT_MARGIN_MIN = 5.0
LINK_MTIME_SLACK_S = 300.0              # a transcript last written >5 min before the stub's last write cannot have written the stub
MAX_FIRST_RECORD_BYTES = 4 * 1024 * 1024
MAX_TAIL_BYTES = 64 * 1024 * 1024
CHUNK = 256 * 1024
NOTIFY_TIMEOUT_S = 60

# The own-report patterns of claude/hooks/agent_footer_gate.py, simplified (that file runs at import and cannot be imported).
_LEFT = r"(?<![\w.~$@+/-])"
_PATH = r"(/[\w.@~+/-]+-report\.md)"
_END = r"(?![\w-])"
FOOTER_DELIVERY = re.compile(r"deliverable to `" + _LEFT + _PATH + r"`")
REPORT_LABEL = re.compile(r"(?im)^[ \t>]{0,6}(?:(?:[A-Za-z]?\d+[a-z]?[.)]|[-*])[ \t]+)?[*_`]*report(?:[ \t]+(?:path|file))?[*_`]*[ \t]*(?:is|:|=)[*_`]*[ \t]*`?"
                          + _LEFT + _PATH + _END)
ANY_REPORT_PATH = re.compile(_LEFT + _PATH + _END)


class StallError(Exception):
    """A usage or environment error: exit 2."""


@dataclass
class Config:
    home: Path
    reports_dir: Path
    projects_dir: Path
    paseo_agents_dir: Path
    state_dir: Path
    stale_min: float = 10.0
    max_age_h: float = 48.0
    tool_grace_min: float = TOOL_CALL_DEFAULT_GRACE_MIN
    repeat_h: float = 6.0
    now: float = field(default_factory=time.time)
    hermes_ping: Path | None = None
    paseo: Path | None = None
    repo: str = "djbclark-ade"
    dry_run: bool = False
    baseline: bool = False
    max_pings: int = 5


def make_config(home: Path, **over: Any) -> Config:
    """A Config under `home` (never the real home implicitly): the stock locations, any of them overridden by keyword."""
    home = Path(home)
    cfg = Config(home=home, reports_dir=home / ".local/state/agent-reports", projects_dir=home / ".claude/projects",
                 paseo_agents_dir=home / ".paseo/agents", state_dir=home / ".local/state/djbclark-ade/subagent-stalls")
    for key, value in over.items():
        if not hasattr(cfg, key):
            raise TypeError(f"unknown Config field {key}")
        setattr(cfg, key, value)
    return cfg


def slug(text: str) -> str:
    """agent_footer_gate.slug: the hook names a derived report `<slug(description)>-report.md` (tests/test_subagent_stalls.py pins parity)."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")
    return s or "subagent"


# ---------------------------------------------------------------- stubs

@dataclass
class Stub:
    path: str
    session: str
    name: str
    mtime: float


def find_stubs(cfg: Config) -> tuple[list[Stub], int]:
    """(stubs younger than max_age_h, how many were skipped as too old). A stub: first line `STATUS: working`, no `.done`."""
    out: list[Stub] = []
    too_old = 0
    if not cfg.reports_dir.is_dir():
        return out, too_old
    for p in sorted(cfg.reports_dir.glob("*/*-report.md")):
        try:
            if not p.is_file():
                continue
            with open(p, "rb") as f:
                first = f.readline(256).decode("utf-8", "replace").strip()
            if first != STUB_FIRST_LINE or Path(str(p) + ".done").exists():
                continue
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if (cfg.now - mtime) / 3600.0 > cfg.max_age_h:
            too_old += 1
            continue
        out.append(Stub(path=str(p), session=p.parent.name, name=p.name, mtime=mtime))
    return out, too_old


# ---------------------------------------------------------------- transcripts

@dataclass
class Transcript:
    path: Path
    session: str
    agent_id: str
    mtime: float


def index_transcripts(cfg: Config, min_mtime: float) -> list[Transcript]:
    out = []
    if not cfg.projects_dir.is_dir():
        return out
    for p in cfg.projects_dir.glob("*/*/subagents/agent-*.jsonl"):
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_mtime < min_mtime:
            continue
        out.append(Transcript(path=p, session=p.parent.parent.name, agent_id=p.stem[len("agent-"):], mtime=st.st_mtime))
    return out


def _content_text(rec: dict) -> str:
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def prompt_text(t: Transcript) -> str | None:
    """The text of the transcript's first record (the sub-agent's prompt), or None when it cannot be read."""
    try:
        with open(t.path, "rb") as f:
            line = f.readline(MAX_FIRST_RECORD_BYTES)
        rec = json.loads(line)
    except (OSError, ValueError):
        return None
    return _content_text(rec) if isinstance(rec, dict) else None


def description_of(t: Transcript) -> str | None:
    try:
        meta = json.loads(t.path.with_name(t.path.stem + ".meta.json").read_text())
    except (OSError, ValueError):
        return None
    desc = meta.get("description") if isinstance(meta, dict) else None
    return desc if isinstance(desc, str) else None


def own_reports(text: str) -> tuple[set[str], bool]:
    """(the report paths the prompt gives as its own, whether it names any `*-report.md` path at all). Own: the footer's delivery
    line and `Report path:` / `Report:` labels; with neither, the one `*-report.md` path of the prompt when it has just one."""
    own = set(FOOTER_DELIVERY.findall(text)) | set(REPORT_LABEL.findall(text))
    anyp = set(ANY_REPORT_PATH.findall(text))
    if not own and len(anyp) == 1:
        own = anyp
    return own, bool(anyp)


def link_stub(stub: Stub, transcripts: list[Transcript], prompts: dict[Path, str | None]) -> list[tuple[Transcript, str]]:
    """Every transcript the stub links to, as (transcript, how). Empty = unlinked."""
    found = []
    for t in transcripts:
        if t.mtime < stub.mtime - LINK_MTIME_SLACK_S:
            continue
        if t.path not in prompts:
            prompts[t.path] = prompt_text(t)
        text = prompts[t.path]
        if text is None:
            continue
        own, named_any = own_reports(text)
        if stub.path in own:
            found.append((t, "path"))
        elif not named_any and t.session == stub.session:
            desc = description_of(t)
            if desc is not None and slug(desc) + "-report.md" == stub.name:
                found.append((t, "session+description"))
    return found


# ---------------------------------------------------------------- last message

@dataclass
class LastMessage:
    kind: str                 # final | tool_pending | assistant | user | none
    tool_timeout_min: float | None = None


def _reverse_lines(path: Path):
    """Lines of a file from the end, as bytes, reading at most MAX_TAIL_BYTES; a line cut by that cap is dropped."""
    with open(path, "rb") as f:
        pos = f.seek(0, os.SEEK_END)
        floor = max(0, pos - MAX_TAIL_BYTES)
        carry = b""
        while pos > floor:
            step = min(CHUNK, pos - floor)
            pos -= step
            f.seek(pos)
            buf = f.read(step) + carry
            parts = buf.split(b"\n")
            carry = parts[0]
            for line in reversed(parts[1:]):
                if line.strip():
                    yield line
        if pos == 0 and carry.strip():
            yield carry


def last_message(path: Path) -> LastMessage | None:
    """Classify the last user/assistant record (attachments, api-request and other bookkeeping records are not messages).
    None when the file cannot be read or holds no message record within the tail cap."""
    try:
        for line in _reverse_lines(path):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict) or rec.get("type") not in ("assistant", "user"):
                continue
            if rec["type"] == "user":
                return LastMessage("user")
            msg = rec.get("message") or {}
            stop = msg.get("stop_reason")
            if stop in FINAL_STOP_REASONS:
                return LastMessage("final")
            blocks = msg.get("content") if isinstance(msg.get("content"), list) else []
            calls = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"]
            if stop == "tool_use" or calls:
                timeouts = [b["input"]["timeout"] for b in calls
                            if isinstance(b.get("input"), dict) and isinstance(b["input"].get("timeout"), (int, float))
                            and not isinstance(b["input"].get("timeout"), bool) and not b["input"].get("run_in_background")]
                return LastMessage("tool_pending", max(timeouts) / 60000.0 if timeouts else None)
            return LastMessage("assistant")
    except OSError:
        return None
    return None


@dataclass
class Assessment:
    transcript: Transcript
    how: str
    idle_min: float
    last: LastMessage | None
    stalled: bool


def assess(cfg: Config, t: Transcript, how: str) -> Assessment:
    idle_min = max(0.0, (cfg.now - t.mtime) / 60.0)
    last = last_message(t.path)
    if last is None or last.kind == "final":
        return Assessment(t, how, idle_min, last, False)         # unreadable is never an alarm; a final message is a finished agent
    threshold = cfg.stale_min
    if last.kind == "tool_pending":
        threshold = max(threshold, cfg.tool_grace_min)
        if last.tool_timeout_min is not None:
            threshold = max(threshold, last.tool_timeout_min + TOOL_TIMEOUT_MARGIN_MIN)
    return Assessment(t, how, idle_min, last, idle_min > threshold)


# ---------------------------------------------------------------- parent (Paseo)

def paseo_parent(cfg: Config, session: str) -> tuple[str | None, bool]:
    """(Paseo agent id whose Claude session is `session`, whether its state file says it is not archived). A live agent wins over an
    archived one; (None, False) when none matches. Reads `<agents>/<cwd slug>/<id>.json` (the daemon's state files)."""
    best: tuple[str, bool] | None = None
    if not cfg.paseo_agents_dir.is_dir():
        return None, False
    for p in cfg.paseo_agents_dir.glob("*/*.json"):
        try:
            text = p.read_text()
            if session not in text:
                continue
            rec = json.loads(text)
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict):
            continue
        sessions = {(rec.get("persistence") or {}).get("sessionId"), (rec.get("persistence") or {}).get("nativeHandle"),
                    (rec.get("runtimeInfo") or {}).get("sessionId")}
        if session not in sessions or not isinstance(rec.get("id"), str):
            continue
        live = not rec.get("archivedAt")
        if best is None or (live and not best[1]):
            best = (rec["id"], live)
    return best if best else (None, False)


# ---------------------------------------------------------------- scan

@dataclass
class Stall:
    report: str
    session_id: str
    agent_id: str
    transcript: str
    idle_min: float
    parent_session: str
    parent_paseo_agent_id: str | None
    parent_live: bool
    last_record: str
    link: str
    suggested_action: str

    def as_dict(self) -> dict:
        return {"report": self.report, "session_id": self.session_id, "agent_id": self.agent_id, "transcript": self.transcript,
                "idle_min": round(self.idle_min, 1), "parent_session": self.parent_session,
                "parent_paseo_agent_id": self.parent_paseo_agent_id, "parent_live": self.parent_live,
                "last_record": self.last_record, "link": self.link, "suggested_action": self.suggested_action}


@dataclass
class ScanResult:
    stalled: list[Stall] = field(default_factory=list)
    unlinked: list[str] = field(default_factory=list)
    checked: int = 0
    too_old: int = 0
    warnings: list[str] = field(default_factory=list)


def resume_text(agent_id: str, report: str) -> str:
    return (f"Sub-agent {agent_id} (report {report}) stopped mid-run: its transcript has not grown and its report has no .done. "
            f"Resume it with SendMessage to {agent_id}: \"resume from where you stopped\" (it continues from its transcript).")


def suggested_action(agent_id: str, report: str, session: str, paseo_id: str | None, live: bool) -> str:
    if paseo_id and live:
        return f"paseo send --json --no-wait {paseo_id} \"{resume_text(agent_id, report)}\""
    return f"SendMessage to {agent_id} from session {session} to resume"


def scan(cfg: Config) -> ScanResult:
    res = ScanResult()
    stubs, res.too_old = find_stubs(cfg)
    res.checked = len(stubs)
    if not stubs:
        return res
    transcripts = index_transcripts(cfg, min(s.mtime for s in stubs) - LINK_MTIME_SLACK_S)
    prompts: dict[Path, str | None] = {}
    for stub in stubs:
        links = link_stub(stub, transcripts, prompts)
        if not links:
            res.unlinked.append(stub.path)
            continue
        assessed = [assess(cfg, t, how) for t, how in links]
        if not all(a.stalled for a in assessed):
            continue
        a = max(assessed, key=lambda x: x.transcript.mtime)
        t = a.transcript
        paseo_id, live = paseo_parent(cfg, t.session)
        res.stalled.append(Stall(
            report=stub.path, session_id=t.session, agent_id=t.agent_id, transcript=str(t.path), idle_min=a.idle_min,
            parent_session=t.session, parent_paseo_agent_id=paseo_id, parent_live=live,
            last_record=a.last.kind if a.last else "unknown", link=a.how,
            suggested_action=suggested_action(t.agent_id, stub.path, t.session, paseo_id, live)))
    return res


# ---------------------------------------------------------------- notify

def stall_key(s: Stall) -> str:
    return f"{s.agent_id}|{s.report}"


def _load_state(path: Path, warnings: list[str]) -> dict:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {"version": 1, "stalls": {}}
    except (OSError, ValueError) as exc:
        warnings.append(f"seen.json unreadable ({exc}); starting empty")
        return {"version": 1, "stalls": {}}
    if not isinstance(data, dict) or not isinstance(data.get("stalls"), dict):
        warnings.append("seen.json has an unexpected shape; starting empty")
        return {"version": 1, "stalls": {}}
    return data


def _write_atomic(path: Path, data: dict) -> None:
    """Temp file in the same directory, fsync, then rename: a reader never sees half a file."""
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=1, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _run(argv: list[str], warnings: list[str]) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=NOTIFY_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        warnings.append(f"{argv[0]} failed: {exc}")
        return None


def ping_text(cfg: Config, s: Stall) -> str:
    parent = s.parent_paseo_agent_id or s.parent_session
    return (f"{cfg.repo}: stalled sub-agent {s.agent_id} (report {s.report}), idle {s.idle_min:.0f} min; parent {parent}")


def parent_idle(cfg: Config, paseo_id: str, warnings: list[str]) -> bool:
    """True only when `paseo agent inspect` says the parent exists, is not archived and is idle: a send to a busy agent would interrupt
    its turn, and one to an archived agent would un-archive it."""
    if cfg.paseo is None:
        warnings.append("no paseo path configured: parent not messaged")
        return False
    proc = _run([str(cfg.paseo), "agent", "inspect", paseo_id, "--json"], warnings)
    if proc is None or proc.returncode != 0:
        return False
    try:
        info = json.loads(proc.stdout)
    except ValueError:
        return False
    return isinstance(info, dict) and info.get("Archived") is False and str(info.get("Status", "")).lower() == "idle"


def notify(cfg: Config, stalls: list[Stall]) -> list[str]:
    """Ping each NEW stall, and each one again at most once per repeat_h. Returns warnings and event lines (printed to stderr)."""
    events: list[str] = []
    repeat_s = cfg.repeat_h * 3600.0
    if not cfg.dry_run:
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
    state_file = cfg.state_dir / "seen.json"
    lock = None
    try:
        if not cfg.dry_run:
            lock = open(cfg.state_dir / "seen.lock", "w")
            fcntl.flock(lock, fcntl.LOCK_EX)
        data = _load_state(state_file, events)
        seen = data["stalls"]
        before = json.dumps(data, sort_keys=True)
        live_keys = {stall_key(s) for s in stalls}
        pings = 0
        for s in stalls:
            entry = seen.setdefault(stall_key(s), {"first_seen": cfg.now, "report": s.report, "agent_id": s.agent_id})
            if cfg.baseline:
                entry["baseline"] = True            # known when the watcher was switched on: shown, never announced
                continue
            if entry.get("baseline"):
                continue
            if pings >= cfg.max_pings and not entry.get("hermes_ping"):
                events.append(f"ping cap ({cfg.max_pings} per run): {s.agent_id} waits for the next run")
                seen.pop(stall_key(s), None)
                continue
            if not entry.get("hermes_ping") or cfg.now - entry["hermes_ping"] >= repeat_s:
                if cfg.dry_run:
                    events.append(f"dry-run: would hermes-ping: {ping_text(cfg, s)}")
                elif cfg.hermes_ping is None:
                    events.append("no hermes-ping path configured: not pinged")
                else:
                    proc = _run([str(cfg.hermes_ping), ping_text(cfg, s)], events)
                    pings += 1
                    if proc is not None and proc.returncode == 0:
                        entry["hermes_ping"] = cfg.now
                        events.append(f"pinged: {s.agent_id}")
                    elif proc is not None:
                        events.append(f"hermes-ping rc={proc.returncode} for {s.agent_id}: {(proc.stderr or '').strip()[:200]}")
            if s.parent_paseo_agent_id and s.parent_live and (not entry.get("paseo_send") or cfg.now - entry["paseo_send"] >= repeat_s):
                if cfg.dry_run:
                    events.append(f"dry-run: would paseo send {s.parent_paseo_agent_id} if idle")
                elif parent_idle(cfg, s.parent_paseo_agent_id, events):
                    proc = _run([str(cfg.paseo), "send", "--json", "--no-wait", s.parent_paseo_agent_id,
                                 resume_text(s.agent_id, s.report)], events)
                    if proc is not None and proc.returncode == 0:
                        entry["paseo_send"] = cfg.now
                        events.append(f"sent resume instruction to {s.parent_paseo_agent_id}")
                    elif proc is not None:
                        events.append(f"paseo send rc={proc.returncode} to {s.parent_paseo_agent_id}: {(proc.stderr or '').strip()[:200]}")
                else:
                    events.append(f"parent {s.parent_paseo_agent_id} is not an idle live agent: not messaged (retried next run)")
            if not entry.get("hermes_ping") and not entry.get("paseo_send") and not cfg.dry_run:
                seen.pop(stall_key(s), None)        # nothing delivered: not "seen", so the next run tries again
        for key in [k for k in seen if k not in live_keys]:
            del seen[key]                            # no longer stalled: a later stall of it is new
        if not cfg.dry_run and json.dumps(data, sort_keys=True) != before:
            _write_atomic(state_file, data)
    finally:
        if lock is not None:
            lock.close()
    return events


# ---------------------------------------------------------------- CLI

def render_text(res: ScanResult) -> str:
    lines = []
    for s in res.stalled:
        lines.append(f"STALLED sub-agent {s.agent_id} idle {s.idle_min:.0f} min (last record: {s.last_record}, link: {s.link})")
        lines.append(f"  report: {s.report}")
        lines.append(f"  transcript: {s.transcript}")
        lines.append(f"  parent: session {s.parent_session}, paseo {s.parent_paseo_agent_id or '-'}{'' if s.parent_live or not s.parent_paseo_agent_id else ' (archived)'}")
        lines.append(f"  action: {s.suggested_action}")
    for path in res.unlinked:
        lines.append(f"unlinked stub (no sub-agent transcript links to it): {path}")
    lines.append(f"{len(res.stalled)} stalled, {len(res.unlinked)} unlinked, {res.checked} working stubs checked, "
                 f"{res.too_old} skipped as too old")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ade-subagent-stalls", description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", action="store_true", help="print the stalled sub-agents as a JSON list")
    ap.add_argument("--notify", action="store_true", help="hermes-ping each new stall; paseo send an idle live Paseo parent (notify only)")
    ap.add_argument("--dry-run", action="store_true", help="with --notify: print what would be sent; send nothing, write no state")
    ap.add_argument("--stale-min", type=float, default=10.0, help="minutes without transcript growth (default 10)")
    ap.add_argument("--max-age-h", type=float, default=48.0, help="skip stubs older than this many hours (default 48)")
    ap.add_argument("--tool-grace-min", type=float, default=TOOL_CALL_DEFAULT_GRACE_MIN,
                    help="minutes a pending tool call may run before it counts as stalled (default 35)")
    ap.add_argument("--repeat-h", type=float, default=6.0, help="ping the same stall again after this many hours (default 6)")
    ap.add_argument("--home", type=Path, default=None, help="home directory holding .local/state, .claude and .paseo (default: the real one)")
    ap.add_argument("--reports-dir", type=Path)
    ap.add_argument("--projects-dir", type=Path)
    ap.add_argument("--paseo-agents-dir", type=Path)
    ap.add_argument("--state-dir", type=Path)
    ap.add_argument("--hermes-ping", type=Path, help="absolute path of hermes-ping (default: <home>/.local/bin/hermes-ping)")
    ap.add_argument("--paseo", type=Path, help="absolute path of paseo (default: <home>/.local/bin/paseo)")
    ap.add_argument("--baseline", action="store_true",
                    help="with --notify: record every stall found now as known, announce nothing (switching the watcher on; they are never pinged)")
    ap.add_argument("--max-pings", type=int, default=5, help="at most this many hermes pings per run (default 5); the rest wait for the next run")
    ap.add_argument("--now", type=float, help=argparse.SUPPRESS)
    return ap


def config_from_args(args: argparse.Namespace) -> Config:
    home = args.home if args.home is not None else Path.home()
    over: dict[str, Any] = {"stale_min": args.stale_min, "max_age_h": args.max_age_h, "tool_grace_min": args.tool_grace_min,
                            "repeat_h": args.repeat_h, "dry_run": args.dry_run, "baseline": args.baseline,
                            "max_pings": args.max_pings}
    for opt, key in (("reports_dir", "reports_dir"), ("projects_dir", "projects_dir"), ("paseo_agents_dir", "paseo_agents_dir"),
                     ("state_dir", "state_dir")):
        if getattr(args, opt) is not None:
            over[key] = getattr(args, opt)
    if args.now is not None:
        over["now"] = args.now
    over["hermes_ping"] = args.hermes_ping if args.hermes_ping is not None else Path(home) / ".local/bin/hermes-ping"
    over["paseo"] = args.paseo if args.paseo is not None else Path(home) / ".local/bin/paseo"
    return make_config(home, **over)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if (args.dry_run or args.baseline) and not args.notify:
        print("ade-subagent-stalls: --dry-run and --baseline need --notify", file=sys.stderr)
        return 2
    try:
        cfg = config_from_args(args)
        for opt in ("stale_min", "max_age_h", "tool_grace_min", "repeat_h", "max_pings"):
            if getattr(cfg, opt) < 0:
                raise StallError(f"--{opt.replace('_', '-')} must not be negative")
        for tool in (cfg.hermes_ping, cfg.paseo):
            if tool is not None and not tool.is_absolute():
                raise StallError(f"{tool}: tool paths must be absolute")
        if args.notify and not cfg.dry_run and not (cfg.hermes_ping and os.access(cfg.hermes_ping, os.X_OK)):
            raise StallError(f"hermes-ping not executable at {cfg.hermes_ping}; pass --hermes-ping /absolute/path")
        res = scan(cfg)
        events = notify(cfg, res.stalled) if args.notify else []      # with none stalled it still prunes the stalls that ended
    except (StallError, OSError) as exc:
        print(f"ade-subagent-stalls: {exc}", file=sys.stderr)
        return 2
    for line in res.warnings + events:
        print(f"ade-subagent-stalls: {line}", file=sys.stderr)
    if args.json:
        print(json.dumps([s.as_dict() for s in res.stalled], indent=1))
    else:
        print(render_text(res))
    return 1 if res.stalled else 0


if __name__ == "__main__":
    sys.exit(main())
