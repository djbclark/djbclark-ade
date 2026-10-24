"""bin/bm-lint (design-basicmemory W3/R6, 2026-10-24).

Every test builds its own small FIXTURE store under tmp_path: no real notes, no network,
no basic-memory binary, no SQLite index (bm-lint reads only the files). The default
--config is always overridden so the real ~/.basic-memory/config.json is never read.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "bin" / "bm-lint"
NO_CONFIG = "/nonexistent-bm-lint-config.json"  # hermetic default: check skipped, never read


def write_note(store, rel, content, age_days=0.0):
    """Create one note with a controlled mtime, the clock bm-lint judges age by."""
    p = Path(store) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    t = time.time() - age_days * 86400
    os.utime(p, (t, t))
    return p


def run(store=None, *flags, env_extra=None, use_env_store=False):
    env = {k: v for k, v in os.environ.items() if not k.startswith("BM_LINT_")}
    if env_extra:
        env.update(env_extra)
    argv = [sys.executable, str(TOOL)]
    if store is not None and not use_env_store:
        argv.append(str(store))
    argv += list(flags)
    if not any(f.startswith("--config") for f in flags):
        argv += ["--config", NO_CONFIG]
    return subprocess.run(argv, capture_output=True, text=True, env=env, timeout=120)


def text_findings(proc, check):
    return [ln for ln in proc.stdout.splitlines() if "[%s]" % check in ln]


def test_clean_store_is_exit_0(tmp_path):
    write_note(tmp_path, "a.md", "---\ntype: note\n---\n# A\nsee [[B]]\n")
    write_note(tmp_path, "b.md", "---\ntype: note\n---\n# B\nsee [[A]]\n")
    proc = run(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "no findings" in proc.stdout
    assert "skipped: empty-project" in proc.stdout  # missing config is a skip, not a finding


def test_missing_type_on_prefixed_notes(tmp_path):
    write_note(tmp_path, "feedback_use_grep.md", "# use grep\n")
    write_note(tmp_path, "reference_notes.md", "---\ntype: reference\n---\n# notes\nsee [[A]]\n")
    write_note(tmp_path, "a.md", "# A\nsee [[B]]\n")
    write_note(tmp_path, "b.md", "# B\nsee [[A]]\n")
    proc = run(tmp_path)
    assert proc.returncode == 1
    lines = text_findings(proc, "missing-type")
    assert len(lines) == 1 and "feedback_use_grep.md" in lines[0]
    assert "expected: ruling" in lines[0]  # R5's prefix -> type mapping


def test_empty_projects_from_config(tmp_path):
    full = tmp_path / "main"
    full.mkdir()
    write_note(full, "a.md", "# A\nsee [[b]]\n")
    write_note(full, "b.md", "# b\nsee [[A]]\n")
    ghost = tmp_path / "ghost"
    ghost.mkdir()
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"projects": {
        "main": {"path": str(full)}, "ghost": {"path": str(ghost)}}}), encoding="utf-8")
    proc = run(full, "--config", str(cfg))
    lines = text_findings(proc, "empty-project")
    assert proc.returncode == 1
    assert len(lines) == 1 and "ghost" in lines[0] and "no markdown notes" in lines[0]


def test_dead_subtree(tmp_path):
    write_note(tmp_path, "basic-memory/mined/m.md", "old", age_days=45)
    write_note(tmp_path, "basic-memory/archive/a.md", "old but archived", age_days=45)
    write_note(tmp_path, "fresh/f.md", "# F\nsee [[G]]\n")
    write_note(tmp_path, "g.md", "# G\nsee [[F]]\n")
    proc = run(tmp_path)
    lines = text_findings(proc, "dead-subtree")
    assert len(lines) == 1
    assert "basic-memory/mined" in lines[0]
    assert "basic-memory/archive" not in lines[0]


def test_stale_handoff_and_archive_exemption(tmp_path):
    write_note(tmp_path, "handoffs/old.md", "old", age_days=40)
    write_note(tmp_path, "handoffs/archive/older.md", "archived", age_days=400)
    write_note(tmp_path, "handoffs/fresh.md", "fresh")
    proc = run(tmp_path)
    lines = text_findings(proc, "stale-handoff")
    assert len(lines) == 1 and "handoffs/old.md" in lines[0] and "40 days" in lines[0]
    assert not text_findings(proc, "dead-subtree")  # handoffs/ is the retention check's own


def test_orphans_by_folder_and_unresolved_relations(tmp_path):
    write_note(tmp_path, "proj/x1.md", "# X1\nsee [[X2]]\n")
    write_note(tmp_path, "proj/x2.md", "# X2\nsee [[X1]]\n")
    write_note(tmp_path, "proj/island.md", "# Island\nno links\n")
    write_note(tmp_path, "proj/x3.md", "# X3\npoints [[Nowhere]]\n")
    proc = run(tmp_path)
    orphans = text_findings(proc, "orphan-notes")
    assert len(orphans) == 1 and "proj" in orphans[0] and "2 of 4" in orphans[0]
    unresolved = text_findings(proc, "unresolved-relation")
    assert len(unresolved) == 1 and "[[Nowhere]]" in unresolved[0]


def test_duplicate_titles_case_insensitive(tmp_path):
    write_note(tmp_path, "d1.md", "---\ntitle: Same Thing\n---\nsee [[b]]\n")
    write_note(tmp_path, "d2.md", "---\ntitle: same thing\n---\nsee [[a]]\n")
    write_note(tmp_path, "a.md", "# a\nsee [[b]]\n")
    write_note(tmp_path, "b.md", "# b\nsee [[a]]\n")
    proc = run(tmp_path)
    lines = text_findings(proc, "duplicate-title")
    assert len(lines) == 1
    assert "d1.md" in lines[0] and "d2.md" in lines[0]


def test_q8_ruling_and_decision_observations(tmp_path):
    write_note(tmp_path, "r1.md", "# R1\n- [ruling] always use gsed (djbclark, 2026-10-01)\n")
    write_note(tmp_path, "r2.md", "# R2\n- [ruling] never bare sed\n")
    write_note(tmp_path, "d1.md", "# D1\n- [decision] chose sqlite\n- [decision] chose pytest\nsee [[D2]]\n")
    write_note(tmp_path, "d2.md", "# D2\n- [decision] chose bash\nno link anywhere\n")
    proc = run(tmp_path)
    undated = text_findings(proc, "ruling-undated")
    assert len(undated) == 1 and "never bare sed" in undated[0]
    unlinked = text_findings(proc, "decision-unlinked")
    assert len(unlinked) == 1 and "d2.md" in unlinked[0]  # once per note, not per line


def test_status_active_needs_recent_verification(tmp_path):
    write_note(tmp_path, "noverify.md", "---\nstatus: active\n---\n# nv\nsee [[v]]\n")
    write_note(tmp_path, "v.md", "# v\nsee [[nv]]\n")
    write_note(tmp_path, "fresh.md", "---\nstatus: active\nverified: 2026-10-20\n---\n# f\nsee [[nv]]\n")
    write_note(tmp_path, "stale.md", "---\nstatus: active\nverified: 2026-01-01\n---\n# s\nsee [[nv]]\n")
    write_note(tmp_path, "done.md", "---\nstatus: done\nverified: 2026-01-01\n---\n# d\nsee [[nv]]\n")
    proc = run(tmp_path)
    lines = text_findings(proc, "status-unverified")
    assert len(lines) == 2
    assert any("noverify.md" in ln and "no verified" in ln for ln in lines)
    assert any("stale.md" in ln for ln in lines)


def test_oversize_note_and_flag(tmp_path):
    write_note(tmp_path, "big.md", "# big\nsee [[b]]\n" + "x" * 60000)
    write_note(tmp_path, "b.md", "# b\nsee [[big]]\n")
    assert len(text_findings(run(tmp_path), "oversize-note")) == 1
    proc = run(tmp_path, "--max-bytes", "100000")
    assert not text_findings(proc, "oversize-note")


def test_dead_path_references(tmp_path):
    home = tmp_path / "fakehome"
    (home / "real" / "dir").mkdir(parents=True)
    (home / "real" / "dir" / "f.md").write_text("here", encoding="utf-8")
    write_note(tmp_path, "gone.md", "# g\nbroken ~/gone/xyz/file.md\n")
    write_note(tmp_path, "glob.md", "# q\ntemplate ~/src/*/build.md\n")
    write_note(tmp_path, "ok.md", "# o\nfine ~/real/dir/f.md\n")
    proc = run(tmp_path, env_extra={"HOME": str(home)})
    lines = text_findings(proc, "dead-path")
    assert len(lines) == 1 and "gone.md" in lines[0] and "~/gone/xyz/file.md" in lines[0]


def test_json_shape_and_exit_codes(tmp_path):
    write_note(tmp_path, "feedback_x.md", "# x\nsee [[b]]\n")
    write_note(tmp_path, "b.md", "# b\n")
    proc = run(tmp_path, "--json")
    assert proc.returncode == 1
    out = json.loads(proc.stdout)
    assert out["tool"] == "bm-lint" and out["notes"] == 2
    assert out["summary"] == {"missing-type": 1}
    f = out["findings"][0]
    assert f["check"] == "missing-type"
    assert f["key"] == "missing-type:feedback_x.md"  # the stable unit fleet-watch diffs
    assert {"path", "detail"} <= set(f)


def test_error_exit_2_on_missing_store(tmp_path):
    proc = run(tmp_path / "nope")
    assert proc.returncode == 2
    assert "not a directory" in proc.stderr


def test_help_lists_every_flag():
    proc = run(None, "--help")
    assert proc.returncode == 0
    for flag in ("--json", "--config", "--handoff-days", "--dead-days",
                 "--verify-days", "--max-bytes", "store"):
        assert flag in proc.stdout, flag


def test_store_from_env(tmp_path):
    write_note(tmp_path, "a.md", "# a\nsee [[b]]\n")
    write_note(tmp_path, "b.md", "# b\nsee [[a]]\n")
    proc = run(use_env_store=True, env_extra={"BM_LINT_STORE": str(tmp_path)})
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_never_writes_to_the_store(tmp_path):
    write_note(tmp_path, "feedback_x.md", "# x\n")
    write_note(tmp_path, "handoffs/old.md", "old", age_days=90)
    write_note(tmp_path, "dead.md", "ref ~/nope/nope/nope.md\n")
    before = {
        str(p.relative_to(tmp_path)): (p.stat().st_mtime_ns, p.stat().st_size, p.stat().st_ino)
        for p in tmp_path.rglob("*")
    }
    for mode in ([], ["--json"]):
        proc = run(tmp_path, *mode)
        assert proc.returncode == 1
    after = {
        str(p.relative_to(tmp_path)): (p.stat().st_mtime_ns, p.stat().st_size, p.stat().st_ino)
        for p in tmp_path.rglob("*")
    }
    assert before == after  # read-only means byte-identical, timestamps included
