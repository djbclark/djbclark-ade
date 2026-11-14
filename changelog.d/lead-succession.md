### Fixed

- A completed `ade-self-session` handoff now carries every lead-id binding to the successor: `ade-worker-run` adopts the archived predecessor's windows and `ade.lead` workers instead of refusing them as another lead's, the installed `ade-net-resume` and `ade-auto-permit` jobs follow the chain to the current lead, and `fable-wait` delivers to it. `ade-net-resume` with a retired lead and no successor now logs `skip-lead-retired` and exits 0 instead of crash-looping with exit 2. (#669)
