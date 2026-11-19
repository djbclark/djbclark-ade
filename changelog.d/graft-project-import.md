### Security

- Restricted graft hook imports to install roots by default; required `ADE_GRAFT_ALLOW_PROJECT_HOOKS=1` to load project packages or bare `dist/claude` helpers for Claude, Cursor, and pre-bash. (#827)
- Rejected canonical project targets from every hook discovery source, including PATH, remembered records, node libraries, global packages, and symlinked modules; rejected relative `TRAIL_HOME` without explicit project opt-in. (#827)
