#!/usr/bin/env python3
"""context_size_nudge.py — early, escalating context-size prompts.

Registered under UserPromptSubmit and PostToolUse. Reads Claude Code hook JSON
on stdin and checks the transcript's context size for a new tier. Prompt-submit
notes use plain stdout; tool-event notes use JSON additionalContext and check
at most every POST_TOOL_CHECK_SECONDS per session.
Each note tells the agent what to do and what to recommend to the operator.

History:
- 2026-10-28: persisted each emitted nudge in a rotating JSONL log, independent
  of compaction resets; added PostToolUse JSON output and a 20 s per-session
  transcript-check limit. Settings registration remains operator-gated.
- 2026-10-29: PostToolUse is in agents/claude/settings.json.tmpl (the live settings get the
  entry by hand once this code is on the shared checkout); PostToolUse calls from a
  sub-agent (agent_id set) are ignored; the mid-task note has one cadence sentence for
  both events (the prompt-only text became false once PostToolUse ran), built from
  POST_TOOL_CHECK_SECONDS instead of a hard-coded 20 s.
- 2026-08-03: built after a session grew to 670k+ tokens unnoticed.
- 2026-08-23: reworded to "never suggest a wrap-up" (continuous operation).
- 2026-10-05: fail-fast tail read + 2 s internal deadline (load 223 killed it).
- 2026-10-08 (operator ruling, supersedes 2026-08-23): prompt earlier and
  harder, and DO recommend /compact, or /handoff then /new. The old single
  150k nudge fired too late. Separable work goes to /bigteam by default so it
  never lands in this context. memory/feedback_context_prompts_early.md.
- 2026-10-10: stop the compaction loop. Measured over 85 compactions in two
  days: a /compact took context from ~187k to ~104k (not the ~33k Claude Code
  reports as postTokens: tool listings, project context and re-attached files
  come back), so the old 150k / +70k tiers re-fired after ~40 requests, and
  sessions compacted every ~25 min (one 24 times in a day). Each compaction
  re-writes ~70k tokens at the 1-hour cache's 2x rate plus the summary, ~150-
  180k base-input-equivalent; with cache reads at 0.025x (Fable 5.1) / 0.05x
  (Opus/Sonnet 5.5) that pays back only after ~45-85 requests, so most were a
  net loss. Growth now counts from the floor after the latest compaction, the
  compact tier is +200k (or 400k total), and the early tier no longer
  recommends /compact. memory/feedback_self_compact.md.
- 2026-10-18 (Fable cache-cost review, operator-approved): autoCompactWindow
  400k -> 300k (simulated -1.6% cost; Claude Code compacts at the window less
  its ~33k buffer, so ~267k), ASK_TOTAL follows it, PAGE_TOTAL 500k -> 400k.
  A fresh session (/new) re-writes ~46k; a compaction re-writes ~72k plus a
  summariser call and leaves ~104k behind, so at a finished task the first
  choice is now the `handoff` skill + /new, and /compact only when the work
  must continue in-context. A once-per-session note at BOUNDARY_TOTAL says so
  early. Never compact at <=200k (simulated +0.9% at 200k, +17.1% at 150k).
- 2026-10-28 (context audit, 38 sessions peaking 200-270k, 72 auto compactions at ~267k):
  the hard tier fired too late or never. floor + ASK_GROWTH 200k was 235-271k (median
  floor 71k: past the wall), ASK_TOTAL 300k sat above it, and after a compaction (floor
  ~104k) the growth tier was unreachable again, so sessions compacted repeatedly with no
  hard nudge (one 25 times). Now ASK_TOTAL = wall - 50k = 217k (also the post-compaction
  trigger, at +113k), ASK_GROWTH 140k for low floors, and the hard text says what to do
  mid-turn (finish the edit, hand off within N tool rounds) since the hook runs only at
  prompt submit.

Measure: input + cache_creation + cache_read tokens of the newest usage block,
i.e. the real context size (cache_read alone reads 0 after a cache miss).
Tiers count GROWTH since the floor: the first usage block of the session, or of
the conversation after its latest compaction (a compact_boundary record as the newest
record, a non-sidechain boundary appended since the previous prompt (the transcript's byte
size is stored per session: an auto-compaction mid-turn is followed by more tool rounds, so
the boundary is no longer the newest record), or a drop below SHRINK_RATIO of the highest
size seen since the last reset). Baselines differ a lot (2026-10-28,
267 sessions: median 71k, range 0-164k; a compacted one ~104k).
An absolute backstop asks at ASK_TOTAL, 50k+ under the auto-compaction wall.

Levels: 1 = early (delegate from now on; no compaction yet);
2+ = handoff + /new at a finished task, /compact only to continue in-context
(self-slash in herdr/Orca; elsewhere auto-compaction), or, mid-turn, finish the
current edit and hand off within a few tool rounds (_midtask_note); again every
REPEAT_EVERY of further growth. A compaction resets the floor and the level, so
the hard tier fires again at ASK_TOTAL (by total, not by growth) after regrowth.
Separately, once per session at BOUNDARY_TOTAL: prefer handoff + /new over
/compact at the next task completion. With the wall at 267k, REPEAT_EVERY (level 3+) and the
PAGE_* tiers are mostly unreachable before the wall (level 3 needs a floor under ~27k).

MUST always exit 0 -- never fail or delay a prompt. Python 3 stdlib only.
Fail-fast: reads only a head window (baseline, once per session) and a tail
window (newest usage), never waits on the Hermes ping (detached Popen), and
an alarm at DEADLINE_SECONDS exits 0 with no output.
"""
# Every failure is swallowed on purpose: a hook error must never block a prompt.
# ruff: noqa: BLE001, S110
import json
import os
import re
import shutil
import signal
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path

