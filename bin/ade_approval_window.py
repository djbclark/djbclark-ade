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
from collections import Counter
from dataclasses import dataclass, field
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
                      "fdisk gpt asr sudo-secretspec sudo-ask-granted sntp ntpdate su login at batch chroot".split())
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
LAUNCHCTL_RUNS = frozenset({"submit", "asuser", "bootstrap", "load", "enable", "kickstart"})
# Path roots the site helper protects (site-public-djbclark roles/sudo_ask_grant/files/sudo-ask-granted at f6dd14ba, PROTECTED and
# PROTECTED_RE, incl. the persistence paths a root process could use to outlive the window). Compared on a case-folded realpath.
PROTECTED = (
    "/private/etc/sudoers", "/private/etc/sudoers.d", "/private/etc/sudo.conf", "/private/etc/pam.d", "/usr/lib/pam",
    "/private/var/db/sudo-ask", "/private/var/log/sudo-ask-grant.log", "/usr/local/libexec", "/usr/local/sbin",
    "/private/var/db/dslocal", "/library/application support/com.apple.tcc", "/private/var/db/tcc", "/library/keychains",
    "/library/launchdaemons", "/library/launchagents", "/library/startupitems", "/private/var/at", "/usr/lib/cron",
    "/private/etc/periodic", "/private/etc/zshenv", "/private/etc/zprofile", "/private/etc/zshrc", "/private/etc/profile",
    "/private/etc/bashrc", "/private/var/root", "/private/etc/ssh", "/library/security/securityagentplugins",
    "/private/etc/ld.so.conf")
PROTECTED_RE = (r"^/private/etc/paths(\.d(/|$)|$)", r"/users/[^/]+/library/application support/com\.apple\.tcc(/|$)",
                r"/users/[^/]+/library/keychains(/|$)", r"(^|/)login\.keychain[^/]*$", r"^/dev/r?disk")
# Commands the site helper treats as read-only (no protected-path check on their arguments; the tripwire strings still apply).
READ_ONLY = frozenset("ls stat file cat head tail wc grep egrep fgrep rg readlink realpath du df basename dirname id whoami "
                      "test [ echo printf true false : pwd ps lsof shasum md5 cmp diff strings hexdump uname sw_vers which "
                      "mdfind sleep".split())

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


class Unparsable(Exception):
    """A command line this module cannot read with confidence: the request stays pending."""


@dataclass
class Stmt:
    """One simple command of a command line: its words with shell quoting removed."""
    words: List[str] = field(default_factory=list)
    subst: set = field(default_factory=set)            # indexes of words holding a command/process substitution
    quoted: set = field(default_factory=set)           # indexes of words that were written with quotes or backslashes
    opens: int = 0                                     # `(` seen since the previous statement (a subshell starts here)
    closes: int = 0                                    # `)` seen since the previous statement (a subshell ended before this one)
    wordsubs: Dict[int, List[str]] = field(default_factory=dict)   # word index -> bodies of the substitutions in it
    redirs: List[str] = field(default_factory=list)    # redirection targets (writes, as far as this module cares)
    heredocs: List[list] = field(default_factory=list)  # [delimiter, quoted, body]
    herestring: bool = False
    herewords: List[str] = field(default_factory=list)  # the words of `<<< WORD`
    sep: str = ""                                      # what ended the statement before this one: ; && || | & newline ( )


_BLANK = " \t\r\f\v"
_OPCHARS = ";&|()<>\n"
MAX_DEPTH = 4


def _match_paren(text: str, i: int) -> int:
    """Index of the `)` that closes a `(` already consumed (i is the first character after it). Quote and heredoc aware."""
    depth, n = 1, len(text)
    pend: List[Tuple[str, bool]] = []
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
        elif c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                raise Unparsable("unbalanced quote")
            i = j + 1
        elif c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            if i >= n:
                raise Unparsable("unbalanced quote")
            i += 1
        elif c == "<" and text.startswith("<<", i) and not text.startswith("<<<", i):
            k = i + 2
            strip = text[k:k + 1] == "-"
            k += 1 if strip else 0
            while k < n and text[k] in " \t":
                k += 1
            m = re.match(r"""'([^']*)'|"([^"]*)"|\\?([A-Za-z0-9_.\-]+)""", text[k:])
            if m:
                pend.append((next(g for g in m.groups() if g is not None), strip))
                i = k + m.end()
            else:
                i += 2
        elif c == "\n" and pend:
            i += 1
            for delim, strip in pend:
                while i < n:
                    j = text.find("\n", i)
                    line = text[i:] if j < 0 else text[i:j]
                    i = n if j < 0 else j + 1
                    if (line.lstrip("\t") if strip else line) == delim:
                        break
            pend = []
        else:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return i
            i += 1
    raise Unparsable("unbalanced parenthesis")


def _match_backtick(text: str, i: int) -> int:
    n = len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
        elif text[i] == "`":
            return i
        else:
            i += 1
    raise Unparsable("unbalanced backtick")


def _read_word(text: str, i: int, nested: List[str]) -> Tuple[str, int, bool, bool]:
    """(word with quoting removed, next index, holds a substitution, was quoted). Substitution bodies go to `nested`."""
    n, out, sub, quoted = len(text), [], False, False
    while i < n:
        c = text[i]
        if c in _BLANK or c in _OPCHARS:
            break
        if c == "\\":
            if i + 1 >= n:
                out.append("\\")
                i += 1
            elif text[i + 1] == "\n":
                i += 2
            else:
                out.append(text[i + 1])
                i += 2
                quoted = True
        elif c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                raise Unparsable("unbalanced quote")
            out.append(text[i + 1:j])
            i = j + 1
            quoted = True
        elif c == '"':
            i += 1
            quoted = True
            while True:
                if i >= n:
                    raise Unparsable("unbalanced quote")
                d = text[i]
                if d == '"':
                    i += 1
                    break
                if d == "\\" and i + 1 < n:
                    e = text[i + 1]
                    if e == "\n":
                        i += 2
                    elif e in '"\\$`':
                        out.append(e)
                        i += 2
                    else:
                        out.append("\\")
                        i += 1
                elif d == "$" and text[i + 1:i + 2] == "(":
                    j = _match_paren(text, i + 2)
                    nested.append(text[i + 2:j])
                    out.append("$(SUB)")
                    sub, i = True, j + 1
                elif d == "`":
                    j = _match_backtick(text, i + 1)
                    nested.append(text[i + 1:j])
                    out.append("$(SUB)")
                    sub, i = True, j + 1
                else:
                    out.append(d)
                    i += 1
        elif c == "$" and text[i + 1:i + 2] == "'":                  # $'...': ANSI-C quoting, read as the shell reads it
            j = i + 2
            while j < n and text[j] != "'":
                j += 2 if text[j] == "\\" else 1
            if j >= n:
                raise Unparsable("unbalanced quote")
            out.append(_ansi_c(text[i + 2:j]))
            quoted = True
            i = j + 1
        elif c == "$" and text[i + 1:i + 2] == '"':                  # $"...": locale quoting, a plain double quote here
            i += 1
        elif c == "$" and text[i + 1:i + 2] == "(":
            j = _match_paren(text, i + 2)
            nested.append(text[i + 2:j])
            out.append("$(SUB)")
            sub, i = True, j + 1
        elif c == "`":
            j = _match_backtick(text, i + 1)
            nested.append(text[i + 1:j])
            out.append("$(SUB)")
            sub, i = True, j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out), i, sub, quoted


_ANSI_SIMPLE = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v", "e": "\x1b", "E": "\x1b",
                "\\": "\\", "'": "'", '"': '"', "?": "?"}


