#!/usr/bin/env python3
"""adversary_marker: read the adversary's verdict marker from a PR body and judge it against the PR head.

  adversary_marker.py --body-file FILE --head SHA
      print the verdict JSON; exit 0 APPROVE for this head, 1 BLOCK / other head / missing,
      2 malformed or unreadable (fail closed)
  adversary_marker.py --event FILE [--event-name NAME] [--repo OWNER/NAME] [--resolve | --prs LIST [--at-head SHA]]
                      [--api-answers FILE]
      what `.github/workflows/adversary-marker.yml` runs. `--resolve` (its first job) finds the PRs the event is
      about, every open PR at the same head included, and writes `matrix=` / `has_work=` to $GITHUB_OUTPUT (one
      cell per head; the second job's concurrency group is `adversary-marker-<head>`); `--prs LIST --at-head SHA`
      (each matrix cell) reads
      each PR's body and head through the API, decides, re-reads the head, body, author, last editor and the PR's
      issue comments, and posts ONE `adversary-marker` commit status per head: success only when every open PR at
      it is approved. An owner-authored PR is approved by default (operator 2026-11-10: trust the owner and AIs
      they run under that login) — no APPROVE marker required; an explicit body APPROVE still counts when its
      last editor is the owner or BODY_TRUSTED_EDITOR_LOGINS. Any other PR is approved only by a live APPROVE
      in an issue comment the owner posted (not via a GitHub App) and nobody but the owner ever edited
      (GraphQL `editor` and `userContentEdits`; unknown attribution fails). A BLOCK or malformed marker in the
      body or any comment fails it. MARKER_POST_AS=check-run posts a check run instead. `--api-answers` serves
      canned API answers from a JSON file and prints the status it would post instead of posting (the tests' entry)

The marker (docs/code-review.md rule 1, its five properties):

    <!-- adversary-verdict:v1 {"verdict":"APPROVE"|"BLOCK","head":"<40-hex>"} -->

The parser below (from the "adversary verdict" banner to `adversary_from_doc`) is the removed PR
waiter's (its lines 263-1047), moved here UNCHANGED on 2026-11-06 (slim-down E8, docs/slim/reports/wave4-E8.md):
three adversary rounds found false APPROVEs and a hidden BLOCK in earlier versions, so the port is judged
by the waiter's marker tests, which moved with it to `tests/test_adversary_marker.py` and pass unchanged.
`gate()` is the adversary branch of the waiter's `assess()`, also unchanged except that an unreadable document is named `adversary-unreadable`. The new
code is the event handling at the end (`find_prs`, `decide`, `judge_pr`, `run_event`).

Trust model of the Action (PLAN E8, amended by the Wave 4 research, 2026-11-06): the workflow runs on
`workflow_run` (completion of `Tests`) and `workflow_dispatch`, so the workflow file and this module come
from the DEFAULT branch, never from the PR; nothing from the PR is checked out or executed; the PR body
and head are read through the API with the job's read-only `GITHUB_TOKEN`; the status is posted with a
token of the `ade-merge-gate` GitHub App (`STATUS_TOKEN`), whose key lives in the `merge-gate`
environment that only `master` can deploy to, and the ruleset pins the required check to that App's
`integration_id`, so a status a PR's own workflow posts under the same context does not satisfy it.
GitHub artifacts **not** from the repository owner are untrusted data (operator, 2026-11-07; restated
2026-11-10: distrust only what does not come from the owner or AIs they run). Body, title, commits, branch
name, comments and check output are read, never executed or interpolated. Owner-authored PRs (the owner's
login, including Cloud Agents acting under it) are trusted by default: `decide` succeeds without an APPROVE
marker (2026-11-10). Outside / MEMBER / COLLABORATOR PRs still need a live APPROVE in an owner issue comment
that no GitHub App posted and no one but the owner edited (`_pr_comments_trusted`, `decide`). An explicit
APPROVE in an owner PR body still counts when the last editor is the owner or BODY_TRUSTED_EDITOR_LOGINS;
the allowlist does not help an outside PR. The owner's edit of an outside body never makes a hidden body
APPROVE count. A BLOCK naming the head counts in the body or any comment, whoever wrote it.

Python 3.9+ (the Mac's stock python3 and the Actions runner's); stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

CONTEXT = "adversary-marker"

# Owner-PR body last editors that may leave a live APPROVE trusted (2026-11-09). Compared
# case-insensitively to GraphQL `editor.login`. Does NOT approve outside/MEMBER/COLLABORATOR
# PRs. Keep this list short: each entry is a residual "our App was steered into writing APPROVE"
# surface, mitigated by the process rule that agents never write a live marker.
BODY_TRUSTED_EDITOR_LOGINS = frozenset({
    "cursor",  # Cursor GitHub App / Cloud Agent body edits (PR 318, 2026-11-08)
})
SHA40 = re.compile(r"^[0-9a-f]{40}$")

# Exact docs-template JSON (AGENTS.md / PR-body examples). Invalid JSON on purpose (`APPROVE"|"BLOCK`);
# agents often leave it unfenced. Treat as documentation, never malformed (2026-11-10, #484).
_DOCS_TEMPLATE_JSON_COMPACT = '{"verdict":"APPROVE"|"BLOCK","head":"<40-hex>"}'


def _is_docs_template_json(raw: str) -> bool:
    """True for the canonical documentation marker payload (whitespace-insensitive)."""
    return re.sub(r"\s+", "", raw or "") == _DOCS_TEMPLATE_JSON_COMPACT


# ---- adversary verdict ----------------------------------------------------------------------------

# The adversary's verdict is read from a MACHINE-READABLE MARKER in the PR body, never from prose:
#
#     <!-- adversary-verdict:v1 {"verdict":"APPROVE"|"BLOCK","head":"<40-hex>"} -->
#
# WHY A MARKER AND NOT PROSE (2026-10-25, after two adversary rounds):
# The first version parsed English. Round 1 found six false APPROVEs and five false MISSES. It was
# patched and 14 tests added; round 2 found fourteen NEW false APPROVEs, including a BLOCK silently
# deleted whenever its reason contained "never", "must not", or named another reviewer. The lesson is
# structural, not a missing case: **the artefact under test was a claim about English**, and no set of
# heuristics makes that correct, because correctness would mean "no sentence anyone could write defeats
# it" - an unbounded set. A filter must only ever DOWNGRADE; the prose version could delete a BLOCK.
#
# THE PRECEDENT IS THE HOUSE'S OWN: AGENTS.md rule 9 reads Codex's review state from
# `<!-- codex-review-state:v1 {...} -->` and matches the `:v1` SUFFIX deliberately (a waiter whose regex
# lacked it saw no state on PR 12 and ran its full 30 minutes). Same shape here, on purpose.
#
# THE PROPERTIES, each of which a test covers:
#   1. `:v1` is part of the match. A near-miss spelling (`adversary-verdict`, `adversary_verdict`, a
#      case variant, a dropped `:`) is NOT this marker: it is `adversary-malformed`, never a default
#      and never silently absent.
#   2. A missing or unknown `verdict` value is `adversary-malformed` too - never a default. Fail closed.
#   3. `head` must be 40 hex AND equal the PR head. Another head is `adversary-stale-or-blocked`, not a
#      pass, and the human line says "other head" rather than "missing".
#   4. A malformed marker is `adversary-malformed`, its own outcome, so a typo reads as a typo rather
#      than as an absence.
#   5. NEVER fall back to prose. No marker means "no machine-readable verdict", full stop; a fallback
#      would reintroduce the parser through the back door and the failure would be invisible again.
#   6. ASYMMETRIC, and this is the property the gate exists for: an APPROVE must be LIVE (outside code)
#      and name this head exactly; a BLOCK naming this head - full 40-hex, or a 7+ hex prefix of it with
#      or without a trailing `…`/`...` - is read from the RAW body, so no ordering, other field, warning,
#      code fence or strip bug can downgrade it (adversary review of 4a56c01, B1/B5c).
#   7. The strip may only REPLACE with spaces, never delete (bundled review of 66/67, C2): deletion
#      joined the text on either side, so a typo could be "repaired" into valid JSON nobody wrote.
#      Code is CommonMark's: equal-length runs per line, and a backtick in a backtick fence's info
#      string means inline code, not a fence (C2/C3). It also never changes the LENGTH, so every index
#      still points at the same character of the raw body (C2'). A rescued BLOCK still reports
#      `malformed` from the LIVE validation, so the rescue cannot launder a typo (C5).
#   8. The marker BOUNDARY is JSON-AWARE (bundled review of 66/67, C1 and C1'): a `<!--`, a `-->` or a
#      brace inside a JSON STRING is content, so a BLOCK whose `note` quotes the delimiter is still one
#      marker - in a fence, in the live text and in the raw-body rescue alike. Only a start whose JSON
#      does not balance falls back to a capture that may not cross another `<!--`, which is what stops
#      an unclosed start quoted in prose from swallowing the next marker. And masking may not "repair"
#      JSON: the marker's JSON is parsed exactly as written in the raw body. Backticks inside JSON
#      strings are content; outside strings they make JSON invalid, hence malformed (C2'). The rescue
#      scans every start outside validated JSON strings, with no `consumed` cursor (D1): a
#      candidate is accepted before its JSON is validated, so letting a rejected outer one hide the
#      BLOCK inside it read as a clean false APPROVE.
# A marker whose JSON is broken is still CAPTURED and then reported as `malformed`, never as an
# absence: a strict `{...}` regex cannot see a malformed marker at all, which would make a typo
# indistinguishable from "no verdict". The capture is the JSON-aware one below; only a start whose JSON
# does not balance falls back to a loose capture up to the closing `-->`.
#
# The BOUNDARY is JSON-AWARE (`_marker_spans`), never a regex. An UNCLOSED start quoted in prose -
# `Every marker begins <!-- adversary-verdict:v1` - used to run to the NEXT `-->`, swallowing the BLOCK
# that followed, and `findall` resumed past it: the body read as a live APPROVE, merge_ready: true
# (bundled review, C1). Tempering the REGEX fixed that and broke the mirror case: a marker whose JSON
# `note` reads `"literal <!-- x"` was then invisible to the raw-body rescue, so a BLOCK vanished again
# (C1', a fail-open the lead reproduced). So the scanner walks the JSON object from each canonical
# start with string and escape awareness - `<!--`, `-->` and braces inside a string are CONTENT - and
# only a start whose JSON does not balance falls back to a TEMPERED capture that may not cross another
# `<!--`, which is what keeps C1's prose-swallow closed. Both directions are pinned by tests.
CANONICAL_START_RE = re.compile(r"<!--\s*adversary-verdict:v1")
# A marker START with no closing `-->` is invisible to `_marker_spans`, and GitHub renders an unclosed
# `<!--` as a comment to the end of the body, so a human does not see it either. Count the starts and
# compare with the matches: any excess is malformed (adversary review, A2).
#
# WIDENED (adversary review of 4a56c01, B2): a `:`-anchored start missed `adversary-verdict {...}`
# and `adversary_verdict:v1 ...`, so a TYPO beside a valid APPROVE was neither seen nor reported and
# the body read as approved. Any near-miss now counts as a start, and a start that `_marker_spans`
# cannot capture is malformed - a typo reads as a typo. The WIDE pattern only COUNTS starts; only
# `CANONICAL_START_RE` may yield a marker, so a near-miss spelling is never parsed into a verdict.
MARKER_START_RE = re.compile(r"<!--\s*adversary[-_ ]?verdict\b", re.IGNORECASE)
HEX40 = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
# A shortened sha is what agents actually type (adversary review of 4a56c01, B1): the marker spec asks
# for 40 hex, but a verdict pasted from a terminal routinely reads `4a56c01db7c2…`. Seven is git's own
# minimum abbreviation, so anything shorter is not a claim about a commit at all. The cap is 40, not 39
# (bundled review of 66/67, C4): a FULL sha carrying a trailing `…` was legitimate per the documented
# property and read as malformed. At equal length `startswith` is equality, so another commit still
# cannot match.
SHORT_HEX_RE = re.compile(r"[0-9a-f]{7,40}", re.IGNORECASE)


def _strict_object(pairs):
    """`object_pairs_hook` that rejects a DUPLICATE key.

    Without it, `{"verdict":"BLOCK","head":H,"verdict":"APPROVE"}` is read last-wins, so a BLOCK is
    silently downgraded by a second key (adversary review, A3).
    """
    seen = set()
    for k, _ in pairs:
        if k in seen:
            raise ValueError(f"duplicate key {k!r}")
        seen.add(k)
    return dict(pairs)


def _is_placeholder(sha: object) -> bool:
    """True only for the TEMPLATE's own placeholder head, never for a real-but-shortened sha.

    Narrowed after the re-stamp review (R3a): `"..." in sha or "…" in sha or "<" in sha` also matched
    `b50521af22b1…`, so a real BLOCK typed with a shortened sha was silently reclassified as
    "documentation" and stopped blocking. A placeholder is the whole value, and carries no hex run.
    """
    if not isinstance(sha, str):
        return False
    if not re.fullmatch(r"<[^<>]*>|…|\.\.\.", sha.strip()):
        return False
    return not re.search(r"[0-9a-fA-F]{7}", sha)


def _head_matches(sha: object, head: str) -> bool:
    """True when `sha` names `head` - exactly, or as a shortened sha an agent actually typed.

    WHY (adversary review of 4a56c01, B1): the spec asks for 40 hex, but a verdict copied from a
    terminal carries `4a56c01db7c2…`. The raw-body pass below is what makes a BLOCK unhidable, and it
    was a FULL-sha-only rescue, so every shortened BLOCK depended on the stripper being right - and
    four ordinary Markdown shapes made it wrong (indented fence line, odd fence counts, mixed fence
    characters, an unterminated fence). A shortened sha is therefore matched by PREFIX here.

    A 40-hex value of another commit is still another head: the prefix comparison runs against a head of
    the same length, so only a value that is a strict prefix of `head` - or `head` itself - can match,
    and the placeholder template (`<40-hex>`) carries no hex run of 7 and never matches.

    A FULL sha with a trailing `…`/`...` counts too (bundled review of 66/67, C4): the ellipsis is
    stripped before the comparison, and the run length is capped at 40 so a 40-hex value survives
    `fullmatch`; at equal length `startswith` is equality, so a different commit still cannot match.
    """
    if not isinstance(sha, str):
        return False
    s = sha.strip()
    if s.lower() == head.lower():
        return True
    for suffix in ("\u2026", "..."):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    s = s.strip().lower()
    return bool(SHORT_HEX_RE.fullmatch(s)) and head.lower().startswith(s)


def _mask_spans(line: str) -> str:
    """Blank every code span on ONE line, CommonMark 6.1's equal-length backtick runs (review C2).

    WHY (bundled adversary review of 66/67, C2): the old stripper used two fixed regexes -
    ``` ``[^`\\n]+`` ``` then `` `[^`\\n]+` `` - and neither can see a DOUBLE-backtick span that CONTAINS
    a single backtick (`` ``literal `X` `` `` is ONE span in CommonMark). The single-backtick regex then
    matched from the inner backtick and left the outer delimiters in place, so a marker inside such a
    span stayed LIVE and a false APPROVE came out: `merge_ready: true` from a body that only QUOTED a
    marker.

    Now a span opens with a run of n backticks and closes at the next run of EXACTLY n; the content may
    contain backticks of any other run length, and an unmatched run is literal text (which is what
    CommonMark says). Replaced by SPACES of the same width, never deleted: deletion would concatenate
    the text on either side, so a body could be "repaired" into different JSON - an author's typo must
    stay a typo.
    """
    out: list[str] = []
    i, n = 0, len(line)
    while i < n:
        if line[i] != "`":
            out.append(line[i])
            i += 1
            continue
        j = i
        while j < n and line[j] == "`":
            j += 1
        run = j - i
        close = -1
        k = j
        while True:
            m = line.find("`" * run, k)
            if m == -1:
                break
            end = m + run
            if (m > 0 and line[m - 1] == "`") or (end < n and line[end] == "`"):
                # Part of a longer run: only an EXACT run closes a span.
                while end < n and line[end] == "`":
                    end += 1
                k = end
                continue
            close = m
            break
        if close == -1:
            out.append(line[i:j])
            i = j
        else:
            start = i
            i = close + run
            out.append(" " * (i - start))
    return "".join(out)


def _strip_code(body: str) -> str:
    """Blank fenced blocks and inline code spans before matching markers, CommonMark-faithfully.

    WHY (adversary review, B1): a PR that DOCUMENTS the format quotes the template in backticks or a
    fence. Reading those as live markers made every such PR unmergeable (`malformed` blocks by
    default), which broke the report-only-by-default property in practice. The review also disposed of
    the counter-argument: the body is author-controlled, so an author who wants a BLOCK gone simply
    deletes it - the gate guards against MISTAKES, not forgery. Reading fences protected nothing and
    created false blocks.

    A placeholder head (`<40-hex>`) is documentation too, and is rejected in `adversary_verdict`.

    REWRITTEN CommonMark-FAITHFUL (adversary review of 4a56c01, B1). The first version toggled on every
    line whose `lstrip()` began with ``` or ~~~, so an ORDINARY structure over-stripped and blanked the
    rest of the body - and with it a BLOCK: a 4-space-indented fence line, a 4-backtick fence holding an
    odd number of 3-backtick lines, a `~~~` fence holding a ``` line, or an unterminated fence. An odd
    number of toggles left `in_fence` true to the end of the body.

    Now: a fence opens only at indent <= 3 (4+ spaces is an indented code block in CommonMark, not a
    fence), only when a backtick fence's INFO STRING holds no backtick (CommonMark 4.5 - otherwise the
    line is inline code, review C3), remembers its character and length, and closes only on the SAME
    character at >= that length with nothing but whitespace after it. Code spans are scanned per line,
    which is the shape `_mask_spans` implements for the equal-length runs.

    OFFSETS ARE EXACT, and that is a contract, not a detail (bundled review, C2'): every line is masked
    in place and the lines are rejoined with `"\n"` after splitting on `"\n"`, so the result is the same
    length as `body` and every index in it points at the same character of `body`. `splitlines()` would
    silently drop a trailing newline and rewrite `\r\n` as `\n`, shifting every offset after the first
    such line - and `adversary_verdict` relies on those offsets to parse the marker's JSON
    exactly as written in the raw body.

    HONEST ABOUT THE ERROR DIRECTION (review C3): an over-strip can still hide a MALFORMED or near-miss
    marker, and so lose its `malformed` warning; what it cannot do is lose a BLOCK naming this head,
    because that is read from the RAW body. Every replacement is a same-width run of spaces, so the text
    outside code is byte-identical and no marker can be "repaired" into a different one; a live marker
    is parsed from the raw body. Backticks inside JSON strings are content; backticks outside
    strings make the JSON invalid. Masking never repairs JSON (C2').

    KNOWN LIMIT, accepted by djbclark at the bundled review of 66/67: a BLOCK whose head is MISTYPED -
    not a prefix of this head at all - and that sits inside code is documentation, so a body with such
    a quote beside a live APPROVE still reads as approved. Recognising it would mean guessing which
    quoted near-miss markers are claims, which is the unbounded English-parsing problem this design
    removed; a BLOCK that names this head is covered by the raw-body rescue above.

    KNOWN LIMITS, documented and deliberately NOT fixed (lead's ruling, C1a/b/c): code shapes outside
    "fenced blocks and inline spans" are still read as LIVE markers, so a quoted real APPROVE for this
    head in one of them approves the PR. Reproduced for three shapes: (a) an INLINE SPAN BROKEN ACROSS A
    LINE, (b) a 4-SPACE INDENTED CODE BLOCK, (c) a FENCED BLOCK INSIDE A BLOCKQUOTE. Each is a false
    APPROVE only in the direction that needs a human to paste our own template; none can hide a BLOCK,
    which is the asymmetry this gate relies on.

    KNOWN FAIL-CLOSED LIMIT (lead decision, PR 175 round 9): a trailing-comma
    documentation marker whose note quotes a marker start and whose nested metadata
    names a same-head BLOCK can be reported as malformed BLOCK. Recovery deliberately
    protects only strictly valid JSON strings; widening protection for readable
    prefixes hid real BLOCKs inside broken envelopes. This false BLOCK cannot approve
    a PR or suppress a same-head BLOCK; keep it fail-closed rather than repairing it.
    """
    out: list[str] = []
    fence = ""  # the open fence: "" when outside, else its character
    fence_len = 0
    for line in body.split("\n"):
        # Indentation is measured with tabs expanded (a tab is four columns), but the TEXT kept is the
        # original, so every masked line keeps its own length.
        lead = line[: len(line) - len(line.lstrip(" \t"))]
        indent = len(lead.expandtabs(4))
        stripped = line[len(lead):]
        run = len(stripped) - len(stripped.lstrip(stripped[0])) if stripped else 0
        char = stripped[0] if stripped else ""
        if fence:
            if (indent <= 3 and char == fence and run >= fence_len
                    and not stripped[run:].strip()):
                fence, fence_len = "", 0
            out.append(" " * len(line))
            continue
        if indent <= 3 and char in "`~" and run >= 3:
            # An INFO STRING after the fence run is allowed (```` ```sh ````); only a closing fence must
            # be bare. A backtick in a BACKTICK fence's info string makes it inline code, not a fence.
            if char == "`" and "`" in stripped[run:]:
                out.append(_mask_spans(line))
                continue
            fence, fence_len = char, run
            out.append(" " * len(line))
            continue
        out.append(_mask_spans(line))
    return "\n".join(out)


def _json_object_end(text: str, i: int) -> int:
    """Index just past the JSON object that starts at `text[i] == '{'`, or -1 if it never balances.

    String- and escape-aware ON PURPOSE (bundled review, C1'): a `{`, `}` or `<!--` inside a JSON
    string is CONTENT, so a marker whose `note` quotes the delimiter still has findable boundaries. A
    regex cannot express this, which is why the boundary moved here.
    """
    depth = 0
    in_str = False
    escaped = False
    k, n = i, len(text)
    while k < n:
        c = text[k]
        if in_str:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return k + 1
        k += 1
    return -1


_MARKER_WS = " \t\r\n"


def _marker_spans(text: str, *, nested: bool = False) -> list[tuple[int, int, int]]:
    """Every CANONICAL marker start in `text`, as `(start, json_start, json_end)` offsets.

    `start` is the `<!--`; the captured JSON is `text[json_start:json_end]`. Only
    `adversary-verdict:v1` exactly (lowercase) can yield a span: a near-miss spelling is COUNTED by
    `_classify_starts` and never parsed, so a typo cannot become a verdict.

    TWO BOUNDARY RULES, and both are load-bearing (bundled review of 66/67, C1 and C1'):
    1. The `-->` is looked for AFTER a BALANCED JSON OBJECT, so a `<!--` inside a string is content and
       a BLOCK whose note quotes the delimiter is still one marker (C1'). A tempered regex got this
       backwards and lost that BLOCK entirely.
    2. Only the FALLBACK - a start whose JSON does not balance - is a loose capture, and it may not
       cross another `<!--` (C1). That is what stops an unclosed start quoted in prose from running to
       the next marker's `-->`, swallowing the BLOCK that follows.

    A start with neither shape is not a marker at all; `_classify_starts` reports it as a typo.

    THE `consumed` CURSOR IS FOR READING, NOT FOR FINDING (bundled review, D1). A candidate is
    accepted as soon as its braces balance and a `-->` follows - BEFORE anyone knows whether that JSON
    is valid - so a start nested inside a REJECTED outer candidate is skipped forever. That is correct
    for the live path, where an accepted marker's interior is content; it was a fail-open in the
    raw-body BLOCK rescue, which iterated these same spans, `continue`d on the outer parse failure and
    never revisited a real same-head BLOCK inside the region: `verdict=APPROVE, malformed=False`. The
    rescue therefore calls this with `nested=True`, which drops the cursor and reports one span per
    start. No false BLOCK is introduced: a marker quoted inside a `note` is ESCAPED in the body
    (`{\\"verdict\\":...`), so its slice cannot parse, and an unescaped quote inside a JSON string
    cannot exist in valid JSON at all.
    """
    spans: list[tuple[int, int, int]] = []
    n = len(text)
    # A candidate that starts INSIDE a marker already accepted is content - a `note` documenting the
    # format quotes the start - so the scan resumes after that marker's `-->` (C1'). The raw-body
    # rescue opts out (`nested=True`, D1): there, a rejected outer candidate must not hide the BLOCK
    # inside it.
    consumed = 0
    for m in MARKER_START_RE.finditer(text):
        if not nested and m.start() < consumed:
            continue
        # The WIDE start only locates the candidate; the canonical one says where `:v1` ends, and the
        # JSON begins after that.
        cm = CANONICAL_START_RE.match(text, m.start())
        if not cm:
            continue
        q = cm.end()
        while q < n and text[q] in _MARKER_WS:
            q += 1
        if q < n and text[q] == "{":
            end = _json_object_end(text, q)
            if end != -1:
                r = end
                while r < n and text[r] in _MARKER_WS:
                    r += 1
                if text.startswith("-->", r):
                    spans.append((m.start(), q, end))
                    consumed = r + 3
                    continue
        rest = text[cm.end():]
        close = rest.find("-->")
        nxt = rest.find("<!--")
        if close != -1 and (nxt == -1 or close < nxt):
            spans.append((m.start(), cm.end(), cm.end() + close))
            consumed = cm.end() + close + 3
    return spans


def _classify_starts(text: str) -> tuple[int, int]:
    """Count marker STARTS that `_marker_spans` cannot capture: `(unclosed, wrong_form)`.

    A start is any near-miss spelling (`adversary-verdict`, `adversary_verdict`, a case variant, a
    dropped `:`). It is `wrong_form` when a `-->` closes it, because then it really is a marker and only
    its spelling is wrong; it is `unclosed` when no `-->` follows before the next `<!--`, in which case
    GitHub renders the rest of the body as a comment and a human cannot see it either.
    """
    spans = _marker_spans(text)
    valid = {start for start, _js, _je in spans}

    def _inside_a_marker(pos: int) -> bool:
        # A marker-shaped text INSIDE another marker's JSON (a `note` documenting the format) is content,
        # not a start of its own; counting it would make a correct body `malformed`.
        return any(js <= pos < je for _s, js, je in spans)

    unclosed = wrongform = 0
    for m in MARKER_START_RE.finditer(text):
        if m.start() in valid or _inside_a_marker(m.start()):
            continue
        rest = text[m.end():]
        close = rest.find("-->")
        nxt = rest.find("<!--")
        if close != -1 and (nxt == -1 or close < nxt):
            wrongform += 1
        else:
            unclosed += 1
    return unclosed, wrongform


def _marker_tokens(text: str):
    """Lex recovery text without interpreting string contents as structure."""
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        start = i
        if text[i] == '"':
            i += 1
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                elif text[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            try:
                value = json.loads(text[start:i])
            except ValueError:
                value = None
            yield "string", value, start
        elif text[i] in "{}[]:,":
            i += 1
            yield text[start], None, start
        else:
            i += 1
            while i < len(text) and not text[i].isspace() and text[i] not in '{}[]:,"':
                i += 1
            yield "other", None, start


def _top_level_marker_fields(text: str) -> tuple[list[tuple[str, str]], bool]:
    """Recover string pairs at object depth one, even with duplicate keys or trailing commas.

    Return fields and whether their boundaries are readable. Trailing commas and
    duplicate keys retain clear boundaries; broken strings/nesting do not. This
    never repairs the JSON used to validate or approve a marker.
    """
    tokens = list(_marker_tokens(text))
    # Trailing commas and duplicate keys have unambiguous field boundaries.
    # Everything else must parse before we trust the recovered object depth.
    trailing = {tokens[i][2] for i in range(len(tokens) - 1)
                if tokens[i][0] == "," and tokens[i + 1][0] in ("}", "]")}
    structural = "".join(c for i, c in enumerate(text) if i not in trailing)
    try:
        json.loads(structural)
        certain = True
    except (ValueError, RecursionError):
        certain = False
    if not tokens or tokens[0][0] != "{":
        return [], certain
    fields = []
    stack = []
    i = 0
    while i < len(tokens):
        kind, value, _ = tokens[i]
        if kind in ("{", "["):
            stack.append(kind)
        elif kind in ("}", "]"):
            if not stack or stack[-1] != {"}": "{", "]": "["}[kind]:
                break  # uncertain depth cannot supply a top-level field
            stack.pop()
            if not stack:
                break
        elif (stack == ["{"] and kind == "string" and i + 2 < len(tokens)
              and tokens[i + 1][0] == ":" and tokens[i + 2][0] == "string"):
            other = tokens[i + 2][1]
            if isinstance(value, str) and isinstance(other, str):
                fields.append((value, other))
            i += 3  # consume the value too: a string value cannot become another key
            continue
        i += 1
    return fields, certain


def adversary_verdict(body: str, head: str) -> dict:
    """Read the adversary verdict marker from a PR body and decide whether it names this head.

    Returns {"present", "verdict", "quoted_sha", "matches_head", "conflict", "malformed", "detail"}.
    Never inspects prose: a body full of verdict-shaped sentences and no marker is simply
    `present: False`, which is the point.
    """
    if not body:
        return {"present": False, "verdict": None, "quoted_sha": None, "matches_head": False,
                "conflict": False, "malformed": False, "detail": "no PR body"}

    # Strip fenced blocks and inline code FIRST: a PR documenting the format must not trip its own
    # gate (adversary review, B1).
    text = _strip_code(body)

    spans = _marker_spans(text)
    unclosed, wrongform = _classify_starts(text)

    # VALIDATION COMES FIRST (bundled adversary review of 66/67, C5). Before this, the raw-body BLOCK
    # rescue returned `malformed: False` unconditionally, so a BLOCK beside a LIVE malformed marker
    # reported a clean block and the typo vanished: the body looked like one assertable verdict. A
    # malformed marker is never ok, so the block must carry the flag too. Every early return below
    # reports the `problems` collected here for the same reason.
    problems: list[str] = []
    if wrongform:
        problems.append(f"{wrongform} marker(s) that are not `adversary-verdict:v1` (exact, "
                        f"lowercase)")
    if unclosed:
        problems.append(f"{unclosed} marker(s) with no closing `-->`")

    # Validate EVERY LIVE marker, so a malformed one beside a good one is still reported.
    parsed: list[dict] = []
    placeholders = 0
    docs_templates = 0
    for _start, jstart, jend in spans:
        # Parse JSON as written: backticks inside a JSON string are content, while
        # backticks outside strings must never be masked into valid JSON.
        raw = body[jstart:jend]
        # Unfenced PR-template / AGENTS.md example: not a verdict, not a typo (2026-11-10).
        if _is_docs_template_json(raw):
            docs_templates += 1
            continue
        try:
            doc = json.loads(raw, object_pairs_hook=_strict_object)
        except ValueError as e:
            problems.append(f"marker is not valid JSON: {e}")
            continue
        if not isinstance(doc, dict):
            problems.append("marker is not a JSON object")
            continue
        verdict = doc.get("verdict")
        sha = doc.get("head")
        # EXACT match: the spec says "APPROVE"|"BLOCK". A lowercase or odd-cased value is outside it
        # and fails closed (adversary review, A5).
        if verdict not in ("APPROVE", "BLOCK"):
            problems.append(f"verdict must be exactly APPROVE or BLOCK, got {verdict!r}")
            continue
        if isinstance(sha, str) and HEX40.match(sha):
            parsed.append({"verdict": verdict, "head": sha.lower()})
            continue
        # A BLOCK naming this head by a SHORTENED sha is the raw-body rescue's own shape, not a typo:
        # it is matched by `_head_matches` below and is therefore NOT a problem. Every other unusable
        # head stays malformed.
        if verdict == "BLOCK" and _head_matches(sha, head):
            continue
        # ASYMMETRIC RULE (adversary review, R3a/R3b): only an APPROVE may be skipped as
        # documentation, and only when its head is the TEMPLATE's own placeholder. A BLOCK with an
        # unusable head stays malformed, because downgrading a BLOCK is the failure this gate
        # exists to prevent - and agents routinely shorten a sha with an ellipsis.
        if verdict == "APPROVE" and _is_placeholder(sha):
            placeholders += 1
            continue
        problems.append(f"head must be a 40-hex sha, got {sha!r}")

    # ASYMMETRIC (adversary review, R3b): a BLOCK naming THIS head counts WHEREVER it appears, the raw
    # body included. An APPROVE must be live (outside code) so documentation cannot approve; a BLOCK
    # must not be hidable by an over-strip bug, a stray backtick, or a malformed fence. Both directions
    # fail closed, which is the point.
    #
    # SHORTENED shas are matched by prefix (adversary review of 4a56c01, B1): a full-sha-only rescue left
    # every `4a56c01db7c2…` BLOCK dependent on the stripper, and four ordinary Markdown shapes defeated
    # it. `_head_matches` is the whole rescue now, so no strip bug can lose a BLOCK. `malformed` still
    # comes from the live validation above (C5): the rescue may not launder a typo.
    #
    # The SAME JSON-aware scanner finds the markers here (bundled review, C1'): a tempered regex made a
    # BLOCK whose JSON `note` quoted `<!--` invisible to this loop, so the rescue could not see the one
    # thing it exists for. `_marker_spans` reads `<!--` inside a string as content, in the raw body
    # exactly as in the stripped text. It runs with `nested=True` (bundled review, D1): the live scan's
    # `consumed` cursor skips starts inside a candidate it has already accepted, and acceptance happens
    # before the JSON is validated - so a real same-head BLOCK nested inside an INVALID outer candidate
    # was invisible here and the body read as a clean APPROVE. The rescue rescans starts outside valid JSON strings; escaped
    # JSON quoted in a `note` still cannot parse, so no false BLOCK arrives that way.
    # A typo cannot hide a same-head BLOCK in code (2026-10-30). Scan wide
    # starts too; only actual BLOCK fields plus a matching head trigger this
    # conservative fallback. Canonical valid markers retain their normal result.
    canonical = {(start, js, je) for start, js, je in _marker_spans(body, nested=True)}
    # A successfully parsed marker's JSON strings are metadata, never new markers.
    # Invalid outer candidates protect nothing: nested real BLOCKs must still be found.
    quoted_strings = []
    for _start, js, je in canonical:
        try:
            json.loads(body[js:je], object_pairs_hook=_strict_object)
        except ValueError:
            continue
        quoted_strings.extend((js + token.start(), js + token.end()) for token in
                              re.finditer(r'"(?:[^"\\]|\\.)*"', body[js:je]))
    for match in MARKER_START_RE.finditer(body):
        start = match.start()
        if any(lo <= start < hi for lo, hi in quoted_strings):
            continue
        # Live near-miss starts are already malformed; preserve their diagnostic
        # rather than promoting a typo to a verdict. Hidden ones need rescuing.
        if (text[start:match.end()] == body[start:match.end()]
                and not CANONICAL_START_RE.match(body, start)):
            continue
        # Discover the payload only inside this comment. Once JSON starts,
        # the existing JSON-aware scanner keeps delimiters in strings as content.
        canonical_start = CANONICAL_START_RE.match(body, start)
        payload_start = canonical_start.end() if canonical_start else match.end()
        comment_end = body.find("-->", payload_start)
        next_start = body.find("<!--", payload_start)
        # Bound discovery at the next start too: thousands of empty starts must
        # not repeatedly scan the remaining body. Allow the doubled-start typo.
        limit = comment_end if comment_end >= 0 else len(body)
        if next_start >= 0:
            if not re.compile(r"<!--\s*\{").match(body, next_start):
                limit = min(limit, next_start)
        payload = body[payload_start:limit]
        # Only an actual root array is documentation; a prose [label] before an
        # object is malformed syntax and cannot conceal its BLOCK.
        first = payload.lstrip()
        root_array = first.startswith("[")
        if root_array:
            # Comment delimiters inside array strings are JSON content. Find
            # the complete root before judging whether its structure is readable.
            array_start = payload_start + len(payload) - len(first)
            stack = []
            array_end = -1
            for kind, _value, offset in _marker_tokens(body[array_start:]):
                if kind in ("{", "["):
                    stack.append(kind)
                elif kind in ("}", "]"):
                    if not stack or stack[-1] != {"}": "{", "]": "["}[kind]:
                        break
                    stack.pop()
                    if not stack:
                        array_end = array_start + offset + 1
                        break
            root_array = False
            if array_end >= 0 and body[array_end:].lstrip().startswith("-->"):
                array_text = body[array_start:array_end]
                _, root_array = _top_level_marker_fields(array_text)
                if root_array:
                    quoted_strings.extend((array_start + token.start(), array_start + token.end())
                                          for token in re.finditer(r'"(?:[^"\\]|\\.)*"', array_text))
        offset = payload.find("{")
        js = payload_start + offset if offset >= 0 and not root_array else -1
        if js < 0:
            continue
        if (next_start >= 0 and next_start < js
                and body[next_start:js].strip() != "<!--"):
            continue
        je = _json_object_end(body, js)
        if je < 0:
            close = body.find("-->", js)
            je = close if close >= 0 else len(body)
        candidate = body[js:je]
        fields, certain = _top_level_marker_fields(candidate)
        fields = [(key.lower(), value) for key, value in fields]
        if not certain:
            # Broken quoting or nesting makes depth unknowable. Fail closed,
            # retaining exact head-value matching; valid metadata stays narrow.
            for key, value in re.findall(
                    r'"(verdict|head)"\s*:\s*("(?:[^"\\]|\\.)*")', candidate, re.I):
                try:
                    fields.append((key.lower(), json.loads(value, strict=False)))
                except ValueError:
                    continue
        if not any(key == "verdict" and value.upper() == "BLOCK" for key, value in fields):
            continue
        quoted_heads = [value for key, value in fields if key == "head"]
        # Preserve duplicate keys and conservative decorated/six-hex typo handling,
        # but only actual top-level head fields can name the reviewed revision.
        heads = (re.fullmatch(r"(?:sha\s+)?([0-9a-f]{6,40})(?:…|\.\.\.)?", value.strip(), re.I)
                 for value in quoted_heads)
        if not any(token and head.lower().startswith(token.group(1).lower()) for token in heads):
            continue
        try:
            doc = json.loads(candidate, object_pairs_hook=_strict_object)
        except ValueError:
            doc = None
        if ((start, js, je) in canonical and isinstance(doc, dict)
                and doc.get("verdict") == "BLOCK" and isinstance(doc.get("head"), str)
                and HEX40.fullmatch(doc["head"]) and not _head_matches(doc["head"], head)):
            continue  # a well-formed verdict for another head remains report-only
        if ((start, js, je) not in canonical or not isinstance(doc, dict)
                or doc.get("verdict") != "BLOCK" or not _head_matches(doc.get("head"), head)):
            return {"present": True, "verdict": "BLOCK", "quoted_sha": head,
                    "matches_head": True, "conflict": any(p["verdict"] == "APPROVE"
                    and p["head"] == head.lower() for p in parsed), "malformed": True,
                    "detail": "malformed same-head BLOCK in raw body"}
    for _start, jstart, jend in _marker_spans(body, nested=True):
        if any(lo <= _start < hi for lo, hi in quoted_strings):
            continue
        try:
            doc = json.loads(body[jstart:jend], object_pairs_hook=_strict_object)
        except ValueError:
            continue
        if isinstance(doc, dict) and doc.get("verdict") == "BLOCK":
            sha = doc.get("head")
            if _head_matches(sha, head):
                # Report a conflict if a live APPROVE for this head also exists: the raw-body path
                # must not lose the `conflict` flag that `assess` and the human line rely on.
                approves_here = False
                for _s2, js2, je2 in _marker_spans(text):
                    try:
                        d2 = json.loads(text[js2:je2], object_pairs_hook=_strict_object)
                    except ValueError:
                        continue
                    if (isinstance(d2, dict) and d2.get("verdict") == "APPROVE"
                            and _head_matches(d2.get("head"), head)):
                        approves_here = True
                        break
                exact = str(sha).strip().lower() == head.lower()
                return {"present": True, "verdict": "BLOCK", "quoted_sha": str(sha).strip().lower(),
                        "matches_head": True, "conflict": approves_here,
                        "malformed": bool(problems),
                        "detail": ("the body says BOTH BLOCK and APPROVE for this head - resolve it, "
                                   "the PR cannot be read as approved" if approves_here
                                   else "BLOCK for this head" if exact
                                   else f"BLOCK for this head, quoted as the shortened sha "
                                        f"{str(sha).strip()} (read from the raw body, so no "
                                        f"code-fence or strip bug can hide it)")}

    if not spans:
        if problems:
            # A marker START that is not a marker: malformed, NOT absent. A typo reads as a typo, and
            # the REASON is named (adversary review of 4a56c01, B3): an unclosed `<!--` and a marker
            # that is not exactly `adversary-verdict:v1` are different mistakes.
            why = []
            if wrongform:
                why.append(f"{wrongform} marker(s) that are not `adversary-verdict:v1` "
                           f"(exact, lowercase): a dropped `:`, a `_` or an odd case")
            if unclosed:
                why.append(f"{unclosed} marker(s) with no closing `-->` "
                           f"(an unclosed `<!--` runs to the end of the body)")
            return {"present": False, "verdict": None, "quoted_sha": None, "matches_head": False,
                    "conflict": False, "malformed": True,
                    "detail": "adversary-verdict marker is malformed: " + "; ".join(why)}
        return {"present": False, "verdict": None, "quoted_sha": None, "matches_head": False,
                "conflict": False, "malformed": False,
                "detail": "no adversary-verdict marker in the PR body (prose verdicts are not read)"}

    if not parsed:
        if (placeholders or docs_templates) and not problems:
            # Every marker was documentation (placeholder head and/or the APPROVE"|"BLOCK template).
            bits = []
            if placeholders:
                bits.append(f"{placeholders} marker(s) carry a placeholder head (<40-hex>)")
            if docs_templates:
                bits.append(f"{docs_templates} marker(s) are the docs template "
                            f'(verdict "APPROVE"|"BLOCK")')
            return {"present": False, "verdict": None, "quoted_sha": None, "matches_head": False,
                    "conflict": False, "malformed": False,
                    "detail": "; ".join(bits) + ": documentation, not a verdict"}
        # A marker was present but unusable: its OWN outcome, so a typo is visibly a typo.
        return {"present": False, "verdict": None, "quoted_sha": None, "matches_head": False,
                "conflict": False, "malformed": True,
                "detail": "adversary-verdict marker is malformed: " + "; ".join(problems)}

    for_marker = [p for p in parsed if p["head"] == head.lower()]
    blocks = [p for p in for_marker if p["verdict"] == "BLOCK"]
    approves = [p for p in for_marker if p["verdict"] == "APPROVE"]

    # INVARIANT, STATED ASYMMETRICALLY (adversary review of 4a56c01, B5c): a BLOCK naming this head -
    # full 40-hex, or a 7+ hex prefix of it with or without a trailing `…`/`...` - is read from the RAW
    # body above, so nothing downstream can downgrade it; an APPROVE must be live. If a body carries
    # both for this head it is a conflict, and the verdict reported is the BLOCK.
    if blocks:
        return {"present": True, "verdict": "BLOCK", "quoted_sha": blocks[0]["head"],
                "matches_head": True, "conflict": bool(approves), "malformed": bool(problems),
                "detail": ("the body says BOTH BLOCK and APPROVE for this head - resolve it, the PR "
                           "cannot be read as approved" if approves else "BLOCK for this head")}
    if approves:
        return {"present": True, "verdict": "APPROVE", "quoted_sha": approves[0]["head"],
                "matches_head": True, "conflict": False, "malformed": bool(problems),
                "detail": f"APPROVE for this head ({approves[0]['head'][:12]})"}

    # A valid marker, but for a different head. That is not a pass.
    other = parsed[0]
    return {"present": True, "verdict": other["verdict"], "quoted_sha": other["head"],
            "matches_head": False, "conflict": False, "malformed": bool(problems),
            "detail": f"marker names {other['head'][:12]}, which is NOT this head ({head[:12]})"}


def adversary_from_doc(doc: dict, head: str) -> dict:
    """Extract the adversary verdict from an ALREADY-FETCHED `pulls/{pr}` document.

    No API call: the poll keeps the document it fetches, so the verdict is always judged from the
    CURRENT body rather than a startup snapshot (a body edited from APPROVE to BLOCK during the wait
    must be seen).
    """
    labels = {l.get("name") for l in (doc.get("labels") or []) if isinstance(l, dict)}
    out = adversary_verdict(doc.get("body") or "", head)
    out["required_by_label"] = "adversary-required" in labels
    return out


# ---- the gate: the PR waiter's assess() adversary branch---------------------------------------------------

def gate(adversary: dict | None, adversary_required: bool = True) -> dict:
    """The removed PR waiter's `assess()` adversary branch, moved unchanged (the warning for an unreadable document is
    renamed `adversary-unreadable`). The Action always calls it with `adversary_required=True`: the ruleset
    makes the status required, so there is no report-only mode in CI. The flag stays so the moved tests,
    which pin the report-only default too, run unchanged.

    A FETCH FAILURE is its own outcome, never "missing": reporting an unknown as absent is how a missing
    gate reads as a passing one (adversary review, F5). A MALFORMED result is never ok, even when a valid
    APPROVE sits beside it: a typo in a BLOCK must not let the PR through (adversary review, A1).
    """
    blockers: list[str] = []
    adversary_warnings: list[str] = []
    if adversary is not None:
        fetch_failed = bool(adversary.get("fetch_failed"))
        malformed = bool(adversary.get("malformed"))
        ok = (not fetch_failed and not malformed and bool(adversary.get("matches_head"))
              and not str(adversary.get("verdict") or "").upper().startswith("BLOCK"))
        if not ok:
            if fetch_failed:
                adversary_warnings.append("adversary-unreadable")
            elif malformed:
                adversary_warnings.append("adversary-malformed")
            elif not adversary.get("present"):
                adversary_warnings.append("adversary-missing")
            else:
                adversary_warnings.append("adversary-stale-or-blocked")
            if adversary_required or fetch_failed or malformed:
                blockers.append(adversary_warnings[-1])
    else:
        # No verdict was collected at all: fail closed (the waiter reported the same case as fetch_failed).
        adversary_warnings.append("adversary-unreadable")
        blockers.append("adversary-unreadable")
    return {"merge_ready": not blockers, "merge_blockers": blockers,
            "adversary": adversary, "adversary_warnings": adversary_warnings,
            "adversary_required": adversary_required}


# One word per outcome, and the exit code of `--body-file` mode. `approve` iff gate() passes it.
EXIT_FOR = {"approve": 0, "block": 1, "other-head": 1, "missing": 1, "malformed": 2, "unreadable": 2, "untrusted": 1,
            "outside": 1, "edited": 1, "edit-unknown": 1}


def outcome(adversary: dict | None) -> str:
    """approve | block | other-head | missing | malformed | unreadable, derived from gate() so there is ONE
    predicate for a pass."""
    if gate(adversary, True)["merge_ready"]:
        return "approve"
    if adversary is None or adversary.get("fetch_failed"):
        return "unreadable"
    if adversary.get("malformed"):
        return "malformed"
    if not adversary.get("present"):
        return "missing"
    if adversary.get("matches_head") and str(adversary.get("verdict") or "").upper().startswith("BLOCK"):
        return "block"
    return "other-head"


def describe(word: str, head: str, where: str = "") -> str:
    """The status description (GitHub caps it at 140 characters). `where` names the source of the deciding marker when
    it is not the PR body ("comment" or "owner comment")."""
    label = {"approve": "APPROVE", "block": "BLOCK", "other-head": "verdict names another head",
             "missing": "no adversary-verdict:v1 marker", "malformed": "malformed marker",
             "unreadable": "PR unreadable", "untrusted": "marker not written by a trusted user",
             "outside": "outside PR: APPROVE only counts in an owner comment",
             "edited": "owner's APPROVE comment was edited by someone else",
             "edit-unknown": "owner's APPROVE comment has an unknown edit history"}.get(word, word)
    if where == "comment":
        label += " in a comment"
    elif where == "owner comment":
        label += " in an owner comment"
    elif where == "owner_pr":
        label = "owner-authored PR (marker optional)"
    return f"{label} at {head[:12]}"[:140]


# ---- the Action: event -> PR -> verdict -> status ------------------------------------------------------

class ApiError(Exception):
    pass


class Api:
    """GitHub REST over urllib. Reads use READ_TOKEN (the job's GITHUB_TOKEN, `pull-requests: read`); the
    one write, the commit status, uses STATUS_TOKEN (the ade-merge-gate App's installation token)."""

    def __init__(self, read_token: str, status_token: str, base: str = "https://api.github.com") -> None:
        self.read_token, self.status_token, self.base = read_token, status_token, base.rstrip("/")
        self.posted: list[dict] = []

    def _req(self, method: str, path: str, token: str, body: dict | None = None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(f"{self.base}/{path.lstrip('/')}", data=data, method=method)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raise ApiError(f"{method} {path}: HTTP {e.code}") from None
        except (urllib.error.URLError, OSError) as e:
            raise ApiError(f"{method} {path}: {e}") from None
        try:
            return json.loads(raw.decode() or "null")
        except ValueError as e:
            raise ApiError(f"{method} {path}: not JSON: {e}") from None

    def get(self, path: str):
        return self._req("GET", path, self.read_token)

    def graphql(self, query: str, variables: dict):
        doc = self._req("POST", "graphql", self.read_token, {"query": query, "variables": variables})
        if not isinstance(doc, dict) or doc.get("errors") or not isinstance(doc.get("data"), dict):
            raise ApiError(f"graphql: {str((doc or {}).get('errors') if isinstance(doc, dict) else doc)[:200]}")
        return doc["data"]

    def post_status(self, repo: str, sha: str, body: dict) -> None:
        if not self.status_token:
            raise ApiError("no STATUS_TOKEN: the ade-merge-gate App token was not minted")
        if os.environ.get("MARKER_POST_AS") == "check-run":
            self._req("POST", f"repos/{repo}/check-runs", self.status_token, check_run_body(sha, body))
        else:
            self._req("POST", f"repos/{repo}/statuses/{sha}", self.status_token, body)
        self.posted.append({"sha": sha, **body})


def check_run_body(sha: str, status: dict) -> dict:
    """The same verdict as a CHECK RUN (the fallback if a commit status from the App does not satisfy the ruleset's
    `integration_id` pin, research item 18, unverified 2026-11-06): set `MARKER_POST_AS: check-run` on the step and give
    the App "Checks: write". The check's name is the status context, so the ruleset entry does not change."""
    out = {"name": status["context"], "head_sha": sha, "status": "completed",
           "conclusion": "success" if status["state"] == "success" else "failure",
           "output": {"title": status["description"], "summary": status["description"]}}
    if status.get("target_url"):
        out["details_url"] = status["target_url"]
    return out


class CannedApi:
    """The tests' API: `answers` maps "GET <path>" to a list of answers served in order (the last one
    repeats); an answer is {"json": ...} or {"error": "..."}. Posts are recorded, never sent."""

    def __init__(self, answers: dict) -> None:
        self.answers = answers
        self.calls: dict[str, int] = {}
        self.posted: list[dict] = []

    def get(self, path: str):
        key = "GET " + path
        seq = self.answers.get(key)
        if not seq:
            raise ApiError(f"GET {path}: no canned answer")
        n = self.calls.get(key, 0)
        self.calls[key] = n + 1
        ans = seq[min(n, len(seq) - 1)]
        if "error" in ans:
            raise ApiError(f"GET {path}: {ans['error']}")
        return ans.get("json")

    def graphql(self, query: str, variables: dict):
        """Served like a GET: {"json": <the `data` object>} or {"error": ...}, from "GRAPHQL <number>" for the PR read
        and "GRAPHQL <number> comments" (the first page) or "GRAPHQL <number> comments after <cursor>" for the comments
        read (`variables` carries `cursor`)."""
        key = f"GRAPHQL {variables.get('number')}"
        if "cursor" in variables:
            key += " comments" + (f" after {variables['cursor']}" if variables["cursor"] else "")
        seq = self.answers.get(key)
        if not seq:
            raise ApiError(f"graphql pr {variables.get('number')}: no canned answer")
        n = self.calls.get(key, 0)
        self.calls[key] = n + 1
        ans = seq[min(n, len(seq) - 1)]
        if "error" in ans:
            raise ApiError(f"graphql: {ans['error']}")
        return ans.get("json")

    def post_status(self, repo: str, sha: str, body: dict) -> None:
        if "POST" in self.answers and self.answers["POST"].get("error"):
            raise ApiError(f"POST repos/{repo}/statuses/{sha}: {self.answers['POST']['error']}")
        self.posted.append({"sha": sha, **body})


def _same_repo(full_name: object, repo: str) -> bool:
    return isinstance(full_name, str) and full_name.lower() == repo.lower()


PULLS_PER_PAGE = 100
PULL_PAGES_MAX = 20        # 2,000 PRs at one head or branch; more is not read in full, which fails closed


def _all_pages(api, path: str) -> list[dict]:
    """Every entry of a paginated REST list (`path` already carries its query, or none): `per_page=100`, page 1, 2, ...
    until a short or empty page. GitHub's default page is 30 and merged or closed PRs fill pages too, so one
    unpaginated read could miss an open sibling (Codex review, 2026-11-07). Raises ApiError, or ValueError when a page
    is not a list of objects or PULL_PAGES_MAX full pages were read: a PR that was not read could BLOCK this head."""
    sep = "&" if "?" in path else "?"
    out: list[dict] = []
    for page in range(1, PULL_PAGES_MAX + 1):
        doc = api.get(f"{path}{sep}per_page={PULLS_PER_PAGE}&page={page}")
        if not isinstance(doc, list) or not all(isinstance(p, dict) for p in doc):
            raise ValueError(f"{path} page {page}: not a list of objects")
        out.extend(doc)
        if len(doc) < PULLS_PER_PAGE:
            return out
    raise ValueError(f"{path}: more than {PULL_PAGES_MAX * PULLS_PER_PAGE} PRs, not read in full")


def _open_prs_at(api, repo: str, head: str) -> list[int]:
    """The open PRs of this repository whose head is `head` (`GET commits/{head}/pulls`, every page). Raises ApiError,
    or ValueError on a bad page or an incomplete read."""
    return [p["number"] for p in _all_pages(api, f"repos/{repo}/commits/{head}/pulls")
            if isinstance(p.get("number"), int) and p.get("state") == "open"
            and str(((p.get("head") or {}).get("sha")) or "").lower() == head
            and _same_repo(((p.get("base") or {}).get("repo") or {}).get("full_name"), repo)]


def _open_prs_by_head(api, repo: str) -> dict[str, list[int]]:
    """Open same-repo PRs grouped by full head sha (push all-open rejudge).

    Used by ``resolve`` to emit one matrix cell per head so each ``marker`` job shares the
    ``adversary-marker-<head>`` concurrency group with dispatch / ``workflow_run`` for that sha
    (Codex P1 on #490, 2026-11-10: a single ``push-rejudge-all-open`` key raced those jobs).
    Raises ValueError when an open PR's head is not 40 hex; ApiError on a failed page.
    """
    by: dict[str, list[int]] = {}
    for p in _all_pages(api, f"repos/{repo}/pulls?state=open"):
        if not isinstance(p.get("number"), int):
            continue
        if p.get("state", "open") != "open":
            continue
        if not _same_repo(((p.get("base") or {}).get("repo") or {}).get("full_name"), repo):
            continue
        head = str(((p.get("head") or {}).get("sha")) or "").lower()
        if not SHA40.match(head):
            raise ValueError(f"open PR #{p['number']} has a non-40-hex head: {head!r}")
        by.setdefault(head, []).append(p["number"])
    return {h: sorted(set(ns)) for h, ns in by.items()}


def find_prs(event_name: str, event: dict, repo: str, api) -> tuple[list[int], str, str]:
    """The PR numbers this event is about, how they were found, and the head they were found at.

    Every open PR of this repository at that head is included (`GET commits/{head}/pulls`), whatever the event names,
    because PRs sharing a head share ONE commit status and the shared-head rule in `run_event` must see them all
    (2026-11-07: a dispatch that judged only PR N posted success on a sha another open PR BLOCKs).

    workflow_dispatch: the `pr` input (digits only); its head is read from `GET pulls/{pr}`. workflow_run: the event's
    `pull_requests[]` (same-repo PRs only; GitHub leaves it empty for a fork PR) and the commit lookup, else
    `GET pulls?head=OWNER:BRANCH` from the run's head repository and branch. push: every open same-repo PR, with
    head ``""`` — ``resolve`` expands them into a per-head matrix so each marker job uses the head-keyed
    concurrency group (never invents APPROVE). Raises ValueError for an event it cannot read, ApiError when a
    lookup fails.
    """
    if event_name == "push":
        # Paths filter in the workflow limits this to marker module / workflow edits on the default branch.
        by = _open_prs_by_head(api, repo)
        return sorted({n for ns in by.values() for n in ns}), "push all-open", ""
    if event_name == "workflow_dispatch":
        pr = str(((event.get("inputs") or {}).get("pr")) or "").strip()
        if not re.fullmatch(r"[1-9][0-9]{0,9}", pr):
            raise ValueError(f"workflow_dispatch input `pr` is not a PR number: {pr!r}")
        _state, head, _body = _pr_state(api, repo, int(pr))
        return sorted({int(pr), *_open_prs_at(api, repo, head)}), "dispatch input", head
    if event_name != "workflow_run":
        raise ValueError(
            f"unsupported event {event_name!r} "
            "(only workflow_run, workflow_dispatch, and push)"
        )
    wr = event.get("workflow_run") or {}
    head_sha = str(wr.get("head_sha") or "").lower()
    if not SHA40.match(head_sha):
        raise ValueError(f"workflow_run.head_sha is not a 40-hex sha: {head_sha!r}")
    nums = []
    for p in wr.get("pull_requests") or []:
        if not isinstance(p, dict) or not isinstance(p.get("number"), int):
            continue
        # The entries name their base repository by API url ({"id", "url", "name"}): a PR of another
        # repository (a fork's own PR into itself) is not ours.
        url = str((((p.get("base") or {}).get("repo") or {}).get("url")) or "")
        if url and not url.lower().endswith("/repos/" + repo.lower()):
            continue
        nums.append(p["number"])
    at_head = _open_prs_at(api, repo, head_sha)
    if nums:
        return sorted({*nums, *at_head}), "workflow_run.pull_requests", head_sha
    if at_head:
        return sorted(set(at_head)), "commits/{sha}/pulls", head_sha
    owner = str(((wr.get("head_repository") or {}).get("owner") or {}).get("login") or "")
    branch = str(wr.get("head_branch") or "")
    if owner and branch and re.fullmatch(r"[A-Za-z0-9-]+", owner) and re.fullmatch(r"[\w./-]+", branch):
        nums = [p["number"] for p in _all_pages(api, f"repos/{repo}/pulls?state=open&head={owner}:{branch}")
                if isinstance(p.get("number"), int) and p.get("state", "open") == "open"
                and str(((p.get("head") or {}).get("sha")) or "").lower() == head_sha]
        if nums:
            return sorted(set(nums)), "pulls?head=", head_sha
    return [], "no open PR has this head", head_sha


def _pr_state(api, repo: str, n: int) -> tuple[str, str, str]:
    """(state, head sha, body) of PR N, read through the API. Raises ApiError, or ValueError on a bad shape."""
    doc = api.get(f"repos/{repo}/pulls/{n}")
    if not isinstance(doc, dict):
        raise ValueError(f"pulls/{n}: not an object")
    head = str(((doc.get("head") or {}).get("sha")) or "").lower()
    if not SHA40.match(head):
        raise ValueError(f"pulls/{n}: head sha is not 40 hex: {head!r}")
    body = doc.get("body")
    return str(doc.get("state") or ""), head, body if isinstance(body, str) else ""


PR_QUERY = ("query($owner: String!, $name: String!, $number: Int!) { repository(owner: $owner, name: $name) { "
            "pullRequest(number: $number) { state headRefOid body authorAssociation author { login } "
            "editor { login } lastEditedAt } } }")
COMMENTS_PER_PAGE = 100
COMMENT_PAGES_MAX = 30     # 3,000 comments; a PR with more is not read in full, which fails closed
EDITS_MAX = 100            # a comment's edit history read in full; a longer one is unknown attribution
# GitHub's GraphQL schema has no `lastEditedBy` (checked against docs.github.com/public/fpt/schema.docs.graphql,
# 2026-11-07): `IssueComment` and `PullRequest` carry `editor` ("the actor who edited"), `lastEditedAt` and
# `includesCreatedEdit`, and `userContentEdits` lists every edit with its `editor`. The comments read takes all of them,
# and the App provenance REST's `performed_via_github_app` gives (GraphQL has no field for it) comes from the REST read.
COMMENTS_QUERY = (
    "query($owner: String!, $name: String!, $number: Int!, $cursor: String) { repository(owner: $owner, name: $name) { "
    f"pullRequest(number: $number) {{ comments(first: {COMMENTS_PER_PAGE}, after: $cursor) {{ totalCount "
    "pageInfo { hasNextPage endCursor } nodes { fullDatabaseId body author { __typename login } "
    "editor { __typename login } lastEditedAt includesCreatedEdit "
    f"userContentEdits(first: {EDITS_MAX}) {{ totalCount nodes {{ editor {{ __typename login }} }} }} }} }} }} }} }}")


def body_editor_trusted(editor: str, owner: str) -> bool:
    """True when ``editor`` may leave an owner-PR body's live APPROVE trusted.

    The owner always qualifies. Logins in BODY_TRUSTED_EDITOR_LOGINS also qualify
    (Cursor cloud rewrites of owner-authored PR bodies). Empty or unknown editors
    never qualify. Outside PRs never consult this for a body APPROVE.
    """
    e = (editor or "").lower()
    o = (owner or "").lower()
    if not e or not o:
        return False
    return e == o or e in {login.lower() for login in BODY_TRUSTED_EDITOR_LOGINS}


def _pr_state_trusted(api, repo: str, n: int) -> dict:
    """{state, head, body, author, editor, association, owner_pr, body_trusted} of PR N from ONE GraphQL read, so the
    body and the editor it is judged by belong together. The editor is `editor` (GitHub's last editor), or the author
    when the body was never edited (`lastEditedAt` null); an edit with no `editor` (a deleted user) is an unknown
    editor, which no body trust survives.

    `owner_pr`: the author is the repository owner (logins compare case-insensitively). `body_trusted`: an owner PR
    whose body last editor is the owner or a BODY_TRUSTED_EDITOR_LOGINS login (2026-11-09). An explicit body APPROVE
    on an owner PR still needs that trust; a markerless owner PR is approved via owner-trust (2026-11-10). The
    allowlist exists so a Cursor Cloud rewrite of an owner PR body does not void an explicit live APPROVE
    (2026-11-09). Before 2026-11-07, the owner's last edit made ANY body trusted, so an owner who ticked a
    task-list box on an outside PR turned an APPROVE the author had hidden in an HTML comment into a trusted
    one; MEMBER or COLLABORATOR authors stay outside-like (outside PRs still need an owner comment). A listed
    App editing an outside body still cannot approve it.
    """
    owner, name = repo.split("/", 1)
    data = api.graphql(PR_QUERY, {"owner": owner, "name": name, "number": n})
    pr = (((data or {}).get("repository") or {}).get("pullRequest")) if isinstance(data, dict) else None
    if not isinstance(pr, dict):
        raise ValueError(f"graphql pr {n}: no pullRequest")
    head = str(pr.get("headRefOid") or "").lower()
    if not SHA40.match(head):
        raise ValueError(f"graphql pr {n}: head is not 40 hex: {head!r}")
    author = str(((pr.get("author") or {}).get("login")) or "")
    editor = str(((pr.get("editor") or {}).get("login")) or "")
    if "editor" in pr and pr["editor"] is None and "lastEditedAt" in pr and pr["lastEditedAt"] is None:
        editor = author                       # explicit never-edited shape only; absent/malformed editor is unknown
    owner_pr = bool(author) and author.lower() == owner.lower()
    body = pr.get("body")
    return {"state": str(pr.get("state") or "").lower(), "head": head, "body": body if isinstance(body, str) else "",
            "author": author, "editor": editor, "association": str(pr.get("authorAssociation") or "").upper(),
            "owner_pr": owner_pr, "body_trusted": owner_pr and body_editor_trusted(editor, owner)}


def _pr_comments(api, repo: str, n: int) -> list[dict]:
    """Every issue comment on PR N ({id, author, via_app, body}), all pages, through `GET issues/{n}/comments`.

    Raises ApiError, or ValueError on a bad shape or a PR with more than COMMENT_PAGES_MAX pages: a comment that was
    not read could hold a BLOCK, so an incomplete read fails closed like an unreadable body. `via_app` is true unless
    the comment carries `performed_via_github_app: null` (a missing field counts as an App: fail closed)."""
    out: list[dict] = []
    for page in range(1, COMMENT_PAGES_MAX + 1):
        doc = api.get(f"repos/{repo}/issues/{n}/comments?per_page={COMMENTS_PER_PAGE}&page={page}")
        if not isinstance(doc, list):
            raise ValueError(f"issues/{n}/comments page {page}: not a list")
        for c in doc:
            if not isinstance(c, dict):
                raise ValueError(f"issues/{n}/comments page {page}: an entry is not an object")
            body = c.get("body")
            out.append({"id": c.get("id"), "author": str(((c.get("user") or {}).get("login")) or ""),
                        "via_app": "performed_via_github_app" not in c or c["performed_via_github_app"] is not None,
                        "body": body if isinstance(body, str) else ""})
        if len(doc) < COMMENTS_PER_PAGE:
            return out
    raise ValueError(f"issues/{n}/comments: more than {COMMENT_PAGES_MAX * COMMENTS_PER_PAGE} comments, "
                     "not read in full")


def _actor(a: object, owner: str) -> tuple[str, str]:
    """('owner' | 'other' | 'unknown', login) for a GraphQL Actor: the owner only as a `User` with the owner's login."""
    if not isinstance(a, dict) or not isinstance(a.get("login"), str) or not a["login"]:
        return "unknown", ""
    login = a["login"]
    if login.lower() != owner.lower():
        return "other", login
    if a.get("__typename") == "User":
        return "owner", login
    return ("unknown" if a.get("__typename") is None else "other"), login


def _edit_attribution(node: dict, owner: str) -> tuple[str, str]:
    """('never' | 'owner' | 'other' | 'unknown', a non-owner editor's login) for one GraphQL comment node.

    GitHub lets any repository writer edit another user's comment while the author stays the same (Codex review,
    2026-11-07), and an owner's later edit (a task-list tick) does not show what an earlier editor hid in it, so
    `owner` means the last editor AND every edit in `userContentEdits` is the owner's. `never`: no `editor`, no
    `lastEditedAt`, no created edit and an empty history. Anything else that names no non-owner (a missing field, a
    deleted editor, a history longer than EDITS_MAX) is `unknown`, which no APPROVE survives."""
    if not all(k in node for k in ("editor", "lastEditedAt", "includesCreatedEdit", "userContentEdits")):
        return "unknown", ""
    edits = node["userContentEdits"]
    if (not isinstance(node["includesCreatedEdit"], bool) or not isinstance(edits, dict)
            or not isinstance(edits.get("totalCount"), int) or not isinstance(edits.get("nodes"), list)):
        return "unknown", ""
    if (node["editor"] is None and node["lastEditedAt"] is None and not node["includesCreatedEdit"]
            and edits["totalCount"] == 0 and not edits["nodes"]):
        return "never", ""
    actors = [node["editor"]] + [e.get("editor") if isinstance(e, dict) else None for e in edits["nodes"]]
    kinds = [_actor(a, owner) for a in actors]
    for kind, login in kinds:
        if kind == "other":
            return "other", login
    if (any(kind != "owner" for kind, _l in kinds) or node["lastEditedAt"] is None
            or edits["totalCount"] > len(edits["nodes"])):
        return "unknown", ""
    return "owner", ""


def _pr_comments_trusted(api, repo: str, n: int) -> list[dict]:
    """Every issue comment on PR N through GraphQL ({id, author, author_kind, body, edit, edited_by}), all pages, so
    the body and the edit attribution it is judged by come from one answer (COMMENTS_QUERY).

    Raises ApiError, or ValueError on a bad shape, more than COMMENT_PAGES_MAX pages, a cursor that does not advance
    or a count that does not match `totalCount`: a comment that was not read could hold a BLOCK, so an incomplete
    read fails closed like an unreadable body."""
    owner, name = repo.split("/", 1)
    out: list[dict] = []
    cursor = None
    for page in range(1, COMMENT_PAGES_MAX + 1):
        data = api.graphql(COMMENTS_QUERY, {"owner": owner, "name": name, "number": n, "cursor": cursor})
        pr = (((data or {}).get("repository") or {}).get("pullRequest")) if isinstance(data, dict) else None
        conn = pr.get("comments") if isinstance(pr, dict) else None
        info = conn.get("pageInfo") if isinstance(conn, dict) else None
        if (not isinstance(conn, dict) or not isinstance(conn.get("nodes"), list)
                or not isinstance(conn.get("totalCount"), int) or not isinstance(info, dict)
                or not isinstance(info.get("hasNextPage"), bool)):
            raise ValueError(f"graphql pr {n} comments page {page}: not a comment connection")
        for c in conn["nodes"]:
            if not isinstance(c, dict) or not isinstance(c.get("body"), str):
                raise ValueError(f"graphql pr {n} comments page {page}: an entry is not a comment with a body")
            kind, login = _actor(c.get("author"), owner)
            edit, edited_by = _edit_attribution(c, owner)
            cid = c.get("fullDatabaseId")
            out.append({"id": str(cid) if isinstance(cid, (int, str)) and str(cid) else None, "author": login,
                        "author_kind": kind, "body": c["body"], "edit": edit, "edited_by": edited_by})
        if not info["hasNextPage"]:
            if len(out) != conn["totalCount"]:
                raise ValueError(f"graphql pr {n} comments: read {len(out)} of {conn['totalCount']}, not in full")
            return out
        nxt = info.get("endCursor")
        if not isinstance(nxt, str) or not nxt or nxt == cursor:
            raise ValueError(f"graphql pr {n} comments page {page}: no next cursor")
        cursor = nxt
    raise ValueError(f"graphql pr {n} comments: more than {COMMENT_PAGES_MAX * COMMENTS_PER_PAGE} comments, "
                     "not read in full")


def _merge_comments(trusted: list[dict], rest: list[dict]) -> list[dict]:
    """The comments `decide` judges: each GraphQL comment, with `via_app` from the REST entry of the same id (no
    matching entry, or one whose body differs, counts as an App: REST can only take trust away, never give it), and
    every REST entry the GraphQL read does not hold with the same body, marked `scan_only` (judged for a BLOCK or a
    malformed marker, never for an APPROVE)."""
    by_id = {str(c["id"]): c for c in rest if c.get("id") is not None}
    out = []
    for c in trusted:
        r = by_id.get(c["id"]) if c["id"] is not None else None
        out.append({**c, "via_app": r is None or r["via_app"] or r["body"] != c["body"], "scan_only": False})
    seen = {(c["id"], c["body"]) for c in trusted}
    for r in rest:
        if (str(r["id"]) if r.get("id") is not None else None, r["body"]) not in seen:
            out.append({"id": r.get("id"), "author": r["author"], "author_kind": "unknown", "body": r["body"],
                        "edit": "unknown", "edited_by": "", "via_app": r["via_app"], "scan_only": True})
    return out


def decide(head: str, owner: str, pr: dict, comments: list[dict]) -> tuple[str, str, str]:
    """(outcome word, where, detail) for one PR: its body and its issue comments, judged by the one parser.

    1. A BLOCK for this head anywhere (the body, or ANY comment, whoever wrote it) blocks, then a malformed marker
       anywhere: the same asymmetry as the body's (rule 1, property 1). A comment marker naming another head is
       history (an approval of an earlier push), not a failure.
    2. An owner PR (repository owner authored it — including Cloud Agents under that login): trusted by default
       (operator 2026-11-10: trust what comes only from the owner or AIs they run). No APPROVE marker is required.
       An explicit body APPROVE still counts when the body editor is trusted (owner or BODY_TRUSTED_EDITOR_LOGINS);
       an APPROVE body last edited by anyone else is `untrusted`. BLOCK/malformed still fail closed.
    3. Any other PR (an outside, MEMBER or COLLABORATOR author): an APPROVE in the body never counts, whoever edited
       it last (a listed App included); only a live APPROVE for this head in a comment by the repository owner, not
       posted via a GitHub App, and never edited by anyone but the owner (`_edit_attribution`), approves. Otherwise
       `edited` (another user edited the owner's APPROVE comment), `edit-unknown` (its edit history is not known in
       full), `untrusted` (the only APPROVE is in someone else's comment, or via an App) or `outside`."""
    body_adv = adversary_verdict(pr["body"], head)
    body_word = outcome(body_adv)
    judged = [(c, outcome(adversary_verdict(c["body"], head))) for c in comments]
    if body_word == "block":
        return "block", "", body_adv.get("detail") or ""
    for c, w in judged:
        if w == "block":
            return "block", "comment", f"BLOCK for this head in comment {c['id']} by {c['author'] or '(ghost)'}"
    if body_word == "malformed":
        return "malformed", "", body_adv.get("detail") or ""
    for c, w in judged:
        if w == "malformed":
            return "malformed", "comment", f"malformed marker in comment {c['id']} by {c['author'] or '(ghost)'}"
    if pr["owner_pr"]:
        if body_word == "approve" and not pr["body_trusted"]:
            return "untrusted", "", f"owner PR body last edited by {pr['editor'] or '(ghost)'}"
        if body_word == "approve":
            return "approve", "", body_adv.get("detail") or ""
        # Owner-authored tip: marker optional (trust the owner / their agents).
        return "approve", "owner_pr", (
            f"owner-authored PR (author {pr.get('author') or '(ghost)'}); "
            "APPROVE marker not required under owner-trust"
        )
    own = [c for c, w in judged if w == "approve" and not c.get("scan_only") and not c.get("via_app", True)
           and c.get("author_kind") == "owner"]
    for c in own:
        if c.get("edit") in ("never", "owner"):
            return "approve", "owner comment", f"APPROVE for this head in owner comment {c['id']}"
    for c in own:
        if c.get("edit") == "other":
            return "edited", "", f"owner comment {c['id']} holds an APPROVE but was edited by {c.get('edited_by')}"
    if own:
        return "edit-unknown", "", f"owner comment {own[0]['id']} holds an APPROVE but its edit history is unknown"
    if any(w == "approve" for _c, w in judged):
        return "untrusted", "comment", "the only APPROVE comments are not the owner's own (another author, or an App)"
    return "outside", "", (f"outside PR (author {pr['author'] or '(ghost)'}): the body's "
                           f"{'APPROVE' if body_word == 'approve' else 'marker'} does not count; "
                           "an owner comment must approve this head")


def judge_pr(api, repo: str, n: int, target_url: str = "") -> dict:
    """Read PR N, decide, and RE-READ the head, the body, its editor and the comments; returns the status to post
    (`run_event` posts it, once per head) or why there is none.

    The verdict is judged from the SECOND read's body (the freshest one) and the comments read after it: a BLOCK
    edit that lands between the two reads is seen. A head that moved posts nothing: the push starts a new `Tests`
    run, whose completion runs this again for the new head, and until then the new head has no status (the
    required check is missing, which blocks the merge)."""
    rec: dict = {"pr": n, "posted": None}
    try:
        state, head, body = _pr_state(api, repo, n)
    except (ApiError, ValueError) as e:
        return {**rec, "result": "error", "detail": str(e)}
    rec["head"] = head
    if state != "open":
        return {**rec, "result": "skipped", "detail": f"PR is {state or 'in an unknown state'}, not open"}
    first = outcome(adversary_verdict(body, head))
    try:
        pr = _pr_state_trusted(api, repo, n)
    except (ApiError, ValueError) as e:
        return {**rec, "result": "error", "detail": f"re-read before posting failed: {e}"}
    if pr["head"] != head:
        return {**rec, "result": "head-moved", "detail": f"head moved {head[:12]} -> {pr['head'][:12]} before posting"}
    if pr["state"] != "open":
        return {**rec, "result": "skipped", "detail": f"PR became {pr['state'] or 'unknown'} before posting"}
    try:
        trusted = _pr_comments_trusted(api, repo, n)
        comments = _merge_comments(trusted, _pr_comments(api, repo, n))
    except (ApiError, ValueError) as e:
        return {**rec, "result": "error", "detail": f"reading the comments failed: {e}"}
    word, where, detail = decide(head, repo.split("/", 1)[0], pr, comments)
    rec.update(last_editor=pr["editor"], trusted=pr["body_trusted"], author=pr["author"], owner_pr=pr["owner_pr"],
               comments=len(trusted))
    status = {"state": "success" if word == "approve" else "failure", "context": CONTEXT,
              "description": describe(word, head, where)}
    if target_url:
        status["target_url"] = target_url
    return {**rec, "result": "decided", "outcome": word, "where": where, "first_read": first, "status": status,
            "detail": detail}


def _matrix_payload(include: list[dict]) -> dict:
    """``matrix`` / ``has_work`` for the workflow's ``strategy.matrix: ${{ fromJson(...) }}``."""
    return {
        "matrix": json.dumps({"include": include}, separators=(",", ":")),
        "has_work": "true" if include else "false",
    }


def resolve(event_name: str, event: dict, repo: str, api) -> tuple[int, dict]:
    """The workflow's first job: a per-head matrix for ``marker``, plus legacy ``prs`` / ``key`` / ``at_head``.

    Every ``marker`` cell uses concurrency group ``adversary-marker-<head>`` and ``--at-head`` for that sha, so a
    push sweep, a dispatch and a ``workflow_run`` that could post on the same commit serialize together
    (2026-11-07; push used a single ``push-rejudge-all-open`` key until 2026-11-10 and raced those jobs — Codex P1
    on #490). ``workflow_run`` / ``workflow_dispatch`` emit one cell; ``push`` emits one cell per distinct open
    head (paths-filtered landing of the marker module / workflow; never invents APPROVE).
    """
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""):
        return 2, {"error": f"not an OWNER/NAME repository: {repo!r}"}
    if event_name == "push":
        try:
            by = _open_prs_by_head(api, repo)
        except (ValueError, ApiError) as e:
            return 2, {"error": str(e)}
        include = [
            {"head": h, "prs": ",".join(str(n) for n in nums)}
            for h, nums in sorted(by.items())
        ]
        prs_csv = ",".join(str(n) for n in sorted({n for ns in by.values() for n in ns}))
        return 0, {
            "prs": prs_csv,
            "key": "",
            "at_head": "",
            "found_by": "push all-open",
            **_matrix_payload(include),
        }
    try:
        prs, how, head = find_prs(event_name, event, repo, api)
    except (ValueError, ApiError) as e:
        return 2, {"error": str(e)}
    key = head if prs else ""
    include = [{"head": head, "prs": ",".join(str(n) for n in prs)}] if prs else []
    return 0, {
        "prs": ",".join(str(n) for n in prs),
        "key": key,
        "at_head": key,
        "found_by": how,
        **_matrix_payload(include),
    }


def parse_prs(text: str) -> list[int]:
    """`--prs 7,9`: positive integers only (ValueError otherwise)."""
    out = []
    for part in (text or "").split(","):
        if not re.fullmatch(r"[1-9][0-9]{0,9}", part.strip()):
            raise ValueError(f"--prs is not a list of PR numbers: {text!r}")
        out.append(int(part.strip()))
    return sorted(set(out))


def _pr_list(rs: list[dict], most: int = 6) -> str:
    """`#7, #8` for a status description, at most MOST numbers then `+N more`, so the 140-character cap never cuts off
    the reason that follows (a shared head with 31 PRs lost "and not all approve", 2026-11-07)."""
    shown = ", ".join(f"#{r['pr']}" for r in rs[:most])
    return shown + (f" +{len(rs) - most} more" if len(rs) > most else "")


def run_event(event_name: str, event: dict, repo: str, api, target_url: str = "",
              prs_given: list[int] | None = None, at_head: str | None = None) -> tuple[int, dict]:
    """The whole Action. Exit 0: every PR found was judged (a status posted, or nothing to post: no open PR
    for the head, a closed PR, a head that moved); 2: the event or an API call could not be read (no status is
    posted for that PR, so its required check stays missing and the merge stays blocked).

    `at_head` (`--at-head`, the resolve job's key): only a PR still at that head gets a status from this run, so a run
    posts only on the sha of its own concurrency group; a PR that moved is `head-moved` (its push has its own run).

    ONE status is posted per head, after every PR at it was judged, so no transient success lands before the
    shared-head failure. Two open PRs with one head share that status: it is success only when every one of them
    approves; a sibling that could not be read fails it too."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""):
        return 2, {"error": f"not an OWNER/NAME repository: {repo!r}"}
    if prs_given is not None:
        prs, how = prs_given, "--prs"
    else:
        try:
            prs, how, _head = find_prs(event_name, event, repo, api)
        except (ValueError, ApiError) as e:
            return 2, {"error": str(e)}
    report: dict = {"event": event_name, "repo": repo, "found_by": how, "prs": []}
    if not prs:
        return 0, report
    results = [judge_pr(api, repo, n, target_url) for n in prs]
    if at_head:
        for r in results:
            if r.get("result") == "decided" and r["head"] != at_head:
                r.update(result="head-moved", detail=f"head is {r['head'][:12]}, not this run's {at_head[:12]}")
    unread = [r for r in results if r.get("result") == "error"]
    by_head: dict[str, list[dict]] = {}
    for r in results:
        if r.get("result") == "decided":
            by_head.setdefault(r["head"], []).append(r)
    for head, rs in by_head.items():
        status = dict(rs[0]["status"])
        nums = _pr_list(rs)
        # Scope unread failures to this head only (Codex P2 on #490, 2026-11-10): a push sweep used to
        # poison every head when any PR in the batch was unreadable. A single-head cell (`at_head`) also
        # fails closed on a PR that never yielded a head (still this concurrency group's status).
        unread_here = [r for r in unread if r.get("head") == head]
        if at_head and head == at_head:
            unread_here = unread_here + [r for r in unread if not r.get("head")]
        if unread_here:
            bad = _pr_list(unread_here)
            status.update(state="failure", description=f"PR {bad} at this head could not be read ({head[:12]})"[:140])
        elif len(rs) > 1 and any(r["outcome"] != "approve" for r in rs):
            status.update(state="failure", description=f"PRs {nums} share head {head[:12]} and not all approve"[:140])
        try:
            api.post_status(repo, head, status)
        except ApiError as e:
            for r in rs:
                r.update(result="error", detail=f"posting the status failed: {e}")
            continue
        for r in rs:
            r.update(result="posted", posted=status)
    report["prs"] = results
    rc = 2 if any(r.get("result") == "error" for r in results) or report.get("error") else 0
    return rc, report


# ---- CLI ----------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="adversary_marker.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--body-file", help="a PR body to judge (with --head)")
    p.add_argument("--head", help="the PR head, 40 hex (with --body-file)")
    p.add_argument("--event", help="a GitHub event payload (the Action passes $GITHUB_EVENT_PATH)")
    p.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    p.add_argument("--api-answers", help="canned API answers (JSON); posts are printed, not sent")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--resolve", action="store_true", help="only find the PRs; write prs= and key= to $GITHUB_OUTPUT")
    g.add_argument("--prs", help="judge these PRs (comma-separated numbers, from --resolve) instead of looking them up")
    p.add_argument("--at-head", help="with --event: post only on this head (40 hex, the resolve job's key); a PR that "
                                     "moved off it gets no status from this run")
    try:
        a = p.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    if a.event:
        try:
            with open(a.event, encoding="utf-8") as f:
                event = json.load(f)
            if not isinstance(event, dict):
                raise ValueError("the event is not a JSON object")
            if a.api_answers:
                with open(a.api_answers, encoding="utf-8") as f:
                    api = CannedApi(json.load(f))
            else:
                api = Api(os.environ.get("GITHUB_TOKEN", ""), os.environ.get("STATUS_TOKEN", ""),
                          os.environ.get("GITHUB_API_URL", "https://api.github.com"))
        except (OSError, ValueError) as e:
            print(f"adversary_marker: {e}", file=sys.stderr)
            return 2
        if a.resolve:
            rc, out = resolve(a.event_name, event, a.repo, api)
            print(json.dumps(out, sort_keys=True))
            if rc == 0 and os.environ.get("GITHUB_OUTPUT"):
                with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
                    f.write(
                        f"prs={out['prs']}\n"
                        f"key={out['key']}\n"
                        f"at_head={out.get('at_head', out['key'])}\n"
                        f"matrix={out['matrix']}\n"
                        f"has_work={out['has_work']}\n"
                    )
            return rc
        try:
            prs_given = parse_prs(a.prs) if a.prs is not None else None
            # Empty --at-head (push all-open rejudge) means no single-head filter.
            raw_at = None if a.at_head is None else a.at_head.strip().lower()
            at_head = None if not raw_at else raw_at
            if at_head is not None and not SHA40.match(at_head):
                raise ValueError(f"--at-head is not 40 hex: {a.at_head!r}")
        except ValueError as e:
            print(f"adversary_marker: {e}", file=sys.stderr)
            return 2
        server, run_id = os.environ.get("GITHUB_SERVER_URL", ""), os.environ.get("GITHUB_RUN_ID", "")
        target = f"{server}/{a.repo}/actions/runs/{run_id}" if server and run_id else ""
        rc, report = run_event(a.event_name, event, a.repo, api, target, prs_given, at_head)
        report["statuses"] = api.posted
        print(json.dumps(report, sort_keys=True))
        return rc
    if not (a.body_file and a.head):
        print("adversary_marker: give --body-file FILE --head SHA, or --event FILE", file=sys.stderr)
        return 2
    head = a.head.strip().lower()
    if not SHA40.match(head):
        print(f"adversary_marker: --head is not 40 hex: {a.head!r}", file=sys.stderr)
        return 2
    try:
        with open(a.body_file, encoding="utf-8") as f:
            body = f.read()
        adv = adversary_verdict(body, head)
    except (OSError, UnicodeDecodeError) as e:
        adv = {"present": False, "verdict": None, "quoted_sha": None, "matches_head": False,
               "conflict": False, "malformed": False, "fetch_failed": True, "detail": f"cannot read the body: {e}"}
    word = outcome(adv)
    print(json.dumps({**adv, "outcome": word, "head": head}, sort_keys=True))
    return EXIT_FOR[word]


if __name__ == "__main__":
    sys.exit(main())
