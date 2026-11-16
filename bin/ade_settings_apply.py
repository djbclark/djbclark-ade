#!/usr/bin/env python3
"""ade-settings-apply: narrow merge of agents/claude/settings.json.tmpl into the live ~/.claude/settings.json.

    ade-settings-apply [--apply] [--template PATH] [--live PATH] [--home DIR] [--json]
    ade-settings-apply --render-template [--template PATH] [--live PATH]   # print the merged result as a template

Only ADE-owned parts are applied (operator ruling 2026-11-15, queue "st-apply"):

  R1. hooks whose command runs a script under the djbclark-ade checkout (``~/src/djbclark-ade/...``) or one of
      ``~/.claude/hooks/`` / ``~/.claude/helpers/``, matched per event by (script path, first non-flag argument).
      The live form wins when both exist (a live ``|| exit 0`` wrapper is kept, no unwrapped duplicate is added);
      a template hook with no live twin is added as its own group. Other hooks (paseo, collie, ...) are never applied.
  R1b. ``permissions.deny`` is a union: template entries missing from live are appended, a live entry is never removed.
  R2. everything else: live wins and is never removed or overwritten. A key the template has and live lacks is
      added (lead ruling 2026-11-15, proposed to cover the sandbox block and model settings); a differing value
      (model, deniedMcpServers) is only listed ("template differs, not applied"), and so are non-ADE hooks.
  R3. dry-run by default (key-path diff, never values). ``--apply`` copies the live file to
      ``settings.json.bak-<UTC stamp>`` (mode kept), then writes a temp file beside and ``os.replace``s it onto the
      realpath. It refuses (exit 1, nothing written) if any live key path would disappear.

Exit 0 ok (including "nothing to do"), 1 refused, 2 usage or unreadable input. The whole live file is read, but no value is printed
except the `/sandbox` block a dry-run would add; `--render-template` refuses a secret-shaped key or value (key paths only in the message).
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HOME_TAG = "{{ .home }}"
# A command's script is found under the checkout or ~/.claude hooks/helpers (the dedupe key); it is ADE-OWNED, and only then added, when it
# also resolves (symlinks followed) into the djbclark-ade tree and exists (adversary A1: never add an entry whose script is missing).
_SCRIPT = re.compile(r"~/(?:\.claude/(?:hooks|helpers)/|src/djbclark-ade/)\S+")
# R2 adds an absent key only under these paths (adversary A1: `env`, helpers, plugins, marketplaces and the like are never auto-added).
ADD_ABSENT = ("/sandbox", "/modelSettings", "/skillOverrides")
_OPS = {"||", "&&", ";", "|", "&"}


def render(text: str, home: str) -> str:
    return text.replace(HOME_TAG, json.dumps(home)[1:-1])


def unrender(text: str, home: str) -> str:
    """Home path back to the tag, only where it is a whole path prefix (not /Users/djbclarkX)."""
    h = re.escape(json.dumps(home)[1:-1])
    return re.sub(r"(?<![\w.-])" + h + r"(?=[/\\\"\s']|$)", HOME_TAG.replace("\\", "\\\\"), text)


def default_roots(home: str) -> list:
    return [Path(__file__).resolve().parent.parent, Path(home) / "src" / "djbclark-ade"]


def is_ade_owned(script: str, home: str, roots) -> bool:
    real = Path(os.path.realpath(script.replace("~", home, 1)))
    if not real.exists():
        return False
    for r in roots:
        try:
            real.relative_to(Path(os.path.realpath(r)))
            return True
        except ValueError:
            continue
    return False


def _norm(cmd: str, home: str) -> str:
    c = cmd.replace('"', "").replace("'", "")
    for h, to in (("${HOME}", "~"), ("$HOME", "~"), (home.rstrip("/") + "/", "~/")):
        c = c.replace(h, to)
    return c


def hook_key(cmd: str, home: str):
    """(script path, graft-hooks subcommand or "") for a command that runs a checkout or ~/.claude hooks/helpers script, else None.

    The key is the script path alone (adversary A2: redirections, `[ ... ]` guards and flags must not change it); only graft-hooks.cjs
    registers several hooks per event, told apart by their subcommand."""
    c = _norm(cmd, home)
    m = _SCRIPT.search(c)
    if not m:
        return None
    script = m.group(0).rstrip(";")
    rest = c[m.end():].split()
    arg = rest[0] if script.endswith("graft-hooks.cjs") and rest and rest[0] not in _OPS and not rest[0].startswith("-") else ""
    return (script, arg)


def _hooks(d: dict) -> list:
    out = []
    for ev, groups in (d.get("hooks") or {}).items():
        for g in groups:
            for h in g.get("hooks", []):
                out.append((ev, g, h))
    return out


def key_paths(d, prefix="") -> set:
    """Every dict key path, plus a path per list index of hooks groups' commands (so a dropped hook shows)."""
    out = set()
    if isinstance(d, dict):
        for k, v in d.items():
            p = f"{prefix}/{k}"
            out.add(p)
            out |= key_paths(v, p)
    return out


