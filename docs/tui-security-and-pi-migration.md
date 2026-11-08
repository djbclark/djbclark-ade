# TUI security research and Pi-first migration

Snapshot: 2026-11-08. Research describes fetched documentation and inspected
source, not an independently reproduced comparative security benchmark.

## A. Controlling operator decisions

A1. Pi is the sole general-purpose third-party terminal coding agent. Retain
vendor clients needed to use monthly plans. Hermes is an explicit exception:
keep it unchanged, including its messaging services. Paseo remains the harness.

A2. Archive other third-party TUIs reversibly, then uninstall their executable
installations and exclusive adapters. Preserve configuration, sessions, work,
package identity and restoration instructions. Never cancel paid work to retire
a client; finish or hand it off first. Do not delete historical agent records.

A3. Security implementation is deferred. This document preserves the research
and implementation options; it does not authorize installing detectors,
confining trusted local peers, or replacing existing protections.

A4. Focus on making Pi work with each applicable service, validating one pool at
a time and moving routing only after acceptance. Unsupported services stay
explicitly blocked or on a retained vendor client. No silent paid fallback.

A5. OpenAI has TWO separate pools: the Codex monthly subscription through the
Codex TUI, and OpenAI API credits through Pi. Never merge their quota, billing,
availability, blocked state or reset metadata. An OpenAI API organization spend
cap says nothing about remaining Codex subscription quota.

A6. Anthropic likewise has a Claude subscription through its vendor client and
API credits that should move to Pi after validation. Historical API-credit use
through omp is not authority to retain omp as a permanent exception. Preserve
its state before retirement and record any Pi acceptance blocker.

## B. Threat model and limits of the research

B1. The target threat is indirect prompt injection in GitHub issues, PR bodies,
comments, diffs, commit messages, branch names, bot output and CI logs. Hidden
HTML comments, terminal control sequences, invisible Unicode and ordinary prose
can carry attacks. A dependency or draft PR is not trusted merely because its
workflow is familiar. Attribution and content provenance matter.

B2. Trust our local peers and operator-owned instructions. An external artifact
does not become trusted because it is saved locally or quoted by a trusted
peer. A reviewer must distinguish the peer's instruction from quoted data.

B3. No evidence established Pi, omp, OpenCode, Crush, Goose, Aider or Qwen Code
as the most injection-resistant TUI in a common-platform, common-model,
adaptive-attack experiment. Advisory counts, stars, LOC, tool approvals and
passive credential discovery are not such a comparison.

B4. Inputs arrive through GitHub MCP, web fetch, `gh`, shell output and files.
WebFetch-only scanning misses other channels. A shell checker may approve an
innocuous read whose output contains hostile instructions. Post-output warnings
may leave the original hostile content in the model's context.

B5. Distinguish attempted actions, blocked effects and successful effects.
Prompt warnings and judge models reduce risk but are not OS containment. A
schema-valid summary can still contain attacker-selected paths, destinations or
commands. Separate contexts do not automatically secure data flow.

