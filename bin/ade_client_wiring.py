"""ade_client_wiring: observe-only check that every current agent TUI is wired.

Two checks per TUI, both report-only (standing order 11: no client config is
ever edited, no fix command is ever run; the fix is printed):

* MCP: each shared server in ``config/mcp-clients.toml`` (the machine-readable
  mirror of docs/mcp-servers.md) x each client it lists. The client's config
  FILE is read for key names and the URL only (``~/.claude.json`` user-scope
  ``mcpServers``; ``~/.codex/config.toml`` ``[mcp_servers.<id>]``;
  ``~/.cursor/mcp.json`` ``mcpServers``; ``~/.hermes/config.yaml``
  ``mcp_servers``). A TUI with no file-readable MCP config is ``unknown`` with
  the reason, never a failure.
* Skills: ``bin/skill-everywhere --check --all`` is run (it is read-only) and
  its per-TUI states are mapped to ok / missing / dangling / elsewhere.

The TUI roster is not listed here: it is the ``targets`` table inside
``bin/skill-everywhere`` (docs/skill-everywhere.md), the one place that knows
which TUIs are current. The MCP roster's ``clients`` must be a subset of it.

Statuses: ok | warn | unknown | error. ``error`` = an unreadable roster or client
config, or exactly one of the roster / ``bin/skill-everywhere`` present.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:  # PyYAML is only needed for Hermes' config.yaml
    import yaml
except ImportError:  # pragma: no cover - exercised by the unknown-reason test
    yaml = None  # type: ignore[assignment]

SKILL_SCRIPT = ("bin", "skill-everywhere")
SKILL_CHECK_TIMEOUT_S = 90
SKILL_ENV_OVERRIDES = ("SKILL_EVERYWHERE_ONLY", "SKILL_EVERYWHERE_NO_COPY", "SKILL_EVERYWHERE_ADE",
                       "SKILL_EVERYWHERE_PRIVATE", "SKILL_EVERYWHERE_SITE", "SKILL_EVERYWHERE_GROKBOT_NOTE")
# Also dropped when the caller pins HOME (fixtures): each one relocates a root the check reads.
SKILL_ENV_HOME_RELATIVE = ("OPS_ROOT", "CODEX_HOME", "HERMES_HOME")
MAX_STDERR_ROWS = 200  # distinct stderr lines kept; the rest are counted, not dropped silently
MAX_DETAIL_LINES = 12

SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
SAFE_URL = re.compile(r"https?://[A-Za-z0-9.:/_-]+\Z")
CLAUDE_HTTP_TYPES = ("http", "streamable-http")  # alias accepted by Claude Code

# (kind, id, status, detail)
Row = tuple[str, str, str, str]
Runner = Callable[[list[str], dict[str, str]], "subprocess.CompletedProcess[str]"]

# TUIs whose MCP config is not a file this machine can read, and why.
NO_MCP_FILE = {
    "pi": "Pi is not a separate MCP client here (docs/mcp-servers.md)",
    "grokbot": "Grok Bot runs on its own Linux box; its MCP config is not on this machine",
}


# ---------------------------------------------------------------- TUI roster

def tui_roster(root: Path) -> list[str]:
    """TUI ids from the ``targets`` table of bin/skill-everywhere, in its order."""
    text = root.joinpath(*SKILL_SCRIPT).read_text(encoding="utf-8")
    m = re.search(r"^targets='\n(.*?)^'", text, re.S | re.M)
    if not m:
        raise ValueError("skill-everywhere has no targets table")
    ids = [ln.split("|", 1)[0].strip() for ln in m.group(1).splitlines() if "|" in ln]
    if not ids or any(not SAFE_ID.match(i) for i in ids):
        raise ValueError("skill-everywhere targets table is unreadable")
    return ids


# ---------------------------------------------------------------- MCP roster

def default_roster_path(root: Path) -> Path:
    return root / "config" / "mcp-clients.toml"


def load_roster(path: Path, tuis: list[str] | None = None) -> list[dict[str, Any]]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    rows = data.get("server")
    if not isinstance(rows, list) or not rows:
        raise ValueError("no [[server]] rows")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("[[server]] row is not a table")
        sid, url, clients = row.get("id"), row.get("url"), row.get("clients")
        if not isinstance(sid, str) or not SAFE_ID.match(sid) or sid in seen:
            raise ValueError(f"bad or duplicate server id {sid!r}")
        seen.add(sid)
        if not isinstance(url, str) or not SAFE_URL.match(url):
            raise ValueError(f"server {sid}: url must be plain http(s) (letters, digits, . : / _ -)")
        if not isinstance(clients, list) or not clients or any(
                not isinstance(c, str) or not SAFE_ID.match(c) for c in clients):
            raise ValueError(f"server {sid}: clients must be a non-empty list of TUI ids")
        if tuis is not None and (bad := [c for c in clients if c not in tuis]):
            raise ValueError(f"server {sid}: client(s) {bad} not in the skill-everywhere roster {tuis}")
    return rows


def safe_url(url: Any, want: str) -> str:
    """Scheme and host:port only; the path is shown only when it equals the
    expected one (some endpoints carry an API key in the path). Never userinfo,
    query or fragment; control characters are dropped."""
    if not isinstance(url, str):
        return "<non-string>"
    if not re.match(r"https?://", url):
        return "<non-http url>"
    try:
        p = urlsplit(url)
        host = p.hostname or ""
        if p.port:
            host += f":{p.port}"
        path = p.path if p.path.rstrip("/") == urlsplit(want).path.rstrip("/") else "/<other path>"
    except ValueError:
        return "<unparseable>"
    shown = f"{p.scheme}://{host}{path}"
    return "".join(c if c.isprintable() else "?" for c in shown)[:120]


def fix_add(tui: str, sid: str, url: str) -> str:
    q = shlex.quote
    if tui == "claude":
        return f"claude mcp add --scope user --transport http {q(sid)} {q(url)}"
    if tui == "codex":
        return f"codex mcp add {q(sid)} --url {q(url)}"
    if tui == "cursor-agent":
        return f'add "{sid}": {{"url": "{url}"}} under mcpServers in ~/.cursor/mcp.json'
    return f"add {sid}: url: {url} under mcp_servers in ~/.hermes/config.yaml"


def fix_swap(tui: str, sid: str, url: str) -> str:
    q = shlex.quote
    if tui == "claude":
        return f"claude mcp remove --scope user {q(sid)} && {fix_add(tui, sid, url)}"
    if tui == "codex":
        return f"codex mcp remove {q(sid)} && {fix_add(tui, sid, url)}"
    return f"correct the {sid} entry: " + fix_add(tui, sid, url)


# Loaders return (path, servers-dict-or-None-when-file-absent).
def _load_claude(home: Path) -> tuple[Path, dict[str, Any] | None]:
    path = home / ".claude.json"
    if not path.is_file():
        return path, None
    data = json.loads(path.read_text(encoding="utf-8"))
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    return path, servers if isinstance(servers, dict) else {}


def _load_codex(home: Path) -> tuple[Path, dict[str, Any] | None]:
    path = home / ".codex" / "config.toml"
    if not path.is_file():
        return path, None
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    servers = data.get("mcp_servers")
    return path, servers if isinstance(servers, dict) else {}


def _load_cursor(home: Path) -> tuple[Path, dict[str, Any] | None]:
    path = home / ".cursor" / "mcp.json"
    if not path.is_file():
        return path, None
    data = json.loads(path.read_text(encoding="utf-8"))
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    return path, servers if isinstance(servers, dict) else {}


def _load_hermes(home: Path) -> tuple[Path, dict[str, Any] | None]:
    path = home / ".hermes" / "config.yaml"
    if not path.is_file():
        return path, None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    servers = data.get("mcp_servers") if isinstance(data, dict) else None
    return path, servers if isinstance(servers, dict) else {}


_LOADERS: dict[str, Callable[[Path], tuple[Path, dict[str, Any] | None]]] = {
    "claude": _load_claude,
    "codex": _load_codex,
    "cursor-agent": _load_cursor,
    "hermes": _load_hermes,
}


def _judge(tui: str, sid: str, want: str, entry: Any) -> tuple[str, str]:
    """(state, detail): state is ok | missing | wrong-url | wrong-type | disabled."""
    add = fix_add(tui, sid, want)
    swap = fix_swap(tui, sid, want)
    if entry is None:
        return "missing", f"not registered; run: {add}"
    if not isinstance(entry, dict):
        return "wrong-type", f"entry is not a table/object; run: {swap}"
    if tui == "claude" and entry.get("type") not in CLAUDE_HTTP_TYPES:
        # An entry without type is read as stdio, so its url is ignored.
        t = entry.get("type")
        shown = repr(t) if isinstance(t, str) and len(t) <= 32 else "<missing or odd>"
        return "wrong-type", f"entry type is {shown}, want 'http'; run: {swap}"
    if entry.get("enabled") is False:
        return "disabled", f"present but enabled = false; set enabled = true for {sid}"
    got = entry.get("url")
    if not isinstance(got, str) or got.rstrip("/") != want.rstrip("/"):
        return "wrong-url", f"url is {safe_url(got, want)}, want {want}; run: {swap}"
    return "ok", f"registered at {want}"


def observe_mcp(roster: list[dict[str, Any]], tuis: list[str], *, home: Path) -> dict[str, list[Row]]:
    """Per TUI, one row per marked server (``mcp`` kind; status ok|warn|unknown|error).
    Reads at most four config files; writes nothing."""
    out: dict[str, list[Row]] = {t: [] for t in tuis}
    for tui in tuis:
        wanted = [r for r in roster if tui in r["clients"]]
        if not wanted:
            continue
        loader = _LOADERS.get(tui)
        reason = NO_MCP_FILE.get(tui, "no file-readable MCP config known for this TUI")
        if tui == "hermes" and yaml is None:
            loader, reason = None, "PyYAML is not importable here, so ~/.hermes/config.yaml is not read"
        if loader is None:
            out[tui].append(("mcp", f"{tui}/*", "unknown", reason))
            continue
        try:
            path, servers = loader(home)
        except (OSError, ValueError, UnicodeDecodeError, RecursionError) as e:
            out[tui].append(("mcp", f"{tui}/*", "error", f"{tui} MCP config unreadable: {type(e).__name__}"))
            continue
        except Exception as e:  # noqa: BLE001 - yaml.YAMLError is not a ValueError
            if yaml is not None and isinstance(e, yaml.YAMLError):
                out[tui].append(("mcp", f"{tui}/*", "error", f"{tui} MCP config unreadable: YAMLError"))
                continue
            raise
        for r in wanted:
            sid, want = r["id"], r["url"]
            if servers is None:
                out[tui].append(("mcp", f"{tui}/{sid}", "warn",
                                 f"missing: {path} absent (TUI not set up?); {fix_add(tui, sid, want)}"))
                continue
            state, detail = _judge(tui, sid, want, servers.get(sid))
            out[tui].append(("mcp", f"{tui}/{sid}", "ok" if state == "ok" else "warn",
                             detail if state == "ok" else f"{state}: {detail}"))
    return out


# -------------------------------------------------------------------- skills

def _default_runner(argv: list[str], env: dict[str, str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(  # noqa: S603 - argv list; the script is read-only under --check
        argv, capture_output=True, text=True, check=False, env=env,
        timeout=SKILL_CHECK_TIMEOUT_S, errors="replace",
    )


def classify_skill_state(state: str) -> str:
    """ok | unknown | missing | dangling | elsewhere | other. Copy-target rows carry a
    trailing ``(<dest>)`` (``copied (/x)``), stripped first."""
    state = re.sub(r" \(.*\)$", "", state)
    if state == "linked" or state.startswith("via ") or state == "copied":
        return "ok"
    if state.startswith("not installed"):
        return "unknown"
    if state == "missing":
        return "missing"
    if state.startswith("dangling"):
        return "dangling"
    if state.startswith(("other link", "chained", "real", "stale copy")):
        return "elsewhere"
    return "other"


def parse_skill_check(text: str) -> tuple[dict[str, dict[str, str]], bool]:
    """(tui -> skill -> state, complete). Complete = the last non-empty line is the
    ``== end`` sentinel and every skill header has at least one row."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    complete = bool(lines) and lines[-1] == "== end"
    table: dict[str, dict[str, str]] = {}
    skill = None
    rowed: set[str] = set()
    headers: list[str] = []
    for line in lines[:-1] if complete else lines:
        if line.startswith("== "):
            skill = line[3:].strip()
            headers.append(skill)
        elif line.startswith("  ") and skill is not None:
            parts = line.split(None, 1)
            if len(parts) == 2:
                table.setdefault(parts[0], {})[skill] = parts[1].strip()
                rowed.add(skill)
    if any(h not in rowed for h in headers):
        complete = False
    return table, complete


