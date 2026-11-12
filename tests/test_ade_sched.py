"""Tests for bin/ade_sched.py and bin/ade-sched (issue #279, 2026-11-04): one plist, three schedulers.

Every scheduler binary here is a fake shell script that logs its argv (the pattern of acp-dispatch's old reap tests); the agent
and unit dirs are per-test temp dirs. conftest.py pins the real ones to /usr/bin/true and a throwaway dir as a safety net.
"""
from __future__ import annotations

import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bin"))
import ade_sched as S

CLI = REPO / "bin" / "ade-sched"
PLISTS = sorted([*(REPO / "launchd").glob("*.plist"), *(REPO / "config/launchd").glob("*.plist")])
SUBST = {"@TARGET@": "claude", "@STATE@": "/st/cpu", "__STATE__": "/st/state", "__REPO__": "/r/ade",
         "__INDEX_DIR__": "/i/index", "__LEAD__": "11111111-1111-4111-8111-111111111111"}
NASTY = "a&b <c> 'd' %x $y \"z\""
# (plist stem, backend) pairs that must refuse with 69 rather than render
REFUSE = {("dev.herdr.server", "cron"),                     # KeepAlive: cron cannot supervise
          ("com.djbclark.load-watch", "cron")}              # StartInterval 20 s: below cron's minute


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


@pytest.fixture
def fake(tmp_path):
    """Fake launchctl/systemctl/loginctl/crontab; env knobs: FAKE_LINGER, FAKE_SD_STATE, FAKE_SD_VERSION, FAKE_CRONTAB_FAIL,
    FAKE_BOOTSTRAP_FAIL. Every call is logged as `name args...` in calls.log."""
    b = tmp_path / "fakebin"
    b.mkdir()
    log = tmp_path / "calls.log"
    ct = tmp_path / "crontab.txt"
    loaded = tmp_path / "launchd-loaded"
    loaded.mkdir()
    _script(b / "launchctl", f'echo "launchctl $*" >> "{log}"\n'
            f'LOADED="{loaded}"\n'
            'if [ "$1" = bootstrap ]; then\n'
            '  if [ -n "$FAKE_BOOTSTRAP_FAIL" ]; then echo "Bootstrap failed: 5: Input/output error" >&2; exit 5; fi\n'
            '  base=$(basename "$3" .plist); touch "$LOADED/$base"; exit 0\n'
            'fi\n'
            'if [ "$1" = bootout ]; then lab="${2##*/}"; rm -f "$LOADED/$lab"; exit 0; fi\n'
            'if [ "$1" = print ]; then\n'
            '  if [ -n "$FAKE_PRINT_RC" ]; then exit "$FAKE_PRINT_RC"; fi\n'
            '  lab="${2##*/}"; if [ -f "$LOADED/$lab" ]; then exit 0; fi; exit 1\n'
            'fi\n'
            'exit 0\n')
    _script(b / "systemctl", f'echo "systemctl $*" >> "{log}"\n'
            'case "$*" in\n'
            '  --version) echo "systemd ${FAKE_SD_VERSION:-255} (255.4)"; echo "+PAM";;\n'
            '  *is-system-running*) echo "${FAKE_SD_STATE:-running}"; [ "${FAKE_SD_STATE:-running}" = running ] || exit 1;;\n'
            '  *is-active*) echo active;;\n'
            '  *NextElapseUSecRealtime*) echo "Thu 2026-11-05 03:50:00 UTC";;\n'
            'esac\nexit 0\n')
    _script(b / "loginctl", f'echo "loginctl $*" >> "{log}"\necho "${{FAKE_LINGER:-yes}}"\n')
    _script(b / "crontab", f'echo "crontab $*" >> "{log}"\n'
            'if [ -n "$FAKE_CRONTAB_FAIL" ]; then echo "crontab: cannot open: Permission denied" >&2; exit 1; fi\n'
            f'if [ "$1" = -l ]; then if [ -f "{ct}" ]; then cat "{ct}"; exit 0; fi; '
            'echo "no crontab for tester" >&2; exit 1; fi\n'
            f'if [ "$1" = - ]; then cat > "{ct}"; exit 0; fi\nexit 2\n')
    env = {**os.environ, "HOME": str(tmp_path / "home"), "USER": "tester",
           "ADE_SCHED_LAUNCHCTL": str(b / "launchctl"), "ADE_SCHED_SYSTEMCTL": str(b / "systemctl"),
           "ADE_SCHED_LOGINCTL": str(b / "loginctl"), "ADE_SCHED_CRONTAB": str(b / "crontab"),
           "ADE_SCHED_LAUNCH_AGENTS": str(tmp_path / "agents"), "ADE_SCHED_UNIT_DIR": str(tmp_path / "units"),
           "ADE_SCHED_LOCK": str(tmp_path / "lock" / "ade-sched.lock")}
    env.pop("ADE_SCHED_BACKEND", None)

    class F:
        pass
    f = F()
    f.env, f.log, f.crontab, f.tmp = env, log, ct, tmp_path
    f.units, f.agents = tmp_path / "units", tmp_path / "agents"
    f.calls = lambda: log.read_text().splitlines() if log.exists() else []
    return f


def job(**kw) -> S.Job:
    d = {"Label": "t.job", "ProgramArguments": ["/bin/true"], "StartInterval": 300}
    d.update(kw)
    return S.Job.from_dict({k: v for k, v in d.items() if v is not None}, ade="/")


