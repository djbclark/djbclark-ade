#!/usr/bin/env python3
"""Derive the forgejo.mit.edu workflow from the repo's GitHub ci.yml, keeping every Gradle step identical."""
import os
import re
import subprocess
import sys

STEP_MIN = int(os.environ.get("DERIVE_STEP_MIN", "25"))   # per-step timeout (minutes)
VARIANT = os.environ.get("DERIVE_STORAGE", "asis")   # asis | tmpfs | loop
assert VARIANT in ("asis", "tmpfs", "loop")
src = subprocess.run(
    ["git", "-C", sys.argv[1], "show", f"{sys.argv[2]}:.github/workflows/ci.yml"],
    check=True, capture_output=True, text=True).stdout

# 1. header: also run on pushes to bench/** so a benchmark can be started with a push.
src = src.replace("name: Android CI\n", "name: Android CI (forgejo.mit.edu)\n", 1)
src = src.replace("on:\n  pull_request:\n",
                  "on:\n  pull_request:\n  push:\n    branches: ['bench/**']\n", 1)
# 2. MIT runner label (SIPB's Forgejo runner offers `ubuntu`, not `ubuntu-latest`).
src = src.replace("runs-on: ubuntu-latest", "runs-on: ubuntu", 1)
if os.environ.get("DERIVE_IMAGE"):
    src = src.replace("runs-on: ubuntu\n", "runs-on: ubuntu\n    container:\n      image: " + os.environ["DERIVE_IMAGE"] + "\n", 1)
# 3. no default actions host there: use the full URL.
src = src.replace("uses: actions/checkout@v4", "uses: https://github.com/actions/checkout@v4", 1)

# 4. replace the setup-java step with an explicit, separately timed toolchain step.
setup = '''      - name: Install JDK 17 and Android SDK (timed separately from Gradle)
        run: |
          set -euo pipefail
          nproc; free -g | head -2
          apt-get update -qq
          apt-get install -y -qq openjdk-17-jdk-headless unzip gcc libc6-dev
          export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
          echo "JAVA_HOME=$JAVA_HOME" >> "$GITHUB_ENV"
          java -version
          export ANDROID_HOME="$HOME/android-sdk"
          mkdir -p "$ANDROID_HOME/cmdline-tools"
          curl -fsSL -o /tmp/cmdline-tools.zip https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
          unzip -q /tmp/cmdline-tools.zip -d "$ANDROID_HOME/cmdline-tools"
          mv "$ANDROID_HOME/cmdline-tools/cmdline-tools" "$ANDROID_HOME/cmdline-tools/latest"
          yes | "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" --licenses > /dev/null || true
          "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" "platform-tools" "platforms;android-36" "build-tools;36.0.0" > /dev/null
          echo "ANDROID_HOME=$ANDROID_HOME" >> "$GITHUB_ENV"
          echo "ANDROID_SDK_ROOT=$ANDROID_HOME" >> "$GITHUB_ENV"
'''
# 4b. the SIPB runner is a libkrun microVM whose TSI networking refuses loopback connects to
# port-0 listeners (libkrun#818), which breaks Gradle's daemon and test workers. Build an
# LD_PRELOAD shim that rewrites port-0 binds to fixed ports and preload it system-wide (/etc/ld.so.preload).
shim_c = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "loopback-port-shim.c")).read()
hb_sh = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "heartbeat.sh")).read()
shim_step = ("      - name: Build loopback port-0 shim (libkrun#818 workaround)\n        run: |\n"
             "          cat > /tmp/portshim.c <<'SHIM_C'\n"
             + "".join(("          " + l if l.strip() else "") + "\n" for l in shim_c.splitlines())
             + "          SHIM_C\n"
             "          cat > /usr/local/bin/hb.sh <<'HB_SH'\n"
             + "".join(("          " + l if l.strip() else "") + "\n" for l in hb_sh.splitlines())
             + "          HB_SH\n"
             "          chmod +x /usr/local/bin/hb.sh\n"
             "          gcc -shared -fPIC -O2 -pthread -o /usr/local/lib/portshim.so /tmp/portshim.c -ldl\n"
             # /etc/ld.so.preload (jobs run as root) reaches every process; an LD_PRELOAD exported
             # through $GITHUB_ENV did NOT reach Gradle's daemon (run 176: it still bound port 39217).
             "          echo /usr/local/lib/portshim.so >> /etc/ld.so.preload\n"
             "          true && python3 -c 'print(\"preload ok\")'\n")
