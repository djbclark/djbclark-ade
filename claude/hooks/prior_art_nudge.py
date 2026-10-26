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
`{"capped":true}` line). Carry-over (previous timestamp, run counters, a salt, recent call hashes, and the prompt counters
`prompt_seq` / `prompt_seq_seen`) lives
in <session id>.state.json for the main agent and <session id>.<agent key>.state.json for each subagent
(Claude Code puts the PARENT's session_id and the subagent's own `agent_id` in every hook payload, so
state keyed on the session alone interleaves parallel subagents), replaced atomically under
<session id>.lock. Every file is opened O_NOFOLLOW | O_NONBLOCK and must be a regular file.

Fields: ts (UTC ISO), schema and classifier_version (so a later reclassification can tell old rows from
new; the records keep no raw input), session (first 12 hex of sha256 of the session id), event (one of
the three registered hook names, else "other"), client (see PRIVACY), tool (see PRIVACY),
category, failed, bytes (UTF-8 length of the tool response or error text), tokens_est (bytes // 4, an
estimate), web_or_memory_before (a web or memory event earlier in the same task), run_length
(consecutive external-tree reads without a web, memory or own-code event between; `external_run` is
run_length >= 3), duplicate, retry, quoting_failure, task_seq, elapsed_ms since the previous event of the
same agent; plus, when they apply: `agent` (first 8 hex of sha256 of a subagent's agent_id, absent for the
main agent), `host_class` and `host` for a fetched URL, `path_class` for a read path, `dropped` (events
lost to a held lock since the previous record).

PRIVACY, exactly what is stored: the category and the booleans, counts and timestamps above; the session
pseudonym; `event` only as one of PostToolUse, PostToolUseFailure, UserPromptSubmit or "other"; `tool`
only as a known built-in tool name, `mcp__<server>` for an MCP server on the fixed lists (the tool name
after the server is never kept), `mcp__other`, `mcp__<kind>_server` (a kind matched by suffix only) or
"other"; `client` only as a model family from a fixed list, for Claude its tier (opus, sonnet, haiku),
then up to three one- or two-digit version numbers, else "claude-code"; `host_class` (loopback,
private_ip, internal, public, invalid); `host` only for a public URL whose registrable domain is on the
fixed ALLOWED_DOMAINS list, and then only that registrable domain, never a sub-domain, port, user, path,
query or fragment; `path_class` (a fixed enum, never a path segment: cwd, src, ops, memory, nix, cache, state,
home, tmp, other, or `unresolved` for a shell read whose every path word needs an unknown variable). NEVER stored: a command, a path, a
query, a URL, a prompt, tool output, a host outside the allowlist, a server name outside the allowlist.
The session id itself is the record's file name (sanitised). Call hashes kept in the state file are
salted with a per-session random value that sits beside them in the same file, so the salt only stops
linking the same call across sessions; whoever can read the state directory can still brute-force a
low-entropy call, and the directory is mode 0700 for that reason. Call hashes never reach the record.

Shell variables: a path word is resolved from the same command's literal assignments (`X=...; cat $X/a`,
`export`, `$HOME`) and literal for-loop lists; one that still needs an unknown variable (`cat "$OUT"`, a
`$( )` value, `${X:-y}`) is never the cwd: with no other resolved path the event is private_other with
`path_class` unresolved, which does not reset run_length. Stated limits: docs/queue.md "D2 built".

Categories: own_code, external_code, memory, web, private_other, task_change (UserPromptSubmit).
A new UserPromptSubmit of the main agent, or an idle gap over PRIOR_ART_IDLE_S (default 1800 s), starts a new task and
resets the run counters. A subagent follows its parent's prompts only: when the user's prompt count has
moved since the subagent's last event, its state is reset (and its elapsed_ms is null); the parent's idle
gap, which happens while a subagent works, does not reset it. `PRIOR_ART_SHADOW=0` disables recording. A UserPromptSubmit also prunes files
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
import socket
import stat
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit

SCHEMA = 2
CLASSIFIER_VERSION = 5

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
MAX_VALUE_CHARS = 4096                                  # a resolved word longer than a path can be is unknown
RECENT_CALLS = 30
EXTERNAL_RUN = 3
LOCK_WAIT_TOTAL_S = 0.5                                 # wall-clock bound on waiting for the session lock
LOCK_POLL_S = 0.02
DEFAULT_IDLE_S = 1800
DEFAULT_RETENTION_DAYS = 30
PRUNE_EVERY_S = 86_400
PRUNE_MAX_SCAN = 20_000
PRUNE_MAX_DELETE = 2_000
# Prune only what this tool names: <session id>[.a<12 hex>].(jsonl|state.json|lock|drops) and mkstemp leftovers.
PRUNE_NAME_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,99}\.(a[0-9a-f]{12}\.)?(jsonl|state\.json|lock|drops)$")
PRUNE_TMP_RE = re.compile(r"^\.st-[a-z0-9_]{8}$")
OWN_GITHUB_OWNERS = ("djbclark",)

