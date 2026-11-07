#!/usr/bin/env python3
"""Print live fallback layers and fail on known-bad shapes.

Exit 0 only when every checked layer is linear, consecutive hops use different
vendors, an enabled MoA default preset exists when MoA is on, and
ai-model-switch cannot write the Hermes chain. Prints provider, model, and
host only. Does not print secrets.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

HOME = Path.home()
HERMES_CONFIG = HOME / ".hermes/config.yaml"
JOBS = HOME / ".hermes/cron/jobs.json"
LITELLM = HOME / ".litellm/config.yaml"
SWITCH = HOME / ".hermes/scripts/ai-model-switch.py"


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    return data if isinstance(data, dict) else {}


def _host(url: str) -> str:
    if not url:
        return ""
    return urlparse(url).hostname or ""


def _litellm_vendor(model: str, host: str) -> str:
    model = model or ""
    if model.startswith("clinepass/"):
        return "clinepass"
    if model.startswith("gemini/"):
        return "gemini"
    if "grok" in model:
        return "xai-oauth"
    if host == "opencode.ai":
        return "opencode-go"
    if model.startswith("openai/") and host == "opencode.ai":
        return "opencode-go"
    return host or model.split("/", 1)[0] or "unknown"


def _one_cycle(graph: dict[str, list[str]]) -> list[str]:
    color: dict[str, int] = {}
    example: list[str] = []

    def walk(node: str, stack: list[str]) -> bool:
        color[node] = 1
        stack.append(node)
        for nxt in graph.get(node, []):
            if color.get(nxt, 0) == 1:
                example.extend(stack[stack.index(nxt):] + [nxt])
                return True
            if color.get(nxt, 0) == 0 and walk(nxt, stack):
                return True
        stack.pop()
        color[node] = 2
        return False

    for node in list(graph):
        if color.get(node, 0) == 0 and walk(node, []):
            return example
    return []


def _same_vendor_pairs(hops: list[tuple[str, str]]) -> list[str]:
    bad = []
    for (v1, n1), (v2, n2) in zip(hops, hops[1:]):
        if v1 and v1 == v2:
            bad.append(f"{v1}/{n1} -> {v2}/{n2}")
    return bad


def _launchd_loaded(label: str) -> bool:
    try:
        out = subprocess.run(
            ["launchctl", "list"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return any(line.split()[-1:] == [label] for line in out.splitlines())


def _switch_refuses() -> bool:
    text = SWITCH.read_text() if SWITCH.exists() else ""
    return "refuses to write" in text and "os.replace" not in text.split("def write_config", 1)[-1].split("def main", 1)[0]


def main() -> int:
    violations: list[str] = []
    hermes = _load_yaml(HERMES_CONFIG)
    model = hermes.get("model") or {}
    primary = (str(model.get("provider") or ""), str(model.get("default") or ""))
    fallbacks = [
        (str(item.get("provider") or ""), str(item.get("model") or ""))
        for item in hermes.get("fallback_providers") or []
        if isinstance(item, dict)
    ]
    hermes_hops = [primary, *fallbacks]
    print("a. Hermes interactive")
    for i, (vendor, name) in enumerate(hermes_hops):
        label = "primary" if i == 0 else f"fallback {i}"
        print(f"  {label}: {vendor} / {name}")
    for pair in _same_vendor_pairs(hermes_hops):
        violations.append(f"hermes same-vendor pair: {pair}")
    seen = set()
    for vendor, name in hermes_hops:
        key = (vendor, name)
        if key in seen:
            violations.append(f"hermes cycle: {vendor} / {name}")
        seen.add(key)

    jobs_doc = json.loads(JOBS.read_text())
    raw_jobs = jobs_doc.get("jobs") if isinstance(jobs_doc, dict) else jobs_doc
    jobs = [job for job in raw_jobs if isinstance(job, dict)] if isinstance(raw_jobs, list) else []
    script_pins = [
        job.get("name")
        for job in jobs
        if job.get("no_agent") and (job.get("model") or job.get("provider"))
    ]
    agent_pins = [
        f"{job.get('name')}: {job.get('provider')} / {job.get('model')}"
        for job in jobs
        if not job.get("no_agent") and (job.get("model") or job.get("provider"))
    ]
    print("b. Cron pins that still name a model")
    print(f"  no_agent with a model id: {len(script_pins)}")
    for name in agent_pins:
        print(f"  agent: {name}")
    if script_pins:
        violations.append(f"no_agent jobs still store a model pin: {len(script_pins)}")

    moa_raw = hermes.get("moa")
    moa: dict[str, Any] = moa_raw if isinstance(moa_raw, dict) else {}
    presets_raw = moa.get("presets")
    presets: dict[str, Any] = presets_raw if isinstance(presets_raw, dict) else {}
    enabled_presets = [
        name
        for name, preset in presets.items()
        if isinstance(preset, dict) and preset.get("enabled", True) is not False
    ]
    moa_on = primary[0] == "moa" or bool(enabled_presets) or moa.get("enabled") is True
    default_preset = str(moa.get("default_preset") or "")
    print("c. MoA")
    print(f"  provider is moa: {primary[0] == 'moa'}")
    print(f"  enabled presets: {enabled_presets or 'none'}")
    print(f"  default_preset: {default_preset or '(empty)'} exists={default_preset in presets}")
    if moa_on and default_preset not in presets:
        violations.append(f"MoA is on and default_preset {default_preset!r} does not exist")

    litellm = _load_yaml(LITELLM)
    aliases: dict[str, tuple[str, str]] = {}
    for item in litellm.get("model_list") or []:
        if not isinstance(item, dict):
            continue
        params = item.get("litellm_params") or {}
        name = str(item.get("model_name") or "")
        model_id = str(params.get("model") or "")
        aliases[name] = (_litellm_vendor(model_id, _host(str(params.get("api_base") or ""))), model_id)
    graph: dict[str, list[str]] = {}
    print("d. LiteLLM fallbacks")
    router = litellm.get("router_settings")
    fallback_entries = router.get("fallbacks") if isinstance(router, dict) else None
    for entry in fallback_entries or []:
        if not isinstance(entry, dict) or len(entry) != 1:
            continue
        alias, hops = next(iter(entry.items()))
        hop_names = [str(h) for h in hops or []]
        graph[str(alias)] = hop_names
        print(f"  {alias} -> {', '.join(hop_names)}")
        resolved = [aliases.get(h, ("unknown", h)) for h in hop_names]
        for pair in _same_vendor_pairs(resolved):
            violations.append(f"litellm same-vendor pair: {pair}")
    cycle = _one_cycle(graph)
    if cycle:
        violations.append("litellm cycle: " + " -> ".join(cycle))

    loaded = _launchd_loaded("com.djbclark.ai-model-switch")
    refuses = _switch_refuses()
    print("f. Second writer")
    print(f"  ai-model-switch loaded: {loaded}")
    print(f"  write_config refuses: {refuses}")
    if loaded:
        violations.append("ai-model-switch is loaded in launchd")
    if not refuses:
        violations.append("ai-model-switch write_config can still write the Hermes chain")

    print("g. Violations")
    unique: list[str] = []
    for item in violations:
        if item not in unique:
            unique.append(item)
    if not unique:
        print("  none")
        return 0
    for i, item in enumerate(unique, 1):
        print(f"  {i}. {item}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
