## web-digest: one-call web research digest for small-context models.
## Port of the original bin/web-digest (Python). Entry label: tool_web_digest; arguments in ade_argv.
##
##   web-digest "<question>" [--url URL ...] [--max-tokens 700] [--pages 4] [--thorough] [--timeout 120]
##
## Searches (or reads the given --url pages), fetches the best pages through the web-get failover
## ladder, ranks passages against the question (BM25, no model call) and prints a few cited passages
## inside a hard size cap. Exit 0 ok, 2 usage, 5 nothing could be fetched or searched.
## Output goes to the process stdout/stderr because the caller captures it; narrator is not used.

init python:
    import argparse
    import concurrent.futures as cf
    import json
    import math
    import os
    import re
    import subprocess
    import sys
    import time
    from collections import Counter
    from pathlib import Path

    # renpy.config.basedir is console/; the original looks for web-get beside itself in bin/.
    WD_HERE = Path(renpy.config.basedir).resolve().parent / "bin"
    WD_WEB_GET = os.environ.get("WEB_DIGEST_WEB_GET") or str(WD_HERE / "web-get")
    WD_CHARS_PER_TOKEN = 4
    WD_FAST_SKIP = "crawl4ai,wayback"
    WD_PASSAGE_MAX = 700
    WD_PASSAGE_MIN = 60
    WD_STOP = set(
        "a an and are as at be but by can do does for from has have how i if in into is it its of on "
        "or that the their then there these this to was were what when where which who why will with "
        "you your about use using used get gets".split()
    )

    def wd_tokens(text):
        out = []
        for w in re.findall(r"[a-z0-9][a-z0-9.+#_-]*", text.lower()):
            w = w.strip(".-_")
            if not w or w in WD_STOP:
                continue
            for suf in ("ing", "ed", "es", "s"):
                if len(w) > len(suf) + 3 and w.endswith(suf):
                    w = w[: -len(suf)]
                    break
            out.append(w)
        return out

    def wd_clean(md):
        md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)
        md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)
        md = re.sub(r"https?://\S{60,}", "", md)
        md = re.sub(r"<[^>]{1,200}>", "", md)
        md = re.sub(r"[ \t]+", " ", md)
        return md

    def wd_passages(text):
        """Split page text into passages of WD_PASSAGE_MIN..WD_PASSAGE_MAX characters."""
        out = []
        buf = ""
        for block in re.split(r"\n\s*\n", wd_clean(text)):
            block = block.strip()
            if not block:
                continue
            links = len(re.findall(r"\bhttps?://", block))
            if links > 3 and len(block) / (links + 1) < 80:
                continue
            if len(block) < WD_PASSAGE_MIN:
                buf = (buf + " " + block).strip() if len(buf) + len(block) < WD_PASSAGE_MAX else block
                if len(buf) >= WD_PASSAGE_MIN * 2:
                    out.append(buf)
                    buf = ""
                continue
            if buf:
                out.append(buf)
                buf = ""
            while len(block) > WD_PASSAGE_MAX:
                cut = max(block.rfind(". ", 0, WD_PASSAGE_MAX), block.rfind("\n", 0, WD_PASSAGE_MAX))
                cut = cut + 1 if cut > WD_PASSAGE_MAX // 2 else WD_PASSAGE_MAX
                out.append(block[:cut].strip())
                block = block[cut:].strip()
            if block:
                out.append(block)
        if buf:
            out.append(buf)
        return out

    def wd_rank(question, docs, k1=1.4, b=0.75):
        """docs: (source_no, passage, boost). Returns [(score, source_no, passage)], best first."""
        q = wd_tokens(question)
        if not docs:
            return []
        toks = [wd_tokens(p) for _, p, _ in docs]
        avg = sum(len(t) for t in toks) / len(toks) or 1
        df = Counter()
        for t in toks:
            df.update(set(t))
        n = len(docs)
        scored = []
        for (src, p, boost), t in zip(docs, toks):
            tf = Counter(t)
            s = 0.0
            for w in set(q):
                if w not in tf:
                    continue
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                s += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(t) / avg))
            scored.append((s * boost, src, p))
        scored.sort(key=lambda x: -x[0])
        return scored

    def wd_parse_search(content):
        res = []
        for block in re.split(r"\n---\n", content):
            m = re.search(r"^URL:\s*(\S+)", block, re.M)
            if not m:
                continue
            title = re.search(r"^Title:\s*(.+)$", block, re.M)
            snip = re.search(r"^Snippet:\s*(.*)", block, re.M | re.S)
            res.append({
                "url": m.group(1),
                "title": title.group(1).strip() if title else m.group(1),
                "snippet": snip.group(1).strip() if snip else "",
            })
        return res

    def wd_run_web_get(args, timeout):
        try:
            p = subprocess.run([WD_WEB_GET, *args, "--json"], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"timeout after {timeout:.0f}s"}
        try:
            d = json.loads(p.stdout)
        except ValueError:
            return {"ok": False, "error": (p.stderr.strip().splitlines() or ["no output"])[-1][:200]}
        if not d.get("ok"):
            errs = "; ".join(f"{a['provider']}: {a.get('error')}" for a in d.get("attempts", [])[-3:])
            d["error"] = errs or "all providers failed"
        return d

    def wd_fetch_page(url, thorough, deadline):
        left = max(10.0, deadline - time.monotonic())
        args = ["fetch", url, "--max-bytes", "300000", "--timeout", "30" if not thorough else "60"]
        if not thorough:
            args += ["--skip", WD_FAST_SKIP, "--walk-budget", "15"]
        return url, wd_run_web_get(args, left)

    def wd_digest(question, urls, max_tokens, pages, thorough, total_s):
        deadline = time.monotonic() + total_s
        notes = []
        if urls:
            sources = [{"url": u, "title": u, "snippet": ""} for u in urls]
        else:
            s = wd_run_web_get(["search", question, "--n", str(max(pages + 2, 6))], min(90.0, total_s))
            if not s.get("ok"):
                return None, f"search failed: {s.get('error')}"
            sources = wd_parse_search(s.get("content", ""))
            if not sources:
                return None, "search returned no results"
            sources = sources[: pages + 2]
        want = sources if urls else sources[:pages]
        docs = []
        fetched = {}
        with cf.ThreadPoolExecutor(max_workers=min(4, len(want) or 1)) as ex:
            futs = [ex.submit(wd_fetch_page, s["url"], thorough, deadline) for s in want]
            for f in futs:
                url, d = f.result()
                if d.get("ok"):
                    fetched[url] = d.get("content", "")
                    if d.get("truncated"):
                        notes.append(f"CUT SHORT: {url} (provider size cap; only the start was read)")
                else:
                    notes.append(f"NOT FETCHED: {url} ({d.get('error')}); "
                                 f"retry: web-digest --thorough --url {url} \"...\"")
        numbered = []
        for s in sources:
            n = len(numbered) + 1
            numbered.append((n, s))
            if s["snippet"]:
                for p in wd_passages(re.sub(r"\s*\n?\.\.\.\n?\s*", "\n\n", s["snippet"])):
                    docs.append((n, p, 1.25))
            body = fetched.get(s["url"])
            if body:
                for p in wd_passages(body):
                    docs.append((n, p, 1.0))
        if not docs:
            return None, "no readable text: " + " | ".join(notes[:4] or ["nothing fetched"])
        ranked = wd_rank(question, docs)
        budget = max_tokens * WD_CHARS_PER_TOKEN
        picked = []
        seen = set()
        per_src = Counter()
        used = 0
        top = ranked[0][0] if ranked else 0.0
        for score, src, p in ranked:
            if picked and (score <= 0 or score < 0.3 * top):
                break
            key = re.sub(r"\W+", " ", p.lower())[:80]
            if key in seen or per_src[src] >= 3:
                continue
            if used + len(p) > budget and picked:
                continue
            picked.append((src, p))
            seen.add(key)
            per_src[src] += 1
            used += len(p)
            if used >= budget:
                break
        used_src = sorted({n for n, _ in picked})
        out = ["SOURCES:"]
        for n, s in numbered:
            if n in used_src:
                out.append(f"[{n}] {s['title'][:100]} - {s['url']}")
        out.append("")
        out.append("PASSAGES (ranked by relevance to the question; cite sources by [n]):")
        for n, p in picked:
            out.append(f"[{n}] {' '.join(p.split())}")
        if notes:
            out.append("")
            out += notes
        return "\n".join(out), None

    def wd_main(argv):
        """Return (exit_code, text_for_stdout_or_None)."""
        ap = argparse.ArgumentParser(prog="web-digest", description="One-call web research digest for small-context models.")
        ap.add_argument("question", help="the question or search query")
        ap.add_argument("--url", action="append", default=[], help="read this page instead of searching (repeatable)")
        ap.add_argument("--max-tokens", type=int, default=700, help="output cap in tokens (default 700, hard max 2000)")
        ap.add_argument("--pages", type=int, default=4, help="search results to fetch (default 4)")
        ap.add_argument("--thorough", action="store_true", help="walk the whole ladder per page (slower)")
        ap.add_argument("--timeout", type=float, default=120.0, help="total wall-clock budget in seconds")
        try:
            a = ap.parse_args(argv)
        except SystemExit as exc:
            return (exc.code if isinstance(exc.code, int) else 2), None
        a.max_tokens = max(100, min(a.max_tokens, 2000))
        text, err = wd_digest(a.question, a.url, a.max_tokens, max(1, min(a.pages, 8)), a.thorough, a.timeout)
        if err:
            msg = ("WEB-DIGEST FAILED: " + err + "\n"
                   "STOP. Tell the user the web lookup failed and quote the line above. "
                   "Do NOT answer from memory and do not guess.")
            return 5, msg
        return 0, text

label tool_web_digest:
    python:
        _wd_code, _wd_out = wd_main(ade_argv)
        if _wd_out is not None:
            print(_wd_out, file=sys.__stdout__)
        sys.__stdout__.flush()
        sys.__stderr__.flush()
        ade_exit_code = _wd_code
    return
