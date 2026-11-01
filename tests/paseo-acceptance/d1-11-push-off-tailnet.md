# d1-11: push notification while the Mac is off the tailnet (DRAFT, MANUAL, plan T15)

CONTRACT: D1.11: with the Paseo relay off, a phone push for a permission request or a finished agent arrives
via Expo while the phone has no tailnet route to the Mac.
SCOPE: manual, second daemon only, a throwaway agent. DESTRUCTIVE: second daemon only (the test disconnects the
daemon's network).
STEPS: 1. Start a second daemon with the relay off. 2. Pair the phone. 3. Turn the phone's Tailscale off.
4. Have an agent on the second daemon request a permission. 5. Note whether a push arrives and how long it takes.
EXPECT: push arrives within 60 s (value to confirm: UNVERIFIED).
ON-FAIL: the B8 phone path needs the relay or a tailnet-independent route; ask djbclark before changing the relay setting.
Record yes/no, latency and the daemon version in `docs/d1-results.md`.
