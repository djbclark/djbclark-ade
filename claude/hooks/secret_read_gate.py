#!/usr/bin/env python3
"""PreToolUse: block a tool call that would read or write a secret file (2026-11-04, issue #284 item 2).

The policy is config/secret-deny.toml, rendered by bin/render-secret-deny into config/secret_deny_policy.json, which
this hook reads (found from this file's realpath: <repo>/claude/hooks/ -> <repo>/config/; SECRET_DENY_POLICY overrides
it). docs/secret-deny.md says what is enforced where and the honest limits.

What it inspects: Read/Edit/MultiEdit/Write/NotebookEdit `file_path`/`notebook_path`; Grep `path` and `glob`; a Bash
`command` (shlex tokens, `<file`, `--x=file`, `a:b` parts, `~`/`~user`/`$HOME`/`${HOME}`, glob tokens); Codex
`apply_patch` file headers (`*** Add|Update|Delete File:`, `*** Move to:`) in any string of a non-file tool's input. Glob
is not gated (it returns names only). Each candidate path is evaluated as given, absolutized against the payload's `cwd`,
and as its realpath, separately: the call is blocked when ANY candidate matches a deny pattern and no allow pattern
matches that same candidate. A pattern ending in `/**` also denies its directory (`grep -r x ~/.ssh`, `tar c ~/.ssh`).

A Bash glob token (`*`, `?`, `[...]` or `{a,b}`) is expanded against the filesystem (lazily, at most MAX_GLOB_HITS
matches, inside the time budget) and each match checked as a path. When nothing matches, the pattern itself is checked:
it blocks when some path could match it and a deny pattern and no allow pattern, under two rules that keep code and
regexes from tripping it: the hidden-file rule (a wildcard never consumes a leading `.`) and pinning (the token's
wildcards may not stand in for a deny pattern's literal text). So `cat ~/.ssh/id_*` and `find . -name '*.key'` block,
while `echo *` and `grep 'a.*'` pass.

Grep (2026-11-04): Claude's Grep runs ripgrep with `--hidden`, so it reads dotfiles and descends into `~/.ssh`. Its root
(`path`, else the cwd) is walked breadth-first (bounded: depth, entries, time; VCS dirs and node_modules skipped) and the
call blocks when a denied file under it is one the `glob` lets through, naming the file and how to leave it out. When the
walk hits a bound it fails open, except for a root that contains a home-level deny (`~`, `/home`, `/`), which blocks.
`.gitignore` is not consulted, so a gitignored `.env` still blocks a whole-project Grep (the price of not parsing ignore
files). The glob is also checked as a pattern (pinning, no hidden-file rule): `glob: ".env*"` blocks, `"*.py"` passes.

Block: exit 2 with one line on stderr naming the rule and docs/secret-deny.md (Claude and Codex both block on 2).
Fail open: bad stdin, a missing or corrupt policy, or any exception exits 0 with a short stderr notice, so a bug never
turns into a block on every Read. SECRET_DENY_OFF=1 (operator's environment) turns it off.

Runs under Python 3.9 (macOS /usr/bin/python3): no tomllib, no `match`, no runtime `X | Y` types.
"""
from __future__ import annotations

import glob as globmod
import json
import os
import re
import shlex
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
MAX_TOKEN = 4096        # PATH_MAX; a longer token is a heredoc body or data, not a path
MAX_TOKENS = 20000
MAX_GLOB_HITS = 500
MAX_BRACE = 64
MAX_STATES = 200000     # product-automaton budget; exhausting it counts as an overlap (blocks)
BUDGET_S = 8.0          # whole-call analysis budget; past it the hook fails open (the settings timeout is 15 s)
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


_DEADLINE = [float("inf")]


def tick() -> None:
    if time.monotonic() > _DEADLINE[0]:
        raise OutOfTime("analysis took longer than %.0f s" % BUDGET_S)


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


