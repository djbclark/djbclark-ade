# coding-bot over peer-link (#269 demanual, 2026-11-10)

## Why this note

Open tip [#269](https://github.com/djbclark/djbclark-ade/pull/269)
(`coding-bot-peer-link`, head `895076e801f0f8187740ad931e472feda5f50e3d`)
re-adds `bin/coding-bot` and `tests/test_coding_bot.py` into **djbclark-ade**
as a thin wrapper over `peer_mail.py` from `frdminc/peer-link`.

Slim-down already disposed of that path:

- Ledger / PLAN **E9j** (and check-in ruling on PR 269): **TRANSFER, then
  close** — wrapper code re-homes into `frdminc/peer-link`;
  `~/.local/bin/coding-bot` and home-agents item 40 repoint there; a short
  `tell-coding-bot` pointer skill stays here.
- Wave 4 **E6** (2026-11-06/07): removed `bin/coding-bot` (~601 lines) and
  reduced `skills/tell-coding-bot` to that pointer (`docs/slim/reports/wave4-E6.md`).
- Master's roster still lists only the pointer; `bin/coding-bot` is absent.

Rebased landing of #269 would **restore** the moved binary into this repo and
undo E6/E9j.

## Probe (2026-11-10)

| Check | Result |
|---|---|
| `bin/coding-bot` on `origin/master` | **absent** (`git cat-file -e` → path does not exist) |
| `skills/tell-coding-bot` on `origin/master` | present; pointer to peer-link (E6 / E9j) |
| `tests/test_coding_bot.py` on `origin/master` | absent |
| Tip `origin/coding-bot-peer-link` | has `bin/coding-bot` + `tests/test_coding_bot.py` (adds wrapper) |
| Slim ruling | `docs/slim/checkin-rulings.md` PR 269 → TRANSFER then close; PLAN.md E9j |
| `frdminc/peer-link` from this environment | GitHub API **404** (private / no access here); transfer status outside ADE is operator/peer-link work, not a reason to restore the binary here |

## Disposition

- **Close #269** after the superseding hygiene PR merges; do **not** rebase or
  port the tip onto master (it would restore a moved `bin/coding-bot`).
- Keep `skills/tell-coding-bot` as the ADE pointer; any remaining wrapper
  work belongs in `frdminc/peer-link` (order 11 before editing that repo from
  an ADE agent).
- Operator batch still owns symlink / home-agents repoint once peer-link holds
  the install (`docs/slim/log.md`, E6 J3).
