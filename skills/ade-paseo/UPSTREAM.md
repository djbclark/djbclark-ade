# Vendored from getpaseo/paseo

Source: https://github.com/getpaseo/paseo, `skills/` at commit fcda2f1 (2026-10-18), Apache-2.0
(upstream `LICENSE`). Six skills, upstream `paseo`, `paseo-advisor`, `paseo-committee`, `paseo-handoff`,
`paseo-help`, `paseo-plugin`, kept here as `ade-paseo`, `ade-paseo-advisor`, `ade-paseo-committee`,
`ade-paseo-handoff`, `ade-paseo-help`, `ade-paseo-plugin`. Taken 2026-10-18 after scanning every `SKILL.md`
(they are the only files): no scripts, no install-and-run lines, network use is fetching paseo.sh docs and
the local `paseo` CLI.

**Local patches** (re-apply all three when updating):

1. The `description` of `ade-paseo-advisor`, `ade-paseo-committee` and `ade-paseo-handoff` is narrowed to explicit Paseo
   requests. Upstream triggers on plain "handoff", "second opinion" and "stuck", which would take those
   requests away from this repo's `handoff` skill, `acp-run`/`dialogue` and orca-cli.
2. Interim, local-only site policy (2026-10-30; not for upstream): `ade-paseo-handoff`'s Isolation item sends an
   "in a worktree" handoff to a `git worktree add` task worktree with an `isolation: "local"` workspace, until
   `docs/paseo-only-rearchitecture.md` rule D0.3 lifts (D1.3 and D2's gate passed). Remove it then.
3. The `ade-` prefix on every name, directory and cross-reference (2026-11-02). Paseo owns skills by name: any Paseo
   build or home whose skill selection includes them rewrites `~/.agents/skills/<name>` and `~/.claude/skills/<name>`
   to its bundle, and those were links into this repo (getpaseo/paseo#7700). A name Paseo does not ship is never
   touched. Keep every Paseo home's selection at `{"mode":"custom","skills":[]}` so Paseo does not install its own
   unprefixed copies beside these (`docs/skill-everywhere.md` section 3a).

The `paseo` CLI reaches the local daemon from its config (port 7263 on every host here, not
upstream's 6767); other hosts with `--host`. Setup on this fleet: site-djbclark `docs/paseo.md`.

Before 2026-11-02 the unprefixed names let every Paseo daemon (the main one and any dev or test home) overwrite these
files; the last time was 2026-11-01 21:33:38, with the bundle of the installed Paseo 0.15.0-beta.1 (its
`paseo-advisor/SKILL.md` hashes to `f52ce024…`, the value in the manifest it left). The bundle was last compared
on 2026-10-23 (0.13.0-beta.1): `paseo` and `paseo-plugin` are ahead of this copy.

