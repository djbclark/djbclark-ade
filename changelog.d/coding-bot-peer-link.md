### Changed

- `bin/coding-bot` is now a thin wrapper over `peer_mail.py` from the private frdminc/peer-link (`$PEER_LINK_TOOL`, default `~/src/peer-link/peer_mail.py`; `$PEER_LINK_COMM` and `$PEER_LINK_SELF` default to the Coding link and `claude`): `ask` sends, then waits for the reply to that one message (`wait --re ID --fetch`, `drain --re ID`, so agents sharing the mailbox cannot take each other's replies) and prints peer_mail's fenced handover unchanged; `send` prints the id; `wait ID`; `status`. The send runs under `sudo-secretspec run` only when `CODING_BOT_WEBHOOK_KEY` is not already set. Exit codes: 0 done, 1 send failed (peer_mail exit 1 means stored but nobody woken: not to be sent again), 2 usage, 4 `BLOCKED:`, 5 not picked up, 124 timeout. Needs peer-link's `--re` support. The `tell-coding-bot` skill is rewritten to match. (#269)

### Removed

- The `coding-bot` webhook client, `deliver`, `inbox`, `bootstrap` and `prompt` subcommands, the clipboard prompt, the `--from` option and the `~/.local/state/coding-bot` outbox/inbox state: peer-link owns the link, the mailbox, the wake and the reply fencing. `CODING_BOT_WEBHOOK_URL` is no longer used. (#269)
