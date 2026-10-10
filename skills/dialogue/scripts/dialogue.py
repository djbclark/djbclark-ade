#!/usr/bin/env python3
"""Multi-model dialogue runner: N models, fixed rounds, one artifact, one final-word model.

    dialogue.py [--run DIR] [--config FILE] <command> ...

Commands (the lead runs these; models never see the lead-only output):

    turn  <model> --phase P [--instruction F] [--timeout S] [--anonymise]
    round --phase P [--instruction F] [--timeout S] [--only m1,m2] [--skip m]
    final --phase P [--instruction F] [--timeout S] [--allow-legacy] [--judge MODEL]
    gate  [--allow-legacy]          # dry check of the final-word state-file gate
    prompt <model> --phase P [--final]   # build the prompt only (dry), print its path and size
    recover <model> --phase P --from FILE [--source task-summary]
    ledger [--all] [--by-needs]     # footers plus the replayed point state
    converged [--stall] [--cap]     # exit 0 when converged; prints converged_by
    folds                           # fold audit, lead-only
    lint [--turn N]                 # protocol checks over the transcript
    strip FILE                      # show what the transport-noise strip would remove
    costs                           # per-phase totals from costs.jsonl
    probe [model]                   # "Reply with exactly: OK" through every pinned route
    unused-ids                      # optional moderator list: evidence and sources never cited

The run folder holds `dialogue.json` (see references/run-config.example.json). With no
config file the read-only commands (ledger, converged, folds, lint, strip) work on
`<run>/dialogue/transcript.md` with the models inferred from the turn headers, so an
older run can be audited in place. Stdlib only; Python 3.9+.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Fixed prompt blocks (Grok 4.7 rulings 5.2 and 1.1/3.9/4.3, 2026-10-10)
# ---------------------------------------------------------------------------

PRIOR_ART_BLOCK = """# Mandatory turn shape (prior-art sentences; never drop these)

1. Open your turn with three lines, `AGREEMENTS:`, `CLASHES:` and `BLIND SPOTS:`, each naming the models and turn numbers.
2. List every clash with both positions and their turn numbers, unblended, never a midpoint.
3. Keep every qualification a model attached to a claim.
4. Use a transcript claim only when the state file or an evidence row contains it.
5. Write one `unresolved clash:` line for every disagreement you did not keep on both sides, with the turn numbers.
6. Never rewrite an evidence-backed claim into a midpoint its quote does not state: keep a side, or cut it and log the cut.
"""
PRIOR_ART_MARKERS = ["`AGREEMENTS:`, `CLASHES:` and `BLIND SPOTS:`", "unblended, never a midpoint",
                     "Keep every qualification", "state file or an evidence row",
                     "`unresolved clash:`", "keep a side, or cut it and log the cut"]

FOOTER_BLOCK = """# Footer contract (mandatory; the last lines of your turn; nothing after `NEXT:`)

```
REFUSED: <point_id> <class>: <one line>      (optional; only these classes: feeling, welfare-conclusion, invented-citation, foreign-edit)
SETTLED:
- <point_id> decided|tested closed_by=<E####|experiment path|ruling|rewrite>: <one line>
OPEN POINTS:
- <point_id> carried|refused: <one line> [needs: E-row|experiment|ruling] [conf: 0.0-1.0]
DISSENT: <your dissent in one line, or exactly "no remaining dissent after turn N">
NEXT: <one line: the work you expect next; it never skips a speaker>
```

Rules: `SETTLED: nothing new` and `OPEN POINTS: none` are allowed only when there is truly
nothing; a bet that is still unrun stays `carried`, never `none`. A point id is short and
stable (`P-12`, `OP-15a`); reuse the id when you answer someone else's point. `tested` needs
an experiment, `decided` a ruling or evidence row, `rewrite` a Decisions pass. An owned-section
flag, the `DISSENT:` line and the footer itself are never refusable. The script strips anything
after the `NEXT:` line and any narration before the `AGREEMENTS:` line before it appends the turn.
"""

INDEPENDENT_BLOCK = """# Independent draft

This phase is built without the transcript. Do not read the transcript, the turn files or
another model's notes before you post this turn: the point is an independent first position.
"""

RESIDENT_BLOCK = """# Team-resident documents (context only)

