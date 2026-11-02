### Added
- `relay.py` pings the operator (one `hermes-ping`, naming the target, the card, the sender and the message id) when a message has waited 30 minutes behind a question or permission card in its target; once per card and target, bounded and never fatal to the message, `RELAY_CARD_ALERT_S` sets the delay (0 = off), and `--pending` shows `[card alert: ...]` (#PR)
- `relay.py` also tells the sender (one notice) and the operator (one `hermes-ping`) when a text has waited 30 minutes for a merely WORKING target (`RELAY_BUSY_ALERT_S`, 0 = off); it never steers by itself, and the usage text and `skills/session-finder/SKILL.md` name the `--steer` re-send and its lost-work risk (#PR)
- Rules in `docs/orchestration-practices.md` and the dispatch footer: never block on a job over about 2 minutes unless the next step depends on it (a blocking agent is deaf as well as silent), never wait on CI, one progress line per fix-and-review round, a reply stuck behind a card is the operator's to unblock (#PR)

### Fixed
- `relay.py` no longer refuses with "cannot tell who is sending" for an agent in a herdr pane whose `HERDR_PANE_ID` is stale after the pane was moved (seen on an omp in w20:p3): the pane is found by its own process tree (#PR)
