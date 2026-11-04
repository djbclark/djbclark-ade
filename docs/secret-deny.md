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
  - **B1b.** `Grep`: `path` (a file, or a directory inside a denied `dir/**`), and `glob` as a pattern under `path`.
  - **B1c.** `Bash`: the `command`, split with `shlex` into words; also the part after `=` (`--config=.env`) and each
    `:`-separated part (`-v ~/.aws/credentials:/c`), with `~`, `$HOME` and `${HOME}` expanded. Words with glob characters
    are expanded against the disk; when nothing matches, the pattern itself is checked (B3).
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
- **B3. A glob that matches nothing on disk** blocks only when some path could match it, a deny pattern and no allow
  pattern, with two rules against false alarms from code and regexes: a wildcard never consumes a leading `.` (the
  shell's and ripgrep's hidden-file rule, so Grep `glob: "*.py"` does not reach `.env.py`), and the word must spell the
  deny pattern's literal text itself (so `echo *`, `grep 'a.*'` and `x * y` in a heredoc pass). A deny wildcard still
  lets a word reach into a denied directory: `cat ~/.ssh/id_*` blocks with no key on disk, `find . -name '*.key'` blocks,
  and `find ~ -name 'id_*'` passes.

## C. The honest limits

- **C1. Bash coverage is a speed bump, not a wall.** Words are matched, programs are not run: `python -c
  "open('.e'+'nv')"`, `cat $(printf .env)`, a variable holding the path, `cd` followed by a relative name that is not
  itself denied, base64 tricks and many more get through. One published tester needed five rounds to stop an agent
  finding routes. The hook makes accidental and casual reads fail loudly; it does not stop a determined agent.
- **C2. `bypassPermissions`.** The Claude template's `defaultMode` is `bypassPermissions`. `PreToolUse` hooks run in
  every mode; whether the static `permissions.deny` rules (B2) still hold under `bypassPermissions` has not been tested
  here (2026-11-04), so treat the hook as the enforcement and the static rules as a backstop to verify.
- **C3. The real wall is the Claude sandbox**: `sandbox.filesystem.denyRead` enforces the same paths at the OS level on
  Bash and its children. It is queued, not done (2026-11-04); the policy file is meant to render into it too.
- **C4. Grep on a directory without `glob`** is not blocked: Claude's Grep is ripgrep, which skips hidden files, and
  blocking every project search because a `.env` sits in it would make the hook unusable. A Grep with `path` set to a
  denied file or into `~/.ssh` is blocked.
- **C5. False positives.** A word that is itself a denied name is blocked wherever it appears: `echo .env`, `grep -n .env
  README.md`, a heredoc whose code holds a bare `.env` word. Escape the pattern (`grep -n '\.env' README.md`), write
  files with the Write tool rather than a heredoc, or have the operator set `SECRET_DENY_OFF=1` in the environment Claude
  Code starts from. `ls ~/.ssh` is blocked too (the directory rule).
- **C6. Case.** Paths are matched case-sensitively except on macOS, where `.ENV` opens `.env`.
- **C7. Fail open.** Bad hook input, a missing or corrupt policy JSON, an internal error, or analysis longer than 8 s
  exits 0 with a one-line `secret-read-gate: ... allowing (fail open)` notice on stderr. The hook is registered without
  `onFailure: block`, so a broken hook never blocks every Read; the static rules (B2) still hold then.

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
- **D5.** Tests: `tests/test_secret_read_gate.py` (the matrix, symlinks, Bash, Codex patches, fail-open, Python 3.9
  syntax) and `tests/test_render_secret_deny.py` (render into copies of the template: idempotent, `--check`, tags and
  other entries kept, the committed JSON equals a fresh render).
