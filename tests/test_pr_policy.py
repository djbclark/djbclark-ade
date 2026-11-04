"""bin/pr-policy (2026-11-04): pull request policy on djbclark's GitHub and Forgejo repositories.

The CLI runs as a subprocess against a fake GitHub + Forgejo HTTP server on 127.0.0.1, a fake sudo-secretspec that
prints a dummy token and a fake hermes-ping that records its argument. Nothing reaches the network, launchd or Hermes."""
from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "bin" / "pr-policy"


def gh_repo(name, policy="all", archived=False, prs=True):
    return {"full_name": name, "html_url": f"https://github.com/{name}", "archived": archived,
            "has_pull_requests": prs, "pull_request_creation_policy": policy}


def gh_pr(repo, n, who, draft=False, kind="User", labels=()):
    return {"repository_url": f"https://api.github.com/repos/{repo}", "number": n, "draft": draft,
            "html_url": f"https://github.com/{repo}/pull/{n}", "node_id": f"PR_{repo}_{n}", "user": {"login": who, "type": kind},
            "labels": [{"name": x} for x in labels]}


def fj_pr(repo, n, who, title="t", draft=False, labels=()):
    return {"repository": {"full_name": repo}, "number": n, "title": title, "user": {"login": who},
            "html_url": f"https://forgejo.example/{repo}/pulls/{n}", "pull_request": {"draft": draft},
            "labels": [{"name": x} for x in labels]}


class World:
    def __init__(self):
        self.user_repos = [gh_repo("djbclark/a"), gh_repo("djbclark/b", "collaborators_only"), gh_repo("djbclark/old", archived=True),
                           gh_repo("djbclark/noprs", prs=False), gh_repo("djbclark/c")]
        self.org_repos = [gh_repo("frdminc/x"), gh_repo("frdminc/skip")]
        self.gh_search = [gh_pr("frdminc/x", 1, "stranger"), gh_pr("frdminc/x", 2, "friend"), gh_pr("djbclark/a", 3, "dependabot[bot]", kind="Bot"),
                          gh_pr("djbclark/a", 4, "drafty", draft=True), gh_pr("someoneelse/z", 5, "stranger")]
        self.gh_perm = {("frdminc/x", "friend"): "write", ("frdminc/x", "stranger"): "read"}
        self.fj_search = [fj_pr("djbclark/barnowl", 4, "siteadmin", "Touhou"), fj_pr("djbclark/barnowl", 5, "djbclark"),
                          fj_pr("djbclark/get", 6, "pal"), fj_pr("djbclark/get", 7, "readpal"), fj_pr("djbclark/get", 8, "x", draft=True)]
        self.fj_collab = {("djbclark/barnowl", "siteadmin"): None, ("djbclark/get", "pal"): "write", ("djbclark/get", "readpal"): "read"}
        self.fj_perm_any = "owner"   # what Forgejo says for a site admin who is no collaborator
        self.stale_patch = False
        self.direct: dict[str, dict] = {}   # what GET /repos/O/R says when the listing lags behind it
        self.link_next = None
        self.redirect_org = None
        self.requests: list[tuple[str, str, str]] = []


