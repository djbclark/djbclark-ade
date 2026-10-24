"""bin/bm-lint (design-basicmemory W3/R6, 2026-10-24).

Every test builds its own small FIXTURE store under tmp_path: no real notes, no network,
no basic-memory binary, no SQLite index (bm-lint reads only the files). The default
--config is always overridden so the real ~/.basic-memory/config.json is never read.
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta
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


def run(store=None, *flags, env_extra=None, use_env_store=False, timeout=120):
    env = {k: v for k, v in os.environ.items() if not k.startswith("BM_LINT_")}
    if env_extra:
        env.update(env_extra)
    argv = [sys.executable, str(TOOL)]
    if store is not None and not use_env_store:
        argv.append(str(store))
    argv += list(flags)
    if not any(f.startswith("--config") for f in flags):
        argv += ["--config", NO_CONFIG]
    return subprocess.run(argv, capture_output=True, text=True, env=env, timeout=timeout)


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
    assert len(unresolved) == 1 and "x3.md" in unresolved[0] and "line 2" in unresolved[0]
    assert "Nowhere" not in proc.stdout  # the link target is note text, never copied


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
    assert len(undated) == 1 and "r2.md" in undated[0] and "line 2" in undated[0]
    assert "never bare sed" not in proc.stdout  # findings never copy note text (M3)
    unlinked = text_findings(proc, "decision-unlinked")
    assert len(unlinked) == 1 and "d2.md" in unlinked[0]  # once per note, not per line


def test_status_active_needs_recent_verification(tmp_path):
    fresh = (date.today() - timedelta(days=5)).isoformat()
    stale = (date.today() - timedelta(days=200)).isoformat()
    write_note(tmp_path, "noverify.md", "---\nstatus: active\n---\n# nv\nsee [[v]]\n")
    write_note(tmp_path, "v.md", "# v\nsee [[nv]]\n")
    write_note(tmp_path, "fresh.md", "---\nstatus: active\nverified: %s\n---\n# f\nsee [[nv]]\n" % fresh)
    write_note(tmp_path, "stale.md", "---\nstatus: active\nverified: %s\n---\n# s\nsee [[nv]]\n" % stale)
    write_note(tmp_path, "done.md", "---\nstatus: done\nverified: %s\n---\n# d\nsee [[nv]]\n" % stale)
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
    assert len(lines) == 1 and "gone.md" in lines[0] and "first at line 2" in lines[0]
    assert "~/gone" not in proc.stdout  # the reference text is note content, never copied


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


# --- repair round (adversary BLOCK on 4d5a19e, 2026-10-24) -------------------------------

def jrun(store, *flags, **kw):
    proc = run(store, "--json", *flags, **kw)
    assert proc.returncode in (0, 1), proc.stdout + proc.stderr
    return proc, json.loads(proc.stdout)


def of(out, check):
    return [f for f in out["findings"] if f["check"] == check]


def test_title_is_frontmatter_else_stem_never_the_h1(tmp_path):
    write_note(tmp_path, "a/one.md", "# Shared Heading\nsee [[two]]\n")
    write_note(tmp_path, "b/two.md", "# Shared Heading\nsee [[one]]\n")
    _proc, out = jrun(tmp_path)
    assert not of(out, "duplicate-title")  # same H1, different stems: not a duplicate


def test_same_stem_in_two_folders_is_a_duplicate_title(tmp_path):
    write_note(tmp_path, "a/notes.md", "# A\nsee [[other]]\n")
    write_note(tmp_path, "b/Notes.md", "# B\nsee [[other]]\n")
    write_note(tmp_path, "other.md", "# O\nsee [[notes]]\n")
    _proc, out = jrun(tmp_path)
    dups = of(out, "duplicate-title")
    assert len(dups) == 1 and "a/notes.md" in dups[0]["detail"] and "b/Notes.md" in dups[0]["detail"]


def test_link_resolves_by_stem_for_a_note_in_a_subfolder(tmp_path):
    write_note(tmp_path, "deep/er/note_one.md", "# Not The Stem\nsee [[hub]]\n")
    write_note(tmp_path, "hub.md", "# Hub\n[[note_one]] [[note-one]] [[Note One]] [[NOTE_ONE|alias]] [[note_one#frag]]\n")
    _proc, out = jrun(tmp_path)
    assert not of(out, "unresolved-relation")
    assert not of(out, "orphan-notes")


def test_link_resolves_by_frontmatter_permalink(tmp_path):
    write_note(tmp_path, "x/y.md", "---\npermalink: custom/place\n---\nsee [[hub]]\n")
    write_note(tmp_path, "hub.md", "# Hub\nsee [[custom/place]]\n")
    _proc, out = jrun(tmp_path)
    assert not of(out, "unresolved-relation")


def test_link_resolves_by_slugged_folder_and_stem(tmp_path):
    write_note(tmp_path, "My Proj/My_Note.md", "see [[hub]]\n")
    write_note(tmp_path, "hub.md", "see [[my-proj/my-note]]\n")
    _proc, out = jrun(tmp_path)
    assert not of(out, "unresolved-relation")


def test_link_resolves_by_frontmatter_title(tmp_path):
    write_note(tmp_path, "zzz.md", "---\ntitle: Pretty Name\n---\nsee [[hub]]\n")
    write_note(tmp_path, "hub.md", "see [[pretty name]]\n")
    _proc, out = jrun(tmp_path)
    assert not of(out, "unresolved-relation")


def test_links_in_code_are_not_relations(tmp_path):
    write_note(tmp_path, "a.md", "see [[b]]\n```\n[[GhostFence]]\n```\n"
                                 "and `[[GhostInline]]` then [[GhostReal]] here\n")
    write_note(tmp_path, "b.md", "see [[a]]\n")
    _proc, out = jrun(tmp_path)
    un = of(out, "unresolved-relation")
    assert len(un) == 1 and "line 5" in un[0]["detail"]  # the one outside code, line kept true


def test_markdown_links_count_as_relations(tmp_path):
    write_note(tmp_path, "a.md", "read [the other](sub/b.md#top) and [web](https://x.example/c.md)\n")
    write_note(tmp_path, "sub/b.md", "back to [a](../a.md)\n")
    write_note(tmp_path, "lone.md", "nothing\n")
    proc, out = jrun(tmp_path)
    orphans = of(out, "orphan-notes")
    assert len(orphans) == 1 and orphans[0]["path"] == "." and "1 of 2" in orphans[0]["detail"]
    assert not of(out, "unresolved-relation")


def test_repeated_unresolved_target_is_one_finding_and_keys_are_unique(tmp_path):
    write_note(tmp_path, "a.md", "[[Ghost]] again [[Ghost]] and [[Ghost]]\n[[Other]]\n")
    write_note(tmp_path, "b.md", "[[Ghost]] [[a]]\n")
    write_note(tmp_path, "r.md", "- [ruling] same words\n- [ruling] same words\n- [ruling] other\n")
    _proc, out = jrun(tmp_path)
    un = of(out, "unresolved-relation")
    assert len(un) == 3
    assert any("3 occurrences" in f["detail"] and f["path"] == "a.md" for f in un)
    keys = [f["key"] for f in out["findings"]]
    assert len(keys) == len(set(keys))


def test_ruling_key_survives_an_edit_above_it(tmp_path):
    p = write_note(tmp_path, "r.md", "# R\n- [ruling] never bare sed\n")
    _proc, before = jrun(tmp_path)
    keys = [f["key"] for f in of(before, "ruling-undated")]
    assert len(keys) == 1
    p.write_text("# R\nnew intro line\nanother\n- [ruling] never bare sed\n", encoding="utf-8")
    _proc, after = jrun(tmp_path)
    assert [f["key"] for f in of(after, "ruling-undated")] == keys
    assert "line 4" in of(after, "ruling-undated")[0]["detail"]


def test_symlinked_note_is_not_read_and_a_fifo_does_not_hang(tmp_path):
    store = tmp_path / "store"
    write_note(store, "a.md", "see [[b]]\n")
    write_note(store, "b.md", "see [[a]]\n")
    outside = write_note(tmp_path, "outside.md", "- [ruling] OUTSIDECANARY said so\n[[OUTSIDELINK]]\n")
    os.symlink(outside, store / "leak.md")
    proc, out = jrun(store)
    assert proc.returncode == 0, proc.stdout
    assert "CANARY" not in proc.stdout and "OUTSIDELINK" not in proc.stdout
    assert out["notes"] == 2
    assert any("symlink" in s and "leak.md" in s for s in out["skipped"])
    if hasattr(os, "mkfifo"):
        os.mkfifo(store / "pipe.md")
        proc = run(store, "--json", timeout=30)  # old code blocks in open(): TimeoutExpired
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert any("pipe.md" in s and "not a regular file" in s
                   for s in json.loads(proc.stdout)["skipped"])


def test_no_note_text_in_findings(tmp_path):
    home = tmp_path / "fakehome"
    home.mkdir()
    write_note(tmp_path, "rr.md", "- [ruling] RULINGCANARY text\n")
    write_note(tmp_path, "ll.md", "see [[LINKCANARY]]\n")
    write_note(tmp_path, "vv.md", "---\nstatus: active\nverified: VERIFYCANARY\n---\n")
    write_note(tmp_path, "t1.md", "---\ntitle: TITLECANARY\n---\nx\n")
    write_note(tmp_path, "t2.md", "---\ntitle: titlecanary\n---\nx\n")
    write_note(tmp_path, "pp.md", "dead ~/PATHCANARY/zz/yy here\n")
    for flags in (["--json"], []):
        proc = run(tmp_path, *flags, env_extra={"HOME": str(home)})
        assert proc.returncode == 1
        blob = (proc.stdout + proc.stderr).upper()
        for canary in ("RULINGCANARY", "LINKCANARY", "VERIFYCANARY", "TITLECANARY", "PATHCANARY"):
            assert canary not in blob, canary
    _proc, out = jrun(tmp_path, env_extra={"HOME": str(home)})
    for check in ("ruling-undated", "unresolved-relation", "status-unverified",
                  "duplicate-title", "dead-path"):
        assert of(out, check), check  # the canaries really did trigger each finding


def test_bad_env_default_is_a_usage_error(tmp_path):
    write_note(tmp_path, "a.md", "see [[b]]\n")
    write_note(tmp_path, "b.md", "see [[a]]\n")
    proc = run(tmp_path, env_extra={"BM_LINT_MAX_BYTES": "50KB"})
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr and "--max-bytes" in proc.stderr


def test_odd_config_shapes_never_crash_with_exit_1(tmp_path):
    write_note(tmp_path, "a.md", "see [[b]]\n")
    write_note(tmp_path, "b.md", "see [[a]]\n")
    for body in ('{"projects": ["a", "b"]}', '{"projects": {"a": 5, "b": {"path": 7}, "c": null}}',
                 '[1, 2]', '{"projects": 3}'):
        cfg = tmp_path / "config.json"
        cfg.write_text(body, encoding="utf-8")
        proc = run(tmp_path, "--config", str(cfg))
        assert "Traceback" not in proc.stderr, body
        assert proc.returncode in (0, 2), (body, proc.stdout, proc.stderr)


def test_hostile_notes_are_linear_time(tmp_path):
    write_note(tmp_path, "a.md", "[" * 20000 + "\n")
    write_note(tmp_path, "b.md", "\n" * 100000 + "x\n")  # the scan that failed on the old ^\s*
    write_note(tmp_path, "c.md", "[[a" * 5000 + "\n")
    write_note(tmp_path, "d.md", "[x" * 10000 + "\n")
    write_note(tmp_path, "e.md", "[](" * 64000 + "\n")
    write_note(tmp_path, "f.md", "[](a.md" * 28000 + "\n")
    write_note(tmp_path, "g.md", "\n" * 40000 + "- [ruling] x\n")
    start = time.monotonic()
    proc = run(tmp_path, "--max-bytes", "10000000", timeout=120)
    elapsed = time.monotonic() - start
    assert proc.returncode in (0, 1), proc.stderr
    # Generous: the quadratic versions took 8-27 s per note, linear ones take well under 1 s,
    # so 10 s still separates them without flaking on a loaded machine.
    assert elapsed < 10, elapsed
    assert text_findings(proc, "ruling-undated")


def test_oversize_note_skips_relations_and_is_not_an_orphan(tmp_path):
    write_note(tmp_path, "big.md", "# big\n" + "x" * 60000)
    write_note(tmp_path, "a.md", "see [[b]]\n")
    write_note(tmp_path, "b.md", "see [[a]]\n")
    _proc, out = jrun(tmp_path)
    assert not of(out, "orphan-notes")
    assert any("relations not parsed" in s and "big.md" in s for s in out["skipped"])


def test_dead_path_skips_globs_templates_and_spaced_paths(tmp_path):
    home = tmp_path / "fakehome"
    (home / "Library" / "Application Support").mkdir(parents=True)
    (home / "real" / "dir").mkdir(parents=True)
    store = tmp_path / "store"
    for rel, line in {
        "glob.md": "~/src/foo-*/x",
        "brace.md": "~/src/proj-{a,b}/x",
        "tmpl.md": "~/src/<name>/x and ~/src/$VAR/x",
        "space.md": "~/Library/Application Support/x",
        "okdir.md": "the dir ~/real/dir/ and (~/real/dir) and `~/real/dir`.",
    }.items():
        write_note(store, rel, "# n\nsee [[b]] %s\n" % line)
    write_note(store, "b.md", "see [[glob]]\n")
    write_note(store, "dead.md", "gone ~/gone/a/b/ and ~/gone/c/d. ok\nsee [[b]]\n")
    proc, out = jrun(store, env_extra={"HOME": str(home)})
    assert [f["path"] for f in of(out, "dead-path")] == ["dead.md"]
    assert "2 of 2" in of(out, "dead-path")[0]["detail"]


def test_leading_bom_does_not_hide_frontmatter(tmp_path):
    write_note(tmp_path, "feedback_bom.md", "\ufeff---\ntype: ruling\n---\n# x\nsee [[b]]\n")
    write_note(tmp_path, "b.md", "see [[feedback_bom]]\n")
    _proc, out = jrun(tmp_path)
    assert not of(out, "missing-type")


def test_unterminated_frontmatter_counts_as_none(tmp_path):
    write_note(tmp_path, "feedback_open.md", "---\ntype: ruling\nbody text\nstatus: active\nsee [[b]]\n")
    write_note(tmp_path, "b.md", "see [[feedback_open]]\n")
    _proc, out = jrun(tmp_path)
    assert [f["path"] for f in of(out, "missing-type")] == ["feedback_open.md"]
    assert not of(out, "status-unverified")


def test_dead_subtree_spares_a_parent_with_a_fresh_child(tmp_path):
    write_note(tmp_path, "p/old.md", "see [[new]]\n", age_days=45)
    write_note(tmp_path, "p/child/new.md", "see [[old]]\n")
    write_note(tmp_path, "q/old.md", "see [[new]]\n", age_days=45)
    _proc, out = jrun(tmp_path)
    assert [f["path"] for f in of(out, "dead-subtree")] == ["q"]


# --- last fixes before merge (Codex P2, adversary round 2 C1-C6, 2026-10-24) -------------

def test_observations_in_a_code_fence_are_examples_not_findings(tmp_path):
    write_note(tmp_path, "fenced.md",
               "# doc\nsee [[fenced]]\n```\n- [decision] example choice\n- [ruling] example rule\n```\n")
    write_note(tmp_path, "open.md", "# doc\n- [decision] real choice\n- [ruling] real rule\n")
    write_note(tmp_path, "inline.md", "# doc\nsee `- [decision] x` and `- [ruling] y` as text\n")
    _proc, out = jrun(tmp_path)
    assert [f["path"] for f in of(out, "decision-unlinked")] == ["open.md"]
    assert [f["path"] for f in of(out, "ruling-undated")] == ["open.md"]
    assert "line 3" in of(out, "ruling-undated")[0]["detail"]  # line numbers stay true


def test_ruling_after_a_fence_keeps_its_line_number(tmp_path):
    write_note(tmp_path, "r.md", "```\n- [ruling] in fence\n```\n\n- [ruling] after\n")
    _proc, out = jrun(tmp_path)
    found = of(out, "ruling-undated")
    assert len(found) == 1 and "line 5" in found[0]["detail"]


def load_tool():
    import importlib.util
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader("bm_lint_under_test", str(TOOL))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


def test_mdlink_re_stays_strict():
    rx = load_tool().MDLINK_RE
    assert rx.search("[t](sub/b.md#top)").group(1) == "sub/b.md"
    assert rx.search("[t](../a.md)").group(1) == "../a.md"
    assert rx.search("[t](https://x.example/c.md)") is None
    assert rx.search("[t](a(b.md)") is None and rx.search("[t](a]b.md)") is None


def test_unreadable_store_root_is_exit_2_not_clean(tmp_path):
    if os.geteuid() == 0:
        import pytest
        pytest.skip("root reads everything")
    store = tmp_path / "store"
    write_note(store, "a.md", "see [[b]]\n")
    os.chmod(store, 0o000)
    try:
        proc = run(store)
    finally:
        os.chmod(store, 0o755)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "not readable" in proc.stderr and "no findings" not in proc.stdout


def test_unreadable_subdirectory_is_listed_under_skipped(tmp_path):
    if os.geteuid() == 0:
        import pytest
        pytest.skip("root reads everything")
    store = tmp_path / "store"
    write_note(store, "a.md", "see [[b]]\n")
    write_note(store, "locked/secret.md", "SECRETBODY see [[a]]\n")
    os.chmod(store / "locked", 0o000)
    try:
        proc = run(store, "--json")
    finally:
        os.chmod(store / "locked", 0o755)
    assert proc.returncode in (0, 1), proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["notes"] == 1
    assert any("directory not readable" in s and "locked" in s for s in out["skipped"]), out["skipped"]
    assert "SECRETBODY" not in proc.stdout


def _need_nonroot():
    if os.geteuid() == 0:
        import pytest
        pytest.skip("root reads everything")


def test_unreadable_note_is_listed_under_skipped_not_dropped(tmp_path):
    _need_nonroot()
    store = tmp_path / "store"
    write_note(store, "a.md", "see [[nope]]\n")
    secret = write_note(store, "locked.md", "SECRETBODY see [[a]]\n")
    os.chmod(secret, 0o000)
    try:
        proc = run(store, "--json")
    finally:
        os.chmod(secret, 0o644)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["notes"] == 1
    assert any("not readable" in s and "locked.md" in s for s in out["skipped"]), out["skipped"]
    assert "SECRETBODY" not in proc.stdout and "denied" not in proc.stdout.lower()
    assert of(out, "unresolved-relation")  # the readable note's findings still come out


def test_store_root_without_search_permission_is_exit_2_not_clean(tmp_path):
    _need_nonroot()
    store = tmp_path / "store"
    write_note(store, "a.md", "x\n")
    write_note(store, "sub/b.md", "y\n")
    os.chmod(store, 0o444)
    try:
        proc = run(store)
    finally:
        os.chmod(store, 0o755)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "no findings" not in proc.stdout
    assert str(store) in proc.stderr


def test_unlistable_subdirectory_with_a_readable_sibling_is_skipped(tmp_path):
    _need_nonroot()
    store = tmp_path / "store"
    write_note(store, "a.md", "x\n")
    write_note(store, "sub/b.md", "y\n")
    os.chmod(store / "sub", 0o444)
    try:
        proc = run(store, "--json")
    finally:
        os.chmod(store / "sub", 0o755)
    out = json.loads(proc.stdout)
    assert out["notes"] == 1
    # listable but not searchable: the directory itself lists, its note cannot be opened
    assert any("sub" in s and "not readable" in s for s in out["skipped"]), out["skipped"]


def test_note_deleted_between_walk_and_read_stays_silent(tmp_path, monkeypatch):
    write_note(tmp_path, "a.md", "x\n")
    write_note(tmp_path, "gone.md", "y\n")
    tool = load_tool()
    real_open = os.open

    def vanishing_open(path, *a, **kw):
        if str(path).endswith("gone.md"):
            raise FileNotFoundError(2, "No such file", str(path))
        return real_open(path, *a, **kw)

    monkeypatch.setattr(tool.os, "open", vanishing_open)
    store = tool.Store(str(tmp_path), 51200)
    assert [n["rel"] for n in store.notes] == ["a.md"]
    assert store.skipped == []


def test_markdown_link_out_of_the_store_gets_no_stem_fallback(tmp_path):
    write_note(tmp_path, "README.md", "nothing\n")
    write_note(tmp_path, "x/a.md", "see [elsewhere](../../elsewhere/README.md)\n")
    _proc, out = jrun(tmp_path)
    orphans = {f["path"]: f["detail"] for f in of(out, "orphan-notes")}
    assert "." in orphans and "1 of 1" in orphans["."]  # README is not reached by the outside link
    assert "x" in orphans


def test_markdown_link_to_a_moved_note_still_falls_back_to_the_stem(tmp_path):
    write_note(tmp_path, "a.md", "see [it](old/place/README.md)\n")
    write_note(tmp_path, "new/README.md", "nothing\n")
    _proc, out = jrun(tmp_path)
    assert not of(out, "orphan-notes")  # in-store guess kept: only `..` escapes are refused


def test_internal_error_is_exit_2_with_a_message(tmp_path, monkeypatch, capsys):
    mod = load_tool()
    write_note(tmp_path, "a.md", "see [[b]]\n")

    def boom(self, store):
        raise RuntimeError("boom")

    monkeypatch.setattr(mod.Linter, "check_oversize", boom)
    rc = mod.main([str(tmp_path), "--config", NO_CONFIG])
    err = capsys.readouterr().err
    assert rc == 2
    assert "internal error" in err and "RuntimeError" in err


def test_readme_roster_documents_every_flag_and_exit_code():
    import re
    help_text = run(None, "--help").stdout
    flags = set(re.findall(r"--[a-z][a-z-]+", help_text)) - {"--help"}
    row = [ln for ln in (REPO / "README.md").read_text(encoding="utf-8").splitlines()
           if ln.startswith("| [`bin/bm-lint`]")]
    assert len(row) == 1, "README roster needs exactly one bin/bm-lint entry"
    assert flags and all(f in row[0] for f in flags), sorted(f for f in flags if f not in row[0])
    assert "Exit codes: 0 no findings, 1 findings, 2 error" in row[0]
