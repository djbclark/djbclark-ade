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
    output omits the line); a `$( )` anywhere in a command that holds a write is read (`BODY="$(cat raw.md)"; gh ... "$BODY"`). JSON payloads (a leading UTF-8 BOM is dropped) are also scanned as their decoded strings (`\\u003c!--`), and a `gh api` write's texts again with GraphQL string escapes decoded (`-f query=`, `-F query=@file`); a flag prefix
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
a body file made by a command the hook does not read (`cp live.md b.md && gh ... --body-file b.md`); a `cd` in a shell function; a `cd` target set in another tool call or built by a command substitution (`cd $D`, `cd $(pwd)/sub`, `cd -`; `D=sub; cd $D` in one command is expanded, in token order, and `cd -P`/`cd --`/`builtin cd`/`{ cd`/`if cd` are followed, and a relative operand is read under every candidate directory the shell may be in: a `cd` that may not run adds its moved directories to the set); a program's output or a decoder piped into `gh api --input -` (`base64 -d`, `gzip -dc`); `gh pr create --fill*`
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
import time

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
MAX_DIRS = 128              # distinct directories tracked for one command, and the most (path, directory) reads of one command's operands
MAX_READS = 5000            # past either (or a tracked path over MAX_PATH), the gh write is denied: it may read a file this gate never reached
MAX_PATH = 4096
MAX_WORK = 30000            # sum over a command's `cd`s of (candidate directories x components of the target); past it the write is denied
MAX_LINKS = 40               # symlinks one physical `..` resolution follows (the kernel's own limit is of this order); past it the physical option is dropped
MAX_STEPS = 65536           # path components one physical resolution walks (40 links x a 1,024-byte target is under it); past it: a deny
MAX_SECONDS = 4.0           # wall-clock budget of the cd tracking (the hook's own timeout is 15 s and fails open); past it the write is denied
PUNCT = ";&|()<>`\n"
# the lenient split's separator runs: a `&` that is not part of `>&`, `<&`, `&>` (a redirect) is one; `&&` always is
SEPARATORS = r"((?:&&|(?<![<>])&(?!>)|[;|()`\n])+)"
# the redirect operators (a run of `<>&` that is none of them is a separator, then a redirect: `&<`, `&&>`)
FD_WORD = re.compile(r"\d+|\{[A-Za-z_]\w*\}")


class FdWord(str):
    """A word that is a file descriptor before a redirect (`2>f`) OR an argument (`2 >f`, `'2'>f`): shlex cannot tell. It stays in `words`
    (so a body file named `2` is still an operand) and `gh_invocation` reads the line both ways."""
REDIRECTS = {"<", ">", ">>", "<<", "<<<", "<>", ">|", ">&", "<&", "&>", "&>>"}
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
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?\+?=")      # NAME=, NAME+=, NAME[i]=
ASSIGN_PARTS = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\[([^\]]*)\])?(\+?)=(.*)$", re.S)


def assign_to(env: dict, tok: str) -> None:
    """Record the assignment word `tok` in `env`: `NAME=v` sets, `NAME+=v` appends to the value in effect, and `NAME[0]=v` (the element `$NAME`
    names in bash) sets or appends like the scalar. Any other subscript changes an element `$NAME` does not name, so the value stays (zsh
    numbers elements from 1 and reads `$NAME` as all of them: a documented limit)."""
    m = ASSIGN_PARTS.match(tok)
    if m:
        name, sub, plus, value = m.groups()
        if sub is None or sub.strip() == "0":
            env[name] = (env.get(name, "") if plus else "") + value


ASSIGNERS = {"export", "local", "declare", "readonly", "typeset"}   # `export D=sub` assigns like `D=sub`
GQL_ESCAPE = re.compile(r"\\(?:u\{([0-9a-fA-F]{1,8})\}|u([0-9a-fA-F]{4})|([\"\\/bfnrt]))")   # GraphQL string-literal escapes
GQL_SIMPLE = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
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
# (the flag run between the words is bounded: an unbounded `(?:-\S+\s+)*` at every `gh` made a padded command quadratic, 35 s for 150 KB)
# the loose forms (a script's argv list, an unparseable command): `gh` then a group and a verb, quotes and commas between
GH_TEXT_LOOSE = re.compile(r"""(?<![\w.-])gh['",\s]+(?:-\S+\s+){0,8}(?:pr|issue)['",\s]+(?:-\S+\s+){0,8}"""
                           r"""(?:create|new|edit|comment|review|close|reopen)(?![\w-])""")
GH_API_LOOSE = re.compile(r"""(?<![\w.-])gh['",\s]+(?:-\S+\s+){0,8}api(?![\w-])""")
GH_WORD = re.compile(r"(?<![\w.-])gh(?![\w-])")      # linear: `gh` as a word anywhere in the command
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
        decoded = graphql_unescape(U_ESCAPE.sub(lambda m: chr(int(m.group()[2:], 16)), text))   # also GraphQL's `\u{41}`
        if decoded == text:
            return False
        text = decoded
    return False


