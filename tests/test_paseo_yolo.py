"""bin/paseo_yolo.py — unattended mode map for launches."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import paseo_yolo  # noqa: E402


def test_known_providers_map_to_unattended_modes():
    assert paseo_yolo.yolo_mode("claude") == "bypassPermissions"
    assert paseo_yolo.yolo_mode("claude/sonnet") == "bypassPermissions"
    assert paseo_yolo.yolo_mode("codex") == "full-access"
    assert paseo_yolo.yolo_mode("opencode") == "build"
    assert paseo_yolo.yolo_mode("omp") == "full"


def test_unknown_providers_have_no_invented_mode():
    assert paseo_yolo.yolo_mode("cursor") is None
    assert paseo_yolo.yolo_mode("pi") is None


def test_resolve_launch_mode_prefers_yolo_then_fallback():
    assert paseo_yolo.resolve_launch_mode("claude", fallback="auto") == "bypassPermissions"
    assert paseo_yolo.resolve_launch_mode("cursor", fallback="default") == "default"
    assert paseo_yolo.resolve_launch_mode("claude", requested="plan") == "plan"
    assert paseo_yolo.resolve_launch_mode("claude", requested="bypassPermissions") == "bypassPermissions"
