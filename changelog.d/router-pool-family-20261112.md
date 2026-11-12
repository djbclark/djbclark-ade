### Fixed

- Match route quota to explicit pool families so Cursor Grok Bot cannot fund Composer/Auto, preserve parent constraints and Claude model caps, and reject familyless fallback readings. (#581)
- Cap Antigravity and Pi OpenAI API/Z.ai waves at one canary per pool until the lead observes a successful turn. (#581)
- Print provider-native unattended modes in dispatch commands so Claude, Codex and Antigravity workers do not inherit Default permissions; omit mode for Pi, which reports none. (#581)
- Load named-family quota before dispatch eligibility checks, map models to their explicit policy families, and align gate fixtures with fail-closed unknown quota. (#581)
