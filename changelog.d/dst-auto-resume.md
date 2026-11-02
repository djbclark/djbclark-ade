### Fixed

- Fixed `acp-dispatch` auto-resume scheduling across a DST change (2026-11-01): the schedule was computed on a fixed-offset `now`, so a `pmset` wake (and `not_before_iso`) that fell after the US fall-back or spring-forward was an hour off; it now computes in UTC (`now_utc()`, frozen by `ACP_DISPATCH_NOW` for tests) and shows local wall time only at the wake instant, in the real zone from `local_zone()` (`TZ`, else `/etc/localtime`); the wake tests are frozen-clock cases across both America/New_York transitions (#213).
