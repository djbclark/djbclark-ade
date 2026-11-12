"""Native Paseo mode audit/explicit live-idle repair. No restart or message send."""
from __future__ import annotations
import argparse
import json
import re
import subprocess
from paseo_yolo import plan_unattended_config, verify_unattended_snapshot

ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')


class Refused(ValueError):
    pass


def native(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)
        data = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise Refused(f'native read/mutation failed: {type(exc).__name__}') from exc
    if result.returncode or not isinstance(data, (dict, list)) or isinstance(data, dict) and data.get('error'):
        raise Refused('native command failed; no success inferred')
    return data


def audit(agent_id, *, repair=False, yes=False, home=None, call=native):
    # Validate identity before any subprocess/path access. Full readback must match
    # exactly; native CLI prefix resolution is not accepted as identity evidence.
    if not isinstance(agent_id, str) or not ID.fullmatch(agent_id):
        raise Refused('invalid agent ID')
    base=['paseo', *(['--home', home] if home else [])]
    snapshot=call([*base,'agent','inspect',agent_id,'--json'])
    if not isinstance(snapshot,dict) or snapshot.get('Id') != agent_id:
        raise Refused('exact agent identity unavailable (prefixes are not accepted)')
    provider=snapshot.get('Provider')
    if not isinstance(provider,str) or '/' in provider:
        raise Refused('native exact provider identity unavailable')
    if snapshot.get('Mode') in {'plan','read-only','dontAsk'}:
        return {'status':'exempt','agent_id':agent_id,'reason':'preserve explicit restrictive mode'}
    rows=call([*base,'provider','ls','--json'])
    matching=[r for r in rows if isinstance(r,dict) and r.get('provider') == provider] if isinstance(rows,list) else []
    if len(matching) != 1:
        raise Refused('native provider availability missing/ambiguous')
    catalog={**matching[0], 'modes':snapshot.get('AvailableModes')}
    plan=plan_unattended_config(provider,catalog)
    if plan['status'] != 'ready':
        raise Refused(plan['reason'])
    verified=verify_unattended_snapshot(plan,snapshot,agent_id=agent_id)
    result={'status':'verified' if verified['ok'] else 'drift','agent_id':agent_id,
            'provider':provider,'mode_id':plan['mode_id'],'reason':verified['reason']}
    if verified['ok'] or not repair:
        return result
    if snapshot.get('Status') != 'idle' or snapshot.get('Archived') is not False:
        raise Refused('repair requires an already-live idle unarchived agent; no resume/restart is attempted')
    if not plan.get('mode_id') or plan.get('provider_options'):
        raise Refused('this CLI cannot repair provider controls with authoritative readback')
    result['argv']=[*base,'agent','mode',agent_id,plan['mode_id'],'--json']
    result['status']='planned'
    if not yes:
        return result
    # The mutation response is only an acknowledgement. A new authoritative
    # inspect must prove the exact identity/provider/live effective mode.
    call(result['argv'])
    observed=call([*base,'agent','inspect',agent_id,'--json'])
    proof=verify_unattended_snapshot(plan,observed,agent_id=agent_id)
    if not proof['ok']:
        raise Refused('repair not verified: '+proof['reason'])
    result.update(status='verified',reason=proof['reason'])
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['check','repair'])
    parser.add_argument('agent_id',help='full exact native agent ID (not a prefix)')
    parser.add_argument('--home',help='explicit native Paseo home/daemon selection')
    parser.add_argument('--json',action='store_true')
    consent=parser.add_mutually_exclusive_group()
    consent.add_argument('--yes',action='store_true',help='apply live-idle repair, then inspect readback')
    consent.add_argument('--dry-run',action='store_true',help='plan only (repair default); native reads only')
    args=parser.parse_args(argv)
    if args.command=='check' and args.yes:
        parser.error('--yes applies only to repair')
    try:
        result=audit(args.agent_id,repair=args.command=='repair',yes=args.yes,home=args.home)
        code=0 if result['status'] in {'verified','exempt','planned'} else 1
    except Refused as exc:
        result={'status':'unavailable','reason':str(exc)}; code=2
    print(json.dumps(result,sort_keys=True) if args.json else f"{result['status']}: {result['reason']}")
    return code
