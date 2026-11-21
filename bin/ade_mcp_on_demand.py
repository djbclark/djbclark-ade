"""`ade-worker-run --mcp NAME`: give one worker an on-demand MCP server (docs/mcp-on-demand.md 11.2 part 1, queue 89).

`paseo run` has no provider-argument passthrough (checked 2026-11-21: its options are title, provider, model, thinking,
mode, workspace/worktree, env, label), and the daemon's per-agent `mcpServers` is not reachable from the CLI. So the
launch route is one Paseo provider profile per provider and MCP set, which the operator adds to `~/.paseo/config.json`:

    "claude-mcp-chrome-devtools": {"extends": "claude", "label": "Claude + chrome-devtools",
                                   "command": ["claude", "--mcp-config", "<state dir>/chrome-devtools.json"]}
    "codex-mcp-chrome-devtools":  {"extends": "codex", "label": "Codex + chrome-devtools",
                                   "command": ["codex", "-c", "mcp_servers.chrome-devtools.enabled=true"]}

`--mcp NAME` rewrites `--provider claude[/model]` to the profile id, after checking the catalog lists it (otherwise it
refuses and prints the snippet; nothing is launched). If the server is already present in the provider's user scope
the flag adds nothing and says so (two entries under one name conflict). The generated Claude config holds the server's
command and args only, never an `env` value, mode 600, written atomically; the registry is `config/mcp-on-demand.toml`.

    bin/ade_mcp_on_demand.py snippet NAME PROVIDER   print the profile entry and write the generated config
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Callable

SUPPORTED = ("claude", "codex")
REGISTRY = Path(__file__).resolve().parent.parent / "config" / "mcp-on-demand.toml"


class McpError(Exception):
    pass


def load_registry(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """name -> {"command": str, "args": [str]}; `env` is rejected so no value can reach a generated file."""
    try:
        data = tomllib.loads((path or REGISTRY).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise McpError(f"cannot read the on-demand MCP registry {path or REGISTRY}: {e}") from e
    out: dict[str, dict[str, Any]] = {}
    for name, ent in (data.get("servers") or {}).items():
        if not isinstance(ent, dict) or not isinstance(ent.get("command"), str) or not ent["command"]:
            raise McpError(f"registry entry {name!r} needs a string `command`")
        args = ent.get("args", [])
        if not isinstance(args, list) or any(not isinstance(a, str) for a in args) or "env" in ent:
            raise McpError(f"registry entry {name!r}: `args` must be a list of strings and `env` is not allowed")
        out[str(name)] = {"command": ent["command"], "args": list(args)}
    return out


def state_dir() -> Path:
    return Path(os.environ.get("ADE_STATE_DIR") or Path.home() / ".local" / "state" / "ade") / "mcp"


def profile_id(provider: str, names: list[str]) -> str:
    return f"{provider}-mcp-{'-'.join(sorted(names))}"


def claude_config(reg: dict[str, dict[str, Any]], names: list[str]) -> dict[str, Any]:
    return {"mcpServers": {n: {"type": "stdio", "command": reg[n]["command"], "args": reg[n]["args"]} for n in names}}


def write_claude_config(reg: dict[str, dict[str, Any]], names: list[str], directory: Path | None = None) -> Path:
    d = directory or state_dir()
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = d / f"{'-'.join(sorted(names))}.json"
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".mcp-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(claude_config(reg, names), f, indent=1, sort_keys=True)
            f.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def profile_entry(provider: str, names: list[str], config_path: Path) -> dict[str, Any]:
    label = f"{provider.capitalize()} + {', '.join(sorted(names))}"
    if provider == "claude":
        cmd = ["claude", "--mcp-config", str(config_path)]
    else:
        cmd = ["codex"]
        for n in sorted(names):
            cmd += ["-c", f"mcp_servers.{n}.enabled=true"]
    return {"extends": provider, "label": label, "command": cmd}


def user_scope_has(provider: str, name: str, claude_json: Path | None = None, codex_toml: Path | None = None) -> bool:
    """Is `name` registered in the provider's user scope? Reads key names only; an unreadable file counts as absent."""
    try:
        if provider == "claude":
            data = json.loads((claude_json or Path.home() / ".claude.json").read_text())
            return name in (data.get("mcpServers") or {})
        data = tomllib.loads((codex_toml or Path.home() / ".codex" / "config.toml").read_text())
        ent = (data.get("mcp_servers") or {}).get(name)
        return isinstance(ent, dict) and ent.get("enabled", True) is not False
    except (OSError, ValueError):
        return False


