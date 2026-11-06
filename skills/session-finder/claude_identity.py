"""Stub for one cycle; removed in the follow-up PR, at the latest 2026-11-20: claude_identity.py moved to bin/ (docs/slim/PLAN.md E3)."""
import importlib.util, pathlib, sys  # noqa: E401  # not `from claude_identity import *`: on an old sys.path this file IS `claude_identity`
_spec = importlib.util.spec_from_file_location("claude_identity", pathlib.Path(__file__).resolve().parents[2] / "bin" / "claude_identity.py")
_mod = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_mod); sys.modules[__name__] = _mod  # noqa: E702
if __name__ == "__main__": _sid = _mod.owner_session_id(); print(_sid); raise SystemExit(0 if _sid else 1)  # noqa: E701,E702
