"""skills/dialogue on Paseo (slim-down E6, 2026-11-06, the one-hour port of R2-16): an `acp` or `paseo` route runs
`paseo run --no-wait --json` and `paseo wait`, and the turn text is the reply file the pointer prompt names. Against the
fake `paseo` in tests/fakes/ (no daemon)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIALOGUE = ROOT / "skills" / "dialogue" / "scripts" / "dialogue.py"


def world(tmp_path: Path, routes: list[dict], **env: str) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    run = tmp_path / "run"
    run.mkdir()
    (run / "dialogue.json").write_text(json.dumps({"order": ["grok"], "models": {"grok": {"routes": routes}}}))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "paseo").symlink_to(ROOT / "tests" / "fakes" / "paseo")
    e = {k: v for k, v in os.environ.items() if not k.startswith(("FAKE_", "DIALOGUE_"))}
    e.update({"PATH": f"{bindir}{os.pathsep}{e.get('PATH', '')}", "FAKE_PASEO_STATE": str(tmp_path / "st"),
              "FAKE_PASEO_AGENT": "reply", "FAKE_PASEO_REPLY": "OK", **env})
    r = subprocess.run([sys.executable, str(DIALOGUE), "--run", str(run), "probe"], capture_output=True, text=True,
                       env=e, timeout=60, check=False)
    calls = tmp_path / "st" / "calls.jsonl"
    return r, [json.loads(x) for x in calls.read_text().splitlines()] if calls.exists() else []


def test_an_acp_route_runs_on_paseo_and_reads_the_reply_file(tmp_path):
    r, calls = world(tmp_path, [{"kind": "acp", "agent": "grok", "model": "grok-4.7", "set": ["reasoning_effort=high"]}])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ok" in r.stdout
    run = next(c for c in calls if c[0] == "run")
    assert run[run.index("--provider") + 1] == "grok/grok-4.7"
    assert run[run.index("--mode") + 1] == "default"                     # the provider's defaultMode
    assert run[run.index("--thinking") + 1] == "high"
    assert "--no-wait" in run and "--json" in run and "--prompt-file" not in run
    assert "probe.prompt.md" in run[-1] and "probe.prompt.reply.md" in run[-1]
    wait = next(c for c in calls if c[0] == "wait")
    assert wait[wait.index("--timeout") + 1] == "300"


def test_a_non_idle_wait_or_a_missing_reply_fails_the_route(tmp_path):
    r, _ = world(tmp_path, [{"kind": "paseo", "provider": "codex", "model": "gpt-6.1-sol", "mode": "auto"}],
                 FAKE_PASEO_WAIT="permission")
    assert r.returncode == 1 and "FAIL" in r.stdout and "permission" in r.stdout
    other = tmp_path / "again"
    other.mkdir()
    r, _ = world(other, [{"kind": "paseo", "provider": "codex", "model": "gpt-6.1-sol"}], FAKE_PASEO_AGENT="nothing")
    assert r.returncode == 1 and "without writing" in r.stdout