def make_handler(w: World):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body=None, headers=None):
            raw = b"" if body is None else json.dumps(body).encode()
            self.send_response(code)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def route(self, method):
            u = urllib.parse.urlsplit(self.path)
            qs = urllib.parse.parse_qs(u.query)
            p = u.path
            w.requests.append((method, self.path, self.headers.get("Authorization", "")))
            if p == "/gh/user":
                return self.send(200, {"login": "djbclark"})
            if p == "/gh/user/repos":
                page = int(qs.get("page", ["1"])[0])
                items = w.user_repos[(page - 1) * 2:page * 2]
                hdr = {}
                if page * 2 < len(w.user_repos):
                    nxt = w.link_next or f"http://127.0.0.1:{self.server.server_port}/gh/user/repos?affiliation=owner&page={page + 1}"
                    hdr["Link"] = f'<{nxt}>; rel="next", <http://127.0.0.1/last>; rel="last"'
                return self.send(200, items, hdr)
            if p == "/gh/orgs/frdminc/repos":
                if w.redirect_org:
                    return self.send(302, None, {"Location": w.redirect_org})
                return self.send(200, w.org_repos)
            if p == "/gh/search/issues":
                assert "draft:false" in qs["q"][0] and "-author:djbclark" in qs["q"][0]
                return self.send(200, {"items": w.gh_search})
            if p == "/gh/graphql":
                b = self.body()
                for it in w.gh_search:
                    if it["node_id"] == b["variables"]["id"]:
                        it["draft"] = True
                return self.send(200, {"data": {"convertPullRequestToDraft": {"pullRequest": {"isDraft": True}}}})
            parts = p.split("/")
            if p.startswith("/gh/repos/") and p.endswith("/permission"):
                repo, who = f"{parts[3]}/{parts[4]}", urllib.parse.unquote(parts[6])
                perm = w.gh_perm.get((repo, who))
                return self.send(200, {"permission": perm}) if perm else self.send(404, {"message": "Not Found"})
            if p.startswith("/gh/repos/") and len(parts) == 5 and method == "GET":
                repo = f"{parts[3]}/{parts[4]}"
                for r in w.user_repos + w.org_repos:
                    if r["full_name"] == repo:
                        return self.send(200, {**r, **w.direct.get(repo, {})})
                return self.send(404, {"message": "Not Found"})
            if p.startswith("/gh/repos/") and method == "PATCH":
                repo = f"{parts[3]}/{parts[4]}"
                val = self.body()["pull_request_creation_policy"]
                for r in w.user_repos + w.org_repos:
                    if r["full_name"] == repo and not w.stale_patch:
                        r["pull_request_creation_policy"] = val
                return self.send(200, {"full_name": repo, "pull_request_creation_policy": "all" if w.stale_patch else val})
            if p == "/fj/api/v1/user":
                return self.send(200, {"login": "djbclark"})
            if p == "/fj/api/v1/repos/issues/search":
                page = int(qs.get("page", ["1"])[0])
                return self.send(200, w.fj_search if page == 1 else [])
            if p.startswith("/fj/api/v1/repos/") and "/collaborators/" in p:
                repo, who = f"{parts[5]}/{parts[6]}", urllib.parse.unquote(parts[8])
                if p.endswith("/permission"):
                    return self.send(200, {"permission": w.fj_collab.get((repo, who)) or w.fj_perm_any})
                return self.send(204) if w.fj_collab.get((repo, who)) else self.send(404, {"message": "not found"})
            if p.startswith("/fj/api/v1/repos/") and "/pulls/" in p and method == "PATCH":
                repo, n = f"{parts[5]}/{parts[6]}", int(parts[8])
                title = self.body()["title"]
                for it in w.fj_search:
                    if it["repository"]["full_name"] == repo and it["number"] == n:
                        it["title"] = title
                        it["pull_request"]["draft"] = title.startswith("WIP:")
                return self.send(201, {"number": n, "title": title, "draft": title.startswith("WIP:")})
            return self.send(404, {"message": f"no route {method} {p}"})

        def do_GET(self):
            self.route("GET")

        def do_PATCH(self):
            self.route("PATCH")

        def do_POST(self):
            self.route("POST")
    return H


@pytest.fixture
def env(tmp_path):
    w = World()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(w))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    cfg = tmp_path / "pr-policy.toml"
    cfg.write_text(f"""[meta]
schema = 1
[github]
api = "{base}/gh"
token_secret = "GH_TOK"
owners = ["djbclark", "frdminc"]
policy = "collaborators_only"
exempt_repos = ["frdminc/skip"]
trusted_authors = ["Dependabot[bot]"]
[forgejo]
host = "forgejo.example"
api = "{base}/fj/api/v1"
token_secret = "FJ_TOK"
owners = ["djbclark"]
draft_prefix = "WIP: "
exempt_repos = []
""")
    fake_ss = tmp_path / "sudo-secretspec"
    fake_ss.write_text("#!/bin/sh\n[ -n \"$FAIL_SECRET\" ] && [ \"$2\" = \"$FAIL_SECRET\" ] && exit 1\nprintf 'sekrit-%s\\n' \"$2\"\n")
    fake_ss.chmod(0o755)
    ping_log = tmp_path / "pings.txt"
    fake_ping = tmp_path / "hermes-ping"
    fake_ping.write_text(f"#!/bin/sh\n[ -n \"$PING_FAIL\" ] && exit 1\nprintf '%s\\n' \"$1\" >> {ping_log}\n")
    fake_ping.chmod(0o755)
    e = {**os.environ, "HOME": str(tmp_path), "PR_POLICY_CONFIG": str(cfg), "PR_POLICY_SECRETSPEC": str(fake_ss),
         "PR_POLICY_PING": str(fake_ping), "PR_POLICY_STATE_DIR": str(tmp_path / "state")}
    e.pop("FAIL_SECRET", None)
    e.pop("PING_FAIL", None)

    def run(*args, extra=None):
        return subprocess.run([sys.executable, str(CLI), *args], env={**e, **(extra or {})}, capture_output=True, text=True, timeout=60)
    run.world, run.tmp, run.base, run.pings, run.cfg = w, tmp_path, base, ping_log, cfg
    yield run
    srv.shutdown()


def writes(w):
    return [r for r in w.requests if r[0] != "GET"]


