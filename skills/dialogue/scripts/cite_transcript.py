#!/usr/bin/env python3
"""Turn bare evidence markers in the dialogue transcript into numbered superscripts.

    python3 -I cite_transcript.py <transcript.md> <evidence.jsonl> [--allow-empty]

(Ported from hiwymi spec/ai-heaven/tools/cite_transcript.py, 2026-10-10.)

Each run of adjacent bare markers (``[E0927]``, ``[E0927][E0931]``,
``[E0927] [E0931]``, ``[E0927], [E0931]``) becomes one
``<sup>[n](#E0927) [m](#E0931)</sup>`` run. Numbers follow first appearance
across the whole file, counting both bare markers and the ids already cited
inside existing ``<sup>`` runs; existing runs are renumbered to match. A marker
whose id is not in the ledger is left alone and listed. Every
``## Citation footnotes`` section already in the file is removed and one
document-wide section is appended at the end, in the format the spec uses
(claim, title, locator, URL). Nothing else changes; the script verifies that
and is idempotent. Stdlib only, no network.

Acceptance (Grok 4.7 ruling 2.3, 2026-10-10): after conversion the file must have
``targets > 0``, i.e. at least one superscript link whose ``#E####`` target is an
anchor in the footnote list. ``markers=0`` after a conversion is expected and is
not the acceptance line. ``--allow-empty`` accepts a file that cites nothing.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

BARE = re.compile(r"\[(E\d{4})\]")
RUN = re.compile(r"\[E\d{4}\](?:(?:[ \t]*,[ \t]*|[ \t]*)\[E\d{4}\])*")
SUP = re.compile(r"<sup>(.*?)</sup>", re.S)
CITE = re.compile(r"\[(\d+)\]\(#(E\d{4})\)")
HEADING = re.compile(r"(?m)^## Citation footnotes[ \t]*$")
ITEM = re.compile(r"^\d+\. <a id=\"E\d{4}\"></a>E\d{4} ")


def load_rows(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                row = json.loads(line)
                rows[row["id"]] = row
    return rows


def footnote(n: int, eid: str, row: dict) -> str:
    claim = " ".join(str(row.get("claim", "")).split())
    title = " ".join(str(row.get("title", "")).split())
    locator = " ".join(str(row.get("locator", "")).split())
    url = str(row.get("url", "")).strip()
    return f'{n}. <a id="{eid}"></a>{eid} — {claim} — {title}, {locator}. {url}'


def strip_footnotes(text: str) -> tuple[str, int]:
    """Remove every '## Citation footnotes' section (heading, its list items,
    surrounding blank lines). Returns the text and the number of sections."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    removed = 0
    while i < len(lines):
        if HEADING.match(lines[i]):
            removed += 1
            i += 1
            while i < len(lines) and (lines[i].strip() == "" or ITEM.match(lines[i])):
                i += 1
            # drop blank lines already emitted so one blank line separates neighbours
            while out and out[-1].strip() == "":
                out.pop()
            if i < len(lines):
                out.append("")
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out), removed


def tokens(text: str) -> Counter:
    body, _ = strip_footnotes(text)
    body = SUP.sub("", body)
    body = BARE.sub("", body)
    return Counter(body.split())