WEB_TOOLS = {"WebSearch", "WebFetch"}
# MCP servers, by normalised name (lower case, "-" -> "_", a "claude_ai_" prefix stripped; a server also
# matches as the tail "_<name>", which covers "plugin_<x>_<name>"). The tool name after the server is
# never recorded.
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
KNOWN_EVENTS = {"PostToolUse", "PostToolUseFailure", "UserPromptSubmit"}
MODEL_FAMILIES = ("claude", "gpt", "gemini", "grok", "qwen", "glm", "kimi", "deepseek", "mistral")
CLAUDE_TIERS = ("opus", "sonnet", "haiku")
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
ASSIGN_BUILTINS = {"export", "declare", "local", "readonly", "typeset"}
GH_REPO_RE = re.compile(r"^/?repos/([^/]+)/([^/]+)/?(.*)$", re.I | re.S)
GH_OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")           # a literal login; no $VAR, {owner}, :owner
GH_CODE_TAIL_RE = re.compile(r"^(contents|readme|releases|tags|tarball|zipball|git)(/|\?|$)", re.I)
GH_API_VALUE_OPTS = {"-X", "--method", "-H", "--header", "-f", "--raw-field", "-F", "--field", "-q", "--jq",
                     "-t", "--template", "--input", "--hostname", "--cache", "-p", "--preview"}
GH_REPO_VALUE_OPTS = {"-R", "--repo", "--json", "-q", "--jq", "-t", "--template", "-b", "--branch",
                      "--hostname"}
GH_URL_RE = re.compile(r"^https?://github\.com/([^/]+)/", re.I)
# Read commands that read stdin when given no path (a no-path run of them is not a read of the cwd), and
# those that default to the cwd.
STDIN_READERS = {"cat", "head", "tail", "wc", "sed", "gsed", "awk", "gawk", "less", "more", "bat",
                 "grep", "egrep", "fgrep", "ggrep"}
GREP_CMDS = {"grep", "egrep", "fgrep", "ggrep"}
NUMERIC_HOST_RE = re.compile(r"^(0x[0-9a-f]+|[0-9]+)(\.(0x[0-9a-f]+|[0-9]+)){0,3}$")
HEREDOC_WORD_END = " \t\r\n;&|<>()"
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
        return f"mcp__{server.lower()}"
    return "other"


def client_label(model: str) -> str:
    """A model family from a fixed list, for Claude its tier, then up to three small version numbers: a
    value built only from fixed words and digits, so no free text from the payload reaches the record."""
    m = re.sub(r"\[.*", "", model.lower()[:60])
    fam = next((f for f in MODEL_FAMILIES if m.startswith(f)), "")
    if not fam and re.match(r"o[0-9]", m):
        fam = "o"
    if not fam:
        return "claude-code"
    label = fam
    if fam == "claude":
        tier = next((t for t in CLAUDE_TIERS if t in m), "")
        label += f"-{tier}" if tier else ""
    nums = [s for s in re.split(r"[-._]", m[len(fam):]) if re.fullmatch(r"[0-9]{1,2}", s)][:3]
    return "-".join([label, *nums])


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


VAR_REF_RE = re.compile(r"\$(?:\{([A-Za-z_]\w*)\}|([A-Za-z_]\w*))")


def _subst_vars(w: str, env: dict) -> list[str] | None:
    """The values a shell word takes once its `$NAME` and `${NAME}` references are replaced from env (the
    literal assignments and loop lists seen earlier in the same command, plus $HOME); one value per
    combination of loop values, at most MAX_PATHS. None when a reference has no literal value, any other
    `$` or backtick form is left (`$(...)`, `$1`, `${X:-y}`), or a value is longer than MAX_VALUE_CHARS
    (checked while the product is built, so it never allocates past those bounds)."""
    if len(w) > MAX_VALUE_CHARS:
        return None
    out = [w]
    for name in dict.fromkeys(a or b for a, b in VAR_REF_RE.findall(w)):
        vals = env.get(name, [str(Path.home())] if name == "HOME" else None)
        if not vals:
            return None
        pat = re.compile(r"\$(?:\{%s\}|%s(?![A-Za-z0-9_]))" % (name, name))
        nxt: list[str] = []
        for o in out:
            for v in vals:
                if len(nxt) >= MAX_PATHS:
                    break
                s = pat.sub(lambda _m, v=v: v, o)
                if len(s) > MAX_VALUE_CHARS:
                    return None
                nxt.append(s)
        out = nxt
    return None if any("$" in o or "`" in o for o in out) else out