def _ansi_c(body: str) -> str:
    """The text of a `$'...'` word: backslash escapes decoded (`$'\\x72m'` is `rm`)."""
    out, i, n = [], 0, len(body)
    while i < n:
        c = body[i]
        if c != "\\" or i + 1 >= n:
            out.append(c)
            i += 1
            continue
        e = body[i + 1]
        if e in _ANSI_SIMPLE:
            out.append(_ANSI_SIMPLE[e])
            i += 2
            continue
        m = None
        if e == "x":
            m = re.match(r"[0-9A-Fa-f]{1,2}", body[i + 2:])
            value, width = (int(m.group(), 16), 2 + len(m.group())) if m else (0, 0)
        elif e in "01234567":
            m = re.match(r"[0-7]{1,3}", body[i + 1:])
            value, width = (int(m.group(), 8) & 0xFF, 1 + len(m.group())) if m else (0, 0)
        elif e in "uU":
            m = re.match(r"[0-9A-Fa-f]{1,8}", body[i + 2:])
            value, width = (int(m.group(), 16), 2 + len(m.group())) if m else (0, 0)
        if m:
            try:
                out.append(chr(value))
            except (ValueError, OverflowError):
                out.append("�")
            i += width
        else:
            out.append("\\" + e)
            i += 2
    return "".join(out)


def _substitutions_in(text: str) -> List[str]:
    """Bodies of `$(...)` and backtick substitutions in an unquoted here-document body (the shell runs those)."""
    out, i = [], 0
    while i < len(text):
        if text.startswith("$(", i):
            j = _match_paren(text, i + 2)
            out.append(text[i + 2:j])
            i = j + 1
        elif text[i] == "`":
            j = _match_backtick(text, i + 1)
            out.append(text[i + 1:j])
            i = j + 1
        elif text[i] == "\\":
            i += 2
        else:
            i += 1
    return out


def _tokenize(text: str) -> Tuple[List[Stmt], List[str]]:
    """Command line -> simple commands, read with the shell's quoting FIRST (so `sh -c 'a; b'` stays one word), plus the
    bodies of every substitution and unquoted here-document substitution. Raises Unparsable on anything doubtful."""
    stmts: List[Stmt] = []
    nested: List[str] = []
    pending: List[Tuple[list, bool]] = []
    state: Dict[str, Any] = {"cur": Stmt(), "sep": "", "opens": 0, "closes": 0}
    n, i = len(text), 0

    def end(new_sep: str, paren: bool = False) -> None:
        cur = state["cur"]
        appended = bool(cur.words or cur.redirs or cur.heredocs or cur.herestring)
        if appended:
            cur.sep = state["sep"]
            cur.opens, cur.closes = state["opens"], state["closes"]
            state["opens"] = state["closes"] = 0
            stmts.append(cur)
        state["cur"] = Stmt()
        if not paren:
            if not (not appended and new_sep == "\n" and state["sep"] in ("&&", "||", "|")):
                state["sep"] = new_sep                 # `a &&` + newline + `b`: the line break does not end the `&&`
        elif appended:
            state["sep"] = ";"                 # `(a) b`: sequential; `a && (b)` keeps the `&&` that joined it

    def redirect_target(at: int) -> int:
        while at < n and text[at] in _BLANK:
            at += 1
        if at < n and text[at] not in _OPCHARS:
            word, at, sub, _ = _read_word(text, at, nested)
            state["cur"].redirs.append(word)
            if sub:
                state["cur"].subst.add(-1)
        return at

    while i < n:
        c = text[i]
        cur = state["cur"]
        if c in _BLANK:
            i += 1
        elif c == "\n":
            end("\n")
            i += 1
            for hd, strip in pending:
                lines: List[str] = []
                while i < n:
                    j = text.find("\n", i)
                    line = text[i:] if j < 0 else text[i:j]
                    i = n if j < 0 else j + 1
                    if (line.lstrip("\t") if strip else line) == hd[0]:
                        break
                    lines.append(line)
                hd[2] = "\n".join(lines)
                if not hd[1]:
                    nested.extend(_substitutions_in(hd[2]))
            pending = []
        elif c == "#":
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif c == ";":
            end(";")
            i += 1
            while i < n and text[i] in ";&":
                i += 1
        elif c == "&":
            if text[i + 1:i + 2] == ">":
                i += 2
                if text[i:i + 1] == ">":
                    i += 1
                i = redirect_target(i)
            elif text[i + 1:i + 2] == "&":
                end("&&")
                i += 2
            else:
                end("&")
                i += 1
        elif c == "|":
            if text[i + 1:i + 2] == "|":
                end("||")
                i += 2
            else:
                end("|")
                i += 2 if text[i + 1:i + 2] == "&" else 1
        elif c in "()":
            if c == "(" and i > 0 and text[i - 1] == "=" and cur.words and cur.words[-1].endswith("="):
                cur.words[-1] += "("                   # `arr=(a b)`: an array, never an empty literal
            end(c, True)
            state["opens" if c == "(" else "closes"] += 1
            i += 1
        elif c in "<>":
            if text.startswith("<<<", i):
                i += 3
                while i < n and text[i] in _BLANK:
                    i += 1
                if i < n and text[i] not in _OPCHARS:
                    hw, i, _, _ = _read_word(text, i, nested)
                    cur.herewords.append(hw)
                cur.herestring = True
            elif text.startswith("<<", i):
                i += 2
                strip = text[i:i + 1] == "-"
                i += 1 if strip else 0
                while i < n and text[i] in _BLANK:
                    i += 1
                delim, i, _, quoted = _read_word(text, i, [])
                hd = [delim, quoted, ""]
                cur.heredocs.append(hd)
                pending.append((hd, strip))
            elif text[i + 1:i + 2] == "(":
                j = _match_paren(text, i + 2)
                nested.append(text[i + 2:j])
                cur.words.append("$(SUB)")
                cur.subst.add(len(cur.words) - 1)
                i = j + 1
            else:
                i += 1
                while i < n and text[i] in "<>":
                    i += 1
                if text[i:i + 1] in ("&", "|") and text[i:i + 1]:
                    i += 1
                i = redirect_target(i)
        else:
            before = len(nested)
            word, j, sub, quoted = _read_word(text, i, nested)
            if j == i:
                i += 1
                continue
            i = j
            if word.isdigit() and not quoted and i < n and text[i] in "<>":
                continue                      # a file descriptor prefix: 2>file
            cur.words.append(word)
            if quoted:
                cur.quoted.add(len(cur.words) - 1)
            if sub:
                cur.subst.add(len(cur.words) - 1)
                cur.wordsubs[len(cur.words) - 1] = nested[before:]
    end("")
    return stmts, nested


def _name(token: str) -> str:
    """The program a word names: its basename, with GNU's leading `g` (grm, gfind) taken off when the rest is known."""
    base = posixpath.basename(posixpath.normpath(token)) if token else ""
    if len(base) > 1 and base[0] == "g" and base[1:] in G_STRIPPABLE:
        return base[1:]
    return base


def _is_program(token: str, names: Iterable[str]) -> Optional[str]:
    """The program name when `token` is that bare name, or a path to it in a system/tool directory."""
    token = posixpath.normpath(token) if token else token
    base = posixpath.basename(token)
    if base not in names:
        return None
    directory = posixpath.dirname(token)
    return base if directory == "" or directory in SYSTEM_DIRS else None


# Wrappers a command can hide behind, and the flags of theirs that take a value (so `sudo -u root visudo` finds visudo).
WRAPPERS = {"sudo": {"-u", "-g", "-h", "-p", "-C", "-r", "-t", "-T", "-U", "-D", "-R", "--user", "--group", "--host", "--prompt",
                     "--chdir", "--role", "--type", "--other-user", "--close-from", "--command-timeout"},
            "env": {"-u", "-C", "--unset", "--chdir"},
            "nohup": set(), "time": set(), "nice": {"-n"}, "command": set(), "exec": {"-a"}, "caffeinate": {"-t", "-w"},
            "arch": {"-arch"}, "stdbuf": {"-i", "-o", "-e"}, "timeout": {"-s", "-k"},
            "xargs": {"-n", "-I", "-L", "-P", "-s", "-E", "-d", "-J", "-R", "-S", "-a"},
            "sudo-ask": set(), "rtk": set(), "bgrun": set(), "bg": set(), "noglob": set(), "nocorrect": set(), "builtin": set(),
            "coproc": set(), "-": set()}
