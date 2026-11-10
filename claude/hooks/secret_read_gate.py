#!/usr/bin/env python3
"""PreToolUse: block a tool call that would read or write a secret file (2026-11-04, issue #284 item 2).

The policy is config/secret-deny.toml, rendered by bin/render-secret-deny into config/secret_deny_policy.json, which
this hook reads (found from this file's realpath: <repo>/claude/hooks/ -> <repo>/config/; SECRET_DENY_POLICY overrides
it). docs/secret-deny.md says what is enforced where and the honest limits.

What it inspects: Read/Edit/MultiEdit/Write/NotebookEdit `file_path`/`notebook_path`; Grep `path` and `glob`; a Bash
`command` (shlex tokens, `<file`, `--x=file`, `a:b` parts, `~`/`~user`/`$HOME`/`${HOME}`, glob tokens; every word, the
lines of a `*** Begin Patch` block included, since the shell runs them); Codex `apply_patch` file headers (`*** Add|Update|
Delete File:`, `*** Move to:`) in any string of a non-file tool's input, and only for a genuine patch payload (SHELL_TOOLS,
PATCH_TOOLS, patch_payload) is a patch block's body left out of the shell words. Glob
is not gated (it returns names only). Each candidate path is evaluated as given, absolutized against the payload's `cwd`,
and as its realpath, separately: the call is blocked when ANY candidate matches a deny pattern and no allow pattern
matches that same candidate. A pattern ending in `/**` also denies its directory (`grep -r x ~/.ssh`, `tar c ~/.ssh`).

A Bash command's literal words are all checked first (cheap), then the glob words without `**`, then those with it.
Each glob word (`*`, `?`, `[...]` or `{a,b}`) is expanded against the filesystem by the hook's own segment-by-segment
walk (os.scandir; a wildcard never matches a leading `.`; a `**` segment is zero or more non-hidden directory levels, as
zsh and bash's globstar expand it; a symlinked directory a wildcard reaches is not entered, so `/proc/*/root` loops end,
but the link itself is checked as a path, so `d -> ~/.ssh` hits `~/.ssh`; a final match may be a symlink and is checked
through its realpath), and each match checked as a path. The walk is bounded for the whole call: MAX_GLOB_SCAN directory
entries, MAX_GLOB_HITS matches per word and GLOB_S seconds. When nothing matches, or the walk was cut short (a bound, or
a symlinked directory skipped), the pattern itself is checked: it blocks when some path could match it and a deny
pattern and no allow pattern, under two rules that keep code and regexes from tripping it: the hidden-file rule (a
wildcard never consumes a leading `.`) and pinning (the token's wildcards may not stand in for a deny pattern's literal
text; a cheap test on the token's literals, `**/` read as "" or `/`, skips the rules it cannot spell). So every word gets
at least that check, `cat ~/.ssh/id_*` and `find . -name '*.key'` block, while `echo *` and `grep 'a.*'`
pass (an absolute deep miss that finishes under the shared glob budget also passes via the pattern check; one
truncated by that budget fails closed). A glob word gets WORD_S on its first try within a shared FIRST_PASS_S cap; one that runs longer is set aside
(cached) and retried after every other word: pattern-only first, then a real walk with remaining budget when the
pattern cannot decide (broad globs such as `id_*` / `*` need the walk to catch `id_rsa` / `server.key` on disk).
If that walk cannot run, times out, or is truncated by the shared GLOB_S / scan bound (completing slow dummies
can start and exhaust GLOB_S under WORD_S while FIRST_PASS_S == GLOB_S, or burn MAX_GLOB_SCAN before a later
secret glob — relative/cwd or absolute/tilde-expanded), the call fails closed. Absolute deep globs whose walk
was not truncated by that shared budget still fall back to the pattern check (intentional allow when the
pattern is clean; a truncated walk never cache-allows). Eight crafted slow words used to spend 8×WORD_S
and fail the call open before a later `cat ~/.ssh/id_*` (docs/secret-deny.md C7, 2026-11-04); the first-pass
cap and set-aside retry close that: a word that times out twice, an OutOfTime while glob words remain unchecked,
a set-aside word whose pattern-only check is inconclusive with no walk budget left, a deferred walk truncated
by GLOB_S / MAX_GLOB_SCAN / MAX_GLOB_HITS, or a first-pass glob (relative/cwd or absolute/tilde) truncated the
same way, fails closed (blocks) instead of allowing. `_glob_budget_hit` is sticky across brace alternatives
inside one word (`{,id_*}` must not clear a prior truncate).

Grep (2026-11-04): Claude's Grep runs ripgrep with `--hidden`, so it reads dotfiles and descends into `~/.ssh`. Its root
(`path`, else the cwd) is walked breadth-first (bounded: depth, entries, time shared by every root; VCS dirs and
node_modules skipped); every distinct directory the root may name is walked, as concrete() gives a file's forms
(2026-11-06: `link/..` searches beside link's target, a normalizing tool searches the normalized path), and the
call blocks when a denied file under one is one the `glob` and `type` let through, as ripgrep combines them (the last
matching glob decides; a positive glob reads a file whatever the `type`; a known `type`, as its file names, filters only
the files no positive glob decides; its names are RG_TYPES unioned with `rg --type-list` of the rg on PATH), naming the
file and how to leave it out. When the walk hits a bound it fails open,
except for a root that contains a home-level deny
(`~`, `/home`, `/`), which blocks. `.gitignore` is not consulted, so a gitignored `.env` still blocks a whole-project Grep
(the price of not parsing ignore files). Only when the root does not exist or the walk was cut short is the glob also
checked as a pattern (pinning, no hidden-file rule): then `glob: ".env*"` blocks and `"*.py"` passes.

Block: exit 2 with one line on stderr naming the rule and docs/secret-deny.md (Claude and Codex both block on 2).
Fail open: bad stdin, a missing or corrupt policy, or any exception exits 0 with a short stderr notice, so a bug never
turns into a block on every Read. SECRET_DENY_OFF=1 (operator's environment) turns it off.

Runs under Python 3.9 (macOS /usr/bin/python3): no tomllib, no `match`, no runtime `X | Y` types.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

DOC = "docs/secret-deny.md"
FILE_TOOLS = {
    "Read": ("file_path",),
    "Edit": ("file_path",),
    "MultiEdit": ("file_path",),
    "Write": ("file_path",),
    "NotebookEdit": ("notebook_path", "file_path"),
    "NotebookRead": ("notebook_path", "file_path"),
}
UNGATED = {"Glob"}
# Tools whose `command` a shell runs: every word of it is analyzed, `*** Begin Patch` regions included. Codex's names
# are listed too (an extra name only makes the hook check more).
SHELL_TOOLS = {"Bash", "shell", "local_shell", "exec_command", "unified_exec", "shell_command", "container.exec"}
PATCH_TOOLS = {"apply_patch", "ApplyPatch"}   # Codex's patch tool: its patch regions are data, only headers are paths
MAX_TOKEN = 4096        # PATH_MAX; a longer token is a heredoc body or data, not a path
MAX_TOKENS = 20000
MAX_GLOB_HITS = 500       # matches checked per Bash glob word; past it the word's pattern is checked too
MAX_GLOB_SCAN = 20000     # directory entries the Bash glob walk may read in one call
GLOB_S = 2.0              # Bash glob walk time in one call (inside BUDGET_S); past it every glob word gets the pattern check
GLOB_MARGIN_S = 3.0       # BUDGET_S time the glob walk always leaves for the checks that follow it
WORD_S = 1.0              # one Bash glob word's first try; past it the word waits until every other word is checked
FIRST_PASS_S = 2.0        # shared first-pass WORD_S budget across all Bash glob words (inside BUDGET_S)
MAX_BRACE = 64
MAX_STATES = 200000     # product-automaton budget; exhausting it counts as an overlap (blocks)
BUDGET_S = 8.0          # whole-call analysis budget; past it the hook fails open (except Bash glob: fail closed)
WALK_S = 4.0            # Grep root walk budget (inside BUDGET_S); past it the walk counts as truncated
MAX_WALK_DEPTH = 6      # directory levels below a Grep root
MAX_WALK_ENTRIES = 20000
WALK_SKIP = {".git", ".svn", ".hg", ".bzr", ".jj", ".sl", "node_modules"}   # Grep's VCS exclusions, plus node_modules
PATCH_BEGIN = re.compile(r"^\*\*\* Begin Patch[ \t]*$", re.MULTILINE)
PATCH_END = re.compile(r"^\*\*\* End Patch[ \t]*$", re.MULTILINE)
PATCH_HEADER = re.compile(r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to):[ \t]*(.+?)[ \t]*$", re.MULTILINE)
BRACE_GROUP = re.compile(r"\{[^{}\"': ]*(?:,|\.\.)[^{}\"': ]*\}")
GLOB_CHARS = set("*?[")


# ---- glob patterns: atoms, a regex for concrete paths, an NFA for pattern overlap ----------------------------------
LIT, QM, STAR, DSTAR, DSLASH = range(5)   # literal char, ?, * (no /), ** (any, / included), **/ ("" or ".*/")


class OutOfTime(Exception):
    pass


class WordOutOfTime(Exception):
    """One Bash glob word's own budget (WORD_S) ran out: the word is set aside and retried after every other word."""


