"""Native Git fork integration. Trusted callers supply specs and policy authority.

The shipped CLI has no mutation grant. Candidate input never supplies authority.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Protocol

from ade_forks import load_policy


class Held(ValueError):
    """Operation safely stopped; workspace diagnostics remain intact."""


@dataclass(frozen=True)
class SyncSpec:
    component: str
    fork: str
    upstream: str
    base_ref: str = "refs/heads/main"
    channel: str = "stable"
    strategy: str = "merge"


@dataclass(frozen=True)
class Plan:
    spec: SyncSpec
    base: str
    upstream_ref: str
    upstream_object: str
    upstream_commit: str
    branch: str


class Authority(Protocol):
    def permits(self, spec: SyncSpec, operation: str) -> bool:
        """Re-read trusted enrollment and operation policy, never candidate data."""


class DenyPolicy:
    def permits(self, spec: SyncSpec, operation: str) -> bool:
        return False


class Runner:
    def __call__(self, argv: list[str], cwd: Path | None = None):
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_MERGE_AUTOEDIT="no")
        return subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                              text=True, timeout=120, shell=False, check=False)


class Sync:
    def __init__(self, runner=None, authority=None):
        self.runner = runner or Runner()
        self.authority = authority or DenyPolicy()

    def run(self, argv, cwd=None, allowed=(0,)):
        r = self.runner(argv, cwd)
        if (not isinstance(r, subprocess.CompletedProcess) or type(r.returncode) is not int
                or not isinstance(r.stdout, str) or not isinstance(r.stderr, str)):
            raise Held("malformed_runner_output")
        if r.returncode not in allowed:
            raise Held("command_failed:" + argv[0])
        return r

    def git(self, workspace, *args):
        return self.run(["git", *args], workspace).stdout.strip()

    def sha(self, value):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
            raise Held("invalid_commit_identity")
        return value

    def validate(self, spec):
        if not isinstance(spec, SyncSpec):
            raise Held("invalid_spec")
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", spec.component):
            raise Held("invalid_component")
        for url in (spec.fork, spec.upstream):
            if not re.fullmatch(r"https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", url):
                raise Held("invalid_repository_identity")
        if spec.fork.lower() == spec.upstream.lower():
            raise Held("upstream_publication_forbidden")
        self.ref(spec.base_ref)
        if not spec.base_ref.startswith("refs/heads/"):
            raise Held("invalid_base_ref")

    def ref(self, ref):
        if not isinstance(ref, str) or not ref.startswith("refs/"):
            raise Held("invalid_ref")
        self.run(["git", "check-ref-format", ref])
        return ref

    def remote(self, url, ref):
        self.ref(ref)
        out = self.run(["git", "ls-remote", "--", url, ref, ref + "^{}"]).stdout
        rows = {}
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) != 2 or parts[1] in rows or parts[1] not in (ref, ref + "^{}"):
                raise Held("malformed_remote_output")
            rows[parts[1]] = self.sha(parts[0])
        if ref not in rows:
            raise Held("missing_ref")
        return rows[ref], rows.get(ref + "^{}", rows[ref])

    def discover(self, spec):
        self.validate(spec)
        if spec.strategy != "merge":
            raise Held("owner_managed_adapter_required")
        if spec.channel == "stable":
            r = self.run(["gh", "api", "repos/" + spec.upstream.split("github.com/")[1] + "/releases/latest"])
            try:
                release = json.loads(r.stdout)
                if (release.get("draft") is not False or release.get("prerelease") is not False
                        or not isinstance(release.get("tag_name"), str)):
                    raise Held("stable_release_unavailable")
                ref = "refs/tags/" + release["tag_name"]
            except (ValueError, AttributeError) as exc:
                raise Held("stable_release_unavailable") from exc
        elif spec.channel.startswith("branch:"):
            ref = "refs/heads/" + spec.channel.removeprefix("branch:")
        else:
            raise Held("unsupported_channel")
        base = self.remote(spec.fork, spec.base_ref)[1]
        obj, commit = self.remote(spec.upstream, ref)
        key = hashlib.sha256((base + obj + commit).encode()).hexdigest()[:24]
        return Plan(spec, base, ref, obj, commit, f"ade-sync/{spec.component}/{key}")

    def unchanged(self, plan):
        if self.remote(plan.spec.fork, plan.spec.base_ref)[1] != plan.base:
            raise Held("fork_base_changed")
        if self.remote(plan.spec.upstream, plan.upstream_ref) != (plan.upstream_object, plan.upstream_commit):
            raise Held("upstream_ref_changed")

    def prs(self, spec):
        raw = self.run(["gh", "pr", "list", "--repo", spec.fork, "--state", "open",
                        "--limit", "1000", "--json", "url,headRefName,headRefOid,baseRefName"]).stdout
        try:
            rows = json.loads(raw)
            if not isinstance(rows, list) or len(rows) >= 1000:
                raise Held("ambiguous_pr_inventory")
            for row in rows:
                if (not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in
                        ("url", "headRefName", "headRefOid", "baseRefName"))):
                    raise Held("malformed_pr_output")
                self.sha(row["headRefOid"])
            return rows
        except (ValueError, TypeError) as exc:
            raise Held("malformed_pr_output") from exc

    def apply(self, plan, workspace, publication_remote, *, unattended=False):
        """Caller exclusively owns workspace; lock serializes this API's retries.

        Trusted authority must bind the complete spec, exact operation and caller.
        No candidate file, CLI flag or receipt is accepted as authority.
        """
        self.validate(plan.spec)
        for operation in ("stage", "publish", "pull-request"):
            if self.authority.permits(plan.spec, operation) is not True:
                raise Held("policy_authority_unavailable:" + operation)
        if unattended and self.authority.permits(plan.spec, "app-token-ci") is not True:
            raise Held("github_app_token_required")
        if plan.spec.strategy != "merge":
            raise Held("owner_managed_adapter_required")
        if publication_remote != plan.spec.fork:
            raise Held("wrong_publication_remote")
        workspace = Path(workspace).resolve()
        lock = workspace.parent / (workspace.name + ".fork-sync.lock")
        # Keep one inode permanently: unlinking permits concurrent owners of
        # different inodes at the same pathname. Kernel releases flock on death.
        fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise Held("workspace_locked") from exc
            return self._apply(plan, workspace, unattended=unattended)
        finally:
            os.close(fd)

    def mutation_authority(self, spec, operation, unattended):
        if self.authority.permits(spec, operation) is not True:
            raise Held("policy_authority_unavailable:" + operation)
        if unattended and self.authority.permits(spec, "app-token-ci") is not True:
            raise Held("github_app_token_required")

    def _apply(self, p, w, *, unattended=False):
        s = p.spec
        if self.git(w, "status", "--porcelain", "--untracked-files=all"):
            raise Held("dirty_workspace")
        if self.git(w, "rev-parse", "--is-shallow-repository") != "false":
            raise Held("complete_ancestry_required")
        self.unchanged(p)
        self.sha(p.base); self.sha(p.upstream_commit); self.sha(p.upstream_object)
        expected = "ade-sync/" + s.component + "/" + hashlib.sha256(
            (p.base + p.upstream_object + p.upstream_commit).encode()).hexdigest()[:24]
        if p.branch != expected:
            raise Held("invalid_candidate_branch")
        rows = self.prs(s)
        # Conservative: all open PRs to this integration base are exclusive.
        active = [r for r in rows if r["baseRefName"] == s.base_ref.removeprefix("refs/heads/")]
        if any(r["headRefName"] != p.branch for r in active) or len(active) > 1:
            raise Held("unrelated_active_pr")
        existing = self.run(["git", "ls-remote", "--", s.fork, "refs/heads/" + p.branch]).stdout.strip()
        if existing:
            parts = existing.split("\t")
            if len(parts) != 2 or parts[1] != "refs/heads/" + p.branch:
                raise Held("malformed_candidate_ref")
            head = self.sha(parts[0])
            self.git(w, "fetch", "--no-tags", "--", s.fork, "refs/heads/" + p.branch)
            if self.git(w, "rev-parse", "FETCH_HEAD") != head:
                raise Held("candidate_changed")
            # Require our exact two-parent merge, never trust a branch name alone.
            parents = self.git(w, "show", "-s", "--format=%P", head).split()
            if parents != [p.base, p.upstream_commit]:
                raise Held("candidate_identity_mismatch")
        else:
            if active:
                raise Held("missing_candidate_branch")
            current = self.sha(self.git(w, "rev-parse", "HEAD"))
            branch_result = self.run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
                                     w, allowed=(0, 1))
            local_branch = branch_result.stdout.strip()
            if branch_result.returncode == 1:
                if local_branch or branch_result.stderr.strip():
                    raise Held("unexpected_symbolic_ref_result")
                local_branch = None  # clean exact-commit CI/task checkout
            elif not local_branch:
                raise Held("unexpected_symbolic_ref_result")
            if local_branch == p.branch:
                if self.git(w, "show", "-s", "--format=%P", current).split() != [p.base, p.upstream_commit]:
                    raise Held("candidate_identity_mismatch")
                head = current
            else:
                if current != p.base:
                    raise Held("workspace_base_mismatch")
                self.git(w, "fetch", "--no-tags", "--", s.upstream, p.upstream_ref)
                if self.git(w, "rev-parse", "FETCH_HEAD^{commit}") != p.upstream_commit:
                    raise Held("upstream_ref_changed")
                self.git(w, "switch", "-c", p.branch)
                result = self.run(["git", "-c", "core.hooksPath=/dev/null", "merge", "--no-ff", "--no-edit",
                                   "-m", "Integrate exact upstream candidate", p.upstream_commit], w, allowed=(0, 1))
                if result.returncode:
                    # MERGE_HEAD, index stages, worktree and Git messages survive.
                    (w.parent / (w.name + ".fork-sync-conflict.txt")).write_text(result.stdout + result.stderr)
                    raise Held("merge_conflict_diagnostics_retained")
                head = self.sha(self.git(w, "rev-parse", "HEAD"))
                if self.git(w, "show", "-s", "--format=%P", head).split() != [p.base, p.upstream_commit]:
                    raise Held("no_new_integration")
            self.unchanged(p)
            self.mutation_authority(s, "publish", unattended)
            # Normal Git push only; no force or default-branch refspec.
            self.git(w, "push", "--no-follow-tags", "--recurse-submodules=no",
                     s.fork, head + ":refs/heads/" + p.branch)
        self.unchanged(p)
        if active:
            if active[0]["headRefOid"] != head:
                raise Held("pr_head_changed")
            url = active[0]["url"]
        else:
            self.mutation_authority(s, "pull-request", unattended)
            url = self.run(["gh", "pr", "create", "--repo", s.fork,
                "--head", p.branch, "--base", s.base_ref.removeprefix("refs/heads/"),
                "--title", "Integrate upstream for " + s.component,
                "--body", f"Base: {p.base}\nUpstream: {p.upstream_commit}\nCandidate: {head}\n"
                "Qualification pending for this exact head. Normal CI and required review must pass. "
                "No adversary verdict supplied; obtain review before merge."]).stdout.strip()
        if not re.fullmatch(re.escape(s.fork) + r"/pull/[0-9]+", url):
            raise Held("malformed_pr_url")
        return {"status": "pr_pending", "head": head, "base": p.base,
                "upstream": p.upstream_commit, "pr": url, "qualified": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "apply"))
    parser.add_argument("--id", required=True)
    args = parser.parse_args(argv)
    try:
        rows = load_policy()  # fixed module-relative trusted path
        row = next((r for r in rows if r["id"] == args.id), None)
        if row is None:
            raise Held("component_not_enrolled")
        if args.command == "apply":
            raise Held("policy_authority_unavailable:foundation_has_no_operation_grants")
        # The registry has no base-ref authority yet; inspect GitHub's default.
        sync = Sync()
        raw = sync.run(["gh", "api", "repos/" + row["fork"].split("github.com/")[1]]).stdout
        repo = json.loads(raw)
        spec = SyncSpec(row["id"], row["fork"], row["upstream"],
                        "refs/heads/" + repo["default_branch"], row["channel"], row["strategy"])
        print(json.dumps({"status": "planned", "authorized": False, "plan": asdict(sync.discover(spec))}))
        return 0
    except (Held, ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "held", "reason": str(exc), "authorized": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