def graphql_unescape(text: str) -> str:
    """`text` with its GraphQL string-literal escapes decoded once (`\\u003c` is `<`, `\\"` is `"`, `\\\\` is `\\`): GitHub's parser does
    that to a `query` field before it stores a comment, so a marker spelled with them is live there (mg-51, queue Carried 52)."""
    def one(m):
        code = m.group(1) or m.group(2)
        if code is None:
            return GQL_SIMPLE.get(m.group(3), m.group(3))
        return chr(int(code, 16)) if int(code, 16) <= 0x10FFFF else m.group()
    return GQL_ESCAPE.sub(one, text)


def live_approve(text: str, am, raw: bool = False) -> str:
    """A reason string when `text` carries a live APPROVE marker the Action could count (or cannot rule out), else "".
    `raw`: the text is a filter's output (`grep`/`sed`/`head` over a file), so a fence around the line in the file is gone."""
    if not VERDICT_WORD.search(text):
        return ""
    if len(VERDICT_WORD.findall(text)) > MAX_STARTS:
        return "more than %d `adversary-verdict` marker starts" % MAX_STARTS if mentions_approve_decoded(text) else ""
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
    for piece in re.split(SEPARATORS, text.replace("\\\n", " ")):
        if piece and set(piece) <= set(PUNCT):
            out.append(piece)
        else:
            out.extend(w.strip("'\"") for w in piece.split() if w.strip("'\""))
    return out, False


def home_expanded(path: str) -> str:
    try:
        return os.path.expanduser(path)
    except ValueError:                         # an embedded NUL: the path is left as it is (read_file refuses it), never a crash
        return path


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


class History(dict):
    """cwd -> the candidate directories the shell may be in by then (at most MAX_DIRS). `overflow` is set when a set grew past the cap,
    a command's `cd` work passed MAX_WORK, a path passed MAX_PATH, the reads passed MAX_READS, a physical walk passed MAX_STEPS or the
    clock passed MAX_SECONDS: the gate then denies any command that names `gh` as a word."""
    overflow = False

    def __init__(self):
        super().__init__()
        self.work = 0                           # sum over the command's `cd`s of (candidates x components of the target)
        self.started = time.monotonic()
        self.dirs = {}                          # path -> os.path.isdir, once per command
        self.known = {}                         # cwd -> set(self[cwd]), so `note` costs the new directories only
        self.real = {}                          # path -> os.path.realpath, once per command

    def isdir(self, path: str) -> bool:
        if path not in self.dirs:
            self.dirs[path] = os.path.isdir(path)
        return self.dirs[path]

    def expired(self) -> bool:
        """The cd tracking has used its time: set `overflow` (a deny) so a slow command cannot outrun the hook's 15 s timeout, which fails open."""
        if not self.overflow and time.monotonic() - self.started > MAX_SECONDS:
            self.overflow = True
        return self.overflow

    def realpath(self, path: str) -> str:
        """The physical path (what `cd -P` reaches), or "" when it cannot be had in bounds: more than MAX_LINKS symlinks (the kernel
        gives up at 32-40 too); more than MAX_STEPS components or the clock running out set `overflow` (a deny) instead. `os.path.realpath` has no such limit (one call through a chain of
        45,000 links took 17 s), so the walk is this one, with a link counter and the clock read every 64 components."""
        if path not in self.real:
            self.real[path] = self.walk(path)
        return self.real[path]

    def walk(self, path: str) -> str:
        todo, out, links, steps = path.split("/")[::-1], "/", 0, 0
        while todo:
            steps += 1
            if steps > MAX_STEPS:               # a directory the shell may reach is out of reach of this walk: a deny, not a dropped option
                self.overflow = True
                return ""
            if steps % 64 == 0 and self.expired():
                return ""
            part = todo.pop()
            if part in ("", "."):
                continue
            if part == "..":
                out = os.path.dirname(out)
                continue
            nxt = os.path.join(out, part)
            try:
                if os.path.islink(nxt):
                    links += 1
                    if links > MAX_LINKS:
                        return ""
                    target = os.readlink(nxt)
                    if os.path.isabs(target):
                        out = "/"
                    todo.extend(target.split("/")[::-1])
                    continue
            except OSError:
                return ""
            out = nxt
        return out

    def note(self, cur: str, visited) -> None:
        have = self.setdefault(cur, [])
        known = self.known.setdefault(cur, set(have))
        extra = [d for d in visited if d not in known]
        if extra:
            for d in dict.fromkeys(extra):
                known.add(d)
                have.append(d)
            if len(have) > MAX_DIRS:
                del have[MAX_DIRS:]
                self.overflow = True


class Pipeline:
    """The simple commands joined by `|` (and a `<(...)` process substitution with the command it feeds)."""

    def __init__(self):
        self.segments = []   # each: {"words": [...], "stdin": [files], "here": [words], "cwd": str}


OPENERS = {"if", "while", "until", "for", "select", "case"}        # a compound command: a `cd` inside may not run (nor run once)
CLOSERS = {"fi", "done", "esac"}
UNSURE_WORDS = ("then", "else", "elif", "do", "coproc")


def seg_empty(seg):
    return not (seg["words"] or seg["stdin"] or seg["here"])


