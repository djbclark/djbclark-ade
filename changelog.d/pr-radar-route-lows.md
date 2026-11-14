### Fixed

- `bin/pr-radar-route`: a router failure now shows route_agent's JSON `reason` ("no eligible service with headroom" is printed on stdout) on stderr, with the last stderr line after it, instead of only the exit code or an aiuse note; a template dispatch (`<id from: …>`, `cursor-cloud launch --repo <url>`: any `<`/`>`) is refused instead of becoming a provider/model override (#688).
- `bin/route_agent.py`: several accounts of one pool keep every window, model sublimit and sublimit reset (the last account's used to overwrite the others); a copy of the file without the ADE modules fails with one stderr line and exit 2, not a traceback (#688).