These files describe the resident. Cite them by file and section, never as an evidence id of
this run; they do not establish facts beyond what their own sections say.
"""

# ---------------------------------------------------------------------------
# Regexes
# ---------------------------------------------------------------------------

TURN_RE = re.compile(r"^## Turn (\d+) — ([\w.-]+) \(([^,]+), ([^)]+)\)\s*$", re.M)
TAIL_RE = re.compile(r"^## Citation footnotes\s*$", re.M)
HDR_FIELD_RE = re.compile(r"^(recovered_from|protocol_failure|route):\s*(.*)$")
LABEL_RE = re.compile(r"^(REFUSED|SETTLED|OPEN POINTS|DISSENT|NEXT):\s*(.*)$")
LEGACY_FOOTER_RE = re.compile(r"^(SETTLED|OPEN POINTS|NEXT):", re.M)
ITEM_RE = re.compile(r"^(?P<id>[A-Za-z][\w.-]*)\s+(?P<status>decided|tested|carried|refused)\b"
                     r"(?:\s+closed_by\s*[=:]\s*(?P<by>[^\s:]+))?\s*[:—–-]?\s*(?P<text>.*)$")
REFUSED_RE = re.compile(r"^(?P<id>[A-Za-z][\w.-]*)\s+(?P<cls>[\w-]+)\s*:\s*(?P<text>.*)$")
NEEDS_RE = re.compile(r"\[needs:\s*([^\]]+)\]")
CONF_RE = re.compile(r"\[conf:\s*([0-9.]+)\]")
EID_RE = re.compile(r"\bE\d{4}\b")
FENCE_RE = re.compile(r"^\s*```", re.M)
CHECKER_ALL_RE = re.compile(r"research_check\.py\b[^\n]*\ball\b")
QUOTA_RE = re.compile(r"usage limit|quota|rate.?limit|too many requests|\b429\b|resets? (at|in)", re.I)
NONE_WORDS = {"none", "nothing new", "nothing", "-", ""}
REFUSABLE = {"feeling", "welfare-conclusion", "invented-citation", "foreign-edit"}
DEFAULT_SUFFIXES = [
    r"\s*🌱\s*graft saved ~[\d,]+ tokens this turn.*$",
    r"\s*graft saved ~[\d,]+ tokens.*$",
    r"\s*Renamed this session.*$",
    r"\s*The prompt border.*$",
]
MAX_QUOTA_WAITS = 6
DEFAULT_WAIT = 1800
MAX_WAIT = 6 * 3600


def now() -> str:
    return dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")


def read(p: Path | None) -> str:
    return p.read_text(encoding="utf-8") if p and p.exists() else ""


def words(s: str) -> int:
    return len(s.split())


# ---------------------------------------------------------------------------
# Run configuration
# ---------------------------------------------------------------------------

class Run:
    def __init__(self, root: Path, cfg: dict[str, Any], has_config: bool):
        self.root = root
        self.cfg = cfg
        self.has_config = has_config
        p = lambda k, d: (root / cfg.get(k, d)).resolve()  # noqa: E731
        self.cwd = p("cwd", ".")
        self.transcript = p("transcript", "dialogue/transcript.md")
        self.turns_dir = p("turns_dir", "dialogue")
        self.prompts = p("prompts_dir", "prompts")
        self.phases_dir = p("phases_dir", "phases")
        self.prompt_out = p("prompt_out", ".prompts")
        self.lock = self.turns_dir / ".lock"
        self.costs = self.turns_dir / "costs.jsonl"
        self.state_file = (root / cfg["state_file"]).resolve() if cfg.get("state_file") else None
        self.artifacts = [(root / a).resolve() for a in cfg.get("artifacts", [])]
        self.context_docs = [(root / a).resolve() for a in cfg.get("context_docs", [])]
        self.protected = [(root / a).resolve() for a in cfg.get("protected_files", [])]
        self.evidence = (root / cfg["evidence_file"]).resolve() if cfg.get("evidence_file") else None
        self.sources = (root / cfg["sources_file"]).resolve() if cfg.get("sources_file") else None
        self.word_budget = int(cfg.get("word_budget", 40_000))
        self.opening = cfg.get("opening_line", "AGREEMENTS:")
        self.suffixes = [re.compile(s) for s in cfg.get("suffix_patterns", DEFAULT_SUFFIXES)]
        self.models: dict[str, dict[str, Any]] = cfg.get("models", {})
        order = list(cfg.get("order") or self.models.keys())
        if not order:  # no config: infer from the transcript headers
            for t in turns(read(self.transcript)):
                if t["model"] not in order:
                    order.append(t["model"])
        self.final_word = cfg.get("final_word") or (order[0] if order else "")
        # Grok 4.4: the final-word model speaks first in every round.
        self.order = ([self.final_word] if self.final_word else []) + [m for m in order if m != self.final_word]
        self.phases: list[dict[str, Any]] = cfg.get("phases", [])
        self.trial_from = cfg.get("trial_from_phase")
        self.optional: dict[str, Any] = cfg.get("optional", {})

    def phase(self, name: str) -> dict[str, Any]:
        for ph in self.phases:
            if ph.get("name") == name:
                return ph
        return {"name": name}

    def phase_index(self, name: str) -> int:
        for i, ph in enumerate(self.phases):
            if ph.get("name") == name:
                return i
        return -1

    def trial_enabled(self, phase: str) -> bool:
        if not self.trial_from:
            return False
        i, j = self.phase_index(phase), self.phase_index(self.trial_from)
        return i >= 0 and j >= 0 and i >= j and not self.phase(phase).get("independent")


def load_run(run_dir: str | None, config: str | None) -> Run:
    root = Path(run_dir or ".").resolve()
    cfg_path = Path(config).resolve() if config else None
    if cfg_path is None:
        for name in ("dialogue.json", "dialogue.toml"):
            if (root / name).exists():
                cfg_path = root / name
                break
    if cfg_path is None:
        return Run(root, {}, False)
    if cfg_path.suffix == ".toml":
        try:
            import tomllib  # Python 3.11+
        except ImportError:
            sys.exit(f"{cfg_path}: TOML needs Python 3.11+; use dialogue.json")
        cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    else:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    return Run(cfg_path.parent if not run_dir else root, cfg, True)


# ---------------------------------------------------------------------------
# Transcript and footer parsing
# ---------------------------------------------------------------------------

def turns(text: str) -> list[dict[str, Any]]:
    """Split the transcript into turns: [{n, model, phase, when, body, raw, fields}]."""
    tail = TAIL_RE.search(text)
    stop = tail.start() if tail else len(text)
    out = []
    ms = [m for m in TURN_RE.finditer(text) if m.start() < stop]
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else stop
        body = text[m.end():end].strip("\n")
        fields: dict[str, str] = {}
        lines = body.split("\n")
        k = 0
        while k < len(lines) and (HDR_FIELD_RE.match(lines[k]) or (fields and not lines[k].strip())):
            fm = HDR_FIELD_RE.match(lines[k])
            if fm:
                fields[fm.group(1)] = fm.group(2).strip()
            k += 1
        out.append({"n": int(m.group(1)), "model": m.group(2), "phase": m.group(3),
                    "when": m.group(4), "body": body, "raw": text[m.start():end], "fields": fields})
    return out


def _item(text: str, section: str) -> dict[str, Any]:
    text = text.strip().lstrip("-*").strip()
    text = re.sub(r"^\d+[.)]\s+", "", text)
    it: dict[str, Any] = {"id": None, "status": None, "by": None, "text": text,
                          "needs": None, "conf": None, "section": section}
    m = ITEM_RE.match(text)
    if m:
        it.update(id=m.group("id"), status=m.group("status"), by=m.group("by"), text=m.group("text"))
    nm, cm = NEEDS_RE.search(text), CONF_RE.search(text)
    if nm:
        it["needs"] = nm.group(1).strip()
    if cm:
        try:
            it["conf"] = float(cm.group(1))
        except ValueError:
            pass
    return it


def parse_footer(body: str) -> dict[str, Any]:
    """Parse the terminal footer. `terminal` is True when the turn ends at its NEXT line."""
    lines = body.rstrip().split("\n")
    f: dict[str, Any] = {"found": False, "terminal": False, "legacy": False, "refused": [], "settled": [],
                         "open": [], "dissent": None, "next": None, "text": "(no footer)", "after": "",
                         "open_none": False, "labels": []}
    idx_next = max((i for i, ln in enumerate(lines) if ln.startswith("NEXT:")), default=-1)
    if idx_next < 0:
        m = LEGACY_FOOTER_RE.search(body)
        if m:
            f["text"] = body[m.start():].strip()
        return f
    idx_set = max((i for i in range(idx_next) if lines[i].startswith("SETTLED:")), default=-1)
    start = idx_set if idx_set >= 0 else idx_next
    j = start - 1
    while j >= 0 and (not lines[j].strip() or lines[j].startswith("REFUSED:")):
        if lines[j].startswith("REFUSED:"):
            start = j
        j -= 1
    block = lines[start:idx_next + 1]
    f.update(found=True, text="\n".join(block).strip(), after="\n".join(lines[idx_next + 1:]).strip())
    f["terminal"] = not f["after"]
    section = None
    for ln in block:
        lm = LABEL_RE.match(ln)
        if lm:
            section, inline = lm.group(1), lm.group(2).strip()
            f["labels"].append(section)
            if section == "NEXT":
                f["next"] = inline
            elif section == "DISSENT":
                f["dissent"] = inline
            elif section == "REFUSED":
                rm = REFUSED_RE.match(inline)
                f["refused"].append({"id": rm.group("id") if rm else None,
                                     "cls": rm.group("cls") if rm else None, "text": inline})
            elif inline.lower().rstrip(".") in NONE_WORDS:
                if section == "OPEN POINTS":
                    f["open_none"] = True
            else:
                (f["settled"] if section == "SETTLED" else f["open"]).append(_item(inline, section))
        elif ln.strip() and section in ("SETTLED", "OPEN POINTS"):
            s = ln.strip()
            if s[:1] in "-*" or re.match(r"^\d+[.)]\s", s) or ITEM_RE.match(s):
                (f["settled"] if section == "SETTLED" else f["open"]).append(_item(s, section))
            else:  # continuation of the previous item
                lst = f["settled"] if section == "SETTLED" else f["open"]
                if lst:
                    lst[-1]["text"] += " " + s
        elif ln.strip() and section == "DISSENT":
            f["dissent"] = ((f["dissent"] or "") + " " + ln.strip()).strip()
    f["legacy"] = all(it["id"] is None for it in f["settled"] + f["open"]) and "DISSENT" not in f["labels"]
    if not f["open"]:
        f["open_none"] = True
    return f


def strip_noise(reply: str, opening: str | None, suffixes: list[re.Pattern[str]]) -> tuple[str, list[str], bool]:
    """Grok 4.1: drop narration before the opening line, everything after the NEXT line, and known
    same-line suffixes on the NEXT line. Returns (clean, removed pieces, fence_after_footer)."""
    removed: list[str] = []
    text = reply.strip("\n")
    if opening:
        k = text.find(opening)
        if k > 0 and text[:k].strip():
            removed.append("BEFORE OPENING LINE:\n" + text[:k].rstrip())
            text = text[k:]
    lines = text.split("\n")
    idx = max((i for i, ln in enumerate(lines) if ln.startswith("NEXT:")), default=-1)
    fence_after = False
    if idx >= 0:
        after = "\n".join(lines[idx + 1:])
        if after.strip():
            fence_after = bool(FENCE_RE.search(after))
            removed.append("AFTER NEXT LINE:\n" + after.strip("\n"))
        nxt = lines[idx]
        for rx in suffixes:
            m = rx.search(nxt)
            if m and m.start() > len("NEXT:"):
                removed.append("SAME-LINE SUFFIX:\n" + nxt[m.start():].strip())
                nxt = nxt[:m.start()].rstrip()
        lines = lines[:idx] + [nxt]
    return "\n".join(lines).rstrip() + "\n", removed, fence_after


def footer_failures(body: str) -> list[str]:
    """Hard protocol failures (Grok 1.2, 3.9, 4.3): the turn is not appended."""
    f = parse_footer(body)
    bad = []
    if not f["found"]:
        return ["no terminal footer: no NEXT: line"]
    if not f["terminal"]:
        bad.append("text after the NEXT: line")
    for lab in ("SETTLED", "OPEN POINTS", "DISSENT", "NEXT"):
        if lab not in f["labels"]:
            bad.append(f"footer label missing: {lab}:")
    d = (f["dissent"] or "").strip().lower().rstrip(".")
    if "DISSENT" in f["labels"] and (d in ("none", "") ):
        bad.append('DISSENT: bare "none" (allowed only as "no remaining dissent after turn N")')
    for r in f["refused"]:
        if (r["cls"] or "") not in REFUSABLE:
            bad.append(f"REFUSED class not refusable: {r['text'][:80]}")
    return bad


# ---------------------------------------------------------------------------
# Point state replay (Grok 1.1, 1.6, 4.3)
# ---------------------------------------------------------------------------

def replay(run: Run, ts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    pts: dict[str, dict[str, Any]] = {}
    final_phases = {ph["name"] for ph in run.phases if ph.get("final_word_only")}
    for t in ts:
        f = parse_footer(t["body"])
        open_ids = set()
        for it in f["open"]:
            if not it["id"]:
                continue
            p = pts.setdefault(it["id"], {"id": it["id"], "raised_by": t["model"], "raised_turn": t["n"],
                                          "history": [], "awaiting": set()})
            p.update(status=it["status"] or "carried", text=it["text"], needs=it["needs"], conf=it["conf"],
                     by=None, frozen=False)
            p["awaiting"] = set()
            p["history"].append((t["n"], t["model"], p["status"], None))
            open_ids.add(it["id"])
        for r in f["refused"]:
            if r["id"]:
                p = pts.setdefault(r["id"], {"id": r["id"], "raised_by": t["model"], "raised_turn": t["n"],
                                             "history": [], "awaiting": set()})
                p.update(status="refused", text=r["text"], frozen=False, by=None)
                p["history"].append((t["n"], t["model"], "refused", None))
                open_ids.add(r["id"])
        for it in f["settled"]:
            if not it["id"] or it["id"] in open_ids:
                continue
            p = pts.setdefault(it["id"], {"id": it["id"], "raised_by": t["model"], "raised_turn": t["n"],
                                          "history": [], "awaiting": set()})
            was_settled = p.get("status") in ("decided", "tested") and p.get("by_model") != t["model"]
            p.update(status=it["status"] or "decided", by=it["by"], text=it["text"], by_model=t["model"])
            p["history"].append((t["n"], t["model"], p["status"], it["by"]))
            if t["model"] == run.final_word and t["phase"] in final_phases:
                p["awaiting"], p["frozen"] = set(), True
            elif not was_settled:
                p["awaiting"] = set(run.order) - {t["model"]}
                p["frozen"] = False
            else:
                p["awaiting"].discard(t["model"])
        # Every other id this speaker leaves unreopened counts as its invariant check passing.
        for pid, p in pts.items():
            if pid not in open_ids and p.get("status") in ("decided", "tested"):
                p["awaiting"].discard(t["model"])
                if not p["awaiting"]:
                    p["frozen"] = True
    return pts


def unresolved(pts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in pts.values() if p.get("status") in ("carried", "refused")]


def last_of(ts: list[dict[str, Any]], model: str) -> dict[str, Any] | None:
    for t in reversed(ts):
        if t["model"] == model:
            return t
    return None


def last_round(run: Run, ts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    k = max(1, len(run.order))
    return ts[-k:]


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

def transcript_for_prompt(run: Run, anonymise: bool = False) -> str:
    ts = turns(read(run.transcript))
    if not ts:
        return "(The transcript is empty: you are the first speaker.)"
    total = 0
    keep: list[dict[str, Any]] = []
    for t in reversed(ts):
        total += words(t["raw"])
        if total > run.word_budget and keep:
            break
        keep.insert(0, t)
    omitted = ts[: len(ts) - len(keep)]
    parts = []
    if omitted:
        parts.append(f"(Earlier turns 1-{omitted[-1]['n']} omitted for length; their footers:)\n")
        for t in omitted:
            parts.append(f"### Turn {t['n']} — {t['model']} ({t['phase']})\n{parse_footer(t['body'])['text']}\n")
        parts.append("\n---\n")
    parts.extend(t["raw"].rstrip("\n") + "\n" for t in keep)
    out = "\n".join(parts)
    return anonymise_text(run, out) if anonymise else out


def anonymise_text(run: Run, text: str) -> str:
    """Optional critique sub-step (Grok 3.10): model names become Speaker A, B, C."""
    for i, m in enumerate(run.order):
        alias = f"Speaker {chr(65 + i)}"
        names = [m] + [run.models.get(m, {}).get("label", "")]
        for nm in sorted({n for n in names if n}, key=len, reverse=True):
            text = re.sub(rf"\b{re.escape(nm)}\b", alias, text, flags=re.I)
    return text


def rounds_text(ts: list[dict[str, Any]]) -> str:
    return "\n".join(t["raw"].rstrip("\n") + "\n" for t in ts) or "(no turns yet)"


def ids_text(us: list[dict[str, Any]]) -> str:
    if not us:
        return "(none)"
    return "\n".join(f"- {p['id']} {p['status']} (raised turn {p['raised_turn']} by {p['raised_by']}): {p.get('text', '')}"
                     for p in us)


def phase_instruction(run: Run, phase: str, instruction: Path | None) -> str:
    inst = instruction or (run.phases_dir / f"{phase}.md")
    if not inst.exists():
        sys.exit(f"no phase instruction: {inst}")
    text = read(inst)
    # Grok 4.6: no evidence-rewriting checker inside a dialogue turn.
    if CHECKER_ALL_RE.search(text) and not run.phase(phase).get("research_final"):
        sys.exit(f"{inst}: asks for `research_check.py ... all`, which rewrites evidence.jsonl; use "
                 "`quotes --no-update`, `numbers`, `claims`, `gate`, or mark the phase research_final "
                 "(protected files are snapshotted and restored either way)")
    return text


def head_parts(run: Run, model: str, phase: str, n: int) -> list[str]:
    label = run.models.get(model, {}).get("label", model)
    return [
        f"# Dialogue turn {n}: you are **{model}** ({label}), phase **{phase}**, {now()}\n\n"
        f"Working directory: {run.cwd} (relative paths are relative to it). Speaking order every "
        f"round: {', '.join(run.order)}; the final word belongs to {run.final_word}.\n",
        read(run.prompts / "common.md"),
        read(run.prompts / f"{model}.md"),
        PRIOR_ART_BLOCK,
        FOOTER_BLOCK,
    ]


def docs_text(paths: list[Path], title: str) -> list[str]:
    out = []
    for p in paths:
        out.append(f"# {title}: {p}\n\n" + (read(p) or "(missing or empty)"))
    return out


def build_prompt(run: Run, model: str, phase: str, instruction: Path | None, mode: str = "normal",
                 anonymise: bool = False) -> str:
    """mode: normal | final | trial. Independent phases (Grok 3.1) omit the transcript."""
    n = next_turn_number(run)
    ts = turns(read(run.transcript))
    inst = phase_instruction(run, phase, instruction)
    lead = read(run.prompts / "lead-notes.md")
    parts = head_parts(run, model, phase, n)
    parts.append("# Instruction for this phase\n\n" + inst)
    if lead.strip():
        parts.append("# Notes from the lead\n\n" + lead)
    us = unresolved(replay(run, ts))
    if mode == "final":
        if run.context_docs:
            parts.append(RESIDENT_BLOCK)
            parts += docs_text(run.context_docs, "Resident document")
        parts.append(f"# State file ({run.state_file})\n\n" + (read(run.state_file) or "(missing)"))
        parts += docs_text(run.artifacts, "Artifact")
        parts.append("# Unresolved point ids\n\n" + ids_text(us))
        parts.append("# Last round (verbatim)\n\n" + rounds_text(last_round(run, ts)))
        parts.append(f"The full transcript stays the record at {run.transcript}; read it when a "
                     "qualification you need is missing above.\n")
    elif mode == "trial":
        parts += docs_text(run.artifacts, "Artifact")
        parts.append("# Unresolved point ids\n\n" + ids_text(us))
        parts.append("# Last round (verbatim)\n\n" + rounds_text(last_round(run, ts)))
    elif run.phase(phase).get("independent"):
        parts.append(INDEPENDENT_BLOCK)
    else:
        parts.append(f"# Transcript so far ({run.transcript.name})\n\n" + transcript_for_prompt(run, anonymise))
    parts.append(f"# Your turn now ({model}, phase {phase}). Reply with the turn text only; it is appended "
                 "verbatim after the noise strip.\n")
    prompt = "\n\n".join(p for p in parts if p is not None)
    missing = [m for m in PRIOR_ART_MARKERS if m not in prompt]
    if missing:  # cannot happen unless the block above is edited; Grok 5.2 makes it mandatory
        sys.exit(f"prompt lacks mandatory prior-art sentences: {missing}")
    return prompt


def next_turn_number(run: Run) -> int:
    ts = turns(read(run.transcript))
    return (ts[-1]["n"] + 1) if ts else 1


def final_gate(run: Run, allow_legacy: bool) -> list[str]:
    """Grok 4.4: block the final-word prompt if a last-round open point is missing from the state file."""
    problems = []
    if not run.state_file:
        return ["no state_file in the config"]
    state = read(run.state_file)
    if not state.strip():
        return [f"state file missing or empty: {run.state_file}"]
    ts = turns(read(run.transcript))
    for t in last_round(run, ts):
        f = parse_footer(t["body"])
        for it in f["open"] + [dict(r, status="refused") for r in f["refused"]]:
            if not it.get("id"):
                if not allow_legacy:
                    problems.append(f"turn {t['n']} {t['model']}: open point without point_id, cannot verify: "
                                    f"{it['text'][:80]}")
                continue
            if not re.search(rf"(?<![\w-]){re.escape(it['id'])}(?![\w-])", state):
                problems.append(f"turn {t['n']} {t['model']}: open point {it['id']} is not in {run.state_file.name}")
    return problems


# ---------------------------------------------------------------------------
# Routes (Grok 4.2, 5.3): pinned per run in the config; second route on empty text
# ---------------------------------------------------------------------------

def route_cmd(run: Run, route: dict[str, Any], prompt_file: Path, timeout: int) -> tuple[list[str], bool]:
    kind = route.get("kind", "acp")
    if kind == "claude":
        cmd = ["claude", "-p", "--model", route["model"], "--output-format", "text",
               "--dangerously-skip-permissions"]
        if route.get("effort"):
            cmd += ["--effort", route["effort"]]
        return cmd, True  # prompt on stdin
    if kind == "acp":
        cmd = ["acp-run", route["agent"], "-C", str(run.cwd), "-f", str(prompt_file)]
        if route.get("model"):
            cmd += ["--model", route["model"]]
        for kv in route.get("set", []):
            cmd += ["--set", kv]
        cmd += ["--perm", route.get("perm", "all"), "--timeout", str(timeout), "--json"]
        return cmd, False
    if kind == "cmd":
        return [a.replace("{prompt}", str(prompt_file)).replace("{cwd}", str(run.cwd)) for a in route["argv"]], \
            bool(route.get("stdin"))
    raise SystemExit(f"unknown route kind {kind}")


def route_name(route: dict[str, Any]) -> str:
    return " ".join(str(x) for x in (route.get("kind"), route.get("agent", ""), route.get("model", "")) if x)


def run_route(run: Run, route: dict[str, Any], prompt_file: Path, timeout: int) -> tuple[str, str]:
    """Return (reply_text, error). error == '' on success."""
    env = os.environ.copy()
    for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        env.pop(k, None)
    cmd, stdin = route_cmd(run, route, prompt_file, timeout)
    try:
        if stdin:
            with prompt_file.open("rb") as fh:
                r = subprocess.run(cmd, cwd=run.cwd, env=env, stdin=fh, capture_output=True, timeout=timeout + 120)
        else:
            r = subprocess.run(cmd, cwd=run.cwd, env=env, capture_output=True, timeout=timeout + 120)
    except subprocess.TimeoutExpired:
        return "", f"timeout after {timeout}s"
    except OSError as e:
        return "", f"cannot run {cmd[0]}: {e}"
    out = r.stdout.decode("utf-8", "replace").strip()
    err = r.stderr.decode("utf-8", "replace")
    if route.get("kind", "acp") == "acp":
        try:
            j = json.loads(out) if out else {}
        except json.JSONDecodeError:
            j = {}
        j = j if isinstance(j, dict) else {}
        if j.get("failure"):
            return "", f"failure: {j['failure']}"
        out = (j.get("text") or "").strip()
    if r.returncode != 0:
        return "", f"{cmd[0]} exit {r.returncode}: {err[-2000:]}"
    if not out:
        return "", "empty reply"
    return out, ""


def quota_wait_seconds(run: Run, model: str) -> int:
    """Seconds until the model's pool resets, from `aiuse --json` (all pools); DEFAULT_WAIT if unknown."""
    try:
        r = subprocess.run(["aiuse", "--json"], capture_output=True, text=True, timeout=120)
        data = json.loads(r.stdout) if r.stdout.strip() else {}
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return DEFAULT_WAIT
    want = str(run.models.get(model, {}).get("pool_label", "")).lower()
    found: list[int] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            label = str(o.get("label") or "").lower()
            resets = o.get("resets_at")
            if want and want in label and isinstance(resets, str):
                try:
                    t = dt.datetime.fromisoformat(resets.replace("Z", "+00:00"))
                    found.append(int((t - dt.datetime.now(dt.timezone.utc)).total_seconds()))
                except ValueError:
                    pass
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    secs = min((s for s in found if s > 0), default=DEFAULT_WAIT)
    return max(120, min(secs + 120, MAX_WAIT))


