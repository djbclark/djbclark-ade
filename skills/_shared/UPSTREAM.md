# Vendored from zhiluop/siyuan-skills

Source: https://github.com/zhiluop/siyuan-skills at commit 2984f56 (2026-04-28), MIT
(`UPSTREAM-LICENSE`). Taken unchanged on 2026-10-12 after reading every script:
no subprocess or eval; network calls go only to the configured SiYuan API, image
URLs the user passes, and an optional user-configured WebDAV server.

Skills: `siyuan` (concepts, API, templates, flashcards), `siyuan-article-import`,
`siyuan-excalidraw`, `siyuan-markdown`. They are written in Chinese. The scripts
import this `_shared` directory, so it is not a skill and is not linked into clients.

Config: `~/.claude/siyuan.json` (outside the repo; found by walking up from the
script). It holds `api_url` and `local_path` only: the token is optional and this
kernel has no access auth code. If `accessAuthCode` is ever set, keep the token in
`sudo-secretspec`, not in that file.