Primary research: [CaMeL](https://arxiv.org/abs/2503.18813),
[AgentDojo](https://arxiv.org/abs/2406.13352), and
[LlamaFirewall](https://arxiv.org/abs/2505.03574). Earlier research also examined
QueryIPI and a commercial Composio Pi/OpenCode task-cost comparison; neither
established a security ranking of these exact TUIs. Saved full sources and the
original counter-evidence/review remain in the private research record.

## C. Host-specific findings

| Host | Relevant finding | Limit |
| --- | --- | --- |
| Pi | Startup trust, tool/result extension hooks, whole-process isolation guidance | No built-in general filesystem/process/network permission boundary; context files can load despite declined project trust |
| omp | Tool hooks, isolated task contexts, advisor and stream rules | Advisor output is model advice, not independent authorization; regex stream correction is not comprehensive enforcement |
| OpenCode | Permission system, MCP, current-generation plugin hooks | Permission UX is not OS sandboxing; V1 plugins may not run on V2 |
| Crush | Tool approvals, MCP and executable configuration | Executable startup configuration and shell hooks are trusted code, not confinement |
| Goose | Pattern-based pre-tool detection and optional ML detection | Detector is not guaranteed; enabled tools retain host authority; ML scanning adds endpoint disclosure considerations |
| Qwen Code | Optional Linux tool sandbox and separate whole-CLI methods | Tool mode leaves CLI/auth on host, permits broad reads and rejects ACP/serve/web-terminal use; macOS defaults differ |
| Aider | Editor/git workflow, shell suggestions and confirmation flags | No comparable agent-wide confinement established in the fetched documentation |

Sources: [Pi safety](https://github.com/earendil-works/pi/blob/v1.5.0/packages/coding-agent/docs/security.md),
[Pi isolation](https://github.com/earendil-works/pi/blob/v1.5.0/packages/coding-agent/docs/containerization.md),
[omp](https://github.com/can1357/oh-my-pi),
[OpenCode security](https://github.com/anomalyco/opencode/security),
[Crush](https://github.com/charmbracelet/crush),
[Goose security](https://github.com/block/goose/blob/main/SECURITY.md),
[Qwen sandbox](https://qwenlm.github.io/qwen-code-docs/en/users/features/sandbox/),
[Aider options](https://aider.chat/docs/config/options.html).

C1. Pi model-configuration command helpers were passive in the retained
synthetic discovery cases, but auth-store command helpers executed during
discovery. Do not generalize to "Pi discovery never executes helpers."
Current omp source has a presence-only authentication method, but its scope
does not prove every current CLI startup path fixed. Local observations and
operator-authored issues belong to the same evidence family.

C2. Pi's historical project-extension advisory
[GHSA-mqxh-6gq7-558m](https://github.com/earendil-works/pi/security/advisories/GHSA-mqxh-6gq7-558m)
describes a startup-loading fix, not a universal prompt-injection defense.
OpenCode's historical c83v advisory concerns a web-UI/XSS/local-API chain, not a
measurement of current terminal-model instruction following. The researched
OpenCode npm channels were `@opencode/cli` 2.2.6 and `opencode-ai` 1.19.5;
older advisory package floors do not establish cross-channel fix inheritance.

## D. Community guards: source findings and public footprint

Figures below are 2026-11-08 snapshots. Contributors are repository records,
not a count of security specialists. Whole-toolkit metrics are not comparable
to a dedicated plugin's code size. They do not measure injection resistance.

| Project | Stars | Relevant integration or control | Important qualification |
| --- | ---: | --- | --- |
| [HOL Guard](https://github.com/hashgraph-online/hol-guard) | 1,077 | Pi/omp/OpenCode adapters; explicit Paseo deployment documentation | Provider-specific coverage, not uniformly fail-closed or a universal Paseo firewall |
| [Tirith](https://github.com/sheeki03/tirith) | 2,780 | Blocking Pi/omp tool-call adapters; command/URL/configuration checks | OpenCode setup is cooperative MCP registration, not equivalent blocking coverage; one named contributor |
| [Microsoft AGT](https://github.com/microsoft/agent-governance-toolkit) | 6,536 | Large governance toolkit, Claude/OpenCode integrations | Inspected OpenCode adapter used legacy V1 hooks; current V2 compatibility unestablished |
| [Sage](https://github.com/gendigitalinc/sage) | 324 | Heuristics and optional ML, including web-prefetch checks | ML off by default, WebFetch-specific, fetch failures fail open; warnings may not remove exposure |
| [Rampart](https://github.com/peg/rampart) | 92 | Native hooks, policy engine and MCP proxy | Prompt-injection policy defaults to watch; no Pi/omp native adapter established |
| [Lasso hooks](https://github.com/lasso-security/claude-hooks) | 273 | Claude post-tool injection warnings | Warns without blocking; inspected history had one author and two commits |
| [OpenCode Injection Guard](https://github.com/remorses/opencode-injection-guard) | 19 | Tool-less judge can replace flagged tool output | Explicitly V1-only; default scan patterns empty; judge and length limits remain |
| [omp-web-guard](https://github.com/charliejimi/omp-web-guard) | 0 | URL/SSRF checks, recognized injection replacement and labeling | Five content patterns; scripted-model tests, not real-model resistance; post-fetch checks cannot undo requests |
| [agentsh](https://github.com/canyonroad/agentsh) | 406 | File/network/process execution policy | Containment rather than text detection; native macOS documented Alpha; shell coverage must be configured |

D1. HOL's [Paseo guidance](https://github.com/hashgraph-online/hol-guard/blob/main/docs/guard/paseo.md)
correctly distinguishes installed adapter files from proven loaded/runtime
coverage. Its coverage does not extend automatically to daemon Git operations,
browser actions, arbitrary plugins, terminal sessions or other hosts.

D2. Other small examples included
[renatodarrigo/claude-guard](https://github.com/renatodarrigo/claude-guard),
[aviv4339/claude-guard](https://github.com/aviv4339/claude-guard) and
[lounis89/agent-guard](https://github.com/lounis89/agent-guard).
They were not established as stronger maintained choices. Name collisions were
excluded: `pi-guard` did not establish Pi coding-agent integration, and
`jev-crush` was unrelated to the Crush TUI. A failed public-repository lookup
is not proof a project has never existed.

## E. Jev integrations in more detail

LOC counts are nonblank physical runtime-source lines, including comments,
from fetched source archives. Tests, evaluation runners and generated/vendor
code were separated. No repository code was executed for those counts.

| Project | Stars / named authors | Runtime / test LOC | Assessment |
| --- | --- | --- | --- |
| [jev-guard](https://github.com/leepokai/jev-guard) | 148 / 3 | 1,104 / 442 | Broad adapter coverage; fail-open default, skipped read-only paths and minimum screening length; OpenCode V2 migration PR open at research time |
| [Jev Sentinel](https://github.com/harshwasan/jev-sentinel) | 15 / 1 | 2,529 / 1,681 | Most elaborate dedicated Pi content/action/taint design inspected; default trusted instruction paths and session-start taint reset need review |
| [oh-my-jev](https://github.com/apetcu/oh-my-jev) | 2 / 1 | 949 / 623 | omp risk/alignment gate; routine-action fast paths; not a complete result-screening pipeline |
| [CogFlux guard](https://github.com/CogFlux/opencode-jev-guard) | 2 / 1 | 878 / 534 | OpenCode 2 shell/remote-shell approval layer; not complete read/edit/MCP coverage |
| [Jev Decision Gate](https://github.com/iDiagoValeta/jev-decision-gate) | 2 / 1 plus bot | 4,418 / 5,311 | Strongest current dedicated Jev engineering inspected: command recovery, credential-path rules, unattended denial and recent CI |
| [OpenCode Security Guard](https://github.com/koppert/opencode-security-guard) | 0 / 1 | 160 / 85 | Narrow Linux-tested shell classifier, not broad external-content protection |

E1. Decision Gate's author-reported 140-case evaluation contained only FOUR
prompt-injection cases. It used the real permission evaluator with a fake host
session and live Jev; it was not a common-protocol end-to-end attack benchmark.
Its legacy fallback had weaker coverage. One recent contributor and CI passing
do not establish independent security validation.

E2. Sentinel can retain original content under a warning and increase later
approval requirements. Its default root `AGENTS.md`, `CLAUDE.md` and `.pi/`
exemptions are unsuitable as unconditional trust for external PR modifications.
Earlier source inspection found taint reset at session start. Public Pi APIs
it used still existed in inspected Pi 1.5.0, but operational compatibility was
not tested. Do not call it broken merely because its development version was
older. Remote judge redaction is pattern-based, not a confidentiality guarantee.

E3. [jev-guard PR 14](https://github.com/leepokai/jev-guard/pull/14) was open,
replacing unmerged PR 13. Main/released V1 hooks should not be counted as V2
protection. Its npm release also preceded some main-branch changes.

E4. [Berget guardrails](https://github.com/berget-ai/guardrails-md) was related,
but its current default was `berget/bev`, not Jev. It had 14 stars, four authors,
1,209 runtime lines and 1,415 test lines. Endpoint failure and missing-credential
behavior differed; bash-only coverage and credential-less inactivity matter.

## F. Project-health services actually consulted

| Service and artifact | Observed result | Interpretation |
| --- | --- | --- |
| [OpenSSF: HOL](https://api.securityscorecards.dev/projects/github.com/hashgraph-online/hol-guard) | 8.8/10; eight vulnerability findings; CI/SAST checks had internal errors | Earlier scanned commit, not a clean current-runtime attestation; findings not individually triaged |
| [OpenSSF: AGT](https://api.securityscorecards.dev/projects/github.com/microsoft/agent-governance-toolkit) | 7.9/10; 136 vulnerability findings | Broad toolkit/dependency result, not 136 proven exploitable runtime bugs |
| OpenSSF: inspected dedicated Jev repos and Tirith | No published report returned | Unknown, not zero security |
| [Socket: jev-guard 0.3.1](https://socket.dev/npm/package/jev-guard/overview/0.3.1) | Supply-chain 75, vulnerability 100, quality 100, maintenance 86 | Published-package indicators, not injection efficacy; conflicting cached download counts excluded |
| [Socket: OpenCode Security Guard](https://socket.dev/npm/package/opencode-security-guard) | Supply-chain 72, vulnerability 100, quality 93, maintenance 86 | Same limitation |
| [Libraries.io](https://libraries.io/npm/jev-guard/sourcerank) | SourceRank 7 for jev-guard; 6 for OpenCode Security Guard; 8 for Berget | Metadata/maturity heuristics, not safety ratings |
| [deps.dev](https://api.deps.dev/v3/systems/npm/packages/jev-guard/versions/0.3.1) | No listed advisories/provenance/attestations in inspected response | Absence of listed findings is not proof of safety |
| ecosyste.ms | Stale 48 stars/7 forks for jev-guard versus current GitHub 148/24 | Index freshness matters; current GitHub metadata preferred |

F1. HOL had 189 GitHub User contributor accounts and AGT 161, across their whole
repositories. These are not security-team headcounts. Most dedicated Jev
plugins had one author. Stars, contributors and LOC were supporting maintenance
signals only; no arbitrary numerical safety certification follows.

## G. Deferred architectural containment proposal

G1. The proposed strongest starting-from-scratch stack was a whole-process
microVM, narrow GitHub acquisition broker, host-held credential injection,
restricted egress, mediated MCP/API traffic, and a separate approved publisher.
OpenCode had the clearest first-party Docker integration; Pi had strong-looking
community interception options. Different TUI brands alone create no boundary.

G2. [Docker Sandboxes](https://docs.docker.com/ai/sandboxes/security/) documents
microVM isolation, clone/mountless modes and host proxy credentials. Explicitly
disable SSH-agent forwarding and shared writable skills, choose restricted
network policy and avoid sharing host secrets. Direct workspace mounts expose
live host files. Conflicting descriptions of skills defaults require explicit
configuration and verification. Token placeholders do not prevent misuse of
the authorized service. OAuth passthrough reduces credential isolation.

G3. [Pipelock](https://github.com/pipelab-org/pipelock) documents bidirectional
MCP scanning, DLP, tool drift checks and risky action-chain detection. It sees
mediated traffic only. Direct sockets/DNS can bypass proxy settings without an
enforced boundary; plain CONNECT does not expose encrypted bodies, and an
allowlisted service can still receive exfiltrated data. TLS interception and
stateful policies need explicit configuration; do not stack unverified proxies
and assume their guarantees compose.

G4. [AgentGuard](https://github.com/ebrindley/AgentGuard) provides macOS Seatbelt
controls for OpenCode/Pi/omp, but its documented network is unrestricted and
reads are broad outside denies. Pi/omp policy differs from OpenCode. Its
predecessor pi-sandbox-guard is deprecated. Treat it as lower-overhead partial
containment, not equivalent to the proposed credential-free microVM boundary.

G5. [agents-sandbox](https://github.com/inoio/agents-sandbox) documents Pi,
OpenCode and omp microVM launchers. Its defaults can copy host configuration,
including auth, provide public network access and preserve agent-home volumes.
Use explicit host-config opt-out, secret injection, no browser-link handoff and
restricted networking if evaluated. Defaults are not a complete safe profile.

G6. GitHub MCP `--toolsets` and `--tools` combine ADDITIVELY. A command supplying
broad toolsets plus three tools is not a three-tool allowlist. Read-only mode
does not stop cross-repository reads with an overbroad token. Enforce exact
repositories, methods and argument destinations at the acquisition broker.
[Official behavior](https://github.com/github/github-mcp-server#specifying-individual-tools).

G7. [MCP-Scan](https://invariantlabs-ai.github.io/docs/mcp-scan/) documented tool
pinning and runtime policies; current [Snyk Agent Scan](https://github.com/snyk/agent-scan)
must be checked rather than assuming old proxy commands remain current. Tool
description hashes detect changes, not malicious GitHub payloads.
[Shield KYA](https://github.com/The-Pixel-Boys/shield-kya) documents fail-open
local hooks and distinct hosted/MCP enforcement; it is not automatically a
universal hard local gate.

G8. The [destyling paper](https://arxiv.org/html/2603.12277v6) reports 61% to 10%
attack success in a specific experiment using an auxiliary LLM to rewrite
forged reasoning. That number does NOT validate stripping Markdown comments,
Unicode or terminal escapes. Preserve raw evidence; generate a separate safe
display rather than silently rewriting code diffs or treating sanitized text
as trusted.

G9. [PromptGuard 2](https://meta-llama.github.io/PurpleLlama/LlamaFirewall/docs/documentation/scanners/prompt-guard-2)
is an optional lightweight detector, not zero-latency. AlignmentCheck is an
experimental reasoning auditor with additional inference/trace requirements.
No complete ready-made integration or comparative attack rate for these TUIs
was established. Judge models themselves may be injected.

G10. Acceptance would require malicious issue/comment/diff fixtures attempting
canary reads, cross-repo access, egress, persistence and publication. Exercise
actual shell/file/MCP/extension paths, timeout/crash behavior, resume and
compaction. Keep attempts separate from effects. Passing tests does not remove
the risk of poisoned recommendations or patches approved later by a human.

## H. Historical recommendation scores, not measured safety

These subjective 2026-11-08 stack-fit scores used 40% containment integration,
35% interception and 25% compatibility/maturity. Small differences were
inconclusive. They did not rate bare TUI attack resistance and are superseded
as a selection decision by the operator's Pi-first ruling.

| TUI | Containment fit | Interception | Maturity | Weighted /100 |
| --- | ---: | ---: | ---: | ---: |
| OpenCode | 95 | 80 | 90 | 89 |
| Pi | 90 | 90 | 80 | 88 |
| omp | 90 | 85 | 70 | 83 |
| Qwen Code | 90 | 75 | 80 | 82 |
| Goose | 90 | 75 | 80 | 82 |
| Crush | 85 | 55 | 75 | 72 |
| Aider | 85 | 45 | 80 | 70 |

H1. The interim everything-local-is-trusted proposal was Pi plus a validated
Sentinel integration, or OpenCode plus Decision Gate and controlled ingestion.
It aimed to screen external data and check consequential actions while keeping
ordinary work autonomous. Without confinement, a successful bypass retains
account authority. This proposal is preserved, not being implemented now.

## I. Provider coverage and distinct billing pools

| Pool | Pi path | Migration rule |
| --- | --- | --- |
| OpenAI API credits | Built-in `openai`, API-key authentication | Distinct from Codex subscription; retain original API spend-cap failure |
| Codex/ChatGPT subscription | Built-in ChatGPT OAuth exists | Operator currently keeps subscription through Codex TUI; do not silently replace or merge |
| Anthropic API credits | Built-in `anthropic` | Validate inference, attribution and passive rate-limit handling before moving |
| Claude subscription | OAuth implementation exists in Pi | Retain vendor Claude client; code presence is not supported entitlement |
| OpenCode Go | Built-in `opencode-go` | One bounded MiniMax M3 smoke passed; not all models or full operational acceptance |
| OpenCode Zen/free | Built-in `opencode` | Separate pool; retired paid Zen remains disabled |
| Cursor | Community provider or compatibility layer | Validate actual allowance and tool interception; some bridges execute tools in Cursor instead of Pi |
| Antigravity | Community provider | Unofficial transport, account and compatibility risks; retain required vendor access |
| ClinePass | Community OpenAI-compatible provider | Validate authentication, catalog and pool attribution |
| Other declared API services | Built-in or documented compatible provider | Validate each real entitlement separately; model-list presence is insufficient |

I1. Pi `openai` supports both API keys and ChatGPT OAuth; the separate
`openai-codex` namespace was legacy in inspected source. Namespace alone is not
billing identity. Go and Zen may share an environment-variable name without
sharing balances. API support for a model vendor does not transfer Cursor,
Claude or Google subscription allowances.

I2. Sources: [Pi providers](https://github.com/earendil-works/pi/blob/v1.5.0/packages/coding-agent/docs/providers.md),
[OpenCode providers](https://opencode.ai/docs/providers/),
[Cursor compatibility provider](https://github.com/oakimov/cursor-opencode-provider),
[Pi Cursor CLI bridge](https://github.com/netandreus/pi-cursor-provider#tool-calls),
[Antigravity integration](https://github.com/cortexkit/antigravity-auth),
[Pi Antigravity](https://pi.dev/packages/pi-antigravity),
[ClinePass provider](https://github.com/jellydn/pi-clinepass-provider).
These are implementation/documentation claims, not acceptance for our account.

I3. The Pi Cursor CLI bridge explicitly delegates tools to Cursor while Pi
observes them. Pi hooks cannot be assumed to control those executions. Audit
each bridge's execution location before claiming security or hook parity.

I4. [Anthropic's authentication guidance](https://code.claude.com/docs/en/legal-and-compliance#authentication-and-credential-use)
distinguishes native subscription use from API integrations. OpenCode removed
its bundled subscription-auth plugin in [PR 18186](https://github.com/anomalyco/opencode/pull/18186).
Plugin existence does not establish officially supported subscription access.

## J. Operational migration and preservation gates

J1. Preserve research and restoration state first. Inventory every installation
channel before removal: npm and Homebrew OpenCode may coexist. Archive package
identity/artifacts, configuration, history, plugin and adapter state, launchers,
updater references, routes, schedules and ownership. Keep sensitive material
private and opaque. Do not uninstall shared dependencies or unrelated services.

J2. Finish or hand off running work without cancellation. Preserve idle work
with reports, worktree/head/dirty-state records, PR/check status and exact next
actions. Never overwrite another owner's changes or original failed evidence.
Archiving a workspace can remove a managed worktree: archive agents only when
appropriate, and never discard worktrees as a presentation cleanup.

J3. Validate one service/pool at a time: normal managed authentication, explicit
model and billing identity, bounded inference, tools, report/peer acknowledgement,
quota attribution and continuation. Native Paseo model selection, schedules,
skills, context/compaction and handoff behavior need separate checks. Keep mode
unset when Pi exposes no selectable permission modes.

J4. Retained Pi source findings: native model discovery is a real RPC snapshot,
not entitlement proof; default auth reads can execute configured helpers. The
metadata-only public runtime path can list credential provider/type without
resolving helper values when initialized without refresh. Normal login can
synchronize credentials immediately, so do not call it a passive write.

J5. Earlier OpenAI API smoke failed under an organization spend cap; it was not
Codex subscription exhaustion. The same Pi agent later passed a bounded Go
MiniMax M3 tool/report smoke. These results do not prove all-provider readiness.
The aiuse snapshot already included explicit stale fields; the actual reported
gap was non-resettable blocked-state feedback, not absent freshness metadata.
Tracked separately in [aiuse issue 51](https://github.com/djbclark/aiuse/issues/51).

J6. Anthropic response hooks inspected earlier ran after successful retry
completion, while retry headers were consumed internally and Paseo discarded
some structured retry fields. Therefore passive fail-closed pool/reset feedback
was not established. Preserve this blocker while retiring omp; do not convert
unknown reset time into available credit or keep spending on repeated failures.

J7. Only accepted services move to Pi routing. Archive and uninstall other
third-party TUIs once their work is safe, retaining histories and restore
instructions. Vendor clients and Hermes remain. Unsupported routes get an
explicit pending/blocked status, not an undeclared fallback. Security work stays
deferred; workspace/tab aesthetics remain at the tail.

J8. Completion evidence must name source/config changes, focused checks, hosted
CI, actual per-pool runtime results, retired executables, archive verification
and unresolved blockers separately. A passing catalog lookup is not inference;
a successful inference is not continuation, quota or full migration acceptance.

## K. Archive search is a retirement acceptance condition

K1. Retiring a client must preserve its original transcript/log directories,
SQLite session/message records and archive-search adapters. Uninstalling the
executable must not disable searching its history or trigger index pruning.
Keep the full-text history database and the Paseo transcript-search database
separate, with consistent private snapshots and per-client before/after counts.

K2. `/session-finder` must search archived-client history without launching or
reinstalling that client. Preserve legacy parsers as data readers, not execution
routes. Restore the missing search entrypoint without reviving retired harness
launch, relay or resume machinery. Search results do not constitute instructions.

K3. Validate FTS and literal searches over archived omp/OpenCode/Crush fixtures
with their executable names unavailable. Verify existing live database records
remain intact and preserve source logs for future re-indexing.

## L. Execution checkpoint (2026-11-08)

L1. Original research and unfinished-work reports were preserved before package
removal. The verified private archive includes original client state, package
artifacts and native agent records. Logs and history indexes remain at original
paths. A supplemental archive preserves a third legacy OpenCode installation.

L2. omp, Crush and all three discovered OpenCode executable installations were
retired; vendor clients, Pi and Hermes were retained. Native retired-provider
launches were disabled without restarting Paseo. Recovery instructions restore
packages selectively rather than overwriting newer logs or daemon settings.

L3. The existing history index passed integrity and real FTS checks with 3,695
omp, 180 OpenCode and 111 Crush session records. Both history databases have
consistent private backups. The restored archive-search code passed 13 focused
regressions, including absent binaries and non-pruning refreshes. Hosted CI,
independent review and installation status are recorded in the migration ledger.

L4. Pi named managed-reference configuration now includes Anthropic, Gemini,
DeepSeek, OpenRouter and Z.ai, preserving OpenAI API and Go entries. Catalog
refresh exposed these namespaces, but is not inference acceptance. A bounded
Z.ai source/tool/report/peer-ack task passed. Anthropic first inference failed
with insufficient API balance; original OpenAI API organization spend cap stays
blocked. Neither error describes the separate vendor subscription allowance.
L5. The first Google API check hit its free-tier input-token-per-minute quota
(HTTP 429). It was not retried; this does not describe Antigravity subscription
availability. DeepSeek and OpenRouter remain configured but unvalidated.

