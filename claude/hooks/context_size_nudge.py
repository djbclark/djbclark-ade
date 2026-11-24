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
  sub-agent or in-process teammate (agent_id set) are ignored; the mid-task note has one
  cadence sentence for both events (the prompt-only text became false once PostToolUse ran), built from
  POST_TOOL_CHECK_SECONDS instead of a hard-coded 20 s.
- 2026-08-03: built after a session grew to 670k+ tokens unnoticed.
- 2026-08-23: reworded to "never suggest a wrap-up" (continuous operation).
- 2026-10-05: fail-fast tail read + 2 s internal deadline (load 223 killed it).
- 2026-10-08 (operator ruling, supersedes 2026-08-23): prompt earlier and
  harder, and DO recommend /compact, or /self-handoff (formerly /handoff) then /new. The old single
  150k nudge fired too late. Separable work goes to /fan-out by default so it
  never lands in this context. memory/feedback_context_prompts_early.md.
- 2026-10-10: stop the compaction loop. Measured over 85 compactions in two
  days: a /compact took context from ~187k to ~104k (not the ~33k Claude Code
  reports as postTokens: tool listings, project context and re-attached files
  come back), so the old 150k / +70k tiers re-fired after ~40 requests, and
  sessions compacted every ~25 min (one 24 times in a day). Each compaction
  re-writes ~70k tokens at the 1-hour cache's 2x rate plus the summary, ~150-
  180k base-input-equivalent; with cache reads at 0.025x (Fable 5.2) / 0.05x
  (Opus/Sonnet 5.5) that pays back only after ~45-85 requests, so most were a
  net loss. Growth now counts from the floor after the latest compaction, the
  compact tier is +200k (or 400k total), and the early tier no longer
  recommends /compact. memory/feedback_self_compact.md.
