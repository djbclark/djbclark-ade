#!/usr/bin/env python3
"""Stop / SessionStart / UserPromptSubmit: enforce script-issued `Ref:` lines and auto-mint on block.

2026-11-21: a session ended several posts with "Ref: youtube-tv-proxy 82118f5", a git short hash
typed by hand, and nothing noticed. A Ref is a unique, script-issued id for one operator-facing
post (docs/ref-labels.md Part B): `ref <BOT>` prints `Ref: <BOT>-<base36>` and logs it in
~/.local/state/djbclark-ade/refs/issued.log (REFS_DIR overrides). This hook is the check.

2026-11-24 (Rule 11 harness fix for session 90acbb75):
  - Missing `Ref:` on a 200+ char final post blocks once (same loop guards as invalid Ref)
    instead of emitting a non-blocking systemMessage that neither logged telemetry nor gave a Ref.
  - On any block (missing Ref or invalid Ref), the hook infers `<BOT>` (`ADE_REF_BOT` / `REF_BOT`,
    else `CLAUDE` for Claude Code), runs `bin/ref [--skip-id <id>] <BOT>` directly, and hands the
    freshly minted `Ref: <BOT>-<id>` line directly in the block reason so the model needs no extra
    Bash round (graceful fallback to naming `ref <BOT>` explicitly if `bin/ref` is unavailable,
    fails, or emits undecodable/unexpected output). Passing `--skip-id` skips an immediate counter
    collision during this mint inside `bin/ref`'s lock before committing, without registering the
    rejected id as issued.
  - Every in-scope top-level `Stop` decision (`allowed-empty`, `allowed-short`, `allowed-valid`,
    `allowed-unreadable-log`, `allowed-stop-hook-active`, `allowed-already-blocked`,
    `blocked-no-ref`, `blocked`) writes a strictly categorical, content-free audit row to
    `decisions.log` (`0700` dir / `0600` files) with `session_id`, `outcome`, `ref_kind`,
    `post_len`, `stop_hook_active`, `reason`, and optional categorical `problem` / `minted_ref`.
    No assistant-supplied text (raw reply lines, malformed Ref text, or unissued/wrong-bot Ref
    substrings) is ever written to `decisions.log`. Exclusions (not logged): sub-agents
    (`agent_id`), non-`Stop` events, unparseable stdin JSON, and `REF_GATE_OFF=1`.
  - On `SessionStart` (fires on startup, resume, clear, compact, fork) and `UserPromptSubmit`
    (once per compaction epoch, keyed by latest main-thread `compact_boundary` identity and
    persisted atomically with `0600` mode; bounded tail scans or transient read failures preserve
    the last known epoch instead of resetting to `initial`), emits a crisp one-line
    `additionalContext` reminder so auto-compaction cannot drop the Ref rule.

When the last non-blank line of the final assistant message starts with `Ref:` it must:
  (a) have the form `Ref: <BOT>-<base36>` (BOT has no spaces or hyphens);
  (b) name an id that is in issued.log;
  (c) carry the bot prefix the log recorded for that id;
  (d) not have been used by an earlier post of the same transcript (grouped by `message.id` with
      duplicate physical records deduplicated).
Any failure, or a 200+ char post with no `Ref:` last line, returns {"decision": "block", "reason": ...}
with a freshly minted `Ref: <BOT>-<id>` line ready to paste. Short progress notes under 200 chars
without a `Ref:` line are exempt (docs/ref-labels.md Part B item 1).

Never loops: nothing is blocked when `stop_hook_active` is set, and a message (by hash) is blocked
at most once per session (guarded by a single stable `.state.lock` file that is never unlinked).
Sub-agents (`agent_id` in the payload) are skipped: their final message goes to the parent, not the
operator. Local and fast: it reads issued.log and the transcript tail, no network. Fails open on
any error, including an issued.log that exists but cannot be read (logged `allowed-unreadable-log`);
an absent log or one without the id is "never issued" and blocks. REF_GATE_OFF=1 disables it. The
log is read as `ref lookup` (bin/ref) reads it; the form check here is stricter (upper-case BOT,
lower-case id) and the block reason never repeats untrusted text from the post, so a Ref line
cannot smuggle an instruction into it. tests/test_ref_integrity_gate.py keeps the two in step.

Environment: REFS_DIR (issued.log directory), REF_GATE_STATE_DIR (once-per-message state, reminder
epoch state and decisions.log, default ~/.local/state/ade/ref-gate), ADE_REF_BOT / REF_BOT (bot
prefix override, default CLAUDE), REF_GATE_REF_BIN (override path to bin/ref).
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager

DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
REF_LINE = re.compile(r"^Ref:")
# The form is closed on purpose: nothing outside it is ever echoed into the block reason (a
# Ref line can carry text from untrusted content or secrets, and the reason reads like a harness order).
REF_FORM = re.compile(r"^Ref: ([A-Z0-9_]{1,32})-([0-9a-z]{1,13})$")
SAFE_BOT = re.compile(r"[A-Z0-9_]{1,32}")
COMPACT_BOUNDARY = re.compile(rb'"subtype":\s*"compact_boundary"')
DEFAULT_BOT = "CLAUDE"
LOCK_WAIT = 1.0  # seconds to wait for a writer holding the log before reading anyway
REF_MINT_TIMEOUT = 3.0  # seconds to wait for `bin/ref <BOT>` before falling back
SHORT_POST = 200  # docs/ref-labels.md Part B item 1: a progress note under 200 chars is exempt
TRANSCRIPT_TAIL = 64 * 1024 * 1024
STATE_MAX_AGE = 14 * 86400
STATE_LOCK_NAME = ".state.lock"

# Strictly categorical audit descriptions written to decisions.log (zero assistant-supplied text).
_AUDIT_PROBLEM: dict[str, str] = {
    "none": f"no Ref: last line on a {SHORT_POST}+ char post",
    "malformed": "Ref: last line is not of the form Ref: <BOT>-<base36 id>",
    "never-issued": "Ref id was never issued by ref",
    "wrong-bot": "Ref id was issued to a different bot prefix",
    "reused": "Ref already ended an earlier post of this session",
    "unreadable-log": "issued.log exists but could not be read",
}


def refs_dir() -> str:
    return os.environ.get("REFS_DIR") or os.path.expanduser("~/.local/state/djbclark-ade/refs")


def state_dir() -> str:
    d = os.environ.get("REF_GATE_STATE_DIR") or os.path.expanduser("~/.local/state/ade/ref-gate")
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _open_private(path: str, flags: int) -> int:
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
    except OSError:
        pass
    return fd


def _atomic_write_private(path: str, data: str) -> None:
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-ref-gate-")
    try:
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


@contextmanager
def _state_lock(root: str):
    """Hold an exclusive flock on a single permanent `.state.lock` file that is never unlinked.

    Keeping one stable lock inode prevents the unlink-while-held race where pruning replaces a
    lock pathname out from under an active session.
    """
    lock_path = os.path.join(root, STATE_LOCK_NAME)
    lock_fd = _open_private(lock_path, os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(lock_fd)


def normalize_bot(name: str) -> str:
    return name.upper().replace(" ", "").replace("-", "")


def infer_bot() -> str:
    """Infer the Ref bot prefix for this Claude Code session.

    Honors ADE_REF_BOT (or REF_BOT) when it normalizes to a valid SAFE_BOT (excluding reserved
    LOOKUP); defaults to CLAUDE for Claude Code sessions (docs/ref-labels.md Prefixes).
    """
    for key in ("ADE_REF_BOT", "REF_BOT"):
        raw = os.environ.get(key)
        if raw and raw.strip():
            bot = normalize_bot(raw.strip())
            if bot != "LOOKUP" and SAFE_BOT.fullmatch(bot):
                return bot
    return DEFAULT_BOT


def find_ref_bin() -> str | None:
    """Locate `bin/ref` without relying on PATH mutation."""
    if "REF_GATE_REF_BIN" in os.environ:
        override = os.environ["REF_GATE_REF_BIN"].strip()
        return override if override and os.path.isfile(override) else None
    repo_ref = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))),
        "bin",
        "ref",
    )
    if os.path.isfile(repo_ref):
        return repo_ref
    local_ref = os.path.expanduser("~/.local/bin/ref")
    if os.path.isfile(local_ref):
        return local_ref
    return shutil.which("ref")


def _ref_argv(ref_bin: str, bot: str, skip_id: str | None = None) -> list[str]:
    extra = ["--skip-id", skip_id] if skip_id else []
    try:
        with open(ref_bin, "rb") as fh:
            head = fh.readline(128)
        if head.startswith(b"#!") and b"python" in head.lower():
            return [sys.executable, ref_bin, *extra, bot]
    except OSError:
        pass
    return [ref_bin, *extra, bot]


def mint_ref(bot: str, session: str, exclude: str | None = None) -> str | None:
    """Run `bin/ref [--skip-id <id>] <BOT>` to mint a fresh valid `Ref: <BOT>-<id>` line; None on any failure."""
    if bot == "LOOKUP" or not SAFE_BOT.fullmatch(bot):
        return None
    ref_bin = find_ref_bin()
    if not ref_bin:
        return None
    skip_id = None
    if exclude:
        m = REF_FORM.match(exclude)
        if m:
            skip_id = m.group(2)
    env = dict(os.environ)
    if not any(
        env.get(k, "").strip()
        for k in ("REF_AGENT", "PASEO_AGENT_ID", "AGENT_ID", "CURSOR_CONVERSATION_ID")
    ):
        if session and session != "unknown":
            env["REF_AGENT"] = session
    argv = _ref_argv(ref_bin, bot, skip_id=skip_id)
    try:
        res = subprocess.run(
            argv,
            env=env,
            capture_output=True,
            timeout=REF_MINT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    try:
        minted = res.stdout.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    form = REF_FORM.match(minted)
    if not form or form.group(1) != bot:
        return None
    if exclude and minted == exclude:
        return None
    return minted


def ref_reminder_text(bot: str) -> str:
    return (
        f"End every operator-facing reply of {SHORT_POST}+ chars with a fresh script-issued "
        f"Ref: line from `ref {bot}`."
    )


def last_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


class LogUnreadable(Exception):
    """issued.log exists but cannot be read: the hook cannot judge a Ref, so it fails open."""


def issued_bot(ident: str) -> str:
    """The bot issued.log recorded for `ident`, "" when it was never issued (the log or its
    directory is absent, or readable without the id). Raises LogUnreadable when the log exists but
    cannot be read (permissions, I/O error, not a regular file). Reads the log as
    `ref lookup` does (shared flock on an existing .lock, first matching line, nothing created);
    a stuck writer is waited for LOCK_WAIT seconds only, and only regular files are opened."""
    d = refs_dir()
    lock_fd = None
    try:
        lock_fd = os.open(os.path.join(d, ".lock"), os.O_RDONLY | os.O_NONBLOCK)
        if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
            os.close(lock_fd)
            lock_fd = None
        else:
            deadline = time.monotonic() + LOCK_WAIT
            while True:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(0.05)
    except OSError:
        lock_fd = None
    try:
        fd = os.open(os.path.join(d, "issued.log"), os.O_RDONLY | os.O_NONBLOCK)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise LogUnreadable("issued.log is not a regular file")
        with os.fdopen(fd, encoding="utf-8", errors="replace") as log:
            for line in log:
                cols = line.rstrip("\n").split("\t")
                if cols[0] == ident and len(cols) >= 2:
                    return cols[1]
    except OSError as exc:
        if exc.errno not in (errno.ENOENT, errno.ENOTDIR):
            raise LogUnreadable(os.strerror(exc.errno or 0)) from exc
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
    return ""


def _entry_texts(msg: dict) -> list[str]:
    content = msg.get("content")
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [
            b["text"]
            for b in content
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
        ]
    return []


def _record_key(entry: dict, raw_line: bytes) -> tuple[str, object]:
    """Identity of one physical transcript record within a message ID."""
    uid = entry.get("uuid")
    if isinstance(uid, str) and uid.strip():
        return ("uuid", uid.strip())
    return ("line", hashlib.sha256(raw_line).digest())


def _collapse_repeated_sequence(blocks: list[str]) -> list[str]:
    """If `blocks` is an exact whole-sequence repetition (e.g. [A, B, A, B] -> [A, B]), return the
    shortest repeating unit; otherwise return `blocks` unchanged."""
    n = len(blocks)
    if n < 2:
        return blocks
    for unit in range(1, n // 2 + 1):
        if n % unit == 0 and blocks[:unit] * (n // unit) == blocks:
            return blocks[:unit]
    return blocks


def assistant_messages(path: str) -> tuple[list[tuple[str, str, list[str], int]], int]:
    """([(message id, complete joined text, individual text blocks, turn)], current_turn) for
    main-thread assistant messages in the transcript tail, oldest first, grouped by `message.id`
    with repeated physical records deduplicated in forward order by record `uuid` (or line digest
    when `uuid` is absent). `turn` increments on every main-thread `user` or `compact_boundary`
    record so callers can prove whether a match belongs to the current turn or an earlier turn."""
    order: list[str | None] = []
    by_id: dict[str, list[str]] = {}
    turn_by_id: dict[str, int] = {}
    seen_records: dict[str, set[tuple[str, object]]] = {}
    anonymous: list[tuple[list[str], int]] = []
    turn = 0
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - TRANSCRIPT_TAIL))
            raw = fh.read()
    except OSError:
        return [], 0
    for line in raw.split(b"\n"):
        has_assistant = b'"assistant"' in line
        has_user = b'"user"' in line
        has_boundary = bool(COMPACT_BOUNDARY.search(line))
        if not (has_assistant or has_user or has_boundary):
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("isSidechain"):
            continue
        etype = entry.get("type")
        if etype == "user" or (etype == "system" and entry.get("subtype") == "compact_boundary"):
            turn += 1
            continue
        if etype != "assistant":
            continue
        msg = entry.get("message")
        if not isinstance(msg, dict):
            continue
        texts = _entry_texts(msg)
        if not texts:
            continue
        mid = str(msg.get("id") or entry.get("uuid") or "")
        if mid:
            rkey = _record_key(entry, line)
            if mid in seen_records and rkey in seen_records[mid]:
                continue
            if mid not in by_id:
                by_id[mid] = []
                turn_by_id[mid] = turn
                seen_records[mid] = set()
                order.append(mid)
            seen_records[mid].add(rkey)
            by_id[mid].extend(texts)
        else:
            anonymous.append((texts, turn))
            order.append(None)
    out: list[tuple[str, str, list[str], int]] = []
    anon_iter = iter(anonymous)
    for key in order:
        if key is None:
            blocks, msg_turn = next(anon_iter)
            out.append(("", "\n".join(blocks), blocks, msg_turn))
        else:
            blocks = by_id[key]
            out.append((key, "\n".join(blocks), blocks, turn_by_id[key]))
    return out, turn


def last_transcript_text(path: str) -> str:
    """Text of the final main-thread assistant message in the transcript (fallback when the payload
    has no `last_assistant_message`). Collects all records sharing the newest assistant
    `message.id`, reverses them to original forward record order before deduplicating repeated
    physical records (matching `assistant_messages()`), skips sidechain records, stops immediately
    at any newer main-thread `user` / task-notification or `compact_boundary` boundary (so a
    textless wake-up tail never reaches back to an earlier reply), and returns "" when that newest
    turn has no text."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - 4 * 1024 * 1024))
            raw = fh.read()
    except OSError:
        return ""
    target_mid: str | None = None
    rev_records: list[tuple[tuple[str, object], list[str]]] = []
    for line in reversed(raw.split(b"\n")):
        has_assistant = b'"assistant"' in line
        has_user = b'"user"' in line
        has_boundary = bool(COMPACT_BOUNDARY.search(line))
        if not (has_assistant or has_user or has_boundary):
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("isSidechain"):
            continue
        etype = entry.get("type")
        if etype == "user" or (etype == "system" and entry.get("subtype") == "compact_boundary"):
            break
        if etype != "assistant":
            continue
        msg = entry.get("message")
        if not isinstance(msg, dict):
            if target_mid is None:
                return ""
            break
        mid = str(msg.get("id") or "")
        texts = _entry_texts(msg)
        if target_mid is None:
            if not mid:
                return "\n".join(texts)
            target_mid = mid
            rev_records.append((_record_key(entry, line), texts))
        else:
            if mid != target_mid:
                break
            rev_records.append((_record_key(entry, line), texts))
    chunks: list[str] = []
    seen_keys: set[tuple[str, object]] = set()
    for rkey, texts in reversed(rev_records):
        if rkey in seen_keys:
            continue
        seen_keys.add(rkey)
        if texts:
            chunks.append("\n".join(texts))
    return "\n".join(chunks)


