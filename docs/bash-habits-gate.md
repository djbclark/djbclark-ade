# Bash habits gate

As of 2026-11-12, `claude/hooks/bash_habits_gate.py` checks a submitted shell
command before execution. A denial blocks the entire submission: **nothing in
the command ran, including any earlier part**. Fix the offending part and
re-run the whole command. This applies to compound commands separated by `;`
or `&&` as well as single commands.

The denial includes this explanation in Claude's permission decision, Codex's
stderr and Cursor's user/agent messages. Warnings continue to allow execution.
Checks include bare BSD `sed`, recursive `grep`, GNU-only flags on BSD tools
and pipelines that mistake a filter's status for the producing command's.