- 2026-10-18 (Fable cache-cost review, operator-approved): autoCompactWindow
  400k -> 300k (simulated -1.6% cost; Claude Code compacts at the window less
  its ~33k buffer, so ~267k), ASK_TOTAL follows it, PAGE_TOTAL 500k -> 400k.
  A fresh session (/new) re-writes ~46k; a compaction re-writes ~72k plus a
  summariser call and leaves ~104k behind, so at a finished task the first
  choice is now the `self-handoff` skill (formerly `handoff`) + /new, and /compact only when the work
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
- 2026-11-21 (operator task): a lead on claude-opus-5-5 handed itself off at ~150k with the wall
  at 267k. The fixed BOUNDARY_TOTAL 120k note ("At the next task completion ... run handoff
  Step 9 yourself", ruling 2026-11-14) read as an instruction whatever room was left, and the
  growth trigger ASK_GROWTH 140k fired the hard tier at ~175k for low floors. Now the wall is
  computed per session (compaction_wall: min(configured window, the model's window) less
  AUTO_COMPACT_BUFFER; CLAUDE_CODE_AUTO_COMPACT_WINDOW, `modelSettings[model]`, then
  `autoCompactWindow`; unreadable/unknown: today's 267k, bin/context-watch imports the same
  function) and every tier derives from it: hard = wall - ASK_HEADROOM (50k), boundary =
  wall - BOUNDARY_HEADROOM (80k, never below BOUNDARY_FLOOR 120k, never above the hard tier),
  paging max(400k, hard tier); the hard tier never below ASK_FLOOR 80k (a small configured
  window would loop handoffs). On the 267k wall that is boundary 187k (was 120k), hard 217k
  (unchanged). 80k is about ten tool rounds ahead of the hard tier's own 50k; there a handoff
  (a fresh session re-writes ~46k) beats the compaction that is certain to follow (~72k
  re-written plus a summariser call, ~104k left behind), and before it a handoff only throws
  away a cache that still has room to pay back; 120k stays the floor because compacting at
  <=200k simulated a net loss (2026-10-18). ASK_GROWTH is gone (only the total fires the
  hard tier). The messages print the computed wall and tokens left, keep the 2026-11-14
  ruling (hand off yourself, never a /new for the operator) and say a finished task alone
  is no reason to hand off below this tier. The EARLY tier is unchanged.
  Adversary L1 (PR 862): the hard tier never sits below ASK_FLOOR 80k, and a wall at or under
  it has no handoff tiers (NO_TIER), so a small configured window cannot make every fresh
  session hand itself off.
- 2026-11-24 (queue #98, PR 862 L2): for compaction windows of ~114k-163k (wall 81k-130k),
  the hard and boundary tiers sit at ASK_FLOOR (80k), only ~9k above the 71k median fresh
  session, so a successor starting above 80k immediately re-handed off on turn 1. Now a
  floor-clamped tier (ask_total <= ASK_FLOOR) requires at least ASK_MIN_GROWTH (16k, ~2 tool
  rounds) of growth since the baseline before firing hard or boundary nudges; larger windows
  (including the live 300k window) are unchanged.
- 2026-11-24 (e0d271f5 harness failure): on a 267k wall, once level 2 fired at 217k,
  REPEAT_EVERY (+100k -> 317k) and PAGE_TOTAL_MIN (400k) / PAGE_GROWTH_MIN (+300k) all sat
  past the 267k wall, so no further nudge or hermes-ping fired up to 265k, and auto-compaction
  reset level=0 and paged=False, erasing the missed hard handoff. Now: (1) while still at or
  above the hard tier (level >= 2 and fired >= 2), emit an escalating hard-handoff reminder
  (kind="ask_repeat") on UserPromptSubmit and rate-limited every HARD_REPEAT_SECONDS (60 s) on
  PostToolUse; (2) fire hermes-ping once per climb when level >= 2 fires (keeping PAGE_* as
  fallback for huge windows); (3) persist `handoff_due` across compaction whenever the session
  had reached fired >= 2 (or already carried `handoff_due`), emit `post_compact_handoff_due`
  on post-compaction turns (rate-limited on PostToolUse, emitted on UserPromptSubmit), and send
  one hermes-ping for that compaction.

Measure: input + cache_creation + cache_read tokens of the newest usage block,
i.e. the real context size (cache_read alone reads 0 after a cache miss).
The early tier counts GROWTH since the floor (the hard and boundary tiers count the total): the first usage block of the session, or of
the conversation after its latest compaction (a compact_boundary record as the newest
record, a non-sidechain boundary appended since the previous prompt (the transcript's byte
size is stored per session: an auto-compaction mid-turn is followed by more tool rounds, so
the boundary is no longer the newest record), or a drop below SHRINK_RATIO of the highest
size seen since the last reset). Baselines differ a lot (2026-10-28,
267 sessions: median 71k, range 0-164k; a compacted one ~104k).
The hard tier asks at the total ASK_HEADROOM (50k) under the session's auto-compaction wall (compaction_wall;
217k on the 267k fallback wall); a growth trigger no longer fires it (2026-11-21).

Levels: 1 = early (delegate from now on; no compaction yet);
2+ = handoff + /new at a finished task, /compact only to continue in-context
(auto-compaction), or, mid-turn, finish the
current edit and hand off within a few tool rounds (_midtask_note); while still
at or above the hard tier (level >= 2, fired >= 2), repeat an escalating reminder
(kind="ask_repeat") on UserPromptSubmit and every HARD_REPEAT_SECONDS on PostToolUse
(plus the full level-climb ask every REPEAT_EVERY of further growth). A hermes-ping
fires once per climb at level >= 2 (with PAGE_TOTAL_MIN / PAGE_GROWTH_MIN kept as a
fallback for huge windows). A compaction resets the floor and the level, so the hard
tier fires again at the ask total on regrowth, and if the session had already reached
level >= 2 before compacting, persists `handoff_due` across the reset so post-compaction
turns keep directing `/self-handoff` (kind="post_compact_handoff_due") plus one
compaction hermes-ping until a fresh session_id starts.
Separately, once per session at the boundary tier (wall - BOUNDARY_HEADROOM, 187k on a 267k wall):
prefer handoff + /new over /compact at the next task completion.

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
import signal
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from typing import NamedTuple

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
HARD_REPEAT_SECONDS = 60  # rate-limit PostToolUse repeats of hard-tier / post-compact handoff nudges
# djbclark, 2026-10-23: lead sessions run on Opus 5.5 high, not Fable (a Fable lead burned ~30% of
# a week's Claude quota); since 2026-11-07 `[lead].fable_lead = true` in config/routing.toml allows a Fable lead.  The quota guard's tight/critical downshift went with the guard (2026-11-07,
# slim-down E7): pausing at a quota limit is the session-guard and usage-auto-resume plugins' job.
FABLE_MODEL = "claude-fable-5-2"
SUCCESSOR_OPUS = "claude/claude-opus-5-5"

# Compaction is not free (see History, 2026-10-10): only compact once the
# context has grown enough above the post-compaction floor to pay it back.
EARLY_GROWTH = 32_000   # 2026-10-25: delegate earlier; this alone never compacts
# ~/.claude/settings.json "autoCompactWindow" (set 2026-10-15, 300k since
# 2026-10-18): Claude Code compacts by itself near this size, on every host, so
# the level-2 note no longer asks the operator. The real
# trigger is the window less the "Autocompact buffer" /context shows (~33k):
# AUTO_COMPACT_WALL = 267k (measured 2026-10-23..28: 72 auto compactions,
# preTokens 266k-285k, median ~268k).
AUTO_COMPACT_WINDOW = 300_000  # the FALLBACK window: used only when nothing better is known (below)
AUTO_COMPACT_BUFFER = 33_000
AUTO_COMPACT_WALL = AUTO_COMPACT_WINDOW - AUTO_COMPACT_BUFFER  # the fallback wall, 267k
# 2026-11-21: the real wall is computed per session (compaction_wall): min(configured window, the
# model's own window) less AUTO_COMPACT_BUFFER. Settings are read once per run from SETTINGS_PATH.
SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
DEFAULT_MODEL_WINDOW = 200_000
LONG_MODEL_WINDOW = 1_000_000
MAX_WINDOW = 10_000_000  # a configured window above this is taken as junk (unset)
# Level 2 (the hard tier) must fire with headroom before that wall: the hook runs at prompt
# submit and, rate-limited, between tool rounds, and the agent still needs several tool rounds
# plus the handoff itself.
# 2026-10-28: ASK_GROWTH 200k fired at floor+200k = 235-271k (median floor 71k: past the
# wall, never), leaving 0-20k, and ASK_TOTAL 300k sat above the wall and never fired.
ASK_HEADROOM = 50_000
# A fresh session already holds ~46-71k (median floor 71k, 2026-10-28), so a hard tier below
# ASK_FLOOR would fire at once and loop self-handoffs on a small configured window (adversary L1,
# PR 862). The hard and boundary tiers therefore never sit below ASK_FLOOR; a wall at or under it
# has no handoff tiers at all (Claude Code compacts first). When a small window (~114k-163k, wall
# 81k-130k) clamps ask_total to ASK_FLOOR, also require ASK_MIN_GROWTH since the baseline so a
# successor starting above 80k does not immediately re-hand-off on turn 1 (queue #98).
ASK_FLOOR = 80_000
NO_TIER = 10**15  # a tier that never fires (_tiers: a wall at or under ASK_FLOOR)
# The boundary tier ("hand off at the next task completion") fires only near the limit
# (2026-11-21: a fixed 120k made a lead on a 267k wall hand itself off at ~150k with 117k left).
# 80k = about ten tool rounds (TOOL_ROUND_TOKENS) before the hard tier's own 50k: the handoff
# (a fresh session re-writes ~46k) is then cheaper than the compaction that is certain to follow
# (~72k re-written plus a summariser call, ~104k left behind), and earlier than this a handoff
# only discards a cache that still has room to pay back. Never below BOUNDARY_FLOOR: compacting
# at <=200k simulated a net loss (History 2026-10-18), so a small wall keeps the old 120k.
BOUNDARY_HEADROOM = 80_000
BOUNDARY_FLOOR = 120_000
TOOL_ROUND_TOKENS = 8_000    # a tool round costs 3-8k; a big file or log read costs more
ASK_MIN_GROWTH = 2 * TOOL_ROUND_TOKENS  # 16k (~2 tool rounds) required on floor-clamped tiers
HANDOFF_RESERVE = 15_000     # what the handoff skill itself needs before the wall
REPEAT_EVERY = 100_000  # level 3, 4, ...: full level-climb ask again per this much more
# 2026-11-24: hard tier (level >= 2) now triggers a once-per-climb hermes-ping on every wall;
# PAGE_GROWTH_MIN / PAGE_TOTAL_MIN remain as the fallback guard for huge windows.
PAGE_GROWTH_MIN = 300_000
PAGE_TOTAL_MIN = 400_000
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


def _loads_or_none(line):
    try:
        return json.loads(line)
    except Exception:
        return None


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
                    obj = _loads_or_none(line)
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


def _routing_policy_path():
    """config/ade.toml or routing.toml: ROUTING_POLICY (as bin/route_agent.py), else this checkout's, else ~/src/djbclark-ade's."""
    env = os.environ.get("ROUTING_POLICY")
    if env:
        return Path(env)
    # W16 (2026-11-12): a unified config/ade.toml is the repo base and wins over the legacy file in the same
    # checkout (`[lead]` sits at its root, so the same parse applies); local.toml overlays are not read here.
    for base in (Path(__file__).resolve().parents[2] / "config", Path.home() / "src" / "djbclark-ade" / "config"):
        for name in ("ade.toml", "routing.toml"):
            if (base / name).is_file():
                return base / name
    return None


def _fable_lead_allowed():
    """`[lead].fable_lead` of config/routing.toml (operator 2026-11-07), False when absent or unreadable: then the
    2026-10-23 "never a Fable lead" rule holds.  tomllib where it exists, else a line scan of the [lead] table (the hook
    may run under a Python older than 3.11)."""
    try:
        path = _routing_policy_path()
        if path is None:
            return False
        text = path.read_text()
        try:
            import tomllib
        except ImportError:
            section = None
            for line in text.splitlines():
                stripped = line.split("#", 1)[0].strip()
                if stripped.startswith("["):
                    section = stripped
                elif section == "[lead]" and re.fullmatch(r"fable_lead\s*=\s*true", stripped):
                    return True
            return False
        return (tomllib.loads(text).get("lead") or {}).get("fable_lead", False) is True
    except Exception:
        return False


def _successor_target(model):
    """(provider/model spec, why) when this session should hand off to another model, else None.

    Fable (any claude-fable-* id, a "[1m]" style suffix ignored) means Opus 5.5, unless `[lead].fable_lead` in
    config/routing.toml is true (operator 2026-11-07: Fable leads allowed for now).  An unknown model (None: the
    transcript tail had no assistant record) or any other model gets None, i.e. a plain /new, never a same-model or
    upward successor (adversary 2026-10-23, observation 8 and round 2 L4)."""
    base = (model or "").split("[", 1)[0]
    if base.startswith("claude-fable") and not _fable_lead_allowed():
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


def read_settings():
    """~/.claude/settings.json as a dict ({} when missing, unreadable or not an object)."""
    try:
        data = json.loads(SETTINGS_PATH.read_text())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _window(value):
    """A usable window from a setting: a whole number above the buffer and at most MAX_WINDOW (`"auto"`, strings,
    bools, fractions, junk, absurd sizes: None). A float such as 300000.0 counts when integral."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    ok = (isinstance(value, int) and not isinstance(value, bool)
          and AUTO_COMPACT_BUFFER < value <= MAX_WINDOW)
    return value if ok else None


def model_window(model):
    """The model's own context window when the id says so: 1M for `[1m]`, 200k for Haiku; None when unknown."""
    name = (model or "").lower()
    if "[1m]" in name:
        return LONG_MODEL_WINDOW
    return DEFAULT_MODEL_WINDOW if "haiku" in name else None


def compaction_wall(settings=None, model=None):
    """Tokens at which Claude Code auto-compacts this session: its window minus AUTO_COMPACT_BUFFER.

    Window = min(the configured window, the model's window). Configured: CLAUDE_CODE_AUTO_COMPACT_WINDOW of this
    process (the hook is a child of the session, so it is the session's own), else settings
    `modelSettings[<model>].autoCompactWindow`, else `autoCompactWindow`. With none configured: the model window
    when the id names one; else 1M when settings `model` carries `[1m]`; else the AUTO_COMPACT_WINDOW fallback
    (300k, today's 267k wall). Not knowable here, so not read: project-level settings, `--autocompact`, the
    `modelSettings` key format beyond an exact model id, the window of any model but Haiku/`[1m]` ids.
    `settings` None reads SETTINGS_PATH."""
    if settings is None:
        settings = read_settings()
    configured = None
    try:
        configured = _window(int(os.environ.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "")))
    except ValueError:
        pass
    per_model = settings.get("modelSettings")
    per_model = per_model.get(model) if isinstance(per_model, dict) and model else None
    if configured is None and isinstance(per_model, dict):
        configured = _window(per_model.get("autoCompactWindow"))
    if configured is None:
        configured = _window(settings.get("autoCompactWindow"))
    known = [w for w in (configured, model_window(model)) if w]
    if known:
        window = min(known)
    else:
        default_model = settings.get("model")
        long_model = isinstance(default_model, str) and "[1m]" in default_model.lower()
        window = LONG_MODEL_WINDOW if long_model else AUTO_COMPACT_WINDOW
    return window - AUTO_COMPACT_BUFFER


class Tiers(NamedTuple):
    wall: int
    ask_total: int
    boundary_total: int
    page_total: int
    page_growth: int


def _tiers(wall):
    """The Tiers for one compaction wall.

    ask = wall - ASK_HEADROOM, at least ASK_FLOOR (a wall at or under it has no handoff tiers:
    NO_TIER). boundary = wall - BOUNDARY_HEADROOM, never below BOUNDARY_FLOOR and never above ask.
    Paging scales: at least PAGE_TOTAL_MIN, and no earlier than the hard tier."""
    if wall <= ASK_FLOOR:  # below a fresh session's own size: Claude Code compacts first; no handoff tiers
        return Tiers(wall, NO_TIER, NO_TIER, NO_TIER, NO_TIER)
    ask = max(wall - ASK_HEADROOM, ASK_FLOOR)
    boundary = min(max(wall - BOUNDARY_HEADROOM, BOUNDARY_FLOOR), ask)
    page_total = max(PAGE_TOTAL_MIN, ask)
    return Tiers(wall, ask, boundary, page_total, max(PAGE_GROWTH_MIN, page_total - 100_000))


# What a session gets when its wall cannot be learned (today's 267k behaviour): the module constants.
_FALLBACK = _tiers(AUTO_COMPACT_WALL)
ASK_TOTAL = _FALLBACK.ask_total            # 217k
BOUNDARY_TOTAL = _FALLBACK.boundary_total  # 187k
PAGE_TOTAL = _FALLBACK.page_total          # 400k
PAGE_GROWTH = _FALLBACK.page_growth        # 300k


def _handoff_growth_ok(growth, tiers):
    """True when `growth` allows handoff tiers for `tiers`: always on normal walls, and at least
    ASK_MIN_GROWTH when a small window (~114k-163k) clamped ask_total to ASK_FLOOR (queue #98)."""
    return tiers.ask_total > ASK_FLOOR or growth >= ASK_MIN_GROWTH


def _level(total, growth, tiers=None):
    """0 = quiet, 1 = early, 2+ = ask (one more per REPEAT_EVERY of total beyond the hard tier).

    Only the TOTAL fires the hard tier (2026-11-21): a growth trigger (ASK_GROWTH 140k, from the
    floor) fired it at ~175k on a 267k wall, 90k before the wall had anything to say. On a small
    window clamped to ASK_FLOOR, require ASK_MIN_GROWTH so a >80k successor does not re-hand-off."""
    tiers = tiers or _FALLBACK
    if total >= tiers.ask_total and _handoff_growth_ok(growth, tiers):
        return 2 + (total - tiers.ask_total) // REPEAT_EVERY
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
        "separable work through /fan-out (Agent sub-agents for small lookups) "
        "so its tokens stay out of this session, and don't read large files or "
        "logs inline. Do not compact yet solely for this early warning. "
        "Cached input is billed on every request; its price and allowance debit "
        "depend on the provider and model. "
        + _COST_NOTE
    )


