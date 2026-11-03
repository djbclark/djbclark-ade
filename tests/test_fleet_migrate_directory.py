"""Offline identity/receipt protocol. No real relay calls or notifications."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "libexec"))
from fleet_migrate.directory import (empty_directory, commit_ready, resolve, directory_digest,
                                     update_recipients, notification, receipt, convergence)


def identity(name, incarnation="session-1"):
    return {"host": "host", "id": name, "native_id": name + "-native", "incarnation": incarnation}


def ready(name):
    return {"identity": identity(name), "workspace_id": "safe", "tui": "pi", "vendor": "openai",
            "model": "openai/gpt-6-astra", "thinking": "high", "billing_pool": "codex-api",
            "ready_receipt": "verified-runtime-receipt", "fence_receipt": "verified-source-fence"}


def directory():
    return commit_ready(empty_directory(), task="task", source=identity("a"), destination=ready("b"),
                        expected_generation=0, commit_receipt="coordinator-commit")


def test_only_ready_successors_are_committed_at_expected_generation():
    d = directory()
    assert d["epoch"] == 1
    assert resolve(d, identity("a")) == identity("b")
    dest = ready("c")
    dest["ready_receipt"] = None
    with pytest.raises(ValueError):
        commit_ready(d, task="task", source=identity("b"), destination=dest,
                     expected_generation=1, commit_receipt="commit")
    with pytest.raises(ValueError):
        commit_ready(d, task="task", source=identity("b"), destination=ready("c"),
                     expected_generation=0, commit_receipt="commit")


def test_a_b_c_routes_to_c_but_preserves_history_and_inspection():
    d = directory()
    d2 = commit_ready(d, task="task", source=identity("b"), destination=ready("c"),
                      expected_generation=1, commit_receipt="commit-2")
    assert resolve(d2, identity("a")) == identity("c")
    assert resolve(d2, identity("b")) == identity("c")
    assert resolve(d2, identity("a"), purpose="history") == identity("a")
    assert len(d2["lineage"]) == 2
    assert resolve(d, identity("a")) == identity("b")  # old snapshot immutable


def test_reused_instance_id_and_cycle_cannot_reactivate_history():
    d = directory()
    with pytest.raises(ValueError):
        commit_ready(d, task="task", source=identity("b"), destination=ready("a"),
                     expected_generation=1, commit_receipt="commit-2")
    bad = {**d, "lineage": d["lineage"] + [{"old": identity("b"), "new": identity("a"), "epoch": 2}]}
    with pytest.raises(ValueError):
        resolve(bad, identity("a"))
    assert resolve(d, identity("a", "reused-other-session")) == identity("a", "reused-other-session")


def test_full_fleet_union_includes_dann_hermes_child_and_newcomers():
    d = directory()
    peers = [identity(n) for n in ("dann", "hermes", "child", "unmigrated")]
    ledger = update_recipients({}, d, peers[:2])
    ledger = update_recipients(ledger, d, peers[2:] + [identity("new")])
    assert len(ledger) == 5
    for peer in peers:
        msg = notification(d, peer)
        assert len(msg["mappings"]) == 1
        assert msg["directory_digest"] == directory_digest(d)
        assert msg["kind"] == "identity-update"


def test_transport_delivery_is_not_application_and_acks_bind_authenticated_identity():
    d = directory()
    peer = identity("dann")
    ledger = update_recipients({}, d, [peer])
    msg = notification(d, peer)
    ledger = receipt(ledger, d, peer, update_id=msg["update_id"], epoch=1,
                     digest=directory_digest(d), kind="delivered", authenticated_caller=None)
    assert convergence(ledger)["delivered"] == 1
    assert convergence(ledger)["applied"] == 0
    with pytest.raises(ValueError):
        receipt(ledger, d, peer, update_id=msg["update_id"], epoch=1,
                digest=directory_digest(d), kind="applied", authenticated_caller=identity("forger"))
    ledger = receipt(ledger, d, peer, update_id=msg["update_id"], epoch=1,
                     digest=directory_digest(d), kind="applied", authenticated_caller=peer)
    assert convergence(ledger)["applied"] == 1


def test_new_incarnation_does_not_inherit_old_application_ack():
    d = directory()
    old = identity("peer")
    ledger = update_recipients({}, d, [old])
    msg = notification(d, old)
    ledger = receipt(ledger, d, old, update_id=msg["update_id"], epoch=1,
                     digest=directory_digest(d), kind="applied", authenticated_caller=old)
    ledger = update_recipients(ledger, d, [identity("peer", "new-session")])
    assert convergence(ledger)["applied"] == 0
    assert convergence(ledger)["historical_recipients"] == 1
    assert convergence(ledger)["pending"] == 1


def test_duplicate_receipts_do_not_loop_or_erase_uncertainty():
    d = directory()
    p = identity("peer")
    ledger = update_recipients({}, d, [p])
    m = notification(d, p)
    args = dict(update_id=m["update_id"], epoch=1, digest=directory_digest(d),
                kind="accepted", authenticated_caller=None)
    ledger = receipt(ledger, d, p, **args)
    assert receipt(ledger, d, p, **args) == ledger
    assert convergence(ledger)["pending"] == 1
    assert convergence(ledger)["delivered"] == 0
    with pytest.raises(ValueError):
        receipt(ledger, d, p, **{**args, "kind": "ack-of-ack"})


def test_stale_epoch_ack_cannot_cover_new_directory():
    d = directory()
    p = identity("peer")
    ledger = update_recipients({}, d, [p])
    m = notification(d, p)
    d2 = commit_ready(d, task="task", source=identity("b"), destination=ready("c"),
                      expected_generation=1, commit_receipt="commit-2")
    ledger = update_recipients(ledger, d2, [p])
    with pytest.raises(ValueError):
        receipt(ledger, d2, p, update_id=m["update_id"], epoch=1, digest=directory_digest(d),
                kind="applied", authenticated_caller=p)
