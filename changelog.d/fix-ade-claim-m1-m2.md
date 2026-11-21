### Fixed

- `bin/ade_claims.py`: a Claude agent that the ade-claim plugin rebound a claim to is the owner on its first launch, with no re-open (M1): `caller_ident` carries `PASEO_AGENT_ID` and `is_mine` accepts it only as the exact `owner.record` of a `bind-owner`-shaped claim, never over an explicit `ADE_CLAIM_ID`. (#842)
- `bin/ade_self_session.py`: `finish` records the predecessor's active claims before the archive and reports any that another agent took meanwhile as `claims_not_rebound`, so a race with the plugin's rebind neither loses a claim silently nor rebinds it twice (M2). (#842)
