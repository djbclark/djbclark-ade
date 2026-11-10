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

# Print-only install plan.
install-plan:
    "{{ root }}/bin/ade-install" plan --root "{{ root }}"

# Bounded apply dry-run (default mode; no writes beyond nothing).
install-apply-dry:
    "{{ root }}/bin/ade-install" apply --dry-run --root "{{ root }}"

# Preview system_argv without executing (Linux apt paths today).
install-apply-system-dry:
    "{{ root }}/bin/ade-install" apply --system --dry-run --root "{{ root }}"

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
