"""Private, read-only GitHub fork inventory projection; never promotion authority."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from ade_forks import load_policy

OWNERS = ("djbclark", "djbcsipb", "frdminc")
SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+\Z")
QUERY = """query($owner:String!,$cursor:String){
  rateLimit { remaining }
  repositoryOwner(login:$owner){login repositories(first:100,after:$cursor,
    isFork:true,ownerAffiliations:[OWNER],orderBy:{field:NAME,direction:ASC}){
    nodes{nameWithOwner url isPrivate isArchived parent{nameWithOwner url isPrivate}}
    pageInfo{hasNextPage endCursor}
  }}
}"""


class InventoryError(ValueError):
    """Invalid or incomplete inventory transport or persistence."""


def slug(value):
    if (not isinstance(value, str) or not SLUG.fullmatch(value)
            or value.split("/")[1] in {".", ".."}):
        raise InventoryError("invalid GitHub repository slug")
    return value


def repo_url(value):
    if not isinstance(value, str):
        raise InventoryError("invalid repository URL")
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise InventoryError("invalid repository URL") from error
    if (parsed.scheme != "https" or parsed.netloc != "github.com"
            or parsed.query or parsed.fragment):
        raise InventoryError("inventory requires canonical GitHub URLs")
    return slug(parsed.path.strip("/"))


def gh_json(args):
    try:
        result = subprocess.run(["gh", "api", *args], capture_output=True, text=True,
                                timeout=45, check=False)
        if result.returncode:
            # API errors can expose private names; keep stderr out of public logs.
            raise InventoryError("GitHub query failed")
        data = json.loads(result.stdout)
        if not isinstance(data, dict) or data.get("errors"):
            raise InventoryError("GitHub query returned errors")
        return data
    except (OSError, subprocess.TimeoutExpired, UnicodeError, json.JSONDecodeError) as error:
        raise InventoryError("GitHub query unavailable or malformed") from error


def discovered_row(node, owner):
    if not isinstance(node, dict) or not isinstance(node.get("parent"), dict):
        raise InventoryError("fork parent inaccessible")
    fork = slug(node.get("nameWithOwner"))
    parent = node["parent"]
    upstream = slug(parent.get("nameWithOwner"))
    if (fork.split("/")[0].lower() != owner.lower()
            or repo_url(node.get("url", "")) != fork
            or repo_url(parent.get("url", "")) != upstream
            or any(type(node.get(k)) is not bool for k in ("isPrivate", "isArchived"))
            or type(parent.get("isPrivate")) is not bool):
        raise InventoryError("invalid fork metadata")
    return {"id": "github-" + fork.lower().replace("/", "--"),
            "upstream_repo": upstream, "fork_repo": fork,
            "upstream": parent["url"], "fork": node["url"], "base_tag": None,
            "watch_releases": not node["isArchived"],
            "private": node["isPrivate"] or parent["isPrivate"], "catalog_ids": []}


def discover(owner, *, query=gh_json, max_pages=20, minimum_remaining=100):
    """Bounded pagination, with rate budget and inaccessible-parent failure."""
    if owner not in OWNERS:
        raise InventoryError("unknown maintained owner")
    preflight = query(["graphql", "-f", "query=query {rateLimit{remaining}}"])
    data = preflight.get("data")
    budget = data.get("rateLimit") if isinstance(data, dict) else None
    remaining = budget.get("remaining") if isinstance(budget, dict) else None
    if type(remaining) is not int or remaining < minimum_remaining:
        raise InventoryError("GitHub rate budget unavailable")
    rows, cursors, cursor = [], set(), None
    for _ in range(max_pages):
        args = ["graphql", "-f", "query=" + QUERY, "-f", "owner=" + owner]
        if cursor is not None:
            args.extend(["-f", "cursor=" + cursor])
        response = query(args)
        data = response.get("data")
        if not isinstance(data, dict):
            raise InventoryError("missing GraphQL result")
        budget = data.get("rateLimit")
        remaining = budget.get("remaining") if isinstance(budget, dict) else None
        if type(remaining) is not int or remaining < minimum_remaining:
            raise InventoryError("GitHub rate budget unavailable")
        actor = data.get("repositoryOwner")
        if (not isinstance(actor, dict) or not isinstance(actor.get("login"), str)
                or actor["login"].lower() != owner):
            raise InventoryError("owner inaccessible")
        connection = actor.get("repositories")
        if not isinstance(connection, dict) or not isinstance(connection.get("nodes"), list):
            raise InventoryError("fork connection inaccessible")
        rows.extend(discovered_row(node, owner) for node in connection["nodes"])
        info = connection.get("pageInfo")
        if not isinstance(info, dict) or type(info.get("hasNextPage")) is not bool:
            raise InventoryError("missing pagination evidence")
        if not info["hasNextPage"]:
            if len({r["fork_repo"].lower() for r in rows}) != len(rows):
                raise InventoryError("duplicate fork during pagination")
            return rows
        cursor = info.get("endCursor")
        if not isinstance(cursor, str) or not cursor or cursor in cursors:
            raise InventoryError("invalid or repeated pagination cursor")
        cursors.add(cursor)
    raise InventoryError("pagination budget exceeded")


def validate_snapshot(snapshot):
    if (not isinstance(snapshot, dict) or type(snapshot.get("schema_version")) is not int
            or snapshot["schema_version"] != 1 or not isinstance(snapshot.get("generated_at"), str)
            or not isinstance(snapshot.get("owners"), dict)
            or set(snapshot["owners"]) != set(OWNERS)
            or not isinstance(snapshot.get("components"), list)):
        raise InventoryError("invalid registry snapshot")
    try:
        timestamp = datetime.fromisoformat(snapshot["generated_at"].replace("Z", "+00:00"))
        if timestamp.utcoffset() is None:
            raise ValueError()
    except ValueError as error:
        raise InventoryError("invalid registry timestamp") from error
    for owner in snapshot["owners"].values():
        if not isinstance(owner, dict) or type(owner.get("complete")) is not bool:
            raise InventoryError("invalid owner coverage")
    ids, forks = set(), set()
    for row in snapshot["components"]:
        if not isinstance(row, dict):
            raise InventoryError("invalid component")
        fork, upstream = slug(row.get("fork_repo")), slug(row.get("upstream_repo"))
        identifier = row.get("id")
        if (not isinstance(identifier, str) or not identifier or identifier in ids
                or fork.lower() in forks or fork.split("/")[0].lower() not in OWNERS
                or repo_url(row.get("fork", "")) != fork
                or repo_url(row.get("upstream", "")) != upstream
                or type(row.get("watch_releases")) is not bool
                or type(row.get("private")) is not bool
                or (row.get("base_tag") is not None and not isinstance(row["base_tag"], str))
                or not isinstance(row.get("catalog_ids"), list)
                or any(not isinstance(v, str) or not v for v in row["catalog_ids"])):
            raise InventoryError("invalid or duplicate component")
        ids.add(identifier)
        forks.add(fork.lower())
    return snapshot


def project(policy, previous=None, *, discover_owner=discover, now=None):
    if previous is not None:
        validate_snapshot(previous)
    rows, coverage = {}, {}
    generated = now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for owner in OWNERS:
        try:
            found = discover_owner(owner)
            # Validate even injected/custom transport results before trusting coverage.
            probe = {"schema_version": 1, "generated_at": generated,
                     "owners": {o: {"complete": True} for o in OWNERS}, "components": found}
            validate_snapshot(probe)
            if any(r["fork_repo"].split("/")[0].lower() != owner for r in found):
                raise InventoryError("foreign owner in discovery")
            coverage[owner] = {"complete": True, "scope": "credential-visible", "error": None}
        except InventoryError as error:
            found = [r for r in (previous or {}).get("components", [])
                     if r["fork_repo"].split("/")[0].lower() == owner]
            coverage[owner] = {"complete": False, "scope": "credential-visible",
                               "error": str(error)}
        rows.update((r["fork_repo"].lower(), dict(r)) for r in found)
    for row in policy:
        fork, upstream = repo_url(row["fork"]), repo_url(row["upstream"])
        if fork.split("/")[0].lower() not in OWNERS:
            raise InventoryError("curated fork outside maintained owners")
        key = fork.lower()
        existing = rows.get(key)
        if existing and existing["upstream_repo"].lower() != upstream.lower():
            raise InventoryError("curated/discovered parent mismatch")
        merged = existing or {"base_tag": None, "watch_releases": fork.lower() != upstream.lower(),
                              "private": False}
        merged.update(id=row["id"], fork_repo=fork, upstream_repo=upstream,
                      fork=row["fork"], upstream=row["upstream"], catalog_ids=row["catalog_ids"])
        rows[key] = merged
    return validate_snapshot({"schema_version": 1, "generated_at": generated,
                              "owners": coverage, "components": sorted(rows.values(), key=lambda r: r["fork_repo"].lower())})


def private_directory(path):
    """Reject links and foreign/writable ancestors; create private missing parents."""
    for parent in [*reversed(path.parents), path]:
        if not parent.exists():
            parent.mkdir(mode=0o700)
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0, os.getuid()}
                or (info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX))):
            raise InventoryError("unsafe registry directory")
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise InventoryError("registry directory must be owner-private")


def read_snapshot(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise InventoryError("cannot open previous registry") from error
    try:
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_size > 16 * 1024 * 1024):
                raise InventoryError("unsafe previous registry")
            return validate_snapshot(json.load(stream))
    except (OSError, UnicodeError, ValueError) as error:
        raise InventoryError("invalid previous registry") from error


def refresh(path, policy, *, discover_owner=discover):
    try:
        private_directory(path.parent)
        lock = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except OSError as error:
        raise InventoryError("registry directory or lock unavailable") from error
    try:
        info = os.fstat(lock)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise InventoryError("unsafe registry lock")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        snapshot = project(policy, read_snapshot(path), discover_owner=discover_owner)
        fd, name = tempfile.mkstemp(prefix=".registry-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(snapshot, stream, ensure_ascii=False, sort_keys=True, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return snapshot
    except OSError as error:
        raise InventoryError("registry persistence unavailable") from error
    finally:
        os.close(lock)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path.home() / ".local/state/djbclark-ade/forks/registry.json")
    args = parser.parse_args(argv)
    try:
        result = refresh(args.output.absolute(), load_policy())
        # Never echo private repository names or raw API errors.
        print(json.dumps({"schema_version": 1, "components": len(result["components"]),
                          "owners": {o: r["complete"] for o, r in result["owners"].items()},
                          "promotion_authority": False}))
        return 0 if all(r["complete"] for r in result["owners"].values()) else 1
    except ValueError:
        print("fork inventory: refresh held (policy, registry, coverage or filesystem invalid)")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
