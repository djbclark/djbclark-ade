#!/usr/bin/env python3
"""adversary_marker_gate: PreToolUse (Bash) hook, an agent never writes a LIVE adversary APPROVE marker to GitHub (am-01).

The `adversary-marker` merge gate (`bin/adversary_marker.py`, docs/code-review.md rule 1, docs/review-boundary.md)
counts an APPROVE only in an owner-authored PR body or an owner-posted comment, and `gh` on this machine is the owner
(`djbclark`). So an agent that runs `gh pr edit --body ...` with a live APPROVE marker forges the review (2026-11-14:
`claude/agents/adversary.md` told the adversary to emit the marker "for the teammate to paste", and a tendcf lead did,
into frdminc/tendcf PR 41). AGENTS.md "Code review" item 1 and docs/code-review.md rule 1 already say agents must not
write a live APPROVE marker (fenced examples only); this hook enforces it.

Denied: a command that runs a `gh` write and sends a LIVE APPROVE marker.
  * a `gh` write is a simple command (after `;`, `&&`, `|`, `(`, a newline, a shell keyword such as `if`/`then`/`do`/`while`,
    behind wrappers by basename such as `env`, `command`, `sudo`, `timeout`, `xargs`, `watch`, `parallel`, `find -exec`,
    `time`, a full-path `bg`, assignments, `cd`/`pushd DIR` (undone at `)`)) whose first two positional words, flags between them
    allowed (`gh pr -R o/r edit`), are `pr|issue create|new|edit|comment|review|close|reopen`, or `gh api` with a body
    flag (`-f`/`-F`/`--field`/`--raw-field`/`--input`, attached forms too) at ANY endpoint, graphql included. Code-bearing
    strings (`bash -c`/`-lc`/`-ec "..."`, `eval "..."`, `$( ... )` inside a double-quoted word, three levels deep) are read
    again; a script heredoc that names `gh pr edit` or `gh api -f` counts, and one fed to a shell (`bash <<'EOF'`) is run
    through the same parser so its `--body-file` operands are read. A gh word inside a quoted string that is not run
    (`rg "gh pr edit"`, a commit message) is not a write, but it does make the command's own words get scanned (no files are read for it);
  * what it sends (the write's own words and operand files first, outside the byte budget; then, within it, the rest):
    every word of the command, so a body written earlier (`printf M > new.md &&`, `BODY=M;`) is seen; the files it names as body operands (`--body-file F`, `-F F`,
    `-F body=@F`, `--input F`, `-T F`, `$(cat F)`, `$(< F)`, relative to the cwd after `cd`), its `< F` and `<<<` operands,
    and, from the commands piped into it (`echo M |`, `cat F |`, `jq --rawfile b F |`, `<(cat F)`, `xargs`), their words and
    the files those words name (40 incidental files at most, spent after the write's own operands). A file read by a FILTER
    (`$(grep M report.md)`, `grep M report.md | gh ...`, `<F tr`, also an unquoted `$( )`) is judged with fences ignored: the filter
    pulls the marker line out of its fence (so a filter over a report with a fenced real-head APPROVE is denied even if its
    output omits the line); a `$( )` anywhere in a command that holds a write is read (`BODY="$(cat raw.md)"; gh ... "$BODY"`). JSON payloads are also scanned as their decoded strings (`\\u003c!--`); a flag prefix
    glued directly before a fence (`--body="```..."`) is not part of the body (a flag word of the write, never a flag's value); heredoc bodies are scanned as their own text.

"Live" is decided by the checker's own parser (`adversary_marker._strip_code`, `_marker_spans`, `MARKER_START_RE`), so what
this gate lets through is what the Action reads as documentation:
  allowed   a BLOCK marker; an APPROVE inside a fenced block or an inline code span; the docs template
            (`"verdict":"APPROVE"|"BLOCK","head":"<40-hex>"`); an APPROVE whose head is the `<...>` placeholder
  denied    a canonical marker whose JSON verdict reads APPROVE (any case) with any other head, a canonical marker
            whose JSON does not parse but mentions APPROVE (a duplicate key, a typo), a near-miss spelling
            (`adversary_verdict`, `adversary-verdict {`) that mentions APPROVE, and a `<!-- adversary-verdict ... $` /
            backtick marker (the shell builds its JSON: `$V`, `$(cat f)`) when APPROVE appears in what the gh write sends;
            a marker comment whose every `verdict` value is a literal BLOCK never counts, whatever the head expands to

Not gated (known limits): a command with no `gh` word (`git commit`, `curl`, the GitHub MCP, a script that calls the API
without naming `gh pr`/`gh api`); a body or body-file path held in a variable set in ANOTHER tool call (`F=raw.md; gh ... --body-file "$F"` in ONE command is seen);
a body file made by a command the hook does not read (`cp live.md b.md && gh ... --body-file b.md`); a `cd` in a shell function; a `cd` target set in another tool call or built by a command substitution (`cd $D`, `cd $(pwd)/sub`; `D=sub; cd $D` in one command is expanded); `gh pr create --fill*`
(the body comes from commit messages); a `gh alias`; `git -C DIR`; a heredoc script in another language (`python3 - <<EOF`: its text is scanned, its file operands are not); more than three levels of `bash -c`; obfuscated markers
(`$'\\x3c'`, a shell-built `verdict` key beside a decoy BLOCK); a text over 70,000 characters is scanned only up to there (GitHub rejects a body over 65,536). `bin/ade-merge-ready
approve-post` is the operator's path: this hook does not see it (it is not a `gh` command), and only the operator, or an agent
the operator tells to, runs it. An agent that wants the verdict recorded puts the marker in its report inside a fenced block.

Failure modes (stated): fails OPEN, with a one-line stderr diagnostic that a hook on exit 0 does not show, for bad stdin,
a non-Bash tool, an unreadable, non-regular or over-256 KB file, the 600,000-character scan budget (the write's own operand files sit outside it: past 400 texts or 2 MB of them the command is denied if it mentions APPROVE), any internal error, a
missing `bin/adversary_marker.py` (looked for beside this file's checkout, then `~/src/djbclark-ade/bin`) and a hook timeout
(15 s). A text with more than 100 marker starts is denied if it mentions APPROVE, never parsed (bounded work); a JSON payload nested past the parser's recursion limit is denied if it mentions APPROVE (its leaves cannot be read). Fails CLOSED
where the command cannot be parsed: shlex failure (a stray apostrophe) splits on the shell operators instead and, when the raw
text names a gh write anywhere, scans the raw command too. Same shape as archived_send_gate.

Block form: stdout JSON permissionDecision "deny", exit 0. Escape hatch for the operator, in the Claude environment:
ADVERSARY_MARKER_GATE_OFF=1 (an assignment inside the command is not read). Inert until `~/.claude/hooks/adversary_marker_gate.py`
is linked (a symlink into this checkout) and `~/.claude/settings.json` is re-rendered from `agents/claude/settings.json.tmpl`.
Design and limits: docs/code-review.md rule 14.
"""
from __future__ import annotations

