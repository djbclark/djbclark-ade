# session-finder adapters

One file per agent. Contract (the core, `session-history.py`, loads every `*.py` here):

    AGENT = "codex"                       # short lowercase name shown in results
    def sessions():                       # cheap: stat/list only, no content parsing
        yield {"key": "codex:<id>",       # globally unique, prefix with AGENT
               "sid": "<native session id>",
               "fp": "<size:mtime or row count>",   # changes iff the session changed
               "mtime": <epoch float>,    # last activity
               "load": <callable>}        # -> (cwd, title, [(role, text), ...]); role is "user"|"assistant"
    def live() -> set[str]:               # optional: native sids that are running now
    def live_info() -> dict:              # optional, for messaging: sid -> {"pid", "procStart", "name"}
    RESUME = "codex resume {sid}"         # optional hint printed for ended sessions
    LIVE_LABEL, ENDED_LABEL = "OPEN", "closed"   # optional: what to print instead of LIVE/ended

Document adapters (`todo.py`: every Basic Memory project's `todo/` notes) use the same
contract with one entry per note, role `"note"` (capped at 4000 chars per row, so split a
long note into one row per section), `live()` = the open ones and the labels above.

Rules: `load()` is only called when `fp` changed, so parse there, not in `sessions()`.
Text only (no tool output, no system prompts/reminders). Read-only on the agent's data;
open SQLite files with `file:...?mode=ro` URIs. Skip a session on any error rather than raising.
