"""Real npm scalar/workspace shapes must retain the latest-release guard."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "npm_metadata", Path(__file__).resolve().parents[1] / "bin/npm_metadata.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('"3.0.74"', "3.0.74"),
        ('["3.0.74"]', "3.0.74"),
        ('["3.0.74", "3.0.74"]', "3.0.74"),
        ('"3.1.0-beta.2+build.1"', "3.1.0-beta.2+build.1"),
    ],
)
def test_one_version(raw, expected):
    assert MODULE.parse_version_metadata(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        '["3.0.74","3.0.75"]',
        "null",
        "{}",
        "true",
        "74",
        '["3.0.74",null]',
        '"latest"',
        '"3.0.74\\n"',
        "not json",
    ],
)
def test_unknown_or_ambiguous_version_fails_closed(raw):
    with pytest.raises(ValueError):
        MODULE.parse_version_metadata(raw)
