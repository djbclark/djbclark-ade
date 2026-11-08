---
name: handoff
description: "OLD WAY compatibility alias: prefer paseo-handoff. Use only when explicitly invoked; the descriptive legacy name is old-handoff-use-paseo-handoff."
---

# handoff: old way; prefer paseo-handoff

For a fresh-agent task handoff, use Paseo's `paseo-handoff` skill. For an explicitly requested
ADE deep recovery record, this compatibility command preserves the old behavior:
read [the legacy skill](../old-handoff-use-paseo-handoff/SKILL.md), pass the arguments unchanged, and follow it.
Existing `/hand` and `/handoff` invocations keep their behavior; explain the preferred name once.

Before moving work between computers, read [old way versus new way](../../docs/old-way-new-way.md).
A local handoff path is not a transferred artifact.
