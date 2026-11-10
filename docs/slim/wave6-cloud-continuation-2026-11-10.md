# Wave 6 cloud continuation — 2026-11-10

## A. Scope and verified source progress

This continues the earlier `wave6-cloud-resume-2026-11-10.md` checkpoint;
that file remains a record of its earlier stopping point. Work focuses on
ADE, with outside changes limited to its specific dependencies. Available
capable agents substitute for unavailable named models under the operator's
explicit exception; review, CI, admission and approval gates remain.

All six dependency source PRs have now merged:

| Dependency | PR | Merge commit |
|---|---|---|
| tendcf A3 | https://github.com/frdminc/tendcf/pull/44 | `3f93d28d36363fb9b0c63d2281e12dd0e82cd294` |
| nix2cf A4 | https://github.com/frdminc/nix2cf/pull/7 | `572b0b705278bf54e53769820a91b8c20413e144` |
| CFEngine instructions A5 | https://github.com/djbclark/cfengine-all/pull/1 | `134c9afb3aea11a00b72750562a935934101406a` |
| aiuse A6 | https://github.com/djbclark/aiuse/pull/54 | `d9cb058c1cf0c4344af41fe35dab96848a14102f` |
| Home instructions A7 | https://github.com/djbclark/site-djbclark/pull/250 | `3dcbd4b09dc153c5f4d6b715e1d33fa9f81369db` |
| fleet-watch X1 | https://github.com/djbclark/site-djbclark/pull/251 | `3eff9ac231512e39edf6cbc0526ce16009f4eea6` |

Site CI passed for both source heads. Aiuse's tests, Semgrep, Cursor approval
and security checks completed successfully before merging. Local review and
validation details remain in the prior checkpoint. ADE checkpoint PR #538
merged as `0c8c31cb9310cf0cd191cbf137a13ee2dd7c330d` after required checks
and owner-trust adversary status passed. No invented APPROVE marker was used.

## B. Additional ADE implementation

- [#540](https://github.com/djbclark/djbclark-ade/pull/540), head
  `31a6c6e4cd80a5e51a7be5c16b9fe1e1aa22a684`: component-scoped doctor,
  including `just doctor hermes`. 82 focused tests pass; separate read-only
  review found no actionable issues. Full CI remains to be checked.
- [#541](https://github.com/djbclark/djbclark-ade/pull/541), head
  `b131be1becb41c3c2f4a0c1d6a071d8db0baa026`: runtime routing adopts the
  effective configuration with final shape validation; explicit legacy
  readers stay isolated. 515 tests and 51 subtests pass, one test skipped.
  Independent review and full CI remain to be checked.

Tests used mocks and temporary homes; no live configuration, provider probes,
quota policy, Pi pool acceptance or installed Mac state changed. Named-model
substitution is not evidence of live account quota; this host has no usable
quota snapshot, and actual account token consumption is unknown.

## C. What still needs the Mac or a decision

Merged source does not establish installed C3 state. Deploy/verify the source
migrations on the Mac, verify fleet delivery and reconcile pending receipts
without replaying accepted/unknown sends, drain B2 after Mac work ends, and
capture fresh evidence. Preserve the previously granted C1+C2 snippets in the
live proofs. The earlier evidence archive is absent on this cloud host.

The [retained-history proposal](c3-retained-history-proposal-2026-11-10.md)
is still only a proposal: no additional CFEngine or aiuse waiver is granted.
Keep historical handoffs, passive accounting and logs. Keep `relay.py`,
`acp-dispatch`, `acp-run` and `review-launch`; no `--allow-early` and no held
Pi pool acceptance. Deletion requires real evidence gate exit 0, the
2026-11-20 date gate and explicit operator confirmation.

The whole implementation plan is not complete. These cloud tasks address
specific unfinished setup-plan work; broader live pilots, service acceptance
and operator policy decisions remain. Do not report a Mac-only stopping point
while cloud implementation/review is still pending.

## D. Vendor-neutral continuation prompt

```text
Resume djbclark/djbclark-ade from docs/slim/wave6-cloud-continuation-2026-11-10.md.
Read AGENTS.md, queue Carried 1, the previous cloud checkpoint and Wave 6
follow-up. Dependency source PRs listed here are merged; verify actual remote
heads before acting. Finish ADE #540/#541 review and exact-head CI, then merge
only with required gates satisfied. No fabricated approval marker.
ADE is the focus; other repositories only for specific ADE dependencies.
The retained-history waiver proposal remains pending unless the operator has
explicitly answered. Source merges do not prove installed Mac state. Next Mac
work is deployment/verification, fleet receipts, B2 drain and fresh capture;
include granted C1+C2 proof snippets. Preserve history, logs and passive readers.
Keep shims/review-launch and held Pi pools false. No early deletion; require
real evidence gate exit 0 and explicit operator confirmation. Use claimed
worktrees, commit/push coherent work and record validation and remaining limits.
```
