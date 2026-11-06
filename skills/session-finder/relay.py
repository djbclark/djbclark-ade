#!/usr/bin/env python3
# Shim, removed in the follow-up PR after one live cycle (PLAN.md F, Wave 6; at the latest 2026-11-20). docs/slim/PLAN.md E3, D1.
"""relay.py (shim): send one message to one Paseo agent with `paseo send`, and say what became of it. Stdlib only.

The old relay.py (4.9k lines: herdr, Orca, tmux, dispatch and launch routes, the deferred outbox, the expected-ack ledger) was retired on
2026-11-06; herdr and Orca panes were retired on 2026-10-31. What is left is Paseo's own receipt, read from `--json`: `paseo send`
exits 0 for every status (queued, sent, completed, timeout, permission, error), so its exit status is never read as delivery.

Paseo 0.15.3 (getpaseo/paseo 9f68af0): a send that carries a source agent ($PASEO_AGENT_ID set; cli send.ts:202-207) is always
enqueued by the daemon and answered `queued` before dispatch (server session.ts:8774-8793), and nothing reports its later delivery:
for an agent sender `queued` is the normal, accepted result (exit 5), proven only by the peer's `ack <id>`. A sourceless send
(deadline, load-watch) is dispatched directly and answers `sent`: that is delivery (exit 0).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

REMOVE_BY = "2026-11-20"
RETIRED_ROUTES = "relay.py reaches Paseo agents only since 2026-11-06 (herdr and Orca panes retired 2026-10-31)"
RETIRED_FLAGS = ("--pending", "--sweep", "--retire", "--transfer-expectations", "--expect-ack")
RETIRED_OUTBOX = "retired 2026-11-06: Paseo has no outbox; see `paseo permit ls` for pending permissions"
DELIVERED = ("sent", "completed")
ACCEPTED_TEXT = ("queued (accepted by the daemon; Paseo batches every agent-to-agent message and reports no later delivery; "
                 "proof is the peer's ack)")
ZERO_WIDTH = "​‌‍⁠﻿᠎"
SENDABLE = ("idle", "running")
# Providers whose session implements steerActiveTurn in Paseo 0.15.3 (providers/{claude,omp,pi}/agent.ts, codex-app-server-agent.ts,
# opencode-agent.ts). `paseo agent inspect`'s Capabilities carries no steer flag (cli inspect.ts:33-38,118-127), so this list decides;
# a Capabilities key naming steer, if a later Paseo adds one, wins. Any other provider's running turn would be REPLACED by a steer.
STEER_PROVIDERS = ("claude", "codex", "opencode", "omp", "pi")
LABEL_RE = re.compile(r"[^A-Za-z0-9_.:-]")
EPILOG = f"""exit status:
  0   delivered: a sourceless send (no $PASEO_AGENT_ID: deadline, load-watch) read `sent` or `completed`
      (with --wait: and `paseo wait` then read `idle`)
  5   accepted: a send from a Paseo agent ($PASEO_AGENT_ID set) read `queued`; the daemon queues every agent-to-agent message
      and reports no later delivery, so the proof is the peer's `ack <id>` (--wait then reports the target's state, never delivery)
  1   paseo failed: not installed, exited non-zero (no daemon, unknown agent), gave no JSON, or did not answer in time
  2   not delivered: `queued` for a sourceless send, `timeout`, `permission`, `error`, or no status; --wait timed out or hit a
      permission; or not sent: `paseo agent inspect` failed, gave another shape or id, shows the target archived, with a pending
      permission or question card, in a status other than idle or running, or running on a provider that cannot steer
  3   TARGET is not exactly one Paseo agent by id or shortId prefix, or is a name ({RETIRED_ROUTES})
  4   no sender: neither $PASEO_AGENT_ID nor $RELAY_SENDER_NAME names who sends (no anonymous sends, 2026-10-25)
  64  usage error, a message file or stdin that is not UTF-8, a --wait that is negative or not finite, a text starting with `/`
      (it would run a built-in in the target), or a retired flag: --via ({RETIRED_ROUTES}); {', '.join(RETIRED_FLAGS)}
      ({RETIRED_OUTBOX})
