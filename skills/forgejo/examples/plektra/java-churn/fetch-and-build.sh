#!/usr/bin/env bash
# fetch-and-build.sh DIR — download okhttp 4.11 + mockwebserver 4.11 and deps from Maven Central into DIR, compile Churn.java
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd); D=${1:?dir}; mkdir -p "$D"; cd "$D"; M=https://repo1.maven.org/maven2
for u in com/squareup/okhttp3/okhttp/4.11.0/okhttp-4.11.0.jar com/squareup/okhttp3/mockwebserver/4.11.0/mockwebserver-4.11.0.jar \
         com/squareup/okio/okio-jvm/3.2.0/okio-jvm-3.2.0.jar org/jetbrains/kotlin/kotlin-stdlib/1.8.21/kotlin-stdlib-1.8.21.jar \
         junit/junit/4.13.2/junit-4.13.2.jar org/hamcrest/hamcrest-core/1.3/hamcrest-core-1.3.jar; do
  [ -s "$(basename "$u")" ] || curl -fsSLO "$M/$u"
done
javac -cp "*" -d . "$HERE/Churn.java" 2>&1 | grep -v '^Note:' || true
ls *.jar | wc -l; ls Churn.class
