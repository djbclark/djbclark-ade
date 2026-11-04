"""bin/instruction-lint (issue 284, 2026-11-04): fixtures under tmp_path, no network."""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "bin" / "instruction-lint"

GRAFT = "<!-- graft:start -->\n## Graft block\n%s\n<!-- graft:end -->\n"
LONG = ("This paragraph is deliberately long enough to pass the eighty character floor "
        "of the duplicate check, so it counts.")


def run(*args, cwd=None):
    r = subprocess.run([sys.executable, str(TOOL), *map(str, args)], capture_output=True,
                       text=True, cwd=cwd)
    return r.returncode, r.stdout, r.stderr


def lint(root, *args):
    rc, out, err = run("--root", root, "--json", *args)
    assert err == "" or rc == 2
    return rc, (json.loads(out) if out.strip() else None)


def checks(data, check=None):
    return [f for f in data["findings"] if check is None or f["check"] == check]


def write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_clean_tree_exit_0(tmp_path):
    write(tmp_path, "AGENTS.md", "# Title\n\nShort prose.\n")
    rc, d = lint(tmp_path)
    assert rc == 0 and d["findings"] == [] and d["files"] == ["AGENTS.md"]
    assert d["summary"] == {"error": 0, "warn": 0} and d["tool"] == "instruction-lint"


def test_tree_check_is_an_error(tmp_path):
    write(tmp_path, "AGENTS.md", "x\n\n```\nsrc/\n├── a.py\n└── b.py\n```\n")
    rc, d = lint(tmp_path)
    assert rc == 1
    (f,) = checks(d, "tree")
    assert f["severity"] == "error" and f["line"] == 5 and f["path"] == "AGENTS.md"


def test_tree_needs_two_lines_and_ignores_table_separators(tmp_path):
    write(tmp_path, "AGENTS.md",
          "one\n├── only\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n| c | d |\n|---|---|\n")
    rc, d = lint(tmp_path)
    assert rc == 0 and checks(d, "tree") == []


def test_tree_ascii_forms(tmp_path):
    write(tmp_path, "AGENTS.md", "|-- a\n`-- b\n\n+-- c\n+-- d\n")
    rc, d = lint(tmp_path)
    assert rc == 1 and len(checks(d, "tree")) == 2


def test_duplicate_across_distinct_files(tmp_path):
    write(tmp_path, "AGENTS.md", "Intro\n\n%s\n" % LONG)
    write(tmp_path, "GEMINI.md", "Other\n\n%s\n" % LONG.upper().replace("  ", " "))
    rc, d = lint(tmp_path)
    assert rc == 1
    (f,) = checks(d, "duplicate")
    assert f["path"] == "AGENTS.md" and "GEMINI.md" in f["detail"] and f["severity"] == "error"


def test_duplicate_whitespace_normalised_and_short_ignored(tmp_path):
    write(tmp_path, "AGENTS.md", "%s\n\nshort twin paragraph here\n" % LONG)
    write(tmp_path, "GEMINI.md", "%s\n\nshort twin paragraph here\n" % LONG.replace(" ", "   \n"))
    rc, d = lint(tmp_path)
    assert len(checks(d, "duplicate")) == 1  # the short paragraph is under 80 chars


def test_duplicate_within_one_file_is_not_flagged(tmp_path):
    write(tmp_path, "AGENTS.md", "%s\n\n%s\n" % (LONG, LONG))
    rc, d = lint(tmp_path)
    assert rc == 0 and checks(d, "duplicate") == []


def test_graft_blocks_are_not_duplicates_and_not_scanned(tmp_path):
    block = GRAFT % (LONG + "\nherdr is mentioned here")
    write(tmp_path, "AGENTS.md", "Intro\n\n" + block)
    write(tmp_path, "GEMINI.md", block)
    skills = tmp_path / "skills" / "graft"
    write(skills, "SKILL.md", "---\nname: graft\n---\n")
    rc, d = lint(tmp_path)
    assert rc == 0 and d["findings"] == []  # no duplicate, no herdr, no heading-skill


def test_symlink_is_read_once(tmp_path):
    write(tmp_path, "AGENTS.md", "%s\n" % LONG)
    os.symlink("AGENTS.md", tmp_path / "CLAUDE.md")
    rc, d = lint(tmp_path)
    assert rc == 0 and d["files"] == ["AGENTS.md"]
    assert d["skipped"] == ["CLAUDE.md: same file as AGENTS.md"]


def test_cursor_rules_are_default_files(tmp_path):
    write(tmp_path, ".cursor/rules/a.mdc", "---\nalwaysApply: true\n---\nHello\n")
    rc, d = lint(tmp_path)
    assert d["files"] == [".cursor/rules/a.mdc"]


