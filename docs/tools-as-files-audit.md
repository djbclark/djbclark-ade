# Lead AI Dev Env Audit + Tools-as-Files / Code Mode

Queued 2026-11-17 (Carried 71). Start only after the current bug fixes land (fail-closed routing #776, Q3 sudo-secretspec export, docs #777, plus #773/#775). This page is the full spec; the queue line points here.

## Objective

Audit the ADE harness, MCP configuration, token/context overhead, and skill infrastructure; then design and implement a "Tools as Files / Code Mode" architecture so MCP tools and APIs are discovered lazily on disk and orchestrated via code execution, rather than injected as raw JSON schemas into every model context.

## Reference patterns (verified, to base the design on)

1. Anthropic "Code Execution with MCP" & programmatic tool calling: typed RPC wrapper modules on disk (`servers/<service>/<tool>.py|.ts`) instead of full JSON schemas; filter/join/aggregate large payloads inside code so raw outputs never enter the context; persist working multi-step scripts as `skills/<name>/SKILL.md` + `scripts/`.
2. Python/uv: `yoloshii/mcp-code-execution-enhanced` (auto Pydantic wrappers from `mcp_config.json`, lazy server connections, optional rootless Podman/Docker sandbox); `datalayer/agent-codemode` (async bindings under `generated/mcp/<server>`, `list_tool_names`/`search_tools`/`get_tool_details`, stateful Python blocks, reusable skills).
3. TypeScript/bun VM: `universal-tool-calling-protocol/code-mode` (`@utcp/code-mode-mcp`; cached TS interfaces, progressive search, VM-isolated `callToolChain`); `olaservo/code-execution-with-mcp` (typed TS wrapper tree + skills-ref frontmatter validation); `cloudflare/agents` Codemode (stateless Executor, typed Connectors with per-tool human-approval flags, Snippets).
4. OpenCode native integration: built-in bash/read/glob/grep + standard skill paths (`.opencode/skills/`, `~/.config/opencode/skills/`, `.claude/skills/`, `~/.claude/skills/`).

## Phase 1 — self-inspection and baseline audit (read-only)

Produce a concrete inventory of:

1. Harness/model routing: global + project OpenCode configs, LiteLLM proxy configs, AGENTS.md/CLAUDE.md/agent prompts; installed runtimes/isolation (uv, python3, bun, node, deno, podman, docker, just, ansible).
2. MCP/tool footprint: every configured server, transport (stdio/SSE/HTTP), tool count, estimated baseline schema token footprint per turn; which servers return large payloads (docs, logs, web scrapes, repo trees, databases) or need multi-step chaining.
3. Existing skills/automation: skill dirs, plugins, dotfiles/fleet repos, existing MCP wrappers — avoid duplicating infrastructure.

## Phase 2 — architecture proposal + approval gate

Compare and recommend one of:

- **Option A (Zero-MCP Shell SDK):** move heavy MCP servers out of active config into an offline registry; auto-generate typed uv/bun client wrappers under a shared local dir; progressive-discovery instructions in AGENTS.md; wrap repeatable pipelines as SKILL.md modules.
- **Option B (Single-Gateway Code-Mode MCP Proxy):** one lightweight proxy (`@utcp/code-mode-mcp` or `agent-codemode`) exposing only `search_tools`/`get_tool_details`/`execute_code`, isolating credentials + approval gates in the proxy.
- **Option C (Hybrid):** keep 1–2 ultra-low-latency native tools attached; route all bulk-data/multi-step MCP servers through A or B.

Include: exact directory layout (`mcp_registry.json`, `servers/`, `runtime/`, `skills/`); security/approval boundaries (credential handling, read-only vs mutating/destructive safeguards, optional container/VM sandbox); how changes persist cleanly into dotfiles/config management (not ad-hoc untracked edits).

**Pause after Phase 2 and ask the operator for confirmation before applying changes.**

## Phase 3 — implementation + verification (after approval)

1. Build the wrapper generator / code-mode runtime (uv or bun) so adding a server auto-regenerates typed wrappers without manual boilerplate.
2. Migrate high-token MCP servers off direct context injection, preserving an instant rollback path in config.
3. Update global AGENTS.md + a bootstrap SKILL.md: discover via filesystem/search → inspect typed signature → execute filtering script in one pass → save proven workflows as validated skills.
4. End-to-end benchmark task before vs after: prompt token count, tool round-trips, wall-clock latency — report measured savings (not estimates).
