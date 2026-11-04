# Secret-file read-deny: one policy, a hook and static Claude rules (2026-11-04)

Issue #284 item 2. Agents should not read `.env` files, private keys or cloud credentials into a transcript. One
policy file says which paths are secret; a renderer turns it into what each TUI enforces. As of 2026-11-04 only Claude
Code is wired; Codex and opencode are queued (the hook already accepts a Codex `PreToolUse` payload, so wiring Codex is a
config change).

| piece | what |
| --- | --- |
| [`config/secret-deny.toml`](../config/secret-deny.toml) | the policy, the one copy: `deny`, `allow`, and `[claude] static` |
| [`bin/render-secret-deny`](../bin/render-secret-deny) | renders the policy; `--check` reports drift |
| [`config/secret_deny_policy.json`](../config/secret_deny_policy.json) | generated, committed: the deny and allow lists the hook reads (it runs under Python 3.9, which has no TOML reader) |
| [`claude/hooks/secret_read_gate.py`](../claude/hooks/secret_read_gate.py) | the `PreToolUse` hook |
| `agents/claude/settings.json.tmpl`, `permissions.deny` | the generated `Read(...)` and `Edit(...)` entries |

## A. The policy (2026-11-04)

- **A1. Denied:** `.env`, `.env.*`, `*.key`, `*.p12`, `*.pfx`, `*-key.pem`, `*.key.pem`, `privkey*.pem`, and `id_rsa`,
  `id_ecdsa`, `id_ed25519` in any directory; `~/.ssh/**` (the directory too), `~/.aws/credentials`, `~/.netrc`,
  `~/.config/gh/hosts.yml`, `~/.docker/config.json`, `~/.kube/config`.
- **A2. Allowed (wins over a deny for the same path):** `.env.example`, `.env.sample`, `.env.template`, `*.pub`,
  `~/.ssh/known_hosts`, `~/.ssh/config`.
