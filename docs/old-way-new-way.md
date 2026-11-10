# A. Old way versus new way

Snapshot: 2026-11-07. Prefer Paseo's native agent, workspace, host and messaging operations;
retain ADE's routing, ownership, review and durable recovery rules. A plugin and a similarly
named skill are separate things. The **Baton plugin** is distinct from ADE's **baton skill**.

| Need | Old way | Preferred way | What still matters |
|---|---|---|---|
| Fresh agent for a task | `hand`, `handoff`, manual clear then `baton` | `paseo-handoff` with a self-contained briefing | Its inspected version creates a child. It does not promise predecessor archival, ADE pointer updates or file transfer. |
| Durable recovery record | ADE Tier 1 pointer and deep Tier 2 document | Baton plugin for convenient idle snapshots; retain ADE records when explicitly needed | Baton has bounded conversation input and host-local storage. It is not a drop-in replacement for ADE's ownership/lineage protocol. |
| Resume an ADE checkpoint | ADE `baton` skill | Keep `baton` for existing Tier 1 chains | Read the exact pointer, check HEAD and owner. A native fresh-agent handoff does not make an old chain yours. |
| Parallel work | `acp-dispatch`, `acp-run`, custom job records | Native `create_agent` / `paseo run`, with `fan-out` for slicing and review discipline | Claimed worktrees, one writer, provider routing, useful reports and result verification remain. Shims delete in the Wave 6 follow-up (`docs/slim/wave6-follow-up.md`, soft deadline 2026-11-20). |
| Find and message peers | `session-finder/relay.py`, local agent IDs | `list_hosts`, host-qualified `list_agents` and `send_agent_prompt`; CLI `paseo send --json` to the selected daemon | Keep `{serverId, agentId}` together. Accepted/queued means wait for a named ack. |
| Local message UI | Relay commands | Installed Tell Agent `/tell` | Same host only; it asks the source agent to forward. It is not the cross-host transport. |
| Change provider | Restart by hand, custom successor logic | Installed Switch provider for a supported history conversion; `paseo-handoff` for a task briefing | Switch provider retains the old agent; transcript conversion has limits and is host-local. |
| Move work to another machine | Pass a Mac absolute path or local pointer | Native remote-host control plus an explicit artifact transfer; evaluate Transfer plugin | Remote control does not synchronize files, provider credentials, plugins or settings. |
| Repeated monitoring | Recurring model prompt | Existing scripts and schedules; judgment wakes only when needed | Keep the operator's script-first rule. |
| Completed tabs | Leave sessions open | Archive completed agents after their results are captured | Archive agents individually; workspace archival affects all its sessions and may remove a managed worktree. |

## B. Skill names and compatibility

The descriptive old-way names are `old-hand-use-paseo-handoff` and
`old-handoff-use-paseo-handoff`. Their descriptions say what to use instead.
`hand` and `handoff` remain compatibility entry points so existing prompts, command wrappers,
and links continue to work. They retain the requested legacy behavior and point to the new way.
The legacy skills remain model-accessible because existing automatic ADE recovery callbacks
need them; the compatibility entry points forward numbered-step references to the canonical protocol.

Use `paseo-handoff` for a new agent with a task briefing. Keep `session-handoff` and `baton`
for reading/writing existing ADE recovery chains. Keep `fan-out`: slicing, ownership and review
are still useful, while native Paseo is the preferred launch/communication surface.
Do not label these remaining responsibilities obsolete merely because Paseo supplies the transport.

## C. Cross-host communication and handoff

**C1. Select the destination explicitly.** Discover hosts with `list_hosts`. Keep the destination's
`serverId` with its agent/workspace IDs. `list_agents`, `list_workspaces`, `create_workspace`,
`create_agent` and `send_agent_prompt` in the current callable MCP surface accept `serverId`.
CLI automation selects its daemon with global `--host <target>`; a display label or server ID is
not automatically a valid CLI connection target. Resolve a registered connection using Paseo's
host facilities, and keep connection/pairing material out of reports.

**C2. Distinguish sending a message from moving a workspace.** A message can carry a self-contained
briefing. It cannot make `/Users/...`, `/home/...`, `~/.local/state/handoffs`, an ignored report,
or an unpushed branch appear on the other host. Use repo origin, pushed branch and full commit SHA
as portable identity, plus repo-relative artifact paths and explicit destination-local paths.
For uncommitted or untracked work, inventory it and transfer it deliberately; preserve the source.
Private briefs need an authorized private destination, even when the code repository is public.

**C3. Prepare and verify the destination.** Discover its providers/models and capabilities there.
Check a clean destination checkout or newly claimed worktree at the intended SHA. Record OS,
tools and platform-specific dependencies; macOS GUI tools and launchd jobs need alternatives on Linux.
Install/relink ADE skills on that host through normal setup. Authenticate providers locally through
the managed secret path. Keep credentials, launch settings and MCP configuration host-local.

**C4. Send a portable briefing and prove receipt.** Include the goal, ownership, exact Git state,
artifact locations, decisions, failed approaches, outstanding questions/jobs, verification evidence
and one next action. Name both predecessor and recipient as host/agent pairs. Ask the recipient to
acknowledge a unique handoff token and confirm that it can read the artifacts, sees the expected SHA,
owns the intended scope and can state the next step. A creation ID, queued send or online host alone
does not prove this. Arrange and verify the return route as well as the outbound route.