_SECRET_KEY = re.compile(r"(?i)(token|secret|passw|api[_-]?key|credential|private[_-]?key|authorization|apikeyhelper|awsauthrefresh|otelheadershelper)")
_SECRET_VAL = re.compile(r"(?i)(sk-[a-z0-9_-]{16,}|gh[pousr]_[a-z0-9]{20,}|xox[abp]-[a-z0-9-]{10,}|AKIA[0-9A-Z]{16}|bearer\s+\S{12,}|[a-f0-9]{40,}|-----BEGIN|github_pat_[a-z0-9_]{20,}|AIza[0-9A-Za-z_-]{35}|eyJ[\w-]+\.[\w-]+\.|[?&](api_?key|token|key)=\S|\b[A-Z_]*(KEY|TOKEN|SECRET)=\S)")


def secret_paths(d, p="") -> list:
    """Key paths holding a secret-shaped key (non-empty string value) or value. Never returns a value."""
    out = []
    if isinstance(d, dict):
        for k, v in d.items():
            q = f"{p}/{k}"
            if isinstance(v, str) and v and _SECRET_KEY.search(k):
                out.append(q)
            else:
                out += secret_paths(v, q)
    elif isinstance(d, list):
        for i, v in enumerate(d):
            out += secret_paths(v, f"{p}[{i}]")
    elif isinstance(d, str) and _SECRET_VAL.search(d):
        out.append(p)
    return out


def merge(live: dict, tmpl: dict, home: str, roots=None):
    """Return (merged, added, not_applied): added/not_applied are lists of key-path strings."""
    roots = default_roots(home) if roots is None else roots
    merged = copy.deepcopy(live)
    added, skipped = [], []
    # R1 hooks
    live_keys = {(ev, hook_key(h.get("command", ""), home)) for ev, _, h in _hooks(live)}
    live_twin = {(ev, hook_key(h.get("command", ""), home)): (g, h) for ev, g, h in _hooks(live)}
    live_cmds = {h.get("command") for _, _, h in _hooks(live)}
    for ev, g, h in _hooks(tmpl):
        k = hook_key(h.get("command", ""), home)
        if k is None:
            if h.get("command") in live_cmds:
                continue
            skipped.append(f"/hooks/{ev} (not ADE-owned: {h.get('command', '')[:40]!r})")
            continue
        if (ev, k) in live_keys:
            tw = live_twin.get((ev, k))
            if tw and (tw[0].get("matcher") != g.get("matcher") or tw[1].get("timeout") != h.get("timeout")):
                skipped.append(f"/hooks/{ev}: ADE hook {k[0]} differs in matcher/timeout (live kept)")
            continue
        if not is_ade_owned(k[0], home, roots):
            skipped.append(f"/hooks/{ev}: {k[0]} not added (script missing or not in the djbclark-ade tree)")
            continue
        live_keys.add((ev, k))
        grp = {kk: copy.deepcopy(vv) for kk, vv in g.items() if kk != "hooks"}
        grp["hooks"] = [copy.deepcopy(h)]
        merged.setdefault("hooks", {}).setdefault(ev, []).append(grp)
        added.append(f"/hooks/{ev}: {k[0]}" + (f" {k[1]}" if k[1] else ""))
    # R1b deny union
    if tmpl.get("permissions", {}).get("deny"):
        cur = merged.setdefault("permissions", {}).setdefault("deny", [])
        new_deny = [e for e in tmpl["permissions"]["deny"] if e not in cur]
        cur.extend(new_deny)
        if new_deny:
            added.append(f"/permissions/deny: +{len(new_deny)} entries")
    # R2: a key ABSENT from live is added; a present one is never touched (a differing value is only listed)
    other_hooks = {}

    def walk(a, b, m, p):
        if p in ("/hooks", "/permissions/deny"):
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b)):
                if k in a and k in b:
                    walk(a[k], b[k], m[k], f"{p}/{k}")
                elif k in b:
                    path = f"{p}/{k}"
                    if any(path == r or path.startswith(r + "/") or p == r for r in ADD_ABSENT):
                        m[k] = copy.deepcopy(b[k])
                        added.append(f"{path} (key absent from live)")
                    else:
                        skipped.append(f"{path} (template only; not on the add list)")
        elif a != b:
            skipped.append(f"{p} (value differs)")
    walk(live, tmpl, merged, "")
    lr = ((live.get("sandbox") or {}).get("filesystem") or {}).get("denyRead")
    tr = ((tmpl.get("sandbox") or {}).get("filesystem") or {}).get("denyRead")
    if isinstance(lr, list) and isinstance(tr, list):
        extra = [e for e in tr if e not in lr]
        merged["sandbox"]["filesystem"]["denyRead"] = lr + extra
        if extra:
            added.append(f"/sandbox/filesystem/denyRead: +{len(extra)} entries")
        skipped[:] = [x for x in skipped if not x.startswith("/sandbox/filesystem/denyRead ")]
    for s_ in [x for x in skipped if x.startswith("/hooks/") and "(not ADE-owned" in x]:
        ev = s_.split(" ")[0]
        other_hooks[ev] = other_hooks.get(ev, 0) + 1
    skipped[:] = [x for x in skipped if not (x.startswith("/hooks/") and "(not ADE-owned" in x)] + [f"{ev}: {n} non-ADE hook(s)" for ev, n in other_hooks.items()]
    return merged, added, skipped


