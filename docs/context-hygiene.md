# Context hygiene — 2026-10-25

Context capacity is a correctness ceiling, not a cost budget. Cached input is
billed again on every request, and Go models debit the same monthly allowance
at different rates. Choose a suitable economical model before trying to save
money by repeatedly compacting an expensive one.

## 1. Natural task boundaries

1. At a completed task, checkpoint before beginning unrelated work. Write the
   owned Tier 1 log and handoff with absolute paths, branch/head, dirty files,
   unresolved decisions, active job records, unread results and exact next steps.
2. A top-level session on a supported host runs the `handoff` skill and lets its
   Step 9 queue one new-session/baton cycle. A dispatched slice writes a
   document-only handoff; it must never clear or archive its parent.
3. Never throw away an unsent draft, interrupt a running worker, or reset before
   the checkpoint is durable. Re-arm existing jobs instead of launching their
   work again. A failed lifecycle operation is reported, not retried in a loop.
4. A larger fixed instruction/tool baseline is not removable conversation.
   Repeated compactions of that baseline waste tokens. Preserve the checkpoint,
   reduce the attached instructions/tools, or continue on a suitable model.

## 2. Earlier Claude nudges

The Claude hook warns after 32,000 tokens of growth and recommends a handoff at
the next completed-task boundary from 120,000 total input tokens. It still
accounts for growth from the post-compaction floor and suppresses repeated
warnings within a tier. These warnings do not interrupt a turn or clear context.

Claude's existing `autoCompactWindow` stays at 300,000. Measurements that motivated
its growth and cooldown guards showed substantial summary/cache-write overhead;
lowering that window indiscriminately can cost more. Those Claude measurements
must not be presented as OpenCode Go prices or compaction thresholds.

## 3. Native OpenCode compaction

Use OpenCode V2's own compaction API at a safe point, including for an ACP
session. Do not type Claude slash commands into a presumed parent terminal.
The [native Go context plugin](../opencode-plugins/go-context/README.md) warns
at 64k and compacts at 96k plus 32k growth (hard trigger 128k) for routine models;
costly models warn at 32k, compact at 64k plus growth and hard-trigger at 96k.
These are local initial policy values, not vendor recommendations. Use current input plus cached reads/writes;
lifetime token totals and output totals do not measure current context.

The plugin adds the `ade_compact` tool, scoped by the native tool context. Use
it from JavaScript/codemode; the hook never rewrites JavaScript. It supplies
`ADE_OPENCODE_SESSION_ID` only for the current native `bash`/`shell` tool call. With that scope, `bin/self-slash "/compact"` verifies
the exact session and Go provider through the native API, then queues compaction.
It can compact an ACP slice's own session without targeting its parent. ACP
launches scrub any inherited native session ID before starting the child. The
command reports acceptance, not completion; use native compaction events for
completion evidence. A repeated manual request within five minutes is refused,
and an uncertain write is recorded before the request so a timeout is not
blindly retried. `--dry-run` makes no API calls.

Native compaction does not accept the Claude `/compact <focus>` syntax here.
Save the focus in the checkpoint first. `/new`, `/clear` and `/reset` through
the scoped native path fail closed: a native reset must have both a durable
owned handoff and a supported, acknowledged successor/baton path. A successful
compaction request alone is not that evidence. Existing supported host lifecycle
paths remain available when their own identity and ownership checks pass.

OpenCode V2 settings are `compaction.auto`, `compaction.keep.tokens` and
`compaction.buffer`; `agents.compaction.model` chooses its summarizer. The
buffer is relative to model capacity, not an absolute cost cap. Do not copy V1
`reserved` or pruning settings into V2. Background compaction is not enabled as
a cost optimization: an unused speculative summary still costs tokens.

## 4. Verification

Test offline with fake native APIs and separate temporary session state. Cover
provider/session identity, concurrent and duplicate requests, uncertain writes,
compaction completion, out-of-order usage, fixed-baseline loops and parent
lifecycle protection. Do not make paid inference requests just to test a guard.

Local focused tests use the full `bg` path. Record the explicit decision first:

```bash
~/src/djbclark-ade/bin/load-watch ci decide /absolute/worktree local "Small offline focused checks; full matrix on GitHub"
~/ops/site-private/bin/bg python3 -m pytest tests/test_opencode_self_compact.py
```

## 5. Primary sources

1. [OpenCode V2 compaction](https://opencode.ai/v2/docs/compaction): safe-point
   scheduling, recent-tail retention, completion events, fixed-baseline limits
   and speculative summary cost.
2. [OpenCode Go usage limits](https://opencode.ai/v2/docs/console/go/#usage-limits)
   and [allowance accounting](https://opencode.ai/v2/docs/console/api/inference/#cost).
3. [OpenCode V2 plugins](https://opencode.ai/v2/docs/plugins): native server
   hooks and plugin discovery. Check the installed SDK against these docs;
   similar V1 names do not establish a V2 hook contract.
