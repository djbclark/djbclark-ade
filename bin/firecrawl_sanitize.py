"""firecrawl_sanitize: Anti-prompt-injection sanitizer & spotlighting helpers for bin/firecrawl-router (stdlib only).

Aligned with BarnOwl's `goose-helper.py` `_s`/`_f` untrusted-text sanitizer and
`docs/security/argon-injection-review-2026-11-07.md` (`S4.1`, `C0d.2`, `C0d.3`):

  1. Unicode smuggling stream filter (`_clean_unicode_stream`, linear-time `O(N)`):
     strips control chars (`Cc`), format chars (`Cf`: zero-width, bidi overrides,
     Unicode Tag block `U+E0000..U+E007F` used for invisible "ASCII smuggling"),
     private-use (`Co`), unassigned (`Cn`), surrogates (`Cs`), variation
     selectors (`U+FE00..U+FE0F`, `U+E0100..U+E01EF`), Mongolian variation
     selectors and Default_Ignorable fillers (`U+034F`, `U+115F`, `U+1160`,
     `U+17B4`, `U+17B5`, `U+180B..U+180D`, `U+180F`, `U+3164`, `U+FFA0`),
     line/paragraph separators (`Zl`/`Zp`), bare `\\r`, and excessive combining
     marks (> 2 consecutive), replacing each stripped run with a single `U+FFFD`
     so hidden chars cannot silently splice adjacent tokens. Preserves clean
     CRLF (`\\r\\n`) and scholarly math (`x² + ½α`) so clean payloads stay
     byte-for-byte untouched.
  2. HTML comment stripper (`_strip_html_comments`, linear-time `O(N)`): runs
     AFTER Unicode cleaning, splits strictly on `\\n` (never `splitlines()`),
     handles HTML5 short/alternate comments (`<!-->`, `<!--->`, `--!>`), inserts
     `\\ufffd` when stripping a comment flanked by word chars (`ig<!--x-->nore`
     -> `ig\\ufffdnore`), and preserves comments inside Markdown code fences ONLY
     when the fence obeys CommonMark §4.5 (no backticks in backtick info string)
     AND has a verified matching closing fence before EOF.
  3. Covers all Firecrawl content routes (`/scrape`, `/search`,
     `/search/developer`, `/map`, `/crawl`, `/batch/scrape`, `/extract`) and all
     untrusted fields (`markdown`, `answer`, `summary`, `html`, `rawHtml`,
     `links`, `json`, and every string inside `metadata`).
  4. Per-call 128-bit random-nonce spotlighting (`spotlight_untrusted`) for
     `Extractor` prompts.
"""

from __future__ import annotations

import re
import secrets
import unicodedata

_VARIATION_SELECTORS = ((0xFE00, 0xFE0F), (0xE0100, 0xE01EF))
_EXTRA_IGNORABLES = frozenset((
    0x034F,  # COMBINING GRAPHEME JOINER
    0x115F,  # HANGUL CHOSEONG FILLER
    0x1160,  # HANGUL JUNGSEONG FILLER
    0x17B4,  # KHMER VOWEL INHERENT AQ
    0x17B5,  # KHMER VOWEL INHERENT AA
    0x180B,  # MONGOLIAN FREE VARIATION SELECTOR ONE
    0x180C,  # MONGOLIAN FREE VARIATION SELECTOR TWO
    0x180D,  # MONGOLIAN FREE VARIATION SELECTOR THREE
    0x180F,  # MONGOLIAN FREE VARIATION SELECTOR FOUR
    0x3164,  # HANGUL FILLER
    0xFFA0,  # HALFWIDTH HANGUL FILLER
))
_MAX_COMBINING_MARKS = 2
_MAX_JSON_DEPTH = 16
_NONCE_HEX_RE = re.compile(r"^[0-9a-f]{32}$")

_CONTENT_ROUTE_RE = re.compile(
    r"^/v\d+/(?:scrape|search(?:/developer)?|map|crawl(?:/[^/]+)?|batch/scrape(?:/[^/]+)?|extract(?:/[^/]+)?)$"
)