from collections import Counter
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
MAX_FILES = 40
MAX_TEXT = 70000   # GitHub rejects a body or comment over 65,536 characters
MAX_TOTAL = 600000
MAX_FORCED = 400            # operand files / stdin texts read outside the byte budget
MAX_FORCED_BYTES = 2000000
MAX_STARTS = 100
PUNCT = ";&|()<>`\n"
WORD_BREAK = set(" \t\r\n;&|(")
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
VERDICT_WORD = re.compile(r"adversary[-_ ]?verdict", re.IGNORECASE)
APPROVE_WORD = re.compile(r"approve", re.IGNORECASE)
EXPANDED_MARKER = re.compile(r"<!--\s*adversary[-_ ]?verdict[^>\n]{0,400}[$`]", re.IGNORECASE)
VERDICT_VALUE = re.compile(r"""verdict\\?["']?\s*:\s*\\?["']?([^,}"'\s\\]*)""", re.IGNORECASE)   # quotes optional: the shell may eat them
MARKER_NAME = re.compile(r"adversary[-_ ]?verdict\s*:?\s*v?\d*", re.IGNORECASE)
FLAG_PREFIX = re.compile(r"(?:--(?:body|comment)=|-[bF]|-[fF][A-Za-z_]*=)(?=```|~~~)")   # glued before a fence: not part of the body
KEY_PREFIX = re.compile(r"[A-Za-z_][\w-]*=(?=```|~~~)")
PLAIN_FEEDERS = {"cat", "echo", "printf"}
ENV_REF = re.compile(r"\$(?:\{(\w+)\}|(\w+))")
U_ESCAPE = re.compile(r"\\u[0-9a-fA-F]{4}")
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
TEXT_VERBS = {"create", "new", "edit", "comment", "review", "close", "reopen"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
RESERVED = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "coproc", "time", "case", "in"}
SHELL_C = re.compile(r"^-[A-Za-z]*c$")
WRAPPERS = {"env", "command", "exec", "builtin", "time", "nice", "ionice", "nohup", "setsid", "sudo", "doas", "timeout",
            "gtimeout", "xargs", "stdbuf", "caffeinate", "rtk", "bg", "ts", "chronic", "flock", "taskpolicy", "arch", "!",
            "{", "secretspec", "sudo-secretspec", "direnv", "op", "uv", "uvx", "npx", "mise", "watch", "script", "parallel", "find"}
GH_VALUE_FLAGS = {"-R", "--repo", "--hostname", "-H", "--header", "-X", "--method", "--jq", "-q", "-t", "--template",
                  "--cache", "-b", "--body", "-F", "--body-file", "-f", "--field", "--raw-field", "--input", "-T",
                  "--title", "--base", "-B", "--head", "--assignee", "-a", "--label", "-l", "--milestone", "-m",
                  "--project", "-p", "--reviewer", "--comment", "-c", "--reason", "-r"}
