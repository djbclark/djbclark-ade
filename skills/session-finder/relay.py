#!/usr/bin/env python3
# Shim, removed in the follow-up PR after one live cycle (PLAN.md F, Wave 6; at the latest 2026-11-20). docs/slim/PLAN.md E3, D1.
"""relay.py (shim): send one message to one Paseo agent with `paseo send`, and say whether it was delivered. Stdlib only.

The old relay.py (4.9k lines: herdr, Orca, tmux, dispatch and launch routes, the deferred outbox, the expected-ack ledger) was retired on
2026-11-06; herdr and Orca panes were retired on 2026-10-31. What is left is Paseo's own delivery receipt, read from `--json`:
`paseo send` exits 0 for every status (queued, sent, completed, timeout, permission, error), so its exit status is never read as delivery.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

REMOVE_BY = "2026-11-20"
RETIRED_ROUTES = "relay.py reaches Paseo agents only since 2026-11-06 (herdr and Orca panes retired 2026-10-31)"
RETIRED_FLAGS = ("--pending", "--sweep", "--retire", "--transfer-expectations", "--expect-ack")
RETIRED_OUTBOX = "retired 2026-11-06: Paseo has no outbox; see `paseo permit ls` for pending permissions"
DELIVERED = ("sent", "completed")
EPILOG = f"""exit status:
  0   delivered: `paseo send --json` read `sent` or `completed` (with --wait: and `paseo wait` then read `idle`)
  1   paseo failed: not installed, exited non-zero (no daemon, unknown agent), gave no JSON, or did not answer in time
  2   not delivered: `queued` (accepted by the daemon, not yet delivered), `timeout`, `permission`, `error`; or --wait timed out or hit a permission
  3   TARGET is not exactly one Paseo agent ({RETIRED_ROUTES})
  64  usage error, or a retired flag: --via ({RETIRED_ROUTES}); {', '.join(RETIRED_FLAGS)} ({RETIRED_OUTBOX})