def _no_placeholder(text: str) -> None:
    assert not S.PLACEHOLDER_RE.search(text), text


# -- every checked-in plist ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("backend", S.BACKENDS)
@pytest.mark.parametrize("plist", PLISTS, ids=lambda p: p.stem)
def test_every_checked_in_plist_renders(plist, backend, fake, tmp_path):
    j = S.Job.from_plist(plist, SUBST, ade=tmp_path)
    if (plist.stem, backend) in REFUSE:
        with pytest.raises(S.SchedError) as e:
            S.render(j, backend, env=fake.env)
        assert e.value.code == 69
        return
    r = S.render(j, backend, env=fake.env)
    assert r.files
    for path, text in r.files.items():
        _no_placeholder(text)
        assert GENERATED_RE.search(text), text
        if backend == "launchd":
            d = plistlib.loads(text.encode())
            assert d["Label"] == j.label and "KillMode" not in d
        if backend == "systemd" and path.suffix == ".service":
            assert ("KillMode=process" in text) != j.supervised
            assert 'Environment="PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin' in text
    if backend == "cron":
        assert r.cron_block.startswith(f"# BEGIN ade-sched:{j.label}\n# generated by bin/ade-sched from ")


GENERATED_RE = re.compile(r"(#|<!--) generated by bin/ade-sched from \S+; edit the plist")


def test_unfilled_placeholder_is_exit_2():
    with pytest.raises(S.SchedError) as e:
        S.Job.from_plist(REPO / "config/launchd/com.djbclark.deadline-sweep.plist")
    assert e.value.code == 2 and "__STATE__" in str(e.value)


def test_default_subst_fills_ade_and_home(tmp_path):
    j = S.Job.from_plist(REPO / "config/launchd/com.djbclark.deadline-sweep.plist", {"__STATE__": "/s"}, ade=tmp_path)
    assert j.argv[0] == f"{os.path.realpath(tmp_path)}/bin/deadline"
    assert j.env["PATH"].startswith(f"{os.environ.get('HOME') or Path.home()}/.local/bin:")


def test_placeholders_fill_the_parsed_dict_not_the_xml(tmp_path):
    # a value with XML metacharacters stays a value: filling the text would have broken the plist
    j = S.Job.from_plist(REPO / "config/launchd/com.djbclark.deadline-sweep.plist", {"__STATE__": "/s/<a&b>"}, ade=tmp_path)
    assert j.env["DEADLINE_STATE_DIR"] == "/s/<a&b>"
    assert j.stdout == "/s/<a&b>/sweep.log"


# -- quoting ---------------------------------------------------------------------------------------------------------

def test_systemd_quoting_of_a_nasty_path():
    j = job(ProgramArguments=["/bin/echo", NASTY, "back\\slash", ";"], WorkingDirectory=f"/w/{NASTY}",
            EnvironmentVariables={"V": NASTY}, StandardOutPath=f"/o/{NASTY}.log")
    svc = S.render_systemd(j)[0]["t.job.service"]
    assert 'ExecStart="/bin/echo" "a&b <c> \'d\' %%x $$y \\"z\\"" "back\\\\slash" ";"' in svc
    assert f"WorkingDirectory=/w/{NASTY.replace('%', '%%')}" in svc
    assert 'Environment="V=a&b <c> \'d\' %%x $y \\"z\\""' in svc   # Environment= does not expand $
    assert f"StandardOutput=append:/o/{NASTY.replace('%', '%%')}.log" in svc


def test_cron_line_runs_a_nasty_path_intact(tmp_path):
    d = tmp_path / NASTY
    d.mkdir()
    out = d / "out.txt"
    code = "import os,sys; open(os.environ['OUT'],'w').write(sys.argv[1]+'|'+os.getcwd()+'|'+os.environ['V'])"
    j = job(ProgramArguments=[sys.executable, "-c", code, NASTY], WorkingDirectory=str(d),
            EnvironmentVariables={"V": NASTY, "OUT": str(out)}, StandardOutPath=str(d / "log %1"),
            StandardErrorPath=str(d / "log %1"))
    home = tmp_path / "home"
    (home / ".local/state/ade").mkdir(parents=True)     # install creates it; the run's flock -n lock lives there
    block, _ = S.render_cron(j, home=str(home))
    line = next(ln for ln in block.splitlines() if not ln.startswith("#"))
    assert "%" not in re.sub(r"\\%", "", line)          # every % is escaped for cron
    cmd = line.split(" ", 5)[5].replace("\\%", "%")      # what cron hands to /bin/sh
    p = subprocess.run(["/bin/sh", "-c", cmd], capture_output=True, text=True, check=False)
    assert p.returncode == 0, p.stderr
    assert out.read_text() == f"{NASTY}|{d}|{NASTY}"
    assert (d / "log %1").exists()


@pytest.mark.parametrize("field", ["argv", "env", "cwd", "stdout"])
def test_newline_in_any_value_is_exit_2(field):
    bad = "/x\ny"
    kw = {"argv": {"ProgramArguments": ["/bin/true", bad]}, "env": {"EnvironmentVariables": {"A": bad}},
          "cwd": {"WorkingDirectory": bad}, "stdout": {"StandardOutPath": "/x\ry"}}[field]
    with pytest.raises(S.SchedError) as e:
        job(**kw)
    assert e.value.code == 2


@pytest.mark.parametrize("name", ["API_KEY", "GH_TOKEN", "client_secret", "DB_PASSWORD", "KeyFile"])
def test_secret_looking_env_name_is_exit_2(name):
    with pytest.raises(S.SchedError) as e:
        job(EnvironmentVariables={name: "x"})
    assert e.value.code == 2 and "secret" in str(e.value)