def compact_epoch_id(path: str) -> str | None:
    """Stable identity of the latest main-thread compact_boundary in the transcript tail.

    Returns:
      - `"uuid:<id>"` or `"off:<offset>:<digest>"` when a main-thread boundary is found;
      - `"initial"` ONLY when no transcript path is given OR a complete scan from byte 0 succeeded
        with no boundary;
      - `None` (indeterminate) when reading the transcript failed or the scan was bounded to the
        last `TRANSCRIPT_TAIL` bytes (`base > 0`) without finding a boundary, so callers preserve
        any already-persisted epoch rather than resetting to `"initial"`.
    """
    if not path:
        return "initial"
    try:
        size = os.path.getsize(path)
        base = max(0, size - TRANSCRIPT_TAIL)
        with open(path, "rb") as fh:
            fh.seek(base)
            raw = fh.read()
    except OSError:
        return None
    end = len(raw)
    while end > 0:
        nl = raw.rfind(b"\n", 0, end)
        start = nl + 1 if nl >= 0 else 0
        line = raw[start:end]
        end = nl if nl >= 0 else 0
        if not line or not COMPACT_BOUNDARY.search(line):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if (
            isinstance(obj, dict)
            and obj.get("type") == "system"
            and obj.get("subtype") == "compact_boundary"
            and not obj.get("isSidechain")
        ):
            uid = obj.get("uuid")
            if isinstance(uid, str) and uid.strip():
                return f"uuid:{uid.strip()[:128]}"
            digest = hashlib.sha256(line).hexdigest()[:16]
            return f"off:{base + start}:{digest}"
    return "initial" if base == 0 else None


