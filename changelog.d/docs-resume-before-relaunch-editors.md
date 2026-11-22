### Changed

- Resume before relaunching, not "never relaunch" (operator rule 2026-11-22): `docs/orchestration-practices.md` item 10 and the `agent_footer_gate.py` resume-guard text now say to resume first and relaunch only after a reasonable effort to resume fails (resume sent, state confirmed, one retry), reusing the dead agent's report, files and worktree; the guard's behaviour is unchanged. `docs/ref-labels.md` lists Gemini Neon (else Argon) among the instruction-file editors (operator rule 2026-11-22). (#929)
