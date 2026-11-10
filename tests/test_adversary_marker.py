"""bin/adversary_marker.py: the adversary-verdict marker parser (moved from the removed PR waiter, 2026-11-06, slim-down E8)
and the Action's event logic (.github/workflows/adversary-marker.yml).

The marker tests below the banner "adversary verdict MARKER in the PR body" moved from the waiter's test file
UNCHANGED: only `load_module()` (now the imported module) and the `gate()` helper's last two lines (the waiter's
`assess()` became `adversary_marker.gate()`, its adversary branch) differ. They are the acceptance test of the
port (AGENTS.md review rule 1's five properties). The Action's tests are at the end.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "bin" / "adversary_marker.py"
WORKFLOW = ROOT / ".github" / "workflows" / "adversary-marker.yml"
sys.path.insert(0, str(ROOT / "bin"))
import adversary_marker  # noqa: E402


def load_module():
    """The module under test (the waiter's tests loaded the script by path; this one is importable)."""
    return adversary_marker


# ---- adversary verdict MARKER in the PR body ------------------------------------------------
#
# Rewritten 2026-10-25 for the MARKER design (Dann 5's ruling after two adversary rounds). The first
# version parsed English; round 1 found six false APPROVEs and five false MISSES, round 2 found
# fourteen NEW false APPROVEs including a BLOCK silently deleted by a prose filter. The prose parser
# and its heuristics are DELETED, not patched: correctness there would mean "no sentence anyone could
# write defeats it", which is unbounded.
#
# Every test below is one of Dann 5's six required properties, plus the regressions the review found.

ADV_HEAD = "a" * 40
OTHER_HEAD = "b" * 40


def marker(verdict: str, head: str = ADV_HEAD) -> str:
    return f'<!-- adversary-verdict:v1 {{"verdict":"{verdict}","head":"{head}"}} -->'


def adv(body: str, head: str = ADV_HEAD) -> dict:
    return load_module().adversary_verdict(body, head)


def passes(body: str, head: str = ADV_HEAD) -> bool:
    """The same predicate assess() uses: matched AND not a BLOCK."""
    r = adv(body, head)
    return bool(r["matches_head"]) and not str(r["verdict"] or "").upper().startswith("BLOCK")


# --- property 1: the :v1 suffix is part of the match -----------------------------------------

def test_a_marker_without_the_v1_suffix_is_not_this_marker() -> None:
    # Rule 9 records a waiter whose regex lacked :v1 seeing no state on PR 12 and running 30 minutes.
    body = '<!-- adversary-verdict {"verdict":"APPROVE","head":"' + ADV_HEAD + '"} -->'
    assert not adv(body)["present"]


def test_the_canonical_marker_approves_this_head() -> None:
    assert passes(marker("APPROVE"))


def test_the_canonical_marker_blocks_this_head() -> None:
    r = adv(marker("BLOCK"))
    assert r["present"] and r["matches_head"] and r["verdict"] == "BLOCK"
    assert not passes(marker("BLOCK"))


# --- property 2: a missing or unknown verdict value fails closed ------------------------------

def test_an_unknown_verdict_value_is_malformed_not_a_default() -> None:
    body = '<!-- adversary-verdict:v1 {"verdict":"LGTM","head":"' + ADV_HEAD + '"} -->'
    r = adv(body)
    assert not r["present"] and r["malformed"]
    assert "APPROVE or BLOCK" in r["detail"]


def test_a_missing_verdict_field_is_malformed() -> None:
    body = '<!-- adversary-verdict:v1 {"head":"' + ADV_HEAD + '"} -->'
    r = adv(body)
    assert not r["present"] and r["malformed"]


# --- property 3: head must be 40 hex and must equal the PR head -------------------------------

def test_a_marker_for_another_head_is_not_a_pass() -> None:
    r = adv(marker("APPROVE", OTHER_HEAD))
    assert r["present"] and not r["matches_head"]
    assert "NOT this head" in r["detail"]


def test_a_short_head_is_malformed() -> None:
    r = adv(marker("APPROVE", ADV_HEAD[:7]))
    assert not r["present"] and r["malformed"]
    assert "40-hex" in r["detail"]


# --- property 4: a malformed marker is its own outcome ---------------------------------------

def test_a_marker_that_is_not_json_is_malformed() -> None:
    r = adv('<!-- adversary-verdict:v1 {"verdict":"APPROVE","head": -->')
    assert not r["present"] and r["malformed"]
    assert "malformed" in r["detail"]


# --- property 5: never fall back to prose ----------------------------------------------------

def test_prose_verdicts_with_no_marker_are_simply_missing() -> None:
    for body in (f"> **APPROVE, no findings** (head {ADV_HEAD})",
                 f"VERDICT: APPROVE {ADV_HEAD}",
                 f"Adversary: APPROVE (head {ADV_HEAD})",
                 f"**Codex verdict:** APPROVE at {ADV_HEAD}"):
        r = adv(body)
        assert not r["present"], body
        assert "marker" in r["detail"], body


def test_an_empty_body_reports_no_verdict() -> None:
    r = adv("")
    assert not r["present"] and r["detail"] == "no PR body"


# --- property 6: a BLOCK is never downgraded (the rule is asymmetric) -------------------------



def test_a_block_beats_an_approve_for_the_same_head() -> None:
    body = marker("APPROVE") + "\n\n" + marker("BLOCK")
    r = adv(body)
    assert r["verdict"] == "BLOCK" and r["conflict"] and r["matches_head"]
    assert not passes(body)
    assert "BOTH" in r["detail"]


def test_an_approve_for_another_head_does_not_block_the_block_for_this_head() -> None:
    body = marker("APPROVE", OTHER_HEAD) + "\n\n" + marker("BLOCK")
    assert not passes(body)


def test_a_malformed_marker_beside_a_good_one_still_reports_the_verdict() -> None:
    body = '<!-- adversary-verdict:v1 {broken -->' + "\n\n" + marker("APPROVE")
    r = adv(body)
    assert r["present"] and r["matches_head"] and r["malformed"]


def gate(body: str, required: bool = True, head: str = ADV_HEAD) -> tuple[bool, list[str]]:
    """Run the REAL gate (`gate`, the waiter's `assess` adversary branch), not a copy of its predicate.

    The first version of these tests only called `adversary_verdict` / a copied predicate, so the
    gate itself (the blocker names, the report-only default, `malformed` handling) was untested —
    which is how a malformed BLOCK beside a valid APPROVE reached `merge_ready: true`.
    """
    mod = load_module()
    adv = mod.adversary_verdict(body, head)
    adv["required_by_label"] = False
    r = mod.gate(adv, required)
    return r["merge_ready"], r["adversary_warnings"]


def test_the_gate_blocks_a_malformed_marker_beside_a_valid_approve() -> None:
    # The A1 finding: `assess()` ignored `malformed`, so a typo in a BLOCK let the PR through.
    # A BLOCK whose head is a PREFIX of this head is not a typo any more: it is a BLOCK for this head
    # (adversary review of 4a56c01, B1) and is covered by its own test below.
    for broken in ('{"verdict":"BLOCKED","head":"' + ADV_HEAD + '"}',
                   '{"verdict":"BLOCK","head":"b50521a"}',
                   '{"verdict":"BLOCK","head":"' + ADV_HEAD + '"}'):  # the third is unclosed below
        body = marker("APPROVE") + "\n<!-- adversary-verdict:v1 " + broken
        ready, warnings = gate(body)
        assert not ready, body
        assert warnings == ["adversary-malformed"], warnings


def test_the_gate_reports_malformed_as_its_own_warning_not_as_missing() -> None:
    ready, warnings = gate('<!-- adversary-verdict:v1 {broken -->')
    assert not ready
    assert warnings == ["adversary-malformed"]


def test_the_gate_passes_a_good_approve() -> None:
    ready, warnings = gate(marker("APPROVE"))
    assert ready and warnings == []


def test_the_gate_blocks_a_block() -> None:
    ready, warnings = gate(marker("BLOCK"))
    assert not ready and warnings == ["adversary-stale-or-blocked"]


def test_the_gate_is_report_only_by_default() -> None:
    ready, warnings = gate(marker("BLOCK"), required=False)
    assert ready, "a missing/stale verdict must not block without opt-in"
    assert warnings == ["adversary-stale-or-blocked"], "but it must still be REPORTED"


def test_a_pr_documenting_the_format_does_not_trip_its_own_gate() -> None:
    # B1: PR 66's own body quotes the template, and reading it as a live marker made every PR that
    # documents the format unmergeable (malformed blocks by default).
    documented = (
        "The marker is:\n\n"
        "```\n"
        '<!-- adversary-verdict:v1 {"verdict":"APPROVE"|"BLOCK","head":"<40-hex>"} -->\n'
        "```\n\n"
        "and inline: `<!-- adversary-verdict:v1 {\"verdict\":\"APPROVE\",\"head\":\"<40-hex>\"} -->`\n"
    )
    r = adv(documented)
    assert not r["malformed"], r["detail"]
    assert not r["present"], "documentation is not a verdict"


def test_a_placeholder_head_alone_is_documentation_not_malformed() -> None:
    body = '<!-- adversary-verdict:v1 {"verdict":"APPROVE","head":"<40-hex>"} -->'
    r = adv(body)
    assert not r["malformed"] and not r["present"]
    assert "placeholder" in r["detail"]


def test_a_real_marker_inside_a_fence_is_ignored() -> None:
    # The review's argument: the body is author-controlled, so reading fences protects nothing and
    # only creates false blocks. A quoted marker is text, not a claim.
    assert not adv("```\n" + marker("APPROVE") + "\n```")["present"]


def test_a_real_marker_in_an_inline_code_span_is_ignored() -> None:
    assert not adv("the previous marker was `" + marker("APPROVE") + "`")["present"]


def test_a_genuinely_malformed_marker_still_fails_closed() -> None:
    r = adv('<!-- adversary-verdict:v1 {"verdict":"BLOCKED","head":"' + ADV_HEAD + '"} -->')
    assert r["malformed"] and not r["present"]


def test_a_shortened_sha_block_is_not_reclassified_as_documentation() -> None:
    # R3a: `"..." in sha` also matched `b50521af22b1…`, so a real BLOCK typed with an ellipsis was
    # silently turned into "no verdict" and stopped blocking. Only the TEMPLATE's placeholder skips.
    for head in ("b50521af22b1…", "<sha>", "b50521af22b1..."):
        body = '<!-- adversary-verdict:v1 {"verdict":"BLOCK","head":"' + head + '"} -->'
        r = adv(body)
        assert r["malformed"] and not r["present"], head


def test_a_shortened_sha_block_beside_a_valid_approve_still_blocks() -> None:
    body = (marker("APPROVE") + "\n"
            '<!-- adversary-verdict:v1 {"verdict":"BLOCK","head":"b50521af22b1…"} -->')
    ready, warnings = gate(body)
    assert not ready, "a BLOCK typed with an ellipsis must not pass"
    assert warnings == ["adversary-malformed"], warnings


def test_a_block_inside_a_broken_fence_still_blocks() -> None:
    # R3b: _strip_code can over-strip on an unterminated fence or a stray backtick pair, which used to
    # let a live BLOCK be hidden beside a live APPROVE. A BLOCK naming THIS head is now read from the
    # RAW body, so no strip bug can hide it.
    fence = chr(96) * 3
    for body in (marker("APPROVE") + "\n" + fence + "\n" + marker("BLOCK"),
                 marker("APPROVE") + "\n" + fence + "py" + fence + " is a span\n" + marker("BLOCK"),
                 marker("APPROVE") + "\n    " + fence + "\n" + marker("BLOCK")):
        r = adv(body)
        assert r["verdict"] == "BLOCK" and r["matches_head"], body
        assert not passes(body)


def test_a_block_in_a_clean_fence_is_still_read_from_the_raw_body() -> None:
    # The asymmetry: an APPROVE must be live, a BLOCK counts wherever it names this head.
    fence = chr(96) * 3
    body = marker("APPROVE") + "\n" + fence + "\n" + marker("BLOCK") + "\n" + fence
    assert adv(body)["verdict"] == "BLOCK"


# ---- adversary review of 4a56c01 (2026-10-27): B1-B6 ------------------------------------------
#
# The blocker: `_strip_code` toggled on every line whose `lstrip()` began with ``` or ~~~, so an ODD
# number of fence-looking lines left `in_fence` true to the end of the body and blanked a live marker.
# Paired with a raw-body rescue that took only a FULL 40-hex sha, that hid a BLOCK typed with a
# shortened sha beside a valid APPROVE: `merge_ready: true`, reproduced through `main()` with
# `--adversary-required` as well. Two independent fixes, because either alone leaves the class open:
# the raw-body pass takes a shortened sha by PREFIX (so no strip bug can lose a BLOCK), and
# `_strip_code` follows CommonMark (so the class stops arising). Pinned at each layer.

TICK = chr(96)
FENCE3 = TICK * 3


def strip(body: str) -> str:
    return load_module()._strip_code(body)


def test_strip_a_fence_opens_only_at_an_indent_of_three_spaces_or_less() -> None:
    # B1c: `line.lstrip()` treated a 4-space-indented fence line as a fence; CommonMark does not.
    for spaces in (0, 1, 2, 3):
        body = " " * spaces + FENCE3 + "\nSECRET\n" + " " * spaces + FENCE3
        assert "SECRET" not in strip(body), f"{spaces} spaces"
    for spaces in (4, 5):
        body = " " * spaces + FENCE3 + "\nSECRET\n"
        assert "SECRET" in strip(body), f"{spaces} spaces"
    assert "SECRET" in strip("\t" + FENCE3 + "\nSECRET\n"), "a tab expands to four spaces"


def test_strip_a_fence_remembers_its_character_and_length() -> None:
    four = TICK * 4
    # B1a: an inner 3-backtick line does not close a 4-backtick fence.
    assert "SECRET" not in strip(four + "md\n" + FENCE3 + "sh\nSECRET\n" + four + "\nAFTER\n")
    # B1b: a ``` line does not close a ~~~ fence.
    assert "SECRET" not in strip("~~~md\n" + FENCE3 + "\nSECRET\n~~~\nAFTER\n")
    # A LONGER closing fence does close it.
    assert "SECRET" not in strip(four + "\nSECRET\n" + TICK * 5 + "\nAFTER\n")
    assert "AFTER" in strip(four + "\nSECRET\n" + TICK * 5 + "\nAFTER\n")


def test_strip_a_fence_line_may_carry_an_info_string_but_a_closing_fence_must_be_bare() -> None:
    assert "SECRET" not in strip(FENCE3 + "sh\nSECRET\n" + FENCE3)
    body = FENCE3 + "md\n" + FENCE3 + " trailing\nSECRET\n" + FENCE3 + "\nAFTER\n"
    assert "SECRET" not in strip(body) and "AFTER" in strip(body)


def test_strip_an_unterminated_fence_runs_to_the_end_of_the_body() -> None:
    # B1e: CommonMark agrees (everything after a fence with no closer is code), which is exactly why
    # the raw-body pass, not the stripper, is the guarantee for a BLOCK.
    assert "SECRET" not in strip(FENCE3 + "md\nSECRET\n")


def test_strip_an_inline_span_does_not_cross_a_line() -> None:
    # B1d: the `` … `` regex used DOTALL, so a span crossed lines and swallowed the marker after it. A
    # span cannot cross the HTML block that `<!--` starts.
    body = "use ``x here\nand `` there\n" + marker("BLOCK")
    assert marker("BLOCK") in strip(body)


def test_head_matches_takes_a_full_sha_and_any_shortened_prefix_of_this_head() -> None:
    m = load_module()
    for sha in (ADV_HEAD, ADV_HEAD.upper(), ADV_HEAD[:7], ADV_HEAD[:12],
                ADV_HEAD[:12] + "\u2026", ADV_HEAD[:12] + "...", " " + ADV_HEAD[:12] + " "):
        assert m._head_matches(sha, ADV_HEAD), sha


def test_head_matches_rejects_another_commit_a_placeholder_and_a_non_prefix() -> None:
    m = load_module()
    other = "b" * 40
    for sha in (other, other[:12] + "\u2026", "<40-hex>", "<sha>", "\u2026", "...",
                ADV_HEAD[:6], ADV_HEAD + "0", None, 42, ""):
        assert not m._head_matches(sha, ADV_HEAD), sha


def test_b1_an_ordinary_markdown_structure_cannot_hide_a_shortened_block() -> None:
    # B1a-B1c and B1e, each reproduced at 4a56c01 as merge_ready: true. A BLOCK naming this head by a
    # SHORTENED sha must survive every one of them, because it is read from the raw body.
    short = marker("BLOCK", ADV_HEAD[:12] + "\u2026")
    shapes = {
        "indented fence line (B1c)": "    " + FENCE3 + "\n",
        "four-backtick fence, odd inner (B1a)": TICK * 4 + "md\n" + FENCE3 + "sh\n" + TICK * 4 + "\n",
        "tilde fence holding a backtick line (B1b)": "~~~md\n" + FENCE3 + "sh\n~~~\n",
        "unterminated fence (B1e)": FENCE3 + "md\n",
    }
    for label, structure in shapes.items():
        body = marker("APPROVE") + "\n\n" + structure + "\n" + short
        r = adv(body)
        assert r["verdict"] == "BLOCK" and r["matches_head"], (label, r)
        ready, warnings = gate(body)
        assert not ready and warnings == ["adversary-stale-or-blocked"], (label, warnings)
        # Report-only by default is the DESIGN, so the gate must still report the BLOCK.
        assert gate(body, required=False)[1] == ["adversary-stale-or-blocked"], label


def test_b1_a_shortened_block_is_read_as_a_block_not_as_malformed() -> None:
    short = marker("BLOCK", ADV_HEAD[:12] + "\u2026")
    alone = adv(short)
    assert alone["verdict"] == "BLOCK" and not alone["malformed"] and not alone["conflict"]
    assert "shortened sha" in alone["detail"] and "raw body" in alone["detail"]
    beside = adv(marker("APPROVE") + "\n\n" + short)
    assert beside["verdict"] == "BLOCK" and beside["conflict"]


def test_b1_the_two_shapes_that_stayed_malformed_still_block() -> None:
    # The two shapes the review listed that did NOT reach merge_ready at 4a56c01: the shortened BLOCK
    # survived long enough to be read as malformed, and malformed always blocks. Pin that too, now
    # that the stripper no longer over-strips them.
    short = marker("BLOCK", ADV_HEAD[:12] + "\u2026")
    for label, structure in {
        "stray double backtick (B1d)": "use ``x here\nand `` there\n\n",
        "balanced four-backtick fence": TICK * 4 + "md\n" + FENCE3 + "sh\necho\n" + FENCE3 + "\n" + TICK * 4 + "\n\n",
    }.items():
        body = marker("APPROVE") + "\n\n" + structure + short
        assert adv(body)["verdict"] == "BLOCK", label
        ready, warnings = gate(body)
        assert not ready, label


def test_a_near_miss_spelling_beside_a_valid_approve_is_malformed_not_ignored() -> None:
    # B2: a `:`-anchored start regex missed `adversary-verdict {...}` and `adversary_verdict:v1 ...`,
    # so a typo'd BLOCK beside a valid APPROVE read as approved and merge-ready.
    for start in ("adversary-verdict", "adversary_verdict:v1", "Adversary-Verdict:v1",
                  "adversary verdict:v1"):
        body = (marker("APPROVE") + "\n<!-- " + start
                + ' {"verdict":"BLOCK","head":"' + ADV_HEAD + '"} -->')
        assert adv(body)["malformed"], start
        ready, warnings = gate(body)
        assert not ready and warnings == ["adversary-malformed"], (start, warnings)


def test_a_near_miss_spelling_names_the_wrong_spelling_not_an_unclosed_comment() -> None:
    # B3: every unparseable start was reported as "no closing -->", which defeats "a typo reads as a
    # typo" - the two mistakes are different.
    wrong = adv('<!-- adversary-verdict:v2 {"verdict":"APPROVE","head":"' + ADV_HEAD + '"} -->')
    assert wrong["malformed"] and "no closing" not in wrong["detail"]
    assert "exact, lowercase" in wrong["detail"]
    unclosed = adv('<!-- adversary-verdict:v1 {"verdict":"APPROVE","head":"' + ADV_HEAD + '"')
    assert unclosed["malformed"] and "no closing" in unclosed["detail"]
    assert "exact, lowercase" not in unclosed["detail"]



# ---- the bundled adversary review of 66/67: C1-C5 ---------------------------------------------
#
# Two of three re-reviewers found the SAME class again: the raw-body/strip interaction still failed
# open, and every finding below reached `merge_ready: true` from a body that merely QUOTED a marker
# or mistyped one. Each fix is pinned through `adv()` and, where the failure was reached through
# `assess()`, through the real gate: a property that holds only inside `adversary_verdict` is not the
# property the gate promises.

def test_c1_an_unclosed_marker_start_quoted_in_code_cannot_swallow_a_block() -> None:
    # MARKER_RE was non-greedy but unbounded, so the unclosed start below ran to the NEXT `-->` - the
    # fenced BLOCK's own - and the JSON parse failed, `continue` skipped it, `findall` resumed AFTER
    # the BLOCK, and the body read as a live APPROVE with the full sha. PR 67's subject is exactly
    # this kind of quoting, so the doc-writing PR could approve itself.
    body = (marker("APPROVE") + "\nEvery marker begins `<!-- adversary-verdict:v1`.\n"
            + FENCE3 + "\n" + marker("BLOCK") + "\n" + FENCE3 + "\n")
    r = adv(body)
    assert r["verdict"] == "BLOCK" and r["matches_head"] and r["conflict"], r
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-stale-or-blocked"], warnings


def test_c1_an_unclosed_start_in_plain_prose_blocks_and_is_reported_malformed() -> None:
    # The same shape without backticks: the BLOCK must survive, and the stray start is a typo that is
    # REPORTED as well - "a BLOCK beside a typo" is not the same body as "a BLOCK".
    body = (marker("APPROVE") + "\nEvery marker begins <!-- adversary-verdict:v1\n"
            + FENCE3 + "\n" + marker("BLOCK") + "\n" + FENCE3 + "\n")
    r = adv(body)
    assert r["verdict"] == "BLOCK" and r["matches_head"] and r["malformed"], r
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-malformed"], warnings


def test_c2_a_double_backtick_span_holding_one_backtick_is_still_code() -> None:
    # CommonMark 6.1: a span opens with n backticks and closes at the next run of EXACTLY n, so
    # ``literal `<marker>` `` is ONE span. The old pair of fixed regexes could not see it, matched from
    # the INNER backtick, and left the marker live: a quoted APPROVE read as a real one.
    body = "``literal `" + marker("APPROVE") + "``\n"
    assert not adv(body)["present"]
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-missing"], warnings
    # Outside the span the same marker is a verdict, so the fix is the span and not a blanket refusal.
    assert passes(body + "\n" + marker("APPROVE"))


def test_c2_the_strip_never_repairs_invalid_json_into_a_different_marker() -> None:
    # Spans used to be replaced with "" - DELETION concatenates the text on either side, so an author's
    # typo could be closed up into valid JSON that was never written. Every replacement is now a run of
    # spaces of the same width.
    broken = marker("APPROVE").replace('"} -->', '","unexpected"} -->')
    assert broken != marker("APPROVE")
    assert adv(broken)["malformed"], "the unquoted typo is a typo"
    quoted = "``literal `" + broken + "``"
    r = adv(quoted)
    assert not r["present"] and not r["malformed"], r


def test_c3_a_backtick_in_an_info_string_is_not_a_fence() -> None:
    # CommonMark 4.5: a backtick fence's info string may not contain a backtick. A line like ```a`b is
    # therefore INLINE CODE, not a fence - and treating it as one blanked the rest of the body, which
    # hid the malformed marker below and let the APPROVE read clean.
    body = (marker("APPROVE") + "\n" + FENCE3 + "a`b\n"
            + '<!-- adversary-verdict:v1 {"verdict":"APPROVE"}\n')
    r = adv(body)
    assert r["verdict"] == "APPROVE" and r["matches_head"] and r["malformed"], r
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-malformed"], warnings


def test_c4_a_full_sha_with_a_trailing_ellipsis_is_a_block_not_a_typo() -> None:
    # The property is documented as "full 40-hex, OR a 7+ hex prefix with or without a trailing …".
    # `[0-9a-f]{7,39}` could not match a full sha carrying an ellipsis, so a legitimate BLOCK read as
    # malformed: report-only by default, which means it silently stopped blocking in the opt-in case
    # that matters. At equal length `startswith` is equality, so the cap can go to 40 safely.
    for tail in ("\u2026", "..."):
        r = adv(marker("BLOCK", ADV_HEAD + tail))
        assert r["verdict"] == "BLOCK" and not r["malformed"] and r["matches_head"], (tail, r)
        ready, warnings = gate(marker("BLOCK", ADV_HEAD + tail))
        assert not ready and warnings == ["adversary-stale-or-blocked"], (tail, warnings)
    # Widening the cap must not make another commit match. An ellipsized sha of a DIFFERENT commit is
    # not a prefix of this head, so it does not match; it also is not 40-hex, so it stays a malformed
    # head rather than a stale verdict - the fail-closed direction, unchanged here.
    other = adv(marker("BLOCK", OTHER_HEAD + "\u2026"))
    assert not other["matches_head"] and other["malformed"], other


def test_c5_a_raw_body_block_cannot_report_a_clean_verdict_beside_a_live_typo() -> None:
    # The raw-body rescue returned `malformed: False` unconditionally, so a BLOCK beside a LIVE
    # malformed marker reported a clean block: the typo vanished from the summary and the body looked
    # like one assertable verdict. Validation now runs first and the rescue carries its result.
    body = ('<!-- adversary-verdict:v2 {"verdict":"APPROVE","head":"' + ADV_HEAD + '"} -->\n'
            + marker("BLOCK"))
    r = adv(body)
    assert r["verdict"] == "BLOCK" and r["matches_head"] and r["malformed"], r
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-malformed"], warnings


def test_c5_a_shortened_block_beside_a_live_typo_is_malformed_too() -> None:
    # The shortened-sha rescue is the one that always said "clean", so it laundered a BLOCK beside a
    # typo. The prefix BLOCK is NOT itself a problem - it is the shape the rescue exists for - but the
    # broken marker beside it still reports.
    short = marker("BLOCK", ADV_HEAD[:12] + "\u2026")
    body = '<!-- adversary-verdict:v1 {broken -->\n' + short
    r = adv(body)
    assert r["verdict"] == "BLOCK" and r["malformed"], r
    assert "shortened sha" in r["detail"] and "raw body" in r["detail"]
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-malformed"], warnings


def test_strip_code_masks_with_spaces_and_never_changes_a_line() -> None:
    # The invariant every fail-open shape above depends on: stripping may only REPLACE characters with
    # spaces. A line's length never changes, no line is added or removed, and every surviving non-space
    # character is the original one at the same position - so no marker can be repaired into another.
    body = "\n".join([
        "plain text  ",
        "\tindented with a tab ",
        FENCE3 + "sh",
        "in the fence ",
        FENCE3,
        "a `span` and ``a `span` with a tick`` end",
        "    " + FENCE3 + " (four spaces: indented code, not a fence)",
        FENCE3 + "a`b (not a fence: a backtick in the info string)",
        "",
    ])
    src = body.splitlines()
    dst = load_module()._strip_code(body).splitlines()
    assert len(dst) == len(src)
    for line_in, line_out in zip(src, dst):
        assert len(line_in) == len(line_out), (line_in, line_out)
        for a, b in zip(line_in, line_out):
            assert b == " " or b == a, (line_in, line_out)
    assert dst[0] == src[0] and dst[1] == src[1], "live lines are untouched"
    assert not dst[2].strip() and not dst[3].strip() and not dst[4].strip(), "the fence is masked"
    assert "span" not in dst[5] and dst[5].startswith("a ") and dst[5].endswith(" end")
    assert dst[6] == src[6] and dst[7] == src[7], "neither line is a fence"


# ---- the lead's re-review of 6083bcb: C1' (regression) and C2' ---------------------------------
#
# C1 was fixed by TEMPERING the marker regex so it could not cross another `<!--`. That closed the
# prose-swallow and opened the mirror: the SAME regex drove the raw-body BLOCK rescue, and extra JSON
# fields are accepted (no schema check), so a BLOCK whose `note` quoted the delimiter became invisible
# to the rescue. A fail-open in the one direction this gate promises never to fail open. The boundary
# is now a JSON-aware scanner (`_marker_spans`), shared by the live path and the rescue, and BOTH
# directions are pinned here: the tempered capture survives as the FALLBACK, for starts whose JSON
# does not balance.

def _marker_with_note(verdict: str, note: str, head: str = ADV_HEAD) -> str:
    """A valid marker carrying an EXTRA field - which the gate accepts, by design."""
    return (f'<!-- adversary-verdict:v1 {{"verdict":"{verdict}","head":"{head}",'
            f'"note":"{note}"}} -->')


def test_c1_prime_a_fenced_block_that_quotes_the_delimiter_is_not_hidden() -> None:
    # At 6083bcb this body read as a clean APPROVE (parent 838413b read BLOCK): the fenced BLOCK's
    # `note` holds `<!--`, the tempered group stopped there, the JSON failed to parse, and the rescue
    # that exists to read a fenced BLOCK skipped it.
    body = (marker("APPROVE") + "\n" + FENCE3 + "\n"
            + _marker_with_note("BLOCK", "literal <!-- x") + "\n" + FENCE3 + "\n")
    r = adv(body)
    assert r["verdict"] == "BLOCK" and r["matches_head"] and r["conflict"], r
    assert not r["malformed"], r
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-stale-or-blocked"], warnings


def test_c1_prime_a_live_block_that_quotes_the_delimiter_is_a_block_not_a_typo() -> None:
    # Same body without the fence: the marker is LIVE, so the tempered group's truncation made valid
    # JSON look malformed (6083bcb: APPROVE + malformed). A delimiter inside a JSON string is CONTENT.
    body = marker("APPROVE") + "\n" + _marker_with_note("BLOCK", "literal <!-- x")
    r = adv(body)
    assert r["verdict"] == "BLOCK" and r["matches_head"] and r["conflict"], r
    assert not r["malformed"], r
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-stale-or-blocked"], warnings


def test_c1_prime_a_near_miss_start_that_quotes_the_delimiter_never_becomes_a_marker() -> None:
    # The scanner must not widen what COUNTS as a marker. A near-miss spelling is a start for
    # `_classify_starts` only, however valid its JSON, so it is reported as a typo and never parsed
    # into a verdict - a typo may not block, and it may not approve either.
    body = ('<!-- adversary-verdict {"verdict":"BLOCK","head":"' + ADV_HEAD
            + '","note":"literal <!-- x"} -->\n' + marker("APPROVE"))
    r = adv(body)
    assert r["verdict"] == "APPROVE" and r["matches_head"] and r["malformed"], r
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-malformed"], warnings


def test_c2_prime_masking_may_not_repair_json_at_a_structural_boundary() -> None:
    # PRE-EXISTING (the lead found it at both revisions), and still wrong: `_strip_code` replaces code
    # with SPACES, so a span sitting where JSON expects whitespace left the punctuation intact -
    # {"verdict":"APPROVE", `junk` "head":"…"} parsed as valid JSON nobody wrote, and read clean-
    # APPROVE. The live slice of the RAW body at the same offsets says what was actually written, so a
    # marker whose JSON differs between the two is `malformed`, never approved.
    body = ('<!-- adversary-verdict:v1 {"verdict":"APPROVE", `junk` "head":"' + ADV_HEAD + '"} -->')
    r = adv(body)
    assert not r["present"] and r["malformed"], r
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-malformed"], warnings
    # Outside code the same JSON is a real verdict: the fix is the repair, not a blanket refusal.
    assert passes(body.replace("`junk`", ""))


def test_strip_code_preserves_every_offset_including_crlf_and_a_trailing_newline() -> None:
    # The C2' check compares slices by INDEX, so `_strip_code` may not change the length by one byte.
    # `splitlines()` dropped a trailing newline and rewrote `\r\n` as `\n`, shifting every offset
    # after the first such line - which turned a clean APPROVE on a CRLF body into `malformed`.
    strip = load_module()._strip_code
    for body in ("text `span` and " + marker("APPROVE") + "\n",
                 "text `span`\r\n\r\n" + marker("APPROVE") + "\r\n",
                 "trailing\n\n",
                 ""):
        out = strip(body)
        assert len(out) == len(body), (body, out)
        # Same line structure: every line terminator survives byte for byte.
        assert out[len(out.rstrip("\r\n")):] == body[len(body.rstrip("\r\n")):], (body, out)
    crlf = "Intro\r\n\r\n" + marker("APPROVE") + "\r\n"
    assert strip(crlf).endswith("\r\n") and len(strip(crlf)) == len(crlf)
    r = adv(crlf)
    assert r["verdict"] == "APPROVE" and r["matches_head"] and not r["malformed"], r


def test_c1_prime_a_note_that_documents_the_marker_is_content_not_a_second_start() -> None:
    # The JSON-aware scanner accepts the WHOLE marker, so a `note` quoting the format is inside that
    # marker's JSON. Counting the quoted start as a second start made a CORRECT body `malformed`, which
    # is the same fail-closed-but-wrong direction as C1 in the other guise. `_classify_starts` skips a
    # start inside an accepted marker, and the scanner resumes after that marker's `-->`.
    quoted_start = 'see <!-- adversary-verdict:v1 in the docs'
    r = adv(_marker_with_note("APPROVE", quoted_start))
    assert r["verdict"] == "APPROVE" and r["matches_head"], r
    assert not r["malformed"], r
    # The same shape with a WHOLE marker nested in the note, escaped as JSON requires.
    nested = json.dumps({"verdict": "APPROVE", "head": ADV_HEAD})
    note = "like <!-- adversary-verdict:v1 " + nested + " --> ok"
    body = ('<!-- adversary-verdict:v1 '
            + json.dumps({"verdict": "APPROVE", "head": ADV_HEAD, "note": note})
            + ' -->')
    r = adv(body)
    assert r["verdict"] == "APPROVE" and r["matches_head"] and not r["malformed"], r
    # And two REAL markers are still two: the skip must not spill past the accepted marker.
    assert adv(body + "\n" + marker("BLOCK"))["verdict"] == "BLOCK"


# ---- the lead's re-review of eb90d20: D1, a BLOCK nested in a REJECTED candidate ---------------
#
# `_marker_spans` accepts a candidate as soon as its braces balance and a `-->` follows - before
# anything validates that JSON - and then sets `consumed` past it. The LIVE path wants exactly that
# (an accepted marker's interior is content). The raw-body BLOCK rescue iterated the SAME spans, so
# when the outer candidate's JSON was junk the rescue `continue`d and never revisited a real
# same-head BLOCK that had started inside the region: `verdict=APPROVE, conflict=False,
# malformed=False`. Two reviewers reached it independently, from two shapes, and both read a clean
# false APPROVE at eb90d20 while 6083bcb read BLOCK: the same fail-open class as C1' in a new guise.
#
# The fix is scoped to the rescue: `_marker_spans(..., nested=True)` drops the cursor so every start
# is scanned on its own. The boundary rules are unchanged, and no false BLOCK arrives - a marker
# quoted inside a `note` is ESCAPED in the body, so its slice cannot parse, and an unescaped quote
# inside a JSON string cannot exist in valid JSON.

def test_d1_a_fenced_block_nested_in_an_invalid_outer_candidate_is_still_a_block() -> None:
    # Reproducer A (codex): the outer `{"note":` candidate's braces balance OVER the inner marker, so
    # it was accepted and `consumed` skipped the BLOCK; its own JSON does not parse, so the rescue
    # skipped the span and found nothing. At eb90d20: APPROVE / conflict False / malformed False.
    body = (marker("APPROVE") + "\n" + FENCE3 + "\n"
            + '<!-- adversary-verdict:v1 {"note":\n'
            + marker("BLOCK") + "\n"
            + '} -->\n' + FENCE3 + "\n")
    r = adv(body)
    assert r["verdict"] == "BLOCK" and r["matches_head"] and r["conflict"], r
    # Round-6 fail-closed recovery retains the invalid outer candidate diagnostic.
    assert r["malformed"], r
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-malformed"], warnings


def test_d1_quote_parity_across_the_scan_cannot_swallow_a_block() -> None:
    # Reproducer B (claude): prose quotes an unclosed start whose opening quote runs on into the
    # fenced marker below, so the candidate's slice spans a literal newline inside a JSON string -
    # invalid JSON, accepted span, consumed, BLOCK gone. Same false APPROVE at eb90d20.
    body = (marker("APPROVE") + "\n"
            + 'A marker begins `<!-- adversary-verdict:v1 {"verdict":"` and so on.\n\n'
            + FENCE3 + "\n"
            + _marker_with_note("BLOCK", 'the \\"never\\" filter') + "\n" + FENCE3 + "\n")
    r = adv(body)
    assert r["verdict"] == "BLOCK" and r["matches_head"] and r["conflict"], r
    assert not r["malformed"], r
    ready, warnings = gate(body)
    assert not ready and warnings == ["adversary-stale-or-blocked"], warnings


def test_d1_the_rescue_reports_a_nested_start_and_the_live_scan_still_skips_it() -> None:
    # The mechanism, pinned at both layers: the same body yields one span to the live scan (the outer
    # APPROVE, whose interior is content) and two to the rescue. If the live scan ever reports the
    # nested start too, a `note` documenting the format becomes `malformed`; if the rescue ever skips
    # it again, D1 is back.
    mod = load_module()
    outer = ('<!-- adversary-verdict:v1 {"verdict":"APPROVE","head":"' + ADV_HEAD
             + '","note":"see:\n' + '<!-- adversary-verdict:v1 {"verdict":"BLOCK","head":"'
             + ADV_HEAD + '"} -->"}\n-->')
    body = outer  # the note holds an UNESCAPED start: the outer JSON is therefore junk
    assert len(mod._marker_spans(body)) == 1, mod._marker_spans(body)
    assert len(mod._marker_spans(body, nested=True)) == 2, mod._marker_spans(body, nested=True)


def test_d1_an_escaped_nested_marker_is_still_not_a_second_verdict() -> None:
    # The other direction: the cursor was dropped only in the rescue, and a marker quoted inside a
    # VALID `note` is escaped, so its slice cannot parse as JSON and cannot become a BLOCK. Without
    # this, every APPROVE documenting the format would come back as a conflict with itself.
    nested = json.dumps({"verdict": "BLOCK", "head": ADV_HEAD})
    note = "like <!-- adversary-verdict:v1 " + nested + " --> ok"
    body = ('<!-- adversary-verdict:v1 '
            + json.dumps({"verdict": "APPROVE", "head": ADV_HEAD, "note": note}) + ' -->')
    r = adv(body)
    assert r["verdict"] == "APPROVE" and r["matches_head"], r
    assert not r["conflict"] and not r["malformed"], r
    assert passes(body)



def test_approve_note_backticks_are_json_content():
    body = '<!-- adversary-verdict:v1 ' + json.dumps({"verdict": "APPROVE", "head": ADV_HEAD, "note": "fixed `x`"}) + ' -->'
    assert adv(body)["malformed"] is False
    assert gate(body)[0] is True


@pytest.mark.parametrize("broken", [
    marker("BLOCK").replace('} -->', '} round2 -->'),
    marker("BLOCK").replace('{', '{"head":"' + ADV_HEAD + '",'),
    marker("BLOCK").replace(ADV_HEAD, 'sha ' + ADV_HEAD),
    marker("BLOCK").replace(':v1', ':V1'),
    marker("BLOCK").replace(':v1', ': v1'),
    marker("BLOCK").replace('BLOCK', 'block'),
    marker("BLOCK").replace(ADV_HEAD, ADV_HEAD[:6]),
])
def test_typo_block_in_code_cannot_hide(broken):
    body = marker("APPROVE") + '\n```\n' + broken + '\n```'
    assert adv(body)["verdict"] == "BLOCK"
    assert adv(body)["malformed"] is True
    assert gate(body, required=False)[0] is False



@pytest.mark.parametrize("old_head", ["1234567", "1234567" * 5 + "12345"])
def test_fenced_other_head_block_note_cannot_name_current_head(old_head):
    # Adversary c4: only the head field identifies the reviewed revision.
    doc = {"verdict": "BLOCK", "head": old_head, "note": "fixed in " + ADV_HEAD[:7]}
    body = marker("APPROVE") + "\n```\n<!-- adversary-verdict:v1 " + json.dumps(doc) + " -->\n```"
    result = adv(body)
    assert result["verdict"] == "APPROVE" and not result["malformed"]
    assert gate(body)[0] is True


def test_doubled_start_cannot_hide_same_head_block():
    broken = '<!-- adversary-verdict:v1 <!-- ' + json.dumps({"verdict": "BLOCK", "head": ADV_HEAD}) + ' -->'
    body = marker("APPROVE") + "\n```\n" + broken + "\n```"
    result = adv(body)
    assert result["verdict"] == "BLOCK" and result["malformed"]
    assert gate(body, required=False)[0] is False


@pytest.mark.parametrize("values", [(ADV_HEAD, OTHER_HEAD), (OTHER_HEAD, ADV_HEAD)])
def test_duplicate_head_fields_cannot_hide_current_head(values):
    payload = '{"verdict":"BLOCK","head":"' + values[0] + '","head":"' + values[1] + '"}'
    body = marker("APPROVE") + "\n```\n<!-- adversary-verdict:v1 " + payload + " -->\n```"
    assert adv(body)["verdict"] == "BLOCK"
    assert gate(body, required=False)[0] is False


@pytest.mark.parametrize("start", ["<!-- adversary-verdict:v1 -->", "<!-- adversary-verdict:V1 -->"])
def test_closed_marker_cannot_borrow_standalone_block_json(start):
    unrelated = json.dumps({"verdict": "BLOCK", "head": ADV_HEAD})
    body = marker("APPROVE") + "\n```\n" + start + "\n" + unrelated + "\n```"
    result = adv(body)
    assert result["verdict"] == "APPROVE" and not result["malformed"]
    assert gate(body, required=False)[0] is True


def test_closed_marker_does_not_hide_a_separate_same_head_block():
    body = marker("APPROVE") + "\n```\n<!-- adversary-verdict:v1 -->\n" + marker("BLOCK") + "\n```"
    result = adv(body)
    assert result["verdict"] == "BLOCK" and result["matches_head"] and result["conflict"]
    assert gate(body)[0] is False


@pytest.mark.parametrize("verdict", ["APPROVE", "BLOCK"])
def test_marker_start_in_json_string_cannot_borrow_metadata_object(verdict):
    doc = {"verdict": verdict, "head": ADV_HEAD,
           "note": "format: <!-- adversary-verdict:v1",
           "example": {"verdict": "BLOCK", "head": ADV_HEAD}}
    result = adv('<!-- adversary-verdict:v1 ' + json.dumps(doc) + ' -->')
    assert result["verdict"] == verdict
    assert result["malformed"] is False


def test_quoted_marker_start_does_not_hide_real_block_after_valid_marker():
    doc = {"verdict": "APPROVE", "head": ADV_HEAD,
           "note": "format: <!-- adversary-verdict:v1",
           "example": {"verdict": "BLOCK", "head": ADV_HEAD}}
    body = '<!-- adversary-verdict:v1 ' + json.dumps(doc) + ' -->\n' + marker("BLOCK")
    assert adv(body)["verdict"] == "BLOCK"
    assert gate(body)[0] is False


@pytest.mark.parametrize("shape", ["object", "array", "string", "pairs_array", "root_array"])
@pytest.mark.parametrize("field", ["head", "verdict"])
@pytest.mark.parametrize("malformed", [False, True])
@pytest.mark.parametrize("context", ["live", "fenced", "inline"])
def test_nested_fields_never_supply_a_marker_verdict(shape, field, malformed, context):
    nested = {"verdict": "BLOCK", "head": ADV_HEAD}
    extra = {"object": nested, "array": [nested], "string": json.dumps(nested),
             "pairs_array": list(nested.items()), "root_array": [nested]}[shape]
    doc = {"verdict": "BLOCK" if field == "head" else "APPROVE",
           "head": OTHER_HEAD if field == "head" else ADV_HEAD, "example": extra}
    payload = json.dumps(extra if shape == "root_array" else doc)
    if malformed:
        payload = payload[:-1] + "," + payload[-1]
    candidate = '<!-- adversary-verdict:v1 ' + payload + ' -->'
    if context == "fenced": candidate = "\n```\n" + candidate + "\n```"
    elif context == "inline": candidate = "\n`" + candidate + "`"
    body = marker("APPROVE") + "\n" + candidate
    result = adv(body)
    if context == "live" and (malformed or shape == "root_array"):
        assert result["malformed"] and not gate(body, required=False)[0]
    else:
        assert result["verdict"] == "APPROVE" and not result["malformed"]
        assert gate(body, required=False)[0]


@pytest.mark.parametrize("shape", ["object", "array", "string", "pairs_array"])
@pytest.mark.parametrize("field", ["head", "verdict"])
@pytest.mark.parametrize("malformed", [False, True])
@pytest.mark.parametrize("context", ["live", "fenced", "inline"])
def test_structured_marker_field_values_are_never_promoted(shape, field, malformed, context):
    nested = {"verdict": "BLOCK", "head": ADV_HEAD}
    value = {"object": nested, "array": [nested], "string": json.dumps(nested),
             "pairs_array": list(nested.items())}[shape]
    doc = {"verdict": "BLOCK", "head": ADV_HEAD, field: value}
    payload = json.dumps(doc)
    if malformed: payload = payload[:-1] + ",}"
    candidate = '<!-- adversary-verdict:v1 ' + payload + ' -->'
    if context == "fenced": candidate = "\n```\n" + candidate + "\n```"
    elif context == "inline": candidate = "\n`" + candidate + "`"
    body = marker("APPROVE") + "\n" + candidate
    result = adv(body)
    if context == "live":
        assert result["malformed"] and not gate(body, required=False)[0]
    else:
        assert result["verdict"] == "APPROVE" and not result["malformed"]
        assert gate(body, required=False)[0]


@pytest.mark.parametrize("payload", [
    '{"verdict":"BLOCK","head":"H\n"}',

    'see <!-- {"verdict":"BLOCK","head":"H"}',
    '{"verdict":"BLOCK","head":"H","note":"<!--", oops}',
    '{"verdict":"BLOCK","head":"H","note":"see <!-- x",}',
    '{"note":"5" <!--","verdict":"BLOCK","head":"H"}',
    '{"verdict":"BLOCK","head":"H","note":"format: <!-- adversary-verdict:v1 {...} -->",}',
    '{"verdict":"BLOCK","head":"H","note":"format: <!-- adversary-verdict:v1 {...}",}',
    '{"Verdict":"BLOCK","head":"H",}',
    '{"note":"5" x","verdict":"\\u0042LOCK","head":"H"}',

    '{"note":"5" screen","verdict":"BLOCK","head":"H"}',
    '{"verdict":"BLOCK","note":"5" screen","head":"H"}',
    '[r5] {"verdict":"BLOCK","head":"H"}',
    '5" {"verdict":"BLOCK","head":"H"}',
    '{"verdict":"BLOCK","x":[1,"head":"H"}',
    '{"note":"a\\","verdict":"BLOCK","head":"H"}',
    '{"verdict":"APPROVE","head":"O","n":"<!-- adversary-verdict:v1"} {"verdict":"BLOCK","head":"H"}',
    '{"verdict":"APPROVE","head":"H","note":"format: <!-- adversary-verdict:v1", BROKEN {"verdict":"BLOCK","head":"H"}}',
])
@pytest.mark.parametrize("context", ["fenced", "inline", "unclosed"])
def test_uncertain_structure_cannot_hide_same_head_block(payload, context):
    payload = payload.replace('"H"', json.dumps(ADV_HEAD)).replace('H\n', ADV_HEAD + '\n').replace('"O"', json.dumps(OTHER_HEAD))
    candidate = '<!-- adversary-verdict:v1 ' + payload + ' -->'
    wrappers = {"fenced": "\n```\n%s\n```", "inline": "\n`%s`", "unclosed": "\n```\n%s"}
    body = marker("APPROVE") + wrappers[context] % candidate
    result = adv(body)
    assert result["verdict"] == "BLOCK" and result["malformed"]
    assert not gate(body, required=False)[0]
    assert not gate(body, required=True)[0]


def test_valid_approve_history_cannot_supply_fallback_block():
    payload = {"verdict": "APPROVE", "head": ADV_HEAD,
               "history": [{"verdict": "BLOCK", "head": ADV_HEAD}]}
    body = '<!-- adversary-verdict:v1 ' + json.dumps(payload) + ' -->'
    result = adv(body)
    assert result["verdict"] == "APPROVE" and not result["malformed"]
    assert gate(body, required=True)[0]


def test_many_empty_marker_starts_do_not_rescan_remaining_body(monkeypatch):
    # Count scanner input, not wall time: repeated suffix scans are quadratic.
    module = load_module().__dict__
    original = module["_marker_tokens"]
    scanned = []
    def counted(text):
        scanned.append(len(text))
        yield from original(text)
    monkeypatch.setitem(module, "_marker_tokens", counted)
    body = marker("APPROVE") + "\n" + '<!-- adversary-verdict:v1 x ' * 2000
    module["adversary_verdict"](body, ADV_HEAD)
    assert sum(scanned) <= 4 * len(body)


@pytest.mark.parametrize("note", ["<!--", "-->", "<!-- adversary-verdict:v1", "quote \" and [ ] <!-- -->"])
@pytest.mark.parametrize("trailing_comma", [False, True])
@pytest.mark.parametrize("context", ["fenced", "inline"])
def test_root_array_comment_delimiters_remain_documentation(note, trailing_comma, context):
    payload = json.dumps([{"note": note, "verdict": "BLOCK", "head": ADV_HEAD}])
    if trailing_comma:
        payload = payload[:-1] + ",]"
    example = '<!-- adversary-verdict:v1 ' + payload + ' -->'
    code = "\n```\n" + example + "\n```" if context == "fenced" else "\n`" + example + "`"
    body = marker("APPROVE") + code
    assert adv(body)["verdict"] == "APPROVE" and not adv(body)["malformed"]
    assert gate(body, required=False)[0] and gate(body, required=True)[0]


def test_root_array_documentation_does_not_hide_following_block():
    example = '<!-- adversary-verdict:v1 ' + json.dumps([{"note": "<!-- -->", "head": ADV_HEAD, "verdict": "BLOCK"}]) + ' -->'
    body = marker("APPROVE") + "\n```\n" + example + "\n" + marker("BLOCK") + "\n```"
    assert adv(body)["verdict"] == "BLOCK" and not gate(body)[0]


@pytest.mark.parametrize("context", ["fenced", "inline", "live", "blockquote", "indented"])
@pytest.mark.parametrize("shape", ["trailing_comma", "quoted_marker", "nested_metadata", "quote_desync", "escaped_strings"])
@pytest.mark.parametrize("verdict,head", [("APPROVE", ADV_HEAD), ("BLOCK", ADV_HEAD), ("BLOCK", OTHER_HEAD)])
def test_marker_family_matrix(context, shape, verdict, head):
    doc = {"verdict": verdict, "head": head, "note": "escaped \" \\ [ ]"}
    if shape == "quoted_marker":
        doc["note"] = "format: <!-- adversary-verdict:v1"
    if shape in ("quoted_marker", "nested_metadata"):
        doc["example"] = {"verdict": "BLOCK", "head": ADV_HEAD}
    payload = json.dumps(doc)
    if shape in ("trailing_comma", "quoted_marker", "nested_metadata"):
        payload = payload[:-1] + ",}"
    if shape == "quote_desync":
        payload = '{"note":"5" screen",' + payload[1:]
    candidate = '<!-- adversary-verdict:v1 ' + payload + ' -->'
    candidate = {"fenced": "\n```\n%s\n```", "inline": "\n`%s`", "live": "\n%s",
                 "blockquote": "\n> ```\n> %s\n> ```", "indented": "\n    %s"}[context] % candidate
    body = marker("APPROVE") + candidate
    result = adv(body)
    live = context in ("live", "blockquote", "indented")
    malformed = shape != "escaped_strings"
    if verdict == "BLOCK" and head == ADV_HEAD:
        assert result["verdict"] == "BLOCK" and result["matches_head"]
        assert not gate(body, required=True)[0]
        if malformed:
            assert not gate(body, required=False)[0]
    elif (live and malformed) or shape == "quoted_marker":
        # Accepted fail-closed limit: trailing-comma note start can borrow metadata.
        assert result["malformed"] and not gate(body, required=False)[0]
    else:
        assert result["verdict"] == "APPROVE" and not result["malformed"]
        assert gate(body, required=True)[0]


def test_documentation_only_matrix_cannot_forge_approve():
    for context in ("\n```\n%s\n```", "\n`%s`"):
        body = context % marker("APPROVE")
        assert not gate(body, required=True)[0]


_MATRIX_CONTEXTS = {"fenced": "\n```\n%s\n```", "inline": "\n`%s`", "live": "\n%s",
                    "blockquote": "\n> ```\n> %s\n> ```", "indented": "\n    %s",
                    "tilde": "\n~~~\n%s\n~~~", "four_ticks": "\n````\n%s\n````",
                    "unclosed_fence": "\n```\n%s", "broken_inline": "\n`\n%s\n`"}
_MATRIX_HEADS = [("APPROVE", ADV_HEAD), ("BLOCK", ADV_HEAD), ("BLOCK", OTHER_HEAD),
                 ("BLOCK", ADV_HEAD[:7]), ("BLOCK", ADV_HEAD[:9] + "…"),
                 ("BLOCK", ADV_HEAD[:9] + "..."), ("APPROVE", ADV_HEAD[:7]),
                 ("BLOCK", OTHER_HEAD[:7]), ("APPROVE", "<40-hex>"), ("BLOCK", "<40-hex>")]


@pytest.mark.parametrize("context", _MATRIX_CONTEXTS)
@pytest.mark.parametrize("shape", ["valid", "trailing_comma", "quoted_marker", "nested_metadata", "quote_desync",
                                   "escaped_strings", "escaped_keys", "root_array", "near_miss", "unclosed_start",
                                   "backtick_inside", "backtick_outside"])
@pytest.mark.parametrize("verdict,head", _MATRIX_HEADS)
@pytest.mark.parametrize("position", ["before", "after"])
def test_complete_marker_safety_matrix(context, shape, verdict, head, position):
    doc = {"verdict": verdict, "head": head}
    if shape == "quoted_marker":
        doc.update(note="format: <!-- adversary-verdict:v1", example={"verdict": "BLOCK", "head": ADV_HEAD})
    elif shape == "nested_metadata":
        doc["example"] = {"verdict": "BLOCK", "head": ADV_HEAD}
    elif shape == "escaped_strings":
        doc["note"] = 'quote " slash \\ [ ]'
    elif shape == "backtick_inside":
        doc["note"] = "a `quoted` word"
    payload = json.dumps([doc] if shape == "root_array" else doc)
    if shape in ("trailing_comma", "quoted_marker"):
        payload = payload[:-1] + ",}"
    if shape == "quote_desync":
        payload = '{"note":"5" screen",' + payload[1:]
    if shape == "escaped_keys":
        payload = payload.replace('"verdict"', '"\\u0076erdict"').replace('"head"', '"\\u0068ead"')
    if shape == "backtick_outside":
        payload = payload[:-1] + "`}"  # never repair invalid raw JSON by stripping code
    start = "<!-- adversary-verdict:V1 " if shape == "near_miss" else "<!-- adversary-verdict:v1 "
    candidate = start + payload + ("" if shape == "unclosed_start" else " -->")
    wrapped = _MATRIX_CONTEXTS[context] % candidate
    # Keep the baseline live even for an unterminated candidate fence.
    before = wrapped + ("\n```" if context == "unclosed_fence" else "") + "\n" + marker("APPROVE")
    body = before if position == "before" else marker("APPROVE") + wrapped
    result = adv(body)
    live = context in ("live", "blockquote", "indented", "broken_inline")
    invalid = shape in ("trailing_comma", "quoted_marker", "quote_desync", "near_miss", "unclosed_start", "backtick_outside")
    same_block = verdict == "BLOCK" and (head == ADV_HEAD or head.startswith(ADV_HEAD[:7]))
    unusable_head = (verdict == "APPROVE" and head == ADV_HEAD[:7]) or (verdict == "BLOCK" and head in (OTHER_HEAD[:7], "<40-hex>"))
    known_limit = shape == "quoted_marker"
    for required in (False, True):
        ready, _ = gate(body, required=required)
        if same_block and shape != "root_array" and not (shape == "near_miss" and live):
            assert result["verdict"] == "BLOCK" and result["matches_head"]
            assert not ready if (required or invalid) else ready
        elif known_limit or (live and (invalid or unusable_head or shape == "root_array")):
            assert result["malformed"] and not ready
        else:
            assert result["verdict"] == "APPROVE" and not result["malformed"] and ready


@pytest.mark.parametrize("key", ["verdict", "head"])
@pytest.mark.parametrize("context", _MATRIX_CONTEXTS)
@pytest.mark.parametrize("position", ["before", "after"])
def test_round9_broken_envelope_cannot_hide_escaped_key_block(key, context, position):
    inner = json.dumps({"}": 1, "verdict": "BLOCK", "head": ADV_HEAD})
    inner = inner.replace('"' + key + '"', '"\\u%04x%s"' % (ord(key[0]), key[1:]))
    broken = '<!-- adversary-verdict:v1 {"note":"<!-- adversary-verdict:v1 ' + inner + ' -->'
    wrapped = _MATRIX_CONTEXTS[context] % broken
    before = wrapped + ("\n```" if context == "unclosed_fence" else "") + "\n" + marker("APPROVE")
    body = before if position == "before" else marker("APPROVE") + wrapped
    result = adv(body)
    assert result["verdict"] == "BLOCK" and result["matches_head"]
    assert not gate(body, required=True)[0]
    assert gate(body, required=False)[0] == (not result["malformed"])


@pytest.mark.parametrize("head", ["<40-hex>", OTHER_HEAD])
@pytest.mark.parametrize("context", ["fenced", "inline"])
def test_round9_unclosed_documentation_cannot_borrow_following_approve(head, context):
    example = '<!-- adversary-verdict:v1 ' + json.dumps({"verdict": "BLOCK", "head": head})
    body = _MATRIX_CONTEXTS[context] % example + "\n" + marker("APPROVE")
    assert adv(body)["verdict"] == "APPROVE" and not adv(body)["malformed"]
    for required in (False, True):
        assert gate(body, required=required)[0]


def test_trailing_comma_string_boundary_limit_is_only_fail_closed():
    doc = {"verdict": "APPROVE", "head": ADV_HEAD, "note": "format: <!-- adversary-verdict:v1",
           "example": {"verdict": "BLOCK", "head": ADV_HEAD}}
    example = '<!-- adversary-verdict:v1 ' + json.dumps(doc)[:-1] + ',} -->'
    body = marker("APPROVE") + _MATRIX_CONTEXTS["fenced"] % example
    assert adv(body)["verdict"] == "BLOCK" and adv(body)["malformed"]
    for required in (False, True):
        assert not gate(body, required=required)[0]
        assert not gate(_MATRIX_CONTEXTS["fenced"] % example, required=required)[0]


@pytest.mark.parametrize("context", _MATRIX_CONTEXTS)
@pytest.mark.parametrize("head", [ADV_HEAD, ADV_HEAD[:7], "<40-hex>"])
def test_documentation_approve_matrix_respects_documented_c1_limits(context, head):
    body = _MATRIX_CONTEXTS[context] % marker("APPROVE", head)
    expected = head == ADV_HEAD and context in ("live", "blockquote", "indented", "broken_inline")
    assert gate(body, required=True)[0] == expected
    # Report-only can ignore a missing verdict; malformed live short heads cannot pass.
    report_ready = not (head == ADV_HEAD[:7] and context in ("live", "blockquote", "indented", "broken_inline"))
    assert gate(body, required=False)[0] == report_ready


# ---- the Action: event -> PR -> verdict -> commit status (new 2026-11-06, slim-down E8) -------------------
#
# Every GitHub call goes through `CannedApi` (or, for the CLI, `--api-answers`), so the branching is tested
# without GitHub. What these tests cannot show is the trust model itself (the App token, the `merge-gate`
# environment, the ruleset's `integration_id` pin): that is verified by the operator with two throwaway PRs
# (docs/slim/reports/wave4-E8.md, E and G).

REPO_A = "djbclark/djbclark-ade"
H1 = "1" * 40
OUTSIDE_PR = {"author": "stranger", "assoc": "NONE"}
GHAPP = {"id": 1, "slug": "some-app", "owner": {"login": "djbclark"}}
H2 = "2" * 40


def pr_doc(head: str = H1, body: str = "", state: str = "open") -> dict:
    return {"json": {"number": 7, "state": state, "head": {"sha": head}, "body": body}}


def gql_doc(head: str = H1, body: str = "", state: str = "OPEN", author: str = "djbclark", editor: str | None = None,
            assoc: str = "OWNER") -> dict:
    """The GraphQL second read (`_pr_state_trusted`): state, head, body, author, last editor, author association."""
    return {"json": {"repository": {"pullRequest": {
        "state": state, "headRefOid": head, "body": body, "authorAssociation": assoc, "author": {"login": author},
        "editor": {"login": editor} if editor else None, "lastEditedAt": EDITED_AT if editor else None}}}}


EDITED_AT = "2026-11-07T12:00:00Z"


def actor(login: str | None) -> dict | None:
    """A GraphQL Actor: a `Bot` for an `[bot]` login, a `User` otherwise, None for a ghost."""
    if not login:
        return None
    return {"__typename": "Bot" if login.endswith("[bot]") else "User", "login": login}


def comment(body: str, login: str = "djbclark", app: object = None, cid: int = 1, editor: str | None = None,
            edits: list | None = None, gql: dict | None = None) -> dict:
    """One comment, as the REST API returns it (`performed_via_github_app` is always present), plus under `_gql` how
    the GraphQL read sees it: never edited unless `editor` (the last editor) or `edits` (the `userContentEdits`
    editors, the creation edit included; the last editor's edit is added when `edits` is not given); `gql` overrides
    or, with a None value, removes node fields."""
    node = {"fullDatabaseId": str(cid), "body": body, "author": actor(login), "editor": None, "lastEditedAt": None,
            "includesCreatedEdit": False, "userContentEdits": {"totalCount": 0, "nodes": []}}
    if editor or edits:
        hist = edits if edits is not None else [login, editor]
        node.update(editor=actor(editor), lastEditedAt=EDITED_AT, includesCreatedEdit=True,
                    userContentEdits={"totalCount": len(hist), "nodes": [{"editor": actor(e)} for e in hist]})
    for k, v in (gql or {}).items():
        if v is None:
            node.pop(k, None)
        else:
            node[k] = v
    return {"id": cid, "user": {"login": login}, "performed_via_github_app": app, "body": body, "_gql": node}


def rest(c: dict) -> dict:
    return {k: v for k, v in c.items() if k != "_gql"}


def comments_key(n: int, page: int = 1) -> str:
    return f"GET repos/{REPO_A}/issues/{n}/comments?per_page=100&page={page}"


def gql_comments_key(n: int, page: int = 1) -> str:
    return f"GRAPHQL {n} comments" + ("" if page == 1 else f" after c{page - 1}")


def gql_comment_pages(n: int, comments: list, per_page: int = 100, total: int | None = None) -> dict:
    """The GraphQL comments read of PR N in pages of PER_PAGE (cursor `c<page>`), from `comment()` entries."""
    nodes = [c["_gql"] for c in comments]
    chunks = [nodes[i:i + per_page] for i in range(0, len(nodes), per_page)] or [[]]
    out = {}
    for i, chunk in enumerate(chunks, 1):
        more = i < len(chunks)
        out[gql_comments_key(n, i)] = [{"json": {"repository": {"pullRequest": {"comments": {
            "totalCount": len(nodes) if total is None else total, "nodes": chunk,
            "pageInfo": {"hasNextPage": more, "endCursor": f"c{i}" if more else None}}}}}}]
    return out


def serve(n: int, body: str, head: str = H1, state: str = "open", second: dict | None = None,
          comments: list | None = None, **trust) -> dict:
    """Canned answers for PR N: the REST first read, the GraphQL second read (the same PR unless `second`) and its
    issue comments (none unless `comments`), through GraphQL and REST alike."""
    return {f"GET repos/{REPO_A}/pulls/{n}": [pr_doc(head, body, state)],
            f"GRAPHQL {n}": [second or gql_doc(head, body, state.upper(), **trust)],
            **rest_comment_pages(n, comments or []), **gql_comment_pages(n, comments or [])}


def rest_comment_pages(n: int, comments: list) -> dict:
    """The REST comments read of PR N in pages of 100 (a full last page is followed by an empty one)."""
    entries = [rest(c) for c in comments]
    return {comments_key(n, i // 100 + 1): [{"json": entries[i:i + 100]}] for i in range(0, len(entries) + 1, 100)}


def commits_key(head: str, page: int = 1) -> str:
    return f"GET repos/{REPO_A}/commits/{head}/pulls?per_page=100&page={page}"


def pull_entry(n: int, head: str, state: str = "open", repo: str = REPO_A) -> dict:
    return {"number": n, "state": state, "head": {"sha": head}, "base": {"repo": {"full_name": repo}}}


def at_head(head: str, *nums: int) -> dict:
    """The `GET commits/{head}/pulls` answer listing open same-repo PRs NUMS at HEAD."""
    return {commits_key(head): [{"json": [pull_entry(n, head) for n in nums]}]}


def run_ev(event: dict, answers: dict, name: str = "workflow_run", **kw):
    # Every lookup also asks `commits/{head}/pulls` for the other open PRs at the head; unless a test says otherwise
    # there are none.
    answers = {**at_head(H1), **at_head(H2), **answers}
    api = adversary_marker.CannedApi(answers)
    rc, report = adversary_marker.run_event(name, event, REPO_A, api, "https://x/run/1", **kw)
    return rc, report, api


def wr_event(head: str = H1, prs=(7,), conclusion: str = "success", **extra) -> dict:
    entries = [{"number": n, "head": {"sha": head}, "base": {"repo": {"url": f"https://api.github.com/repos/{REPO_A}"}}}
               for n in prs]
    return {"action": "completed", "workflow_run": {"head_sha": head, "conclusion": conclusion,
                                                     "pull_requests": entries, **extra}}


@pytest.mark.parametrize("verdict,state,word", [("APPROVE", "success", "approve"), ("BLOCK", "failure", "block")])
def test_a_verdict_for_this_head_posts_its_status_on_that_head(verdict, state, word):
    rc, report, api = run_ev(wr_event(), serve(7, marker(verdict, H1)))
    assert rc == 0, report
    assert api.posted == [{"sha": H1, "state": state, "context": "adversary-marker",
                           "description": f"{verdict} at {H1[:12]}", "target_url": "https://x/run/1"}]
    assert report["prs"][0]["outcome"] == word


@pytest.mark.parametrize("body,word,trust", [
    # Outside PRs still need an owner comment; markerless / wrong-head body does not approve them.
    ("no marker, only prose: APPROVE " + H1, "outside", OUTSIDE_PR),
    ('<!-- adversary-verdict:v1 {broken -->', "malformed", {}),
    (None, "outside", OUTSIDE_PR),
])
def test_anything_but_a_live_approve_for_this_head_posts_failure(body, word, trust):
    body = marker("APPROVE", H2) if body is None else body
    rc, report, api = run_ev(wr_event(), serve(7, body, **trust))
    assert rc == 0 and [p["state"] for p in api.posted] == ["failure"], report
    assert report["prs"][0]["outcome"] == word


def test_a_failed_tests_run_still_gets_its_marker_checked():
    # The Tests result is its own required check; this one judges only the marker.
    rc, _, api = run_ev(wr_event(conclusion="failure"), serve(7, marker("APPROVE", H1)))
    assert rc == 0 and api.posted[0]["state"] == "success"


def test_the_pr_comes_from_the_event_when_it_names_one():
    rc, report, api = run_ev(wr_event(prs=(7,)), serve(7, marker("APPROVE", H1)))
    assert report["found_by"] == "workflow_run.pull_requests"
    # The commit lookup still runs once: other open PRs at this head share its status (2026-11-07).
    assert api.calls[commits_key(H1)] == 1


def test_an_event_entry_for_another_repository_is_ignored_and_the_head_is_looked_up():
    ev = wr_event(prs=())
    ev["workflow_run"]["pull_requests"] = [{"number": 3, "head": {"sha": H1},
                                            "base": {"repo": {"url": "https://api.github.com/repos/someone/fork"}}}]
    answers = {commits_key(H1): [{"json": []}]}
    rc, report, api = run_ev(ev, answers)
    assert rc == 0 and report["prs"] == [] and api.posted == []


def test_with_no_pr_in_the_event_the_pr_is_found_by_head_sha():
    pulls = [{"number": 9, "state": "open", "head": {"sha": H1}, "base": {"repo": {"full_name": REPO_A}}},
             {"number": 8, "state": "closed", "head": {"sha": H1}, "base": {"repo": {"full_name": REPO_A}}},
             {"number": 6, "state": "open", "head": {"sha": H2}, "base": {"repo": {"full_name": REPO_A}}},
             {"number": 5, "state": "open", "head": {"sha": H1}, "base": {"repo": {"full_name": "other/repo"}}}]
    answers = {commits_key(H1): [{"json": pulls}],
               **serve(9, marker("APPROVE", H1))}
    rc, report, api = run_ev(wr_event(prs=()), answers)
    assert rc == 0 and report["found_by"] == "commits/{sha}/pulls"
    assert [r["pr"] for r in report["prs"]] == [9] and api.posted[0]["state"] == "success"


def test_a_fork_pr_is_found_by_its_head_branch_when_the_commit_lookup_is_empty():
    ev = wr_event(prs=(), head_branch="feature/x", head_repository={"owner": {"login": "contrib"}})
    answers = {commits_key(H1): [{"json": []}],
               f"GET repos/{REPO_A}/pulls?state=open&head=contrib:feature/x&per_page=100&page=1": [{"json": [{"number": 11, "head": {"sha": H1}}]}],
               **serve(11, marker("BLOCK", H1))}
    rc, report, api = run_ev(ev, answers)
    assert rc == 0 and report["found_by"] == "pulls?head=" and api.posted[0]["state"] == "failure"


def test_an_unknown_pr_posts_nothing_and_exits_0():
    answers = {commits_key(H1): [{"json": []}]}
    rc, report, api = run_ev(wr_event(prs=()), answers)
    assert rc == 0 and api.posted == [] and report["found_by"] == "no open PR has this head"


def test_a_head_that_moved_between_the_read_and_the_post_posts_nothing():
    answers = serve(7, marker("APPROVE", H1), second=gql_doc(H2, marker("APPROVE", H1)))
    rc, report, api = run_ev(wr_event(), answers)
    assert rc == 0 and api.posted == [], "a stale APPROVE must never land on any head"
    assert report["prs"][0]["result"] == "head-moved"


def test_a_block_edit_between_the_two_reads_is_what_gets_posted():
    answers = serve(7, marker("APPROVE", H1), second=gql_doc(H1, marker("BLOCK", H1)))
    rc, report, api = run_ev(wr_event(), answers)
    assert rc == 0 and api.posted[0]["state"] == "failure"
    assert report["prs"][0]["first_read"] == "approve" and report["prs"][0]["outcome"] == "block"


def test_a_closed_pr_is_skipped():
    rc, report, api = run_ev(wr_event(), serve(7, marker("APPROVE", H1), state="closed"))
    assert rc == 0 and api.posted == [] and report["prs"][0]["result"] == "skipped"


@pytest.mark.parametrize("answers", [
    {f"GET repos/{REPO_A}/pulls/7": [{"error": "HTTP 502"}]},
    {**serve(7, marker("APPROVE", H1)), "GRAPHQL 7": [{"error": "HTTP 502"}]},
    {**serve(7, marker("APPROVE", H1)), "GRAPHQL 7": [{"json": {"repository": {"pullRequest": None}}}]},
    {f"GET repos/{REPO_A}/pulls/7": [{"json": {"head": {"sha": "nothex"}, "state": "open"}}]},
    {**serve(7, marker("APPROVE", H1)), "POST": {"error": "HTTP 403"}},
], ids=["read-fails", "re-read-fails", "re-read-no-pr", "bad-head", "post-fails"])
def test_an_api_failure_fails_the_job_and_posts_no_success(answers):
    rc, report, api = run_ev(wr_event(), answers)
    assert rc == 2, report
    assert not any(p["state"] == "success" for p in api.posted)


def test_a_failed_commit_lookup_fails_the_job():
    rc, report, api = run_ev(wr_event(prs=()), {commits_key(H1): [{"error": "HTTP 500"}]})
    assert rc == 2 and api.posted == [] and "HTTP 500" in report["error"]


def test_two_open_prs_sharing_a_head_with_different_verdicts_end_on_failure():
    answers = {**serve(7, marker("APPROVE", H1)), **serve(8, marker("BLOCK", H1))}
    rc, _, api = run_ev(wr_event(prs=(7, 8)), answers)
    assert rc == 0 and api.posted[-1]["state"] == "failure" and "#7, #8" in api.posted[-1]["description"]


@pytest.mark.parametrize("pr,ok", [("12", True), (" 12 ", True), ("0", False), ("abc", False), ("", False),
                                   ("12; rm -rf /", False), ("-1", False), (None, False)])
def test_a_dispatch_takes_only_a_pr_number(pr, ok):
    event = {"inputs": {"pr": pr}}
    answers = serve(12, marker("APPROVE", H1))
    rc, report, api = run_ev(event, answers, name="workflow_dispatch")
    assert (rc, bool(api.posted)) == ((0, True) if ok else (2, False)), report


@pytest.mark.parametrize("name", ["pull_request", "pull_request_target", "push", ""])
def test_any_other_event_is_refused(name):
    rc, report, api = run_ev(wr_event(), serve(7, marker("APPROVE", H1)), name=name)
    assert rc == 2 and api.posted == []


def test_a_bad_head_sha_in_the_event_is_refused():
    rc, _, api = run_ev(wr_event(head="zz"), {})
    assert rc == 2 and api.posted == []


def cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(MODULE), *args], capture_output=True, text=True, timeout=60,
                          env={"PATH": "/usr/bin:/bin"})


def test_the_cli_event_entry_serves_canned_answers_and_prints_the_status(tmp_path):
    (tmp_path / "ev.json").write_text(json.dumps(wr_event()))
    (tmp_path / "api.json").write_text(json.dumps({**serve(7, marker("APPROVE", H1)), **at_head(H1)}))
    r = cli("--event", str(tmp_path / "ev.json"), "--event-name", "workflow_run", "--repo", REPO_A,
            "--api-answers", str(tmp_path / "api.json"))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["statuses"][0]["state"] == "success" and out["statuses"][0]["sha"] == H1


@pytest.mark.parametrize("body,rc,word", [
    (marker("APPROVE", H1), 0, "approve"), (marker("BLOCK", H1), 1, "block"), ("", 1, "missing"),
    (marker("APPROVE", H2), 1, "other-head"), ('<!-- adversary-verdict:v1 {x -->', 2, "malformed"),
])
def test_the_cli_body_entry_exit_codes(tmp_path, body, rc, word):
    (tmp_path / "body.md").write_text(body)
    r = cli("--body-file", str(tmp_path / "body.md"), "--head", H1)
    assert r.returncode == rc, r.stderr
    assert json.loads(r.stdout)["outcome"] == word


def test_an_unreadable_body_file_fails_closed(tmp_path):
    (tmp_path / "body.md").write_bytes(b"\xff\xfe not utf-8")
    r = cli("--body-file", str(tmp_path / "body.md"), "--head", H1)
    assert r.returncode == 2 and json.loads(r.stdout)["outcome"] == "unreadable"


def test_the_cli_refuses_bad_usage(tmp_path):
    assert cli().returncode == 2
    assert cli("--body-file", "x", "--head", "abc").returncode == 2
    assert cli("--bogus").returncode == 2


def test_the_check_run_fallback_carries_the_same_verdict_under_the_same_name():
    status = {"state": "success", "context": "adversary-marker", "description": f"APPROVE at {H1[:12]}", "target_url": "u"}
    body = adversary_marker.check_run_body(H1, status)
    assert body["name"] == "adversary-marker" and body["head_sha"] == H1 and body["conclusion"] == "success"
    assert body["status"] == "completed" and body["details_url"] == "u"
    assert adversary_marker.check_run_body(H1, {**status, "state": "failure"})["conclusion"] == "failure"


def test_gate_without_a_collected_verdict_fails_closed():
    r = adversary_marker.gate(None, True)
    assert not r["merge_ready"] and r["merge_blockers"] == ["adversary-unreadable"]
    assert adversary_marker.outcome(None) == "unreadable"


# ---- the workflow file: what a reviewer checks, pinned ------------------------------------------------

def workflow() -> dict:
    import yaml
    doc = yaml.safe_load(WORKFLOW.read_text())
    # PyYAML reads the bare key `on` as the boolean True.
    doc["on"] = doc.pop(True, doc.get("on"))
    return doc


def test_the_workflow_runs_only_on_workflow_run_of_tests_and_a_dispatch():
    on = workflow()["on"]
    assert set(on) == {"workflow_run", "workflow_dispatch"}
    assert on["workflow_run"] == {"workflows": ["Tests"], "types": ["completed"]}
    assert on["workflow_dispatch"]["inputs"]["pr"]["required"] is True
    code = [ln for ln in WORKFLOW.read_text().splitlines() if not ln.lstrip().startswith("#")]
    assert not any("pull_request_target" in ln or "pull_request:" in ln for ln in code)


def test_the_tests_workflow_it_follows_exists_under_that_name():
    import yaml
    assert yaml.safe_load((ROOT / ".github" / "workflows" / "test.yml").read_text())["name"] == "Tests"


def test_the_job_has_read_permissions_only_and_the_merge_gate_environment():
    doc = workflow()
    assert doc["permissions"] == {} and "concurrency" not in doc
    for job in doc["jobs"].values():
        assert job["permissions"] == {"pull-requests": "read", "contents": "read"}
    marker_job, resolve_job = doc["jobs"]["marker"], doc["jobs"]["resolve"]
    assert marker_job["environment"] == "merge-gate"
    assert "default_branch" in resolve_job["if"], "a dispatch from another ref does nothing"
    assert marker_job["concurrency"]["cancel-in-progress"] is True
    assert marker_job["concurrency"]["group"].startswith("adversary-marker-")


def test_every_action_is_pinned_by_full_sha_and_the_app_token_uses_client_id():
    uses = [s for job in workflow()["jobs"].values() for s in job["steps"] if "uses" in s]
    assert uses, "no action steps"
    for s in uses:
        ref = s["uses"].split("@", 1)[1]
        assert len(ref) == 40 and all(c in "0123456789abcdef" for c in ref), s["uses"]
    app = [s for s in uses if s["uses"].startswith("actions/create-github-app-token@")]
    assert len(app) == 1 and "client-id" in app[0]["with"] and "app-id" not in app[0]["with"]
    checkout = [s for s in uses if s["uses"].startswith("actions/checkout@")]
    assert len(checkout) == 2
    for c in checkout:
        assert c["with"]["persist-credentials"] is False
        assert "ref" not in c["with"], "the default branch only: never a PR ref"


def test_no_event_field_is_interpolated_into_a_shell_line():
    for job in workflow()["jobs"].values():
        for s in job["steps"]:
            assert "${{" not in s.get("run", ""), s.get("run")


# ---- who may approve (E8 review BLOCK, 2026-11-07; tightened 2026-11-07 after the Argon and Opus reviews;
# trusted-editor allowlist for owner PRs 2026-11-09) -------------------------------------------------------------
#
# A body APPROVE counts only on an OWNER-AUTHORED PR whose body last editor is the owner or a login in
# BODY_TRUSTED_EDITOR_LOGINS (today: `cursor`, so a Cloud Agent rewrite of an owner PR body does not void a live
# APPROVE). Every other PR (an outside author, and MEMBER or COLLABORATOR authors too: the operator's agents act
# under the owner's login) is approved only by an issue comment the owner posted, not via a GitHub App. A listed
# App editing an outside body still cannot approve it. Before 2026-11-07, the owner's last edit made any body
# trusted, so ticking a task-list box on an outside PR turned the author's hidden APPROVE into a trusted one.

OUTSIDE = f"outside PR: APPROVE only counts in an owner comment at {H1[:12]}"
UNTRUSTED = f"marker not written by a trusted user at {H1[:12]}"


@pytest.mark.parametrize("trust,word", [
    ({"author": "djbclark", "assoc": "OWNER"}, "approve"),
    ({"author": "DJBClark", "assoc": "OWNER"}, "approve"),                      # logins are case-insensitive
    ({"author": "djbclark", "assoc": "OWNER", "editor": "DJBCLARK"}, "approve"),
    ({"author": "djbclark", "assoc": "OWNER", "editor": "cursor"}, "approve"),   # Cloud Agent body rewrite
    ({"author": "djbclark", "assoc": "OWNER", "editor": "Cursor"}, "approve"),
    ({"author": "djbclark", "assoc": "OWNER", "editor": "stranger"}, "untrusted"),   # a later edit by anyone else
    ({"author": "alice", "assoc": "MEMBER"}, "outside"),
    ({"author": "bob", "assoc": "COLLABORATOR"}, "outside"),
    ({"author": "stranger", "assoc": "NONE"}, "outside"),                       # an outside fork author's own APPROVE
    ({"author": "stranger", "assoc": "CONTRIBUTOR"}, "outside"),
    ({"author": "stranger", "assoc": "FIRST_TIME_CONTRIBUTOR"}, "outside"),
    ({"author": "stranger", "assoc": "NONE", "editor": "djbclark"}, "outside"),  # hole 2: the owner's edit is no approval
    ({"author": "stranger", "assoc": "NONE", "editor": "DJBClark"}, "outside"),
    ({"author": "stranger", "assoc": "NONE", "editor": "cursor"}, "outside"),    # allowlist does not help outsiders
    ({"author": "alice", "assoc": "MEMBER", "editor": "cursor"}, "outside"),
    ({"author": "alice", "assoc": "MEMBER", "editor": "stranger"}, "outside"),
    ({"author": "stranger", "assoc": "NONE", "editor": "bob"}, "outside"),
    ({"author": "", "assoc": "OWNER"}, "outside"),                              # a deleted (ghost) author
])
def test_a_body_approve_counts_only_on_an_owner_pr_with_a_trusted_body_editor(trust, word):
    rc, report, api = run_ev(wr_event(), serve(7, marker("APPROVE", H1), **trust))
    assert rc == 0 and len(api.posted) == 1, report
    assert report["prs"][0]["outcome"] == word
    assert api.posted[0]["state"] == ("success" if word == "approve" else "failure")
    assert api.posted[0]["description"] == {"approve": f"APPROVE at {H1[:12]}", "untrusted": UNTRUSTED,
                                            "outside": OUTSIDE}[word]


def test_hole2_an_owner_edit_of_an_outside_body_never_approves_its_hidden_marker():
    # The author hid the APPROVE in an HTML comment (invisible when rendered); the owner then ticked a task-list box,
    # which made the owner the body's last editor.
    body = "- [x] docs updated\n\n" + marker("APPROVE", H1)
    rc, report, api = run_ev(wr_event(), serve(7, body, author="stranger", assoc="NONE", editor="djbclark"))
    assert rc == 0 and [p["state"] for p in api.posted] == ["failure"], report
    assert report["prs"][0]["outcome"] == "outside" and api.posted[0]["description"] == OUTSIDE


def test_body_editor_trusted_helper_is_owner_or_allowlist_only():
    import adversary_marker as am
    assert am.body_editor_trusted("djbclark", "djbclark")
    assert am.body_editor_trusted("CURSOR", "djbclark")
    assert not am.body_editor_trusted("stranger", "djbclark")
    assert not am.body_editor_trusted("", "djbclark")
    assert not am.body_editor_trusted("cursor", "")
    assert "cursor" in {x.lower() for x in am.BODY_TRUSTED_EDITOR_LOGINS}


@pytest.mark.parametrize("trust", [OUTSIDE_PR, {"author": "alice", "assoc": "MEMBER"},
                                   {"author": "bob", "assoc": "COLLABORATOR"}])
@pytest.mark.parametrize("login", ["djbclark", "DJBClark"])
def test_an_owner_comment_with_a_live_approve_for_this_head_approves_a_non_owner_pr(trust, login):
    rc, report, api = run_ev(wr_event(), serve(7, "", comments=[comment(marker("APPROVE", H1), login=login)], **trust))
    assert rc == 0 and len(api.posted) == 1, report
    assert api.posted[0]["state"] == "success" and report["prs"][0]["outcome"] == "approve"
    assert api.posted[0]["description"] == f"APPROVE in an owner comment at {H1[:12]}"


@pytest.mark.parametrize("c", [
    comment(marker("APPROVE", H1), app=GHAPP),                                       # the owner's login, via an App
    {k: v for k, v in comment(marker("APPROVE", H1)).items() if k != "performed_via_github_app"},  # field missing
    comment(marker("APPROVE", H1), login="stranger"),                                # another author
    comment(marker("APPROVE", H1), login="chatgpt-codex-connector[bot]"),
    comment(marker("APPROVE", H1), login=""),                                        # a ghost
], ids=["via-app", "app-field-missing", "stranger", "bot", "ghost"])
def test_an_approve_comment_not_posted_by_the_owner_himself_does_not_approve(c):
    rc, report, api = run_ev(wr_event(), serve(7, marker("APPROVE", H1), comments=[c], **OUTSIDE_PR))
    assert rc == 0 and [p["state"] for p in api.posted] == ["failure"], report
    assert report["prs"][0]["outcome"] == "untrusted"
    assert api.posted[0]["description"] == f"marker not written by a trusted user in a comment at {H1[:12]}"


@pytest.mark.parametrize("text,word", [
    ("```\n" + marker("APPROVE", H1) + "\n```", "outside"),           # fenced: documentation
    ("the format is `" + marker("APPROVE", H1) + "`", "outside"),     # inline span: documentation
    (marker("APPROVE", H2), "outside"),                               # another head: an earlier push's approval
    ("APPROVE " + H1, "outside"),                                     # prose is never a verdict
    (marker("APPROVE", H1[:12]), "malformed"),                        # an APPROVE needs the full sha
    ('<!-- adversary-verdict:v1 {"verdict":"approve","head":"' + H1 + '"} -->', "malformed"),
    (marker("APPROVE", H1) + "\n" + marker("BLOCK", H1), "block"),    # both: the BLOCK wins
])
def test_owner_comment_markers_follow_the_body_rules(text, word):
    rc, report, api = run_ev(wr_event(), serve(7, "", comments=[comment(text)], **OUTSIDE_PR))
    assert rc == 0 and [p["state"] for p in api.posted] == ["failure"], report
    assert report["prs"][0]["outcome"] == word


def test_an_old_owner_approval_for_another_head_does_not_fail_the_new_one():
    cs = [comment(marker("APPROVE", H2), cid=1), comment(marker("APPROVE", H1), cid=2)]
    rc, report, api = run_ev(wr_event(), serve(7, "", comments=cs, **OUTSIDE_PR))
    assert api.posted[0]["state"] == "success", report


@pytest.mark.parametrize("trust,body,owner_ok", [
    ({}, marker("APPROVE", H1), True),                                # an owner PR whose body approves
    (OUTSIDE_PR, "", False),                                          # an outside PR
])
@pytest.mark.parametrize("block", [marker("BLOCK", H1), marker("BLOCK", H1[:9] + "…"), marker("BLOCK", H1[:7])])
@pytest.mark.parametrize("login,app", [("stranger", None), ("djbclark", None), ("djbclark", GHAPP),
                                       ("chatgpt-codex-connector[bot]", GHAPP)])
def test_a_block_for_this_head_in_any_comment_fails_the_check(trust, body, owner_ok, block, login, app):
    cs = [comment(marker("APPROVE", H1), cid=1), comment("looks wrong\n" + block, login=login, app=app, cid=2)]
    rc, report, api = run_ev(wr_event(), serve(7, body, comments=cs, **trust))
    assert rc == 0 and [p["state"] for p in api.posted] == ["failure"], report
    assert report["prs"][0]["outcome"] == "block"
    assert api.posted[0]["description"] == f"BLOCK in a comment at {H1[:12]}"


def test_a_malformed_marker_in_any_comment_fails_the_check():
    cs = [comment('<!-- adversary-verdict:v1 {"verdict":"BLOCK","head": -->', login="stranger")]
    rc, report, api = run_ev(wr_event(), serve(7, marker("APPROVE", H1), comments=cs))
    assert api.posted[0]["state"] == "failure" and report["prs"][0]["outcome"] == "malformed"
    assert api.posted[0]["description"] == f"malformed marker in a comment at {H1[:12]}"


def test_an_owner_pr_body_still_approves_and_markerless_owner_pr_also_approves():
    """Owner PRs: explicit body APPROVE still works; no marker is also success (owner-trust, 2026-11-10)."""
    rc, report, api = run_ev(wr_event(), serve(7, marker("APPROVE", H1)))
    assert api.posted[0]["state"] == "success" and api.posted[0]["description"] == f"APPROVE at {H1[:12]}"
    rc, report, api = run_ev(wr_event(), serve(7, "", comments=[comment(marker("APPROVE", H1))]))
    assert api.posted[0]["state"] == "success" and report["prs"][0]["outcome"] == "approve"
    assert report["prs"][0]["where"] == "owner_pr"
    assert "marker optional" in api.posted[0]["description"]


def test_an_owner_pr_with_no_marker_at_all_approves_under_owner_trust():
    rc, report, api = run_ev(wr_event(), serve(7, "just a description, no marker"))
    assert rc == 0 and api.posted[0]["state"] == "success"
    assert report["prs"][0]["outcome"] == "approve" and report["prs"][0]["where"] == "owner_pr"


def test_comments_are_read_on_every_page():
    noise = [comment(f"thanks {i}", login="stranger", cid=i) for i in range(100)]
    answers = serve(7, marker("APPROVE", H1), comments=[*noise, comment(marker("BLOCK", H1), login="stranger", cid=101)])
    rc, report, api = run_ev(wr_event(), answers)
    assert api.posted[0]["state"] == "failure" and report["prs"][0]["outcome"] == "block", report
    assert report["prs"][0]["comments"] == 101
    assert api.calls[gql_comments_key(7, 2)] == 1 and api.calls[comments_key(7, 2)] == 1


@pytest.mark.parametrize("key,page", [
    ("rest", [{"error": "HTTP 502"}]), ("rest", [{"json": {"message": "nope"}}]), ("rest", [{"json": ["x"]}]),
    ("gql", [{"error": "HTTP 502"}]),
    ("gql", [{"json": {"repository": {"pullRequest": None}}}]),
    ("gql", [{"json": {"repository": {"pullRequest": {"comments": {"totalCount": 0, "nodes": "x",
                                                                   "pageInfo": {"hasNextPage": False}}}}}}]),
    ("gql", [{"json": {"repository": {"pullRequest": {"comments": {"totalCount": 1, "nodes": ["x"],
                                                                   "pageInfo": {"hasNextPage": False}}}}}}]),
    ("gql", [{"json": {"repository": {"pullRequest": {"comments": {"totalCount": 0, "nodes": []}}}}}]),
    ("gql", [{"json": {"repository": {"pullRequest": {"comments": {"totalCount": 2, "nodes": [],
                                                                   "pageInfo": {"hasNextPage": False}}}}}}]),
    ("gql", [{"json": {"repository": {"pullRequest": {"comments": {"totalCount": 2, "nodes": [],
                                                                   "pageInfo": {"hasNextPage": True}}}}}}]),
], ids=["rest-http-error", "rest-not-a-list", "rest-bad-entry", "gql-error", "gql-no-pr", "gql-nodes-not-a-list",
        "gql-bad-entry", "gql-no-page-info", "gql-short-of-total", "gql-no-cursor"])
def test_an_unreadable_comment_list_fails_closed_and_posts_nothing(key, page):
    answers = {**serve(7, marker("APPROVE", H1)), (comments_key(7) if key == "rest" else gql_comments_key(7)): page}
    rc, report, api = run_ev(wr_event(), answers)
    assert rc == 2 and api.posted == [], report
    assert report["prs"][0]["result"] == "error" and "comments" in report["prs"][0]["detail"]


@pytest.mark.parametrize("count", [100, 101], ids=["rest-cap", "gql-cap"])
def test_a_pr_with_more_comments_than_the_read_cap_fails_closed(monkeypatch, count):
    # 100 comments fill one GraphQL page with no next page, but a full REST page asks for page 2; 101 need two of each.
    monkeypatch.setattr(adversary_marker, "COMMENT_PAGES_MAX", 1)
    full = [comment("x", login="stranger", cid=i) for i in range(count)]
    rc, report, api = run_ev(wr_event(), serve(7, marker("APPROVE", H1), comments=full))
    assert rc == 2 and api.posted == [] and "not read in full" in report["prs"][0]["detail"]


# ---- hole 1 (2026-11-07): a dispatch judges every open PR at the head, and one status is posted per head ----------

def dispatch(n: int) -> dict:
    return {"inputs": {"pr": str(n)}}


@pytest.mark.parametrize("sibling", [marker("BLOCK", H1), "", marker("APPROVE", H2)], ids=["block", "none", "other-head"])
def test_hole1_a_dispatch_for_an_approved_pr_fails_when_another_open_pr_at_its_head_does_not_approve(sibling):
    # Sibling is an outside PR so markerless / other-head does not ride owner-trust (2026-11-10).
    answers = {
        **serve(10, marker("APPROVE", H1)),
        **serve(11, sibling, **OUTSIDE_PR),
        **at_head(H1, 10, 11),
    }
    rc, report, api = run_ev(dispatch(10), answers, name="workflow_dispatch")
    assert rc == 0, report
    assert [r["pr"] for r in report["prs"]] == [10, 11]
    assert api.posted == [{"sha": H1, "state": "failure", "context": "adversary-marker", "target_url": "https://x/run/1",
                           "description": f"PRs #10, #11 share head {H1[:12]} and not all approve"}], \
        "one post per head, and never a transient success before the shared-head failure"


def test_a_dispatch_where_every_pr_at_the_head_approves_posts_one_success():
    answers = {**serve(10, marker("APPROVE", H1)), **serve(11, marker("APPROVE", H1)), **at_head(H1, 10, 11)}
    rc, report, api = run_ev(dispatch(10), answers, name="workflow_dispatch")
    assert rc == 0 and [p["state"] for p in api.posted] == ["success"], report


def test_a_workflow_run_naming_one_pr_still_judges_the_other_open_pr_at_its_head():
    answers = {**serve(10, marker("APPROVE", H1)), **serve(11, marker("BLOCK", H1)), **at_head(H1, 11)}
    rc, report, api = run_ev(wr_event(prs=(10,)), answers)
    assert rc == 0 and [p["state"] for p in api.posted] == ["failure"], report


def test_a_sibling_at_the_head_that_cannot_be_read_turns_the_shared_status_to_failure():
    answers = {**serve(10, marker("APPROVE", H1)), **at_head(H1, 10, 11), "GRAPHQL 11": [{"error": "HTTP 502"}],
               f"GET repos/{REPO_A}/pulls/11": [pr_doc(H1, marker("APPROVE", H1))]}
    rc, report, api = run_ev(dispatch(10), answers, name="workflow_dispatch")
    assert rc == 2 and [p["state"] for p in api.posted] == ["failure"], report
    assert "#11" in api.posted[0]["description"]


@pytest.mark.parametrize("answers", [
    {f"GET repos/{REPO_A}/pulls/10": [{"error": "HTTP 404"}]},
    {**serve(10, marker("APPROVE", H1)), commits_key(H1): [{"error": "HTTP 500"}]},
], ids=["pr-read-fails", "head-lookup-fails"])
def test_a_dispatch_whose_lookup_fails_posts_nothing(answers):
    rc, report, api = run_ev(dispatch(10), answers, name="workflow_dispatch")
    assert rc == 2 and api.posted == [], report


def test_resolve_for_a_dispatch_keys_by_the_head_like_a_workflow_run():
    answers = {**serve(10, marker("APPROVE", H1)), **at_head(H1, 10, 11)}
    rc, out = adversary_marker.resolve("workflow_dispatch", dispatch(10), REPO_A, adversary_marker.CannedApi(answers))
    rc2, out2 = adversary_marker.resolve("workflow_run", wr_event(prs=(11,)), REPO_A, adversary_marker.CannedApi(answers))
    assert (rc, rc2) == (0, 0) and out["prs"] == out2["prs"] == "10,11" and out["key"] == out2["key"] == H1


def test_at_head_posts_only_on_the_runs_own_head():
    # #11 moved to H2 after the resolve job keyed this run by H1: it gets nothing from this run (its push has its own).
    answers = {**serve(10, marker("APPROVE", H1)), **serve(11, marker("APPROVE", H2), head=H2)}
    rc, report, api = run_ev(wr_event(prs=()), answers, prs_given=[10, 11], at_head=H1)
    assert rc == 0 and [(p["sha"], p["state"]) for p in api.posted] == [(H1, "success")], report
    assert report["prs"][1]["result"] == "head-moved"


@pytest.mark.parametrize("head,rc", [(H1, 0), (H1.upper(), 0), ("abc", 2), ("", 2)])
def test_the_cli_at_head_takes_only_a_full_sha(tmp_path, head, rc):
    (tmp_path / "ev.json").write_text(json.dumps(wr_event(prs=())))
    (tmp_path / "api.json").write_text(json.dumps(serve(7, marker("APPROVE", H1))))
    r = cli("--prs", "7", "--at-head", head, "--event", str(tmp_path / "ev.json"), "--event-name", "workflow_run",
            "--repo", REPO_A, "--api-answers", str(tmp_path / "api.json"))
    assert r.returncode == rc, r.stderr
    if rc == 0:
        assert json.loads(r.stdout)["statuses"][0]["state"] == "success"


def test_the_marker_job_passes_the_resolved_head_as_at_head():
    judge = workflow()["jobs"]["marker"]["steps"][-1]
    assert judge["env"]["AT_HEAD"] == "${{ needs.resolve.outputs.key }}"
    assert '--at-head "$AT_HEAD"' in judge["run"]


def test_a_block_from_an_untrusted_author_still_fails_the_check():
    rc, report, api = run_ev(wr_event(), serve(7, marker("BLOCK", H1), author="stranger", assoc="NONE"))
    assert api.posted[0]["state"] == "failure" and report["prs"][0]["outcome"] == "block"


def test_the_editor_and_the_body_come_from_the_same_read():
    # The first (REST) read says APPROVE by the owner; the GraphQL read shows a stranger re-edited it since.
    second = gql_doc(H1, marker("APPROVE", H1), author="djbclark", editor="stranger")
    rc, report, api = run_ev(wr_event(), serve(7, marker("APPROVE", H1), second=second))
    assert api.posted[0]["state"] == "failure" and report["prs"][0]["last_editor"] == "stranger"


def test_the_graphql_read_asks_for_the_trust_fields():
    q = adversary_marker.PR_QUERY
    for field in ("headRefOid", "body", "authorAssociation", "author { login }", "editor { login }", "lastEditedAt",
                  "state"):
        assert field in q, field
    # GitHub's schema has no `lastEditedBy` (2026-11-07): asking for it fails every read.
    assert "lastEditedBy" not in q and "lastEditedBy" not in adversary_marker.COMMENTS_QUERY


def test_a_legacy_null_history_without_current_attribution_cannot_approve():
    # A legacy null connection cannot substitute for current editor/lastEditedAt attribution.
    second = {"json": {"repository": {"pullRequest": {
        "state": "OPEN", "headRefOid": H1, "body": marker("APPROVE", H1), "authorAssociation": "NONE",
        "author": {"login": "stranger"}, "userContentEdits": None}}}}
    rc, report, api = run_ev(wr_event(), serve(7, marker("APPROVE", H1), second=second))
    assert rc == 0 and api.posted[0]["state"] == "failure"
    assert report["prs"][0]["last_editor"] == "" and report["prs"][0]["outcome"] == "outside"


def test_a_null_editor_in_a_legacy_edit_response_does_not_inherit_the_author():
    # A legacy response without current editor attribution cannot confer author trust.
    second = {"json": {"repository": {"pullRequest": {
        "state": "OPEN", "headRefOid": H1, "body": marker("APPROVE", H1), "authorAssociation": "NONE",
        "author": {"login": "stranger"}, "userContentEdits": {"nodes": [{"editor": None}]}}}}}
    rc, report, api = run_ev(wr_event(), serve(7, marker("APPROVE", H1), second=second))
    assert rc == 0 and api.posted[0]["state"] == "failure"
    assert report["prs"][0]["last_editor"] == "" and report["prs"][0]["outcome"] == "outside"


def test_a_never_edited_body_uses_explicit_current_attribution():
    # Explicit editor/lastEditedAt null preserves an owner's legitimate never-edited approval.
    rc, report, api = run_ev(wr_event(), serve(7, marker("APPROVE", H1), author="djbclark", assoc="OWNER"))
    assert rc == 0 and api.posted[0]["state"] == "success" and report["prs"][0]["last_editor"] == "djbclark"


def test_body_uses_current_editor_and_comment_history_is_bounded_newest_first():
    # PR300 supersedes PR303's first:1 body query with valid current attribution;
    # comments must still request the bounded whole edit history, never last:1.
    q = adversary_marker.PR_QUERY
    assert "editor { login } lastEditedAt" in q
    assert "userContentEdits" not in q
    q = adversary_marker.COMMENTS_QUERY
    assert re.search(r"userContentEdits\(first: 100\)", q), q
    assert not re.search(r"userContentEdits\(last", q), q


# ---- the resolve job and --prs ---------------------------------------------------------------------------

def test_resolve_gives_the_pr_numbers_and_the_concurrency_key():
    # The key is the HEAD the PRs were found at (2026-11-07): one status per sha, so one concurrency group per sha.
    api = adversary_marker.CannedApi(at_head(H1, 11))
    assert adversary_marker.resolve("workflow_run", wr_event(prs=(9, 7)), REPO_A, api) == \
        (0, {"prs": "7,9,11", "key": H1, "found_by": "workflow_run.pull_requests"})
    api = adversary_marker.CannedApi({commits_key(H1): [{"json": []}]})
    rc, out = adversary_marker.resolve("workflow_run", wr_event(prs=()), REPO_A, api)
    assert rc == 0 and out["key"] == "" and out["prs"] == ""
    assert adversary_marker.resolve("pull_request", wr_event(), REPO_A, api)[0] == 2


def test_the_cli_resolve_writes_github_output(tmp_path):
    (tmp_path / "ev.json").write_text(json.dumps(wr_event(prs=(7,))))
    (tmp_path / "api.json").write_text(json.dumps(at_head(H1)))
    out = tmp_path / "gh-output"
    r = subprocess.run([sys.executable, "-I", str(MODULE), "--resolve", "--event", str(tmp_path / "ev.json"),
                        "--event-name", "workflow_run", "--repo", REPO_A, "--api-answers", str(tmp_path / "api.json")],
                       capture_output=True, text=True, timeout=60, env={"PATH": "/usr/bin:/bin", "GITHUB_OUTPUT": str(out)})
    assert r.returncode == 0, r.stderr
    assert out.read_text() == f"prs=7\nkey={H1}\n"


@pytest.mark.parametrize("prs,rc", [("7", 0), ("7,9", 0), ("", 2), ("7;rm", 2), ("0", 2), ("7,x", 2)])
def test_prs_judges_exactly_the_resolved_list_and_refuses_anything_else(tmp_path, prs, rc):
    (tmp_path / "ev.json").write_text(json.dumps(wr_event(prs=())))   # no lookup may happen with --prs
    (tmp_path / "api.json").write_text(json.dumps({**serve(7, marker("APPROVE", H1)), **serve(9, marker("APPROVE", H1))}))
    r = cli("--prs", prs, "--event", str(tmp_path / "ev.json"), "--event-name", "workflow_run", "--repo", REPO_A,
            "--api-answers", str(tmp_path / "api.json"))
    assert r.returncode == rc, r.stderr
    if rc == 0:
        assert sorted(x["pr"] for x in json.loads(r.stdout)["prs"]) == [int(x) for x in prs.split(",")]


def test_the_marker_job_is_keyed_by_the_resolved_pr_and_requests_both_app_permissions():
    jobs = workflow()["jobs"]
    assert set(jobs) == {"resolve", "marker"}
    assert "environment" not in jobs["resolve"] and jobs["marker"]["needs"] == "resolve"
    assert jobs["marker"]["concurrency"] == {"group": "adversary-marker-${{ needs.resolve.outputs.key }}",
                                             "cancel-in-progress": True}
    app = [s for s in jobs["marker"]["steps"] if s.get("uses", "").startswith("actions/create-github-app-token@")][0]
    assert app["with"]["permission-statuses"] == "write" and app["with"]["permission-checks"] == "write"
    judge = jobs["marker"]["steps"][-1]
    assert '--prs "$PRS"' in judge["run"] and judge["env"]["PRS"] == "${{ needs.resolve.outputs.prs }}"


# ---- B1 (Codex review, 2026-11-07): an owner comment approves only if nobody but the owner edited it ----------------
# GitHub lets any repository writer edit someone else's comment while the author stays the owner, so the comments are
# read through GraphQL (`editor`, `lastEditedAt`, `includesCreatedEdit`, `userContentEdits`; the schema has no
# `lastEditedBy`). REST only supplies the App provenance and can only take trust away.

EDITED = f"owner's APPROVE comment was edited by someone else at {H1[:12]}"
EDIT_UNKNOWN = f"owner's APPROVE comment has an unknown edit history at {H1[:12]}"
OWNER_COMMENT_OK = f"APPROVE in an owner comment at {H1[:12]}"


@pytest.mark.parametrize("kw,word,desc", [
    ({}, "approve", OWNER_COMMENT_OK),                                                   # never edited
    ({"editor": "djbclark"}, "approve", OWNER_COMMENT_OK),                               # edited by the owner
    ({"editor": "DJBClark"}, "approve", OWNER_COMMENT_OK),
    ({"editor": "bob"}, "edited", EDITED),                                               # a collaborator's edit
    ({"editor": "some-app[bot]"}, "edited", EDITED),                                     # an App's (bot's) edit
    ({"editor": "djbclark", "edits": ["djbclark", "bob", "djbclark"]}, "edited", EDITED),  # owner ticked a box after bob
    ({"edits": ["djbclark", None]}, "edit-unknown", EDIT_UNKNOWN),                       # edited by a deleted user
    ({"gql": {"editor": None}}, "edit-unknown", EDIT_UNKNOWN),                           # attribution fields missing
    ({"gql": {"lastEditedAt": None}}, "edit-unknown", EDIT_UNKNOWN),
    ({"gql": {"userContentEdits": None}}, "edit-unknown", EDIT_UNKNOWN),
    ({"gql": {"includesCreatedEdit": None}}, "edit-unknown", EDIT_UNKNOWN),
    ({"gql": {"lastEditedAt": EDITED_AT}}, "edit-unknown", EDIT_UNKNOWN),               # edited, editor null
    ({"editor": "djbclark", "gql": {"userContentEdits": {"totalCount": 150, "nodes": [{"editor": actor("djbclark")}]}}},
     "edit-unknown", EDIT_UNKNOWN),                                                      # history not read in full
    ({"editor": "djbclark", "gql": {"editor": {"login": "djbclark"}}}, "edit-unknown", EDIT_UNKNOWN),  # no __typename
], ids=["never-edited", "owner-edit", "owner-edit-case", "collaborator-edit", "bot-edit", "collaborator-in-history",
        "ghost-editor", "no-editor-field", "no-edited-at-field", "no-history-field", "no-created-edit-field",
        "edited-without-editor", "history-truncated", "editor-without-type"])
def test_b1_an_owner_comment_approves_only_when_nobody_else_edited_it(kw, word, desc):
    c = comment(marker("APPROVE", H1), **kw)
    rc, report, api = run_ev(wr_event(), serve(7, "", comments=[c], **OUTSIDE_PR))
    assert rc == 0 and len(api.posted) == 1, report
    assert report["prs"][0]["outcome"] == word
    assert api.posted[0]["state"] == ("success" if word == "approve" else "failure")
    assert api.posted[0]["description"] == desc


def test_b1_a_collaborator_edit_cannot_be_laundered_by_a_second_trusted_comment_elsewhere():
    # One trusted owner APPROVE is enough; a second, collaborator-edited one does not spoil it, and a collaborator's
    # edit that ADDS a BLOCK to an owner comment still fails.
    ok = comment(marker("APPROVE", H1), cid=1)
    edited = comment(marker("APPROVE", H1), editor="bob", cid=2)
    rc, report, api = run_ev(wr_event(), serve(7, "", comments=[edited, ok], **OUTSIDE_PR))
    assert api.posted[0]["state"] == "success", report
    blocked = comment(marker("BLOCK", H1), editor="bob", cid=3)
    rc, report, api = run_ev(wr_event(), serve(7, "", comments=[ok, blocked], **OUTSIDE_PR))
    assert api.posted[0]["state"] == "failure" and report["prs"][0]["outcome"] == "block"


def test_b1_an_owner_comment_the_rest_read_does_not_confirm_is_not_trusted():
    # Trust needs BOTH reads: GraphQL for the author and edits, REST for "no App". Missing from REST, or a REST body
    # that differs (an edit between the reads), is not confirmed.
    c = comment(marker("APPROVE", H1))
    answers = {**serve(7, "", comments=[c], **OUTSIDE_PR), comments_key(7): [{"json": []}]}
    rc, report, api = run_ev(wr_event(), answers)
    assert api.posted[0]["state"] == "failure" and report["prs"][0]["outcome"] == "untrusted", report
    answers = {**serve(7, "", comments=[c], **OUTSIDE_PR),
               comments_key(7): [{"json": [{**rest(c), "body": marker("APPROVE", H1) + " "}]}]}
    rc, report, api = run_ev(wr_event(), answers)
    assert api.posted[0]["state"] == "failure" and report["prs"][0]["outcome"] == "untrusted", report


def test_b1_a_block_only_the_rest_read_saw_still_fails():
    c = comment(marker("APPROVE", H1))
    answers = {**serve(7, "", comments=[c], **OUTSIDE_PR),
               comments_key(7): [{"json": [rest(c), rest(comment(marker("BLOCK", H1), login="stranger", cid=9))]}]}
    rc, report, api = run_ev(wr_event(), answers)
    assert api.posted[0]["state"] == "failure" and report["prs"][0]["outcome"] == "block", report


def test_b1_a_failing_graphql_comment_read_posts_nothing():
    c = comment(marker("APPROVE", H1))
    answers = {**serve(7, "", comments=[c], **OUTSIDE_PR), gql_comments_key(7): [{"error": "HTTP 502"}]}
    rc, report, api = run_ev(wr_event(), answers)
    assert rc == 2 and api.posted == [] and "comments" in report["prs"][0]["detail"], report


def test_b1_the_comment_query_asks_for_the_attribution_fields():
    q = adversary_marker.COMMENTS_QUERY
    for field in ("fullDatabaseId", "body", "author { __typename login }", "editor { __typename login }",
                  "lastEditedAt", "includesCreatedEdit", "userContentEdits(first: 100)", "totalCount",
                  "pageInfo { hasNextPage endCursor }", "after: $cursor"):
        assert field in q, field


def test_b1_an_edited_pr_body_with_a_deleted_editor_is_not_the_owners():
    second = {"json": {"repository": {"pullRequest": {
        "state": "OPEN", "headRefOid": H1, "body": marker("APPROVE", H1), "authorAssociation": "OWNER",
        "author": {"login": "djbclark"}, "editor": None, "lastEditedAt": EDITED_AT}}}}
    rc, report, api = run_ev(wr_event(), serve(7, marker("APPROVE", H1), second=second))
    assert api.posted[0]["state"] == "failure" and report["prs"][0]["outcome"] == "untrusted", report


@pytest.mark.parametrize("editor_shape", ["missing", {}, {"login": None}, {"login": ""}])
def test_b1_unknown_body_editor_cannot_inherit_owner_when_timestamp_is_null(editor_shape):
    second = gql_doc(body=marker("APPROVE", H1))
    pr = second["json"]["repository"]["pullRequest"]
    if editor_shape == "missing":
        del pr["editor"]
    else:
        pr["editor"] = editor_shape
    rc, report, api = run_ev(wr_event(), serve(7, marker("APPROVE", H1), second=second))
    assert rc == 0, report
    assert api.posted[0]["state"] == "failure", report
    assert report["prs"][0]["outcome"] == "untrusted", report


def test_b1_explicit_never_edited_owner_body_still_approves():
    rc, report, api = run_ev(wr_event(), serve(7, marker("APPROVE", H1),
                                             second=gql_doc(body=marker("APPROVE", H1))))
    assert rc == 0, report
    assert api.posted[0]["state"] == "success", report


# ---- B2 (Codex review, 2026-11-07): both shared-head lookups read every page -----------------------------------------

def _shared_head_answers(page2: list | dict | None, sibling: str = marker("BLOCK", H1)) -> dict:
    """PR 1..30 open at H1 and approved, 70 merged/closed/other-repo/other-head noise filling page 1, and on page 2
    PR 99 at H1 carrying SIBLING (absent when PAGE2 is given)."""
    page1 = [pull_entry(n, H1) for n in range(1, 31)]
    page1 += [pull_entry(100 + i, H1, state="closed") for i in range(60)]
    page1 += [pull_entry(200 + i, H1, repo="someone/fork") for i in range(5)]
    page1 += [pull_entry(300 + i, H2) for i in range(5)]
    answers = {commits_key(H1, 1): [{"json": page1}],
               commits_key(H1, 2): page2 if page2 is not None else [{"json": [pull_entry(99, H1),
                                                                               pull_entry(98, H1, state="closed")]}]}
    for n in [*range(1, 31), 99]:
        answers.update(serve(n, marker("APPROVE", H1) if n != 99 else sibling))
    return answers


@pytest.mark.parametrize("name,event", [("workflow_dispatch", dispatch(1)), ("workflow_run", wr_event(prs=(1,)))])
def test_b2_a_block_sibling_on_page_two_of_the_head_lookup_fails_the_status(name, event):
    rc, report, api = run_ev(event, _shared_head_answers(None), name=name)
    assert rc == 0, report
    assert api.calls[commits_key(H1, 2)] == 1, "page 2 must be requested"
    assert [r["pr"] for r in report["prs"]] == [*range(1, 31), 99], "noise is filtered, page 2's open PR is judged"
    assert [p["state"] for p in api.posted] == ["failure"]
    assert "not all approve" in api.posted[0]["description"]


def test_b2_every_page_approved_posts_success():
    rc, report, api = run_ev(dispatch(1), _shared_head_answers(None, marker("APPROVE", H1)), name="workflow_dispatch")
    assert rc == 0 and [p["state"] for p in api.posted] == ["success"], report


@pytest.mark.parametrize("page2", [[{"error": "HTTP 502"}], [{"json": {"message": "nope"}}], [{"json": ["x"]}],
                                   [{"json": None}]], ids=["http-error", "not-a-list", "bad-entry", "null"])
@pytest.mark.parametrize("name,event", [("workflow_dispatch", dispatch(1)), ("workflow_run", wr_event(prs=(1,)))])
def test_b2_an_unreadable_page_of_the_head_lookup_fails_closed(page2, name, event):
    rc, report, api = run_ev(event, _shared_head_answers(page2), name=name)
    assert rc == 2 and api.posted == [], report
    rc, out = adversary_marker.resolve(name, event, REPO_A, adversary_marker.CannedApi(_shared_head_answers(page2)))
    assert rc == 2 and "error" in out


def test_b2_the_head_lookup_page_cap_fails_closed(monkeypatch):
    monkeypatch.setattr(adversary_marker, "PULL_PAGES_MAX", 1)
    rc, report, api = run_ev(dispatch(1), _shared_head_answers(None), name="workflow_dispatch")
    assert rc == 2 and api.posted == [] and "not read in full" in report["error"], report


def test_b2_the_pulls_head_fallback_reads_every_page():
    ev = wr_event(prs=(), head_branch="feature/x", head_repository={"owner": {"login": "contrib"}})
    key = f"GET repos/{REPO_A}/pulls?state=open&head=contrib:feature/x&per_page=100&page="
    answers = {commits_key(H1): [{"json": []}],
               key + "1": [{"json": [{"number": 500 + i, "state": "open", "head": {"sha": H2}} for i in range(100)]}],
               key + "2": [{"json": [{"number": 11, "state": "open", "head": {"sha": H1}}]}],
               **serve(11, marker("BLOCK", H1))}
    rc, report, api = run_ev(ev, answers)
    assert rc == 0 and report["found_by"] == "pulls?head=" and api.calls[key + "2"] == 1, report
    assert [r["pr"] for r in report["prs"]] == [11] and api.posted[0]["state"] == "failure"
    answers[key + "2"] = [{"json": {"message": "nope"}}]
    rc, report, api = run_ev(ev, answers)
    assert rc == 2 and api.posted == [], report
