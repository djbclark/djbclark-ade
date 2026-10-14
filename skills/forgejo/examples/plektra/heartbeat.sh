#!/bin/sh
# Heartbeat for hang diagnosis, installed as /usr/local/bin/hb.sh by derive-forgejo-ci.py.
# Every 15 s: load, memory, java count, top-3 processes. For each Gradle test worker: lifetime CPU ticks,
# thread count and threads in uninterruptible sleep (D); every 75 s a jstack summary of its "Test worker" thread.
i=0
while :; do
  echo "HEARTBEAT $(date +%T) load=$(cut -d' ' -f1-3 /proc/loadavg) $(free -m | awk '/Mem/{print "used="$3" avail="$7}') java=$(pgrep -c java)"
  ps -eo pid,pcpu,rss,stat,etimes,args --sort=-pcpu | sed -n 2,4p | cut -c1-150
  for p in $(pgrep -f 'Gradle Test Executor'); do
    echo "TESTWORKER pid=$p cpu_ticks=$(awk '{print $14+$15}' /proc/$p/stat) threads=$(ls /proc/$p/task | wc -l) D=$(cat /proc/$p/task/*/stat 2>/dev/null | awk '{print $3}' | grep -c D)"
    if [ $((i % 5)) = 4 ]; then
      jstack "$p" > /tmp/js.$p 2>&1
      echo "JSTACK pid=$p $(grep 'Thread.State' /tmp/js.$p | sort | uniq -c | tr -s ' ' | tr '\n' ';')"
      grep -A32 '^"Test worker"' /tmp/js.$p | cut -c1-170
    fi
  done
  i=$((i+1)); sleep 15
done
