# Non-independent source review

A1. This is static code/skill research, not end-to-end testing. Inspected unit tests establish that tests exist for isolated classification/chain/serialization/summary behavior, not that fleet migration works. No local builds/tests or live provider-switch actions were run.

A2. Nuance retained: Continuity does pass a creation idempotency key and durable lineage labels; it is wrong to say it has no duplicate protection. Those primitives do not establish transactionally durable source retirement or account-level concurrent admission.

A3. Nuance retained: keeping an old agent alive may protect live resources; it is not inherently a defect in a manual converter. It does require an external ownership policy before unattended task continuation.

A4. Collision with installed Auto Resume is explicitly inferred from code paths, not reproduced. Installed enablement is observed, but provider-specific settings/reservations were not dumped or changed. Risk is conditional on an eligible old agent and an enabled matching scheduled continuation.

A5. Native conversion is not described as arbitrary live-runtime reattachment; completed tool states in the OpenCode writer are not treated as execution receipts. No claim of txcript-wide fidelity or dependency security is made.

A6. No broad absence claim: no plugin-bundled SKILL.md was found in enumerated source trees and a scoped search found no matching ADE/Pi skill. Existing generic/ADE handoff skills have different lifecycle assumptions; the brief asks Astra to reconcile them with current public APIs, not bypass either.

A7. Installation decision is deliberately conservative and within the user's conditional grant: leave switch-provider useful/enabled, leave Continuity absent until ownership/scheduler coordination is designed. No separate permission is invented to disable other plugins.