def test_plan_is_read_only_and_lists_every_change(env):
    p = env("plan", "--json")
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    locks = sorted(a["repo"] for a in out["actions"] if a["kind"] == "lock")
    assert locks == ["djbclark/a", "djbclark/c", "frdminc/x"]   # not b (already), old (archived), noprs, skip (exempt)
    drafts = sorted((a["forge"], a["repo"], a["number"]) for a in out["actions"] if a["kind"] == "draft")
    assert drafts == [("forgejo", "djbclark/barnowl", 4), ("forgejo", "djbclark/get", 7), ("github", "frdminc/x", 1)]
    assert writes(env.world) == []
    assert not (env.tmp / "state" / "changes.jsonl").exists()


def test_an_approved_outside_pull_request_stays_ready(env):
    w = env.world
    w.gh_search.append(gh_pr("frdminc/x", 9, "stranger", labels=("PR-Policy-Approved",)))
    w.fj_search.append(fj_pr("djbclark/get", 10, "readpal", labels=("pr-policy-approved",)))
    w.gh_search.append(gh_pr("frdminc/x", 11, "stranger", labels=("approved",)))
    out = json.loads(env("plan", "--json").stdout)
    drafts = {(a["repo"], a["number"]) for a in out["actions"] if a["kind"] == "draft"}
    assert ("frdminc/x", 9) not in drafts and ("djbclark/get", 10) not in drafts
    assert ("frdminc/x", 11) in drafts and ("frdminc/x", 1) in drafts


def test_a_token_that_is_not_one_printable_word_is_refused_unechoed(env, tmp_path):
    bad = tmp_path / "bad-secretspec"
    bad.write_text("#!/bin/sh\nprintf 'sekrit with\\tspace\\n'\n")
    bad.chmod(0o755)
    p = env("plan", "--json", extra={"PR_POLICY_SECRETSPEC": str(bad)})
    assert p.returncode == 1
    errs = json.loads(p.stdout)["errors"]
    assert any("not one printable token (length 17)" in e for e in errs)
    assert "sekrit" not in p.stdout + p.stderr and env.world.requests == []


def test_quiet_plan_still_lists_pending_changes(env):
    p = env("plan", "--quiet")
    assert p.returncode == 0 and "would change 6" in p.stdout and "github  lock   djbclark/a" in p.stdout


def test_apply_without_yes_is_plan(env):
    p = env("apply")
    assert p.returncode == 0 and "would change 6" in p.stdout
    assert writes(env.world) == []


def test_apply_yes_changes_records_and_is_idempotent(env):
    p = env("apply", "--yes")
    assert p.returncode == 0, p.stderr
    w = env.world
    assert {r["full_name"]: r["pull_request_creation_policy"] for r in w.user_repos + w.org_repos} == {
        "djbclark/a": "collaborators_only", "djbclark/b": "collaborators_only", "djbclark/old": "all",
        "djbclark/noprs": "all", "djbclark/c": "collaborators_only", "frdminc/x": "collaborators_only", "frdminc/skip": "all"}
    assert [it["draft"] for it in w.gh_search] == [True, False, False, True, False]
    titles = {(it["repository"]["full_name"], it["number"]): it["title"] for it in w.fj_search}
    assert titles[("djbclark/barnowl", 4)] == "WIP: Touhou" and titles[("djbclark/get", 7)] == "WIP: t"
    assert titles[("djbclark/get", 6)] == "t" and titles[("djbclark/barnowl", 5)] == "t"
    log = [json.loads(x) for x in (env.tmp / "state" / "changes.jsonl").read_text().splitlines()]
    assert len(log) == 6 and {x["result"] for x in log} == {"ok"}
    assert all("node_id" not in x and "title" not in x for x in log)
    before = len(writes(w))
    p2 = env("apply", "--yes", "--quiet")
    assert p2.returncode == 0 and p2.stdout == "" and len(writes(w)) == before


def test_tokens_go_only_to_their_own_api_and_never_into_output(env):
    p = env("apply", "--yes")
    for method, path, auth in env.world.requests:
        want = "Bearer sekrit-GH_TOK" if path.startswith("/gh/") else "token sekrit-FJ_TOK"
        assert auth == want, (method, path)
    assert "sekrit" not in p.stdout + p.stderr
    assert "sekrit" not in (env.tmp / "state" / "changes.jsonl").read_text()


def test_link_to_another_host_is_refused(env):
    env.world.link_next = "http://evil.invalid/gh/user/repos?page=2"
    p = env("plan", "--json")
    assert p.returncode == 1
    assert any("another origin: http://evil.invalid" in e for e in json.loads(p.stdout)["errors"])


