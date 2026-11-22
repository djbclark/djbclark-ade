#!/usr/bin/env python3
"""ade_approval_window: answer agent tool-permission prompts while the sudo-ask approval window is open.

Operator ruling (2026-11-22): "we want our limited-duration token to also avoid prompts such as this" (a Claude Code
`rm` safety card, shown by Paseo because a bypass-mode Claude agent has no allow rule that clears it).

The window itself belongs to site-public-djbclark's `sudo-ask grant [DURATION]` (the root-owned file
/var/db/sudo-ask/grant; schema and the command denylist live in that repo's roles/sudo_ask_grant). This module only READS
it (`read_window`, `window_open`) and, while it is open, allows pending permission requests (`decide`, `sweep`) except for
the ones named in docs/approval-window.md. It never opens, extends or closes a window and never calls sudo.

Everything here is pure or takes its dependencies as parameters, so tests never touch the real grant file, the real daemon
or the real log. The grant path is hard-coded in production (`GRANT_PATH`): no environment variable or option moves it, and
tests inject another path only through a function parameter. Python 3.9 compatible (the Claude hook runs under it).
"""
from __future__ import annotations

import errno
import fcntl
import json
import os
import posixpath
import re
import shlex
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

GRANT_PATH = "/var/db/sudo-ask/grant"   # hard-coded: same as site-public-djbclark roles/sudo_ask_grant/files/sudo-ask-granted
OWNER_UID = 0                            # the grant dir and file must be owned by root
MIN_WINDOW_S = 60                        # the helper refuses a shorter grant
MAX_WINDOW_S = 86400                     # ... and a longer one; a file that expires later than this from now is tampered
CLOCK_SLACK_S = 120                      # tolerated skew for a grant stamped "in the future" (same as the helper)
MAX_GRANT_BYTES = 4096

DEFAULT_DAEMON_URL = "http://127.0.0.1:7263/mcp/agents"   # Paseo's loopback Agent MCP route (bootstrap.ts agentMcpRoute)
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
MIN_POLL_S = 2.0                         # `watch` never polls faster
COMMAND_PREFIX_CHARS = 200
MAX_TEXT_CHARS = 200_000                 # a request string longer than this is not scanned: it stays pending (unreadable)


def default_log_path() -> Path:
    return Path.home() / ".local/state/djbclark-ade/approval-window/permits.jsonl"


# ---------------------------------------------------------------- the window (read only, fails closed)


@dataclass(frozen=True)
class Window:
    open: bool
    reason: str
    expires_epoch: Optional[int] = None
    remaining_s: Optional[int] = None


_ISO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


def _parse_iso(text: Any) -> int:
    if not isinstance(text, str) or not _ISO.fullmatch(text):
        raise ValueError("bad timestamp")
    return int(datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())


def _trusted(st: os.stat_result, want_dir: bool, owner_uid: int) -> bool:
    kind_ok = stat.S_ISDIR(st.st_mode) if want_dir else stat.S_ISREG(st.st_mode)   # lstat: a symlink is neither
    return kind_ok and st.st_uid == owner_uid and (st.st_mode & 0o022) == 0


def read_window(path: str = GRANT_PATH, now: Optional[float] = None, owner_uid: int = OWNER_UID) -> Window:
    """The state of the approval window. Closed on any doubt: a missing, foreign-owned, writable, linked, damaged,
    expired or far-future grant is closed. `owner_uid` exists for tests (they cannot create root-owned files); every
    production caller leaves it at 0."""
    now = time.time() if now is None else now
    try:
        directory = os.path.dirname(path) or "."
        if not _trusted(os.lstat(directory), True, owner_uid):
            return Window(False, "grant dir is not a root-owned, non-writable directory")
        before = os.lstat(path)
        if not _trusted(before, False, owner_uid):
            return Window(False, "grant file is not a root-owned, non-writable regular file")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    except FileNotFoundError:
        return Window(False, "no window is open")
    except OSError as exc:
        return Window(False, "cannot read the grant file (%s)" % (exc.strerror or exc.errno))
    try:
        after = os.fstat(fd)
        if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino) or not _trusted(after, False, owner_uid):
            return Window(False, "grant file changed while it was read")
        if after.st_size > MAX_GRANT_BYTES:
            return Window(False, "grant file is too large")
        raw = os.read(fd, MAX_GRANT_BYTES + 1)
    except OSError as exc:
        return Window(False, "cannot read the grant file (%s)" % (exc.strerror or exc.errno))
    finally:
        os.close(fd)
    try:
        data = json.loads(raw.decode("utf-8"))
        expires = _parse_iso(data["expires_utc"])
        granted = _parse_iso(data["granted_utc"])
        duration, uid, nonce = data["duration_s"], data["granted_by_uid"], data["nonce"]
        if not isinstance(duration, int) or isinstance(duration, bool) or not isinstance(uid, int):
            raise ValueError("types")
        if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
            raise ValueError("nonce")
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return Window(False, "grant file is damaged")
    if not MIN_WINDOW_S <= duration <= MAX_WINDOW_S or expires - granted != duration:
        return Window(False, "grant file has an impossible duration")
    if granted > now + CLOCK_SLACK_S:
        return Window(False, "grant file is dated in the future")
    if expires - now > MAX_WINDOW_S:
        return Window(False, "grant file expires more than 24h from now (tampered?)")
    if expires <= now:
        return Window(False, "the window has expired")
    return Window(True, "window open", expires, int(expires - now))


