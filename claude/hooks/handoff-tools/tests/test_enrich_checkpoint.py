"""enrich_checkpoint.py's summarizer must be unable to act on the transcript."""
import sys
from pathlib import Path

import anyio

TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from enrich_checkpoint import build_options, deny_all_tools  # noqa: E402


def test_no_tools_settings_or_mcp_are_loaded():
    opts = build_options()
    assert opts.tools == []
    assert opts.allowed_tools == []
    assert opts.setting_sources == []
    assert opts.strict_mcp_config is True
    assert opts.permission_mode == "default"
    assert opts.max_turns == 1


def test_any_tool_request_is_denied():
    result = anyio.run(deny_all_tools, "Bash", {"command": "touch x"}, None)
    assert result.behavior == "deny"
