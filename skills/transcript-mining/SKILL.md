---
name: transcript-mining
description: >-
  Reusable analyses over agent transcripts (~/.claude/projects/*/*.jsonl) and
  harness state logs (self-slash.log, relay records): context peaks,
  compaction stats, per-day command usage, refusal/failure counts. Use when
  asked "how big do contexts get", "how often do we compact", "what did
  agents run last week", or before writing a new one-off Python analyzer of
  session telemetry. Replaces the rewritten-each-time one-offs.
---

# transcript-mining — agent telemetry analysis

Born 2026-11-05 from two one-off analyzers written 2026-10-27
(`~/.local/state/ade-briefs/transcript-context-peaks.py`,
`selfslash-log-by-day.py`), both instances of the same recurring workflow:
answer an operator question about agent behaviour by scanning transcript
jsonl or harness logs with a small Python script, then report numbers. Each
time the script was rewritten from scratch and left unversioned in a state
dir; this skill keeps parameterized versions instead.

## 1. What lives where

1. Transcripts: `~/.claude/projects/*/*.jsonl`, one jsonl per session, one
   JSON object per line. Relevant line shapes: `compact_boundary` events
   (carry `compactMetadata.trigger` and `compactMetadata.preTokens`) and
   assistant messages (`message.usage`, `message.model`; skip lines with
   `isSidechain` — sub-agent traffic, not the main context).
2. Harness logs: `~/.local/state/self-slash.log`
   (`date time host pane: message`), relay/acp-dispatch records under
   `~/.local/state/{acp-dispatch,acp-run}/`.
3. Scripts: `scripts/context-peaks.py` and `scripts/log-by-day.py` in this
   skill (below). Output goes to a dated brief under
   `~/.local/state/ade-briefs/`, descriptive filename — never `report.md`.

## 2. Rules

1. **Bounded scan, never all of `~`.** Always an mtime window
   (`--days N`, default 7) or an explicit day set; state the file count
   covered in the output so "0 files" is visible, not silent.
2. **Cheap substring prefilter before `json.loads`.** Test
   `'"compact_boundary"' in line` / `'"usage"' in line and '"assistant"' in
   line` first; parsing every line of every transcript is the difference
   between seconds and minutes. Every `json.loads` sits in its own
   `try/except` — transcripts contain truncated final lines.
3. **Token accounting includes cache tokens.** A context-size figure is
   `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`;
   input alone understates the peak by up to ~10x.
4. **Open files with `errors="replace"`** and wrap `stat()` in
   `try/except OSError`; sessions rotate underneath a running scan.
5. **Aggregate day-keyed** (`defaultdict(Counter)`), and normalize ids in
   free-text log keys (`re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27}", "<id>", ...)`)
   before counting, or one uuid swamps the histogram.
6. **Argv lists, no shell pipes for status** (house review rule 2): output is
   printed or written to a file, exit code checked directly.
7. Report medians and maxima, not just totals; the operator's questions are
   usually distributional ("how bad is the worst case").

## 3. Scripts

Both take `--days N` (context-peaks) or `--days N`/`--last N` (log-by-day),
print a plain-text summary, and exit 0 on success even when zero files
matched (the file count is in the first line). Add new analyzers here
rather than in a scratch dir; if one grows specific to another skill, move
it there (same rule as the skillopt-sleep catch-all).

1. `context-peaks.py [--days N] [--root PATH]` — per-day compaction counts
   by trigger, preTokens median/max, session context-peak histogram
   (<100k / 100–200k / 200–270k / 270–400k / >=400k), top-10 peaks with
   model and session id.
2. `log-by-day.py [--days N] [--log PATH]` — per-day counts of slash/`$`
   commands sent, distinct agents active, and the top normalized
   refusal/failure/timeout message shapes from self-slash.log.
