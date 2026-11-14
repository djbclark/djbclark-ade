"""Never resurrect an archived agent by messaging it (ls-02, 2026-11-14).

Paseo un-archives and runs an archived agent that is sent a message (2026-11-14: the ex-lead 994234ba came back running,
`Archived=false`, after a message reached it, and could act as a stale lead). `ade-self-session finish` archives a handed-off
agent and leaves `handoff-<predecessor>.json`; `ade_lead_succession` reads those records. This module decides, for one send
target, what a sender should do instead:

  pass      the target is live (or unknown to Paseo, which then reports it): send as asked.
  redirect  a completed self-handoff replaced the target: send to the current holder of its role instead. Applies even when
            the old agent is already running again (`Archived=false`): the chain says it was replaced.
  refuse    the target is archived and nothing replaced it, or its succession ledger is cyclic, or the successor itself is
            archived: nothing is sent. `allow_archived` (operator override, deliberate resume of an archived agent) turns
            a plain archived target into `pass` when it is True or equals that agent's full id; it never overrides a
            redirect or a cycle.

`inspect` is injected: `inspect(id_or_name) -> {"Id": ..., "Archived": bool, ...}`, raising LookupError when Paseo does not
know the agent and anything else (OSError, ValueError, ...) when it cannot answer. A Paseo outage fails OPEN (`pass`): a
guard that blocks every message during a daemon restart would be worse than the bug (the send itself fails then).
Read-only: this module never writes a record and never sends.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ade_lead_succession as succ  # noqa: E402

PASS, REDIRECT, REFUSE = "pass", "redirect", "refuse"
ALLOW_ENV = "ADE_ALLOW_ARCHIVED_SEND"  # =<the agent's full id> in a command's environment: one deliberate resume of it
EXIT_REFUSED = 4  # the ADE report class for "blocked"
EXIT_REDIRECT = 3  # send to the decision's target, not to the one asked for


@dataclass(frozen=True)
class Decision:
    action: str
    target: str  # the id to send to (the original target for pass and refuse)
    reason: str = ""

    def as_dict(self) -> dict:
        return {"action": self.action, "target": self.target, "reason": self.reason}


def _record(inspect, ident: str) -> dict | None:
    """The inspect record for `ident`, None when Paseo does not know it. Other failures propagate (caller fails open)."""
    try:
        data = inspect(ident)
    except LookupError:
        return None
    return data if isinstance(data, dict) else None


def decide(target: str, inspect, allow_archived: bool | str | None = False, state_dir: Path | None = None,
           home: Path | None = None) -> Decision:
    """What to do about a send to `target` (an id, an id prefix or a name Paseo resolves)."""
    if target.startswith("-"):  # an option, not an agent: never hand it to the inspect CLI
        return Decision(PASS, target, "not an agent id: not guarded")
    try:
        record = _record(inspect, target)
    except Exception:  # noqa: BLE001 - Paseo unreadable: fail open, the send reports its own error
        return Decision(PASS, target, "paseo could not inspect the target: not guarded")
    if record is None or not isinstance(record.get("Id"), str):
        return Decision(PASS, target, "unknown to paseo: not guarded")
    ident = record["Id"]
    try:
        current = succ.effective_lead(ident, state_dir, home)
    except succ.SuccessionError as exc:
        return Decision(REFUSE, target, f"{exc}: the succession ledger is inconsistent; ask the operator")
    if current != ident:
        try:
            successor = _record(inspect, current)
        except Exception:  # noqa: BLE001
            successor = None
        if successor is not None and successor.get("Archived") is True:
            return Decision(REFUSE, target, f"{ident} was replaced by {current}, which is archived too: nothing to send to")
        return Decision(REDIRECT, current, f"{ident} was replaced through a completed self-handoff; send to {current}")
    if record.get("Archived") is True and not (allow_archived is True or allow_archived == ident):
        return Decision(REFUSE, target, f"{ident} is archived and no completed handoff replaced it: a send would un-archive "
                        f"and run it. Send to its live owner; resuming an archived agent needs the operator's explicit "
                        f"instruction ({ALLOW_ENV}=<its full id>, for that one send)")
    return Decision(PASS, target)


def paseo_inspect(paseo: str = "paseo", timeout: int = 5):
    """An `inspect` callable over `paseo agent inspect ID --json` (argv list, bounded). LookupError for a not-found agent."""
    def inspect(ident: str) -> dict:
        proc = subprocess.run([paseo, "agent", "inspect", ident, "--json"], capture_output=True, text=True, timeout=timeout,
                              check=False)
        if proc.returncode != 0:
            text = (proc.stderr + proc.stdout).lower()
            if "not found" in text or "no agent" in text or "ambiguous" in text:
                raise LookupError(ident)
            raise OSError(f"paseo agent inspect exited {proc.returncode}")
        return json.loads(proc.stdout)
    return inspect


def guard(target: str, paseo: str = "paseo", env=None, **kw) -> Decision:
    """`decide` over the real paseo CLI, honouring ADE_ALLOW_ARCHIVED_SEND."""
    env = os.environ if env is None else env
    return decide(target, paseo_inspect(paseo), allow_archived=env.get(ALLOW_ENV) or False, **kw)


def main(argv=None) -> int:
    """`python3 ade_send_guard.py TARGET`: print the decision as JSON; exit 0 pass, 3 redirect (send to `.target`), 4 refuse."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0].startswith("-"):
        print("usage: ade-send-guard TARGET", file=sys.stderr)
        return 2
    d = guard(args[0])
    print(json.dumps(d.as_dict()))
    return EXIT_REFUSED if d.action == REFUSE else EXIT_REDIRECT if d.action == REDIRECT else 0


if __name__ == "__main__":
    raise SystemExit(main())
