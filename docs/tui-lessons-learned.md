# Agent TUI retirement: lessons learned (2026-11-04)

After consolidation, this file is the lasting record of the agent TUIs retired or never adopted on
this machine: what they were for, why they left, the gotchas worth remembering, and where their
support lived. The keep/retire map starts from the consolidation plan ("the plan": PR 283,
`docs/tui-consolidation.md` at commit `2c22ba5b`, snapshot 2026-11-04 10:10-10:40 EST) and is
**superseded where djbclark's rulings of 2026-11-04 differ** ("the rulings"): **pi folds into omp;
cline retires** (ClinePass may live outside the Cline client). Evidence pointers are repo-relative
paths, commits/PRs, or dated sessions; private memory notes are restated as technical lessons only.

## A. Scope

Retired, folded, or not adopted (plan §D + rulings 2026-11-04):

1. **A1 `zcode`** — fold into opencode (D1): Z.ai lists OpenCode for the GLM Coding Plan; zcode
   cost ~45 code files and had no native Paseo provider.
2. **A2 `copilot` CLI** — fold into opencode (D2): since 2026-10-30 the Copilot Pro pool is
   GitHub-use / explicit-request only; ruling "D2 yes, keep a fallback" (which fallback, the CLI or Paseo's Copilot provider, is still open on 2026-11-04).
3. **A3 `crush` (+ `crush-acp`)** — retire (D3): local build of unmerged charmbracelet/crush#2450;
   SIPB models already on opencode's `sipb` provider.
4. **A4 `venicecode`** — retire (D4): upstream archived 2026-08-31; OpenCode has a `venice`
   provider; Venice API barely funded / disabled in aiuse.
5. **A5 `dsh`** — do not adopt (D5): DeepSeek Harness developer preview with promised breaking
   changes; DeepSeek V4 already on OpenCode Go.
6. **A6 `qwen-code`** — retire (D7): Alibaba coding plan disabled in aiuse; zero slices; opencode
   already has `alibaba` / `alibaba-cn`.
7. **A7 `goose` / `goose-scout`** — retire again (D8): operator 2026-10-03 removal; Scout return
   ran nothing; Bedrock via opencode if needed.
8. **A8 `muse`** — retire, pending djbclark's answer to H5 (D9 asked "is there a use for it?"): disabled in
   aiuse since 2026-10-08; only non-ACP headless TUI; zero slices.
9. **A9 `aider`** — retire (D10): no ACP, no Paseo, no slices; opencode covers the job.
10. **A10 `kiro-cli`** — retire (D11): operator 2026-10-25 never-route; acp-run row already `--`.
11. **A11 `devin`** — retire (D12): binary gone; wrapper and `--` row left; ACUs disabled in aiuse.
12. **A12 `pi`** — fold into omp (ruling 2026-11-04): OpenAI API pool moves to omp; port pi's
    fail-closed capacity gate and subagent model/thinking overrides (ruling 2026-11-04).
13. **A13 `cline`** — retire (ruling 2026-11-04): ClinePass is allowed outside Cline; Dann's
    substrate leg moves to omp + cline-pass; `paseo-new-seat`'s `--provider cline` default must
    move.

Kept (rulings 2026-11-04): **`claude`** (only Max client, plan B1), **`codex`** (`local-review` +
ChatGPT pool), **`agy`** (only Antigravity client, B3), **`cursor-agent`**, **`grok`**, **`omp`**
(multi-vendor API-credit harness: Anthropic and, after the pi fold, OpenAI), **`opencode`** (open
multi-provider harness; keep both omp and opencode per ruling 2026-11-04), **`hermes`** (messaging
gateway, never a coding target).

## B. Cross-cutting lessons

1. **B1 A flag's name is not its behaviour.** `acp-run --perm deny` set no restrictive mode for
   several agents until 2026-10-12; a canary created a file with zero permission requests. Verify
   tool boundaries with a canary (`touch` in an empty `-C`), and put the verification in the brief,
   not only the flag name. Evidence: crush findings in `docs/queue.md` (~1200–1216); session
   2026-10-12 ACP permission audit.
2. **B2 Third-party ACP adapters are supply-chain surface.** Registry id `antigravity-acp` is
   Google's proprietary binary, not the community Bun adapter of the same name; `zcode-acp-server`
   is broader than a protocol shim. Static-source vetting (2026-10-03) still missed
   npm-tarball-vs-source gaps and opaque vendor child binaries. Prefer vendor-native ACP; treat
   community adapters as supply chain.
3. **B3 OAuth churns; store the key, scrub the env.** Daily OAuth logout on one vendor TUI was
   fixed by writing a stored API key into the client's credential format and never re-running
   interactive login afterward. Wrap launches in `sudo-secretspec run`, then scrub unrelated
   provider env (e.g. `AWS_*`) so the TUI does not auto-bind the wrong backend. A vendor credential
   store can outrank process env — sync the store, not only the env (dsh, 2026-11-04).
4. **B4 TUIs write junk into the repo and home.** Examples: `.zcode/` sandbox under `-C`,
   `.crush/crush.db`, `.aider.*`, rewritten cwd config, large session DBs (tens to hundreds of MB).
   Run `git status --porcelain` after batches; use per-run data dirs; keep credential path
   exclusions in `bin/ade-backup-stores` after binaries go (plan §G3).
5. **B5 Quota failures arrive as prose inside a normal end_turn.** Encoding and timezone differ per
   vendor (e.g. zcode `1310` weekly limit with a Beijing-time reset; copilot premium text
   JSON-escaped in session-log events). Classify at the source (`fail=quota` + reset), preflight
   before launch, and decide from `remaining_percent`, never bare `used_percent`. Commits
   `61f22572`, `5b789b5f`; `skills/bigteam/SKILL.md` failure table.
6. **B6 Model-id and catalog drift is normal.** Catalogs can be per-account; tool snapshots fail
   open after upgrades; effort lists differ between TUI UI and API. Read back every knob
   (`applied:` line, measured context) and fail as `config` on mismatch.
   `tools/acp-run/README.md` (copilot / qwen / zcode sections).
7. **B7 Burst limits are per-client and invisible to quota meters.** agy hit RESOURCE_EXHAUSTED
   across models while aiuse still showed headroom; in-process retries then `--print-timeout` exit
   0 with partial output. Stop, read the CLI's own log; do not loop probes.
   `skills/bigteam/SKILL.md` failure table (kept TUI; same vetting round as zcode).
8. **B8 Headless: close stdin, redirect output, check content — exit 0 proves nothing.** Inherited
   stdin hung one client; another exited 0 with empty review (auto-denied permission); copilot
   exited 0 with the answer only in a footer / resume id. Treat empty capture as unverified.
9. **B9 A fork is a nightly subscription.** `crush-acp` (unmerged PR) and `venicecode` (archived
   upstream rebuilt every night) cost upkeep for 2 and 0 dispatches. Standing order 8: upstream or
   drop (plan §D3, §D4).
10. **B10 Removal must be enforced — retirements have already regressed.** crush removed
    2026-10-08 came back 2026-10-11; goose removed 2026-10-03 came back as goose-scout ~2026-10-24
    (ruling 2026-11-04). Uninstall-by-omission fails when `brew-fast-upgrade` passes, shell wrappers,
    Paseo providers, `skill-everywhere` targets, acp-run rows, `failover.py` rows, skillopt-night
    allow lists, or `routing.toml` extras reinstall. Removal needs something that **stops drift
    back** (enforcement flag / deny list), not only a one-shot delete (plan §G4).
11. **B11 Never bridge a subscription into a client the vendor did not ship.** Anthropic
    (2026-04-04) and Google (Antigravity clause 6) suspend for it; Cursor ToS §1.5 forbids
    omp/opencode holding an active Cursor credential (staff note 2026-08-10). Same pattern covers
    Venice web-session proxies (plan §F4). Ruling D3: add an acp-run guard refusing omp/opencode
    runs while a Cursor, Antigravity, or Anthropic-subscription credential is active in them.
12. **B12 Attribute pools to TUIs only from the operator or the vendor's mapping.** crush was
    wrongly labelled ClinePass then zai before operator correction; model-routing keeps a per-pool
    "only client" column (plan §B). Billing is tracked by **vendor** (FOCUS `InvoiceIssuerName`),
    not by TUI brand — one TUI may serve several vendors (ruling 2026-11-04; see C7).
13. **B13 Weak models need harness guards, not better prompts.** Repeat-tool-call stops and
    bounded digests before small-context models (crush/SIPB, goose/Scout) belong at the harness
    layer for any small-context route on a kept TUI.
14. **B14 First contact may be slow by design.** One-time model downloads need per-agent
    handshake timeouts, not a global short default (kiro, 2026-10-25).

## C. Money and quota

1. **C1 Three Anthropic money surfaces (2026-11-04).** (a) Console **API-credit grant** for the
   org linked to the API key — what omp's Anthropic Messages API can spend; (b) claude.ai Usage
   **cloud-session / Usage-credits** meters; (c) Console **tier spend caps**. Confusing (b) for
   (a) made aiuse report a large "Claude API credits" balance while omp API calls returned HTTP
   400 "Your credit balance is too low…" (billing sessions 2026-11-04; aiuse historically keyed
   `window_id: claude-cloud-credits`, commit `02c0eb8` on 2026-10-15).
2. **C2 Reported billing facts that disagree — leave unresolved.** Session **23adbb25** (2026-11-04):
   real omp grant is the monthly Console API credit (~$200/month example), linked 2026-10-13, next
   credit 2026-11-06, **currently spent**; CodexBar Platform picked the wrong Console org; cloud-
   session ~$249/$250 was the wrong meter labelled as API credits. Session **501a7e0d** (rulings):
   the `$250` cloud-session row is a **one-time** Claude Code cloud-session credit (Max), spendable
   only through `claude --cloud` / claude.ai/code, expiring 2026-11-04 23:59 PT, which omp can
   **never** spend; monthly API credit exists only after **one** Console org is linked at
   Settings → Billing → API credits (one link per plan). Both agree cloud-session ≠ omp spend and
   that org pinning matters; they differ on grant size/schedule, one-time vs monthly framing of the
   $250 row, and exact empty-grant timing. Treat both as reported; do not pick a winner in this
   doc — consolidation verifies against the Console UI after the aiuse fix lands.
3. **C3 "Credit balance is too low" ≠ Claude Code OAuth quota.** The 400 is Console API prepaid
   for the key's org. Claude Max subscription quota is a separate surface spent only by `claude`
   (plan B1). Route and preflight must treat the billing 400 as quota/exhausted, not opaque
   `preflight` that skips `note-exhausted` (billing session 2026-11-04).
4. **C4 Pin the Console organization.** Multi-org CodexBar may pick the first readable Console
   org, not the one linked to omp's key (CodexBar#4654). Configure `[credits.omp] organization`
   (and grant clock fields) after the aiuse `claudeplatform` collector lands (billing sessions 2026-11-04).
5. **C5 Route off a live probe, not only a reading.** Until measurement and preflight agree, a
   high aiuse headroom can keep offering omp while the API refuses. Prefer: corrected aiuse omp
   row **plus** a live probe that maps billing 400 → `note-exhausted` with a sensible reset.
6. **C6 Subscription OAuth in a third-party harness (omp, until 2026-11-03).** omp's only active
   Anthropic credential after 2026-11-03 is an API key; its subscription OAuth login was disabled
   that day. Until then, omp's ~1,077 slices that month drew on the Claude Max **weekly** pool
   through OAuth — third-party-harness use Anthropic forbids since 2026-04-04 (billing session 2026-11-04;
   plan B1/F4). omp also held Cursor, Copilot, Antigravity, Codex, Go, Z.ai and xAI logins (used
   ~2026-08-20..10-13, deleted 2026-10-13); Copilot premium through omp reportedly exceeded 100%.
   Lesson: disable foreign subscription OAuth in omp/opencode; enforce with the acp-run guard in
   B11 / ruling D3 — do not rely on docs alone.
7. **C7 Billing is tracked by vendor, not by TUI.** The company money goes to (FOCUS
   `InvoiceIssuerName`) owns the pool; one TUI may spend several vendors' credits (omp: Anthropic
   API + OpenAI API after the pi fold). Brands label clients; vendors label invoices (ruling 2026-11-04).
