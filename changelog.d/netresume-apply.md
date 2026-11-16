### Changed

- `ade-net-resume` resumes a quota-stopped agent instead of only logging `would-resume-quota` (its launchd template now passes `--apply`), and gains a preventive `--transition-below PERCENT` pass that asks every agent whose pool headroom is nearly spent to hand off or switch account before it stops. Eligibility is uniform: the current lead counts exactly like a descendant, so a lead stopped by a provider window is no longer unrecoverable. (#769)
