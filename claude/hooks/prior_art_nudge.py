#!/usr/bin/env python3
"""prior_art_nudge.py — SHADOW telemetry for the "web prior art before code spelunking" question.

Registered under PostToolUse, PostToolUseFailure and UserPromptSubmit (agents/claude/settings.json.tmpl).
It RECORDS, one JSON line per event, when an agent reads or searches code in a way a prior-art web
search might have answered, and what happened next. It NEVER prints to the model, never blocks and never
changes a prompt: stdout and stderr stay empty and the exit status is always 0. Nothing about agent
behaviour changes until these numbers exist (djbclark, 2026-10-25, "approve, but measure first",
docs/queue.md "Research: web prior art ..." decision C1; slice D2 of
research-web-python-lsp-report.md).

Record  ~/.claude/state/prior-art-shadow/<session id>.jsonl   (dir `PRIOR_ART_STATE` overrides;
dir mode 0700, file mode 0600, one O_APPEND write per line, capped at 5 MB with one last
`{"capped":true}` line). Carry-over (previous timestamp, run counters, a salt, recent call hashes) lives
in <session id>.state.json for the main agent and <session id>.<agent key>.state.json for each subagent
(Claude Code puts the PARENT's session_id and the subagent's own `agent_id` in every hook payload, so
state keyed on the session alone interleaves parallel subagents), replaced atomically under
<session id>.lock. Every file is opened O_NOFOLLOW | O_NONBLOCK and must be a regular file.

Fields: ts (UTC ISO), schema and classifier_version (so a later reclassification can tell old rows from
new; the records keep no raw input), session (first 12 hex of sha256 of the session id), event, client
(the payload's `model` if it looks like a known model family, else "claude-code"), tool (see PRIVACY),
category, failed, bytes (UTF-8 length of the tool response or error text), tokens_est (bytes // 4, an
estimate), web_or_memory_before (a web or memory event earlier in the same task), run_length
(consecutive external-tree reads without a web, memory or own-code event between; `external_run` is
run_length >= 3), duplicate, retry, quoting_failure, task_seq, elapsed_ms since the previous event of the
same agent; plus, when they apply: `agent` (first 8 hex of sha256 of a subagent's agent_id, absent for the
main agent), `host_class` and `host` for a fetched URL, `path_class` for a read path, `dropped` (events
lost to a held lock since the previous record).

PRIVACY, exactly what is stored: the category and the booleans, counts and timestamps above; the session
pseudonym; `tool` only when it is a known built-in tool name or an MCP tool of a known server (everything
else is "other" or "mcp__other"); `client` only for a known model family; `host_class` (loopback,
private_ip, internal, public, invalid); `host` only for a public URL whose registrable domain is on the
fixed ALLOWED_DOMAINS list, and then only that registrable domain, never a sub-domain, port, user, path,
query or fragment; `path_class` (a fixed enum, never a path segment). NEVER stored: a command, a path, a
query, a URL, a prompt, tool output, a host outside the allowlist, a server name outside the allowlist.
The session id itself is the record's file name (sanitised). Call hashes kept in the state file are
salted with a per-session random value that sits beside them in the same file, so the salt only stops
linking the same call across sessions; whoever can read the state directory can still brute-force a
low-entropy call, and the directory is mode 0700 for that reason. Call hashes never reach the record.

Categories: own_code, external_code, memory, web, private_other, task_change (UserPromptSubmit).
A new UserPromptSubmit, or an idle gap over PRIOR_ART_IDLE_S (default 1800 s), starts a new task and
resets the run counters. `PRIOR_ART_SHADOW=0` disables recording. A UserPromptSubmit also prunes files
older than PRIOR_ART_RETENTION_DAYS (default 30) from the state directory, at most once a day.

MUST exit 0 silently on every failure (malformed event, deep JSON, unwritable state dir, bad UTF-8)
and stay within the hook-deadline wrapper. Python 3 stdlib only.
"""
# Every failure is swallowed on purpose: a telemetry hook must never block or annoy a session.
# ruff: noqa: BLE001, S110
import contextlib
import errno
import fcntl
import hashlib
import ipaddress
import itertools
import json
import os
import re
import shlex
import stat
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = 2
CLASSIFIER_VERSION = 2

CAP_BYTES = 5 * 1024 * 1024
CAP_TAIL = b'{"capped":true}\n'
MAX_STDIN = 32 * 1024 * 1024
MAX_STATE_BYTES = 1024 * 1024
MAX_WALK_NODES = 200_000
MAX_WALK_DEPTH = 12
SCAN_CHARS = 200_000
MAX_CMD_CHARS = 20_000
MAX_TOKENS = 2_000
MAX_PATHS = 50
RECENT_CALLS = 30
EXTERNAL_RUN = 3
LOCK_RETRIES = 25
LOCK_WAIT_S = 0.02
DEFAULT_IDLE_S = 1800
DEFAULT_RETENTION_DAYS = 30
PRUNE_EVERY_S = 86_400
PRUNE_MAX_SCAN = 20_000
PRUNE_MAX_DELETE = 2_000
OWN_GITHUB_OWNERS = ("djbclark",)