8. **C8 Vendor-locked plans (plan §B).** Claude Max → `claude` only (B1). Google AI Pro → `agy`
   only; never OAuth plugins in opencode (B3). Cursor → Cursor clients (B4). SuperGrok → `grok`
   (B5). ChatGPT stays on `codex` here because `bin/local-review` needs it (B2). Z.ai GLM and
   Copilot Pro officially support OpenCode (B6, B7). Never install subscription-bridge plugins
   (F4). Keep both **omp** and **opencode** (ruling 2026-11-04).
9. **C9 Fixture dollars that match a known-wrong UI meter are a smell.** Tests that encoded the
   cloud-session $250 row as the omp success case locked in the wrong wallet (billing session 2026-11-04). Re-probe
   before acting (standing order 4).

## D. Per retired TUI

### D1. zcode (Z.ai GLM Coding Plan)

1. **D1a For / why.** Only local client for the `zai` pool (54 dispatches / 30d); folds because
   OpenCode is an official GLM Coding Plan client with `zai-coding-plan` (plan D1).
2. **D1b Gotchas.** Daily OAuth expiry → manual API-key auth source via `bin/zcode-key-auth`, never
   `zcode login` after; non-selectable API-key providers; `--model` needed `ZCODE_BIN` → package
   `vendor/zcode.cjs`; backend ignored `--disallowed-tools` → denylist shim + per-run settings
   strip; `--mode build|edit` hangs headless; quota `1310` reset in Beijing time; model ids use
   `builtin:zai-coding-plan\GLM-…`; `.zcode/` under `-C`. Commits `52c15328`, `72c797d4`,
   `451b65be`, `4a6e4d59`, `efb49107`; `tools/acp-run/README.md` zcode section;
   `docs/model-routing.md` (~428–439).