def convert(text: str, rows: dict[str, dict]) -> tuple[str, dict]:
    body, removed = strip_footnotes(text)
    body = body.rstrip("\n")

    # first-appearance order over bare markers and existing sup citations
    events: list[tuple[int, str]] = []
    for m in BARE.finditer(body):
        events.append((m.start(), m.group(1)))
    for m in SUP.finditer(body):
        for c in CITE.finditer(m.group(1)):
            events.append((m.start() + c.start(), c.group(2)))
    events.sort()
    number: dict[str, int] = {}
    unknown: list[str] = []
    for _, eid in events:
        if eid not in rows:
            if eid not in unknown:
                unknown.append(eid)
            continue
        if eid not in number:
            number[eid] = len(number) + 1

    existing_runs = SUP.findall(body)
    renumbered = 0

    def sub_sup(match: re.Match[str]) -> str:
        nonlocal renumbered
        inner = match.group(1)
        new_inner = CITE.sub(
            lambda c: f"[{number.get(c.group(2), int(c.group(1)))}](#{c.group(2)})", inner
        )
        if new_inner != inner:
            renumbered += 1
        return f"<sup>{new_inner}</sup>"

    body = SUP.sub(sub_sup, body)

    converted = 0
    left: list[str] = []

    def sub_run(match: re.Match[str]) -> str:
        nonlocal converted
        ids = BARE.findall(match.group(0))
        if any(eid not in rows for eid in ids):
            left.extend(eid for eid in ids if eid not in rows)
            return match.group(0)
        converted += len(ids)
        return "<sup>" + " ".join(f"[{number[eid]}](#{eid})" for eid in ids) + "</sup>"

    body = RUN.sub(sub_run, body)

    lines = [footnote(n, eid, rows[eid]) for eid, n in sorted(number.items(), key=lambda kv: kv[1])]
    result = body + "\n\n## Citation footnotes\n\n" + "\n".join(lines) + "\n"
    stats = {
        "footnote_sections_removed": removed,
        "existing_sup_runs": len(existing_runs),
        "existing_runs_renumbered": renumbered,
        "markers_converted": converted,
        "unknown_ids": unknown,
        "markers_left": len(left),
    }
    return result, stats


def report(text: str, rows: dict[str, dict], allow_empty: bool = False) -> bool:
    body, _ = strip_footnotes(text)
    bare = BARE.findall(body)
    sups = SUP.findall(body)
    pairs = [(int(n), eid) for s in sups for n, eid in CITE.findall(s)]
    cited = {eid for _, eid in pairs}
    found = HEADING.search(text)
    foot = text[found.end():] if found else ""
    anchors = re.findall(r'<a id="(E\d{4})"></a>', foot)
    by_id: dict[str, set[int]] = {}
    for n, eid in pairs:
        by_id.setdefault(eid, set()).add(n)
    consistent = all(len(v) == 1 for v in by_id.values())
    order_ok = [eid for eid, _ in sorted(((e, min(v)) for e, v in by_id.items()), key=lambda kv: kv[1])] == anchors
    numbers_ok = sorted(min(v) for v in by_id.values()) == list(range(1, len(by_id) + 1))
    print(f"bare_markers_remaining={len(bare)} {sorted(set(bare)) if bare else ''}")
    print(f"sup_runs={len(sups)}")
    print(f"distinct_ids_cited={len(cited)}")
    print(f"anchors_defined={len(anchors)}")
    print(f"cited_equals_defined={cited == set(anchors)}")
    print(f"numbering_consistent={consistent} dense_1_to_n={numbers_ok} footnote_order={order_ok}")
    print(f"unresolved_cited={[e for e in cited if e not in rows]}")
    targets = sum(1 for _, eid in pairs if eid in set(anchors))
    print(f"targets={targets} (acceptance: targets > 0)")
    return (not bare) and cited == set(anchors) and consistent and numbers_ok and order_ok \
        and (targets > 0 or allow_empty)


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--allow-empty"]
    allow_empty = len(args) != len(sys.argv) - 1
    if len(args) != 2:
        raise SystemExit(__doc__)
    path = Path(args[0])
    rows = load_rows(Path(args[1]))
    before = path.read_text(encoding="utf-8")
    after, stats = convert(before, rows)
    for k, v in stats.items():
        print(f"{k}={v}")
    tb, ta = tokens(before), tokens(after)
    print(f"token_check={'PASS' if tb == ta else 'FAIL'} before={sum(tb.values())} after={sum(ta.values())}")
    if tb != ta:
        diff = (tb - ta) + (ta - tb)
        print(f"token_diff={list(diff.items())[:10]}")
        raise SystemExit(1)
    if after != before:
        path.write_text(after, encoding="utf-8")
        print(f"wrote={path}")
    else:
        print("unchanged")
    ok = report(after, rows, allow_empty)
    raise SystemExit(0 if ok else 2)


if __name__ == "__main__":
    main()
