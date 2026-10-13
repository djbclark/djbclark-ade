#!/usr/bin/env python3
"""Serial benchmark of an OpenAI-compatible LLM server (built for SIPB LLMs) as an
agentic-coding backend.

Per model: direct probes (cold time to first token, decode speed, a ~10k-token prefill
twice for cache behaviour), then task A ("fizz": fix a two-bug repo, run tests, commit) a
few times, then task B ("wordstats": a five-phase build) if task A passed. Tasks are driven
through an agent runner (default: `acp-run crush`) and checked by running the tests
ourselves, never by trusting the agent's own report.

Everything is strictly serial: the SIPB server loads one model at a time, so never run two
of these at once and never run this against a shared server in a loop.

Results are appended to RESULTS (one JSON object per line); `summary` prints a table.

  SIPB_API_KEY=sk-...  bench.py run --models qwen3.5:27b,gemma4:26b
  bench.py run --models qwen3.5:27b --dry-run        # show the plan, touch nothing
  bench.py summary                                   # markdown table from results.jsonl

See SKILL.md for setup (API key, proxy, agent runner) and how to read the numbers.
"""
import argparse, json, os, re, shlex, shutil, statistics, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TASKS = os.path.join(HERE, "tasks")
O = os.path.expanduser(os.environ.get("SIPB_BENCH_DIR", "~/.local/state/sipb-bench"))
BASE = os.environ.get("SIPB_BASE", "https://llms-dev-1.mit.edu/api").rstrip("/")
RC = os.path.expanduser(os.environ.get("CRUSH_RC", "~/.config/crush/crushrc"))
# Model families that stream reasoning (so crush is told --can-reason and --think works).
REASONERS = ("qwen3.5", "qwen3.6", "qwen3.7", "qwen3.8", "gpt-oss", "deepseek-r1", "gemma4")
DEFAULT_RUNNER = "acp-run crush -C {dir} -p {prompt} --timeout {cap} --log {log}"

# Optional: the small coding + sysadmin battery (each task has a Python verifier).
try:
    sys.path.insert(0, HERE)
    import essentials  # noqa: E402
except Exception:  # noqa: BLE001
    essentials = None


def key():
    """API key from $SIPB_API_KEY, else the first sk- token in the crush config. Never printed."""
    k = os.environ.get("SIPB_API_KEY")
    if k:
        return k.strip()
    try:
        return re.search(r"(sk-[A-Za-z0-9_-]+)", open(RC).read()).group(1)
    except Exception:
        sys.exit("no API key: set SIPB_API_KEY (Open WebUI: Settings, Account, API keys)")


def status(msg):
    os.makedirs(O, exist_ok=True)
    with open(f"{O}/status.txt", "w") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


def record(d):
    d["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    d["load1"] = os.getloadavg()[0]
    os.makedirs(O, exist_ok=True)
    with open(f"{O}/results.jsonl", "a") as f:
        f.write(json.dumps(d) + "\n")


def stream(model, prompt, max_tokens, effort=None, timeout=400):
    """Return (ttft, total, n_chunks, error). Never prints the key."""
    body = {"model": model, "stream": True, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]}
    if effort:
        body["reasoning_effort"] = effort
    req = urllib.request.Request(BASE + "/chat/completions", json.dumps(body).encode(),
                                 {"Authorization": "Bearer " + key(), "Content-Type": "application/json"})
    t0 = time.time(); ttft = None; n = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for line in r:
                if not line.startswith(b"data: ") or line.startswith(b"data: [DONE]"):
                    continue
                try:
                    d = json.loads(line[6:])
                    delta = (d.get("choices") or [{}])[0].get("delta") or {}
                except Exception:
                    continue
                if delta.get("content") or delta.get("reasoning_content") or delta.get("reasoning"):
                    if ttft is None:
                        ttft = time.time() - t0
                    n += 1
        return ttft, time.time() - t0, n, None
    except Exception as e:
        return ttft, time.time() - t0, n, str(e)[:200]


def probes(label, model, effort):
    status(f"{label}: probe cold")
    r = {"kind": "probe", "combo": label, "model": model}
    t, tot, n, err = stream(model, "Reply with exactly: OK", 8, effort)
    r.update(cold_ttft=t, cold_total=tot, cold_err=err)
    if err:
        record(r); return False
    status(f"{label}: probe decode")
    t, tot, n, err = stream(model, "Count from 1 to 150 separated by single spaces. Output only the numbers.", 400, effort)
    r.update(decode_ttft=t, decode_total=tot, decode_chunks=n, decode_err=err,
             decode_cps=(n / (tot - t) if t and tot > t else None))
    big = ("The quick brown fox jumps over the lazy dog. " * 900) + "\nSay OK."
    for i in (1, 2):
        status(f"{label}: probe prefill {i}")
        t, tot, n, err = stream(model, big, 4, effort, timeout=600)
        r.update({f"prefill{i}_ttft": t, f"prefill{i}_err": err})
    record(r)
    return True


