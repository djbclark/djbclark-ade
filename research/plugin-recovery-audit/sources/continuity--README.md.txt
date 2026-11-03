# Paseo Continuity

Provider failover for [Paseo](https://paseo.sh). When an agent stops because its provider has
exhausted quota or hit a rate limit, Continuity creates a fresh agent on the next configured
provider and gives it a bounded copy of the conversation so work can continue without asking the
failed provider to produce a handoff.

Each transition stays in the same workspace. The successor gets a provider-prefixed title such as
`● Codex · Fix authentication`, chain labels for discovery, and a prompt containing the relevant
timeline. The old chat gets a transition card, while the **Continuity chain** workspace panel links
the related chats.

## Install

Requires Paseo 0.10.1 or later. Enable plugins under **Settings → Plugins**, then:

```bash
paseo plugin install npm:paseo-continuity
# or from GitHub
paseo plugin install github:keefeere/paseo-continuity
```

Plugins are trusted, unsandboxed code. Continuity runs in the Paseo daemon and can read agent
timelines and create agents in their workspaces.

## Configure

Open **Settings → Plugins → Paseo Continuity**. The fallback chain accepts one provider per entry,
optionally with a model and mode:

```text
codex:auto
claude:auto
gemini:auto
```

The safe defaults react only to quota and rate-limit failures, bound transferred context, redact
common secrets, skip unavailable providers, prevent duplicate successors, and stop after the
configured number of consecutive transitions.

Use `/continuity` or the Command Center action to test or trigger a transition manually.

### Composer pill

The pill shows how much quota the current provider has left (its tightest window, e.g.
`Codex 23%`). At or below the **Warn when remaining quota drops to** threshold it shows `⚠` and
suggests compacting and moving. Pressing it opens a chooser of the other providers in your chain,
each with its own remaining quota. **Compact & move** writes a condensed, redacted handoff to
`.paseo/continuity/` (self-ignored by git) and starts the chosen provider on it. Turn on **Use LLM summary**
in settings to have a separate provider/model (for example a cheap or local one) write a summary
that is placed in front of a short verbatim tail; if it fails or times out, the plain transcript
is used. If you ignore the
warning, nothing changes: automatic failover still happens when the provider actually fails.

## How it works

- Watches completed turns in the daemon, independent of the failed provider.
- Classifies quota and rate-limit errors conservatively.
- Serializes a bounded projected timeline and redacts common credential patterns.
- Selects the next ready provider from the configured chain.
- Creates and starts a successor in the same workspace with chain metadata.
- Adds a transition card to the previous chat and exposes the chain in a workspace panel.

Automatic transitions require a fallback provider that is configured and ready in Paseo. A
transition creates a new agent/chat because the current public plugin API cannot replace the
provider of an existing agent.

## Develop

```bash
npm install
npm run typecheck
npm test
paseo plugin install "$PWD"   # first time
paseo plugin reload paseo-continuity
paseo plugin logs paseo-continuity
```

To release, bump the version and push the tag. GitHub Actions publishes to npm through trusted
publishing, and Paseo Cafe picks up the new version:

```bash
npm version patch   # or minor; commits and tags vX.Y.Z
git push --follow-tags
```

## License

MIT
