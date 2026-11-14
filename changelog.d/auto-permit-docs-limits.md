### Changed

- Docs follow-up to #710: `bin/ade-auto-permit` skips `ade.kind=external-review` agents and their Paseo descendants that carry no `ade.lead` or `--ade-label` of a lead in the lineage; docs/orchestration-practices.md section 3, docs/scheduling.md, skills/fan-out and docs/peer-trust.md rule 2 now state the limits (only the label counts; a top-level `bin/ade-worker-run` child of a labelled agent, and senders marked only by config ids or title patterns, are still approved under `--all-local`). (#719)
