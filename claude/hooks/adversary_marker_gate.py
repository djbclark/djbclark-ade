#!/usr/bin/env python3
"""adversary_marker_gate: PreToolUse (Bash) hook, an agent never writes a LIVE adversary APPROVE marker to GitHub (am-01).

The `adversary-marker` merge gate (`bin/adversary_marker.py`, docs/code-review.md rule 1, docs/review-boundary.md)
counts an APPROVE only in an owner-authored PR body or an owner-posted comment, and `gh` on this machine is the owner
(`djbclark`). So an agent that runs `gh pr edit --body ...` with a live APPROVE marker forges the review (2026-11-14:
`claude/agents/adversary.md` told the adversary to emit the marker "for the teammate to paste", and a tendcf lead did,
into frdminc/tendcf PR 41). AGENTS.md "Code review" item 1 and docs/code-review.md rule 1 already say agents must not
write a live APPROVE marker (fenced examples only); this hook enforces it.

Denied: a `gh` invocation that writes GitHub text, and whose text carries a LIVE APPROVE marker:
  * `gh pr create|edit|comment|review`, `gh issue create|edit|comment|review` (a PR is an issue to the comments API)
  * `gh api` with a write (`-f`/`-F`/`--field`/`--raw-field`/`--input`, or `-X`/`--method` other than GET) whose
    endpoint names `pulls` or `issues` (PR create/update, issue comments)
The text is read from every word of the invocation (`--body`, `-b`, `--body=...`, `-f body=...`), from the files it
names (`--body-file F`, `-F F` of `gh pr`, `-F body=@F`, `--input F`, `--body "$(cat F)"`), and from heredoc bodies
(`--body-file - <<'EOF'`, `--body "$(cat <<'EOF' ...)"`), each body scanned as its own text so a fence at a line start
is a fence.

"Live" is decided by the checker's own parser (`adversary_marker._strip_code`, `_marker_spans`, `_classify_starts`
inputs), so what this gate lets through is what the Action reads as documentation:
  allowed   a BLOCK marker; an APPROVE inside a fenced block or an inline code span; the docs template
            (`"verdict":"APPROVE"|"BLOCK","head":"<40-hex>"`); an APPROVE whose head is the `<...>` placeholder
  denied    a canonical marker whose JSON verdict reads APPROVE (any case) with any other head, a canonical marker
            whose JSON does not parse but mentions APPROVE (a duplicate key, a typo), and a near-miss spelling
            (`adversary_verdict`, `adversary-verdict {`) that mentions APPROVE

Not gated: `gh pr create` with no marker text; reads; other tools (`git commit -m`, `curl`, the GitHub MCP, a Python
program that calls the API). `bin/ade-merge-ready approve-post` and the owner's own browser are the owner path and are
not `gh pr ...` commands this hook sees. An agent that wants the verdict recorded puts the marker in its report inside
a fenced block; the owner (or an owner-authored path) applies it.

Parsing and failure modes (the sibling gates' rules, stated): the command is tokenised with shlex after heredoc bodies
are cut out; when shlex cannot parse it (a stray apostrophe), the command is split on the shell operators and
whitespace instead and the raw command is scanned too (fail closed there: a fenced example in such a command is
denied, since its fence is not at a line start), so a mention of `gh pr edit` with a live APPROVE still denies. A command with no `gh` write is
never read for markers. Fails OPEN, silently, for: bad stdin, a non-Bash tool, an unreadable or oversized body file, a
body built by the shell (`$VAR`, a substitution other than `$(cat FILE)`), and any internal error or a missing
`bin/adversary_marker.py` (a guard never blocks on its own bug). Same as archived_send_gate; unlike
upstream_review_gate it does not fail closed on a gated-looking target, because "gated" here is the marker text itself.

Block form: stdout JSON permissionDecision "deny", exit 0. Escape hatch for the operator, in the Claude environment:
ADVERSARY_MARKER_GATE_OFF=1 (an assignment inside the command is not read). Design and limits: docs/code-review.md rule 14.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import sys

BIN = Path(__file__).resolve().parent.parent.parent / "bin"
MAX_FILE = 262144
MAX_SHLEX = 100000
PUNCT = ";&|()<>`\n"
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
VERDICT_WORD = re.compile(r"adversary[-_ ]?verdict", re.IGNORECASE)
APPROVE_WORD = re.compile(r"approve", re.IGNORECASE)
CAT_SUB = re.compile(r"\$\(\s*cat\s+([^\s()]+)\s*\)")
TEXT_GROUPS = {"pr", "issue"}
TEXT_VERBS = {"create", "edit", "comment", "review"}
API_FLAGS = {"-f", "-F", "--field", "--raw-field", "--input"}
API_VALUE_FLAGS = {"-X", "--method", "-H", "--header", "--jq", "-q", "-t", "--template", "--hostname", "--cache", "-f",
                   "-F", "--field", "--raw-field", "--input", "-R", "--repo"}
PR_VALUE_FLAGS = {"-R", "--repo", "-b", "--body", "-F", "--body-file", "-t", "--title", "-B", "--base", "-H", "--head",
                  "-a", "--assignee", "-l", "--label", "-m", "--milestone", "-p", "--project", "-r", "--reviewer"}


def deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                              "permissionDecisionReason": reason}}))


def _checker():
    sys.path.insert(0, str(BIN))
    import adversary_marker  # noqa: PLC0415 - lazy: any import problem must fail open
    return adversary_marker


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


def invocations(tokens):
    """Argument lists of every `gh` word (path allowed), each cut at the next shell operator."""
    out = []
    for i, tok in enumerate(tokens):
        if os.path.basename(tok) != "gh":
            continue
        args = []
        for t in tokens[i + 1:]:
            if t and set(t) <= set(PUNCT):
                break
            args.append(t)
        out.append(args)
    return out


def positional(args, value_flags):
    """The first two non-flag words (group, verb) of a gh argument list."""
    words, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a.startswith("-"):
            skip = a in value_flags
        else:
            words.append(a)
        if len(words) == 2:
            break
    return words


def is_write(args):
    """(kind, positional words) for a gh invocation that writes PR/issue text, else None."""
    words = positional(args, PR_VALUE_FLAGS | {"-R", "--repo"})
    if len(words) == 2 and words[0] in TEXT_GROUPS and words[1] in TEXT_VERBS:
        return "text", words
    if words and words[0] == "api":
        rest = args[args.index("api") + 1:] if "api" in args else args
        method = None
        for i, a in enumerate(rest):
            if a in ("-X", "--method") and i + 1 < len(rest):
                method = rest[i + 1].upper()
            elif a.startswith("--method="):
                method = a.split("=", 1)[1].upper()
        has_body = any(a in API_FLAGS or a.startswith(("--field=", "--raw-field=", "--input=")) for a in rest)
        if method not in (None, "GET") or (has_body and method is None):
            endpoints = [a for a in positional_all(rest) if re.search(r"(^|/)(pulls|issues)(/|$)", a)]
            if endpoints:
                return "api", words
    return None


def positional_all(args):
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a.startswith("-"):
            skip = a in API_VALUE_FLAGS
        else:
            out.append(a)
    return out


def read_file(path: str, cwd: str) -> str:
    try:
        p = Path(os.path.expanduser(path))
        if not p.is_absolute():
            p = Path(cwd) / p
        if not p.is_file() or p.stat().st_size > MAX_FILE:
            return ""
        return p.read_text(errors="replace")
    except OSError:
        return ""


def body_files(kind: str, args):
    """Paths of files the invocation reads its text from (`-` is stdin: the heredoc is in the raw command)."""
    paths = []
    for i, a in enumerate(args):
        nxt = args[i + 1] if i + 1 < len(args) else ""
        if a == "--body-file" or (kind == "text" and a == "-F"):
            paths.append(nxt)
        elif a.startswith("--body-file="):
            paths.append(a.split("=", 1)[1])
        elif a == "--input" or a.startswith("--input="):
            paths.append(nxt if a == "--input" else a.split("=", 1)[1])
        elif a in ("-F", "--field", "--raw-field", "-f") or a.startswith(("--field=", "--raw-field=")):
            val = nxt if a in ("-F", "--field", "--raw-field", "-f") else a.split("=", 1)[1]
            if "=@" in val:
                paths.append(val.split("=@", 1)[1])
        elif a.startswith(("-F", "-f")) and "=@" in a:
            paths.append(a.split("=@", 1)[1])
    return [p for p in paths if p and p != "-"]


def judge(command: str, cwd: str, am) -> str:
    """The deny reason, or "" to allow."""
    if "gh" not in command:
        return ""
    cleaned, bodies = split_heredocs(command)
    tokens, parsed = tokenize(cleaned)
    texts = None
    for args in invocations(tokens):
        w = is_write(args)
        if not w:
            continue
        if texts is None:
            texts = list(bodies)
            if not parsed:
                texts.append(command)
            texts += [read_file(m.group(1), cwd) for m in CAT_SUB.finditer(command)]
        texts += args
        texts += [read_file(p, cwd) for p in body_files(w[0], args)]
    for t in texts or []:
        found = live_approve(t, am) if t else ""
        if found:
            return found
    return ""


def reason_for(found: str) -> str:
    return ("Adversary marker gate: this `gh` write carries %s. An agent never writes a live APPROVE marker to a PR body "
            "or comment (AGENTS.md \"Code review\" item 1, docs/code-review.md rules 1 and 14): the merge gate counts it "
            "as the owner's, and `gh` here is the owner. Put the marker in your report inside a fenced block (a BLOCK "
            "marker and a fenced example pass this gate) and state the verdict in the PR body as prose; the operator or "
            "owner-authored path applies the live marker (docs/review-boundary.md). To lift the gate, the operator sets "
            "ADVERSARY_MARKER_GATE_OFF=1 in the Claude environment." % found)


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
        found = judge(command, str(event.get("cwd") or os.getcwd()), _checker())
        if found:
            deny(reason_for(found))
    except Exception as exc:  # noqa: BLE001 - a guard must never block on its own bug
        print(f"adversary_marker_gate: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