3. **D1c Replaced by.** `acp-run opencode --model zai-coding-plan/…` after G2 proves the Coding
   Plan window moves (not an API balance). Keep session-store harvest in `bin/skillopt_sources.py`
   until history is done (G3).
4. **D1d Where it lived.** Heaviest: `tools/acp-run/acp-run`, `bin/acp-dispatch`,
   `bin/zcode-key-auth`, `bin/skillopt_sources.py`, `bin/ade-backup-stores`,
   `skills/model-routing/SKILL.md`, `skills/bigteam/SKILL.md`, `config/routing.toml`, many
   `tests/test_acp_*` / `test_ade_backup_stores.py`; also aiuse collectors/models and
   site-public `brew-fast-upgrade.sh.j2` (inventory 2026-11-04).

### D2. copilot CLI (Copilot Pro)

1. **D2a For / why.** Local CLI for Copilot Pro (31 dispatches); pool stays for GitHub review /
   explicit request; CLI folds to opencode `github-copilot` with a fallback kept (ruling D2).
   Device-login vs `sudo-secretspec` `GITHUB_TOKEN` for that provider is still unverified (plan
   D2).
2. **D2b Gotchas.** `--allow-all-tools` can disable itself and hang without a TTY; autopilot may
   end with only `task_complete` (empty `--json` text → `text_source=task_complete`); exit 0 with
   answer off-stream; premium exhaustion in session-log events; **per-account** catalog (run
   `--info`); `set_config_option model` resets context tier; stale package cache under
   `Library/Caches/copilot/pkg` (2026-08-23). Commits `3762f342`, `5b789b5f`, `c2b66a82`;
   `tools/acp-run/README.md` (~378–382).