def window_open(path: str = GRANT_PATH, now: Optional[float] = None, owner_uid: int = OWNER_UID) -> bool:
    return read_window(path, now, owner_uid).open


# ---------------------------------------------------------------- the pending request, as Paseo's MCP reports it


@dataclass(frozen=True)
class Request:
    agent_id: str
    request_id: str
    provider: str
    name: str
    kind: str
    title: str
    description: str
    input: Optional[Dict[str, Any]]
    detail: Optional[Dict[str, Any]]
    metadata: Optional[Dict[str, Any]]


def _s(value: Any) -> str:
    return value if isinstance(value, str) else ""


def parse_pending(payload: Any) -> List[Request]:
    """`list_pending_permissions` structured content -> requests. Raises ValueError on a shape that is not Paseo's:
    a daemon answer that cannot be read must never approve anything."""
    if not isinstance(payload, dict) or not isinstance(payload.get("permissions"), list):
        raise ValueError("unexpected list_pending_permissions shape")
    out: List[Request] = []
    for item in payload["permissions"]:
        if not isinstance(item, dict) or not isinstance(item.get("request"), dict):
            raise ValueError("malformed pending permission")
        r = item["request"]
        agent, rid = item.get("agentId"), r.get("id")
        if not isinstance(agent, str) or not agent or not isinstance(rid, str) or not rid:
            raise ValueError("pending permission without ids")
        out.append(Request(
            agent_id=agent, request_id=rid, provider=_s(r.get("provider")), name=_s(r.get("name")), kind=_s(r.get("kind")),
            title=_s(r.get("title")), description=_s(r.get("description")),
            input=r["input"] if isinstance(r.get("input"), dict) else None,
            detail=r["detail"] if isinstance(r.get("detail"), dict) else None,
            metadata=r["metadata"] if isinstance(r.get("metadata"), dict) else None))
    return out


# ---------------------------------------------------------------- the policy


@dataclass(frozen=True)
class Decision:
    allow: bool
    rule: str            # why: `allow:window` or the rule that keeps it pending (`kind:plan`, `denylist:sudoers`, ...)
    subject: str = ""    # command (or path, or tool name) prefix for the audit line; credential-looking text redacted


# Content keys: text the agent wrote INTO a file or a prompt. Not scanned (a doc that mentions sudoers is not an edit of it);
# the target of a write is a path key, which is scanned. `description` inside a tool's input is the agent's own gloss.
CONTENT_KEYS = frozenset(k.replace("_", "").casefold() for k in (
    "content", "text", "new_string", "old_string", "newText", "oldText", "unifiedDiff", "diff", "patch", "output", "plan",
    "prompt", "questions", "message", "body", "result", "log", "stdout", "stderr", "description", "options", "label"))
COMMAND_KEYS = frozenset(k.replace("_", "").casefold() for k in (
    "command", "cmd", "script", "code", "argv", "args", "commandline", "shell"))
PATH_KEYS = frozenset(k.replace("_", "").casefold() for k in (
    "file_path", "filePath", "path", "paths", "notebook_path", "filename", "filepaths", "files", "directory", "dir",
    "cwd", "target", "destination", "source", "worktreePath", "from", "to", "pattern", "glob", "url"))
COMMAND_TOOL_NAMES = frozenset({"bash", "codexbash", "shell", "exec", "execute", "run_shell_command", "terminal", "powershell"})
FILE_TOOL_NAMES = frozenset({"write", "edit", "multiedit", "notebookedit", "read", "codexfilechange", "applypatch",
                             "apply_patch", "fileedit", "filewrite", "create", "delete", "move"})
