#!/usr/bin/env bash
# disk-experiments.sh — Linux, root, inside a CI job. Where can a build put its files so small-file
# and write-heavy work is fast? Compares: the job's virtiofs, ext4 on a loop image stored on virtiofs,
# ext4 on a loop image stored on tmpfs, and plain tmpfs. Also fio IOPS/latency, parallel scaling, and
# a realistic unpack+checkout workload. Needs: apt-get (fio jq e2fsprogs unzip), python3, curl.
set +e
here=$(cd "$(dirname "$0")" && pwd)
apt-get update -qq; apt-get install -y -qq fio jq e2fsprogs unzip util-linux > /dev/null 2>&1
echo "== mount facts"; grep virtiofs /proc/self/mountinfo | cut -c1-220; dmesg 2>/dev/null | grep -Ei 'virtiofs|fuse|dax' | head -5
echo "== loop devices usable?"; ls /dev/loop* | head -3; losetup -f 2>&1
mkdir -p /root/v /mnt/lv /mnt/lt /dev/shm/t
truncate -s 24G /root/loop-v.img && mkfs.ext4 -q -F -E lazy_itable_init=1,lazy_journal_init=1 /root/loop-v.img && mount -o loop,noatime /root/loop-v.img /mnt/lv; echo "mount loop-on-virtiofs rc=$?"
truncate -s 8G /dev/shm/loop-t.img && mkfs.ext4 -q -F -E lazy_itable_init=1,lazy_journal_init=1 /dev/shm/loop-t.img && mount -o loop,noatime /dev/shm/loop-t.img /mnt/lt; echo "mount loop-on-tmpfs rc=$?"
df -hT /root/v /mnt/lv /mnt/lt /dev/shm/t 2>&1
declare -A T=( [virtiofs]=/root/v [ext4_loop_on_virtiofs]=/mnt/lv [ext4_loop_on_tmpfs]=/mnt/lt [tmpfs]=/dev/shm/t )
ORDER="virtiofs ext4_loop_on_virtiofs ext4_loop_on_tmpfs tmpfs"
echo; echo "######## 1. small files and sequential (disk-probe.py)"
for k in $ORDER; do echo "--- $k"; python3 "$here/disk-probe.py" "${T[$k]}/dp" | tail -n +2; done
echo; echo "######## 2. fio (page cache on, buffered): rand 4k read, rand 4k write, 4k write+fsync each"
for k in $ORDER; do d=${T[$k]}/fio; mkdir -p $d; echo "--- $k"
  fio --name=rr --directory=$d --rw=randread --bs=4k --size=512M --numjobs=4 --ioengine=psync --runtime=10 --time_based --group_reporting --output-format=json 2>/dev/null | jq -r '"randread_4k_iops \(.jobs[0].read.iops|floor)  lat_mean_us \(.jobs[0].read.lat_ns.mean/1000|floor)"'
  fio --name=rw --directory=$d --rw=randwrite --bs=4k --size=512M --numjobs=4 --ioengine=psync --runtime=10 --time_based --group_reporting --output-format=json 2>/dev/null | jq -r '"randwrite_4k_iops \(.jobs[0].write.iops|floor)  lat_mean_us \(.jobs[0].write.lat_ns.mean/1000|floor)"'
  fio --name=fs --directory=$d --rw=write --bs=4k --size=64M --fsync=1 --ioengine=psync --runtime=10 --time_based --output-format=json 2>/dev/null | jq -r '"write_4k_fsync_iops \(.jobs[0].write.iops|floor)  lat_mean_us \(.jobs[0].write.lat_ns.mean/1000|floor)"'
  rm -rf $d; done
echo; echo "######## 3. parallel scaling: 16 processes each creating/stating/reading/unlinking 5000 files"
for k in $ORDER; do echo "--- $k"; for i in $(seq 1 16); do python3 "$here/disk-probe.py" --small "${T[$k]}/par$i" > /tmp/par-$k-$i.txt & done; wait
  cat /tmp/par-$k-*.txt | awk '/create_4KiB/{c+=$2} /stat_per_s/{s+=$2} /open_read/{r+=$2} /unlink/{u+=$2} END{printf "  16proc_total create/s %d stat/s %d open_read/s %d unlink/s %d\n", c,s,r,u}'; done
echo; echo "######## 4. realistic: unpack the Gradle distribution (zip), tar-extract the checkout, git status, remove"
curl -sSL -o /dev/shm/gradle.zip https://services.gradle.org/distributions/gradle-8.13-bin.zip; ls -l /dev/shm/gradle.zip | awk '{print "gradle zip bytes", $5}'
tar cf /dev/shm/repo.tar -C "${GITHUB_WORKSPACE:-$PWD}" . 2>/dev/null; ls -l /dev/shm/repo.tar | awk '{print "repo tar bytes", $5}'
tm() { local a=$(date +%s.%N); "$@" > /dev/null 2>&1; echo "$(echo "$(date +%s.%N) - $a" | bc 2>/dev/null || awk -v a=$a -v b=$(date +%s.%N) 'BEGIN{print b-a}')"; }
for k in $ORDER; do d=${T[$k]}/real; mkdir -p $d/g $d/r; echo "--- $k"
  echo "  unzip_gradle_s $(tm unzip -q /dev/shm/gradle.zip -d $d/g)"
  echo "  tar_extract_repo_s $(tm tar xf /dev/shm/repo.tar -C $d/r)"
  echo "  git_status_s $(tm git -C $d/r status --porcelain)"
  echo "  rm_rf_s $(tm rm -rf $d)"; done
echo "== done"