**C5. Transfer ownership only after acceptance.** Keep one writer per workspace; stop scheduling
new writes in the handed-off scope and let existing work finish before the recipient starts writing.
Carry outstanding review and permission requests; moving hosts grants no new authority.
Capture results, notify the relevant peers with host-qualified identities and acknowledged messages,
then archive the predecessor when no longer needed. Never archive its whole workspace if others use it.
On offline/uncertain delivery, retain the source and inspect destination state before retrying a write.

**C6. Acceptance before adopting a migration tool.** Prove macOS → Linux and Linux → macOS using a
disposable fixture: Git history/SHA, dirty and untracked files, ignored-file handling, conversation
support, destination path remapping, an explicit recipient ack and a return message. Interrupt a transfer
and verify source preservation and partial-copy recovery. Copy first; approve Move only after verified
ownership transfer. Unsupported provider history needs a deliberate briefing fallback, never silent loss.

## D. Plugin advice

The local `paseo plugin ls --json` snapshot showed all 21 installed plugins enabled/running.
The remote daemon's separate read-only inventory listed 14 plugins, all disabled, including
`cross-daemon`, `skills`, `session-janitor` and `usage-auto-resume`; Transfer was absent there too.
Preserve those disabled states until their purpose and dependencies are established. Native remote
workspace discovery succeeded without enabling them. No live plugin setting was changed for this document. Recommendations below are distinct from
installation and from an end-to-end migration proof.

| Plugin/capability | Advice | Reason and limits |
|---|---|---|
| Native Paseo tools and connected hosts | Keep enabled; configure on each intended daemon | Remote operations are built in. A read-only remote workspace-list call succeeded in this session; no transfer or round-trip peer ack was tested. |
| Transfer (`paseo-transfer`), absent on both inspected hosts | Evaluate installation on both hosts | Current README supports Linux/macOS/WSL and requires Node 22+, Git, destination provider CLIs and credentials. Copy/Move previews, Claude/Codex histories and verification fit this requirement. Provider support does not cover every planned Pi/OMP workflow. |
| Transfer settings/use | Begin with Copy and the preview; retain source | Ignored files, credentials, MCP and launch settings stay behind. Move refuses ignored files. Agent tools only list destinations/read status; initiating transfer uses the UI preview. App/plugin reload loses preview/status, requiring inspection before retry. |
| Baton | Keep for convenient same-host recovery | `.paseo/handoffs` or a configured directory stays on the daemon. Select a cheap eligible writer profile, keep `waitForSubagents` on, and choose durable retention deliberately. Consider `deleteStaleHandoffs` and `cleanupOldHandoffs` off for records relied on across a transfer until explicitly retained elsewhere; this trades disk retention for recoverability. These are recommendations, not verified current values. |
| Tell Agent | Keep as a local UI convenience | Its installed overview explicitly says same-host only. Use native host-targeted messaging across computers. |
| Skills | Keep; install on each participating host as needed | Exposes descriptions and descriptive legacy names. A Mac installation does not populate a Linux host's skill directories. |
| Switch provider | Keep optional for same-host conversion | Installed overview says Claude/Codex/Pi/OpenCode conversions use local provider formats; other routes use a temporary Markdown transcript. It leaves the old agent running. It is not workspace migration. |
| Session Guard | Keep; validate OS-specific settings | Installed README uses Linux `/proc` for native subagent suspension. It directs other hosts to turn **Include native subagents** off for foreground interruption/continuation. Verify the effective value separately on each host before changing it. |
| session-recovery | Keep; review continuation overlap | Interruption recovery, selected-goal continuation and quota pauses have different owners. Avoid duplicate continuation loops with Session Guard; check effective settings and prove manual stops stay stopped. Do not blindly toggle recovery off. |
| Vitals; reopen-archived | Keep | Useful for measuring host RAM and recovering archived work. No measured plugin-by-plugin RAM saving is claimed. |
| Herdr harness; paseo-runner | Review dependencies before disabling | These bridge/extension projects may still support live workflows. The repo's retirement of Herdr does not authorize breaking them. Inventory consumers and preserve their state before proposing removal. |
| Better Paseo, Forges, Herald, Cafe, Side Chat, PR Radar, Progress, Questions please, workspace accent, Claude entrypoint env | No change required by this migration | Keep their current roles; assess optional UI/RAM costs from measurements rather than names. |

There is no demonstrated need to uninstall a plugin now. The main new candidate is Transfer;
the immediate choice for cross-machine messages is native host targeting. Plugin installation is
per daemon, and host-scoped settings do not automatically become shared across machines.
Adding Transfer, altering another repository or changing live plugin settings remains a separate
concrete action from this advice.

## E. Evidence and remaining checks

**E1. Local evidence, 2026-11-07:** installed `paseo`, `paseo-handoff` and `paseo-plugin` skills;
installed plugin inventory and Baton/Tell Agent/Switch provider/Session Guard/session-recovery/Skills
overviews; callable MCP schemas. Registered remote discovery succeeded and a remote workspace list
returned successfully. No remote provider process was launched and no real work was moved.

**E2. Current upstream references, fetched 2026-11-07:**
[Paseo orchestration](https://paseo.sh/docs/orchestration),
[CLI host targeting](https://paseo.sh/docs/cli),
[plugin host scope and lifecycle](https://paseo.sh/docs/plugins/reference),
[Transfer README](https://github.com/tomgrin10/paseo-transfer#readme).
The installed surface is authoritative for this machine; deployed docs and plugins can advance independently.

**E3. Still to prove:** effective plugin settings on each daemon; bidirectional host/agent messaging with
receipt acknowledgments; Transfer source/security review and compatibility; the C6 fixture matrix;
support or fallback for Pi/OMP conversations; retention and ownership through interruption/restart.
Update this document with measured results before calling cross-host handoff production-ready.
