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

A lead's other top-level workers (started with `env -u PASEO_AGENT_ID -u PASEO_AGENT_CWD -u PASEO_WORKSPACE_ID
paseo run …`, so they are not its descendants) carry `--label ade.lead=<lead agent id>`; without it
`bin/ade-auto-permit` skips their permission prompts. A successor lead labels its own workers with its own id
and runs the watcher with `--lead <its id>` (2026-11-13).

Placement differs: workers go in the lead's one `WORKERS <repo> (<work>)` window, and workers the operator asks for
interactively in the lead's own `MAIN <repo> (<work>)` window (`skills/fan-out` section 3, `docs/workspace-layout.md`), but a
**successor is a new lead, not a worker**: it starts top-level in its own placement (not in the predecessor's WORKERS window;
it names its own window `MAIN …` with `ade-worker-run rename-main`), then opens its own WORKERS window when it dispatches
(2026-11-13; window names carry no lead id).