WEB_TOOLS = {"WebSearch", "WebFetch"}
# MCP servers, by normalised name (lower case, "-" -> "_", "claude_ai_" and "plugin_<x>_" prefixes
# stripped; a server also matches as the tail "_<name>"). Tool names after the server are free-form.
WEB_SERVERS = ("firecrawl", "exa", "jina", "parallel", "parallel_search", "tavily", "perplexity",
               "brave_search", "context7", "deepwiki", "duckduckgo", "kagi", "searxng", "web_search")
MEMORY_SERVERS = ("basic_memory", "memory", "mem0", "openmemory")
OWN_CODE_SERVERS = ("graft", "trail")
OTHER_KNOWN_SERVERS = ("github", "hermes", "ghost_os", "cow", "beeper", "bezalel", "gmail",
                       "playwright", "chrome_devtools", "orca", "paseo", "herdr", "superset")
ALL_SERVERS = {*WEB_SERVERS, *MEMORY_SERVERS, *OWN_CODE_SERVERS, *OTHER_KNOWN_SERVERS}
KNOWN_TOOLS = {
    "Bash", "BashOutput", "KillShell", "Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "NotebookRead",
    "Grep", "Glob", "LSP", "WebSearch", "WebFetch", "Task", "Agent", "TodoWrite", "Skill", "SlashCommand",
    "ExitPlanMode", "AskUserQuestion", "ToolSearch", "TaskOutput", "TaskStop", "Monitor",
    "ScheduleWakeup", "shell", "shell_command", "exec_command", "apply_patch",
}
KNOWN_MODELS_RE = re.compile(r"^(claude|gpt|o\d|gemini|grok|qwen|glm|kimi|deepseek|mistral)[a-z0-9._-]{0,40}$", re.I)
MCP_TOOL_RE = re.compile(r"^[A-Za-z0-9_-]{1,60}$")
READ_TOOLS = {"Read", "Grep", "Glob", "NotebookRead", "LSP"}
SHELL_TOOLS = {"Bash", "shell", "shell_command", "exec_command"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
# Read commands whose arguments name what is read.
READ_CMDS = {"rg", "grep", "egrep", "fgrep", "ggrep", "cat", "head", "tail", "sed", "gsed", "awk", "gawk",
             "bat", "find", "fd", "ls", "less", "more", "tree", "wc", "graft"}
PATTERN_FIRST = {"rg", "grep", "egrep", "fgrep", "ggrep", "fd"}      # first positional is the pattern
SCRIPT_FIRST = {"sed", "gsed", "awk", "gawk"}                          # first positional is the script
PATTERN_FLAGS = {"-e", "--regexp", "-f", "--file", "--expression"}
VALUE_FLAGS = {
    "rg": {"-e", "-f", "-g", "-t", "-T", "-m", "-A", "-B", "-C", "-j", "-M", "-r", "-d", "--glob", "--iglob",
           "--type", "--type-not", "--max-count", "--regexp", "--file", "--max-depth", "--context",
           "--after-context", "--before-context", "--replace", "--threads", "--max-filesize", "--sort",
           "--sortr", "--encoding", "--colors", "--engine", "--ignore-file", "--pre", "--pre-glob"},
    "grep": {"-e", "-f", "-m", "-A", "-B", "-C", "-d", "-D", "--regexp", "--file", "--max-count", "--include",
             "--exclude", "--exclude-dir", "--context", "--after-context", "--before-context", "--label",
             "--binary-files"},
    "head": {"-n", "-c", "--lines", "--bytes"},
    "tail": {"-n", "-c", "--lines", "--bytes"},
    "sed": {"-e", "-f", "-l", "--expression", "--file"},
    "awk": {"-F", "-f", "-v"},
    "ls": {"-I", "-w", "-T", "--ignore", "--width"},
    "fd": {"-e", "-E", "-t", "-d", "-x", "-X", "-j", "-S", "--extension", "--exclude", "--type",
           "--max-depth", "--color", "--size", "--changed-within", "--changed-before"},
    "bat": {"-l", "-r", "-H", "--language", "--line-range", "--theme", "--style", "--color", "--tabs",
            "--terminal-width"},
    "tree": {"-L", "-P", "-I", "--charset"},
}
VALUE_FLAGS.update({k: VALUE_FLAGS["grep"] for k in ("egrep", "fgrep", "ggrep")})
VALUE_FLAGS.update({"gsed": VALUE_FLAGS["sed"], "gawk": VALUE_FLAGS["awk"]})
FETCH_CMDS = {"web-get", "web_get", "curl", "wget", "http", "https", "xh"}
SUDO_ARG_OPTS = {"-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U", "--user", "--group", "--host",
                 "--prompt", "--close-from", "--chdir", "--chroot", "--command-timeout", "--other-user"}
ENV_ARG_OPTS = {"-u", "-C", "-S", "--unset", "--chdir", "--split-string"}
NICE_ARG_OPTS = {"-n", "-c", "-p", "--adjustment", "--class"}
PLAIN_WRAPPERS = {"command", "time", "nohup", "exec", "builtin", "rtk", "stdbuf"}
SHELL_KEYWORDS = {"do", "then", "else", "elif", "if", "while", "until", "!", "{"}   # prefix of the command after them
EXTERNAL_PARTS = ("node_modules", "site-packages", "dist-packages", ".venv", "venv/lib",
                  "vendor", "third_party", "third-party", ".cargo/registry", ".cargo/git",
                  "go/pkg/mod", ".gradle", ".m2", ".npm", ".pnpm-store", ".cache", "nix/store")
QUOTING_MARKERS = ("syntax error", "unexpected eof", "unterminated")
PATH_KEYS = ("file_path", "path", "notebook_path", "filePath")
URL_RE = re.compile(r"^https?://", re.I)
ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_]\w*=")
GH_REPO_RE = re.compile(r"^/?repos/([^/]+)/", re.I)
MEMORY_REL_RE = re.compile(r"^(\.claude/projects/[^/]+/memory|ops/[^/]+/memory|\.agents|kb|basic-memory)(/|$)")
SID_BAD_RE = re.compile(r"[^A-Za-z0-9._-]")
SHELL_PUNCT = ";&|<>()\n"
INTERNAL_SUFFIXES = (".local", ".internal", ".lan", ".home.arpa", ".sipb.cloud", ".ts.net", ".corp", ".intranet")
TWO_LABEL_SUFFIXES = {"co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "co.jp", "co.nz", "com.br", "co.in"}
ALLOWED_DOMAINS = {
    "github.com", "githubusercontent.com", "gitlab.com", "bitbucket.org", "codeberg.org", "sourcehut.org",
    "python.org", "pypi.org", "readthedocs.io", "readthedocs.org", "npmjs.com", "nodejs.org", "crates.io",
    "docs.rs", "rust-lang.org", "go.dev", "golang.org", "stackoverflow.com", "stackexchange.com",
    "mozilla.org", "wikipedia.org", "nixos.org", "kernel.org", "gnu.org", "apache.org", "debian.org",
    "ubuntu.com", "archlinux.org", "freedesktop.org", "w3.org", "ietf.org", "arxiv.org", "huggingface.co",
    "anthropic.com", "openai.com", "google.com", "microsoft.com", "apple.com", "amazon.com", "cloudflare.com",
    "reddit.com", "ycombinator.com", "medium.com", "substack.com", "rubygems.org", "hex.pm", "maven.org",
    "typescriptlang.org", "pytorch.org", "kubernetes.io", "docker.com", "hashicorp.com", "jetbrains.com",
}


def _state_dir() -> Path:
    return Path(os.environ.get("PRIOR_ART_STATE") or Path.home() / ".claude/state/prior-art-shadow")


def _idle_s() -> float:
    try:
        return float(os.environ.get("PRIOR_ART_IDLE_S", DEFAULT_IDLE_S))
    except ValueError:
        return float(DEFAULT_IDLE_S)


def _retention_s() -> float:
    try:
        return float(os.environ.get("PRIOR_ART_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)) * 86_400
    except ValueError:
        return DEFAULT_RETENTION_DAYS * 86_400.0


def _now() -> float:
    try:
        return float(os.environ["PRIOR_ART_NOW"])      # tests only
    except (KeyError, ValueError):
        return time.time()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def safe_session_id(sid: object) -> str:
    s = SID_BAD_RE.sub("_", str(sid or ""))[:100].lstrip(".")
    return s or "unknown"


def agent_key(data: dict) -> str:
    """"" for the main agent, "a<12 hex>" for a subagent (payload `agent_id`)."""
    aid = data.get("agent_id")
    return "a" + _sha(aid)[:12] if isinstance(aid, str) and aid else ""


def tool_label(tool: str) -> str:
    """The tool name as recorded: only fixed names, so a planted name never reaches the record."""
    if tool in KNOWN_TOOLS:
        return tool
    if tool.startswith("mcp__"):
        server, _, name = tool[5:].partition("__")
        norm = _norm_server(server)
        kind = _server_kind(norm)
        if not kind:
            return "mcp__other"
        if norm not in ALL_SERVERS:                     # matched only by a suffix: keep the kind, not the name
            return f"mcp__{kind}_server"
        return f"mcp__{server.lower()}__{name}"[:100] if name and MCP_TOOL_RE.match(name) else f"mcp__{server.lower()}"
    return "other"


def read_event() -> dict | None:
    """Normalize the hook payload (same tolerant parse as bash_habits_gate.main: one JSON object on
    stdin, anything else ignored). Bytes are decoded leniently and trailing junk after the first
    JSON value is dropped, so a bad UTF-8 tail or a second document never loses the event."""
    raw = sys.stdin.buffer.read(MAX_STDIN)
    text = raw.decode("utf-8", "replace").lstrip()
    try:
        data, _ = json.JSONDecoder().raw_decode(text)
    except (ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def walk_text(obj: object) -> int:
    """UTF-8 byte length of every string leaf in a tool response, iteratively and bounded."""
    total, nodes = 0, 0
    stack = [(obj, 0)]
    while stack and nodes < MAX_WALK_NODES:
        cur, depth = stack.pop()
        nodes += 1
        if isinstance(cur, str):
            total += len(cur.encode("utf-8", "replace"))
        elif depth < MAX_WALK_DEPTH:
            if isinstance(cur, dict):
                stack.extend((v, depth + 1) for k, v in cur.items() if k != "type")   # content-block labels
            elif isinstance(cur, list):
                stack.extend((v, depth + 1) for v in cur)
    return total


def scan_text(obj: object) -> str:
    """Up to SCAN_CHARS of string leaves, lower-cased, for marker matching only (never stored)."""
    parts, size, nodes = [], 0, 0
    stack = [(obj, 0)]
    while stack and nodes < MAX_WALK_NODES and size < SCAN_CHARS:
        cur, depth = stack.pop()
        nodes += 1
        if isinstance(cur, str):
            parts.append(cur[:SCAN_CHARS])
            size += len(parts[-1])
        elif depth < MAX_WALK_DEPTH:
            if isinstance(cur, dict):
                stack.extend((v, depth + 1) for v in cur.values())
            elif isinstance(cur, list):
                stack.extend((v, depth + 1) for v in cur)
    return "\n".join(parts).lower()


# ---- paths ------------------------------------------------------------------------------------

def _expand(p: str, cwd: str) -> str:
    if p.startswith("~"):
        p = str(Path.home()) + p[1:]
    elif not p.startswith("/"):
        p = os.path.join(cwd or "/", p)
    return os.path.normpath(p)


def _expand_word(w: str, cwd: str) -> str | None:
    """A shell word as an absolute path; None when it needs a variable we cannot know, or is /dev/*."""
    home = str(Path.home())
    for var in ("$HOME", "${HOME}"):
        if w.startswith(var):
            w = home + w[len(var):]
    if "$" in w or "`" in w:
        return None
    p = _expand(w, cwd)
    return None if p == "/dev" or p.startswith("/dev/") else p


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def is_external(path: str) -> bool:
    home = str(Path.home())
    if _under(path, "/nix/store"):
        return True
    if _under(path, home + "/.cache"):
        return True
    parts = "/" + "/".join(p for p in path.split("/") if p) + "/"
    return any(f"/{m}/" in parts for m in EXTERNAL_PARTS if m != ".cache" and m != "nix/store")


def is_memory(path: str) -> bool:
    home = str(Path.home())
    return _under(path, home) and bool(MEMORY_REL_RE.match(path[len(home):].lstrip("/")))


def is_own(path: str, cwd: str) -> bool:
    home = str(Path.home())
    roots = [home + "/src", home + "/ops"]
    if cwd and cwd not in ("/", home):
        roots.append(os.path.normpath(cwd))
    return any(_under(path, r) for r in roots)


def path_class(path: str, cwd: str) -> str:
    """A fixed enum for where a read path lies; never a path segment."""
    home = str(Path.home())
    if is_memory(path):
        return "memory"
    if cwd and cwd not in ("/", home) and _under(path, os.path.normpath(cwd)):
        return "cwd"
    if _under(path, home + "/ops"):
        return "ops"
    if _under(path, home + "/src"):
        return "src"
    if _under(path, "/nix/store"):
        return "nix"
    if any(_under(path, home + sub) for sub in ("/.cache", "/.npm", "/.m2", "/.gradle", "/.cargo",
                                                 "/.rustup", "/.local/share")):
        return "cache"
    if any(_under(path, home + sub) for sub in ("/.local/state", "/.claude", "/.config")):
        return "state"
    if _under(path, home):
        return "home"
    if any(_under(path, r) for r in ("/tmp", "/private/tmp", "/private/var/folders", "/var/folders")):
        return "tmp"
    return "other"


def _tool_paths(tool: str, tin: dict, cwd: str) -> list[str]:
    out = [v for k in PATH_KEYS if isinstance(v := tin.get(k), str) and v]
    pat = tin.get("pattern")
    if tool == "Glob" and isinstance(pat, str) and pat[:1] in ("/", "~"):
        out.append(pat)
    return [_expand(p, cwd) for p in out[:MAX_PATHS]]


def _classify_paths(paths: list[str], cwd: str) -> tuple[str, str]:
    """(category, path_class) for what was read; no path means the session cwd."""
    paths = paths or ([os.path.normpath(cwd)] if cwd else [])
    if not paths:
        return "own_code", ""
    for pick, cat in ((is_memory, "memory"), (is_external, "external_code")):
        hit = next((p for p in paths if pick(p)), None)
        if hit:
            return cat, path_class(hit, cwd)
    if all(is_own(p, cwd) for p in paths):
        return "own_code", path_class(paths[0], cwd)
    return "private_other", path_class(paths[0], cwd)


# ---- shell commands ---------------------------------------------------------------------------

def _command(tin: dict) -> str:
    cmd = tin.get("command") or tin.get("cmd")
    if isinstance(cmd, list):
        cmd = cmd[-1] if cmd else ""
    return cmd if isinstance(cmd, str) else ""


def _shell_tokens(cmd: str) -> list[str]:
    cmd = cmd[:MAX_CMD_CHARS]
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=SHELL_PUNCT)
        lex.whitespace = " \t\r"                       # a newline is a command separator
        lex.whitespace_split = True
        lex.commenters = ""
        return list(itertools.islice(lex, MAX_TOKENS))
    except ValueError:                                  # unbalanced quote: a coarse split is enough
        toks = re.split(r"(&&|\|\||\|&|[;|&\n()<>])|\s+", cmd)
        return [t.strip("'\"") for t in toks if t and t.strip("'\"")][:MAX_TOKENS]


def _is_punct(tok: str) -> bool:
    return bool(tok) and all(c in SHELL_PUNCT for c in tok)


def _commands(tokens: list[str]) -> list[list[str]]:
    """The first command of every pipeline, as a word list: split on && || ; & newline and parentheses,
    drop everything after the first | (a pipe filter is not a read), and drop redirect operators with
    their targets and heredoc bodies."""
    cmds: list[list[str]] = []
    cur: list[str] = []
    piped = False
    heredoc = body = None
    prev_nl = False
    i, n = 0, len(tokens)
    while i < n:
        t = tokens[i]
        i += 1
        if body is not None:                            # inside a heredoc body
            if t == body and prev_nl:
                body = None
            prev_nl = "\n" in t and _is_punct(t)
            continue
        if not _is_punct(t):
            prev_nl = False
            if not piped and t != "$":
                cur.append(t)
            continue
        redirect = ("<" in t or ">" in t) and "(" not in t
        if redirect:
            if t.strip("\n") in ("<<", "<<-") and i < n:
                heredoc = tokens[i]
                i += 1
            elif i < n and not _is_punct(tokens[i]):
                i += 1                                  # the redirect target
            if cur and cur[-1].isdigit():
                cur.pop()                               # the fd in 2>file
            continue
        core = t.replace("\n", "")
        if core in ("|", "|&"):
            piped = True
            continue
        if cur:
            cmds.append(cur)
        cur, piped = [], False
        prev_nl = "\n" in t
        if prev_nl and heredoc is not None:
            body, heredoc = heredoc, None
    if cur:
        cmds.append(cur)
    return cmds


def _skip_opts(words: list[str], i: int, arg_opts: set, assign: bool = False) -> int:
    while i < len(words):
        w = words[i]
        if assign and ENV_ASSIGN_RE.match(w):
            i += 1
        elif w.startswith("-") and w != "-":
            i += 2 if w in arg_opts else 1
        else:
            break
    return i


def _unwrap(words: list[str]) -> tuple[str, list[str]]:
    """Strip FOO=bar, sudo/env/nice/time/... and their options: (command basename, its arguments)."""
    i, n = 0, len(words)
    while i < n:
        w = words[i]
        if ENV_ASSIGN_RE.match(w) or w in SHELL_KEYWORDS:
            i += 1
            continue
        base = os.path.basename(w)
        if base in ("sudo", "doas"):
            i = _skip_opts(words, i + 1, SUDO_ARG_OPTS)
        elif base == "env":
            i = _skip_opts(words, i + 1, ENV_ARG_OPTS, assign=True)
        elif base in ("nice", "ionice"):
            i = _skip_opts(words, i + 1, NICE_ARG_OPTS)
        elif base == "timeout":
            i = _skip_opts(words, i + 1, {"-s", "-k", "--signal", "--kill-after"}) + 1
        elif base in PLAIN_WRAPPERS:
            if base == "command" and any(a in ("-v", "-V") for a in words[i + 1:i + 3]):
                return "command", []
            i = _skip_opts(words, i + 1, set())
        else:
            return base, words[i + 1:]
    return "", []


def _positionals(name: str, args: list[str]) -> list[str]:
    """The arguments of a read command that name what is read (flags, their values, the grep/rg pattern
    and the sed/awk script removed); None-free, unexpanded."""
    if name == "find":
        paths = []
        for a in args:
            if a in ("-H", "-L", "-P", "-E", "-x", "-X", "-s", "-d") and not paths:
                continue
            if a.startswith("-") or a in ("!", "(", ")", "\\("):
                break
            paths.append(a)
        return paths
    if name == "graft":
        return []                                       # `graft ask "question"`: words, not paths
    valued = VALUE_FLAGS.get(name, set())
    pos: list[str] = []
    has_pat = False
    i, n = 0, len(args)
    while i < n:
        a = args[i]
        i += 1
        if a == "--":
            pos.extend(args[i:])
            break
        if not a.startswith("-") or a == "-":
            pos.append(a)
            continue
        flag = a.split("=", 1)[0]
        if flag in PATTERN_FLAGS:
            has_pat = True
        if "=" not in a and flag in valued:
            i += 1
    if name in PATTERN_FIRST and not has_pat and "--files" not in args:
        pos = pos[1:]
    elif name in SCRIPT_FIRST and not has_pat:
        pos = pos[1:]
    return pos


def _in_place_edit(name: str, args: list[str]) -> bool:
    return name in ("sed", "gsed") and any(a == "--in-place" or a.startswith("--in-place=")
                                           or (a.startswith("-") and not a.startswith("--") and "i" in a[1:])
                                           for a in args)


def _gh_is_prior_art(args: list[str]) -> bool:
    pos = [a for a in args if not a.startswith("-")]
    if not pos:
        return False
    if pos[0] == "search":
        return True
    if pos[0] == "api":
        for a in pos[1:3]:
            m = GH_REPO_RE.match(a)
            if m:
                return m.group(1).lower() not in OWN_GITHUB_OWNERS
        return False
    if pos[0] == "repo" and len(pos) >= 3 and pos[1] in ("view", "clone") and "/" in pos[2]:
        return pos[2].split("/")[0].lower() not in OWN_GITHUB_OWNERS
    return False


def _shell_facts(cmd: str, cwd: str, depth: int = 0) -> dict:
    """{web: bool, url: str, reads: [[abs path, ...], ...]} for one shell command string."""
    facts: dict = {"web": False, "url": "", "reads": []}
    eff = cwd or "/"
    for words in _commands(_shell_tokens(cmd)):
        name, args = _unwrap(words)
        if not name:
            continue
        if name in ("cd", "pushd"):
            tgt = next((a for a in args if not a.startswith("-")), "")
            if tgt != "-":
                eff = _expand_word(tgt or "~", eff) or eff
        elif name in SHELLS and depth < 2:
            flags = [a for a in args[:3] if a.startswith("-") and not a.startswith("--") and "c" in a]
            if flags and len(args) > args.index(flags[0]) + 1:
                sub = _shell_facts(args[args.index(flags[0]) + 1], eff, depth + 1)
                facts["web"] = facts["web"] or sub["web"]
                facts["url"] = facts["url"] or sub["url"]
                facts["reads"].extend(sub["reads"])
        elif name in FETCH_CMDS:
            url = next((a for a in args if URL_RE.match(a)), "")
            if url and host_info(url)[0] == "public":
                facts["web"], facts["url"] = True, facts["url"] or url
        elif name == "gh":
            facts["web"] = facts["web"] or _gh_is_prior_art(args)
        elif name in READ_CMDS and not _in_place_edit(name, args):
            paths = [p for a in _positionals(name, args)[:MAX_PATHS] if (p := _expand_word(a, eff))]
            facts["reads"].append(paths or [os.path.normpath(eff)])
    return facts


# ---- URLs and MCP servers ---------------------------------------------------------------------

def host_info(url: str) -> tuple[str, str]:
    """(host_class, registrable domain if on ALLOWED_DOMAINS else "") for a URL; host_class is one of
    loopback, private_ip, internal, public, invalid. Nothing else about the URL is kept."""
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return "invalid", ""
    if not host:
        return "invalid", ""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if ip.is_loopback:
            return "loopback", ""
        if not ip.is_global:
            return "private_ip", ""
        return "public", ""
    if host == "localhost" or host.endswith(".localhost"):
        return "loopback", ""
    if "." not in host or host.endswith(INTERNAL_SUFFIXES):
        return "internal", ""
    labels = host.split(".")
    keep = 3 if ".".join(labels[-2:]) in TWO_LABEL_SUFFIXES else 2
    domain = ".".join(labels[-keep:])
    return "public", domain if domain in ALLOWED_DOMAINS else ""


def _norm_server(server: str) -> str:
    s = server.lower().replace("-", "_")
    if s.startswith("claude_ai_"):
        s = s[len("claude_ai_"):]
    return s


def _server_kind(server: str) -> str:
    """web, memory, own, other or "" for a normalised MCP server name."""
    def match(names):
        return any(server == n or server.endswith("_" + n) for n in names)
    if match(WEB_SERVERS):
        return "web"
    if match(MEMORY_SERVERS):
        return "memory"
    if match(OWN_CODE_SERVERS):
        return "own"
    return "other" if match(OTHER_KNOWN_SERVERS) else ""


def classify(tool: str, tin: dict, cwd: str) -> tuple[str, dict]:
    """(category, extras) from the tool name and input; heuristic, no I/O. extras may hold host_class,
    host and path_class."""
    extras: dict = {}
    kind = ""
    if tool.startswith("mcp__"):
        server, _, name = tool[5:].partition("__")
        kind = _server_kind(_norm_server(server))
        if kind == "other" and _norm_server(server) == "github" and name.startswith("search_"):
            kind = "web"
    if tool in WEB_TOOLS or kind == "web":
        url = tin.get("url") if isinstance(tin.get("url"), str) else ""
        if url:
            extras["host_class"], host = host_info(url)
            if host:
                extras["host"] = host
        return "web", extras
    if kind == "memory":
        return "memory", extras
    if kind == "own":
        return "own_code", extras
    if tool in SHELL_TOOLS:
        facts = _shell_facts(_command(tin), cwd)
        if facts["web"]:
            if facts["url"]:
                extras["host_class"], host = host_info(facts["url"])
                if host:
                    extras["host"] = host
            return "web", extras
        if not facts["reads"]:
            return "private_other", extras
        cat, pclass = _classify_paths([p for paths in facts["reads"] for p in paths], cwd)
        if pclass:
            extras["path_class"] = pclass
        return cat, extras
    if tool in READ_TOOLS:
        cat, pclass = _classify_paths(_tool_paths(tool, tin, cwd), cwd)
        if pclass:
            extras["path_class"] = pclass
        return cat, extras
    return "private_other", extras


def is_failed(data: dict, resp: object) -> bool:
    if data.get("hook_event_name") == "PostToolUseFailure" or "error" in data:
        return True
    if data.get("is_error") is True:
        return True
    if isinstance(resp, dict):
        if resp.get("is_error") is True or resp.get("isError") is True:
            return True
        for k in ("exit_code", "exitCode", "returncode", "returnCode"):
            v = resp.get(k)
            if isinstance(v, int) and not isinstance(v, bool) and v != 0:
                return True
    return False


# ---- files ------------------------------------------------------------------------------------

def _open_regular(path: Path, flags: int, mode: int = 0o600) -> int:
    """Open without following a symlink or blocking on a FIFO, and insist on a regular file."""
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, mode)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, "not a regular file")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _load_state(path: Path) -> dict:
    try:
        fd = _open_regular(path, os.O_RDONLY)
    except OSError:
        return {}
    try:
        st = json.loads(os.read(fd, MAX_STATE_BYTES))
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}
    finally:
        os.close(fd)


