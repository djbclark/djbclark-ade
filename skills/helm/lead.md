# helm lead: get every agent unblocked or safe to quit (`/helm lead`, `/watch lead`)

Operator, 2026-11-02: "Contact all running agents in all tabs in herdr and paseo and see what they need to either continue or be
safe to quit. If they are waiting on things try to change things so everything gets unblocked as soon as possible. But do not lose
money by stopping anything in flight. The other agents should interface with you to ask picklist questions. They should not bring
up blocking cards themselves."

In lead mode this session is the operator's single point of contact for every agent. Agents send it their questions as picklists through
`relay.py`. It answers the ones the repo, the rules or a probe can answer, batches the rest into one prompt for the operator, relays each
pick back, and carries out picks that act on the fleet. Relay mode (SKILL.md section 2) never decides anything. Lead mode decides only
what written rules or facts settle (section 3). `/watch lead` is an alias for this file: watch's own engine has no model and does not do this.

```bash
F="python3 -I $HOME/src/djbclark-ade/skills/session-finder/fleet.py"
H="python3 -I $HOME/src/djbclark-ade/skills/helm/helm.py"
R="python3 -I $HOME/src/djbclark-ade/skills/session-finder/relay.py"
P=paseo   # the Paseo CLI
```

## 1. Survey (spends no turns on peers)

1. `$F list` and `$H scan --all`: every session in every host (Paseo, herdr panes, Claude registry, Hermes, ACP launches).
2. Every Paseo agent that is not archived, `closed` ones included: `$P logs <full id> --tail 25`. Reading the timeline is free. Messaging a
   `closed` agent resumes it, and that costs a turn.
3. Cards and stalls: `$P permit ls --json`, and `$R --why <ident>` for each live agent (it reports `card:*`, `silent` = running with nothing
   new for 15+ min, or `working`).
4. `~/src/djbclark-ade/bin/load-watch admit --json`. Slices and `bg` runs often sit on its gate.
5. Put each agent in one class:
   1. **in flight**: working, busy-background, or a waiter on a slice;
   2. **needs the operator**: a decision, or a physical action (Touch ID, a paste, a phone setting);
   3. **needs another agent or a gate**;
   4. **finished**: work committed or recorded and nothing in flight, so it is safe to quit;
   5. **hung**: `running`, silent, and the last timeline entry is a final report.

## 2. Contact

1. Every live agent (idle, working, busy-background, the watchers) gets the brief in item 4:
   `$R <ident> --message-file F --expect-ack lead-<ident> --ack`. A working agent's copy is queued, never `--steer`ed. A herdr pane is
   reached by typing, which proves nothing (exit 3 `unverified`): do not resend. Watch for its `ack` instead.
2. A `closed` agent gets the brief only when its timeline shows a pending operator decision whose options you cannot write yourself.
   Otherwise summarise its need from the timeline and do not wake it.
3. An agent that is on a card cannot take a message. Relay the card (section 4 item 2): it is the only card this mode still carries.
4. The brief (fill in `{LEAD}` with your fleet id and `{ID}` with `lead-<ident>`):

   > From the lead session {LEAD} (djbclark asked me to get every agent either unblocked or safe to quit, without stopping anything in
   > flight). Reply through relay.py to {LEAD}, starting with `ack {ID}`, with ONE of: (a) `safe to quit` if your work is finished,
   > committed or recorded, and nothing of yours is in flight; (b) `continuing, nothing needed` plus what you are waiting on and when it
   > should end; (c) each decision you need from djbclark as a picklist: a one-line question, 2-4 numbered options each with a short
   > tradeoff, and which one you recommend. I put the picklist to him and relay his pick back to you. From now on do NOT open
   > AskUserQuestion/ask/question cards yourself: a card blocks every message to you; ask me through relay instead. Do not stop or
   > cancel anything in flight. If I can do something for you (run a command, check a PR, answer from a repo), say exactly what.

5. Add one sentence per target with anything you already know that unblocks it, for example "load-watch admit is ok now, your
   gated slice should start" or the answer to the question in its last reply (section 3).

## 3. Unblock it yourself first

1. **Answer** a question whose answer follows from AGENTS.md, a skill, or a probe you just ran. Example (2026-11-02): "dispatch the
   adversary now or wait for the checks?" Answer: now, since the adversary does not need CI and admit was ok. Say which rule or probe
   the answer rests on.