OPERATORS = ("<<<", "&>>", "&&", "||", "|&", ">>", "<<", ">&", "<&", "&>", ">|", "<>", ";;", "<(", ">(",
             ";", "&", "|", "(", ")", "<", ">", "`", "\n")         # the shell's own greedy lexing of a punctuation run, longest first


def split_redirects(tokens):
    """shlex makes ONE token of a run of punctuation (`;</dev/null`, `&&>`, `&<`, `(<`): split it the way the shell lexes it, a separator
    token and each redirect operator its own token (`;` + `<`, `&&` + `>`, `&` + `<`), so a redirect never hides the separator before it
    nor the command after it. A run without a redirect (`&&\n`, `;;`, `<(`) stays whole."""
    out = []
    for tok in tokens:
        if not tok or tok in REDIRECTS or not set(tok) <= set(PUNCT) or not ("<" in tok or ">" in tok):
            out.append(tok)
            continue
        ops, k = [], 0
        while k < len(tok):
            op = next((o for o in OPERATORS if tok.startswith(o, k)), tok[k])
            ops.append(op)
            k += len(op)
        if not any(o in REDIRECTS for o in ops):
            out.append(tok)
            continue
        run = ""
        for op in ops:
            if op in REDIRECTS:
                if run:
                    out.append(run)
                    run = ""
                out.append(op)
            else:
                run += op
        if run:
            out.append(run)
    return out


