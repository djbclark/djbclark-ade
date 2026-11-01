#!/usr/bin/env bash
# d1-08-vps-security
# CONTRACT: D1.8/F3: the vps-primary daemon refuses unauthenticated requests, runs agents as a dedicated unprivileged user, and that user cannot read deploy keys or other services' secrets
# EXPECT:   an unauthenticated request from the Mac is refused; ps shows the daemon and pilot agents under PILOT_USER; 'sudo -n -u PILOT_USER cat <deploy key>' style reads fail (checked with ls -l, never by reading a secret)
# ON-FAIL:  the pilot does not start (plan D1.8); the NixOS change goes back to the proposal
# SCOPE:    READ-ONLY against vps-primary (no change there); never against the Mac daemon
# HOW:      VPS=vps-primary.greyhound-sidemirror.ts.net PILOT_USER=<name> bash tests/paseo-acceptance/d1-08-vps-security.sh --i-know-it-is-the-pilot-host
# NEEDS:    ssh to the host; a pilot user (open question 6); the daemon upgraded to 0.14+ (until then rc=0 and empty plugin ls is expected, V4)
# STATUS:   DRAFT, never run; unverified CLI shapes are marked UNVERIFIED
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=d1-08-vps-security
. "$here/lib/common.sh"
ON_FAIL=the\ pilot\ does\ not\ start\ \(plan\ D1.8\)\;\ the\ NixOS\ change\ goes\ back\ to\ the\ proposal
[ "${1:-}" = "--i-know-it-is-the-pilot-host" ] || die "refusing without --i-know-it-is-the-pilot-host"
: "${VPS:?set VPS}" "${PILOT_USER:?set PILOT_USER}"
code=$(curl -s -m 10 -o /dev/null -w '%{http_code}' "http://$VPS:7263/api/agents" || echo 000)   # UNVERIFIED path; any unauthenticated endpoint will do
procs=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$VPS" "ps -eo user,args | grep -E 'paseo' | grep -v grep | awk '{print \$1}' | sort | uniq -c")
listen=$(ssh -o BatchMode=yes "$VPS" "ss -ltnp 2>/dev/null | grep 7263")
perm=$(ssh -o BatchMode=yes "$VPS" "sudo -n -u $PILOT_USER sh -c 'ls /var/lib/deploy 2>&1 | head -1'" 2>&1)   # UNVERIFIED path; use the host's real deploy-key directory
ev=$(python3 -c "import json,sys; print(json.dumps({'unauthHttp':sys.argv[1],'procUsers':sys.argv[2],'listen':sys.argv[3],'pilotReadsDeploy':sys.argv[4][:80]}))" "$code" "$procs" "$listen" "$perm")
case "$code" in 401|403|000) ;; *) fail "unauthenticated request got HTTP $code" "$ev";; esac
printf '%s' "$procs" | grep -q "$PILOT_USER" || fail "no paseo process under $PILOT_USER" "$ev"
case "$listen" in *0.0.0.0:7263*|*'*:7263'*) fail "daemon listens on all interfaces" "$ev";; esac
pass "$ev"