class GlobBudgetExceeded(Exception):
    """Bash glob analysis could not finish within budget: fail closed (an unchecked word may name a secret)."""

    def __init__(self, word: str = ""):
        self.word = word
        Exception.__init__(self, "glob analysis budget exceeded%s" % ((" on %s" % word) if word else ""))


# Sentinel in Checker._words: word was set aside after WordOutOfTime; deferred retry clears it.
_SET_ASIDE = object()

_DEADLINE = [float("inf")]
_WORD_DEADLINE = [float("inf")]


def tick() -> None:
    now = time.monotonic()
    if now > _DEADLINE[0]:
        raise OutOfTime("analysis took longer than %.0f s" % BUDGET_S)
    if now > _WORD_DEADLINE[0]:
        raise WordOutOfTime()


def literal_prefix(ats: list) -> str:
    out = []
    for kind, c in ats:
        if kind != LIT:
            break
        out.append(c)
    return "".join(out)


def literal_runs(ats: list) -> list:
    """The runs of consecutive literal atoms."""
    runs, cur = [], []
    for kind, c in ats:
        if kind == LIT:
            cur.append(c)
        elif cur:
            runs.append("".join(cur))
            cur = []
    if cur:
        runs.append("".join(cur))
    return runs


def token_items(ats: list) -> list:
    """What a token can spell under pinning, item by item: a literal character; "\\x00" for `?` (it must take a character
    by a wildcard move, so it breaks a run); None for `**/`, which spells "" or a literal `/`. `*` and `**` drop out:
    under pinning they can only match "" inside a deny pattern's literal run. Under pinning every literal run of a deny
    pattern is spelled by consecutive token literal moves with only empty wildcard matches between them, so a run the
    token cannot spell (`spells`) rules the overlap out (2026-11-04: `f(**kw0)` in a heredoc cost 80 ms a word; a
    `**/node_modules/**` line of a .gitignore heredoc 0.1-0.7 s before `**/` was modelled here)."""
    out = []
    for kind, c in ats:
        if kind == LIT:
            out.append(c)
        elif kind == QM:
            out.append("\x00")
        elif kind == DSLASH:
            out.append(None)
    return out


def spells(items: list, run: str) -> bool:
    """True when `run` is a substring of some string the items spell (each None as "" or "/"). Sound for pinning: it
    answers False only when no choice of the `**/` items puts `run` among the token's consecutive literals."""
    n = len(items)

    def close(states):
        todo = list(states)
        seen = set(states)
        while todo:
            j = todo.pop()
            if j < n and items[j] is None and j + 1 not in seen:
                seen.add(j + 1)
                todo.append(j + 1)
        return seen

    states = close(range(n + 1))
    for ch in run:
        states = close({j + 1 for j in states if j < n and (items[j] == ch or (items[j] is None and ch == "/"))})
        if not states:
            return False
    return True


def atoms(pat: str, prefix: str = "") -> list:
    """`prefix` is taken literally (a cwd may hold glob characters). `[...]` becomes one `?`; policy patterns never
    hold one (render refuses it)."""
    out = [(LIT, c) for c in prefix]
    i, n = 0, len(pat)
    while i < n:
        c = pat[i]
        if c == "*":
            j = i
            while j < n and pat[j] == "*":
                j += 1
            if j - i == 1:
                out.append((STAR, None))
                i = j
            elif j < n and pat[j] == "/":
                out.append((DSLASH, None))
                i = j + 1
            else:
                out.append((DSTAR, None))
                i = j
            continue
        if c == "?":
            out.append((QM, None))
        elif c == "[" and pat.find("]", i + 2) != -1:
            out.append((QM, None))
            i = pat.find("]", i + 2) + 1
            continue
        else:
            out.append((LIT, c))
        i += 1
    return out


def to_regex(ats: list, fold: bool):
    parts = []
    for kind, c in ats:
        if kind == LIT:
            parts.append(re.escape(c))
        elif kind == QM:
            parts.append("[^/]")
        elif kind == STAR:
            parts.append("[^/]*")
        elif kind == DSTAR:
            parts.append(".*")
        else:
            parts.append("(?:.*/)?")
    return re.compile("".join(parts), re.DOTALL | (re.IGNORECASE if fold else 0))


class Nfa:
    """States 0..n follow the atoms; `**/` adds one extra state. Transitions are (kind, char, target) with kind 'lit',
    'ns' (any char but /) or 'any'. With `dotfile`, a wildcard never consumes a `.` that starts a path segment (the
    shell's and ripgrep's hidden-file rule: `*.py` does not reach `.env.py`, `**/` does not enter `.ssh/`)."""

    def __init__(self, ats: list, dotfile: bool = False):
        self.dotfile = dotfile
        n = len(ats)
        self.eps = [[] for _ in range(n + 1)]
        self.trans = [[] for _ in range(n + 1)]
        self.final = n
        for i, (kind, c) in enumerate(ats):
            if kind == LIT:
                self.trans[i].append(("lit", c, i + 1))
            elif kind == QM:
                self.trans[i].append(("ns", None, i + 1))
            elif kind == STAR:
                self.trans[i].append(("ns", None, i))
                self.eps[i].append(i + 1)
            elif kind == DSTAR:
                self.trans[i].append(("any", None, i))
                self.eps[i].append(i + 1)
            else:
                m = len(self.eps)
                self.eps.append([])
                self.trans.append([("any", None, m), ("lit", "/", i + 1)])
                self.eps[i].extend([i + 1, m])

    def closure(self, states) -> frozenset:
        seen = set(states)
        todo = list(states)
        while todo:
            for t in self.eps[todo.pop()]:
                if t not in seen:
                    seen.add(t)
                    todo.append(t)
        return frozenset(seen)

    def literals(self, states):
        """The set of characters these states can take when all their transitions are literals, else None."""
        out = set()
        for s in states:
            for kind, c, _ in self.trans[s]:
                if kind != "lit":
                    return None
                out.add(c)
        return out

    def moves(self, state: int, ch: str, seg_start: bool = False) -> list:
        """[(target, kind)] for one character from one state (no epsilon closure)."""
        hidden = self.dotfile and seg_start and ch == "."
        out = []
        for kind, c, t in self.trans[state]:
            if kind == "lit":
                if c == ch:
                    out.append((t, kind))
            elif not hidden and (kind == "any" or ch != "/"):
                out.append((t, kind))
        return out

    def step(self, states, ch: str, seg_start: bool = False) -> frozenset:
        return self.closure({t for s in states for t, _ in self.moves(s, ch, seg_start)})