def _resolve_word(w: str, cwd: str, env: dict) -> list[str] | None:
    """A shell word as absolute paths (several when it uses a loop variable); [] for an empty value or
    /dev/*, which name nothing read; None when it needs a variable we cannot know. An unresolved word is
    NOT the cwd: a read of it is bucketed as path_class `unresolved`."""
    vals = _subst_vars(w, env)
    if vals is None:
        return None
    paths = [_expand(v, cwd) for v in vals if v]
    return [p for p in paths if p != "/dev" and not p.startswith("/dev/")]


def _assign(words: list[str], env: dict) -> None:
    """Apply `NAME=value` words to env: a literal value is kept; anything else makes the name unknown."""
    for w in words:
        name, _, val = w.partition("=")
        vals = _subst_vars(val, env)
        env[name] = vals[:1] if vals else None


def _for_loop(words: list[str], env: dict) -> None:
    """`for NAME in w1 w2 ...`: the literal word list becomes NAME's values; a list with a substitution,
    an unresolved variable or no words (`$(ls)` leaves none) makes NAME unknown."""
    items: list[str] = []
    for w in words[3:]:
        vals = _subst_vars(w, env)
        if vals is None:
            items = []
            break
        items.extend(vals)
    env[words[1]] = items[:MAX_PATHS] or None


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


def _heredoc_word(cmd: str, i: int) -> tuple[str, int] | None:
    """The delimiter of a heredoc whose `<<` (and `-`) ends just before i, and the index after it."""
    n = len(cmd)
    while i < n and cmd[i] in " \t":
        i += 1
    start, word = i, []
    while i < n and cmd[i] not in HEREDOC_WORD_END:
        c = cmd[i]
        if c in "'\"":
            j = cmd.find(c, i + 1)
            if j < 0:
                return None
            word.append(cmd[i + 1:j])
            i = j + 1
        elif c == "\\" and i + 1 < n:
            word.append(cmd[i + 1])
            i += 2
        else:
            word.append(c)
            i += 1
    return ("".join(word), i) if i > start else None


def _skip_heredoc_body(cmd: str, i: int, word: str, dash: bool) -> int:
    """Index after the terminator line of a heredoc body that starts at i (end of text if none)."""
    n = len(cmd)
    while i < n:
        j = cmd.find("\n", i)
        line = cmd[i:n if j < 0 else j].rstrip("\r")
        i = n if j < 0 else j + 1
        if (line.lstrip("\t") if dash else line) == word:
            break
    return i


def _prepare(cmd: str) -> str:
    """The command text with what must not be tokenised removed: heredoc bodies (<<WORD, <<-WORD with its
    tab-stripped terminator, quoted forms; an unterminated body runs to the end, as in bash), comments
    (`#` at the start of a word), and backslash-newline continuations; a backtick substitution becomes
    `$( ... )` and each heredoc operator becomes `<< _ `. A digit word touching `<` or `>` (the fd of
    `2>f`, `0<f`) becomes the marker word NUL+digits before the operator, so `head -n 5 < f` keeps its
    `< f`. A `$( ... )` or backtick substitution inside double quotes is NOT scanned (`echo "$(find
    /nix/store)"` is a miss): its text, heredoc body included, stays one quoted word. Quote state follows
    bash for ' " and backslash."""
    if "\x00" in cmd:
        cmd = cmd.replace("\x00", " ")
    out: list[str] = []
    pending: list[tuple[str, bool]] = []
    n, i = len(cmd), 0
    quote, tick, word_start, digits = "", False, True, 0
    while i < n:
        c = cmd[i]
        fd, digits = digits, 0
        if quote == "'":
            out.append(c)
            i += 1
            quote = "" if c == "'" else quote
            continue
        if c == "\\":
            if cmd[i + 1:i + 2] != "\n":
                out.append(cmd[i:i + 2])
                word_start = False
            i += 2
            continue
        if quote == '"':
            out.append(c)
            i += 1
            quote = "" if c == '"' else quote
            continue
        if fd and c in "<>":
            num = "".join(out[-fd:])
            del out[-fd:]
            out.append(f" \x00{num} ")
        if c in "'\"":
            quote = c
        elif c == "#" and word_start:
            j = cmd.find("\n", i)
            i = n if j < 0 else j
            continue
        elif c == "`":
            out.append(")" if tick else "$(")
            tick, word_start = not tick, True
            i += 1
            continue
        elif c == "\n":
            out.append(c)
            i += 1
            word_start = True
            for word, dash in pending:
                i = _skip_heredoc_body(cmd, i, word, dash)
            pending.clear()
            continue
        elif c == "<" and cmd.startswith("<<", i) and not cmd.startswith("<<<", i) and cmd[i - 1:i] != "<":
            dash = cmd.startswith("-", i + 2)
            found = _heredoc_word(cmd, i + 2 + dash)
            if found:
                pending.append((found[0], dash))
                out.append("<< _ ")
                i, word_start = found[1], True
                continue
        out.append(c)
        i += 1
        digits = fd + 1 if c in "0123456789" and (fd or word_start) else 0
        word_start = c in " \t;&|("
    return "".join(out)


