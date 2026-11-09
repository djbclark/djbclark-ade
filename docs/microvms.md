# MicroVMs inventory (podman, kev, laya, hyades-docker)

Snapshot **2026-11-09**. First cut for Carried **#20** (`docs/queue.md`): what this
repo already records about the four named resources, and what is still unknown on
the live Mac / SIPB Hyades host. **No live host facts are invented here** — rows
marked TBD need an operator (or an agent on the Mac with Hyades access) to run
the suggested probes and update this doc with a new snapshot date.

## Scope

| Name (Carried #20) | Kind (as this repo describes it) | Canonical skill / home (outside this checkout) |
|---|---|---|
| **podman** | Local (Mac) container / microVM engine, and the engine inside Hyades CI / image push | brew / `podman`; used by `forgejo-ci` and `hyades-docker` elsewhere |
| **kev** | Jev-like System One judge on Hyades | `djbclark-kev.sipb.cloud` (or shared `djbclark-jevlike`); skill `jevlike` in sipb-agent-skills |
| **laya** | Jev-like System One judge on Hyades | `djbclark-laya.sipb.cloud` (or shared `djbclark-jevlike`); same skill |
| **hyades-docker** | Run OCI images as libkrun microVMs on SIPB Hyades (`NAME.sipb.cloud`) | skill `hyades-docker` in sipb-agent-skills; console script `hyades` |

Related microVMs named in this repo but **not** the Carried #20 title set:
`djbclark-jevlike` (shared judge host since 2026-10-30), `djbclark-fc-api` /
`djbclark-fc-searxng` (Firecrawl stack). They are listed under [Related](#related-hyades-microvms-named-here)
so an inventory pass does not miss them.

Skills that used to live as symlinks here (`hyades-docker`, `forgejo`,
`forgejo-ci`, `jevlike`) were **unlinked** in the 2026-11-06/07 slim-down (E1/E2);
targets remain in their own repos. Relink is still an operator-batch item
(`docs/slim/operator-batch.md` C24; `docs/skills.md`).

---

## A. podman

### A1. Known from this repo

1. **Role in Carried #20's original brief** (`git show pre-slim-2026-11-06:docs/queue.md`
   around the microVM entry, 2026-10-23): rootless podman is the engine of the
   forgejo.mit.edu Hyades runner (one libkrun microVM per job) and the push path
   of `hyades-docker`'s `hyades-registry`; whether **this Mac** runs podman as a
   local sandbox for untrusted code was already marked unchecked.
2. **Mac presence (dated probes, not re-run here):**
   - 2026-10-19 software-factory research found `/opt/homebrew/bin/podman` on the
     Mac (`docs/history/software-factory-reviews/codex-research-2026-10-19.md`);
     no containment test was run.
   - 2026-11-07 injection-classifier eval ran the harness in
     `podman run --rm --network none` on a **podman-machine applehv** VM with
     image `python:3.12-alpine` (`docs/security/injection-classifier-eval-2026-11-07.md`
     §2.3). That proves a working local podman machine existed on that day for
     that eval; it does not prove current health or a standing ADE sandbox policy.
3. **Hyades CI runner (via skill docs cited historically, skill not in this
   checkout):** capacity **4**, one krun microVM per job; stock labels have
   git/node/python3/podman/go but no gcc, JDK or Android SDK; shared host
   loopback / TSI issues documented in forgejo handoffs
   (`docs/handoffs/HANDOFF_standalone-cdee_*`). Per-job resources recorded in
   history as 16 vCPU / ~62.8 GiB / virtiofs + 32 GiB tmpfs
   (`docs/history/apply-toolchain-prompt.md` forgejo row).

### A2. Unknown on the live Mac / host (TBD)

| Fact | Suggested probe (operator Mac) |
|---|---|
| `podman` still on PATH / version | `command -v podman; podman --version` |
| Machine running (applehv) | `podman machine ls; podman machine info` |
| Can pull and run a disposable container | `podman run --rm --network none alpine:3.20 true` (rc 0) |
| Used as a standing ADE sandbox for untrusted reviews | TBD design; no ADE config in this repo names a podman policy |
| Hyades runner capacity / labels still match the 2026-10 notes | On Mac with forgejo skill: follow `forgejo-ci` SKILL.md probes; or Forgejo Actions UI for the `ubuntu` runner |

---

## B. kev (Kev-0.8B)

### B1. Known from this repo

1. **Hostnames / models:** `djbclark-kev.sipb.cloud`, model id `kev-latest`
   (Kev-0.8B), Hyades microVM, CPU; **8,192-token** context
   (`docs/security/injection-classifier-eval-2026-11-07.md` §2.1).
2. **Role:** Jev-like System One judge; historically "loaded by default" when
   kev and laya were separate VMs. Auth: `JEVLIKE_API_KEY` via `sudo-secretspec`;
   helper shape `jevlike ask noul|choice|score` → `decide: yes|no|escalate`
   (act only at p≥0.9 or p≤0.1)
   (`docs/history/apply-toolchain-prompt.md` jevlike row).
3. **Shared VM (2026-10-30):** operator moved the judges onto one Hyades
   microVM `djbclark-jevlike`, one judge at a time, **Kev by default**
   (`docs/paseo-only-rearchitecture.md` E.5; commits named there:
   jev-like-hyades `bff0d6b`, sipb-agent-skills `6d71b98`). The eval of
   2026-11-07 still lists the `djbclark-kev.sipb.cloud` endpoint — whether
   that name still resolves separately or only through `djbclark-jevlike` is
   TBD on the host.
4. **Measured fitness (2026-11-07):** unusable as a prompt-injection gate
   (0% recall at the act bar; ~near-chance; p50 ~4.1 s under 2-concurrent load).
   Free (self-hosted). See the eval doc §4–§6. Setup-plan / security plan
   sections restate: do not use Kev for that gate.
5. **Skill status here:** `skills/jevlike` unlinked (E2); canonical copy
   `~/src/sipb-agent-skills/skills/jevlike` (Forgejo:
   `djbclark/sipb-agent-skills`). Source tree also named `~/src/jev-like-hyades`
   in the pre-slim queue brief.

### B2. Unknown on the live host (TBD)

| Fact | Suggested probe |
|---|---|
| Is `djbclark-kev` still a distinct microVM, or only `djbclark-jevlike`? | `hyades list` / `hyades status djbclark-kev`; `hyades status djbclark-jevlike` |
| Which judge is loaded now | `hyades getconf djbclark-jevlike` (or kev); never dump secrets — filter image/name fields |
| Endpoint answers `choice` | From Mac with key: `sudo-secretspec run -- …/jevlike ask choice …` (see skill); or HTTPS probe only with the operator's key path |
| Quota / restart behaviour / disk | `hyades df`, `hyades logs …` (operator); TBD numbers |
| Who can reach it | SIPB Hyades account + `JEVLIKE_API_KEY` holder (djbclark); agents must not post on `SIPB/*` |

---

## C. laya (Laya)

### C1. Known from this repo

1. **Hostname / variants:** `djbclark-laya.sipb.cloud`; variants measured
   `english` (512-token context) and `typed-decisions` (1,024-token);
   one judge loaded at a time, switch via `jev-like-hyades scripts/deploy`
   (`docs/security/injection-classifier-eval-2026-11-07.md` §2.1).
2. **Same jevlike / `JEVLIKE_API_KEY` / decide thresholds as kev** (history
   apply-toolchain row; pre-slim queue).
3. **Shared with kev on `djbclark-jevlike` since 2026-10-30** (paseo-only E.5);
   Kev default, so Laya is the alternate load.
4. **Measured fitness (2026-11-07):** near-chance as injection gate; **silently
   truncates** long state (`usage.truncated` / `state_tokens_dropped` on 73 and
   33 samples for the two variants). Free / CPU microVM. Not recommended for
   that gate.
5. **Skill / source:** same as kev (`jevlike`, `jev-like-hyades`).

### C2. Unknown on the live host (TBD)

| Fact | Suggested probe |
|---|---|
| Distinct `djbclark-laya` vs only `djbclark-jevlike` | `hyades status djbclark-laya`; `hyades list` |
| Currently loaded variant | getconf / deploy status in `~/src/jev-like-hyades` |
| Multilingual variant (unevaluated 2026-11-07) | only if operator wants that probe |
| Same reachability / key questions as kev | see B2 |

---

## D. hyades-docker

### D1. Known from this repo

1. **What it is (Carried #20 brief + skills inventory):** skill to run OCI
   images as **libkrun** microVMs on SIPB Hyades at `NAME.sipb.cloud`;
   `scripts/hyades` is the SSH console wrapper; `hyades-registry` push path
   (also `HYADES_ENGINE=crane|skopeo` for VM-free push on the Mac — from git
   history of the skill, not present in this checkout).
2. **Canonical location:** symlink was
   `skills/hyades-docker` → `~/src/sipb-agent-skills/skills/hyades-docker`
   (`docs/slim/inventory.md`, wave2-E1 report); unlinked E1; operator relink
   still open (C24).
3. **Consumers still documented here:**
   - Self-hosted Firecrawl on Hyades (`djbclark/firecrawl-hyades`); Mac side
     `bin/firecrawl-router` + MCP `firecrawl` (`docs/mcp-servers.md`,
     `docs/threat-model.md` entry 10).
   - Named Firecrawl-related microVMs: `djbclark-fc-api`, `djbclark-fc-searxng`
     (10-microVM account quota noted 2026-10-24 in `docs/mcp-servers.md`).
   - Handoffs under `docs/handoffs/HANDOFF_standalone-59e7_*` and
     `HANDOFF_standalone-cdee_*` record console faults, TSI/loopback shims,
     and ticket maps (`SIPB/hyades`, libkrun).
4. **Trust notes:** a public-read-only GitHub token for developer search lives
   in the `djbclark-fc-searxng` microVM envs (readable by Hyades admins /
   `hyades getconf`); threat-model § entry 10.
5. **Not in this checkout:** the skill tree, `examples/firecrawl/`, tickets/,
   or `scripts/hyades` binary — only docs and history point at them.

### D2. Unknown on the live host (TBD)

| Fact | Suggested probe |
|---|---|
| Skill relinked into agent skill dirs | `ls -l ~/.claude/skills/hyades-docker ~/src/sipb-agent-skills/skills/hyades-docker` |
| `hyades` wrapper on PATH | `command -v hyades; hyades list` (needs SIPB creds / SSH) |
| Which djbclark-* microVMs are up | `hyades list` / `hyades status <name>` |
| Account quota used / free | compare list length to the "10-microVM" note; confirm with SIPB docs or getconf |
| Registry push path (podman vs crane/skopeo) | read live skill `hyades-registry`; `command -v crane skopeo podman` |
| Firecrawl stack health | from Mac: MCP/router health; on Hyades: `hyades status djbclark-fc-api` and `…-fc-searxng` (operator) |

---

## Related Hyades microVMs named here

| Name | Role (repo evidence) | Doc anchors |
|---|---|---|
| `djbclark-jevlike` | Shared host for Kev/Laya, one at a time, Kev default (2026-10-30) | `docs/paseo-only-rearchitecture.md` E.5 |
| `djbclark-fc-api` | Firecrawl API microVM; `RESEARCH_PROXY_URL` → local 3010 | `docs/mcp-servers.md` |
| `djbclark-fc-searxng` | SearXNG + `devsearch`; holds public GitHub token env | `docs/mcp-servers.md`, `docs/threat-model.md`, handoff 3212 |

Other Firecrawl companion VMs (Playwright, Caddy gate, etc.) appear in skill
history and firecrawl-hyades docs; **not enumerated from this checkout** —
fill from `hyades list` and firecrawl-hyades when probing.

---

## E. What "full use" still means (Carried #20, not done)

From the pre-slim queue brief (2026-10-23), after inventory:

1. Route heavy tests/builds and untrusted-code probes off the Mac onto Hyades /
   disposable podman where appropriate (`forgejo-ci` CI-first lane).
2. Use kev/laya (jevlike) at process sites that once pointed at `docs/jev.md` /
   `bin/jev` shadow mode — **those files are gone** with Jev (slim-down E2);
   any new sites need a fresh design against current Paseo-only tooling.
3. Do not fan out past Hyades runner capacity; never have agents post on
   `SIPB/*`.

This first cut only does the inventory document. Updating live facts and
routing work stays on Carried #20 until those land.

## F. Sources in this repo (non-exhaustive)

- `docs/queue.md` Carried #20; full pre-slim text:
  `git show pre-slim-2026-11-06:docs/queue.md` (section starting
  "Make full use of the podman, kev, laya and hyades-docker microVMs")
- `docs/security/injection-classifier-eval-2026-11-07.md`
- `docs/paseo-only-rearchitecture.md` E.5
- `docs/mcp-servers.md` (Firecrawl / fc-* VMs)
- `docs/threat-model.md` (Hyades token residual)
- `docs/skills.md`, `docs/slim/inventory.md`, `docs/slim/operator-batch.md` C24
- `docs/history/apply-toolchain-prompt.md` (jevlike / forgejo rows)
- `docs/history/software-factory-reviews/codex-research-2026-10-19.md` (podman path)
- `docs/handoffs/HANDOFF_standalone-59e7_*`, `HANDOFF_standalone-cdee_*`
