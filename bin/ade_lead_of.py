"""Repo-keyed lead lookup and live candidate discovery (Carried #106 and #107, 2026-11-26).

`ade-self-session finish` and `ade-self-session link` write a repo-keyed lead record under
`${ADE_REPO_LEADS_DIR:-${ADE_SELF_SESSION_STATE:-~/.local/state/djbclark-ade/self-session}/repo-leads}/<repo>.json`.
Operators can also set one directly with `bin/ade-lead-of set REPO AGENT_ID`.

Resolution order (`resolve_repo_lead`):
  1. Authoritative repo-keyed record for this `PASEO_HOME`, followed through `ade_lead_succession`
     (completed chain + fresh live acknowledged hop) and confirmed `Archived: false` via Paseo ->
     `verified: true`.
  2. If no live verified record exists (absent, stale/archived, or unknown to Paseo), discover live
     (`Archived: false`, non-worker) candidate leads for `REPO` via structured metadata (`ade.repo`
     + lead labels, registered `LEAD` window in `ade_ws_names`), `ade.chain` + repo `cwd`, or
     `LEAD <repo>` / `MAIN <repo>` window display name. Every fallback result carries
     `verified: false` and is NEVER used as an automatic send redirect.

Exit codes for `bin/ade-lead-of`:
  0  resolved a verified live lead (or a single unverified fallback when `--allow-unverified` is set)
  1  no lead found or multiple ambiguous candidates
  2  invalid usage or repo/UUID validation failure
  3  unverified fallback guess (single candidate or Paseo unavailable to confirm a recorded lead)
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any, Callable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ade_lead_succession as succ  # noqa: E402
import ade_paseo_client as paseo_client  # noqa: E402
import ade_ws_names as ws_names  # noqa: E402

REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
UUID_RE = succ.UUID_RE
REPO_LEADS_ENV = "ADE_REPO_LEADS_DIR"
MAX_RECORD_BYTES = 65536

EXIT_OK = 0
EXIT_NOT_FOUND = 1
EXIT_USAGE = 2
EXIT_UNVERIFIED = 3

_RETIRED_LEAD_TITLE_RE = re.compile(r"^(?:RETIRED\s+)?(?:LEAD|MAIN)\s+([A-Za-z0-9][A-Za-z0-9._-]{0,127})\b")
_WORKER_PREFIX_RE = re.compile(r"^(?:worker|other)\s+", re.IGNORECASE)


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def validate_repo(repo: str) -> str:
    if not isinstance(repo, str) or not REPO_RE.fullmatch(repo) or repo in (".", ".."):
        raise ValueError(f"invalid repo name {repo!r} (expected [A-Za-z0-9][A-Za-z0-9._-]*)")
    return repo


def default_repo_leads_dir(state_dir: Path | None = None, env: Mapping[str, str] | None = None) -> Path:
    e = _env(env)
    override = e.get(REPO_LEADS_ENV)
    if override:
        return Path(override)
    base = state_dir if state_dir is not None else succ.default_state_dir(e)
    return Path(base) / "repo-leads"


def repo_record_path(
    repo: str,
    *,
    repo_leads_dir: Path | None = None,
    state_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    clean = validate_repo(repo)
    base = Path(repo_leads_dir) if repo_leads_dir is not None else default_repo_leads_dir(state_dir, env)
    return base / f"{clean}.json"


def _read_regular_json(path: Path) -> dict[str, Any] | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or (st.st_mode & 0o022):
                return None
            raw = os.read(fd, MAX_RECORD_BYTES + 1)
        finally:
            os.close(fd)
        if len(raw) > MAX_RECORD_BYTES:
            return None
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise OSError(f"refusing to overwrite symlink {path}")
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_repo_lead(
    repo: str,
    *,
    repo_leads_dir: Path | None = None,
    state_dir: Path | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """Read and validate the durable repo-keyed lead record for `repo` on `home`, else None."""
    try:
        clean = validate_repo(repo)
    except ValueError:
        return None
    path = repo_record_path(clean, repo_leads_dir=repo_leads_dir, state_dir=state_dir, env=env)
    rec = _read_regular_json(path)
    if not rec:
        return None
    if rec.get("kind") != "repo-lead" or rec.get("repo") != clean:
        return None
    lead = rec.get("lead")
    raw_home = rec.get("home")
    if not isinstance(lead, str) or not UUID_RE.fullmatch(lead):
        return None
    if not isinstance(raw_home, str) or not os.path.isabs(raw_home):
        return None
    expected_home = home if home is not None else succ.default_home(_env(env))
    try:
        if Path(raw_home).resolve() != Path(expected_home).resolve():
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return rec


def write_repo_lead(
    repo: str,
    lead: str,
    *,
    source: str = "manual",
    predecessor: str | None = None,
    cwd: str | None = None,
    repo_leads_dir: Path | None = None,
    state_dir: Path | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Atomically write `<repo_leads_dir>/<repo>.json` (0700 dir, 0600 file)."""
    clean = validate_repo(repo)
    if not isinstance(lead, str) or not UUID_RE.fullmatch(lead):
        raise ValueError(f"lead must be a full lowercase UUID (got {lead!r})")
    if predecessor is not None and (not isinstance(predecessor, str) or not UUID_RE.fullmatch(predecessor)):
        raise ValueError(f"predecessor must be a full lowercase UUID (got {predecessor!r})")
    resolved_home = str((home if home is not None else succ.default_home(_env(env))).resolve())
    record: dict[str, Any] = {
        "schema_version": 1,
        "kind": "repo-lead",
        "repo": clean,
        "lead": lead,
        "home": resolved_home,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": str(source or "manual"),
        "predecessor": predecessor,
        "cwd": str(cwd) if cwd else None,
    }
    path = repo_record_path(clean, repo_leads_dir=repo_leads_dir, state_dir=state_dir, env=env)
    _write_atomic(path, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return record


def list_repo_leads(
    *,
    repo_leads_dir: Path | None = None,
    state_dir: Path | None = None,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    base = Path(repo_leads_dir) if repo_leads_dir is not None else default_repo_leads_dir(state_dir, env)
    try:
        names = sorted(p.name for p in base.iterdir())
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for name in names:
        if not name.endswith(".json"):
            continue
        repo = name[:-5]
        rec = read_repo_lead(repo, repo_leads_dir=base, state_dir=state_dir, home=home, env=env)
        if rec is not None:
            out.append(rec)
    return out


def _clean_cwd_repo(cwd: Any) -> str | None:
    if not isinstance(cwd, str) or not cwd.strip():
        return None
    expanded = os.path.expanduser(cwd.strip())
    if not os.path.isabs(expanded):
        return None
    try:
        real = os.path.realpath(expanded)
        home_real = os.path.realpath(str(Path.home()))
    except OSError:
        return None
    if real in ("/", home_real):
        return None
    name = ws_names.repo_of(real)
    if not name or not REPO_RE.fullmatch(name):
        return None
    return name


def infer_repo_from_agent(record: Mapping[str, Any] | None) -> str | None:
    """Derive a repo name from an inspected/listed Paseo agent record (labels -> Cwd -> display title)."""
    if not isinstance(record, Mapping):
        return None
    labels = record.get("Labels") if isinstance(record.get("Labels"), Mapping) else record.get("labels")
    if isinstance(labels, Mapping):
        labelled = labels.get("ade.repo")
        if isinstance(labelled, str) and REPO_RE.fullmatch(labelled):
            return labelled
    cwd = record.get("Cwd") if isinstance(record.get("Cwd"), str) else record.get("cwd")
    from_cwd = _clean_cwd_repo(cwd)
    if from_cwd:
        return from_cwd
    title = record.get("Name") if isinstance(record.get("Name"), str) else record.get("title")
    if isinstance(title, str) and title.strip():
        m = _RETIRED_LEAD_TITLE_RE.match(title.strip())
        if m and REPO_RE.fullmatch(m.group(1)):
            return m.group(1)
    return None


def _is_worker_row(row: Mapping[str, Any]) -> bool:
    labels = row.get("labels") if isinstance(row.get("labels"), Mapping) else row.get("Labels")
    labels = labels if isinstance(labels, Mapping) else {}
    if labels.get("ade.lead") or labels.get("slice") or labels.get("ade.retired") or labels.get("baton-writer"):
        return True
    box = labels.get("ade.box")
    if isinstance(box, str) and box and box != "LEAD":
        return True
    role = labels.get("ade.role")
    if isinstance(role, str) and role.lower() in ("load-watch", "load_watch", "watcher"):
        return True
    if row.get("parentAgentId") or row.get("ParentAgentId"):
        return True
    title = str(row.get("title") or row.get("name") or row.get("Name") or "").strip()
    if _WORKER_PREFIX_RE.match(title) and not labels.get("ade.role") and not labels.get("ade.chain"):
        return True
    if title.startswith("RETIRED "):
        return True
    return False


def _is_archived_row(row: Mapping[str, Any]) -> bool:
    if row.get("archived") is True or row.get("Archived") is True:
        return True
    if row.get("archivedAt") or row.get("ArchivedAt"):
        return True
    return False


def format_designation(
    agent_id: str,
    *,
    workspace_id: str | None = None,
    window: str | None = None,
    tab: str | None = None,
) -> str:
    """Format an agent reference per 2026-11-25/26 operator rulings: `<7-char> (<full-UUID>)` + workspace/window/tab."""
    base = f"{agent_id[:7]} ({agent_id})"
    parts: list[str] = []
    if workspace_id:
        parts.append(f"workspace {workspace_id}")
    if window:
        parts.append(f"window {window!r}")
    if tab:
        parts.append(f"tab {tab!r}")
    return f"{base} [{', '.join(parts)}]" if parts else base


def discover_live_candidates(
    repo: str,
    *,
    list_agents: Callable[[], list[dict[str, Any]]],
    list_workspaces: Callable[[], list[dict[str, Any]]] | None = None,
    ws_state_dir: Path | None = None,
    exclude: set[str] | tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Find live (`Archived: false`, non-worker) candidate leads for `repo`. Every result is a heuristic (`verified: false`)."""
    clean = validate_repo(repo)
    excluded = set(exclude)
    try:
        rows = list_agents()
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(rows, list):
        return []

    ws_by_id: dict[str, dict[str, Any]] = {}
    if list_workspaces is not None:
        try:
            ws_rows = list_workspaces()
            if isinstance(ws_rows, list):
                for w in ws_rows:
                    if isinstance(w, dict) and isinstance(w.get("workspaceId"), str):
                        ws_by_id[w["workspaceId"]] = w
        except Exception:  # noqa: BLE001
            pass

    registered_lead_ws: set[str] = set()
    try:
        reg = ws_names.all_registered_windows(ws_state_dir)
        for wks_id, entry in reg.items():
            if isinstance(entry, dict) and entry.get("box") == "LEAD" and entry.get("repo") == clean:
                registered_lead_ws.add(wks_id)
    except Exception:  # noqa: BLE001
        pass

    scored: list[tuple[int, str, dict[str, Any]]] = []
    seen_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        aid = row.get("id") or row.get("Id")
        if not isinstance(aid, str) or not UUID_RE.fullmatch(aid) or aid in excluded or aid in seen_ids:
            continue
        if _is_archived_row(row) or _is_worker_row(row):
            continue
        labels = row.get("labels") if isinstance(row.get("labels"), Mapping) else row.get("Labels")
        labels = labels if isinstance(labels, Mapping) else {}
        raw_ws_id = row.get("workspaceId") if isinstance(row.get("workspaceId"), str) else row.get("WorkspaceId")
        ws_id = raw_ws_id if isinstance(raw_ws_id, str) else None
        ws_row = ws_by_id.get(ws_id or "", {})
        raw_ws_name = ws_row.get("name") if isinstance(ws_row.get("name"), str) else ws_row.get("title")
        ws_name = raw_ws_name if isinstance(raw_ws_name, str) and raw_ws_name.strip() else None
        tab = str(row.get("title") or row.get("name") or row.get("Name") or "").strip() or None
        cwd = row.get("cwd") if isinstance(row.get("cwd"), str) else row.get("Cwd")
        cwd_repo = _clean_cwd_repo(cwd)

        parsed_ws = ws_names.parse(ws_name) if ws_name else None
        legacy_ws = ws_names.parse_legacy(ws_name) if (ws_name and parsed_ws is None) else None
        non_lead_window = (
            (parsed_ws is not None and parsed_ws.box != "LEAD")
            or (legacy_ws is not None and legacy_ws.kind != "MAIN")
            or (ws_name is not None and ws_name.upper().startswith("WATCH "))
        )

        reason: str | None = None
        tier = 99
        if labels.get("ade.repo") == clean and (labels.get("ade.box") == "LEAD" or labels.get("ade.role") or labels.get("ade.chain")):
            tier, reason = 1, "label:ade.repo"
        elif ws_id and ws_id in registered_lead_ws:
            tier, reason = 2, "registry:lead-window"
        elif parsed_ws is not None and parsed_ws.box == "LEAD" and parsed_ws.repo == clean:
            if labels.get("ade.chain") or labels.get("ade.role") or cwd_repo == clean:
                tier, reason = 3, f"window:{parsed_ws.kind}+meta"
            else:
                tier, reason = 4, f"window:{parsed_ws.kind}"
        elif legacy_ws is not None and legacy_ws.kind == "MAIN" and (legacy_ws.middle == clean or cwd_repo == clean):
            tier, reason = 4, "window:MAIN"
        elif not non_lead_window and cwd_repo == clean and (labels.get("ade.chain") or labels.get("ade.role")):
            tier, reason = 5, "chain+cwd"
        elif not non_lead_window and cwd_repo == clean and tab:
            m = _RETIRED_LEAD_TITLE_RE.match(tab)
            if (m and m.group(1) == clean) or (f"lead {clean}".lower() in tab.lower()):
                tier, reason = 6, "cwd+title"
        if reason is None:
            continue
        seen_ids.add(aid)
        scored.append((
            tier,
            aid,
            {
                "id": aid,
                "short_id": aid[:7],
                "reason": reason,
                "workspace_id": ws_id,
                "window": ws_name,
                "tab": tab,
                "cwd": cwd if isinstance(cwd, str) else None,
                "status": str(row.get("status") or row.get("Status") or ""),
            },
        ))
    scored.sort(key=lambda item: (item[0], item[1]))
    if not scored:
        return []
    # Return the highest-confidence tier if structured signals exist, else all matches in the winning tier.
    best_tier = scored[0][0]
    return [item[2] for item in scored if item[0] == best_tier]


def _follow_live_acknowledged(
    current: str,
    inspect: Callable[[str], dict[str, Any]],
    state_dir: Path | None,
    home: Path | None,
) -> str:
    seen = {current}
    while True:
        nxt = succ.successor_of(current, state_dir, home, statuses=succ.ACKNOWLEDGED)
        if nxt is None:
            return current
        try:
            rec = inspect(nxt)
        except Exception:  # noqa: BLE001
            return current
        if not isinstance(rec, dict) or rec.get("Archived") is not False:
            return current
        end = succ.effective_lead(nxt, state_dir, home)
        if end != nxt:
            try:
                end_rec = inspect(end)
            except Exception:  # noqa: BLE001
                return current
            if not isinstance(end_rec, dict) or end_rec.get("Archived") is not False:
                return current
        if end in seen:
            raise succ.SuccessionError(f"lead succession from {current} is cyclic")
        seen.update((nxt, end))
        current = end


def resolve_repo_lead(
    repo: str,
    *,
    inspect: Callable[[str], dict[str, Any]],
    list_agents: Callable[[], list[dict[str, Any]]],
    list_workspaces: Callable[[], list[dict[str, Any]]] | None = None,
    state_dir: Path | None = None,
    repo_leads_dir: Path | None = None,
    home: Path | None = None,
    ws_state_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
    exclude: set[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Resolve the current lead of `repo`: authoritative repo-keyed record first (`verified: true`), else live fallback (`verified: false`)."""
    clean = validate_repo(repo)
    e = _env(env)
    sdir = state_dir if state_dir is not None else succ.default_state_dir(e)
    phome = home if home is not None else succ.default_home(e)
    rdir = repo_leads_dir if repo_leads_dir is not None else default_repo_leads_dir(sdir, e)

    rec = read_repo_lead(clean, repo_leads_dir=rdir, state_dir=sdir, home=phome, env=e)
    stale_record: str | None = None
    if rec is not None:
        recorded_id = rec["lead"]
        try:
            resolved = succ.effective_lead(recorded_id, sdir, phome)
            resolved = _follow_live_acknowledged(resolved, inspect, sdir, phome)
        except succ.SuccessionError as exc:
            return {
                "repo": clean,
                "lead": None,
                "short_id": None,
                "verified": False,
                "source": "error",
                "reason": str(exc),
                "stale_record": recorded_id,
                "candidates": [],
            }
        try:
            info = inspect(resolved)
        except LookupError:
            stale_record = resolved
            info = None
        except Exception:  # noqa: BLE001 - Paseo unavailable: cannot confirm recorded lead is live
            return {
                "repo": clean,
                "lead": resolved,
                "short_id": resolved[:7],
                "verified": False,
                "source": "record-unconfirmed",
                "reason": "paseo unavailable to confirm recorded lead is live",
                "record": rec,
                "stale_record": None,
                "candidates": [],
            }
        if isinstance(info, dict) and info.get("Archived") is False and resolved not in set(exclude):
            ws_id = info.get("WorkspaceId") or info.get("workspaceId")
            ws_name = None
            if list_workspaces is not None and isinstance(ws_id, str):
                try:
                    for w in list_workspaces():
                        if isinstance(w, dict) and w.get("workspaceId") == ws_id:
                            raw_wn = w.get("name") if isinstance(w.get("name"), str) else w.get("title")
                            ws_name = raw_wn if isinstance(raw_wn, str) and raw_wn.strip() else None
                            break
                except Exception:  # noqa: BLE001
                    pass
            return {
                "repo": clean,
                "lead": resolved,
                "short_id": resolved[:7],
                "verified": True,
                "source": "record+succession" if resolved != recorded_id else "record",
                "record": rec,
                "workspace_id": ws_id,
                "window": ws_name,
                "tab": info.get("Name") or info.get("title"),
                "stale_record": None,
                "candidates": [],
            }
        stale_record = resolved

    candidates = discover_live_candidates(
        clean,
        list_agents=list_agents,
        list_workspaces=list_workspaces,
        ws_state_dir=ws_state_dir,
        exclude=exclude,
    )
    if len(candidates) == 1:
        c = candidates[0]
        return {
            "repo": clean,
            "lead": c["id"],
            "short_id": c["short_id"],
            "verified": False,
            "source": f"fallback:{c['reason']}",
            "workspace_id": c["workspace_id"],
            "window": c["window"],
            "tab": c["tab"],
            "stale_record": stale_record,
            "candidates": candidates,
        }
    if len(candidates) > 1:
        return {
            "repo": clean,
            "lead": None,
            "short_id": None,
            "verified": False,
            "source": "ambiguous",
            "stale_record": stale_record,
            "candidates": candidates,
        }
    return {
        "repo": clean,
        "lead": None,
        "short_id": None,
        "verified": False,
        "source": "none",
        "stale_record": stale_record,
        "candidates": [],
    }


def candidates_hint_for_refusal(
    target_record: Mapping[str, Any] | None,
    *,
    inspect: Callable[[str], dict[str, Any]],
    list_agents: Callable[[], list[dict[str, Any]]],
    list_workspaces: Callable[[], list[dict[str, Any]]] | None = None,
    state_dir: Path | None = None,
    repo_leads_dir: Path | None = None,
    home: Path | None = None,
    ws_state_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Build an informational refusal suffix naming recorded or live candidate leads for the target's repo (never a redirect)."""
    repo = infer_repo_from_agent(target_record)
    if not repo:
        return ""
    target_id = str(target_record.get("Id") or "") if isinstance(target_record, Mapping) else ""
    res = resolve_repo_lead(
        repo,
        inspect=inspect,
        list_agents=list_agents,
        list_workspaces=list_workspaces,
        state_dir=state_dir,
        repo_leads_dir=repo_leads_dir,
        home=home,
        ws_state_dir=ws_state_dir,
        env=env,
        exclude={target_id} if target_id else (),
    )
    if res.get("verified") and res.get("lead"):
        lead = res["lead"]
        desig = format_designation(
            lead,
            workspace_id=res.get("workspace_id"),
            window=res.get("window"),
            tab=res.get("tab"),
        )
        link_hint = (
            f" (or record succession: `ade-self-session link --predecessor {target_id} --successor {lead} --operator-attested`)"
            if UUID_RE.fullmatch(target_id) else ""
        )
        return f" Recorded live lead for {repo} (not auto-redirected — verify before sending): {desig}{link_hint}."
    cands = res.get("candidates") or []
    if cands:
        formatted = "; ".join(
            format_designation(c["id"], workspace_id=c.get("workspace_id"), window=c.get("window"), tab=c.get("tab"))
            + f" ({c['reason']})"
            for c in cands[:5]
        )
        return (
            f" Unverified live candidate lead(s) for {repo} (not redirected — verify before sending): {formatted}."
        )
    return ""


def paseo_inspect_fn(paseo: str = "paseo", timeout: int = 5, env: Mapping[str, str] | None = None):
    tenv = _env(env)
    use_cli = paseo_client.transport_mode(cli_override=paseo, env=tenv) == "cli"
    if not use_cli:
        client = None

        def inspect_daemon(ident: str) -> dict[str, Any]:
            nonlocal client
            try:
                if client is None:
                    client = paseo_client.PaseoClient(env=tenv, timeout=timeout)
                return client.inspect_agent(ident, cli_shape=True)
            except paseo_client.AgentNotFoundError as exc:
                raise LookupError(ident) from exc
            except paseo_client.DaemonError as exc:
                raise OSError(f"paseo daemon inspect failed: {exc}") from exc

        return inspect_daemon

    def inspect_cli(ident: str) -> dict[str, Any]:
        proc = subprocess.run([paseo, "agent", "inspect", ident, "--json"], capture_output=True, text=True,
                              timeout=timeout, check=False, env=dict(tenv))
        if proc.returncode != 0:
            text = (proc.stderr + proc.stdout).lower()
            if "not found" in text or "no agent" in text or "ambiguous" in text:
                raise LookupError(ident)
            raise OSError(f"paseo agent inspect exited {proc.returncode}")
        return json.loads(proc.stdout)

    return inspect_cli


def paseo_list_agents_fn(paseo: str = "paseo", timeout: int = 10, env: Mapping[str, str] | None = None):
    tenv = _env(env)
    use_cli = paseo_client.transport_mode(cli_override=paseo, env=tenv) == "cli"
    if not use_cli:
        client = None

        def ls_daemon() -> list[dict[str, Any]]:
            nonlocal client
            try:
                if client is None:
                    client = paseo_client.PaseoClient(env=tenv, timeout=timeout)
                rows = client.list_agents(include_background=True, include_archived=False, cli_rows=False)
            except paseo_client.DaemonError as exc:
                raise OSError(f"paseo daemon list_agents failed: {exc}") from exc
            return rows if isinstance(rows, list) else []

        return ls_daemon

    def ls_cli() -> list[dict[str, Any]]:
        proc = subprocess.run([paseo, "ls", "-g", "--json"], capture_output=True, text=True,
                              timeout=timeout, check=False, env=dict(tenv))
        if proc.returncode != 0:
            raise OSError(f"paseo ls exited {proc.returncode}")
        data = json.loads(proc.stdout)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("agents"), list):
            return data["agents"]
        return []

    return ls_cli


def paseo_list_workspaces_fn(paseo: str = "paseo", timeout: int = 10, env: Mapping[str, str] | None = None):
    tenv = _env(env)
    use_cli = paseo_client.transport_mode(cli_override=paseo, env=tenv) == "cli"
    if not use_cli:
        client = None

        def ws_daemon() -> list[dict[str, Any]]:
            nonlocal client
            try:
                if client is None:
                    client = paseo_client.PaseoClient(env=tenv, timeout=timeout)
                rows = client.list_workspaces(include_background=False)
            except paseo_client.DaemonError as exc:
                raise OSError(f"paseo daemon list_workspaces failed: {exc}") from exc
            return rows if isinstance(rows, list) else []

        return ws_daemon

    def ws_cli() -> list[dict[str, Any]]:
        proc = subprocess.run([paseo, "workspace", "ls", "--json"], capture_output=True, text=True,
                              timeout=timeout, check=False, env=dict(tenv))
        if proc.returncode != 0:
            raise OSError(f"paseo workspace ls exited {proc.returncode}")
        data = json.loads(proc.stdout)
        return data if isinstance(data, list) else []

    return ws_cli


def _format_human(res: dict[str, Any]) -> str:
    repo = res["repo"]
    if res.get("lead"):
        desig = format_designation(
            res["lead"],
            workspace_id=res.get("workspace_id"),
            window=res.get("window"),
            tab=res.get("tab"),
        )
        tag = "verified" if res.get("verified") else f"unverified ({res.get('source')})"
        return f"{repo}: {desig} [{tag}]"
    cands = res.get("candidates") or []
    if cands:
        lines = [f"{repo}: ambiguous ({len(cands)} unverified live candidates):"]
        for c in cands:
            lines.append("  " + format_designation(
                c["id"], workspace_id=c.get("workspace_id"), window=c.get("window"), tab=c.get("tab")
            ) + f" [{c['reason']}]")
        return "\n".join(lines)
    extra = f" (reason: {res['reason']})" if res.get("reason") else ""
    stale = f" (stale record: {res['stale_record']})" if res.get("stale_record") else ""
    return f"{repo}: no live lead found{stale}{extra}"


_GLOBAL_VALUE_OPTS = frozenset(("--state-dir", "--repo-leads-dir", "--paseo-home", "--paseo"))


def _insert_default_get(argv: list[str]) -> list[str]:
    """Allow shorthand `ade-lead-of [global opts] REPO [get opts]` alongside explicit `get`/`set`/`list`."""
    idx = 0
    while idx < len(argv):
        tok = argv[idx]
        if tok in ("-h", "--help"):
            return argv
        if tok in _GLOBAL_VALUE_OPTS:
            idx += 2
            continue
        if any(tok.startswith(opt + "=") for opt in _GLOBAL_VALUE_OPTS):
            idx += 1
            continue
        if tok.startswith("-"):
            return argv
        if tok not in ("get", "set", "list"):
            return [*argv[:idx], "get", *argv[idx:]]
        return argv
    return argv


def main(argv: list[str] | None = None) -> int:
    raw = _insert_default_get(list(sys.argv[1:] if argv is None else argv))
    p = argparse.ArgumentParser(prog="ade-lead-of", description=__doc__)
    p.add_argument("--state-dir", type=Path, default=None)
    p.add_argument("--repo-leads-dir", type=Path, default=None)
    p.add_argument("--paseo-home", type=Path, default=None)
    p.add_argument("--paseo", default="paseo")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("get", help="look up the current lead of REPO")
    g.add_argument("repo")
    g.add_argument("--json", action="store_true")
    g.add_argument("--allow-unverified", action="store_true",
                   help="exit 0 on a single unverified fallback candidate (default exits 3)")

    s = sub.add_parser("set", help="record AGENT_ID as the lead of REPO")
    s.add_argument("repo")
    s.add_argument("agent_id")
    s.add_argument("--cwd", default=None)
    s.add_argument("--offline", action="store_true", help="skip live Paseo liveness verification")
    s.add_argument("--json", action="store_true")

    ls_p = sub.add_parser("list", help="list all recorded repo leads")
    ls_p.add_argument("--json", action="store_true")

    args = p.parse_args(raw)
    sdir = args.state_dir or succ.default_state_dir()
    phome = args.paseo_home or succ.default_home()
    rdir = args.repo_leads_dir or default_repo_leads_dir(sdir)

    if args.cmd == "list":
        rows = list_repo_leads(repo_leads_dir=rdir, state_dir=sdir, home=phome)
        if args.json:
            print(json.dumps(rows, indent=2, sort_keys=True))
        else:
            for r in rows:
                print(f"{r['repo']}\t{r['lead'][:7]} ({r['lead']})\t{r.get('source', '')}\t{r.get('updated_at', '')}")
        return EXIT_OK

    if args.cmd == "set":
        try:
            clean = validate_repo(args.repo)
            if not UUID_RE.fullmatch(args.agent_id):
                raise ValueError(f"agent_id must be a full lowercase UUID (got {args.agent_id!r})")
        except ValueError as exc:
            print(f"ade-lead-of: {exc}", file=sys.stderr)
            return EXIT_USAGE
        cwd = args.cwd
        if not args.offline:
            inspect = paseo_inspect_fn(args.paseo)
            try:
                info = inspect(args.agent_id)
            except LookupError:
                print(f"ade-lead-of: agent {args.agent_id} not found in Paseo", file=sys.stderr)
                return EXIT_NOT_FOUND
            except OSError as exc:
                print(f"ade-lead-of: cannot inspect {args.agent_id} ({exc}); pass --offline to skip live check", file=sys.stderr)
                return EXIT_NOT_FOUND
            if info.get("Archived") is not False:
                print(f"ade-lead-of: refusing to record archived agent {args.agent_id} as lead of {clean}", file=sys.stderr)
                return EXIT_NOT_FOUND
            if cwd is None and isinstance(info.get("Cwd"), str):
                cwd = info["Cwd"]
        rec = write_repo_lead(clean, args.agent_id, source="manual", cwd=cwd,
                              repo_leads_dir=rdir, state_dir=sdir, home=phome)
        if args.json:
            print(json.dumps(rec, indent=2, sort_keys=True))
        else:
            print(f"recorded lead of {clean}: {rec['lead'][:7]} ({rec['lead']})")
        return EXIT_OK

    # cmd == "get"
    try:
        validate_repo(args.repo)
    except ValueError as exc:
        print(f"ade-lead-of: {exc}", file=sys.stderr)
        return EXIT_USAGE
    res = resolve_repo_lead(
        args.repo,
        inspect=paseo_inspect_fn(args.paseo),
        list_agents=paseo_list_agents_fn(args.paseo),
        list_workspaces=paseo_list_workspaces_fn(args.paseo),
        state_dir=sdir,
        repo_leads_dir=rdir,
        home=phome,
    )
    if args.json:
        print(json.dumps(res, indent=2, sort_keys=True))
    else:
        print(_format_human(res))
    if res.get("verified") and res.get("lead"):
        return EXIT_OK
    if res.get("lead"):
        return EXIT_OK if args.allow_unverified else EXIT_UNVERIFIED
    return EXIT_NOT_FOUND


if __name__ == "__main__":
    raise SystemExit(main())