# Programs whose arguments are text or data, never a command line they run: a remover word there is prose, not a removal.
NON_EXEC = frozenset("ls stat file cat head tail wc grep egrep fgrep rg readlink realpath du df basename dirname id whoami "
                     "test [ [[ echo printf true false : pwd ps lsof shasum md5 cmp diff strings hexdump uname sw_vers which "
                     "mdfind sleep git gh jq man type whereis help tldr paseo hermes-ping clip ref ref-append graft".split())
REMOVER_NAMES = frozenset({"rm", "rmdir", "unlink", "srm", "shred", "trash", "trash-put", "rip", "rimraf", "del-cli"})
# A remover word anywhere in a multi-word string (a shell body, a quoted command line): `rm`, `grm -rf`, `-delete`, `git clean`.
REMOVER_TEXT = re.compile(r"(?<![\w.$~-])(?:g?rm|g?rmdir|g?unlink|g?srm|g?shred|trash(?:-put)?|rip|rimraf|del-cli)(?![\w./-])"
                          r"|(?<![\w-])--?(?:delete|del)(?:-[a-z-]+)?(?![\w])|(?<![\w-])git\s+(?:-\S+\s+)*clean\b")
DEFINITION = re.compile(r"(?:^|[\s;&|(){}])(?:alias\s|function\s+\S|[A-Za-z_][\w.:-]*\s*\(\s*\))")
INTERPRETERS = re.compile(r"(?:python[0-9.]*|perl[0-9.]*|ruby[0-9.]*|node(?:js)?|osascript|php[0-9.]*|lua[0-9.]*|deno|bun)")
INTERPRETER_BAD = re.compile(r"rmtree|unlink|remove|rmdir|rm_rf?|rm_f|rmSync|\brm\s*[-(]|do\s+shell\s+script|delete|trash", re.I)
FIND_NAME_TESTS = frozenset({"-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename", "-lname", "-ilname"})
FIND_ALWAYS_NARROW = frozenset({"-empty", "-samefile", "-inum"})
FIND_OPERATORS = frozenset({"-o", "-or", "!", "-not", ","})
FIND_ACTIONS = frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir"})
# Runners that start an interpreter named later on their command line (`uv run python -c ...`, `npx node -e ...`).
RUNNERS = frozenset({"uv", "uvx", "pipx", "poetry", "npx", "bunx", "pnpm", "npm", "pdm", "rye", "hatch"})
G_STRIPPABLE = REMOVERS | RECURSIVE_CHANGERS | {"mv", "find", "xargs", "env", "nice", "timeout", "stdbuf", "date"}
COMPOUND_OPENERS = frozenset({"if", "while", "until", "for", "select", "case"})
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "csh", "tcsh", "fish", "ash"})
KEYWORDS = frozenset({"{", "}", "!", "if", "then", "do", "else", "elif", "while", "until", "fi", "done", "esac", "case",
                      "select", "function"})
SHELL_VALUE_FLAGS = frozenset({"-o", "+o", "-O", "+O", "--rcfile", "--init-file"})
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*", re.S)
# Names that are also ordinary words or arguments (`echo passwd`, `ls security`): judged only where a command would stand.
COMMAND_POSITION_ONLY = frozenset({"passwd", "profiles", "gpt", "asr", "security", "diskutil", "dscl", "su", "login", "at",
                                   "batch", "chroot", "sntp", "ntpdate", "crontab", "launchctl", "date"})


def _skip(words: List[str], i: int) -> int:
    while i < len(words) and (words[i] in KEYWORDS or ASSIGNMENT.fullmatch(words[i])):
        i += 1
    return i


def _chain(words: List[str]) -> Tuple[List[int], Optional[str]]:
    """Indexes of the wrapper chain (`sudo -u x env A=b nice rm`) ending at the program, and an `env -S` string when one
    names the real command line."""
    chain: List[int] = []
    n = len(words)
    i = _skip(words, 0)
    while i < n:
        chain.append(i)
        nm = _name(words[i])
        if nm not in WRAPPERS:
            break
        j = i + 1
        while j < n and (words[j].startswith("-") or re.fullmatch(r"[0-9.]+[smhd]?", words[j])):
            w = words[j]
            if nm == "env" and (w == "-S" or w == "--split-string" or w.startswith(("--split-string=", "-S"))):
                if w in ("-S", "--split-string"):
                    inner, rest = (words[j + 1] if j + 1 < n else ""), words[j + 2:]
                elif w.startswith("--split-string="):
                    inner, rest = w.split("=", 1)[1], words[j + 1:]
                else:
                    inner, rest = w[2:], words[j + 1:]
                return chain, inner + "".join(" " + shlex.quote(x) for x in rest)
            j += 2 if w in WRAPPERS[nm] else 1
        i = _skip(words, j)
    return chain, None


EXEC_FLAGS = ("-exec", "-execdir", "-ok", "-okdir")


@dataclass
class _Found:
    deny: Optional[str] = None
    crit: Optional[str] = None
    unp: Optional[str] = None


def _tripwire(text: str, found: _Found) -> None:
    """Tripwire strings in `text`, as written, with shell quoting removed and with the path normalised (`/var/db//x`)."""
    forms = {text.casefold()}
    if "/" in text:
        forms.add(posixpath.normpath(text).casefold())
    for form in forms:
        for tripwire in TRIPWIRES:
            if tripwire in form:
                found.deny = found.deny or tripwire
                return


def _is_under(p: str, root: str) -> bool:
    return p == root or p.startswith(root.rstrip("/") + "/")


def _protected(word: str, cwd: Optional[str], home: str) -> Optional[str]:
    """The protected root or pattern a word names as a path (after `~`, `--opt=PATH`, `-oPATH`, `..`, links, case), else None.
    Mirrors path_problem of the site helper (roles/sudo_ask_grant/files/sudo-ask-granted)."""
    cands = {word}
    if "=" in word:
        cands.add(word.split("=", 1)[1])
    if re.match(r"-[A-Za-z][^-]", word):
        cands.add(word[2:])
    for cand in cands:
        if not cand or "\0" in cand:
            continue
        if cand == "~" or cand.startswith("~/"):
            cand = home + cand[1:]
        if "/" not in cand and cand not in (".", ".."):
            continue
        if not cand.startswith("/"):
            if cwd is None:
                continue
            cand = posixpath.join(cwd, cand)
        p = os.path.realpath(cand).casefold()
        for root in PROTECTED:
            if _is_under(p, root):
                return root
        for rx in PROTECTED_RE:
            if re.search(rx, p):
                return rx
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


_GLOB = re.compile(r"[*?\[\]{}]")
# A glob that is a name pattern with an extension (`*.log`, `?*-old.txt`): it does not reach "everything" in its directory.
_NARROW_GLOB = re.compile(r"[*?]+[A-Za-z0-9_-]*\.[A-Za-z0-9]{2,}")
_VAR = re.compile(r"\$(?:\{([^}]*)\}|([A-Za-z_][A-Za-z0-9_]*|[0-9@*]))")
UNKNOWN_NAMES = frozenset({"PWD", "OLDPWD", "DIRSTACK"})      # set by the shell itself: never "empty"


