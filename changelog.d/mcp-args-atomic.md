### Fixed

- `agents/modify_merge_lib.py`: an MCP server's `args` vector is replaced whole instead of merged as a collection, so repeated positional flags survive and a template can clear the live arguments. Same rule as `notify` (Codex review on #771).
