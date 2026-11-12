"""ade-install keys-collect: batch ``sudo-secretspec set``, delivery, expiry (W15). Offline only."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
sys.path.insert(0, str(BIN))
import ade_install as ai  # noqa: E402

TODAY = date(2026, 11, 12)
SENTINEL = "SECRET_VALUE_SHOULD_NOT_LEAK"

CATALOG = (
    "schema_version = 1\n"
    '[[component]]\nid = "tool-a"\nclass = "hard"\npresence = "python3"\nsummary = "Tool A"\n'
    '[[component]]\nid = "tool-off"\nclass = "optional"\nchosen = false\npresence = "python3"\nsummary = "Unchosen"\n'
    '[[key]]\nname = "A_KEY"\ncomponents = ["tool-a"]\ncreate_url = "https://example.com/a"\n'
    'verify = "fixture"\nverify_argv = ["true"]\n'
    '[[key]]\nname = "B_KEY"\ncomponents = ["tool-a"]\ncreate_url = "https://example.com/b"\n'
    'verify = "UNKNOWN"\n'
    '[[key]]\nname = "C_KEY"\ncomponents = ["tool-off"]\ncreate_url = "https://example.com/c"\n'
    'verify = "fixture"\nverify_argv = ["true"]\n'
)


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text())
    (root / "config" / "install.toml").write_text(CATALOG)
    real = ai._probe_executable_missing
    monkeypatch.setattr(
        ai, "_probe_executable_missing", lambda a: False if a == "sudo-secretspec" else real(a))
    return ai.load_catalog(root=root)


class Fake:
    """Fake sudo-secretspec: ``exits`` maps key name -> queue of verify/presence exit codes."""

    def __init__(self, exits, stderr=None, check_rc=0, check_out=""):
        self.exits = {k: list(v) for k, v in exits.items()}
        self.stderr = stderr or {}
        self.check_rc, self.check_out = check_rc, check_out
        self.calls: list[list[str]] = []

    def runner(self, argv, cwd):
        self.calls.append(list(argv))
        if argv[:2] == ["sudo-secretspec", "check"]:
            return subprocess.CompletedProcess(argv, self.check_rc, stdout=self.check_out, stderr="")
        assert argv[:2] == ["sudo-secretspec", "run"]
        name = argv[argv.index("--reason") + 1].split()[-1]
        queue = self.exits.get(name, [0])
        code = queue.pop(0) if len(queue) > 1 else queue[0]
        return subprocess.CompletedProcess(
            argv, code, stdout=SENTINEL, stderr=self.stderr.get(name, ""))


def _asker(*answers):
    queue = list(answers)
    prompts: list[str] = []

    def ask(prompt):
        prompts.append(prompt)
        if not queue:
            raise EOFError
        return queue.pop(0)

    ask.prompts = prompts  # type: ignore[attr-defined]
    return ask


def _collect(catalog, tmp_path, fake, *, interactive, ask=None, setter=None, today=TODAY):
    lines: list[str] = []
    result = ai.keys_collect(
        catalog, interactive=interactive, emit=lines.append, ask=ask or _asker(),
        setter=setter, runner=fake.runner, keys_state_path=tmp_path / "keys.json", today=today)
    return result, lines


def test_non_interactive_lists_names_and_never_prompts_or_sets(catalog, tmp_path):
    fake = Fake({"A_KEY": [14], "B_KEY": [14]})
    sets: list = []
    result, lines = _collect(
        catalog, tmp_path, fake, interactive=False,
        ask=lambda p: pytest.fail("must not prompt"), setter=lambda a, c: sets.append(a) or 0)
    assert result["rc"] == ai.EXIT_KEYS_COLLECT_NEEDS_TERMINAL == 3
    assert [w["name"] for w in result["worklist"]] == ["A_KEY", "B_KEY"]  # C_KEY: unchosen
    assert sets == []
    text = "\n".join(lines)
    assert "A_KEY" in text and "B_KEY" in text and "C_KEY" not in text
    assert "https://example.com/a" in text and SENTINEL not in text
    assert result["worklist"][0]["consumers"] == ["tool-a"]


def test_interactive_batch_sets_verifies_and_records_delivery(catalog, tmp_path):
    fake = Fake({"A_KEY": [14, 0], "B_KEY": [14, 0]})
    sets: list[list[str]] = []
    result, lines = _collect(
        catalog, tmp_path, fake, interactive=True, ask=_asker("y", "", ""),
        setter=lambda argv, cwd: sets.append(argv) or 0)
    assert result["rc"] == 0
    assert sets == [
        ["sudo-secretspec", "set", "A_KEY", "--reason", "ade-install keys-collect A_KEY"],
        ["sudo-secretspec", "set", "B_KEY", "--reason", "ade-install keys-collect B_KEY"],
    ]
    assert [(r["name"], r["outcome"]) for r in result["results"]] == [("A_KEY", "ok"), ("B_KEY", "ok")]
    assert all(r["delivery"] == ai.DELIVERY_MODE and r["consumers"] == ["tool-a"]
               for r in result["results"])
    saved = json.loads((tmp_path / "keys.json").read_text())
    assert saved["keys"]["A_KEY"]["status"] == "ok"
    assert saved["keys"]["B_KEY"]["status"] == "present"  # no verify command: presence only
    assert SENTINEL not in (tmp_path / "keys.json").read_text() + "\n".join(lines)
    # B_KEY has no verify_argv, so it is probed by the value-free presence child.
    presence = [c for c in fake.calls if "-c" in c]
    assert presence and all(c[-1] == "B_KEY" for c in presence)


def test_declining_the_batch_sets_nothing_and_exits_nonzero(catalog, tmp_path):
    fake = Fake({"A_KEY": [14], "B_KEY": [14]})
    sets: list = []
    result, _ = _collect(catalog, tmp_path, fake, interactive=True, ask=_asker("n"),
                         setter=lambda a, c: sets.append(a) or 0)
    assert sets == [] and result["rc"] == 1
    assert {r["outcome"] for r in result["results"]} == {"skipped"}


def test_skip_all_and_eof_skip_the_rest(catalog, tmp_path):
    fake = Fake({"A_KEY": [14], "B_KEY": [14]})
    sets: list = []
    result, _ = _collect(catalog, tmp_path, fake, interactive=True, ask=_asker("y", "a"),
                         setter=lambda a, c: sets.append(a) or 0)
    assert sets == [] and [r["outcome"] for r in result["results"]] == ["skipped", "skipped"]
    sets.clear()
    fake = Fake({"A_KEY": [14], "B_KEY": [14]})
    result, _ = _collect(catalog, tmp_path, fake, interactive=True, ask=_asker("y"),  # EOF next
                         setter=lambda a, c: sets.append(a) or 0)
    assert sets == [] and result["rc"] == 1


def test_set_failure_offers_retry_then_succeeds_and_never_declares(catalog, tmp_path):
    fake = Fake({"A_KEY": [14, 0], "B_KEY": [0]})
    rcs = iter([1, 0])
    argvs: list[list[str]] = []

    def setter(argv, cwd):
        argvs.append(argv)
        return next(rcs)

    ask = _asker("y", "", "r", "")
    result, _ = _collect(catalog, tmp_path, fake, interactive=True, ask=ask, setter=setter)
    assert [r["outcome"] for r in result["results"]] == ["ok"]
    assert len(argvs) == 2 and all(a[:2] == ["sudo-secretspec", "set"] for a in argvs)
    assert not any(c[:2] == ["sudo-secretspec", "add"] for c in fake.calls + argvs)
    assert any("sudo-secretspec add" in p for p in ask.prompts)  # hint only, not run


def test_verify_still_failing_after_set_is_failed_then_skippable(catalog, tmp_path):
    fake = Fake({"A_KEY": [14, 10], "B_KEY": [0]})
    result, _ = _collect(catalog, tmp_path, fake, interactive=True, ask=_asker("y", "", "s"),
                         setter=lambda a, c: 0)
    assert result["results"][0]["outcome"] == "failed" and result["rc"] == 1
    assert json.loads((tmp_path / "keys.json").read_text())["keys"]["A_KEY"]["status"] == "invalid"


def test_unreachable_verify_after_set_is_stored_unverified(catalog, tmp_path):
    fake = Fake({"A_KEY": [14, 12], "B_KEY": [0]})
    result, _ = _collect(catalog, tmp_path, fake, interactive=True, ask=_asker("y", ""),
                         setter=lambda a, c: 0)
    assert result["results"][0]["outcome"] == "stored-unverified" and result["rc"] == 1
    assert result["results"][0]["delivery"] == ai.DELIVERY_MODE


@pytest.mark.parametrize("detail,expect", [
    ("verify expiring 2026-11-20 (no value read)", "expiring 2026-11-20"),   # inside 14 days
    ("verify expiring 2026-11-26 (no value read)", "expiring 2026-11-26"),   # exactly 14 days
    ("verify expiring 2026-11-27 (no value read)", None),                    # later: waits
    ("verify expiring 2026-11-01 (no value read)", "expired 2026-11-01"),
    ("verify expiring (no value read)", "expiring (date unknown)"),
])
def test_expiry_window(detail, expect):
    assert ai.keys_collect_reason("expiring", detail, today=TODAY) == expect


def test_status_reasons_and_non_collectable_statuses():
    for status in ("missing", "invalid", "no-quota"):
        assert ai.keys_collect_reason(status, "", today=TODAY) == status
    for status in ("ok", "present", "unknown", "unreachable", "error"):
        assert ai.keys_collect_reason(status, "", today=TODAY) is None


def test_expiring_key_rejoins_the_batch_from_a_fresh_probe(catalog, tmp_path):
    fake = Fake({"A_KEY": [13], "B_KEY": [0]},
                stderr={"A_KEY": "ADE_KEY_VERIFY:expiring:2026-11-18\n"})
    result, lines = _collect(catalog, tmp_path, fake, interactive=False)
    assert [(w["name"], w["reason"]) for w in result["worklist"]] == [("A_KEY", "expiring 2026-11-18")]
    far = Fake({"A_KEY": [13], "B_KEY": [0]}, stderr={"A_KEY": "ADE_KEY_VERIFY:expiring:2027-03-01\n"})
    result, _ = _collect(catalog, tmp_path, far, interactive=False)
    assert result["worklist"] == [] and result["rc"] == 0


def test_nothing_to_collect_and_no_secretspec(catalog, tmp_path, monkeypatch):
    fake = Fake({"A_KEY": [0], "B_KEY": [0]})
    result, _ = _collect(catalog, tmp_path, fake, interactive=True,
                         ask=lambda p: pytest.fail("must not prompt"))
    assert result["rc"] == 0 and result["worklist"] == []
    monkeypatch.setattr(ai.shutil, "which", lambda _n: None)
    monkeypatch.setattr(ai, "_probe_executable_missing", lambda _a: True)
    result, _ = _collect(catalog, tmp_path, Fake({}), interactive=True)
    assert result["rc"] == 2


def test_default_setter_inherits_terminal_stdio(monkeypatch, tmp_path):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"], seen["kwargs"] = argv, kwargs
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(ai.subprocess, "run", fake_run)
    assert ai._inherited_stdio_runner(["sudo-secretspec", "set", "A_KEY"], tmp_path) == 0
    for forbidden in ("stdin", "stdout", "stderr", "input", "capture_output", "shell"):
        assert forbidden not in seen["kwargs"]


def _fake_secretspec(tmp_path, *, check_rc, probe_rc):
    """A real executable named sudo-secretspec on a private PATH dir (stdout/stderr empty)."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    exe = bindir / "sudo-secretspec"
    exe.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = check ]; then exit {check_rc}; fi\n'
        'if [ "$1" = set ]; then echo SET_WAS_RUN >> "$FAKE_LOG"; exit 0; fi\n'
        f"exit {probe_rc}\n")
    exe.chmod(0o755)
    return bindir


