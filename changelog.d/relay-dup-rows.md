### Fixed

- `relay.py` no longer refuses a session as ambiguous with itself: rows of one session (same session id or Paseo agent id) are one recipient, so a full Paseo agent id or session id always resolves, and a short prefix of two different sessions is still refused; `fleet.py` lists a session once when a resume leaves two live Claude processes (registry files) of the same session id, keeping the entry updated last (#222)