def call_model(run: Run, model: str, pf: Path, timeout: int, n: int, phase: str) -> tuple[str, str, str]:
    """Try each pinned route in order (normally two); wait out quota on a route. -> (reply, route, errors)."""
    routes = run.models.get(model, {}).get("routes", [])
    if not routes:
        return "", "", f"no routes pinned for {model} in the config"
    errors = []
    for route in routes[:2]:
        for attempt in range(MAX_QUOTA_WAITS + 1):
            reply, err = run_route(run, route, pf, timeout)
            if not err:
                return reply, route_name(route), ""
            if not QUOTA_RE.search(err) or attempt == MAX_QUOTA_WAITS:
                break
            wait = quota_wait_seconds(run, model)
            until = (dt.datetime.now() + dt.timedelta(seconds=wait)).astimezone().strftime("%Y-%m-%d %H:%M %Z")
            marker = run.turns_dir / f"turn-{n:03d}-{model}.waiting.md"
            marker.write_text(f"# WAITING turn {n} {model} ({phase}, {now()})\n\nroute: {route_name(route)}\n"
                              f"quota: {err[:500]}\n\nretry {attempt + 1}/{MAX_QUOTA_WAITS} at {until} ({wait}s)\n",
                              encoding="utf-8")
            print(f"turn {n} {model} quota exhausted; retry {attempt + 1}/{MAX_QUOTA_WAITS} at {until}", flush=True)
            try:
                time.sleep(wait)
            finally:
                marker.unlink(missing_ok=True)
        errors.append(f"{route_name(route)}: {err}")
        print(f"turn {n} {model} route failed ({route_name(route)}): {err[:200]}", flush=True)
    return "", "", "\n".join(errors)