def pin_crush_data_model(model):
    """acp-run's crush forces CRUSH_GLOBAL_DATA=~/.local/share/crush-acp, whose
    crush.json `models` overrides the per-run crushrc; point it at the model under
    test for the run (returns a restore callable). Without this the run silently
    goes to whatever model that shared file holds (here, an Anthropic model) and
    the measured `providers` is wrong."""
    d = os.path.expanduser("~/.local/share/crush-acp")
    os.makedirs(d, exist_ok=True)
    path = f"{d}/crush.json"
    try:
        old = open(path).read()
    except OSError:
        old = None
    try:
        j = json.loads(old) if old else {}
    except ValueError:
        j = {}
    j.setdefault("models", {})["large"] = {"model": model, "provider": "sipb-llms"}
    j["models"]["small"] = {"model": model, "provider": "sipb-llms"}
    with open(path, "w") as f:
        f.write(json.dumps(j))

    def restore():
        if old is None:
            try:
                os.remove(path)
            except OSError:
                pass
        else:
            with open(path, "w") as f:
                f.write(old)
    return restore


def make_rc(model, think, effort, dest):
    """Copy the user's crushrc, replace its model add/large/small lines, optionally set effort."""
    text = open(RC).read()
    lines = []; buf = ""
    for ln in text.split("\n"):          # join backslash continuations
        buf = buf + "\n" + ln if buf else ln
        if buf.rstrip().endswith("\\"):
            continue
        lines.append(buf); buf = ""
    out = []
    for ln in lines:
        if re.match(r"\s*model\s+(add|large|small)\b", ln):
            continue
        if effort and "--extra-body" in ln:
            ln = re.sub(r'"reasoning_effort":"[a-z]+"', f'"reasoning_effort":"{effort}"', ln)
        out.append(ln)
    reason = "true" if model.startswith(REASONERS) else "false"
    out.append(f'model add sipb-llms/{model} --name "{model}" --can-reason {reason} --context-window 32768 --default-max-tokens 8192')
    out.append(f"model large sipb-llms/{model}" + (" --think" if think else ""))
    out.append(f"model small sipb-llms/{model}")
    os.makedirs(f"{dest}/crush", exist_ok=True)
    with open(f"{dest}/crush/crushrc", "w") as f:
        f.write("\n".join(out) + "\n")
    os.chmod(f"{dest}/crush/crushrc", 0o600)


def sh(cmd, cwd, timeout=120):
    p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr)


def run_task(*args):
    try:
        return run_task_inner(*args)
    except Exception as e:
        record({"kind": "task", "combo": args[0], "task": args[4], "pass": False,
                "harness_error": str(e)[:300], "secs": None, "tools": None, "thought_chunks": None, "stop": None})
        return False