API_BODY_FLAG = re.compile(r"-[fF]|--field|--raw-field|--input")
# the loose forms (a script's argv list, an unparseable command): `gh` then a group and a verb, quotes and commas between
GH_TEXT_LOOSE = re.compile(r"""(?<![\w.-])gh['",\s]+(?:-\S+\s+)*(?:pr|issue)['",\s]+(?:-\S+\s+)*"""
                           r"""(?:create|new|edit|comment|review|close|reopen)(?![\w-])""")
GH_API_LOOSE = re.compile(r"""(?<![\w.-])gh['",\s]+(?:-\S+\s+)*api(?![\w-])""")
API_FLAG_LOOSE = re.compile(r"""(?<![\w-])(?:-[fF]|--field|--raw-field|--input)""")


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


def mentions_approve(text: str) -> bool:
    """`approve` in the text, or in the text with its `\\uXXXX` escapes decoded: the checker reads a marker's JSON, so
    `"verdict":"\\u0041PPROVE"` is APPROVE to it (am-02, adversary round 1 M2)."""
    if APPROVE_WORD.search(text):
        return True
    return bool(U_ESCAPE.search(text) and APPROVE_WORD.search(U_ESCAPE.sub(lambda m: chr(int(m.group()[2:], 16)), text)))


def mentions_approve_decoded(text: str) -> bool:
    """`mentions_approve` after decoding `\\uXXXX` escapes to a fixed point (at most 8 rounds): a JSON payload's string is decoded by
    GitHub and then the marker's own JSON is decoded by the checker, so `\\u005cu0041PPROVE` is APPROVE (cq-45c, adversary r2 M1)."""
    for _ in range(8):
        if mentions_approve(text):
            return True
        decoded = U_ESCAPE.sub(lambda m: chr(int(m.group()[2:], 16)), text)
        if decoded == text:
            return False
        text = decoded
    return False


def live_approve(text: str, am, raw: bool = False) -> str:
    """A reason string when `text` carries a live APPROVE marker the Action could count (or cannot rule out), else "".
    `raw`: the text is a filter's output (`grep`/`sed`/`head` over a file), so a fence around the line in the file is gone."""
    if not VERDICT_WORD.search(text):
        return ""
    if len(VERDICT_WORD.findall(text)) > MAX_STARTS:
        return "more than %d `adversary-verdict` marker starts" % MAX_STARTS if mentions_approve(text) else ""
    stripped = text if raw else am._strip_code(text)
    spans = am._marker_spans(stripped)
    for _start, js, je in spans:
        body = text[js:je]
        if am._is_docs_template_json(body):
            continue
        try:
            doc = json.loads(body, object_pairs_hook=am._strict_object)
        except ValueError:
            if mentions_approve(body):
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
        if mentions_approve(stripped[m.start():len(stripped) if nxt == -1 else nxt]):
            return "a near-miss `adversary-verdict` marker spelling that mentions APPROVE"
    return ""


# ---- reading the command ------------------------------------------------------------------------------------------


def split_heredocs(command: str):
    """(command without heredoc bodies, [(heredoc body, the command text before its `<<`, delimiter quoted)]); bodies are scanned as their own text, so a fence at the start
    of a body line is a fence (the raw command's `--body '```` is not at a line start and would read as live)."""
    out, bodies, end, cur, head, quoted = [], [], None, [], "", False
    for line in command.split("\n"):
        if end is not None:
            if line.strip() == end:
                end = None
                bodies.append(("\n".join(cur), head, quoted))
                cur = []
            else:
                cur.append(line)
            continue
        out.append(line)
        m = HEREDOC.search(line)
        if m:
            end = m.group(2)
            head = line[:m.start()]
            quoted = bool(m.group(1))
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


class Pipeline:
    """The simple commands joined by `|` (and a `<(...)` process substitution with the command it feeds)."""

    def __init__(self):
        self.segments = []   # each: {"words": [...], "stdin": [files], "here": [words], "cwd": str}