def used_earlier(path: str, ref_line: str, message: str) -> bool:
    """True when an earlier main-thread assistant message of this transcript already ended with
    `ref_line` (evaluated on each message's complete grouped text). The current message is normally
    already in the transcript, so the newest match is dropped ONLY when it is the latest assistant
    message in the current transcript turn (no newer main-thread `user` or `compact_boundary`
    record follows it) and matches the message being checked; a lagging transcript with a
    previous-turn match is never misdropped."""
    messages, current_turn = assistant_messages(path)
    if not messages:
        return False
    ends = [m for m in messages if last_line(m[1]) == ref_line]
    if ends:
        cur_mid, cur_text, cur_blocks, cur_turn = ends[-1]
        is_current_turn_tail = cur_turn == current_turn and ends[-1] is messages[-1]
        if is_current_turn_tail:
            norm_msg = message.rstrip()
            collapsed_text = "\n".join(_collapse_repeated_sequence(cur_blocks)).rstrip()
            if (
                norm_msg.endswith(cur_text.rstrip())
                or norm_msg.endswith(collapsed_text)
                or (cur_blocks and all(b.rstrip() == norm_msg for b in cur_blocks))
            ):
                ends = [e for e in ends if e[0] != cur_mid] if cur_mid else ends[:-1]
    return bool(ends)


