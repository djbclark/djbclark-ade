"""firecrawl_sanitize: Anti-prompt-injection sanitizer & spotlighting helpers for bin/firecrawl-router (stdlib only).

Aligned with BarnOwl's `goose-helper.py` `_s`/`_f` untrusted-text sanitizer and
`docs/security/argon-injection-review-2026-11-07.md` (`S4.1`, `C0d.2`, `C0d.3`):

  1. Single-line metadata fields (`sanitize_field`): NFKC normalization, strips
     control chars (`Cc`), format chars (`Cf`: zero-width, bidi overrides,
     Unicode Tag block `U+E0000..U+E007F` used for invisible "ASCII smuggling"),
     private-use (`Co`), unassigned (`Cn`), surrogates (`Cs`), variation
     selectors (`U+FE00..U+FE0F`, `U+E0100..U+E01EF`), line/paragraph separators
     (`Zl`/`Zp`), and excessive combining marks (> 2 consecutive), replacing
     each stripped run with a single `U+FFFD`, then collapsing whitespace and
     newlines into single ASCII spaces.
  2. Markdown / document bodies (`sanitize_markdown`): linear-time (`O(N)`)
     stripping of hidden HTML comments (`<!-- ... -->`) outside fenced code
     blocks plus the same invisible/smuggling Unicode classes (`Cf`, `Cc`
     except `\\n`/`\\t`, `Co`, `Cn`, `Cs`, `Zl`, `Zp`, variation selectors,
     combining-mark runs > 2), without destructive NFKC folding of legitimate
     scholarly math/Greek superscripts or fractions.
  3. Per-call 128-bit random-nonce spotlighting (`spotlight_untrusted`) for
     `Extractor` prompts so third-party page content cannot forge a closing
     fence or masquerade as system/user instructions.
"""

from __future__ import annotations

import secrets
import unicodedata

_VARIATION_SELECTORS = ((0xFE00, 0xFE0F), (0xE0100, 0xE01EF))
_MAX_COMBINING_MARKS = 2

_META_FIELD_KEYS = (
    "title",
    "ogTitle",
    "description",
    "ogDescription",
    "oaSource",
    "author",
)


def _is_variation_selector(cp: int) -> bool:
    for lo, hi in _VARIATION_SELECTORS:
        if lo <= cp <= hi:
            return True
    return False


def _clean_unicode_stream(
    text: str,
    *,
    allow_newlines: bool,
    allow_tabs: bool,
) -> tuple[str, int]:
    """Strip invisible/control/smuggling Unicode classes in linear time.

    Each contiguous run of hostile/hidden characters is replaced with a single
    U+FFFD so hidden text cannot silently splice adjacent tokens (e.g.
    `ig\\u200bnore` -> `ig\\ufffdnore`). Returns `(cleaned_text, stripped_runs)`.
    """
    out: list[str] = []
    in_run = False
    marks = 0
    stripped_runs = 0
    for ch in text:
        if ch == "\r":
            continue
        cp = ord(ch)
        cat = unicodedata.category(ch)
        if ch == "\t":
            if allow_tabs:
                in_run = False
                marks = 0
                out.append("\t")
                continue
            ch, cat = " ", "Zs"
        elif cat == "Zs" and ch != " ":
            ch, cat = " ", "Zs"

        if ch == "\n" and allow_newlines:
            in_run = False
            marks = 0
            out.append("\n")
            continue

        bad = (
            cat in ("Cc", "Cf", "Co", "Cn", "Cs", "Zl", "Zp")
            or _is_variation_selector(cp)
        )
        if not bad and cat in ("Mn", "Mc", "Me"):
            marks += 1
            if marks > _MAX_COMBINING_MARKS:
                bad = True
        elif not bad:
            marks = 0

        if bad:
            if not in_run:
                out.append("\ufffd")
                stripped_runs += 1
                in_run = True
            continue

        in_run = False
        out.append(ch)
    return "".join(out), stripped_runs


def sanitize_field(text: object, limit: int = 300) -> str:
    """Single-line metadata sanitizer (BarnOwl `_f` parity): NFKC + strip hidden/control chars."""
    if not isinstance(text, str):
        return ""
    if limit <= 0:
        return ""
    bounded = text[: limit * 4]
    normalized = unicodedata.normalize("NFKC", bounded)
    cleaned, _ = _clean_unicode_stream(normalized, allow_newlines=False, allow_tabs=False)
    return " ".join(cleaned.split())[:limit]


