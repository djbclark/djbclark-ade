#!/usr/bin/env python3
"""Derive the forgejo.mit.edu workflow from the repo's GitHub ci.yml, keeping every Gradle step identical."""
import os
import re
import subprocess
import sys

src = subprocess.run(
    ["git", "-C", sys.argv[1], "show", f"{sys.argv[2]}:.github/workflows/ci.yml"],
    check=True, capture_output=True, text=True).stdout

# 1. header: also run on pushes to bench/** so a benchmark can be started with a push.
src = src.replace("name: Android CI\n", "name: Android CI (forgejo.mit.edu)\n", 1)
src = src.replace("on:\n  pull_request:\n",
                  "on:\n  pull_request:\n  push:\n    branches: ['bench/**']\n", 1)
# 2. MIT runner label (SIPB's Forgejo runner offers `ubuntu`, not `ubuntu-latest`).
src = src.replace("runs-on: ubuntu-latest", "runs-on: ubuntu", 1)
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
# LD_PRELOAD shim that rewrites port-0 binds to fixed ports and export it to every later step.
shim_c = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "loopback-port-shim.c")).read()
shim_step = ("      - name: Build loopback port-0 shim (libkrun#818 workaround)\n        run: |\n"
             "          cat > /tmp/portshim.c <<'SHIM_C'\n"
             + "".join(("          " + l if l.strip() else "") + "\n" for l in shim_c.splitlines())
             + "          SHIM_C\n"
             "          gcc -shared -fPIC -O2 -o /tmp/portshim.so /tmp/portshim.c -ldl\n"
             '          echo "LD_PRELOAD=/tmp/portshim.so" >> "$GITHUB_ENV"\n')
setup = setup + "\n" + shim_step
src, n = re.subn(r"      - name: Set up JDK 17\n(?:        .*\n|          .*\n)+?(?=\n      - name: Make Gradle executable)", setup, src, count=1)
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
    return (f"      - name: {name}\n        run: |\n"
            f"          trap 'echo \"BENCHSTEP end {name} $(date +%s.%N) rc=$?\"' EXIT\n"
            f"          echo \"BENCHSTEP start {name} $(date +%s.%N)\"\n")


src = re.sub(r"      - name: (.+)\n        run: \|\n", mark, src)
sys.stdout.write(src.rstrip("\n") + "\n")
