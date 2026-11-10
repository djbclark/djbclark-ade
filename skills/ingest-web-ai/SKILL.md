---
name: ingest-web-ai
description: >-
  Design and offline normalizer for feeding Gemini/Grok (and similar) web
  chats into ADE memory. No live scrape, no credentials, no S1 writes from
  this skill — read docs/ingest-web-ai.md and run the local fixture/export
  normalizer only.
---

# ingest-web-ai — web-chat → memory (design + offline stub)

Carried queue **#23**. Full design: [`docs/ingest-web-ai.md`](../../docs/ingest-web-ai.md).

## When to use

- Planning or reviewing how Gemini / Grok *web* conversations enter S1 or
  curated memory.
- Turning an **operator-supplied local export file** (or a synthetic fixture)
  into S1-shaped event JSONL for inspection.

## Hard limits (this skill)

1. **No network I/O** to Gemini, Grok, X, Google, or VESTI backends.
2. **No credentials** in argv, env, or fixtures checked into this repo.
3. **No writes** to `~/.hindsight`, Basic Memory stores, or any path outside
   the caller's chosen output file (default: stdout).
4. Live browser capture (`paseo-screen`, logged-in scrape, localhost mirror)
   needs an explicit operator gate — see the design doc §E. Do not start it
   from this skill.

## Offline normalize

```sh
python3 skills/ingest-web-ai/scripts/normalize_export.py \
  --input tests/fixtures/ingest-web-ai/gemini-sample.json \
  --producer gemini-web
```

Emits one JSON object per line (event envelope v0). Pass `--output PATH` to
write a file instead of stdout. Exit 0 on success, 2 on usage/input errors.

## See also

- Memory landscape: [`docs/history/ai-memory-landscape.md`](../../docs/history/ai-memory-landscape.md)
- Threat model (untrusted web input): [`docs/threat-model.md`](../../docs/threat-model.md)
- Queue cite: [`docs/queue.md`](../../docs/queue.md) Carried #23