# ---------------------------------------------------------------------------
# Appending turns
# ---------------------------------------------------------------------------

def append_turn(run: Run, n: int, model: str, phase: str, reply: str, fields: dict[str, str] | None = None) -> Path:
    header = f"## Turn {n} — {model} ({phase}, {now()})\n\n"
    extra = "".join(f"{k}: {v}\n" for k, v in (fields or {}).items())
    block = header + (extra + "\n" if extra else "") + reply.rstrip("\n") + "\n\n"
    run.turns_dir.mkdir(parents=True, exist_ok=True)
    if not run.transcript.exists():
        run.transcript.parent.mkdir(parents=True, exist_ok=True)
        title = run.cfg.get("title", "dialogue")
        run.transcript.write_text(
            f"# {title}: multi-model dialogue transcript\n\nEvery turn verbatim, in order ({', '.join(run.order)}), "
            "after the transport-noise strip (removed text is in turn-NNN-<model>.suffix.md). Headers give "
            "model, phase and local time. Nothing here is edited after the fact.\n\n", encoding="utf-8")
    with run.transcript.open("a", encoding="utf-8") as fh:
        fh.write(block)
    tf = run.turns_dir / f"turn-{n:03d}-{model}.md"
    tf.write_text(block, encoding="utf-8")
    return tf


