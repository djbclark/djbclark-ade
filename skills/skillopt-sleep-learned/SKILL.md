---
name: skillopt-sleep-learned
description: >-
  Preferences and procedures learned from past local agent sessions on this
  Mac by the nightly SkillOpt-Sleep cycle. Use as general background for any
  task here when no more specific skill applies; read the rules below before
  acting.
---

# skillopt-sleep-learned

This file is the catch-all target of the nightly SkillOpt-Sleep cycle
(`bin/skillopt-night`, docs/skillopt-sleep.md). The cycle only stages
proposals; a human or agent adopts them with `skillopt-sleep adopt`, and each
adoption is an ordinary commit in `~/src/djbclark-ade`. Keep it short: when a
rule here grows specific to one skill, move it into that skill instead.

## Rules

1. Verify against the artifact, not a proxy: check exit codes, structured
   output and the file itself before claiming a result.
2. Run commands yourself, including Touch ID and `sudo-ask` steps; never hand
   the operator a command to type.
3. Number every list in a reply; never restart numbering within one reply.
4. Commit and push your own changes by path as each unit lands; never stage
   another session's edits.
5. Start anything slower than about 15 seconds in the background (interactive
   sessions) or in a bounded foreground wait (sub-agents); never read a result
   through a pipe.
6. Report completion, or anything that needs the operator, with one line via
   `~/.local/bin/hermes-ping "<repo>: <line>"`.
