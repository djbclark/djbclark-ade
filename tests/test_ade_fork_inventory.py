"""Coverage and privacy failures must preserve known inventory, not certify it."""
import copy
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import ade_fork_inventory as inv


def node(name="demo", owner="djbclark", private=False, archived=False):
    return {"nameWithOwner": f"{owner}/{name}", "url": f"https://github.com/{owner}/{name}",
            "isPrivate": private, "isArchived": archived,
            "parent": {"nameWithOwner": f"upstream/{name}",
                       "url": f"https://github.com/upstream/{name}", "isPrivate": private}}


def page(nodes, more=False, cursor=None):
    return {"data": {"rateLimit": {"remaining": 1000}, "repositoryOwner": {
        "login": "djbclark", "repositories": {"nodes": nodes,
            "pageInfo": {"hasNextPage": more, "endCursor": cursor}}}}}


def transport(*pages):
    responses = iter([{"data": {"rateLimit": {"remaining": 1000}}}, *pages])
    calls = []
    def query(args):
        calls.append(args)
        return next(responses)
    return query, calls


def test_private_paginated_and_archived_forks_are_preserved():
    query, calls = transport(page([node(private=True)], True, "next"),
                             page([node("retired", archived=True)]))
    rows = inv.discover("djbclark", query=query)
    assert rows[0]["private"] is True and rows[0]["watch_releases"] is True
    assert rows[1]["watch_releases"] is False
    assert "cursor=next" in calls[2]
    assert all("ownerAffiliations:[OWNER]" in x for x in [inv.QUERY])


@pytest.mark.parametrize("pages", [
    [page([node()], True, None)],
    [page([node()], True, "x"), page([node("second")], True, "x")],
    [page([node()], True, "x"), page([node()])],
    [page([{**node(), "parent": None}])],
    [page([{**node(), "isPrivate": 1}])],
    [{"data": {"rateLimit": {"remaining": 99}, "repositoryOwner": None}}],
    [{"data": {"rateLimit": {"remaining": 1000}, "repositoryOwner": None}}],
])
def test_incomplete_discovery_never_returns_partial_rows(pages):
    query, _ = transport(*pages)
    with pytest.raises(inv.InventoryError):
        inv.discover("djbclark", query=query)


def test_preflight_and_page_cap_stop_before_unbounded_queries():
    calls = []
    def exhausted(args):
        calls.append(args)
        return {"data": {"rateLimit": {"remaining": 10}}}
    with pytest.raises(inv.InventoryError):
        inv.discover("djbclark", query=exhausted)
    assert len(calls) == 1
    query, calls = transport(page([], True, "x"))
    with pytest.raises(inv.InventoryError):
        inv.discover("djbclark", query=query, max_pages=1)
    assert len(calls) == 2


def curated():
    return [{"id": "demo", "fork": "https://github.com/djbclark/demo",
             "upstream": "https://github.com/upstream/demo", "catalog_ids": ["demo"]}]


def discovery(owner):
    return [inv.discovered_row(node(owner=owner, private=True), owner)]


def test_curated_merge_preserves_private_status_and_suppresses_self_release_watch():
    policy = curated() + [{"id": "ade-plugins", "fork": "https://github.com/djbclark/ade",
                           "upstream": "https://github.com/djbclark/ade", "catalog_ids": []}]
    snapshot = inv.project(policy, discover_owner=discovery)
    rows = {r["id"]: r for r in snapshot["components"]}
    assert rows["demo"]["private"] is True
    assert rows["demo"]["catalog_ids"] == ["demo"]
    assert rows["ade-plugins"]["watch_releases"] is False
    assert all(o["complete"] for o in snapshot["owners"].values())


def test_failed_owner_retains_every_previous_row_without_claiming_completeness():
    previous = inv.project(curated(), discover_owner=discovery)
    def failing(owner):
        if owner == "djbclark":
            raise inv.InventoryError("owner inaccessible")
        return []
    current = inv.project(curated(), previous, discover_owner=failing)
    assert current["owners"]["djbclark"]["complete"] is False
    assert current["owners"]["frdminc"]["complete"] is True
    assert current["components"] == [r for r in previous["components"]
                                     if r["fork_repo"].startswith("djbclark/")]


def test_parent_mismatch_holds_instead_of_rewriting_upstream():
    policy = curated()
    policy[0]["upstream"] = "https://github.com/other/demo"
    with pytest.raises(inv.InventoryError):
        inv.project(policy, discover_owner=discovery)


def test_foreign_discovery_is_incomplete_not_complete():
    snapshot = inv.project([], discover_owner=lambda owner: discovery("djbclark"))
    assert snapshot["owners"]["djbclark"]["complete"] is True
    assert snapshot["owners"]["frdminc"]["complete"] is False


@pytest.mark.parametrize("mutation", [
    lambda s: s.update(schema_version=True),
    lambda s: s["owners"].pop("frdminc"),
    lambda s: s["owners"]["frdminc"].update(complete=1),
    lambda s: s["components"].append(copy.deepcopy(s["components"][0])),
    lambda s: s["components"][0].update(watch_releases="true"),
    lambda s: s["components"][0].update(fork_repo="../x"),
    lambda s: s["components"][0].update(fork="https://github.com.evil/djbclark/demo"),
])
def test_malformed_previous_snapshot_is_never_a_baseline(mutation):
    snapshot = inv.project(curated(), discover_owner=discovery)
    mutation(snapshot)
    with pytest.raises(inv.InventoryError):
        inv.project(curated(), snapshot, discover_owner=discovery)


def test_atomic_private_projection_and_no_private_names_in_cli_output(tmp_path, capsys, monkeypatch):
    directory = tmp_path / "private"
    path = directory / "registry.json"
    snapshot = inv.refresh(path, curated(), discover_owner=discovery)
    assert path.stat().st_mode & 0o777 == 0o600
    assert directory.stat().st_mode & 0o777 == 0o700
    assert json.loads(path.read_text()) == snapshot
    monkeypatch.setattr(inv, "load_policy", lambda: curated())
    monkeypatch.setattr(inv, "refresh", lambda *a: snapshot)
    assert inv.main(["--output", str(path)]) == 0
    output = capsys.readouterr().out
    assert "djbclark/demo" not in output and '"promotion_authority": false' in output


def test_invalid_previous_and_symlink_targets_do_not_get_overwritten(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    path = directory / "registry.json"
    path.write_text("broken")
    path.chmod(0o600)
    with pytest.raises(inv.InventoryError):
        inv.refresh(path, curated(), discover_owner=discovery)
    assert path.read_text() == "broken"
    path.unlink()
    target = directory / "target"
    target.write_text("keep")
    path.symlink_to(target)
    with pytest.raises(inv.InventoryError):
        inv.refresh(path, curated(), discover_owner=discovery)
    assert target.read_text() == "keep"


def test_failed_final_write_preserves_previous_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "private" / "registry.json"
    inv.refresh(path, curated(), discover_owner=discovery)
    before = path.read_bytes()
    monkeypatch.setattr(inv.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("full")))
    with pytest.raises(inv.InventoryError):
        inv.refresh(path, curated(), discover_owner=lambda owner: [])
    assert path.read_bytes() == before
    assert not list(path.parent.glob(".registry-*"))