def _unknown_variable(arg: str, assigned: "set[str]") -> Optional[str]:
    """The variable of `arg` whose value this module cannot know: a name the command line sets anywhere (assignment, `for`,
    `read`, `export`...), a positional (`$1`, `$@`, `$*`), `$PWD`, or a `${NAME<operator>...}` expansion. A name the line never
    sets stays EMPTY (Claude Code's own rm warning is about exactly that, and the screenshot class is that), so this is None."""
    for m in _VAR.finditer(arg):
        if m.group(2) is not None:
            name, rest = m.group(2), ""
        else:
            mm = re.match(r"([A-Za-z_][A-Za-z0-9_]*|[0-9@*#?!$-])(.*)", m.group(1), re.S)
            if not mm:
                return "${%s}" % m.group(1)
            name, rest = mm.groups()
            if rest:
                return "${%s}" % m.group(1)               # `${X:-y}`, `${X:?}`, `${X?}`, `${X/a/b}`: not a plain name
        if name == "HOME" and isinstance(assigned, _AllNames):
            continue
        if name in assigned or name in UNKNOWN_NAMES or name.isdigit() or name in ("@", "*"):
            return "$" + name
    return None


class _AllNames:
    """`name in _AllNames()` is always true: the command line sources a file (or `set -a`, `eval`), which may set anything."""

    def __contains__(self, name: object) -> bool:
        return True


SOURCING = re.compile(r"(?:^|[;&|(){}!\n'\"]|\b(?:then|do|else|elif|if|while|until|time)\b)\s*(?:source|\.)\s+\S|\bset\s+-[a-z]*a|\bexport\s+\$\(|\beval\b")
FRESH_TEMP = "/private/tmp/ade-fresh-mktemp"          # what `$(mktemp ...)` is modelled as: a new, unique, removable path
DECLARERS = frozenset({"export", "local", "declare", "typeset", "readonly"})


def _assigned_counts(text: str) -> "Counter[str]":
    """How many times the text sets each variable name: NAME=, NAME+=, NAME[i]=, `${NAME:=x}`, `for NAME`, `select NAME`, `read NAME`,
    `mapfile`, `getopts`, `printf -v NAME`, `declare/local/export NAME=`. Over-approximate on purpose (a `--opt=x` word counts)."""
    counts: "Counter[str]" = Counter()
    counts.update(re.findall(r"(?<![\w$])([A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]]*\])?\+?=", text))
    counts.update(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*):?=", text))
    counts.update(re.findall(r"\b(?:for|select)\s+\(?\(?\s*([A-Za-z_][A-Za-z0-9_]*)", text))
    counts.update(re.findall(r"\bprintf\s+-v\s+([A-Za-z_][A-Za-z0-9_]*)", text))
    for m in re.finditer(r"\b(?:read|mapfile|readarray|getopts|unset)\b([^;&|\n)]*)", text):
        counts.update(re.findall(r"(?<![\w-])([A-Za-z_][A-Za-z0-9_]*)", m.group(1)))
    return counts


def _crit_kind(cand: str, home_cf: str) -> Optional[str]:
    """"tree" (everything below it is critical), "dir" (it, but not a file inside a narrow glob), or None."""
    low = cand.casefold()
    parts = [p for p in low.split("/") if p]
    if any(low == t or low.startswith(t + "/") for t in CRITICAL_TREES):
        return "tree"
    if low in CRITICAL_EXACT or low == home_cf or low == home_cf + "/library" or low == home_cf + "/library/application support":
        return "dir"
    if len(parts) == 2 and parts[0] in ("users", "volumes"):          # a home directory or a volume root
        return "dir"
    if len(parts) in (3, 4) and parts[0] == "users" and parts[2] == "library" and (len(parts) == 3 or parts[3] == "application support"):
        return "dir"                                                    # ~/Library and ~/Library/Application Support: ancestors of the protected paths
    return None


# `claude-*`, `pytest-of-*.log` below /tmp: a literal stem of 2 or more characters, no leading dot.
_STEM_GLOB = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]+[*?][A-Za-z0-9_.*?-]*")
TMP_DIRS = ("/tmp", "/private/tmp")


def _glob_is_narrow(directory: str, comp: str) -> bool:
    """A glob in the first component under a critical `directory` that does not reach everything in it. Only `/` (the screenshot's
    `$S/*.log` with S empty) and the temp directories get that: an extension pattern; the temp directories also a stem pattern.
    Home, /Applications, /Library, /Users and the rest never do (`~/*.app`, `/Applications/*.app`)."""
    low = directory.casefold()
    if low == "/" or low in TMP_DIRS:
        if _NARROW_GLOB.fullmatch(comp):
            return True
    return low in TMP_DIRS and _STEM_GLOB.fullmatch(comp) is not None


def _critical_abs(path: str, home: str) -> Optional[str]:
    """The critical path an absolute path names. A glob or brace in the first component under a critical directory (`~/*`,
    `~/.*`, `~/{*,.*}`, `~/?*`, `~/[a-z]*`, `/Users/*`) reaches everything in it, so it is critical too; a glob that names an
    extension (`/*.log`, `~/*.log`) does not (it is what the screenshot's `$S/*.log` becomes with S empty)."""
    home_cf = posixpath.normpath(home).casefold()
    parts = path.split("/")
    gi = next((i for i, p in enumerate(parts) if i > 0 and _GLOB.search(p)), None)
    if gi is not None and ".." in parts[gi + 1:]:                 # `/tmp/cl*/../../Users`: it climbs out, judge the whole path
        path = posixpath.normpath(path)
        parts = path.split("/")
        gi = next((i for i, p in enumerate(parts) if i > 0 and _GLOB.search(p)), None)
    if gi is not None:
        prefix = "/".join(parts[:gi]) or "/"
        for cand in (posixpath.normpath(prefix), os.path.realpath(prefix)):
            kind = _crit_kind(cand, home_cf)
            if kind == "tree" or (kind == "dir" and not _glob_is_narrow(cand, parts[gi])):
                return cand
        return None
    core = path or "/"
    for cand in (posixpath.normpath(core), os.path.realpath(core)):     # /etc is /private/etc; a symlink cannot hide a target
        if _crit_kind(cand, home_cf):
            return cand
    return None


def _broad_relative(exp: str, filtered: bool = False) -> bool:
    """A relative removal target that reaches the whole of the (unknown) current directory or its parent: `.`, `..`, `../x`, a
    glob or brace in the first component (`*`, `.*`, `*.*`, `?*`, `[a-z]*`, `{a,b}`), but not `*.log`."""
    norm = posixpath.normpath(exp)
    first = norm.split("/")[0]
    if norm == ".":
        return not filtered                  # `find . -name x -delete` has a test; a bare `rm -rf .` does not
    if first == "..":
        return True
    return bool(_GLOB.search(first)) and _NARROW_GLOB.fullmatch(first) is None


def _find_narrow(args: List[str]) -> bool:
    """A find that cannot reach everything below its start path: a `-name`/`-iname`/`-path` test whose pattern keeps at least two
    literal characters (one of them a letter or digit): `-name node_modules`, `-name '*.pyc'`, `-name 'core.*'`; or `-empty`,
    `-samefile`, `-inum`. `-type`, `-mtime`, `-size`, `-user`, `-newer`, `-perm` and `-name '*'` do not narrow it, and nothing does
    when the expression is negated or has an `-o`."""
    if any(a in FIND_OPERATORS for a in args):
        return False
    args = args[:next((k for k, a in enumerate(args) if a in FIND_ACTIONS), len(args))]     # a test after the action filters nothing
    for k, a in enumerate(args):
        if a in FIND_ALWAYS_NARROW:
            return True
        if a in FIND_NAME_TESTS and k + 1 < len(args):
            pat = args[k + 1]
            if pat and not re.search(r"[*?\[\\]", pat):
                return True                               # an exact name
            lit = [c for c in re.sub(r"\[[^\]]*\]", "", pat) if c not in "*?\\"]
            if len(lit) >= 2 and any(c.isalnum() for c in lit):
                return True
    return False


