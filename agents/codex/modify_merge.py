#!/usr/bin/env python3
"""Merge owned Codex config.toml keys into a live document (chezmoi modify_ helper).

    agents/codex/modify_merge.py --desired RENDERED.toml [--live LIVE.toml] [--write OUT.toml]

Reads the live TOML table from --live or stdin, merges owned keys from the rendered
template (--desired), keeps unowned live keys (including [hooks.trust.*], /private/tmp
[projects.*], and marketplace last_revision lines absent from the template), and writes
the result to --write or stdout. Refuses the operator's live ~/.codex/config.toml
(order 11).

Exit: 0 ok, 1 refused/failed, 2 usage.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent.parent / "modify_merge_lib.py"
_spec = importlib.util.spec_from_file_location("agents_modify_merge_lib", _LIB)
if _spec is None or _spec.loader is None:
    raise SystemExit("modify_merge: cannot load agents/modify_merge_lib.py")
lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lib)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="agents/codex/modify_merge.py",
        description="Owned-key merge for Codex ~/.codex/config.toml (no live home apply).",
    )
    ap.add_argument(
        "--desired",
        required=True,
        type=Path,
        help="rendered template TOML (owned keys)",
    )
    ap.add_argument(
        "--live",
        type=Path,
        help="live config.toml (default: stdin)",
    )
    ap.add_argument(
        "--write",
        type=Path,
        help="write merged TOML here (default: stdout); refuses ~/.codex/config.toml",
    )
    args = ap.parse_args(argv)

    try:
        desired = lib.load_toml(lib.read_text(args.desired, "desired"))
        live_text = lib.read_text(args.live, "live") if args.live else sys.stdin.read()
        live = lib.load_toml(live_text) if live_text.strip() else {}
    except (ValueError, SystemExit) as e:
        if isinstance(e, SystemExit):
            raise
        print(f"modify_merge: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # tomllib.TOMLDecodeError and friends
        print(f"modify_merge: {type(e).__name__}: parse failed (text withheld)", file=sys.stderr)
        return 1

    merged = lib.merge_owned(live, desired)
    try:
        out = lib.dump_toml(merged)
    except TypeError as e:
        print(f"modify_merge: cannot encode TOML: {e}", file=sys.stderr)
        return 1

    if args.write is None:
        sys.stdout.write(out)
        return 0

    reason = lib.refuse_live_home(args.write)
    if reason:
        print(f"modify_merge: {reason}", file=sys.stderr)
        return 1
    try:
        lib.atomic_write(args.write, out)
    except OSError as e:
        print(f"modify_merge: cannot write {args.write}: {e.strerror}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
