# Pi duplicate-skill cleanup (2026-11-03)

## A. Scope and safety

A1. `bin/skill-everywhere` already supplies Pi through `~/.agents/skills`.
Do not create a second native link farm, remove either resource tree, or disable
skill warnings globally. `bin/pi-skill-dedup` only adds **exact absolute
`-…/SKILL.md` exclusions** to Pi's `skills` array. It never installs anything.

A2. This helper deliberately accepts explicit pairs, not an automatic sweep.
Global pairs must be matching direct children of the agent's `skills` directory
(default `~/.pi/agent/skills`) and `~/.agents/skills`. It keeps the shared copy.
`PI_CODING_AGENT_DIR` or `--agent-dir` selects a non-default agent directory.
Paths supplied to the helper must be absolute (a leading `~` is accepted).

A3. Matching `SKILL.md` alone is insufficient: scripts, references, relative
assets and executable bits can differ. The helper compares the **whole bundle**,
including hidden files and empty directories. Root symlinks are supported;
internal symlinks, special files, unreadable entries, oversized files (>8 MiB),
bundles over 10,000 entries, nonportable names and differing content are refused.
Aliases to the same real bundle need no cleanup and are refused. Differing copies
need a separate source reconciliation decision, never a forced exclusion.

A4. Existing settings files must be JSON objects with unique keys and a string
array `skills` if present. No JSONC, duplicate keys or non-finite numbers. Existing
settings must already exist; creating/provisioning them is outside this tool.
Unrelated settings and user skill entries survive. Existing glob exclusions
(`!…`) and discovery ignore files are refused rather than approximating Pi's
matcher. Exact exclusions that would disable the keeper are refused. Resource
packages, custom skill loaders, ancestor project catalogs, CLI overrides and
SDK overrides are not audited: verify the actual Pi catalog after review.

## B. Dry run, review, apply, reverse

B1. From the reviewed checkout, plan one or more explicit pairs. `plan` is always
a dry run for settings. Without `--output` it writes nothing; with it, it creates
a new private plan file (parent directory must exist). Repeat `--pair` for more
skills. Output contains proposed exclusion paths and counts, not settings values.

```sh
~/src/djbclark-ade/bin/pi-skill-dedup plan \
  --pair ~/.pi/agent/skills/skills-everywhere ~/.agents/skills/skills-everywhere \
  --output /ABSOLUTE/PRIVATE/cleanup-plan.json
```

B2. Review the proposed paths, scope, retained resources and plan. Plans bind the
settings bytes, symlink real targets and bundle fingerprints. `apply` re-verifies
everything and refuses stale/edited plans. It requires an active ADE claim on the
**real settings file**, not merely the development workspace or parent directory.
The operator/lead must authorize and serialize runtime edits first. Do not edit
preferences concurrently in Pi or another process. This is an advisory ownership
contract plus last-moment byte checks, not a transaction lock against other apps.

The existing registry supports non-repository runtime targets through
`--no-pointer` (no Git pointer is appropriate for a settings file). After approval,
use the ordinary registry command, substituting the actual real file, reviewed
source SHA and owning session; do not invent a claim, unset safeguards, or use an
override to get past a refusal:

```sh
python3 ~/src/djbclark-ade/bin/ade_claims.py new \
  --id pi-skills-runtime-UNIQUE --path /REAL/PATH/settings.json \
  --branch runtime --base-sha REVIEWED_SOURCE_SHA \
  --owner-session OWNER_SESSION --owner-agent pi --no-pointer
ADE_CLAIM_ID=pi-skills-runtime-UNIQUE ~/src/djbclark-ade/bin/pi-skill-dedup apply \
  --plan /ABSOLUTE/PRIVATE/cleanup-plan.json \
  --receipt /ABSOLUTE/PRIVATE/cleanup-receipt.json
```

B3. Receipt publication precedes the settings edit so an interruption retains
recovery information. Outputs never overwrite existing files or symlinks. The
settings edit uses a temporary file beside the **real target**, fsync and atomic
replacement, preserving its permission bits and the original symlink. Settings
must be caller-owned, single-linked, and not group/world writable. Plan/receipt
files use mode 0600; keep them private (they contain resource paths). No credentials
are accessed. A runtime claim does not authorize editing another repository's
tracked settings: use that repository's approved workspace/install path instead.

B4. Reversal is also dry-run first:

```sh
~/src/djbclark-ade/bin/pi-skill-dedup undo --receipt /ABSOLUTE/PRIVATE/cleanup-receipt.json
ADE_CLAIM_ID=pi-skills-runtime-UNIQUE ~/src/djbclark-ade/bin/pi-skill-dedup undo \
  --receipt /ABSOLUTE/PRIVATE/cleanup-receipt.json --apply
```

Undo removes only this operation's additions and restores an originally absent
`skills` key. Later edits to unrelated settings are preserved. **Any later change
to the skills array causes refusal**, rather than guessing which entries are still
owned. Symlink retargeting is also refused. An already reversed operation (or an
apply that never reached settings) is a no-op. Keep the receipt for inspection;
it is not deleted. Reacquire the real-target claim before a later reversal.

B5. After an approved apply or undo, reload Pi and inspect its actual diagnostics
and catalog, including the retained skill's path. Do not claim success from a
symlink listing alone. Release the runtime claim through
`ade_claims.py set-state ID released` after the serialized operation. Later
resource upgrades can invalidate equivalence: rerun an audit/review rather than
assuming an old exclusion still represents identical copies.

## C. Project-local graft is a separate case

C1. Never exclude global graft merely because one project has its own graft copy:
other projects still need the global skill. `plan --project /ABSOLUTE/PROJECT`
only accepts an excluded `.pi/skills/graft` or `.agents/skills/graft` directly in
that project, retaining global `graft` from the agent or shared skill directory.
It writes only that project's existing `.pi/settings.json`. Supply the explicit
local/global pair and use a separate plan, receipt and real-target runtime claim.

C2. The installed Pi implementation applies project skill overrides to project
resources and user overrides to user resources. A project exclusion of a global
path is therefore not a supported fix. The helper excludes the **local** copy
only if the full bundles are equivalent. If project graft contains project-specific
instructions, it refuses; preserve both and report the collision for a separate
reviewed naming/source decision. Project settings require Pi project trust.

## D. Delivery and verification

D1. Development stays in a claimed ADE workspace. After independent review and
integration, use the normal `ade-update` fast-forward path to make the reviewed
helper available at `~/src/djbclark-ade/bin/pi-skill-dedup`; invoke that path directly.
No installed-script patch, native skill symlink or live-settings edit is needed
for delivery. `skill-everywhere --check --all` remains the normal shared-link check.
A separate approved runtime claim is mandatory before applying exclusions.

D2. Synthetic regression coverage lives in `tests/test_pi_skill_dedup.py`; tests
use temporary homes and claim registries, never live settings. Run through the
repository's Linux `Tests` workflow (manual branch dispatch); do not run full
suites/builds on the operator's Mac. Relevant installed Pi references read for
this implementation: `docs/settings.md`, `docs/skills.md`, `docs/configuration.md`,
`docs/packages.md`; exact resource matching/discovery was also checked in
`dist/core/package-manager.js`.