def test_relative_program_is_exit_2():
    with pytest.raises(S.SchedError) as e:
        job(ProgramArguments=["deadline", "sweep"])
    assert e.value.code == 2


# -- schedules -------------------------------------------------------------------------------------------------------

def test_calendar_mapping_day_weekday_and_list():
    j = job(StartInterval=None, RunAtLoad=True,
            StartCalendarInterval=[{"Weekday": 7, "Hour": 3}, {"Weekday": 0, "Hour": 4, "Minute": 5},
                                   {"Day": 1, "Hour": 9, "Minute": 0}, {"Month": 2, "Day": 29, "Minute": 30}])
    files, _ = S.render_systemd(j)
    tim = files["t.job.timer"]
    assert "OnCalendar=Sun *-*-* 03:*:00" in tim
    assert "OnCalendar=Sun *-*-* 04:05:00" in tim
    assert "OnCalendar=*-*-01 09:00:00" in tim
    assert "OnCalendar=*-02-29 *:30:00" in tim
    assert "Persistent=true" in tim and "OnActiveSec=1s" in tim and "AccuracySec=1s" in tim
    block, _ = S.render_cron(j, home="/h")
    scheds = [" ".join(ln.split()[:5]) if not ln.startswith("@") else "@reboot"
              for ln in block.splitlines() if not ln.startswith("#")]
    assert scheds == ["* 3 * * 0", "5 4 * * 0", "0 9 1 * *", "30 * 29 2 *", "@reboot"]


def test_interval_timer_and_run_at_load():
    tim = S.render_systemd(job(StartInterval=1800))[0]["t.job.timer"]
    assert "OnActiveSec=1800s" in tim and "OnUnitActiveSec=1800s" in tim and "AccuracySec=1s" in tim
    assert "Persistent" not in tim
    tim = S.render_systemd(job(StartInterval=60, RunAtLoad=True))[0]["t.job.timer"]
    assert "OnActiveSec=1s" in tim and "OnUnitActiveSec=60s" in tim


def test_run_at_load_only_is_a_wanted_oneshot():
    files, _ = S.render_systemd(job(StartInterval=None, RunAtLoad=True))
    assert set(files) == {"t.job.service"}
    assert "WantedBy=default.target" in files["t.job.service"]
    assert "TimeoutStartSec" not in files["t.job.service"]
    assert S.render_cron(job(StartInterval=None, RunAtLoad=True), home="/h")[0].count("@reboot ") == 1


def test_nothing_to_schedule_is_exit_2():
    with pytest.raises(S.SchedError) as e:
        S.render_systemd(job(StartInterval=None))
    assert e.value.code == 2


@pytest.mark.parametrize("secs,sched,rounded", [
    (60, "* * * * *", False), (90, "* * * * *", True), (300, "*/5 * * * *", False), (420, "*/6 * * * *", True),
    (600, "*/10 * * * *", False), (1800, "*/30 * * * *", False), (3600, "0 * * * *", False), (5400, "0 * * * *", True),
    (18000, "0 */4 * * *", True), (21600, "0 */6 * * *", False), (86400, "0 0 * * *", False),
    (172800, "0 0 * * *", True)])
def test_cron_interval_rounding(secs, sched, rounded):
    block, notes = S.render_cron(job(StartInterval=secs), home="/h")
    assert f"\n{sched} " in block
    assert any("rounded down" in n for n in notes) == rounded


@pytest.mark.parametrize("secs", [1, 20, 59])
def test_cron_refuses_sub_minute_interval(secs):
    with pytest.raises(S.SchedError) as e:
        S.render_cron(job(StartInterval=secs), home="/h")
    assert e.value.code == 69 and f"every {secs}s" in str(e.value)


def test_keep_alive_mapping():
    files, _ = S.render_systemd(job(StartInterval=None, RunAtLoad=True, KeepAlive={"SuccessfulExit": False}))
    svc = files["t.job.service"]
    assert "Type=simple" in svc and "Restart=on-failure" in svc and "RestartSec=10s" in svc
    assert "WantedBy=default.target" in svc and "KillMode" not in svc and "TimeoutStartSec" not in svc
    assert "Restart=always" in S.render_systemd(job(StartInterval=None, KeepAlive=True))[0]["t.job.service"]
    with pytest.raises(S.SchedError) as e:
        S.render_cron(job(KeepAlive=True), home="/h")
    assert e.value.code == 69


# -- amendments: KillMode, timeouts, PATH, version -------------------------------------------------------------------

def test_kill_mode_defaults_to_process_for_a_oneshot():
    assert "KillMode=process" in S.render_systemd(job())[0]["t.job.service"]
    assert "KillMode=control-group" in S.render_systemd(job(KillMode="control-group"))[0]["t.job.service"]
    j = S.Job.from_dict({"Label": "t.job", "ProgramArguments": ["/bin/true"], "StartInterval": 60}, ade="/",
                        kill_mode="mixed")
    assert "KillMode=mixed" in S.render_systemd(j)[0]["t.job.service"]
    with pytest.raises(S.SchedError):
        job(KillMode="sometimes")
    assert "KillMode" not in S.render_launchd(job(KillMode="process"))