def _run_cli(catalog, tmp_path, bindir, *extra):
    log = tmp_path / "fake.log"
    return subprocess.run(
        [sys.executable, "-I", "-B", str(BIN / "ade-install"), "keys-collect", *extra,
         "--root", str(catalog.root), "--keys-state", str(tmp_path / "k.json")],
        capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL,
        env={"PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(tmp_path),
             "ADE_INSTALL_STATE_DIR": str(tmp_path), "FAKE_LOG": str(log)}), log


def test_cli_json_exits_3_when_work_remains_and_never_sets(catalog, tmp_path):
    # Every probe exits 14 (missing): the worklist is non-empty, so --json must exit 3.
    proc, log = _run_cli(catalog, tmp_path, _fake_secretspec(tmp_path, check_rc=1, probe_rc=14), "--json")
    assert proc.returncode == 3, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["interactive"] is False and payload["results"] == []
    assert [w["name"] for w in payload["worklist"]] == ["A_KEY", "B_KEY"]
    assert not log.exists()  # `set` never ran


def test_cli_without_terminal_exits_3_and_lists_names(catalog, tmp_path):
    proc, log = _run_cli(catalog, tmp_path, _fake_secretspec(tmp_path, check_rc=1, probe_rc=14))
    assert proc.returncode == 3 and "A_KEY" in proc.stdout and "no terminal" in proc.stdout
    assert not log.exists()