def split_pipelines(tokens, cwd: str, expand=None, history=None, bases=()):
    """Pipelines of segments, with `cd`/`pushd` tracked into each segment's cwd and `<` / `<<<` operands set aside.
    A `cd` counts behind `builtin`/`command` and a shell keyword (`{ cd`, `if cd`, `then cd`); its options (`-P`, `-L`, `-e`, `--`) are
    skipped, a bare `cd` goes to HOME. `expand` turns `$NAME` in a `cd` target into the value the same command assigned (`D=sub; cd $D`;
    the assignment in effect at that point, so a later `D=decoy` does not move it); a name it cannot resolve stays literal (no such
    directory, the `cd` fails, nothing moves) and the file read falls back to the event cwd (docs/code-review.md rule 14).
    The shell's directory is a SET of candidates (`cands`). A `cd` is SURE only on plain straight-line code: outside every compound command
    (`if`/`while`/`until`/`for`/`select`/`case`) and `{ }` group that is itself conditional, not behind `then`/`else`/`elif`/`do`/`coproc`,
    not `pushd -n`, not an element of a pipeline or of an AND-OR list that ends in `&`, and not after `||`, nor after `&&` unless the command before it was a sure `cd`
    that moved every candidate. A sure `cd` replaces the set by its targets; any other adds its targets to the old set. A target is applied to
    every candidate (normalised, lexical `..`; when it holds `..`, the physical `realpath` too, for `set -P`/`cd -P` through a symlink), and a
    candidate for which it is no directory stays where it was (the `cd` fails). `popd` and a bare `pushd` add every candidate seen so far.
    Not modelled (so a documented limit): a `cd` in a shell function, `trap`, a `#` comment, a quoted reserved word, `time -p if`, zsh `repeat`,
    a directory named `2`, `cd ~1`, zsh `cd old new`, a heredoc inside a `bash -c` string, a directory that an earlier command of the same line creates. `history` (a History) gets, for each tracked cwd, the candidates by then; past MAX_DIRS candidates or MAX_WORK of `cd` work it sets
    `overflow` (the write is then denied) and stops tracking."""
    tokens = split_redirects(tokens)
    pipes, pipe, seg, cur = [], Pipeline(), None, cwd
    cands = list(dict.fromkeys([cwd, *bases]))   # `bases`: the directories an enclosing nested shell runs under
    if len(cands) > MAX_DIRS:
        cands = cands[:MAX_DIRS]
        if history is not None:
            history.overflow = True
    seen = list(cands)                          # every directory that was ever a candidate (for `popd`)
    seen_set = set(seen)
    want_dir = redirect = None
    no_more_options = pushd_n = False
    last_sep, last_cd, this_cd, snap = "", None, None, None   # last_cd: did the previous segment's `cd` move every candidate surely (True)
    comp, braces, case_marks, stack, group_snap, list_snap = 0, [], [], [], None, (cwd, cands)
    nbraces = [0]                               # how many open `{` groups are conditional (O(1) per token)   # braces: [(conditional?, (cur, cands) at the `{`)]
    groups = []                                 # one entry per open `{` / `(`: (comp at the opener, the AND-OR list start outside it): a list inside it starts afresh
    assigned = {}                               # name -> value, in token order (a later reassignment does not reach an earlier cd)
    dirs = history.isdir if history is not None else os.path.isdir

    flags = {"lead": True, "reserved": True, "assign": True, "unsure": False, "assigned": False, "fd": False, "redir": False}   # about seg["words"], updated per word: O(1) per token

    def new_seg():
        if history is not None and not history.overflow:    # past an overflow the verdict is a deny: stop paying
            history.note(cur, cands)
        flags.update(lead=True, reserved=True, assign=True, unsure=False, assigned=False, fd=False, redir=False)
        return {"words": [], "stdin": [], "here": [], "cwd": cur}
    seg = new_seg()

    def push(tok):
        seg["words"].append(tok)
        is_assign = bool(ASSIGN.match(tok))
        # `FOO=1 cd d` still moves the shell; a reserved word after an assignment is no keyword (`A=1 time cd d` runs an external `time`)
        flags["lead"] = flags["lead"] and (tok in ("builtin", "command") or is_assign or (tok in RESERVED and not flags["assigned"]))
        flags["assigned"] = flags["assigned"] or is_assign
        flags["reserved"] = flags["reserved"] and tok in RESERVED
        flags["assign"] = flags["assign"] and bool(ASSIGN.match(tok) or tok in ASSIGNERS)
        flags["unsure"] = flags["unsure"] or tok in UNSURE_WORDS or (flags["redir"] and tok in RESERVED)   # bash runs `>f time cd d` as an external `time`, zsh as the keyword

    def close(same_pipe):
        nonlocal seg, pipe
        if seg["words"] or seg["stdin"] or seg["here"]:
            pipe.segments.append(seg)
        seg = new_seg()
        if not same_pipe and pipe.segments:
            pipes.append(pipe)
            pipe = Pipeline()

    def placed_unsure():
        return (comp > 0 or nbraces[0] > 0 or flags["unsure"] or "||" in last_sep
                or "|" in last_sep.replace("||", "") or ("&&" in last_sep and last_cd is not True))

    def overflowed():
        return history is not None and history.overflow

    def widen(more):
        nonlocal cands
        if more is cands or overflowed():       # nothing to add, or the verdict is a deny already: stop paying (O(|more|) a call, never O(|more| x |seen|))
            return
        have = set(cands)
        extra = [d for d in dict.fromkeys(more) if d not in have]
        if extra:
            cands = [*cands, *extra]
        for d in more:
            if d not in seen_set and len(seen) < MAX_DIRS:
                seen.append(d)
                seen_set.add(d)
        if len(cands) > MAX_DIRS:
            if history is not None:
                history.overflow = True
            del cands[MAX_DIRS:]

    def apply(target, kind, extra=False):
        """One `cd`/`pushd` to `target` (a word, or "" for HOME); `extra`: more operands follow (`cd a b` fails in bash, substitutes in zsh)."""
        nonlocal cur, cands, this_cd, snap
        if overflowed() or (history is not None and history.expired()):   # past an overflow the verdict is a deny: stop paying for tracking
            return
        if len(target) > MAX_PATH and history is not None:
            history.overflow = True
            return
        nd = Path(home_expanded((expand(target, assigned) if expand else target) if target else "~"))
        if history is not None:
            history.work += len(cands) * max(1, len(nd.parts))      # the stat/realpath work scales with the target's components too
            if history.work > MAX_WORK:
                history.overflow = True
                return
        unsure = pushd_n or extra or placed_unsure() or flags["fd"]
        if snap is None:
            snap = (cur, list(cands))
        moved, clean = [], True
        for v in cands:
            if history is not None and history.expired():
                return
            joined = nd if nd.is_absolute() else Path(v) / nd
            options = [os.path.normpath(str(joined))]
            if ".." in nd.parts:                # a physical shell (`cd -P`, `set -P`) resolves `link/..` through the link
                options.append(history.realpath(str(joined)) if history is not None else os.path.realpath(str(joined)))
            found = [m for m in dict.fromkeys(options) if dirs(m)]
            clean = clean and bool(found)
            moved += found or [v]
        cur = os.path.normpath(str(nd if nd.is_absolute() else Path(cur) / nd))
        cands = [] if not unsure else cands
        widen(moved)
        this_cd = bool(not unsure and clean)
        if len(cur) > MAX_PATH and history is not None:     # a path that long is a pile of `cd`s: stop extending it (quadratic)
            history.overflow = True
            cur = cwd
        seg["cwd"] = cur
        if history is not None:
            history.note(cur, cands)
    for i, tok in enumerate(tokens):
        if history is not None and not i & 255:     # the whole token loop is on the clock, not only `apply` (a pile of `&`, `popd`, `{` ...)
            history.expired()
        if tok and (tok in REDIRECTS or set(tok) <= set(PUNCT)):
            if (tok in REDIRECTS or (set(tok) <= set("<>&") and ("<" in tok or ">" in tok))) and not tok.startswith("<("):   # `>`, `2>&1` (`>&`), `&>`, `>|`: a redirect, not a background `&` or a pipe
                redirect = "stdin" if tok == "<" else "here" if tok == "<<<" else "skip"
                flags["reserved"], flags["redir"] = False, True     # a word after a redirect is no keyword in bash (`>f fi`, `>f time cd d`)
                continue
            if want_dir:                        # a bare `cd` (HOME) or `pushd` ends at the boundary; it must not take the next command for its directory
                if want_dir == "cd":
                    apply("", "cd")
                else:
                    widen(seen)
                    this_cd = False
            want_dir = None
            no_more_options = pushd_n = False
            flat = tok.replace("&&", "").replace("||", "")
            for held in (snap, group_snap):     # `cd d | cat`, `cd d &`, `{ cd d; } | tee`: the shell here did not move
                if held is not None and ("|" in flat or "&" in flat):
                    widen(held[1])
                    cur = held[0]
            group_snap = None
            bg = "&" in flat
            if bg and list_snap is not None:    # `cd a && cd b &`: the whole AND-OR list ran in a background subshell
                widen(list_snap[1])
                cur = list_snap[0]
            if tok.strip("\n") == "" and seg_empty(seg) and ("&&" in last_sep or "||" in last_sep or "|" in last_sep):
                continue                        # `false &&` NEWLINE `cd d`: the line continues, the boundary before it still holds
            last_sep, last_cd, this_cd, snap = tok, this_cd, None, None
            for ch in tok:                      # a `cd` inside `( ... )` ends with it
                if ch == "(":
                    stack.append((cur, cands))
                    groups.append((comp, list_snap))
                    list_snap = (cur, cands)
                elif ch == ")" and case_marks and len(stack) == case_marks[-1]:
                    pass                        # the `)` closing a `case` pattern
                elif ch == ")" and stack:
                    cur, cands = stack.pop()
                    if groups:
                        list_snap = groups.pop()[1]
            continued = tok.rstrip("\n").endswith(("&&", "||", "|", "|&"))     # `&&` NEWLINE is one shlex token: the list goes on
            if bg or ((";" in tok or "\n" in tok) and not continued and comp == (groups[-1][0] if groups else 0)):
                list_snap = (cur, cands)         # a new AND-OR list starts here, at the level of the innermost `{`/`(` (a `;` in a compound command inside it does not end it)
            close("|" in tok.replace("||", "") or "<(" in tok or ">(" in tok)
            continue
        if redirect:
            if redirect in ("stdin", "here"):
                seg[redirect].append(tok)
            redirect = None
            continue
        if want_dir:
            if tok == "--" and not no_more_options:
                no_more_options = True
                continue
            if re.fullmatch(r"[+-]\d+", tok) and not no_more_options:     # `pushd +1`, `pushd -0`, zsh `cd +1`: an entry of the directory stack
                widen(seen)                    # ... or, in bash `cd`, a directory literally named `+1`: the operand is applied below as well, unsure
                this_cd = False
                if tok.startswith("-"):
                    continue
                stackish = True
            else:
                stackish = False
            if tok.startswith("-") and tok != "-" and not no_more_options:
                pushd_n = pushd_n or (want_dir == "pushd" and "n" in tok[1:])
                continue                       # `cd -P DIR`, `cd -L -e DIR`: an option, the directory comes later
            if tok.isdigit() and i + 1 < len(tokens) and tokens[i + 1] and set(tokens[i + 1]) <= set("<>&") and set(tokens[i + 1]) & set("<>"):
                continue                       # `cd 2>/dev/null DIR`: the `2` is a file descriptor
            kind = want_dir
            want_dir = None
            no_more_options = False
            if tok != "-":                     # `cd -` is OLDPWD, which this command cannot name: the same limit as an unresolved `$D`
                nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
                more = bool(nxt) and not set(nxt) <= set(PUNCT) and not (nxt.isdigit() and i + 2 < len(tokens) and set(tokens[i + 2]) <= set("<>&") and set(tokens[i + 2]) & set("<>"))
                apply(tok, kind, extra=more or stackish)
            pushd_n = False
            continue
        lead = flags["lead"]
        if FD_WORD.fullmatch(tok) and i + 1 < len(tokens) and tokens[i + 1] in REDIRECTS:
            seg["words"].append(FdWord(tok))   # `2>/dev/null gh ...`, `gh 2>/dev/null pr create`, `A=1 2>&1 gh`: an fd or an argument (`gh pr create --body-file 2 >f`):
            flags["fd"] = flags["redir"] = True    # kept, `lead` untouched (the fd reading); `gh_invocation` reads both; a `cd` behind it is unsure
            flags["reserved"] = False          # ... and what follows is no keyword (`2>f fi`)
            continue
        if tok in ("cd", "pushd") and lead:
            want_dir = tok
            continue
        if tok == "popd" and lead:             # back to an earlier directory: any candidate seen so far
            widen(seen)
            this_cd = False
        elif flags["reserved"]:
            if tok in OPENERS:
                comp += 1
                if tok == "case":
                    case_marks.append(len(stack))
            elif tok in CLOSERS:
                comp = max(0, comp - 1)
                if tok == "esac" and case_marks:
                    case_marks.pop()
            elif tok == "{":
                cond = placed_unsure() or ")" in last_sep
                nbraces[0] += cond
                braces.append((cond, (cur, cands)))
                groups.append((comp, list_snap))
                list_snap = (cur, cands)
            elif tok == "}" and braces:
                cond, group_snap = braces.pop()
                nbraces[0] -= cond
                if groups:
                    list_snap = groups.pop()[1]
        if flags["assign"] and ASSIGN.match(tok):
            assign_to(assigned, tok)
        push(tok)
    if want_dir:
        apply("", "cd") if want_dir == "cd" else widen(seen)
    close(False)
    return pipes