_NFAS = {}


def nfa(ats: list, dotfile: bool = False) -> Nfa:
    key = (tuple(ats), dotfile)
    m = _NFAS.get(key)
    if m is None:
        m = _NFAS[key] = Nfa(ats, dotfile)
    return m


def nonempty(include: list, exclude: list, dotfile_first: bool = False, pin_first: bool = False) -> bool:
    """True when some string matches every atom list in `include` and none in `exclude`. The include side runs as a
    product of NFA state tuples, the exclude side as subsets, so the answer is exact; a blown budget answers True.

    `dotfile_first` gives include[0] the hidden-file rule (it is a shell or ripgrep glob). `pin_first` (with two
    include lists) forbids a wildcard of include[0] from consuming a character that include[1] matches with a literal:
    a glob token must spell a denied name itself (`id_*` reaches no `id_rsa`, `*` reaches no `x.key`), while a deny
    wildcard still lets a token reach into a denied directory (`~/.ssh/id_*` against `~/.ssh/**`)."""
    inc = [nfa(a, dotfile_first and i == 0) for i, a in enumerate(include)]
    exc = [nfa(a) for a in exclude]
    k = len(inc)
    pin = pin_first and k >= 2
    alphabet = {c for a in list(include) + list(exclude) for kind, c in a if kind == LIT}
    alphabet.update(("/", ".", "\x00"))   # "\x00" stands for every other character (never a pattern literal)

    def close(tup):
        out = [()]
        for i, st in enumerate(tup):
            out = [o + (c,) for o in out for c in inc[i].closure({st})]
        return out

    start_inc = frozenset(close((0,) * k))
    start = (start_inc, tuple(m.closure({0}) for m in exc), True)
    seen = {start}
    todo = [start]
    while todo:
        tick()
        tuples, ex, seg = todo.pop()
        if any(all(t[i] == inc[i].final for i in range(k)) for t in tuples) and not any(
                m.final in ex[j] for j, m in enumerate(exc)):
            return True
        # Only characters every include machine can take here: a literal-only state set narrows it to its literals.
        chars = alphabet
        for i in range(k):
            lits = inc[i].literals({t[i] for t in tuples})
            if lits is not None:
                chars = lits if chars is alphabet else chars & lits
        for ch in chars:
            nxt_t = set()
            for t in tuples:
                combos = [((), False, False)]   # (targets so far, first is a wildcard move, second is a literal move)
                for i in range(k):
                    moves = inc[i].moves(t[i], ch, seg)
                    combos = [(tg + (to,), w or (i == 0 and kind != "lit"), l or (i == 1 and kind == "lit"))
                              for tg, w, l in combos for to, kind in moves]
                for tg, w, l in combos:
                    if pin and w and l:
                        continue
                    nxt_t.update(close(tg))
            if not nxt_t:
                continue
            nxt = (frozenset(nxt_t), tuple(m.step(ex[j], ch, seg) for j, m in enumerate(exc)), ch == "/")
            if nxt in seen:
                continue
            if len(seen) >= MAX_STATES:
                return True
            seen.add(nxt)
            todo.append(nxt)
    return False


# ---- the policy ---------------------------------------------------------------------------------------------------
def home_forms() -> list:
    home = os.path.expanduser("~").rstrip("/") or "/"
    forms = [home]
    try:
        real = os.path.realpath(home)
        if real not in forms:
            forms.append(real)
    except OSError:
        pass
    return forms


def absolute_forms(pat: str, homes: list) -> list:
    """A policy pattern as absolute-path globs: `~/x` per home form, `/x` as is, `**/x` as is, a bare `x` as `**/x`."""
    if pat.startswith("~/"):
        return [h.rstrip("/") + pat[1:] for h in homes]
    if pat.startswith("/") or pat.startswith("**/"):
        return [pat]
    return ["**/" + pat]


class Rule:
    def __init__(self, name: str, glob_str: str, fold: bool):
        self.name = name
        self.atoms = atoms(glob_str.lower() if fold else glob_str)
        self.regex = to_regex(self.atoms, fold)
        self.prefix = literal_prefix(self.atoms)
        self.runs = literal_runs(self.atoms)


class Policy:
    def __init__(self, deny: list, allow: list, homes=None, fold=None):
        if fold is None:
            fold = sys.platform == "darwin"   # APFS is case-insensitive: `.ENV` opens `.env`
        self.fold = fold
        self._verdicts = {}
        homes = homes if homes is not None else home_forms()
        self.deny = []
        self.allow = []
        for pat in deny:
            for g in absolute_forms(pat, homes):
                self.deny.append(Rule(pat, g, fold))
                if g.endswith("/**") and len(g) > 3:   # `dir/**` also denies the directory itself (a Grep or tar root)
                    self.deny.append(Rule(pat, g[:-3], fold))
        for pat in allow:
            for g in absolute_forms(pat, homes):
                self.allow.append(Rule(pat, g, fold))
        # One alternation of every deny regex: a cheap first test for the Grep walk's many paths.
        self.any_deny = re.compile("|".join("(?:%s)" % r.regex.pattern for r in self.deny),
                                   re.DOTALL | (re.IGNORECASE if fold else 0))
        # Where each absolute deny rule lives: the directory holding its first wildcard, or a literal path's parent.
        # A Grep root at or above one of these (`~`, `/home`, `/`) can reach that secret.
        self.anchors = []
        for r in self.deny:
            if not r.prefix.startswith("/"):
                continue
            whole = len(r.prefix) == len(r.atoms)
            anchor = os.path.dirname(r.prefix) if whole else r.prefix.rsplit("/", 1)[0]
            anchor = anchor or "/"
            if anchor not in [a for a, _ in self.anchors]:
                self.anchors.append((anchor, r.name))

    def anchor_under(self, root: str):
        """(anchor, rule name) of an absolute deny rule whose anchor is `root` or lies below it, or None."""
        key = root.lower() if self.fold else root
        base = key.rstrip("/") + "/"
        for anchor, name in self.anchors:
            if anchor == key or anchor.startswith(base):
                return anchor, name
        return None

    def verdict(self, path: str):
        """The deny rule name a concrete absolute path hits, or None (no deny, or an allow matches this path)."""
        if any(r.regex.fullmatch(path) for r in self.allow):
            return None
        for r in self.deny:
            if r.regex.fullmatch(path):
                return r.name
        return None

    def pattern_verdict(self, glob_str: str, prefix: str = "", dotfile: bool = True):
        """The deny rule name some path matching the glob (`prefix` taken literally) could hit with no allow covering
        it, or None. `dotfile` applies the shell's hidden-file rule; Grep's ripgrep runs with `--hidden`, so not there."""
        key = (glob_str, prefix, dotfile)
        if key not in self._verdicts:
            self._verdicts[key] = self._pattern_verdict(glob_str, prefix, dotfile)
        return self._verdicts[key]

    def _pattern_verdict(self, glob_str: str, prefix: str, dotfile: bool = True):
        ats = atoms(glob_str.lower() if self.fold else glob_str, prefix.lower() if self.fold else prefix)
        lead = literal_prefix(ats)
        items = token_items(ats)
        allows = [r.atoms for r in self.allow]
        for r in self.deny:
            if not (lead.startswith(r.prefix) or r.prefix.startswith(lead)):
                continue   # their fixed leading text differs: no common path
            if not all(spells(items, run) for run in r.runs):
                continue   # the token cannot spell this rule's literal text (pinning, see nonempty)
            if nonempty([ats, r.atoms], allows, dotfile_first=dotfile, pin_first=True):
                return r.name
        return None


