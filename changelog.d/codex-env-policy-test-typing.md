### Changed

- `tests/test_codex_shell_env_policy.py`: the helpers `rendered`, `policy_toml`, `Policy` and `tool_env` now carry type annotations
  (typed dicts, `ClassVar` and `@override` on `Policy`, narrowed `CODEX` and pipe handles in `tool_env`, explicit `_ =` on ignored call
  results). No test behaviour changes; it clears every basedpyright error and unknown-type warning in that range. (#851)