def log_cost(run: Run, row: dict[str, Any]) -> None:
    run.turns_dir.mkdir(parents=True, exist_ok=True)
    with run.costs.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def snapshot(paths: list[Path]) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in paths if p.exists()}


def restore(run: Run, snap: dict[Path, bytes], n: int, model: str) -> list[str]:
    """Grok 4.6: an evidence-rewriting checker never changes a protected file during a turn."""
    msgs = []
    for p, before in snap.items():
        after = p.read_bytes() if p.exists() else b""
        if after != before:
            keep = run.turns_dir / f"turn-{n:03d}-{model}.rewritten-{p.name}"
            keep.write_bytes(after)
            tmp = p.with_name(p.name + ".dialogue-restore")
            tmp.write_bytes(before)
            os.replace(tmp, p)
            msgs.append(f"{p} was rewritten during the turn; restored (sha256 {hashlib.sha256(before).hexdigest()[:12]}),"
                        f" the rewritten copy is {keep.name}")
    return msgs


def accept_reply(run: Run, n: int, model: str, phase: str, reply: str, fields: dict[str, str],
                 accept_failure: bool) -> tuple[int, str]:
    clean, removed, fence_after = strip_noise(reply, run.opening, run.suffixes)
    if removed:
        (run.turns_dir / f"turn-{n:03d}-{model}.suffix.md").write_text(
            f"# Transport noise removed from turn {n} {model} ({phase}, {now()})\n\n"
            f"fence_after_footer: {fence_after}\n\n" + "\n\n".join(removed) + "\n", encoding="utf-8")
    bad = footer_failures(clean)
    if fence_after:
        print(f"turn {n} {model}: fenced block after the footer (stripped; counted as a protocol failure)")
    if bad and not accept_failure:
        (run.turns_dir / f"turn-{n:03d}-{model}.failed.md").write_text(
            f"# FAILED turn {n} {model} ({phase}, {now()}): protocol\n\n" + "\n".join(f"- {b}" for b in bad)
            + "\n\n## Reply after strip\n\n" + clean, encoding="utf-8")
        print(f"turn {n} {model} PROTOCOL FAILURE (not appended): {'; '.join(bad)}", flush=True)
        return 2, clean
    if bad:
        fields = dict(fields, protocol_failure="; ".join(bad))
    tf = append_turn(run, n, model, phase, clean, fields)
    print(f"turn {n} {model} ok {words(clean)}w -> {tf.name}", flush=True)
    print(parse_footer(clean)["text"], flush=True)
    return 0, clean