3. **D2c Replaced by.** GitHub-side Copilot for review; opencode on explicit request after trial.
4. **D2d Where it lived.** Same acp-run / acp-dispatch / routing / bigteam / failover / skillopt
   surfaces as other ACP TUIs; inventory: distinguish `copilot-cli` from `copilot:pool` (pool
   collectors and review docs stay). Heaviest shared file: `tools/acp-run/acp-run`.

### D3. crush + crush-acp (SIPB)

1. **D3a For / why.** Charm Crush for mit-sipb-llms via local ACP fork; 2 dispatches; retire for
   unmerged upstream + opencode `sipb` (D3). Regression exemplar: removed 2026-10-08, returned
   2026-10-11 (B10).
2. **D3b Gotchas.** Project `crushrc` runs as shell; MCP not covered by `disabled_tools`;
   deny-mode excluded 2026-10-14; `--model` needs private data dir; config arrays **append** →
   two-layer strip; auto-loads `AGENTS.md`/`CLAUDE.md` (~32k) → `bin/crush-context-check`; pool
   attribution wrong twice (B12). `tools/acp-run/README.md` crush section; `docs/queue.md`
   (~1200–1216).
3. **D3c Replaced by.** `acp-run opencode --model sipb/qwen3.6:35b-a3b-q4_K_M` (SIPB agent-task
   pin, commit `b607dfb2`; `docs/model-routing.md` ~222). Keep digest-before-small-context for
   kept small-context routes.