def split_pipelines(tokens, cwd: str, expand=None):
    """Pipelines of segments, with `cd`/`pushd` tracked into each segment's cwd and `<` / `<<<` operands set aside.
    `expand` turns `$NAME` in a `cd` target into the value the same command assigned (`D=sub; cd $D`); a name it cannot
    resolve stays literal, so the tracked cwd is wrong and the file read falls back to the event cwd (docs/code-review.md rule 14)."""
    pipes, pipe, seg, cur = [], Pipeline(), None, cwd
    want_dir = redirect = None
    stack = []

    def new_seg():
        return {"words": [], "stdin": [], "here": [], "cwd": cur}
    seg = new_seg()

    def close(same_pipe):
        nonlocal seg, pipe
        if seg["words"] or seg["stdin"] or seg["here"]:
            pipe.segments.append(seg)
        seg = new_seg()
        if not same_pipe and pipe.segments:
            pipes.append(pipe)
            pipe = Pipeline()
    for tok in tokens:
        if tok and set(tok) <= set(PUNCT):
            if set(tok) <= set("<>") and not tok.startswith("<("):
                redirect = "stdin" if tok == "<" else "here" if tok == "<<<" else "skip"
                continue
            # a boundary: `|` (not `||`) and `<(`/`>(` keep the pipeline, everything else ends it
            for ch in tok:                     # a `cd` inside `( ... )` ends with it
                if ch == "(":
                    stack.append(cur)
                elif ch == ")" and stack:
                    cur = stack.pop()
            close("|" in tok.replace("||", "") or "<(" in tok or ">(" in tok)
            continue
        if redirect:
            if redirect in ("stdin", "here"):
                seg[redirect].append(tok)
            redirect = None
            continue
        if want_dir:
            want_dir = None
            if not tok.startswith("-"):
                nd = Path(os.path.expanduser(expand(tok) if expand else tok))
                cur = str(nd if nd.is_absolute() else Path(cur) / nd)
                seg["cwd"] = cur
            continue
        if not seg["words"] and tok in ("cd", "pushd"):
            want_dir = True
            continue
        seg["words"].append(tok)
    close(False)
    return pipes


def gh_invocation(words):
    """(group, verb, args after gh, index of gh) when the segment runs gh (behind wrappers and assignments), else None."""
    i = 0
    while i < len(words) and (ASSIGN.match(words[i]) or words[i] in RESERVED):
        i += 1
    if i >= len(words):
        return None
    if os.path.basename(words[i]) != "gh":
        if os.path.basename(words[i]) not in WRAPPERS:
            return None
        for j in range(i, min(len(words), i + 40)):
            if os.path.basename(words[j]) == "gh":
                i = j
                break
        else:
            return None
    args = words[i + 1:]
    pos, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a.startswith("-"):
            skip = a in GH_VALUE_FLAGS
        else:
            pos.append(a)
    return (pos[0] if pos else "", pos[1] if len(pos) > 1 else "", args, i)


def is_write(group: str, verb: str, args) -> bool:
    if group in ("pr", "issue") and verb in TEXT_VERBS:
        return True
    return group == "api" and any(API_BODY_FLAG.match(a) for a in args)


def operand_files(group: str, args):
    """Files a gh write reads its text from."""
    out = []
    for i, a in enumerate(args):
        nxt = args[i + 1] if i + 1 < len(args) else ""
        if a in ("--body-file", "-T", "--template", "--input") or (group in ("pr", "issue") and a == "-F"):
            out.append(nxt)
        elif a.startswith(("--body-file=", "--template=", "--input=")):
            out.append(a.split("=", 1)[1])
        elif group in ("pr", "issue") and re.match(r"-[FT].", a):
            out.append(a[2:])
        if "=@" in a:
            out.append(a.split("=@", 1)[1])
        elif a in ("-F", "-f", "--field", "--raw-field") and "=@" in nxt:
            out.append(nxt.split("=@", 1)[1])
    return [o for o in out if o and o != "-"]


