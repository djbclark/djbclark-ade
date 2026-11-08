# djbclark-ade — thin recipe entry points (S2). Each recipe calls a bin/ tool.

set shell := ["bash", "-uc"]

root := justfile_directory()

# Validate the versioned effective config (pure; no writes, no network).
config-check:
    "{{ root }}/bin/ade-config" check --root "{{ root }}"