def observe_skills(
    root: Path,
    tuis: list[str],
    *,
    home: Path | None = None,
    runner: Runner | None = None,
) -> tuple[dict[str, list[Row]], list[Row]]:
    """Per-TUI ``skill`` rows (ok summary or per-skill warns) plus global rows.
    Runs ``skill-everywhere --check --all`` and nothing else."""
    script = root.joinpath(*SKILL_SCRIPT)
    fix = f"{script} --all"
    # An inherited ONLY/NO_COPY/root override would narrow or redirect the check and still print a
    # complete-looking report (bin/ade-update helper_env, round 15): drop them all.
    drop = SKILL_ENV_OVERRIDES + (SKILL_ENV_HOME_RELATIVE if home is not None else ())
    env = {k: v for k, v in os.environ.items() if k not in drop}
    if home is not None:
        env["HOME"] = str(home)
    run = runner or _default_runner
    glob: list[Row] = []
    out: dict[str, list[Row]] = {t: [] for t in tuis}
    try:
        cp = run([str(script), "--check", "--all"], env)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        glob.append(("skill", "skill-everywhere", "warn", f"check could not run ({type(e).__name__})"))
        return out, glob
    table, complete = parse_skill_check(cp.stdout or "")
    if not complete:
        glob.append(("skill", "skill-everywhere", "warn",
                     f"check ended early (rc {cp.returncode}, no '== end'); no skill result trusted"))
        return out, glob
    attached: dict[str, list[Row]] = {t: [] for t in tuis}
    counts: dict[str, int] = {}
    for line in (cp.stderr or "").splitlines():
        if line.strip():
            text = "".join(c if c.isprintable() else "?" for c in line)[:200]
            counts[text] = counts.get(text, 0) + 1
    for n_seen, (text, times) in enumerate(counts.items()):
        if n_seen >= MAX_STDERR_ROWS:
            glob.append(("skill", "skill-everywhere", "warn", f"(+{len(counts) - MAX_STDERR_ROWS} more distinct stderr lines)"))
            break
        shown = text + (f" (x{times})" if times > 1 else "")
        # The script's own TUI-specific warnings start `warning: <tui-id> ` (no colon: `warning: <skill>:`
        # is a per-skill line, and a skill may share a TUI's name). Anything else is global.
        m = re.match(r"warning: ([A-Za-z0-9][A-Za-z0-9._-]*) (?!:)", text)
        owner = m.group(1) if m and m.group(1) in attached else None
        if owner:
            attached[owner].append(("skill", f"{owner}/warning", "warn", shown))
        else:
            glob.append(("skill", "skill-everywhere", "warn", shown))
    if cp.returncode not in (0, 1):
        glob.append(("skill", "skill-everywhere", "warn", f"check exited rc {cp.returncode}"))
    # cursor-agent-style TUIs read ~/.claude/skills: judge claude first, independent of table order.
    claude_states = table.get("claude") or {}
    claude_gaps = any(classify_skill_state(st) not in ("ok", "unknown") for st in claude_states.values())
    claude_unchecked = bool(claude_states) and all(
        classify_skill_state(st) == "unknown" for st in claude_states.values())
    for tui in tuis:
        out[tui].extend(attached[tui])
        states = table.get(tui)
        if not states:
            out[tui].append(("skill", f"{tui}/*", "unknown", "skill-everywhere reported nothing for this TUI"))
            continue
        if all(st.startswith("via ") and "claude" in st for st in states.values()):
            if claude_gaps:
                out[tui].append(("skill", f"{tui}/via-claude", "warn",
                                 "reads ~/.claude/skills, which has gaps (see claude/* rows)"))
                continue
            if claude_unchecked or not claude_states:
                out[tui].append(("skill", f"{tui}/*", "unknown",
                                 "reads ~/.claude/skills, which was not checked (claude not installed)"))
                continue
        groups: dict[str, list[str]] = {}
        for skill, state in sorted(states.items()):
            groups.setdefault(classify_skill_state(state), []).append(skill)
        n = len(states)
        if len(groups.get("unknown", [])) == n:
            reason = next(iter(states.values()))
            out[tui].append(("skill", f"{tui}/*", "unknown", reason[:160]))
            continue
        bad = {k: v for k, v in groups.items() if k not in ("ok", "unknown")}
        if not bad:
            out[tui].append(("skill", f"{tui}/*", "ok", f"{len(groups.get('ok', []))}/{n} skills linked"))
            continue
        for kind in ("missing", "dangling", "elsewhere", "other"):
            names = bad.get(kind)
            if not names:
                continue
            shown = ", ".join(names[:MAX_DETAIL_LINES]) + (f" (+{len(names) - MAX_DETAIL_LINES} more)" if len(names) > MAX_DETAIL_LINES else "")
            label = {"elsewhere": "points elsewhere or not our link"}.get(kind, kind)
            out[tui].append(("skill", f"{tui}/{kind}", "warn", f"{len(names)} {label}: {shown}; run: {fix}"))
    return out, glob


