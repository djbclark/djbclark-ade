# Disabled skills, plugins and MCP servers

What was switched off in Claude Code on 2026-10-10 to shrink the context every
session carries, what each item does, and how to turn any of it back on. Nothing
was uninstalled: every item below re-enables with one setting or one `mv`.

## Why

Claude Code loads every connected MCP server's instructions and tool names, and
every skill's description, into every session, and loads them again after every
`/compact`. A compacted session still held ~104k tokens, re-written at the
1-hour cache's 2x rate. Measured with `claude -p "/context"`:

| | Before | First pass | Final (end of 2026-10-10) |
|---|---|---|---|
| Fresh session total | 37.5k | 31.8k | 26.7k |
| MCP server instructions | 9.2k | 3.8k | 3.1k |
| MCP tools loaded up front | 5.7k | | 4.8k |
| Memory files (`~/.claude/CLAUDE.md` condensed 20.4 → 12.6 KB) | 8.6k | | 5.5k |
| Skills listing | 10k | | 10k |
| Deferred MCP tool schemas (loaded only on ToolSearch, but their names are always listed) | 751k | 107k | 105.5k |

The skills listing did not move although ~40 skill folders were moved out and 19
descriptions were shortened (10,958 → 6,706 chars). It is a budget: 1% of the
context window (10k on a 1M model), filled and then cut, least-used descriptions
first (confirmed 2026-10-18, code.claude.com/docs/en/skills).

### Second pass (2026-10-18)

The 10-10 trim grew back to 46.3k in eight days: CLAUDE.md edits, `bl skill
update` and the paseo CLI re-linking their skills, and two always-loaded
Firecrawl servers. Basis: `docs/claude-cache-cost-research-report.md` plus a
Fable review of it; the preamble was 17% of a week's Claude Code cost.

