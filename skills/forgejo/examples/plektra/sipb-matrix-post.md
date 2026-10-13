# Matrix post to the SIPB Forgejo/Hyades admin (draft, not sent)

Hi! I'm djbclark, using forgejo.mit.edu CI. I think I found a networking bug in the `ubuntu` runner (sipbphus, runner v13.1.0, image ci-images:ubuntu).

**Problem:** inside a job, TCP to localhost doesn't work. A process listening on 127.0.0.1 can't be reached by a connect from the same container (ECONNREFUSED). Repro, stdlib Python:

s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(5)
socket.create_connection(("127.0.0.1", s.getsockname()[1]))  # Connection refused

Same for ::1, and for a 0.0.0.0 listener reached via the container IP 10.89.0.2. Only a listener bound on dummy0's 203.0.113.1 connects. Java agrees; `ip link set lo up` changes nothing. This breaks anything that talks to itself over localhost: Gradle ("Could not connect to the Gradle daemon"), its test workers, Kotlin daemon, dev servers, integration tests.

**Likely cause:** per SIPB/hyades the jobs run in libkrun microVMs, and my job's kernel (6.12.91) is libkrunfw's. With no virtio-net NIC libkrun uses TSI, which proxies guest sockets through the host VMM. https://github.com/libkrun/libkrun/issues/818: bind(port 0)+listen() makes the VMM bind a *different* ephemeral port, so the listener is unreachable even to its creator. Fixed ports work. Still open, no fix yet.

**Fix (host, as root), from that issue:** boot the CI microVMs with a real NIC via passt, which disables TSI. With crun-krun that is `--annotation krun.use_passt=1`; the reporter says the symptom then disappears. Loopback is the guest kernel's own again.

Full write-up with the address-by-address table: https://github.com/djbclark/djbclark-ade/blob/master/skills/forgejo/examples/plektra/sipb-loopback-report.md
Happy to test a fix. Thanks!
