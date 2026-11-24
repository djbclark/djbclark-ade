"""Never resurrect an archived agent by messaging it (ls-02, 2026-11-14).

Paseo un-archives and runs an archived agent that is sent a message (2026-11-14: the ex-lead 994234ba came back running,
`Archived=false`, after a message reached it, and could act as a stale lead). `ade-self-session finish` archives a handed-off
agent and leaves `handoff-<predecessor>.json`; `ade_lead_succession` reads those records. This module decides, for one send
target, what a sender should do instead:

  pass      the target is live (or unknown to Paseo, which then reports it): send as asked.
  redirect  a completed self-handoff replaced the target: send to the current holder of its role instead. Applies even when
            the old agent is already running again (`Archived=false`): the chain says it was replaced.
            An `acknowledged` handoff (the successor attested, `finish` has not archived the predecessor yet) redirects too
            (rq-38, 2026-11-15: five done notices to the acknowledged 6621fe2b stretched `finish`'s idle wait ~15 min), but only to
            a successor (and the holder of its role) Paseo knows and reports `Archived: false`, and only while the record is fresh
            (`ade_lead_succession.ACK_WINDOW_SECONDS` after `accept`, no `finish` failure but waiting); otherwise the hop is
            ignored and the target passes as before.
  refuse    the target is archived and nothing replaced it, or its succession ledger is cyclic, or the successor itself is
            archived: nothing is sent. A plain archived target (no handoff replaced it) passes in two cases only: (1) the SENDER
            OWNS it, `owner_proof` below (operator ruling 2026-11-21: agents may un-archive their own archived workers without
            asking the operator when resuming one with its context is cheaper than a fresh one; the launcher is the lead; fail
            closed; the use is logged, `log_resume`), or (2) `allow_archived` (operator override, deliberate resume of any
            archived agent) is True or equals that agent's full id. Neither ever overrides a redirect or a cycle. `allow_replaced` (operator override, ADE_ALLOW_REPLACED_SEND, 2026-11-14) turns a redirect
            into `pass` only when it equals the target's full id, the target is live (`Archived` is False, so the send cannot
            un-archive it) and its succession chain is sound; the decision then carries `replaced_by` and `guard()` logs the use.

`inspect` is injected: `inspect(id_or_name) -> {"Id": ..., "Archived": bool, ...}`, raising LookupError when Paseo does not
know the agent and anything else (OSError, ValueError, ...) when it cannot answer. A Paseo outage fails OPEN (`pass`): a
guard that blocks every message during a daemon restart would be worse than the bug (the send itself fails then).
Read-only: this module never writes a record and never sends.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ade_lead_succession as succ  # noqa: E402
import ade_paseo_client as paseo_client  # noqa: E402

PASS, REDIRECT, REFUSE = "pass", "redirect", "refuse"
ALLOW_ENV = "ADE_ALLOW_ARCHIVED_SEND"  # =<the agent's full id> in a command's environment: one deliberate resume of it
ALLOW_REPLACED_ENV = "ADE_ALLOW_REPLACED_SEND"  # =<a live, replaced agent's full id>: send to it anyway, not to its successor
SENDER_ENV = "PASEO_AGENT_ID"  # the sender: ownership of an archived worker is judged against this agent and its lineage
LOG_ENV = "ADE_SEND_GUARD_LOG"  # where overrides are logged (default DEFAULT_LOG under the home directory)
DEFAULT_LOG = Path(".local/state/djbclark-ade/send-guard-overrides.jsonl")
EXIT_REFUSED = 4  # the ADE report class for "blocked"
EXIT_REDIRECT = 3  # send to the decision's target, not to the one asked for
MAX_PARENT_HOPS = 8  # a worker's worker's worker ...: further up is no proof


@dataclass(frozen=True)
class Decision:
    action: str
    target: str  # the id to send to (the original target for pass and refuse)
    reason: str = ""
    replaced_by: str = ""  # set on a `pass` that ignored a redirect (ADE_ALLOW_REPLACED_SEND): the successor it skipped
    resumed: str = ""  # set on a `pass` that un-archives the sender's OWN worker: "owner"
    proof: str = ""  # with resumed == "owner": the evidence (`label:ade.lead=<id>` or `parent:<id>`)

    def as_dict(self) -> dict:
        return {"action": self.action, "target": self.target, "reason": self.reason}



def _coord():
    """Load only our trusted absolute sibling; valid after temporary -I paths restore."""
    import importlib.util
    import sys
    path = Path(__file__).resolve().with_name("ade_coord.py")
    name = "ade_coord"
    found = sys.modules.get(name)
    if found is not None and Path(found.__file__).resolve() == path:
        return found
    key = name if found is None else "_ade_coord_" + str(path)
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(key, None)
        raise
    return module


def _record(inspect, ident: str) -> dict | None:
    """The inspect record for `ident`, None when Paseo does not know it. Other failures propagate (caller fails open)."""
    try:
        data = inspect(ident)
    except LookupError:
        return None
    return data if isinstance(data, dict) else None


def _cached(inspect):
    """`inspect` memoised for one decision (sr-43 e): the target, the successor and the chain end are each read once.
    A not-found answer (LookupError) is cached too; any other failure is not, so it still fails open each time."""
    seen: dict = {}

    def cached(ident: str):
        if ident not in seen:
            try:
                seen[ident] = inspect(ident)
            except LookupError:
                seen[ident] = LookupError(ident)
        if isinstance(seen[ident], LookupError):
            raise seen[ident]
        return seen[ident]
    return cached


def _follow(ident: str, inspect, state_dir: Path | None, home: Path | None) -> str:
    """The current holder of `ident`'s role: the end of its completed chain, then across `acknowledged` hops (each only to a
    successor that is live, so a crashed successor never leaves the predecessor unreachable), then that agent's completed chain."""
    current = succ.effective_lead(ident, state_dir, home)
    seen = {ident, current}
    while True:
        nxt = succ.successor_of(current, state_dir, home, statuses=succ.ACKNOWLEDGED)
        if nxt is None:
            return current
        try:
            live = _record(inspect, nxt)
        except Exception:  # noqa: BLE001 - cannot tell whether the successor lives: do not redirect on a guess
            return current
        if live is None or live.get("Archived") is not False:
            return current
        end = succ.effective_lead(nxt, state_dir, home)
        if end != nxt:  # the successor itself was replaced since: its holder must be live too
            try:
                live = _record(inspect, end)
            except Exception:  # noqa: BLE001
                return current
            if live is None or live.get("Archived") is not False:
                return current
        current = end
        if current in seen:
            raise succ.SuccessionError(f"lead succession from {ident} is cyclic")
        seen.update((nxt, current))


