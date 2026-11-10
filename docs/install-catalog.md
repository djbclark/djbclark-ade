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
No tracked `config/ade.toml` ships, and `ade-config set` explicitly refuses the new
install/keys paths until writer adoption.

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
ade-install doctor [--root DIR] [--id ID ...] [--json]
ade-install keys [--root DIR] [--json] [--keys-state PATH]
ade-install apply [--root DIR] [--json] [--dry-run|--yes] [--id ID ...] [--force]
                  [--system] [--print-system-argv] [--apply-system]
                  [--state-dir DIR] [--prefix DIR]
just install-check
just install-doctor
just keys / just keys-check   # ade-install keys (S3b observe; keys-check is the setup-plan alias)
just keys-check-install       # daily ade-sched job for keys observe
just install-plan
just update-plan            # configured dependency candidates only; no probes/updates
just install-apply-dry
just install-print-system-argv
just doctor                 # alias of install-doctor (setup-plan S2 name)
just doctor hermes          # selected component only (setup-plan S3a)
just install [-- --yes]    # ade-install apply (dry-run by default; --yes for live)
just update [-- --check|--auto|--auto --apply-checkout]
just update-auto [-- --apply-checkout]  # default observe-only exit 5; opt-in checkout apply; plist pending
```

Python 3.11+ must already be available as `python3` on PATH. Older Python exits
2 with a prerequisite diagnostic before importing the catalog implementation;
without Python, the executable's shebang cannot start. No-argument guidance
does not load a catalog, probe components, download tools or change files.
Explicit subcommands keep their existing behavior and exit contracts. Just is
not needed for these direct CLI commands: preview with `ade-install plan` /
`ade-install apply --dry-run`, then explicitly request a missing Just install
with `ade-install apply --yes --id just`. Automatic Python/Just bootstrap is
still unimplemented; no package-manager or Python acquisition path is selected.

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
  This changes neither `just update` (ADE checkout/skills only) nor automatic
  update policy, package ownership, scheduling or pool acceptance.
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
  `--system --dry-run` previews `system_argv` as `would-system-install`;
  `--print-system-argv` dumps the same argv print-only. Live `system_argv`
  requires `--yes --system --apply-system` (argv list via subprocess, never
  `shell=True`); `--yes --system` alone still exits 2 (`refuse-system-exec`).
  Exit 0 ok, 1 blocked/failed, 2 system-exec refused / usage.
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
changes no credential or verification-outcome state. New identities,
`verify_argv`, `components`, installation choices and other array fields remain
refused. See [the scalar contract](config-migration.md#c3-bounded-metadata-writes-2026-11-10).
