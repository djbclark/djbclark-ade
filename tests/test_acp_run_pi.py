"""Pi's ACP registration and fail-closed permission contract, without live credentials."""
import ast
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools/acp-run/acp-run"


def test_pi_registry_uses_external_rpc_bridge():
    tree = ast.parse(SCRIPT.read_text())
    table = next(node.value for node in tree.body
                 if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "AGENTS" for t in node.targets))
    entry = next(value for key, value in zip(table.keys, table.values)
                 if isinstance(key, ast.Constant) and key.value == "pi")
    assert ast.literal_eval(entry) == (["pi-acp"], None)


def test_pi_refuses_unverified_deny_and_read_only_modes():
    tree = ast.parse(SCRIPT.read_text())
    denied = next(node.value for node in tree.body
                  if isinstance(node, ast.Assign)
                  and any(isinstance(t, ast.Subscript)
                          and isinstance(t.value, ast.Name) and t.value.id == "DENY_UNSUPPORTED"
                          and isinstance(t.slice, ast.Constant) and t.slice.value == "pi"
                          for t in node.targets))
    assert "without ACP permission requests" in ast.literal_eval(denied)
    readonly = next(node.value for node in tree.body
                    if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "READONLY_AGENTS" for t in node.targets))
    assert "pi" not in ast.literal_eval(readonly)
