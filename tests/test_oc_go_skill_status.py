"""skills/oc-go-key/scripts/go-status: classify quota walls from the OpenCode log, never from a command line.

The bug this pins: the log records the SHELL COMMANDS sessions run, so a session grepping for
"Go usage limit exceeded" (or running this very script) logs a line that contains both the phrase and
`level=ERROR`. The first live run of the script counted itself as an outage.
"""
import datetime as dt
import importlib.machinery
import importlib.util
import re
from pathlib import Path

import pytest

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


@pytest.fixture
def state(tmp_path, monkeypatch):
    gs = load()
    tool = tmp_path / "oc-go-key"
    tool.write_text("#!/bin/sh\nprintf \"  opencode 'dclark' key cred_fake\\n\"\n")
    tool.chmod(0o755)
    log = tmp_path / "opencode.log"
    log.write_text(f"timestamp={ts(minutes_ago=1441)} level=INFO message=started\n")
    monkeypatch.setattr(gs, "OC_GO_KEY", tool)
    monkeypatch.setattr(gs, "LOG", log)
    return gs


def test_printed_failures_redact_credentials_after_cause_split(state, capsys):
    state.LOG.write_text(
        f'timestamp={ts()} level=ERROR provider=opencode-go cause="AI.Error: Go usage limit exceeded '
        'oc_live_abcdef123 Bearer zzz.bbb sk-fake_123"\n'
    )
    assert state.main([]) == 2
    output = capsys.readouterr().out
    assert "go-limit" in output
    assert "oc_live_abcdef123" not in output
    assert "zzz.bbb" not in output
    assert "sk-fake_123" not in output
    assert "quota" in output


def test_covered_hours_uses_first_timestamp_and_requested_window():
    gs = load()
    text = ("no timestamp here\ntimestamp=invalid level=INFO\n"
            f"timestamp={ts(minutes_ago=186)} level=INFO\n"
            f"timestamp={ts()} level=INFO\n")
    assert gs.covered_hours(text, 24) == pytest.approx(3.1, abs=0.01)
    assert gs.covered_hours(text, 1) is None
    assert gs.covered_hours("no records\n", 24) is None


def test_short_log_span_hedges_header_and_none(state, capsys):
    state.LOG.write_text(f"timestamp={ts(minutes_ago=186)} level=INFO\n")
    assert state.main(["--hours", "24"]) == 0
    output = capsys.readouterr().out
    assert "== failures in the last 24 h (log tail covers 3.1 h) ==" in output
    assert "  none in the covered span (log tail from opencode.log)" in output


def test_full_log_window_keeps_original_header(state, capsys):
    assert state.main(["--hours", "24"]) == 0
    output = capsys.readouterr().out
    assert "== failures in the last 24 h ==" in output
    assert "  none (log tail from opencode.log)" in output
    assert "log tail covers" not in output


def test_tail_coverage_skips_partial_first_line(state):
    complete = f"timestamp={ts(minutes_ago=186)} level=INFO message=complete\n"
    state.LOG.write_text(f"prefix timestamp={ts(minutes_ago=1441)} level=INFO\n" + complete)
    text = state.recent_log_bytes(n=state.LOG.stat().st_size - 3)
    assert text == complete
    assert state.covered_hours(text, 24) == pytest.approx(3.1, abs=0.01)


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


@pytest.mark.parametrize(
    "detail", ["tokens=401", "retries: 401", "HTTP 4010", "status=4010", "http.span=401"]
)
def test_unrelated_401_is_not_auth(detail):
    gs = load()
    assert gs.scan(f"timestamp={ts()} level=ERROR provider=opencode-go cause=AI.Error: {detail}", 1) == []


# Every shape an HTTP client prints a 401 in. `http.span=` is deliberately absent: it is a request
# counter in opencode's log, so matching it would flag a working key (see test above).
@pytest.mark.parametrize("detail", [
    "http.status=401", "HTTP 401", "http 401", "HTTP/1.1 401", "HTTP/2 401",
    "status=401", "status= 401", "status:401", "status: 401",
    '"status":401', '"status": 401',
    'statusCode: 401', 'statusCode=401', "status_code=401", '"statusCode":401',
    "401 Unauthorized",
    "api_key_expired", "invalid api key", "invalid api_key", "invalid api-key",
])
def test_http_401_and_existing_literals_are_auth(detail):
    gs = load()
    hits = gs.scan(f"timestamp={ts()} level=ERROR provider=opencode-go cause=AI.Error: {detail}", 1)
    assert [name for _, name, _ in hits] == ["auth"]


def test_changelog_names_ui_go_429_and_its_observation_date():
    text = (SCRIPT.parents[3] / "CHANGELOG.md").read_text()
    entry = next(line for line in text.splitlines() if line.startswith("- `skills/oc-go-key`"))
    assert "`go-limit` / `no-funds` / `go-429` / `region` / `auth`" in entry
    assert "`go-429` is the UI-side error name" in entry
    assert "no live occurrences observed on 2026-10-30" in entry
    assert "- Fixed `go-status`" in text
    # The lead fills the PR number in after opening the PR: accept the placeholder or the number,
    # so this test does not have to be edited by hand at the one moment nobody is testing.
    assert re.search(r"exit codes \(#(?:\d+|TBD)\)\.", text)