def policy_path() -> str:
    env = os.environ.get("SECRET_DENY_POLICY")
    if env:
        return env
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    return os.path.join(root, "config", "secret_deny_policy.json")


def load_policy(path=None) -> Policy:
    with open(path or policy_path(), encoding="utf-8") as f:
        data = json.load(f)
    deny, allow = data.get("deny"), data.get("allow")
    for name, lst in (("deny", deny), ("allow", allow)):
        if not isinstance(lst, list) or not all(isinstance(x, str) and x for x in lst):
            raise ValueError("policy field %r is not a list of strings" % name)
    if not deny:
        raise ValueError("policy has no deny patterns")
    return Policy(deny, allow)


# ---- candidates -----------------------------------------------------------------------------------------------------
def expand_home(s: str) -> str:
    home = os.path.expanduser("~")
    s = s.replace("${HOME}", home).replace("$HOME", home)
    if s == "~" or s.startswith("~/"):
        s = home + s[1:]
    elif s.startswith("~"):
        try:
            s = os.path.expanduser(s)   # `~user/...`: that user's home (unchanged when there is no such user)
        except (KeyError, ValueError, OSError):
            pass
    return s


def is_glob(s: str) -> bool:
    return bool(GLOB_CHARS.intersection(s)) or bool(BRACE_GROUP.search(s))


def expand_braces(s: str) -> list:
    """The shell's (and ripgrep's) `{a,b}` alternatives, innermost group first. A `{1..3}` range, or more than
    MAX_BRACE results, becomes `*` instead: a superset, so a token can only block more."""
    done, todo = [], [s]
    while todo:
        cur = todo.pop()
        m = BRACE_GROUP.search(cur)
        if not m:
            done.append(cur)
            continue
        body = m.group()[1:-1]
        alts = body.split(",") if "," in body else ["*"]
        todo.extend(cur[:m.start()] + a + cur[m.end():] for a in alts)
        if len(done) + len(todo) > MAX_BRACE:
            prev = None
            while prev != s:
                prev, s = s, BRACE_GROUP.sub("*", s)
            return [s]
    return done


def concrete(path: str, cwd: str) -> list:
    out = []
    if os.path.isabs(path):
        out.append(path)
    joined = os.path.join(cwd, path)
    full = os.path.normpath(joined)
    out.append(full)
    try:
        # Both realpaths: the kernel opens `link/../x` beside link's target (realpath of the unnormalized join,
        # Codex review on PR 289), while a tool that normalizes `..` by text first opens the normalized path,
        # which may itself be a symlink to a secret (adversary on PR 289). Checking more paths only blocks more.
        out.append(os.path.realpath(joined))
        out.append(os.path.realpath(full))
    except (OSError, ValueError):
        pass
    seen = []
    for p in out:
        if p not in seen:
            seen.append(p)
    return seen


_scandir = os.scandir   # the Bash glob walk's directory reader (a test replaces it with a synthetic tree)
_SEG_RX = {}


def seg_regex(seg: str):
    rx = _SEG_RX.get(seg)
    if rx is None:
        rx = _SEG_RX[seg] = re.compile(fnmatch.translate(seg))
    return rx


