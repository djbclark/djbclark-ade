"""skills/oc-go-key/scripts/go-status: classify quota walls from the OpenCode log, never from a command line.

The bug this pins: the log records the SHELL COMMANDS sessions run, so a session grepping for
"Go usage limit exceeded" (or running this very script) logs a line that contains both the phrase and
`level=ERROR`. The first live run of the script counted itself as an outage.
"""
import datetime as dt
import importlib.machinery
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "skills" / "oc-go-key" / "scripts" / "go-status"


def load():
    loader = importlib.machinery.SourceFileLoader("go_status", str(SCRIPT))
    spec = importlib.util.spec_from_loader("go_status", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def ts(minutes_ago=0):
    when = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago)
    return when.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def test_a_real_go_wall_is_found():
    gs = load()
    line = (f'timestamp={ts()} level=ERROR run=x message="Failed to drain Session" '
            'cause="AI.Error: Go usage limit exceeded\\n at QX" role=server')
    hits = gs.scan(line, hours=1)
    assert [name for _, name, _ in hits] == ["go-limit"]


def test_a_credit_wall_is_not_called_a_go_wall():
    gs = load()
    line = (f'timestamp={ts()} level=ERROR message="Failed to drain Session" cause="AI.Error: '
            'Upstream request failed: Insufficient account funds [cause]: AI.Error.QuotaExceeded: '
            'Upstream request failed: Insufficient account funds"')
    assert [name for _, name, _ in gs.scan(line, hours=1)] == ["no-funds"]


def test_the_log_of_a_session_grepping_for_the_phrase_is_not_an_outage():
    """The recorded command contains the phrase AND level=ERROR; it is not a failure record."""
    gs = load()
    line = (f'timestamp={ts()} level=INFO run=x message="spawning process" '
            'command=rg -o "timestamp= level=ERROR run=" ~/.local/share/opencode/log/opencode.log '
            '"Go usage limit exceeded"')
    assert gs.scan(line, hours=1) == []


def test_an_old_failure_falls_outside_the_window():
    gs = load()
    line = (f'timestamp={ts(minutes_ago=120)} level=ERROR message="Failed to drain Session" '
            'cause="AI.Error: Go usage limit exceeded"')
    assert gs.scan(line, hours=1) == []


def test_region_and_auth_are_their_own_classes():
    gs = load()
    region = (f'timestamp={ts()} level=ERROR message="Failed to drain Session" '
              'cause="AI.Error: 400 this model requires Global regions"')
    auth = (f'timestamp={ts()} level=ERROR message="Failed to drain Session" '
            'cause="AI.Error: 401 api_key_expired"')
    assert [n for _, n, _ in gs.scan(region, hours=1)] == ["region"]
    assert [n for _, n, _ in gs.scan(auth, hours=1)] == ["auth"]
