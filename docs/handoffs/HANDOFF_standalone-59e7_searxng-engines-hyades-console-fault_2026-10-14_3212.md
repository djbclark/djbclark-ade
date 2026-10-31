---
schema_version: 1
handoff_id: 3212
parent_handoff_ids: []
lineage: none
chain: [standalone-59e7]
repo: kool-ade
workspace: main
branch: master
head_sha: e2cad59d3f145b6a4aa2e4470f059f9c901c4143
created_at: 2026-10-14T22:42:26-04:00
writer: cursor-agent
---
# Handoff — Hyades SearXNG engines, blocked r2 deploy, Hyades console fault

## The Goal

Self-hosted Firecrawl on Hyades (SIPB microVMs) is the first search and fetch rung
everywhere (`web-get`, the shared `firecrawl_search` MCP via `firecrawl-router`, Hermes).
This session's tail tuned its SearXNG backend:

1. Disable Brave (it 429s every SearXNG query) and make the Wikipedia/Wikidata engines send
   a Wikimedia-compliant bot User-Agent. **Done and live (image `-r1`).**
2. Turn on Grokipedia plus twelve specialist engines (operator, 2026-10-14). **Built as
   `-r2` and pushed; not deployed**, blocked by a Hyades host fault.
3. Report that fault upstream (SIPB/hyades#11) and the SearXNG User-Agent defect
   (searxng#6840). **Done.**

## Where We Are

1. **Live:** `forgejo.mit.edu/djbclark/firecrawl-searxng:2026.10.15-b00212a83-r1` runs as
   `djbclark-fc-searxng`. Brave off; Wikipedia/Wikidata patched to `searxng_useragent()`
   with `outgoing.useragent_suffix: "(+<kool-ade firecrawl examples URL>)"`.
2. **Built, not deployed:** `...-r2` (digest `sha256:154518668e87...`). Adds Grokipedia
   (general category: every plain query asks it) and, shortcut-only: hackernews, npm,
   crates.io, lib.rs, pkg.go.dev, huggingface, codeberg, gitlab, openalex (`mailto` = git
   `user.email`, read at build time; the image is publicly pullable, operator chose this),
   crossref, nixos wiki, lobste.rs.
3. **Hyades console fault (host side), since ~22:20 EDT:** every login prints `Could not
   enable linger: No such device or address`; everything using `systemctl --user` fails
   (`Failed to connect to user scope bus ... $XDG_RUNTIME_DIR not defined`). `list`,
   `getconf`, `df`, `logs` work; running microVMs keep serving. The failed `deploy apply`
   **did save `-r2` into `hyades.json`** (getconf shows it) but `daemon-reload` failed, so
   the loaded unit still runs `-r1` until a reload + restart.
4. **Issues:** SIPB/hyades#11 (human) + djbclark/hyades#9 (AI detail), linked;
   searxng/searxng#6840 (Wikimedia User-Agent, cites closed #6454).
5. `docs/queue.md` entry "Hyades SearXNG: turn on Grokipedia" holds the remaining steps and
   the operator's conditional retry instruction.

## What We Tried

1. **Claimed SearXNG's engines from memory twice, wrong both times**: first "Google and
   Bing" (both disabled), then "Startpage and Mojeek" (both `inactive: true`, proof-of-work
   CAPTCHAs). The real general set is DuckDuckGo, Google Programmable Search (`google cse`,
   keyless), Wikipedia, Wikidata. Lesson: compute it from `searx/settings.yml` plus each
   engine module's `categories`, never recall it. Docs corrected (0f16d30).
2. **Patching engine .py files alone would not work**: the base image ships
   *unchecked-hash* `.pyc` files (flags byte `01`), which Python loads without checking the
   source. The layer whiteouts `wikipedia.cpython-314.pyc` and `wikidata.cpython-314.pyc`.
   The build fails loudly if the Python version or patched source changes.
3. **Retried the console** at 22:21, ~22:22, 22:35, 22:38: same errors. Our wrapper uses a
   fresh SSH connection per call (no ControlMaster), and SIPB/hyades has no commits since
   2026-10-12, so it is the host.
4. **Hunk staging by position committed a peer's edit** (1284be5): `git diff` ran in
   parallel with my queue edit, so "first hunk" was another agent's. Undone in b48bff5
   (`git apply -R --cached` of HEAD's hunk; their working tree untouched). Rule added to
   site-private `memory/reference_agent_rules_ops_housekeeping.md` (51b9d27): pick your
   hunk by content, after your edit lands.

## Key Decisions

1. Specialist engines are **shortcut-only** (`!st`, `!gh`, `!arx`, ...), not added to the
   general category: Firecrawl sends SearXNG no category (`SEARXNG_CATEGORIES` unset, and it
   would be global), and keyless APIs are metered per IP (Stack Exchange about 300/day,
   GitHub search 10/min). Rejected: setting `SEARXNG_CATEGORIES`, or moving them into
   general.
2. Grokipedia stays general (operator chose to enable it knowing it is AI-generated and its
   API is undocumented).
3. OpenAlex polite-pool email: the operator chose the git email despite the public image.
   Crossref's engine has no contact setting, so it stays anonymous.
4. Rejected: carrying full upstream engine files in the layer (version skew); we extract the
   base image's own files with `crane export` and patch them with asserted replacements.

## Evidence & Data

1. Build script: `skills/hyades-docker/examples/firecrawl/build-searxng-image` (`REV="r2"`);
   deploy default `SX_IMAGE` in `.../firecrawl/deploy` is `-r2`.
2. Verified live on `-r1`: plain search 8 results; `!arx`, `!st`, `!gh`, `!goc` 8 results
   each through `web-get search --only firecrawl`; `web-get check --only firecrawl` 2/2;
   no Brave lines in the SearXNG journal after 22:09.
3. Console timeline (EDT): clean logins 22:09:05, 22:09:14; 22:10:03 linger failed with
   ESRCH ("No such process") while `systemctl --user` still worked; from 22:20:37 ENXIO +
   no user bus on every login. Full analysis: djbclark/hyades#9 and
   `skills/hyades-docker/tickets/8-console-no-logind-session/ai.md`.
4. Docs touched: `skills/fallback-chains/references/web-access.md` §2.1 (shortcuts and
   limits), `docs/firecrawl-commercial-vs-selfhosted-2026-10-14.md` (engine list),
   `skills/hyades-docker/references/console.md` (known fault #11), `skills/forgejo/SKILL.md`
   (filed-issues list), `bin/web-get` (comment only).
5. Tests: none run this tail (only a comment changed in `bin/web-get`; `py_compile` ok).

## Operator Feedback

1. "Queue it for turning on" (Grokipedia), then picked all engine groups plus documenting
   shortcuts.
2. On the console fault: "Try now, and tell me what the errors are if they happen again. If
   they do not happen again, update the skill to wait 3 minutes and then try again before
   prompting that there is a problem." Errors recurred, so no skill change yet; recorded in
   the queue entry.
3. "Go ahead and open the issue, keeping to our issue-and-fork-issue humans/ai scheme"
   (filed without a separate draft review; disclosed).
4. `/loose` choices: reword Stack Exchange/shared-IP claims (done), add console.md note
   (done), draft then file the SearXNG issue (done, #6840).

## Where We're Going

1. **Next action: when SIPB/hyades#11 is fixed, deploy `-r2`.** Check with
   `~/src/djbclark-ade/skills/hyades-docker/scripts/hyades status djbclark-fc-searxng`
   (rc 0 and no linger error = fixed). Then in `skills/hyades-docker/examples/firecrawl`:
   `./deploy apply`, `hyades stop djbclark-fc-searxng`, `hyades start djbclark-fc-searxng`,
   and verify `web-get search --only firecrawl` plain plus `'!gp general relativity'`,
   `'!hn rust'`, `'!oa transformer attention'`, `'!crates serde'`. Then update the queue
   entry (ship it into the docs and remove it) and add the new shortcuts to web-access.md
   §2.1's "Enabled" list.
2. If the fault proves transient (a later retry just works without a SIPB fix), implement
   the operator's instruction: in `skills/hyades-docker/scripts/hyades`, on those two error
   strings wait 180 s and retry once before reporting.
3. Watch SIPB/hyades#11 and searxng/searxng#6840 for replies; update both tiers of #11 by
   editing bodies in place (forgejo skill two-tier rule 4). When #6840 is fixed upstream,
   drop the patch in `build-searxng-image` (comment there says so).
4. Not this chain's: other `docs/queue.md` items (Ralph postponed, self-slash/omp decision).

## Detached jobs

none

## Quick Start

```bash
cd ~/src/djbclark-ade && git pull --rebase
H=skills/hyades-docker/scripts/hyades
$H status djbclark-fc-searxng; echo "rc=$?"          # fault fixed?
$H getconf djbclark-fc-searxng | rg -o '"image": "[^"]*"'   # never print the whole entry (secret)
bin/web-get search --only firecrawl '!st git rebase onto'   # stack health
gh issue view 6840 --repo searxng/searxng --comments
curl -sS https://forgejo.mit.edu/api/v1/repos/SIPB/hyades/issues/11 | jq '.state, .comments'
```