def _find_parts(args: List[str]) -> Tuple[List[str], bool, List[str]]:
    """(roots, -delete present, programs run by -exec/-execdir/-ok/-okdir) of a find command line."""
    i, roots = 0, []
    while i < len(args):
        a = args[i]
        if a in ("-H", "-L", "-P", "-E", "-X", "-x", "-d", "-s") or re.fullmatch(r"-O[0-3]", a):
            i += 1
        elif a == "-f" and i + 1 < len(args):
            roots.append(args[i + 1])
            i += 2
        else:
            break
    while i < len(args) and not (args[i].startswith("-") or args[i] in ("(", ")", "!", ",")):
        roots.append(args[i])
        i += 1
    rest = args[i:]
    execs = [_name(rest[k + 1]) for k, a in enumerate(rest) if a in EXEC_FLAGS and k + 1 < len(rest)]
    return roots or ["."], "-delete" in rest, execs


class _Scan:
    def __init__(self, home: str, counts: Optional["Counter[str]"] = None, all_unknown: bool = False) -> None:
        self.home = home
        self.counts: "Counter[str]" = counts if counts is not None else Counter()    # `_assigned_counts` of the whole request
        self.all_unknown = all_unknown           # the line sources a file: any variable may have been set by it
        self.assigned: Any = _AllNames() if all_unknown else {n for n, c in self.counts.items() if c}
        self.values: Dict[str, List[str]] = {}   # names set once, by a plain assignment, to a literal or a fresh temp path
        self.found = _Found()
        self.cd_unknown = False                  # a `cd` to a variable or substitution came before: relative operands are unknown
        self.was_cd = False                      # the statement that just ran was a cd, pushd or popd
        self.alts: List[str] = []                # other directories the line may be in (a cd chain that was cut short)
        self.chain: Optional[Tuple[Optional[str], Tuple[str, ...]]] = None   # directory (and alternatives) before a `cd X && ...` chain
        self.loops = 0                           # `for`/`while`/`until`/`select` bodies open around the statement
        self.has_function = False                # the request defines a function or alias (`return` can leave, tracking is off)

    def note(self, kind: str, what: str) -> None:
        if getattr(self.found, kind) is None:
            setattr(self.found, kind, what)

    def text(self, text: str, cwd: Optional[str], depth: int) -> None:
        if depth > MAX_DEPTH:
            self.note("unp", "nesting too deep")
            return
        try:
            stmts, nested = _tokenize(text)
        except Unparsable as exc:
            self.note("unp", str(exc))
            return
        saved = (dict(self.values), self.cd_unknown, list(self.alts), self.chain, self.loops) if depth else None
        self.chain = None if depth else self.chain                # a body is a subshell: nothing it sets leaks out
        for body in nested:
            self.text(body, cwd, depth + 1)
        stack: List[Tuple[Optional[str], bool, Dict[str, List[str]], List[str], Any]] = []
        pending: Optional[Tuple[Optional[str], bool, List[str], Optional[str], bool]] = None
        prev: Optional[Stmt] = None
        compound, loops = 0, 0
        for idx, st in enumerate(stmts):
            for _ in range(st.closes):                    # `( ... )` ended: its cd and its assignments are gone
                if stack:
                    cwd, self.cd_unknown, self.values, self.alts, self.chain = stack.pop()
                pending = None
            if pending is not None:
                cwd = self.after_cd(pending, st)
                pending = None
            elif self.chain is not None and st.sep not in ("&&", "|"):
                cwd = self.break_chain(cwd)               # the `&&` chain after a cd ended: the cd may have failed
            for _ in range(st.opens):
                stack.append((cwd, self.cd_unknown, dict(self.values), list(self.alts), self.chain))
            self.loops = loops
            old_unknown, old_alts = self.cd_unknown, list(self.alts)
            self.was_cd = False
            new_cwd = self.stmt(st, prev, cwd, depth)
            nxt = stmts[idx + 1].sep if idx + 1 < len(stmts) else ""
            if self.was_cd and st.sep == "|":
                self.cd_unknown = old_unknown             # a cd in a pipeline stage is lost with its subshell
            elif self.was_cd:
                pending = (cwd, old_unknown, old_alts, new_cwd, self.cd_unknown)
            else:
                cwd = new_cwd
                self.track(st, nxt, compound)
            compound, loops = self.compound_after(st, compound, loops)
            prev = st
        if saved:
            self.values, self.cd_unknown, self.alts, self.chain, self.loops = saved

    @staticmethod
    def compound_after(st: Stmt, compound: int, loops: int) -> Tuple[int, int]:
        """Depth of `if`/`while`/`until`/`for`/`select`/`case` bodies after this statement (`then`, `do`, `else` do not close one)."""
        w = st.words
        if not w:
            return compound, loops
        head = w[1] if w[0] in ("then", "do", "else", "elif") and len(w) > 1 else w[0]
        if head in COMPOUND_OPENERS:
            return compound + 1, loops + (1 if head in ("for", "while", "until", "select") else 0)
        if w[0] in ("fi", "done", "esac"):
            return max(0, compound - 1), max(0, loops - (1 if w[0] == "done" else 0))
        return compound, loops

    def leaves(self, st: Stmt) -> bool:
        """The statement ends the shell (or the loop or function) when it runs: `exit` always, `return` only where a function is
        defined, `break` and `continue` only inside a loop (bash at the top level just prints an error and goes on)."""
        chain, _ = _chain(st.words)
        if not chain:
            return False
        name = _name(st.words[chain[-1]])
        if name == "exit":
            return True
        if name == "return":
            return self.has_function
        return name in ("break", "continue") and self.loops > 0

    def break_chain(self, cwd: Optional[str]) -> Optional[str]:
        """A `cd X && A` chain ended at `;`, a newline, `||` or `&`: if the cd failed the rest runs where it was before, so the
        directory is unknown, or both directories when both are known."""
        chain, self.chain = self.chain, None
        if chain is None:
            return cwd
        old, old_alts = chain
        if old is None or cwd is None:
            self.alts = []
            return None
        alts = [d for d in dict.fromkeys(list(old_alts) + [old]) if d != cwd]
        if len(alts) > 8:
            self.alts = []
            return None
        self.alts = alts
        return cwd

    def child_text(self, text: str, cwd: Optional[str], depth: int) -> None:
        """A `-c` body or an `env -S` line runs in a new process: it sees only exported names, and `sudo` and `env -i` drop even
        those, so no value tracked in the outer line applies (a name it sets itself is tracked inside)."""
        outer, self.values = self.values, {}
        try:
            self.text(text, cwd, depth)
        finally:
            self.values = outer

    def after_cd(self, pending: Tuple[Optional[str], bool, List[str], Optional[str], bool], st: Stmt) -> Optional[str]:
        """The directory after a `cd`, known only from what joins the next statement: `&&` keeps it for as long as `&&` (or a
        pipe) keeps joining the statements, `|| exit` keeps it for good; a pipe means the cd ran in a subshell and changed
        nothing; `;`, a newline, `||`, `&` mean it may have failed, so the directory is unknown (both directories when both
        are known) and relative removals that reach everything are held."""
        old, old_unknown, old_alts, new, new_unknown = pending
        if st.sep == "&&":
            if self.chain is None:
                self.chain = (old, tuple(old_alts))
            self.alts = []
            self.cd_unknown = new_unknown
            return new
        if st.sep == "|":
            self.cd_unknown = old_unknown
            self.alts = list(old_alts)
            return old
        self.cd_unknown = new_unknown
        if st.sep == "||" and self.leaves(st):
            self.chain, self.alts = None, []
            return new
        if self.chain is None:
            self.chain = (old, tuple(old_alts))
        return self.break_chain(new)

    # ---- variables with a known value

    def candidates(self, arg: str) -> Optional[List[str]]:
        """`arg` with every tracked variable replaced by each of its values (all of a `for` list). None when there are too many."""
        out = [arg]
        if "$" not in arg or not self.values:
            return out
        for name, vals in self.values.items():
            pat = re.compile(r"\$\{%s\}|\$%s(?![A-Za-z0-9_])" % (re.escape(name), re.escape(name)))
            if any(pat.search(a) for a in out):
                out = [pat.sub(lambda m, v=v: v, a) for a in out for v in vals]
                if len(out) > 32:
                    return None
        return out

    def track(self, st: Stmt, nxt: str, compound: int = 0) -> None:
        """Remember the value of a plain assignment (`S=/private/tmp/x`, `S=$(mktemp -d)`, `export S=...`) or of a `for NAME in
        WORDS` list, when the name is set exactly once on the whole line, at the top of a command list (not after `&&`/`||`, not
        in a pipeline, not in `(...)`, not after `then`). Anything else stays an unknown variable."""
        words = st.words
        if self.all_unknown or self.has_function or compound or not words or st.sep not in ("", ";", "\n") or nxt in ("|", "&"):
            return
        if words[0] == "for":
            if len(words) >= 4 and words[2] == "in" and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", words[1]) \
                    and self.counts.get(words[1], 0) == 1:
                items = words[3:]
                if not any(k in st.subst or re.search(r"[$`*?\[\]{}\s]", it) or it.startswith("-")
                           for k, it in enumerate(items, 3)):
                    exp = [_expand(it, self.home) for it in items]
                    if all(e is not None for e in exp):
                        self.values[words[1]] = [e for e in exp if e is not None]
            return
        k = 0
        if words[0] in DECLARERS:
            k = 1
            while k < len(words) and words[k].startswith("-"):
                k += 1
        rest = words[k:]
        if not rest or not all(ASSIGNMENT.fullmatch(w) or (k and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", w)) for w in rest):
            return
        for j, w in enumerate(rest):
            m = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", w, re.S)
            if m:
                self.set_value(m.group(1), m.group(2), st.wordsubs.get(k + j), (k + j) in st.subst)

    def set_value(self, name: str, value: str, subs: Optional[List[str]], has_sub: bool) -> None:
        if self.counts.get(name, 0) != 1:
            return
        if has_sub:
            m = re.fullmatch(r"\$\(SUB\)(/[^$`\s]*)?", value)
            if m and subs and len(subs) == 1 and self.is_mktemp(subs[0]):
                self.values[name] = [FRESH_TEMP + (m.group(1) or "")]
            return
        if re.search(r"[\s`]", value) or value.startswith(("-", "(")):
            return
        cands = self.candidates(value)
        if cands is None:
            return
        vals: List[str] = []
        for c in cands:
            exp = None if _unknown_variable(c, self.assigned) else _expand(c, self.home)
            if exp is None:
                return
            vals.append(exp)
        self.values[name] = vals

    def is_mktemp(self, body: str) -> bool:
        """`mktemp ...` alone: a fresh path that nothing else uses, safe to remove."""
        try:
            stmts, nested = _tokenize(body.strip())
        except Unparsable:
            return False
        if len(stmts) != 1 or nested or stmts[0].subst or stmts[0].redirs or stmts[0].heredocs or stmts[0].herestring:
            return False
        w = stmts[0].words
        return bool(w) and _is_program(w[0], ["mktemp", "gmktemp"]) is not None

    # ---- paths

    def judge(self, operand: str, cwd: Optional[str], filtered: bool = False) -> Optional[str]:
        """The critical path a removal operand names, for each value of the tracked variables in it."""
        cands = self.candidates(operand)
        if cands is None:
            self.note("unp", "too many values for a variable in a removal")
            return None
        hit = None
        for cand in cands:
            for where in [cwd] + (self.alts if cwd is not None else []):
                hit = hit or self.judge_one(cand, where, filtered)
        return hit

    def judge_one(self, operand: str, cwd: Optional[str], filtered: bool = False) -> Optional[str]:
        """Held (a note, no path) when a variable the line sets (and this module cannot value), a positional or a `${NAME:-x}`
        form is in the operand, or when it is relative and the directory it is relative to is unknown and it reaches all of it
        (`.`, `..`, `../x`, `*`, `.*`, `?*`). `filtered`: a find with a narrowing test (`find . -name x -delete`)."""
        var = _unknown_variable(operand, self.assigned)
        if var:
            self.note("unp", "variable %s in a removal" % var)
            return None
        exp = _expand(operand, self.home)
        if not exp:
            return None
        if not exp.startswith("/"):
            if cwd is None:
                if self.cd_unknown:
                    self.note("unp", "removal after a cd to an unknown directory")
                elif _broad_relative(exp, filtered):
                    self.note("unp", "removal of %s relative to an unknown directory" % operand)
                return None
            exp = posixpath.join(cwd, exp)
        return _critical_abs(exp, self.home)

    def directory(self, target: str, cwd: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """(directory, why not known). `cd -`, a variable, a substitution: not known (`variable`); a relative target while the
        current directory is unknown: no directory, but nothing wrong either."""
        cands = self.candidates(target)
        if cands is None or len(cands) != 1:
            return None, "variable"
        target = cands[0]
        if FRESH_TEMP in target:
            return None, "variable"                   # mktemp may have failed: `cd ""` stays where it is
        stripped = re.sub(r"\$\{HOME\}|\$HOME\b", "", target)
        if target == "-" or "$" in stripped or "`" in target or _unknown_variable(target, self.assigned):
            return None, "variable"
        exp = _expand(target, self.home)
        if not exp:
            return None, "variable"
        if exp.startswith("/"):
            return posixpath.normpath(exp), None
        if cwd:
            return posixpath.normpath(posixpath.join(cwd, exp)), None
        return None, ("relative" if _broad_relative(exp) else None)

    def cd(self, args: List[str], cwd: Optional[str]) -> Optional[str]:
        ops = [a for a in args if a == "-" or not a.startswith("-")]
        if not ops:
            self.cd_unknown = False
            return self.home
        directory, why = self.directory(ops[0], cwd)
        if why == "variable":
            self.cd_unknown = True
        elif directory is not None:
            self.cd_unknown = False
        return directory

    def remove_operand(self, name: str, operand: str, idx: int, st: Stmt, cwd: Optional[str], filtered: bool = False) -> None:
        if idx in st.subst:
            self.note("unp", "substitution in a removal")
            return
        hit = self.judge(operand, cwd, filtered)
        if hit:
            self.note("crit", "%s %s" % (name, hit))

    # ---- one simple command

    def stmt(self, st: Stmt, prev: Optional[Stmt], cwd: Optional[str], depth: int) -> Optional[str]:
        words, home = st.words, self.home
        for w in words + st.redirs:
            _tripwire(w, self.found)
        chain, env_split = _chain(words)
        if env_split is not None:
            self.child_text(env_split, cwd, depth + 1)
            return cwd
        if not chain:
            self.remover_words(st, set())
            return cwd
        for c in chain:                              # the command word must be a plain word the shell will not rewrite
            w = words[c]
            if c not in st.subst and w not in ("[", "[[") and (c in st.quoted or w.startswith("=") or re.search(r"[$?*\[{]", w)):
                self.note("unp", "command word %r is not a plain word" % w[:40])
        exempt: set = set()
        new_cwd = self.dispatch(st, prev, cwd, depth, chain, exempt)
        self.remover_words(st, exempt)
        return new_cwd

    def remover_words(self, st: Stmt, exempt: set) -> None:
        """The textual tripwire (round 3): a remover word anywhere in a command that the parser did not itself judge as a removal
        (`parallel rm`, `ssh h rm -rf x`, `xargs -d '\\n' rm`, `fd -X rm`, `flock f rm`, `script rm`, `alias ls='rm -rf'`) holds the request."""
        for k, w in enumerate(st.words):
            if k in exempt or not w:
                continue
            if re.search(r"\s", w):
                hit = REMOVER_TEXT.search(w) is not None
            else:
                hit = (_name(w) in REMOVER_NAMES or re.fullmatch(r"--?(?:delete|del)(?:-[a-z-]+)?(?:=.*)?", w) is not None
                       or ("=" in w and _name(w.split("=", 1)[1]) in REMOVER_NAMES))
            if hit:
                self.note("unp", "remover word %r outside a command the parser judged" % w[:40])
                return

    def dispatch(self, st: Stmt, prev: Optional[Stmt], cwd: Optional[str], depth: int, chain: List[int],
                 exempt: set) -> Optional[str]:
        words, home = st.words, self.home
        pi = chain[-1]
        prog, args = _name(words[pi]), words[pi + 1:]
        at = set(chain)
        for j, tok in enumerate(words):
            if tok in EXEC_FLAGS and j + 1 < len(words):
                at.add(j + 1)
        self.denylist(words, at)
        read_only = prog in READ_ONLY
        for target in st.redirs:
            root = _protected(target, cwd, home)
            if root:
                self.note("deny", "protected " + root)
        if not read_only:
            for w in args:
                root = _protected(w, cwd, home)
                if root:
                    self.note("deny", "protected " + root)
        sub_in_args = any(k >= pi for k in st.subst) or -1 in st.subst
        if pi in st.subst:
            self.note("unp", "substitution as the command")
        idx0 = pi + 1                              # index in `words` of args[0]
        if prog in NON_EXEC and not (prog == "git" and self.git_runs_commands(args)):
            exempt.update(range(idx0, len(words)))

        def operands_of(arglist: List[str], first: int) -> List[Tuple[int, str]]:
            out, end_of_opts = [], False
            for k, a in enumerate(arglist):
                if a == "--" and not end_of_opts:
                    end_of_opts = True
                elif end_of_opts or not a.startswith("-"):
                    out.append((first + k, a))
            return out

        if prog in REMOVERS:
            exempt.add(pi)
            if "--no-preserve-root" in args:
                self.note("crit", "%s --no-preserve-root" % prog)
            for k, operand in operands_of(args, idx0):
                self.remove_operand(prog, operand, k, st, cwd)
            self.xargs_input(chain, words, st, prev, cwd)
        elif prog == "find":
            roots, delete, execs = _find_parts(args)
            for j, w in enumerate(words):
                if w == "-delete":
                    exempt.add(j)
                elif w in EXEC_FLAGS and j + 1 < len(words):
                    exempt.add(j + 1)
            if delete or any(e in REMOVERS or e in SHELLS for e in execs):
                if sub_in_args:
                    self.note("unp", "substitution in a find that removes")
                filtered = _find_narrow(args)
                for root in roots:
                    hit = self.judge(root, cwd, filtered)
                    if hit:
                        self.note("crit", "find %s" % hit)
        elif prog == "mv":
            skip = {k + 1 for k, a in enumerate(args) if a in ("-t", "--target-directory")}
            has_target = bool(skip) or any(a.startswith("--target-directory=") for a in args)
            ops = [(k, a) for k, a in operands_of(args, idx0) if (k - idx0) not in skip]
            sources = ops if has_target else ops[:-1]
            for k, operand in sources:
                self.remove_operand("mv", operand, k, st, cwd)
        elif prog in RUNNERS:
            for k, a in enumerate(args):
                if INTERPRETERS.fullmatch(_name(a)):
                    self.interpreter(st, args[k + 1:])
                    break
        elif prog in RECURSIVE_CHANGERS:
            flags = [a for a in args if a.startswith("-") and a != "--"]
            if any(re.fullmatch(r"-[A-Za-z]*R[A-Za-z]*", f) or f == "--recursive" for f in flags):
                ops = operands_of(args, idx0)
                if not any(f.startswith("--reference") for f in flags):
                    ops = ops[1:]
                for k, operand in ops:
                    self.remove_operand(prog, operand, k, st, cwd)
        elif prog == "rsync":
            if any(a.startswith("--del") for a in args):
                exempt.update(j for j, w in enumerate(words) if w.startswith("--del"))
                ops = [(k, a) for k, a in operands_of(args, idx0)]
                if ops:
                    self.remove_operand("rsync", ops[-1][1], ops[-1][0], st, cwd)
        elif prog == "git":
            self.git(args, idx0, st, cwd)
        elif prog in SHELLS:
            body_at = self.shell(st, args, cwd, depth)
            if body_at is not None:
                exempt.add(idx0 + body_at)           # recursed into: the words of the body are judged as commands
        elif prog == "eval":
            self.note("unp", "eval")
        elif prog in ("source", "."):
            target = args[0] if args else ""
            if not target or target == "-" or target.startswith(("/dev/stdin", "/dev/fd", "/proc/self/fd")) or idx0 in st.subst:
                self.note("unp", "source of stdin or a substitution")
        elif prog in ("cd", "pushd"):
            self.was_cd = True
            return self.cd(args, cwd)
        elif prog == "popd":
            self.was_cd = True
            self.cd_unknown = True
            return None
        elif INTERPRETERS.fullmatch(prog):
            self.interpreter(st, args)
        elif prog in ("crontab", "launchctl", "date"):
            pass
        return cwd

    @staticmethod
    def git_runs_commands(args: List[str]) -> bool:
        """`git submodule foreach CMD`, `rebase --exec CMD`, `bisect run CMD`, `-c alias.x=!CMD`: arguments that are command lines."""
        return any(a in ("foreach", "--exec", "-x", "run") or a.startswith("--exec=") or re.match(r"alias\.[^=]*=!", a) is not None
                   for a in args)

    def interpreter(self, st: Stmt, args: List[str]) -> None:
        """A python/perl/ruby/node/osascript one-liner (-c, -e, a here-document) that names a deletion."""
        one_liner = bool(st.heredocs) or st.herestring or any(
            a in ("-", "--eval", "--print") or re.fullmatch(r"-[A-Za-z]*[cerp][A-Za-z]*", a) for a in args)
        if not one_liner:
            return
        text = " ".join(args) + " " + " ".join(h[2] for h in st.heredocs) + " " + " ".join(st.herewords)
        if INTERPRETER_BAD.search(text):
            self.note("unp", "interpreter one-liner that deletes")

    def xargs_input(self, chain: List[int], words: List[str], st: Stmt, prev: Optional[Stmt], cwd: Optional[str]) -> None:
        if not any(_name(words[c]) == "xargs" for c in chain[:-1]):
            return
        if prev is not None and st.sep == "|":
            pchain, _ = _chain(prev.words)
            if pchain:
                pprog, pargs = _name(prev.words[pchain[-1]]), prev.words[pchain[-1] + 1:]
                if pprog in ("echo", "printf", "find") and (prev.subst or any("$(" in a or "`" in a for a in pargs)):
                    self.note("unp", "xargs removal of substitution input")
                    return
                if pprog in ("echo", "printf"):
                    for a in pargs:
                        hit = self.judge(a, cwd) if not a.startswith("-") else None
                        if hit:
                            self.note("crit", "xargs rm %s" % hit)
                    return
                if pprog == "find":
                    filtered = _find_narrow(pargs)
                    for root in _find_parts(pargs)[0]:
                        hit = self.judge(root, cwd, filtered)
                        if hit:
                            self.note("crit", "xargs rm %s" % hit)
                    return
        self.note("unp", "xargs removal of unknown input")

    def git(self, args: List[str], first: int, st: Stmt, cwd: Optional[str]) -> None:
        gcwd, k, sub, bad = cwd, 0, None, None
        while k < len(args):
            a = args[k]
            if a in ("-C", "--work-tree") and k + 1 < len(args):
                gcwd, why = self.directory(args[k + 1], gcwd)
                bad = bad or why
                k += 2
            elif a.startswith("--work-tree="):
                gcwd, why = self.directory(a.split("=", 1)[1], gcwd)
                bad = bad or why
                k += 1
            elif a in ("-c", "--git-dir", "--namespace") and k + 1 < len(args):
                k += 2
            elif a.startswith("-"):
                k += 1
            else:
                sub, k = a, k + 1
                break
        if sub != "clean":
            return
        rest = args[k:]
        if not any(re.fullmatch(r"-[A-Za-z]*f[A-Za-z]*", x) or x == "--force" for x in rest):
            return
        if bad == "variable" or self.cd_unknown:
            self.note("unp", "git clean in a directory that cannot be read")
        elif bad == "relative":
            self.note("unp", "git clean relative to an unknown directory")
        if gcwd is not None:
            hit = _critical_abs(gcwd, self.home)
            if hit:
                self.note("crit", "git clean %s" % hit)
        for x in rest:
            if not x.startswith("-"):
                hit = self.judge(x, gcwd)
                if hit:
                    self.note("crit", "git clean %s" % hit)

    def shell(self, st: Stmt, args: List[str], cwd: Optional[str], depth: int) -> Optional[int]:
        """Judge a shell's command line. Returns the index (in args) of a `-c` body that was recursed into."""
        if st.heredocs or st.herestring:
            self.note("unp", "here-document fed to a shell")
        k, body_at, script, script_at = 0, None, False, 0
        while k < len(args):
            a = args[k]
            if a == "--":
                script, script_at = k + 1 < len(args), k + 1
                break
            if a in SHELL_VALUE_FLAGS:
                k += 2
                continue
            if a.startswith("-") and not a.startswith("--") and "c" in a[1:]:
                body_at = k + 1
                break
            if not a.startswith("-") and not a.startswith("+"):
                script, script_at = True, k
                break
            k += 1
        if script and script_at < len(args):
            target = args[script_at]
            if target == "-" or target.startswith(("/dev/stdin", "/dev/fd", "/proc/self/fd")):
                self.note("unp", "shell script read from stdin")
            elif any(j >= 0 and j - (len(st.words) - len(args)) == script_at for j in st.subst):
                self.note("unp", "shell script named by a substitution")
        if body_at is not None:
            if body_at >= len(args):
                self.note("unp", "shell -c without a command")
                return None
            body = args[body_at]
            params = args[body_at + 1:]
            if params:                         # `sh -c 'rm -rf "$1"' _ /`: positional parameters name the operands
                def fill(m: "re.Match[str]") -> str:
                    key = m.group(1) or m.group(2)
                    if key in ("@", "*"):
                        return " ".join(params[1:])
                    pos = int(key)
                    return params[pos] if pos < len(params) else ""
                body = re.sub(r"\$(?:\{([0-9]+|@|\*)\}|([0-9@*]))", fill, body)
            self.child_text(body, cwd, depth + 1)
            return body_at
        if not script:
            self.note("unp", "shell reads its commands from stdin")
        return None

    def denylist(self, words: List[str], at: set) -> None:
        for i, tok in enumerate(words):
            base = posixpath.basename(posixpath.normpath(tok)) if tok else ""
            if not (i in at or base not in COMMAND_POSITION_ONLY):
                continue
            if _is_program(tok, NAME_DENY) or (_is_program(tok, [base]) and base.startswith(NAME_DENY_PREFIX)):
                if base in COMMAND_POSITION_ONLY and i not in at:
                    continue
                self.note("deny", base)
                continue
            if i not in at:
                continue
            args = words[i + 1:]
            if _is_program(tok, ["diskutil"]):
                verbs = [a.lower() for a in args if not a.startswith("-")]
                verb = verbs[0] if verbs else ""
                if verb in ("apfs", "cs", "appleraid", "corestorage"):
                    verb = verbs[1] if len(verbs) > 1 else ""
                    if verb not in DISKUTIL_SUB_OK:
                        self.note("deny", "diskutil " + (verb or "?"))
                elif verb not in DISKUTIL_OK:
                    self.note("deny", "diskutil " + (verb or "?"))
            elif _is_program(tok, ["dscl"]):
                low = {a.lstrip("-").lower() for a in args}
                if low & DSCL_WRITE or not low & DSCL_READ:
                    self.note("deny", "dscl write")
            elif _is_program(tok, ["security"]):
                verbs = [a for a in args if not a.startswith("-")]
                verb = verbs[0] if verbs else ""
                if verb not in SECURITY_OK or (verb == "list-keychains" and any(a.startswith(("-s", "-d")) for a in args)):
                    self.note("deny", "security " + (verb or "?"))
            elif _is_program(tok, ["crontab"]):
                if args != ["-l"]:
                    self.note("deny", "crontab")
            elif _is_program(tok, ["launchctl"]):
                if args[:1] and args[0] in LAUNCHCTL_RUNS:
                    self.note("deny", "launchctl " + args[0])
            elif _is_program(tok, ["date"]):
                if "-j" not in args and any(not a.startswith(("-", "+")) for a in args):
                    self.note("deny", "date sets the clock")
            elif tok == "sudo-ask" or tok.endswith("/sudo-ask"):
                if any(a in ("grant", "revoke", "--grant", "--revoke") for a in args):
                    self.note("deny", "sudo-ask window change")


def _analyze(commands: List[str], paths: List[str], file_tool: bool, home: str, cwd: Optional[str]) -> _Found:
    commands = list(dict.fromkeys(commands))              # the same text in two fields must not count as two assignments
    counts: "Counter[str]" = Counter()
    for text in commands:
        counts.update(_assigned_counts(text))
    scan = _Scan(home, counts, any(SOURCING.search(text) for text in commands))
    scan.has_function = any(DEFINITION.search(re.sub(r"[\\'\"]", "", text)) for text in commands)
    for text in commands:
        _tripwire(text, scan.found)
        flat = re.sub(r"[\\'\"]", "", text)
        if DEFINITION.search(flat) and REMOVER_TEXT.search(flat):
            scan.note("unp", "alias or function definition with a removal")
        scan.text(text, cwd, 0)
    for path in paths:
        _tripwire(path, scan.found)
        base = posixpath.basename(posixpath.normpath(path)) if path else ""
        if base in NAME_DENY and base not in COMMAND_POSITION_ONLY and _is_program(path, NAME_DENY):
            scan.note("deny", base)
        if file_tool:
            root = _protected(path, cwd, home)
            if root:
                scan.note("deny", "protected " + root)
    return scan.found


def _request_cwd(req: "Request") -> Optional[str]:
    for part in (req.input, req.detail):
        if isinstance(part, dict) and isinstance(part.get("cwd"), str) and part["cwd"].startswith("/"):
            return posixpath.normpath(part["cwd"])
    return None


GATE_MARKERS = ("Frontier sub-agent:",)          # the text of claude/hooks/frontier_agent_gate.py's ask (`_ask`)
SUBAGENT_TOOLS = frozenset({"agent", "task"})   # Claude's sub-agent launch tools (the frontier gate matches "Agent", "Task")


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
    # Our own gates: the frontier sub-agent gate asks the operator on purpose (scarce Fable). Never answer it.
    if compact in SUBAGENT_TOOLS:
        return hold("gate:subagent")
    reason_fields = json.dumps([req.title, req.description, req.detail, req.metadata], default=str)
    if any(marker in reason_fields for marker in GATE_MARKERS):
        return hold("gate:ade")
    why = _unreadable(req, commands, paths, texts)
    if why:
        return hold("unreadable:" + why)
    file_tool = compact in {re.sub(r"[^a-z0-9]", "", n) for n in FILE_TOOL_NAMES} - {"read"} or "filechange" in compact
    found = _analyze(commands, paths, file_tool, home, _request_cwd(req))
    # raw tripwires over every other string (titles, reasons, metadata) as before
    for text in texts:
        if found.deny is None:
            _tripwire(text, found)
    if found.deny:
        return hold("denylist:" + found.deny)
    reason_text = " ".join(t for t in (req.title, req.description) if t)
    if CRITICAL_REASON.search(reason_text):
        return hold("critical-reason")
    if found.crit:
        return hold("critical-rm:" + found.crit)
    if found.unp:
        return hold("unreadable:unparsable:" + found.unp)
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
