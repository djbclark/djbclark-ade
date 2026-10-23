# Vendored from getpaseo/paseo

Source: https://github.com/getpaseo/paseo, `skills/` at commit fcda2f1 (2026-10-18), Apache-2.0
(upstream `LICENSE`). Six skills: `paseo`, `paseo-advisor`, `paseo-committee`, `paseo-handoff`,
`paseo-help`, `paseo-plugin`. Taken 2026-10-18 after scanning every `SKILL.md` (they are the only
files): no scripts, no install-and-run lines, network use is fetching paseo.sh docs and the local
`paseo` CLI.

**One local patch** (the only change from upstream): the `description` of `paseo-advisor`,
`paseo-committee` and `paseo-handoff` is narrowed to explicit Paseo requests. Upstream triggers on
plain "handoff", "second opinion" and "stuck", which would take those requests away from this
repo's `handoff` skill, `acp-run`/`dialogue` and orca-cli. Re-apply when updating.

The `paseo` CLI reaches the local daemon from its config (port 7263 on every host here, not
upstream's 6767); other hosts with `--host`. Setup on this fleet: site-djbclark `docs/paseo.md`.

**Paseo overwrites these files at every daemon start** unless its skill selection is `custom` with no skills
(`agents.skills.selection` in `~/.paseo/config.json`; docs/skill-everywhere.md section 3a, 2026-10-23). The bundle
was last compared on 2026-10-23 (0.13.0-beta.1): `paseo` and `paseo-plugin` are ahead of this copy.