setup = setup + "\n" + shim_step
# 4d. our own image (DERIVE_IMAGE=ghcr.io/djbclark/ci-image-plektra@sha256:...) already has JDK 17, the Android SDK,
# node and /usr/local/lib/portshim.so: no install, no compile, only the system-wide preload (jobs run as root).
IMAGE = os.environ.get("DERIVE_IMAGE")
if IMAGE:
    assert VARIANT == "asis", "DERIVE_IMAGE combines only with the default storage"
    setup = ('''      - name: Toolchain and loopback shim from the image (no install, no compile)
        run: |
          set -euo pipefail
          nproc; free -g | head -2
          java -version
          echo "ANDROID_HOME=$ANDROID_HOME"; ls "$ANDROID_HOME/platforms"
          echo /usr/local/lib/portshim.so >> /etc/ld.so.preload
          true && python3 -c 'print("preload ok")'
''')
# 4c. optional storage step BEFORE the toolchain install: the job's disk is virtiofs (small-file ops
# 0.03-0.2x of a Mac, probed 2026-10-13); move the checkout, Gradle home and Android SDK onto a guest tmpfs
# (mounted at /mnt/fast, 48 GiB; /dev/shm is only 32 GiB and noexec) or onto an ext4 image on a loop device. The workspace is bind-mounted over its
# own path so later steps keep their working directory.
if VARIANT != "asis":
    # /dev/shm is mounted noexec (aapt2 and SDK tools would not run), so mount a fresh guest tmpfs
    # (root in the job; crun-krun --tmpfs would be host-side, so do it in the guest). 48 GiB cap of 62.8 GiB.
    prep = ("          F=/mnt/fast; mkdir -p $F; mount -t tmpfs -o size=48g,mode=755 tmpfs $F\n" if VARIANT == "tmpfs" else
            "          apt-get update -qq && apt-get install -y -qq e2fsprogs\n"
            "          truncate -s 40G /root/fast.img\n          mkfs.ext4 -q -F -E lazy_itable_init=1,lazy_journal_init=1 /root/fast.img\n"
            "          F=/mnt/fast; mkdir -p $F; mount -o loop,noatime /root/fast.img $F\n")
    storage = (f"      - name: Storage variant {VARIANT} (workspace, Gradle home, Android SDK)\n        run: |\n"
               "          set -euo pipefail\n" + prep +
               "          mkdir -p $F/ws $F/gradle $F/sdk\n"
               '          cp -a "$GITHUB_WORKSPACE/." $F/ws/\n'
               '          mount --bind $F/ws "$GITHUB_WORKSPACE"\n'
               '          ln -sfn $F/gradle "$HOME/.gradle"; ln -sfn $F/sdk "$HOME/android-sdk"\n'
               "          df -hT \"$GITHUB_WORKSPACE\" \"$HOME/.gradle/\" \"$HOME/android-sdk/\"\n")
    setup = storage + "\n" + setup
src, n = re.subn(r"      - name: Set up JDK 17\n(?:        .*\n|          .*\n)+?(?=\n      - name: Make Gradle executable)", lambda m: setup, src, count=1)  # lambda: setup holds backslashes (shell \n, awk)
assert n == 1, "setup-java step not found"

# 5. an explicit compile-only step before the first test step: isolates compile time.
compile_step = '''      - name: Compile stable debug (compile time only)
        run: |
          ./gradlew :app:compileStableDebugKotlin :app:compileStableDebugJavaWithJavac

'''
src = src.replace("      - name: Run core modifier regression tests\n",
                  compile_step + "      - name: Run core modifier regression tests\n", 1)

# 6. drop the artifact upload (upload-artifact@v4 is not supported by Forgejo Actions).
src, n = re.subn(r"\n      - name: Upload test and lint reports\n(?:        .*\n|          .*\n)+", "\n", src, count=1)
assert n == 1, "upload step not found"
# 7. step-timing markers: the Forgejo job-log endpoint carries no per-step markers, so each
# `run:` step prints BENCHSTEP start/end lines with epoch seconds (read by ci-step-times).
def mark(m: "re.Match[str]") -> str:
    name = m.group(1)
    return (f"      - name: {name}\n        timeout-minutes: {STEP_MIN}\n        run: |\n"
            f"          trap 'rc=$?; [ -n \"$HB\" ] && kill $HB 2>/dev/null; echo \"BENCHSTEP end {name} $(date +%s.%N) rc=$rc\"' EXIT\n"
            "          HB=; [ -x /usr/local/bin/hb.sh ] && { /usr/local/bin/hb.sh & HB=$!; } || true\n"
            f"          echo \"BENCHSTEP start {name} $(date +%s.%N)\"\n")


src = re.sub(r"      - name: (.+)\n        run: \|\n", mark, src)
# 7b. optional: replace the full-suite command, to isolate a hang (DERIVE_FULL_CMD="./gradlew ... --info").
FULL = os.environ.get("DERIVE_FULL_CMD")
if FULL:
    full_re = re.compile(r"(      - name: Run stable debug unit tests\n(?:        .*\n|          .*\n)*?)          \./gradlew :app:testStableDebugUnitTest\n")
    full_line = "          " + FULL + "\n"
    src, n = full_re.subn(lambda m: m.group(1) + full_line, src, count=1)
    assert n == 1, "full test step not found"
# 8. final step: how much space and RAM the build actually used (sizes the tmpfs or SSD ask to SIPB).
usage = '''
      - name: Storage and memory used by this build
        if: always()
        run: |
          echo "BENCHUSAGE workspace $(du -shL "$GITHUB_WORKSPACE" 2>/dev/null | cut -f1) gradle_home $(du -shL "$HOME/.gradle" 2>/dev/null | cut -f1) android_sdk $(du -shL "$HOME/android-sdk" 2>/dev/null | cut -f1)"
          df -hT / /mnt/fast /dev/shm 2>/dev/null; free -m | head -2
'''
src = src.rstrip("\n") + "\n" + usage
sys.stdout.write(src.rstrip("\n") + "\n")