def _lex(cmd: str) -> list[str]:
    """shlex tokens of prepared text; ValueError on an unbalanced quote."""
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=SHELL_PUNCT)
    lex.whitespace = " \t\r"                           # a newline is a command separator
    lex.whitespace_split = True
    lex.commenters = ""
    return list(itertools.islice(lex, MAX_TOKENS))


def _shell_tokens(cmd: str) -> list[str]:
    cmd = _prepare(cmd[:MAX_CMD_CHARS])
    try:
        return _lex(cmd)
    except ValueError:                                  # unbalanced quote: a coarse split is enough
        toks = re.split(r"(&&|\|\||\|&|[;|&\n()<>])|\s+", cmd)
        return [t.strip("'\"") for t in toks if t and t.strip("'\"")][:MAX_TOKENS]


def _is_punct(tok: str) -> bool:
    return bool(tok) and all(c in SHELL_PUNCT for c in tok)


class Cmd(NamedTuple):
    """One command of a pipeline's head: its words, its `< file` input redirects, and, for the marker
    entries that stand for a parenthesis, scope "(" or ")" with no words."""
    words: list
    inputs: list
    scope: str = ""


def _commands(tokens: list[str]) -> list[Cmd]:
    """The first command of every pipeline: split on && || ; & newline and parentheses (each parenthesis
    also yields a scope marker), drop everything after the first | (a pipe filter is not a read), drop
    redirect operators and their targets, but keep the target of a `< file` as the command's input."""
    cmds: list[Cmd] = []
    cur: list[str] = []
    ins: list[str] = []
    piped, fd = False, ""
    i, n = 0, len(tokens)
    while i < n:
        t = tokens[i]
        i += 1
        if not _is_punct(t):
            if t.startswith("\x00"):  # the fd digits touching the next < or >
                fd = t[1:]
            elif not piped and t != "$":
                cur.append(t)
            continue
        if ("<" in t or ">" in t) and "(" not in t:
            target = None
            if i < n and not _is_punct(tokens[i]):
                target = tokens[i]
                i += 1
            fd_ok = fd in ("", "0")                     # 2>file and 3<file are not stdin
            fd = ""
            if t.strip("\n") == "<" and target is not None and fd_ok and not piped:
                ins.append(target)
            continue
        if t.replace("\n", "") in ("|", "|&"):
            piped = True
            continue
        if cur:
            cmds.append(Cmd(cur, ins))
        cur, ins, piped = [], [], False
        cmds.extend(Cmd([], [], ch) for ch in t if ch in "()")
    if cur:
        cmds.append(Cmd(cur, ins))
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


def _gh_positionals(args: list[str], value_opts: set) -> list[str]:
    pos: list[str] = []
    i, n = 0, len(args)
    while i < n:
        a = args[i]
        i += 1
        if a == "--":
            pos.extend(args[i:])
            break
        if a.startswith("-") and a != "-":
            i += 1 if "=" not in a and a in value_opts else 0
        else:
            pos.append(a)
    return pos


def _gh_other_owner(owner: str) -> bool:
    """A literal GitHub login that is not ours; a variable, placeholder or unknown form is not."""
    return bool(GH_OWNER_RE.match(owner)) and owner.lower() not in OWN_GITHUB_OWNERS


