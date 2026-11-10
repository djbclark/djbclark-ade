---
name: ingest-web-ai
description: >-
  Design and offline normalizer for feeding Gemini/Grok (and similar) web
  chats into ADE memory. No live scrape, no credentials, no S1 writes from
  this skill — read docs/ingest-web-ai.md and run the local fixture/export
  normalizer only. Default CLI writes opaque JSONL to a file and prints a
  metadata summary (counts/paths) to stdout — never raw message text.
---

# ingest-web-ai — web-chat → memory (design + offline stub)

Carried queue **#23**. Full design: [`docs/ingest-web-ai.md`](../../docs/ingest-web-ai.md).

## When to use

- Planning or reviewing how Gemini / Grok *web* conversations enter S1 or
  curated memory.
- Turning an **operator-supplied local export file** (or a synthetic fixture)
  into S1-shaped event JSONL for a **non-agent** ingest path (file on disk).

## Hard limits (this skill)

1. **No network I/O** to Gemini, Grok, X, Google, or VESTI backends.
2. **No credentials** in argv, env, or fixtures checked into this repo.
3. **No writes** to `~/.hindsight`, Basic Memory stores, or any path outside
   the caller's chosen output file (default: `<input-stem>.events.jsonl`
   beside the export).
4. **No raw export text in agent tool transcripts.** The CLI always writes
   events to an opaque file and prints only a metadata summary (counts,
   paths, role tallies) on stdout. Do not `cat` the JSONL into a prompt.
5. Live browser capture (`paseo-screen`, logged-in scrape, localhost mirror)
   needs an explicit operator gate — see the design doc §E. Do not start it
   from this skill.

## Offline normalize

```sh
python3 skills/ingest-web-ai/scripts/normalize_export.py \
  --input tests/fixtures/ingest-web-ai/gemini-sample.json \
  --producer gemini-web
```

Writes `tests/fixtures/ingest-web-ai/gemini-sample.events.jsonl` (or pass
`--output PATH`) and prints one summary JSON object to stdout, for example:

```json
{"conversation_count":1,"event_count":2,"input":"…","output":"…","producer":"gemini-web","roles":{"assistant":1,"user":1},"schema":"ade.web-ai.normalize.summary.v0"}
```

Stdout never includes message `text`. Exit 0 on success, 2 on usage/input
errors. Read the JSONL only from a non-agent ingest path (later S1 adapter,
or an operator inspecting the file outside an agent turn).

## See also

- Memory landscape: [`docs/history/ai-memory-landscape.md`](../../docs/history/ai-memory-landscape.md)
- Threat model (untrusted web input): [`docs/threat-model.md`](../../docs/threat-model.md)
- Queue cite: [`docs/queue.md`](../../docs/queue.md) Carried #23
