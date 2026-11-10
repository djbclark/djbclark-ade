# djbclark-ade — thin recipe entry points (S2). Each recipe calls a bin/ tool.

set shell := ["bash", "-uc"]

root := justfile_directory()

# Validate the versioned effective config (pure; no writes, no network).
config-check:
    "{{ root }}/bin/ade-config" check --root "{{ root }}"

# Validate the transitional install catalog (pure; no installs).
install-check:
    "{{ root }}/bin/ade-install" check --root "{{ root }}"

# Observe-only install doctor (no repair, no secret reads; includes Claude context_size_nudge registration).
install-doctor:
    "{{ root }}/bin/ade-install" doctor --root "{{ root }}"

# Observe-only key presence via sudo-secretspec check (no values, no verify).
keys *args:
    "{{ root }}/bin/ade-install" keys --root "{{ root }}" {{ args }}

# Alias for setup-plan S3b wording (`just keys --check`); keys is already observe-only.
keys-check *args:
    "{{ root }}/bin/ade-install" keys --root "{{ root }}" {{ args }}

# Print-only install plan.
install-plan:
    "{{ root }}/bin/ade-install" plan --root "{{ root }}"

# Bounded apply dry-run (default mode; no writes beyond nothing).
install-apply-dry:
    "{{ root }}/bin/ade-install" apply --dry-run --root "{{ root }}"

# Preview system_argv without executing (Linux apt paths today).
install-apply-system-dry:
    "{{ root }}/bin/ade-install" apply --system --dry-run --root "{{ root }}"

# Print-only platform system_argv (never executes; safe in CI).
install-print-system-argv *args:
    "{{ root }}/bin/ade-install" apply --print-system-argv --root "{{ root }}" {{ args }}

# Canonical names from docs/setup-plan.md (thin wrappers over install-* / ade-update).
# `just install` defaults to apply dry-run; pass `-- --yes` for live user-scoped apply.
# doctor includes install.jobs drift (ade-sched scan); never unloads foreign owners.
[positional-arguments]
doctor component="":
    #!/usr/bin/env bash
    set -eu
    args=()
    if [[ -n "${1:-}" ]]; then args=(--id "$1"); fi
    exec "{{ root }}/bin/ade-install" doctor --root "{{ root }}" "${args[@]}"

install *args:
    "{{ root }}/bin/ade-install" apply --root "{{ root }}" {{ args }}

update *args:
    "{{ root }}/bin/ade-update" --repo "{{ root }}" {{ args }}

# Pure dependency command inventory; never runs updates or probes.
update-plan:
    "{{ root }}/bin/ade-install" update-plan --root "{{ root }}"

# S4 stub: observe-only then exit 5 (full auto-apply not implemented; no scheduled apply).
update-auto *args:
    "{{ root }}/bin/ade-update-auto" --repo "{{ root }}" {{ args }}

# Install the daily ade-update --check job (Linux: systemd; Mac: launchd via --backend auto).
# Requires --set __STATE__; never auto-applies updates (check only).
# Omit --ade so ade-sched's linked-worktree guard applies (install from the
# canonical checkout; docs show --ade ~/src/djbclark-ade when that path is used).
update-check-install:
    "{{ root }}/bin/ade-sched" --backend auto install "{{ root }}/config/launchd/com.djbclark.ade-update-check.plist" \
        --set "__STATE__={{ env_var_or_default('HOME', '/tmp') }}/.local/state/ade"

# Install the daily read-only harden-check job (Linux: systemd; Mac: launchd).
# Never mutates GitHub settings (ade-harden observe only).
harden-check-install:
    "{{ root }}/bin/ade-sched" --backend auto install "{{ root }}/config/launchd/com.djbclark.harden-check.plist" \
        --set "__STATE__={{ env_var_or_default('HOME', '/tmp') }}/.local/state/ade"

# Install the daily S3b keys-check job (Linux: systemd; Mac: launchd).
# Observe-only: never prompts; never prints secret values.
keys-check-install:
    "{{ root }}/bin/ade-sched" --backend auto install "{{ root }}/config/launchd/com.djbclark.keys-check.plist" \
        --set "__STATE__={{ env_var_or_default('HOME', '/tmp') }}/.local/state/ade"

# S4b: ADE-owned jobs inventory and live drift (report only; never unload).
sched-list:
    "{{ root }}/bin/ade-sched" list --root "{{ root }}"

sched-diff:
    "{{ root }}/bin/ade-sched" diff --root "{{ root }}"

