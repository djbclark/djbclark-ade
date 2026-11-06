# Restart after the 2026-11-06 Mac reboot

## A. Where and what to paste

A1 CWD: `/Users/djbclark/src/djbclark-ade`
A2 Agent: a new Paseo agent, omp `anthropic/claude-opus-5-5` (the helm lead seat), or reopen the existing "HELM LEAD" tab (7c58015b).
A3 Prompt:

```
/baton ~/.local/state/handoffs/chains/helm-lead-2026-11-02/SESSION_LOG.md

You are the HELM LEAD after the 2026-11-06 Mac reboot. Read that handoff and
~/.local/state/bigteam/lead-2026-11-02/reboot-2026-11-06/RESTART-PROMPT.md (section B is the
agent table; my edits to its "restart" column are binding).
1. Check Paseo came back: `paseo ls --json` against reboot-2026-11-06/paseo-agents.json.
   Reopen any missing agent in its own workspace; never create duplicates; leave the
   three Dann tabs closed.
2. Bring each herdr pane I marked "revive" into Paseo by resuming its native session
   (handoff section C3 has cwd + resume command).
3. Wake agents at most 4 at a time, `bin/load-watch admit` between batches, plain relay
   (no --steer): "Mac rebooted; you are still PAUSED for the slim-down; confirm idle,
   reply `ack reboot-<id>`". Agents marked "cancel" get no wake; tell me and I archive
   or close them myself.
4. Do not resume anyone's work. Everything stays paused until the slim-down split
   session finishes and I say continue.
5. Report back: a labelled list of who is up, who is missing, any delivery not verified.
```

## B. Agents and what each was working on (all paused; edit the restart column)

Restart values: keep = bring back idle; revive = herdr pane to bring into Paseo; cancel = do not bring back.

### B1. Paseo agents

| id | tab / title | harness | cwd | was working on | state | restart (default) |
|---|---|---|---|---|---|---|
| 7c58015b | HELM LEAD | omp opus-5-5 | ~/src/djbclark-ade | fleet coordination; slim-down check-ins (done); PRs 261, 270, 294 open | paused | keep |
| 1e61c979 | LEAD paseo-only rearch | omp opus-5-5 | ~/src/djbclark-ade | djbclark-ade lead: lands PRs, D1 Paseo acceptance (d1-prep), slices for PRs 208/214/256/260 | paused; lander/feeder booted out | keep |
| 3ac46de6 | tendcf nixos stage D | omp opus-5-5 | ~/s/cm/tendcf/tendcf | tendcf lead: S5 design, fork CMDB, Q10 policy (slices stopped + pushed for reboot); Q9 answered | paused | keep |
| 0dc43dbd | Can you make it so that on all my repos... | cursor opus-5-5 | ~/src/djbclark-ade | pr-policy + agent-TUI retirement lead; Q1-Q5 answered; rest folded into the split | paused | keep |
| bcff073a | watch paseo 1j | codex gpt-6.1-sol | ~/src/djbclark-ade | Paseo upstream watcher; paseo#8780 deferred | watching | keep |
| 6eb6d3f6 | watch cfengine 1f | codex gpt-6.1-sol | ~/src/djbclark-ade | CFEngine upstream watcher; cfengine PR 6424 prep (clean worktree) | watching | keep |
| ff08899e | watch load t | cursor opus-5-5 | ~/src/djbclark-ade | load watcher | watching | keep |
| f111c672 | Set up communications with the GrokBot "Coding" bot | omp opus-5-5 | ~ | Coding bot link; PR 269 to re-home into frdminc/peer-link; Dann<->Eve cut-over approved | paused | keep |
| ebd6ed1a | Do not do this until the "pi" herdr tab... | pi gpt-6.1-sol | ~/src/djbclark-ade | fleet-migrate tool (offline WIP, shelved) | paused | keep (or cancel: shelved) |
| 9e5b46d1 | snipe follow-up | omp sonnet-5-5 | ~/src/djbclark-ade | PRs 252 (merged) and 254 (not merge-ready: Cursor security thread) | paused | keep |
| ac95a703 | You are continuing the session of agent 9e5b46d1... | pi gpt-6.1-sol | ~/src/djbclark-ade | PR 254 backtick repair (pushed e0250889) | paused | cancel? duplicate of 9e5b46d1 |
| 19ece915 | You are continuing the session of agent 7c58015b... | pi gpt-6.1-sol | ~/src/djbclark-ade | helm lead continuation during my outage; recovery notes | paused | cancel? its own rec (i) |
| 18b6d528 | zsh+autorename followups | claude sonnet-5-5 | ~/src/djbclark-ade | autorename session-id fix, PR 259 merged | done | cancel? |
| 501a7e0d | Look at all the installed TUIs... | cursor opus-5-5 | ~/src/djbclark-ade | TUI consolidation plan PR 283, superseded by PR 288 | done | cancel? |
| ce04246a | Find get download best skills to use claude cloud... | cursor grok-4.7 | ~/src/djbclark-ade | Claude Cloud skills research; installed Claude.app + 2 plugins | done | cancel? |
| 23adbb25 | Do this work in a worktree. | cursor composer-2.5 | ~/src/aiuse | aiuse PRs 47/48, v4.0.1 shipped | done | cancel? |
| 2507bcbf | The dann-workspace-accent plugin... | omp sonnet-5-5 | ~/src/paseo | dann-workspace-accent plugin (separate repo) | paused | keep |
| 1057582a | Is there a way to make all of the plugins... | omp sonnet-5-5 | ~/src/paseo | Paseo plugin sync, paseo-runner (stage 2 waits on you) | paused | keep |
| 3846a46e | Do nothing on this yet except name this workspace "herdr4paseo" | omp sonnet-5-5 | ~/src/herdr4paseo | herdr4paseo bridge placeholder; nothing in flight | idle | keep |
| 63c48307 | adapters-s0-pt (check-in id 2b4437d2) | claude sonnet-5-5 | ~/.cow/pastures/paseo4herdr/paseo4herdr-seam-fixes | paseo4herdr adapter; real-shell trial waits on your yes | paused | keep |
| 042d0c8d | v0-release-pt | omp sonnet-5-5 | ~/src/sudo-secretspec | sudo-secretspec rollout (pastebin paste waits on you) | paused | keep |
| c3cbe51a | key-remap-pt | omp sonnet-5-5 | ~/src/plektra-djbclark | Plektra device checks (phone wireless debugging waits on you) | paused | keep |
| ba920539 | N2 mask fix (pi) | pi gpt-6.1-sol | ~/src/te-async-wt | techno-euphora SIGINT fix; committed by Dann 7 | done | cancel? |
| 0b68fe51 | N2 mask fix (pi) | pi gpt-6.1-sol | ~/src/techno-euphora | techno-euphora SIGINT probe; report only | done | cancel? |
| df4a2ed6 | Herald summary (check-in c688cc) | claude haiku-4-5 | ~/src/djbclark-ade | one Herald message on tendcf Q10 | done | cancel? |
| 7df4c112 | Herald summary (check-in ed6863c7) | claude haiku-4-5 | ~/src/djbclark-ade | wind-down; made commit 9946ed38 on the shared checkout | done | cancel? |
| 428f5f02 | Dann VPS 2 | opencode go | ~/src/techno-euphora | Dann work (techno-euphora) | closed | leave closed (never archive) |
| 193014a8 | Dann Chat 4 | opencode go | ~/src/techno-euphora | Dann work | closed | leave closed (never archive) |
| d2a505dd | Dann 7 | opencode go | ~/src/techno-euphora | Dann work; Dann<->Eve cut-over slice queued for it | closed | leave closed (never archive) |

