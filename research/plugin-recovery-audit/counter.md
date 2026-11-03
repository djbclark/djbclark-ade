# Counter-evidence

A1. Against 'neither plugin implements best practices': Continuity implements external failure detection, idempotency keys, chain metadata, cooldowns and in-process guards; switch-provider implements native-history conversion and deterministic compacted context with transcript references. The report credits each.

A2. Against 'Continuity is enough for fleet handoff': core state is explicitly memory-only; creation is followed by success display, not source retirement/target acceptance/peer/job ownership transfer. Existing Auto Resume can independently continue the old instance.

A3. Against 'keep full history': both code/documentation show bounded/cut or transformed content. Session conversion does not restore process handles or child runtime ownership.

A4. Against 'disable switch-provider': it is useful for deliberate manual conversion and leaves the original runtime intact. Wrap it in a safe procedure instead of treating a purpose-limited tool as useless.

A5. Against 'the existing handoff skills solve it': richer ADE guidance helps peer expectations but documents refusal cases for unavailable/non-Claude owners. Current parentage/detach semantics must be verified. A future skill must admit unsupported recovery states.
