# Vendored from zhiluop/siyuan-skills

Source: https://github.com/zhiluop/siyuan-skills at commit 2984f56 (2026-04-28), MIT
(`UPSTREAM-LICENSE`). Taken 2026-10-12 after reading every script and scanning every
`SKILL.md` and reference file: no subprocess or eval, no injection patterns; network
calls go only to the configured SiYuan API, image URLs the user passes, and an
optional user-configured WebDAV server.

**One local patch** (the only change from upstream): `siyuan-article-import/scripts/
import_article.py`, `ensure_notebook_exists`, unwraps the `{"notebooks": [...]}` shape
that SiYuan 3.8.6's `/api/notebook/lsNotebooks` returns; upstream iterates it as a bare
list and crashes with `AttributeError: 'str' object has no attribute 'get'`. Found by a
live write test on 2026-10-12 (create doc, check blocks, delete). Draft issue:
`docs/upstream-issues.md` #3. Drop the patch if upstream fixes it.

Also from that test: `verify_document` right after `create_document` reports 0 blocks
because SiYuan's SQL index lags by a moment (3 blocks a few seconds later); not a bug in
the doc, just don't trust an immediate 0.

Skills: `siyuan` (concepts, API, templates, flashcards), `siyuan-article-import`,
`siyuan-excalidraw`, `siyuan-markdown`. They are written in Chinese. The scripts
import this `_shared` directory, so it is not a skill and is not linked into clients.
`SKILL.md` in `siyuan-excalidraw` says `pip install requests`; use `uv`, and note the
default `python3` (`~/.local/bin`, 3.14) already has `requests`.

Config: `~/.claude/siyuan.json` (outside the repo; found by walking up from the script):
`api_url`, `local_path`, and **`"api_token": ""` (empty, but the key must exist)**:
`import_article.py` indexes `config['api_token']` directly and raises `KeyError`
without it, while `insert_image.py` uses `.get`. This kernel has no access auth code, so
an empty token is accepted. If `accessAuthCode` is ever set, keep the real token in
`sudo-secretspec`, not in that file.