def test_both_quota_phrases_use_first_match_go_limit():
    gs = load()
    line = (f"timestamp={ts()} level=ERROR provider=opencode-go cause=AI.Error: "
            "Insufficient account funds; Go usage limit exceeded")
    assert [name for _, name, _ in gs.scan(line, 1)] == ["go-limit"]


def test_unknown_quoted_labels_are_named_after_table(state, monkeypatch, capsys):
    listing = ("service pid 21228 http://127.0.0.1:49374\n"
               "  opencode 'dclark' key cred_fake\n"
               "* opencode 'new label' login cred_other\n"
               "  opencode-go 'renamed-label' key cred_another\n"
               "  opencode 'new label' login cred_duplicate")
    monkeypatch.setattr(state, "run", lambda *args, **kwargs: (0, listing))
    assert state.main([]) == 0
    output = capsys.readouterr().out
    assert listing in output
    assert output.splitlines()[-1] == "  not in this table: new label, renamed-label"
    assert "OPENCODE_GO_API_KEY_DCLARKUS (listed above)" in output
    assert "Console login (OAuth) (no credential on this Mac)" in output


def test_known_labels_add_no_extra_account_line(state, monkeypatch, capsys):
    listing = ("  opencode 'dclark' key cred_fake\n"
               "  opencode 'djbclark' login cred_other\n"
               "* opencode 't-e' login cred_another")
    monkeypatch.setattr(state, "run", lambda *args, **kwargs: (0, listing))
    assert state.main([]) == 0
    output = capsys.readouterr().out
    assert "not in this table:" not in output
    assert output.count("(listed above)") == 3
    assert "(no credential on this Mac)" not in output


def test_main_missing_oc_go_key_returns_4(state, capsys):
    state.OC_GO_KEY.unlink()
    assert state.main([]) == 4
    assert "no oc-go-key at" in capsys.readouterr().err


def test_main_failed_listing_returns_4(state, capsys):
    state.OC_GO_KEY.write_text("#!/bin/sh\nprintf 'listing unavailable\\n' >&2\nexit 7\n")
    assert state.main([]) == 4
    assert "oc-go-key list failed (rc 7)" in capsys.readouterr().err


def test_main_unreadable_log_returns_4(state, capsys):
    state.LOG.unlink()
    state.LOG.mkdir()  # A directory raises OSError even when tests run as root.
    assert state.main([]) == 4
    assert "cannot read" in capsys.readouterr().err


def test_main_fresh_failure_returns_2_with_broken_now(state, capsys):
    state.LOG.write_text(state.LOG.read_text() +
                        f"timestamp={ts()} level=ERROR provider=opencode-go cause=AI.Error: Go usage limit exceeded\n")
    assert state.main([]) == 2
    output = capsys.readouterr().out
    assert "BROKEN NOW: go-limit in the last 0.5 h." in output
    assert "Rotate:  oc-go-key use <label>" in output


def test_main_clean_log_returns_0(state, capsys):
    assert state.main([]) == 0
    output = capsys.readouterr().out
    assert "  none (log tail from opencode.log)" in output
    assert "BROKEN NOW" not in output


def test_main_older_hit_is_reported_without_broken_now(state, capsys):
    state.LOG.write_text(state.LOG.read_text() +
                        f"timestamp={ts(minutes_ago=60)} level=ERROR "
                        "cause=AI.Error: Insufficient account funds\n")
    assert state.main([]) == 0
    output = capsys.readouterr().out
    assert "counts: no-funds=1" in output
    assert "BROKEN NOW" not in output


def test_error_record_command_text_is_not_classified():
    gs = load()
    line = (f"timestamp={ts()} level=ERROR message=AI.Error.Internal "
            'command=rg "Go usage limit exceeded" opencode.log')
    assert gs.scan(line, 1) == []


def test_regions_gotcha_names_the_account_label():
    text = (SCRIPT.parents[1] / "SKILL.md").read_text()
    line = next(line for line in text.splitlines() if "needs Regions = Global" in line)
    assert "**`dclark` needs Regions = Global**" in line
    assert "dclark@dclark.us" not in line


def test_sanitized_listing_is_printed_intact(state, monkeypatch, capsys):
    listing = "  opencode 'sk-testlabel' key cred_fake"
    monkeypatch.setattr(state, "run", lambda *args, **kwargs: (0, listing))
    assert state.main([]) == 0
    assert listing in capsys.readouterr().out


def test_first_unstarred_unknown_label_survives_listing_strip(state, capsys):
    state.OC_GO_KEY.write_text("#!/bin/sh\nprintf \"  opencode 'fourth' key cred_fake\\n\"\n")
    assert state.main([]) == 0
    assert "  not in this table: fourth" in capsys.readouterr().out


