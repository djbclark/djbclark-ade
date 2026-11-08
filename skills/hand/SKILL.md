---
name: hand
description: "OLD WAY compatibility alias: prefer paseo-handoff for a fresh agent. Preserves existing ADE recovery flows and explicit hand requests; descriptive name: old-hand-use-paseo-handoff."
---

# hand: old way; prefer paseo-handoff

This is a compatibility entry point for the existing ADE recovery protocol.
Read [the legacy skill](../old-hand-use-paseo-handoff/SKILL.md), pass all arguments unchanged, and follow it
from its first step. Existing operator invocations and automatic ADE recovery callbacks keep
their behavior. References elsewhere to `hand` steps mean the numbered steps in that linked
canonical protocol, including handoff Step 9. This entry point adds no extra actions or questions.

For a new task briefing, the preferred skill is Paseo's `paseo-handoff`.
Before moving work between computers, read [old way versus new way](../../docs/old-way-new-way.md).
A local handoff path is not a transferred artifact.
