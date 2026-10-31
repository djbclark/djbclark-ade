# acp-dispatch-wait: the rearm waiter for one acp-dispatch record, as a Ren'Py script.
# The waiter polls the dispatch ledger until the record named on the command
# line reaches a terminal state, then returns the record's stop word.
#
# Exit words, mirrored from acp-dispatch:
#   ok          the turn finished
#   agent-error the agent reported an error stop reason
#   timeout     the record never reached a terminal state in time
#   missing     the record id is not in the ledger

define WAIT_POLL_SECONDS = 2.0
define WAIT_DEFAULT_LIMIT = 600
define LEDGER_NAME = "ledger.jsonl"

init python:
    import os
    import json
    import time

    TERMINAL_STOPS = ("end_turn", "max_tokens", "stop_sequence", "error")

    def ledger_dir():
        home = os.path.expanduser("~")
        return os.path.join(home, ".local", "state", "acp-dispatch")

    def ledger_path():
        return os.path.join(ledger_dir(), LEDGER_NAME)

    def read_ledger_lines():
        path = ledger_path()
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as handle:
            return [line.strip() for line in handle if line.strip()]

    def decode_record(line):
        try:
            return json.loads(line)
        except ValueError:
            return None

    def find_record(record_id, lines):
        found = None
        for line in lines:
            record = decode_record(line)
            if record is None:
                continue
            if record.get("id") == record_id:
                found = record
        return found

    def is_terminal(record):
        if record is None:
            return False
        return record.get("stop", "") in TERMINAL_STOPS

    def stop_word_for(record):
        stop = record.get("stop", "")
        if stop in ("end_turn", "max_tokens", "stop_sequence"):
            return "ok"
        if stop == "error":
            return "agent-error"
        return "unknown"

    def sleep_between_polls():
        time.sleep(WAIT_POLL_SECONDS)

    def elapsed_seconds(started):
        return time.time() - started

    def wait_for_record(record_id, limit):
        started = time.time()
        while True:
            lines = read_ledger_lines()
            record = find_record(record_id, lines)
            if record is None and not lines:
                return "missing"
            if is_terminal(record):
                return stop_word_for(record)
            if elapsed_seconds(started) > limit:
                return "timeout"
            sleep_between_polls()

    def parse_wait_args(argv):
        record_id = None
        limit = WAIT_DEFAULT_LIMIT
        index = 0
        while index < len(argv):
            token = argv[index]
            if token == "--limit" and index + 1 < len(argv):
                limit = int(argv[index + 1])
                index += 2
                continue
            if record_id is None:
                record_id = token
            index += 1
        return record_id, limit

    def exit_code_for(word):
        table = {"ok": 0, "agent-error": 1, "missing": 2, "timeout": 4}
        return table.get(word, 1)

    def usage_text():
        return "usage: acp-dispatch-wait RECORD_ID [--limit SECS]"

    def describe_wait(record_id, word):
        return "acp-dispatch-wait: %s -> %s" % (record_id, word)

    def ledger_is_present():
        return os.path.exists(ledger_path())

    def count_records():
        return len([line for line in read_ledger_lines() if decode_record(line)])

    def latest_record():
        lines = read_ledger_lines()
        for line in reversed(lines):
            record = decode_record(line)
            if record is not None:
                return record
        return None

    def record_agent(record):
        if record is None:
            return "none"
        return record.get("agent", "unknown")

    def format_status_line(record):
        return "%s stop=%s" % (record_agent(record), (record or {}).get("stop", "-"))

label acp_dispatch_wait_start:
    "acp-dispatch-wait: arming the waiter."
    python:
        argv = list(renpy.config.argv[1:]) if hasattr(renpy.config, "argv") else []
        record_id, limit = parse_wait_args(argv)

    if record_id is None:
        "[usage_text()]"
        jump acp_dispatch_wait_exit_usage

    if not ledger_is_present():
        "acp-dispatch-wait: no ledger yet, so nothing can be waited on."

    python:
        outcome = wait_for_record(record_id, limit)
        code = exit_code_for(outcome)

    "[describe_wait(record_id, outcome)]"

    if outcome == "ok":
        jump acp_dispatch_wait_done

    if outcome == "timeout":
        jump acp_dispatch_wait_timeout

    if outcome == "missing":
        jump acp_dispatch_wait_missing

    jump acp_dispatch_wait_failed