4. **D3d Where it lived.** `tools/acp-run/acp-run`, `tests/test_acp_run_crush.py`,
   `bin/crush-context-check`, `bin/ade-backup-stores`, session-history adapters, routing/skills;
   site-public `bin/s1_crush.py`; crush-acp source tree outside ade (G4).

### D4. venicecode (Venice API)

1. **D4a For / why.** OpenCode fork for array-content / Venice; wired 2026-11-04 session then
   retired (archived upstream, disabled Venice plan, native `venice` provider) (D4).
2. **D4b Gotchas.** `sudo-secretspec run` injects all secrets → strip `AWS_*` or Bedrock hijacks;
   OpenCode v2 singular dir names (`plugin`, `command`); isolated config dir +
   `OPENCODE_DISABLE_DEFAULT_PLUGINS`; never web-session bridge plugins (B11). Parallel
   clipboard secrets-collect races clear the pasteboard (session 2026-11-04).
3. **D4c Replaced by.** opencode `venice` + `VENICE_API_KEY` via secretspec if re-enabled; add
   aiuse collector then.
4. **D4d Where it lived.** Thin in ade (mostly doc); site-public `brew-fast-upgrade.sh.j2` and
   upgrade wrapper; machine paths under G4.

### D5. dsh (DeepSeek Harness)

1. **D5a For / why.** Official DeepSeek harness trial 2026-11-04; not adopted (preview, weak ACP,
   API disabled, V4 on Go) (D5).
2. **D5b Gotchas.** pnpm global link farm can leave darwin-arm64 native addon unlinkable (~12 KB
   `attempts[]` dump) — repair script + upgrade-pass pairing; npm `-g` hits `EBADDEVENGINES`;
   credential YAML outranks env; YOLO is `DSH_PERMISSION_MODE=danger-full-access` + profile patch;
   PATH prepend shadows wrappers → absolute-path shell function (dsh session 2026-11-04; site-djbclark
   commit `3913c57`).
3. **D5c Replaced by.** OpenCode Go DeepSeek models; no ade routing row.
4. **D5d Where it lived.** ade docs only; site-public `bin/dsh_repair_native_binding.py`,
   brew-fast-upgrade template; machine wrappers/profiles are G4 material after operator yes.

### D6. qwen-code (Alibaba coding plan)

1. **D6a For / why.** Client for dashscope coding-intl; plan disabled, 0 slices → retire (D7).
2. **D6b Gotchas.** No `--auth-type` flag (authType in `settings.json` / `--info` suffix); effort
   must be a listed `reasoning_effort` or exit 2; TUI `/effort` wider than API; `--context` exits
   2. Fail-fast on bad knobs is the pattern to keep. `tools/acp-run/README.md` (~410–420).
3. **D6c Replaced by.** opencode `alibaba` / `alibaba-cn` if the plan returns.
4. **D6d Where it lived.** acp-run, routing, skill-everywhere, skillopt/failover-style adapters;
   inventory: split `qwen-cli` vs `qwen:model` (model names stay).

### D7. goose / goose-scout

1. **D7a For / why.** Bedrock Llama 4 Scout via ACP wrapper; never stable; removed 2026-10-03,
   crept back ~2026-10-24, retire again (D8; B10).
2. **D7b Gotchas.** ACP `chat` mode still ran shell; Scout tool-call loops needed a proxy callback
   (rules prepend + repeat stop); Desktop cask resurrected via ansible until
   `goose_desktop_enabled=false` enforced absence; LiteLLM alias removal does not revoke keys;
   Bedrock key deactivated 2026-10-29 → 403 even if ENABLED. Commit `6332ef05`; acp-run goose
   section.
3. **D7c Replaced by.** opencode Bedrock provider if needed; proxy-callback guard pattern kept
   conceptually for weak models (B13).
4. **D7d Where it lived.** acp-run, skills (session-finder/helm/etc.), site-public goose role /
   docs, aiuse mentions; Paseo provider disabled.

### D8. muse (Meta Muse Code)

