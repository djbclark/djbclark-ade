# tendcf qualification adapter

`bin/ade_fork_tendcf.py` assesses eligibility only. It performs no filesystem,
Git, pin, tag, root, archive, deploy or runtime writes. Both owners reviewed this
ADE-only scope on 2026-11-18. They have **not** approved a complete machine-readable
full-fork feature contract. Default assessment therefore holds with
`missing-full-fork-contract`; the historical register and overlay are not that
contract. The proposed mapping remains under owner review outside this source.

The pure adapter requires four independent protected callbacks: approval of the
complete contract digest, generic release-receipt authentication (the existing
`VerifiedArtifact.authenticates` API), authentication of the entire coupled build
proof, and approved permanent retention of the exact payload digest. These are
trusted in-process code, never candidate-supplied booleans or callable names.
Defaults deny, including transport failures. Receipt consistency alone is not
authentication. No deployment or pin permission is returned even when eligible.

The protected contract binds exact consumer/core/libntech repositories and SHAs,
the mode-160000 gitlink from that core tree, explicit libntech source repository,
overlay/workflow/recipe digests, platform and complete feature-to-evidence maps.
The release receipt must match the same core, dependency, consumer recipe,
platform, overlay and payload bytes. The separately authenticated build proof
binds those measured inputs to an exact repository/run/attempt and each actual
job/platform/suite result. `GATE_DONE`, overall green, source presence and script
exit zero do not establish each suite's success. Unexpected skips, failures,
errors and XPASS hold. Required full-fork features cannot borrow overlay results.

Current owner requirements include the full Linux vm matrix and Debian build,
debug core units, CMDB/simulate/exec-timeout acceptance, policy fork-loader probes,
separately proven full-fork json/mustache/security discriminators, and production
test-hook exclusion. The owners must finish the exhaustive feature contract,
including numeric semantics outside the overlay and historical patch retirement.
Strict CMDB loading remains distinct from lenient legacy readjson/def.json APIs;
atomic all-or-nothing replaces the retired per-entry skip implementation.

The Debian Actions artifact `cfengine-fork-debian13` currently has 14-day retention
and a consumer-only REVISION. Neither proves permanent retention or the coupled
fork identities. A protected authenticated job receipt may establish coupling;
REVISION alone cannot. No permanent live destination is approved. This module
does not create one or copy artifacts there. Missing proven retention holds.

Source references owned by tendcf: `overlay/fork.json`, `overlay/overlay.json`,
`.github/actions/build-fork/action.yml`, `.github/workflows/linux.yml`,
`tests/policy/run.sh`, `docs/architecture/upstream-overlay.md` and
`docs/architecture/upstream-register.md`. Read them at the consumer receipt's
exact commit; dated reports are historical candidate mappings. No macOS run or
upstream CFEngine/NorthernTech/Jira/email submission is authorized here.
