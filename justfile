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
keys:
    "{{ root }}/bin/ade-install" keys --root "{{ root }}"

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
doctor:
    "{{ root }}/bin/ade-install" doctor --root "{{ root }}"

install *args:
    "{{ root }}/bin/ade-install" apply --root "{{ root }}" {{ args }}

update *args:
    "{{ root }}/bin/ade-update" --repo "{{ root }}" {{ args }}

# Install the daily ade-update --check job (Linux: systemd; Mac: launchd via --backend auto).
# Requires --set __STATE__; never auto-applies updates (check only).
# Omit --ade so ade-sched's linked-worktree guard applies (install from the
# canonical checkout; docs show --ade ~/src/djbclark-ade when that path is used).
update-check-install:
    "{{ root }}/bin/ade-sched" --backend auto install "{{ root }}/config/launchd/com.djbclark.ade-update-check.plist" \
        --set "__STATE__={{ env_var_or_default('HOME', '/tmp') }}/.local/state/ade"

# S4b: ADE-owned jobs inventory and live drift (report only; never unload).
sched-list:
    "{{ root }}/bin/ade-sched" list --root "{{ root }}"

sched-diff:
    "{{ root }}/bin/ade-sched" diff --root "{{ root }}"

# S4b: ADE-owned systemd reconcile + ownership ledger (default dry-run; pass -- --yes to write).
sched-reconcile *args:
    "{{ root }}/bin/ade-sched" reconcile --root "{{ root }}" {{ args }}

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
      printf '%s
' "missing prompt: ${prompt}" >&2
      exit 2
    fi
    mode=ai
    for a in "$@"; do
      case "${a}" in
        --self|self) mode=self ;;
        -h|--help|help)
          printf '%s
' \
            "Usage: just hermes-setup [--self]" \
            "  (default) open Claude Code on prompts/setup/hermes.md" \
            "  --self    print the DIY checklist only (no agent)"
          exit 0
          ;;
        *)
          printf '%s
' "unknown argument: ${a} (try --self or --help)" >&2
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
      printf '%s
' "claude not on PATH. Install Claude Code, or run: just hermes-setup --self" >&2
      exit 2
    fi
    exec claude -- "Read and follow the checked-in prompt at ${prompt} for Hermes basic setup (setup-plan S3a). Opt-in only: do not install Hermes if the user skipped it; do not configure peer-link live. Walk the checklist one card at a time with the recommended option first; stop for each secret (user types into sudo-secretspec themselves, never into chat); finish with just install-doctor and hermes doctor when available."
