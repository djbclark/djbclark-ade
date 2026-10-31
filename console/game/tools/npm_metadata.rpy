## npm_metadata: parse npm's scalar and workspace-array version metadata without guessing.
## Port of the original bin/npm_metadata.py, an import-only module. Entry label: tool_npm_metadata.
##
## The original exposes parse_version_metadata(raw) and is imported by other tools, so the logic lives
## in init python as npm_parse_version_metadata(raw). The label is a thin driver: the first ade_argv
## entry is the raw `npm view ... --json` output, and the single exact version is printed on stdout.
## Exit 0 ok, 1 rejected metadata (ValueError), 2 usage.

init python:
    import json
    import re
    import sys

    NPM_VERSION_RE = r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?"

    def npm_parse_version_metadata(raw):
        """Return one exact version, rejecting ambiguous or malformed npm output."""
        value = json.loads(raw)
        versions = value if isinstance(value, list) else [value]
        if not versions or any(
            not isinstance(version, str) or re.fullmatch(NPM_VERSION_RE, version) is None
            for version in versions
        ):
            raise ValueError("npm metadata must contain exact version strings")
        if len(set(versions)) != 1:
            raise ValueError("npm metadata contains multiple distinct versions")
        return versions[0]

label tool_npm_metadata:
    python:
        if len(ade_argv) != 1:
            print("usage: npm_metadata RAW_JSON", file=sys.__stderr__)
            ade_exit_code = 2
        else:
            try:
                print(npm_parse_version_metadata(ade_argv[0]), file=sys.__stdout__)
                ade_exit_code = 0
            except ValueError as exc:
                print(f"npm_metadata: {exc}", file=sys.__stderr__)
                ade_exit_code = 1
        sys.__stdout__.flush()
        sys.__stderr__.flush()
    return
