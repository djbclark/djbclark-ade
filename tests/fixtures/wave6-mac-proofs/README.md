# FIXTURE — Wave 6 Mac proof shape (NOT live Mac stdout)

Snapshot: 2026-11-10. Queue Carried **item 33** residual (no live Mac cycle yet).

These files exist so CI can prove the `mac_proofs` FAILCLOSED contract and the
capture **shape** (`cmd:` + `verified: no match` when idle) without inventing a
Mac live-cycle paste. Every proof file's first line is `FIXTURE — NOT live Mac
stdout`.

## Shape regression: `--dry-run`

```bash
bin/wave6-delete-check --dry-run --json
```

Exit 0 means labeled FIXTURE proofs are non-empty (FAILCLOSED shape OK).
`ready` stays false — never deletion-ready. Unlabeled / invented “live”
content under this directory fails closed (`fixture_invalid`).

## Do not use as deletion evidence

`bin/wave6-delete-check --evidence` for the **deletion PR** must point at
operator-captured Mac files from `bin/wave6-mac-proof-capture --live --out DIR`
(or the equivalent paste in `docs/slim/wave6-follow-up.md` §B). Pointing the
gate at this fixture bundle (or greening `--dry-run`) does not satisfy Carried
item 33's Mac live cycle.

## Replace after the Mac live cycle

1. On the Mac: `bin/wave6-mac-proof-capture --live --out ./wave6-evidence --json`
2. Copy or merge the printed `mac_proofs` paths into the real `evidence.json`
3. Keep C3 proof files from outside probes / waives (order 11)
4. Run `bin/wave6-delete-check --evidence ./wave6-evidence/evidence.json`
5. Paste live stdout into the deletion PR; retire or delete this fixture bundle
   once live proofs are the only path tests need (or keep fixtures for shape
   regression only — still labeled FIXTURE)

Gate: [`bin/wave6-delete-check`](../../../bin/wave6-delete-check).
Harness: [`bin/wave6-mac-proof-capture`](../../../bin/wave6-mac-proof-capture).
Docs: [`docs/slim/wave6-follow-up.md`](../../../docs/slim/wave6-follow-up.md).
