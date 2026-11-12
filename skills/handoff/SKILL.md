---
name: handoff
description: "OLD WAY compatibility alias: use acknowledged self-handoff for a fresh agent. Preserves existing ADE recovery flows and explicit handoff requests; descriptive name: old-handoff-use-paseo-handoff."
---

# handoff: old way; acknowledged self-handoff

This is a compatibility entry point for the existing ADE recovery protocol.
Read [the legacy skill](../old-handoff-use-paseo-handoff/SKILL.md), pass all arguments unchanged, and follow it
from its first step. Existing operator invocations and automatic ADE recovery callbacks keep
their recovery records. References elsewhere to `handoff` steps mean the numbered steps in that linked
canonical protocol, including handoff Step 9. This entry point adds no extra actions or questions.

Whole-session replacement follows handoff Step 9 and the ADE self-session protocol.
Before moving work between computers, read [old way versus new way](../../docs/old-way-new-way.md).
A local handoff path is not a transferred artifact.

For a whole-session handoff, Step 9 defaults to `~/src/djbclark-ade/bin/ade-self-session
handoff --checkpoint ABSOLUTE_BRIEF --quiesced` and the
[acknowledged successor protocol](../../docs/self-session.md#c-self-handoff-to-a-new-session).
If the helper refuses before creation, launch the top-level successor yourself
with the documented unattended fallback. Verify its acknowledgement and idle-only
retirement; operator typing is never the fallback. Partial transfers keep the
predecessor running, as specified by Step 9.