def test_cli_json_exits_2_without_sudo_secretspec(catalog, tmp_path):
    proc, _ = _run_cli(catalog, tmp_path, tmp_path / "nonexistent-bin", "--json")
    assert proc.returncode == 2 and json.loads(proc.stdout)["worklist"] == []


def test_replacement_key_with_distant_expiry_is_ok_not_unverified(catalog, tmp_path):
    # F1 (PR 597 review): an expiring key replaced by one expiring in 30 days must end ok.
    fake = Fake({"A_KEY": [13], "B_KEY": [0]},
                stderr={"A_KEY": "ADE_KEY_VERIFY:expiring:2026-11-18\n"})
    original = fake.runner
    sets: list = []

    def runner(argv, cwd):
        proc = original(argv, cwd)
        if "A_KEY" in " ".join(argv) and any(a == "run" for a in argv) and sets:
            return subprocess.CompletedProcess(argv, 13, stdout="", stderr="ADE_KEY_VERIFY:expiring:2026-12-12\n")
        return proc

    lines: list[str] = []
    result = ai.keys_collect(catalog, interactive=True, emit=lines.append, ask=_asker("y", ""),
                             setter=lambda a, c: sets.append(a) or 0, runner=runner,
                             keys_state_path=tmp_path / "keys.json", today=TODAY)
    assert [(r["name"], r["outcome"]) for r in result["results"]] == [("A_KEY", "ok")]
    assert result["rc"] == 0


