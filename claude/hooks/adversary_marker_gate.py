#!/usr/bin/env python3
"""adversary_marker_gate: PreToolUse (Bash) hook, an agent never writes a LIVE adversary APPROVE marker to GitHub (am-01).

The `adversary-marker` merge gate (`bin/adversary_marker.py`, docs/code-review.md rule 1, docs/review-boundary.md)
counts an APPROVE only in an owner-authored PR body or an owner-posted comment, and `gh` on this machine is the owner
(`djbclark`). So an agent that runs `gh pr edit --body ...` with a live APPROVE marker forges the review (2026-11-14:
`claude/agents/adversary.md` told the adversary to emit the marker "for the teammate to paste", and a tendcf lead did,
into frdminc/tendcf PR 41). AGENTS.md "Code review" item 1 and docs/code-review.md rule 1 already say agents must not
write a live APPROVE marker (fenced examples only); this hook enforces it.

Denied: a command that contains a `gh` write and, anywhere in what it sends, a LIVE APPROVE marker.
  * a `gh` write is `gh pr|issue create|new|edit|comment|review|close|reopen` (also after `-R X`, `command`, `env`,
    `sudo`, a path, inside `bash -c "..."`, `eval`, `xargs`, or a script heredoc that names it), or `gh api` with a body
    flag (`-f`/`-F`/`--field`/`--raw-field`/`--input`, attached forms included) at ANY endpoint, graphql too;
  * "anywhere in what it sends": once a gh write is present, every word of the whole command is scanned (`--body`,
    `-b`, `-f body=...`, an `echo`/`printf` feeding stdin, a here-string), every heredoc body, and every existing regular
    file a word names (`--body-file F`, `-F F`, `-F body=@F`, `--input F`, `-T F`, `< F`, `cat F`, `jq --rawfile b F`,
    `$(cat F)`, `$(< F)`), after any `cd DIR` earlier in the command.

"Live" is decided by the checker's own parser (`adversary_marker._strip_code`, `_marker_spans`, `MARKER_START_RE`), so what
this gate lets through is what the Action reads as documentation:
  allowed   a BLOCK marker; an APPROVE inside a fenced block or an inline code span; the docs template
            (`"verdict":"APPROVE"|"BLOCK","head":"<40-hex>"`); an APPROVE whose head is the `<...>` placeholder
  denied    a canonical marker whose JSON verdict reads APPROVE (any case) with any other head, a canonical marker
            whose JSON does not parse but mentions APPROVE (a duplicate key, a typo), a near-miss spelling
            (`adversary_verdict`, `adversary-verdict {`) that mentions APPROVE, and a marker whose JSON the shell would
            build (`$V`, `$(cat f)`, a backtick) when APPROVE appears anywhere in the scanned text

Not gated: commands with no `gh` write; `git commit -m`, `curl`, the GitHub MCP, a Python program that calls the API
with no `gh` word; a body built by a variable (`--body "$BODY"`); `gh pr create --fill*` (the body comes from commit
messages); markers hidden by obfuscation (`$'\\x3c'`, an escaped file). `bin/ade-merge-ready approve-post` is the operator's
path: this hook does not see it (it is not a `gh` command), and only the operator, or an agent the operator tells to, runs
it. An agent that wants the verdict recorded puts the marker in its report inside a fenced block.

Failure modes (stated): fails OPEN, with a one-line stderr diagnostic that a hook on exit 0 does not show, for bad stdin,
a non-Bash tool, an unreadable, non-regular or over-256 KB file, any internal error, a missing `bin/adversary_marker.py`
(looked for beside this file's checkout, then `~/src/djbclark-ade/bin`) and a hook timeout (15 s; a pathological body of thousands of
unclosed marker starts can take seconds). Fails CLOSED where the command cannot be parsed: shlex failure (a stray
apostrophe) falls back to splitting on the shell operators and also scans the raw command, so a mention of a gh write
with a live APPROVE still denies. Same shape as archived_send_gate; unlike upstream_review_gate it has no gated target
to fail closed on.

Block form: stdout JSON permissionDecision "deny", exit 0. Escape hatch for the operator, in the Claude environment:
ADVERSARY_MARKER_GATE_OFF=1 (an assignment inside the command is not read). Inert until `~/.claude/hooks/adversary_marker_gate.py`
is linked (a symlink into this checkout) and `~/.claude/settings.json` is re-rendered from `agents/claude/settings.json.tmpl`.
Design and limits: docs/code-review.md rule 14.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import sys

HERE = Path(__file__).resolve().parent.parent.parent
BIN_DIRS = (HERE / "bin", Path.home() / "src" / "djbclark-ade" / "bin")
MAX_FILE = 262144
MAX_SHLEX = 100000
MAX_FILES = 60
PUNCT = ";&|()<>`\n"
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
VERDICT_WORD = re.compile(r"adversary[-_ ]?verdict", re.IGNORECASE)
APPROVE_WORD = re.compile(r"approve", re.IGNORECASE)
CAT_SUB = re.compile(r"""(?:\$\(|`)\s*(?:cat\s+(?:--\s+)?|<\s*)['"]?([^\s()'"`]+)""")
EXPANDED_MARKER = re.compile(r"adversary[-_ ]?verdict[^>]*[$`]", re.IGNORECASE)
# `gh [-R X] pr|issue VERB`, or `gh api`: also after quotes/commas (a script's argv list), so `bash -c`, eval, xargs and a
# heredoc script that names them are seen without being re-parsed
GH_TEXT = re.compile(r"""(?<![\w.-])gh['",\s]+(?:(?:-R|--repo)[\s=]\S+\s+)?(?:pr|issue)['",\s]+"""
                     r"""(?:create|new|edit|comment|review|close|reopen)(?![\w-])""")