def check(message: str, transcript: str) -> tuple[str, str] | None:
    """None when the post is fine; else (ref_kind, interactive_problem), built only from fixed text
    and from values that matched REF_FORM (or the log's bot, when it is a plain prefix)."""
    line = last_line(message)
    form = REF_FORM.match(line)
    if not form:
        return (
            "malformed",
            "the last line is not of the form `Ref: <BOT>-<base36 id>` (BOT upper case, id lower case)",
        )
    bot, ident = form.groups()
    issued = issued_bot(ident)
    if not issued:
        return (
            "never-issued",
            f"id `{ident}` was never issued by `ref` (a git hash, PR number or hand-typed id is not a Ref)",
        )
    if issued != bot:
        shown = issued if SAFE_BOT.fullmatch(issued) else "another bot"
        return (
            "wrong-bot",
            f"id `{ident}` was issued to bot `{shown}`, not `{bot}`",
        )
    if transcript and used_earlier(transcript, line, message):
        return (
            "reused",
            f"`{line}` already ended an earlier post of this session (one Ref per post, never reused)",
        )
    return None


def log_decision(
    session: str,
    outcome: str,
    ref_kind: str,
    *,
    reason: str,
    post_len: int,
    stop_hook_active: bool,
    problem: str = "",
    minted_ref: str | None = None,
) -> None:
    """Append one strictly categorical, content-free structured telemetry row to decisions.log (0600).

    Never logs raw reply text, malformed Ref text, or assistant-supplied Ref substrings; records
    only classifications, lengths, categorical reasons/problems, and valid minted Ref IDs.
    """
    try:
        rec: dict[str, object] = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "session": session,
            "session_id": session,
            "outcome": outcome,
            "ref_kind": ref_kind,
            "post_len": post_len,
            "stop_hook_active": stop_hook_active,
            "reason": reason[:500],
        }
        if problem:
            rec["problem"] = problem[:300]
        if minted_ref and REF_FORM.match(minted_ref):
            rec["minted_ref"] = minted_ref
        log_path = os.path.join(state_dir(), "decisions.log")
        fd = _open_private(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def _safe_session_name(session: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", session)[:120]


def _prune_state_files_locked(root: str, keep: set[str] | None = None) -> None:
    """Expire old `.blocked` / `.reminded` session files while holding `.state.lock`.

    NEVER unlinks `.state.lock` (or any `.lock` file) or `decisions.log`.
    """
    keep_names = keep or set()
    cutoff = time.time() - STATE_MAX_AGE
    try:
        for name in os.listdir(root):
            if name in keep_names or name == STATE_LOCK_NAME or name.endswith(".lock"):
                continue
            if not (name.endswith(".blocked") or name.endswith(".reminded")):
                continue
            full = os.path.join(root, name)
            try:
                if os.path.getmtime(full) < cutoff:
                    os.unlink(full)
            except OSError:
                pass
    except OSError:
        pass


def already_blocked(session: str, digest: str) -> bool:
    """Record that this message was blocked; True when it had been (so it is never blocked twice).

    Guarded by the permanent `.state.lock` flock across check-and-append (and stale-file pruning)
    so overlapping Stop invocations for the same session and digest cannot double-block or
    double-mint.
    """
    root = state_dir()
    fname = _safe_session_name(session) + ".blocked"
    path = os.path.join(root, fname)
    with _state_lock(root):
        try:
            with open(path, encoding="utf-8") as fh:
                if digest in fh.read().split():
                    return True
        except OSError:
            pass
        fd = _open_private(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(digest + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        _prune_state_files_locked(root, keep={fname})
    return False


def should_remind_epoch(session: str, epoch: str | None) -> bool:
    """True once per (session, compaction epoch identity), persisted atomically with 0600 mode.

    When `epoch` is `None` (bounded tail scan found no boundary or transient transcript read
    failure), any already-persisted epoch is preserved untouched and False is returned so the
    session does not emit a duplicate reminder; if no epoch has been persisted yet, `"initial"`
    is recorded and True is returned.
    """
    root = state_dir()
    fname = _safe_session_name(session) + ".reminded"
    path = os.path.join(root, fname)
    try:
        with _state_lock(root):
            prev: str | None = None
            try:
                with open(path, encoding="utf-8") as fh:
                    val = fh.read().strip()
                    if val:
                        prev = val
            except OSError:
                pass
            if epoch is None:
                if prev is not None:
                    return False
                target = "initial"
            else:
                if prev == epoch:
                    return False
                target = epoch
            _atomic_write_private(path, target + "\n")
            _prune_state_files_locked(root, keep={fname})
    except OSError:
        return True
    return True


def _no_ref_block_reason(post_len: int, bot: str, minted: str | None) -> str:
    prefix = (
        f"ref-integrity: this post ({post_len} chars) has no `Ref:` last line. "
        f"Operator-facing posts of {SHORT_POST}+ chars must end with a fresh script-issued Ref "
        "(docs/ref-labels.md Part B)."
    )
    if minted:
        return f"{prefix} No Bash call is needed; append this exact last line to your reply: {minted}"
    return (
        f"{prefix} Run `ref {bot}` with Bash, then send your reply again with the exact line `ref` "
        "printed as the last line."
    )


def _invalid_ref_block_reason(why: str, bot: str, minted: str | None) -> str:
    prefix = (
        f"Invalid Ref line: {why}. A Ref is a unique id issued by a script for one operator-facing "
        "post; never a commit hash, PR number or text you typed."
    )
    if minted:
        return (
            f"{prefix} No Bash call is needed; replace the last line of your reply with this exact "
            f"freshly minted line: {minted}"
        )
    return (
        f"{prefix} Run `ref {bot}` with Bash, then send the post again with its last line replaced "
        "by the exact line `ref` printed."
    )


def _audit_block_reason(ref_kind: str, bot: str, minted: str | None) -> str:
    cat = _AUDIT_PROBLEM.get(ref_kind, "invalid Ref: last line")
    if minted:
        return f"blocked: {cat} (auto-minted {minted})"
    return f"blocked: {cat} (fallback: ref {bot})"


def handle_session_start(data: dict) -> int:
    if data.get("agent_id"):
        return 0
    bot = infer_bot()
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": ref_reminder_text(bot),
        }
    }))
    return 0


