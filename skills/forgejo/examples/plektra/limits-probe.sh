#!/usr/bin/env bash
# limits-probe.sh — Linux only. What kind of disk is under a CI job, and what can throttle it:
# cgroups, ulimits, sysctls, hypervisor CPU steal, network speed. Read-only. Run in a job.
set +e
echo "== how the root filesystem is mounted (virtiofs/overlay => no guest-visible block device)"
cat /proc/cmdline | tr ' ' '\n' | grep -E 'rootfstype|root=|init=' 
grep -E ' / | /workspace' /proc/mounts | cut -c1-200
ls /sys/fs/virtiofs 2>/dev/null && for t in /sys/fs/virtiofs/*/tag; do echo "virtiofs tag: $(cat $t)"; done
echo "== block devices the guest can see"
lsblk -d -o NAME,MODEL,ROTA,SIZE,TYPE,TRAN 2>&1 | head
for b in /sys/block/*; do n=$(basename $b); echo "$n rotational=$(cat $b/queue/rotational 2>/dev/null) sched=$(cat $b/queue/scheduler 2>/dev/null) model=$(cat $b/device/model 2>/dev/null) vendor=$(cat $b/device/vendor 2>/dev/null) rd_ahead_kb=$(cat $b/queue/read_ahead_kb 2>/dev/null)"; done
ls /sys/block | wc -l
echo "== virtio devices"; ls /sys/bus/virtio/devices 2>/dev/null | head; for d in /sys/bus/virtio/devices/*; do echo "$(basename $d) driver=$(basename $(readlink $d/driver 2>/dev/null) 2>/dev/null) device=$(cat $d/device 2>/dev/null)"; done
echo "== cgroups"
mount | grep -i cgroup; cat /proc/self/cgroup
find /sys/fs/cgroup -maxdepth 3 \( -name cpu.max -o -name memory.max -o -name io.max -o -name pids.max -o -name cpu.weight \) 2>/dev/null | head | while read f; do echo "$f: $(cat $f 2>/dev/null | tr '\n' ' ')"; done
echo "== resource limits (this shell)"; cat /proc/self/limits
echo "== kernel knobs"
for k in vm.dirty_ratio vm.dirty_background_ratio vm.overcommit_memory vm.swappiness fs.file-max fs.inotify.max_user_watches fs.inotify.max_user_instances kernel.pid_max kernel.threads-max net.ipv4.ip_local_port_range net.core.somaxconn; do echo "$k = $(sysctl -n $k 2>/dev/null)"; done
echo "== pressure stall (cumulative since boot)"; for r in cpu memory io; do echo "$r: $(cat /proc/pressure/$r 2>/dev/null | tr '\n' ' ')"; done
echo "== hypervisor CPU steal while 16 busy loops run for 6 s"
s0=$(awk '/^cpu /{print $9, $2+$3+$4+$5+$6+$7+$8+$9}' /proc/stat)
for i in $(seq 1 $(nproc)); do (timeout 6 sh -c 'while :; do :; done') & done; wait
s1=$(awk '/^cpu /{print $9, $2+$3+$4+$5+$6+$7+$8+$9}' /proc/stat)
echo "steal ticks before/after (steal total): $s0 -> $s1"
awk -v a="$s0" -v b="$s1" 'BEGIN{split(a,x," ");split(b,y," ");printf "steal_percent_of_busy_window %.2f\n", 100*(y[1]-x[1])/(y[2]-x[2])}'
echo "== network"
curl -s -o /dev/null -w "gradle_dist_download_MB_per_s %{speed_download}\n" https://services.gradle.org/distributions/gradle-8.13-bin.zip | awk '{printf "%s %.1f\n", $1, $2/1e6}'
curl -s -o /dev/null -w "repo_maven_time_to_first_byte_s %{time_starttransfer}\n" https://repo.maven.apache.org/maven2/