def test_link_with_another_scheme_on_the_same_host_is_refused(env):
    env.world.link_next = env.base.replace("http://", "https://") + "/gh/user/repos?page=2"
    p = env("plan", "--json")
    assert p.returncode == 1
    assert any("another origin: https://127.0.0.1" in e for e in json.loads(p.stdout)["errors"])


def test_a_bot_is_checked_like_anyone_unless_trusted(env):
    env.cfg.write_text(env.cfg.read_text().replace('trusted_authors = ["Dependabot[bot]"]\n', ""))
    out = json.loads(env("plan", "--json", "--only", "github").stdout)
    assert ("djbclark/a", 3) in [(a["repo"], a.get("number")) for a in out["actions"] if a["kind"] == "draft"]


def test_redirect_is_not_followed_with_the_token(env):
    seen = []

    class Catch(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            seen.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"[]")
    other = ThreadingHTTPServer(("127.0.0.1", 0), Catch)
    threading.Thread(target=other.serve_forever, daemon=True).start()
    try:
        env.world.redirect_org = f"http://127.0.0.1:{other.server_port}/steal"
        p = env("plan", "--json")
        assert p.returncode == 1 and any("HTTP 302" in e for e in json.loads(p.stdout)["errors"])
        assert seen == []
    finally:
        other.shutdown()


def test_patch_that_does_not_stick_is_an_error(env):
    env.world.stale_patch = True
    p = env("apply", "--yes", "--only", "github", "--json")
    assert p.returncode == 1
    log = [json.loads(x) for x in (env.tmp / "state" / "changes.jsonl").read_text().splitlines()]
    assert any(x["kind"] == "lock" and x["result"].startswith("error:") for x in log)


def test_a_lagging_listing_is_not_patched_or_reported(env):
    env.world.direct["djbclark/a"] = {"pull_request_creation_policy": "collaborators_only"}
    p = env("apply", "--yes", "--only", "github", "--notify")
    assert p.returncode == 0, p.stderr
    assert not any(m == "PATCH" and path == "/gh/repos/djbclark/a" for m, path, _ in env.world.requests)
    assert "same   github  lock   djbclark/a" in p.stdout
    assert "(+" not in env.pings.read_text() and env.pings.read_text().startswith("djbclark-ade: pr-policy: 3 change(s): ")


def test_notify_once_per_change_run_and_once_per_new_error(env):
    p = env("apply", "--yes", "--notify", "--quiet")
    assert p.returncode == 0
    pings = env.pings.read_text().splitlines()
    assert len(pings) == 1 and pings[0].startswith("djbclark-ade: pr-policy: 6 change(s): ") and "(+3 more)" in pings[0]
    env("apply", "--yes", "--notify", "--quiet")
    assert len(env.pings.read_text().splitlines()) == 1   # compliant: silent
    for _ in range(2):
        p = env("apply", "--yes", "--notify", "--quiet", extra={"FAIL_SECRET": "FJ_TOK"})
        assert p.returncode == 1 and "sudo-secretspec get FJ_TOK failed" in p.stderr
    pings = env.pings.read_text().splitlines()
    assert len(pings) == 2 and "1 new error(s)" in pings[1]


def test_an_error_whose_ping_failed_is_reported_again(env):
    env("apply", "--yes", "--notify", "--quiet")
    fail = {"FAIL_SECRET": "FJ_TOK"}
    p = env("apply", "--yes", "--notify", "--quiet", extra={**fail, "PING_FAIL": "1"})
    assert p.returncode == 1 and "hermes-ping failed" in p.stderr
    env("apply", "--yes", "--notify", "--quiet", extra=fail)
    pings = env.pings.read_text().splitlines()
    assert len(pings) == 2 and "1 new error(s)" in pings[1]


def test_plain_http_to_a_real_host_is_refused(env):
    env.cfg.write_text(env.cfg.read_text().replace(f'api = "{env.base}/gh"', 'api = "http://api.example.com"'))
    p = env("plan", "--only", "github", "--json")
    assert p.returncode == 1 and any("refusing to send a token over http" in e for e in json.loads(p.stdout)["errors"])
    assert not any(r[1].startswith("/gh/") for r in env.world.requests)


def test_bad_config_schema_exits_2(env):
    env.cfg.write_text("[meta]\nschema = 2\n")
    assert env("plan").returncode == 2


def test_install_dry_run_renders_the_template(env):
    p = env("install", "--dry-run", "--ade", str(REPO))
    assert p.returncode == 0, p.stderr
    assert "__" not in p.stdout
    pl = plistlib.loads(p.stdout.encode())
    assert pl["Label"] == "com.djbclark.pr-policy"
    assert pl["ProgramArguments"] == [str(REPO / "bin/pr-policy"), "apply", "--yes", "--notify", "--quiet"]
    assert pl["EnvironmentVariables"]["PR_POLICY_STATE_DIR"] == str((env.tmp / "state").resolve())