class Scan:
    """What one command's gh writes send, gathered with a byte budget. The write's own operands are `force`d past it."""

    def __init__(self, cwd: str = ""):
        self.texts, self.write, self.budget, self.cwd0 = [], False, MAX_TOTAL, cwd
        self.token_write, self.incidental, self.forced, self.forced_bytes, self.truncated = False, 0, 0, 0, False
        self.raw_texts, self.env, self.deep = [], {}, False

    def add(self, text: str, force: bool = False, operand: bool = False, raw: bool = False):
        """`force`: the write's own arguments (bounded by the command's length); `operand`: a file or stdin text it reads,
        outside the byte budget but capped in count and bytes (past the cap `truncated` is set and the text is not read)."""
        if not text:
            return
        full, text = text, text[:MAX_TEXT]
        if operand:
            if self.forced >= MAX_FORCED or self.forced_bytes + len(text) > MAX_FORCED_BYTES:
                self.truncated = True
                return
            self.forced += 1
            self.forced_bytes += len(text)
        elif not force and self.budget <= 0:
            return
        self.budget -= len(text)
        (self.raw_texts if raw else self.texts).append(text)
        if full.lstrip()[:1] in ("{", "["):    # any JSON payload: a decoy code span or fence reaches across leaves of the raw text (am-02, M1)
            try:                               # JSON: GitHub stores the decoded strings (`\\u003c` is `<`), each its own text
                strings = []

                def leaves(node, depth=0):
                    if isinstance(node, str):
                        strings.append(node)
                    elif depth < 8 and isinstance(node, dict):
                        for v in node.values():
                            leaves(v, depth + 1)
                    elif depth < 8 and isinstance(node, list):
                        for v in node:
                            leaves(v, depth + 1)
                leaves(json.loads(full))
                chunk, alone, rest = "", 0, []
                for t in strings:              # a string that names a verdict is its own text: a decoy fence in a neighbour leaf
                    if not VERDICT_WORD.search(t):   # (`{"title":"```","body":"\u003c!-- ..."}`) cannot swallow it (am-02, C1)
                        rest.append(t)
                    elif alone < MAX_STARTS:
                        alone += 1
                        self.texts.append(t[:MAX_TEXT])
                    else:
                        rest.append(t)         # past the cap: joined as before, and denied beside APPROVE
                        self.truncated = self.truncated or mentions_approve(t)
                for t in rest:                 # the other strings are joined into texts of at most MAX_TEXT, so none is lost
                    if len(chunk) + len(t) + 1 > MAX_TEXT and chunk:
                        self.texts.append(chunk)
                        chunk = ""
                    chunk += t[:MAX_TEXT] + "\n"
                if chunk:
                    self.texts.append(chunk)
            except ValueError:
                pass
            except RecursionError:             # nested past the parser's limit: no leaf can be read, so an APPROVE anywhere in the
                self.deep = self.deep or mentions_approve_decoded(full)   # whole text is denied by `judge` (cq-45c, review D1)

    def expand(self, path: str) -> str:
        """`$NAME` / `${NAME}` in a path, from the assignments the same command makes."""
        return ENV_REF.sub(lambda m: self.env.get(m.group(1) or m.group(2), m.group(0)), path) if "$" in path else path

    def reads(self, path: str, cwd: str) -> list[str]:
        """The file under the tracked cwd AND, when that differs from the event cwd, under the event cwd: a `cd` in a closed
        subshell, a `cd` target we mis-tracked or expanded from an assignment that does not apply (`cd $D ...; D=decoy`) must not
        move the read away from the file the shell reads. Every distinct text is returned and scanned (am-02, adversary round 1 L1)."""
        path = self.expand(path)
        texts = [read_file(path, cwd)]
        if self.cwd0 and cwd != self.cwd0 and not os.path.isabs(os.path.expanduser(path)):
            texts.append(read_file(path, self.cwd0))
        return [t for k, t in enumerate(texts) if t and t not in texts[:k]]

    def add_file(self, path: str, cwd: str, **kw) -> None:
        for text in self.reads(path, cwd):
            self.add(text, **kw)


def loose_write(text: str) -> bool:
    return bool(GH_TEXT_LOOSE.search(text) or (GH_API_LOOSE.search(text) and API_FLAG_LOOSE.search(text)))


def substitutions(word: str):
    """The commands inside `$( ... )` and backticks within one (double-quoted) word."""
    out, i = [], 0
    while True:
        i = word.find("$(", i)
        if i < 0:
            break
        depth, j = 1, i + 2
        while j < len(word) and depth:
            depth += (word[j] == "(") - (word[j] == ")")
            j += 1
        out.append(word[i + 2:j - 1 if depth == 0 else j])
        i = j
    out.extend(m.group(1) for m in re.finditer(r"`([^`]*)`", word))
    return out


def merge_substitutions(tokens):
    """Rejoin an UNQUOTED `$( ... )`, `$(( ... ))` or backtick pair (shlex splits them at the punctuation) into the one word
    the shell makes of it, so `--body $(grep M report.md)` is the write's argument, not a separate command. Linear: after
    the first group that never closes the rest is left as it is."""
    out, i = [], 0
    while i < len(tokens):
        tok = tokens[i]
        opener = tok and set(tok) == {"("} and out and out[-1] and not set(out[-1]) <= set(PUNCT) and out[-1].endswith("$")
        if opener or tok == "`":
            depth, j, inner, rest = (len(tok) if opener else 1), i + 1, [], ""
            while j < len(tokens) and depth:
                t = tokens[j]
                if opener and t and set(t) <= set(PUNCT):
                    piece = ""
                    for k, ch in enumerate(t):
                        depth += (ch == "(") - (ch == ")")
                        if depth == 0:
                            rest = t[k + 1:]
                            break
                        piece += ch
                    if piece:
                        inner.append(piece)
                elif not opener and t and set(t) <= set(PUNCT) and "`" in t:
                    piece, rest, depth = t[:t.index("`")], t[t.index("`") + 1:], 0
                    if piece:
                        inner.append(piece)
                elif t and set(t) <= set(PUNCT):
                    inner.append(t)
                else:
                    inner.append(shlex.quote(t))
                j += 1
            if depth != 0:
                out.extend(tokens[i:])         # never closed: nothing after it can close either
                break
            word = ("(" + " ".join(inner) + ")") if opener else ("`" + " ".join(inner) + "`")
            if opener:
                out[-1] = out[-1] + word
            else:
                out.append(word)
            if rest:
                out.append(rest)
            i = j
            continue
        out.append(tok)
        i += 1
    return out