TARGET is a Paseo agent id, a unique prefix (4+ characters) of its shortId, or `self` ($PASEO_AGENT_ID), as `paseo ls -a -g` lists them;
never a name (title): a name is exit 3, pass the id.
A sender with no $PASEO_AGENT_ID (a launchd job) is named in a `[relay from NAME]` prefix, NAME from $RELAY_SENDER_NAME
(letters, digits, `-`, `_`, `.`, `:`; at most 64).
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
    # an id, or a prefix of a shortId; never a name: a title comes from the first prompt (`/baton`, "say hi"), a weak address
    # (adversary L3; lead's ruling, 2026-11-06)
    for match in (lambda r: r.get("id") == target, lambda r: len(target) >= 4 and str(r.get("shortId") or "").startswith(target)):
        hits = [r for r in rows if isinstance(r, dict) and match(r)]
        if hits:
            return hits
    return []


def status_of(obj: object) -> str:
    return str((obj.get("status") or obj.get("deliveryStatus") or "") if isinstance(obj, dict) else "")


def refusal(info: object, aid: str) -> str | None:
    """Why the target must not get this send, from `paseo agent inspect --json`; None only for the exact expected shape (fail closed)."""
    if not isinstance(info, dict) or info.get("Id") != aid:
        return f"`paseo agent inspect` did not describe {aid}"
    if info.get("Archived") is not False:
        return f"{aid} is archived (a send would unarchive it), or inspect does not say it is not"
    if info.get("PendingPermissions") != []:
        return f"{aid} waits on a permission or question card (`paseo permit ls`), or inspect does not say it does not"
    status = info.get("Status")
    if status not in SENDABLE:
        return f"{aid} is {status!r}, not idle or running"
    if status == "running":
        caps = info.get("Capabilities") if isinstance(info.get("Capabilities"), dict) else {}
        steer = [v for k, v in caps.items() if "steer" in str(k).lower()]
        provider = str(info.get("Provider") or "").split("/")[0]
        if not (steer[0] is True if steer else provider in STEER_PROVIDERS):
            return f"{aid} is busy, not sent (provider {provider or '?'} cannot steer: its running turn would be replaced)"
    return None


def read_text(path: str | None, positional: str | None) -> str:
    if path == "-":
        return sys.stdin.buffer.read().decode("utf-8-sig")
    if path:
        with open(path, "rb") as fh:
            return fh.read().decode("utf-8-sig")
    return positional or ""