# ------------------------------------------------------------------- combine

def observe(
    root: Path,
    *,
    home: Path | None = None,
    roster_path: Path | None = None,
    runner: Runner | None = None,
) -> list[Row]:
    """All rows: per TUI one ``tui`` summary then its ``mcp``/``skill`` detail rows
    (non-ok only, plus ok MCP rows), then global rows. ``[]`` when both the roster and
    skill-everywhere are absent (fixture catalogs); exactly one of them is an error row."""
    path = roster_path if roster_path is not None else default_roster_path(root)
    has_script = root.joinpath(*SKILL_SCRIPT).is_file()
    if not has_script and not path.is_file():
        return []
    if has_script and not path.is_file():
        return [("tui", "roster", "error", f"MCP roster missing ({path}); skill-everywhere is present")]
    if not has_script:
        return [("tui", "roster", "error", f"{root.joinpath(*SKILL_SCRIPT)} missing; the TUI roster cannot be read")]
    home_dir = home if home is not None else Path.home()
    try:
        tuis = tui_roster(root)
        roster = load_roster(path, tuis)
    except (OSError, ValueError, UnicodeDecodeError) as e:
        return [("tui", "roster", "error", f"TUI/MCP roster unreadable ({path}): {e}")]
    mcp = observe_mcp(roster, tuis, home=home_dir)
    skills, glob = observe_skills(root, tuis, home=home, runner=runner)
    rows: list[Row] = []
    for tui in tuis:
        det = mcp[tui] + skills[tui]
        statuses = {r[2] for r in det}
        if "error" in statuses:
            status = "error"
        elif "warn" in statuses:
            status = "warn"
        elif "unknown" in statuses:
            status = "unknown"  # partly unchecked is never reported as ok
        else:
            status = "ok"
        parts = []
        for kind, label in (("mcp", "mcp"), ("skill", "skills")):
            sub = [r for r in det if r[0] == kind]
            if not sub:
                parts.append(f"{label}: none marked" if kind == "mcp" else f"{label}: n/a")
            elif all(r[2] == "ok" for r in sub):
                parts.append(f"{label}: ok" + (f" ({len(sub)})" if kind == "mcp" else f" ({sub[0][3].split()[0]})"))
            elif all(r[2] == "unknown" for r in sub):
                parts.append(f"{label}: unknown ({sub[0][3]})")
            else:
                parts.append(f"{label}: {sum(1 for r in sub if r[2] not in ('ok', 'unknown'))} gap(s)")
        rows.append(("tui", tui, status, "; ".join(parts)))
        rows.extend(r for r in det if r[2] != "unknown" and (r[0] == "mcp" or r[2] != "ok"))
    rows.extend(glob)
    return rows