def owner_proof(ident: str, sender, inspect, ls_label, state_dir: Path | None = None, home: Path | None = None) -> str:
    """Why the SENDER may resume the archived agent `ident` without the operator (ruling 2026-11-21): "" when it cannot be
    proven (fail closed: no sender, a sender that is not a full agent id, a sender that is the target, a Paseo that cannot be
    asked, an inconsistent ledger), else the evidence. The sender's lineage is the sender plus the leads it replaced through
    completed self-handoffs (`succ.recent_lineage`: a worker the previous incarnation launched is the successor's too). Two proofs,
    each from what Paseo itself records, never from a name or from text:
      `label:ade.lead=<x>`  the target is in the server-side listing `paseo ls -a -g --label ade.lead=<x>` for x in the lineage
                            (`bin/ade-worker-run` launches every ADE worker top-level with that label: it strips PASEO_AGENT_ID, so the
                            worker has no Paseo parent and the label is the only record of whose it is);
      `parent:<x>`          the target's `ParentAgentId` chain (at most MAX_PARENT_HOPS, cycle-safe, every hop read from Paseo) reaches
                            x in the lineage: a worker started natively (`paseo run`, `create_agent`) from the sender's session.
    A label can be set by whoever launches an agent, so this is an accident guard under the operator's internal-trust ruling
    (AGENTS.md, Trust), not a sandbox."""
    sender = sender.strip() if isinstance(sender, str) else ""
    if not succ.UUID_RE.fullmatch(sender) or sender == ident:
        return ""
    try:  # the sender must itself hold its role: a predecessor's old workers are its successor's (PR 907 review MED-1)
        if succ.effective_lead(sender, state_dir, home) != sender:
            return ""  # replaced by a completed handoff (or an enrolled role holder)
        if succ.successor_of(sender, state_dir, home, statuses=succ.ACKNOWLEDGED) is not None:
            return ""  # handing off right now: the successor owns them
        me = _record(inspect, sender)
        if me is None or me.get("Archived") is not False:
            return ""  # an archived (or unknown) sender is no live owner
        lineage = succ.recent_lineage(sender, state_dir, home)
    except Exception:  # noqa: BLE001 - a cyclic or unreadable ledger, or an unreadable sender: ownership unknown
        return ""
    members = set(lineage)
    try:  # the parent chain first: it needs only inspect reads
        seen, cur = {ident}, (inspect(ident) or {}).get("ParentAgentId")
        for _ in range(MAX_PARENT_HOPS):
            if not isinstance(cur, str) or not cur or cur in seen:
                break
            if cur in members:
                return f"parent:{cur}"
            seen.add(cur)
            cur = (_record(inspect, cur) or {}).get("ParentAgentId")
    except Exception:  # noqa: BLE001 - cannot read the chain: fall through to the label proof, which stands on its own evidence
        pass
    if ls_label is None:
        return ""
    try:  # canary (PR 907 review LOW-1): a Paseo that ignores the filter lists everything, so an unknown lead must list nothing
        if ls_label(f"ade.lead={uuid.uuid4()}") != []:
            return ""
    except Exception:  # noqa: BLE001
        return ""
    for lead in lineage:
        if not succ.UUID_RE.fullmatch(lead):  # never hand Paseo a label value that is not a full lowercase id
            continue
        try:
            rows = ls_label(f"ade.lead={lead}")
        except Exception:  # noqa: BLE001 - this lead's listing is unreadable: no evidence from it
            continue
        if any(isinstance(r, dict) and r.get("id") == ident for r in rows):
            return f"label:ade.lead={lead}"
    return ""