def test_retired_term_is_a_word_bounded_warning(tmp_path):
    write(tmp_path, "AGENTS.md",
          "Use Herdr here.\nOrchestration of orcas is fine.\nUse herdr4paseo and paseo4herdr.\n"
          "See skills/session-finder/relay.py and acp-run and cow pasture and tmux.\n")
    rc, d = lint(tmp_path)
    assert rc == 0
    got = {f["line"]: f["detail"] for f in checks(d, "retired-term")}
    assert set(got) == {1, 4}
    assert "herdr" in got[1]
    for t in ("relay.py", "acp-run", "cow pasture", "tmux"):
        assert t in got[4]
    assert all(f["severity"] == "warn" for f in checks(d, "retired-term"))


def test_strict_makes_warnings_fail(tmp_path):
    write(tmp_path, "AGENTS.md", "mentions tmux\n")
    assert lint(tmp_path)[0] == 0
    assert lint(tmp_path, "--strict")[0] == 1


def test_heading_skill_warns(tmp_path):
    write(tmp_path / "skills" / "retro", "SKILL.md", "---\nname: retro-night\n---\nx\n")
    write(tmp_path / "skills", "notes.md", "not a skill dir")
    write(tmp_path, "AGENTS.md",
          "## Retro\n\n## retro night plan\n\n## Retrospective\n\n```\n## Retro\n```\n")
    rc, d = lint(tmp_path)
    assert rc == 0
    got = checks(d, "heading-skill")
    assert [f["line"] for f in got] == [1, 3] and got[0]["severity"] == "warn"


def test_skills_dir_option(tmp_path):
    other = tmp_path / "elsewhere"
    write(other / "foo", "SKILL.md", "---\nname: foo\n---\n")
    write(tmp_path, "AGENTS.md", "# Foo\n")
    assert checks(lint(tmp_path)[1], "heading-skill") == []
    assert len(checks(lint(tmp_path, "--skills-dir", other)[1], "heading-skill")) == 1


def test_explicit_files_replace_defaults(tmp_path):
    write(tmp_path, "AGENTS.md", "tmux\n")
    f = write(tmp_path, "other.md", "clean\n")
    rc, d = lint(tmp_path, f)
    assert d["files"] == ["other.md"] and d["findings"] == []


def test_output_is_byte_stable(tmp_path):
    write(tmp_path, "AGENTS.md", "tmux\n\n|-- a\n|-- b\n\n%s\n" % LONG)
    write(tmp_path, "GEMINI.md", "%s\n" % LONG)
    a = run("--root", tmp_path, "--json")
    b = run("--root", tmp_path, "--json")
    assert a == b and "generated_at" not in a[1]


def test_keys_are_unique_stable_and_line_independent(tmp_path):
    write(tmp_path, "AGENTS.md", "tmux\ntmux\n")
    d1 = lint(tmp_path)[1]
    keys = [f["key"] for f in d1["findings"]]
    assert len(set(keys)) == 2 and all(len(k) == 12 for k in keys)
    write(tmp_path, "AGENTS.md", "\n\ntmux\ntmux\n")
    assert [f["key"] for f in lint(tmp_path)[1]["findings"]] == keys


def test_text_output_never_echoes_document_text(tmp_path):
    write(tmp_path, "AGENTS.md", "SECRETWORD tmux\n")
    rc, out, err = run("--root", tmp_path)
    assert rc == 0 and "SECRETWORD" not in out and "warning(s)" in out.splitlines()[0]


def test_exit_2_cases(tmp_path):
    assert run("--root", tmp_path / "nope")[0] == 2
    assert run("--root", tmp_path, tmp_path / "missing.md")[0] == 2
    assert run("--bogus")[0] == 2


def test_internal_error_prints_class_name_only(tmp_path, monkeypatch):
    write(tmp_path, "AGENTS.md", "SECRETWORD\n")
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader("instruction_lint", str(TOOL))
    spec = importlib.util.spec_from_loader("instruction_lint", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)

    def boom(*a, **k):
        raise KeyError("SECRETWORD")
    monkeypatch.setattr(mod, "mask_graft", boom)
    import io
    err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", err)
    assert mod.main(["--root", str(tmp_path)]) == 2
    assert err.getvalue().strip() == "instruction-lint: internal error: KeyError"


def test_real_repo_has_no_errors():
    rc, out, err = run("--root", REPO, "--json")
    d = json.loads(out)
    assert rc == 0 and d["summary"]["error"] == 0, out
    assert "AGENTS.md" in d["files"] and "CLAUDE.md" not in d["files"]
