#!/usr/bin/env bash
# resource-probe.sh — what one machine (CI job or laptop) actually gives a build.
# Same script runs on the MIT runner (workflow probe-resources.yml) and locally, so the
# numbers compare. Needs cc and python3. Prints "KEY value" lines; read-only except a
# 1 GiB scratch file under $TMPDIR (default /tmp), removed at the end.
set -u
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
OS=$(uname -s)
echo "== identity"; echo "uname $(uname -srm)"
if [ "$OS" = Linux ]; then
  NCPU=$(nproc)
  echo "nproc $NCPU"; grep -m1 'model name' /proc/cpuinfo; grep -m1 'cpu MHz' /proc/cpuinfo
  lscpu 2>/dev/null | grep -Ei 'threads per core|cores per socket|socket|max mhz|L3|vendor|hypervisor'
  echo "== memory"; free -m | head -2; grep -E 'MemTotal|SwapTotal' /proc/meminfo
  echo "== cgroup limits (max = unlimited)"
  for f in cpu.max memory.max memory.high memory.swap.max pids.max io.max; do
    for d in /sys/fs/cgroup /sys/fs/cgroup/$(cut -d: -f3 /proc/self/cgroup); do [ -r "$d/$f" ] && echo "$f ($d) $(tr '\n' ' ' < "$d/$f")"; done
  done
  echo "== disk"; df -h / "$PWD" | sort -u; ulimit -a | grep -Ei 'open files|processes|file size'
else
  NCPU=$(sysctl -n hw.ncpu); echo "ncpu $NCPU (perf $(sysctl -n hw.perflevel0.physicalcpu), eff $(sysctl -n hw.perflevel1.physicalcpu))"
  sysctl -n machdep.cpu.brand_string; echo "mem_gib $(( $(sysctl -n hw.memsize) / 1073741824 ))"
  echo "== disk"; df -h / "$PWD" | sort -u
fi
cat > "$W/b.c" <<'C'
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec*1e-9;}
static volatile unsigned long sink;
static void *cpu(void *a){unsigned long x=88172645463325252UL,s=0;double f=1.0;for(long i=0;i<*(long*)a;i++){x^=x<<13;x^=x>>7;x^=x<<17;s+=x%1000003;f=f*1.0000001+0.5;}sink=s+(unsigned long)f;return 0;}
static void *mem(void *a){size_t n=128UL<<20;char *s=malloc(n),*d=malloc(n);memset(s,1,n);memset(d,2,n);for(int i=0;i<6;i++){memcpy(d,s,n);s[i]++;}sink=d[7];free(s);free(d);return 0;}
static double run(void *(*fn)(void*),int t,long arg,double units){pthread_t th[256];double a=now();for(int i=0;i<t;i++)pthread_create(&th[i],0,fn,&arg);for(int i=0;i<t;i++)pthread_join(th[i],0);return units*t/(now()-a);}
int main(int c,char**v){int n=atoi(v[1]);long it=200000000;
 double s1=run(cpu,1,it,it/1e6); double sn=run(cpu,n,it,it/1e6);
 printf("cpu_1thread_Miter_per_s %.1f\ncpu_%dthreads_Miter_per_s %.1f\ncpu_scaling_x %.2f\n",s1,n,sn,sn/s1);
 double m1=run(mem,1,0,6*128.0/1024*2); double mn=run(mem,n,0,6*128.0/1024*2);
 printf("mem_copy_1thread_GiB_per_s %.1f\nmem_copy_%dthreads_GiB_per_s %.1f\n",m1,n,mn);return 0;}
C
cc -O2 -pthread -o "$W/b" "$W/b.c" 2>&1 | head -3
echo "== compute and memory (own C benchmark, same source both sides)"; "$W/b" "$NCPU"
echo "== openssl (library may differ: treat as coarse)"
openssl speed -seconds 2 -evp sha256 2>/dev/null | tail -1 | awk '{sub("k","",$NF); print "sha256_1thread_16KB_kB_s", $NF}'
echo "== disk write+fsync, 1 GiB"
python3 - "$W" <<'PY'
import os, sys, time
p = os.path.join(sys.argv[1], "d"); buf = os.urandom(1 << 20)
t = time.time()
with open(p, "wb") as f:
    for _ in range(1024): f.write(buf)
    f.flush(); os.fsync(f.fileno())
w = time.time() - t
print(f"disk_write_fsync_MiB_per_s {1024 / w:.0f}")
t = time.time(); n = 0
with open(p, "rb") as f:
    while (b := f.read(1 << 20)): n += len(b)
print(f"disk_read_cached_MiB_per_s {n / 1048576 / (time.time() - t):.0f}")
PY