def is_content_route(path: str) -> bool:
    """True when `path` is a Firecrawl route that can return untrusted web/document content."""
    route = path.split("?", 1)[0].rstrip("/").lower()
    if route in ("/scrape", "/search", "/search/developer", "/map"):
        return True
    return bool(_CONTENT_ROUTE_RE.match(route))


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

    Preserves clean `\\r\\n` when `allow_newlines=True` so benign CRLF replies remain
    byte-for-byte untouched; any bare `\\r` is treated as hostile `Cc` (`\\ufffd`).
    Each contiguous run of hostile/hidden characters is replaced with a single `U+FFFD`.
    """
    out: list[str] = []
    in_run = False
    marks = 0
    stripped_runs = 0
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        # Clean CRLF handling: preserve when multiline, collapse to space when single-line.
        if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
            in_run = False
            marks = 0
            if allow_newlines:
                out.append("\r\n")
            else:
                out.append(" ")
            i += 2
            continue

        cp = ord(ch)
        cat = unicodedata.category(ch)
        if ch == "\t":
            in_run = False
            marks = 0
            out.append("\t" if allow_tabs else " ")
            i += 1
            continue

        if ch == "\n":
            in_run = False
            marks = 0
            out.append("\n" if allow_newlines else " ")
            i += 1
            continue

        if cat == "Zs" and ch != " ":
            in_run = False
            marks = 0
            out.append(" ")
            i += 1
            continue

        bad = (
            cat in ("Cc", "Cf", "Co", "Cn", "Cs", "Zl", "Zp")
            or _is_variation_selector(cp)
            or cp in _EXTRA_IGNORABLES
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
            i += 1
            continue

        in_run = False
        out.append(ch)
        i += 1
    return "".join(out), stripped_runs


def _find_html_comment_end(text: str, after_open: int) -> int:
    """Return index immediately after the closing delimiter of an HTML5 comment, or -1 if unclosed.

    `after_open` is the index immediately after `<!--`.
    Handles HTML5 short comments `<!-->` (starts with `>`) and `<!--->` (starts with `->`)
    as well as standard `-->` and HTML5 alternate closer `--!>`.
    """
    n = len(text)
    if after_open < n and text[after_open] == ">":
        return after_open + 1
    if after_open + 1 < n and text[after_open : after_open + 2] == "->":
        return after_open + 2
    pos = after_open
    while pos < n:
        idx = text.find("--", pos)
        if idx == -1:
            return -1
        if idx + 2 < n and text[idx + 2] == ">":
            return idx + 3
        if idx + 3 < n and text[idx + 2 : idx + 4] == "!>":
            return idx + 4
        pos = idx + 1
    return -1


def _strip_comments_plain(text: str) -> tuple[str, int]:
    """Strip HTML comments from `text` in O(N) time without fence exemptions."""
    if "<!--" not in text:
        return text, 0
    out: list[str] = []
    pos = 0
    n = len(text)
    count = 0
    while pos < n:
        start = text.find("<!--", pos)
        if start == -1:
            out.append(text[pos:])
            break
        if start > pos:
            out.append(text[pos:start])
        end = _find_html_comment_end(text, start + 4)
        count += 1
        if end == -1:
            # Unclosed comment: drop to end of string so payload cannot survive.
            if start > 0 and text[start - 1].isalnum():
                out.append("\ufffd")
            break
        # Prevent silent token splicing (`ig<!-- x -->nore` -> `ig\ufffdnore`).
        left_word = start > 0 and text[start - 1].isalnum()
        right_word = end < n and text[end].isalnum()
        if left_word and right_word:
            out.append("\ufffd")
        pos = end
    return "".join(out), count


def _parse_fence_open(line: str) -> tuple[str, int] | None:
    """CommonMark §4.5 opening fence parser: at most 3 leading spaces, >=3 backticks or tildes;
    backtick info strings MUST NOT contain any backtick (rejects inline ` ```code``` ` spoofs)."""
    core = line[:-1] if line.endswith("\n") else line
    if core.endswith("\r"):
        core = core[:-1]
    stripped = core.lstrip(" ")
    if len(core) - len(stripped) > 3 or len(stripped) < 3:
        return None
    ch = stripped[0]
    if ch not in ("`", "~"):
        return None
    run = 0
    while run < len(stripped) and stripped[run] == ch:
        run += 1
    if run < 3:
        return None
    info = stripped[run:]
    if ch == "`" and "`" in info:
        return None
    return ch, run


def _is_fence_close(line: str, fence_char: str, fence_len: int) -> bool:
    core = line[:-1] if line.endswith("\n") else line
    if core.endswith("\r"):
        core = core[:-1]
    stripped = core.lstrip(" ")
    if len(core) - len(stripped) > 3 or len(stripped) < fence_len:
        return False
    if stripped[0] != fence_char:
        return False
    run = 0
    while run < len(stripped) and stripped[run] == fence_char:
        run += 1
    return run >= fence_len and stripped[run:].strip(" \t") == ""


def _strip_html_comments(text: str, *, preserve_fences: bool) -> tuple[str, int]:
    """Strip HTML comments in O(N) time; splits strictly on `\\n` (never `splitlines()`).

    When `preserve_fences=True`, HTML comments inside a Markdown fenced code block are
    preserved ONLY when the fence satisfies CommonMark §4.5 AND has a verified matching
    closing fence before EOF (defeating both inline-span and unclosed-fence spoofs).
    """
    if "<!--" not in text:
        return text, 0
    if not preserve_fences:
        return _strip_comments_plain(text)

    # Split strictly on '\n' preserving '\n' endings.
    parts = text.split("\n")
    lines = [p + "\n" for p in parts[:-1]]
    if parts[-1] != "" or not lines:
        lines.append(parts[-1])

    out: list[str] = []
    plain_buf: list[str] = []
    fence_buf: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    total_stripped = 0

    def _flush_plain() -> None:
        nonlocal total_stripped
        if not plain_buf:
            return
        chunk, n = _strip_comments_plain("".join(plain_buf))
        total_stripped += n
        out.append(chunk)
        plain_buf.clear()

    for line in lines:
        if not in_fence:
            opened = _parse_fence_open(line)
            if opened is not None:
                # Only allow opening a fence if plain_buf is not currently inside an open HTML comment.
                plain_joined = "".join(plain_buf)
                last_open = plain_joined.rfind("<!--")
                in_open_comment = last_open != -1 and _find_html_comment_end(plain_joined, last_open + 4) == -1
                if not in_open_comment:
                    _flush_plain()
                    in_fence = True
                    fence_char, fence_len = opened
                    fence_buf.append(line)
                    continue
            plain_buf.append(line)
        else:
            fence_buf.append(line)
            if _is_fence_close(line, fence_char, fence_len):
                # Verified closed fence: preserve its lines verbatim.
                out.extend(fence_buf)
                fence_buf.clear()
                in_fence = False
                fence_char = ""
                fence_len = 0

    if in_fence and fence_buf:
        # Unclosed fence at EOF: refuse fence exemption and strip comments inside it too.
        chunk, n = _strip_comments_plain("".join(fence_buf))
        total_stripped += n
        out.append(chunk)
        fence_buf.clear()

    _flush_plain()
    return "".join(out), total_stripped


def _sanitize_field_counted(text: object, limit: int = 300) -> tuple[str, int]:
    """Single-line metadata sanitizer: strips hidden/smuggling Unicode & HTML comments, collapses whitespace.

    Preserves legitimate scholarly symbols (`x² + ½α`) without destructive NFKC folding.
    """
    if not isinstance(text, str) or limit <= 0:
        return "", 0
    bounded = text[: limit * 4]
    u_clean, n_u = _clean_unicode_stream(bounded, allow_newlines=False, allow_tabs=False)
    c_clean, n_c = _strip_html_comments(u_clean, preserve_fences=False)
    collapsed = " ".join(c_clean.split())[:limit]
    events = n_u + n_c
    if events == 0 and collapsed != text:
        # Newline / multi-space / over-limit normalization in metadata
        if "\n" in text or "\r" in text or "\t" in text:
            events = 1
    return collapsed, events


def sanitize_field(text: object, limit: int = 300) -> str:
    """Single-line metadata sanitizer (returns cleaned string)."""
    cleaned, _ = _sanitize_field_counted(text, limit=limit)
    return cleaned


def sanitize_markdown(text: str) -> tuple[str, int]:
    """Sanitize scraped Markdown / document body for agent & Extractor consumption.

    Runs Unicode smuggling filter FIRST, then strips HTML comments outside verified closed fences.
    Returns `(cleaned_text, stripped_events_count)`.
    """
    if not isinstance(text, str) or not text:
        return ("" if not isinstance(text, str) else text), 0
    u_clean, n_unicode = _clean_unicode_stream(text, allow_newlines=True, allow_tabs=True)
    c_clean, n_comments = _strip_html_comments(u_clean, preserve_fences=True)
    return c_clean, n_unicode + n_comments


def sanitize_html(text: str) -> tuple[str, int]:
    """Sanitize HTML / rawHtml fields (Unicode smuggling + all HTML comments)."""
    if not isinstance(text, str) or not text:
        return ("" if not isinstance(text, str) else text), 0
    u_clean, n_unicode = _clean_unicode_stream(text, allow_newlines=True, allow_tabs=True)
    c_clean, n_comments = _strip_html_comments(u_clean, preserve_fences=False)
    return c_clean, n_unicode + n_comments


def sanitize_json_value(val: object, depth: int = 0) -> tuple[object, int]:
    """Recursively sanitize all strings in a JSON-like value (capped depth)."""
    if depth >= _MAX_JSON_DEPTH:
        return val, 0
    if isinstance(val, str):
        return sanitize_markdown(val)
    if isinstance(val, list):
        total = 0
        changed = False
        out_list = []
        for item in val:
            s_item, n = sanitize_json_value(item, depth + 1)
            total += n
            if n or s_item is not item:
                changed = True
            out_list.append(s_item)
        return (out_list if changed else val), total
    if isinstance(val, dict):
        total = 0
        changed = False
        out_dict = {}
        for k, v in val.items():
            sk, nk = _sanitize_field_counted(k, limit=200) if isinstance(k, str) else (k, 0)
            sv, nv = sanitize_json_value(v, depth + 1)
            total += nk + nv
            if nk or nv or sk != k or sv is not v:
                changed = True
            out_dict[sk] = sv
        return (out_dict if changed else val), total
    return val, 0


def spotlight_untrusted(text: str, nonce: str | None = None) -> tuple[str, str]:
    """Wrap untrusted page text in per-call 128-bit random-nonce delimiters."""
    tok = nonce if (isinstance(nonce, str) and _NONCE_HEX_RE.fullmatch(nonce)) else secrets.token_hex(16)
    return f"<<<UNTRUSTED_WEB_DATA_{tok}>>>\n{text}\n<<<END_UNTRUSTED_WEB_DATA_{tok}>>>", tok


def _sanitize_metadata_dict(meta: dict, depth: int = 0) -> tuple[bool, int]:
    if depth >= _MAX_JSON_DEPTH:
        return False, 0
    mutated = False
    stripped = 0
    for key in list(meta.keys()):
        val = meta[key]
        lim = 1000 if str(key).lower().endswith("description") else 500
        if isinstance(val, str):
            cleaned, n = _sanitize_field_counted(val, limit=lim)
            if n or cleaned != val:
                meta[key] = cleaned
                stripped += max(n, 1) if cleaned != val else n
                mutated = True
        elif isinstance(val, list):
            list_mut = False
            new_list = []
            for item in val:
                if isinstance(item, str):
                    cleaned, n = _sanitize_field_counted(item, limit=500)
                    if n or cleaned != item:
                        stripped += max(n, 1) if cleaned != item else n
                        list_mut = True
                    new_list.append(cleaned)
                else:
                    new_list.append(item)
            if list_mut:
                meta[key] = new_list
                mutated = True
        elif isinstance(val, dict):
            sub_mut, sub_n = _sanitize_metadata_dict(val, depth + 1)
            if sub_mut:
                mutated = True
            stripped += sub_n
    return mutated, stripped


def _sanitize_doc_object(data: dict) -> tuple[bool, int]:
    """Sanitize a Firecrawl document object (scrape / crawl item / batch-scrape item / search item)."""
    stripped = 0
    mutated = False
    for key in ("markdown", "answer", "summary"):
        val = data.get(key)
        if isinstance(val, str):
            cleaned, n = sanitize_markdown(val)
            if n or cleaned != val:
                data[key] = cleaned
                stripped += max(n, 1) if cleaned != val else n
                mutated = True
    for key in ("html", "rawHtml"):
        val = data.get(key)
        if isinstance(val, str):
            cleaned, n = sanitize_html(val)
            if n or cleaned != val:
                data[key] = cleaned
                stripped += max(n, 1) if cleaned != val else n
                mutated = True
    for key, lim in (("title", 300), ("description", 1000)):
        val = data.get(key)
        if isinstance(val, str):
            cleaned, n = _sanitize_field_counted(val, limit=lim)
            if n or cleaned != val:
                data[key] = cleaned
                stripped += max(n, 1) if cleaned != val else n
                mutated = True
    links = data.get("links")
    if isinstance(links, list):
        links_mut = False
        new_links = []
        for item in links:
            if isinstance(item, str):
                cleaned, n = _sanitize_field_counted(item, limit=2048)
                if n or cleaned != item:
                    stripped += max(n, 1) if cleaned != item else n
                    links_mut = True
                new_links.append(cleaned)
            elif isinstance(item, dict):
                sub_mut, sub_n = _sanitize_doc_object(item)
                if sub_mut:
                    links_mut = True
                stripped += sub_n
                new_links.append(item)
            else:
                new_links.append(item)
        if links_mut:
            data["links"] = new_links
            mutated = True
    if "json" in data and data["json"] is not None:
        cleaned_j, n_j = sanitize_json_value(data["json"])
        if n_j or cleaned_j is not data["json"]:
            data["json"] = cleaned_j
            stripped += max(n_j, 1) if cleaned_j is not data["json"] else n_j
            mutated = True
    meta = data.get("metadata")
    if isinstance(meta, dict):
        m_mut, m_n = _sanitize_metadata_dict(meta)
        if m_mut:
            mutated = True
        stripped += m_n
    return mutated, stripped


def _sanitize_doc_list(items: list) -> tuple[bool, int]:
    mutated = False
    stripped = 0
    for idx, item in enumerate(items):
        if isinstance(item, dict):
            sub_mut, sub_n = _sanitize_doc_object(item)
            if sub_mut:
                mutated = True
            stripped += sub_n
        elif isinstance(item, str):
            cleaned, n = _sanitize_field_counted(item, limit=2048)
            if n or cleaned != item:
                items[idx] = cleaned
                stripped += max(n, 1) if cleaned != item else n
                mutated = True
    return mutated, stripped


def sanitize_firecrawl_reply(path: str, doc: object) -> tuple[bool, int]:
    """Sanitize a Firecrawl JSON response dict in-place on all untrusted content routes.

    Returns `(mutated, stripped_events_count)`. Clean payloads are left byte-for-byte untouched.
    """
    if not isinstance(doc, dict) or not is_content_route(path):
        return False, 0
    mutated = False
    stripped = 0

    # Top-level `links` (used by /map)
    if isinstance(doc.get("links"), list):
        l_mut, l_n = _sanitize_doc_list(doc["links"])
        mutated = mutated or l_mut
        stripped += l_n

    # Top-level `data` (dict for /scrape & /extract & /search v2; list for /search v1 & /crawl & /batch/scrape)
    data = doc.get("data")
    if isinstance(data, dict):
        d_mut, d_n = _sanitize_doc_object(data)
        mutated = mutated or d_mut
        stripped += d_n
        # Categorized /search or /search/developer dicts (e.g. {"web": [...], "news": [...], "github": [...]})
        for key, val in data.items():
            if key in ("links", "metadata", "json"):
                continue
            if isinstance(val, list):
                s_mut, s_n = _sanitize_doc_list(val)
                mutated = mutated or s_mut
                stripped += s_n
    elif isinstance(data, list):
        l_mut, l_n = _sanitize_doc_list(data)
        mutated = mutated or l_mut
        stripped += l_n

    return mutated, stripped
