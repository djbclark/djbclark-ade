# Install catalog (transitional, 2026-11-09)

Typed component / key-reference catalog with print-only `plan`, observe-only
`doctor` (runs `probe_argv` when recorded), observe-only `keys` (bulk
`sudo-secretspec check` plus per-key `verify_argv` under `sudo-secretspec
run` when recorded), and **bounded `apply`** (user `install_argv` by
default; `system_argv` only with explicit `--apply-system`). Doctor and keys
do **not** repair or read secret values. Full ownership-aware reconciliation
remains later work (`docs/setup-plan.md` S3).

## A. Source

| File | Role |
| --- | --- |
| `config/install.toml` | Transitional editable catalog (`schema_version = 1`) |
| `config/install.schema.json` | Structural schema (checked by `ade-install check`) |
| `bin/ade_install.py` / `bin/ade-install` | Loader, plan, doctor, apply |
| `bin/ade_user_install.py` / `bin/ade-user-install` | User-scoped uv/just fetch, `bin/` symlinks, Linux sudo-secretspec media |

Reader adoption **2026-11-10**: default `ade_install.load_catalog()` reads the
joint install/keys domain through `ade_config.load_effective`. Without a unified
file, the legacy catalog projects unchanged. A present unified file supplies the
base; local metadata overlays it by leaf, and arrays replace whole. No legacy
catalog data is resurrected behind a present unified file. The catalog requires
`install.component`; optional missing `keys` means an empty registry. Pure shared
validation/mapping lives in `bin/ade_install_catalog.py`.

The explicit library `install_path=` override retains its isolated legacy read
and original refusal when `config/ade.toml` is present. Default adoption does not
change the installer, keys engine, ledger paths or system-execution permissions.
No tracked `config/ade.toml` ships (W16, 2026-11-12: the generator and cut-over checklist are in
[config-migration F](config-migration.md#f-unified-adetoml-generation-and-cut-over-2026-11-12); the commit waits
for in-flight catalog edits). Bounded install writes are in the next-but-one section.

The mapping preserves legacy row fields: `[[component]]` and `[[login]]` become
`[[install.component]]` and `[[install.login]]`; jobs/retired jobs keep their
`install.*` paths. `[[key]]` becomes `[keys.<NAME>]`, with the name restored in
the Catalog adapter. Existing key metadata fields merge independently without
ever storing a credential value.

`--root` catalog-only trees still need only `install.toml` and its schema for a
legacy read. Raw unified/local inputs require the root or bundled full effective
schema before scope isolation; an unavailable schema refuses overlays. Generic
`ade-config check|get|diff` expose and validate new domains when present, while
router/gate readers retain their explicit existing domain scope.

## B. Component classes

`hard` · `offered` · `optional` · `suggested` · `never` (from setup-plan S3.2).

- `offered` / `optional` / `suggested` require an explicit `chosen` boolean.
- `hard` is always expected; `chosen=false` is rejected.
- `install` / `update` / `probe` may be prose or the sentinel `UNKNOWN`.
- `install_argv` / `update_argv` / `probe_argv` are argv lists.
  Tokens: `{bin}`, `{root}`, `{home}`, `{prefix}` (default `~/.local/bin` or
  `ADE_INSTALL_PREFIX`).
- `needs_system = true` marks package-manager / root paths; pair with
  `system_argv` (Linux) and optional `system_argv_darwin` (Homebrew).
  `--system --dry-run` / `--print-system-argv` preview the platform pick;
  live system exec needs `--yes --system --apply-system` (default refuse).
- `presence` is a PATH basename fallback when `probe_argv` is absent.
- `paseo_plugin` is an observe-only Paseo plugin id. Doctor runs
  `paseo plugin ls --json` and reports `ok` / `disabled` / `missing` (never
  installs or enables). `install_argv` is refused on these rows; apply skips
  or blocks them. Unchosen optional rows still get a status so missing and
  disabled are visible without failing the doctor exit code.

## C. Keys and logins

`[[key]]` entries are **names and metadata only** (create URL, `verify`,
optional `verify_argv`, expiry=unknown|…). Doctor never reads
`sudo-secretspec` values. Login checks are separate from keys; consent is not
key validation. Recorded login commands (2026-11-09): `claude auth login`,
`codex login`, `agent login` — doctor does not execute them.

Eight fixed S3b metadata probes are implemented through `ade-install verify-key
PROVIDER` (`openai`, `openrouter`, `anthropic`, `gemini`, `deepseek`, `cursor`,
`github`, `telegram`), referenced by those keys' `verify_argv` entries. This
helper is intended to run under the existing `sudo-secretspec run` boundary,
reads only the selected key from its injected environment, and emits no stdout
and no stderr except the allowlisted expiring marker (github). Keys are sent
only in Bearer Authorization, except Gemini's `x-goog-api-key` header and
Telegram's documented bot-token URL path (`api.telegram.org/bot<token>/getMe`;
Telegram defines no header form, the value is interpolated in-process, and
path/query structure characters are refused without any transport); no
query-string secret or key/URL value flags exist.

