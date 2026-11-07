"""A copy of config/routing.toml with the protective floors the 2026-11-02 run-out-of-quota ruling removed put back (plenty_min 50,
the codex and antigravity-claude estimate floors, the tendcf/nix2cf astra override, no per-service min_headroom).

The floor MECHANISMS (the plenty gate, estimate floors, repo overrides, the headroom minimum) are still code, and their tests pin
numbers; they run against this fixture through ROUTING_POLICY instead of the live policy, which no longer sets those floors."""
from __future__ import annotations

import re
from pathlib import Path

LIVE = Path(__file__).resolve().parent.parent / "config" / "routing.toml"

OLD_FLOORS = (
    ("plenty_min = 0.0", "plenty_min = 50.0"),
    ('"codex:frontier" = 0.0', '"codex:frontier" = 60.0'),
    ('"codex:judgment" = 0.0', '"codex:judgment" = 25.0'),
    ("\ncodex = 0.0\n", "\ncodex = 10.0\n"),
    ("\nantigravity-claude = 0.0\n", "\nantigravity-claude = 15.0\n"),
)
REPO_OVERRIDES = '''
[dispatch.repo_overrides.tendcf.estimate_floor]
"codex:frontier" = 20.0

[dispatch.repo_overrides.nix2cf.estimate_floor]
"codex:frontier" = 20.0
'''


def old_floors_text() -> str:
    text = LIVE.read_text()
    for new, old in OLD_FLOORS:
        assert new in text, f"routing.toml no longer contains {new!r}"
        text = text.replace(new, old, 1)
    text = re.sub(r"(?m)^min_headroom = 0\.0\n", "", text)
    marker = "\n# The orchestrating (lead) session's own model"
    assert marker in text
    return text.replace(marker, REPO_OVERRIDES + marker, 1)


def write_old_floors(directory: Path) -> Path:
    path = Path(directory) / "routing-old-floors.toml"
    path.write_text(old_floors_text())
    return path


_installed: dict[str, object] = {}


def install() -> None:
    """Module fixture (`setUpModule`): point ROUTING_POLICY at the old-floors copy for this process and its subprocesses, and reload
    route_agent from it. Pair with `uninstall()` in `tearDownModule`."""
    import os
    import sys
    import tempfile

    sys.path.insert(0, str(LIVE.parent.parent / "bin"))
    import route_agent

    tmp = tempfile.TemporaryDirectory(prefix="old-floors-")
    _installed.update(tmp=tmp, env=os.environ.get("ROUTING_POLICY"))
    os.environ["ROUTING_POLICY"] = str(write_old_floors(Path(tmp.name)))
    route_agent.reload_policy()


def uninstall() -> None:
    import os
    import route_agent

    prior = _installed.pop("env", None)
    if prior is None:
        os.environ.pop("ROUTING_POLICY", None)
    else:
        os.environ["ROUTING_POLICY"] = str(prior)
    route_agent.reload_policy()
    tmp = _installed.pop("tmp", None)
    if tmp is not None:
        tmp.cleanup()
