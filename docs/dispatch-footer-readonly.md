## Delivery contract (read-only sub-agent: no file tools; `agent_footer_gate` fills `{lead}` inline)

You cannot write files, so this contract replaces any instruction elsewhere in this prompt to write a report file, create a `.done` marker or read an inbox file, a pasted standard delivery contract included.

1. Your final message is the deliverable: the full report, answer first, then the evidence (`file:line` spans, short command-output excerpts), then open questions. Write no report file, `.done` marker, inbox or replies file, and never wait for one: your caller saves your final message.
2. The harness cuts a sub-agent's final message at 4,000 characters and the parent never sees the rest, so keep it under about 3,500 characters. If you need more and have SendMessage, send the full text to `{lead}` in ordered chunks under 3,500 characters each (`1/3`, `2/3`, ...) and end your final message with a short summary that says how many chunks you sent. Without SendMessage, cut the least important evidence and say what you left out.
3. Never end your turn on a question. If you are blocked, make the first line of your final message `BLOCKED: <the question, one line>` and stop. A decision you can make conservatively, make it, and record it in the final message under `DECIDED:`.
4. Change nothing: run no command that writes, and never create a file with a shell redirect, `tee` or a heredoc. Read-only commands only.
5. The last line of your final message is `DONE` (or it starts with `BLOCKED:` as above), so the caller can tell a complete report from a cut one.