def _save_state(path: Path, st: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".st-")
    try:
        os.write(fd, json.dumps(st, separators=(",", ":")).encode())
        os.close(fd)
        fd = -1
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _ensure_dir(d: Path) -> None:
    """Create the state dir 0700, or tighten an existing one; refuse a symlink, a non-directory and a
    directory owned by someone else."""
    try:
        st = os.lstat(d)
    except FileNotFoundError:
        d.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(FileExistsError):
            d.mkdir(mode=0o700)
        st = os.lstat(d)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise OSError(errno.ENOTDIR, "state path is not our directory")
    if stat.S_IMODE(st.st_mode) != 0o700:
        os.chmod(d, 0o700)


def _lock(path: Path) -> int:
    fd = _open_regular(path, os.O_RDWR | os.O_CREAT)
    for _ in range(LOCK_RETRIES):
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            time.sleep(LOCK_WAIT_S)
    os.close(fd)
    return -1


def _count_drop(path: Path) -> None:
    """One byte appended per event lost to a held lock; the next record reports the difference."""
    with contextlib.suppress(Exception):
        fd = _open_regular(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        try:
            os.write(fd, b".")
        finally:
            os.close(fd)


def _drops(path: Path) -> int:
    try:
        return os.lstat(path).st_size
    except OSError:
        return 0


def prune(d: Path, keep_prefix: str, now: float) -> None:
    """Delete this tool's files older than the retention, at most once a day (stamp file), bounded."""
    stamp = d / ".prune-stamp"
    with contextlib.suppress(OSError):
        if now - os.lstat(stamp).st_mtime < PRUNE_EVERY_S:
            return
    fd = _open_regular(stamp, os.O_WRONLY | os.O_CREAT)
    os.close(fd)
    os.utime(stamp, (now, now))
    cutoff = now - _retention_s()
    scanned = deleted = 0
    with os.scandir(d) as it:
        for e in it:
            scanned += 1
            if scanned > PRUNE_MAX_SCAN or deleted >= PRUNE_MAX_DELETE:
                break
            name = e.name
            if name.startswith(keep_prefix) or not (name.endswith((".jsonl", ".state.json", ".lock", ".drops"))
                                                    or name.startswith(".st-")):
                continue
            try:
                st = e.stat(follow_symlinks=False)
                if stat.S_ISREG(st.st_mode) and st.st_mtime < cutoff:
                    os.unlink(e.path)
                    deleted += 1
            except OSError:
                continue


# ---- records ----------------------------------------------------------------------------------

def build_record(data: dict, st: dict, now: float, agent: str = "", dropped: int = 0) -> dict:
    event = str(data.get("hook_event_name") or "PostToolUse")
    tool = str(data.get("tool_name") or "")
    tin = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    resp = data.get("tool_response") if "tool_response" in data else data.get("error")
    cwd = data.get("cwd") if isinstance(data.get("cwd"), str) else ""
    sid = str(data.get("session_id") or "")

    last_ts = st.get("last_ts")
    elapsed = int((now - last_ts) * 1000) if isinstance(last_ts, (int, float)) and now >= last_ts else None
    new_task = event == "UserPromptSubmit" or (
        isinstance(last_ts, (int, float)) and now - last_ts > _idle_s())
    if new_task:
        st.update(task_seq=int(st.get("task_seq", 0)) + 1, web_or_memory=False, run=0,
                  recent=[], last_failed_call="")
    st.setdefault("salt", os.urandom(8).hex())

    model = str(data.get("model") or "")
    rec: dict = {
        "ts": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="milliseconds"),
        "schema": SCHEMA,
        "classifier_version": CLASSIFIER_VERSION,
        "session": _sha(sid)[:12],
        "event": event,
        "client": model[:60] if KNOWN_MODELS_RE.match(model) else "claude-code",
    }
    if agent:
        rec["agent"] = agent[1:9]
    if dropped:
        rec["dropped"] = dropped
    if event == "UserPromptSubmit":
        rec.update(tool="", category="task_change", failed=False, bytes=0, tokens_est=0,
                   web_or_memory_before=False, run_length=0, external_run=False, duplicate=False,
                   retry=False, quoting_failure=False)
    else:
        category, extras = classify(tool, tin, cwd)
        failed = is_failed(data, resp)
        nbytes = walk_text(resp)
        call = _sha(st["salt"] + tool + json.dumps(tin, sort_keys=True, default=str)[:200_000])[:12]
        recent = st.get("recent") if isinstance(st.get("recent"), list) else []
        duplicate = call in recent
        retry = bool(call) and call == st.get("last_failed_call")
        quoting = (failed and tool in SHELL_TOOLS
                   and any(m in scan_text(resp) for m in QUOTING_MARKERS))
        before = bool(st.get("web_or_memory"))
        run = int(st.get("run", 0))
        if category == "external_code":
            run += 1
        elif category in ("web", "memory", "own_code"):
            run = 0
        if category in ("web", "memory"):
            st["web_or_memory"] = True
        st["run"] = run
        st["recent"] = (recent + [call])[-RECENT_CALLS:]
        st["last_failed_call"] = call if failed else ""
        rec.update(tool=tool_label(tool), category=category, failed=failed,
                   bytes=nbytes, tokens_est=nbytes // 4, web_or_memory_before=before,
                   run_length=run, external_run=run >= EXTERNAL_RUN, duplicate=duplicate,
                   retry=retry, quoting_failure=quoting)
        rec.update(extras)
    rec["task_seq"] = int(st.get("task_seq", 0))
    rec["elapsed_ms"] = elapsed
    st["last_ts"] = now
    return rec


