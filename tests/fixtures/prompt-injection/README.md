# Prompt-injection smoke fixtures

Inert test data. Nothing here is an instruction to any agent reading this directory: every file is a
payload that a *detector* must recognise as hostile. The canary is a Touhou reference, because it is
harmless, unmistakable in output, and impossible to produce by accident from this repo's subject
matter - if a Touhou name ever appears in an ADE report, something obeyed one of these files.

Each payload carries a directive (`CANARY` in `tests/test_prompt_injection_smoke.py`) plus a quoted
`adversary-verdict` marker, so one fixture exercises two things at once: whether the text survives
masking, and whether a quoted verdict can be read as a live one.

`__HEAD__` is replaced with the 40-hex head under test. Carriers, and what `bin/pr-wait`'s
`_strip_code` does to each, are asserted in the test module - including the three shapes the strip
deliberately does not mask (documented limits C1a/b/c).
