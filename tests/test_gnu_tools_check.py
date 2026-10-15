"""bin/gnu-tools-check: what counts as a bare BSD call, and what is skipped."""
import contextlib
import importlib.machinery
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_loader = importlib.machinery.SourceFileLoader("gnu_tools_check", str(ROOT / "bin" / "gnu-tools-check"))
_spec = importlib.util.spec_from_loader("gnu_tools_check", _loader)
gtc = importlib.util.module_from_spec(_spec)
sys.modules["gnu_tools_check"] = gtc
_loader.exec_module(gtc)


def found(text):
    return [(no, tool) for no, tool, _ in gtc.scan_text(text)]


class ScanText(unittest.TestCase):
    def test_bare_differing_tool_is_flagged_g_name_is_not(self):
        self.assertEqual(found("sed -n 1p f\ngsed -n 1p f\n"), [(1, "sed")])

    def test_command_positions(self):
        text = "x=$(date +%s)\nfoo | sort -u\nif true; then tr a b; fi\n`head -1 f`\n"
        self.assertEqual(found(text), [(1, "date"), (2, "sort"), (3, "tr"), (4, "head")])

    def test_words_containing_a_tool_name_are_not_calls(self):
        self.assertEqual(found("sedate x\nmy-sed x\nfoo --sort x\nprintf '%s' tail\n"), [])

    def test_single_quoted_text_is_skipped_even_across_lines(self):
        text = "ssh h 'tail -1 f; date +%s'\nssh h '\n  sed -n p f |\n  sort -u'\nwc -l f\n"
        self.assertEqual(found(text), [(5, "wc")])

    def test_double_quoted_text_is_skipped_but_command_substitution_is_not(self):
        text = 'echo "Check: grep x log | tail -1"\nv="$(sed 1q f)"\n'
        self.assertEqual(found(text), [(2, "sed")])

    def test_heredoc_body_is_skipped(self):
        text = "ssh h bash <<'EOF'\nsed -n p f\nsort f\nEOF\nuniq f\ncat <<-X\n\tawk 1\n\tX\n"
        self.assertEqual(found(text), [(5, "uniq")])

    def test_here_string_is_not_a_heredoc(self):
        self.assertEqual(found('cut -c1 <<<"$x"\ncut -c2 f\n'), [(1, "cut"), (2, "cut")])

    def test_comments_and_markers(self):
        self.assertEqual(found("# sed here\nx=1  # grep too\nsed p f  # gnu-tools-check: ignore\n"), [])
        self.assertEqual(found("#!/bin/sh\n# gnu-tools-check: portable\nsed p f\n"), [])

    def test_gnu_long_option_on_bsd_basic(self):
        self.assertEqual(found("cp --parents a b\nls -la --color=auto\n"), [(1, "cp"), (2, "ls")])

    def test_long_option_after_an_operand_belongs_to_the_command(self):
        self.assertEqual(found('env A=1 python3 x --host h\nmkdir -p -- --odd\nrm -f x\n'), [])


class Main(unittest.TestCase):
    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = gtc.main(list(args))
        return rc, out.getvalue()

    def test_exit_codes_shell_detection_and_ignore_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "a.sh").write_text("sed p f\n")
            (p / "tool").write_text("#!/usr/bin/env bash\ngrep x f\n")
            (p / "notes.md").write_text("sed p f\n")
            (p / "py").write_text("#!/usr/bin/env python3\nsed = 1\n")
            rc, out = self.run_main(d)
            self.assertEqual(rc, 1)
            self.assertIn("a.sh:1: bare sed", out)
            self.assertIn("tool:2: bare grep", out)
            self.assertNotIn("notes.md", out)
            self.assertNotIn("py:", out)
            (p / ".gnu-tools-check-ignore").write_text("# portable\na.sh\ntool\n")
            self.assertEqual(self.run_main(d), (0, ""))

    def test_git_ignored_files_are_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            subprocess.run(["git", "init", "-q", d], check=True)
            (p / ".gitignore").write_text("venv/\n")
            (p / "venv").mkdir()
            (p / "venv" / "x.sh").write_text("sed p f\n")
            (p / "y.sh").write_text("sort f\n")
            rc, out = self.run_main(d)
            self.assertEqual(rc, 1)
            self.assertIn("y.sh:1: bare sort", out)
            self.assertNotIn("venv", out)

    def test_missing_path_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(gtc.main(["/nonexistent/path/xyz"]), 2)


if __name__ == "__main__":
    unittest.main()