1. **D8a For / why.** Non-ACP headless TUI; models also via opencode-go `muse-spark-*`; disabled
   in aiuse; retiring by default unless djbclark names a use (H5 still open on 2026-11-04).
2. **D8b Gotchas.** None operational (0 slices). Session store and unversioned local binary noted
   in inventory docs (2026-10-19). Headless invocation discipline still applies (B8).
3. **D8c Replaced by.** Nothing required; opencode-go Muse-named models if wanted.
4. **D8d Where it lived.** Broad: aiuse `src/aiuse/collectors/muse.py` (130 lines), ade
   skill/doc/test rows, `bin/skillopt_sources.py`, backup-stores; drop from skill-everywhere in G1.

### D9. aider

1. **D9a For / why.** Generic API-key editor; 1 code file, 0 slices → retire (D10).
2. **D9b Gotchas.** `.aider.*` droppings join B4; nothing else harvested.
3. **D9c Replaced by.** opencode.
4. **D9d Where it lived.** Sparse: ade history/tests; site-public code/doc/history; stayturgid
   mentions.

### D10. kiro-cli (AWS Kiro)

1. **D10a For / why.** Trial 2026-10-25; operator never-route (D11).
2. **D10b Gotchas.** Workspace reads/edits without permission prompts → deny impossible (only
   `--perm all` + read-only brief + diff check); first `session/new` ~66 s downloading semantic
   search model → 120 s handshake; nested PTY hid the TUI from session-finder until argv
   discovery. Commits `e94b8dc4`, `4a9dfd0a`; `tools/acp-run/README.md` (~482–487).
3. **D10c Replaced by.** Nothing; never routed.
4. **D10d Where it lived.** acp-run row, routing `never_route`, docs/skills/tests; site-public
   brew-fast-upgrade / docs.

### D11. devin

1. **D11a For / why.** Autonomous PR-shaped work; deliberately dormant; binary gone (D12).
2. **D11b Gotchas.** Leaving a `--` acp-run row and stale "dormant" docs after binary removal is
   exactly what G1 cleans — retirement without registry hygiene.
3. **D11c Replaced by.** Nothing active.
4. **D11d Where it lived.** acp-run, routing, skill-everywhere, aiuse collectors/tests, skills/docs;
   wrapper-only on machine.

### D12. pi (OpenAI API credits → omp)