def _gh_is_prior_art(args: list[str]) -> bool:
    """`gh search`; `gh api repos/<other owner>/<repo>/<code or docs path>` (not PR, issue or CI polling);
    `gh repo view|clone <other owner>/<repo>`. An owner that is a variable or placeholder is unknown."""
    pos = _gh_positionals(args, GH_REPO_VALUE_OPTS)
    if not pos:
        return False
    if pos[0] == "search":
        return True
    if pos[0] == "api":
        for a in _gh_positionals(args[args.index("api") + 1:], GH_API_VALUE_OPTS):
            if m := GH_REPO_RE.match(a):
                return _gh_other_owner(m.group(1)) and bool(GH_CODE_TAIL_RE.match(m.group(3)))
        return False
    if pos[0] == "repo" and len(pos) >= 3 and pos[1] in ("view", "clone"):
        m = GH_URL_RE.match(pos[2])
        owner = m.group(1) if m else pos[2].partition("/")[0] if "/" in pos[2] else ""
        return _gh_other_owner(owner)
    return False


def _grep_recursive(args: list[str]) -> bool:
    return any(a in ("--recursive", "--dereference-recursive", "--directories=recurse")
               or (a.startswith("-") and not a.startswith("--") and ("r" in a[1:] or "R" in a[1:]))
               for a in args)


def _read_paths(name: str, args: list[str], inputs: list[str], eff: str, env: dict) -> tuple[list[str], bool]:
    """(absolute paths a read command reads, whether a path word stayed unresolved). `ls rg fd find tree
    graft` and `grep -r` with no path read the cwd; a stdin reader (`cat head tail wc sed awk less more
    bat`, grep without -r) reads its path words and its `< file` input, and with neither it reads stdin,
    which is not a read of anything. A path word that needs an unknown variable (`cat "$OUT"`) is NOT
    the cwd: it adds nothing to the paths and sets the flag."""
    pos = _positionals(name, args)[:MAX_PATHS]
    if name in STDIN_READERS and not (name in GREP_CMDS and _grep_recursive(args)):
        pos = [a for a in pos if a != "-"] + inputs[:MAX_PATHS]
        if not pos:
            return [], False
    if not pos:
        return [os.path.normpath(eff)], False
    paths: list[str] = []
    unresolved = False
    for a in pos:
        got = _resolve_word(a, eff, env)
        if got is None:
            unresolved = True
        else:
            paths.extend(got)
    return paths, unresolved


def _shell_facts(cmd: str, cwd: str, depth: int = 0) -> dict:
    """{web: bool, url: str, reads: [[abs path, ...], ...], unresolved: bool} for one shell command string."""
    facts: dict = {"web": False, "url": "", "reads": [], "unresolved": False}
    eff = cwd or "/"
    env: dict = {}                                      # NAME -> literal values, None when unknown
    scopes: list[tuple[str, dict]] = []
    for cm in _commands(_shell_tokens(cmd)):
        if cm.scope:                                    # a `cd` or assignment inside ( ... ) does not leak
            if cm.scope == "(":
                scopes.append((eff, dict(env)))
            elif scopes:
                eff, env = scopes.pop()
            continue
        lead = list(itertools.dropwhile(lambda w: w in SHELL_KEYWORDS, cm.words))   # `do for g in ...`
        if lead and all(ENV_ASSIGN_RE.match(w) for w in lead):
            _assign(lead, env)
            continue
        if len(lead) >= 3 and lead[0] == "for" and lead[2] == "in":
            _for_loop(lead, env)
            continue
        name, args = _unwrap(cm.words)
        if not name:
            continue
        if name in ("cd", "pushd"):
            tgt = next((a for a in args if not a.startswith("-")), "")
            if tgt != "-":
                got = _resolve_word(tgt or "~", eff, env)
                eff = got[0] if got else eff
        elif name in ASSIGN_BUILTINS:
            _assign([a for a in args if ENV_ASSIGN_RE.match(a)], env)
        elif name in ("read", "unset"):
            env.update({a: None for a in args if not a.startswith("-")})
        elif name in SHELLS and depth < 2:
            flags = [a for a in args[:3] if a.startswith("-") and not a.startswith("--") and "c" in a]
            if flags and len(args) > args.index(flags[0]) + 1:
                sub = _shell_facts(args[args.index(flags[0]) + 1], eff, depth + 1)
                facts["web"] = facts["web"] or sub["web"]
                facts["url"] = facts["url"] or sub["url"]
                facts["reads"].extend(sub["reads"])
                facts["unresolved"] = facts["unresolved"] or sub["unresolved"]
        elif name in FETCH_CMDS:
            url = next((a for a in args if URL_RE.match(a)), "")
            if url and host_info(url)[0] == "public":
                facts["web"], facts["url"] = True, facts["url"] or url
        elif name == "gh":
            facts["web"] = facts["web"] or _gh_is_prior_art(args)
        elif name in READ_CMDS and not _in_place_edit(name, args):
            paths, unresolved = _read_paths(name, args, cm.inputs, eff, env)
            if paths:
                facts["reads"].append(paths)
            facts["unresolved"] = facts["unresolved"] or unresolved
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
    ip = None
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if NUMERIC_HOST_RE.match(host):                 # 127.1, 0x7f.1, 2130706433: the forms curl accepts
            try:
                ip = ipaddress.ip_address(socket.inet_aton(host))
            except (OSError, ValueError):
                return "invalid", ""
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
            if facts["unresolved"]:                    # a read of a path we cannot know: not the cwd
                extras["path_class"] = "unresolved"
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
    deadline = time.monotonic() + LOCK_WAIT_TOTAL_S      # wall clock, not tries: sleeps stretch under load
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            if time.monotonic() >= deadline:
                break
            time.sleep(LOCK_POLL_S)
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
            if name.startswith(keep_prefix) or not (PRUNE_NAME_RE.match(name) or PRUNE_TMP_RE.match(name)):
                continue
            try:
                st = e.stat(follow_symlinks=False)
                if stat.S_ISREG(st.st_mode) and st.st_mtime < cutoff:
                    os.unlink(e.path)
                    deleted += 1
            except OSError:
                continue