### B2. Herdr panes (herdr is retired; bring into Paseo only if revived)

| pane | harness | cwd | was working on | state | restart (default) |
|---|---|---|---|---|---|
| w20:pE (32779db2) | claude sonnet-5-5 | ~/ops | Finder/mds CPU, daemon freeze, NeoFinder; PR 231 open; removemacai waits on you | paused | revive |
| w20:pQ | omp sonnet-5-5 | ~/src/djbclark-ade-bridge-guard-wt | opencode bridge guard PR 281 (wait until after the split) | paused | revive |
| w20:pN | omp sonnet-5-5 | ~/src/aiuse | aiuse features (all pushed) | done | cancel? |
| w38:p8 | omp sonnet-5-5 | ~/src/djbclark-ade | Pi first-class in ADE (all merged); AGENTS.md item 15 edit pending | done | cancel? |
| w20:pS | codex | ~/src/djbclark-ade-278-recovery-wt | issue 278 recovery architecture, PR 282 merged | done | cancel? |
| w20:p0 | cursor composer | ~/src/aiuse | dsh setup (dsh is being retired) | done | cancel? |
| w20:p11 | cursor composer | ~/src/djbclark-ade | OpenCode /hand YAML fix, PR 286 merged | done | cancel? |
| w20:p12 | cursor composer | ~/src/djbclark-ade | relay answers only | done | cancel? |
| w36:pD | cursor | ~/src/barnowl | "Flash drive in-use processes (mac256usb)"; no check-in | unknown | ask |
| w20:pM | agy | ~/src/bottom | unknown; never checked in | unknown | ask |
| w36:pB | agy | ~/src/barnowl | unknown; never checked in | unknown | ask |

### B3. Not on this Mac
Claude cloud sessions 01BvGHLy (issue 279, PR 291), 01BvGHLzD4 (PR 289), 01BvGHM3 (PR 290): unaffected by the reboot.