def _successor_note(successor):
    """The Fable-lead ruling (2026-10-23): a Fable session hands off to Opus."""
    if not successor:
        return ""
    spec, why = successor
    return (f" Note: {why}; after the handoff tell the operator to relaunch "
            f"`claude --model {spec.split('/', 1)[1]}` rather than continuing on this model.")


_SELF_HANDOFF = ("`~/src/djbclark-ade/bin/ade-self-session handoff`, an acknowledged self-handoff; "
                 "add `--thinking LEVEL` to pin the successor's thinking level")


def _boundary_message(total, successor=None, wall=None):
    wall = AUTO_COMPACT_WALL if wall is None else wall
    left = max(0, wall - total)
    return (
        f"Context is {total:,}: {left:,} tokens left before Claude Code compacts this session at "
        f"{wall:,}. This is context pressure near the real limit, not a reason of its own to hand "
        "off: below this tier a finished task alone is no reason to hand off or compact. "
        "At the next task completion, if the following "
        f"work is not a direct continuation and work remains, run self-handoff Step 9 yourself "
        f"({_SELF_HANDOFF}) instead of /compact, and never hand the operator a /new "
        "(operator ruling 2026-11-14: when handing off, do it yourself): a fresh session "
        "re-writes ~46k, a compaction re-writes ~72k plus a summariser call and leaves ~104k "
        "behind. Do not compact mid-task."
        + _successor_note(successor)
    )


