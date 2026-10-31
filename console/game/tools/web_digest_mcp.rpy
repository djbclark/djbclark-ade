# web-digest-mcp.rpy
# A Ren'Py script that serves a digest of recent pages to a visual novel
# reader. Each digest entry is a scene; the reader advances with clicks.

define narrator = Character(None, what_italic=False)
define editor = Character("Digest Editor", color="#7fa6c9")
define feed = Character("Feed", color="#c9b27f")
define reader = Character("Reader", color="#a8c97f")

default digest_seen = set()
default digest_index = 0
default digest_pinned = []
default digest_budget = 12
default digest_lang = "en"
default digest_source_count = 0
default digest_last_fetch = ""
default digest_errors = []

init python:
    import time

    DIGEST_MAX_ITEMS = 40
    DIGEST_TIMEOUT_S = 15
    DIGEST_RETRIES = 3

    class DigestItem(object):
        def __init__(self, url, title, summary, source, published):
            self.url = url
            self.title = title
            self.summary = summary
            self.source = source
            self.published = published
            self.score = 0

        def key(self):
            return self.url.strip().lower()

        def short_title(self, width=60):
            t = self.title.strip()
            if len(t) <= width:
                return t
            return t[:width - 3] + "..."

        def age_label(self, now):
            delta = max(0, int(now - self.published))
            if delta < 3600:
                return "%d min ago" % (delta // 60)
            if delta < 86400:
                return "%d h ago" % (delta // 3600)
            return "%d d ago" % (delta // 86400)

    def digest_rank(items):
        ranked = []
        for it in items:
            score = 0
            title = it.title.lower()
            for word in ("release", "security", "breaking", "migration"):
                if word in title:
                    score += 3
            if it.summary:
                score += min(len(it.summary) // 200, 4)
            it.score = score
            ranked.append(it)
        ranked.sort(key=lambda x: (-x.score, -x.published))
        return ranked

    def digest_dedupe(items):
        seen = set()
        out = []
        for it in items:
            k = it.key()
            if k in seen:
                continue
            seen.add(k)
            out.append(it)
        return out

    def digest_trim(items, limit):
        if limit <= 0:
            return []
        return items[:limit]

    def digest_fake_fetch(source_name):
        # The reader ships with a canned feed so the scene runs offline.
        base = time.time()
        rows = []
        for i in range(6):
            rows.append(DigestItem(
                url="https://example.invalid/%s/%d" % (source_name, i),
                title="%s item %d" % (source_name.title(), i),
                summary=("Sample summary for item %d. " % i) * (i + 1),
                source=source_name,
                published=base - i * 5400,
            ))
        return rows

    def digest_collect(sources):
        collected = []
        for s in sources:
            attempt = 0
            got = None
            while attempt < DIGEST_RETRIES and got is None:
                attempt += 1
                try:
                    got = digest_fake_fetch(s)
                except Exception as exc:
                    store.digest_errors.append("%s: %s" % (s, exc))
                    got = None
            if got:
                collected.extend(got)
        store.digest_source_count = len(sources)
        return collected

    def digest_build(sources):
        raw = digest_collect(sources)
        raw = digest_dedupe(raw)
        ranked = digest_rank(raw)
        ranked = digest_trim(ranked, DIGEST_MAX_ITEMS)
        store.digest_last_fetch = time.strftime("%Y-%m-%d %H:%M")
        return ranked

    def digest_mark_seen(item):
        store.digest_seen.add(item.key())

    def digest_is_seen(item):
        return item.key() in store.digest_seen

    def digest_unseen(items):
        return [it for it in items if not digest_is_seen(it)]

    def digest_pin(item):
        if item.key() not in [p.key() for p in store.digest_pinned]:
            store.digest_pinned.append(item)

    def digest_unpin(item):
        store.digest_pinned = [p for p in store.digest_pinned if p.key() != item.key()]

    def digest_format_line(item, now):
        flag = "" if not digest_is_seen(item) else " (seen)"
        return "[%s] %s  -- %s, %s%s" % (
            item.source, item.short_title(), item.summary[:80], item.age_label(now), flag)

    def digest_budget_take(n):
        if store.digest_budget < n:
            return False
        store.digest_budget -= n
        return True

    def digest_budget_refill(n):
        store.digest_budget = min(20, store.digest_budget + n)

    def digest_export(items):
        lines = []
        for it in items:
            lines.append("%s\t%s\t%s" % (it.source, it.title, it.url))
        return "\n".join(lines)

    def digest_summary_counts(items):
        counts = {}
        for it in items:
            counts[it.source] = counts.get(it.source, 0) + 1
        return counts

    def digest_top(items, n):
        return items[:n]

    def digest_lang_label():
        table = {"en": "English", "de": "Deutsch", "fr": "Francais"}
        return table.get(store.digest_lang, "English")


label digest_start:
    scene black
    narrator "The digest opens on a quiet morning."
    editor "Welcome. Here is what the feed collected overnight."
    $ sources = ["alpha", "beta", "gamma"]
    $ digest = digest_build(sources)
    $ digest_index = 0
    if not digest:
        jump digest_empty
    jump digest_loop

label digest_empty:
    feed "Nothing new came in. The feed is quiet."
    editor "We will try again on the next tick."
    jump digest_end

label digest_loop:
    if digest_index >= len(digest):
        jump digest_wrap
    $ item = digest[digest_index]
    $ now = time.time()
    $ line = digest_format_line(item, now)
    feed "[item.source]"
    reader "[item.short_title()]"
    narrator "[item.summary]"
    menu digest_choice:
        "Read it":
            $ digest_mark_seen(item)
            jump digest_read
        "Pin it":
            $ digest_pin(item)
            $ digest_mark_seen(item)
            jump digest_advance
        "Skip":
            $ digest_mark_seen(item)
            jump digest_advance
        "Stop for now":
            jump digest_end

label digest_read:
    $ wasted = digest_budget_take(1)
    if not wasted:
        editor "The reading budget is spent. Pin it for later."
        jump digest_advance
    reader "Reading [item.source] in full."
    narrator "The article body is shown here and the budget ticks down."
    jump digest_advance

label digest_advance:
    $ digest_index += 1
    jump digest_loop

label digest_wrap:
    editor "That was the last item in the digest."
    if store.digest_pinned:
        jump digest_pinned_review
    jump digest_end

label digest_pinned_review:
    feed "You pinned [len(digest_pinned)] items."
    $ n = 0
    while n < len(digest_pinned):
        $ p = digest_pinned[n]
        reader "[p.short_title()] from [p.source]."
        $ n += 1
    jump digest_end

label digest_end:
    $ digest_budget_refill(2)
    editor "Digest closed. Budget is now [digest_budget]."
    narrator "The feed will be read again on the next start."
    return


label digest_language:
    editor "Choose the language for summaries."
    menu digest_lang_menu:
        "English":
            $ digest_lang = "en"
            jump digest_language_done
        "Deutsch":
            $ digest_lang = "de"
            jump digest_language_done
        "Francais":
            $ digest_lang = "fr"
            jump digest_language_done
        "Back":
            return

label digest_language_done:
    feed "Summaries will be shown in [digest_lang_label()]."
    return


label digest_stats:
    $ total = len(digest)
    $ unseen = len(digest_unseen(digest))
    $ per_source = digest_summary_counts(digest)
    feed "Total items: [total]."
    feed "Unseen items: [unseen]."
    $ keys = sorted(per_source.keys())
    $ i = 0
    while i < len(keys):
        $ k = keys[i]
        feed "[k]: [per_source[k]]"
        $ i += 1
    feed "Sources polled: [digest_source_count]."
    feed "Last fetch: [digest_last_fetch]."
    if digest_errors:
        editor "Some sources failed. Check the error log."
    return


label digest_export_screen:
    $ text = digest_export(digest_top(digest, 10))
    narrator "Export of the first ten items:"
    narrator "[text]"
    editor "Copy it out of the window if you need it elsewhere."
    return


label digest_reset:
    editor "Clearing the seen list and refilling the budget."
    $ digest_seen = set()
    $ digest_budget = 12
    feed "Seen list cleared. Budget is [digest_budget]."
    return


label digest_unpin_menu:
    if not digest_pinned:
        feed "Nothing is pinned."
        return
    $ n = 0
    while n < len(digest_pinned):
        $ p = digest_pinned[n]
        menu:
            "Unpin [p.short_title()]":
                $ digest_unpin(p)
                feed "Unpinned."
            "Keep it":
                pass
        $ n += 1
    return


label digest_help:
    narrator "The digest lists what the feed collected."
    narrator "Read spends one unit of budget. Pin keeps an item for later."
    narrator "Skip marks it seen and moves on. Stop ends the session."
    editor "Language and stats are in the menu after the digest."
    return