class Checker:
    def __init__(self, policy: Policy, cwd: str):
        self.policy = policy
        self.cwd = cwd
        try:
            real = os.path.realpath(cwd)
        except (OSError, ValueError):
            real = cwd
        self.cwds = [cwd] if real == cwd else [cwd, real]
        self._words = {}
        self.deferred = []       # glob words whose WORD_S ran out, retried after every other word
        self._aside_count = {}   # times a glob word was set aside; a second time fails closed
        self._scanned = 0        # directory entries the glob walk has read in this call
        self._glob_until = None  # the glob walk's deadline, set on its first use
        self._glob_budget_hit = False  # True when expand truncated on GLOB_S / MAX_GLOB_SCAN / MAX_GLOB_HITS

    def path(self, raw: str):
        """(rule, shown path) for a literal path, or None."""
        if not raw or len(raw) > MAX_TOKEN or "\x00" in raw:
            return None
        p = expand_home(raw)
        for cand in concrete(p, self.cwd):
            hit = self.policy.verdict(cand)
            if hit:
                return hit, cand
        return None

    def glob(self, raw: str):
        """(rule, shown) for a glob: filesystem matches checked as paths; with none, the pattern itself."""
        if not raw or len(raw) > MAX_TOKEN or "\x00" in raw:
            return None
        # Reset once per word, not per brace alternative: a later empty alt (`{,id_*}`) must not
        # clear a truncate flag set while walking an earlier secret alt (Security HIGH, PR 413 tip).
        self._glob_budget_hit = False
        for pat in expand_braces(expand_home(raw)):
            found = self._glob_one(raw, pat)
            if found:
                return found
        return None

    def expand(self, base: str, segs: list, state: dict):
        """(path, is_match) under `base` (taken literally) for the glob segments, depth first and lazily, as the shell
        expands them: a wildcard segment never matches a leading `.`; a literal segment is joined as is (and followed, as
        the shell does); a `**` segment is zero or more non-hidden directory levels (zsh's default, bash's globstar;
        2026-11-04), and as the last segment every non-hidden entry below. A directory a wildcard or `**` reaches is
        entered only when it is not a symlink (`/proc/*/root` and `a -> ..` loop); such a symlink is yielded with
        is_match False, so the caller checks the link itself (its realpath: `d -> ~/.ssh` hits `~/.ssh`), and the walk
        is marked incomplete. A final match may be a symlink (the caller checks its realpath). Every entry read counts
        against MAX_GLOB_SCAN and the call's GLOB_S deadline; hitting either sets state["complete"] False."""
        if self._glob_until is None:
            self._glob_until = min(time.monotonic() + GLOB_S, _DEADLINE[0] - GLOB_MARGIN_S)
        until = self._glob_until
        stack = [(base, 0)]
        seen = set()
        while stack:
            d, i = stack.pop()
            if (d, i) in seen:
                continue
            seen.add((d, i))
            seg = segs[i]
            last = i == len(segs) - 1
            if not GLOB_CHARS.intersection(seg):
                self._scanned += 1
                if self._scanned > MAX_GLOB_SCAN or time.monotonic() > until:
                    state["complete"] = False
                    self._glob_budget_hit = True
                    tick()   # WordOutOfTime / OutOfTime when those deadlines also elapsed
                    return
                p = os.path.join(d, seg)
                if last:
                    if os.path.lexists(p):
                        yield p, True
                elif os.path.isdir(p):
                    stack.append((p, i + 1))
                continue
            rec = seg == "**"
            rx = None if rec else seg_regex(seg)
            dot = seg.startswith(".")
            found, sub, links = [], [], []
            if rec and last and i > 0:
                found.append(d.rstrip("/") + "/")   # bash's `a/**` lists `a/` itself
            try:
                it = _scandir(d)
            except OSError:
                it = None
            if it is not None:
                try:
                    with it:
                        for e in it:   # reading can fail midway (EACCES on /proc/1/map_files): the shell sees no more
                            self._scanned += 1
                            if self._scanned > MAX_GLOB_SCAN or time.monotonic() > until:
                                state["complete"] = False
                                self._glob_budget_hit = True
                                tick()   # WordOutOfTime / OutOfTime when those deadlines also elapsed
                                return
                            name = e.name
                            if (name[:1] == "." and not dot) or (rx is not None and not rx.match(name)):
                                continue
                            p = os.path.join(d, name)
                            if last and not rec:
                                found.append(p)
                                continue
                            try:
                                if e.is_symlink():
                                    if last:
                                        found.append(p)
                                    elif e.is_dir():   # follows the link: only a link to a directory is one to enter
                                        state["complete"] = False
                                        links.append(p)
                                elif e.is_dir(follow_symlinks=False):
                                    if rec and last:
                                        found.append(p)
                                    sub.append((p, i if rec else i + 1))
                                elif rec and last:
                                    found.append(p)
                            except OSError:
                                continue
                except OSError:
                    pass
            for p in found:
                yield p, True
            for p in links:
                yield p, False
            if rec and not last:
                sub.insert(0, (d, i + 1))   # zero levels: popped first
            stack.extend(reversed(sub))

    def _glob_one(self, raw: str, pat: str):
        base = "/" if os.path.isabs(pat) else self.cwd
        segs = [x for x in pat.split("/") if x]
        state = {"complete": True}
        # Do not clear `_glob_budget_hit` here: brace alts share one word's sticky truncate flag
        # (see `glob()`). Setting True below / in `expand` still latches for check_command.
        n = links = 0
        if segs:
            for h, is_match in self.expand(base, segs, state):
                if not is_match:
                    links += 1
                    if links <= MAX_GLOB_HITS:
                        found = self.path(h)
                        if found:
                            return found
                    continue
                n += 1
                found = self.path(h)
                if found:
                    return found
                if n >= MAX_GLOB_HITS:
                    state["complete"] = False
                    # Hits bound is the same incomplete-walk case as GLOB_S / MAX_GLOB_SCAN: latch
                    # so check_command fails closed for walk-dependent secrets (`*`, `id_*`).
                    self._glob_budget_hit = True
                    break
        if n and state["complete"]:
            return None
        # No match, or a walk cut short: the pattern itself (so a bound never lets a word through unchecked).
        if os.path.isabs(pat):
            hit = self.policy.pattern_verdict(pat)
            return (hit, raw) if hit else None
        for base in self.cwds:
            hit = self.policy.pattern_verdict(pat, base.rstrip("/") + "/")
            if hit:
                return hit, raw
        return None

    def set_aside(self, raw: str):
        """Mark a glob word as deferred without spending WORD_S (first-pass cap exhausted, or a timed-out check).
        A second set-aside of the same word (deferred retry also timed out) fails closed."""
        if self._words.get(raw) is _SET_ASIDE:
            return   # already deferred this round (duplicate token or re-entry)
        n = self._aside_count.get(raw, 0) + 1
        self._aside_count[raw] = n
        if n > 1:
            raise GlobBudgetExceeded(raw)
        self._words[raw] = _SET_ASIDE
        if raw not in self.deferred:
            self.deferred.append(raw)

    def glob_pattern_only(self, raw: str):
        """Pattern check only (no filesystem walk): cheap first step of a set-aside retry. Inconclusive for broad
        globs (`id_*`, `*`) that need a walk to catch deny matches on disk — the deferred retry then walks or refuses."""
        if not raw or len(raw) > MAX_TOKEN or "\x00" in raw:
            return None
        for pat in expand_braces(expand_home(raw)):
            if os.path.isabs(pat):
                hit = self.policy.pattern_verdict(pat)
                if hit:
                    return hit, raw
                continue
            for base in self.cwds:
                hit = self.policy.pattern_verdict(pat, base.rstrip("/") + "/")
                if hit:
                    return hit, raw
        return None

    def word(self, raw: str, word_s=None, pattern_only: bool = False):
        """A word's (rule, shown) or None. With `word_s`, a glob word whose check runs longer than that is set aside in
        self.deferred (answering None for now), so one slow word cannot use up the time the words after it need.
        A set-aside is cached (`_SET_ASIDE`); a deferred retry clears it and, with `pattern_only`, skips the walk
        (caller then walks or fails closed when the pattern cannot decide). A second set-aside of the same word fails
        closed (`GlobBudgetExceeded`)."""
        if raw in self._words:
            cached = self._words[raw]
            if cached is not _SET_ASIDE:
                return cached
            if word_s is not None and not pattern_only:
                return None   # still first pass; already deferred
            del self._words[raw]
        tick()
        if not is_glob(raw):
            self._words[raw] = self.path(raw)
            return self._words[raw]
        if word_s is not None:
            _WORD_DEADLINE[0] = time.monotonic() + word_s
        try:
            res = self.glob_pattern_only(raw) if pattern_only else self.glob(raw)
        except WordOutOfTime:
            self.set_aside(raw)
            return None
        finally:
            _WORD_DEADLINE[0] = float("inf")
        self._words[raw] = res
        return res


# ---- Grep: ripgrep with --hidden over a root ------------------------------------------------------------------------
def _grep_glob_regex(alt: str, cross: bool, fold: bool):
    """A ripgrep `--glob` as a regex over a path relative to the search root (gitignore rules: no `/` but a trailing
    one matches a name at any depth, else it is anchored at the root). `cross` lets `*` cross `/` too (a superset)."""
    a = alt.rstrip("/") or alt
    if a.startswith("/"):
        a = a[1:]
    elif "/" not in a:
        a = "**/" + a
    ats = atoms(a.lower() if fold else a)
    if cross:
        ats = [(DSTAR, None) if k == STAR else (k, c) for k, c in ats]
    return to_regex(ats, fold)