def decide(target: str, inspect, allow_archived: bool | str | None = False, state_dir: Path | None = None,
           home: Path | None = None, allow_replaced: str | None = None, sender: str | None = None, ls_label=None) -> Decision:
    """What to do about a send to `target` (an id, an id prefix or a name Paseo resolves). `sender` is the calling agent's full
    id (PASEO_AGENT_ID) and `ls_label(K=V)` lists the agents carrying a label: together they prove ownership of an archived
    worker (`owner_proof`)."""
    inspect = _cached(inspect)
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
        current = _follow(ident, inspect, state_dir, home)
    except succ.SuccessionError as exc:
        return Decision(REFUSE, target, f"{exc}: the succession ledger is inconsistent; ask the operator")
    if current != ident:
        try:
            successor = _record(inspect, current)
        except Exception:  # noqa: BLE001
            successor = None
        if successor is not None and successor.get("Archived") is True:
            return Decision(REFUSE, target, f"{ident} was replaced by {current}, which is archived too: nothing to send to")
        if allow_replaced == ident and record.get("Archived") is False:  # live: the send cannot un-archive it
            return Decision(PASS, target, f"{ident} was replaced by {current}, but {ALLOW_REPLACED_ENV} names it and it is live: "
                            "sent as asked", replaced_by=current)
        return Decision(REDIRECT, current, f"{ident} was replaced through a self-handoff (completed, or acknowledged and not yet "
                        f"archived); send to {current}")
    if record.get("Archived") is True and not (allow_archived is True or allow_archived == ident):
        proof = owner_proof(ident, sender, inspect, ls_label, state_dir, home)
        if proof:  # operator ruling 2026-11-21: a lead may un-archive its own archived worker without asking
            return Decision(PASS, target, f"{ident} is archived and is the sender's own worker ({proof}): resumed (logged)",
                            resumed="owner", proof=proof)
        return Decision(REFUSE, target, f"{ident} is archived and no completed handoff replaced it: a send would un-archive "
                        f"and run it. Your own archived worker (launched by you or a lead you replaced: its `ade.lead=<you>` label, or "
                        f"your session as its Paseo parent) is let through without asking anyone, and this one is not provably yours. "
                        f"Send to its live owner; resuming another agent's archived one needs the operator's explicit "
                        f"instruction ({ALLOW_ENV}=<its full id>, for that one send)")
    return Decision(PASS, target)