try:
    import fcntl
except ImportError:  # non-POSIX hosts still emit best-effort nudges
    fcntl = None

STATE_PATH = Path.home() / ".claude" / "state" / "context-nudges.json"
LOG_PATH = Path(os.environ.get("CONTEXT_NUDGE_LOG_PATH") or
                Path.home() / ".claude" / "state" / "context-nudge-log.jsonl")
if not LOG_PATH.is_absolute():
    LOG_PATH = Path.home() / ".claude" / "state" / "context-nudge-log.jsonl"
LOG_MAX_BYTES = 2 * 1024 * 1024
POST_TOOL_CHECK_SECONDS = 20
# Written by the quota guard (another slice, 2026-10-23); may not exist.  Only `level` is read.
QUOTA_GUARD_PATH = Path.home() / ".local" / "state" / "ade" / "quota-guard.json"
# djbclark, 2026-10-23: lead sessions run on Opus 5.5 high (Sonnet 5.5 when quota is tight),
# not Fable (a Fable lead burned ~30% of a week's Claude quota).
FABLE_MODEL = "claude-fable-5-1"
SUCCESSOR_OPUS = "claude/claude-opus-5-5"
SUCCESSOR_SONNET = "claude/claude-sonnet-5-5"

# Compaction is not free (see History, 2026-10-10): only compact once the
# context has grown enough above the post-compaction floor to pay it back.
EARLY_GROWTH = 32_000   # 2026-10-25: delegate earlier; this alone never compacts
# ~/.claude/settings.json "autoCompactWindow" (set 2026-10-15, 300k since
# 2026-10-18): Claude Code compacts by itself near this size, on every host, so
# outside herdr/Orca the level-2 note no longer asks the operator. The real
# trigger is the window less the "Autocompact buffer" /context shows (~33k):
# AUTO_COMPACT_WALL = 267k (measured 2026-10-23..28: 72 auto compactions,
# preTokens 266k-285k, median ~268k).
AUTO_COMPACT_WINDOW = 300_000
AUTO_COMPACT_BUFFER = 33_000
AUTO_COMPACT_WALL = AUTO_COMPACT_WINDOW - AUTO_COMPACT_BUFFER
# Level 2 (the hard tier) must fire with headroom before that wall: the hook runs only at
# prompt submit, and the agent still needs several tool rounds plus the handoff itself.
# 2026-10-28: ASK_GROWTH 200k fired at floor+200k = 235-271k (median floor 71k: past the
# wall, never), leaving 0-20k, and ASK_TOTAL 300k sat above the wall and never fired.
ASK_HEADROOM = 50_000
ASK_TOTAL = AUTO_COMPACT_WALL - ASK_HEADROOM  # 217k: level 2 regardless of floor; after a
# compaction (floor ~104k) this is what fires, at +113k, since floor + ASK_GROWTH would be 244k
ASK_GROWTH = 140_000    # level 2 for a low floor (35-77k): sooner than ASK_TOTAL, always < it
TOOL_ROUND_TOKENS = 8_000    # a tool round costs 3-8k; a big file or log read costs more
HANDOFF_RESERVE = 15_000     # what the handoff skill itself needs before the wall
BOUNDARY_TOTAL = 120_000  # 2026-10-25: earlier handoff at completed task boundaries
REPEAT_EVERY = 100_000  # level 3, 4, ...: again per this much more
PAGE_GROWTH = 300_000   # Hermes ping (once per climb), whichever comes first
PAGE_TOTAL = 400_000
SHRINK_RATIO = 0.75     # a size below this share of the last one = compacted
COMPACTED = "compacted"  # _last_context_tokens: boundary newer than any usage
# Unescaped quotes only: the same text inside a tool result is JSON-escaped.
_BOUNDARY = re.compile(rb'"subtype":\s*"compact_boundary"')
# The boundary search over the appended bytes (_compaction_floor_since): raw-bytes chunks that
# overlap by more than the longest match (the needle is 28 bytes plus whatever whitespace),
# starting a little before the previous prompt's size, never more than the cap in total.
_SCAN_CHUNK = 1024 * 1024
_SCAN_OVERLAP = 128
_SCAN_BACK = 64 * 1024
_SCAN_CAP = 64 * 1024 * 1024

