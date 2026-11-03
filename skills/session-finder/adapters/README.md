# session-finder adapters

One file per agent. Contract (the core, `session-history.py`, loads every `*.py` here):

    AGENT = "codex"                       # short lowercase name shown in results
    def sessions():                       # cheap: stat/list only, no content parsing
        yield {"key": "codex:<id>",       # globally unique, prefix with AGENT
               "sid": "<native session id>",
               "fp": "<size:mtime or row count>",   # changes iff the session changed
               "mtime": <epoch float>,    # last activity
               "supersedes": ["old-key"], # optional migration: same-agent/id/cwd legacy rows retired after successful load
               "load": <callable>}        # -> (cwd, title, [(role, text), ...]); role is "user"|"assistant"
    def live() -> set[str]:               # optional: native sids that are running now
    def live_info() -> dict:              # optional, for messaging: sid -> {"pid", "procStart", "name"}
    RESUME = "codex resume {sid}"         # optional hint printed for ended sessions
                                          # (or a function (sid, cwd) -> command, already shell-quoted: crush.py)
    RESUME_USES_KEY = True                # optional: pass the stable key instead of sid to RESUME (Pi file targets)
    LIVE_LABEL, ENDED_LABEL = "OPEN", "closed"   # optional: what to print instead of LIVE/ended
    ROOT_ENV = ("CODEX_HOME",)            # REQUIRED if the adapter reads an environment variable to find its store:
                                          # `--install` copies those variables (when set) into the launchd job

Document adapters (`todo.py`: every Basic Memory project's `todo/` notes) use the same
contract with one entry per note, role `"note"` (capped at 4000 chars per row, so split a
long note into one row per section), `live()` = the open ones and the labels above.

Rules: `load()` is only called when `fp` changed, so parse there, not in `sessions()`.
Text only (no tool output, no system prompts/reminders). Read-only on the agent's data;
open SQLite files with `file:...?mode=ro` URIs. Skip a session on any error rather than raising.

Pi (`pi.py`, added 2026-11-03) reads native JSONL under `~/.pi/agent/sessions`,
or the `PI_CODING_AGENT_DIR` / `PI_CODING_AGENT_SESSION_DIR` overrides. Only user
and assistant text is indexed; thinking and tool output are excluded. The most
recent nonempty `session_info` name supplies the title. Listing is stat-only for canonical
file names (`<ISO timestamp, e.g. 2026-11-03T15-25-31-559Z>_<id>.jsonl`); a noncanonical name
(`pi --session /x/daily.jsonl`) costs one bounded (64 KiB) header read in `sessions()`, which
must be a regular file (a FIFO or oversized/malformed header is skipped). Listing skips
symlink session files/directories. As of 2026-11-03, keys are
`pi:<canonical absolute session file>`; the native ID is retained separately, including
underscores. Flat custom stores and project-grouped stores are supported. Successful
indexing retires a same-project former `pi:<id>` key; other-project orphans are preserved.
An orphan legacy key cannot produce a safe
resume hint. No native session file is modified.

History prints shell-quoted `pi --session <absolute file>` commands: Pi resumes that
file in its recorded working directory, without directory-sensitive ID lookup or a
custom-root environment dependency. Missing working directories retain Pi's native
interactive prompt. History JSON includes `sessionKey`. Exact Pi liveness requires
matching absolute session files; a full ID plus project cwd names no storage root, so it
stays `LIVE?` (and never hides another root's history). An ID alone never suffices. A file known to differ never falls back to the ID. Cwd-only evidence
remains the weaker `LIVE?` label.
