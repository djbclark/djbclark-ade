#!/usr/bin/env python3
"""PreToolUse (Bash): deny a write that CFEngine upstream would see (2026-11-12, port of the shell gate).

Operator ruling (djbclark, 2026-11-12): "Re-enable, CFEngine-only". Upstream closed all 26 PRs and rejected all 26
Jira tickets of this effort in August 2026 and asked for one bug and one small PR with a human in the loop, so
anything cfengine/NorthernTechHQ sees is sent by djbclark (cfengine-all/AGENTS.md, "Upstream contributions -
standing rules"). This hook replaces ~/.claude/hooks/upstream_review_gate.sh, which was never versioned, had not
been registered in any settings file since about 2026-08-24, and had two gaps (below).

Gated targets, and only these (every other third-party repo is allowed: agents file upstream issues elsewhere
under a separate rule):
  * GitHub owners `cfengine` and `NorthernTechHQ` (any repo, any case): `gh` writes and `git push`.
  * A mutating request to `*.atlassian.net` (Jira): curl/wget/httpie/xh with -X POST|PUT|PATCH|DELETE, -d/--data*/
    --json/-F/-T (a `-G` request with --data-urlencode is a GET and passes), plus a Composio Jira write (a Bash
    `composio ... jira ... create|update|...` command, or a Composio MCP tool call carrying a JIRA_<WRITE> slug).

Reads are never gated (`gh pr view`, `gh api` GETs, `gh repo fork`, anonymous Jira GETs, `git fetch`).

How the target of a `gh` write is found (the shell gate read only -R and the cwd's remotes):
  1. Explicit: -R/--repo (also `HOST/OWNER/REPO`, a URL), `GH_REPO=`, a github.com URL positional (`gh pr comment
     <url>`), an OWNER/NAME positional naming a gated owner (`gh issue transfer 5 cfengine/core`), `--owner`, and for
     `gh api` the endpoint (`repos/OWNER/NAME/...`, `/repos/...`, `orgs/OWNER/...`, a full api.github.com URL). An
     explicit target decides: ours -> allowed, gated -> denied.
  2. No explicit target (`gh pr create`, `gh api repos/{owner}/{repo}/...`, `repositories/ID`): the working
     directory's remotes (after any `cd` earlier in the command). Any remote of a gated owner denies, since gh
     defaults to the parent of a fork. Pass `-R djbclark/<repo>` to say the fork is meant.
  3. `gh api graphql`: only a mutation is a write; it is denied when the owner appears anywhere in the command or in
     a `-F query=@file`/`--input` file it reads, or when it names no repo (node IDs) and the cwd is a gated fork.
Write detection: a verb outside the read set in a repo-scoped group (`gh pr|issue|release|repo|label|workflow|
run|secret|variable|project|ruleset|cache ...`: create edit merge ready review comment close reopen delete lock
unlock transfer pin unpin update-branch develop revert rerun cancel run enable disable set sync archive unarchive
rename upload ...), and for `gh api` a non-GET -X/--method or, with no -X, any of -f/-F/--field/--raw-field/--input
(gh sends those as a POST; with an explicit `-X GET` they are query parameters and it is a read).

`git push`: the remote (named, or the URL, or `--repo`, or the branch's pushRemote/remote.pushDefault/
branch.<b>.remote/origin when none is given) is resolved with `git -C <dir> remote get-url --push --all`; a URL on
github.com owned by a gated owner denies. A libntech worktree with origin = NorthernTechHQ/libntech cannot `git
push` bare; `git push fork ...` passes. `git push -n/--dry-run` passes.

Parsing: shlex over the command (`;`, `&&`, `||`, `|`, `&`, newlines, parentheses and backticks separate segments;
`cd` updates the directory for the later segments; `$( )`/backtick bodies, `bash -c STR`, `eval ...` and heredocs
fed to a shell are analysed again; wrappers such as env, sudo, timeout, xargs, nohup, rtk and bg are looked
through; heredoc bodies fed to cat/git/gh/tee are data). Any gated write in any segment denies. A command shlex
cannot parse is split on the shell operators and whitespace instead, so a stray apostrophe never lets a gated write
through. Fails closed only for a gated target: unrelated commands, bad stdin and any internal error exit 0 silently.

Known limits (honest): a script or `just` recipe that runs gh/git itself is not seen; a repo-ID API path
(`repositories/N`) is judged by the cwd; a fork with only an `origin` remote (parent known only to the GitHub API) is
not detected for a bare `gh pr create` (no network call is made); `jj git push` and `ssh host gh ...` are not parsed;
Jira on `api.atlassian.com` is not matched.

Block: stdout JSON permissionDecision "deny" with the reason, exit 0 (the form secret_read_gate and bash_habits_gate
use). Escape hatch for the operator, in the Claude environment: UPSTREAM_REVIEW_GATE_OFF=1 (an assignment inside the
command is not read). Runs under Python 3.9 (macOS /usr/bin/python3).
"""
from __future__ import annotations

