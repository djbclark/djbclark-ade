# Runner notes: forgejo.mit.edu CI (moved verbatim from skills/forgejo/SKILL.md, 2026-10-14)

The long-form findings behind `SKILL.md`; every claim here carries its run numbers.

Runner: SIPB's `sipbphus` (Forgejo Runner v13.1.0), docs in `SIPB/hyades`
(`docs/inessential.md`) and `SIPB/ci-images`. Read these before debugging.

1. **Label is `runs-on: ubuntu`**, not `ubuntu-latest` (a job on the wrong label
   waits forever, no error). Image `forgejo.mit.edu/sipb/ci-images:ubuntu`:
   Ubuntu 26.04, root with `sudo`, git, node 22, podman, nix. **No Java, no
   Android SDK** (`apt-get install` works; Android/Gradle/Maven hosts reachable).
2. **No default actions host:** write `uses: https://github.com/actions/checkout@v4`.
   `upload-artifact@v4` is unsupported on Forgejo.
3. Workflows live in `.forgejo/workflows/`; when that directory exists
   `.github/workflows` is ignored. The job starts within a second of the push.
4. Hardware seen by a job: AMD EPYC, `nproc` 16, 62 GB RAM, 931 GB disk. It is a
   libkrun microVM, shared with other users, so repeat runs for timings.
5. **Gradle needs the port-0 shim there.** Inside the job a listener bound to port 0
   cannot be connected to (even from the same process): libkrun TSI bug libkrun#818;
   fixed-port binds work. Gradle's daemon, test workers and Kotlin daemon all bind
   port 0, so unshimmed builds die with "Could not connect to the Gradle daemon"
   (runs 168-174, 176). SIPB does not want `krun.use_passt=1` (nested passt). **Fix,
   verified in runs 175 and 177 (Gradle daemon, forked test worker, 4+ test steps
   `BUILD SUCCESSFUL`):** `examples/plektra/loopback-port-shim.c` is an `LD_PRELOAD`
   shim that rewrites port-0 `bind()` to a random port in 20000-32000. In the job:
   `apt-get install -y gcc libc6-dev`, `gcc -shared -fPIC -O2 -o /usr/local/lib/portshim.so
   shim.c -ldl`, `echo /usr/local/lib/portshim.so >> /etc/ld.so.preload` (root).
   **An `LD_PRELOAD` written to `$GITHUB_ENV` does not reach Gradle's daemon (run 176)**;
   `/etc/ld.so.preload` does. `derive-forgejo-ci.py` adds this step. `--no-daemon` does
   not help (Gradle forks a single-use daemon over the same socket). `examples/plektra/sipb-loopback-report.md`
   has the report and the 2026-10-13 update.
   **Three more TSI behaviours, found and worked around 2026-10-14 (runs 189-228), all in the same shim:**
   (a) **A thread blocked in `recv()`/`read()`/`accept()` on a socket blocks every other call on that socket
   from other threads: `send()`, `shutdown()`, `getpeername()`** (`getsockopt(SO_ACCEPTCONN)` returns at once
   but says 0 for a listener). Java's `ServerSocket.close()`/`Socket.close()` call `shutdown()` first, so okhttp
   MockWebServer tests hung the test worker forever (**disk speed was not the cause: as-is, tmpfs and loop
   storage all hung identically**), and a WebSocket client's writer thread stalled behind its reader thread (the
   deterministic `OpenAiLiveSpeechClientTest` 3 s timeouts). A thread parked in `poll()` does not hold the lock, so the
   shim waits in `poll()` before every blocking `read`/`recv`/`recvfrom`/`recvmsg`/`accept`/`accept4` on a TCP
   socket (fd table kept from `socket()`/`accept()`), and still wraps `listen`/`close`/`dup2`/`dup3`/`shutdown()`
   (no-op on listeners, otherwise real call in a helper thread with a 300 ms wait; `SHIM_SHUTDOWN=passthrough|noop`
   for experiments; build with `-pthread`). Probe: `duplex-probe.c` (`probe-duplex.yml`). (b) **A port number
   reused right after its listener closed lands the new listener's connections on the old one**
   (`unexpected end of stream`, `Broken pipe`): the shim's old random port seed repeated within a second, so
   consecutive MockWebServers got the same port. The shim now seeds from the nanosecond clock and skips the last 4096
   ports it handed out. (c) With `SO_REUSEADDR` on both sockets, a second `bind()`+`listen()` on a port that
   already has a listener succeeds (a normal kernel returns `EADDRINUSE`; `dup-bind-probe.py`). Java sets
   `SO_REUSEADDR` on `ServerSocket` by default, so neither the kernel nor the shim sees a collision.
   Results: full suite run 203 (before): 1,417 tests, 7 failed; run 222 (port fix): 4 failed; the Java
   okhttp/MockWebServer churn repro (`java-churn/`, `probe-javachurn.yml`) went from about 30% failures to 0 of 800 and
   from 150 s to 1 s per 800 iterations. Diagnosis tools: `heartbeat.sh` (jstack of the test worker and Gradle daemon
   every 75 s), `run-matrix.sh` (`MATRIX_MODE=diag`, `DIAG_CMD`), `push-probe.sh`, `probe-*.yml`,
   `listener-churn-repro.py`, `keepalive-repro.py` (negative: plain Python keep-alive is fine).
6. The job-log endpoint carries only the first step's `⭐ Run` marker, and there
   is no per-step API: `examples/plektra/forgejo-ci.yml` prints `BENCHSTEP`
   markers and `scripts/ci-step-times` reads them (or Gradle's `BUILD ... in`).

7. **Resources per job (probed 2026-10-13, `examples/plektra/resource-probe.sh`,
   `limits-probe.sh`, `disk-probe.py`; run on the Mac too to compare):** 16 vCPU
   (EPYC at 3.0 GHz, 1 thread/core, KVM) and 62.8 GiB RAM, no swap, no cgroup
   limits (the VM is the cap), CPU steal 0.01 %. Versus an M1 Air: 2.0x cores,
   3.9x RAM, 2.6x all-thread compute, 0.85x one-thread compute. **Disk is the weak
   spot:** `/`, `/tmp` and the workspace are all virtiofs (no guest block device, so
   SSD vs HDD is not detectable; nosync write = fsync write = 177 MiB/s, i.e. write-through
   FUSE). Small files: about 1.6-2.3k creates/s, 13-15k stats/s, 4-5k opens/s, which is
   0.14x, 0.034x, 0.075x of the Mac. **`/dev/shm` is a 32 GiB tmpfs: 29-33x faster than
   virtiofs on small-file operations** (51k creates/s, 380k stats/s, 117k open+read/s),
   so put `GRADLE_USER_HOME`, the Android SDK and the checkout there for speed.
   Other limits: soft `nofile` 1024 (hard 4096), `kernel.pid_max` 16384,
   `inotify.max_user_instances` 128, virtio balloon present, PSI off.

`examples/plektra/` holds the workflow derived from the repo's GitHub `ci.yml`
(`derive-forgejo-ci.py` keeps every Gradle step identical) and the probe
history. Compare runs with
`scripts/ci-step-times forgejo OWNER/REPO RUN` and `... github OWNER/REPO RUN`.
