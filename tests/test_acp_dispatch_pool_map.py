"""map_agent_to_provider in bin/acp-dispatch: which aiuse window a slice is judged by.

2026-10-15: a `cursor --model default` slice was costed and headroom-checked on Cursor's
third-party window (11% left) although Auto, the pool `default` draws on, had 74%.
"""
import importlib.machinery
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_loader = importlib.machinery.SourceFileLoader("acp_dispatch_pool_map", str(ROOT / "bin" / "acp-dispatch"))
_spec = importlib.util.spec_from_loader("acp_dispatch_pool_map", _loader)
acpd = importlib.util.module_from_spec(_spec)
_loader.exec_module(acpd)


class CursorPoolsTest(unittest.TestCase):
    def test_default_is_the_auto_pool(self):
        self.assertEqual(acpd.map_agent_to_provider("cursor", "default"), ("cursor", "auto"))
        self.assertEqual(acpd.map_agent_to_provider("cursor", "auto"), ("cursor", "auto"))
        self.assertEqual(acpd.map_agent_to_provider("cursor", None), ("cursor", "auto"))

    def test_named_models_are_third_party(self):
        for model in ("claude-sonnet-5-5", "gpt-5.6-sol", "grok-4.7", "composer-2.5"):
            self.assertEqual(acpd.map_agent_to_provider("cursor", model), ("cursor", None), model)

    def test_router_resolves_auto_to_its_own_service(self):
        router = acpd.route_module()
        self.assertEqual(router.pool_service("cursor", "auto"), "cursor-auto")
        self.assertEqual(router.pool_service("cursor", None), "cursor")

    def test_other_agents_unchanged(self):
        self.assertEqual(acpd.map_agent_to_provider("claude", "fable"), ("claude", None))
        self.assertEqual(acpd.map_agent_to_provider("zcode", "GLM-5.3-Flash"), ("zai", None))
        self.assertIsNone(acpd.map_agent_to_provider("hermes", None))


if __name__ == "__main__":
    unittest.main()
