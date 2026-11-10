# Retained C3 history/accounting — proposal, not a grant

Snapshot: 2026-11-10. The operator has authorized the active dependency
migrations. **No additional waiver is recorded by this proposal.** C1+C2
remain the only granted waivers until an explicit reply authorizes more.

## A. Concrete remaining references

- `cfengine-all` active instructions migrated in
  [#1](https://github.com/djbclark/cfengine-all/pull/1), merged as
  `134c9afb3aea11a00b72750562a935934101406a`. The reviewed AGENTS.md has no
  `cfenginewatch`, `fleet-watch`, or `bin/watch` matches. Dated files under
  `docs/handoffs/` retain descriptions of the former watcher. These are
  historical records, not instructions to reinstall or run it. This does not
  certify the separate installed `cfengine-core` or Mac fleet state.
- `aiuse` active guidance/runtime-message migration is
  [#54](https://github.com/djbclark/aiuse/pull/54), reviewed head
  `a69d2e80b0f743a65b7c54ec8421c2b9cc9ef32d`. Retained modules
  `src/aiuse/collectors/acp_usage.py`, `usage_sources.py`, `quota_refusals.py`,
  and `analysis/frozen_quota.py` consume existing log/accounting data; they do
  not require launching the retired ADE executable. Keep their fixtures,
  format documentation, historical handoffs and logs. Passive refusal scans
  may still update quota notes from existing logs: this is not a claim that
  all accounting code is read-only.

## B. Proposed operator lines

These lines are proposed text only, **not** live proof snippets or granted
`waive:` records. Apply each only after explicit operator authorization and
after the active migration it depends on has merged.

> 2026-11-10: waive Wave 6 C3 cfengine only for preserved dated handoff
> references after the active instruction migration; do not rewrite history
> or reinstate retired watcher commands. Active runtime dependencies and Mac
> verification remain required.

> 2026-11-10: waive Wave 6 C3 aiuse only for passive consumption of existing
> ACP logs and its associated tests, format documentation and dated history,
> after active launcher guidance is migrated. Preserve accounting and logs;
> this does not authorize new retired-tool launches or waive live callers.

## C. Effect and limits

If granted, record the exact operator decision in `docs/slim/log.md` and
prepare matching proof snippets for the next Mac capture. Keep any installed
active caller unresolved until migrated. Do not infer `ready=true`, B2 drain,
Pi pool acceptance, early deletion permission, or deletion confirmation from
these narrow record-retention waivers.
