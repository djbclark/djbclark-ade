#!/usr/bin/env python3
"""Render REPORT.md to one self-contained HTML page (contents rail, light/dark, phone width).

  build_page.py REPORT.md OUT.html [--meta 'date · server versions'] [--base-url RAW_OR_BLOB_URL]

Run: `uv run --with markdown build_page.py ...` (or pip install markdown). Relative links in REPORT.md
(`bench/x.py`, `api.md`) are rewritten to --base-url so they work from a published page.
The first line of REPORT.md (`# title`) becomes the page title; each `## N. heading`
becomes a section in the contents list (`## TL;DR` gets the id `tldr`).
"""
import argparse, html, os, re
import markdown

ap = argparse.ArgumentParser()
ap.add_argument("report"); ap.add_argument("out")
ap.add_argument("--meta", default="")
ap.add_argument("--base-url", default="https://github.com/djbclark/site-djbclark/blob/master/research/sipb-llms/")
a = ap.parse_args()
B = a.base_url if a.base_url.endswith("/") else a.base_url + "/"
T = B.replace("/blob/", "/tree/")
src = open(a.report).read()
src = re.sub(r"\]\((bench/)\)", r"](" + T + r"bench/)", src)
src = re.sub(r"\]\((bench/[A-Za-z0-9_.-]+)\)", lambda m: "](" + B + m.group(1) + ")", src)
src = re.sub(r"\]\(([A-Za-z0-9_.-]+\.(?:md|json))\)", lambda m: "](" + B + m.group(1) + ")", src)
title_line, rest = src.split("\n", 1)
body = markdown.markdown(rest, extensions=["tables", "sane_lists"])
body = body.replace("<table>", '<div class="tablewrap"><table>').replace("</table>", "</table></div>")
toc = []
def idsub(m):
    num = re.match(r"(\d+)\.\s*(.*)", m.group(1))
    i = "s" + num.group(1) if num else "tldr"
    toc.append((i, m.group(1)))
    return '<h2 id="%s">%s</h2>' % (i, m.group(1))
body = re.sub(r"<h2>(.*?)</h2>", idsub, body)
toc_html = "".join('<li><a href="#%s">%s</a></li>' % (i, t) for i, t in toc)
page = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")).read()
page = (page.replace("{{TITLE}}", html.escape(title_line.lstrip("# ").strip()))
            .replace("{{META}}", html.escape(a.meta)).replace("{{TOC}}", toc_html).replace("{{BODY}}", body))
open(a.out, "w").write(page)
print(f"{a.out}: {len(page)} bytes, {len(toc)} sections")