PING_BIN = Path.home() / ".local" / "bin" / "hermes-ping"

# Internal deadline: past this the hook exits 0 silently (see module docstring).
DEADLINE_SECONDS = 2

# Tail-read windows, smallest first. Newest usage block is almost always in the
# first window; the last one matches the original 2 MB scan.
_TAIL_WINDOWS = (128 * 1024, 2 * 1024 * 1024)
_TAIL_REJECT_LIMIT = 64
_HEAD_WINDOW = 512 * 1024


def _on_deadline(signum, frame):
    # os._exit: no unwinding, no buffered partial output, no chance of a hang.
    os._exit(0)


def _usage_from_line(line):
    """Context size (input + cache creation + cache read) from one transcript
    line, or None. Sub-agent (sidechain) records are skipped."""
    if b"cache_read_input_tokens" not in line:
        return None  # cheap reject: skips json.loads for most lines
    try:
        obj = json.loads(line)
    except Exception:
        return None
    if not isinstance(obj, dict) or obj.get("isSidechain"):
        return None
    message = obj.get("message")
    usage = message.get("usage") if isinstance(message, dict) else None
    if not isinstance(usage, dict):
        return None
    parts = [usage.get(k) for k in
             ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")]
    if not any(isinstance(p, int) for p in parts):
        return None
    total = sum(p for p in parts if isinstance(p, int))
    # A zero-usage record is an API-error stub (model "<synthetic>", e.g. a session or
    # weekly limit notice), never a context reading: counted, it reads as a shrink to 0
    # and the next prompt's whole context looks like growth (adversary 108 r4 F2).
    return total if total > 0 else None


def _is_boundary_line(line):
    """True for a real main-session compaction record: a `system` record of subtype
    compact_boundary. The raw-bytes match alone also hits a structured tool_use input that
    holds the same JSON (round 3, F3), so a hit is parsed."""
    if not _BOUNDARY.search(line):
        return False
    try:
        obj = json.loads(line)
    except Exception:
        return False
    return (isinstance(obj, dict) and obj.get("type") == "system"
            and obj.get("subtype") == "compact_boundary" and not obj.get("isSidechain"))


def _last_context_tokens(transcript_path):
    """Best-effort: the newest usage block's context size.

    Reads a small window off the end of the file and scans it newest line
    first, returning at the first hit; only widens the window (up to 2 MB)
    when the small one had none. A huge transcript is never read forward.
    Search raw needles backwards, skipping unrelated lines without parsing;
    reject at most 64 candidate records across both windows (PostToolUse's
    frequent checks must stay comfortably inside the two-second deadline).
    Exhaustion returns no measurement rather than an older, misleading one.
    """
    try:
        with Path(transcript_path).open("rb") as f:
            size = os.fstat(f.fileno()).st_size
            tried = 0
            skipped = 0
            rejected = 0
            for window in _TAIL_WINDOWS:
                chunk_size = min(size, window)
                if chunk_size <= tried:
                    break
                f.seek(size - chunk_size)
                data = f.read(chunk_size)
                first = data.find(b"\n") + 1 if chunk_size < size else 0
                # Only scan older complete lines. Include the partial line the
                # previous window skipped, but never reject its full lines twice.
                end = chunk_size - tried + skipped
                tried, skipped = chunk_size, first
                while end > first:
                    pos = max(data.rfind(b"cache_read_input_tokens", first, end),
                              data.rfind(b'"compact_boundary"', first, end))
                    if pos < 0:
                        break
                    start = data.rfind(b"\n", first, pos) + 1
                    start = max(first, start)
                    stop = data.find(b"\n", pos, end)
                    line = data[start:stop if stop >= 0 else end]
                    end = start
                    if _is_boundary_line(line):
                        return COMPACTED  # no request since the compaction yet
                    value = _usage_from_line(line)
                    if value is not None:
                        return value
                    rejected += 1
                    if rejected >= _TAIL_REJECT_LIMIT:
                        return None
                if chunk_size >= size:
                    break
    except Exception:
        return None
    return None


def _file_size(transcript_path):
    try:
        return Path(transcript_path).stat().st_size
    except Exception:
        return None


def _line_span(f, pos, size):
    """Byte offsets (start, end) of the line holding `pos`; `end` is past its newline (or the
    file size when the writer has not finished it). Looks at most _SCAN_CAP bytes either way."""
    start = pos
    lo = max(0, pos - _SCAN_CAP)
    while start > lo:
        step = min(_SCAN_CHUNK, start - lo)
        f.seek(start - step)
        index = f.read(step).rfind(b"\n")
        if index >= 0:
            start = start - step + index + 1
            break
        start -= step
    end = pos
    hi = min(size, pos + _SCAN_CAP)
    while end < hi:
        f.seek(end)
        buf = f.read(min(_SCAN_CHUNK, hi - end))
        if not buf:
            break
        index = buf.find(b"\n")
        if index >= 0:
            return start, end + index + 1
        end += len(buf)
    return start, end


def _usage_after(f, pos, size):
    """The first usage record in [pos, size), read in chunks; None when there is none."""
    pieces = []
    while pos < size:
        f.seek(pos)
        buf = f.read(min(_SCAN_CHUNK, size - pos))
        if not buf:
            break
        pos += len(buf)
        parts = buf.split(b"\n")
        pieces.append(parts[0])
        if len(parts) == 1:
            continue
        lines = [b"".join(pieces)] + parts[1:-1]
        pieces = [parts[-1]]
        for line in lines:
            value = _usage_from_line(line)
            if value is not None:
                return value
    return _usage_from_line(b"".join(pieces))


def _compaction_floor_since(transcript_path, since, size):
    """A compaction between two prompts, from the bytes appended since the last one.

    `since`/`size`: the transcript's byte size at the previous prompt and now. None when no
    non-sidechain compact_boundary was appended (or either size is unusable); else the first
    usage after the NEWEST such boundary (the new floor), or COMPACTED when none follows.

    The whole appended region is searched as raw bytes, newest chunk first (a heavy turn writes
    megabytes after a mid-turn compaction: round 3, F1); a line is split and parsed only around
    a hit. The search starts _SCAN_BACK bytes before `since` so a record that was still being
    written at the previous prompt is found once complete; a hit whose line ended by `since`
    is an old boundary and ends the search. Past _SCAN_CAP appended bytes only the largest
    tail window is searched."""
    if (not isinstance(since, int) or isinstance(since, bool) or since < 0
            or not isinstance(size, int) or size <= since):
        return None
    if size - since > _SCAN_CAP:
        start = max(since, size - _TAIL_WINDOWS[-1])
    else:
        start = max(0, since - _SCAN_BACK)
    try:
        with Path(transcript_path).open("rb") as f:
            after = None  # offset just past the newest real boundary's line
            rejected = size  # matches at or after this offset sit on a line already rejected
            hi = size
            while hi > start and after is None:
                lo = max(start, hi - _SCAN_CHUNK)
                f.seek(lo)
                data = f.read(min(size, hi + _SCAN_OVERLAP) - lo)
                for match in reversed(list(_BOUNDARY.finditer(data))):
                    pos = lo + match.start()
                    if pos >= hi or pos >= rejected:
                        continue  # a newer chunk's, or on a line already rejected
                    line_start, line_end = _line_span(f, pos, size)
                    if line_end <= since:
                        return None  # complete before the previous prompt: so is all that is older
                    f.seek(line_start)
                    if _is_boundary_line(f.read(line_end - line_start)):
                        after = line_end
                        break
                    rejected = line_start
                hi = lo
            if after is None:
                return None
            value = _usage_after(f, after, size)
    except Exception:
        return None
    return COMPACTED if value is None else value


def _last_assistant_model(transcript_path):
    """The newest non-sidechain assistant record's `message.model`, or None.

    The same tail windows as _last_context_tokens; synthetic records (model
    "<synthetic>", e.g. an API-error stub) are skipped."""
    try:
        with Path(transcript_path).open("rb") as f:
            size = os.fstat(f.fileno()).st_size
            tried = 0
            for window in _TAIL_WINDOWS:
                chunk_size = min(size, window)
                if chunk_size <= tried:
                    break
                f.seek(size - chunk_size)
                data = f.read(chunk_size)
                tried = chunk_size
                lines = data.split(b"\n")
                if chunk_size < size:
                    lines = lines[1:]
                for line in reversed(lines):
                    if b'"model"' not in line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(obj, dict) or obj.get("isSidechain"):
                        continue
                    message = obj.get("message")
                    model = message.get("model") if isinstance(message, dict) else None
                    if isinstance(model, str) and model and not model.startswith("<"):
                        return model
                if chunk_size >= size:
                    break
    except Exception:
        return None
    return None


def _guard_level():
    """`level` of the quota guard's state file ("" when absent or unreadable)."""
    try:
        data = json.loads(QUOTA_GUARD_PATH.read_text())
        level = data.get("level") if isinstance(data, dict) else None
    except Exception:
        return ""
    return level if isinstance(level, str) else ""


def _successor_target(model, guard_level):
    """(provider/model spec, why) when this session should hand off to another model, else None.

    Fable (any claude-fable-* id, a "[1m]" style suffix ignored) means Opus 5.5.  A quota guard
    saying tight or critical moves a session only DOWN, and only from a model known to be above the
    target: tight (Sonnet 5.5) from Fable or Opus, critical (Opus 5.5) from Fable.  An unknown model
    (None: the transcript tail had no assistant record), Haiku, or a session already on the target
    or below gets None, i.e. a plain /new, never a same-model or upward successor (adversary
    2026-10-23, observation 8 and round 2 L4; the handoff skill's Step 9 uses the same rule)."""
    base = (model or "").split("[", 1)[0]
    fable = base.startswith("claude-fable")
    if guard_level == "tight":
        if fable or base.startswith("claude-opus"):
            return SUCCESSOR_SONNET, "the quota guard says tight"
        return None
    if guard_level == "critical":
        if fable:
            return SUCCESSOR_OPUS, "the quota guard says critical"
        return None
    if fable:
        return SUCCESSOR_OPUS, "this session runs on Fable"
    return None


def _first_context_tokens(transcript_path):
    """The session's first usage block (its starting context), or None."""
    try:
        with Path(transcript_path).open("rb") as f:
            data = f.read(_HEAD_WINDOW)
    except Exception:
        return None
    for line in data.split(b"\n"):
        value = _usage_from_line(line)
        if value is not None:
            return value
    return None


def _level(total, growth):
    """0 = quiet, 1 = early, 2+ = ask (one more per REPEAT_EVERY)."""
    steps = []
    if growth >= ASK_GROWTH:
        steps.append((growth - ASK_GROWTH) // REPEAT_EVERY)
    if total >= ASK_TOTAL:
        steps.append((total - ASK_TOTAL) // REPEAT_EVERY)
    if steps:
        return 2 + max(steps)
    return 1 if growth >= EARLY_GROWTH else 0


_COST_NOTE = (
    "For the measured Claude sessions, compaction re-wrote ~72k tokens at the 1-hour cache's "
    "2x rate plus a summariser call and left ~104k behind, so it paid back only "
    "after dozens of further requests on the same work. Those are Claude measurements, "
    "not thresholds or prices for OpenCode Go; use its native context guard."
)


def _early_message(total, growth):
    return (
        f"Context check: {total:,} tokens in context (+{growth:,} since this "
        "session started or last compacted). From now on, send discrete, "
        "separable work through /bigteam (Agent sub-agents for small lookups) "
        "so its tokens stay out of this session, and don't read large files or "
        "logs inline. Do not compact yet solely for this early warning. "
        "Cached input is billed on every request; its price and allowance debit "
        "depend on the provider and model. "
        + _COST_NOTE
    )


def _which(name):
    # The same PATH bin/self-slash searches: it exports PATH="/opt/homebrew/bin:$PATH" before
    # choosing a host (self-slash line ~87), and a hook's inherited PATH may lack that prefix
    # (Codex on PR 19, 2026-10-20).  Tests replace this; the hook never spawns orca itself.
    return shutil.which(name, path="/opt/homebrew/bin:" + os.environ.get("PATH", os.defpath))


def _self_slash_host():
    # The same host selection as bin/self-slash, in its order (2026-10-20, Codex on PR 19):
    # a herdr pane only with HERDR_ENV=1 (a stale HERDR_PANE_ID alone is not one), an Orca
    # terminal only when the orca CLI is on PATH, else a Paseo agent (2026-10-19: `paseo
    # wait` then `paseo send` of the root-only built-ins).  None: self-slash would refuse.
    if os.environ.get("HERDR_ENV") == "1" and os.environ.get("HERDR_PANE_ID"):
        return "herdr"
    if os.environ.get("ORCA_TERMINAL_HANDLE") and _which("orca"):
        return "orca"
    if os.environ.get("PASEO_AGENT_ID") and _paseo_cli():
        return "paseo"
    return None


def _paseo_cli():
    # self-slash (lines ~141-142): PASEO_CLI, else paseo on PATH, and it must be executable;
    # otherwise it exits 3 and the operator types the command (Codex on PR 19, 2026-10-20).
    cli = os.environ.get("PASEO_CLI") or _which("paseo")
    return bool(cli) and os.access(cli, os.X_OK)


def _can_self_slash():
    return _self_slash_host() is not None


def _paseo_finish_note():
    # On Paseo /quit is not a command (it reaches Claude as plain text), so ending a
    # session there is --finish, which archives the agent once idle (2026-10-20).
    # Archiving is the operator's choice (loose Rule 4), never something the model
    # decides alone.
    if _self_slash_host() != "paseo":
        return ""
    return (" On Paseo, a finished task with nothing to continue: offer the `loose` Rule 4 "
            "choices (handoff and continue, or finish and archive, which is "
            "~/src/djbclark-ade/bin/self-slash --finish as the last action; it archives "
            "this agent once idle, and /quit does nothing there) rather than archiving "
            "yourself.")


def _step9_text(successor):
    """What the handoff's Step 9 runs: the successor form (Paseo only) or /new."""
    if successor and _self_slash_host() == "paseo":
        spec, why = successor
        return (f"~/src/djbclark-ade/bin/self-slash --finish --successor {spec} --thinking high "
                f"({why}: it starts a NEW agent on {spec.split('/', 1)[1]} that runs /baton, "
                "then archives this one; the pre-handoff transcript survives only in the "
                "handoff document and the archived agent's log)")
    return "~/src/djbclark-ade/bin/self-slash \"/new\" ONCE and queues /baton into the fresh session"


def _successor_note(successor):
    """Where the successor form is unavailable (herdr, Orca, no host): relaunch by hand."""
    if not successor or _self_slash_host() == "paseo":
        return ""
    spec, why = successor
    return (f" Note: {why}; self-slash --successor needs Paseo, so after the handoff tell the "
            f"operator to relaunch `claude --model {spec.split('/', 1)[1]}` in this pane.")


def _boundary_message(total, successor=None):
    # self-slash refuses outside herdr, Orca and Paseo: there the operator types /new.
    if _can_self_slash():
        new = (f"(its Step 9 runs {_step9_text(successor)})" if successor and _self_slash_host() == "paseo"
               else "(its Step 9 runs ~/src/djbclark-ade/bin/self-slash \"/new\" and queues /baton)")
    else:
        new = "and then tell the operator /new is ready"
    return (
        f"Context is {total:,}. At the next task completion, if the following "
        f"work is not a direct continuation, run the `handoff` skill "
        f"{new} instead of /compact: a fresh session re-writes ~46k, a "
        "compaction re-writes ~72k plus a summariser call and leaves ~104k "
        "behind. Do not compact mid-task."
        + (" Do not run /new yourself as well: self-slash refuses the second one. Only the "
           "top-level session does this; a sub-agent or dispatched slice treats a handoff "
           "as document-only." if _can_self_slash() else "")
        + _paseo_finish_note()
        + _successor_note(successor)
    )


def _midtask_note(total, in_context):
    """Say how many tool rounds fit before the wall.
    The hook runs on prompt submit and between tool rounds (PostToolUse, rate-limited), so the
    cadence sentence is the same for both events (2026-10-28: "at the next natural boundary"
    was never reached in the 14-20k tokens that were left).
    `in_context` names the caller's way to continue in-context: each message branch has its own."""
    left = max(0, AUTO_COMPACT_WALL - total)
    rounds = (left - HANDOFF_RESERVE) // TOOL_ROUND_TOKENS
    cadence = (f"this reminder runs when a prompt is submitted and between tool rounds "
               f"(at most every {POST_TOOL_CHECK_SECONDS} s). ")
    lead = (
        f"About {left:,} tokens remain before Claude Code compacts this session at "
        f"{AUTO_COMPACT_WALL:,}; " + cadence
        + "If this turn is mid-task: finish the current edit "
        "(never leave one half-written), then run the handoff "
    )
    alternative = f" (or, if the work must continue in-context, {in_context})."
    if rounds > 0:
        return lead + (
            f"before the next tool round beyond {rounds} more "
            f"(about {TOOL_ROUND_TOKENS // 1000}k tokens each; a large file or log read "
            "counts double)" + alternative
        )
    return lead + "right after it, with no further tool rounds" + alternative


def _ask_message(total, growth, repeat, successor=None):
    lead = "Context is still growing" if repeat else "Context is large"
    if _can_self_slash():
        # A herdr pane, Orca terminal or Paseo agent can queue its own /new or /compact
        # (standing operator ruling 2026-10-09, memory/feedback_self_compact.md).
        return (
            f"{lead}: {total:,} tokens (+{growth:,} since the session started "
            "or last compacted). Handle it yourself, without asking (operator "
            "2026-10-15): first choice when the current task is finished (a "
            "task done, never mid-edit or with a sub-agent result unread), same "
            "topic or not: run the `handoff` "
            "skill (it writes the Tier 2 document; its Step 9 runs "
            + _step9_text(successor)
            + ", so do not run /new yourself as well) and end the turn "
            "(a fresh session re-writes ~46k). Only the top-level session does this; "
            "a sub-agent or dispatched slice treats a handoff as document-only. "
            "Only if the work must continue "
            "in-context: save what the next turn needs, run self-slash "
            "\"/compact <focus>\" ONCE and end the turn. Only if self-slash "
            "refuses (a draft on the input line) ask the operator for /new or "
            "/compact."
            + _paseo_finish_note() + _successor_note(successor) + " "
            + _midtask_note(total, "the /compact path above") + " "
            + _COST_NOTE
        )
    # Bare branch (no herdr, Orca or Paseo host; every ACP slice lands here too, since acp-run
    # scrubs PASEO_AGENT_ID): it has no self-slash path, and says nothing of a handoff being
    # document-only for a dispatched slice (known limit, round 2 F5: the hook cannot tell a
    # slice from the top-level session; the handoff skill itself states the rule).
    return (
        f"{lead}: {total:,} tokens (+{growth:,} since the session started or "
        "last compacted). Do not ask: Claude Code compacts this session by "
        f"itself at about {AUTO_COMPACT_WALL:,} tokens "
        f"(autoCompactWindow {AUTO_COMPACT_WINDOW:,} in ~/.claude/settings.json "
        "less its buffer; the PreCompact hook writes the Tier 1 checkpoint "
        "first). Until then start no new heavy work inline: send it through "
        "/bigteam or a minimum-spec sub-agent. When the current task is "
        "finished, same topic or not, run the `handoff` skill (Tier 2 "
        "document) and tell the operator /new is ready (a fresh session "
        "re-writes ~46k); keep going in-context only when the work must "
        "continue. "
        + _midtask_note(total, "let the auto-compaction take it") + " "
        + _COST_NOTE
    )


def _session_successor(transcript_path):
    return _successor_target(_last_assistant_model(transcript_path), _guard_level())


def _load_state():
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def _save_state(state):
    tmp = None
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=STATE_PATH.name + ".", suffix=".tmp", dir=STATE_PATH.parent)
        tmp = Path(name)
        with os.fdopen(fd, "w") as stream:
            stream.write(json.dumps(state))
        os.replace(tmp, STATE_PATH)
    except Exception:
        pass
    finally:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def _sweep_state_temps():
    """Reap day-old interrupted saves; inspect at most 128 entries under the lock."""
    cutoff = time.time() - 24 * 60 * 60
    try:
        with os.scandir(STATE_PATH.parent) as entries:
            for entry in islice(entries, 128):
                if not (entry.name.startswith(STATE_PATH.name + ".") and entry.name.endswith(".tmp")):
                    continue
                try:
                    if entry.is_file(follow_symlinks=False) and entry.stat(follow_symlinks=False).st_mtime < cutoff:
                        os.unlink(entry.path)
                except OSError:
                    pass
    except OSError:
        pass


@contextmanager
def _state_lock():
    """Serialize the whole read/modify/write; fail open after at most 200 ms.

    Lock a stable sibling inode, since saving replaces the state inode. The
    hook's two-second alarm also covers acquisition and the protected work.
    Without fcntl, or on contention/errors, atomic saves still prevent corruption
    but a concurrent update may be lost.
    """
    fd = None
    try:
        if fcntl is not None:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(STATE_PATH.with_suffix(".lock"),
                         os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            deadline = time.monotonic() + 0.2
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    _sweep_state_temps()
                    break
                except BlockingIOError:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    time.sleep(min(0.01, remaining))
    except (OSError, AttributeError):
        pass
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)  # also releases an acquired flock


def _send_ping(message, cwd):
    """Fire and forget: the ping must never hold the prompt."""
    try:
        import subprocess
        subprocess.Popen(
            [str(PING_BIN), message],
            cwd=cwd if cwd and os.path.isdir(cwd) else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


def _log_nudge(session_id, event, level, total, growth, kind):
    """Best-effort bounded history, one O_APPEND write per emitted note.

    Rotation atomically replaces the single backup. Concurrent sessions may
    cross the approximate size cap before rotating; no blocking lock or fsync
    is used on the prompt path. Compaction never touches this log.
    """
    try:
        line = (json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id, "event": event, "level": level,
            "total": total, "growth": growth, "kind": kind,
        }) + "\n").encode("utf-8")
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            if LOG_PATH.stat().st_size + len(line) > LOG_MAX_BYTES:
                os.replace(LOG_PATH, Path(str(LOG_PATH) + ".1"))
        except FileNotFoundError:
            pass
        fd = os.open(LOG_PATH, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except Exception:
        pass


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return
    if not isinstance(data, dict):
        return

    session_id = data.get("session_id") or "unknown"
    event = data.get("hook_event_name", "UserPromptSubmit")
    if event not in ("UserPromptSubmit", "PostToolUse"):
        return
    # A sub-agent's tool calls fire the same PostToolUse hooks with the PARENT's session_id and
    # transcript_path plus an agent_id (absent on the main thread). Its additionalContext would
    # reach the sub-agent, and stamping the parent's level, boundary and throttle would spend the
    # top-level session's one-shot notes there (PR 127 adversary r1, B1): leave it to the main thread.
    if event == "PostToolUse" and data.get("agent_id"):
        return
    transcript_path = data.get("transcript_path") or ""
    if not transcript_path:
        return

    with _state_lock():
        _check_state(data, event, session_id, transcript_path)


def _check_state(data, event, session_id, transcript_path):
    state = _load_state()
    if not isinstance(state, dict):
        state = {}
    session_state = state.get(session_id)
    if not isinstance(session_state, dict):
        session_state = {}

    if event == "PostToolUse":
        now = time.time()
        last_check = session_state.get("last_check")
        # Wall time persists across hook processes/reboots. A clock rollback
        # must not suppress checks until the old clock catches up.
        if isinstance(last_check, (int, float)) and 0 <= now - last_check < POST_TOOL_CHECK_SECONDS:
            return
        session_state["last_check"] = now
        state[session_id] = session_state
        _save_state(state)  # throttle even an empty/unreadable transcript

    # Size first: records appended during the usage read are scanned next time.
    size = _file_size(transcript_path)
    total = _last_context_tokens(transcript_path)
    prev_size = session_state.get("size")
    if total is not None:
        session_state["size"] = size
    if total is None:
        return

    if total == COMPACTED:
        # Compacted, no request since: the next measured size is the new floor.
        session_state.update(baseline=None, level=0, paged=False, last=None, peak=None)
        state[session_id] = session_state
        _save_state(state)
        return

    baseline = session_state.get("baseline")
    # The highest size seen since the last reset: a run of small dips (each < 25% of the
    # previous prompt) that sums to a real shrink must still read as one.
    seen = [v for v in (session_state.get("last"), session_state.get("peak")) if isinstance(v, int)]
    peak = max(seen) if seen else None
    floor = _compaction_floor_since(transcript_path, prev_size, size)
    if floor is not None:
        # An auto-compaction mid-turn: more tool rounds followed it, so no boundary is the
        # newest record now and the regrowth may hide it from the shrink test (round 2, F1).
        baseline = floor if floor != COMPACTED else total
        session_state.update(level=0, paged=False)
        peak = None
    elif peak is not None and total < peak * SHRINK_RATIO:
        baseline = total  # compacted between two prompts: new floor
        session_state["level"] = 0
        peak = None
    if not isinstance(baseline, int):
        if "level" in session_state:
            baseline = total  # first size after a compaction
        else:
            baseline = _first_context_tokens(transcript_path) or total
    session_state["baseline"] = baseline
    session_state["last"] = total
    session_state["peak"] = max(total, peak or 0)
    growth = max(0, total - baseline)

    level = _level(total, growth)
    fired = session_state.get("level", 0)
    if not isinstance(fired, int):
        fired = 0
    # Old or corrupt state (a level the session cannot have reached) must not stick (round 2,
    # F4): clamp to what the stored peak computes (peak resets together with the level). The
    # dipped total is no bound: a floor-20k session fired level 2 at 160k, dips to 125k, and
    # must not print it again at 161k (round 3, F2).
    peak_total = session_state["peak"]
    fired = min(fired, _level(peak_total, peak_total))

    messages = []
    if level > fired:
        if level == 1:
            messages.append((_early_message(total, growth), "early"))
        else:
            messages.append((_ask_message(total, growth, repeat=fired >= 2,
                                         successor=_session_successor(transcript_path)), "ask"))
    # Never lower the stored level on a dip: a compaction or a real shrink already reset it
    # above, and a smaller dip must not let the next climb past the tier reprint the message.
    session_state["level"] = max(level, fired)

    # Once per session id, not per compaction: a /new starts a new id.
    if total >= BOUNDARY_TOTAL and not session_state.get("boundary"):
        session_state["boundary"] = True
        messages.append((_boundary_message(total, successor=_session_successor(transcript_path)), "boundary"))

    if messages:
        message = "\n".join(text for text, _ in messages)
        if event == "PostToolUse":
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PostToolUse", "additionalContext": message,
            }}), flush=True)
        else:
            print(message, flush=True)
        for _, kind in messages:
            _log_nudge(session_id, event, level, total, growth, kind)
            if kind == "ask":
                # PR 108 embeds the mid-task note in every hard-tier message.
                _log_nudge(session_id, event, level, total, growth, "midtask")

    if growth >= PAGE_GROWTH or total >= PAGE_TOTAL:
        if not session_state.get("paged"):
            session_state["paged"] = True
            repo = os.path.basename((data.get("cwd") or "").rstrip("/")) or "claude"
            _send_ping(
                f"{repo}: Claude Code context at ~{total // 1000}k "
                f"(+{growth // 1000}k since start or last compact); agent will "
                "/handoff then /new, or /compact, at its next boundary.",
                data.get("cwd"),
            )
    elif level < 2:
        session_state["paged"] = False  # compacted: page again on regrowth

    state[session_id] = session_state
    _save_state(state)


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGALRM, _on_deadline)
        signal.alarm(DEADLINE_SECONDS)
    except Exception:
        pass  # no SIGALRM (non-POSIX): run without the internal deadline
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
