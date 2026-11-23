### Fixed

- Map model families and `--effort` onto Paseo's separated `thinkingOptionIds` catalog shape in `bin/model_family.py`, `bin/route_agent.py`, and `config/ade.toml` (`gemini-*-neon --effort high`, `gemini-*-argon --effort high`), keeping backward compatibility for legacy `-<effort>` family suffixes and bare-id catalogs (#950)