def _gh_at(words):
    """(group, verb, args after gh, index of gh) for one reading of the words, or None."""
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


def gh_invocation(words):
    """(group, verb, args after gh, index of gh) when the segment runs gh (behind wrappers and assignments), else None. A word that is an
    `FdWord` (`2` before a redirect) is read as a file descriptor (dropped for the group, the verb and the command) AND as an argument (kept):
    the write is placed if either reading places it, and its `args` keep every word, so an operand file named `2` is read."""
    if not any(isinstance(w, FdWord) for w in words):
        return _gh_at(words)
    keep = [k for k, w in enumerate(words) if not isinstance(w, FdWord)]
    fd_reading = _gh_at([words[k] for k in keep])
    if fd_reading:
        k = keep[fd_reading[3]]
        fd_reading = (fd_reading[0], fd_reading[1], words[k + 1:], k)
    if fd_reading and is_write(fd_reading[0], fd_reading[1], fd_reading[2]):
        return fd_reading
    arg_reading = _gh_at(list(words))
    if arg_reading and is_write(arg_reading[0], arg_reading[1], arg_reading[2]):
        return arg_reading
    return fd_reading or arg_reading


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
        self.raw_texts, self.env, self.deep, self.api_write, self.history = [], {}, False, False, History()
        self.cache, self.payload_ids, self.read_calls = {}, set(), 0      # (path, dir) -> text; id() of each text parsed as a whole JSON payload

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
        full = full.lstrip("\ufeff")           # a UTF-8 BOM before the payload: json.loads refuses it, a JSON reader may not (mg-51)
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
                self.payload_ids.add(id(text))      # a whole JSON payload: its leaves are its texts, so judge leaves it undecoded
                chunk, alone, rest = "", 0, []
                for t in strings:              # a string that names a verdict is its own text: a decoy fence in a neighbour leaf
                    if not (VERDICT_WORD.search(t) or ("\\" in t and VERDICT_WORD.search(graphql_unescape(t)))):   # (`{"title":"```","body":"\u003c!-- ..."}`)
                        # cannot swallow it (am-02, C1); a verdict word spelled with GraphQL escapes (`adversary\u002dverdict`) names it too (mg-51 r2, B3)
                        rest.append(t)
                    elif alone < MAX_STARTS:
                        alone += 1
                        self.texts.append(t[:MAX_TEXT])
                    else:
                        rest.append(t)         # past the cap: joined as before, and denied beside APPROVE
                        self.truncated = self.truncated or mentions_approve_decoded(t)
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
                self.payload_ids.add(id(text))
                self.deep = self.deep or mentions_approve_decoded(full)   # whole text is denied by `judge` (cq-45c, review D1)

    def expand(self, path: str, first: dict | None = None) -> str:
        """`$NAME` / `${NAME}` in a path, from the assignments the same command makes (`first`: those already in effect at this
        point, which win over the command's last assignment of the name)."""
        env = {**self.env, **(first or {})}
        return ENV_REF.sub(lambda m: env.get(m.group(1) or m.group(2), m.group(0)), path) if "$" in path else path

    def reads(self, path: str, cwd: str) -> list[str]:
        """The file under the tracked cwd, the event cwd AND every candidate directory the shell may be in by then (`history`, from the
        candidate set of `split_pipelines`: a `cd` that may not run, or is not on straight-line code, adds its moved directories to the set
        instead of replacing it; later relative `cd`s and this path resolve against all of them; a nested shell starts from that set). Not covered: a `cd` in a shell function,
        `trap`, a `#` comment, a target the gate cannot name (`cd $D` set elsewhere, `cd -`, `cd $(...)`) and a directory an earlier command of the
        same line creates. Every distinct text is returned and scanned (am-02 round 1 L1; mg-51 r2 B1, r5)."""
        path = self.expand(path)
        dirs = [cwd]
        if not os.path.isabs(home_expanded(path)):
            dirs += [d for d in (self.cwd0, *self.history.get(cwd, ())) if d]
        texts = []
        for d in dict.fromkeys(dirs):
            if (path, d) not in self.cache:
                self.read_calls += 1
                if self.read_calls > MAX_READS:        # a command with thousands of operands x directories must not outrun the hook's 15 s
                    self.history.overflow = True
                    break
                self.cache[path, d] = read_file(path, d)   # each (path, dir) is read once: a repeated operand costs nothing more
            texts.append(self.cache[path, d])
        return [t for k, t in enumerate(texts) if t and t not in texts[:k]]

    def add_file(self, path: str, cwd: str, **kw) -> None:
        if kw.get("operand") and self.forced >= MAX_FORCED:    # past the operand cap nothing more is read (it would be dropped by `add`)
            self.truncated = True
            return
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


