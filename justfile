# djbclark-ade — thin recipe entry points (S2). Each recipe calls a bin/ tool.

set shell := ["bash", "-uc"]

root := justfile_directory()

# Validate the versioned effective config (pure; no writes, no network).
config-check:
    "{{ root }}/bin/ade-config" check --root "{{ root }}"

# Validate the transitional install catalog (pure; no installs).
install-check:
    "{{ root }}/bin/ade-install" check --root "{{ root }}"

# Observe-only install doctor (no repair, no secret reads).
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

# Canonical names from docs/setup-plan.md (thin wrappers over install-* / ade-update).
# `just install` defaults to apply dry-run; pass `-- --yes` for live user-scoped apply.
doctor:
    "{{ root }}/bin/ade-install" doctor --root "{{ root }}"

install *args:
    "{{ root }}/bin/ade-install" apply --root "{{ root }}" {{ args }}

update *args:
    "{{ root }}/bin/ade-update" --repo "{{ root }}" {{ args }}