| | 2026-10-18 before | After settings changes |
|---|---|---|
| Fresh session total (in this repo) | 46.3k | 31.2k |
| MCP tools loaded up front | 11.0k | 0 |
| MCP server instructions | 4.8k | 3.4k |
| Skills listing | 10k | 7k |
| Memory files (global `CLAUDE.md` + this repo's `AGENTS.md`) | 14.5k | 14.7k (condense in progress) |

What changed, all in `~/.claude/settings.json` unless noted:

1. `deniedMcpServers` gained `claude.ai Firecrawl`, `claude.ai Google Drive`
   and `claude.ai Google Calendar` (table below).
2. `~/.claude.json` `mcpServers.firecrawl` has `"alwaysLoad": false`. The shared
   server marks `firecrawl_scrape`/`firecrawl_search` `alwaysLoad` in `_meta`; the
   client-side key overrides it (−6.1k). The first Firecrawl call in a session now
   needs one ToolSearch. Revert: delete the key.
3. `skillOverrides` and `skillListingBudgetFraction: 0.007` (section "Skills
   hidden by setting" below).
4. `autoCompactWindow` 400000 → 300000 (compaction fires at ~267k, the window less
   the 33k buffer). Simulated −1.6% of cost; a 200k window costs +1%, 150k +17%.
5. The graft per-prompt hook was back (table "Hooks removed"); removed again.
6. `claudeMdExcludes: ["/Users/djbclark/CLAUDE.md", "/Users/djbclark/AGENTS.md"]`:
   in `~`, `~/AGENTS.md` is the same file as `~/.claude/CLAUDE.md`, and it loaded
   twice (~8.4k extra). A fresh session in `~` fell from 39.9k to 27.4k.
   (`~/CLAUDE.md` is a dangling link to the removed `site-private/home-agents.md`.)

Kept: `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS` at its 200k default. Idle compaction
at 100k loses money below ~127k, given the ~104k floor a compaction leaves.

### Kept on purpose (2026-10-10)

1. **Firecrawl** (~5.6k tokens/session, the most expensive item left): ~250
   calls a week, the most-used web tool. Its two always-loaded tools
   (`firecrawl_search`, `firecrawl_scrape`) cannot be deferred from our side:
   `ENABLE_TOOL_SEARCH=true` was tested and changed nothing (the server most
   likely marks them `alwaysLoad` in `_meta`). The only untried route is a local
   http server entry with `"alwaysLoad": false` shadowing the claude.ai
   connector, which needs its own API key and sign-in. **Done 2026-10-18**: the
   shared self-hosted `firecrawl` entry got `"alwaysLoad": false` (honoured), and
   the claude.ai connector is denied.
2. **Context7** (~0.2k): agent-friendly library docs; re-check its use on or
   after 2026-10-24 (docs/queue.md).
3. **token-savior**: djbclark kept it although transcripts show 0 calls ever. **Removed 2026-10-18** (0 real calls in 14 days of 1,458 transcripts): deregistered from every agent CLI, `uv tool uninstall token-savior-recall`, launcher deleted.
4. **graft**: kept, but its tools now load on demand (`alwaysLoad` dropped from
   `.mcp.json`) and its per-prompt hook is gone. Measured over the week to
   2026-10-10: used in ~6% of sessions, and 64% of its answers were followed by
   a re-read of the same file; its "tokens saved" banner claimed 1.95M against
   ~71k tokens of actual output. **MCP registration removed 2026-10-18** (95 MCP
   calls vs ~24,000 CLI uses in 14 days; ~270 MB of per-session stdio processes):
   the `graft` CLI and graft's hooks stay.

That trims every request of every session, not just compacted ones. Background:
`~/ops/site-private/memory/feedback_self_compact.md` item 7. Re-add anything
you actually use; each item costs only a few hundred tokens per session.

Same day, same file (`~/.claude/settings.json`): `"promptCacheTtl": "1h"`
pins the 1-hour prompt cache for main conversations even when a session draws
on extra-usage credits, where Claude Code would otherwise drop to 5 minutes and
re-write the whole context after every 5-minute wait
(code.claude.com/docs/en/prompt-caching, "Which TTL each request gets").
`ENABLE_PROMPT_CACHING_1H=1` covers sub-agents and compaction too. **Do not
move anything to the 5-minute TTL** (simulated on 7 days of transcripts,
2026-10-18, `bin/claude-cost-whatif`): 5 minutes everywhere +30%, sub-agents
only (`CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL=5m`) +2.8%, because 3.2% of
requests follow a 5-60 minute gap and would re-write their whole context.

## MCP servers blocked in Claude Code (`deniedMcpServers`)

They stay available on claude.ai web and desktop; only Claude Code skips them.
Re-enable one: delete its `{"serverName": ...}` entry from `deniedMcpServers`
in `~/.claude/settings.json` (takes effect at once, even mid-session).
Claude Code reports these as "blocked by enterprise policy" / "blocked by the
organization's managed policy", at startup and in the model's context. That is
only its label for this user-level list; there is no org policy here (v2.1.303).

| Server | Tools | What it is |
|---|---|---|
| `claude.ai ElevenLabs` | 158 | Speech, voice design, image/video generation, ElevenLabs agents. The largest single item (~2.7k tokens). |
| `claude.ai Canva` | 41 | Create and edit Canva designs. |
| `claude.ai Figma` | 41 | Read and write Figma/FigJam designs, design-to-code. |
| `claude.ai Cloudflare Developer Platform` | 23 | D1, KV, R2, Workers, Hyperdrive. |
| `claude.ai Hugging Face` | 5 | Hub search, models, datasets, Spaces. |
| `claude.ai Slack` | 27 | Read and post Slack messages, canvases, lists. |
| `claude.ai Wolfram` | 3 | Wolfram Alpha / Wolfram Language. |
| `claude.ai Have I Been Pwned` | 2 | Breach lookups. |
| `cua-driver` (local, `~/.claude.json`) | 56 | Background computer-use driver; overlaps ghost-os, claude-in-chrome and bezalel `computer__*`. |
| `ghost-os` (local, `~/.claude.json`) | 29 | macOS accessibility-tree + vision computer use; overlaps cua-driver. |
| `claude.ai Claude Docs` | 8 | Anthropic's doc-authoring connector ("living docs you create and edit"), not API-doc lookup; 0 calls in all transcripts since 2026-08-03, ~1.3k tokens/session. Blocked 2026-10-10. |
| `paper-search` (local) | 57 | Academic search/download across arXiv, PubMed, SSRN, Semantic Scholar, OpenAlex and more; ~0.65k tokens/session, 3 calls in the week to 2026-10-10, all doable with the `arxiv` MCP, Firecrawl `firecrawl_research_*` or an OpenAlex `curl`. Blocked 2026-10-10. |
| `claude.ai Firecrawl` | 10 | The paid cloud Firecrawl, which global rule 7 already forbids (credits ran out 2026-10-15), yet it took 506 calls in the 14 days to 2026-10-18. ~5.4k tokens/session, two tools always loaded. The shared self-hosted `firecrawl` server does the same work for free. Blocked 2026-10-18. |
| `claude.ai Google Drive` | 11 | Drive files; 0 calls in 14 days. Blocked 2026-10-18. |
| `claude.ai Google Calendar` | 9 | Calendar events; 1 call in 14 days, and its tool fetch timed out in `claude mcp list`. Blocked 2026-10-18. |
| `bezalel` (local, `~/.claude.json`) | ~80 | djbclark's capability plane (email, cards, finance, memory, computer, connectors). The longest server instructions (~1.5k tokens/session); 8 calls in 14 days. Blocked 2026-10-18 by djbclark, pending a scope trim (Basic Memory todo "Trim bezalel MCP sub-services"); still used from other agents. |
| `siyuan` (local) | - | SiYuan notes. Fails to connect at every start (ECONNREFUSED) and had 0 calls; its skills were already `user-invocable-only`. Blocked 2026-10-18 (/doctor). |

Still on: Beeper (re-enabled 2026-10-16 by djbclark to watch the Hyades room), Gmail, Context7, Firecrawl (self-hosted, shared),
claude-in-chrome, basic-memory, arxiv, hermes, cow (token-savior and
graft's MCP server were removed 2026-10-18).

## Plugins disabled

| Plugin | How it was disabled | Re-enable |
|---|---|---|
| `adhd@adhd` | `enabledPlugins: false` | set it to `true` |
| `mattpocock-skills@mattpocock` | `enabledPlugins: false` | set it to `true` |
| `engineering`, `cowork-plugin-management` (synced from the claude.ai organization) | `"syncClaudeAiPlugins": false` (stops all claude.ai plugin sync; these were the only two) | remove the key or set it `true` |
| `composio@composio` | `enabledPlugins: false` (2026-10-18, /doctor). Its SessionStart hook (`composio dev toolkits list` plus `composio whoami` on every startup, resume, clear and compact) had a 3.8 s median, 48.8 s max, and 153 of 405 runs (38%) cut off at its 8 s cap; 0 `composio` CLI uses in 6 days. Its UserPromptSubmit hook goes with it; the `composio-cli` skill is `"off"` | set it to `true` and drop the `composio-cli` skillOverride |
| `claude-powerline@claude-powerline` | `enabledPlugins: false` (2026-10-18, /doctor): unused, since `statusLine` is `site-private/bin/claude-statusline`. The npm global `@owloops/claude-powerline` stays | set it to `true` |

## Hooks removed or narrowed (`~/.claude/settings.json` `hooks`)

Backups of the settings file before each change: none are kept in the repo; the
old entries are quoted here so they can be pasted back.

| Hook | Change | Re-enable |
|---|---|---|
| Superset notify (8 entries: SessionStart, UserPromptSubmit, PostToolUse, Stop) | removed; Superset itself uninstalled 2026-10-30 (see "Superset uninstalled" below) | none; reinstalling Superset re-writes them |
| graft per-prompt pack (UserPromptSubmit `node ~/.claude/helpers/graft-hooks.cjs prompt`) | removed: ~150-300 tokens on every prompt, kept in history, often unrelated to the prompt. **`graft init` re-added it; removed again 2026-10-18** (measured ~120 tokens, two of three hits off-target), and site-djbclark's `macos/graft-hook-timeout-fix/graft-hook-guard.sh`, which `graft-hook-timeout-fix.py` keeps on every graft hook, now skips the `prompt` event | add the entry back under UserPromptSubmit and set `GRAFT_PROMPT_HOOK=1` in `env` |
| graft alwaysLoad keeper (SessionStart `python3 ~/.claude/hooks/graft_mcp_alwaysload.py`) | removed, and `"alwaysLoad": true` dropped from the graft entry in `.mcp.json` of aiuse, kool-ade and tendcf: graft's 6 tool schemas (~880 tokens) now load on demand via ToolSearch. Measured: graft called in 6% of sessions, 64% of its answers followed by a read of the same file anyway | re-add the hook and the flag |
| rtk Bash rewrite (PreToolUse Bash `rtk hook claude`) | now `python3 "$HOME/.claude/hooks/rtk_hook.py"` (symlink to `claude/hooks/rtk_hook.py`), which skips the rewrite when cwd is under `.claude/worktrees/`: Claude Code's worktree-isolation guard refuses rewritten commands, so a worktree sub-agent couldn't run plain `git` (2026-10-12) | set the command back to `rtk hook claude` |
| cswap quota table (SessionStart `~/.claude/hooks/cswap_quota_context.sh`, ~950 tokens) | now `matcher: "^(startup|resume|clear)$"`: no longer re-injected after each compaction. Since 2026-10-18 it reuses `cswap list` output for 5 minutes (`~/.cache/cswap_quota_context.txt`; median was 2.4 s, 27 of 337 runs hit the 10 s cap) | drop the matcher; delete the cache block |
| graft project-scope hooks (djbclark-ade `.claude/settings.json`, written by `graft init` 2026-10-16 in aef5f51) | removed 2026-10-18: they ran every graft hook a second time next to the guarded user-level ones, and their UserPromptSubmit `prompt` hook bypassed the guard. site-djbclark's `graft-hook-guard.sh` now runs `graft-hook-timeout-fix.py strip-project "$CLAUDE_PROJECT_DIR"` on session-start, so a re-init in any repo is stripped at the next session (logged to `~/.local/state/graft-hook-timeout-fix.log`; skips `~/src/Graft`, and does nothing unless the user settings route graft through the guard) | `git revert` the djbclark-ade commit; add the repo to `KEEP_PROJECTS` in the fixer |

## Skills hidden by setting (2026-10-18)

Moving folders does not hold: `bl skill update` re-created the `bailian-*`
links and the paseo CLI the `paseo*` ones, both on 2026-10-18. `skillOverrides`
in `~/.claude/settings.json` does hold, whatever re-links the folder:

1. `"off"` (gone for the model and from `/`): the nine `bailian-*` skills,
   and `composio-cli` (its plugin is off too; /doctor 2026-10-18).
2. `"user-invocable-only"` (you can still type `/name`; the model no longer
   sees the description): `paseo`, `paseo-advisor`, `paseo-committee`,
   `paseo-handoff`, `paseo-help`, `paseo-plugin`, the five `ralph-tui-*`,
   `siyuan`, `siyuan-article-import`, `siyuan-excalidraw`, `siyuan-markdown`,
   `skillopt-sleep`, `skillopt-sleep-learned`, `terminus-kira`, `reorg-orca`,
   `setup-modern-cli`, `teach`. None was invoked by the Skill tool in the 14
   days to 2026-10-18. Added after /doctor the same day, also unused by the
   model: `dialogue`, `effort-routing`, `coderabbit-feeder`, `graft` (the
   `graft` CLI and its hooks stay) and `herdr-tidy`.

`"skillListingBudgetFraction": 0.007` caps the listing at 7k tokens. Past the
cap, descriptions are dropped least-used first; names stay. `/doctor` shows
which descriptions were dropped.

Re-enable a skill globally by deleting its key. For one repo only, add
`"skillOverrides": {"<name>": "on"}` to that repo's `.claude/settings.json`.

## Skill folders moved aside (2026-10-10, superseded above for bailian)

Moved from `~/.claude/skills/` to `~/.claude/skills-disabled/` (symlinks,
untouched otherwise). The targets under
`~/.agents/skills/` and `~/.bailian/skills/` stay, so Codex and zcode still see
the bailian and caveman skills; cursor-agent and muse, which read
`~/.claude/skills`, no longer do. Re-enable one:
`mv ~/.claude/skills-disabled/<name> ~/.claude/skills/` (new sessions pick it
up). The bailian skills are Aliyun Bailian/DashScope `bl` CLI wrappers (model
calls, image/video/speech generation, fine-tuning, managed agents, web search,
docs wiki); their descriptions are in Chinese. A second batch (caveman leftovers, a generic coding-discipline pack, the
ln-* reviewers, book-to-skill) followed the same day.

## Superset uninstalled (2026-10-30)

The Superset desktop app and CLI were not installed (no `superset`/`paradev`
binary, no app, no `~/.superset`), only their leftovers. Removed: the 14
`~/.agents/skills/superset-*` skills, `~/.agents/commands/superset`,
`~/.claude/skills/superset` and `~/.claude/skills-disabled/superset`; the notify
hooks in the Claude, Codex, Cursor, Gemini, Factory and Mastracode configs, the
Grok, Amp, omp and pi hook files; the `com.djbclark.superset-home-dir`
LaunchAgent and the `SUPERSET_HOME_DIR` blocks in `~/.bashrc`, `~/.zshrc` and
site-djbclark's `shell/bashrc` and `shell/zshrc`; the ShipIt updater plist.
Timestamps showed the skill and hook files re-written 2026-10-29 17:36 by an
unidentified writer; if they reappear, find that writer rather than deleting again.

## Every disabled skill

| Skill | Source | Description (from its SKILL.md, truncated) |
|---|---|---|
| `bailian-cli` | bailian (Aliyun `bl`) | 阿里云百炼 / Aliyun Bailian / DashScope 资源管理与 `bl` CLI hub： 应用调用（bl app）、应用记忆、知识库检索、模型目录/模型列表、用量/额度/配额、免费额度、 工作空间、MCP 市场、pipeline、文件上传、console API、登录鉴权与配置、 Agent skill 安装/列表/更新/卸载（bl skill add/list/update/remove，百炼 skill registry）。 用户点名百炼 / DashScope / `bl`，或继续既有 `… |
| `bailian-docs-llm-wiki` | bailian (Aliyun `bl`) | 阿里云百炼平台技术文档知识库（LLM Wiki）。当用户查询百炼模型列表、API 参数、错误码、 应用开发（智能体/RAG/知识库/记忆/插件）、模型对比与定价、SDK/OpenAI 兼容接口、 多模态能力（语音/图片/视频）、Token 计费等百炼相关问题时激活。 包含 models 结构化模型市场数据（含 contextWindow/QPM/价格/sample code）、 wiki 合成层（主题页/概念页/对比页）和 raw 原始文档层； 模型规格类问题先查 models/index.md，文档类问题先查 w… |
| `bailian-finetune` | bailian (Aliyun `bl`) | 阿里云百炼模型精调训练入口：用户要精调、微调、训练自己的模型（fine-tune，支持 SFT / SFT-LoRA / DPO / DPO-LoRA / CPT， 覆盖文本、语音、图像）、校验或上传训练数据集、看训练进度和日志、挑 checkpoint、导出精调产物、 把专属模型部署成服务时使用 `bl dataset` / `bl finetune` / `bl deploy`。链路是 validate 校验数据 → upload 拿 file-id → finetune create 建任务 → watch … |
| `bailian-gen` | bailian (Aliyun `bl`) | 阿里云百炼图片/视频/语音生成与理解入口：用户要生图、画图、生成照片、生成图片、AI 绘画、海报、头像、插画、 文生图（text-to-image）、图生图、改图、修图、多图合成、生成视频、文生视频、图生视频、参考生视频、视频编辑、风格转换、 配音、语音合成（TTS）、朗读、转写、语音识别（ASR），或图片理解、看图问答、视频理解、读视频、多模态理解时使用 `bl image` / `bl video` / `bl speech` / `bl vision describe` / `bl omni`。 **默认行为… |
| `bailian-managed-agent` | bailian (Aliyun `bl`) | 阿里云百炼托管 Agent 声明式基础设施入口：用户要创建agent、初始化 agents.yaml、校验或预览 agent 配置变更、 创建/更新/销毁百炼托管 Agent 或 Deployment、和托管 agent 对话、查会话事件历史、导入或取消跟踪远端资源时使用 `bl managed-agent`。以 agents.yaml 为唯一事实源做 IaC：init 建脚手架、validate 离线校验、plan 预览 diff、 apply / destroy 变更远端资源且必须带 `--yes`，务必先 p… |
| `bailian-model-recommend` | bailian (Aliyun `bl`) | 阿里云百炼模型选型与推荐。当用户需要"选择、推荐、对比"模型，或描述一个 AI 场景/功能需求（隐含需要帮其决策用哪个模型）时激活。核心意图是帮用户做决策， 不是单纯查资料。触发词：推荐模型、选哪个、哪个适合、对比、做一个XX、实现XX 功能、用什么模型好、XX场景方案。当用户同时涉及模型查询和模型选择时，优先 使用本 skill（本 skill 内部会读取模型数据完成推荐）。 |
| `bailian-protocol` | bailian (Aliyun `bl`) | 阿里云百炼 `bl` 家族共享执行协议（consent 确认、版本预检、鉴权/安装、错误上报、本地文件与输出约定）。 不是面向用户意图的业务入口；当任一 bailian-* 业务 skill（bailian-cli / bailian-gen / bailian-finetune / bailian-managed-agent / bailian-web-search）执行前需要公共上下文，或用户首次安装/鉴权/`bl` 报错需上报时读取本 skill。 官方安装为整包：`bl skill init`（与业务 sk… |
| `bailian-train-deploy` | bailian (Aliyun `bl`) | 用百炼 CLI (`bl`) 走完"数据→微调训练→导出→部署→调用"的完整闭环，或跳过训练直接部署基座模型。支持文本模型（SFT/DPO/CPT）、音频 TTS 模型（CosyVoice）、图像生成模型（Wan2.7）和视频生成模型（Wan i2v/kf2v）微调。涵盖数据集校验/上传、创建微调任务、等待训练、导出最佳 checkpoint、创建推理部署、等待就绪、给出调用示例。当用户提到在百炼 / DashScope / 阿里云模型工作室上"训练模型""微调""fine-tune""finetune""部署模型… |
| `bailian-web-search` | bailian (Aliyun `bl`) | 阿里云百炼联网搜索（web search）入口：为联网搜索 / 网页搜索 / 查最新资讯做路径分发。 先识别当前连接身份：Token Plan（profile `token-plan` 或 base_url host 为 `token-plan.<region>.maas.aliyuncs.com`）→ 模型自带搜索 （`bl text chat --api responses --tool '{"type":"web_search"}'`）；其他 / 默认 → Bailian MCP（`bl search web… |
| `caveman` | caveman | Terse caveman voice: answer first, fluff gone, every technical fact kept. Use for /caveman, "caveman mode", "talk like caveman", "be brief", "less tokens". Stays on until "stop caveman" or "normal mode". |
| `caveman-commit` | caveman | Write a Conventional Commits message compressed to intent only. Use for "write a commit", "commit message", /commit or /caveman-commit. |
| `caveman-compress` | caveman | Compress a memory file such as CLAUDE.md or a todo list into caveman format to save input tokens, keeping a readable backup. Trigger: /caveman-compress. |
| `caveman-discover` | caveman | Find and label every LLM workflow in the repository so Caveman Cloud groups spend by workflow instead of one bucket. Use for "discover workflows" or breaking LLM spend down by workflow. |
| `caveman-evidence-review` | caveman | Read-only review of Caveman Cloud evidence: cost, Cave Score, workflows, traces, latency, errors, routing, savings. Use when asked what Caveman found or where LLM spend goes. |
| `caveman-explore` | caveman | Read-only repository explorer for cold-start orientation, broad cross-file localization, or when a direct search failed. Skip it when the exact file or symbol is already named. Returns path:line citations only; its reads stay out of main context. |
| `caveman-help` | caveman | Quick-reference card for the three caveman skills and their commands. Trigger: /caveman-help or "caveman help". |
| `caveman-learn` | caveman | Act on a Caveman learn report - review the ranked token sinks, apply cost-lowering fixes with per-edit consent, and report what those fixes returned. Use when asked to lower an agent's token cost, what caveman has saved, to trim a heavy CLAUDE.md, or to offloa… |
| `caveman-manage` | caveman | Inspect Caveman Cloud's experiment lifecycle and block unsafe execution. Use when asked to start, approve, cancel, promote or roll back a Caveman experiment. |
| `caveman-optimize` | caveman | Turn a Caveman optimization observation into an operator-chosen candidate with a paired baseline evaluation. Use when asked to inspect or evaluate a Caveman optimization report. Needs explicit approval. |
| `caveman-review` | caveman | Compressed code review - one line per finding with location, problem and fix. Use for /caveman-review, "review this PR", or "review the diff". |
| `caveman-setup` | caveman | Wire a repository through the Caveman Cloud gateway so every LLM request is measured, with no behavior change. Use for "set up caveman" or adding LLM spend observability. |
| `caveman-stats` | caveman | Show recorded output and cache-read token usage and mode attribution for the current Claude Code session, or locate the host's native usage report. Trigger: /caveman-stats. |
| `adhd` | plugin adhd@adhd | Parallel divergent ideation for coding agents. Spawns N isolated branches under different cognitive frames (regulator, biology, speedrunner, 10-year-old, $0 budget), scores, clusters, prunes traps, and deepens top survivors. Use on /adhd, "ADHD mode", brainsto… |
| `engineering:architecture` | claude.ai synced plugin engineering | Create or evaluate an architecture decision record (ADR). Use when choosing between technologies (e.g., Kafka vs SQS), documenting a design decision with trade-offs and consequences, reviewing a system design proposal, or designing a new component from require… |
| `engineering:code-review` | claude.ai synced plugin engineering | Review code changes for security, performance, and correctness. Trigger with a PR URL or diff, "review this before I merge", "is this code safe?", or when checking a change for N+1 queries, injection risks, missing edge cases, or error handling gaps. |
| `engineering:debug` | claude.ai synced plugin engineering | Structured debugging session — reproduce, isolate, diagnose, and fix. Trigger with an error message or stack trace, "this works in staging but not prod", "something broke after the deploy", or when behavior diverges from expected and the cause isn't obvious. |
| `engineering:deploy-checklist` | claude.ai synced plugin engineering | Pre-deployment verification checklist. Use when about to ship a release, deploying a change with database migrations or feature flags, verifying CI status and approvals before going to production, or documenting rollback triggers ahead of time. |
| `engineering:documentation` | claude.ai synced plugin engineering | Write and maintain technical documentation. Trigger with "write docs for", "document this", "create a README", "write a runbook", "onboarding guide", or when the user needs help with any form of technical writing — API docs, architecture docs, or operational r… |
| `engineering:incident-response` | claude.ai synced plugin engineering | Run an incident response workflow — triage, communicate, and write postmortem. Trigger with "we have an incident", "production is down", an alert that needs severity assessment, a status update mid-incident, or when writing a blameless postmortem after resolut… |
| `engineering:standup` | claude.ai synced plugin engineering | Generate a standup update from recent activity. Use when preparing for daily standup, summarizing yesterday's commits and PRs and ticket moves, formatting work into yesterday/today/blockers, or structuring a few rough notes into a shareable update. |
| `engineering:system-design` | claude.ai synced plugin engineering | Design systems, services, and architectures. Trigger with "design a system for", "how should we architect", "system design for", "what's the right architecture for", or when the user needs help with API design, data modeling, or service boundaries. |
| `engineering:tech-debt` | claude.ai synced plugin engineering | Identify, categorize, and prioritize technical debt. Trigger with "tech debt", "technical debt audit", "what should we refactor", "code health", or when the user asks about code quality, refactoring priorities, or maintenance backlog. |
| `engineering:testing-strategy` | claude.ai synced plugin engineering | Design test strategies and test plans. Trigger with "how should we test", "test strategy for", "write tests for", "test plan", "what tests do we need", or when the user needs help with testing approaches, coverage, or test architecture. |
| `cowork-plugin-management:cowork-plugin-customizer` | claude.ai synced plugin cowork-plugin-management | Customize a Claude Code plugin for a specific organization's tools and workflows. Use when: customize plugin, set up plugin, configure plugin, tailor plugin, adjust plugin settings, customize plugin connectors, customize plugin skill, tweak plugin, modify plug… |
| `cowork-plugin-management:create-cowork-plugin` | claude.ai synced plugin cowork-plugin-management | Guide users through creating a new plugin from scratch in a cowork session. Use when users want to create a plugin, build a plugin, make a new plugin, develop a plugin, scaffold a plugin, start a plugin from scratch, or design a plugin. This skill requires Cow… |
| `mattpocock-skills:ask-matt` | plugin mattpocock-skills@mattpocock (engineering) | Ask which skill or flow fits your situation. A router over the skills in this repo. |
| `mattpocock-skills:code-review` | plugin mattpocock-skills@mattpocock (engineering) | Review the changes since a fixed point (commit, branch, tag, or merge-base) along two axes: Standards (does the code follow this repo's documented coding standards?) and Spec (does the code match what the originating issue/spec asked for?). Runs both reviews i… |
| `mattpocock-skills:codebase-design` | plugin mattpocock-skills@mattpocock (engineering) | Shared vocabulary for designing deep modules. Use when the user wants to design or improve a module's interface, find deepening opportunities, decide where a seam goes, make code more testable or AI-navigable, or when another skill needs the deep-module vocabu… |
| `mattpocock-skills:diagnosing-bugs` | plugin mattpocock-skills@mattpocock (engineering) | Diagnosis loop for hard bugs and performance regressions. Use when the user says "diagnose"/"debug this", or reports something broken/throwing/failing/slow. |
| `mattpocock-skills:domain-modeling` | plugin mattpocock-skills@mattpocock (engineering) | Build and sharpen a project's domain model. Use when discussing codebase terminology, writing or editing a CONTEXT.md, or recording or editing an ADR. |
| `mattpocock-skills:grill-with-docs` | plugin mattpocock-skills@mattpocock (engineering) | A relentless interview to sharpen a plan or design, which also creates docs (ADR's and glossary) as we go. |
| `mattpocock-skills:implement` | plugin mattpocock-skills@mattpocock (engineering) | Implement a piece of work based on a spec or set of tickets. |
| `mattpocock-skills:improve-codebase-architecture` | plugin mattpocock-skills@mattpocock (engineering) | Scan a codebase for deepening opportunities, present them as a visual HTML report, then grill through whichever one you pick. |
| `mattpocock-skills:prototype` | plugin mattpocock-skills@mattpocock (engineering) | Build a throwaway prototype to answer a design question. Use when the user wants to sanity-check whether a state model or logic feels right, or explore what a UI should look like. |
| `mattpocock-skills:research` | plugin mattpocock-skills@mattpocock (engineering) | Investigate a question against high-trust primary sources and capture the findings as a Markdown file in the repo. Use when the user wants a topic researched, docs or API facts gathered, or reading legwork delegated to a background agent. |
| `mattpocock-skills:resolving-merge-conflicts` | plugin mattpocock-skills@mattpocock (engineering) | Use when you need to resolve an in-progress git merge/rebase conflict. |
| `mattpocock-skills:setup-matt-pocock-skills` | plugin mattpocock-skills@mattpocock (engineering) | Configure this repo for the engineering skills: set up its issue tracker, triage label vocabulary, and domain doc layout. Run once before first use of the other engineering skills. |
| `mattpocock-skills:tdd` | plugin mattpocock-skills@mattpocock (engineering) | Test-driven development. Use when the user wants to build features or fix bugs test-first, mentions "red-green-refactor", or wants integration tests. |
| `mattpocock-skills:to-spec` | plugin mattpocock-skills@mattpocock (engineering) | Turn the current conversation into a spec and publish it to the project issue tracker: no interview, just synthesis of what you've already discussed. |
| `mattpocock-skills:to-tickets` | plugin mattpocock-skills@mattpocock (engineering) | Break a plan, spec, or the current conversation into a set of tracer-bullet tickets, each declaring its blocking edges, published to the configured tracker (edges as text in one file per ticket locally, or native blocking links on a real tracker). |
| `mattpocock-skills:triage` | plugin mattpocock-skills@mattpocock (engineering) | Move issues and external PRs through a state machine of triage roles, categorise, verify, grill if needed, and write agent-ready briefs. |
| `mattpocock-skills:wayfinder` | plugin mattpocock-skills@mattpocock (engineering) | Plan a huge chunk of work (more than one agent session can hold) as a shared map of decision tickets on your issue tracker, and resolve them one at a time until the way to the destination is clear. |
| `mattpocock-skills:wizard` | plugin mattpocock-skills@mattpocock (engineering) | Generate an interactive bash wizard that walks a human through steps only they can perform. Use when provisioning infrastructure, setting up credentials or CI secrets, walking an unfamiliar third-party dashboard, or running a one-off migration or cutover. Don'… |
| `mattpocock-skills:claude-handoff` | plugin mattpocock-skills@mattpocock (in-progress) | Hand the current conversation off to a fresh background agent that picks up the work immediately. |
| `mattpocock-skills:implement-spec` | plugin mattpocock-skills@mattpocock (in-progress) | Implement a specification in code. |
| `mattpocock-skills:loop-me` | plugin mattpocock-skills@mattpocock (in-progress) | Grill me about specs for the workflows I want to build, within this workspace. |
| `mattpocock-skills:setup-ts-deep-modules` | plugin mattpocock-skills@mattpocock (in-progress) | Wire dependency-cruiser into a TypeScript repo so each package is a deep module, with implementation hidden in subfolders and reachable only through its entry-point files. User-invoked. |
| `mattpocock-skills:writing-beats` | plugin mattpocock-skills@mattpocock (in-progress) | Writing, exploit; assemble raw material into a journey of beats, grounding each term before a beat leans on it. |
| `mattpocock-skills:writing-fragments` | plugin mattpocock-skills@mattpocock (in-progress) | Writing, explore: mine raw fragments, no structure yet. |
| `mattpocock-skills:writing-shape` | plugin mattpocock-skills@mattpocock (in-progress) | Writing, exploit: shape raw material into an article, paragraph by paragraph. |
| `mattpocock-skills:git-guardrails-claude-code` | plugin mattpocock-skills@mattpocock (misc) | Set up Claude Code hooks to block dangerous git commands (push, reset --hard, clean, branch -D, etc.) before they execute. Use when user wants to prevent destructive git operations, add git safety hooks, or block git push/reset in Claude Code. |
| `mattpocock-skills:migrate-to-shoehorn` | plugin mattpocock-skills@mattpocock (misc) | Migrate test files from `as` type assertions to @total-typescript/shoehorn. Use when user mentions shoehorn, wants to replace `as` in tests, or needs partial test data. |
| `mattpocock-skills:scaffold-exercises` | plugin mattpocock-skills@mattpocock (misc) | Create exercise directory structures with sections, problems, solutions, and explainers that pass linting. Use when user wants to scaffold exercises, create exercise stubs, or set up a new course section. |
| `mattpocock-skills:setup-pre-commit` | plugin mattpocock-skills@mattpocock (misc) | Set up Husky pre-commit hooks with lint-staged (Prettier), type checking, and tests in the current repo. Use when user wants to add pre-commit hooks, set up Husky, configure lint-staged, or add commit-time formatting/typechecking/testing. |
| `mattpocock-skills:grill-me` | plugin mattpocock-skills@mattpocock (productivity) | A relentless interview to sharpen a plan or design. |
| `mattpocock-skills:grilling` | plugin mattpocock-skills@mattpocock (productivity) | Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases. |
| `mattpocock-skills:handoff` | plugin mattpocock-skills@mattpocock (productivity) | Compact the current conversation into a handoff document for another agent to pick up. |
| `mattpocock-skills:teach` | plugin mattpocock-skills@mattpocock (productivity) | Teach the user a new skill or concept, within this workspace. |
| `mattpocock-skills:to-questionnaire` | plugin mattpocock-skills@mattpocock (productivity) | Turn a decision you can't fully answer into a questionnaire for someone else to fill in. |
| `mattpocock-skills:wait-what` | plugin mattpocock-skills@mattpocock (productivity) | Stop. That last message did not land: re-pitch it. |
| `mattpocock-skills:writing-for-agents` | plugin mattpocock-skills@mattpocock (productivity) | Writing documents for agents. Use when creating or editing skills, or modifying AGENTS.md or CLAUDE.md. |
| `cavecrew` | caveman | When to delegate to `cavecrew-investigator` (locate code), `cavecrew-builder` (1-2 file edit) or `cavecrew-reviewer` (diff review) instead of working inline or using `Explore`. Their output is compressed, so main context lasts longer. |
| `megacave` | caveman | Caveman in Classical Chinese: 文言文 register, far fewer characters, technical terms verbatim. Invoke only with /megacave or /caveman wenyan. Stays on until "stop caveman" or "normal mode". |
| `ultracave` | caveman | Caveman at maximum compression: fragments, one word when one word is enough, each fact once. Invoke only with /ultracave or /caveman ultra. Stays on until "stop caveman" or "normal mode". |
| `investigate-first` | third-party (discipline pack) | Diagnose ambiguous failures before editing. Use for unknown causes, intermittent behavior, performance regressions, or investigations needing evidence-ranked hypotheses. |
| `lean-build` | third-party (discipline pack) | Build feature work with high overbuilding risk. Use for new behavior, product slices, or integrations where repository reuse, strict scope, and an explicit stop condition matter. |
| `safe-refactor` | third-party (discipline pack) | Restructure code while preserving behavior. Use for extraction, consolidation, ownership moves, or cleanup where verification must bracket structural edits. |
| `surgical-patch` | third-party (discipline pack) | Fix bugs and small behavior changes at the narrowest responsible layer. Use when regression proof, preserved surrounding behavior, and task-relevant tests matter. |
| `verify-and-stop` | third-party (discipline pack) | Prove existing work meets acceptance conditions without expanding scope. Use for validation-only tasks, completion checks, focused gate runs, and last-mile proof. |
| `migration` | third-party (discipline pack) | Implement reversible compatibility-safe transitions. Use for schema, data, API, protocol, configuration, or dependency migrations requiring rollback and preservation proof. |
| `ln-11-plan-reviewer` | third-party (ln-* pack) | Reviews implementation plans against repository evidence and current authoritative guidance. Use before execution to expose gaps and risks; not for completed delivery review. |
| `ln-21-documentation-auditor` | third-party (ln-* pack) | Audits documentation and code comments for structure, coverage, factual accuracy, and maintainability. Use for documentation trust reviews; not code, test, or architecture audits. |
| `book-to-skill` | third-party | Converts books and documents (PDF, EPUB, DOCX, HTML, Markdown, plain text, RTF, MOBI/AZW with Calibre) into structured agent skills, extracting frameworks, mental models, principles, techniques, and anti-patterns. Use when the user wants to study a document th… |
