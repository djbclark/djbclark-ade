"""Parse npm's scalar and workspace-array version metadata without guessing."""

import json
import re


def parse_version_metadata(raw: str) -> str:
    """Return one exact version, rejecting ambiguous or malformed npm output."""
    value = json.loads(raw)
    versions = value if isinstance(value, list) else [value]
    if not versions or any(
        not isinstance(version, str)
        or re.fullmatch(
            r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", version
        )
        is None
        for version in versions
    ):
        raise ValueError("npm metadata must contain exact version strings")
    if len(set(versions)) != 1:
        raise ValueError("npm metadata contains multiple distinct versions")
    return versions[0]