GH_API = re.compile(r"""(?<![\w.-])gh['",\s]+(?:(?:-R|--repo)[\s=]\S+\s+)?api(?![\w-])""")
API_BODY_FLAG = re.compile(r"""(?<![\w-])(?:-[fF]|--field|--raw-field|--input)""")


def deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                              "permissionDecisionReason": reason}}))


def _checker():
    for d in BIN_DIRS:
        if (d / "adversary_marker.py").is_file():
            sys.path.insert(0, str(d))
            import adversary_marker  # noqa: PLC0415 - lazy: any import problem must fail open
            return adversary_marker
    raise ImportError("bin/adversary_marker.py not found beside the checkout or in ~/src/djbclark-ade")


# ---- live marker -----------------------------------------------------------------------------------------------


def live_approve(text: str, am) -> str:
    """A reason string when `text` carries a live APPROVE marker the Action could count (or cannot rule out), else ""."""
    if not VERDICT_WORD.search(text):
        return ""
    stripped = am._strip_code(text)
    spans = am._marker_spans(stripped)
    for _start, js, je in spans:
        raw = text[js:je]
        if am._is_docs_template_json(raw):
            continue
        try:
            doc = json.loads(raw, object_pairs_hook=am._strict_object)
        except ValueError:
            if APPROVE_WORD.search(raw):
                return "an `adversary-verdict:v1` marker that does not parse as JSON and mentions APPROVE"
            continue
        if not isinstance(doc, dict):
            continue
        verdict = doc.get("verdict")
        if isinstance(verdict, str) and verdict.strip().upper() == "APPROVE" and not am._is_placeholder(doc.get("head")):
            return "a live `adversary-verdict:v1` APPROVE marker"
    valid = {s for s, _js, _je in spans}
    for m in am.MARKER_START_RE.finditer(stripped):
        if m.start() in valid or any(js <= m.start() < je for _s, js, je in spans):
            continue
        nxt = stripped.find("<!--", m.end())
        if APPROVE_WORD.search(stripped[m.start():len(stripped) if nxt == -1 else nxt]):
            return "a near-miss `adversary-verdict` marker spelling that mentions APPROVE"
    return ""


# ---- reading the command ------------------------------------------------------------------------------------------


def has_gh_write(command: str) -> bool:
    return bool(GH_TEXT.search(command)) or bool(GH_API.search(command) and API_BODY_FLAG.search(command))


def split_heredocs(command: str):
    """(command without heredoc bodies, [heredoc bodies]); bodies are scanned as their own text, so a fence at the start
    of a body line is a fence (the raw command's `--body '```` is not at a line start and would read as live)."""
    out, bodies, end, cur = [], [], None, []
    for line in command.split("\n"):
        if end is not None:
            if line.strip() == end:
                end = None
                bodies.append("\n".join(cur))
                cur = []
            else:
                cur.append(line)
            continue
        out.append(line)
        m = HEREDOC.search(line)
        if m:
            end = m.group(2)
    if end is not None:  # no terminator: `<<` was not a heredoc (quoted, arithmetic): judge the whole command
        return command, []
    return "\n".join(out), bodies