def test_kill_mode_process_keeps_detached_children_on_the_deadline_plist(tmp_path):
    j = S.Job.from_plist(REPO / "config/launchd/com.djbclark.deadline-sweep.plist", {"__STATE__": "/s"}, ade=tmp_path)
    assert j.effective_kill_mode == "process"
    assert "KillMode=process" in S.render_systemd(j)[0]["com.djbclark.deadline-sweep.service"]


@pytest.mark.parametrize("kw,timeout", [({"StartInterval": 60}, 300), ({"StartInterval": 600}, 1800),
                                        ({"StartInterval": None, "StartCalendarInterval": {"Hour": 3, "Minute": 50}}, 86400),
                                        ({"StartInterval": None, "StartCalendarInterval": {"Minute": 5}}, 3600)])
def test_start_timeout(kw, timeout):
    assert f"TimeoutStartSec={timeout}s" in S.render_systemd(job(**kw))[0]["t.job.service"]


def test_path_prefix_on_systemd_and_cron():
    j = job(EnvironmentVariables={"PATH": "/Users/x/.local/bin:/opt/homebrew/bin:/usr/bin"})
    svc = S.render_systemd(j)[0]["t.job.service"]
    assert 'Environment="PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin:/Users/x/.local/bin:/opt/homebrew/bin"' in svc
    block, _ = S.render_cron(j, home="/h")
    assert "/usr/bin/env PATH=/h/.local/bin:/usr/local/bin:/usr/bin:/bin:/Users/x/.local/bin:/opt/homebrew/bin " in block
    # no PATH in the plist: one is set
    assert 'Environment="PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin"' in S.render_systemd(job())[0]["t.job.service"]
    assert "/usr/bin/env PATH=/h/.local/bin:/usr/local/bin:/usr/bin:/bin /bin/true" in S.render_cron(job(), home="/h")[0]


@pytest.mark.parametrize("version,line", [(None, "StandardOutput=append:/o.log"), (255, "StandardOutput=append:/o.log"),
                                          (238, "StandardOutput=file:/o.log"), (232, None)])
def test_systemd_version_picks_the_output_mode(version, line):
    svc, notes = S.render_systemd(job(StandardOutPath="/o.log"), version)
    svc = svc["t.job.service"]
    if line:
        assert line in svc
    else:
        assert "StandardOutput" not in svc and any("journal" in n for n in notes)


def test_systemd_version_probe_uses_the_override(fake):
    assert S.systemd_version(env=fake.env) == 255
    assert S.systemd_version(env={**fake.env, "FAKE_SD_VERSION": "238"}) == 238
    r = S.render(job(StandardOutPath="/o.log"), "systemd", env={**fake.env, "FAKE_SD_VERSION": "238"})
    assert "StandardOutput=file:/o.log" in r.files[fake.units / "t.job.service"]


# -- detection -------------------------------------------------------------------------------------------------------

def _which(present):
    return lambda name, path=None: f"/usr/bin/{name}" if name in present else None


def _runner(state, rc=0, seen=None):
    def run(argv, env):
        if seen is not None:
            seen.append((argv, dict(env)))
        return rc, state + "\n", ""
    return run


BARE = {"PATH": "/usr/bin", "HOME": "/h"}


def test_detect_matrix(tmp_path):
    booted = tmp_path / "systemd"
    booted.mkdir()
    gone = str(tmp_path / "absent")
    d = {"env": BARE, "exists": lambda p: False}
    assert S.detect("cron", **d).name == "cron"
    assert S.detect(None, env={**BARE, "ADE_SCHED_BACKEND": "launchd"}, exists=lambda p: False).name == "launchd"
    assert S.detect("systemd", **d).reason == "--backend"   # explicit beats the env
    for bad, code in (("none", 69), ("upstart", 2)):
        with pytest.raises(S.SchedError) as e:
            S.detect(None, env={**BARE, "ADE_SCHED_BACKEND": bad}, exists=lambda p: False)
        assert e.value.code == code
    assert S.detect(**d, platform="darwin", which=_which({"launchctl", "crontab"}), booted_dir=gone).name == "launchd"
    assert S.detect(**d, platform="darwin", which=_which({"crontab"}), booted_dir=gone).name == "cron"
    for state, rc in (("running", 0), ("degraded", 1), ("starting", 1), ("initializing", 1)):
        b = S.detect(**d, platform="linux", which=_which({"systemctl", "crontab"}), run=_runner(state, rc),
                     booted_dir=str(booted))
        assert b.name == "systemd", state
    with pytest.raises(S.SchedError) as e:   # booted, user manager offline: 69 even with crontab, never a silent cron
        S.detect(**d, platform="linux", which=_which({"systemctl", "crontab"}), run=_runner("offline", 1),
                 booted_dir=str(booted), uid=1234)
    assert e.value.code == 69 and "export XDG_RUNTIME_DIR=/run/user/1234" in str(e.value)
    assert S.detect(**d, platform="linux", which=_which({"crontab"}), booted_dir=gone).name == "cron"
    with pytest.raises(S.SchedError) as e:
        S.detect(**d, platform="linux", which=_which(set()), booted_dir=gone)
    assert e.value.code == 69 and "no scheduler" in str(e.value)