def run_task_inner(label, model, think, effort, task, cap, prompt_file, rules, extra_args, runner):
    run = f"{label}-{task}-{int(time.time())}"
    d = f"{O}/runs/{run}"
    proj = f"{d}/proj"; xdg = f"{d}/xdg"; xdgd = f"{d}/xdgdata"
    os.makedirs(proj)
    sh("git init -q && git config user.email t@t && git config user.name t", proj)
    if task.startswith("fizz"):
        for f in os.listdir(f"{TASKS}/fizz-template"):
            if f.endswith(".py"):
                shutil.copy(f"{TASKS}/fizz-template/{f}", proj)
        sh("git add -A && git commit -qm init", proj)
    env = dict(os.environ)
    crush = runner is DEFAULT_RUNNER
    restore = None
    if crush:                                     # private crush config + data dir per run
        make_rc(model, think, effort, xdg)
        restore = pin_crush_data_model(model)
        if rules:
            shutil.copy(rules, f"{xdg}/crush/CRUSH.md")
        os.makedirs(f"{xdgd}/crush", exist_ok=True)
        gp = os.path.expanduser("~/.local/share/crush/providers.json")
        if os.path.exists(gp):
            shutil.copy(gp, f"{xdgd}/crush/providers.json")
        env.update(XDG_CONFIG_HOME=xdg, XDG_DATA_HOME=xdgd)
    else:                                         # custom runner: it must pick the model itself
        env.update(SIPB_MODEL=model, SIPB_THINK="1" if think else "0", SIPB_EFFORT=effort or "")
        if rules:
            shutil.copy(rules, f"{proj}/AGENTS.md")
    prompt = open(prompt_file).read()
    cmd = [a.replace("{dir}", proj).replace("{prompt}", prompt).replace("{cap}", str(cap))
            .replace("{log}", f"{d}/log.jsonl") for a in shlex.split(runner)] + list(extra_args)
    status(f"{label}: {task} running")
    t0 = time.time()
    try:
        p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=cap + 90)
        err = p.stderr[-600:]; rc = p.returncode
    except subprocess.TimeoutExpired:
        err = "harness-timeout"; rc = 124
    if restore:
        restore()
    secs = time.time() - t0
    m = re.search(r"stop=(\S+) secs=([\d.]+) tools=(\d+)", err)     # acp-run's summary line
    thoughts = 0
    names = {}
    try:
        for ln in open(f"{d}/log.jsonl"):
            r = json.loads(ln)
            if r.get("kind") == "update":
                u = r["data"].get("sessionUpdate")
                if u == "agent_thought_chunk": thoughts += 1
                if u == "tool_call":
                    t = (r["data"].get("title") or "?").split()[0]
                    names[t] = names.get(t, 0) + 1
    except Exception:
        pass
    provs = set()
    try:                                          # which provider really served the run
        provs = set(re.findall(r'"provider":"([^"]+)"', open(f"{proj}/.crush/logs/crush.log").read()))
    except Exception:
        pass
    _, cnt = sh("git rev-list --count HEAD 2>/dev/null || echo 0", proj)
    ncommits = int((cnt.strip().split() or ["0"])[0])
    if task.startswith("fizz"):
        urc, _out = sh("python3 -m unittest 2>&1", proj)
        res = {"tests_ok": urc == 0, "committed": ncommits >= 2}
        res["pass"] = res["tests_ok"] and res["committed"]
    else:
        urc, out = sh("python3 -m unittest discover 2>&1", proj)
        mt = re.search(r"Ran (\d+) tests", out)
        notes = open(f"{proj}/NOTES.md").read() if os.path.exists(f"{proj}/NOTES.md") else ""
        cli = f"{proj}/wordstats/cli.py"
        res = {"tests_ok": urc == 0, "ntests": int(mt.group(1)) if mt else 0, "committed": ncommits >= 1,
               "curl200": "200" in notes,
               "stopwords": os.path.exists(cli) and "stopwords" in open(cli).read()}
        res["pass"] = bool(res["tests_ok"] and res["committed"] and res["ntests"] >= 16)
    vm = re.search(r"verify=(\w+) verify_attempts=(\d+)", err)
    record({"kind": "task", "combo": label, "model": model, "think": think, "effort": effort, "task": task,
            "secs": round(secs, 1), "rc": rc, "stop": m.group(1) if m else None,
            "tools": int(m.group(3)) if m else None, "thought_chunks": thoughts, "tool_names": names,
            "err_tail": err[-200:] if rc else "", "providers": sorted(provs),
            "verify": vm.groups() if vm else None, "rules": bool(rules), "extra": extra_args, **res})
    shutil.rmtree(xdg, ignore_errors=True)        # holds the API key
    shutil.rmtree(xdgd, ignore_errors=True)
    return res["pass"]