def token_text(ats: list):
    """A token's literals with its `*` atoms dropped and each `?` as a break, or None when it holds `**` (whose `/`
    may be either). Under pinning every literal run of a deny pattern is spelled by token literals with only empty
    `*` matches between them, so a run absent from this text rules the overlap out."""
    out = []
    for kind, c in ats:
        if kind == LIT:
            out.append(c)
        elif kind == QM:
            out.append("\x00")
        elif kind != STAR:
            return None
    return "".join(out)


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
        text = token_text(ats)
        allows = [r.atoms for r in self.allow]
        for r in self.deny:
            if not (lead.startswith(r.prefix) or r.prefix.startswith(lead)):
                continue   # their fixed leading text differs: no common path
            if text is not None and not all(run in text for run in r.runs):
                continue   # the token does not spell this rule's literal text (pinning, see nonempty)
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
    full = os.path.normpath(os.path.join(cwd, path))
    out.append(full)
    try:
        out.append(os.path.realpath(full))
    except (OSError, ValueError):
        pass
    seen = []
    for p in out:
        if p not in seen:
            seen.append(p)
    return seen


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
        for pat in expand_braces(expand_home(raw)):
            found = self._glob_one(raw, pat)
            if found:
                return found
        return None

    def _glob_one(self, raw: str, pat: str):
        full = pat if os.path.isabs(pat) else os.path.join(globmod.escape(self.cwd), pat)
        n = 0
        for h in globmod.iglob(full):   # lazy: a huge expansion (`/*/*/*/*/*/*`) stays inside the budget
            tick()
            n += 1
            found = self.path(h)
            if found:
                return found
            if n >= MAX_GLOB_HITS:
                break
        if n:
            return None
        if os.path.isabs(pat):
            hit = self.policy.pattern_verdict(pat)
            return (hit, raw) if hit else None
        for base in self.cwds:
            hit = self.policy.pattern_verdict(pat, base.rstrip("/") + "/")
            if hit:
                return hit, raw
        return None

    def word(self, raw: str):
        if raw not in self._words:
            tick()
            self._words[raw] = self.glob(raw) if is_glob(raw) else self.path(raw)
        return self._words[raw]


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


def _rel_hits(rx, rel: str) -> bool:
    """The glob matches the file or one of its directories below the root (a matched directory covers its files)."""
    parts = rel.split("/")
    return any(rx.fullmatch("/".join(parts[:i])) for i in range(1, len(parts) + 1))


class GrepGlob:
    """Which files under the root Grep's `glob` lets ripgrep read. Every plausible reading of the string counts (as one
    glob; split on whitespace; split on whitespace and commas outside braces), and a file is reached when ANY reading
    reaches it: positive globs are matched loosely (`*` may cross `/`, case folded on macOS), `!` exclusions strictly,
    so the doubt always falls on the side of reaching the file."""

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
            pos, neg = [], []
            for part in parts:
                negp = part.startswith("!")
                body = part[1:] if negp else part
                if not body:
                    continue
                for alt in expand_braces(body):
                    if negp:
                        neg.append(_grep_glob_regex(alt, False, False))
                    else:
                        pos.append(_grep_glob_regex(alt, True, fold))
                        if alt not in self.positives:
                            self.positives.append(alt)
            self.readings.append((pos, neg))

    def reaches(self, rel: str) -> bool:
        for pos, neg in self.readings:
            if pos and not any(_rel_hits(rx, rel) for rx in pos):
                continue
            if any(_rel_hits(rx, rel) for rx in neg):
                continue
            return True
        return False


def grep_walk(policy: Policy, roots: list, reach):
    """Breadth-first over roots[0] (its other forms name the same files): ((rule, path) of the first denied file the glob
    reaches, or None, truncated). Symlinks are not followed (ripgrep's default); VCS dirs and node_modules are skipped."""
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
        with it:
            for e in it:
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
    return None, truncated


def check_grep(ck: Checker, policy: Policy, ti: dict, cwd: str):
    """(rule, path, hint) when Grep (ripgrep --hidden) could read a denied file, else None."""
    raw = ti.get("path") if isinstance(ti.get("path"), str) and ti.get("path") else None
    narrow = "pass a narrower path"
    found = ck.path(raw or cwd)
    if found:
        return found + (narrow,)
    root = os.path.normpath(os.path.join(cwd, expand_home(raw or cwd)))
    g = ti.get("glob") if isinstance(ti.get("glob"), str) and ti.get("glob").strip() else None
    gg = GrepGlob(g, policy.fold) if g else None
    if os.path.isdir(root):
        roots = [root]
        try:
            real = os.path.realpath(root)
            if real != root:
                roots.append(real)
        except (OSError, ValueError):
            pass
        hit, truncated = grep_walk(policy, roots, gg.reaches if gg else (lambda rel: True))
        if hit:
            name = os.path.basename(hit[1])
            return hit + ("Grep reads hidden files; %s or a glob that leaves it out (e.g. '*.py', or '!%s')"
                          % (narrow, name),)
        if truncated:
            for form in roots:
                anc = policy.anchor_under(form)
                if anc:
                    return (anc[1], form, "this tree holds %s and is too big to check; %s (a project directory)"
                            % (anc[0], narrow))
    elif os.path.exists(root):
        return None   # a file: ripgrep reads just it, and ck.path checked it
    if gg:
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


def check_command(ck: Checker, cmd: str):
    shell, headers = split_patch(cmd) if PATCH_BEGIN.search(cmd) else (cmd, [])
    for p in headers:
        found = ck.path(p)
        if found:
            return found
    for w in shell_words(shell):
        found = ck.word(w)
        if found:
            return found
    return None


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
    if isinstance(cmd, list):
        for part in cmd:
            if isinstance(part, str):
                found = check_command(ck, part)
                if found:
                    return (tool,) + found
    elif isinstance(cmd, str):
        found = check_command(ck, cmd)
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