def _strip_html_comments_outside_fences(text: str) -> tuple[str, int]:
    """Strip `<!-- ... -->` HTML comments outside Markdown fenced code blocks in O(N) time."""
    if "<!--" not in text:
        return text, 0

    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    in_comment = False
    comments_stripped = 0

    for line in lines:
        if not in_comment:
            stripped = line.lstrip(" ")
            indent = len(line) - len(stripped)
            if indent <= 3 and (stripped.startswith("```") or stripped.startswith("~~~")):
                ch = stripped[0]
                run = 0
                while run < len(stripped) and stripped[run] == ch:
                    run += 1
                if not in_fence and run >= 3:
                    in_fence = True
                    fence_char = ch
                    fence_len = run
                    out.append(line)
                    continue
                if in_fence and ch == fence_char and run >= fence_len and stripped[run:].strip() == "":
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
                    out.append(line)
                    continue

        if in_fence:
            out.append(line)
            continue

        pos = 0
        n = len(line)
        line_buf: list[str] = []
        while pos < n:
            if in_comment:
                end = line.find("-->", pos)
                if end == -1:
                    pos = n
                    break
                in_comment = False
                pos = end + 3
            else:
                start = line.find("<!--", pos)
                if start == -1:
                    line_buf.append(line[pos:])
                    break
                if start > pos:
                    line_buf.append(line[pos:start])
                in_comment = True
                comments_stripped += 1
                pos = start + 4
        if line_buf:
            out.append("".join(line_buf))
    return "".join(out), comments_stripped


def sanitize_markdown(text: str) -> tuple[str, int]:
    """Sanitize scraped Markdown / document body for agent & Extractor consumption.

    Returns `(cleaned_text, stripped_events_count)`.
    Preserves newlines, tabs, and legitimate math/Greek characters while stripping
    hidden HTML comments outside fenced code blocks and invisible/smuggling Unicode
    classes (`Cf` including zero-width/bidi/Unicode Tag block `U+E0000..U+E007F`,
    `Cc` except `\\n`/`\\t`, `Co`, `Cn`, `Cs`, `Zl`, `Zp`, variation selectors,
    and combining-mark runs > 2).
    """
    if not isinstance(text, str) or not text:
        return ("" if not isinstance(text, str) else text), 0
    no_comments, n_comments = _strip_html_comments_outside_fences(text)
    cleaned, n_unicode = _clean_unicode_stream(no_comments, allow_newlines=True, allow_tabs=True)
    return cleaned, n_comments + n_unicode


def spotlight_untrusted(text: str, nonce: str | None = None) -> tuple[str, str]:
    """Wrap untrusted page text in per-call 128-bit random-nonce delimiters."""
    tok = nonce if (isinstance(nonce, str) and len(nonce) == 32) else secrets.token_hex(16)
    return f"<<<UNTRUSTED_WEB_DATA_{tok}>>>\n{text}\n<<<END_UNTRUSTED_WEB_DATA_{tok}>>>", tok


def _sanitize_search_items(items: list) -> int:
    stripped = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        for key, lim in (("title", 300), ("description", 1000)):
            val = item.get(key)
            if isinstance(val, str):
                cleaned = sanitize_field(val, limit=lim)
                if cleaned != val:
                    item[key] = cleaned
                    stripped += 1
        md = item.get("markdown")
        if isinstance(md, str):
            cleaned_md, n = sanitize_markdown(md)
            if n:
                item["markdown"] = cleaned_md
                stripped += n
    return stripped


def _sanitize_scrape_data(data: dict) -> tuple[bool, int]:
    stripped = 0
    mutated = False
    md = data.get("markdown")
    if isinstance(md, str):
        cleaned_md, n = sanitize_markdown(md)
        if n or cleaned_md != md:
            data["markdown"] = cleaned_md
            stripped += n
            mutated = True
    ans = data.get("answer")
    if isinstance(ans, str):
        cleaned_ans, n = sanitize_markdown(ans)
        if n or cleaned_ans != ans:
            data["answer"] = cleaned_ans
            stripped += n
            mutated = True
    meta = data.get("metadata")
    if isinstance(meta, dict):
        for key in _META_FIELD_KEYS:
            val = meta.get(key)
            if isinstance(val, str):
                cleaned = sanitize_field(val, limit=300 if key != "description" and key != "ogDescription" else 1000)
                if cleaned != val:
                    meta[key] = cleaned
                    stripped += 1
                    mutated = True
    return mutated, stripped


def sanitize_firecrawl_reply(path: str, doc: object) -> tuple[bool, int]:
    """Sanitize a Firecrawl JSON response dict in-place on /scrape and /search routes.

    Returns `(mutated, stripped_events_count)`. Clean payloads are left byte-for-byte untouched.
    """
    if not isinstance(doc, dict):
        return False, 0
    route = path.split("?", 1)[0].rstrip("/")
    data = doc.get("data")
    stripped = 0
    mutated = False
    if route.endswith("/scrape") and isinstance(data, dict):
        mutated, stripped = _sanitize_scrape_data(data)
    elif route.endswith("/search"):
        if isinstance(data, list):
            stripped += _sanitize_search_items(data)
            mutated = stripped > 0
        elif isinstance(data, dict):
            for val in data.values():
                if isinstance(val, list):
                    stripped += _sanitize_search_items(val)
            mutated = stripped > 0
    return mutated, stripped
