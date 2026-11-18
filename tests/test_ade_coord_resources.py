"""Transfer blockers: durable unknown launch, actual group, identity and races."""
import importlib.util
import multiprocessing
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from ade_coord_resources import ResourceError, Resources, run_job

AUTH = {"owner": {"host": "host-a", "server": "server-a", "agent": "a"},
        "ownership_epoch": 1, "generation": 1, "revision": 2}


def competing_launch(directory, output):
    state = Resources(Path(directory))
    try:
        run_job(state, job="one", claim="claim", authority=AUTH,
                argv=[sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).open('a').write('effect\\n')", output],
                authorize=lambda *_: None)
    except ResourceError:
        pass
    finally:
        state.close()


class ResourceTests(unittest.TestCase):
    def test_unknown_launch_survives_reopen_and_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Resources(Path(tmp))
            state.intent("j", "claim", AUTH)
            state.close()
            state = Resources(Path(tmp))
            self.assertFalse(state.quiescence("claim", AUTH)["jobs_stopped"])
            self.assertEqual(state.get("j")["state"], "START_UNKNOWN")
            with self.assertRaises(ResourceError):
                state.complete("j", {"exit_code": 0})
            state.close()

    def test_actual_process_group_must_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Resources(Path(tmp))
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
            try:
                state.intent("j", "claim", AUTH)
                state.spawned("j", child.pid)
                with self.assertRaises(ResourceError):
                    state.complete("j", {"exit_code": 0})
                self.assertFalse(state.quiescence("claim", AUTH)["jobs_stopped"])
            finally:
                child.terminate()
                child.wait(timeout=10)
            state.complete("j", {"exit_code": child.returncode})
            self.assertTrue(state.quiescence("claim", AUTH)["jobs_stopped"])
            state.close()

    def test_reused_pid_does_not_hide_remaining_group(self):
        old = {"pid": 100, "birth": "old", "boot": "boot", "pgid": 100, "state": "S"}
        with tempfile.TemporaryDirectory() as tmp:
            state = Resources(Path(tmp), inspect=lambda _: old, members=lambda _: [101])
            state.intent("j", "claim", AUTH)
            state.spawned("j", 100)
            state.inspect = lambda _: {**old, "birth": "new"}
            with self.assertRaises(ResourceError):
                state.complete("j", {"exit_code": 0})
            state.members = lambda _: []
            state.complete("j", {"exit_code": 0})
            self.assertTrue(state.quiescence("claim", AUTH)["jobs_stopped"])
            state.close()

    def test_two_launchers_cannot_duplicate_same_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, output = str(Path(tmp) / "state"), str(Path(tmp) / "effects")
            state = Resources(Path(directory))
            state.close()
            children = [multiprocessing.Process(target=competing_launch, args=(directory, output)) for _ in range(2)]
            for child in children:
                child.start()
            for child in children:
                child.join(timeout=20)
                self.assertEqual(child.exitcode, 0)
            self.assertEqual(Path(output).read_text().splitlines(), ["effect"])
            state = Resources(Path(directory))
            self.assertEqual(state.get("one")["state"], "QUIESCENT")
            state.close()

    def test_authority_failure_prevents_intent_and_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Resources(Path(tmp))
            def deny(*_):
                raise ResourceError("authority unavailable")
            with self.assertRaises(ResourceError):
                run_job(state, job="j", claim="claim", authority=AUTH,
                        argv=[sys.executable, "-c", "raise SystemExit(99)"], authorize=deny)
            with self.assertRaises(ResourceError):
                state.get("j")
            state.close()


if __name__ == "__main__":
    unittest.main()
