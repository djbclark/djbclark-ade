---
name: handoff
description: "Deprecated alias for /paseo-handoff (task handoff to a fresh subagent). For whole-session ADE replacement (ade-self-session), use /self-handoff."
---

# handoff (deprecated alias for `/paseo-handoff`)

Deprecated alias (2026-11-24): load and follow the installed `paseo-handoff` skill verbatim, passing all arguments unchanged.
Do not add extra actions or questions; `paseo-handoff` spawns a fresh child subagent with a self-contained task briefing.

If the caller actually wants a whole-session ADE lead/session replacement (`bin/ade-self-session`, Tier 1/Tier 2 recovery records, acknowledged successor and predecessor retirement), use `/self-handoff` ([`../self-handoff/SKILL.md`](../self-handoff/SKILL.md)) instead.

If a lead was already replaced by hand outside `ade-self-session finish`, record the completed succession link so `ade_lead_succession`, `ade_send_guard`, `supervisor/lead`, and `bin/ade-lead-of <REPO>` stay in sync:

```bash
~/src/djbclark-ade/bin/ade-self-session link --predecessor <OLD_UUID> --successor <NEW_UUID> --operator-attested [--repo <REPO>]
```
