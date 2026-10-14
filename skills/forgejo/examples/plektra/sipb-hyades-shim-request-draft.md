# DRAFT, not filed. Title: Request: ship a precompiled loopback LD_PRELOAD shim in the ci-images (opt-in), for jobs that start local servers

## Summary

Jobs on the `ubuntu`, `alpine` and `rocky` labels that start a local server on loopback (Gradle test workers, okhttp MockWebServer, WebSocket
clients, anything that listens on port 0) hit three libkrun TSI behaviours: a listener bound to port 0 is unreachable (libkrun#818); a thread blocked in
`recv()`/`accept()` blocks `send()`/`shutdown()`/`getpeername()` on that socket (libkrun#819, #926); and a listener closed during a blocked `accept()` stays
alive, so a new listener on the same port loses connections (libkrun#929; see also #860). A small `LD_PRELOAD` shim works around all three, and I would like
to ask whether you could ship it, precompiled and **opt-in**, in the ci-images.

Prepared with an AI coding assistant (Claude Code) from probe runs on the runner; I reviewed the results.

## Evidence

1. The shim builds from one source file and works the same on all three labels (ubuntu glibc 2.43, alpine musl, rocky glibc 2.39), run 238: port-0 listener unreachable without it and reachable with it; `send()` behind a blocked `recv()` takes 3004 ms without it and 1 ms with it; a listener-reuse probe succeeds 20 of 20 rounds with it and 1 to 2 of 10 without it.
2. A real Gradle/Robolectric suite (1,417 tests) went from 7 failures per run (a different flaky subset each time) and a hang in the test step to 1 failure (a test that also fails on GitHub Actions and on a laptop), in two consecutive runs (229, 230). A standalone okhttp MockWebServer loop went from about 30% failures and 150 s per 150 iterations to 0 of 800 failures and 1 s per 800.
3. Details, probes and numbers: SIPB/hyades#2, libkrun#818, #819, #860, #926, #929, and https://github.com/djbclark/djbclark-ade/tree/master/skills/forgejo/examples/plektra (`loopback-port-shim.c`, `duplex-probe.c`, `reuse-probe.c`, `dup-bind-probe.py`, `java-churn/`, `shim-by-default.md`).

## What I am asking for

1. A precompiled `/usr/local/lib/portshim.so` in each ci-images Dockerfile (a build stage with `gcc`; glibc build for ubuntu and rocky, musl build for alpine), from `loopback-port-shim.c` (about 270 lines of C, MIT-compatible, I am happy to license it as you prefer). Today every job installs `gcc` (about 30 s) and compiles it.
2. **Opt-in, not global.** Jobs enable it with `LD_PRELOAD=/usr/local/lib/portshim.so` or one line into `/etc/ld.so.preload`. I am not asking for it to be preloaded for every job, because: it makes blocking reads wait in `poll()`, which changes `EINTR` behaviour for programs that rely on `SA_RESTART` (untested); it does not reach Go or other static binaries, which the images ship (`golang`, `podman`, `hugo`); and with `capacity = 4` the VMs share the host's loopback ports (#860), which the shim only reduces.
3. Optionally: if you carry your own libkrun fork ("2.0-sipb"), the proper fix is in the guest TSI driver (not holding the socket lock across a blocking `recv`/`accept`; releasing a closed listener; port-0 binds), and then the shim goes away.

## What I checked on your side (documented, not tested here)

The runner config has `runner.envs`, `container.options` and `container.valid_volumes`, which would allow a global setting later; and a job can already use any image with `container: image:` (verified: ghcr.io/cirruslabs/android-sdk:36 pulled in 47 s), so none of this blocks me. I am asking because a shared image would help everyone who runs Java/okhttp/WebSocket tests on Hyades.
