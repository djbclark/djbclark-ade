---
name: sipb-llm-bench
description: Benchmark a model on MIT SIPB LLMs (or any OpenAI-compatible Open WebUI/Ollama server) as an agentic-coding backend: speed probes, a tool-call conformance check, and two real tool-using tasks scored by running the tests. Use to test a new or upgraded model, re-run after a server upgrade, or compare models; also for "does model X work for coding agents on SIPB LLMs", /sipb-llm-bench.
---

# sipb-llm-bench

Measures whether a model on the SIPB LLMs server (or any OpenAI-compatible endpoint) can
drive a terminal coding agent. It is the harness behind
[research/sipb-llms/REPORT.md](https://github.com/djbclark/site-djbclark/blob/master/research/sipb-llms/REPORT.md),
packaged so SIPB admins and users can run it on other models. Everything is in this directory:
`bench.py`, `toolcall_conformance.py`, `tasks/` (prompts, the broken-repo template, a short
rules file), `crushrc.example`.

## Be a good neighbour (read first)

The server is shared and holds **one model on the GPU at a time**. A model swap costs
everyone 10-19 s and a busy server queues silently for minutes.

1. Run one `bench.py` at a time, never in parallel, never in a loop. A full model takes
   about 15-40 minutes (probes ~1 min, task A ~2-4 min, task B up to 10-15 min per run).
2. Prefer off-peak hours and avoid the Friday 4-5 pm front-end update window.
3. Test one model, finish, then the next. Do not test several models "at once".
4. Use your own API key; nothing in this directory contains one. The harness never prints it.

## What you need

1. Python 3.9+ (standard library only) for the probes and the conformance check.
2. An API key: Open WebUI, profile icon, Settings, Account, API keys. Export it:
   `export SIPB_API_KEY=sk-...` (or keep it in `~/.config/crush/crushrc`; the harness reads
   the first `sk-` token there if `SIPB_API_KEY` is unset).
3. Network: the server is often MITnet or VPN only (`https://llms-dev-1.mit.edu/api`).
   Override with `SIPB_BASE=https://host/api` for another server.
4. For the two agent tasks (`--probes-only` skips them and needs no runner): an agent runner. The default is
   [`acp-run crush`](https://github.com/djbclark/djbclark-ade/tree/master/tools/acp-run) with a Charm Crush
   build that has an ACP server and auto-approve (PRs
   [#2450](https://github.com/charmbracelet/crush/pull/2450) and
   [#3909](https://github.com/charmbracelet/crush/pull/3909)). Any other agent works through
   `--runner` (below).
5. Strongly recommended: the loopback proxy
   [tools/sipb-llms-proxy](https://github.com/djbclark/site-djbclark/tree/master/tools/sipb-llms-proxy)
   (stdlib Python). Open WebUI 0.6.30 ends tool-call streams with `finish_reason: "stop"`,
   which makes OpenAI-style agents stop after the first tool call. Without the proxy (or a
   fixed server) the agent tasks fail for reasons that are not the model's fault.
   `toolcall_conformance.py` tells you which case you are in. The proxy (2026-10-13) also
   rewrites a tool call the model wrote *as text* (`<tool_calls><invoke …`, `<function=…`,
   `<view>…`) into a real `tool_calls` delta; without it the agent runs nothing (REPORT.md
   section 4.7).

## Run it

```bash
S=skills/sipb-llm-bench          # this directory
export SIPB_API_KEY=sk-...
# 1. does the server's tool-call path work for this model? (about 1 minute, 3 requests)
python3 $S/toolcall_conformance.py --long MODEL            # direct
python3 $S/toolcall_conformance.py --base http://127.0.0.1:8890/api MODEL   # via the proxy
# 2. plan, then run (probes, task A x2, task B if task A passed)
python3 $S/bench.py run --models MODEL --dry-run
python3 $S/bench.py run --models MODEL --tag m1
# 3. the table
python3 $S/bench.py summary
```

Useful options of `bench.py run`:

| option | meaning |
| --- | --- |
| `--models a,b` | server model ids (as `GET /api/models` lists them); run serially |
| `--modes think,nothink` | default: both for reasoning families (qwen3.5/3.6, gpt-oss, gemma4, ...), `nothink` for the rest |
| `--fizz N` | task A repetitions (default 2) |
| `--wordstats FILE`, `--wordstats-cap S` | task B prompt under `tasks/` (`wordstats-lean.txt` default, `wordstats.txt` full) and cap in seconds |
| `--rules` | give the agent `tasks/rules.md` (five short rules for small models) |
| `--extra '--verify\|python3 -m unittest discover'` | extra runner args; with `acp-run`, `--verify` re-prompts the agent until the tests pass (the "verify loop" in the report) |
| `--force-wordstats` / `--fizz-only` / `--no-probe` / `--probes-only` | skip the gating, only task A, only tasks, or only the speed probes |
| `--runner 'CMD'` | other agent runner; placeholders `{dir}` `{prompt}` `{cap}` `{log}`; it must work in `{dir}`, and gets the model in env `SIPB_MODEL`, `SIPB_THINK`, `SIPB_EFFORT` |
| `--tag X` | batch tag; a finished batch writes `DONE-X` and is skipped on rerun |

State lives in `$SIPB_BENCH_DIR` (default `~/.local/state/sipb-bench`): `results.jsonl` (one JSON
object per probe or task, no prompts or responses), `status.txt` (what is running now), `runs/`
(per-run project directories and agent logs).

With the default runner the harness builds a private Crush config per run from your
`~/.config/crush/crushrc` (see `crushrc.example`: a provider block pointing at the proxy or
server, nothing else is required), so set that up once. It deletes the per-run copy, which holds the key, after each run.

## How a run is judged

1. **Probes** (direct requests): cold time to first token (includes a model swap if another
   model was loaded), decode speed in streamed chunks/s (an upper bound on tokens/s: reasoning
   deltas count), time to first token for a ~10k-token prompt the first and second time (the
   second shows prefix caching).
2. **Task A, "fizz"**: a three-test repo with two bugs; fix, run the tests, commit. Pass =
   `python3 -m unittest` passes afterwards **and** a new commit exists (checked by the
   harness, not the agent). Time cap 300 s.
3. **Task B, "wordstats"**: five phases (build a package with 12+ tests, run it, one `curl`,
   extend with 4+ tests, notes and commit). Pass = tests pass, 16 or more tests exist, one
   commit exists. Cap 600 s (lean prompt) or 900 s.
4. Every task row records the provider that actually served it (`providers`); `summary`
   counts only rows served by `sipb-llms`, and skips rows you mark `"invalid": true`.

## Reading the numbers

1. Task A is a smoke test; most usable models pass it. Task B separates models: small
   changes in prompt, rules and verify loop move it a lot, so run it at least twice and read
   the pass count, not one time.
2. A model that fails the conformance check or task A with 0 tool calls is a server-side
   tool-parsing problem (template or parser), not a capability problem: see REPORT.md 4.3-4.4.
   A model that answers a task by *describing* the tool call as text (or printing the
   command in a fence) instead of emitting a `tool_calls` delta is the same class of problem
   (REPORT.md 4.7); the proxy converts the explicit text forms, but a model that only prints
   a ```` ```bash ```` fence is not rescued and should be dropped — `deepseek-r1:32b` did
   this every time and is not in the example config.
3. Runs that fail on a timeout or network error during an outage are suspect (ours), not the
   model's: mark them (`"invalid": true`, or a note row) and rerun.
4. Do not edit task files between models you want to compare.

## Adding a model or a task

1. Model: nothing to add; pass its id to `--models`. Add it to `REASONERS` in `bench.py` only
   if it streams reasoning and you want `--think` set for it.
2. Task: put `NAME.txt` under `tasks/` and score it in `run_task_inner` (see the `fizz` and
   `wordstats` branches: they run the tests themselves and read git state).

## Updating the report (or branching it) after a run

The published report is [research/sipb-llms/REPORT.md](https://github.com/djbclark/site-djbclark/blob/master/research/sipb-llms/REPORT.md)
with its raw rows in `research/sipb-llms/bench/results.jsonl`. After testing a model, update it
in the same sitting, on a branch of its own so the published copy stays as it was until
someone reviews the change. `report/build_page.py` and `report/template.html` render it as a web page.

1. Branch: in a clone of `djbclark/site-djbclark` (or your fork, or a copy of that directory),
   `git switch -c sipb-bench/MODEL-YYYY-MM-DD`. (Updating in place on `master` is fine for your
   own rerun of a model already in the report.)
2. Data: append only this model's new rows to `research/sipb-llms/bench/results.jsonl`
   (`cat $SIPB_BENCH_DIR/results.jsonl` rows with a `ts` after your start). Mark rows you
   discarded (outages, mistakes) `"invalid": true` or with a `{"kind":"note",...}` row saying why.
3. Edit `REPORT.md`, keeping its structure and numbers consistent:
   1. date line and server versions at the top (`GET /api/version`, Ollama via the admins);
   2. TL;DR bullet 2 (which models work) and the ranked table only if your finding changes a rank;
   3. section 2 table: one row from `bench.py summary` (cold first token, chunks/s, prefill);
   4. section 3: one row for task A and B, and the "N valid runs" count in its heading;
   5. section 4: a new numbered problem only if the model fails differently (a conformance
      failure, a new `null`/200 body, a stall); section 7.1 if the conformance script now
      passes or fails against the server directly;
   6. section 8: link anything new you added (new tasks, new rules file).
4. Page: `uv run --with markdown report/build_page.py REPORT.md out.html --meta '2026-10-12 · Open WebUI X · Ollama Y · host'`.
   Publish `out.html` wherever the previous page lives (it is one self-contained file).
5. `git add -A && git commit -m "sipb-llms report: add MODEL"`, push the branch, and open a
   pull request (or send the branch to the admins). Merge to `master` once reviewed.

## Publishing results

Send `results.jsonl` (it contains no credentials, prompts or responses) and the
`summary` table. For the SIPB admins: `sipb-llms@mit.edu`.