def shell_substitutions(text: str, *, heredoc: bool = False, _depth: int = 0) -> list[str]:
    """Active `$( ... )` and backtick bodies that POSIX/bash/zsh execute in `text`.

    Single-quoted `'...'` and ANSI-C `$'...'` spans do not expand substitutions and are skipped;
    unquoted and double-quoted `"..."` spans do (honouring `\\` escapes, `#` comments at word start,
    nested quotes inside `$( ... )`, and nested substitutions). In an unquoted heredoc (`heredoc=True`),
    `'` and `"` are literal characters and do not suppress substitutions. Unclosed `'...'`/`$'...'`
    fail closed (the tail is scanned rather than skipped). Linear in `len(text)`.
    """
    out: list[str] = []
    stack: list[tuple] = [("heredoc",) if heredoc else ("top",)]
    i, n = 0, len(text)
    at_word_start = not heredoc
    squote_dead = ansi_dead = backtick_dead = False

    while i < n:
        frame = stack[-1][0]
        ch = text[i]

        if ch == "#" and at_word_start and frame in ("top", "cmdsub", "paren"):
            nl = text.find("\n", i + 1)
            i = n if nl == -1 else nl + 1
            at_word_start = True
            continue

        if ch == "'" and frame in ("top", "cmdsub", "paren"):
            if not squote_dead:
                end = text.find("'", i + 1)
                if end != -1:
                    i = end + 1
                    at_word_start = False
                    continue
                squote_dead = ansi_dead = True
            i += 1
            at_word_start = False
            continue

        if ch == "$" and i + 1 < n and text[i + 1] == "'" and frame in ("top", "cmdsub", "paren"):
            if not ansi_dead:
                j = i + 2
                closed = False
                while j < n:
                    if text[j] == "\\":
                        j += 2
                    elif text[j] == "'":
                        closed = True
                        j += 1
                        break
                    else:
                        j += 1
                if closed:
                    i = j
                    at_word_start = False
                    continue
                ansi_dead = True
            i += 2
            at_word_start = False
            continue

        if ch == '"' and frame != "heredoc":
            if frame == "dquote":
                stack.pop()
            else:
                stack.append(("dquote",))
            i += 1
            at_word_start = False
            continue

        if ch == "\\":
            if frame in ("dquote", "heredoc"):
                if i + 1 < n and text[i + 1] in ("$", "`", "\\", "\n", '"' if frame == "dquote" else ""):
                    i += 2
                else:
                    i += 1
            else:
                i += 2 if i + 1 < n else 1
                at_word_start = False
            continue

        if ch == "$" and i + 1 < n and text[i + 1] == "(":
            stack.append(("cmdsub", i + 2))
            i += 2
            at_word_start = True
            continue

        if ch == "(" and frame in ("cmdsub", "paren"):
            stack.append(("paren",))
            i += 1
            at_word_start = True
            continue

        if ch == ")" and frame == "paren":
            stack.pop()
            i += 1
            at_word_start = False
            continue

        if ch == ")" and frame == "cmdsub":
            _, start = stack.pop()
            out.append(text[start:i])
            i += 1
            at_word_start = False
            continue

        if ch == "`":
            if not backtick_dead:
                in_dq = frame == "dquote"
                j = i + 1
                buf = []
                closed = False
                while j < n:
                    if text[j] == "\\" and j + 1 < n and text[j + 1] in ("$", "`", "\\", "\n", '"' if in_dq else ""):
                        if text[j + 1] != "\n":
                            buf.append(text[j + 1])
                        j += 2
                    elif text[j] == "`":
                        closed = True
                        j += 1
                        break
                    else:
                        buf.append(text[j])
                        j += 1
                if closed:
                    inner = "".join(buf)
                    out.append(inner)
                    if _depth < 4 and ("$(" in inner or "`" in inner):
                        out.extend(shell_substitutions(inner, _depth=_depth + 1))
                    i = j
                    at_word_start = False
                    continue
                backtick_dead = True
            i += 1
            at_word_start = False
            continue

        if frame in ("top", "cmdsub", "paren"):
            at_word_start = ch in WORD_BREAK
        i += 1

    # Unclosed `$( ...`: emit only the outermost one (keeps O(N) on `"$(" * 8000` while failing closed)
    for item in stack:
        if item[0] == "cmdsub":
            out.append(text[item[1]:])
            break
    return out


