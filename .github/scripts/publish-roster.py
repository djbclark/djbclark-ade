#!/usr/bin/env python3
"""Publish a standalone roster from trusted master to generated-roster (2026-11-12).

Run only in the master-only Roster workflow. Git plumbing leaves the checkout and
master ref unchanged; the sole remote write is refs/heads/generated-roster.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys


def publish(root: Path) -> str:
    def git(*args: str, data: str | None = None) -> str:
        result = subprocess.run(
            ["git", "-C", str(root), *args], input=data, capture_output=True,
            text=True, check=True, timeout=120,
            env={**os.environ, "GIT_AUTHOR_NAME": "github-actions[bot]",
                 "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
                 "GIT_COMMITTER_NAME": "github-actions[bot]",
                 "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com"},
        )
        return result.stdout.strip()

    source = git("rev-parse", "HEAD")
    url = "https://github.com/djbclark/djbclark-ade"
    roster = subprocess.run(
        [sys.executable, str(root / "bin" / "ade-roster"), "--root", str(root),
         "--link-prefix", f"{url}/blob/{source}/"],
        capture_output=True, text=True, check=True, timeout=60,
    ).stdout
    document = f"# Skill and tool roster\n\nSource: [{source}]({url}/commit/{source})\n\n{roster}"
    blob = git("hash-object", "-w", "--stdin", data=document)
    tree = git("mktree", data=f"100644 blob {blob}\tROSTER.md\n")
    commit = git("commit-tree", tree, data=f"Publish roster for {source}\n")
    git("push", "--force", "origin", f"{commit}:refs/heads/generated-roster")
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    print(f"Published roster for {publish(args.root.resolve())}")


if __name__ == "__main__":
    main()
