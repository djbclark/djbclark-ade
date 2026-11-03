# Surplus work: djbclark-ade

Things worth spending a "use it or lose it" quota surplus on (djbclark, 2026-11-02): `bin/quota-surplus notify` tells the leads
when a window is about to reset with quota left, and `bin/quota-surplus list-work` prints this list beside every other repo's,
most valuable first. Skill: [skills/quota-surplus](../skills/quota-surplus/SKILL.md).

## Format (any repo may adopt it: `docs/surplus-work.md`)

One numbered line per item, fields separated by ` | `; the parser reads only numbered lines that contain a `|`:

    N. One-line task, with the PR, branch or queue heading it is about | kind: K | size: S | fit: F | read-only: yes | value: V

1. `kind`: review, second-opinion, research, design, refactor or tests.
2. `size`: S (under 30 min), M (under 2 h), L (longer). A lead never starts an item it cannot finish before the reset.
3. `fit`: `frontier` (worth gpt-6-astra, Fable or Gemini 4 Argon), `bulk` (any cheaper pool) or `any`; a comma list is allowed.
4. `read-only`: `yes` when the item only reads and reports (dispatch those first: nothing to land or clean up), else `no`.
5. `value`: high, medium or low; `list-work` sorts on it, then read-only first.

Remove an item when it is done or stale; keep the numbers of the rest (a lead may cite `djbclark-ade#3`).

## Items (2026-11-02)

1. Adversarial review of PR 261 (relay: question ledger for leads, --ask/--inbox/--answer/--withdraw) at its head | kind: review | size: M | fit: frontier | read-only: yes | value: high
2. Adversarial review of PR 260 (route: per-repo/seat scope for routing pools, `allow_repos`/`allow_seats`, acp-dispatch scope_block) | kind: review | size: M | fit: frontier | read-only: yes | value: high
3. Second opinion on PR 258 (helm lead mode, `/helm lead`): the `--idle 1800` rule for Claude Paseo targets and the ack flow | kind: second-opinion | size: M | fit: frontier | read-only: yes | value: high
4. Second opinion on the docs/queue.md proposal "relay: card-blocked records should fail fast": is failing fast safe for every route? | kind: second-opinion | size: S | fit: frontier | read-only: yes | value: medium
5. Design the "model tiers as data" change (docs/queue.md, after D1): what moves out of route_agent.py into config, and the tests that pin it | kind: design | size: L | fit: frontier | read-only: yes | value: medium
6. Research how to keep relay.py and self-slash from blocking on TUI picklists and modal states (docs/queue.md research item, 2026-10-28) | kind: research | size: M | fit: frontier,bulk | read-only: yes | value: medium
7. Review PR 214 (governor and quota guard: deeply nested JSON no longer crashes their readers) against the queue's sibling RecursionError readers | kind: review | size: S | fit: bulk | read-only: yes | value: medium
8. Research what porting the Linux suite and the g-tool symlinks to uutils needs (docs/queue.md, PR 102's ubuntu-24.04 stopgap) | kind: research | size: M | fit: bulk | read-only: yes | value: low
9. Audit tests/ for tests that pin wording or incidental behaviour (AGENTS.md test rules) and list deletions with reasons | kind: tests | size: M | fit: bulk | read-only: yes | value: low