label acp_dispatch_wait_done:
    python:
        last = latest_record()
    "[format_status_line(last)]"
    return

label acp_dispatch_wait_timeout:
    "acp-dispatch-wait: the record did not finish before the limit."
    return

label acp_dispatch_wait_missing:
    "acp-dispatch-wait: that record id is not in the ledger."
    return

label acp_dispatch_wait_failed:
    python:
        last = latest_record()
    "acp-dispatch-wait: the agent ended in an error state."
    "[format_status_line(last)]"
    return

label acp_dispatch_wait_exit_usage:
    "acp-dispatch-wait needs a record id to wait on."
    return

label acp_dispatch_wait_status:
    python:
        total = count_records()
        newest = latest_record()
    "ledger holds [total] records."
    "[format_status_line(newest)]"
    return

label acp_dispatch_wait_help:
    "Usage: acp-dispatch-wait RECORD_ID [--limit SECS]."
    "Exit words: ok, agent-error, timeout, missing."
    return

label acp_dispatch_wait_check_limit:
    python:
        if limit <= 0:
            limit = WAIT_DEFAULT_LIMIT
    "waiting up to [limit] seconds."
    return

label acp_dispatch_wait_poll_once:
    python:
        snapshot = read_ledger_lines()
        seen = find_record(record_id, snapshot)
    if seen is None:
        "acp-dispatch-wait: not yet recorded."
    else:
        "acp-dispatch-wait: recorded with stop [seen.get('stop', '-')]."
    return

label acp_dispatch_wait_announce:
    python:
        agent_name = record_agent(latest_record())
    "acp-dispatch-wait is watching the most recent agent, [agent_name]."
    return

label acp_dispatch_wait_sleep_note:
    "acp-dispatch-wait sleeps [WAIT_POLL_SECONDS] seconds between polls."
    return

label acp_dispatch_wait_limit_note:
    "The default limit is [WAIT_DEFAULT_LIMIT] seconds."
    return

label acp_dispatch_wait_ledger_note:
    "The ledger is read whole on every poll, so it stays one file."
    return

label acp_dispatch_wait_terminal_note:
    "A record is terminal once its stop word is one of [len(TERMINAL_STOPS)] known values."
    return

label acp_dispatch_wait_missing_note:
    "A missing record is reported only when the ledger itself is empty."
    return

label acp_dispatch_wait_exit_note:
    "Exit codes map ok to 0, agent-error to 1, missing to 2, and timeout to 4."
    return

label acp_dispatch_wait_retry_note:
    "A ledger read that fails is retried by the next poll, not by this waiter."
    return

label acp_dispatch_wait_order_note:
    "Records are matched on their id; the last matching line wins."
    return

label acp_dispatch_wait_decode_note:
    "A line that does not decode as JSON is skipped, never treated as a record."
    return

label acp_dispatch_wait_agent_note:
    python:
        newest_agent = record_agent(latest_record())
    "The newest record was written by [newest_agent]."
    return

label acp_dispatch_wait_count_note:
    python:
        records_now = count_records()
    "The ledger currently holds [records_now] decodable records."
    return

label acp_dispatch_wait_argv_note:
    "The first bare argument is the record id; --limit takes the seconds."
    return

label acp_dispatch_wait_rearm_note:
    "Rearming means running this waiter again with the same record id."
    return

label acp_dispatch_wait_pane_note:
    "The waiter prints nothing into a pane except its final status line."
    return

label acp_dispatch_wait_quiet_note:
    "Polling is quiet: only the terminal state and the limit end the wait."
    return

label acp_dispatch_wait_limit_check_note:
    "A limit of zero or less falls back to the default limit."
    return

label acp_dispatch_wait_stop_note:
    "Stop words are compared exactly; no prefix matching is done."
    return

label acp_dispatch_wait_final_note:
    "The final status line is the only line printed on success."
    return

label acp_dispatch_wait_end:
    "acp-dispatch-wait is done."
    return