def test_detect_points_systemctl_at_the_user_bus(tmp_path):
    booted = tmp_path / "systemd"
    booted.mkdir()
    seen: list = []
    b = S.detect(env=BARE, platform="linux", which=_which({"systemctl"}), run=_runner("running", seen=seen),
                 booted_dir=str(booted), run_user_dir="/run/user", uid=1000, exists=lambda p: p == "/run/user/1000/bus")
    assert seen[0][0][1:] == ["--user", "is-system-running"]
    assert seen[0][1]["XDG_RUNTIME_DIR"] == "/run/user/1000"
    assert seen[0][1]["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1000/bus"
    assert b.env["XDG_RUNTIME_DIR"] == "/run/user/1000"
    # an existing XDG_RUNTIME_DIR is kept
    env = S.systemd_env({**BARE, "XDG_RUNTIME_DIR": "/x"}, uid=1000, exists=lambda p: True)
    assert env["XDG_RUNTIME_DIR"] == "/x" and "DBUS_SESSION_BUS_ADDRESS" not in env


def test_dirs_and_overrides(tmp_path):
    env = {"HOME": "/h", "XDG_CONFIG_HOME": "rel", "XDG_STATE_HOME": "/st"}
    assert S.unit_dir(env) == Path("/h/.config/systemd/user")            # a relative XDG_* is unset
    assert S.unit_dir({**env, "XDG_CONFIG_HOME": "/c"}) == Path("/c/systemd/user")
    assert S.unit_dir({**env, "ADE_SCHED_UNIT_DIR": "/u"}) == Path("/u")
    assert S.unit_dir({**env, "ADE_SCHED_UNIT_DIR": "/u"}, "/o") == Path("/o")
    assert S.launch_agents_dir(env) == Path("/h/Library/LaunchAgents")
    assert S.launch_agents_dir({**env, "ADE_SCHED_LAUNCH_AGENTS": "/a"}, "/o") == Path("/o")
    assert S.lock_path(env) == Path("/st/ade/ade-sched.lock")
    assert S.tool("launchctl", {"ADE_SCHED_LAUNCHCTL": "/e"}, "/o") == "/o"
    assert S.tool("launchctl", {"ADE_SCHED_LAUNCHCTL": "/e"}) == "/e"
    with pytest.raises(TypeError):
        S.render(job(), "launchd", env=env, launch_agents="/x")


# -- install / uninstall / status: systemd ---------------------------------------------------------------------------

def test_systemd_install_status_uninstall(fake, capsys):
    j = job(StandardOutPath=str(fake.tmp / "logs/out.log"))
    S.install(j, "systemd", env=fake.env)
    svc, tim = fake.units / "t.job.service", fake.units / "t.job.timer"
    assert svc.exists() and tim.exists()
    assert stat.S_IMODE(svc.stat().st_mode) == 0o600 and stat.S_IMODE(tim.stat().st_mode) == 0o600
    assert not list(fake.units.glob("*.tmp")) and not list(fake.units.glob(".*"))
    assert (fake.tmp / "logs").is_dir()
    calls = fake.calls()
    sysd = [c for c in calls if c.startswith("systemctl") and "--version" not in c]
    assert sysd == ["systemctl --user daemon-reload", "systemctl --user enable t.job.timer",
                    "systemctl --user restart t.job.timer"]
    assert "loginctl show-user tester -p Linger --value" in calls
    st = S.status("t.job", "systemd", env=fake.env)
    assert st.installed and st.active and st.next_run == "Thu 2026-11-05 03:50:00 UTC"
    assert S.installed_labels("systemd", env=fake.env) == ["t.job"]
    fake.log.unlink()
    assert S.uninstall("t.job", "systemd", env=fake.env) is True
    assert not svc.exists() and not tim.exists()
    assert "systemctl --user disable --now t.job.timer" in fake.calls()
    assert "systemctl --user daemon-reload" in fake.calls()
    assert S.uninstall("t.job", "systemd", env=fake.env) is False
    assert not S.status("t.job", "systemd", env=fake.env).installed


def test_systemd_service_only_restart_does_not_block(fake):
    S.install(job(StartInterval=None, RunAtLoad=True), "systemd", env=fake.env)
    assert "systemctl --user restart --no-block t.job.service" in fake.calls()
    assert "systemctl --user enable t.job.service" in fake.calls()


def test_systemd_install_refuses_without_linger_before_writing(fake, capsys):
    env = {**fake.env, "FAKE_LINGER": "no"}
    with pytest.raises(S.SchedError) as e:
        S.install(job(), "systemd", env=env)
    assert e.value.code == 69
    assert "sudo loginctl enable-linger tester" in str(e.value)
    assert not fake.units.exists() or not list(fake.units.iterdir())
    assert not any("sudo" in c.split()[0] for c in fake.calls())
    S.install(job(), "systemd", env=env, allow_no_linger=True)
    assert (fake.units / "t.job.timer").exists()
    assert "linger is off for tester" in capsys.readouterr().err


def test_systemd_install_removes_an_old_cron_block(fake):
    fake.crontab.write_text("MAILTO=x\n# BEGIN ade-sched:t.job\n*/5 * * * * old\n# END ade-sched:t.job\n")
    S.install(job(), "systemd", env=fake.env)
    assert fake.crontab.read_text() == "MAILTO=x\n"


def test_systemd_activation_failure_is_exit_1(fake, tmp_path):
    _script(tmp_path / "fakebin" / "systemctl", 'case "$*" in *enable*) echo "Failed to enable: Access denied" >&2; exit 1;; esac\n')
    with pytest.raises(S.SchedError) as e:
        S.install(job(), "systemd", env=fake.env)
    assert e.value.code == 1 and "Access denied" in str(e.value)


def test_dry_run_changes_nothing(fake, capsys):
    S.install(job(), "systemd", env=fake.env, dry_run=True)
    out = capsys.readouterr().out
    assert f"# {fake.units / 't.job.service'}\n" in out and f"# {fake.units / 't.job.timer'}\n" in out
    assert "# run: " in out
    assert not fake.units.exists()
    assert not [c for c in fake.calls() if "--version" not in c]


def test_no_activate_writes_and_prints_commands(fake, capsys):
    S.install(job(), "systemd", env=fake.env, activate=False)
    assert (fake.units / "t.job.service").exists()
    out = capsys.readouterr().out
    assert f"{fake.env['ADE_SCHED_SYSTEMCTL']} --user daemon-reload" in out
    assert not [c for c in fake.calls() if "--user" in c]


def test_systemd_drops_a_stale_timer(fake):
    S.install(job(), "systemd", env=fake.env)
    S.install(job(StartInterval=None, RunAtLoad=True), "systemd", env=fake.env)
    assert not (fake.units / "t.job.timer").exists()
    assert "systemctl --user disable --now t.job.timer" in fake.calls()


# -- cron ------------------------------------------------------------------------------------------------------------

def test_cron_install_twice_one_block_foreign_lines_kept(fake):
    fake.crontab.write_text("MAILTO=me\n0 1 * * * /usr/bin/foreign\n# BEGIN ade-sched:other\n* * * * * x\n# END ade-sched:other\n")
    S.install(job(), "cron", env=fake.env)
    S.install(job(StartInterval=600), "cron", env=fake.env)
    text = fake.crontab.read_text()
    assert text.count("# BEGIN ade-sched:t.job") == 1 and text.count("# END ade-sched:t.job") == 1
    assert "*/10 * * * *" in text and "*/5 * * * *" not in text
    assert text.startswith("MAILTO=me\n0 1 * * * /usr/bin/foreign\n# BEGIN ade-sched:other\n")
    assert (fake.tmp / "lock" / "ade-sched.lock").exists()
    st = S.status("t.job", "cron", env=fake.env)
    assert st.installed and st.next_run == "*/10 * * * *"
    assert S.installed_labels("cron", env=fake.env) == ["other", "t.job"]
    assert S.uninstall("t.job", "cron", env=fake.env) is True
    assert "t.job" not in fake.crontab.read_text() and "foreign" in fake.crontab.read_text()
    assert S.uninstall("t.job", "cron", env=fake.env) is False
    assert not S.status("t.job", "cron", env=fake.env).installed


def test_cron_install_into_an_empty_crontab(fake):
    S.install(job(), "cron", env=fake.env)
    assert fake.crontab.read_text().startswith("# BEGIN ade-sched:t.job\n")


def test_cron_read_failure_aborts_without_writing(fake):
    fake.crontab.write_text("0 1 * * * /usr/bin/precious\n")
    with pytest.raises(S.SchedError) as e:
        S.install(job(), "cron", env={**fake.env, "FAKE_CRONTAB_FAIL": "1"})
    assert e.value.code == 1 and "Permission denied" in str(e.value)
    assert fake.crontab.read_text() == "0 1 * * * /usr/bin/precious\n"
    assert "crontab -" not in fake.calls()


def test_drop_cron_block():
    text = "a\n# BEGIN ade-sched:x\n1\n# END ade-sched:x\nb\n# BEGIN ade-sched:xy\n2\n# END ade-sched:xy\n"
    out, found = S.drop_cron_block(text, "x")
    assert found and out == "a\nb\n# BEGIN ade-sched:xy\n2\n# END ade-sched:xy\n"
    assert S.drop_cron_block("a", "x") == ("a\n", False)


def test_extract_cron_block():
    block = "# BEGIN ade-sched:x\n1\n# END ade-sched:x\n"
    text = "a\n" + block + "b\n# BEGIN ade-sched:xy\n2\n# END ade-sched:xy\n"
    assert S.extract_cron_block(text, "x") == block
    assert S.extract_cron_block("nope\n", "x") is None
    assert S.extract_cron_block("# BEGIN ade-sched:x\nno end\n", "x") is None


def test_drop_cron_block_refuses_an_unterminated_block():
    """A BEGIN with no END must not swallow the operator's following lines (adversary confirm on PR 291)."""
    text = "0 1 * * * mine\n" + S.cron_begin("x") + "\n* * * * * job\n5 5 * * * also-mine\n"
    with pytest.raises(S.SchedError) as e:
        S.drop_cron_block(text, "x")
    assert e.value.code == S.EX_ACTIVATE and "not changed" in str(e.value)


# -- launchd ---------------------------------------------------------------------------------------------------------

def test_launchd_install_status_uninstall(fake):
    j = job(KillMode="process")
    S.install(j, "launchd", env=fake.env)
    p = fake.agents / "t.job.plist"
    d = plistlib.loads(p.read_bytes())
    assert d["Label"] == "t.job" and d["StartInterval"] == 300 and "KillMode" not in d
    assert stat.S_IMODE(p.stat().st_mode) == 0o600 and not list(fake.agents.glob(".*"))
    uid = os.getuid()
    assert fake.calls() == [f"launchctl bootout gui/{uid}/t.job", f"launchctl bootstrap gui/{uid} {p}"]
    st = S.status("t.job", "launchd", env=fake.env)
    assert st.installed and st.active
    assert S.installed_labels("launchd", env=fake.env) == ["t.job"]
    assert S.uninstall("t.job", "launchd", env=fake.env) is True and not p.exists()
    assert S.uninstall("t.job", "launchd", env=fake.env) is False


def test_launchd_bootstrap_failure_quotes_stderr(fake):
    with pytest.raises(S.SchedError) as e:
        S.install(job(), "launchd", env={**fake.env, "FAKE_BOOTSTRAP_FAIL": "1"})
    assert e.value.code == 1 and "Input/output error" in str(e.value)


def test_unknown_keys_survive_on_launchd_and_are_noted_elsewhere(fake):
    j = job(ThrottleInterval=30)
    assert plistlib.loads(S.render_launchd(j).encode())["ThrottleInterval"] == 30
    assert any("ThrottleInterval" in n for n in S.render_systemd(j)[1])


def test_per_call_overrides_beat_env(fake, tmp_path):
    other = tmp_path / "other-agents"
    S.install(job(), "launchd", env={**fake.env, "ADE_SCHED_LAUNCHCTL": "/nonexistent"}, agents_dir=other,
              launchctl=fake.env["ADE_SCHED_LAUNCHCTL"])
    assert (other / "t.job.plist").exists() and not fake.agents.exists()


# -- worktree guard --------------------------------------------------------------------------------------------------

def test_install_refuses_a_defaulted_ade_in_a_linked_worktree(fake, tmp_path, monkeypatch):
    wt, common = tmp_path / "wt", tmp_path / "main.git" / "worktrees" / "wt"
    common.mkdir(parents=True)
    (common / "commondir").write_text("../..\n")
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {common}\n")
    assert S.is_linked_worktree(wt) and not S.is_linked_worktree(tmp_path)
    monkeypatch.setattr(S, "REPO", wt)
    d = {"Label": "t.job", "ProgramArguments": ["__ADE__/bin/x"], "StartInterval": 300}
    j = S.Job.from_dict(d)
    assert j.worktree == str(wt)
    S.install(j, "systemd", env=fake.env, dry_run=True)       # dry-run and render are allowed
    with pytest.raises(S.SchedError) as e:
        S.install(j, "systemd", env=fake.env)
    assert e.value.code == 2 and "worktree" in str(e.value)
    assert S.Job.from_dict(d, ade=wt).worktree is None          # an explicit ade is the operator's call
    assert S.Job.from_dict({**d, "ProgramArguments": ["/bin/x"]}).worktree is None


# -- systemd-analyze -------------------------------------------------------------------------------------------------

@pytest.mark.skipif(not shutil.which("systemd-analyze"), reason="systemd-analyze not installed")
def test_systemd_analyze_verifies_generated_units(tmp_path):
    d = tmp_path / "u"
    d.mkdir()
    jobs = [job(ProgramArguments=["/bin/true", NASTY, ";"], RunAtLoad=True, WorkingDirectory="/tmp",
                EnvironmentVariables={"PATH": "/opt/homebrew/bin", "V": NASTY}, StandardOutPath=f"/tmp/{NASTY}.log",
                Nice=5, LowPriorityIO=True, ProcessType="Background",
                StartCalendarInterval=[{"Weekday": 7, "Hour": 3}, {"Day": 1, "Minute": 5}]),
            S.Job.from_dict({"Label": "t.ka", "ProgramArguments": ["/bin/true"], "RunAtLoad": True,
                             "KeepAlive": {"SuccessfulExit": False}}, ade="/"),
            S.Job.from_dict({"Label": "t.once", "ProgramArguments": ["/bin/true"], "RunAtLoad": True}, ade="/")]
    paths = []
    for j in jobs:
        for name, text in S.render_systemd(j)[0].items():
            (d / name).write_text(text)
            paths.append(str(d / name))
    p = subprocess.run(["systemd-analyze", "verify", "--man=no", *paths], capture_output=True, text=True, check=False,
                       env={**os.environ, "SYSTEMD_LOG_LEVEL": "warning"})
    ours = [ln for ln in (p.stdout + p.stderr).splitlines() if str(d) in ln or "t.job" in ln or "t.ka" in ln
            or "t.once" in ln]
    assert p.returncode == 0 and not ours, p.stdout + p.stderr


# -- the CLI ---------------------------------------------------------------------------------------------------------

def cli(*args, env=None):
    return subprocess.run([sys.executable, "-I", str(CLI), *args], capture_output=True, text=True, check=False,
                          env=env or os.environ.copy())


def test_cli_render_under_isolated_mode(fake):
    p = cli("--backend", "cron", "render", str(REPO / "config/launchd/com.djbclark.deadline-sweep.plist"),
            "--set", "__STATE__=/st", "--ade", str(fake.tmp), env=fake.env)
    assert p.returncode == 0, p.stderr
    assert p.stdout.startswith("# crontab (user)\n# BEGIN ade-sched:com.djbclark.deadline-sweep\n")
    p = cli("render", "--backend", "systemd", str(REPO / "config/launchd/com.djbclark.deadline-sweep.plist"), env=fake.env)
    assert p.returncode == 2 and "__STATE__" in p.stderr
    p = cli("--set", "nokey", "--backend", "cron", "render", str(REPO / "config/launchd/com.djbclark.pr-policy.plist"),
            env=fake.env)
    assert p.returncode == 2



TEMPLATED_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.example.@TARGET@-job</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/true</string><string>@TARGET@</string></array>
  <key>StartInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>@STATE@/job.out</string>
</dict>
</plist>
"""


def test_cli_set_before_and_after_the_subcommand_both_count(fake):
    """argparse's subcommand append replaced the top-level --set list (Codex P2 on PR 291)."""
    # a templated plist of its own (the proc-cpu-watch plist that used to serve here was deleted, slim-down E5, 2026-11-06)
    plist = fake.tmp / "com.example.target-job.plist"
    plist.write_text(TEMPLATED_PLIST)
    p = cli("--set", "@STATE@=/st", "--backend", "systemd", "render", plist, "--set", "@TARGET@=opencode",
            "--ade", str(fake.tmp), env=fake.env)
    assert p.returncode == 0, p.stderr
    assert "opencode" in p.stdout and "/st" in p.stdout

def test_cli_install_status_uninstall_cron(fake):
    plist = str(REPO / "config/launchd/com.djbclark.pr-policy.plist")
    p = cli("install", "--backend", "cron", plist, "--set", f"__STATE__={fake.tmp}/st", "--ade", str(fake.tmp),
            env=fake.env)
    assert p.returncode == 0, p.stderr
    assert "# BEGIN ade-sched:com.djbclark.pr-policy" in fake.crontab.read_text()
    p = cli("status", "--backend", "cron", "com.djbclark.pr-policy", env=fake.env)
    assert p.returncode == 0 and "installed\tactive\tnext=*/10 * * * *; @reboot" in p.stdout
    assert cli("status", "--backend", "cron", "nope", env=fake.env).returncode == 3
    assert cli("uninstall", "--backend", "cron", "com.djbclark.pr-policy", env=fake.env).returncode == 0
    assert "pr-policy" not in fake.crontab.read_text()
    assert cli("uninstall", "--backend", "cron", "com.djbclark.pr-policy", env=fake.env).returncode == 0


def test_cli_exit_codes(fake):
    plist = str(REPO / "config/launchd/dev.herdr.server.plist")
    assert cli("--backend", "cron", "render", plist, env=fake.env).returncode == 69
    assert cli("backend", env={**fake.env, "ADE_SCHED_BACKEND": "none"}).returncode == 69
    p = cli("backend", "--backend", "systemd", env=fake.env)
    assert p.returncode == 0 and "linger: yes" in p.stdout and f"units: {fake.units}" in p.stdout
    assert cli("frobnicate", env=fake.env).returncode == 2
    p = cli("install", "--backend", "systemd", "--ade", str(fake.tmp), "--set", "__STATE__=/s",
            str(REPO / "config/launchd/com.djbclark.deadline-sweep.plist"), env={**fake.env, "FAKE_LINGER": "no"})
    assert p.returncode == 69 and "--allow-no-linger" in p.stderr
    p = cli("install", "--backend", "systemd", "--ade", str(fake.tmp), "--set", f"__STATE__={fake.tmp}/s",
            "--allow-no-linger", str(REPO / "config/launchd/com.djbclark.deadline-sweep.plist"),
            env={**fake.env, "FAKE_LINGER": "no"})
    assert p.returncode == 0, p.stderr
    assert (fake.units / "com.djbclark.deadline-sweep.timer").exists()


def test_imports_on_python_3_10():
    """bin/deadline imports ade_sched at load, and a Linux host's python3 may be 3.10 (Ubuntu 22.04): no 3.11+ typing
    names, and the source parses as 3.10 (adversary A1, 2026-11-04: `typing.Self` broke every deadline subcommand)."""
    import ast
    src = (Path(__file__).resolve().parents[1] / "bin" / "ade_sched.py").read_text()
    tree = ast.parse(src, feature_version=(3, 10))
    newer = {"Self", "LiteralString", "Never", "assert_never", "reveal_type", "TypeVarTuple", "Unpack",
             "Required", "NotRequired", "dataclass_transform", "override"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "typing":
            assert not newer & {a.name for a in node.names}



def test_cron_runs_are_serialized_with_flock(tmp_path):
    """cron starts a new copy while the last still runs; launchd and systemd never do (Codex P2 on PR 291)."""
    block, notes = S.render_cron(job(StartInterval=600), home="/h", flock="/usr/bin/flock")
    assert "/usr/bin/flock -n /h/.local/state/ade/" in block and ".cron.lock /usr/bin/env " in block
    block, notes = S.render_cron(job(StartInterval=600), home="/h", flock=None)
    assert "flock" not in block and any("overlap" in n for n in notes)


def test_day_and_weekday_together_fire_on_either_like_launchd():
    """launchd (and cron) fire when Day OR Weekday matches; one systemd expression would need both, so the pair becomes
    two OnCalendar= lines (Codex P2 on PR 291)."""
    files, _ = S.render_systemd(job(StartInterval=None, StartCalendarInterval={"Day": 1, "Weekday": 1, "Hour": 9, "Minute": 0}))
    tim = files["t.job.timer"]
    assert "OnCalendar=Mon *-*-* 09:00:00" in tim and "OnCalendar=*-*-01 09:00:00" in tim
    assert "Mon *-*-01" not in tim
    block, _ = S.render_cron(job(StartInterval=None, StartCalendarInterval={"Day": 1, "Weekday": 1, "Hour": 9, "Minute": 0}),
                             home="/h")
    assert "0 9 1 * 1 " in block                                  # cron's own day-of-month/weekday OR


def test_pasted_cron_block_creates_its_lock_dir():
    """A block printed by --no-activate/--dry-run and pasted before ~/.local/state/ade exists must still run (adversary C1)."""
    block, _ = S.render_cron(job(StartInterval=600), home="/h", flock="/usr/bin/flock")
    assert "mkdir -p /h/.local/state/ade && /usr/bin/flock -n /h/.local/state/ade/" in block