def do_turn(run: Run, model: str, phase: str, instruction: Path | None, timeout: int, mode: str = "normal",
            anonymise: bool = False, judge: str | None = None) -> int:
    if not run.has_config:
        sys.exit("turn/round/final need a dialogue.json in the run folder")
    if model not in run.models:
        sys.exit(f"unknown model {model}; configured: {', '.join(run.models)}")
    if run.lock.exists():
        sys.exit(f"lock present ({run.lock}); another turn is running")
    run.turns_dir.mkdir(parents=True, exist_ok=True)
    run.lock.write_text(f"{model} {phase} {now()} pid {os.getpid()}\n")
    snap = snapshot(run.protected)
    n = next_turn_number(run)
    try:
        prompt = build_prompt(run, model, phase, instruction, mode, anonymise)
        run.prompt_out.mkdir(parents=True, exist_ok=True)
        tag = f"judge-{n:03d}-{model}" if judge else f"turn-{n:03d}-{model}"
        pf = run.prompt_out / f"{tag}.prompt.md"
        pf.write_text(prompt, encoding="utf-8")
        cost = {"turn": n, "model": model, "phase": phase, "mode": "judge" if judge else mode, "when": now(),
                "prompt_words": words(prompt), "prompt_bytes": len(prompt.encode())}
        if mode == "normal" and run.trial_enabled(phase):  # Grok 1.3 trial, recorded beside the full prompt
            trial = build_prompt(run, model, phase, instruction, "trial")
            tp = run.prompt_out / f"{tag}.trial.prompt.md"
            tp.write_text(trial, encoding="utf-8")
            cost.update(trial_words=words(trial), trial_bytes=len(trial.encode()))
        print(f"turn {n} {model} phase={phase} mode={mode} prompt={cost['prompt_words']}w -> running", flush=True)
        t0 = time.time()
        reply, route, err = call_model(run, model, pf, timeout, n, phase)
        cost.update(seconds=round(time.time() - t0), route=route)
        if err:
            (run.turns_dir / f"{tag}.failed.md").write_text(
                f"# FAILED turn {n} {model} ({phase}, {now()}): route\n\n{err}\n", encoding="utf-8")
            print(f"turn {n} {model} FAILED (not a turn): {err[:300]}", flush=True)
            log_cost(run, dict(cost, status="route-failed"))
            return 1
        if judge:  # optional fresh judge: written beside, never appended, never replaces the resident
            out = run.turns_dir / f"{tag}.md"
            out.write_text(f"# Fresh-judge output, turn slot {n}, {model} ({phase}, {now()})\n\n{reply}\n",
                           encoding="utf-8")
            print(f"judge output -> {out}")
            log_cost(run, dict(cost, status="judge", reply_words=words(reply)))
            return 0
        rc, clean = accept_reply(run, n, model, phase, reply, {}, False)
        log_cost(run, dict(cost, status="ok" if rc == 0 else "protocol-failed", reply_words=words(clean)))
        return rc
    finally:
        for m in restore(run, snap, n, model):
            print("PROTECTED:", m, flush=True)
        run.lock.unlink(missing_ok=True)


def phase_spent(run: Run, phase: str) -> int:
    total = 0
    for ln in read(run.costs).splitlines():
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if row.get("phase") == phase:
            total += int(row.get("prompt_words", 0))
    return total


def do_round(run: Run, phase: str, instruction: Path | None, timeout: int, only: str | None, skip: str | None) -> int:
    ph = run.phase(phase)
    if ph.get("final_word_only"):
        models = [run.final_word]
    else:
        models = [m for m in run.order if m in only.split(",")] if only else list(run.order)
    if skip:  # lead-only (Grok 3.13): NEXT never skips a speaker
        skipped = skip.split(",")
        models = [m for m in models if m not in skipped]
        log_cost(run, {"phase": phase, "when": now(), "status": "lead-skip", "skipped": skipped})
    for m in models:
        budget = ph.get("budget_words")
        if budget and run.optional.get("phase_budget_stop") and phase_spent(run, phase) >= budget:
            us = unresolved(replay(run, turns(read(run.transcript))))
            print(f"phase {phase} budget spent ({phase_spent(run, phase)}w >= {budget}w); stopping. "
                  f"Unconverged ids go to the final word: {[p['id'] for p in us]}")
            return 3
        rc = do_turn(run, m, phase, instruction, timeout)
        if rc:
            return rc
    ok, by, _ = converged(run, stall=bool(run.optional.get("stall_stop")), cap=True)
    print(f"round done; converged={ok} converged_by={by}")
    return 0


# ---------------------------------------------------------------------------
# Lead tools
# ---------------------------------------------------------------------------

def converged(run: Run, stall: bool = False, cap: bool = False) -> tuple[bool, str, list[str]]:
    ts = turns(read(run.transcript))
    pts = replay(run, ts)
    why: list[str] = []
    for m in run.order:
        t = last_of(ts, m)
        if not t:
            why.append(f"{m} has not spoken")
            continue
        if t["fields"].get("recovered_from"):  # Grok 4.2
            why.append(f"{m}'s last turn {t['n']} is recovered_from {t['fields']['recovered_from']}")
        f = parse_footer(t["body"])
        # legacy items (no id) block; an id blocks only while the replayed state still has it carried
        still = [it for it in f["open"] if not it["id"] or pts.get(it["id"], {}).get("status") == "carried"]
        if still:
            why.append(f"{m} turn {t['n']} lists {len(still)} open point(s)")
    us = [p for p in pts.values() if p.get("status") == "carried"]
    if us:
        why.append("carried ids: " + ", ".join(p["id"] for p in us))
    unfrozen = [p for p in pts.values() if p.get("status") in ("decided", "tested") and not p.get("frozen")]
    if unfrozen:  # Grok 1.6: settled is not frozen until the other owners' invariant check
        why.append("settled, awaiting invariant check: " + ", ".join(p["id"] for p in unfrozen))
    if not why:
        return True, "none", why
    if stall:  # optional (Grok 3.2): open id set unchanged over two round ends
        k = max(1, len(run.order))
        ends = [ts[:i] for i in range(len(ts), 0, -k)][:3]
        sets = [frozenset(p["id"] for p in unresolved(replay(run, e))) for e in ends]
        if len(sets) == 3 and sets[0] == sets[1] == sets[2] and sets[0]:
            return True, "stall", why
    if cap and ts:
        ph = run.phase(ts[-1]["phase"])
        mr = ph.get("max_rounds")
        if mr and sum(1 for t in ts if t["phase"] == ph["name"]) >= mr * len(run.order):
            return True, "cap", why
    return False, "-", why