import json
import os
import signal
import re
import shlex
import subprocess
import sys
from functools import lru_cache

GATED_OWNERS = frozenset({"cfengine", "northerntechhq"})
GATED_TEXT = re.compile(r"(?i)(?<![\w.-])(cfengine|northerntechhq)(?![\w-]|\.\w)")
MAX_DEPTH = 5
GIT_TIMEOUT_S = 5
MAX_FILE = 262144
MAX_SHLEX = 100000
MAX_DELIMS = 20
BUDGET_S = 10

SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh", "fish"})
WRAPPERS = frozenset({
    "env", "command", "exec", "time", "nice", "ionice", "nohup", "setsid", "builtin", "sudo", "doas", "timeout",
    "gtimeout", "xargs", "stdbuf", "caffeinate", "script", "watch", "rtk", "bg", "ts", "chronic", "parallel",
    "!", "{", "secretspec", "sudo-secretspec", "direnv", "op", "uv", "uvx", "npx", "mise", "flock",
    "taskpolicy", "arch",
})
HTTP_TOOLS = frozenset({"curl", "wget", "http", "https", "xh", "xhs"})
INTERESTING = frozenset({"gh", "git", "cd", "pushd", "eval"}) | HTTP_TOOLS | SHELLS
ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
SHELLISH = re.compile(r"(?<![\w.-])(bash|sh|zsh|dash|ksh|eval|source|python3?|node|perl|ruby|ssh|xargs)(?!\w)")
HEREDOC_DELIM = re.compile(r"-?[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
PUNCT = ";&|()<>`\n"

# gh groups that act on a repository, and the verbs in them that only read. Any other verb is a write.
GH_GROUPS = frozenset({"pr", "issue", "release", "repo", "label", "workflow", "run", "secret", "variable",
                       "project", "ruleset", "cache", "discussion", "agent-task"})
GH_READ_VERBS = frozenset({
    "view", "list", "ls", "status", "diff", "checks", "checkout", "co", "clone", "fork", "browse", "watch",
    "download", "get", "field-list", "item-list", "search", "verify", "verify-asset", "check", "help",
    "credits", "garden", "set-default",
})
# `gh repo deploy-key add`, `gh repo autolink create`: the verb is a namespace, the action is the next word
GH_NESTED = frozenset({"deploy-key", "autolink", "gitignore", "license"})
GH_VALUE_LONG = frozenset({
    "--repo", "--body", "--title", "--base", "--head", "--header", "--hostname", "--field", "--raw-field",
    "--input", "--method", "--jq", "--template", "--cache", "--body-file", "--notes", "--notes-file", "--tag",
    "--target", "--assignee", "--label", "--milestone", "--project", "--reviewer", "--json", "--state",
    "--author", "--search", "--limit", "--owner", "--discussion-category", "--subject", "--ref", "--branch",
    "--commit-message", "--subject-line", "--match-head-commit", "--description", "--homepage", "--name",
    "--color", "--template-file", "--app", "--org", "--env", "--visibility", "--remote", "--source", "--reason",
    "--app", "--user", "--found-in", "--env-file", "--title", "--editor", "--add-label", "--remove-label",
    "--add-assignee", "--remove-assignee", "--add-reviewer", "--remove-reviewer", "--add-project",
    "--remove-project", "--add-milestone", "--remove-milestone", "--format", "--field", "--preview",
})
GH_VALUE_SHORT = frozenset("RbtBHFfXq")   # the rest are booleans in some verbs (`pr merge -s URL`)

WRITE_WORDS = re.compile(r"(?i)(?<![a-z])(create|update|add|comment|transition|delete|edit|assign|remove|link|move)(?![a-z])")


@lru_cache(maxsize=32)
def mentions_gated(text: str) -> bool:
    return bool(GATED_TEXT.search(text))


@lru_cache(maxsize=32)
def has_mutation(text: str) -> bool:
    return bool(re.search(r"(?i)\bmutation\b", text))


class Finding(Exception):
    """A gated write: the message is the deny reason."""


def deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    sys.exit(0)


def reason_for(what: str, target: str) -> str:
    what = re.sub(r"(?<=//)[^/@\s]+@", "", what)       # a remote URL may carry a token as userinfo
    target = re.sub(r"(?<=//)[^/@\s]+@", "", target)
    return ("Upstream review gate: %s would write to CFEngine upstream (%s). Upstream accepts exactly what djbclark "
            "sends: show djbclark the exact text (title/body/payload) and let djbclark run it, or have djbclark lift "
            "the gate (UPSTREAM_REVIEW_GATE_OFF=1 in the Claude environment). Reads are not blocked; the forks "
            "(djbclark/core, djbclark/libntech) are the destination for everything else: pass -R djbclark/<repo> "
            "or `git push fork ...`. Rules: cfengine-all/AGENTS.md, \"Upstream contributions - standing rules\"."
            % (what, target))


# ---- parsing --------------------------------------------------------------------------------------------------


def tokenize(text: str):
    """shlex words with the shell operators as their own tokens, or None when the quoting is unbalanced."""
    if len(text) > MAX_SHLEX:                           # shlex is quadratic on a huge word
        return None
    lex = shlex.shlex(text.replace("\\\n", " "), posix=True, punctuation_chars=PUNCT)
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        return list(lex)
    except ValueError:
        return None


def is_boundary(tok: str) -> bool:
    return bool(tok) and (any(c in ";|()`\n" for c in tok) or set(tok) == {"&"})


def is_redirect(tok: str) -> bool:
    return bool(tok) and all(c in "<>&" for c in tok) and ("<" in tok or ">" in tok)


def lenient_segments(text: str):
    """Split on the shell operators and whitespace, redirections dropped; used when shlex cannot parse."""
    out = []
    for piece in re.split(r"[;&|()`\n]+", text.replace("\\\n", " ")):
        words = []
        skip_next = False
        for w in piece.split():
            if skip_next:
                skip_next = False
                continue
            m = re.match(r"^\d?(&>|[<>]+&?)(.*)$", w)
            if m:
                skip_next = not m.group(2)
                continue
            w = w.strip("'\"")
            if w:
                words.append(w)
        if words:
            out.append(words)
    return out


def segments(text: str):
    """The command text as a list of word lists (one per simple command) with "(" / ")" markers for subshells,
    `$( )` and backticks. `$(which gh) pr ...` becomes ["gh", "pr", ...]. Files after `<` go to REDIR_IN."""
    toks = tokenize(text)
    if toks is None:
        return lenient_segments(text)
    out = []
    cur = []
    skip = None
    pending = None
    in_bt = False
    sub_stack = []

    def flush():
        nonlocal cur
        if cur:
            out.append(cur)
        cur = []

    for tok in toks:
        if skip is not None:                            # the file or fd after a redirection
            if skip == "<":
                REDIR_IN.append(tok)
            skip = None
            continue
        if is_boundary(tok) and set(tok) <= set(PUNCT):
            for c in tok:
                if c in ";|&\n":
                    flush()
                    pending = None
                elif c == "(":
                    if cur and cur[-1].endswith("$"):
                        cur[-1] = cur[-1][:-1]
                        if not cur[-1]:
                            cur.pop()
                        sub_stack.append(True)
                    else:
                        sub_stack.append(False)
                    flush()
                    out.append("(")
                    pending = None
                elif c == ")":
                    flush()
                    out.append(")")
                    was_sub = sub_stack.pop() if sub_stack else False
                    pending = None
                    inner = _last_words(out)
                    if was_sub and inner and base(inner[-1]) in ("gh", "git"):
                        pending = base(inner[-1])
                elif c == "`":
                    flush()
                    if in_bt:
                        out.append(")")
                        inner = _last_words(out)
                        pending = base(inner[-1]) if inner and base(inner[-1]) in ("gh", "git") else None
                    else:
                        out.append("(")
                        pending = None
                    in_bt = not in_bt
        elif is_redirect(tok):
            skip = "<" if tok == "<" else ">"
            if len(cur) > 0 and len(cur[-1]) == 1 and cur[-1].isdigit():
                cur.pop()                                # the fd of `2>&1` or `2>/dev/null`
        else:
            if pending and not cur:
                cur = [pending]
            pending = None
            cur.append(tok)
    flush()
    return out


def _last_words(out):
    for item in reversed(out):
        if isinstance(item, list):
            return item
        if item == "(":
            return None
    return None


def split_heredocs(text: str):
    """(text with heredoc bodies and comments removed, bodies fed to a shell-like consumer, every body)."""
    lines = text.split("\n")
    out = []
    kept = []
    all_bodies = []
    stack = []
    in_s = in_d = False
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        delims = []
        j = 0
        n = len(line)
        while j < n:
            c = line[j]
            if in_s:
                if c == "'":
                    in_s = False
            elif c == "$" and line.startswith("$(", j) and not line.startswith("$((", j):
                stack.append((in_d, 1))                  # `"$(cat <<EOF ... )"`: unquoted inside the substitution
                in_d = False
                j += 1
            elif stack and not in_d and c == "(":
                stack[-1] = (stack[-1][0], stack[-1][1] + 1)
            elif stack and not in_d and c == ")":
                depth_in = stack[-1][1] - 1
                if depth_in == 0:
                    in_d = stack.pop()[0]
                else:
                    stack[-1] = (stack[-1][0], depth_in)
            elif in_d:
                if c == "\\":
                    j += 1
                elif c == '"':
                    in_d = False
            elif c == "\\":
                j += 1
            elif c == "'":
                in_s = True
            elif c == '"':
                in_d = True
            elif c == "#" and (j == 0 or line[j - 1] in " \t;|&("):
                out[-1] = line[:j]                       # a shell comment is not part of the command
                break
            elif line.startswith("<<", j) and not line.startswith("<<<", j) and (j == 0 or line[j - 1] != "<"):
                m = HEREDOC_DELIM.match(line, j + 2)
                if m:
                    if len(delims) < MAX_DELIMS:
                        delims.append((m.group(2), line.startswith("<<-", j)))
                    j = m.end() - 1
            j += 1
        shellish = bool(delims) and bool(SHELLISH.search(line))
        for delim, dash in delims:
            body = []
            while i < len(lines):
                cand = lines[i]
                i += 1
                if (cand.strip("\t") if dash else cand).rstrip("\r") == delim:
                    break
                body.append(cand)
            all_bodies.append("\n".join(body))
            if shellish:
                kept.append("\n".join(body))
    return "\n".join(out), kept, all_bodies


def base(word: str) -> str:
    return os.path.basename(word)


def resolve_dir(path: str, cur: str) -> str:
    home = os.path.expanduser("~")
    path = path.replace("${HOME}", home).replace("$HOME", home)
    if not path or "$" in path or "`" in path:
        return cur
    p = os.path.expanduser(path)
    if not os.path.isabs(p):
        p = os.path.join(cur, p)
    return os.path.normpath(p)


# ---- git ------------------------------------------------------------------------------------------------------

_GIT_CACHE = {}
REDIR_IN = []      # files read by `< file` redirections of the command
DATA = []          # every heredoc body of the command: stdin for `gh api graphql -F query=@-`


def git(dirpath: str, *args: str, gitdir=None):
    """(returncode, stdout) of `git -C dirpath args` (or --git-dir), or (127, "") when git is unusable."""
    key = (dirpath, gitdir) + args
    if key in _GIT_CACHE:
        return _GIT_CACHE[key]
    res = (127, "")
    if os.path.isdir(dirpath):
        try:
            env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
            argv = ["git", "--git-dir", gitdir] if gitdir else ["git", "-C", dirpath]
            r = subprocess.run(argv + list(args), capture_output=True, text=True, cwd=dirpath,
                               timeout=GIT_TIMEOUT_S, env=env)
            res = (r.returncode, r.stdout)
        except (OSError, subprocess.SubprocessError):
            res = (127, "")
    _GIT_CACHE[key] = res
    return res


def github_owner(url: str):
    """(owner, name) of a github.com URL (https, ssh, scp-like), else None."""
    m = re.search(r"(?i)github\.com[:/]+([\w.-]+)/([\w.-]+?)(?:\.git)?/?(?:[#?].*)?$", url.strip())
    if m:
        return m.group(1), m.group(2)
    m = re.search(r"(?i)github\.com[:/]+([\w.-]+)(?:/|$)", url.strip())
    return (m.group(1), "") if m else None


def gated_url(url: str):
    o = github_owner(url)
    return "%s/%s" % o if o and o[0].lower() in GATED_OWNERS else None


def gated_remotes(dirpath: str):
    """[(remote name, 'owner/name')] for the remotes of dirpath that belong to a gated owner."""
    rc, out = git(dirpath, "remote", "-v")
    found = []
    if rc != 0:
        return found
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            slug = gated_url(parts[1])
            if slug and (parts[0], slug) not in found:
                found.append((parts[0], slug))
    return found


def check_git(args, cur: str, env=None, fulltext: str = "") -> None:
    i = 0
    dirpath = cur
    gitdir = resolve_dir(env["GIT_DIR"], cur) if env and env.get("GIT_DIR") else None
    while i < len(args) and args[i].startswith("-"):
        a = args[i]
        if a == "-C" and i + 1 < len(args):
            dirpath = resolve_dir(args[i + 1], dirpath)
            i += 2
        elif a.startswith("--git-dir="):
            gitdir = resolve_dir(a.split("=", 1)[1], dirpath)
            i += 1
        elif a == "--git-dir" and i + 1 < len(args):
            gitdir = resolve_dir(args[i + 1], dirpath)
            i += 2
        elif a in ("-c", "--work-tree", "--namespace", "--exec-path", "--config-env"):
            i += 2
        else:
            i += 1
    if i >= len(args) or args[i] != "push":
        return
    rest = args[i + 1:]
    remote = None
    positionals = []
    j = 0
    while j < len(rest):
        a = rest[j]
        if a == "--":
            positionals.extend(rest[j + 1:])
            break
        if a == "--dry-run" or (re.match(r"^-[fnquv46]+$", a) and "n" in a):
            return
        if a.startswith("--repo="):
            remote = a.split("=", 1)[1]
        elif a == "--repo" and j + 1 < len(rest):
            remote = rest[j + 1]
            j += 1
        elif a in ("-o", "--push-option", "--receive-pack", "--exec") and j + 1 < len(rest):
            j += 1
        elif a.startswith("-") and len(a) > 1:
            pass
        else:
            positionals.append(a)
        j += 1
    if remote is None and positionals:
        remote = positionals[0]
    if remote is None:
        rc, branch = git(dirpath, "symbolic-ref", "--short", "-q", "HEAD", gitdir=gitdir)
        branch = branch.strip() if rc == 0 else ""
        keys = (["branch.%s.pushRemote" % branch] if branch else []) + ["remote.pushDefault"] + \
               (["branch.%s.remote" % branch] if branch else [])
        for key in keys:
            rc, val = git(dirpath, "config", "--get", key, gitdir=gitdir)
            if rc == 0 and val.strip():
                remote = val.strip()
                break
        remote = remote or "origin"
    if "$" in remote or "`" in remote:
        if mentions_gated(fulltext) or mentions_gated(" ".join(args)):
            raise Finding(reason_for("`git push` (remote not resolvable: %s)" % remote, "cfengine/NorthernTechHQ named in the command"))
        return
    rc, out = git(dirpath, "remote", "get-url", "--push", "--all", remote, gitdir=gitdir)
    urls = out.split() if rc == 0 else [remote]
    for u in urls:
        slug = gated_url(u)
        if slug:
            raise Finding(reason_for("`git push %s`" % remote, "%s via %s" % (slug, u)))


# ---- gh -------------------------------------------------------------------------------------------------------


def parse_gh(args):
    """(positionals, [(flag, value)]) with long/short value flags consumed."""
    pos = []
    flags = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            pos.extend(args[i + 1:])
            break
        if a.startswith("--"):
            name, eq, val = a.partition("=")
            if not eq and name in GH_VALUE_LONG and i + 1 < len(args):
                val = args[i + 1]
                i += 1
            flags.append((name, val if (eq or name in GH_VALUE_LONG) else None))
        elif a.startswith("-") and len(a) > 1:
            c = a[1]
            if c in GH_VALUE_SHORT:
                if len(a) > 2:
                    val = a[2:].lstrip("=")
                elif i + 1 < len(args):
                    val = args[i + 1]
                    i += 1
                else:
                    val = ""
                flags.append(("-" + c, val))
            else:
                flags.append((a, None))
        else:
            pos.append(a)
        i += 1
    return pos, flags


def slug_of(s: str):
    """(owner, name) of an OWNER/NAME, HOST/OWNER/NAME or github URL value, else None."""
    s = s.strip()
    o = github_owner(s)
    if o:
        return o
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", s)
    parts = [p for p in s.split("/") if p]
    if len(parts) >= 3 and "." in parts[0]:
        parts = parts[1:]
    if len(parts) >= 2:
        return parts[0], re.sub(r"(\.git)?(#.*)?$", "", parts[1])
    return None


def api_target(endpoint: str):
    """('repo', owner, name) / ('owner', owner, '') / ('cwd', '', '') / None for a gh api endpoint."""
    ep = re.sub(r"^https?://[^/]+/", "", endpoint.strip()).lstrip("/")
    m = re.match(r"repos/([^/]+)/([^/?]*)", ep)
    if m:
        if m.group(1).startswith("$"):
            return ("unknown", ep, "")
        if m.group(1).startswith(("{", ":")):
            return ("cwd", "", "")
        return ("repo", m.group(1), m.group(2))
    m = re.match(r"(?:orgs|users)/([^/?]+)", ep)
    if m:
        return ("owner", m.group(1), "")
    if ep.startswith("repositories/") or "{owner}" in ep or "{repo}" in ep:
        return ("cwd", "", "")
    return None


def read_text(path: str, cur: str) -> str:
    try:
        p = resolve_dir(path, cur)
        if os.path.isfile(p) and os.path.getsize(p) <= MAX_FILE:
            with open(p, "r", errors="replace") as fh:
                return fh.read()
    except OSError:
        pass
    return ""


def check_gh(args, env, cur: str, fulltext: str) -> None:
    pos, flags = parse_gh(args)
    if not pos:
        return
    group = pos[0]
    flagmap = {}
    for f, v in flags:
        flagmap.setdefault(f, []).append(v)
    targets = []          # ('repo'|'owner'|'cwd', owner, name)
    label = "gh " + " ".join(pos[:2])
    write = False
    is_graphql = False
    if group == "api":
        ep = pos[1] if len(pos) > 1 else ""
        method = None
        for f in ("-X", "--method"):
            for v in flagmap.get(f, []):
                method = (v or "").upper()
        has_field = any(f in flagmap for f in ("-f", "-F", "--field", "--raw-field", "--input"))
        is_graphql = re.sub(r"^https?://[^/]+/", "", ep).strip("/") == "graphql"
        if is_graphql:
            text = ""
            stdin_used = any(v == "-" for v in flagmap.get("--input", [])) or any(
                (v or "").endswith("=@-") for f in ("-f", "-F", "--field", "--raw-field") for v in flagmap.get(f, []))
            if stdin_used:
                for rf in REDIR_IN:
                    text += "\n" + read_text(rf, cur)
            for f in ("-f", "-F", "--field", "--raw-field"):
                for v in flagmap.get(f, []):
                    if v and "=@" in v:
                        text += "\n" + read_text(v.split("=@", 1)[1], cur)
            for v in flagmap.get("--input", []):
                if v and v != "-":
                    text += "\n" + read_text(v, cur)
            data_text = "\n".join(DATA)
            write = (has_mutation(text) or has_mutation(fulltext) or has_mutation(data_text)) \
                and method not in ("GET", "HEAD")
            if write:
                if mentions_gated(text) or mentions_gated(fulltext) or mentions_gated(data_text):
                    raise Finding(reason_for("`gh api graphql` mutation", "cfengine/NorthernTechHQ named in the request"))
                if gated_remotes(cur):
                    g = gated_remotes(cur)[0]
                    raise Finding(reason_for("`gh api graphql` mutation (no repository named)",
                                             "directory remote %s = %s" % g))
            return
        write = (method not in (None, "GET", "HEAD")) if method is not None else has_field
        label = "gh api %s %s" % (method or ("POST" if has_field else "GET"), ep)
        t = api_target(ep) if ep else None
        if t:
            targets.append(t)
    else:
        if group not in GH_GROUPS or len(pos) < 2:
            return
        verb = pos[1]
        if (group, verb) == ("label", "clone"):
            pass                                        # copies labels INTO the -R repo: a write
        elif verb in GH_NESTED:
            if len(pos) > 2 and pos[2] in GH_READ_VERBS:
                return
        elif verb in GH_READ_VERBS:
            return
        write = True
    if not write:
        return
    # explicit targets
    for f in ("-R", "--repo"):
        for v in flagmap.get(f, []):
            s = slug_of(v or "")
            if s:
                targets.append(("repo", s[0], s[1]))
            elif v and "$" in v:
                targets.append(("unknown", v, ""))
    for v in flagmap.get("--owner", []):
        if v:
            targets.append(("owner", v, ""))
    if env.get("GH_REPO") and not flagmap.get("-R") and not flagmap.get("--repo"):
        s = slug_of(env["GH_REPO"])
        if s:
            targets.append(("repo", s[0], s[1]))
    if group != "api":
        for p in pos[2:]:
            if re.match(r"(?i)^(https?://|git@|ssh://)?([\w.-]+@)?(www\.)?github\.com[/:]", p):
                s = github_owner(p)
                if s:
                    targets.append(("repo", s[0], s[1]))
            elif re.match(r"(?i)^(cfengine|northerntechhq)/[\w.-]+(#\d+)?$", p):
                s = slug_of(p)
                targets.append(("repo", s[0], s[1]))
    explicit = False
    for kind, owner, name in targets:
        if kind in ("repo", "owner"):
            if owner.lower() in GATED_OWNERS:
                raise Finding(reason_for("`%s`" % label, ("%s/%s" % (owner, name)) if name else owner))
            if "$" not in owner:
                explicit = True
        if kind == "unknown" or "$" in owner:
            if mentions_gated(fulltext):
                raise Finding(reason_for("`%s` (target is a shell variable)" % label,
                                         "cfengine/NorthernTechHQ named elsewhere in the command"))
    if explicit and not any(t[0] == "cwd" for t in targets):
        return
    remotes = gated_remotes(cur)
    if remotes:
        n, slug = remotes[0]
        raise Finding(reason_for("`%s` (no -R: gh defaults to this repository or its parent)" % label,
                                 "%s remote %s = %s in %s" % ("a" if len(remotes) == 1 else "first", n, slug, cur)))


# ---- Jira / Composio ------------------------------------------------------------------------------------------

JIRA_HOST = re.compile(r"(?i)atlassian\.net")
HTTPIE = frozenset({"http", "https", "xh", "xhs"})
CURL_VALUE_SHORT = frozenset("AbcCdDeEFHKmoPQrTuUwxXyYz")
CURL_DATA = re.compile(r"^(--data(-raw|-binary|-ascii|-urlencode)?|--json|--form|--form-string|--upload-file|"
                       r"--post-data|--post-file|--body-data|--body-file)(=|$)")


def http_write(name: str, args) -> bool:
    get_mode = False
    data = False
    implicit_data = False
    method = None
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-G", "--get"):
            get_mode = True
        elif a in ("-X", "--request", "--method") and i + 1 < len(args):
            method = args[i + 1].upper()
            i += 1
        elif a.startswith("--request=") or a.startswith("--method="):
            method = a.split("=", 1)[1].upper()
        elif a.startswith("-X") and len(a) > 2 and not a.startswith("--"):
            method = a[2:].lstrip("=").upper()
        elif CURL_DATA.match(a):
            data = True
        elif name == "curl" and re.match(r"^-[A-Za-z]{2,}", a):       # a cluster: -sSX DELETE, -sd @b
            for k, letter in enumerate(a[1:], 1):
                if letter in CURL_VALUE_SHORT:
                    rest = a[k + 1:]
                    if letter == "X":
                        if rest:
                            method = rest.lstrip("=").upper()
                        elif i + 1 < len(args):
                            method = args[i + 1].upper()
                    elif letter in "dFT":
                        data = True
                    break
        elif a in ("-d", "-F", "-T") or (re.match(r"^-[dFT].", a) and name == "curl"):
            data = True
        elif name in HTTPIE and a.upper() in ("POST", "PUT", "PATCH", "DELETE"):
            method = a.upper()
        elif name in HTTPIE and not a.startswith("-") and "://" not in a and re.match(r"^[^=:\s]+(=(?!=)|:=)", a):
            implicit_data = True                       # httpie sends a POST once there are data items
        i += 1
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        return True
    if implicit_data and method in (None, "GET") and not get_mode:
        return True
    return data and not get_mode


def check_jira(seglist, fulltext: str) -> None:
    host_anywhere = bool(JIRA_HOST.search(fulltext))
    if not host_anywhere:
        return
    for name, args in seglist:
        if name not in HTTP_TOOLS or not http_write(name, args):
            continue
        urls = [a for a in args if re.match(r"(?i)^(https?://|[\w.-]+\.[a-z]{2,}(/|$))", a)]
        if any(JIRA_HOST.search(a) for a in args) or not urls:
            raise Finding(reason_for("this %s request" % name, "a mutating request to atlassian.net (Jira)"))


def check_composio(words) -> None:
    joined = " ".join(words)
    if re.search(r"(?i)composio", joined) and re.search(r"(?i)jira", joined) and WRITE_WORDS.search(joined):
        raise Finding(reason_for("this Composio call", "a Jira write"))


# ---- driver ---------------------------------------------------------------------------------------------------


def command_of(words, env):
    """(name, args, env) of the simple command, looking through wrappers; None when it is not one we gate."""
    env = dict(env)
    while words and ASSIGN.match(words[0]):
        k, v = ASSIGN.match(words[0]).groups()
        env[k] = v
        words = words[1:]
    if not words:
        return None
    name = base(words[0])
    if ("$(" in words[0] or "`" in words[0]) and re.search(r"(?<![\w-])(gh|git)(?![\w-])", words[0]):
        name = re.search(r"(?<![\w-])(gh|git)(?![\w-])", words[0]).group(1)   # "$(command -v gh)" pr create
    if name in WRAPPERS:
        for j in range(1, len(words)):
            m = ASSIGN.match(words[j])
            if m:
                env[m.group(1)] = m.group(2)
            elif base(words[j]) in INTERESTING:
                return base(words[j]), words[j + 1:], env
        return None
    if name in INTERESTING:
        return name, words[1:], env
    return None


RESERVED = frozenset({"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}", "time", "coproc",
                      "function", "exec"})


def expand(word: str, senv) -> str:
    """$NAME and ${NAME} replaced by a value assigned earlier in the command (unknown names stay)."""
    if "$" not in word:
        return word
    return re.sub(r"\$\{(\w+)\}|\$(\w+)", lambda m: senv.get(m.group(1) or m.group(2), m.group(0)), word)


def check_text(text: str, cwd: str, depth: int, senv=None):
    """Analyse one command text; returns the (cwd, environment) its end leaves for what follows."""
    segs = segments(text)
    cur = cwd
    seglist = []
    senv = dict(senv or {})
    for k in ("GH_REPO", "GIT_DIR"):
        if os.environ.get(k) and k not in senv:
            senv[k] = os.environ[k]
    stack = []
    for words in segs:
        if words == "(":
            stack.append((cur, dict(senv)))
            continue
        if words == ")":
            if stack:
                cur, senv = stack.pop()
            continue
        for w in words:
            if ("$(" in w or "`" in w) and depth < MAX_DEPTH:
                check_command(w, cur, depth + 1, senv)
        words = [expand(w, senv) for w in words]
        while words and words[0] in RESERVED:
            words = words[1:]
        assigns = words[1:] if words and words[0] in ("export", "declare", "typeset", "local", "readonly") else words
        if assigns and all(ASSIGN.match(w) for w in assigns):
            for w in assigns:                           # `export GH_REPO=cfengine/core; gh issue create ...`
                k, v = ASSIGN.match(w).groups()
                senv[k] = v
            continue
        cmd = command_of(words, senv)
        if not cmd:
            continue
        name, args, env = cmd
        if name in ("cd", "pushd"):
            tgt = [a for a in args if not a.startswith("-")]
            if tgt:
                cur = resolve_dir(tgt[0], cur)
        elif name in SHELLS:
            for k, a in enumerate(args):
                if re.match(r"^-[A-Za-z]*c$", a) and k + 1 < len(args) and depth < MAX_DEPTH:
                    check_command(args[k + 1], cur, depth + 1, env)
                    break
        elif name == "eval":
            if depth < MAX_DEPTH:
                check_command(" ".join(args), cur, depth + 1, env)
        elif name == "gh":
            check_gh(args, env, cur, text)
        elif name == "git":
            check_git(args, cur, env, text)
        elif name in HTTP_TOOLS:
            seglist.append((name, args))
    for words in segs:                                  # composio, `npx composio`, `uvx composio` alike
        if isinstance(words, list) and any(re.search(r"(?i)composio", w) for w in words):
            check_composio(words)
    check_jira(seglist, text)
    return cur, senv


def check_command(cmd: str, cwd: str, depth: int = 0, senv=None) -> None:
    if depth > MAX_DEPTH or not cmd:
        return
    body, kept, bodies = split_heredocs(cmd)
    DATA.extend(bodies)
    cur, env = check_text(body, cwd, depth, senv)
    for text in kept:                                   # a heredoc fed to a shell runs after the cd before it
        check_text(text, cur, depth, env)


def check_mcp(tool_name: str, tool_input) -> None:
    if "composio" not in tool_name.lower():
        return
    blob = tool_name + " " + json.dumps(tool_input)
    if re.search(r"(?i)jira", blob) and re.search(r"(?i)jira_\w*(create|update|add|edit|delete|assign|transition|comment|remove|link|move)", blob):
        raise Finding(reason_for("this Composio tool call", "a Jira write"))


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        sys.exit(0)
    if not isinstance(data, dict) or os.environ.get("UPSTREAM_REVIEW_GATE_OFF", "").lower() not in ("", "0", "false", "no"):
        sys.exit(0)
    if hasattr(signal, "SIGALRM"):                     # a pathological input must not hang: fail open
        signal.signal(signal.SIGALRM, lambda *_: (print("upstream_review_gate: timed out", file=sys.stderr),
                                                  sys.exit(0)))
        signal.alarm(BUDGET_S)
    tool = str(data.get("tool_name") or "")
    tin = data.get("tool_input") or {}
    cwd = data.get("cwd") if isinstance(data.get("cwd"), str) and data.get("cwd") else os.getcwd()
    try:
        if tool in ("", "Bash", "shell", "shell_command", "exec_command", "local_shell") and isinstance(tin, dict):
            cmd = tin.get("command")
            if isinstance(cmd, list):
                cmd = cmd[-1] if cmd else ""
            if isinstance(cmd, str):
                check_command(cmd, cwd)
        else:
            check_mcp(tool, tin)
    except Finding as f:
        deny(str(f))
    except Exception as exc:                            # a bug must never block an unrelated command
        print("upstream_review_gate: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
