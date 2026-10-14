#!/bin/sh
# Heartbeat for hang diagnosis, installed as /usr/local/bin/hb.sh by derive-forgejo-ci.py.
# Every 15 s: load, memory, java count, top-3 processes, test progress (result XML files written so far).
# For each Gradle test worker: lifetime CPU ticks, thread count, threads in uninterruptible sleep (D);
# every 75 s a jstack summary: thread states, most common thread names, the "Test worker" thread, and any
# thread that is shutting the JVM down.
i=0
while :; do
  echo "HEARTBEAT $(date +%T) load=$(cut -d' ' -f1-3 /proc/loadavg) $(free -m | awk '/Mem/{print "used="$3" avail="$7}') java=$(pgrep -c java) results_xml=$(ls /workspace/*/*/app/build/test-results/testStableDebugUnitTest/*.xml 2>/dev/null | wc -l) test_files=$(find /workspace/*/*/app/src/test -name '*Test.kt' 2>/dev/null | wc -l)"
  ps -eo pid,pcpu,rss,stat,etimes,args --sort=-pcpu | sed -n 2,4p | cut -c1-150
  for p in $(pgrep -f 'Gradle Test Executor'); do
    echo "TESTWORKER pid=$p cpu_ticks=$(awk '{print $14+$15}' /proc/$p/stat) threads=$(ls /proc/$p/task | wc -l) D=$(cat /proc/$p/task/*/stat 2>/dev/null | awk '{print $3}' | grep -c D)"
    if [ $((i % 5)) = 4 ]; then
      jstack "$p" > /tmp/js.$p 2>&1
      echo "JSTACK pid=$p $(grep 'Thread.State' /tmp/js.$p | sort | uniq -c | tr -s ' ' | tr '\n' ';')"
      echo "THREADNAMES $(grep '^"' /tmp/js.$p | sed -E 's/^"([^"]*)".*/\1/; s/[0-9]+/N/g' | sort | uniq -c | sort -rn | head -8 | tr -s ' ' | tr '\n' ';')"
      grep -A32 '^"Test worker"' /tmp/js.$p | cut -c1-170
      awk 'BEGIN{RS="";ORS="\n\n"} /java.lang.Shutdown|Runtime.exit|DestroyJavaVM/' /tmp/js.$p | head -50 | cut -c1-170
      echo "WORKER-OTHER-THREADS (not looper/GC/pool)"
      awk 'BEGIN{RS="";ORS="\n\n"} !/queued-work-looper|DefaultDispatcher|GC Thread|Refine|Conc#|Cleaner|pool-|Compiler|Signal|Reference|Finalizer|Service Thread|Monitor|Notification|Attach|Sweeper|VM Thread/ && /org.gradle|plektra|robolectric|java.net|SocketChannel/' /tmp/js.$p | head -70 | cut -c1-170
    fi
  done
  if [ $((i % 5)) = 4 ]; then
    dp=$(pgrep -f 'GradleDaemon' | head -1)
    if [ -n "$dp" ]; then
      jstack "$dp" > /tmp/jd.$dp 2>&1
      echo "DAEMONSTACK pid=$dp $(grep 'Thread.State' /tmp/jd.$dp | sort | uniq -c | tr -s ' ' | tr '\n' ';')"
      awk 'BEGIN{RS="";ORS="\n\n"} /SocketChannelImpl|EPoll|test|Test|worker/ && !/GC Thread|Refine|Conc#|Cleaner|Compiler|Signal|Reference|Finalizer|Service Thread|Attach|Sweeper|VM Thread/' /tmp/jd.$dp | head -90 | cut -c1-170
    fi
    echo "TCP $(awk 'NR>1{print $4}' /proc/net/tcp /proc/net/tcp6 2>/dev/null | sort | uniq -c | tr -s ' ' | tr '\n' ';') QUEUED=$(awk 'NR>1 && $5!="00000000:00000000"{n++} END{print n+0}' /proc/net/tcp /proc/net/tcp6 2>/dev/null)"
  fi
  i=$((i+1)); sleep 15
done