def test_earlier_keys_are_reverified_after_the_whole_batch(catalog, tmp_path):
    # F2: `run` refuses while any required secret is unset, so A_KEY's immediate verify is
    # inconclusive (exit 1) until B_KEY is set too. The post-batch pass must confirm both.
    sets: list[str] = []

    def runner(argv, cwd):
        if argv[:2] == ["sudo-secretspec", "check"]:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="")
        name = argv[argv.index("--reason") + 1].split()[-1]
        done = {s[2] for s in sets}
        if name in done and len(done) == 2:
            code = 0
        elif name in done:
            code = 1  # blocked: the other required key is still unset
        else:
            code = 14
        return subprocess.CompletedProcess(argv, code, stdout="", stderr="")

    lines: list[str] = []
    result = ai.keys_collect(catalog, interactive=True, emit=lines.append, ask=_asker("y", "", ""),
                             setter=lambda a, c: sets.append(a) or 0, runner=runner,
                             keys_state_path=tmp_path / "keys.json", today=TODAY)
    assert [(r["name"], r["outcome"]) for r in result["results"]] == [("A_KEY", "ok"), ("B_KEY", "ok")]
    assert result["rc"] == 0
    assert any("confirmed after the batch" in line for line in lines)
    assert json.loads((tmp_path / "keys.json").read_text())["keys"]["A_KEY"]["status"] == "ok"


