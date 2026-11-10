# A3/A4 native-routing proposal — 2026-11-10

Status: **authorized 2026-11-10; merged in tendcf#44/nix2cf#7**.
Available-agent substantive review completed with no findings under the
operator's 2026-11-10 environment exception; current merge/CI status is in
[the resume record](wave6-cloud-resume-2026-11-10.md#d-dependency-checkpoint).
Scope: only the active frontier-review instructions in each `AGENTS.md`,
in separate claimed worktrees and PRs. Preserve historical handoffs.

## A. Pinned source

| Project | Master commit | AGENTS.md blob |
|---|---|---|
| frdminc/tendcf | `069958d5c56e9a6331f20adc6f433c23e26faa98` | `41857d3241fcd4b3dfe7b33d204072bc3378214f` |
| frdminc/nix2cf | `bf2842eca8b905a0834d2b3e9854de49d4321ecb` | `dd60c05c517e4d5fa92d750e9b2730bf3cda5829` |

Default-branch and commit-pinned connector reads returned matching blobs.
ADE reference: `7589e329e4a43f5569e9e14c349cec812d99e24d`.
Re-fetch upstream before applying; re-review if the target block changed.
The shared stale block starts at tendcf line 28 / nix2cf line 35.

## B. Proposed replacements

### B1. Mechanics paragraph

Replace from “Every other repo keeps the default. The mechanics stay…”
(including `Every` on the preceding line in the originals) through
“to get around them” with:

> Every other repo keeps the default. The mechanics stay: frontier allowance,
> fresh quota readings, estimate floors and caps, headroom, per-wave limits
> and in-flight reservations are not overridden. Native routing is described
> in djbclark-ade's `skills/model-routing/SKILL.md`, sections D–E. Never
> override a route, lower headroom, change the estimate or omit admission
> checks to force a review. A printed native launch command or an
> `ade.kind=frontier` label is not proof of admission. If the current native
> path cannot preserve these checks, hold the review and report the missing check.

### B2. Reviewer command bullets

Replace the three old launcher command bullets with:

> 1. Astra: Codex provider, `gpt-6-astra`, `high`.
> 2. Fable: Claude provider, its current Fable frontier model, `high`.
> 3. Gemini 4 Argon: Antigravity provider, `gemini-4-argon`, `high`.
>    Argon is fallback-only when Astra or Fable is short. Require a fresh
>    reading for its Google AI Pro subscription pool; an API entitlement is
>    not a substitute.
>
> Plan each review with
> `~/src/djbclark-ade/bin/route_agent.py plan --kinds frontier --repo REPO --json`,
> replacing `REPO` with this project's name (`tendcf` or `nix2cf`). Keep the
> reviewer order and model-family independence above; a non-frontier model
> cannot satisfy this rule. Re-plan immediately before admission and launch.
> Record the reason `REPO standing rule: cross-model review` in the brief
> and admission evidence, substituting the actual project name.
>
> Use the current ADE review launch path after admission. Preserve the
> enforced `bin/review-launch` boundary when reviewing untrusted external
> input; do not replace it with an unrestricted invocation. Trusted own-agent
> work follows ADE's ordinary permission policy. For reviews relying on
> instructions rather than tool restrictions, direct the reviewer to change
> nothing and compare worktree status and diff before and after; do not claim
> that this is an enforced read-only sandbox.
>
> Native Paseo launches use the admitted provider/model and `--thinking high`,
> carry `ade.kind=frontier`, `ade.name`, `ade.lead` and `ade.task` labels,
> and use the explicit workspace and cwd verified under ADE's orchestration
> practices. Include the delivery footer in the positional brief. Do not
> translate retired launcher flags into unsupported native flags.

### B3. Availability and fit

Replace the old availability/dry-run material before “Astra's fallback
estimate…” with:

> A pool is short when a fresh quota reading marks it unusable, the intended
> reviewer does not fit every relevant window with the required headroom,
> or admission refuses it for concurrency, reservation or preflight reasons.
> Missing or stale readings do not establish availability. Move to the next
> eligible reviewer and report the reason; never force admission.
>
> Read `aiuse --available --json` first, `paseo usage ls --json` second, and
> inspect the fresh planner's structured result. A Paseo report whose status
> is not `available` is unknown. Planner output is not proof that a subsequent
> launch passed admission; native commands do not inherit the old dispatcher's
> exit-code or dry-run contract. Preserve admission and actual launch results.

Retain the detailed Astra 20-point fallback-floor/cap paragraph, replacing:

- “selected by the repository name from `-C`'s `origin` remote” with
  “selected explicitly with `plan --repo tendcf` or `plan --repo nix2cf`”.
- “Only the dry-run and the dispatch decide” with
  “Only fresh quota, fit and admission evidence establish availability”.

### B4. Limits and reservation gap

Replace item 4 with:

> 4. **Limits that still hold.** Preserve the effective frontier allowance
>    and per-wave caps from ADE's `config/gates.toml [frontier]`, estimate
>    floors/caps, headroom and in-flight reservation accounting. The 20-point
>    Astra estimate override is not a permanent minimum quota balance and
>    waives no other check. Fable remains advisory; execution or elevated
>    effort requires the operator approvals prescribed by ADE. No Fable
>    `xhigh`/`max` without djbclark's approval. At most one Astra slice at a time.
>
>    Native `route_agent.py plan` checks fit against the remaining reading
>    but does not subtract sibling in-flight reservations. Re-planning alone
>    does not restore that protection. Until native reservation admission is
>    verified, serialize launches only when one coordinator can establish
>    exclusive control of the pool, account for every existing consumer, and
>    retain the reservation through completion and refreshed usage
>    reconciliation. If that cannot be proven, hold the review; do not launch
>    unguarded or revive retired tools. Missing admission parity remains a
>    blocker to operational migration completion.

### B5. Retired adversary client and weekly Google check

Replace the sentence about the `/bigteam` adversary round using omp Opus with:

> The additional adversary round still runs where the current ADE workflow
> calls for it, using an eligible judgment route. It never counts as the
> cross-model frontier review and must not revive the retired omp client.

Replace item 5's old-command availability explanation with:

> 5. **Gemini 4 Carbon** (announced 2026-10-28, availability unverified here):
>    recheck weekly with `paseo provider models antigravity` and
>    `aiuse --available --json`. Adopt it as the Google frontier model only
>    after confirming the intended subscription pool, native routing and
>    admission checks.

Keep the lead restrictions, quality floor, design-review double requirement,
disagreement escalation, PR evidence requirements and handoff exceptions.

## C. Acceptance and remaining limitations

Review each resulting diff against its pinned original; no change outside the
named active block. Verify the resulting AGENTS.md no longer teaches the
retiring launchers; check the projects' applicable Markdown/instruction checks
and PR CI. An empty name probe is not proof of live admission parity.

This proposal intentionally holds frontier reviews when capacity cannot be
proven. It neither implements native reservations nor certifies a working Mac
launch path. Record actual migration evidence only after the approved changes
land, and keep operational limitations explicit. No C3 status, waive, Pi
acceptance or deletion approval is granted by this document.