# Names that are a question, plan or mode change meant for the operator (copied from bin/ade-auto-permit STEMS: its list
# was read from Paseo's source). A `kind` other than "tool" stays pending too; Paseo sets it for Claude, Codex, Pi and OMP.
QUESTION_STEMS = ("question", "elicit", "askuser", "userinput", "exitplan", "enterplan", "planmode", "planapproval",
                  "switchmode", "requestinput")

# (b) the sudo-ask denylist targets, mirroring roles/sudo_ask_grant/files/sudo-ask-granted (PROTECTED, TRIPWIRE, ALWAYS_DENY,
# the diskutil/dscl/security verb lists). Substrings are matched case-folded anywhere in a path or command string.
TRIPWIRES = ("sudoers", "pam.d", "usr/lib/pam", "sudo.conf", "sudo-ask-grant", "sudo-ask-granted", "/db/sudo-ask",
             "secretspec", "com.apple.tcc", "tcc.db", "library/keychains", ".keychain", "dslocal",
             "/usr/local/libexec", "/usr/local/sbin", "/var/log/sudo-ask")
NAME_DENY = frozenset("visudo csrutil nvram tccutil fdesetup passwd pwpolicy profiles systemsetup dseditgroup sysadminctl "
                      "fdisk gpt asr sudo-secretspec sudo-ask-granted".split())
NAME_DENY_PREFIX = ("newfs_", "mkfs")
SYSTEM_DIRS = frozenset({"/bin", "/sbin", "/usr/bin", "/usr/sbin", "/usr/local/bin", "/usr/local/sbin", "/opt/homebrew/bin",
                         "/usr/libexec", "/usr/local/libexec", "/System/Library/CoreServices", "/usr/lib"})
DISKUTIL_OK = frozenset({"list", "info", "activity", "listfilesystems", "mount", "mountdisk", "unmount", "unmountdisk",
                         "eject", "verifyvolume", "verifydisk"})
DISKUTIL_SUB_OK = frozenset({"list", "listcryptousers", "listsnapshots", "listvolumegroups"})
DSCL_WRITE = frozenset({"create", "delete", "change", "append", "merge", "passwd", "createpl", "createpli", "changei",
                        "appendpl", "appendpli", "deletepl", "deletepli", "mcxset", "mcxedit", "mcxdelete", "mcxexport",
                        "mcximport", "diff"})
DSCL_READ = frozenset({"read", "readall", "readpl", "readpli", "list", "search", "ls", "cat"})
SECURITY_OK = frozenset({"find-certificate", "find-identity", "show-keychain-info", "verify-cert", "error", "help",
                         "list-keychains"})

# (a) critical-path removal.
REMOVERS = frozenset({"rm", "rmdir", "unlink", "srm", "shred"})
RECURSIVE_CHANGERS = frozenset({"chmod", "chown", "chgrp", "chflags"})
CRITICAL_EXACT = frozenset({
    "/", "/users", "/system", "/usr", "/etc", "/var", "/private", "/volumes", "/bin", "/sbin", "/opt", "/library",
    "/applications", "/cores", "/dev", "/home", "/tmp", "/private/var", "/private/etc", "/private/tmp", "/usr/local",
    "/opt/homebrew"})
CRITICAL_TREES = ("/system", "/bin", "/sbin", "/usr/bin", "/usr/sbin", "/usr/lib", "/usr/libexec", "/etc", "/private/etc",
                  "/private/var/db", "/var/db")
CRITICAL_REASON = re.compile(r"critical\s+(?:system\s+)?(?:path|director)", re.I)

_SECRET = re.compile(
    r"(?i)\b(?:proxy-)?authorization\b[\s:=]*(?:(?:bearer|basic|token)\s+)?\S+"
    r"|(?i:\bbearer\s+)\S+"
    r"|(?i:\b(?:token|secret|passwd|password|apikey|api[_-]?key)\b\s*[=:]\s*)\S+"
    r"|(?i:--?(?:token|secret|password|passwd|api-?key)[=\s]+)\S+"
    r"|(?:gh[pousr]_|github_pat_|sk-|sk_(?:live|test)_|xox[a-z]-|glpat-|AIza)[A-Za-z0-9_\-]{8,}|AKIA[0-9A-Z]{16}"
    r"|[A-Za-z0-9+/=]{40,}")


def redact(text: str) -> str:
    return _SECRET.sub("<redacted>", text)