def sub_files_for_inners(inners):
    """(files read verbatim, files read through a filter) from extracted substitution bodies: a lone
    `cat F ...` or `< F` keeps the file's fence; anything else (grep, sed, head, `<F tr`, a pipe) is a filter."""
    plain, filt = [], []
    for inner in inners:
        toks = tokenize(inner)[0]
        words = [t for t in toks if t and not set(t) <= set(PUNCT)]
        piped = any(t and set(t) <= set(PUNCT) and "|" in t for t in toks)
        m = re.fullmatch(r"\s*<\s*(\S+)\s*", inner)
        if m:
            plain.append(m.group(1).strip("'\""))
        elif not piped and words and os.path.basename(words[0]) == "cat":
            plain.extend(w for w in words[1:] if not w.startswith("-"))
        else:
            filt.extend(words)
    return plain, filt


def sub_files(word: str):
    """(files read verbatim, files read through a filter) named inside the `$( ... )`/backticks of `word`."""
    return sub_files_for_inners(substitutions(word))


def prefix_stripped(words):
    """The texts a write's words send: a flag prefix glued before a fence (`--body="```...`, `-b"```...`, `-f body=```...`)
    is not part of the body (a prefix before anything else is, and stays)."""
    out, prev = [], ""
    for w in words:
        if prev in ("-f", "-F", "--field", "--raw-field"):
            m = KEY_PREFIX.match(w)
        else:                                  # a value of a flag (`--body "-b```..."`) is the body itself
            m = FLAG_PREFIX.match(w) if w.startswith("-") and prev not in GH_VALUE_FLAGS else None
        out.append(w[m.end():] if m else w)
        prev = w
    return out


def shell_head(head: str) -> bool:
    """True when the text before a heredoc's `<<` runs a shell reading its script from stdin (`bash`, `sh -s`, `| bash`)."""
    words = []
    for tok in tokenize(head)[0]:
        if tok and set(tok) <= set(PUNCT):
            words = []
        else:
            words.append(tok)
    for k, w in enumerate(words):
        if os.path.basename(w) in SHELLS:
            return not any(SHELL_C.match(x) for x in words[k + 1:])
    return False


def collect(command: str, cwd: str, scan: Scan, depth: int = 0) -> None:
    cleaned, bodies = split_heredocs(command)
    tokens, parsed = tokenize(cleaned)
    tokens = merge_substitutions(tokens)
    words_all = [t for t in tokens if t and not set(t) <= set(PUNCT)]
    for w in words_all:
        if ASSIGN.match(w):
            scan.env[w.split("=", 1)[0]] = w.split("=", 1)[1]
    if not parsed and loose_write(command):
        scan.write = True                      # unparseable: fail closed, scan the raw command too
        scan.add(command)
    for body, head, _quoted in bodies:
        if loose_write(body):                  # a script heredoc that names a gh write is one
            scan.write = True
            scan.add(body)
        if depth < 3 and shell_head(head):     # a script fed to a shell: its gh writes read their operand files
            collect(body, cwd, scan, depth + 1)
    pipes = split_pipelines(tokens, cwd, scan.expand)
    cwds = []
    for pipe in pipes:
        for seg in pipe.segments:
            if seg["cwd"] not in cwds:
                cwds.append(seg["cwd"])
    active_subs = shell_substitutions(cleaned)
    own = Counter()                            # the write's own argument words, counted: a second identical word is another word
    seen_sub_reads = set()

    def scan_subs(inners, dirs) -> None:
        """Files read by active `$( ... )`/backticks: a lone `cat F` keeps its fence, a filter's output does not."""
        if not inners:
            return
        plain, filt = sub_files_for_inners(inners)
        for at in dirs:
            for f in plain:
                key = (at, f, False)
                if key not in seen_sub_reads:
                    seen_sub_reads.add(key)
                    scan.add_file(f, at, operand=True)
            for f in filt:
                key = (at, f, True)
                if key not in seen_sub_reads:
                    seen_sub_reads.add(key)
                    scan.add_file(f, at, operand=True, raw=True)

    def feeder(w: str, seg, raw: bool = False) -> None:
        scan.add(w)
        if scan.incidental < MAX_FILES and len(w) < 4096 and "\n" not in w:
            found = scan.reads(w.split("=", 1)[-1] if "=" in w else w, seg["cwd"])
            if found:
                scan.incidental += 1
                for content in found:
                    scan.add(content, raw=raw)
    if depth < 3:
        for inner in active_subs:
            if "gh" in inner:
                for at in cwds[:8] or [cwd]:
                    collect(inner, at, scan, depth + 1)
    for pipe in pipes:
        gh = [(seg, gh_invocation(seg["words"])) for seg in pipe.segments]
        writes = [(seg, g) for seg, g in gh if g and is_write(g[0], g[1], g[2])]
        for seg in pipe.segments:              # code-bearing strings are collected again
            words = seg["words"]
            for k, w in enumerate(words):
                code = None
                if os.path.basename(w) in SHELLS:
                    for x in range(k + 1, len(words)):
                        if SHELL_C.match(words[x]):
                            code = words[x + 1:x + 2]
                            break
                elif w == "eval":
                    code = [" ".join(words[k + 1:])]
                if code and depth < 3:
                    collect(code[0], seg["cwd"], scan, depth + 1)
                    break
        if not writes:
            continue
        scan.write = scan.token_write = True
        feeders = [seg for seg, g in gh if not (g and is_write(g[0], g[1], g[2]))]
        # a file read through a filter (`grep M report.md | gh ...`) reaches the write without its fence
        filtered = len(feeders) > 1 or any(not seg["words"] or os.path.basename(seg["words"][0]) not in PLAIN_FEEDERS
                                           for seg in feeders)
        for seg, g in gh:
            if g and is_write(g[0], g[1], g[2]):
                own.update(g[2])
                for shown in prefix_stripped(g[2]):
                    scan.add(shown, force=True)
                for f in operand_files(g[0], g[2]):
                    scan.add_file(f, seg["cwd"], operand=True)
                for w in seg["words"][:g[3]]:  # `find . -name F -exec gh ...`, `xargs`: words before gh may name files
                    feeder(w, seg)
            else:                              # a feeder: echo/printf words, cat F, jq --rawfile b F
                for w in seg["words"]:
                    feeder(w, seg, raw=filtered)
            for f in seg["stdin"]:
                scan.add_file(f, seg["cwd"], operand=True, raw=filtered and not (g and is_write(g[0], g[1], g[2])))
            for h in seg["here"]:
                scan.add(h, operand=True)
    if not scan.token_write and loose_write(cleaned):
        scan.write = True                      # backstop: a gh write the token path could not place; words only, no files
    if scan.write:
        for w in words_all:                    # a body file or variable the same command writes first
            if own[w] > 0:                     # a write's own words went in above (a fence prefix removed); one use each,
                own[w] -= 1                    # so a word that only equals a flag word elsewhere is scanned as written (am-02, C3)
            else:
                scan.add(w)
        sub_dirs = cwds[:8] or [cwd]           # `cd DIR && BODY="$(cat raw.md)"; gh ... "$BODY"`: tracked cwds + event cwd
        scan_subs(active_subs, sub_dirs)
        for body, _head, quoted in bodies:
            scan.add(body)
            if not quoted:                     # an unquoted heredoc expands its `$( )` lines; a quoted one does not
                scan_subs(shell_substitutions(body, heredoc=True), sub_dirs)