def run_essentials(label, model, think, effort, runner, rules, extra, only=None):
    """Run each essentials task once; one row per task; check the artifact, not the
    agent's report. Returns (passed, total)."""
    passed = 0
    tasks = [t for t in essentials.TASKS if not only or t["name"] in only]
    for task in tasks:
        run = f"{label}-ess-{task['name']}-{int(time.time())}"
        d = f"{O}/runs/{run}"
        proj, xdg, xdgd = f"{d}/proj", f"{d}/xdg", f"{d}/xdgdata"
        os.makedirs(proj)
        essentials.seed_project(proj, task)
        env = dict(os.environ)
        restore = None
        if runner is DEFAULT_RUNNER:
            make_rc(model, think, effort, xdg)
            restore = pin_crush_data_model(model)
            if rules:
                shutil.copy(rules, f"{xdg}/crush/CRUSH.md")
            os.makedirs(f"{xdgd}/crush", exist_ok=True)
            gp = os.path.expanduser("~/.local/share/crush/providers.json")
            if os.path.exists(gp):
                shutil.copy(gp, f"{xdgd}/crush/providers.json")
            env.update(XDG_CONFIG_HOME=xdg, XDG_DATA_HOME=xdgd)
        else:
            env.update(SIPB_MODEL=model, SIPB_THINK="1" if think else "0", SIPB_EFFORT=effort or "")
            if rules:
                shutil.copy(rules, f"{proj}/AGENTS.md")
        cmd = [a.replace("{dir}", proj).replace("{prompt}", task["prompt"]).replace("{cap}", "300")
               .replace("{log}", f"{d}/log.jsonl") for a in shlex.split(runner)] + list(extra)
        status(f"{label}: essentials {task['name']} running")
        t0 = time.time()
        try:
            p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=390)
            err, rc = p.stderr[-600:], p.returncode
        except subprocess.TimeoutExpired:
            err, rc = "harness-timeout", 124
        if restore:
            restore()
        secs = time.time() - t0
        try:
            ok, detail = task["verify"](proj)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"verify-error: {e}"
        provs = set()
        try:
            provs = set(re.findall(r'"provider":"([^"]+)"', open(f"{proj}/.crush/logs/crush.log").read()))
        except Exception:
            pass
        shutil.rmtree(xdg, ignore_errors=True)
        shutil.rmtree(xdgd, ignore_errors=True)
        record({"kind": "essentials", "combo": label, "model": model, "think": think,
                "effort": effort, "task": task["name"], "pass": bool(ok), "secs": round(secs, 1),
                "rc": rc, "detail": str(detail)[:200], "providers": sorted(provs),
                "err_tail": err[-150:] if rc else ""})
        passed += bool(ok)
    return passed, len(tasks)


def build_combos(models, modes):
    """label -> (model, think, effort). Default mode: think for reasoning families, nothink otherwise."""
    out = {}
    for m in models:
        ms = modes or (["think", "nothink"] if m.startswith(REASONERS) else ["nothink"])
        for mode in ms:
            think = mode == "think"
            effort = ("high" if think else "none") if m.startswith(REASONERS) else None
            out[f"{m}-{mode}"] = (m, think, effort)
    return out


def cmd_run(a):
    combos = build_combos([m for m in a.models.split(",") if m], [x for x in a.modes.split(",") if x])
    extra = a.extra.split("|") if a.extra else []
    runner = a.runner or DEFAULT_RUNNER
    rules = os.path.join(TASKS, "rules.md") if a.rules else None
    wordstats = os.path.join(TASKS, a.wordstats)
    if a.dry_run:
        print(f"results dir {O}\nbase {BASE}\nrunner {runner}\nrules {rules}\nwordstats {wordstats} cap {a.wordstats_cap}s")
        for label, (m, think, eff) in combos.items():
            print(f"  {label}: model={m} think={think} effort={eff}; probes={not a.no_probe}; "
                  f"fizz x{a.fizz}; wordstats={'forced' if a.force_wordstats else 'if fizz passes' if not a.fizz_only else 'no'}")
        return
    if os.path.exists(f"{O}/DONE-{a.tag}"):
        return
    probed = set()
    for label, (model, think, effort) in combos.items():
        if not a.no_probe and model not in probed:
            probed.add(model)
            if not probes(label, model, effort):
                record({"kind": "skip", "combo": label, "why": "probe failed"}); continue
        if a.probes_only:
            continue
        passes = 0
        for i in range(a.fizz):
            passes += run_task(label, model, think, effort, f"fizz{i+1}", 300, f"{TASKS}/fizz.txt", rules, extra, runner)
        if a.fizz_only:
            continue
        if passes or a.force_wordstats:
            run_task(label, model, think, effort, "wordstats", a.wordstats_cap, wordstats, rules, extra, runner)
        else:
            record({"kind": "skip", "combo": label, "why": "fizz failed twice"})
    status("finished")
    open(f"{O}/DONE-{a.tag}", "w").write(time.strftime("%c") + "\n")


def cmd_essentials(a):
    if essentials is None:
        sys.exit("essentials.py not found next to bench.py")
    combos = build_combos([m for m in a.models.split(",") if m], [x for x in a.modes.split(",") if x])
    extra = a.extra.split("|") if a.extra else []
    runner = a.runner or DEFAULT_RUNNER
    rules = os.path.join(TASKS, "rules.md") if a.rules else None
    only = set(x for x in a.only.split(",") if x)
    if a.dry_run:
        for label, (m, think, eff) in combos.items():
            print(f"  {label}: {len(essentials.TASKS)} essentials tasks; runner {runner}")
        return
    if os.path.exists(f"{O}/DONE-ess-{a.tag}"):
        return
    for label, (model, think, effort) in combos.items():
        passed, total = run_essentials(label, model, think, effort, runner, rules, extra, only)
        print(f"{label}: {passed}/{total} essentials passed")
    status("finished")
    open(f"{O}/DONE-ess-{a.tag}", "w").write(time.strftime("%c") + "\n")


