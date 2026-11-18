### Fixed
- Match shell heredoc delimiters exactly, preserving quoted Python/YAML data while still rejecting unterminated bodies and live unsafe commands after them. (#797)
- Preserve quoted subshell heredoc boundaries during watcher inspection and match deeply nested substitutions without Python recursion. (#797)