1. **D12a For / why.** Pi-family harness for the OpenAI measured API pool (first-class 2026-11-03,
   PRs #273–#280); plan kept it (C7) and asked H4 whether to fold later. **Ruling 2026-11-04:
   fold into omp** — one multi-vendor API harness. Barely exercised in dispatch (1 / 0 ok in 30d
   at plan snapshot); paid canary never verified (pi-support session 2026-11-03).
2. **D12b Gotchas / ports.** Pi ≠ omp with a rename: billing scopes, session identity, ACP
   `--perm all` only, env leakage (`OMP` exporting `PI_SESSION_*`) forced separate paths (pi-support session 2026-11-03).
   Pi fail-closed capacity without a fresh reading (`bin/acp-dispatch` `pi_capacity_refusal`); omp
   still fail-open — **port fail-closed for independent API pools** (ruling 2026-11-04; pi-support session 2026-11-03). Port
   subagent per-call model/thinking overrides + consent (`pi/extensions/subagent`). Shared
   `AGENT_GUARDS` / `EXACT_EXECUTABLES` already cover identity; scrub `PI_*` in tests (pi-support session 2026-11-03).
   Absolute worktree paths for edits (pi-support session 2026-11-03). Native reset/successor missing; compaction always
   refuses (pi-support session 2026-11-03).
3. **D12c Replaced by.** omp spending OpenAI API credits; keep history/fleet adapters until
   harvested; remove pi from skill-everywhere / acp-run after ports land.
4. **D12d Where it lived.** PRs #273–#280 touch ACP/routing, history/fleet, autorename bridges,
   `bin/agent_guard.py`, `skills/session-finder/fleet.py`, `pi/extensions/subagent`, docs; aiuse
   3.14.0 Pi `codex-api` scope. Heaviest classes: code + skill + test in ade (plan ~31 code files).

### D13. cline (ClinePass / Dann substrate)

1. **D13a For / why.** Plan C10 kept cline because Dann seats and `DANN_SUBSTRATE` failover used
   the Paseo `cline` provider (Hermes already reaches ClinePass via LiteLLM). **Ruling
   2026-11-04: retire the Cline client** — ClinePass is allowed outside Cline; move Dann's
   substrate leg to **omp + cline-pass**, and change `paseo-new-seat`'s default `--provider
   cline`. Stale `config/routing.toml` "TUI is uninstalled" comment was already wrong while cline
   3.0.74 was installed (plan D6).
2. **D13b Gotchas.** `discovery.never_route` / operator gate for slices stays relevant for the
   *pool*; do not mark `clinepass` retired in a way that drops it from `hermes_chain` in
   `bin/route_agent.py` (plan G1 warning). Substrate needs a second provider before removing the
   only failover leg — ruling names omp + cline-pass as that pair.
3. **D13c Replaced by.** omp (and opencode-go as needed) for ClinePass-shaped work; Hermes
   unchanged via LiteLLM.
4. **D13d Where it lived.** `bin/paseo-new-seat`, `bin/route_agent.py` (`DANN_SUBSTRATE`,
   `hermes_chain`), `config/routing.toml` / `[substrate].lifeline`, acp-run row, skill-everywhere,
   ~36 code files (plan A15); Paseo `cline` provider.

## E. Patterns worth keeping

1. **E1 Shared guard tables, then row flips.** `AGENT_GUARDS` / `docs/agent-guard-contract.md` and
   `fleet.EXACT_EXECUTABLES` make later TUIs a row flip, not a rewrite (pi/omp PRs 273–275;
   `bin/agent_guard.py`, `skills/session-finder/fleet.py`). Applies to every kept ACP TUI still
   marked `unreviewed`, and to the omp absorb of pi.
2. **E2 Scoped feature PR, separate same-family audit.** Pi first-class (#273) then omp audit
   (#274/#275) found different bugs (pi-support session 2026-11-03). Applies when porting pi → **omp**.
3. **E3 Env scrub in tests.** Autouse scrub of `PI_*` / related vars in `tests/conftest.py` (pi-support
   session 2026-11-03). Applies to **omp** while pi paths linger, then any dual-harness cleanup.
4. **E4 Absolute worktree paths.** Relative edits landed in the shared checkout during #276 (pi-support
   session 2026-11-03). Applies to every agent under order 9.
5. **E5 Manual auth-source / named-exception key writer.** Beats OAuth re-login loops; review rule
   3 exception shape (`bin/zcode-key-auth`). Applies when **opencode** (or omp) adds key-backed
   providers.
6. **E6 Denylist / allowlist shim at session create.** When the backend ignores config-level tool
   denial. Pattern for **opencode** plugins that ignore deny.
7. **E7 Isolated config + env scrub for a second identity of opencode.** One provider, one config
   dir, strip foreign cloud env (venicecode). Applies to **opencode**.
8. **E8 Repair script + upgrade-pass + `verify_clean`.** Native-binding drift after global package
   upgrades (dsh). Applies to any kept TUI with native addons under brew-fast-upgrade.
9. **E9 Fail-closed effort/context knobs.** Exit 2 naming valid values (qwen); read-back-by-tier
   (copilot context). Applies to **acp-run** for all kept TUIs.
10. **E10 Per-agent handshake timeout.** Slow first-contact downloads (kiro). Applies to any kept
    TUI with one-time setup.
11. **E11 Digest-before-small-context.** `web-digest-mcp` / skill-get for SIPB-sized windows.
    Applies to **opencode** SIPB routes.
12. **E12 Empty output + exit 0 → unverified.** Copilot/agy/codex headless. Applies to every kept
    headless path (**codex**, **agy**, **opencode**, **omp**).
13. **E13 Enforcement flags for retirement.** Config that *requires* absence (goose Desktop; B10).
    Applies when removing any TUI (G4).
14. **E14 Credential-presence guard on multi-provider harnesses.** Refuse omp/opencode while
    Cursor / Antigravity / Anthropic-subscription OAuth is active (ruling D3; B11/C6). Applies to
    **omp** and **opencode**.
15. **E15 Fail-closed capacity for independent API pools.** Port from pi to omp (ruling 2026-11-04;
    pi-support session 2026-11-03). Applies to **omp**.

## F. Adoption checklist for a new TUI

1. **F1** Name the quota pool only this client can spend, from vendor docs — else you add a TUI
   without retiring one (plan F3; B12). Track billing by vendor (C7).
2. **F2** Check the vendor's client policy for that pool before any adapter (Antigravity clause 6;
   Anthropic 2026-04-04; Cursor ToS §1.5; B11/C6).
3. **F3** Prefer native ACP; if third-party only, vet source **and** npm tarball vs source (B2).
4. **F4** No unmerged-upstream fork builds — wait or upstream (crush#2450; B9).
5. **F5** Canary the permission story in an empty `-C` (deny must deny, including MCP) (B1).
6. **F6** Classify quota-failure prose (reset time, timezone) and wire an aiuse collector or
   accept preflight guessing (zcode `1310`; B5).
7. **F7** Effort/context knobs read back; unsupported values fail closed (qwen/copilot; B6).
8. **F8** Auth via `sudo-secretspec run` + env scrub; check whether a local credential store
   outranks env (dsh; B3). Never leave subscription OAuth in a third-party harness (C6).
9. **F9** Isolate per-run config/data dirs (crush two-layer strip; venicecode; B4).
10. **F10** Inventory cwd/`$HOME` writes; add cleanup and backup-store exclusions before adopt
    (B4).
11. **F11** Measure headless end-to-end: stdin closed, output non-empty, ignore bare exit 0 (B8).
12. **F12** Budget upkeep across session-finder / helm / autorename / self-slash / failover /
    skillopt (zcode ≈ 45 code files; plan A10). Prefer folding into **omp** or **opencode** when
    the pool is not vendor-locked.
13. **F13** Plan removal while adopting: enforcement that stops drift back across upgrade passes,
    wrappers, Paseo, skill-everywhere, acp-run, failover, skillopt, routing (crush/goose; B10).
14. **F14** Do not adopt archived upstreams or previews that promise breaking changes (venicecode;
    dsh).

## G. Open items for the consolidation work

1. **G1 Pi → omp ports (ruling 2026-11-04; pi-support session 2026-11-03).** Land fail-closed capacity for independent API pools
   on omp (pi-support session 2026-11-03); port subagent model/thinking overrides; then drain pi rows. Residual shared
   hygiene: `session-find --all` maps `LIVE?` → `ended` (`docs/queue.md` ~118); `ACP_RUN_OMP_ANY_MODEL=1`
   agent-settable and `--agent-arg`-only scan (`tools/acp-run/acp-run` ~2602–2625); fix
   `bin/agent_guard.py` header test name; flip remaining `unreviewed` `AGENT_GUARDS` /
   `EXACT_EXECUTABLES` rows; scrub pi `failureDetail` stderr (pi-support session 2026-11-03).
2. **G2 Cline drain.** Move `paseo-new-seat` default off `--provider cline`; retarget
   `DANN_SUBSTRATE` to omp + cline-pass; remove cline from skill-everywhere / acp-run without
   cutting `clinepass` out of Hermes's chain (plan G1 warning).
3. **G3 Billing / routing (plan H7; billing sessions and rulings of 2026-11-04).** Land aiuse `fix/omp-promo-credits-only`;
   operator `[credits.omp]` org + grant clock; CodexBar cookies / org picker; map "credit balance
   is too low" → quota + `note-exhausted`; clear stale omp preflight `ok: true` caches. **Resolve
   C2** against the Console UI (23adbb25 vs 501a7e0d). Add acp-run foreign-credential guard (B11).
4. **G4 Operator / machine (order 11).** G4 uninstall list needs djbclark's yes. Whether to
   archive site-private memory notes after folding lessons here. Keep `bin/ade-backup-stores`
   credential exclusions as a named exception (plan G3). `feat/fleet-migrate` remains a successor
   with no PR (pi-support session 2026-11-03).
5. **G5 Plan questions closed or still open.** Closed by ruling: H4 (fold pi → omp) and H3 (cline
   retires). Still open: H5 (muse; retiring by default); operational: H1 roster now eight keepers — confirm
   in G1 docs PR; H2 dsh uninstall vs unrouted trial; H6 X Subscription wait; H7 after C2
   verification. Migration order unchanged in spirit: registry/docs → trials (GLM + SIPB via
   opencode) → re-point routing → machine removal after yes → plan decisions E1–E4. After drain,
   **this document** plus CHANGELOG/handoff history should be the only intentional mentions of
   the retired names (plan wave 4).
