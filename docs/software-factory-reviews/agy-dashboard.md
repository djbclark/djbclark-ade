# Raw response: acp-run agy (default model), section 7 dashboard UX (2026-10-19 ~15:05 EDT)

acp-run applied: {"model": "gemini-3.8-flash", "effort": "high", "ctx": 1048576, "ctx_source": "usage_update"}; no cost reported; exit 0

---

MODEL: Gemini 2.5 Pro

### 1. Fatal Flaw: The Broken Phone/Telegram Loop (P0)
Daniel lives on Telegram/Hermes, but the plan treats mobile actionability as an afterthought (D4). 
* **The Gap:** A read-only mobile glance that requires opening a laptop to approve or rework fails J1/J2. 
* **Fix:** The primary interaction loop must be **Telegram-native interactive cards**: an alert message with the failure snippet, diff stat, and inline buttons (`[Approve]`, `[Rework]`, `[View Diff]`). Tapping `[Rework]` should prompt for a Telegram reply text that posts directly to the orchestrator inbox. Mobile webview should be a fallback, not the primary mobile interface.

---

### 2. Information Architecture & Wireframe Critiques (P0)
* **Needs-You Row Over-compression:** In Desktop Wireframe 7.4.1, `004-retry-backoff` shows `security CHANGES x3`, but hides the actual blocker reason. Daniel cannot act (`[a][w]`) without seeing *why*. Put the failure reason (e.g., `"token logged in debug path"`) directly under the job title as a secondary line in the queue.
* **Kill the Kanban Board (7.3, 7.4.1):** Kanban columns across automated loop stages (`review r1 -> build -> review r2`) provide zero utility for an autonomous factory; jobs bounce back and forth, turning boards into visual noise. Kill the `[table|board]` toggle. Use a strict, single-column **Triage View**:
  1. *Attention Queue* (Needs Human, Stuck, Blocked Quota)
  2. *Active Runs* (In-progress, heartbeats)
  3. *Recent History / Archive* (Filterable table)
* **Hygiene & Spend as Standalone Tabs is Over-built:** Stale worktrees or unisolated checkouts are system invariants. If an agent runs unisolated on `master`, that is an emergency banner in the header with an instant `[Isolate / Kill]` button, not a passive panel you browse.

---

### 3. User Journey Refinements (P1)
* **J3 (Rework) Needs Granular Feedback:** Reworking with a freeform multi-line note leads to agent drift. The UI must offer checkboxes next to failing reviewer findings: `[x] Address security finding (r3)`, `[ ] Ignore UX nit`. This scopes the rework prompt automatically.
* **J4 (Start Job) is Web-Bloat:** Selecting role models, budget tables, and vendors in a web modal duplicates CLI/spec workflows. For v1, dashboard J4 should strictly be **`Clone / Re-run with tweaks`** or **`Trigger from Issue URL`**. Keep spec creation in Git/CLI.

---

### 4. States & Live Updates (P1)
* **Blunt Stuck Detection (7.5.3):** A flat `stuck_after (10m)` heuristic produces false alarms during large test suites or slow LLM reasoning chains. Distinguish sub-states: `inferring` (awaiting API chunk) vs `running_tool` (process alive with PID).
* **Polling Battery Drain (7.6.1):** Polling `index.json` every 5s destroys mobile battery. Use HTTP `ETag` / `304 Not Modified`, back off to 60s when inactive, and trigger an immediate fetch on window focus (`visibilitychange`).

---

### 5. Keyboard Shortcuts & Safety (P2)
* **Dangerous Single Keys (7.8.3):** Single-key triggers (`a` approve, `w` rework, `r` retry) without modifier chords are prone to misfires when focus slips out of an input field. Adopt `g`-prefixed or command-palette interactions (e.g., `x a` to approve, `x r` to rework), or require standard `Cmd+Enter` confirmation.
* **Diff Navigation:** Missing single-key file jumper in diff view (`n` / `p` for next/prev changed file, `j` / `k` for hunks).

---

### 6. Accessibility & Polish (P2)
* Live regions: Ensure `aria-live="assertive"` is bound specifically to the *Needs You* counter increment, while background log tails stay `aria-live="off"` to prevent screen reader thrashing.
* High-contrast diffs: Side-by-side diffs break on mobile widths. Enforce unified diff view with sticky file headers on viewports `< 768px`.

---

### 7. Reprioritized Delivery Plan
* **D1 (Core Loop):** Headless alerts with Telegram/Hermes inline action callbacks (`Approve`, `Rework`) + static HTML triage view (Needs You + Running).
* **D2 (Detail & Diff):** Job detail, diff viewer with unified mobile layout, and basic log tail.
* **D3 (Desktop Speed):** Keyboard navigation, `Cmd+K` palette, local actions via inbox.
* **Cut / Defer:** Kanban view, interactive job creation wizard, standalone hygiene explorer.
