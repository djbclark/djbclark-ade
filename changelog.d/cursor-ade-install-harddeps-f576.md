### Added

- Recorded user-scoped `install_argv` / `update_argv` / `probe_argv` for hard deps `cswap`, `paseo` (`@getpaseo/cli`), and `pi` (`@mariozechner/pi-coding-agent`) (#334).
- Recorded npm `install_argv` / `update_argv` for vendor CLIs `claude-code` (`@anthropic-ai/claude-code`) and `codex` (`@openai/codex`); corrected `cursor-cli` presence/probe to the official `agent` binary and recorded `agent update` (#334).
- Recorded offered `hermes` probe/update (`hermes doctor` / `hermes update`) from NousResearch's installer docs; install stays curl\|bash without `install_argv` (#334).