def test_still_inconclusive_after_the_batch_stays_stored_unverified(catalog, tmp_path):
    sets: list = []

    def runner(argv, cwd):
        if argv[:2] == ["sudo-secretspec", "check"]:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="")
        name = argv[argv.index("--reason") + 1].split()[-1]
        return subprocess.CompletedProcess(argv, 1 if sets else 14, stdout="", stderr="")

    result = ai.keys_collect(catalog, interactive=True, emit=lambda _l: None, ask=_asker("y", "", ""),
                             setter=lambda a, c: sets.append(a) or 0, runner=runner,
                             keys_state_path=tmp_path / "keys.json", today=TODAY)
    assert {r["outcome"] for r in result["results"]} == {"stored-unverified"} and result["rc"] == 1


def test_pasted_value_at_a_choice_prompt_is_discarded_never_echoed_never_acted_on(catalog, tmp_path):
    fake = Fake({"A_KEY": [14, 0], "B_KEY": [14, 0]})
    sets: list[list[str]] = []
    value = "sk-live-NOTAREALKEY1234567890"
    result, lines = _collect(
        catalog, tmp_path, fake, interactive=True, ask=_asker("y", value, "", ""),
        setter=lambda argv, cwd: sets.append(argv) or 0)
    # "sk-..." must not read as [s]kip (or any first-letter choice): it is re-asked.
    assert [r["outcome"] for r in result["results"]] == ["ok", "ok"] and len(sets) == 2
    blob = "\n".join(lines) + (tmp_path / "keys.json").read_text()
    assert "sk-live" not in blob and "NOTAREALKEY" not in blob
    assert "input discarded unread" in blob


def test_junk_three_times_means_skip_all(catalog, tmp_path):
    fake = Fake({"A_KEY": [14], "B_KEY": [14]})
    sets: list = []
    result, _ = _collect(catalog, tmp_path, fake, interactive=True,
                         ask=_asker("y", "enter now please", "es", "eee"),
                         setter=lambda a, c: sets.append(a) or 0)
    assert sets == [] and result["rc"] == 1


def test_default_choice_reader_is_getpass_without_echo(catalog, tmp_path, monkeypatch):
    import getpass
    seen: list[str] = []
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": seen.append(prompt) or "n")
    lines: list[str] = []
    result = ai.keys_collect(catalog, interactive=True, emit=lines.append,
                             runner=Fake({"A_KEY": [14], "B_KEY": [14]}).runner,
                             keys_state_path=tmp_path / "keys.json", today=TODAY)
    assert seen and result["rc"] == 1


def test_failed_check_never_reports_nothing_to_do(catalog, tmp_path):
    # A required secret is unset: every `run` probe exits 1 (unknown/error); check marks B_KEY.
    listing = ("Checking secrets in site (profile: default)...\n\n"
               "\u2713 A_KEY - found; mentions B_KEY in its description\n"
               "\u2717 B_KEY - Test key (required)\n"
               "\u25cb C_KEY - optional unset (optional)\n\nSummary: 1 found, 1 missing, 1 optional\n")
    fake = Fake({"A_KEY": [1], "B_KEY": [1]}, check_rc=1, check_out=listing)
    result, lines = _collect(catalog, tmp_path, fake, interactive=False)
    assert [w["name"] for w in result["worklist"]] == ["B_KEY"] and result["rc"] == 3
    # check fails and marks no selected key: unconfirmed, never rc 0, nothing offered.
    for out in ("\u2717 OTHER - x (required)\n", "B_KEY_TWO\n", "\u2713 B_KEY - found\n", ""):
        fake = Fake({"A_KEY": [1], "B_KEY": [1]}, check_rc=1, check_out=out)
        result, lines = _collect(catalog, tmp_path, fake, interactive=False)
        assert result["worklist"] == [] and result["rc"] == 1
        assert any("unconfirmed" in line for line in lines)


