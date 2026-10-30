---
name: oc-go-key
description: >-
  Recover a session that stopped with "Go usage limit exceeded" or "Insufficient account funds":
  read which OpenCode Go account is serving this Mac, swap the live credential with `oc-go-key use
  <label>`, and resume the aborted turn so the entity is not dark with a working key. Use when a
  Paseo/OpenCode tab dies mid-turn on a quota or credit error, when OpenCode Go quota is tight,
  when asked which Go account is active or to switch OpenCode accounts, or when a session must
  continue in place instead of in a new tab.
version: 0.1.0
author: Dan Clark (djbclark), Dann 7
license: Apache-2.0
platforms: macos
tags: opencode, opencode-go, quota, credentials, continuity, macos
---

# oc-go-key — the OpenCode Go quota wall

A Go quota wall does not look like a crash. It looks like the tab quietly stopped:

| Text in the tab | Bill it refused | Helps to rotate the credential? |
| --- | --- | --- |
| `Go usage limit exceeded` | the Go subscription behind the active credential | yes, to an account with Go left |
| `Insufficient account funds` | the Console **credit balance** (`opencode/<model>` prefix) | only onto a credential whose balance is not empty |
| `requires Global regions` | not quota at all: the account's workspace region setting | no — fix Settings › Privacy › Regions |

Rotating is a **spend-policy decision** (which account's quota to burn), so this skill reports the
state and performs the rotation when asked; it does not decide on its own which account to spend.

## Read the state first

```sh
~/src/djbclark-ade/skills/oc-go-key/scripts/go-status        # rc 2 = a wall in the last 30 min
~/src/djbclark-ade/skills/oc-go-key/scripts/go-status --hours 24
```

It prints every server, every credential label with the active one starred, the failures in the
log window, and the account table. Read-only; it prints labels and emails, never key material.

## Which credential actually serves Go — the trap

OpenCode v2 keeps credentials in `~/.local/share/opencode/opencode.db`, shared by the background
service and every `opencode serve` a Paseo tab owns. **`opencode-go/*` models are authenticated by
the active credential of the Console integration `opencode`**, *not* by the `opencode-go` key
credential. On 2026-10-29 a day went into activating `opencode-go` keys that were never consulted,
while the real source was an exhausted Console login, with no error saying which credential a
request used ([anomalyco/opencode#52374](https://github.com/anomalyco/opencode/issues/52374)).

Consequence: `oc-go-key list`'s `*` on the `opencode` row is the one that matters. The
`opencode-go` row can be starred and irrelevant.

## Rotate

```sh
oc-go-key list                       # labels, active, which server pids
oc-go-key use dclark                 # label, or a vault name (OPENCODE_GO_API_KEY_<X>)
oc-go-key use djbclark
oc-go-key use t-e
```

`use` activates the credential and `POST /api/location/reload` on every running server, so **running
sessions pick the new key up at their next step — no new tab.** Two consequences, both real:

- a reload **cancels pending permission prompts and forms**; do not rotate while the session is
  waiting on an answer you care about;
- a reload changes the key, **not the prompt**. See below.

`use <vault name>` reads the key with `sudo-secretspec get` (never argv, env or disk) and recreates
the credential if the vault value changed. If a Console **login** of the same label exists, that
login wins and the key is not substituted.

## Resume — the step that is usually skipped

The turn that hit the wall **already failed**. A new key alone leaves the tab idle and silent: the
entity is dark, now with a working credential. Re-prompt it:

```sh
~/src/djbclark-ade/skills/session-finder/relay.py <session-id> \
  "Quota wall: the Go account was exhausted and the credential is now '<label>'. Your last turn was
   cut off mid-work. Check your own last state and continue it; do not restart from the beginning."
```

Find the id from the fleet (`skills/session-finder/fleet.py`), the registry row, or the tab the
session is in — give `relay.py` an **id**, never a name. This applies to your own seat too: after
rotating for yourself, continue in place rather than opening a new tab.

**Read the exit, do not assume the send.** A session stopped on an error is *usually* idle, but
"it is idle, so it went in" is the assumption that leaves the entity dark with a working credential
— which is the whole failure this skill exists to end. From an agent session relay's delivery watch
is on by default and its exit code is the verdict:

| exit | word | what it means for the resume |
| --- | --- | --- |
| 0 | `delivered` | the text is in the target's transcript (or its Paseo timeline): the turn was re-prompted |
| 1 | not delivered | nothing arrived (bad id, an ended session, a refusal): fix the id and retry |
| 3 | `unverified` | sent or still queued with no proof yet — **do not resend**; open the tab and look |
| 2 / 4 | usage / no sender | the send never happened; nothing is pending, nothing to wait for |

`accepted` and `queued` are settlements, not proof: relay keeps watching, but you must not report a
resume you have not seen. When the send ends `unverified`, read the seat before believing it —
`relay.py <id> --why` names what it is doing right now (`idle`, `working`, `silent`,
`card:<kind>`), and a `silent` or `card:` answer means the resume did not land and a human is
needed. Say so through `hermes-ping` rather than moving on, and tell djbclark which account was
exhausted and which credential now serves it.

First contact with a stopped session is where a **named ack** earns its place: put the ask in the
text and pass `--expect-ack <label>`, so the resume is closed by the session's own words and
`--pending` pages you if it never answers.

## When no account has headroom

Stop, and say so:

1. `scripts/go-status` to confirm the wall is quota and not `region`/`auth`.
2. Tell djbclark via `hermes-ping "…: all OpenCode Go accounts exhausted (reset <window>)"`, once.
3. Do not spin: no retries, no re-dispatches. A wall that reset-time fixes is not a bug to work
   around, and burning another pool's quota to hide it is not a continuity fix.
4. If the work matters more than the wait, route it elsewhere for real (`skills/model-routing`), and
   say which pool you moved to.

## Gotchas

- **Prefix chooses the bill.** `opencode-go/<model>` draws the Go subscription; `opencode/<model>`
  draws Console credits. A Go wall on a session that is actually on `opencode/` is a funds wall —
  rotating credentials is right, but check the model prefix before blaming Go. A Paseo agent's model
  is `settings.model`; `paseo agent update` changes it.
- **`dclark` needs Regions = Global** for DeepSeek models (`requires Global regions`);
  its workspace was switched on 2026-10-29.
- **Never print a credential.** Not the key, not an OAuth `access` token, not a log line holding one.
  The 2026-10-29 session leaked a Jina bearer token into a transcript through name-based redaction;
  cite the field name, never the value.
- **`oc-go-key` lives in `~/src/one-offs/stow/bin/oc-go-key`** (stowed as `~/.local/bin/oc-go-key`),
  and needs `sudo-secretspec` for vault names. It cannot run where those are absent.
- **Restarting a tab is not a fix** and not the same thing: it loses the turn, the pending prompt
  and the context. Rotate + resume, in that order.

## Related

- `~/ops/site-private/memory/reference_hermes_opencode_go_key.md` — the Hermes side of the same
  provider (untouched by `oc-go-key`).
- `~/src/one-offs/stow/README.md` § oc-go-key — the upstream tool and how it works.
- `skills/model-routing` — where to send work when Go is not an option.