def do_ledger(run: Run, show_all: bool, by_needs: bool) -> None:
    ts = turns(read(run.transcript))
    if not ts:
        print("(empty transcript)")
        return
    chosen = ts if show_all else [t for t in ts if t is last_of(ts, t["model"])]
    for t in chosen:
        f = parse_footer(t["body"])
        flags = []
        if t["fields"].get("recovered_from"):
            flags.append(f"recovered_from: {t['fields']['recovered_from']}")
        if t["fields"].get("protocol_failure"):
            flags.append(f"protocol_failure: {t['fields']['protocol_failure']}")
        if f["found"] and not f["terminal"]:
            flags.append(f"text after NEXT: {words(f['after'])}w")
        if f["legacy"]:
            flags.append("legacy footer (no point ids)")
        tag = f"  [{'; '.join(flags)}]" if flags else ""
        print(f"### Turn {t['n']} — {t['model']} ({t['phase']}, {t['when']}){tag}\n{f['text']}\n")
    pts = replay(run, ts)
    if pts:
        print("## Point state (replayed from footers)\n")
        rows = sorted(pts.values(), key=(lambda p: (p.get("needs") or "~", p["id"])) if by_needs else
                      (lambda p: (p["raised_turn"], p["id"])))
        for p in rows:
            st = p["status"]
            if st in ("decided", "tested"):
                st += " frozen" if p.get("frozen") else f" (awaiting invariant check: {', '.join(sorted(p['awaiting'])) or '-'})"
            extra = "".join(f" {k}={p[k]}" for k in ("by", "needs", "conf") if p.get(k) not in (None, ""))
            print(f"- {p['id']}: {st}{extra}; raised turn {p['raised_turn']} by {p['raised_by']}")
        confs = [p["conf"] for p in pts.values() if p.get("conf") is not None and p["status"] == "carried"]
        if confs:
            print(f"\nconf spread over carried points: min={min(confs)} max={max(confs)} (a tag only, never a stop)")
    ok, by, why = converged(run)
    print(f"\nconverged={ok} converged_by={by}" + ("" if ok else "; " + "; ".join(why)))


def do_folds(run: Run) -> None:
    """Fold audit (Grok 1.4), lead-only: a fold is unsupported when the closing citation is not about that
    point_id, or when the raiser drops the point without settling it. No rate is printed."""
    ts = turns(read(run.transcript))
    raised: dict[str, tuple[str, int]] = {}
    settled_by: dict[str, tuple[str, int]] = {}
    found = 0
    legacy = 0
    for t in ts:
        f = parse_footer(t["body"])
        if f["legacy"]:
            legacy += 1
        prev = last_of([x for x in ts if x["n"] < t["n"]], t["model"])
        prev_open = {it["id"] for it in parse_footer(prev["body"])["open"] if it["id"]} if prev else set()
        now_open = {it["id"] for it in f["open"] if it["id"]}
        settled = {it["id"]: it for it in f["settled"] if it["id"]}
        for it in f["open"]:
            if it["id"] and it["id"] not in raised:
                raised[it["id"]] = (t["model"], t["n"])
        for pid in prev_open - now_open:
            if raised.get(pid, ("", 0))[0] != t["model"]:
                continue
            it = settled.get(pid)
            other = settled_by.get(pid)
            if not it and other and other[0] != t["model"] and other[1] > (prev["n"] if prev else 0):
                continue  # accepting another model's closure is not a fold; that closure is audited on its own turn
            if not it:
                found += 1
                print(f"UNSUPPORTED turn {t['n']} {t['model']}: dropped its own point {pid} without settling it")
                continue
            by = it.get("by") or ""
            if by == "rewrite":
                continue
            paras = [p for p in re.split(r"\n\s*\n", t["body"]) if re.search(rf"(?<![\w-]){re.escape(pid)}(?![\w-])", p)]
            about = any(by and by in p for p in paras) or (by and by in it["text"])
            if not by or not about:
                found += 1
                print(f"UNSUPPORTED turn {t['n']} {t['model']}: settled its own point {pid} "
                      f"closed_by={by or '(none)'}, which no paragraph about {pid} cites")
        for pid in settled:
            settled_by[pid] = (t["model"], t["n"])
    print(f"\n{found} unsupported fold(s) listed; {legacy} legacy footer(s) without point ids not audited. "
          "Lead-only: do not paste this list into a model prompt.")


def sentences(s: str) -> int:
    return len([x for x in re.split(r"(?<=[.!?])\s+", s.strip()) if x.strip()])


def do_lint(run: Run, only: int | None) -> int:
    ts = turns(read(run.transcript))
    k = max(1, len(run.order))
    first_seen: dict[str, int] = {}
    cited_before: set[str] = set()
    fails = 0
    for i, t in enumerate(ts):
        f = parse_footer(t["body"])
        msgs: list[tuple[str, str]] = []
        for b in footer_failures(t["body"]):
            msgs.append(("FAIL", b))
        sfx = run.turns_dir / f"turn-{t['n']:03d}-{t['model']}.suffix.md"
        if "fence_after_footer: True" in read(sfx):
            msgs.append(("FAIL", "fenced block after the footer (stripped before append)"))
        if f["after"] and FENCE_RE.search(f["after"]):
            msgs.append(("FAIL", "fenced block after the footer"))
        lead_body = "\n".join(ln for ln in t["body"].split("\n") if not HDR_FIELD_RE.match(ln)).lstrip()
        if run.opening and not lead_body.startswith(run.opening):
            msgs.append(("WARN", f"does not open with {run.opening}"))
        if t["fields"].get("recovered_from"):
            msgs.append(("WARN", f"recovered_from: {t['fields']['recovered_from']} (cannot satisfy converged)"))
        if CHECKER_ALL_RE.search(t["body"]):
            msgs.append(("WARN", "mentions `research_check.py ... all` (rewrites evidence.jsonl; never in a turn)"))
        nxt = (f["next"] or "").lower()
        if i + 1 < len(ts) and run.order:
            exp = run.order[(run.order.index(t["model"]) + 1) % len(run.order)] if t["model"] in run.order else None
            named = [m for m in run.order if re.match(rf"\W*{re.escape(m)}\b", nxt)]
            if exp and named and named[0] != exp and named[0] != t["model"]:
                msgs.append(("WARN", f"NEXT names {named[0]}; the fixed order continues with {exp} (NEXT never skips)"))
        # Grok 1.5: per-point length warning after a point's second round.
        body_ids = set(EID_RE.findall(t["body"]))
        for it in f["open"] + f["settled"]:
            pid = it["id"]
            if not pid:
                continue
            first_seen.setdefault(pid, t["n"])
            if t["n"] - first_seen[pid] < 2 * k:
                continue
            paras = [p for p in re.split(r"\n\s*\n", t["body"].split("\nSETTLED:")[0])
                     if re.search(rf"(?<![\w-]){re.escape(pid)}(?![\w-])", p)]
            n_sent = sum(sentences(p) for p in paras)
            new_quote = bool(set(EID_RE.findall(" ".join(paras))) - cited_before)
            exempt = new_quote or re.search(r"counterexample|experiment|\btested\b", " ".join(paras), re.I)
            if n_sent > 3 and not exempt:
                msgs.append(("WARN", f"{pid}: {n_sent} sentences after its second round with no counterexample, "
                                     "new quote or experiment (warning only)"))
        cited_before |= body_ids
        if only is not None and t["n"] != only:
            continue
        fails += sum(1 for lv, _ in msgs if lv == "FAIL")
        for lv, m in msgs:
            print(f"turn {t['n']:>3} {t['model']:<8} {lv} {m}")
    print(f"lint: {fails} failure(s) over {len(ts) if only is None else 1} turn(s)")
    return 1 if fails else 0