def _lost(a, b, p, out):
    if isinstance(a, dict):
        if not isinstance(b, dict):
            out.append(p or "/")
            return
        for k, v in a.items():
            if k not in b:
                out.append(f"{p}/{k}")
            else:
                _lost(v, b[k], f"{p}/{k}", out)
    elif isinstance(a, list):
        if not isinstance(b, list) or any(x not in b for x in a):
            out.append(p + " (list element)")
    elif a != b:
        out.append(p + " (value)")


def refuse_if_dropped(live: dict, merged: dict) -> list:
    """Key paths, list elements or values of live that merged lacks or changed (never expected)."""
    out: list = []
    _lost(live, merged, "", out)
    return sorted(out)


def backup_path(live: Path) -> Path:
    return live.with_name(live.name + ".bak-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))


def write_backup(live: Path, data: bytes, bk: Path) -> Path:
    """Exclusive create with the live file's mode (never overwrites an earlier backup; a collision gets a numeric suffix)."""
    mode = stat.S_IMODE(os.stat(os.path.realpath(live)).st_mode)
    for n in range(100):
        cand = bk if n == 0 else bk.with_name(bk.name + f".{n}")
        try:
            fd = os.open(cand, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        except FileExistsError:
            continue
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(cand, mode)
        return cand
    raise OSError("no free backup name")


def write_atomic(live: Path, data: dict) -> None:
    real = Path(os.path.realpath(live))
    fd, tmp = tempfile.mkstemp(prefix=real.name + ".", dir=real.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        shutil.copymode(real, tmp)
        os.replace(tmp, real)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--render-template", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--home", default=str(Path.home()))
    ap.add_argument("--live")
    ap.add_argument("--template")
    a = ap.parse_args(argv)
    home = a.home
    live_p = Path(a.live or Path(home) / ".claude" / "settings.json")
    tmpl_p = Path(a.template or Path(__file__).resolve().parent.parent / "agents" / "claude" / "settings.json.tmpl")
    try:
        live_bytes = live_p.read_bytes()
        live = json.loads(live_bytes)
        tmpl = json.loads(render(tmpl_p.read_text(), home))
    except (OSError, ValueError) as e:
        print(f"ade-settings-apply: cannot read inputs: {e.__class__.__name__}: {e}", file=sys.stderr)
        return 2
    merged, added, skipped = merge(live, tmpl, home)
    if a.render_template:
        bad = secret_paths(merged)
        if bad:
            print("ade-settings-apply: --render-template REFUSED, secret-shaped entries at: " + ", ".join(bad), file=sys.stderr)
            return 1
        print(unrender(json.dumps(merged, indent=2, ensure_ascii=False), home))
        return 0
    dropped = refuse_if_dropped(live, merged)
    rep = {"live": str(live_p), "added": added, "not_applied": skipped, "dropped": dropped, "applied": False, "backup": None,
           "sandbox_added": merged.get("sandbox") if "sandbox" not in live else None}
    rc = 0
    if dropped:
        rc = 1
        print("ade-settings-apply: REFUSED, live key paths would disappear: " + ", ".join(dropped), file=sys.stderr)
    elif a.apply and merged != live:
        if live_p.read_bytes() != live_bytes:
            print("ade-settings-apply: live file changed while merging; nothing written, rerun", file=sys.stderr)
            return 1
        bk = backup_path(live_p)
        bk = write_backup(live_p, live_bytes, bk)
        write_atomic(live_p, merged)
        rep.update(applied=True, backup=str(bk))
    if a.json:
        print(json.dumps(rep, indent=2))
    else:
        verb = "applied" if rep["applied"] else ("would add" if added else "nothing to add")
        print(f"settings: {verb}: {len(added)} item(s) from the template" + (f" (backup {rep['backup']})" if rep["backup"] else ""))
        for x in added:
            print("  + " + x)
        for x in skipped:
            print("  template differs, not applied: " + x)
        if rep["sandbox_added"] is not None:  # it changes Bash behaviour for every new session: show all of it
            print("  the /sandbox block added:")
            for ln in json.dumps(rep["sandbox_added"], indent=2).splitlines():
                print("    " + ln)
    return rc


if __name__ == "__main__":
    sys.exit(main())