@pytest.mark.parametrize("text,expect", [
    ("\u2717 B_KEY - desc (required)\nSummary: 0 found, 1 missing, 0 optional\n", {"B_KEY"}),
    ("\u2717 B_KEY (required)\nSummary: 0 found, 1 missing, 0 optional\n", {"B_KEY"}),  # no description
    ("\x1b[31m\u2717\x1b[0m \x1b[1;36mB_KEY\x1b[0m - d (required)\nSummary: 0 found, 1 missing\n", {"B_KEY"}),
    ("\u2717 B_KEY - desc (required)\n", set()),                    # no Summary footer: unconfirmed
    ("\u2713 A_KEY - see\n\u2717 FOO (required)\n\u2713 FOO - ok\nSummary: 2 found, 0 missing\n", set()),
    ("\u2713 A_KEY - see\u2028\u2717 FOO (required)\nSummary: 1 found, 0 missing\n", set()),
    ("\u2713 A_KEY - x\n\u2717 FOO (required)\n\u2717 BAR (required)\nSummary: 1 found, 1 missing\n", set()),
    ("\u2713 A_KEY - list:\n  - GH_TOKEN - legacy\n  uses GH_TOKEN\n", set()),    # continuation lines
    ("\u2713 A_KEY - multi\n\u2717 not a real mark line GH_TOKEN\n", set()),
    ("\u2713\ufe0f A_KEY - variant tick\n\u2714 B_KEY - heavy tick\n", set()),
    ("\u25cb C_KEY - x (optional)\n\u25cb D_KEY - y (has default)\n", set()),
    ("\u2717 C_KEY - optional-looking (optional)\n", set()),             # not (required)
    ("Missing required secrets: B_KEY\nSummary: 1 found, 1 missing\n", set()),
    ("Secret 'B_KEY' is required but not set\n", set()),
])
def test_check_reported_missing_is_an_allowlist(text, expect):
    assert ai.check_reported_missing(text) == expect


def test_catalog_text_cannot_inject_terminal_escapes(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text())
    (root / "config" / "install.toml").write_text(
        CATALOG.replace('summary = "Tool A"', 'summary = "Tool \\u001b]52;c;eA==\\u0007A"'))
    real = ai._probe_executable_missing
    monkeypatch.setattr(ai, "_probe_executable_missing",
                        lambda a: False if a == "sudo-secretspec" else real(a))
    catalog = ai.load_catalog(root=root)
    result, lines = _collect(catalog, tmp_path, Fake({"A_KEY": [14], "B_KEY": [14]}), interactive=False)
    assert result["worklist"] and not any("\x1b" in line or "\x07" in line for line in lines)
    assert ai._printable("a\x1b[31m\x9bb\x7f") == "a?[31m?b?"


def test_scrub_key_env_removes_only_catalog_key_names(catalog):
    env = {"A_KEY": "stale", "OTHER": "x", "C_KEY": "y"}
    assert sorted(ai.scrub_key_env(catalog, env)) == ["A_KEY", "C_KEY"] and env == {"OTHER": "x"}


def test_interrupt_after_set_records_stored_unverified_and_saves_state(catalog, tmp_path):
    fake = Fake({"A_KEY": [14, 0], "B_KEY": [14, 0]})
    calls = {"a": 0}

    def runner(argv, cwd):
        if "A_KEY" in " ".join(argv):
            calls["a"] += 1
            if calls["a"] == 2:  # the post-set verify
                raise KeyboardInterrupt
        return fake.runner(argv, cwd)

    lines: list[str] = []
    result = ai.keys_collect(catalog, interactive=True, emit=lines.append, ask=_asker("y", ""),
                             setter=lambda a, c: 0, runner=runner,
                             keys_state_path=tmp_path / "keys.json", today=TODAY)
    assert [(r["name"], r["outcome"]) for r in result["results"]] == [
        ("A_KEY", "stored-unverified"), ("B_KEY", "skipped")]
    assert result["rc"] == 1 and (tmp_path / "keys.json").is_file()
    assert any("summary" in line for line in lines)


def test_default_probe_runner_closes_stdin(tmp_path, monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(ai.subprocess, "run", fake_run)
    ai._devnull_stdin_runner(5.0)(["sudo-secretspec", "check"], tmp_path)
    assert seen["stdin"] is subprocess.DEVNULL and seen["shell"] is False