2. **Gates:** tell every agent waiting on `load-watch admit` when it opens. Do not lift a gate and do not bypass one.
3. **Between agents:** pass a need from one agent to the agent that owns it, through `relay.py`, and name who asked.
4. **Never:** stop, cancel or kill a turn or process in flight; `--steer` a working agent; archive an agent with a turn running;
   answer a permission card; pick for the operator on a product, spending, security, or irreversible choice, or anything outside the
   asking agent's grant (djbclark-ade order 11). Those decisions are his, and section 4 asks him.

## 4. Ask the operator

1. Before the prompt, write one numbered prose block. It gives one line of context per decision and lists the things only he can do by
   hand (Touch ID, a paste, a phone or GUI step), which get no picker.
2. Then make one prompt-tool call (`AskUserQuestion`, or omp's `ask`) with one question per decision. Each question:
   1. header chip: the project, 12 characters at most;
   2. options: the agent's own picklist, numbered, in its order, with its recommendation kept.
   A card (a herdr pane's AskUserQuestion, an omp `ask` box, a Paseo permission card) is relayed the same way as SKILL.md 2.1
   and 2.2, then answered with `$H answer <id> --fp <fp> <n>`, `herdr pane send-keys <pane> enter` once the cursor is on his pick
   (read the pane first), or `$P permit allow|deny <agent> -- <request id>` (never without the request id).
3. Send each pick back with `$R <ident> --message-file F --ack`. End the message with "decisions from now on: ask me through relay.py
   as a picklist, not a card".
4. Carry out a pick that acts on the fleet yourself: archive (`$P agent archive <id>`), quit a finished pane (`/quit` typed with
   `herdr pane send-text` plus `send-keys enter`), interrupt a hung turn (`$P agent stop <id>`). Report what each command printed.

## 5. Rounds

Replies arrive as messages (`[Message received] <sender>` in Paseo, or the relayed text). In each round:
1. run `$R --sweep`;
2. gather the new picklists into one prompt;
3. ask the operator;
4. relay the picks back.

The mode is finished when every agent is in one of three states: in flight with nothing needed, waiting only on a by-hand step listed for
the operator, or quit or archived. An ack that is still missing past its deadline (OVERDUE) is handled under peer-relay item 13. At the
end, `hermes-ping` one line: counts by class and what still waits on him.

## 6. Operator rulings (binding in this mode)

1. **`Dann*` tabs** (Dann VPS 2, Dann 7, Dann Chat ...) stay open, always. One may hand off to a new instance, but it is never archived
   (2026-11-02).
2. A **hung** turn is interrupted only on his pick. A **finished** agent is archived only on his pick, never by default.

## 7. Reach limits (seen 2026-11-02)

1. **A Claude background session** (`"kind":"bg"` in `~/.claude/sessions/<pid>.json`, listed by `claude agents --json`) whose recorded
   herdr pane no longer exists: helm prints `no channel` and `herdr pane read` says `pane_not_found`. Read its card yourself by running
   `claude attach <8-char job id>` as a pty service. The full session id prints "No job matching". Killing that attach client detaches;
   the session keeps running in its own process. Before you relay the card, check that its `cwd` still exists and that no later session
   has done the work. Case 2026-11-02: a card 4 days old, its directory renamed, its question already settled by another session's PR.
   Such a card gets an extra option for him, `claude stop <job id>`: nothing is in flight in it, and its transcript stays resumable.
2. **An omp `ask` box in a herdr pane** reads as `idle`, so `helm.py keys` refuses ("not waiting on a prompt"). Read the pane, then use
   `herdr pane send-keys <pane> enter` when the highlighted option is his pick.
3. **An opencode Paseo agent that is `running` but silent** (OpenCode records the turn as finished while Paseo still has it running):
   `paseo agent stop` prints "active run cancellation was not acknowledged", and `~/.paseo/daemon.log` shows "Timed out interrupting
   session during cancel". Do not retry the stop in a loop. Case 2026-11-02: a plain message from its owning seat woke the agent. When
   none does, the owning seat's export, delete, then import under the same id (Dann 7's seat-recovery recipe) brings it back.