@pytest.mark.parametrize("detail", [
    "access_token=EXAMPLE_PRIVATE_TOKEN", "Authorization: bearer EXAMPLE_PRIVATE_TOKEN",
    '"API_KEY": "EXAMPLE_PRIVATE_TOKEN"', "password=EXAMPLE_PRIVATE_TOKEN",
])
def test_upstream_credentials_never_reach_output(state, capsys, detail):
    state.LOG.write_text(f'timestamp={ts()} level=ERROR provider=opencode-go cause="AI.Error: invalid api key {detail}"')
    assert state.main([]) == 2
    captured = capsys.readouterr()
    assert "EXAMPLE_PRIVATE_TOKEN" not in captured.out + captured.err
    assert "authentication failed" in captured.out


def test_failed_listing_stderr_never_reaches_output(state, capsys):
    state.OC_GO_KEY.write_text("#!/bin/sh\nprintf 'Authorization: bearer EXAMPLE_PRIVATE_TOKEN\\n' >&2\nexit 7\n")
    assert state.main([]) == 4
    captured = capsys.readouterr()
    assert "EXAMPLE_PRIVATE_TOKEN" not in captured.out + captured.err


@pytest.mark.parametrize("context", ["provider=anthropic", 'model=anthropic/claude',
                                        'provider=anthropic model=opencode-go/test'])
def test_foreign_auth_withholds_go_recovery(state, capsys, context):
    state.LOG.write_text(f'timestamp={ts()} level=ERROR {context} cause="AI.Error: invalid api key"')
    assert state.main([]) == 0
    output = capsys.readouterr().out
    assert "auth" in output
    assert "BROKEN NOW" not in output and "RECENT AUTH FAILURE" not in output
    assert "Rotate:" not in output and "re-store" not in output


def test_unattributed_auth_is_flagged_without_go_recovery(state, capsys):
    # OpenCode's real error records carry no provider field (2026-10-30): a recent generic auth failure is surfaced
    # with its own exit code, but never as a Go credential problem.
    state.LOG.write_text(f'timestamp={ts()} level=ERROR run=r1 message=x cause="AI.Error: invalid api key"')
    assert state.main([]) == 3
    output = capsys.readouterr().out
    assert "RECENT AUTH FAILURE (provider not recorded)" in output
    assert "BROKEN NOW" not in output and "Rotate:" not in output and "re-store" not in output


@pytest.mark.parametrize("cause,kind", [("Go usage limit exceeded", "go-limit"), ("GoUsageLimitError", "go-429"),
                                        ("Insufficient account funds", "no-funds"),
                                        ("requires Global regions", "region")])
def test_go_console_errors_attribute_themselves_without_a_provider_field(state, capsys, cause, kind):
    # The record shape OpenCode actually writes (no provider/model field): the Go wall must still read as broken.
    state.LOG.write_text(f'timestamp={ts()} level=ERROR run=r1 message=x cause="AI.Error: {cause}"')
    assert state.main([]) == 2
    assert f"BROKEN NOW: {kind}" in capsys.readouterr().out


@pytest.mark.parametrize("context", ["model=anthropic/claude", "provider=anthropic",
                                        "provider=anthropic model=opencode-go/test"])
@pytest.mark.parametrize("cause,kind", [("Go usage limit exceeded", "go-limit"), ("GoUsageLimitError", "go-429"),
                                        ("Insufficient account funds", "no-funds"),
                                        ("requires Global regions", "region")])
def test_go_wall_in_a_record_naming_a_foreign_field_still_reads_as_broken(state, capsys, context, cause, kind):
    # A fallback record can carry another provider's model before cause=; the Go/Console text attributes itself,
    # so the wall must not be printed (foreign) with exit 0, a silent quota outage.
    state.LOG.write_text(f'timestamp={ts()} level=ERROR {context} cause="AI.Error: {cause}"')
    assert state.main([]) == 2
    assert f"BROKEN NOW: {kind}" in capsys.readouterr().out


def test_mixed_provider_only_open_code_failure_drives_advice(state, capsys):
    state.LOG.write_text(
        f'timestamp={ts()} level=ERROR provider=anthropic cause="AI.Error: invalid api key"\n'
        f'timestamp={ts()} level=ERROR model=opencode/test cause="AI.Error: Insufficient account funds"\n')
    assert state.main([]) == 2
    output = capsys.readouterr().out
    assert "BROKEN NOW: no-funds" in output
    assert "re-store" not in output


def test_naive_timestamp_skipped_before_valid_failure(state, capsys):
    state.LOG.write_text(
        'timestamp=2026-10-30T20:00:00 level=ERROR provider=opencode-go cause="AI.Error: invalid api key"\n'
        f'timestamp={ts()} level=ERROR provider=opencode-go cause="AI.Error: Go usage limit exceeded"\n')
    assert state.main([]) == 2
    assert "BROKEN NOW: go-limit" in capsys.readouterr().out