def _transport_env(env):
    """Merge os.environ with explicit caller env for daemon transport discovery (never used for security overrides)."""
    if env is None:
        return os.environ
    merged = dict(os.environ)
    merged.update(env)
    return merged


def paseo_inspect(paseo: str = "paseo", timeout: int = 5, env=None):
    """An `inspect` callable over Paseo's loopback daemon API (zero subprocesses by default), or `paseo agent inspect`
    when an explicit CLI binary path or `ADE_PASEO_TRANSPORT=cli` is requested. LookupError for a not-found agent."""
    tenv = _transport_env(env)
    use_cli = paseo_client.transport_mode(cli_override=paseo, env=tenv) == "cli"
    if not use_cli:
        client = paseo_client.PaseoClient(env=tenv, timeout=timeout)

        def inspect_daemon(ident: str) -> dict:
            try:
                return client.inspect_agent(ident, cli_shape=True)
            except paseo_client.AgentNotFoundError as exc:
                raise LookupError(ident) from exc
            except paseo_client.DaemonError as exc:
                raise OSError(f"paseo daemon inspect failed: {exc}") from exc

        return inspect_daemon

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


def paseo_ls_label(paseo: str = "paseo", timeout: int = 10, env=None):
    """An `ls_label` callable over Paseo's loopback daemon API (zero subprocesses by default) or
    `paseo ls -a -g --json --label K=V` when an explicit CLI binary or `ADE_PASEO_TRANSPORT=cli` is requested.
    Raises on any failure: a caller that cannot read the listing has no evidence (ownership fails closed)."""
    tenv = _transport_env(env)
    use_cli = paseo_client.transport_mode(cli_override=paseo, env=tenv) == "cli"
    if not use_cli:
        client = paseo_client.PaseoClient(env=tenv, timeout=timeout)

        def ls_label_daemon(label: str) -> list:
            if "=" not in label:
                raise ValueError("label must be K=V")
            key, value = label.split("=", 1)
            try:
                rows = client.list_agents(
                    include_background=True,
                    include_archived=True,
                    labels={key: value},
                    cli_rows=True,
                )
            except paseo_client.DaemonError as exc:
                raise OSError(f"paseo daemon ls failed: {exc}") from exc
            if not isinstance(rows, list):
                raise ValueError("paseo daemon did not return a list")
            return rows

        return ls_label_daemon

    def ls_label(label: str) -> list:
        proc = subprocess.run([paseo, "ls", "-a", "-g", "--json", "--label", label], capture_output=True, text=True,
                              timeout=timeout, check=False)
        if proc.returncode != 0:
            raise OSError(f"paseo ls exited {proc.returncode}")
        rows = json.loads(proc.stdout)
        if not isinstance(rows, list):
            raise ValueError("paseo ls did not return a list")
        return rows
    return ls_label