def tokenize(text: str):
    """(shlex words with the shell operators as their own tokens, True); the lenient split and False when shlex cannot
    parse (a stray apostrophe), so a mention of a gh write still reaches the scan."""
    if len(text) <= MAX_SHLEX:
        lex = shlex.shlex(text.replace("\\\n", " "), posix=True, punctuation_chars=PUNCT)
        lex.whitespace = " \t\r"
        lex.whitespace_split = True
        lex.commenters = ""
        try:
            return list(lex), True
        except ValueError:
            pass
    out = []
    for piece in re.split(r"([;&|()`\n]+)", text.replace("\\\n", " ")):
        if piece and set(piece) <= set(PUNCT):
            out.append(piece)
        else:
            out.extend(w.strip("'\"") for w in piece.split() if w.strip("'\""))
    return out, False


def read_file(path: str, cwd: str) -> str:
    try:
        p = Path(os.path.expanduser(path))
        if not p.is_absolute():
            p = Path(cwd) / p
        if not p.is_file() or p.stat().st_size > MAX_FILE:
            return ""
        return p.read_text(errors="replace")
    except (OSError, ValueError):
        return ""


def file_candidates(tok: str):
    """Paths a word may name: itself, the value of `KEY=VALUE`, `@FILE`, `KEY=@FILE`, an attached `-FFILE`/`-fKEY=@FILE`."""
    out = [tok]
    for sep in ("=@", "=", "@"):
        if sep in tok:
            out.append(tok.split(sep, 1)[1])
    if re.match(r"-[fFT].", tok):
        out.append(tok[2:])
    return [c.lstrip("@") for c in out if c]


def collect_texts(command: str, cwd: str, depth: int = 0):
    """Everything a gh write in `command` may send: heredoc bodies, every word, every file a word names. A word that is
    itself a command line (`bash -c "..."`, `eval "..."`) is collected again, two levels deep."""
    cleaned, bodies = split_heredocs(command)
    tokens, parsed = tokenize(cleaned)
    texts = list(bodies)
    if not parsed:
        texts.append(command)
        texts += [read_file(m.group(1), cwd) for m in CAT_SUB.finditer(command)]
    cur, want_dir, files = cwd, False, 0
    seen = set()
    for tok in tokens:
        if set(tok) <= set(PUNCT):
            continue
        texts.append(tok)
        texts += [read_file(m.group(1), cur) for m in CAT_SUB.finditer(tok)]
        if depth < 2 and re.search(r"\s", tok) and len(tok) < MAX_SHLEX:
            texts += collect_texts(tok, cur, depth + 1)
        if tok == "cd":
            want_dir = True
            continue
        if want_dir:
            want_dir = False
            if not tok.startswith("-"):
                nd = Path(os.path.expanduser(tok))
                cur = str(nd if nd.is_absolute() else Path(cur) / nd)
            continue
        for cand in file_candidates(tok):
            key = (cand, cur)
            if key in seen or files >= MAX_FILES or len(cand) > 4096 or "\n" in cand:
                continue
            seen.add(key)
            content = read_file(cand, cur)
            if content:
                files += 1
                texts.append(content)
    return texts


def judge(command: str, cwd: str, am_loader) -> str:
    """The deny reason, or "" to allow. `am_loader` is called only for a command that holds a gh write."""
    if "gh" not in command or not has_gh_write(command):
        return ""
    am = am_loader()
    texts = collect_texts(command, cwd)
    for t in texts:
        found = live_approve(t, am) if t else ""
        if found:
            return found
    joined = "\n".join(texts)
    if EXPANDED_MARKER.search(joined) and APPROVE_WORD.search(joined):
        return "an `adversary-verdict` marker built by the shell next to the word APPROVE"
    return ""


def reason_for(found: str) -> str:
    return ("Adversary marker gate: this `gh` write carries %s. An agent never writes a live APPROVE marker to a PR body "
            "or comment (AGENTS.md \"Code review\" item 1, docs/code-review.md rules 1 and 14): the merge gate counts it "
            "as the owner's, and `gh` here is the owner. Put the marker in your report inside a fenced block (a BLOCK "
            "marker and a fenced example pass this gate) and state the verdict in the PR body as prose; only the "
            "operator applies a live marker (an owner comment, `bin/ade-merge-ready approve-post`; docs/review-boundary.md). "
            "To lift the gate, the operator sets ADVERSARY_MARKER_GATE_OFF=1 in the Claude environment." % found)


def main() -> int:
    try:
        if os.environ.get("ADVERSARY_MARKER_GATE_OFF") == "1":
            return 0
        event = json.load(sys.stdin)
        if not isinstance(event, dict) or event.get("tool_name") != "Bash":
            return 0
        command = (event.get("tool_input") or {}).get("command")
        if not isinstance(command, str):
            return 0
        found = judge(command, str(event.get("cwd") or os.getcwd()), _checker)
        if found:
            deny(reason_for(found))
    except Exception as exc:  # noqa: BLE001 - a guard must never block on its own bug
        print(f"adversary_marker_gate: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
