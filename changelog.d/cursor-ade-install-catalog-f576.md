### Added

- Transitional install catalog `config/install.toml` and `ade-install check|catalog|plan|doctor`
  (`bin/ade_install.py`): typed components, key-name references, and login checks; print-only plan and
  observe-only doctor (no install/repair/secret reads) while `config/ade.toml` is absent (#320).