class GrepGlob:
    """Which files under the root Grep's `glob` (and `type`) lets ripgrep read. Every plausible reading of the string
    counts (as one glob; split on whitespace; split on whitespace and commas outside braces), and a file is reached when
    ANY reading reaches it. Within a reading the globs act as ripgrep's overrides (checked against /usr/bin/rg 14.1.0,
    2026-11-04): the LAST glob that matches a path decides it (`-g '!.env' -g '*'` reads `.env`); a directory a `!`
    glob decides is not entered; a file a positive glob decides is read whatever the `type` (`-t ts -g 'src/**'` reads
    `src/.env`); a file no glob matches is skipped when the reading has a positive glob, and otherwise left to the
    `type` (so `!x` globs alone still combine with it). Positive globs are matched loosely (`*` may cross `/`, case
    folded on macOS, and a matched directory covers its files), `!` globs strictly (a trailing `/` matches directories
    only), so the doubt always falls on the side of reaching the file."""

    def __init__(self, g: str, fold: bool):
        ws = g.split()
        cs = [p for part in ws for p in (part.split(",") if "{" not in part else [part]) if p]
        readings = [[g]]
        for parts in (ws, cs):
            if parts and parts not in readings:
                readings.append(parts)
        self.positives = []
        self.readings = []
        for parts in readings:
            globs, has_pos = [], False
            for part in parts:
                negp = part.startswith("!")
                body = part[1:] if negp else part
                if not body:
                    continue
                for alt in expand_braces(body):
                    if negp:
                        dir_only = alt.endswith("/") and alt.rstrip("/") != ""
                        globs.append((True, _grep_glob_regex(alt, False, False), dir_only))
                    else:
                        has_pos = True
                        globs.append((False, _grep_glob_regex(alt, True, fold), False))
                        if alt not in self.positives:
                            self.positives.append(alt)
            self.readings.append((globs, has_pos))

    @staticmethod
    def _last(globs: list, parts: list, is_dir: bool):
        """The last glob that decides the path parts[:] (negative strictly on the path, positive on it or a parent):
        True for a negative, False for a positive, None when none matches."""
        path = "/".join(parts)
        for negp, rx, dir_only in reversed(globs):
            if negp:
                if (is_dir or not dir_only) and rx.fullmatch(path):
                    return True
            elif any(rx.fullmatch("/".join(parts[:i])) for i in range(1, len(parts) + 1)):
                return False
        return None

    def reaches(self, rel: str, type_ok=None) -> bool:
        parts = rel.split("/")
        for globs, has_pos in self.readings:
            if any(self._last(globs, parts[:k], True) for k in range(1, len(parts))):
                continue   # a `!` glob decides one of its directories: ripgrep never enters it
            last = self._last(globs, parts, False)
            if last is True:
                continue
            if last is False:
                return True   # a positive glob decides it: read whatever the type
            if has_pos:
                continue
            if type_ok is None or type_ok(rel):
                return True
        return False


def grep_walk(policy: Policy, roots: list, reach, deadline=None):
    """Breadth-first over roots[0] (its other forms name the same files): ((rule, path) of the first denied file the glob
    reaches, or None, truncated). Symlinks are not followed (ripgrep's default); VCS dirs and node_modules are skipped.
    `deadline` is shared by every root of one Grep call (default: WALK_S from now, inside the call's budget)."""
    if deadline is None:
        deadline = min(_DEADLINE[0] - 1.0, time.monotonic() + WALK_S)
    todo = [("", 0)]
    n, truncated, i = 0, False, 0
    while i < len(todo):
        rel, depth = todo[i]
        i += 1
        if time.monotonic() > deadline:
            return None, True
        try:
            it = os.scandir(os.path.join(roots[0], rel) if rel else roots[0])
        except OSError:
            continue
        try:
            with it:
                for e in it:   # reading can fail midway (EACCES): ripgrep cannot read the rest either
                    n += 1
                    if n > MAX_WALK_ENTRIES or (n % 256 == 0 and time.monotonic() > deadline):
                        return None, True
                    r = rel + "/" + e.name if rel else e.name
                    try:
                        is_dir = e.is_dir(follow_symlinks=False)
                    except OSError:
                        is_dir = False
                    if is_dir:
                        if e.name in WALK_SKIP:
                            continue
                        if depth + 1 > MAX_WALK_DEPTH:
                            truncated = True
                            continue
                        todo.append((r, depth + 1))
                        continue
                    for root in roots:
                        p = root.rstrip("/") + "/" + r
                        if policy.any_deny.fullmatch(p):
                            rule = policy.verdict(p)
                            if rule and reach(r):
                                return (rule, p), False
        except OSError:
            continue
    return None, truncated


# ripgrep's file types for Grep's `type`: the file names each one reads, copied from `rg --type-list` of ripgrep 14.1.0
# (2026-11-04; Ruby is `ruby`, not `rb`), plus `.env` and `*.env` in `sh`, which ripgrep 15.2 added (2026-11-06, Codex
# security review on PR 289). A type not here leaves the walk unfiltered (every file counts), which can only block more;
# a name here that ripgrep drops only makes the walk reach more. At run time the globs of an `rg` on PATH are added to a
# type's (rg_type_globs), so a newer ripgrep can only widen the filter, never narrow it.
RG_TYPES = {
    "py": ("*.py", "*.pyi"),
    "js": ("*.cjs", "*.js", "*.jsx", "*.mjs", "*.vue"),
    "ts": ("*.cts", "*.mts", "*.ts", "*.tsx"),
    "go": ("*.go",),
    "rust": ("*.rs",),
    "java": ("*.java", "*.jsp", "*.jspx", "*.properties"),
    "c": ("*.[chH]", "*.[chH].in", "*.cats"),
    "cpp": ("*.[ChH]", "*.[ChH].in", "*.[ch]pp", "*.[ch]pp.in", "*.[ch]xx", "*.[ch]xx.in", "*.cc", "*.cc.in", "*.hh",
            "*.hh.in", "*.inl"),
    "sh": ("*.bash", "*.bashrc", "*.csh", "*.cshrc", "*.ksh", "*.kshrc", "*.sh", "*.tcsh", "*.zsh", ".bash_login",
           ".bash_logout", ".bash_profile", ".bashrc", ".cshrc", ".kshrc", ".login", ".logout", ".profile", ".tcshrc",
           ".zlogin", ".zlogout", ".zprofile", ".zshenv", ".zshrc", "bash_login", "bash_logout", "bash_profile",
           "bashrc", "profile", "zlogin", "zlogout", "zprofile", "zshenv", "zshrc", ".env", "*.env"),
    "md": ("*.markdown", "*.md", "*.mdown", "*.mdwn", "*.mdx", "*.mkd", "*.mkdn"),
    "json": ("*.json", "*.sarif", "composer.lock"),
    "yaml": ("*.yaml", "*.yml"),
    "toml": ("*.toml", "Cargo.lock"),
    "ruby": ("*.gemspec", "*.rb", "*.rbw", ".irbrc", "Gemfile", "Rakefile", "config.ru"),
    "php": ("*.php", "*.php3", "*.php4", "*.php5", "*.php7", "*.php8", "*.pht", "*.phtml"),
    "swift": ("*.swift",),
    "kotlin": ("*.kt", "*.kts"),
    "html": ("*.ejs", "*.htm", "*.html"),
    "css": ("*.css", "*.scss"),
}


RG_LIST_S = 1.0   # `rg --type-list` time, inside BUDGET_S; past it (or on any failure) the static map stands alone
RG_LIST_MAX_BYTES = 65536   # a longer `rg --type-list` answer is ignored (14.1.0 prints about 9 KiB)
RG_LIST_MAX_GLOBS = 200     # so is one naming more globs for a type (the largest real type has a few dozen)


def _split_type_globs(s: str) -> list:
    """`rg --type-list` globs of one type: comma-separated, a comma inside `{...}` kept."""
    out, cur, depth = [], [], 0
    for ch in s:
        if ch == "{":
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
        if ch == "," and not depth:
            out.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    out.append("".join(cur).strip())
    return [g for g in out if g]