def do_costs(run: Run) -> None:
    per: dict[str, dict[str, int]] = {}
    for ln in read(run.costs).splitlines():
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            continue
        d = per.setdefault(row.get("phase", "?"), {"turns": 0, "prompt_words": 0, "trial_words": 0, "reply_words": 0})
        d["turns"] += 1 if row.get("turn") else 0
        for key in ("prompt_words", "trial_words", "reply_words"):
            d[key] += int(row.get(key, 0) or 0)
    if not per:
        print(f"(no rows in {run.costs})")
    for ph, d in per.items():
        budget = run.phase(ph).get("budget_words")
        print(f"{ph}: " + " ".join(f"{k}={v}" for k, v in d.items()) + (f" budget={budget}" if budget else ""))


def do_recover(run: Run, model: str, phase: str, src: Path, source: str) -> int:
    """Grok 4.2 / 5.1: a pasted recovery is a turn with a recovered_from header; it never satisfies converged."""
    if run.lock.exists():
        sys.exit(f"lock present ({run.lock})")
    n = next_turn_number(run)
    rc, _ = accept_reply(run, n, model, phase, read(src), {"recovered_from": source}, True)
    log_cost(run, {"turn": n, "model": model, "phase": phase, "when": now(), "status": "recovered",
                   "recovered_from": source})
    return rc


def do_probe(run: Run, model: str | None) -> int:
    run.prompt_out.mkdir(parents=True, exist_ok=True)
    pf = run.prompt_out / "probe.prompt.md"
    pf.write_text("Reply with exactly: OK\n", encoding="utf-8")
    bad = 0
    for m in ([model] if model else run.order):
        for route in run.models.get(m, {}).get("routes", []):
            reply, err = run_route(run, route, pf, 300)
            ok = not err and "OK" in reply
            bad += 0 if ok else 1
            print(f"{m:<8} {route_name(route):<40} {'ok' if ok else 'FAIL ' + (err or reply)[:160]}")
    return 1 if bad else 0


def do_unused(run: Run) -> None:
    """Optional moderator (Grok 3.15): evidence ids and source URLs never cited in transcript or artifacts."""
    corpus = read(run.transcript) + "".join(read(a) for a in run.artifacts)
    cited = set(EID_RE.findall(corpus))
    if run.evidence:
        ids = []
        for ln in read(run.evidence).splitlines():
            try:
                ids.append(json.loads(ln)["id"])
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        unused = [i for i in ids if i not in cited]
        print(f"evidence ids never cited: {len(unused)} of {len(ids)}\n" + " ".join(unused))
    if run.sources:
        urls = re.findall(r"https?://[^\s|)>]+", read(run.sources))
        unused_u = [u for u in dict.fromkeys(urls) if u not in corpus.replace(read(run.sources), "")]
        print(f"\nsources.md URLs never cited: {len(unused_u)}\n" + "\n".join(unused_u))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", help="run folder (default: cwd)")
    ap.add_argument("--config", help="config file (default: <run>/dialogue.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("turn", "prompt"):
        t = sub.add_parser(name)
        t.add_argument("model")
        t.add_argument("--phase", required=True)
        t.add_argument("--instruction", type=Path)
        t.add_argument("--timeout", type=int, default=1800)
        t.add_argument("--anonymise", action="store_true", help="optional critique sub-step: strip model names")
        if name == "prompt":
            t.add_argument("--final", action="store_true")
    r = sub.add_parser("round")
    r.add_argument("--phase", required=True)
    r.add_argument("--instruction", type=Path)
    r.add_argument("--timeout", type=int, default=1800)
    r.add_argument("--only", help="lead-only: comma list (kept in the fixed order)")
    r.add_argument("--skip", help="lead-only: comma list of models to skip this round (logged)")
    fw = sub.add_parser("final")
    fw.add_argument("--phase", required=True)
    fw.add_argument("--instruction", type=Path)
    fw.add_argument("--timeout", type=int, default=3600)
    fw.add_argument("--allow-legacy", action="store_true")
    fw.add_argument("--judge", help="optional fresh judge model: same prompt, output beside, not appended")
    g = sub.add_parser("gate")
    g.add_argument("--allow-legacy", action="store_true")
    rc = sub.add_parser("recover")
    rc.add_argument("model")
    rc.add_argument("--phase", required=True)
    rc.add_argument("--from", dest="src", type=Path, required=True)
    rc.add_argument("--source", default="task-summary")
    lg = sub.add_parser("ledger")
    lg.add_argument("--all", action="store_true")
    lg.add_argument("--by-needs", action="store_true")
    cv = sub.add_parser("converged")
    cv.add_argument("--stall", action="store_true")
    cv.add_argument("--cap", action="store_true")
    sub.add_parser("folds")
    li = sub.add_parser("lint")
    li.add_argument("--turn", type=int)
    st = sub.add_parser("strip")
    st.add_argument("file", type=Path)
    sub.add_parser("costs")
    pr = sub.add_parser("probe")
    pr.add_argument("model", nargs="?")
    sub.add_parser("unused-ids")
    a = ap.parse_args()
    run = load_run(a.run, a.config)

    if a.cmd == "turn":
        sys.exit(do_turn(run, a.model, a.phase, a.instruction, a.timeout, anonymise=a.anonymise))
    if a.cmd == "prompt":
        mode = "final" if a.final else "normal"
        p = build_prompt(run, a.model, a.phase, a.instruction, mode, a.anonymise)
        run.prompt_out.mkdir(parents=True, exist_ok=True)
        out = run.prompt_out / f"dry-{a.model}-{a.phase}-{mode}.prompt.md"
        out.write_text(p, encoding="utf-8")
        print(f"{out} {words(p)}w {len(p.encode())}B")
        return
    if a.cmd == "round":
        sys.exit(do_round(run, a.phase, a.instruction, a.timeout, a.only, a.skip))
    if a.cmd in ("final", "gate"):
        probs = final_gate(run, a.allow_legacy)
        for p in probs:
            print("GATE:", p)
        if probs:
            sys.exit("final-word prompt blocked: add the missing open points to the state file")
        print("gate ok: every last-round open point is in the state file")
        if a.cmd == "final":
            model = a.judge or run.final_word
            sys.exit(do_turn(run, model, a.phase, a.instruction, a.timeout, mode="final", judge=a.judge))
        return
    if a.cmd == "recover":
        sys.exit(do_recover(run, a.model, a.phase, a.src, a.source))
    if a.cmd == "ledger":
        do_ledger(run, a.all, a.by_needs)
        return
    if a.cmd == "converged":
        ok, by, why = converged(run, a.stall, a.cap)
        print(f"{'converged' if ok else 'not converged'} converged_by={by}" + ("" if not why else "\n- " + "\n- ".join(why)))
        sys.exit(0 if ok else 1)
    if a.cmd == "folds":
        do_folds(run)
        return
    if a.cmd == "lint":
        sys.exit(do_lint(run, a.turn))
    if a.cmd == "strip":
        clean, removed, fence = strip_noise(read(a.file), run.opening, run.suffixes)
        print(f"removed {len(removed)} piece(s); fence_after_footer={fence}")
        for r_ in removed:
            print("---\n" + r_)
        print("--- footer failures after strip:", footer_failures(clean) or "none")
        return
    if a.cmd == "costs":
        do_costs(run)
        return
    if a.cmd == "probe":
        sys.exit(do_probe(run, a.model))
    if a.cmd == "unused-ids":
        do_unused(run)
        return


if __name__ == "__main__":
    main()