def _midtask_note(total, in_context, wall=None):
    """Say how many tool rounds fit before the wall.
    The hook runs on prompt submit and between tool rounds (PostToolUse, rate-limited), so the
    cadence sentence is the same for both events (2026-10-28: "at the next natural boundary"
    was never reached in the 14-20k tokens that were left).
    `in_context` names the caller's way to continue in-context: each message branch has its own."""
    wall = AUTO_COMPACT_WALL if wall is None else wall
    left = max(0, wall - total)
    rounds = (left - HANDOFF_RESERVE) // TOOL_ROUND_TOKENS
    cadence = (f"this reminder runs when a prompt is submitted and between tool rounds "
               f"(at most every {POST_TOOL_CHECK_SECONDS} s). ")
    lead = (
        f"About {left:,} tokens remain before Claude Code compacts this session at "
        f"{wall:,}; " + cadence
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


def _ask_message(total, growth, repeat, successor=None, wall=None):
    wall = AUTO_COMPACT_WALL if wall is None else wall
    lead = "Context is still growing" if repeat else "Context is large"
    # bin/self-slash is gone (2026-11-06, slim-down E4): there is no path to queue a /compact for the session, so
    # auto-compaction takes it (a Claude session cannot run built-in slash commands itself).
    return (
        f"{lead}: {total:,} tokens (+{growth:,} since the session started or "
        "last compacted). Do not ask: Claude Code compacts this session by "
        f"itself at about {wall:,} tokens, {max(0, wall - total):,} from now "
        f"(this session's compaction window {wall + AUTO_COMPACT_BUFFER:,}, the lower of "
        "autoCompactWindow in ~/.claude/settings.json and the model's own window, "
        f"less its {AUTO_COMPACT_BUFFER:,} buffer; the PreCompact hook writes the Tier 1 checkpoint "
        "first). Until then start no new heavy work inline: send it through "
        "/fan-out or a minimum-spec sub-agent. When the current task is "
        "finished and more work remains, same topic or not, run self-handoff Step 9 yourself "
        f"(the `self-handoff` skill's Tier 2 document, then {_SELF_HANDOFF}) and never "
        "hand the operator a /new (operator ruling 2026-11-14); a fresh session "
        "re-writes ~46k. Keep going in-context only when the work must "
        "continue. "
        + _midtask_note(total, "let the auto-compaction take it", wall) + _successor_note(successor) + " "
        + _COST_NOTE
    )


def _hard_repeat_message(total, growth, repeat_num, successor=None, wall=None):
    wall = AUTO_COMPACT_WALL if wall is None else wall
    left = max(0, wall - total)
    urgency = "URGENT — imminent auto-compaction" if left <= HANDOFF_RESERVE else "Hard handoff reminder"
    return (
        f"{urgency} (#{repeat_num}): {total:,} / {wall:,} tokens "
        f"({left:,} left; +{growth:,} since baseline). "
        "Still at or above the hard handoff tier — stop starting inline work and "
        f"run `/self-handoff` Step 9 now ({_SELF_HANDOFF}) before auto-compaction hits. "
        + _midtask_note(total, "let the auto-compaction take it", wall)
        + _successor_note(successor)
    )


def _post_compact_handoff_message(total, handoff_due, successor=None, wall=None):
    wall = AUTO_COMPACT_WALL if wall is None else wall
    pre_peak = handoff_due.get("peak") if isinstance(handoff_due, dict) else None
    pre_wall = handoff_due.get("wall") if isinstance(handoff_due, dict) else None
    if not _is_int(pre_wall) or pre_wall <= 0:
        pre_wall = wall
    peak_clause = (
        f"after reaching ~{pre_peak:,} / {pre_wall:,} tokens"
        if _is_int(pre_peak) and pre_peak > 0
        else f"after reaching the hard handoff tier (wall {pre_wall:,})"
    )
    return (
        f"Post-compaction handoff due: this session auto-compacted {peak_clause} "
        f"and is now at {total:,} tokens in degraded compacted context. "
        "A hard handoff was already missed — do not keep working in this compacted session. "
        f"Run `/self-handoff` Step 9 now ({_SELF_HANDOFF}) and never hand the operator a /new "
        "(operator ruling 2026-11-14)."
        + _successor_note(successor)
    )


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _rate_limited(last_ts, now, interval):
    """True when `last_ts` is within `interval` seconds before `now`; wall-clock rollback is never throttled."""
    return isinstance(last_ts, (int, float)) and not isinstance(last_ts, bool) and 0 <= now - last_ts < interval


def _repo_name(data):
    return os.path.basename((data.get("cwd") or "").rstrip("/")) or "claude"


def _ping_compacted_overdue(data, handoff_due, total=None):
    repo = _repo_name(data)
    pre_peak = handoff_due.get("peak") if isinstance(handoff_due, dict) else None
    pre_wall = handoff_due.get("wall") if isinstance(handoff_due, dict) else None
    peak_str = f"~{pre_peak // 1000}k" if _is_int(pre_peak) and pre_peak > 0 else "hard tier"
    wall_str = f"/{pre_wall // 1000}k" if _is_int(pre_wall) and pre_wall > 0 else ""
    now_str = f", now ~{total // 1000}k" if _is_int(total) else ""
    _send_ping(
        f"{repo}: Claude Code auto-compacted after missed hard handoff "
        f"(peak {peak_str}{wall_str}{now_str}); /self-handoff is overdue.",
        data.get("cwd"),
    )


def _record_compaction_handoff_due(session_state, prev_fired, prev_peak, wall):
    """Persist `handoff_due` across compaction whenever the session had already hit hard tier."""
    existing = session_state.get("handoff_due")
    existing = existing if isinstance(existing, dict) else None
    if prev_fired >= 2:
        peak_val = prev_peak
        if not (_is_int(peak_val) and peak_val > 0) and existing:
            prev_existing_peak = existing.get("peak")
            peak_val = prev_existing_peak if _is_int(prev_existing_peak) else 0
        session_state["handoff_due"] = {
            "peak": peak_val or 0,
            "wall": wall,
            "level": prev_fired,
            "compacted_at": datetime.now(UTC).isoformat(),
            "paged": False,
        }
        session_state["last_post_compact_nudge"] = None
        return True
    if existing is not None:
        session_state["handoff_due"] = existing
    return False


def _session_successor(transcript_path):
    return _successor_target(_last_assistant_model(transcript_path))


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
            "ts": datetime.now(UTC).isoformat(),
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
    # agent_id also marks an in-process agent-team teammate (hooks reference), skipped the same
    # way: whether its hook input carries its own session_id and transcript is not documented.
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

    now = time.time()
    if event == "PostToolUse":
        last_check = session_state.get("last_check")
        # Wall time persists across hook processes/reboots. A clock rollback
        # must not suppress checks until the old clock catches up.
        if _rate_limited(last_check, now, POST_TOOL_CHECK_SECONDS):
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

    prev_fired = session_state.get("level", 0)
    if not _is_int(prev_fired):
        prev_fired = 0
    prev_paged = bool(session_state.get("paged"))
    # The highest size seen since the last reset: a run of small dips (each < 25% of the
    # previous prompt) that sums to a real shrink must still read as one.
    seen = [v for v in (session_state.get("last"), session_state.get("peak")) if _is_int(v)]
    peak = max(seen) if seen else None

    if total == COMPACTED:
        # Compacted, no request since: the next measured size is the new floor.
        saved_wall = session_state.get("wall")
        if not (_is_int(saved_wall) and saved_wall > 0):
            try:
                saved_wall = compaction_wall(read_settings(), _last_assistant_model(transcript_path))
            except Exception:
                saved_wall = AUTO_COMPACT_WALL
        if peak is not None:
            prev_fired = min(prev_fired, _level(peak, peak, _tiers(saved_wall)))
        newly_due = _record_compaction_handoff_due(session_state, prev_fired, peak, saved_wall)
        session_state.update(
            baseline=None, level=0, paged=False, last=None, peak=None,
            last_hard_nudge=None, hard_repeat_count=0,
        )
        if newly_due and not prev_paged:
            _ping_compacted_overdue(data, session_state["handoff_due"])
            session_state["handoff_due"]["paged"] = True
        state[session_id] = session_state
        _save_state(state)
        return

    # This session's real wall (settings read once, the model from the transcript tail): every
    # handoff/compact tier below derives from it. Anything unreadable: today's 267k fallback.
    try:
        wall = compaction_wall(read_settings(), _last_assistant_model(transcript_path))
    except Exception:
        wall = AUTO_COMPACT_WALL
    session_state["wall"] = wall
    tiers = _tiers(wall)
    if peak is not None:
        prev_fired = min(prev_fired, _level(peak, peak, tiers))

    baseline = session_state.get("baseline")
    floor = _compaction_floor_since(transcript_path, prev_size, size)
    if floor is not None:
        # An auto-compaction mid-turn: more tool rounds followed it, so no boundary is the
        # newest record now and the regrowth may hide it from the shrink test (round 2, F1).
        _record_compaction_handoff_due(session_state, prev_fired, peak, wall)
        baseline = floor if floor != COMPACTED else total
        session_state.update(level=0, paged=False, last_hard_nudge=None, hard_repeat_count=0)
        peak = None
    elif peak is not None and total < peak * SHRINK_RATIO:
        _record_compaction_handoff_due(session_state, prev_fired, peak, wall)
        baseline = total  # compacted between two prompts: new floor
        session_state.update(level=0, paged=False, last_hard_nudge=None, hard_repeat_count=0)
        peak = None
    if not _is_int(baseline):
        if "level" in session_state:
            baseline = total  # first size after a compaction
        else:
            baseline = _first_context_tokens(transcript_path) or total
    session_state["baseline"] = baseline
    session_state["last"] = total
    session_state["peak"] = max(total, peak or 0)
    growth = max(0, total - baseline)

    level = _level(total, growth, tiers)
    fired = session_state.get("level", 0)
    if not _is_int(fired):
        fired = 0
    # Old or corrupt state (a level the session cannot have reached) must not stick (round 2,
    # F4): clamp to what the stored peak computes (peak resets together with the level). The
    # dipped total is no bound: a floor-20k session fired level 2 at 160k, dips to 125k, and
    # must not print it again at 161k (round 3, F2).
    peak_total = session_state["peak"]
    fired = min(fired, _level(peak_total, peak_total, tiers))

    messages = []
    successor_loaded = False
    successor = None

    def get_successor():
        nonlocal successor_loaded, successor
        if not successor_loaded:
            successor = _session_successor(transcript_path)
            successor_loaded = True
        return successor

    if level > fired:
        if level == 1:
            messages.append((_early_message(total, growth), "early"))
        else:
            messages.append((_ask_message(total, growth, repeat=fired >= 2,
                                         successor=get_successor(), wall=wall), "ask"))
            session_state["last_hard_nudge"] = now
            session_state["hard_repeat_count"] = 0
    elif level >= 2 and fired >= 2:
        # Still at or above the hard tier: do not go silent until +100k (2026-11-24).
        last_hard = session_state.get("last_hard_nudge")
        if event != "PostToolUse" or not _rate_limited(last_hard, now, HARD_REPEAT_SECONDS):
            repeat_count = session_state.get("hard_repeat_count", 0)
            repeat_count = (repeat_count if _is_int(repeat_count) and repeat_count >= 0 else 0) + 1
            session_state["hard_repeat_count"] = repeat_count
            session_state["last_hard_nudge"] = now
            messages.append((_hard_repeat_message(total, growth, repeat_count,
                                                 successor=get_successor(), wall=wall), "ask_repeat"))
    # Never lower the stored level on a dip: a compaction or a real shrink already reset it
    # above, and a smaller dip must not let the next climb past the tier reprint the message.
    session_state["level"] = max(level, fired)

    # Once per session id, not per compaction: a /new starts a new id.
    if (total >= tiers.boundary_total and _handoff_growth_ok(growth, tiers)
            and not session_state.get("boundary")):
        session_state["boundary"] = True
        messages.append((_boundary_message(total, successor=get_successor(), wall=wall),
                         "boundary"))

    # Post-compaction handoff_due: if auto-compaction happened after reaching hard tier,
    # keep reminding the agent to run /self-handoff even while context is back below hard tier.
    handoff_due = session_state.get("handoff_due")
    handoff_due = handoff_due if isinstance(handoff_due, dict) else None
    if handoff_due is not None and level < 2:
        last_post = session_state.get("last_post_compact_nudge")
        if event != "PostToolUse" or not _rate_limited(last_post, now, HARD_REPEAT_SECONDS):
            session_state["last_post_compact_nudge"] = now
            messages.append((_post_compact_handoff_message(total, handoff_due,
                                                          successor=get_successor(), wall=wall),
                             "post_compact_handoff_due"))

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

    pinged_this_call = False
    if level >= 2 or growth >= tiers.page_growth or total >= tiers.page_total:
        if not session_state.get("paged"):
            session_state["paged"] = True
            pinged_this_call = True
            repo = _repo_name(data)
            _send_ping(
                f"{repo}: Claude Code context at ~{total // 1000}k/{wall // 1000}k "
                f"(+{growth // 1000}k since start or last compact, hard handoff tier); agent will "
                "/self-handoff then /new, or /compact, at its next boundary.",
                data.get("cwd"),
            )
    elif session_state["level"] < 2:
        session_state["paged"] = False  # compacted: page again on regrowth

    if handoff_due is not None and not handoff_due.get("paged") and not pinged_this_call:
        handoff_due["paged"] = True
        session_state["handoff_due"] = handoff_due
        _ping_compacted_overdue(data, handoff_due, total=total)

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
