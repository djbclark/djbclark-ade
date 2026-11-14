### Changed

- `bin/route_agent.py` and `tests/test_route_agent*.py`: clear every ruff finding with behaviour-preserving edits (import order, unused `re`, `removesuffix`, explicit `check=False`, `ClassVar` annotations, collapsed `if`s, unused unpacked names); the two `TRY004` and three `FURB162` findings carry a reasoned `noqa` instead, since their fixes would change behaviour. (#664)