# S4b: ADE-owned systemd/cron reconcile + ownership ledger (default dry-run; pass -- --yes to write).
sched-reconcile *args:
    "{{ root }}/bin/ade-sched" reconcile --root "{{ root }}" {{ args }}

# Linux one-step: reconcile every ADE-owned labeled job (update-check / keys-check /
# harden-check / deadline-sweep / …). Default dry-run; pass -- --yes to write.
# Folded into `ade-install apply` (full apply, no --id) as well.
sched-reconcile-checks *args:
    "{{ root }}/bin/ade-sched" reconcile --root "{{ root }}" \
        --name ade-update-check --name keys-check --name harden-check \
        --name deadline-sweep --name pr-policy --name load-watch {{ args }}

# Validate github.toml + merge-gate App manifest (setup-plan S8; pure).
github-setup-check:
    "{{ root }}/bin/ade-github-setup" check --root "{{ root }}"

# Observe-only merge-gate setup (optional gh probes; no repair, no secret reads).
github-setup-observe:
    "{{ root }}/bin/ade-github-setup" observe --root "{{ root }}"

# Local-only observe (skip gh network probes).
github-setup-observe-local:
    "{{ root }}/bin/ade-github-setup" observe --local --root "{{ root }}"

# Print-only S8 step plan.
github-setup-plan:
    "{{ root }}/bin/ade-github-setup" plan --root "{{ root }}"

# Dry-run github setup apply (default; no mutations).
github-setup:
    "{{ root }}/bin/ade-github-setup" apply --dry-run --root "{{ root }}"

# Alias for github-setup (explicit dry-run name).
github-setup-dry:
    "{{ root }}/bin/ade-github-setup" apply --dry-run --root "{{ root }}"

# Live API apply: environment + ruleset (refuses browser App confirm / PEM store).
github-setup-apply:
    "{{ root }}/bin/ade-github-setup" apply --yes --root "{{ root }}"

# API-only verify of manifest + environment + ruleset (no throwaway T0-T3b).
github-setup-verify:
    "{{ root }}/bin/ade-github-setup" apply --verify --root "{{ root }}"

# Validate hardening.toml (setup-plan S6; pure).
harden-check-config:
    "{{ root }}/bin/ade-harden" check --root "{{ root }}"

# Observe-only hardening drift (gh read-back; no writes, no auto-reapply).
harden-check:
    "{{ root }}/bin/ade-harden" observe --root "{{ root }}"

# Local-only harden-check (skip gh network probes).
harden-check-local:
    "{{ root }}/bin/ade-harden" observe --local --root "{{ root }}"

# Opt-in Hermes basic setup (setup-plan S3a). Does not install or force Hermes.
# Default: open Claude Code on prompts/setup/hermes.md.
# `just hermes-setup --self`: print the DIY checklist only (no agent, no peer-link).
# Prompt+recipe only (no bin/ shim); exception to the thin-bin rule above.
# [positional-arguments] forwards *args into the shebang recipe's $@ (without it,
# --self/--help never reach the loop and the recipe always takes the AI path).
[positional-arguments]
hermes-setup *args:
    #!/usr/bin/env bash
    set -euo pipefail
    root="{{ root }}"
    prompt="${root}/prompts/setup/hermes.md"
    if [[ ! -f "${prompt}" ]]; then
      printf '%s\n' "missing prompt: ${prompt}" >&2
      exit 2
    fi
    mode=ai
    for a in "$@"; do
      case "${a}" in
        --self|self) mode=self ;;
        -h|--help|help)
          printf '%s\n' \
            "Usage: just hermes-setup [--self]" \
            "  (default) open Claude Code on prompts/setup/hermes.md" \
            "  --self    print the DIY checklist only (no agent)"
          exit 0
          ;;
        *)
          printf '%s\n' "unknown argument: ${a} (try --self or --help)" >&2
          exit 2
          ;;
      esac
    done
    if [[ "${mode}" == self ]]; then
      awk '
        /^## DIY checklist/ {p=1}
        p && /^## / && !/^## DIY checklist/ {exit}
        p {print}
      ' "${prompt}"
      exit 0
    fi
    if ! command -v claude >/dev/null 2>&1; then
      printf '%s\n' "claude not on PATH. Install Claude Code, or run: just hermes-setup --self" >&2
      exit 2
    fi
    exec claude -- "Read and follow the checked-in prompt at ${prompt} for Hermes basic setup (setup-plan S3a). Opt-in only: do not install Hermes if the user skipped it; do not configure peer-link live. Walk the checklist one card at a time with the recommended option first; stop for each secret (user types into sudo-secretspec themselves, never into chat); finish with just install-doctor and hermes doctor when available."