TARGET is a Paseo agent id, a prefix of its id or shortId, its name (title), or `self` ($PASEO_AGENT_ID), as `paseo ls -a -g --json` lists it.
A sender with no $PASEO_AGENT_ID (a launchd job) is named in a `[relay from NAME]` prefix, NAME from $RELAY_SENDER_NAME.
Shim: removed in the follow-up PR after one live cycle, at the latest {REMOVE_BY}."""


class Parser(argparse.ArgumentParser):
    def error(self, message: str):    # usage errors are 64, so they never read as "not delivered" (2)
        self.print_usage(sys.stderr)
        sys.stderr.write(f"relay.py: {message}\n")
        raise SystemExit(64)


def paseo(*args: str, timeout: float) -> tuple[int, object, str]:
    """(rc, parsed JSON or None, stderr). rc 1 for a missing binary, a non-zero exit, no JSON or no answer in time."""
    exe = shutil.which("paseo")
    if not exe:
        return 1, None, "paseo is not on PATH"
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 1, None, f"paseo {args[0]} did not answer in {timeout:g} s"
    except OSError as e:
        return 1, None, str(e)
    if r.returncode != 0:
        return 1, None, (r.stderr or r.stdout or "").strip() or f"paseo {args[0]} exited {r.returncode}"
    try:
        return 0, json.loads(r.stdout), r.stderr
    except ValueError:
        return 1, None, f"paseo {args[0]} gave no JSON: {(r.stdout or r.stderr or '').strip()[:200]}"


def resolve(target: str, rows: list[dict]) -> list[dict]:
    if target == "self":
        target = os.environ.get("PASEO_AGENT_ID", "")
        if not target:
            return []
    for match in (lambda r: target in (r.get("id"), r.get("shortId")), lambda r: r.get("name") == target,
                  lambda r: len(target) >= 4 and any(str(r.get(k) or "").startswith(target) for k in ("id", "shortId"))):
        hits = [r for r in rows if isinstance(r, dict) and match(r)]
        if hits:
            return hits
    return []


def status_of(obj: object) -> str:
    return str((obj.get("status") or obj.get("deliveryStatus") or "") if isinstance(obj, dict) else "")


def main(argv: list[str]) -> int:
    for a in argv:
        flag = a.split("=", 1)[0]
        if flag == "--via":
            print(f"relay.py: --via is retired: {RETIRED_ROUTES}", file=sys.stderr)
            return 64
        if flag in RETIRED_FLAGS:
            print(f"relay.py: {flag} is {RETIRED_OUTBOX}", file=sys.stderr)
            return 64
    ap = Parser(prog="relay.py", description="Send MESSAGE to one Paseo agent with `paseo send --no-wait --json` and report its delivery status.",
                epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", metavar="TARGET", help="Paseo agent id, id/shortId prefix, name, or `self`")
    ap.add_argument("message", metavar="MESSAGE", nargs="?", help="the text (exactly one of MESSAGE and --message-file)")
    ap.add_argument("--message-file", metavar="PATH", help="read the text from PATH, UTF-8 (`-`: stdin); for text with backticks, `$` or quotes")
    ap.add_argument("--ack", metavar="NAME", nargs="?", const="", help="append \"Reply with `ack NAME` through relay.py\" to the text; "
                    "bare --ack appends nothing (delivery is always read from the status); put MESSAGE before a bare --ack")
    ap.add_argument("--wait", metavar="S", type=float, help="after a delivered send, `paseo wait TARGET --timeout S`: exit 0 only when it reads idle")
    a = ap.parse_args(argv)
    if (a.message is None) == (a.message_file is None):
        ap.error("give exactly one of MESSAGE and --message-file")
    try:
        text = sys.stdin.read() if a.message_file == "-" else open(a.message_file, encoding="utf-8-sig").read() if a.message_file else a.message
    except OSError as e:
        ap.error(f"--message-file: {e}")
    text = text[:-1] if text.endswith("\n") else text
    if not text.strip():
        ap.error("the message is empty")
    if a.ack:
        text += f"\n\nReply with `ack {a.ack}` through relay.py."
    if not os.environ.get("PASEO_AGENT_ID"):
        text = f"[relay from {os.environ.get('RELAY_SENDER_NAME') or 'a non-Paseo caller'}] {text}"
    rc, rows, err = paseo("ls", "-a", "-g", "--json", timeout=30)
    if rc:
        print(f"relay.py: paseo ls failed: {err}", file=sys.stderr)
        return 1
    rows = rows.get("agents", []) if isinstance(rows, dict) else rows if isinstance(rows, list) else []
    hits = resolve(a.target, rows)
    if len(hits) != 1:
        why = f"target {a.target} matches {len(hits)} Paseo agents ({', '.join(str(h.get('id')) for h in hits)})" if hits else \
            f"target {a.target} is not a Paseo agent"
        print(f"relay.py: {RETIRED_ROUTES}; {why}", file=sys.stderr)
        return 3
    aid = str(hits[0]["id"])
    with tempfile.TemporaryDirectory(prefix="relay-shim-") as tmp:    # a file, not argv: no text in `ps`, no option parsing of a leading `-`
        path = os.path.join(tmp, "message.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        # steer, not Paseo's default: with no $PASEO_AGENT_ID (deadline, launchd) the default is interrupt, which would cancel the target's turn
        rc, out, err = paseo("send", aid, "--prompt-file", path, "--behavior", "steer", "--no-wait", "--json", timeout=60)
    if rc:
        print(f"relay.py: paseo send failed: {err}", file=sys.stderr)
        return 1
    st = status_of(out)
    if st not in DELIVERED:
        print("queued (accepted by the daemon, not yet delivered: the target has not been quiet for 2 s)" if st == "queued" else st or "no status")
        return 2
    print("delivered")
    if a.wait is None:
        return 0
    rc, out, err = paseo("wait", aid, "--timeout", f"{a.wait:g}", "--json", timeout=a.wait + 30)
    if rc:
        print(f"relay.py: paseo wait failed: {err}", file=sys.stderr)
        return 1
    st = status_of(out)
    if st == "idle":
        print("idle")
        return 0
    print(f"wait timed out after {a.wait:g} s" if st == "timeout" else "permission (pending: `paseo permit ls`)" if st == "permission" else st or "no status")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