def _harvest(obj: Any, out: List[Tuple[str, str]], key: str = "", depth: int = 0) -> None:
    """Every string in `obj` as (normalised key, text), minus content keys. Depth-limited; lists keep their parent's key."""
    if depth > 8:
        return
    if isinstance(obj, str):
        out.append((key, obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            nk = str(k).replace("_", "").casefold()
            if nk in CONTENT_KEYS:
                continue
            _harvest(v, out, nk, depth + 1)
    elif isinstance(obj, (list, tuple)):
        if key in COMMAND_KEYS and obj and all(isinstance(v, str) for v in obj):
            out.append((key, " ".join(shlex.quote(v) for v in obj)))       # an argv list is one command
            return
        for v in obj:
            _harvest(v, out, key, depth + 1)


def _gather(req: Request) -> Tuple[List[str], List[str], List[str]]:
    """(commands, paths, all scanned text) from every field Paseo's providers fill."""
    pairs: List[Tuple[str, str]] = []
    for text in (req.title, req.description):
        if text:
            pairs.append(("", text))
    for part in (req.input, req.detail, req.metadata):
        if part is not None:
            _harvest(part, pairs)
    commands, paths, texts = [], [], []
    for key, text in pairs:
        texts.append(text)
        if key in COMMAND_KEYS:
            commands.append(text)
        elif key in PATH_KEYS:
            paths.append(text)
    if req.title.startswith("Run command: "):          # Codex titles its command card this way
        commands.append(req.title[len("Run command: "):])
    return commands, paths, texts


def _unreadable(req: Request, commands: List[str], paths: List[str], texts: List[str]) -> Optional[str]:
    """Why the request's command or details cannot be read (it then stays pending), else None."""
    name = req.name.replace("_", "").casefold()
    if any(len(t) > MAX_TEXT_CHARS for t in texts):
        return "too-large"
    shell_detail = isinstance(req.detail, dict) and req.detail.get("type") == "shell"
    command_tool = name in {n.replace("_", "") for n in COMMAND_TOOL_NAMES} or shell_detail or (
        req.input is not None and any(str(k).replace("_", "").casefold() in COMMAND_KEYS for k in req.input))
    if command_tool:
        return None if any(c.strip() for c in commands) else "no-command"
    file_tool = name in {n.replace("_", "") for n in FILE_TOOL_NAMES} or "filechange" in name
    if file_tool:
        return None if any(p.strip() for p in paths) else "no-path"
    if req.input is None and req.detail is None and not req.title and not req.description:
        return "no-details"
    return None


def _segments(text: str, depth: int = 0) -> Iterable[List[str]]:
    """Token lists of every command segment in `text`, descending into quoted `sh -c '...'` style arguments."""
    if depth > 4:
        return
    for seg in re.split(r"[;&|\n`]+|\$\(|\)", text):
        seg = seg.strip()
        if not seg:
            continue
        try:
            toks = shlex.split(seg, comments=False, posix=True)
        except ValueError:
            toks = seg.split()
        yield toks
        for tok in toks:
            if len(tok) > 3 and re.search(r"[\s;&|]", tok):
                for inner in _segments(tok, depth + 1):
                    yield inner


def _is_program(token: str, names: Iterable[str]) -> Optional[str]:
    """The program name when `token` is that bare name, or a path to it in a system/tool directory."""
    base = posixpath.basename(token)
    if base not in names:
        return None
    directory = posixpath.dirname(token)
    return base if directory == "" or directory in SYSTEM_DIRS else None


# Wrappers a command can hide behind, and the flags of theirs that take a value (so `sudo -u root visudo` finds visudo).
WRAPPERS = {"sudo": {"-u", "-g", "-h", "-p", "-C", "-r", "-t", "-T", "-U", "-D", "-R"}, "env": {"-u", "-C", "-S"},
            "nohup": set(), "time": set(), "nice": {"-n"}, "command": set(), "exec": set(), "caffeinate": {"-t", "-w"},
            "arch": {"-arch"}, "stdbuf": {"-i", "-o", "-e"}, "timeout": {"-s", "-k"}, "xargs": {"-n", "-I", "-L", "-P", "-s", "-E"},
            "sudo-ask": set(), "rtk": set(), "bgrun": set(), "bg": set()}
# Names that are also ordinary words or arguments (`echo passwd`, `ls security`): judged only where a command would stand.
COMMAND_POSITION_ONLY = frozenset({"passwd", "profiles", "gpt", "asr", "security", "diskutil", "dscl"})


def _command_positions(toks: List[str]) -> set:
    """Indexes in `toks` where a command may stand: the first word, the one after a wrapper (and its options),
    and the one after find's -exec/-execdir/-ok/-okdir."""
    positions: set = set()
    i = 0
    while i < len(toks):
        while i < len(toks) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", toks[i]):
            i += 1
        if i >= len(toks):
            break
        positions.add(i)
        wrapper = posixpath.basename(toks[i])
        if wrapper not in WRAPPERS:
            break
        i += 1
        while i < len(toks) and (toks[i].startswith("-") or re.fullmatch(r"[0-9.]+[smhd]?", toks[i])):
            i += 2 if toks[i] in WRAPPERS[wrapper] else 1
    for j, tok in enumerate(toks):
        if tok in ("-exec", "-execdir", "-ok", "-okdir") and j + 1 < len(toks):
            positions.add(j + 1)
    return positions


def _denylist_hit(commands: List[str], paths: List[str], texts: List[str]) -> Optional[str]:
    for text in texts:
        low = text.casefold()
        for tripwire in TRIPWIRES:
            if tripwire in low:
                return tripwire
    for text in commands + paths:
        for toks in _segments(text):
            at = _command_positions(toks)
            for i, tok in enumerate(toks):
                base = posixpath.basename(tok)
                judged = i in at or base not in COMMAND_POSITION_ONLY
                if not judged:
                    continue
                if _is_program(tok, NAME_DENY) or (_is_program(tok, [base]) and base.startswith(NAME_DENY_PREFIX)):
                    if base in COMMAND_POSITION_ONLY and i not in at:
                        continue
                    return base
                args = toks[i + 1:]
                if i not in at:
                    continue
                if _is_program(tok, ["diskutil"]):
                    verbs = [a.lower() for a in args if not a.startswith("-")]
                    verb = verbs[0] if verbs else ""
                    if verb in ("apfs", "cs", "appleraid", "corestorage"):
                        verb = verbs[1] if len(verbs) > 1 else ""
                        if verb not in DISKUTIL_SUB_OK:
                            return "diskutil " + (verb or "?")
                    elif verb not in DISKUTIL_OK:
                        return "diskutil " + (verb or "?")
                elif _is_program(tok, ["dscl"]):
                    low = {a.lstrip("-").lower() for a in args}
                    if low & DSCL_WRITE or not low & DSCL_READ:
                        return "dscl write"
                elif _is_program(tok, ["security"]):
                    verbs = [a for a in args if not a.startswith("-")]
                    verb = verbs[0] if verbs else ""
                    if verb not in SECURITY_OK or (verb == "list-keychains" and any(a.startswith(("-s", "-d")) for a in args)):
                        return "security " + (verb or "?")
                elif tok == "sudo-ask" or tok.endswith("/sudo-ask"):
                    if any(a in ("grant", "revoke", "--grant", "--revoke") for a in args):
                        return "sudo-ask window change"
    return None


def _expand(arg: str, home: str) -> Optional[str]:
    """An rm argument as a path with variables modelled as EMPTY (the failure Claude Code's own check warns about:
    `rm -rf $S/` with S unset is `rm -rf /`). None when it cannot be modelled (command substitution)."""
    if "$(" in arg or "`" in arg:
        return None
    if arg == "~" or arg.startswith("~/"):
        arg = home + arg[1:]
    elif arg.startswith("~"):
        return "/users"                      # ~someone: treated as a home root, kept pending
    arg = re.sub(r"\$\{HOME\}|\$HOME\b", home, arg)
    arg = re.sub(r"\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*", "", arg)
    return arg


def _critical_path(arg: str, home: str) -> Optional[str]:
    expanded = _expand(arg, home)
    if not expanded or not expanded.startswith("/"):
        return None                          # empty or relative (no cwd known): not named as a critical path
    core = re.sub(r"(?:/(?:\*\*|\.\*|\*))+/*$", "", expanded)   # `D/*`, `D/.*` and `D/**` reach everything in D
    core = core or "/"
    cands = {posixpath.normpath(core)}
    cands.add(os.path.realpath(core))        # /etc is /private/etc; a symlink cannot hide a target
    home_cf = posixpath.normpath(home).casefold()
    for cand in cands:
        low = cand.casefold()
        if low in CRITICAL_EXACT or low == home_cf:
            return cand
        if any(low == t or low.startswith(t + "/") for t in CRITICAL_TREES):
            return cand
        parts = [p for p in low.split("/") if p]
        if len(parts) == 2 and parts[0] in ("users", "volumes"):      # a home directory or a volume root
            return cand
    return None


def _critical_removal(commands: List[str], home: str) -> Optional[str]:
    for text in commands:
        for toks in _segments(text):
            for i, tok in enumerate(toks):
                name = _is_program(tok, REMOVERS | RECURSIVE_CHANGERS | {"find"})
                if not name:
                    continue
                args = toks[i + 1:]
                flags = [a for a in args if a.startswith("-") and a != "--"]
                operands = [a for a in args if not a.startswith("-")]
                if name == "find":
                    if "-delete" not in args:
                        continue
                    operands = []
                    for a in args:
                        if a.startswith(("-", "(", "!")):
                            break
                        operands.append(a)
                elif name in RECURSIVE_CHANGERS:
                    if not any(re.fullmatch(r"-[A-Za-z]*R[A-Za-z]*", f) or f == "--recursive" for f in flags):
                        continue
                    operands = [a for a in operands if a.startswith(("/", "~", "$"))]
                for operand in operands:
                    hit = _critical_path(operand, home)
                    if hit:
                        return "%s %s" % (name, hit)
    return None


def decide(req: Request, home: Optional[str] = None) -> Decision:
    """Allow or keep pending. Window state is the caller's business (`sweep`, the hook)."""
    home = home or os.path.expanduser("~")
    commands, paths, texts = _gather(req)
    subject = redact((commands[0] if commands else (paths[0] if paths else (req.title or req.name))).strip())
    subject = subject[:COMMAND_PREFIX_CHARS]

    def hold(rule: str) -> Decision:
        return Decision(False, rule, subject)

    if req.kind != "tool":
        return hold("kind:" + (req.kind or "missing"))
    compact = re.sub(r"[^a-z0-9]", "", req.name.casefold())
    if not compact:
        return hold("missing-name")
    for stem in QUESTION_STEMS:
        if stem in compact:
            return hold("question:" + stem)
    why = _unreadable(req, commands, paths, texts)
    if why:
        return hold("unreadable:" + why)
    hit = _denylist_hit(commands, paths, texts)
    if hit:
        return hold("denylist:" + hit)
    reason_text = " ".join(t for t in (req.title, req.description) if t)
    if CRITICAL_REASON.search(reason_text):
        return hold("critical-reason")
    crit = _critical_removal(commands, home)
    if crit:
        return hold("critical-rm:" + crit)
    return Decision(True, "allow:window", subject)


def claude_hook_request(tool_name: str, tool_input: Any) -> Request:
    """A Claude Code PermissionRequest hook's stdin as a Request (provider claude)."""
    kind = {"ExitPlanMode": "plan", "AskUserQuestion": "question"}.get(tool_name, "tool")
    return Request(agent_id="", request_id="", provider="claude", name=tool_name, kind=kind, title="", description="",
                   input=tool_input if isinstance(tool_input, dict) else None, detail=None, metadata=None)


# ---------------------------------------------------------------- the audit log


class AuditLog:
    """Append-only JSONL, 0600 in a 0700 directory. A line that cannot be written aborts the action it describes."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def write(self, **fields: Any) -> None:
        row = {"time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        row.update(fields)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(str(self.path), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), 0o600)
        try:
            os.write(fd, (json.dumps(row, sort_keys=True) + "\n").encode("utf-8"))
        finally:
            os.close(fd)

    def decision(self, req: Request, decision: str, rule: str, subject: str) -> None:
        self.write(agent=req.agent_id, provider=req.provider, tool=req.name, request=req.request_id,
                   command=subject[:COMMAND_PREFIX_CHARS], decision=decision, rule=rule)


# ---------------------------------------------------------------- Paseo's loopback Agent MCP route


class DaemonError(Exception):
    """The daemon could not be listed or answered; nothing is approved on this evidence."""


Opener = Callable[[str, bytes, Dict[str, str], float], Tuple[int, str, bytes]]


def urllib_opener(url: str, body: bytes, headers: Dict[str, str], timeout: float) -> Tuple[int, str, bytes]:
    no_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # a loopback call never goes through a proxy
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with no_proxy.open(request, timeout=timeout) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read(8_000_000)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", "") if exc.headers else "", exc.read(65_536)


class McpDaemon:
    """`list_pending_permissions` and `respond_to_permission` over Paseo's Agent MCP route (stateless streamable HTTP).

    Source: packages/server/src/server/agent/tools/paseo-tools.ts lines 3211-3273 (the two tools), bootstrap.ts around 1537
    (the route, no session, no password when none is configured). The `paseo permit ls --json` rows carry no command
    (packages/cli/src/commands/permit/ls.ts lines 8-14 and 28-38: id, agentId, name, description only), so the CLI cannot show what a
    Bash request would run; the MCP tool returns the whole request (input, detail, metadata)."""

    def __init__(self, url: str = DEFAULT_DAEMON_URL, opener: Opener = urllib_opener, timeout: float = 10.0) -> None:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname or ""
        if parsed.scheme != "http" or host not in LOOPBACK_HOSTS or parsed.path != "/mcp/agents" or parsed.query:
            raise DaemonError("daemon URL must be http://<loopback>:<port>/mcp/agents")
        self.url, self.opener, self.timeout, self._id = url, opener, timeout, 0

    def _call(self, tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self._id += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self._id, "method": "tools/call",
                           "params": {"name": tool, "arguments": arguments}}).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        try:
            status, ctype, raw = self.opener(self.url, body, headers, self.timeout)
        except (OSError, urllib.error.URLError, ValueError) as exc:
            raise DaemonError("daemon unreachable: %s" % type(exc).__name__) from exc
        if status != 200:
            raise DaemonError("daemon answered HTTP %s" % status)
        text = raw.decode("utf-8", "replace")
        messages: List[Any] = []
        try:
            if "text/event-stream" in ctype:
                messages = [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]
            else:
                messages = [json.loads(text)]
        except ValueError as exc:
            raise DaemonError("daemon answer is not JSON") from exc
        for msg in messages:
            if isinstance(msg, dict) and msg.get("id") == self._id:
                if "error" in msg:
                    raise DaemonError("daemon refused %s" % tool)
                result = msg.get("result")
                if not isinstance(result, dict) or result.get("isError"):
                    raise DaemonError("%s failed" % tool)
                structured = result.get("structuredContent")
                if not isinstance(structured, dict):
                    raise DaemonError("%s returned no structured content" % tool)
                return structured
        raise DaemonError("no answer to %s" % tool)

    def list_pending(self) -> List[Request]:
        try:
            return parse_pending(self._call("list_pending_permissions", {}))
        except ValueError as exc:
            raise DaemonError(str(exc)) from exc

    def allow(self, agent_id: str, request_id: str) -> None:
        answer = self._call("respond_to_permission", {"agentId": agent_id, "requestId": request_id,
                                                      "response": {"behavior": "allow"}})
        if answer.get("success") is not True:
            raise DaemonError("allow not confirmed")


# ---------------------------------------------------------------- one sweep


@dataclass
class SweepResult:
    window: Window
    allowed: int = 0
    held: int = 0
    errors: int = 0


def sweep(daemon: Any, log: AuditLog, *, grant_path: str = GRANT_PATH, now: Optional[Callable[[], float]] = None,
          owner_uid: int = OWNER_UID, home: Optional[str] = None, seen: Optional[set] = None) -> SweepResult:
    """One pass. Window closed: returns without touching the daemon. `seen` (a set kept by `watch`) logs each held request once."""
    clock = now or time.time
    window = read_window(grant_path, clock(), owner_uid)
    result = SweepResult(window)
    if not window.open:
        return result
    try:
        pending = daemon.list_pending()
    except DaemonError as exc:
        result.errors += 1
        _log_error(log, "list", str(exc), seen)
        return result
    for req in pending:
        decision = decide(req, home)
        if not decision.allow:
            result.held += 1
            key = (req.agent_id, req.request_id, decision.rule)
            if seen is None or key not in seen:
                log.decision(req, "hold", decision.rule, decision.subject)
                if seen is not None:
                    seen.add(key)
            continue
        if not read_window(grant_path, clock(), owner_uid).open:    # expired or revoked since the sweep began
            break
        log.decision(req, "allow", decision.rule, decision.subject)  # audit first: a log that fails aborts the allow
        try:
            daemon.allow(req.agent_id, req.request_id)
            result.allowed += 1
        except DaemonError as exc:
            result.errors += 1
            log.decision(req, "error", "allow-failed:" + str(exc)[:80], decision.subject)
    return result


def _log_error(log: AuditLog, where: str, message: str, seen: Optional[set]) -> None:
    key = ("error", where, message)
    if seen is not None:
        if key in seen:
            return
        seen.add(key)
    log.write(agent="", provider="", tool="", request="", command="", decision="error", rule="%s:%s" % (where, message[:120]))


# ---------------------------------------------------------------- the CLI (bin/ade-approval-window)


def _lock(path: Path) -> Any:
    """One responder per audit path: an overlapping launchd run must not double-answer. None when another holds it."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = open(str(path) + ".lock", "a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        if exc.errno in (errno.EAGAIN, errno.EACCES):
            return None
        raise
    return handle


def _status_text(w: Window) -> str:
    if not w.open:
        return "approval window: closed (%s)" % w.reason
    r = w.remaining_s or 0
    return "approval window: OPEN, %dh%02dm left (expires %s)" % (
        r // 3600, (r % 3600) // 60, datetime.fromtimestamp(w.expires_epoch or 0, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


USAGE = """usage: ade-approval-window status [--json]
       ade-approval-window respond --once [--daemon-url URL] [--log FILE]
       ade-approval-window watch [--interval S] [--duration S] [--daemon-url URL] [--log FILE]

status   whether the sudo-ask approval window is open (exit 0 open, 1 closed); never contacts the daemon
respond  one sweep: while the window is open, allow pending agent permission requests except the ones docs/approval-window.md keeps
watch    sweeps every INTERVAL seconds (at least 2), contacting the daemon only while a grant file exists; --duration bounds the run
"""


def main(argv: List[str], *, daemon: Any = None, grant_path: str = GRANT_PATH, owner_uid: int = OWNER_UID,
         log_path: Optional[Path] = None, now: Optional[Callable[[], float]] = None, out: Any = None,
         sleep: Callable[[float], None] = time.sleep, monotonic: Callable[[], float] = time.monotonic,
         home: Optional[str] = None) -> int:
    out = out or sys.stdout
    args = list(argv)
    if not args or args[0] in ("-h", "--help"):
        out.write(USAGE)
        return 0 if args else 64
    cmd, rest = args[0], args[1:]
    clock = now or time.time

    def option(name: str, default: Optional[str] = None) -> Optional[str]:
        if name in rest:
            i = rest.index(name)
            if i + 1 >= len(rest):
                raise ValueError(name + " needs a value")
            return rest[i + 1]
        return default

    try:
        if cmd == "status":
            if any(a not in ("--json",) for a in rest):
                out.write(USAGE)
                return 64
            w = read_window(grant_path, clock(), owner_uid)
            if "--json" in rest:
                out.write(json.dumps({"open": w.open, "reason": w.reason, "expires_epoch": w.expires_epoch,
                                      "remaining_s": w.remaining_s}) + "\n")
            else:
                out.write(_status_text(w) + "\n")
            return 0 if w.open else 1
        if cmd not in ("respond", "watch"):
            out.write(USAGE)
            return 64
        if cmd == "respond" and "--once" not in rest:
            out.write("respond needs --once (one sweep); use watch to keep sweeping\n")
            return 64
        known = {"--once", "--daemon-url", "--log"} | ({"--interval", "--duration"} if cmd == "watch" else set())
        values = {"--daemon-url", "--log", "--interval", "--duration"}
        i = 0
        while i < len(rest):
            if rest[i] not in known:
                out.write("unknown option %s\n" % rest[i])
                return 64
            i += 2 if rest[i] in values else 1
        log = AuditLog(Path(option("--log") or log_path or default_log_path()))
        if daemon is None:
            daemon = McpDaemon(option("--daemon-url", DEFAULT_DAEMON_URL) or DEFAULT_DAEMON_URL)
        lock = _lock(log.path)
        if lock is None:
            out.write("another responder holds the lock; nothing done\n")
            return 1
        seen: set = set()
        try:
            if cmd == "respond":
                res = sweep(daemon, log, grant_path=grant_path, now=clock, owner_uid=owner_uid, home=home, seen=seen)
                out.write("%s; allowed %d, held %d, errors %d\n" % (_status_text(res.window), res.allowed, res.held, res.errors))
                return 1 if res.errors else 0
            interval = max(MIN_POLL_S, float(option("--interval", "2") or 2))
            duration = float(option("--duration", "0") or 0)
            deadline = monotonic() + duration if duration > 0 else None
            code = 0
            while deadline is None or monotonic() < deadline:
                if os.path.lexists(grant_path):                   # no grant file: the daemon is never contacted
                    res = sweep(daemon, log, grant_path=grant_path, now=clock, owner_uid=owner_uid, home=home, seen=seen)
                    code = 1 if res.errors else 0
                wait = interval if deadline is None else min(interval, max(0.0, deadline - monotonic()))
                if deadline is not None and wait <= 0:
                    break
                sleep(wait)
            return code
        finally:
            lock.close()
    except (ValueError, DaemonError) as exc:
        out.write("ade-approval-window: %s\n" % exc)
        return 64
    except OSError as exc:                  # e.g. the audit log cannot be written: nothing was allowed for that request
        out.write("ade-approval-window: %s\n" % exc)
        return 1
    except KeyboardInterrupt:
        return 130
