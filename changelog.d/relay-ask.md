### Added
- `relay.py --ask`, `--inbox`, `--answer` and `--withdraw`, a question ledger for leads: a decision for a lead is a 0600 record under `~/.local/state/relay/asks/` that the lead reads with `--inbox`, never text typed into its turn, so a lead on a card or mid-turn no longer queues (cap 20) and loses its replies. `--ask` opens the asker's expectation under the question's id and queues one wake-up text per target outside every cap; the pick comes back as `ack q-ID pick N: <option>`. Only the addressed lead, or the operator with the question's nonce and the operator token file (`--nonce`, `--operator-token-file`, `--via-label`), answers. `--pending` lists questions and `--sweep` expires and prunes them (#261)

### Changed
- `relay.py --cancel` refuses (exit 2) a queued message addressed to the caller: a message is read when it is delivered, and only its sender or the operator from a shell cancels it (#261)