def handle_user_prompt_submit(data: dict) -> int:
    if data.get("agent_id"):
        return 0
    session = str(data.get("session_id") or "unknown")
    transcript = data.get("transcript_path") if isinstance(data.get("transcript_path"), str) else ""
    epoch = compact_epoch_id(transcript)
    if should_remind_epoch(session, epoch):
        bot = infer_bot()
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": ref_reminder_text(bot),
            }
        }))
    return 0


def handle_stop(data: dict) -> int:
    if data.get("agent_id"):
        return 0  # a sub-agent's final message goes to its parent, not the operator
    session = str(data.get("session_id") or "unknown")
    transcript = data.get("transcript_path") if isinstance(data.get("transcript_path"), str) else ""
    stop_active = bool(data.get("stop_hook_active"))
    message = data.get("last_assistant_message")
    if not isinstance(message, str):
        message = last_transcript_text(transcript) if transcript else ""
    stripped = message.strip()
    if not stripped:
        log_decision(
            session, "allowed-empty", "none",
            reason="no final assistant text to check",
            post_len=0, stop_hook_active=stop_active,
        )
        return 0
    post_len = len(stripped)
    line = last_line(message)
    if not REF_LINE.match(line):
        if post_len < SHORT_POST:
            log_decision(
                session, "allowed-short", "none",
                reason=f"short post under {SHORT_POST} chars (progress-note exemption)",
                post_len=post_len, stop_hook_active=stop_active,
            )
            return 0
        cat_problem = _AUDIT_PROBLEM["none"]
        digest = hashlib.sha256(message.encode("utf-8", "replace")).hexdigest()[:16]
        if stop_active:
            log_decision(
                session, "allowed-stop-hook-active", "none",
                reason=f"loop-guard: stop_hook_active is true ({cat_problem})",
                problem=cat_problem, post_len=post_len, stop_hook_active=True,
            )
            return 0
        if already_blocked(session, digest):
            log_decision(
                session, "allowed-already-blocked", "none",
                reason=f"loop-guard: message already blocked once in this session ({cat_problem})",
                problem=cat_problem, post_len=post_len, stop_hook_active=False,
            )
            return 0
        bot = infer_bot()
        minted = mint_ref(bot, session)
        reason = _no_ref_block_reason(post_len, bot, minted)
        log_decision(
            session, "blocked-no-ref", "none",
            reason=_audit_block_reason("none", bot, minted),
            problem=cat_problem, minted_ref=minted,
            post_len=post_len, stop_hook_active=False,
        )
        print(json.dumps({"decision": "block", "reason": reason}))
        return 0
    try:
        finding = check(message, transcript)
    except LogUnreadable:
        cat_problem = _AUDIT_PROBLEM["unreadable-log"]
        log_decision(
            session, "allowed-unreadable-log", "unreadable-log",
            reason=f"fail-open: {cat_problem}",
            problem=cat_problem, post_len=post_len, stop_hook_active=stop_active,
        )
        return 0
    if finding is None:
        log_decision(
            session, "allowed-valid", "valid",
            reason="valid script-issued Ref",
            post_len=post_len, stop_hook_active=stop_active,
        )
        return 0
    ref_kind, interactive_why = finding
    cat_problem = _AUDIT_PROBLEM.get(ref_kind, "invalid Ref: last line")
    digest = hashlib.sha256(message.encode("utf-8", "replace")).hexdigest()[:16]
    if stop_active:
        log_decision(
            session, "allowed-stop-hook-active", ref_kind,
            reason=f"loop-guard: stop_hook_active is true ({cat_problem})",
            problem=cat_problem, post_len=post_len, stop_hook_active=True,
        )
        return 0
    if already_blocked(session, digest):
        log_decision(
            session, "allowed-already-blocked", ref_kind,
            reason=f"loop-guard: message already blocked once in this session ({cat_problem})",
            problem=cat_problem, post_len=post_len, stop_hook_active=False,
        )
        return 0
    bot = infer_bot()
    minted = mint_ref(bot, session, exclude=line)
    reason = _invalid_ref_block_reason(interactive_why, bot, minted)
    log_decision(
        session, "blocked", ref_kind,
        reason=_audit_block_reason(ref_kind, bot, minted),
        problem=cat_problem, minted_ref=minted,
        post_len=post_len, stop_hook_active=False,
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


def main() -> int:
    if os.environ.get("REF_GATE_OFF"):
        return 0
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(data, dict):
        return 0
    event = data.get("hook_event_name")
    if event == "Stop":
        return handle_stop(data)
    if event == "SessionStart":
        return handle_session_start(data)
    if event == "UserPromptSubmit":
        return handle_user_prompt_submit(data)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # fail open: a gate bug must never wedge an agent
        sys.exit(0)