def _provider_value(rest: list[str]) -> tuple[int, str]:
    idx = [i for i, a in enumerate(rest) if a == "--provider" or a.startswith("--provider=")]
    if len(idx) != 1:
        raise McpError("--mcp needs exactly one explicit --provider (claude or codex)")
    i = idx[0]
    if rest[i] == "--provider":
        if i + 1 >= len(rest):
            raise McpError("--provider needs a value")
        return i + 1, rest[i + 1]
    return i, rest[i].split("=", 1)[1]


def apply(rest: list[str], names: list[str], catalog: Callable[[], Any], reg: dict[str, dict[str, Any]] | None = None,
          user_has: Callable[[str, str], bool] = user_scope_has, directory: Path | None = None,
          note: Callable[[str], None] | None = None) -> list[str]:
    """The `paseo run` arguments with --provider swapped for the MCP profile; unchanged when nothing needs adding."""
    if not names:
        return rest
    if note is None:
        def note(msg: str) -> None:
            _ = sys.stderr.write(msg + "\n")
    reg = load_registry() if reg is None else reg
    for n in names:
        if n not in reg:
            raise McpError(f"unknown MCP name {n!r}; the registry (config/mcp-on-demand.toml) has: {', '.join(sorted(reg)) or 'none'}")
    pos, value = _provider_value(rest)
    base, sep, model = value.partition("/")
    if base not in SUPPORTED:
        raise McpError(f"--mcp supports --provider claude or codex, not {base!r} (a profile name already carries its own MCP set)")
    need = []
    for n in sorted(set(names)):
        if user_has(base, n):
            note(f"ade-worker-run: --mcp {n}: already in {base}'s user scope; nothing added (two entries under one name conflict)")
        else:
            need.append(n)
    if not need:
        return rest
    pid = profile_id(base, need)
    rows = catalog()
    row = next((r for r in rows if isinstance(r, dict) and r.get("provider") == pid), None) if isinstance(rows, list) else None
    if row is None or row.get("enabled") not in (True, "Enabled") or row.get("status") not in ("ready", "available") or row.get("error"):
        path = write_claude_config(reg, need, directory) if base == "claude" else Path("-")
        snippet = json.dumps({pid: profile_entry(base, need, path)}, indent=2)
        raise McpError(f"no ready, enabled Paseo provider profile {pid!r} (paseo run cannot pass provider arguments, so --mcp "
                       f"selects a profile). Add it under `agents.providers` in ~/.paseo/config.json, then relaunch (nothing "
                       f"was launched):\n{snippet}")
    out = list(rest)
    new = pid + (sep + model if sep else "")
    if rest[pos - 1] == "--provider":
        out[pos] = new
    else:
        out[pos] = f"--provider={new}"
    return out


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "snippet":
        _, name, provider = argv
        try:
            reg = load_registry()
            if name not in reg or provider not in SUPPORTED:
                raise McpError(f"need a registry name and a provider in {SUPPORTED}")
            path = write_claude_config(reg, [name]) if provider == "claude" else Path("-")
            print(json.dumps({profile_id(provider, [name]): profile_entry(provider, [name], path)}, indent=2))
            return 0
        except McpError as e:
            sys.stderr.write(f"ade_mcp_on_demand: {e}\n")
            return 2
    sys.stderr.write(__doc__ or "")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
