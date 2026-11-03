"""Offline draft planning and explicit runtime refusals. No live action imports."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .planning import build_plan, validate_plan
from .storage import Store, read_input


def parser():
    p = argparse.ArgumentParser(description="Draft safe fleet migration plans. Live execution is not admitted.")
    p.add_argument("--state-dir", type=Path, default=Path.home() / ".local/state/ade/fleet-migrate")
    subs = p.add_subparsers(dest="command", required=True)
    plan = subs.add_parser("plan", help="Read metadata inventory and write a private draft; never launch or notify.")
    plan.add_argument("--from-tui", required=True)
    plan.add_argument("--from-vendor")
    plan.add_argument("--to-tui", required=True)
    plan.add_argument("--to-vendor", required=True)
    plan.add_argument("--include-herdr", action="store_true")
    plan.add_argument("--inventory", type=Path, help="Exported normalized v1 metadata (offline evidence, not runtime authority).")
    plan.add_argument("--output", required=True, type=Path, help="Private plan path; parent must be 0700 (created if absent).")
    validate = subs.add_parser("validate", help="Validate digest and deterministic draft policy; not runtime readiness.")
    validate.add_argument("plan", type=Path)
    validate.add_argument("--json", action="store_true")
    apply = subs.add_parser("apply", help="Verify approval digest; persist BLOCKED without any live action.")
    apply.add_argument("plan", type=Path)
    apply.add_argument("--approved-digest", required=True)
    status = subs.add_parser("status", help="Read a private local run record.")
    status.add_argument("run")
    status.add_argument("--json", action="store_true")
    reconcile = subs.add_parser("reconcile", help="Inspect a blocked run; no external changes supported.")
    reconcile.add_argument("run")
    mode = reconcile.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    reconcile.add_argument("--approved-digest")
    notify = subs.add_parser("notify", help="Refuse notification when no ownership epoch was committed.")
    notify.add_argument("run")
    notify.add_argument("--retry-due", required=True, action="store_true")
    return p


def _emit(value):
    print(json.dumps(value, sort_keys=True))


def _valid(p):
    errors = validate_plan(p)
    if errors:
        raise ValueError("invalid-plan:" + ",".join(errors))


def _summary(p):
    return {"schema_version": 1, "digest": p["digest"], "execution_authorized": False,
            **{k: len(p[k]) for k in ("selected", "excluded", "unresolved", "recipients", "unresolved_recipients")},
            "runtime_blockers": p["runtime_blockers"]}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "plan":
            if args.inventory is None:
                _emit({"state": "BLOCKED", "reason": "authoritative-live-inventory-adapter-not-admitted",
                       "next": "Supply an offline normalized v1 --inventory; see docs/fleet-migrate.md."})
                return 4
            p = build_plan(read_input(args.inventory), from_tui=args.from_tui, from_vendor=args.from_vendor,
                           to_tui=args.to_tui, to_vendor=args.to_vendor, include_herdr=args.include_herdr)
            output = args.output.absolute()
            with Store(output.parent, create=True) as s, s.lock():
                # A draft cannot silently overwrite an approved artifact or other work.
                try:
                    s.read(output.name)
                except FileNotFoundError:
                    pass
                else:
                    raise ValueError("output-already-exists")
                s.write(output.name, p)
            _emit(_summary(p))
            return 0
        if args.command == "validate":
            p = read_input(args.plan)
            _valid(p)
            _emit({**_summary(p), "draft_valid": True, "runtime_ready": False})
            return 0
        if args.command == "apply":
            p = read_input(args.plan)
            _valid(p)
            if args.approved_digest != p["digest"]:
                raise ValueError("approval-digest-mismatch")
            # Approval binds a fixed artifact/selection, never a new provider-wide query.
            run_id = "run-" + p["digest"]
            with Store(args.state_dir.absolute(), create=True) as s, s.lock():
                name = run_id + ".json"
                try:
                    run = s.read(name)
                    _check_run(run)
                    if run.get("plan_digest") != p["digest"]:
                        raise ValueError("run-identity-conflict")
                except FileNotFoundError:
                    run = {"schema_version": 1, "run_id": run_id, "plan_digest": p["digest"],
                           "state": "BLOCKED", "ownership_committed": False,
                           "communication_converged": False, "blockers": p["runtime_blockers"],
                           "selected_ids": [{"host": r["source"]["host"], "id": r["source"]["id"]} for r in p["selected"]],
                           "journal": [{"action": "apply", "result": "BLOCKED", "external_actions": 0}]}
                    s.write(name, run)
            _emit(run)
            return 4
        with Store(args.state_dir.absolute()) as s:
            run = s.read(Store._name(args.run) + ".json")
        _check_run(run)
        if args.command == "reconcile" and args.apply and args.approved_digest != run.get("plan_digest"):
            raise ValueError("approval-digest-mismatch")
        if args.command == "notify":
            _emit({"state": "BLOCKED", "reason": "no-committed-ownership-epoch", "messages_sent": 0})
            return 4
        _emit(run)
        return 0 if args.command == "status" or args.dry_run else 4
    except (ValueError, OSError, TypeError, KeyError, RecursionError) as error:
        # Internal code-only ValueErrors are actionable. Never echo untrusted
        # paths, titles, checkpoints, JSON or OS diagnostics (including filenames).
        reason = str(error) if isinstance(error, ValueError) else "unsafe-artifact-or-invalid-schema"
        if not re.fullmatch(r"[a-z][a-z0-9:,-]{0,200}", reason):
            reason = "invalid-or-unsafe-artifact-or-approval"
        _emit({"state": "REFUSED", "reason": reason})
        return 2


def _check_run(run):
    if (not isinstance(run, dict) or run.get("schema_version") != 1 or
            run.get("state") != "BLOCKED" or run.get("ownership_committed") is not False or
            run.get("communication_converged") is not False):
        raise ValueError("unsupported-run-record")


if __name__ == "__main__":
    sys.exit(main())