def sub_files(word: str):
    """(files read verbatim, files read through a filter) named inside the `$( ... )`/backticks of `word`: a lone
    `cat F ...` or `< F` keeps the file's fence; anything else (grep, sed, head, `<F tr`, a pipe) is a filter."""
    plain, filt = [], []
    for inner in substitutions(word):
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


def prefix_stripped(words):
    """The texts a write's words send: a flag prefix glued before a fence (`--body="```...`, `-b"```...`, `-f body=```...`)
    is not part of the body (a prefix before anything else is, and stays)."""
    def strip(w, prev):
        if prev in ("-f", "-F", "--field", "--raw-field"):
            m = KEY_PREFIX.match(w)
        else:                                  # a value of a flag (`--body "-b```..."`) is the body itself
            m = FLAG_PREFIX.match(w) if w.startswith("-") and prev not in GH_VALUE_FLAGS else None
        return w[m.end():] if m else w

    out, prev, after_fd = [], "", False
    for w in words:
        if isinstance(w, FdWord):              # `2>f` (a descriptor: the flag before it still owns the next word) or `2 >f` (an argument):
            out.append(w)                      # a word behind it is stripped as the flag before the `2` and as the `2`, and judged unstripped too
            after_fd = True
            continue
        out.append(strip(w, prev))
        if after_fd:
            out.extend((strip(w, ""), w))
        after_fd = False
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


