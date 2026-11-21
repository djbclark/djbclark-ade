### Fixed

- `docs/model-routing.md` A2c names the frontier tail (Neon, Argon, cursor-grok) as the one exception to "the score decides" and gives its order under the right condition (static rank Neon, Argon, cursor-grok when neither codex nor claude is a candidate); B4a states when Argon is admitted (only while codex or claude is short on quota, not for an `exclude` or wave cap) and when `alternatives` shows it (PR 919 LOW-1, LOW-2; PR 921 r1). (#921)
