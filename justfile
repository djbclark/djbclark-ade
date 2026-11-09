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

# Observe-only systemd linger (Linux user timers). Exit 69 when Linger=no; never runs sudo.
# n/a (exit 0) on launchd/cron. Operator enables once: sudo loginctl enable-linger $USER
linger:
    "{{ root }}/bin/ade-sched" --backend auto linger

# Install the daily ade-update --check job (Linux: systemd; Mac: launchd via --backend auto).
# Requires --set __STATE__; never auto-applies updates (check only).
# On Linux: run `just linger` first (Linger=no → install exits 69).
# Omit --ade so ade-sched's linked-worktree guard applies (install from the
# canonical checkout; docs show --ade ~/src/djbclark-ade when that path is used).
update-check-install:
    "{{ root }}/bin/ade-sched" --backend auto install "{{ root }}/config/launchd/com.djbclark.ade-update-check.plist" \
        --set "__STATE__={{ env_var_or_default('HOME', '/tmp') }}/.local/state/ade"