def record(data: dict) -> None:
    sid = safe_session_id(data.get("session_id"))
    agent = agent_key(data)
    key = f"{sid}.{agent}" if agent else sid
    d = _state_dir()
    _ensure_dir(d)
    now = _now()
    lock_fd = _lock(d / f"{sid}.lock")
    if lock_fd < 0:
        _count_drop(d / f"{key}.drops")
        return
    try:
        st_path = d / f"{key}.state.json"
        st = _load_state(st_path)
        if agent and not st:                            # a new subagent joins the main agent's task
            st["task_seq"] = int(_load_state(d / f"{sid}.state.json").get("task_seq", 0) or 0)
        drops = _drops(d / f"{key}.drops")
        fd = _open_regular(d / f"{sid}.jsonl", os.O_RDWR | os.O_APPEND | os.O_CREAT)
        try:
            size = os.fstat(fd).st_size
            if size >= len(CAP_TAIL) and os.pread(fd, len(CAP_TAIL), size - len(CAP_TAIL)) == CAP_TAIL:
                return
            seen = int(st.get("drops_seen", 0) or 0)
            rec = build_record(data, st, now, agent, max(0, drops - seen))
            st["drops_seen"] = drops
            line = (json.dumps(rec, separators=(",", ":")) + "\n").encode()
            if size + len(line) + len(CAP_TAIL) > CAP_BYTES:
                os.write(fd, CAP_TAIL)
            else:
                os.write(fd, line)
        finally:
            os.close(fd)
        _save_state(st_path, st)
    finally:
        os.close(lock_fd)
    if data.get("hook_event_name") == "UserPromptSubmit" and not agent:
        with contextlib.suppress(Exception):
            prune(d, sid + ".", now)


def main() -> None:
    with contextlib.suppress(Exception):
        sys.stderr = open(os.devnull, "w")             # noqa: SIM115 - shadow mode is silent
    try:
        if os.environ.get("PRIOR_ART_SHADOW") == "0":
            return
        data = read_event()
        if data is not None:
            record(data)
    except BaseException:                              # noqa: BLE001 - incl. RecursionError, MemoryError
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
