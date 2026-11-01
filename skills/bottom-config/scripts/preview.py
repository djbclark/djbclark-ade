#!/usr/bin/env python3
"""Start bottom in a throwaway tmux session with a config, print what it drew.

    preview.py [--config FILE] [--bin PATH] [--width N] [--height N]
               [--keys KEYS] [--seconds S] [-- EXTRA_BTM_ARGS...]

Defaults: the fork build ~/.local/bin/btm-mt, ~/.config/bottom/bottom.toml,
140x30, process widget expanded (`-e --default_widget_type proc`), 4 s.
--keys is sent to tmux after startup (e.g. `t` for tree mode, `P` for
name/command); letters only, no Enter. Nothing is left running.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], capture_output=True, text=True, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path.home() / ".config/bottom/bottom.toml")
    parser.add_argument("--bin", type=Path, default=Path.home() / ".local/bin/btm-mt")
    parser.add_argument("--width", type=int, default=140)
    parser.add_argument("--height", type=int, default=30)
    parser.add_argument("--keys", default="")
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument("extra", nargs="*")
    args = parser.parse_args()

    if shutil.which("tmux") is None:
        print("tmux not found", file=sys.stderr)
        return 2
    if not args.bin.exists():
        print(f"binary not found: {args.bin}", file=sys.stderr)
        return 2

    session = f"btm-preview-{os.getpid()}"
    cmd = [str(args.bin), "-C", str(args.config), "-e", "--default_widget_type", "proc", *args.extra]
    started = tmux(
        "new-session", "-d", "-s", session, "-x", str(args.width), "-y", str(args.height), *cmd
    )
    if started.returncode != 0:
        print(started.stderr.strip(), file=sys.stderr)
        return 2
    try:
        time.sleep(args.seconds)
        if args.keys:
            tmux("send-keys", "-t", session, *list(args.keys))
            time.sleep(2)
        shot = tmux("capture-pane", "-t", session, "-p")
        print(shot.stdout, end="")
        if shot.returncode != 0:
            print("btm exited before it could be captured (bad config or flag?)", file=sys.stderr)
            return 1
    finally:
        tmux("kill-session", "-t", session)
    return 0


if __name__ == "__main__":
    sys.exit(main())
