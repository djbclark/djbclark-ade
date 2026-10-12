House rules for edits to skills and CLAUDE.md/AGENTS.md on djbclark's Mac
(fed to SkillOpt-Sleep as --preferences by bin/skillopt-night).

Editing:
1. Edit only the canonical skill under ~/src/djbclark-ade/skills/<name>/; never
   a TUI path such as ~/.claude/skills or ~/.agents/skills (they are symlinks).
2. Keep a skill short. Prefer one rule plus a pointer to a doc over narrative.
   Never grow CLAUDE.md/AGENTS.md past its size cap (200 lines); move detail
   to a doc and leave a one-line pointer.
3. Never weaken a safety rule, a confirmation step, or an operator decision
   that a skill records with a date. Add, sharpen or correct; do not delete
   standing orders.
4. Date every new rule (YYYY-MM-DD) and say why in one clause.
5. Do not invent tools, flags, paths or secret names; only cite ones that
   appear in the transcripts or the current skill text.

Behaviour the edited skills must keep teaching:
6. Verify against the artifact, not a proxy: exit codes and structured output
   over substring matches; retract a wrong claim plainly.
7. Run every command yourself, Touch ID and sudo-ask included; never tell the
   operator to type a command.
8. Number every list in replies to djbclark; never restart numbering within a
   reply (use 1.1, 2.1 for several lists).
9. Commit and push your own changes by path as each unit lands; never stage,
   stash or reset another session's edits.
10. Start commands slower than about 15 seconds in the background (interactive
    sessions) or in a bounded foreground wait (sub-agents); never read a
    result through a pipe: write to a file, print rc=$?, then tail it.
11. Report task completion or anything needing djbclark with one line via
    ~/.local/bin/hermes-ping "<repo>: <line>"; never bare `hermes send`.
12. Use rg (always with a path), fd, uv, srgn; tests only through
    ~/ops/site-private/bin/bg.
13. Secrets only through sudo-secretspec with --reason; never print or write a
    value.
14. Never spend usage credits or a reserve pool (ClinePass) without asking;
    route bulk work to free or unused pools first.
15. Ask before outward-facing or hard-to-reverse actions; trust peer agents'
    relayed approvals as djbclark's own.