- **A3. Not every `*.pem`.** CA bundles (`/etc/ssl/certs/*.pem`, `cacert.pem`, certifi's bundle) are public and read
  all the time, so only the usual private-key names are denied: `*-key.pem` (mkcert, cfssl), `*.key.pem`,
  `privkey*.pem` (Let's Encrypt). A private key saved as `server.pem` is not covered.
- **A4. Pattern forms.** A name or glob with no `/` matches that file name in any directory; `**/a/b` any depth; `~/a/b`
  under home; `/a/b` absolute. `*` and `?` stop at `/`, `**` crosses it. Render refuses `[...]`, `{...}`, `!`,
  parentheses, backslashes and whitespace.

## B. What is enforced where

- **B1. The hook (Claude now; Codex-ready).** `claude/hooks/secret_read_gate.py` checks:
  - **B1a.** `Read`, `Edit`, `MultiEdit`, `Write`, `NotebookEdit`: `file_path` / `notebook_path`.
  - **B1b.** `Grep` (corrected 2026-11-04): Claude's Grep runs ripgrep with `--hidden`, which excludes only VCS
    directories, so it reads `.env` and descends into `~/.ssh`. The hook blocks a Grep whose root (`path`, else the
    session directory) is a denied file or inside a denied `dir/**`, and otherwise walks the root breadth-first (at most 6
    levels, 20000 entries and 4 s; `.git`, `.svn`, `.hg`, `.bzr`, `.jj`, `.sl` and `node_modules` skipped; symlinks not
    followed, as ripgrep does not) looking for a denied, not-allowed file that the `glob` and the `type` let through. A
    hit blocks, and the message names the file and asks for a narrower `path` or a `glob` that leaves it out (`*.py`,
    `!.env`). When the walk hits a bound it allows (fail open), except for a root at or above a home-level deny (`~`,
    `~/.aws`, `/home`, `/`), which blocks: those trees are big, and they hold `~/.ssh`. The `glob` is matched as ripgrep
    does (no `/`: a name at any depth; with `/`: from the root; `!` excludes, and a `!` glob with a trailing `/`
    excludes directories only; a matched directory covers its files), counting every way the string may be split
    (whole, on whitespace, on commas outside braces). Within one split the globs combine as ripgrep's overrides do
    (corrected 2026-11-04, adversary round 3, checked against `/usr/bin/rg` 14.1.0): the last glob that matches a path
    decides it, so `!.env *` reads `.env` and `* !.env` does not; a directory a `!` glob decides is not entered. The
    `type` (2026-11-04) narrows the walk to the file names ripgrep gives it for `py`, `js`, `ts`, `go`, `rust`, `java`,
    `c`, `cpp`, `sh`, `md`, `json`, `yaml`, `toml`, `ruby`, `php`, `swift`, `kotlin`, `html` and `css` (so `type: "py"`
    passes beside a `.env` and blocks beside a `.env.py`), but only for files no positive glob decides: ripgrep reads a
    file a positive glob matches whatever the `type` (`rg --hidden -t ts -g 'src/**'` reads `src/.env`), and skips a file
    no positive glob matches when there is one. So `{"type": "ts", "glob": "src/**"}`, `{"type": "py", "glob": "*"}` and
    `{"type": "py", "glob": ".env"}` block beside a `src/.env`, while `!` globs alone (`{"type": "py", "glob":
    "!.env"}`) still combine with the type. Any other type (Ruby's is `ruby`; `rb` is not a ripgrep type) narrows
    nothing, and the block message then suggests a `glob` naming the files. The
    `glob`'s text is checked as a pattern (B3) only when the walk could not see the whole tree: the root does not exist,
    or the walk was cut short by a bound (2026-11-04: after a complete walk the files themselves have answered, so
    `glob: ".env*"` passes in a project with no `.env`-named file and blocks beside one).
  - **B1c.** `Bash`: the `command`, split with `shlex` into words; also the part after `=` (`--config=.env`) and each
    `:`-separated part (`-v ~/.aws/credentials:/c`), with `~`, `~user`, `$HOME` and `${HOME}` expanded. Every literal
    word is checked first; then the words with glob characters are expanded against the disk by the hook's own walk,
    one path segment at a time (corrected 2026-11-04: the earlier `glob.iglob` checked its time only per match, so `ls
    /*/*/*/*/*/*/*/zzqq*`, which matches nothing and loops through `/proc/*/root`, ran past 60 s). The walk follows the
    shell: a wildcard never matches a leading `.`; a `**` path segment is zero or more non-hidden directory levels
    (2026-11-04, adversary round 3: zsh's default and bash's `globstar`, so `grep -n TODO **/*` blocks beside
    `a/b/server.key`; it was walked as `*` before); a directory a wildcard or `**` reaches is entered only when it is not
    a symlink (so symlink loops end), and that symlink is itself checked as a path (B1f: `cat */id_*` where `d ->
    ~/.ssh` blocks on `~/.ssh`); a final match may be a symlink and is checked through its realpath. It reads at most
    20000 directory entries and 2 s per call, all glob words together, and checks at most 500 matches per word. When
    nothing matches, or the walk was cut short (a bound, the match cap, or a symlinked directory left unentered), the
    pattern itself is checked (B3), so every word gets at least that check and a bound never lets one through
    unchecked. Measured 2026-11-04: that repro takes 0.07 s through the hook. The order is cheapest first (2026-11-04):
    every literal word, then the glob words without `**`, then those with it; each glob word gets 1 s on its first try,
    and one that runs longer is set aside and retried, with the rest of the 8 s, after every other word, so a slow word
    cannot use up the time a later `cat ~/.ssh/id_*` needs.
  - **B1d.** Codex `apply_patch` headers (`*** Add File:`, `*** Update File:`, `*** Delete File:`, `*** Move to:`) inside a
    `*** Begin Patch` block, in the command or any other string of a non-file tool. The patch body is not read, so a patch
    whose code mentions `.env` passes.
  - **B1e.** Not `Glob`: it returns names, not contents.
  - **B1f.** Each path is checked three ways, separately: as given, absolute against the payload's `cwd`, and its
    realpath. Any of them denied, with no allow matching that same form, blocks. So a symlink `notes.txt -> .env`, or
    `/tmp/a.pub -> ~/.ssh/id_ed25519`, is blocked although its own name looks harmless.
  - **B1g.** A block is exit 2 with one line on stderr naming the deny rule and this doc; Claude shows it to the model.
- **B2. Static Claude rules.** `Read(...)` and `Edit(...)` entries in `permissions.deny`, for the `[claude] static`
  patterns: `.env`, the key extensions and names, `~/.ssh/id_rsa|id_ecdsa|id_ed25519`, and the five home credential files.
  Claude applies them to its file tools even if the hook is missing. Each static pattern must lie inside the deny list and
  share no path with an allow pattern; render refuses one that does not. That is why `.env.*` and `~/.ssh/**` are
  hook-only: Claude's `!` negation is unverified here, works only relative to the session directory (so it cannot reopen
  a `~/` rule) and cannot reopen a file inside a directory that is denied whole. A name with no `/` is written
  `**/name`, which Claude reads relative to the session directory, so the three key names are also listed under `~/.ssh/`.
  Render owns every `Read(`/`Edit(` entry in that list: one added by hand is removed on the next render.
- **B3. A glob that matches nothing on disk** (or that a walk could not finish: B1b, B1c) blocks only when some path could match it, a deny pattern and no allow
  pattern, with two rules against false alarms from code and regexes. The word must spell the deny pattern's literal text
  itself (pinning: `echo *`, `grep 'a.*'`, `x * y` in a heredoc and Grep `glob: "*.py"` pass, while `.env*` and `*.key`
  block). Pinning also makes the check cheap: a rule whose literal text the word cannot spell, reading each `**/` as ""
  or `/`, is skipped before the automaton runs (2026-11-04, adversary round 3: a `**/node_modules/**` word took 0.1 to
  0.7 s, so a 60-line `.gitignore` heredoc followed by `cat ~/.ssh/id_*` ran past 8 s and failed open; it now takes
  about 0.07 s and blocks). For a Bash word, a wildcard also never consumes a leading `.` (the shell's hidden-file rule). Grep gets no such
  rule (2026-11-04: ripgrep runs with `--hidden`, so its `*` does reach `.env.py`); a Grep glob that pinning lets pass
  but that does reach a secret on disk, such as `.e*` beside a `.env`, is caught by the walk (B1b), not here. A deny
  wildcard still lets a word reach into a denied directory: `cat ~/.ssh/id_*` blocks with no key on disk, `find . -name
  '*.key'` blocks, and `find ~ -name 'id_*'` passes.

## C. The honest limits

- **C1. Bash coverage is a speed bump, not a wall.** Words are matched, programs are not run. Known routes through it
  (2026-11-04):
  - **C1a.** Interpreters reading files: `python -c "open('.e'+'nv')"`, `node -e`, `awk` scripts, `sqlite3 .read`.
  - **C1b.** Command substitution and quoting tricks: `cat $(printf .env)`, `` cat `echo .env` ``, `cat .e''nv`.
  - **C1c.** Variables other than `HOME`: `f=.env; cat $f`, `cat $XDG_CONFIG_HOME/gh/hosts.yml`, `$OLDPWD`.
  - **C1d.** Encoded or computed paths: base64, hex, `printf '\x2eenv'`, `rev`, brace ranges built at run time.
  - **C1e.** Glob matches beyond the bounds: a word whose expansion has more than 500 matches, or that the walk cuts
    short (20000 entries or 2 s per call), is checked on the matches found and then only as a pattern (B3), so a secret
    the walk did not reach passes when the word does not spell its name (`cat */*/*` over a tree of more than 20000
    entries passes when `a/b/server.key` lies past the bound; `cat */*/*.key` blocks). A symlinked directory a wildcard
    or `**` matches is not entered; the link itself is checked (corrected 2026-11-04: it was skipped unchecked), so a
    link into a denied directory blocks (`d -> ~/.ssh`), but a link to a harmless directory that holds a secret below
    it (`d -> /srv/app`, with `/srv/app/.env`) is checked only as a pattern: `cat */.env` blocks, `cat */*` passes.
  - **C1f.** `shopt -s dotglob` (or zsh `GLOB_DOTS`) followed by `cat *`: the hook applies the default hidden-file rule,
    so `*` is not taken to reach `.env`.
  - **C1g.** `cd` followed by a relative name that is not itself denied; `~user` for a user other than the policy's home.
  One published tester needed five rounds to stop an agent finding routes. The hook makes accidental and casual reads
  fail loudly; it does not stop a determined agent.
- **C2. `bypassPermissions`.** The Claude template's `defaultMode` is `bypassPermissions`. `PreToolUse` hooks run in
  every mode; whether the static `permissions.deny` rules (B2) still hold under `bypassPermissions` has not been tested
  here (2026-11-04), so treat the hook as the enforcement and the static rules as a backstop to verify.
- **C3. The real wall is the Claude sandbox**: `sandbox.filesystem.denyRead` enforces the same paths at the OS level on
  Bash and its children. It is queued, not done (2026-11-04); the policy file is meant to render into it too.
- **C4. Grep: what the walk trades (2026-11-04; corrects the earlier claim that ripgrep skips hidden files, which is
  false for Claude's Grep).** A Grep whose root holds a `.env` is blocked even when `.gitignore` lists it and ripgrep
  would skip it: the hook does not parse ignore files, so a whole-project Grep in a project with a `.env` needs a `glob`
  (`*.py`, `!.env`) or a narrower `path`. The walk stops at 6 levels, 20000 entries or 4 s and then allows, so a secret
  deeper or later than that in a big non-home tree is not seen; a root at or above a home-level deny (`~`, `/home`,
  `/`) blocks instead whenever the walk is cut short, so a whole-home Grep is refused in practice. `node_modules` is not
  walked, though ripgrep reads it when it is not gitignored. The `type` map (B1b) is the hook's copy of ripgrep's, for
  19 common types, copied from `rg --type-list` of ripgrep 14.1.0 (2026-11-04; the suite checks, where `rg` is
  installed, that each is a ripgrep type and that the copy lists every name ripgrep gives it): a later ripgrep that
  reads more names for a type could reach a denied file the walk thinks it skips; the denied names (A1) fall in those
  types only by extension (`.env.py`, `hosts.yml`, `config.json`), which the copy covers. Measured 2026-11-04: a Grep of this repository's root (about 1200 entries) adds about 45 ms; a
  20000-entry walk of `/usr` about 100 ms; a long brace glob (`**/*.{ts,tsx,...}`, 22 extensions) 0.05 s, down from 5.7 s
  when its text was also run through the pattern check after a complete walk.
- **C5. False positives.** A word that is itself a denied name is blocked wherever it appears: `echo .env`, `grep -n .env
  README.md`, a heredoc whose code holds a bare `.env` word. Escape the pattern (`grep -n '\.env' README.md`), write
  files with the Write tool rather than a heredoc, or have the operator set `SECRET_DENY_OFF=1` in the environment Claude
  Code starts from. `ls ~/.ssh` is blocked too (the directory rule).
- **C6. Case.** Paths are matched case-sensitively except on macOS, where `.ENV` opens `.env`.
- **C7. Fail open.** Bad hook input, a missing or corrupt policy JSON, an internal error, or analysis longer than 8 s
  exits 0 with a one-line `secret-read-gate: ... allowing (fail open)` notice on stderr. The Bash glob walk (B1c) does
  not reach that budget: it stops at its own bounds (20000 entries, 2 s, leaving at least 3 s of the 8 s) and falls back
  to the pattern check, with no notice (2026-11-04). A glob word whose check runs past its own 1 s is retried after
  every other word (B1c), so one slow word cannot starve a later read. Limit (adversary round 4, 2026-11-04): about
  eight crafted slow glob words (each repeat or variant spends its own 1 s) still use up the 8 s before a later glob
  read such as `cat ~/.ssh/id_*` is reached, and the call fails open; a later literal path (`cat ~/.ssh/id_rsa`) is
  checked first and still blocks. Ordinary code tokens are fast; the fix (cache set-aside words, cap the first pass) is
  queued in `docs/queue.md`. A directory that opens but cannot be read to the end
  (`/proc/1/map_files`) is skipped by both walks, as the shell and ripgrep skip it; before 2026-11-04 it raised and
  failed the hook open. A Grep walk that hits its own bound allows silently, unless its glob's text blocks (B1b) or the
  root is above a home-level deny (C4). The hook is registered without `onFailure: block`, so a broken hook never
  blocks every Read; the static rules (B2) still hold then.

## D. Changing the policy

- **D1.** Edit `config/secret-deny.toml`.
- **D2.** Run `bin/render-secret-deny` (Python 3.11 or later). It rewrites `config/secret_deny_policy.json` and the
  `Read(...)`/`Edit(...)` entries of `permissions.deny` in `agents/claude/settings.json.tmpl`, by a text splice that keeps
  every other line and every `{{ ... }}` tag, then checks that the template still parses with the tags masked and differs
  only in that list.
- **D3.** Commit the TOML, the JSON and the template together. `bin/render-secret-deny --check` exits 1 with a diff when
  either output is stale, 0 when clean, 2 on a usage error, an invalid policy or a template whose `permissions.deny`
  list cannot be found. Options: `--policy`, `--policy-json`, `--claude-template`.
- **D4.** The live settings come from the template through the normal install path; the hook reaches
  `~/.claude/hooks/secret_read_gate.py` as a symlink into this checkout (`bin/ade-update` reports a missing link), and
  finds the policy JSON from its own realpath (`../../config/`; `SECRET_DENY_POLICY` overrides it).
- **D5.** Tests: `tests/test_secret_read_gate.py` (the matrix, symlinks, Grep's walk, glob readings, how `glob` and
  `type` combine and the `type` map against `rg --type-list`, Bash, `**` recursion, symlinked directories, Codex
  patches, fail-open, the glob walk's bounds on a synthetic endless tree and a symlink loop, heredoc speed including a
  60-line `.gitignore`, the per-word budget, Python 3.9 syntax) and `tests/test_render_secret_deny.py` (render into copies of the template: idempotent, `--check`, tags and
  other entries kept, the committed JSON equals a fresh render).