def collect_argv(argv: list[str], cwd: str, scan: Scan, stdin_path: str | None = None) -> None:
    """Gather what an already-expanded `gh` process argv (e.g. from `bin/ade-gh-guard`) sends.
    No shell runs backticks, `$( )`, heredocs or variable expansions on these words; only the write's
    own arguments, its operand files and its spooled stdin are scanned (queue #117)."""
    g = gh_invocation(argv)
    if not (g and is_write(g[0], g[1], g[2])):
        return
    scan.write = scan.token_write = True
    for shown in prefix_stripped(g[2]):
        scan.add(shown, force=True)
    for f in operand_files(g[0], g[2]):
        scan.add_file(f, cwd, operand=True)
    if stdin_path:
        scan.add_file(stdin_path, cwd, operand=True)


def judge(command: str, cwd: str, am_loader, *, argv: list[str] | None = None,
          stdin_path: str | None = None) -> str:
    """The deny reason, or "" to allow. `am_loader` is called only for a command that holds a gh write.
    When `argv` is given (real process argv from `bin/ade-gh-guard`), no shell parsing or substitution
    expansion runs on its words."""
    if argv is None and "gh" not in command:
        return ""
    scan = Scan(cwd)
    if argv is not None:
        collect_argv(argv, cwd, scan, stdin_path=stdin_path)
    else:
        collect(command, cwd, scan)
    if not scan.write:
        return ""
    am = am_loader()
    for t in scan.texts:
        found = live_approve(t, am)
        if found:
            return found
    for t in scan.raw_texts:
        found = live_approve(t, am, raw=True)
        if found:
            return found
    if scan.deep:                              # judged on the whole payload, not on its MAX_TEXT cut or its channel (file, pipe, filter)
        return "a JSON payload nested past this gate's parser limit that mentions APPROVE (its leaves cannot be read)"
    if any(mentions_approve(t) for t in scan.texts):
        if scan.truncated:
            return "more operand text than this gate can scan in time (%d files or %d bytes) next to the word APPROVE" % (
                MAX_FORCED, MAX_FORCED_BYTES)
        for t in scan.texts:
            stripped = am._strip_code(t)
            for m in EXPANDED_MARKER.finditer(stripped):
                end = stripped.find("-->", m.start())
                comment = stripped[m.start():end if 0 < end < m.start() + 450 else m.start() + 450]
                values = [v.upper() for v in VERDICT_VALUE.findall(MARKER_NAME.sub("", comment, count=1))]
                if values and all(v == "BLOCK" for v in values):
                    continue                   # every `verdict` value in this comment is a literal BLOCK, whatever the head expands to
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
