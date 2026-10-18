// Pure helpers for the fork's background shells and acp-dispatch jobs: parsing commands,
// output paths, job records and log tails. Nothing here touches `$`, so tests call it directly.
import type { AcpJob } from '../types'

// Agent CLIs behind `acp-run <agent>` / `acp-dispatch <agent>`.
const ACP_AGENTS = 'codex|grok|agy|opencode|cursor-agent|cursor|crush|copilot|qwen|cline|omp|hermes|zcode|gemini|muse|kiro|claude'
// Where a command starts: after `;`, `&&`, `|`, `(`, then `timeout 900`, `nohup`, `FOO=1` and the like.
const START = String.raw`(?:^|[;&|(])\s*(?:\w+=\S*\s+)*(?:(?:timeout|nohup|nice|env|time|command)(?:\s+[-\w.=:]+)*\s+)?(?:\S*\/)?`
const ACP_RUN = new RegExp(`${START}acp-(?:run|dispatch)\\s+(?:--agent[ =])?(${ACP_AGENTS})(?=\\s|$)`)
const DIRECT = new RegExp(`${START}(?:(codex)\\s+exec|(opencode)\\s+run|(cursor-agent|agy|crush|copilot|qwen|cline|omp|hermes))(?=\\s|$)`)
const MODEL = /(?:^|\s)(?:--model|-m)(?:\s+|=)["']?(\w[\w.:/-]*)/
const CODEX_MODEL = /\s-c\s+["']?model\s*=\s*\\?["']?([\w.:/-]+)/

const MAX_COMMAND = 4096 // the agent CLI and its --model come early; a huge command must not stall the regexes
const MAX_FIELD = 200 // one displayed field of a job record
const MAX_PATH = 1024

// The non-Claude agent a shell command runs and its `--model`, or undefined for any other command.
export function agentOf(full: string): { agent: string; model?: string } | undefined {
  const command = full.slice(0, MAX_COMMAND)
  const m = ACP_RUN.exec(command) ?? DIRECT.exec(command)
  if (!m) return undefined
  const agent = m[1] ?? m[2] ?? m[3] ?? m[4]
  if (!agent) return undefined
  const part = command.slice(m.index).split(/\s*(?:&&|\|\||;|\|(?!&))\s*/)[0]!
  // A quoted prompt may mention --model: look past quoted strings, except as a flag's own value.
  const bare = part.replace(/(?<!(?:--model|-m)[\s=])(["'])(?:(?!\1).)*\1/g, ' _ ')
  const model = MODEL.exec(bare)?.[1] ?? CODEX_MODEL.exec(part)?.[1]
  return { agent, model }
}

// What the band calls a background shell: the agent and model it runs, else the Bash
// description, else the first 50 characters of the command. `detail` is the other one, for the pane.
export function shellLabel(command: string, description?: string): { label: string; detail: string } {
  const flat = oneLine(command.slice(0, MAX_COMMAND), 200)
  const text = oneLine(description ?? '', 200) || flat.slice(0, 50)
  const a = agentOf(command)
  return a ? { label: a.model ? `${a.agent} ${a.model}` : a.agent, detail: text } : { label: text, detail: flat }
}

// Where Claude Code keeps a background shell's output: `.../tasks/<id>.output` in 2.1.x
// ("You can read its output at ..."), "written to: ....output" in older text, or the result's own field.
// Only an absolute path with no whitespace, control characters or `..` is taken: lsof and tail run on it.
export function outputPathOf(text: string | undefined, result?: unknown): string | undefined {
  const r = result && typeof result === 'object' ? (result as { backgroundOutputPath?: unknown }) : undefined
  if (isOutputPath(r?.backgroundOutputPath)) return r.backgroundOutputPath
  const t = (text ?? '').slice(0, MAX_COMMAND)
  const found = [/(\/[^\s"'`]*\/tasks\/[\w-]+\.output)/.exec(t)?.[1], /(?:written to|output (?:file )?(?:is|at)):?\s+(\S+\.output)/i.exec(t)?.[1]]
  return found.find(isOutputPath)
}

// A path the radar may hand to lsof, tail or the screen: absolute, no whitespace or control characters
// (C0, DEL, C1, bidi), no `..` segment, not absurdly long.
export function isSafePath(p: unknown): p is string {
  return typeof p === 'string' && p.length <= MAX_PATH && /^\/[^\x00-\x20\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]+$/.test(p) && !p.split('/').includes('..')
}

export function isOutputPath(p: unknown): p is string {
  return isSafePath(p) && p.endsWith('.output')
}

export function baseName(path: string) {
  return path.slice(path.lastIndexOf('/') + 1)
}

// Does the command name this path as a whole word (not inside a longer path or file name)?
function mentions(command: string, p: string | undefined): boolean {
  if (!p) return false
  for (let i = command.indexOf(p); i >= 0; i = command.indexOf(p, i + 1)) {
    if (!/[\w./~-]/.test(command[i - 1] ?? ' ') && !/[\w./-]/.test(command[i + p.length] ?? ' ')) return true
  }
  return false
}

// Is this shell command the waiter or the launcher of that job? Then the job is the one line.
// By identity only: the record path (what `rearm` runs on) or the .done marker named as a word, or the
// launcher's `--name`. `record` and `done` are the paths the scan found and checked (parseRecords), never a
// short string a record could choose to match every command.
export function jobMatches(command: string, job: Pick<AcpJob, 'name' | 'record' | 'done'>): boolean {
  if (mentions(command, job.record) || mentions(command, job.done)) return true
  const name = /acp-dispatch\b[^;&|]*?--name[ =]["']?([\w.-]+)/.exec(command.slice(0, MAX_COMMAND))?.[1] // capped: the lazy scan is quadratic
  return name !== undefined && name === job.name
}

// Text from a command, a log or a record is shown on the terminal: drop every escape sequence (CSI, OSC such as
// the clipboard write, DCS and the like, 7- and 8-bit), every other control character (tab and line breaks stay)
// and the bidi controls that make text read in another order than it is written.
const ESCAPES = /\x1b(?:\[[0-?]*[ -/]*[@-~]|[\]PX^_][\s\S]*?(?:\x07|\x1b\\|$)|[ -/]*[0-~])|\x9b[0-?]*[ -/]*[@-~]|[\x90\x98\x9d\x9e\x9f][\s\S]*?(?:\x07|\x9c|$)|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/g
export function clean(text: string) {
  return text.replace(ESCAPES, '')
}

// One displayed line from external text: cut first (so no regex sees a huge string), cleaned, whitespace collapsed.
export function oneLine(text: unknown, max = MAX_FIELD): string {
  return typeof text === 'string' ? clean(text.slice(0, max * 4)).replace(/\s+/g, ' ').trim().slice(0, max) : ''
}

// The last n non-empty lines of an output tail (carriage-return progress included), each cut short.
export function tailLines(text: string, n = 8): string[] {
  return clean(text)
    .split(/[\r\n]+/)
    .map(l => l.trimEnd())
    .filter(l => l.trim() !== '')
    .slice(-n)
    .map(l => l.slice(0, 200))
}

// An acp-run log (JSONL of ACP events) tail as short lines: tool calls and the agent's own words.
// The first line of a tail is usually cut in half and is skipped when it does not parse.
export function logSummary(text: string, n = 8): string[] {
  const out: string[] = []
  let words = ''
  const flush = () => {
    if (words.trim()) out.push(...clean(words).split(/[\r\n]+/).map(l => l.trim()).filter(Boolean).map(l => l.slice(0, 200)))
    words = ''
  }
  for (const raw of text.split('\n')) {
    let ev: { kind?: string; data?: Record<string, any> }
    try {
      ev = JSON.parse(raw)
    } catch {
      continue
    }
    const d = ev.data ?? {}
    if (ev.kind === 'update' && d.sessionUpdate === 'agent_message_chunk') words += String(d.content?.text ?? '')
    else if (ev.kind === 'update' && d.sessionUpdate === 'tool_call') {
      flush()
      out.push(`> ${oneLine(String(d.title ?? 'tool')) || 'tool'}`)
    } else if (ev.kind === 'turn') {
      flush()
      out.push(`turn ${oneLine(String(d.n ?? '?'), 20) || '?'}: ${oneLine(String(d.stop_reason ?? 'ended'), 40) || 'ended'}${typeof d.seconds === 'number' ? ` after ${Math.round(d.seconds)}s` : ''}`)
    } else if (ev.kind === 'result') {
      flush()
      out.push(`result: exit ${oneLine(String(d.exit ?? '?'), 20) || '?'}${d.tool_calls !== undefined ? ` · ${oneLine(String(d.tool_calls), 20)} tool calls` : ''}`)
    }
  }
  flush()
  return out.slice(-n)
}

// The shell script that lists this session's job records: only records that name the session and
// changed in the last 3 days, each after a \001 line with its path. One process for all of them.
// A \001 inside a file is dropped (LC_ALL=C: BSD tr rejects invalid UTF-8), so no file can forge a block.
// A record is read only if it is a regular file under 64 KiB, and at most 64 KiB of it, once: the session id is
// looked for in that one copy. The read runs under the alarm of TAILS_SH (a record swapped for a FIFO between
// find's type check and the open would block `head` for ever, and find and sh with it). `-exec sh -c 'for f'`
// keeps a file name with a newline in one piece. A relative or option-like $root (ACP_DISPATCH_STATE) is refused.
export const RECORDS_SH = `# radar:records
root=$1; sid=$2
case $root in /*) ;; *) exit 0;; esac
[ -d "$root" ] || exit 0
# a slice whose process died without finalize would otherwise read as running forever (2026-10-18). At most once
# per 2 minutes machine-wide, detached: inline on every 5 s poll of every session it started a Python reap per poll,
# the poll's 8 s timeout orphaned them on the starved E-cores, and load reached 110 (2026-10-18).
stamp="$root/.radar-reap-stamp"
if command -v acp-dispatch >/dev/null 2>&1 && [ -z "$(find "$stamp" -mmin -2 2>/dev/null)" ]; then
  : > "$stamp" 2>/dev/null && ( acp-dispatch reap --quiet "$root" </dev/null >/dev/null 2>&1 & )
fi
# Only records that name the session go through the per-file read below: one grep for all of them first
# (-D skip passes FIFOs and devices by, --null keeps any file name whole). Reading all ~44 records every
# poll cost sh+head+watchdog+sleep per record per session, ~250 forks/s across 7 sessions (2026-10-18).
find "$root" -maxdepth 3 -type f -path '*/jobs/*.json' -mtime -3 -size -64k -exec grep -l --null -D skip -F -- "$sid" {} + 2>/dev/null | xargs -0 sh -c 'sid=$1; shift; for f; do b=$(perl -e "alarm 3; exec @ARGV" head -c 65536 -- "$f" 2>/dev/null | LC_ALL=C tr -d "\\001"); case $b in *"$sid"*) printf "\\001%s\\n%s\\n" "$f" "$b";; esac; done' sh "$sid" 2>/dev/null
exit 0
`

// The tail of each file named, each after a \001 line with its path: one process for all of them.
// A \001 inside a tail is dropped (see RECORDS_SH), so a log cannot forge the tail of another file.
// Only a regular file that is not a symlink is tailed (not a FIFO or a device such as /dev/zero, which tail would
// never finish reading), and the tail is killed after 3 s anyway, in case a file is swapped for a FIFO between the check and
// the open: `perl -e 'alarm 3; exec @ARGV'` arms SIGALRM and becomes the tail, so the alarm kills that one
// process. It replaced a `( sleep 3; kill $t ) &` watchdog subshell per file: killing the subshell left its
// `sleep 3` orphaned, 4 forks per file per 5 s poll per session, 75 orphans alive at once and load 46
// (2026-10-18).
export const TAILS_SH = `# radar:tails
for f in "$@"; do
  printf '\\001%s\\n' "$f"
  [ -f "$f" ] && [ ! -L "$f" ] || continue
  perl -e 'alarm 3; exec @ARGV' tail -c 16384 -- "$f" 2>/dev/null | LC_ALL=C tr -d '\\001'
done
exit 0
`

// Splits "\001path\n<body>" blocks.
export function blocks(stdout: string): { path: string; body: string }[] {
  return stdout
    .split('\x01')
    .filter(Boolean)
    .map(b => {
      const nl = b.indexOf('\n')
      return nl < 0 ? { path: b.trim(), body: '' } : { path: b.slice(0, nl).trim(), body: b.slice(nl + 1) }
    })
}

// The job records this session owns. Anything that is no JSON object with a name is skipped.
// Every field is external data: text is cleaned and cut, paths are kept only if `isSafePath` and inside the
// record's own <out> (the log is read by tail, the others are shown or matched), numbers only if finite.
// `rearm` is not kept: it only repeats the record path.
export function parseRecords(stdout: string, sessionId: string): AcpJob[] {
  const jobs: AcpJob[] = []
  for (const { path, body } of blocks(stdout)) {
    try {
      const r = JSON.parse(body) as Record<string, any>
      if (!r || typeof r.name !== 'string' || r.owner !== sessionId || r.status === 'dry-run') continue
      const name = oneLine(r.name, 100)
      if (!name) continue
      // acp-dispatch writes <out>/jobs/<name>.json and the report, marker and log into <out>: so the record is
      // the file the scan found (a record cannot name another), and every other path must be inside that <out>.
      const dir = path.slice(0, path.lastIndexOf('/'))
      const out = dir.slice(0, -'/jobs'.length)
      if (!isSafePath(path) || !dir.endsWith('/jobs') || out.length < 2 || baseName(path) !== `${r.name}.json`) continue
      const inside = (p: unknown): p is string => isSafePath(p) && p.startsWith(`${out}/`)
      const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : undefined)
      const field = (v: unknown, max = 64) => oneLine(v, max) || undefined
      jobs.push({
        name,
        agent: field(r.agent) ?? '?',
        model: field(r.model) ?? null,
        effort: field(r.effort, 32) ?? null,
        status: field(r.status, 32) ?? 'running',
        exit: num(r.exit) ?? null,
        report: inside(r.report) ? r.report : undefined,
        log: inside(r.log) ? r.log : undefined,
        record: path,
        done: inside(r.done) && r.done.endsWith('.done') ? r.done : undefined,
        started: num(r.started),
        finished: num(r.finished) ?? null,
      })
    } catch {
      /* a record being rewritten: the next poll reads it whole */
    }
  }
  return jobs
}

// A command that dispatches a job (or works with the bigteam state): the records scan starts after one.
export function isDispatchCommand(command: string): boolean {
  return /\b(?:acp-dispatch|bigteam)\b/.test(command.slice(0, MAX_COMMAND))
}

// Scan the job records? Only once this session has run a dispatch command and until no tracked job
// runs and `afterMs` have passed since the last one; `force` (the first /radar) scans once regardless.
export function shouldScan(list: readonly { kind?: string; status: string }[], lastDispatchAt: number, at: number, force = false, afterMs = 60_000): boolean {
  if (force) return true
  if (list.some(a => a.kind === 'acp' && a.status === 'running')) return true
  return lastDispatchAt > 0 && at - lastDispatchAt < afterMs
}

export function isJobRunning(job: Pick<AcpJob, 'status'>) {
  return job.status === 'running' || job.status === 'pending' || job.status === 'resume-scheduled'
}

// File names `lsof -Fn` reports open, as base names (the task id is unique; /tmp and /private/tmp agree).
export function parseOpen(stdout: string): Set<string> {
  const open = new Set<string>()
  for (const line of stdout.split('\n')) if (line.startsWith('n')) open.add(baseName(line.slice(1).trim()))
  return open
}