def _append_line(record: dict, log_path: Path | None) -> None:
    """One JSON line, appended atomically (O_APPEND, one write) to `log_path`, else $ADE_SEND_GUARD_LOG, else DEFAULT_LOG (directory
    0700, file 0600). Never raises and never blocks: a path that is a symlink, a FIFO or any non-regular file is not written
    (O_NOFOLLOW, O_NONBLOCK, fstat), and a failure is swallowed."""
    try:
        path = Path(log_path or os.environ.get(LOG_ENV) or Path.home() / DEFAULT_LOG)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        line = json.dumps({"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **record, "pid": os.getpid(),
                           "ppid": os.getppid(), "argv0": Path(sys.argv[0] if sys.argv and sys.argv[0] else "python").name})
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            if stat.S_ISREG(os.fstat(fd).st_mode):
                os.write(fd, (line + "\n").encode())
        finally:
            os.close(fd)
    except Exception:  # noqa: BLE001
        pass


def log_override(d: Decision, log_path: Path | None = None, source: str = "send") -> None:
    """Append one JSON line for a send that ADE_ALLOW_REPLACED_SEND let through (no message text). `source` is `send` at the point
    of sending (the shim, an in-repo sender) and `hook-precheck` for the Claude hook, which runs before the command and cannot
    know it was sent. Never raises and never blocks (see `_append_line`)."""
    _append_line({"override": ALLOW_REPLACED_ENV, "target": d.target, "successor": d.replaced_by, "source": source}, log_path)


def log_resume(d: Decision, sender: str = "", log_path: Path | None = None, source: str = "send") -> None:
    """Append one JSON line for a send that un-archives the sender's own worker: `override` is `owner`, with the `proof`.
    Fields: ts (UTC), sender, target, proof, source (no message text). `source` as in `log_override`. Never raises, never blocks."""
    _append_line({"override": "owner", "sender": sender or "", "target": d.target, "proof": d.proof, "source": source}, log_path)


def log_revive(
    target: str,
    *,
    sender: str = "",
    proof: str = "",
    reason: str = "",
    log_path: Path | None = None,
    source: str = "ade-revive",
) -> None:
    """Append one JSON line for a supported `ade-revive` un-archive (queue #97, 2026-11-24; no message text).
    Fields: ts (UTC), event="revive", target, sender, proof, reason, source, pid, ppid, argv0. Never raises, never blocks."""
    _append_line(
        {
            "event": "revive",
            "target": target,
            "sender": sender or "",
            "proof": proof or "",
            "reason": reason or "",
            "source": source,
        },
        log_path,
    )


def guard(target: str, paseo: str = "paseo", env=None, log_path: Path | None = None, source: str = "send", **kw) -> Decision:
    """`decide` over the real paseo CLI, honouring ADE_ALLOW_ARCHIVED_SEND, ADE_ALLOW_REPLACED_SEND and the sender's ownership
    (PASEO_AGENT_ID); a use of the replaced override and every resume of the sender's own archived worker is logged
    (`log_override`, `log_resume`)."""
    env = os.environ if env is None else env
    current_role = _coord().current_role
    CoordinationError = _coord().CoordinationError
    try:
        enrolled = current_role(target)
        if enrolled is not None:
            record = paseo_inspect(paseo, env=env)(enrolled)
            if record.get("Archived") is not False:
                return Decision(REFUSE, target, "enrolled owner is archived or unavailable")
            return Decision(REDIRECT if enrolled != target else PASS, enrolled, "authoritative stable role owner")
    except Exception:
        # A configured enrollment or role read error must never become legacy pass.
        return Decision(REFUSE, target, "enrolled authority unavailable; no local fallback")
    sender = (env.get(SENDER_ENV) or "").strip()
    d = decide(target, paseo_inspect(paseo, env=env), allow_archived=env.get(ALLOW_ENV) or False,
               allow_replaced=env.get(ALLOW_REPLACED_ENV) or None, sender=sender or None, ls_label=paseo_ls_label(paseo, env=env), **kw)
    if d.replaced_by:
        log_override(d, log_path, source)
    if d.resumed:
        log_resume(d, sender, log_path, source)
    return d


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
