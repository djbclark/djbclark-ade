"""claude/hooks/upstream_review_gate.py: a write that CFEngine upstream (GitHub owners cfengine and NorthernTechHQ,
Jira on atlassian.net, Composio Jira) would see is denied; reads, our forks and every other third-party repo pass.
Cases are the two 2026-11-12 gaps of the old shell gate (a `gh api` path never read; `-f/-F` with no `-X` a POST)
plus the forms agents use daily. Remote cases use temporary git repos."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "claude" / "hooks" / "upstream_review_gate.py"
ENV = {k: v for k, v in os.environ.items() if not k.startswith("UPSTREAM_REVIEW_GATE")}
ENV.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")


def run(command, cwd, tool="Bash", tool_input=None, env=None, stdin=None):
    payload = stdin if stdin is not None else json.dumps(
        {"tool_name": tool, "tool_input": tool_input if tool_input is not None else {"command": command},
         "cwd": str(cwd)})
    r = subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, text=True, timeout=60,
                       env=env or ENV)
    assert r.returncode == 0, r.stderr
    assert r.stderr == ""
    return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None


def denied(command, cwd, **kw):
    out = run(command, cwd, **kw)
    if out is None:
        return False
    assert out["hookEventName"] == "PreToolUse" and out["permissionDecision"] == "deny"
    assert "Upstream review gate" in out["permissionDecisionReason"]
    return True


def make_repo(path, **remotes):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True, env=ENV)
    for name, url in remotes.items():
        subprocess.run(["git", "-C", str(path), "remote", "add", name, url], check=True, env=ENV)
    return path


@pytest.fixture
def plain(tmp_path):
    return tmp_path / "plain"          # a directory that is not a repository (created lazily)


@pytest.fixture
def ours(tmp_path):                    # origin is ours, no upstream
    return make_repo(tmp_path / "ours", origin="https://github.com/djbclark/stayturgid.git")


@pytest.fixture
def core_fork(tmp_path):               # a fork whose upstream is cfengine/core
    return make_repo(tmp_path / "core", origin="git@github.com:djbclark/core.git",
                     upstream="https://github.com/cfengine/core.git")


@pytest.fixture
def libntech(tmp_path):                # the libntech worktrees: origin is the upstream, `fork` is ours
    return make_repo(tmp_path / "libntech", origin="https://github.com/NorthernTechHQ/libntech.git",
                     fork="https://github.com/djbclark/libntech.git")


@pytest.fixture(autouse=True)
def _plain_exists(plain):
    plain.mkdir(exist_ok=True)


# ---- the two gaps ---------------------------------------------------------------------------------------------


def test_apple_container_patch_from_our_repo_is_allowed(ours):
    # 2026-11-12: this exact call went through the old gate; apple/container is not CFEngine, so it still does.
    assert not denied("gh api -X PATCH repos/apple/container/issues/2489 -F body=@f", ours)


def test_same_patch_against_cfengine_core_is_denied_from_our_repo(ours):
    assert denied("gh api -X PATCH repos/cfengine/core/issues/2489 -F body=@f", ours)


@pytest.mark.parametrize("flag", ["-F body=@f", "-f body=x", "--field body=x", "--raw-field body=x",
                                  "--input payload.json", "-fbody=x"])
def test_api_field_flags_without_x_are_a_post(ours, flag):
    assert denied("gh api repos/cfengine/core/issues/5/comments %s" % flag, ours)
    assert not denied("gh api repos/djbclark/core/issues/5/comments %s" % flag, ours)


def test_explicit_get_with_fields_is_a_read(ours):
    assert not denied("gh api -X GET repos/cfengine/core/issues -f state=open", ours)
    assert not denied("gh api --method=GET /repos/cfengine/core/pulls -F per_page=5", ours)


@pytest.mark.parametrize("command", [
    "gh api repos/cfengine/core/issues/6293",
    "gh api /repos/NorthernTechHQ/libntech/pulls --paginate --jq '.[].number'",
    "gh api https://api.github.com/repos/cfengine/core/pulls/1/comments",
    "gh api orgs/cfengine/repos",
    "gh api graphql -f query='query { repository(owner:\"cfengine\", name:\"core\") { id } }'",
])
def test_gh_api_reads_are_allowed(ours, command):
    assert not denied(command, ours)


@pytest.mark.parametrize("command", [
    "gh api -X POST repos/cfengine/core/issues -f title=x",
    "gh api --method DELETE /repos/NorthernTechHQ/libntech/issues/comments/9",
    "gh api --method=PUT repos/CFEngine/core/pulls/1/merge",
    "gh api -XPATCH repos/cfengine/core/issues/1 -f state=closed",
    "gh api https://api.github.com/repos/cfengine/core/issues -f title=x",
    "gh api orgs/NorthernTechHQ/teams -f name=x",
])
def test_gh_api_writes_to_gated_owners_are_denied(ours, command):
    assert denied(command, ours)


def test_graphql_mutation_naming_the_owner_is_denied(ours):
    q = 'gh api graphql -f query=\'mutation { addComment(input:{subjectId:"X", body:"b"}) { clientMutationId } }\' ' \
        '-f owner=cfengine'
    assert denied(q, ours)
    assert not denied(q.replace("cfengine", "djbclark"), ours)            # no gated owner, our cwd: allowed


def test_graphql_mutation_by_node_id_in_a_gated_fork_is_denied(core_fork):
    assert denied("gh api graphql -f query='mutation { closeIssue(input:{issueId:\"I_1\"}) { clientMutationId } }'",
                  core_fork)


def test_graphql_query_file_is_read(ours, tmp_path):
    (tmp_path / "q.graphql").write_text('mutation { x(owner: "NorthernTechHQ", name: "libntech") { id } }')
    assert denied("gh api graphql -F query=@q.graphql", tmp_path)


def test_api_placeholder_path_uses_the_cwd(core_fork, ours):
    cmd = "gh api -X POST repos/{owner}/{repo}/issues -f title=x"
    assert denied(cmd, core_fork)
    assert not denied(cmd, ours)


# ---- gh verbs, URLs, cwd --------------------------------------------------------------------------------------


def test_gh_pr_comment_url_form(ours):
    assert denied("gh pr comment https://github.com/cfengine/core/pull/6293 --body hi", ours)
    assert denied("gh pr comment https://github.com/cfengine/core/pull/6293#issuecomment-1 -b hi", ours)
    assert not denied("gh pr comment https://github.com/djbclark/core/pull/3 --body hi", ours)
    assert not denied("gh pr view https://github.com/cfengine/core/pull/6293", ours)


def test_body_text_mentioning_cfengine_is_not_a_target(ours):
    assert not denied("gh issue comment -R djbclark/core 5 --body 'see https://github.com/cfengine/core/pull/1'",
                      ours)
    assert not denied("gh pr create -R djbclark/core --title 'Fix cfengine/core#1' --body x", ours)


def test_bare_gh_pr_create_in_a_fork_of_cfengine_core(core_fork, ours):
    assert denied("gh pr create --title x --body y", core_fork)
    assert denied("gh issue comment 5 --body hi", core_fork)
    assert not denied("gh pr create -R djbclark/core --title x --body y", core_fork)
    assert not denied("gh pr create --repo djbclark/core --title x", core_fork)
    assert not denied("GH_REPO=djbclark/core gh pr create --title x", core_fork)
    assert denied("gh pr create -R cfengine/core --title x", ours)
    assert not denied("gh pr create --title x --body y", ours)


@pytest.mark.parametrize("command", [
    "gh pr view 12", "gh pr list", "gh pr diff 5", "gh pr checks 5", "gh pr checkout 5", "gh issue view 5",
    "gh issue list", "gh repo view", "gh repo fork cfengine/core", "gh run list", "gh release download v1",
    "gh api repos/cfengine/core/issues", "gh auth status", "gh search issues foo", "gh pr", "gh",
])
def test_reads_in_a_gated_fork_are_allowed(core_fork, command):
    assert not denied(command, core_fork)


@pytest.mark.parametrize("command", [
    "gh pr create -t x", "gh pr edit 5 --title y", "gh pr merge 5 --squash", "gh pr ready 5", "gh pr review 5 -a",
    "gh pr comment 5 -b x", "gh pr close 5", "gh pr reopen 5", "gh issue create -t x", "gh issue edit 5 -b y",
    "gh issue comment 5 -b x", "gh issue close 5", "gh issue delete 5", "gh release create v1", "gh pr lock 5",
    "gh issue transfer 5 cfengine/core", "gh repo edit --description x", "gh workflow run build.yml",
    "gh run rerun 5",
])
def test_writes_in_a_gated_fork_are_denied(core_fork, command):
    assert denied(command, core_fork)


def test_no_git_repo_means_no_cwd_inference(plain):
    assert not denied("gh pr create --title x --body y", plain)
    assert denied("gh pr create -R cfengine/core --title x", plain)


def test_other_third_party_repos_are_not_gated(ours, plain):
    for cmd in ("gh issue create -R apple/container --title x", "gh pr comment 1 -R RikkaApps/Shizuku -b x",
                "gh api -X POST repos/apple/container/issues -f title=x",
                "gh api -X PATCH repos/apple/container/issues/2489 -F body=@f"):
        assert not denied(cmd, plain), cmd


def test_owner_match_is_exact_and_case_insensitive(plain):
    assert denied("gh issue create -R CFENGINE/core --title x", plain)
    assert denied("gh issue create -R github.com/northerntechhq/libntech --title x", plain)
    assert not denied("gh issue create -R cfengine-contrib/core --title x", plain)
    assert not denied("gh issue create -R djbclark/cfengine --title x", plain)


# ---- compound commands, quoting, substitutions ----------------------------------------------------------------


@pytest.mark.parametrize("command", [
    "cd /tmp && gh pr create -R cfengine/core -t x",
    "echo hi; gh issue comment -R cfengine/core 1 -b x",
    "true || gh issue close -R cfengine/core 1",
    "echo x | gh pr comment 1 -R cfengine/core -F -",
    "echo $(gh pr create -R cfengine/core -t x)",
    "echo \"$(gh pr create -R cfengine/core -t x)\"",
    "echo `gh pr create -R cfengine/core -t x`",
    "bash -c 'gh pr create -R cfengine/core -t x'",
    "bash -lc \"gh issue comment 1 -R cfengine/core -b it's\"",
    "eval 'gh pr create -R cfengine/core -t x'",
    "timeout 60 gh pr create -R cfengine/core -t x",
    "env FOO=1 gh pr create -R cfengine/core -t x",
    "rtk gh pr create -R cfengine/core -t x",
    "/opt/homebrew/bin/gh pr create -R cfengine/core -t x",
    "echo a | xargs -I{} gh issue comment {} -R cfengine/core -b x",
    "(gh pr create -R cfengine/core -t x)",
    "echo it's; gh pr create -R cfengine/core -t x",                      # unbalanced quote: lenient split
    "gh pr create -R cfengine/core \\\n  --title x",
    "cat <<'EOF' | bash\ngh pr create -R cfengine/core -t x\nEOF",
])
def test_compound_forms_are_still_denied(plain, command):
    assert denied(command, plain)


@pytest.mark.parametrize("command", [
    "cd /tmp && gh pr create -R djbclark/core -t x",
    "echo 'gh pr create -R cfengine/core' > note.txt",
    "echo gh pr create -R cfengine/core",       # not a gh invocation; the shell word is echo
    "git commit -m \"gh pr create -R cfengine/core\"",
    "cat <<'EOF' > note.md\ngh pr create -R cfengine/core -t x\nit's data\nEOF\nls",
    "rg 'cfengine/core' docs/ | head",
    "gh pr view 5 -R cfengine/core | head",
    "gh pr list -R cfengine/core --json number --jq '.[].number'",
])
def test_data_mentions_and_reads_pass(plain, command):
    assert not denied(command, plain)


def test_cd_into_a_gated_checkout_moves_the_cwd(core_fork, plain):
    assert denied("cd %s && gh pr create --title x" % core_fork, plain)
    assert denied("cd %s; gh issue comment 1 -b x" % core_fork, plain)
    assert not denied("cd %s && gh pr create --title x" % plain, core_fork)


def test_shell_variable_target_with_gated_owner_elsewhere(plain):
    assert denied("R=cfengine/core; gh issue comment 5 -R $R -b x", plain)
    assert not denied("R=djbclark/core; gh issue comment 5 -R $R -b x", plain)


# ---- git push -------------------------------------------------------------------------------------------------


def test_git_push_from_a_libntech_worktree(libntech):
    assert denied("git push", libntech)
    assert denied("git push origin main", libntech)
    assert denied("git push -u origin HEAD", libntech)
    assert denied("git -C %s push" % libntech, libntech.parent)
    assert denied("cd %s && git push --force-with-lease" % libntech, libntech.parent)
    assert not denied("git push fork main", libntech)
    assert not denied("git push -u fork HEAD", libntech)
    assert not denied("git push -n origin main", libntech)
    assert not denied("git push --dry-run", libntech)


def test_git_push_by_url_and_repo_flag(plain, ours):
    assert denied("git push https://github.com/cfengine/core.git HEAD:refs/heads/x", plain)
    assert denied("git push git@github.com:NorthernTechHQ/libntech.git main", plain)
    assert denied("git push --repo=https://github.com/cfengine/core.git", plain)
    assert not denied("git push https://github.com/djbclark/core.git main", plain)
    assert not denied("git push origin main", ours)


def test_git_push_default_remote_follows_config(tmp_path):
    repo = make_repo(tmp_path / "r", origin="https://github.com/djbclark/core.git",
                     upstream="https://github.com/cfengine/core.git")
    assert not denied("git push", repo)
    subprocess.run(["git", "-C", str(repo), "config", "remote.pushDefault", "upstream"], check=True, env=ENV)
    assert denied("git push", repo)


def test_git_push_pushurl_is_what_counts(tmp_path):
    repo = make_repo(tmp_path / "r", origin="https://github.com/djbclark/core.git")
    subprocess.run(["git", "-C", str(repo), "config", "remote.origin.pushurl",
                    "https://github.com/cfengine/core.git"], check=True, env=ENV)
    assert denied("git push origin main", repo)


def test_git_reads_and_other_subcommands_pass(libntech):
    for cmd in ("git fetch origin", "git pull", "git status", "git log -3", "git remote -v",
                "git commit -m 'git push origin' --allow-empty", "echo git push origin"):
        assert not denied(cmd, libntech), cmd


# ---- Jira / Composio ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("command", [
    "curl -X POST https://northerntech.atlassian.net/rest/api/3/issue -d @b.json",
    "curl -sS -XPUT https://northerntech.atlassian.net/rest/api/3/issue/CFE-1 -H 'x: y'",
    "curl --request PATCH https://northerntech.atlassian.net/rest/api/3/issue/CFE-1",
    "curl -X DELETE https://x.atlassian.net/rest/api/3/issue/CFE-1",
    "curl https://northerntech.atlassian.net/rest/api/3/issue --data '{}'",
    "curl https://northerntech.atlassian.net/rest/api/3/issue --json @b.json",
    "curl -F file=@a https://northerntech.atlassian.net/rest/api/3/issue/CFE-1/attachments",
    "wget --post-data=x https://northerntech.atlassian.net/rest/api/3/issue",
    "http POST https://northerntech.atlassian.net/rest/api/3/issue a=b",
    "U=https://northerntech.atlassian.net; curl -X POST $U/rest/api/3/issue -d @b",
])
def test_atlassian_writes_are_denied(plain, command):
    assert denied(command, plain)


@pytest.mark.parametrize("command", [
    "curl https://northerntech.atlassian.net/rest/api/3/search/jql?jql=x",
    "curl -s https://northerntech.atlassian.net/rest/api/2/issue/CFE-4736?fields=status,resolution",
    "curl -G https://northerntech.atlassian.net/rest/api/3/search/jql --data-urlencode 'jql=project=CFE'",
    "curl -X GET https://northerntech.atlassian.net/rest/api/3/issue/CFE-1",
    "curl -X POST https://example.com/hook -d x",
    "curl -X POST https://example.com/hook -d x; echo https://x.atlassian.net",
    "http GET https://northerntech.atlassian.net/rest/api/3/issue/CFE-1",
])
def test_atlassian_reads_and_other_hosts_pass(plain, command):
    assert not denied(command, plain)


def test_composio_jira_write(plain):
    assert denied("composio execute JIRA_CREATE_ISSUE --params x", plain)
    assert denied("npx composio actions run JIRA_ADD_COMMENT -p x", plain)
    assert not denied("composio execute JIRA_GET_ISSUE --params x", plain)
    assert not denied("composio execute GITHUB_CREATE_ISSUE --params x", plain)
    assert denied("", plain, tool="mcp__composio__COMPOSIO_MULTI_EXECUTE_TOOL",
                  tool_input={"tools": [{"tool_slug": "JIRA_CREATE_ISSUE", "arguments": {}}]})
    assert not denied("", plain, tool="mcp__composio__COMPOSIO_MULTI_EXECUTE_TOOL",
                      tool_input={"tools": [{"tool_slug": "JIRA_GET_ISSUE", "arguments": {}}]})


# ---- hook contract --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["ls -la", "git status", "rg -n foo docs/", "echo hi && make test",
                                     "python3 -c 'print(1)'", "sed -n 1p f", ""])
def test_unrelated_commands_emit_nothing(core_fork, command):
    assert run(command, core_fork) is None


def test_malformed_input_and_other_tools_emit_nothing(plain):
    assert run("", plain, stdin="not json") is None
    assert run("", plain, stdin="") is None
    assert run("", plain, stdin="[1,2]") is None
    assert run("", plain, stdin=json.dumps({"tool_name": "Bash"})) is None
    assert run("", plain, stdin=json.dumps({"tool_name": "Bash", "tool_input": {"command": 5}})) is None
    assert run("gh pr create -R cfengine/core", plain, tool="Read",
               tool_input={"file_path": "gh pr create -R cfengine/core"}) is None


def test_operator_off_switch(plain):
    env = dict(ENV, UPSTREAM_REVIEW_GATE_OFF="1")
    assert run("gh pr create -R cfengine/core -t x", plain, env=env) is None
    # an assignment inside the command is not the operator's switch
    assert denied("UPSTREAM_REVIEW_GATE_OFF=1 gh pr create -R cfengine/core -t x", plain)


def test_reason_names_target_and_how_to_proceed(plain):
    out = run("gh api -X POST repos/cfengine/core/issues -f title=x", plain)
    reason = out["permissionDecisionReason"]
    assert "cfengine/core" in reason and "djbclark" in reason and "UPSTREAM_REVIEW_GATE_OFF" in reason
    assert "title=x" not in reason                                  # the payload is not echoed