def main(argv: list[str]) -> int:
    for a in argv:
        flag = a.split("=", 1)[0]
        if flag == "--via":
            print(f"relay.py: --via is retired: {RETIRED_ROUTES}", file=sys.stderr)
            return 64
        if flag in RETIRED_FLAGS:
            print(f"relay.py: {flag} is {RETIRED_OUTBOX}", file=sys.stderr)
            return 64
    ap = Parser(prog="relay.py", description="Send MESSAGE to one Paseo agent with `paseo send --no-wait --json` and report what Paseo says became of it.",
                epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", metavar="TARGET", help="Paseo agent id, unique shortId prefix, or `self` (not a name)")
    ap.add_argument("message", metavar="MESSAGE", nargs="?", help="the text (exactly one of MESSAGE and --message-file)")
    ap.add_argument("--message-file", metavar="PATH", help="read the text from PATH, UTF-8 (`-`: stdin); for text with backticks, `$` or quotes")
    ap.add_argument("--ack", metavar="NAME", nargs="?", const="", help="append \"Reply with `ack NAME` through relay.py\" to the text; "
                    "bare --ack appends nothing; put MESSAGE before a bare --ack")
    ap.add_argument("--wait", metavar="S", type=float, help="after a delivered (0) or accepted (5) send, `paseo wait TARGET --timeout S`; "
                    "for a delivered send exit 0 only when it reads idle; for an accepted one it reports the target's state only")
    a = ap.parse_args(argv)
    if (a.message is None) == (a.message_file is None):
        ap.error("give exactly one of MESSAGE and --message-file")
    if a.wait is not None and not (math.isfinite(a.wait) and a.wait >= 0):
        ap.error("--wait takes a finite number of seconds, 0 or more")
    try:
        text = read_text(a.message_file, a.message)
    except OSError as e:
        ap.error(f"--message-file: {e}")
    except UnicodeDecodeError as e:
        ap.error(f"the message is not UTF-8: {e}")
    text = text[:-1] if text.endswith("\n") else text
    if not text.strip():
        ap.error("the message is empty")
    lead = text
    while lead and (lead[0].isspace() or lead[0] in ZERO_WIDTH):    # every Unicode space and the zero-width set: Paseo trims before its parser
        lead = lead[1:]
    if lead.startswith(("/", "／")):
        ap.error("not sent: text starting with '/' would run a built-in; peers do not run another session's built-ins")
    source = bool(os.environ.get("PASEO_AGENT_ID", "").strip())
    if not source:
        label = LABEL_RE.sub("", os.environ.get("RELAY_SENDER_NAME") or "")[:64]
        if not label:
            print("relay.py: no sender: set $RELAY_SENDER_NAME (letters, digits, `-`, `_`, `.`, `:`) or run as a Paseo agent; "
                  "anonymous sends cannot be answered (2026-10-25)", file=sys.stderr)
            return 4
        text = f"[relay from {label}] {text}"
    if a.ack:
        text += f"\n\nReply with `ack {a.ack}` through relay.py."
    rc, rows, err = paseo("ls", "-a", "-g", "--json", timeout=30)
    if rc:
        print(f"relay.py: paseo ls failed: {err}", file=sys.stderr)
        return 1
    rows = rows.get("agents", []) if isinstance(rows, dict) else rows if isinstance(rows, list) else []
    hits = resolve(a.target, rows)
    if len(hits) != 1:
        named = [r for r in rows if isinstance(r, dict) and r.get("name") == a.target]
        why = (f"target {a.target} matches {len(hits)} Paseo agents ({', '.join(str(h.get('id')) for h in hits)})" if hits else
               f"target {a.target} is a Paseo agent's name, not its id: pass the id (`paseo ls -a -g` shows it)" if named else
               f"target {a.target} is not a Paseo agent")
        print(f"relay.py: {RETIRED_ROUTES}; {why}", file=sys.stderr)
        return 3
    aid = str(hits[0]["id"])
    # never into a card, an archive, a starting or failed agent, or a running turn that cannot take a steer (docs/threat-model.md):
    # a sourceless send runs with clearPendingPermissions and would answer a pending card with this text
    rc, info, err = paseo("agent", "inspect", aid, "--json", timeout=30)
    why = f"`paseo agent inspect` failed: {err}" if rc else refusal(info, aid)
    if why:
        print(f"not sent: {why}")
        return 2
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
    if st in DELIVERED:
        print("delivered")
        result = 0
    elif st == "queued" and source:
        print(ACCEPTED_TEXT)
        result = 5
    else:
        print("queued (accepted by the daemon, not delivered)" if st == "queued" else st or "no status")
        return 2
    if a.wait is None:
        return result
    rc, out, err = paseo("wait", aid, "--timeout", f"{a.wait:g}", "--json", timeout=a.wait + 30)
    st = "" if rc else status_of(out)
    word = ("idle" if st == "idle" else f"wait timed out after {a.wait:g} s" if st == "timeout" else
            "permission (pending: `paseo permit ls`)" if st == "permission" else f"wait failed: {err}" if rc else st or "no status")
    if result == 5:
        print(f"target {word}")    # the target's state, never the message's delivery
        return 5
    if rc:
        print(f"relay.py: paseo wait failed: {err}", file=sys.stderr)
        return 1
    print(word)
    return 0 if st == "idle" else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