# ---- records ----------------------------------------------------------------------------------

def _count(v) -> int:
    """A state counter read back from disk: a non-negative int, else 0 (a corrupt file must not drop events)."""
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 1 << 31 else 0


def build_record(data: dict, st: dict, now: float, agent: str = "", dropped: int = 0) -> dict:
    event = str(data.get("hook_event_name") or "PostToolUse")
    event = event if event in KNOWN_EVENTS else "other"
    tool = str(data.get("tool_name") or "")
    tin = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    resp = data.get("tool_response") if "tool_response" in data else data.get("error")
    cwd = data.get("cwd") if isinstance(data.get("cwd"), str) else ""
    sid = str(data.get("session_id") or "")

    last_ts = st.get("last_ts")
    elapsed = int((now - last_ts) * 1000) if isinstance(last_ts, (int, float)) and now >= last_ts else None
    prompt = event == "UserPromptSubmit" and not agent
    new_task = prompt or (isinstance(last_ts, (int, float)) and now - last_ts > _idle_s())
    if prompt:
        st["prompt_seq"] = _count(st.get("prompt_seq")) + 1
    if new_task:
        st.update(task_seq=int(st.get("task_seq", 0)) + 1, web_or_memory=False, run=0,
                  recent=[], last_failed_call="")
    st.setdefault("salt", os.urandom(8).hex())

    rec: dict = {
        "ts": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="milliseconds"),
        "schema": SCHEMA,
        "classifier_version": CLASSIFIER_VERSION,
        "session": _sha(sid)[:12],
        "event": event,
        "client": client_label(str(data.get("model") or "")),
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
    with contextlib.suppress(OSError):                  # a live session's lock must not look 30 days old
        os.utime(lock_fd, (now, now))
    try:
        st_path = d / f"{key}.state.json"
        st = _load_state(st_path)
        if agent:                                       # a subagent joins the main agent's current task
            parent = _load_state(d / f"{sid}.state.json")
            parent_seq, prompts = _count(parent.get("task_seq")), _count(parent.get("prompt_seq"))
            if not st:
                st.update(task_seq=parent_seq, prompt_seq_seen=prompts)
            elif _count(st.get("prompt_seq_seen")) != prompts:
                # The user sent a new prompt while this subagent was idle (a resumed subagent): its run,
                # recent calls and web flag belong to the old task. Only the parent's UserPromptSubmit
                # counts, never the parent's idle rule (the parent is quiet while a subagent works), and
                # the test is "differs", so no counter of the subagent's own can put it ahead. last_ts
                # goes too, so the subagent's idle rule cannot count a second change on top.
                st.update(task_seq=parent_seq, prompt_seq_seen=prompts, web_or_memory=False, run=0,
                          recent=[], last_failed_call="")
                st.pop("last_ts", None)
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