def code_string(words):
    """The code a shell wrapper in `words` runs: the word after the first `-c` behind a shell name, or what follows `eval`, else None. Linear:
    the next `-c` of every word comes from one right-to-left pass (a pile of shell names must not cost n^2 `SHELL_C` matches)."""
    after, nearest = [None] * len(words), None
    for x in range(len(words) - 1, -1, -1):
        after[x] = nearest
        if SHELL_C.match(words[x]):
            nearest = x
    for k, w in enumerate(words):
        if os.path.basename(w) in SHELLS:
            if after[k] is not None and after[k] + 1 < len(words):
                return words[after[k] + 1]
        elif w == "eval":
            return " ".join(words[k + 1:])
    return None


def collect(command: str, cwd: str, scan: Scan, depth: int = 0, bases=()) -> None:
    cleaned, bodies = split_heredocs(command)
    tokens, parsed = tokenize(cleaned)
    tokens = merge_substitutions(tokens)
    words_all = [t for t in tokens if t and not set(t) <= set(PUNCT)]
    for w in words_all:
        if ASSIGN.match(w):
            assign_to(scan.env, w)
    if not parsed and loose_write(command):
        scan.write = True                      # unparseable: fail closed, scan the raw command too
        scan.add(command)
    for body, head, _quoted in bodies:
        if loose_write(body):                  # a script heredoc that names a gh write is one
            scan.write = True
            scan.add(body)
    pipes = split_pipelines(tokens, cwd, scan.expand, scan.history, bases)
    running = None                             # (at, bases) of a script fed to a shell: the same for every such heredoc, so built once
    for body, head, _quoted in bodies:
        if depth < 3 and shell_head(head):     # a script fed to a shell: its gh writes read their operand files, under the directory of the
            # command that runs it (`cd real && bash <<X`); which segment that is, is not tracked, so it is collected once, under the
            # last cwd, and every cwd the command had is tried for its relative operands (`history`)
            if scan.history.expired():         # out of time or over a cap: stop reading; the verdict is a deny (judge), but only for a gh write,
                if "gh" in body:               # so a script that names gh counts as one (a linear test: no regex over the body)
                    scan.write = True
                break
            if running is None:
                segs = list(dict.fromkeys(seg["cwd"] for pipe in pipes for seg in pipe.segments))
                at = [seg["cwd"] for pipe in pipes for seg in pipe.segments][-1:] or [cwd]
                scan.history.note(at[0], [cwd, *segs])
                held = dict.fromkeys(d for sg in segs for d in scan.history.get(sg, ()))
                running = (at[0], list(dict.fromkeys([cwd, *segs, *held])))
            collect(body, running[0], scan, depth + 1, bases=running[1])
    own = Counter()                            # the write's own argument words, counted: a second identical word is another word

    def subs(w: str, at: str) -> None:
        """Files a `$( ... )`/backtick inside `w` reads: a lone `cat F` keeps its fence, a filter's output does not."""
        if "$(" in w or "`" in w:
            plain, filt = sub_files(w)
            for f in plain:
                scan.add_file(f, at, operand=True)
            for f in filt:
                scan.add_file(f, at, operand=True, raw=True)

    def feeder(w: str, seg, raw: bool = False) -> None:
        scan.add(w)
        if scan.incidental < MAX_FILES and len(w) < 4096 and "\n" not in w:
            found = scan.reads(w.split("=", 1)[-1] if "=" in w else w, seg["cwd"])
            if found:
                scan.incidental += 1
                for content in found:
                    scan.add(content, raw=raw)
    for pipe in pipes:
        if scan.history.expired():             # out of time or over a cap: stop reading; judge denies any command that names `gh` as a word (GH_WORD), a write placed or not
            break
        gh = [(seg, gh_invocation(seg["words"])) for seg in pipe.segments]
        writes = [(seg, g) for seg, g in gh if g and is_write(g[0], g[1], g[2])]
        for seg in pipe.segments:              # code-bearing strings are collected again
            words = seg["words"]
            if depth < 3:
                plain = [w for w in words if not isinstance(w, FdWord)]    # `bash -c 2>/dev/null 'CODE'`: the `2` is a descriptor, or the code
                done = set()
                for reading in ([words] if len(plain) == len(words) else [plain, words]):
                    code = code_string(reading)
                    if code is not None and code not in done:
                        done.add(code)
                        collect(code, seg["cwd"], scan, depth + 1, bases=scan.history.get(seg["cwd"], ()))
                for w in (*words, *seg["here"]):
                    if "gh" in w and ("$(" in w or "`" in w):
                        for inner in substitutions(w):
                            collect(inner, seg["cwd"], scan, depth + 1, bases=scan.history.get(seg["cwd"], ()))
        if not writes:
            continue
        scan.write = scan.token_write = True
        feeders = [seg for seg, g in gh if not (g and is_write(g[0], g[1], g[2]))]
        # a file read through a filter (`grep M report.md | gh ...`) reaches the write without its fence
        filtered = len(feeders) > 1 or any(not seg["words"] or os.path.basename(seg["words"][0]) not in PLAIN_FEEDERS
                                           for seg in feeders)
        for seg, g in gh:
            if g and is_write(g[0], g[1], g[2]):
                scan.api_write = scan.api_write or g[0] == "api"   # a GraphQL `query` is read decoded too (judge)
                own.update(g[2])
                for shown in prefix_stripped(g[2]):
                    scan.add(shown, force=True)
                plain = [w for w in g[2] if not isinstance(w, FdWord)]     # an fd word is also no operand (`--body-file 2>/dev/null b.md` reads b.md)
                for f in dict.fromkeys([*operand_files(g[0], g[2]), *(operand_files(g[0], plain) if len(plain) < len(g[2]) else ())]):
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
                subs(h, seg["cwd"])            # a here-string expands `$( )` (`<<< "$(cat b.md)"`)
    if not scan.token_write and loose_write(cleaned):
        scan.write = True                      # backstop: a gh write the token path could not place; words only, no files
    if scan.write:
        for w in words_all:                    # a body file or variable the same command writes first
            if own[w] > 0:                     # a write's own words went in above (a fence prefix removed); one use each,
                own[w] -= 1                    # so a word that only equals a flag word elsewhere is scanned as written (am-02, C3)
            else:
                scan.add(w)
        cwds = []                              # `cd DIR && BODY="$(cat raw.md)"; gh ... "$BODY"`: each segment's own cwd
        for pipe in pipes:
            for seg in pipe.segments:
                for w in seg["words"]:
                    subs(w, seg["cwd"])
                if seg["cwd"] not in cwds:
                    cwds.append(seg["cwd"])
        for body, _head, quoted in bodies:
            scan.add(body)
            if not quoted:                     # an unquoted heredoc expands its `$( )` lines; a quoted one does not
                for at in cwds[:8] or [cwd]:
                    subs(body, at)


