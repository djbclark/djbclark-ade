# Pi session backup and fixture recovery — 2026-11-12

## A. Coverage

`ade-backup-stores` includes the `pi` store by default. It copies the complete
`~/.pi/agent/sessions/` tree to `<generation>/pi/sessions/`. The same store can
be selected explicitly:

```sh
bin/ade-backup-stores --only pi --dry-run --json
bin/ade-backup-stores --only pi --strict-stores --dest /private/backup/generation
```

Pi's canonical history is native JSONL. The full files retain session headers,
messages, sibling branches, names, compaction summaries, extension records and
fork `parentSession` paths. Backup does not use the history reader's reduced
user/assistant-text projection. A successful manifest records file sizes and
SHA-256 hashes; generation directories are 0700 and copied files are 0600.

Only the session tree is added. `~/.pi/agent/auth.json` remains excluded; the
agent config, models, extensions and broad `.pi` home are not backup roots.
Existing credential-name/path exclusions also apply within the session tree,
and existing symlink and destination-refusal rules remain in force. Transcript
content is preserved verbatim and can include previously pasted private text.

This is the **default-path** inventory. Pi supports `PI_CODING_AGENT_DIR`,
`PI_CODING_AGENT_SESSION_DIR`, sessionDir settings and explicit CLI/SDK session
paths; this backup store does not discover those alternate locations. Confirm
the manifest's `sources` matches the sessions in use. Historical pi-acp mapping
files are not part of the current native session store and are left untouched.

## B. Recovery boundary

For a recovery, stop writers to the affected Pi session tree, retain any surviving
copy separately, and check the generation's manifest: `ok=true`, Pi store
`status=ok`, and the recorded file hashes. Restore only `pi/sessions/` into the
original session-tree path. Original-path restoration preserves absolute
`parentSession` references; relocating the tree to another home does not rewrite
those references. Do not replace `auth.json` or the surrounding agent directory.

The fixture test simulates loss, restores the original session paths, verifies
all bytes/branch ancestry/fork links and builds a fresh searchable history index
from restored files with no Pi executable or provider access. It proves offline
file recovery. It does not prove live Pi resume, an atomic snapshot across active
JSONL writers, or deployed Mac coverage. The existing file-copy engine is used;
a quiescent source and separate live validation remain necessary for those claims.

Other client store entries and source archives are unchanged. The default
`--keep 0` preserves existing backup generations. Explicit `--keep` retention
and `--clean-parts` retain their existing meanings; this repair changes neither
their policy nor the scheduled job. Keep historical archives in a separate
retained location when using generation pruning.

## C. Evidence and validation

Layout checked on 2026-11-12 against current upstream
[config.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/config.ts),
[session manager](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/session-manager.ts)
and [session format](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/session-format.md).
Their observed Git blob IDs were respectively
`5a9552d5de451817ab06e99f2626e931d15c3384`,
`2420f8a72d80478888e0cb8bad2370be11f9cc3d` and
`715341998fb36c905508ae958727ea49cc84b4d6`.
The public npm metadata for `@earendil-works/pi-coding-agent` 1.5.2 identifies
`earendil-works/pi` as its source repository; no package is pinned or installed
by this repair. No independent native prompt-history database was identified:
the JSONL session tree is the canonical history covered here.

`tests/test_pi_backup_recovery.py` verifies real inventory selection, complete
native-record recovery, private modes/hashes, credential/link exclusions,
source and archive immutability, dry-run/schema checks, missing-store behavior
and destination refusal. The existing backup engine and passive history suites
remain part of validation. Tests use temporary homes and synthetic records only.