def cmd_summary(a):
    rows = [json.loads(l) for l in open(f"{O}/results.jsonl") if l.strip()]
    by = {}
    for r in rows:
        c = r.get("combo")
        if not c or r.get("kind") not in ("probe", "task", "essentials") or r.get("invalid"):
            continue
        # a task/essentials row counts only if the run really went to this server's provider
        if r["kind"] in ("task", "essentials") and not a.all and r.get("providers") != ["sipb-llms"]:
            continue
        by.setdefault(c, {"probe": None, "fizz": [], "ws": [], "ess": []})
        if r["kind"] == "probe":
            by[c]["probe"] = r
        elif r["kind"] == "essentials":
            by[c]["ess"].append(r)
        elif r["task"].startswith("fizz"):
            by[c]["fizz"].append(r)
        else:
            by[c]["ws"].append(r)

    def f(x, nd=1):
        return "-" if x is None else f"{x:.{nd}f}"

    def tasks(rs):
        if not rs:
            return "-"
        ok = [r["secs"] for r in rs if r.get("pass") and r.get("secs")]
        return f"{sum(1 for r in rs if r.get('pass'))}/{len(rs)}" + (f", median {statistics.median(ok):.0f} s" if ok else "")

    print("| combo | cold TTFT s | decode chunks/s | 10k prefill s (1st / repeat) | task A | task B | essentials |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for c, v in by.items():
        p = v["probe"] or {}
        print(f"| {c} | {f(p.get('cold_ttft'))} | {f(p.get('decode_cps'), 0)} | "
              f"{f(p.get('prefill1_ttft'))} / {f(p.get('prefill2_ttft'))} | {tasks(v['fizz'])} | {tasks(v['ws'])} | {tasks(v['ess'])} |")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="probes + tasks for the given models, strictly serial")
    r.add_argument("--models", required=True, help="comma-separated server model ids, e.g. qwen3.5:27b,gemma4:26b")
    r.add_argument("--modes", default="", help="think,nothink (default: both for reasoning families, nothink for others)")
    r.add_argument("--fizz", type=int, default=2, help="task A repetitions")
    r.add_argument("--wordstats", default="wordstats-lean.txt", help="task B prompt file under tasks/ (wordstats.txt = full)")
    r.add_argument("--wordstats-cap", type=int, default=600, help="task B time cap in seconds")
    r.add_argument("--no-probe", action="store_true")
    r.add_argument("--rules", action="store_true", help="give the agent tasks/rules.md (short working rules for small models)")
    r.add_argument("--extra", default="", help="extra runner args, '|'-separated, e.g. '--verify|python3 -m unittest discover'")
    r.add_argument("--runner", help=f"agent runner command; placeholders {{dir}} {{prompt}} {{cap}} {{log}} (default: {DEFAULT_RUNNER})")
    r.add_argument("--force-wordstats", action="store_true", help="run task B even if task A failed")
    r.add_argument("--fizz-only", action="store_true")
    r.add_argument("--probes-only", action="store_true", help="speed probes only; no agent runner needed")
    r.add_argument("--tag", default="A", help="batch tag; a batch with DONE-<tag> present is skipped")
    r.add_argument("--dry-run", action="store_true", help="print the plan and exit; no requests")
    r.set_defaults(fn=cmd_run)
    e = sub.add_parser("essentials",
                       help="small coding+sysadmin battery (file/config/git/pipeline tasks), one pass per model")
    e.add_argument("--models", required=True, help="comma-separated server model ids, e.g. qwen3.6:35b-a3b-q4_K_M")
    e.add_argument("--modes", default="", help="think,nothink (default: both for reasoning families)")
    e.add_argument("--rules", action="store_true", help="give the agent tasks/rules.md")
    e.add_argument("--extra", default="", help="extra runner args, '|'-separated")
    e.add_argument("--runner", help=f"agent runner command (default: {DEFAULT_RUNNER})")
    e.add_argument("--tag", default="ess", help="batch tag; a finished batch (DONE-ess-<tag>) is skipped")
    e.add_argument("--only", default="", help="comma-separated task names to run (default: all)")
    e.add_argument("--dry-run", action="store_true")
    e.set_defaults(fn=cmd_essentials)
    s = sub.add_parser("summary", help="markdown table from results.jsonl (skips rows with \"invalid\": true)")
    s.add_argument("--all", action="store_true", help="also count task rows whose provider is not exactly sipb-llms")
    s.set_defaults(fn=cmd_summary)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