def judge(command: str, cwd: str, am_loader) -> str:
    """The deny reason, or "" to allow. `am_loader` is called only for a command that holds a gh write."""
    if "gh" not in command:
        return ""
    scan = Scan(cwd)
    collect(command, cwd, scan)
    if not scan.write and not (scan.history.overflow and GH_WORD.search(command)):   # an overflow stops the collector early: the write may be unplaced
        return ""
    am = am_loader()
    # a `gh api` write may carry a GraphQL `query` (`-f query=...`, `-F query=@file`, a `--input` JSON leaf) whose string literals GitHub
    # decodes, so every text with a backslash is also judged decoded (an extra look: a false deny at worst; mg-51, Carried 52). A
    # whole JSON payload that `Scan.add` parsed is not a query text (its leaves are, and are separate texts), so it is left alone.
    api = scan.api_write or bool(GH_API_LOOSE.search(command) and API_FLAG_LOOSE.search(command))   # also a `gh api` write the loose paths placed

    def gql(texts):
        return [graphql_unescape(t) for t in texts if "\\" in t and id(t) not in scan.payload_ids] if api else []
    decoded, decoded_raw = gql(scan.texts), gql(scan.raw_texts)
    for t in scan.texts + decoded:
        found = live_approve(t, am)
        if found:
            return found
    for t in scan.raw_texts + decoded_raw:
        found = live_approve(t, am, raw=True)
        if found:
            return found
    if scan.history.overflow:                  # more directories, reads or path than this gate can follow: a live file may be out of reach
        return "more `cd` directories or operand reads than this gate can follow in time (%d directories, %d reads)" % (MAX_DIRS, MAX_READS)
    if scan.deep:                              # judged on the whole payload, not on its MAX_TEXT cut or its channel (file, pipe, filter)
        return "a JSON payload nested past this gate's parser limit that mentions APPROVE (its leaves cannot be read)"
    if scan.truncated and any(mentions_approve_decoded(t) for t in scan.texts):   # the unread rest may hold an escaped APPROVE (mg-51)
        return "more operand text than this gate can scan in time (%d files or %d bytes) next to the word APPROVE" % (
            MAX_FORCED, MAX_FORCED_BYTES)
    if any(mentions_approve(t) for t in scan.texts):
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
