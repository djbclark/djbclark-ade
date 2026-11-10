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