| Key | Fixed read-only request | Validated metadata shape |
|---|---|---|
| `OPENAI_API_KEY` | `GET https://api.openai.com/v1/models` | `object=list`, array of model objects/ids (empty allowed) |
| `OPENROUTER_API_KEY` | `GET https://openrouter.ai/api/v1/key` | `data.is_free_tier` boolean and nonnegative finite `data.usage` |
| `ANTHROPIC_API_KEY` | `GET https://api.anthropic.com/v1/models` | `data` model rows with `type=model`/id and boolean `has_more` |
| `GEMINI_API_KEY` | `GET https://generativelanguage.googleapis.com/v1beta/models` | Explicit `models` array with `models/…` resource names |
| `DEEPSEEK_API_KEY` | `GET https://api.deepseek.com/models` | `object=list`, array of model objects/ids |
| `CURSOR_API_KEY` | `GET https://api.cursor.com/v1/me` | Nonempty string `apiKeyName` |
| `TELEGRAM_BOT_TOKEN` | `GET https://api.telegram.org/bot<token>/getMe` | `ok=true`, integer `result.id` (bool refused) and `result.is_bot=true` |
| `FIRECRAWL_GITHUB_PUBLIC_TOKEN` | `GET https://api.github.com/rate_limit` | `resources.core.limit` integer ≥ 5000 (an accepted token's documented core rate limit; an unauthenticated 200 reports 60) |

Provider contracts checked 2026-11-10: [OpenAI models list](https://developers.openai.com/api/reference/resources/models/methods/list)
and [OpenRouter current key](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-api-key).
Additional fixed contracts: [Anthropic list models](https://platform.claude.com/docs/en/api/models/list)
explicitly shows Bearer authentication plus `anthropic-version: 2026-10-21`;
that is the implemented API contract, not a date-computed version.
[Gemini authentication](https://aistudio.google.com/api-reference#authentication)
documents header authentication, while [Gemini list models](https://aistudio.google.com/api-reference/models/list-models)
documents the fixed GET and response. The query-key example is not used.
[DeepSeek models](https://api-docs.deepseek.com/api/list-models/),
[authentication](https://api-docs.deepseek.com/api/deepseek-api/) and
[base URL](https://api-docs.deepseek.com/) document its model-list/Bearer contract.
2026-11-12 contracts: [Cursor Cloud Agents API endpoints](https://cursor.com/docs/cloud-agent/api/endpoints)
document the API Key Info metadata `GET /v1/me` and Bearer authentication for
that API; [Telegram `getMe`](https://core.telegram.org/bots/api#getme) documents
the token-bearing path; [GitHub rate limit](https://docs.github.com/en/rest/rate-limit)
documents `GET /rate_limit` (it does not count against the limit and rejects bad
credentials with 401). GitHub's [token expiration and revocation](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/token-expiration-and-revocation)
documents expiring tokens but not the response header's shape for fine-grained
PATs, so the probe treats `github-authentication-token-expiration` as
best-effort: only a leading ISO calendar date is kept, and an absent or
unparseable header reports plain `ok`. Contract checks on 2026-11-12 used only
unauthenticated requests (401/200 response shapes for the cursor and telegram
routes and the github endpoint) plus public documentation; no
credential-bearing request was made.
No actual credential requests were made during the earlier implementation. The helper
makes at most one GET, uses a 10-second socket timeout (the existing outer
key engine also bounds the process), reads at most 256 KiB plus one overflow
byte and refuses redirects. It does not print response or exception bodies,
model ids, key labels, balances or values; no inference call is made.
Only the first page is checked; pagination tokens and `has_more` never cause
extra requests. Explicit empty model arrays are accepted; missing/malformed
arrays are not treated as successful verification.

Helper exits: 0 authenticated metadata; 10 HTTP 401/403 or invalid header-value
characters (and Telegram path/query structure characters); 12 network/TLS/timeout, redirects and other HTTP failures (including
429); 14 missing value; 1 malformed/oversized success data. Rate limits are not
guessed to mean exhausted quota. Authentication success proves neither inference
entitlement/funding nor subscription availability, routing eligibility or Pi
acceptance. Other HTTP errors, including a provider's HTTP 400 key/configuration
rejection, remain conservatively unsuccessful rather than parsed for an
inferred quota/authentication diagnosis. Four tracked rows still have no
probe, recorded deliberately rather than probed against undocumented or
money-spending endpoints (checked 2026-11-12): `ZAI_CODING_PLAN_API_KEY` — the
z.ai API reference (docs.z.ai/llms.txt, checked 2026-11-12) documents chat,
image, video, audio and tool endpoints but no metadata list for the coding-plan
key, so the unauthenticated-observed `/models` route stays unprobed to avoid
false failures; `EXA_API_KEY` — every public endpoint consumes paid credits and
the usage API needs a separately enabled team service key, so any probe would
spend; `JINA_API_KEY` — Reader/Search consume token quota on authenticated
requests and no free metadata endpoint is documented; `GREPTILE_API_KEY` — the
REST metadata routes answer 404 (observed 2026-11-12) and the current API is
MCP with OAuth, whose `get_me` is a POST JSON-RPC call and probes never post.
Expiry reporting is wired where a provider's metadata itself exposes a date
(github); the other metadata endpoints expose none. Batch collection, the
launch-time delivery route and expiry rejoin are implemented (`keys-collect`,
2026-11-12); live validation remains unfinished. Component/key selection behavior is unchanged.

The three-provider extension builds on #552's reviewed fixed transport. Its
code tests use mocked responses only; no inference, billing or pool-acceptance
claims are made. API credits and subscription pools remain separate. The
2026-11-12 extension (cursor, telegram, github) reuses the same transport under
the same rules.

`ade-install keys` / `just keys` (2026-11-09 presence; 2026-11-10 verify) is
setup-plan S3b check-then-verify:

1. Lists catalog key/login references.
2. Runs `sudo-secretspec check --reason "ade-install keys"` when the binary is
   on PATH.
3. For each key with a recorded `verify_argv`, runs
   `sudo-secretspec run --reason "ade-install keys verify <NAME>" --
   <verify_argv…>` (argv lists; the probe reads the key from the injected
   environment). Exit contract: `0` ok, `10` invalid, `11` no-quota,
   `12` unreachable, `13` expiring, `14` missing. Optional stderr marker
   `ADE_KEY_VERIFY:expiring:YYYY-MM-DD` may refine an ok or expiring
   outcome (ISO calendar date only; failure exits stay failure).
4. Writes outcomes atomically to `~/.local/state/djbclark-ade/keys.json` (or
   `ADE_KEYS_STATE_PATH` / `--keys-state`); **no values and no hashes**.

It never calls get/export/set, never prints secret values, and never echoes
probe stdout/stderr bodies into observations. Catalog rows may still say
`verify = "UNKNOWN"` until a probe argv is recorded. Exit 1 when `check`
fails or any verify status is invalid/no-quota/unreachable/missing/error; a
missing `sudo-secretspec` is `unknown` (exit 0). Collect/set remains a later
unit.

## D. CLI

```
ade-install                         # first-run guidance only; exit 0
ade-install check [--root DIR] [--json]
ade-install catalog [--root DIR] [--json]
ade-install plan [--root DIR] [--json]
ade-install update-plan [--root DIR] [--json]
ade-install update [--root DIR] [--json] [--dry-run|--yes] [--id ID ...]
                   [--state PATH] [--prefix DIR]
ade-install bootstrap [--root DIR] [--prefix DIR] [--dry-run|--yes] [--json]
ade-install python [--state-dir DIR] [--dry-run|--yes] [--recover] [--json]
sh bin/ade-bootstrap [--yes] [--recover] [--state-dir DIR]   # cold start: no Python 3.11+ yet
ade-install doctor [--root DIR] [--id ID ...] [--json]
ade-install hermes-choice {skip,self,ai} [--state-dir DIR] [--json]
ade-install keys [--root DIR] [--json] [--keys-state PATH]
ade-install keys-plan [--root DIR] [--json] [--state PATH]   # cached worklist; no probes/writes
ade-install keys-collect [--root DIR] [--json] [--keys-state PATH]   # batch sudo-secretspec set; terminal only, else list + exit 3
ade-install verify-key PROVIDER  # one of the eight fixed providers above; probe exit code only
ade-install apply [--root DIR] [--json] [--dry-run|--yes] [--id ID ...] [--force]
                  [--system] [--print-system-argv] [--apply-system]
                  [--state-dir DIR] [--prefix DIR]
just install-check
just install-doctor
just keys / just keys-check   # ade-install keys (S3b observe; keys-check is the setup-plan alias)
just keys-plan [--json] [--state PATH]   # ade-install keys-plan (cached outcomes only)
just keys-collect [--json]       # ade-install keys-collect (interactive batch; --json lists only)
just keys-check-install       # daily ade-sched job for keys observe
just install-plan
just update-plan            # configured dependency candidates only; no probes/updates
just install-apply-dry
just install-print-system-argv
just doctor                 # alias of install-doctor (setup-plan S2 name)
just doctor hermes          # catalog probe plus S3a checklist probes (setup-plan S3a)
just install [-- --yes]    # asks the S3a Hermes choice on a tty, records it, then apply
just update              # full S4 update: checkout ff + dependency update_argv (--yes) + doctor;
                         # args (e.g. `just update -- --check`) pass through to ade-update alone
just update-auto [-- --apply-checkout|-- --apply]  # observe-only exit 5 by default;
                         # --apply = scheduled apply (mid-turn skip, durable deferral,
                         # failure ping; no job installed by this repository)
```

Python 3.11+ must already be available as `python3` on PATH. Older Python exits
2 with a prerequisite diagnostic before importing the catalog implementation;
without Python, the executable's shebang cannot start. No-argument guidance
does not load a catalog, probe components, download tools or change files.
Explicit subcommands keep their existing behavior and exit contracts. Just is
not needed for these direct CLI commands: preview with `ade-install plan` /
`ade-install apply --dry-run`, then explicitly request a missing Just install
with `ade-install apply --yes --id just`. Python acquisition is the separate,
explicit step below (W17, 2026-11-12); nothing runs automatically, and no
package-manager path is selected.

**Python acquisition (W17, 2026-11-12).** Python is the one prerequisite the
catalog cannot install, so it has its own step: `ade-install python` (Python
already running) and the POSIX-sh cold-start bridge `sh bin/ade-bootstrap`
(no Python yet). Both default to a preview that downloads and writes nothing (the bridge preview only runs
`id -u`). Rules, shared by both:

- Source is `uv` only (`uv python install 3.13`, then `uv python find
  '>=3.11'`); never pip, sudo, a system package manager or a write into system
  Python. They refuse as root (exit 77 / `refused-root`): there is no
  fall-through into a root-owned user install. A missing `uv` is not fetched:
  the report names the command to run (`brew install uv` or Astral's documented
  user installer; exit 69 / `uv-missing`).
- A candidate counts only after it runs (`python -I`, version >= 3.11): `python3.13`,
  `3.12`, `3.11` and `python3` on PATH, then `uv python find` (and, after a
  bridge hand-off or in recovery, the interpreter running `ade-install`). macOS's
  `/usr/bin/python3` CLT stub is never probed by ADE's own code, by any path or symlink (running it
  can raise an install dialog). No `python3` shim is created, so a uv-managed interpreter is invoked
  by path: `PYTHON -I bin/ade-install ...`; the command prints that line.
- Ledger concurrency (keeps #561): `ade-install python --yes` runs under
  `install_ledger_lock`, writes a `python` ledger entry `pending` before any
  download, then `installed` (path, version) or `failed`, preserving every other
  entry. The bridge cannot hold the flock, so it shares a sentinel instead,
  `<state>/python-acquire.pending` (`pid=`, `started=`, `token=`, `argv=`;
  exclusive create, so a concurrent bridge or Python owner loses). The bridge
  `exec`s into `ade-install python --yes`, keeping its pid and exporting the
  one-time token as `ADE_BOOTSTRAP_TOKEN`; the Python side adopts a sentinel only
  when both match (a stale file with a reused pid is never adopted), verifies,
  records the ledger and removes the sentinel. Either side removes only a
  sentinel it observed and adopted or wrote itself (re-read first), never a newer
  owner's. Ledger `python` statuses: `installed` (acquired by uv here or by the
  bridge), `present` (an interpreter found or recovered; source `found` /
  `recovered-found`, so a Homebrew Python is never recorded as ADE-installed),
  `pending`, `failed`. Every uv call runs `uv --no-config`, `uv python find --system
  --no-project`, from the state directory, never from the caller's directory, so a
  `.venv`, `pyproject.toml` or `uv.toml` there cannot steer discovery or downloads.
- Recovery is explicit, never silent: an unknown outcome (timeout, crash, kill)
  leaves the sentinel (and, when the Python side was the one acquiring, a
  `pending` ledger entry; the bridge writes no ledger), and every later run
  refuses with `pending-recovery` (exit 75 from the bridge) naming
  `ade-install python --recover --yes` or `sh bin/ade-bootstrap --recover --yes`.
  Recovery verifies what is there and records it; it never re-downloads. A live
  owner pid reports `owner-active`. A known failure (`uv` exit nonzero, nothing
  verifiable) is recorded `failed` and the sentinel cleared.
- Not done here: crash/orphan recovery of component operations (W18), a
  `python3` shim, fetching uv, Just and full setup (`ade-install bootstrap` and
  `just install` stay separate explicit steps).

`ade-install bootstrap` is a separate opt-in partial bootstrap for a host that
already has suitable Python. Default / `--dry-run` checks PATH and destination
metadata and prints exact argv/cwd only: no version probes, subprocesses,
downloads or state/cache writes. Existing Just is `present-unverified`, never
assumed healthy. Missing Just is planned for the existing user-scoped
`ade-user-install just --prefix DIR` helper; default prefix follows
`ADE_INSTALL_PREFIX` or `~/.local/bin`.

With explicit `--yes`, missing Just is acquired, then the selected executable
must pass `--version` before the next step. An existing off-PATH file or dangling
destination link is verified instead of overwritten. Nonzero version status is
`broken`; execution/timeout or unrecognized version output is `unknown`. Either
stops the flow, as does failed acquisition. The preview argv is exactly
`JUST --justfile ROOT/justfile install --dry-run`, with cwd `ROOT` and the
selected Just's parent prepended only to the child's PATH. No `--yes` is passed
to the installation recipe; other components, keys and provider credentials
are not installed/configured by bootstrap. The preview may run the existing
installer's observe-only component/scheduler checks, so only default bootstrap
is subprocess-free. Acquisition does not create an ownership/removal grant.

Exit 0 means the dry-run was described or the explicitly requested acquisition
and installation preview completed; `setup_complete` always remains false.
Exit 1 reports acquisition/verification/preview failure (or invalid root), and
parser conflicts such as `--yes --dry-run` exit 2. Bare `ade-install` keeps its
guidance-only behavior. This does not acquire Python (see the Python acquisition
step above) or establish full setup.

Daily behind-check (not auto-apply): install
`config/launchd/com.djbclark.ade-update-check.plist` with an explicit log dir
(operator step; queue Carried #15). The same plist is the source of truth for
**macOS launchd** and **Linux systemd** (ade-sched's backends):

```
# Linux (systemd user timer; linger required, else exit 69)
bin/ade-sched --backend systemd install config/launchd/com.djbclark.ade-update-check.plist \
  --set __STATE__=$HOME/.local/state/ade --ade ~/src/djbclark-ade
# or from the canonical checkout: just update-check-install
# (omits --ade so a linked worktree cannot install a job that vanishes after merge)

# Daily S3b keys observe (never prompts / never prints values)
bin/ade-sched --backend systemd install config/launchd/com.djbclark.keys-check.plist \
  --set __STATE__=$HOME/.local/state/ade --ade ~/src/djbclark-ade
# or: just keys-check-install

# macOS (launchd; auto backend also picks this when launchctl is present)
bin/ade-sched --backend launchd install config/launchd/com.djbclark.ade-update-check.plist \
  --set __STATE__=$HOME/.local/state/ade --ade ~/src/djbclark-ade
```

`__ADE__` / `__HOME__` are filled automatically; `__STATE__` is not and exits 2 if left blank.
Pass `--ade` only with a durable checkout (`~/src/djbclark-ade`); never with a linked worktree path.

- `plan` is print-only: `would-install` (has `install_argv`) / `needs-system` /
  `blocked` / `skip`.
- `update-plan` is a pure inventory of configured dependency update candidates.
  It never observes installation/version/activity, runs commands, checks keys,
  reads ownership ledgers or writes state (including repository bytecode caches
  on a cold CLI run). Selection follows catalog classes and recorded choices;
  unchosen/never/suggested rows are skipped. Missing `update_argv` is
  `unconfigured`; update prose is never interpreted as a command. Recorded argv
  tokens are expanded for display only; an invalid token produces `blocked`.
  Explicit `paseo_plugin` metadata marks an `owner-managed` integration and does
  not produce an execution candidate. No component ownership field exists in
  this catalog: every row reports `ownership=unknown` and
  `execution_authorized=false`. `owner_managed=true` comes only from plugin
  metadata; `null` means unspecified, never a claim of ADE ownership.
  `needs_system` is the catalog flag, not proof that false means no root
  effects. Installed/version/activity, root effects and platform compatibility
  remain `unknown`; the catalog's platform list is printed without deciding
  host applicability. JSON has `mode=plan-only`, `steps` and an explanatory
  `note`; text carries the same limits. Exit 0 means a valid plan was produced,
  even with skipped/unconfigured/blocked rows; invalid catalog input exits 1.
  This changes neither automatic update policy, package ownership, scheduling
  nor pool acceptance (2026-11-12: the sentence about `just update` being
  checkout/skills only is superseded — `just update` with no arguments now runs
  `update --yes` plus doctor, below).
- `update` executes each candidate's own recorded `update_argv` (S4, 2026-11-12;
  unit W20). Default `--dry-run` is print-only: candidates with their expanded
  argv and a pre-observation (the same `probe_argv`/PATH-presence observation
  doctor uses), no command runs, no state is written; exit 0. `--yes` runs every
  candidate that is not clearly absent: absent binaries are skipped (the fix
  path is `apply`, not update), each remaining candidate's argv runs exactly as
  recorded (argv list, never a shell string; `system_argv` is never touched
  here and `paseo_plugin` rows stay owner-managed), a scoped doctor then
  validates exactly the updated ids, and each doctor-failing component gets
  ONE update retry and is then reported — nothing is ever rolled back. Exit 1
  when any update command failed or any updated component still fails doctor
  after its retry; the outcome evidence (argv, rc, output tails, pre/post
  observations, doctor before/after fail lists, retries) is written atomically
  to `--state` (default `~/.local/state/djbclark-ade/updates.json`), values and
  secrets never included. Ownership, root effects and platform compatibility
  stay `unknown`: only catalog-selected user-scope `update_argv` runs. Unknown
  ids to `--id` exit 2; `--yes --dry-run` exit 2. New-component installation
  stays with `apply` (S4 bullet 3 is not automated by `update`); scheduling and
  the scheduled-apply policy live in `ade-update-auto --apply` (docs/scheduling.md).
- `doctor` prefers `paseo_plugin` (observe-only `paseo plugin ls --json`), else
  `probe_argv` (runs the tool; argv list, short timeout), else PATH `presence`.
  When `agents/claude/settings.json.tmpl` is present under `--root`, it also
  checks that live `~/.claude/settings.json` registers `context_size_nudge.py`
  under every hook event the template does (queue Carried #10, 2026-11-09); a
  miss prints a hand-apply hint and fails. Doctor never mutates live settings
  (order 11). Doctor also probes `~/.local/state/ade/credential-bak/` (Carried
  #14, delete-after **2026-11-19**): presence only — **WARN** within 14 days
  before that date while the vault still exists, **FAIL** (`error`) on/after the
  date while it still exists; absent is `ok`. Doctor **never deletes** the vault
  and never reads its contents (deletion waits for operator yes after the date).
  Missing, disabled, or failed **expected** components fail the command
  (including hard-dep `graft` when `graft --version` is missing or errors);
  unchosen `paseo_plugin` rows still print `missing`/`disabled` without failing;
  `unknown` is neither healthy nor absent. When `config/pi-pool-acceptance.toml`
  is present under `--root`, doctor also runs an **advisory** `ade-pi-pools`
  check: `warn` names every still-UNACCEPTED pool and keeps exit 0; accepted
  pools (Cursor / Z.ai on the shipped file) stay quiet; doctor never writes
  `accepted=true` (operator flips the file; docs/pi-defaults.md B4). Doctor does
  not repair, install, or enable.
- `doctor --id ID` (repeatable) validates every selected component id before
  probing, then checks only those components. Unknown ids fail. Unchosen
  components never execute a probe in this mode, including unchosen plugins.
  Installation-wide keys/logins, settings, jobs, credential vault and pool
  advisories are skipped. JSON `scope` is `{"kind":"components","component_ids":[...]}`;
  `ok` applies to that scope only. Plain doctor retains all existing behavior
  and reports `scope: {"kind":"all"}`. Text output also identifies partial checks.
- `keys` is observe-only: bulk presence via `sudo-secretspec check`, then
  per-key `verify_argv` under `sudo-secretspec run` when recorded; no secret
  values.
- `apply` defaults to **dry-run**. `--yes` executes user `install_argv` for
  expected missing components (or `--force`). Writes an atomic ledger under
  `~/.local/state/djbclark-ade/install/ledger.json` (or `ADE_INSTALL_STATE_DIR`).
  As of **2026-11-11**, default apply requires a known `missing` observation:
  an unknown presence, failed probe, timeout or probe execution error is
  `blocked` (exit 1), with no installer command or component ledger write.
  A healthy component still skips. `--force` explicitly requests repair or
  reinstallation despite the observation; it does not choose an unchosen
  component, enable observe-only plugins, bypass missing recipes or relax any
  system-execution flag/ledger requirement. Repairing a probe may establish
  presence without authorizing replacement.
  `--system --dry-run` previews `system_argv` as `would-system-install`;
  `--print-system-argv` dumps the same argv print-only. Live `system_argv`
  requires `--yes --system --apply-system` (argv list via subprocess, never
  `shell=True`); `--yes --system` alone still exits 2 (`refuse-system-exec`).
  Exit 0 ok, 1 blocked/failed, 2 system-exec refused / usage.
  As of **2026-11-12**, live component execution holds a shared POSIX lock on
  the stable `ledger.lock` file across fresh planning, ledger load, pending
  record, command and terminal record. Whenever live apply plans an executable
  step or `ledger.lock` already exists, it acquires `ledger.lock` and
  re-validates component observations under the lock before deciding what
  executes; `ledger.json` is loaded only when the locked plan still has
  executable steps. Concurrent applies serialize and recheck presence after
  waiting; one stale snapshot cannot erase another operation's evidence, cause a
  double install or skip a needed install. The lock releases on errors and
  before scheduler reconciliation, which has its own ownership ledger. Dry-run
  and blocked/skip/refused-only component plans load no ledger and, when no
  `ledger.lock` exists, acquire no install lock and create no install state.
  `save_ledger` remains a low-level atomic replacement whose read-modify-write
  callers must hold this lock; all production callers do so.

  This mutex (**2026-11-12**) covers concurrent live owners, not crash/orphan
  admission or recovery. A failed terminal save or unexpected runner exception
  may leave `pending` evidence, and a child could survive an owner crash. Those
  existing unknown outcomes are preserved. Existing explicit apply eligibility is
  unchanged; this is not a new pending/orphan admission gate and introduces no
  automatic retry or recovery. The Python acquisition bridge (W17) uses this lock plus a
  pending sentinel with explicit `--recover` (above); crash/orphan recovery of
  component operations is still separate work (W18).
- `ade-user-install uv|just|cursor-cli|hermes|link <name>|sudo-secretspec` fetches
  release binaries / vendor packages, symlinks a repo `bin/` tool, or stages
  Linux sudo-secretspec media into the prefix. No `shell=True`, no root. Cursor
  reads the version pin from `https://cursor.com/install` then downloads the lab
  tarball; Hermes urllib-fetches `install.sh` and runs
  `bash <temp>/install.sh --non-interactive`. Non-dry-run Cursor/Hermes installs
  require `ADE_USER_INSTALL_TRUST_VENDOR=1` (TLS to the publisher CDN; no forever
  digest pin — standing order 8).
- `ade-user-install sudo-secretspec` (Linux x86_64): resolve
  `frdminc/sudo-secretspec` `releases/latest`, fetch the versioned
  `.tar.gz` + `.sha256`, verify, extract under
  `{prefix.parent}/lib/sudo-secretspec/<version>/`, report
  `libexec` install argv. Opt-in privilege step:
  `--declarations PATH --run-install` (never puts secret values on argv).

## E. Recorded recipes (2026-11-09)

| id | apply path |
| --- | --- |
| `just`, `uv` | `ade-user-install` release fetch → `{prefix}` |
| `skill-everywhere`, `firecrawl-router` | `ade-user-install link` into `{prefix}` |
| `node` | Mac `brew install node`; Linux `system_argv` `apt-get install -y nodejs npm`; `node --version` probe |
| `npm` | separate hard row (`npm --version`); same Mac brew / Linux apt argv as node |
| `graft` | `npm install -g @nanonets/graft` (user npm prefix) |
| `git`, `gh` | `needs_system` + Linux `system_argv` (`apt-get`) + `system_argv_darwin` (`brew`); preview or `--apply-system` |
| `sudo-secretspec` | Mac: `system_argv_darwin` brew tap (`--system` / `--apply-system`). Linux: no `system_argv`; `install_argv` → `ade-user-install sudo-secretspec` (latest → versioned asset → sha256 → extract; libexec install opt-in) |
| `aiuse` | `uv tool install git+https://github.com/djbclark/aiuse` |
| `cswap` | `uv tool install claude-swap` (presence `cswap`) |
| `paseo` | `npm install -g @getpaseo/cli` (CLI only; desktop/daemon later) |
| `pi` | `npm install -g @mariozechner/pi-coding-agent` |
| `claude-code` | `npm install -g @anthropic-ai/claude-code` (presence `claude`) |
| `codex` | `npm install -g @openai/codex` |
| `cursor-cli` | `ade-user-install cursor-cli` (lab tarball → `~/.local/share/cursor-agent` + `{prefix}/agent`); update `agent update` |
| `hermes` (offered) | `ade-user-install hermes` (script fetch + `bash … --non-interactive`); update `hermes update` |
| `ade-claim` | observe-only `paseo_plugin`; no `install_argv` (operator `paseo plugin install`) |
| others | still `UNKNOWN` / no `install_argv` |

## F. Operator path for live system apply (2026-11-09)

Default refuse stays: `ade-install apply --yes --system` → exit 2
`refuse-system-exec`. Opt-in live path (operator machine only; never CI root):

```
# Preview (safe anywhere)
ade-install apply --system --dry-run --id git
ade-install apply --print-system-argv --id git --json

# Live (explicit; writes ledger kind=system_argv)
ade-install apply --yes --system --apply-system --id git
```

`subprocess` uses argv lists only. Prefer `--id` so one package set is
applied at a time. CI must keep using dry-run / print / mocked runners — do
not pass `--apply-system` in automated jobs.

S4b jobs: `ade-sched list` / `diff` / `just doctor` stay report-only (never
unload). `ade-sched reconcile` / `just sched-reconcile` is the first ADE write
path (systemd user units + `jobs.json` ownership ledger; dry-run default;
`--yes` writes; never unloads foreign/unknown or root/`--system`). A full
`ade-install apply` (no `--id`) also plans/runs that reconcile for ADE-owned
labeled jobs (`--no-reconcile-sched` to skip; `--reconcile-sched` to force when
`--id` is set). Convenience: `just sched-reconcile-checks` (pass `-- --yes`).
On a non-write host backend (launchd today on master), apply reports
`skip-reconcile-backend` and the hand `just *-install` recipes still apply.
Full-apply reconcile omits `--ade` (passes `ade=None`) so `Job.from_*` keeps
the linked-worktree refuse, and blocks when the catalog root itself is a linked
worktree (exit 1 / `blocked`) — run from the primary checkout, or use
`ade-sched install --ade <persistent-path>`. See `docs/scheduling.md`.

## G. J6 Paseo plugins (catalog only, 2026-11-10)

Offered `paseo-plugin-*` rows re-landed from stranded #354 (session-guard, baton, asks, questions-please, tell-agent, vitals, resources, skills, and siblings). **macOS host RAM:** `paseo-plugin-resources` chosen, not vitals (`docs/paseo-host-ram-plugins.md`). Install/probe argv stay UNKNOWN until Mac live `paseo plugin ls` (order 11). Doctor observes presence only.

## H. Next units

The bounded S3 Just bootstrap and the explicit Python acquisition step above
are implemented; automatic full setup remains unfinished.

Ownership-aware reconcile beyond the install ledger (setup-plan S3), remaining
owner installers (curl-free Cursor CLI fetch, Hermes offered path — basic setup
via `just hermes-setup`, Paseo desktop/daemon and skill bundle), opt-in
privilege-boundary `sudo-secretspec install --declarations` as a managed apply
step (Linux media staging is recorded), recorded provider `verify_argv` recipes
in the catalog, collect/set batch. S4b cron reconcile write path landed with
systemd (2026-11-10); launchd/`paseo schedule` reconcile write paths remain later work.
Follow-up: tighten `--apply-system` with an ownership generation / read-back
lock if multi-agent installs share a machine.

## Bounded key metadata edits (2026-11-10)

`ade-config set keys.NAME.FIELD VALUE` supports string `create_url`, `verify`,
`expiry` and `notes` for an existing valid registry identity. Local targets
overlay metadata; repo targets edit unified keys when present or the unique
legacy `[[key]]` row. The writer validates the final overlaid catalog and
changes no credential or verification-outcome state. See
[the scalar contract](config-migration.md#c3-bounded-metadata-writes-2026-11-10).

**W16 (2026-11-12).** The same command now also writes `keys.NAME.verify_argv` and
`keys.NAME.components` (arrays of non-empty strings, `--target repo` only), adds a new identity with
`--create-key` (`NAME` matches `[A-Za-z_][A-Za-z0-9_]*`; a unified/local `[keys.NAME]` table or an appended
legacy `[[key]]` row), and edits **existing** install rows by identity:
`install.component.ID.{chosen,install_argv,update_argv,probe_argv,system_argv,system_argv_darwin,platforms}` and
`install.jobs.NAME.{chosen,set,platforms}` (quote ids containing dots: `install.component."a.b".chosen`).
Row edits are `--target repo` only: local component/job arrays replace whole, so a local row edit would shadow the
entire array. Every edit reparses to exactly one changed field and passes the catalog schema and semantics
(a `hard` row cannot be unchosen; argv arrays stay non-empty). Row creation/removal/reordering, `class`, `id`,
free-text `install`/`update`/`probe` commands and credential fields remain refused. See
[config-migration C4](config-migration.md#c4-install-arrays-choices-and-key-identities-2026-11-12).

## I. Cached key worklist (2026-11-11)

`ade-install keys-plan --json` / `just keys-plan --json` reports cached outcomes
from the existing nonsecret keys state. `--state PATH` selects another existing
file; the default honors `ADE_KEYS_STATE_PATH`. It never refreshes observations,
runs commands, contacts providers, reads credential values or writes files.
Exit 0 means a report was produced, including missing/invalid cache; exit 1 means
the catalog could not be loaded. Neither exit establishes healthy credentials.

Every registered key remains visible. A key is selected only through a known
component selected by existing install policy. Unchosen/never components are
skipped; unlinked keys and unknown component references remain coverage gaps.
The report lists selected component purposes and registry creation URLs, with
unknown URLs and absent verify commands explicit. Registry URLs are metadata,
not newly verified browser destinations.

Cached `missing`, `invalid`, `no-quota` and `expiring` request credential review;
`unreachable`/`error` request verification retry, not replacement. Unknown or
absent outcomes remain unresolved. Cached `ok` avoids a replacement suggestion,
but **freshness is always unverified, current verification unknown and
setup_complete false**, even when every cached status is ok. Reports emit only
allowlisted status tokens and validated UTC timestamps from state; raw details,
extra fields and malformed data are not copied to output. No executable store
argv or automatic replacement authorization is produced.
Cache reads are capped at 1 MiB and use nonblocking descriptors; FIFOs, devices
and other nonregular inputs are reported as invalid rather than read.

Source checked 2026-11-11 at
sudo-secretspec `3c37fe3511e4907d643f35d615d27d898bf3b68a` confirms
[`set NAME --reason REASON`](https://github.com/frdminc/sudo-secretspec/blob/3c37fe3511e4907d643f35d615d27d898bf3b68a/sudo-secretspec-cli/src/main.rs#L49),
delegated by the [broker](https://github.com/frdminc/sudo-secretspec/blob/3c37fe3511e4907d643f35d615d27d898bf3b68a/sudo-secretspec-cli/src/broker.rs#L1139)
to [`prompt_and_set`](https://github.com/frdminc/sudo-secretspec/blob/3c37fe3511e4907d643f35d615d27d898bf3b68a/secretspec/src/secrets.rs#L5722).
TTY stdin invokes `inquire::Password`; non-TTY stdin reads value bytes. There is
no companion `secrets-collect` CLI verb at that revision. Future collection must
use direct inherited terminal stdio with no ADE value input/capture, preserve
explicit choices and handle undeclared names without silently adding declarations.
This audit does not establish installed runtime versions, Paseo secure storage
or provider acceptance.

### `ade-install keys-collect` / `just keys-collect` (W15, 2026-11-12)

Batch collection for the selected-key worklist (setup-plan S3b.4-5). Offline-tested
only; no live vault, terminal session or provider call was made.

1. **Fresh observation first.** It runs the `keys` path (`sudo-secretspec check`,
   each recorded `verify_argv` under `run`) so the worklist reflects current
   outcomes, not the cache. A key with no `verify_argv` is settled by a
   value-free presence child under `run` (it exits 0 or 14 and prints nothing).
   The CLI first removes every catalog key name from its own environment, so a
   stale exported `NAME` cannot make a probe pass for a key the store lacks
   (defence in depth: whether `run` forwards the caller's environment is not
   verified). Probes run with stdin closed, so none can prompt on the terminal
   before the batch question. `sudo-secretspec run` refuses to start while a
   required secret is unset, so then every probe is inconclusive: the command
   takes into the batch only the keys `check` itself marks missing (from
   secretspec's source: a missing required secret is the line
   `✗ NAME - description (required)`, or `✗ NAME (required)`; found is `✓`,
   optional or defaulted `○`; only that exact `✗ … (required)` shape counts, matched
   linearly on `\n`-split lines, and only when the count equals the footer's
   `Summary: N found, M missing`, else nothing counts; a name in a description or
   a stray look-alike line therefore fails safe; colour codes are stripped;
   nothing from the output is printed). When `check` fails but no selected key is
   marked, it exits 1 as unconfirmed, never 0.
2. **Worklist** = `keys-plan` selection (components chosen) whose fresh status is
   `missing`, `invalid` or `no-quota`, or `expiring` with a date within 14 days
   (or past) or with no date. A later expiry date waits, so a year-out GitHub
   token is not nagged. Expired keys therefore rejoin the batch on the next run.
3. **Non-interactive** (no terminal on stdin and stdout, or `--json`): prints the
   key names, consumers, purposes and creation URLs, never prompts, never runs
   `set`, and exits **3**. `--json` is the agent form (an agent has no terminal,
   so the operator types values: S3a.3). Exit 2: `sudo-secretspec` not on PATH.
4. **Interactive:** one question for the whole batch, then per key: name, reason,
   consumers, URL, and `[Enter]` to run
   `sudo-secretspec set NAME --reason "ade-install keys-collect NAME"` with the
   terminal's own stdio inherited (no pipes: the value never reaches ade-install,
   an agent, a log or the state file), `[s]kip` or skip `[a]ll`. Choices are read
   with `getpass` (no echo) and only exact tokens count (`""`, `e`, `s`, `a`, `r`,
   `y`, `n` or the full word); anything else, such as a key pasted at the wrong
   prompt, is discarded unread, never echoed or acted on, and three of them mean
   skip all. EOF and Ctrl-C also skip all; Ctrl-C after a successful `set`
   records `stored-unverified`. Catalog-derived text is printed with control and
   escape characters replaced by `?`. A non-zero `set` (for example an undeclared name) offers
   retry/skip/skip-all and prints a hint to declare the name with
   `sudo-secretspec add`; the name is never declared automatically.
5. **Verify straight away** (probe or presence) and write the outcome to
   `keys.json` (status and a fixed-template detail only). Outcomes: `ok`, `stored-unverified` (stored but the
   probe was unreachable/inconclusive), `skipped`, `failed` (still failing or
   expiring after `set`; retry offered). The run ends with a table and exits 0
   only when every key is `ok`. Because `run` refuses while any required
   secret is unset, a key verified early in a multi-key batch can be inconclusive
   only because a later key was still missing; every `stored-unverified` key is
   therefore re-verified once after the whole batch. A replacement key whose
   expiry lies beyond the 14-day window counts as `ok`.
6. **Delivery (decided 2026-11-12, S3b.5 fallback):** no Paseo secure credential
   store has been probed, so nothing is copied into Paseo or any tool's config.
   Each result names its consumers (the key's selected components) and the route
   `launch-under-sudo-secretspec-run`: the consumer reads the key from the store
   when launched under `sudo-secretspec run`. A replaced key needs no
   re-delivery. If a Paseo/TUI secure store is later probed and proven, a writer
   (value on stdin or environment inside `run`, never argv) is a separate unit.
