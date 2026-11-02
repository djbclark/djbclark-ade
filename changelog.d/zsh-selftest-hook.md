### Added

- The Claude session-start hook (`claude/hooks/cswap_quota_context.sh`) also ran `~/.config/zsh/selftest.sh` (the zsh port of the bash shell-config selftest, installed 2026-11-02 when zsh became the login shell) when a zsh config file changed since its last passing run, with its own mtime stamp; skipped where the zsh port is absent (#250)
