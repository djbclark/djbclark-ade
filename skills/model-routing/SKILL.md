---
name: model-routing
description: >-
  Route AI work by vendor × model × effort across every service on this
  machine: map aiuse --json lines to their TUIs, know which pools are
  monthly subscription vs prepaid vs free, spot chronically-unused quota
  worth burning, and pick the right AI for the kind of work. Use when
  choosing which agent/model/service should run a task, before big
  multi-agent runs, when a quota window is tight, or when asked "which AI
  should do X", "what models do we have", or about aiuse output.
---

# Model routing on this machine

Canonical source of this skill: `skills/model-routing/SKILL.md` in the
djbclark-ade repo (github.com/djbclark/djbclark-ade); the copy at
`~/.claude/skills/model-routing/` is the deployed live copy — keep them
identical.

The canonical, dated matrix lives at
`~/orca/projects/djbclark-ade/docs/model-routing.md` (repo
djbclark/djbclark-ade). Read it first; this skill carries the stable
method, not the volatile numbers.

## Probes (prefer these over a hand-kept snapshot; aiuse's own cache is fine while fresh)

- `aiuse --json 2>/dev/null` — authoritative cross-service usage
  (operator's own tool, github.com/djbclark/aiuse; takes ~1 min). **Stdout
  is the JSON document from line 1** (verified 2026-09-26); the preamble
  goes to stderr, so `tail -n +3` now eats the opening brace — parse stdout
  as-is, or `sed -n '/^{/,$p'` if unsure. `snapshot.accounts[].windows[]`
  carries `label`, `used_percent`, `remaining_percent`, `resets_at`. Ignore
  its `kind:"conserve"` pace alerts for go/no-go calls. **Read it with the
  rules in *Reading quota numbers* below.**
  **Fast path: `~/ops/site-private/bin/aiuse-pools`** prints every window as
  "X% USED / Y% LEFT" (so it cannot be misread) plus the age of the data, from the
  newest cached snapshot in 0.4 s instead of the ~30-60 s live collect. The cache
  is `~/.cache/aiuse/snapshots/latest.json` (flat shape: `.accounts[]`, no
  `.snapshot` envelope; `completed_at` gives its age). It stays fresh because the
  operator often runs `aiuse watch` (a refresh every 10-20 min, each one written
  to history) and a launchd job snapshots hourly. `aiuse-pools` exits 3 when the
  data is older than 25 min, incomplete, or had collector failures; then run
  `aiuse-pools --live`. A cached read is fine for classifying pools; it cannot see
  a pool drained in the last few minutes, so still preflight each target (item 5
  below). `aiuse serve` is not running here (port 8787 belongs to another
  service), so do not rely on its HTTP API.
- `cswap list` — Claude accounts + 5h/weekly/Fable windows.
- `codex login status`; `opencode models`; `bl quota list`;
  `curl -s localhost:4000/v1/models` (LiteLLM/ClinePass);
  `agy --version`; `devin --version`; `copilot --version`.
- Orca's agent roster + per-agent launch flags:
  `~/Library/Application Support/orca/profiles/local-default/orca-data.json`
  → `settings.agentDefaultArgs` / `disabledTuiAgents`. Nearly every TUI
  is configured inside Orca; macro-graph dispatch reaches any enabled one.

## Reading quota numbers (a misreading here already cost a dispatch round)

1. **`used_percent` is the share CONSUMED; 100 means empty.** `remaining_percent`
   is the headroom. Decide from `remaining_percent` and never quote a bare
   percentage: write "100% used / 0% left". On 2026-10-03 `Codex 5-hour quota:
   100` was read as "100% free" and a review was sent to an exhausted codex.
2. **An account is usable only if every one of its windows has headroom.** The
   fullest window binds: codex at 100% used on its 5-hour window is unusable for
   ~5 hours even with its weekly window at 35% used.
3. **One TUI can hold several independent pools, one per model family.** agy:
   Gemini and Claude/GPT are separate pools (`agy models`); Claude: ordinary vs
   Fable bucket; Cursor: Auto/included vs "other models". A 429 or
   `RESOURCE_EXHAUSTED` describes the pool the chosen model draws on, not the
   vendor. Retry on a model from the vendor's other pool before declaring the
   vendor spent (agy: a `gemini-*` model when a `claude-*`/`gpt-*` one is
   exhausted, and vice versa), and pick the model by which pool is fresh, not
   only by which is strongest.
4. **State moves within a session.** agy's Claude/GPT 5-hour window read 0% used
   at probe time and was exhausted ~35 minutes later after one Opus-high review.
   Re-probe before each batch.
5. **Preflight** each target with one trivial call through the exact invocation
   and model about to be used (`"Reply with exactly: OK"`); `usage limit`,
   `RESOURCE_EXHAUSTED` or 429 means that pool is spent. Note the reset time the
   error prints.

## Billing classes (2026-08-23 shape; membership drifts)

- **Monthly subscription windows**: claude (5h/weekly/+Fable bucket),
  codex (ChatGPT Plus weekly), antigravity/agy (Google AI Pro — also
  exposes Claude/GPT windows), copilot (premium requests), cursor Pro,
  grok (SuperGrok; reserve for GrokBot), zai GLM lite (via the zcode TUI), clinepass (Cline windows, also the crush TUI; feeds
  hermes via LiteLLM :4000; reserve, never run out), devin (disabled in Orca on
  purpose).
- **Free**: opencode-go bundled models; sipb (MIT-hosted, `opencode`
  provider `sipb`).
- **Prepaid real money, gated**: opencode-zen, openrouter, deepseek —
  only via the `opencode-ralph-tui-*` gate scripts, never by default.

## Headless invocation (one-shot prompts to other TUIs)

### First choice: `acp-run` for every agent that speaks ACP

For a one-shot or headless call to an agent with an
[Agent Client Protocol](https://agentclientprotocol.com/) mode, use
`~/ops/site-private/bin/acp-run` instead of the per-CLI forms below. It
speaks ACP to the agent over stdio, so permission requests come back to the
caller, tool calls arrive typed, and usage is reported, instead of scraping
text and passing `--yolo`-style flags.

```
acp-run <agent> -C <dir> (-p PROMPT | -f FILE | stdin) --model M \
        [--mode M] [--perm all|deny|scoped:P1,P2] [--timeout S] [--log PATH] [--json]
acp-run --list              # agents and the command each runs
acp-run <agent> --info      # its models, modes and auth methods
```

- **Agents** (`--list`): claude (via the `claude-agent-acp` adapter), codex
  (via `codex-acp`), copilot, opencode, cursor, qwen, devin, cline, goose,
  hermes. Which ones currently work end to end, and what the others need, is
  in `site-private/memory/feedback_prefer_acp_for_delegation.md`; check
  there, not here.
- **Output:** final message on stdout; one summary line on stderr (stop
  reason, seconds, tool calls, permissions allowed/denied, tokens, cost, log
  path); full JSONL event log under `~/.local/state/acp-run/` unless
  `--log` names one. Exit 0 = end_turn, 1 = error/other stop reason,
  124 = timeout (it sends `session/cancel` first).
- **Always pass `--model`.** Without it the agent uses its own default; for
  the claude adapter that is the settings model, which cost about 6× a
  `--model sonnet` run on the same task. `--info` lists valid values.
- **`--perm`:** `scoped:<paths>` allows reads, searches and commands, and
  allows edits only under the listed paths (relative to `-C`); `deny` refuses
  every request (read-only review). Only agents that ask are bound by it:
  copilot and cline ask; claude, cursor and opencode follow their own
  settings and mostly auto-allow, so pick a stricter `--mode` (see `--info`)
  when that matters, and check the diff afterwards.
- **Exit 0 is still not success.** An agent can end its turn normally with a
  provider error as its reply. Verify the outcome (tests, diff, a real
  review in the output) exactly as for the headless forms.
- cline's ACP mode defaults to its paid `cline` provider and ignores the
  TUI's ClinePass setting, so acp-run always sets `provider=cline-pass`
  (generic form: `--set <config-id>=<value>`, ids from `--info`).
- cline bills ClinePass and claude bills the orchestrator's own pool: see
  *Reserve pools* below before sending either bulk work.

### Knowing when a delegated call finished

Run each delegation (`acp-run ...` or a per-CLI form below) as a **foreground
command in its own Bash call with `run_in_background: true`**, with no trailing
`&`. The harness then re-invokes you when it exits. A shell-`&` job is not
tracked and finishes silently (tested 2026-10-03); a wait loop built on
`pgrep -f '<pattern>'` matches itself and never ends. ACP does not change this:
`acp-run` is an ordinary command, and ACP only makes its exit code (0, 1, 124)
and stop reason reliable. Full recipe: `bigteam` Step 4.

### Per-CLI headless forms (no ACP mode, or fallback)

agy, zcode, crush, muse and the grok TUI have no ACP server mode, so they
keep these forms. The rows for ACP-capable CLIs stay as a fallback for when
an ACP route is broken.

**Authority for launch flags:** Orca's roster,
`~/Library/Application Support/orca/profiles/local-default/orca-data.json`
→ `settings.agentDefaultArgs`. That map is what actually works on this
machine for every enabled TUI (codex `--dangerously-bypass-approvals-and-sandbox`,
antigravity `--dangerously-skip-permissions`, copilot/cursor/crush `--yolo`,
grok `--permission-mode bypassPermissions`, …). Read it instead of guessing
flags. Standing rule (frontier-ai-review-stack memory): prefer a TUI's
official headless mode, or a maintained orchestrator (Orca
`worker-start --agent <name>`, see the `orchestration` skill), over a
hand-rolled subprocess wrapper.

When a direct one-shot call is still the right tool (a single review of a
diff), these forms are verified 2026-09-20. Every one runs with **stdin
closed** (`< /dev/null`) and output redirected to a file; backgrounding a
TUI with `&` inherits the harness's stdin and codex blocks on it forever.

| TUI | Verified headless form | Failure mode seen |
| --- | --- | --- |
| codex (GPT-6 Astra default) | `codex exec -s read-only -C <dir> "<prompt>" < /dev/null > out 2>&1` | without `< /dev/null`: prints `Reading additional input from stdin...` and hangs with no timeout. |
| agy (Antigravity) | `agy --dangerously-skip-permissions -p='<prompt>' < /dev/null > out 2>&1` — **attach the prompt with `-p=`**, which is order-independent and cannot be confused with a flag. `-p`/`--print`/`--prompt` is a *required-value string flag*, not a boolean. | `agy -p` with no value: exits 2, `flag needs an argument: -p`. `agy -p --effort high` (value-less `-p` before another flag): **since 1.1.18 this is a clean exit 2** naming the mistake — *"-p took \"--effort\" as its prompt…"* — and before 1.1.18 it silently ran with `--effort` as the prompt. Verified on 1.2.16, 2026-10-03. Headless still needs `--dangerously-skip-permissions` or tool permissions auto-deny (by design, hardened in 1.2.15). |
| copilot | `copilot -p "<prompt>" --model auto --allow-all-tools --allow-all-paths --silent < /dev/null > out 2>&1` | fine as-is. **Do not add `--reasoning-effort` with `--model auto`**: exits 1, `Model "auto" does not support reasoning effort configuration` (2026-09-26). Name a concrete model if you want an effort level. |
| opencode (free Go bundle) | `opencode run -m opencode-go/<model> "<prompt>" < /dev/null > out 2>&1` — e.g. `opencode-go/deepseek-v4-pro`, `opencode-go/gpt-6-luna`, `opencode-go/kimi-k3` (all answered 2026-09-26; `opencode models \| grep ^opencode-go/` lists 33). | **`opencode/<model>` is the prepaid Zen catalogue, not Go**: every `opencode/*` model except `big-pickle` fails with `Upstream request failed: Insufficient account funds`. `big-pickle` answers but on a review prompt spent its run trying to install pytest and returned nothing — steer it with "do not run tests or install anything". **Side effect:** every `opencode run` rewrites `./opencode.json` in the cwd (adds a `$schema` key) — `git checkout -- opencode.json` afterwards in repos that track it. |
| cursor-agent | `cursor-agent -p --trust --output-format text "<prompt>" < /dev/null > out 2>&1` | without `--trust` (or `--yolo`/`-f`) in a directory Cursor hasn't trusted: exits 1 with a "Workspace Trust Required" prompt and no review. |
| zai (zcode) | `zcode -p "<prompt>" < /dev/null > out 2>&1` — `-p` already defaults to `--mode yolo`; `--attach <file>` works (verified 2026-09-30). Inlining the file into the prompt is equally fine. | **Never pass `--mode build` (or `--mode edit`) headless**: it gates every tool behind an approval no one can give, so the run hangs indefinitely — process alive, ~0 CPU, no `zcode-cli` worker doing work, zero output — until it's killed (seen 2026-09-30, `--mode build --attach`). The default yolo mode auto-approves. The `ZCode Built-in skipped (not-due)` lines on stderr are a benign memory-heartbeat, not an error. |

Where DeepSeek lives on this machine (probed 2026-09-26): free —
`opencode-go/deepseek-v4-pro` / `-v4-flash` / `-v4.1-flash` (Go bundle)
and `sipb/deepseek-r1:{8b,14b,32b}` (MIT-hosted); paid —
`opencode/deepseek-*` (Zen prepaid), `clinepass-deepseek`
via LiteLLM :4000 (ClinePass, a reserve pool), and the `deepseek`
prepaid account. Check `aiuse` for what is left in each. z.ai serves GLM, not DeepSeek.

Rules that fall out of this:

- Exit 0 is not success. Append `echo "<tool> exit=$?"` to each output
  file and treat a file holding only a preamble line as a failed run.
- Prefer the read-only sandbox where one exists (codex `-s read-only`).
  Where it does not (agy), check `git status --porcelain` afterwards;
  agy left an empty `graft/` directory in the repo on one run.
- One background Bash call per batch with a long timeout, never chained
  `sleep`s; read each output file when the batch notification arrives.
- A reviewer that returns exit 0 with no findings is a failed run, not a
  clean bill: check the file has an actual review before counting it.
- Run reviewers against a stable tree: don't edit the file under review
  while they read it. For a second round after fixes, tell them what the
  first round found and fixed, so they verify rather than repeat.

Herdr-hosted TUIs (driving agents in Herdr panes; verified 2026-09-26):

- `herdr workspace create` returns before the pane's shell is up;
  `herdr agent start` a moment later fails `agent_pane_busy: … is not an
  available shell`. Poll `herdr pane read <pane>` for a shell prompt (`$`)
  first — ~2 s.
- Key names are `ctrl+c`, `enter`, `esc` (`ctrl-c` → `invalid_key`).
- `herdr pane read` prints plain text; every other command prints one JSON
  envelope, `{"error":…}` **with exit 0** on failure — parse the envelope.
- `herdr agent prompt <target> "/exit"` cleanly ends a Claude session and
  returns the pane to its shell; `bin/herdr-sleeper` in djbclark-ade
  builds on this (see docs/agent-sleep.md).

## Routing method

1. Free and chronically-unused subscription pools first for bulk work —
   aiuse's history section names them (historically: antigravity,
   opencode-go, copilot, cursor).
2. Claude/codex for judgment and agentic work; tier inside them (haiku/
   low for mechanical, fable/xhigh for hardest adjudication — Fable has
   its own weekly bucket).
3. **Reserve pools: never run them out.** clinepass (Hermes runs on it
   via LiteLLM :4000) and the `grok` TUI's SuperGrok pool (GrokBot runs on
   it). Both can be used, carefully. Grok *models* through another TUI bill
   that TUI's pool instead. Claude gets the same care:
   use it, but orchestration runs from it, so an empty Claude window stops
   every other agent too. Detail: the `bigteam` skill's *Reserve pools*.
   Never prepaid without an explicit fresh operator decision.
4. Levers: `acp-run <agent> --model <m> [--mode <m>]` for one-shot calls
   to ACP-capable agents (`--info` lists the values); Claude workflows
   `agent(..., {model, effort})`; Orca
   `worker-start --agent <any enabled TUI> --model --effort`; codex
   `model_reasoning_effort`; the per-CLI flags in the headless table for
   non-ACP CLIs.

Standing orders that pair with this: continuous operation over handoff
rituals; flag best-practice deviations to the operator (site-private
memory).