def rg_live_types() -> dict:
    """{type: [globs]} from `rg --type-list` of the rg on PATH (argv list, at most RG_LIST_S and never past the call's
    budget), or {} when there is no rg or it fails. Only ever added to the static map, so a bad answer cannot narrow."""
    try:
        rg = shutil.which("rg")
        left = _DEADLINE[0] - time.monotonic() - 2.0
        if not rg or left <= 0.05:
            return {}
        r = subprocess.run([rg, "--type-list"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=min(RG_LIST_S, left))
        if r.returncode != 0 or len(r.stdout) > RG_LIST_MAX_BYTES:
            return {}
        out = {}
        for line in r.stdout.decode("utf-8", "replace").splitlines():
            name, sep, rest = line.partition(":")
            if sep and name.strip():
                globs = _split_type_globs(rest)
                if len(globs) > RG_LIST_MAX_GLOBS:
                    return {}       # an rg that floods its answer is ignored whole: the static map stands alone
                out[name.strip()] = globs
        return out
    except Exception:
        return {}


def rg_type_globs(t: str, live=None):
    """The globs ripgrep's type `t` reads: the static map's, unioned with the live rg's (`live`, else rg_live_types()).
    None for a type the static map does not know (the walk is then unfiltered, whatever the live rg says)."""
    globs = RG_TYPES.get(t)
    if globs is None:
        return None
    if live is None:
        live = rg_live_types()
    out = list(globs)
    for g in live.get(t) or ():
        if g not in out:
            out.append(g)
    return out


def rg_type_filter(t: str, fold: bool, live=None):
    """A test on a path relative to the Grep root for a known ripgrep type (its base name against the type's globs;
    a glob holding `/` against the whole relative path too), or None for an unknown type."""
    globs = rg_type_globs(t, live)
    if globs is None:
        return None
    base_rx, path_rx = [], []
    for g in globs:
        for alt in expand_braces(g):
            (path_rx if "/" in alt else base_rx).append("(?:%s)" % fnmatch.translate(alt))
    try:
        flags = re.IGNORECASE if fold else 0
        brx = re.compile("|".join(base_rx), flags) if base_rx else None
        prx = re.compile("|".join(path_rx), flags) if path_rx else None
    except re.error:
        return None   # a glob this hook cannot read: filter nothing (blocks more, never less)

    def ok(rel):
        if brx is not None and brx.match(rel.rsplit("/", 1)[-1]):
            return True
        return bool(prx is not None and (prx.match(rel) or prx.match(rel.rsplit("/", 1)[-1])))
    return ok


def check_grep(ck: Checker, policy: Policy, ti: dict, cwd: str):
    """(rule, path, hint) when Grep (ripgrep --hidden) could read a denied file, else None."""
    raw = ti.get("path") if isinstance(ti.get("path"), str) and ti.get("path") else None
    narrow = "pass a narrower path"
    found = ck.path(raw or cwd)
    if found:
        return found + (narrow,)
    # Every root ripgrep might search, as concrete() gives a file (2026-11-06, Codex review on PR 289): the kernel
    # resolves `link/..` beside link's target (rg searches ~/.config/gh for `link/..` when link -> ~/.config/gh/subdir),
    # while a normalizing tool searches the normalized path. Each distinct directory is walked; any hit blocks.
    cands = concrete(expand_home(raw or cwd), cwd)
    g = ti.get("glob") if isinstance(ti.get("glob"), str) and ti.get("glob").strip() else None
    gg = GrepGlob(g, policy.fold) if g else None
    t = ti.get("type").strip() if isinstance(ti.get("type"), str) and ti.get("type").strip() else None
    tf = rg_type_filter(t, policy.fold) if t else None
    if t and tf is None:
        narrow += " (type %r is not one this hook maps to file names, so it narrows nothing here: use a glob that " \
                  "names the files instead, such as '*.<extension>')" % t

    def reach(rel):
        # ripgrep: a positive glob decides alone; `type` filters only the files no positive glob speaks for.
        if gg:
            return gg.reaches(rel, tf)
        return tf(rel) if tf is not None else True

    groups, unseen = [], []   # groups: [forms] per distinct directory (its realpath as key); unseen: missing roots
    for c in cands:
        if os.path.isdir(c):
            try:
                key = os.path.realpath(c)
            except (OSError, ValueError):
                key = c
            for grp in groups:
                if grp[0] == key:
                    break
            else:
                grp = [key, []]
                groups.append(grp)
            for form in (c, key):
                if form not in grp[1]:
                    grp[1].append(form)
        elif not os.path.exists(c):
            unseen.append(c)
        # else a file: ripgrep reads just it, and ck.path checked it
    deadline = min(_DEADLINE[0] - 1.0, time.monotonic() + WALK_S)   # one walk budget for every root
    for _, roots in groups:
        hit, truncated = grep_walk(policy, roots, reach, deadline)
        if hit:
            name = os.path.basename(hit[1])
            return hit + ("Grep reads hidden files; %s or a glob that leaves it out (e.g. '*.py', or '!%s')"
                          % (narrow, name),)
        if not truncated:
            continue   # the whole tree was seen: what the glob reaches is known, so its text proves nothing more
        for form in roots:
            anc = policy.anchor_under(form)
            if anc:
                return (anc[1], form, "this tree holds %s and is too big to check; %s (a project directory)"
                        % (anc[0], narrow))
        unseen.extend(roots)
    # A root is missing or its walk was cut short: the glob's text stands in for the files not seen.
    if gg:
        for root in unseen:
            base = root.rstrip("/") + "/"
            for alt in gg.positives:
                pat = alt.lstrip("/") if "/" in alt.rstrip("/") else "**/" + alt
                hit = policy.pattern_verdict(pat, base, dotfile=False)
                if hit:
                    return hit, os.path.join(root, g), "use a glob that cannot match it"
    return None


def shell_words(cmd: str) -> list:
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        toks = cmd.split()
    out = []
    for tok in toks[:MAX_TOKENS]:
        tok = tok.strip("`'\"").lstrip("<>")
        if not tok or len(tok) > MAX_TOKEN or not tok.strip("();<>|&"):
            continue
        out.append(tok)
        if "=" in tok:
            out.append(tok.split("=", 1)[1])
        if ":" in tok:
            out.extend(part for part in tok.split(":") if part)
    return out


def split_patch(text: str):
    """(shell text outside any patch, [header paths]) for a string holding `*** Begin Patch` blocks."""
    outside, paths, pos = [], [], 0
    for m in PATCH_BEGIN.finditer(text):
        if m.start() < pos:
            continue
        outside.append(text[pos:m.start()])
        end = PATCH_END.search(text, m.end())
        stop = end.end() if end else len(text)
        paths.extend(PATCH_HEADER.findall(text[m.start():stop]))
        pos = stop
    outside.append(text[pos:])
    return "\n".join(outside), paths


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            for s in strings(v):
                yield s
    elif isinstance(obj, list):
        for v in obj:
            for s in strings(v):
                yield s


def check_command(ck: Checker, cmd: str, shell_tool: bool = True):
    """Patch headers, then every literal word (cheap), then the glob words without `**` (a bounded walk, then their
    pattern), then those with `**` (the costly ones), each glob word within WORD_S under a shared FIRST_PASS_S cap;
    last, set-aside words are retried: pattern-only first, then a real walk with remaining budget when the pattern
    cannot decide. A second timeout on one word, an OutOfTime while glob words remain, a set-aside word that still
    needs a walk with no budget left, a deferred walk truncated by GLOB_S / MAX_GLOB_SCAN, or a first-pass
    glob truncated the same way (relative/cwd or absolute/tilde-expanded; expand ticks on truncate; absolute
    deep globs keep the pattern fallback only when the shared budget did not truncate), fails closed
    (`GlobBudgetExceeded`) instead of allowing.

    For a shell tool (`shell_tool`, the default) every word of the text is analyzed, `*** Begin Patch` regions included:
    the shell runs them (2026-11-06, Cursor review on PR 289: `*** Begin Patch\\ncat ~/.ssh/id_rsa\\n*** End Patch`
    is three commands to Bash), and their headers are checked as well. Only a genuine patch payload (a non-shell tool
    such as Codex `apply_patch`) has its patch regions left out of the shell words, so a patch body that mentions
    `.env` passes there."""
    if PATCH_BEGIN.search(cmd):
        rest, headers = split_patch(cmd)
        shell = cmd if shell_tool else rest
    else:
        shell, headers = cmd, []
    for p in headers:
        found = ck.path(p)
        if found:
            return found
    words = shell_words(shell)
    globs = []
    for w in words:
        if is_glob(w):
            globs.append(w)
            continue
        found = ck.word(w)
        if found:
            return found
    globs.sort(key=lambda w: "**" in w)   # stable: cheap glob words first, in command order
    first_until = time.monotonic() + FIRST_PASS_S
    try:
        for w in globs:
            rem = first_until - time.monotonic()
            if rem <= 0:
                ck.set_aside(w)
                continue
            found = ck.word(w, min(WORD_S, rem))
            if found:
                return found
            # First-pass walk truncated by GLOB_S / MAX_GLOB_SCAN: expand marks _glob_budget_hit and may
            # fall back to an inconclusive pattern check — refuse for relative/cwd and absolute/tilde alike,
            # never cache-allow walk-dependent secrets (`id_*`, `$ABS/id_*`, `*`). Pattern fallback for
            # absolute deep globs remains only when the shared budget did not truncate (and when the
            # pattern itself denies: `if found` above still returns a hit).
            if ck._glob_budget_hit:
                raise GlobBudgetExceeded(w)
        while ck.deferred:
            w = ck.deferred.pop(0)
            # Cheap pattern check first (*.key, ~/.ssh/id_*, …). Broad globs (id_*, *) often return None here.
            found = ck.word(w, WORD_S, pattern_only=True)
            if found:
                return found
            # Pattern alone cannot decide: never allow a walk-dependent secret glob after set-aside. Retry with a
            # real filesystem walk under the remaining overall budget, or fail closed.
            rem = _DEADLINE[0] - time.monotonic()
            if rem <= 0:
                raise GlobBudgetExceeded(w)
            if w in ck._words:
                del ck._words[w]   # drop the pattern-only None cache so word() walks
            found = ck.word(w, min(WORD_S, rem), pattern_only=False)
            if found:
                return found
            # Walk timed out: re-enters set_aside and, with aside_count already 1, raises GlobBudgetExceeded.
            # Walk truncated by GLOB_S / MAX_GLOB_SCAN (e.g. completing dummies already burned GLOB_S while
            # FIRST_PASS_S == GLOB_S): expand ticks, but when WORD/DEADLINE still remain the incomplete walk
            # used to fall through to an inconclusive pattern check and ALLOW — refuse for relative/cwd and
            # absolute/tilde alike (same as first-pass). Pattern fallback for absolute deep globs remains
            # only when the shared budget did not truncate; a deny from pattern_verdict still returns above.
            if ck._glob_budget_hit:
                raise GlobBudgetExceeded(w)
            # Else the walk completed with no hit (verified miss).
    except OutOfTime:
        # Overall budget ended with Bash glob words still unresolved: fail closed (secret paths may remain).
        raise GlobBudgetExceeded(ck.deferred[0] if ck.deferred else (globs[-1] if globs else ""))
    return None


def patch_payload(tool: str, text: str) -> bool:
    """True when `text` is a genuine Codex apply_patch payload, whose `*** Begin Patch` regions are patch data and not
    shell: the tool is a patch tool, or a tool that is not a shell holds patch blocks and nothing else (2026-11-06).
    A shell tool's text is never one: the shell runs every line of it."""
    if tool in SHELL_TOOLS:
        return False
    if tool in PATCH_TOOLS:
        return True
    return bool(PATCH_BEGIN.search(text)) and not split_patch(text)[0].strip()


def check(payload: dict, policy: Policy):
    """(tool, rule, path) or (tool, rule, path, hint) when the call must be blocked, else None."""
    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input")
    if tool in UNGATED or not isinstance(ti, dict):
        return None
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not os.path.isabs(cwd):
        cwd = os.getcwd()
    ck = Checker(policy, cwd)
    if tool in FILE_TOOLS:
        for key in FILE_TOOLS[tool]:
            v = ti.get(key)
            if isinstance(v, str):
                found = ck.path(v)
                if found:
                    return (tool,) + found
        return None
    if tool == "Grep":
        found = check_grep(ck, policy, ti, cwd)
        return (tool,) + found if found else None
    # Bash, and any other tool (Codex `apply_patch`, `shell`, `exec_command`): its command and patch headers.
    cmd = ti.get("command")
    parts = []
    if isinstance(cmd, str):
        parts = [cmd]
    elif isinstance(cmd, list):
        parts = [p for p in cmd if isinstance(p, str)]
    for part in parts:
        found = check_command(ck, part, shell_tool=not patch_payload(tool, part))
        if found:
            return (tool,) + found
    for s in strings({k: v for k, v in ti.items() if k != "command"}):
        if PATCH_BEGIN.search(s):
            for p in split_patch(s)[1]:
                found = ck.path(p)
                if found:
                    return (tool,) + found
    return None


def notice(msg: str) -> None:
    try:
        sys.stderr.write("secret-read-gate: %s; allowing (fail open)\n" % msg)
    except Exception:
        pass


def main() -> int:
    if os.environ.get("SECRET_DENY_OFF") == "1":
        return 0
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            raise ValueError("not an object")
    except Exception:
        notice("unreadable hook input")
        return 0
    try:
        policy = load_policy()
    except Exception as e:
        notice("policy %s unusable (%s)" % (policy_path(), type(e).__name__))
        return 0
    _DEADLINE[0] = time.monotonic() + BUDGET_S
    try:
        hit = check(payload, policy)
    except GlobBudgetExceeded as e:
        tool = payload.get("tool_name") or "Bash"
        shown = e.word if len(e.word) <= 200 else e.word[:200] + "..."
        sys.stderr.write(
            "secret-read-gate: blocked %s on %s: glob analysis budget exceeded (fail closed); see %s\n"
            % (tool, shown.replace("\n", " ") or "(glob)", DOC))
        return 2
    except Exception as e:
        notice("internal error (%s: %s)" % (type(e).__name__, str(e)[:120]))
        return 0
    if not hit:
        return 0
    tool, rule, path = hit[:3]
    hint = "; " + hit[3] if len(hit) > 3 and hit[3] else ""
    shown = path if len(path) <= 200 else path[:200] + "..."
    sys.stderr.write("secret-read-gate: blocked %s on %s: deny rule %r in config/secret-deny.toml%s; see %s\n"
                     % (tool, shown.replace("\n", " "), rule, hint.replace("\n", " "), DOC))
    return 2


if __name__ == "__main__":
    try:
        code = main()
    except BaseException:
        code = 0
    sys.exit(code)
