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

// The non-Claude agent a shell command runs and its `--model`, or undefined for any other command.
export function agentOf(command: string): { agent: string; model?: string } | undefined {
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
  const text = (description ?? '').trim() || command.replace(/\s+/g, ' ').trim().slice(0, 50)
  const a = agentOf(command)
  return a ? { label: a.model ? `${a.agent} ${a.model}` : a.agent, detail: text } : { label: text, detail: command.replace(/\s+/g, ' ').trim().slice(0, 200) }
}

// Where Claude Code keeps a background shell's output: `.../tasks/<id>.output` in 2.1.x
// ("You can read its output at ..."), "written to: ....output" in older text, or the result's own field.
export function outputPathOf(text: string | undefined, result?: unknown): string | undefined {
  const r = result && typeof result === 'object' ? (result as { backgroundOutputPath?: unknown }) : undefined
  if (typeof r?.backgroundOutputPath === 'string' && r.backgroundOutputPath) return r.backgroundOutputPath
  const t = text ?? ''
  return /(\/[^\s"'`]*\/tasks\/[\w-]+\.output)/.exec(t)?.[1] ?? /(?:written to|output (?:file )?(?:is|at)):?\s+(\S+\.output)/i.exec(t)?.[1]
}

export function baseName(path: string) {
  return path.slice(path.lastIndexOf('/') + 1)
}

// Is this shell command the waiter or the launcher of that job? Then the job is the one line.
export function jobMatches(command: string, job: Pick<AcpJob, 'name' | 'record' | 'done' | 'rearm'>): boolean {
  if (job.record && command.includes(job.record)) return true
  if (job.done && command.includes(job.done)) return true
  if (job.rearm && command.includes(job.rearm)) return true
  const name = /acp-dispatch\b[^;&|]*?--name[ =]["']?([\w.-]+)/.exec(command)?.[1]
  return name !== undefined && name === job.name
}

export function clean(text: string) {
  return text.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, '')
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
    if (words.trim()) out.push(...words.split(/\n+/).map(l => l.trim()).filter(Boolean).map(l => l.slice(0, 200)))
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
      out.push(`> ${String(d.title ?? 'tool').slice(0, 200)}`)
    } else if (ev.kind === 'turn') {
      flush()
      out.push(`turn ${d.n ?? '?'}: ${d.stop_reason ?? 'ended'}${typeof d.seconds === 'number' ? ` after ${Math.round(d.seconds)}s` : ''}`)
    } else if (ev.kind === 'result') {
      flush()
      out.push(`result: exit ${d.exit ?? '?'}${d.tool_calls !== undefined ? ` · ${d.tool_calls} tool calls` : ''}`)
    }
  }
  flush()
  return out.slice(-n)
}

// The shell script that lists this session's job records: only records that name the session and
// changed in the last 3 days, each after a \001 line with its path. One process for all of them.
export const RECORDS_SH = `# radar:records
root=$1; sid=$2
[ -d "$root" ] || exit 0
find "$root" -maxdepth 3 -type f -path '*/jobs/*.json' -mtime -3 -exec grep -lF -- "$sid" {} + 2>/dev/null |
  while IFS= read -r f; do printf '\\001%s\\n' "$f"; cat -- "$f"; done
exit 0
`

// The tail of each file named, each after a \001 line with its path: one process for all of them.
export const TAILS_SH = `# radar:tails
for f in "$@"; do printf '\\001%s\\n' "$f"; tail -c 16384 -- "$f" 2>/dev/null; done
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
export function parseRecords(stdout: string, sessionId: string): AcpJob[] {
  const jobs: AcpJob[] = []
  for (const { path, body } of blocks(stdout)) {
    try {
      const r = JSON.parse(body) as Record<string, any>
      if (!r || typeof r.name !== 'string' || r.owner !== sessionId || r.status === 'dry-run') continue
      jobs.push({
        name: r.name,
        agent: String(r.agent ?? '?'),
        model: r.model ?? null,
        effort: r.effort ?? null,
        status: String(r.status ?? 'running'),
        exit: typeof r.exit === 'number' ? r.exit : null,
        report: typeof r.report === 'string' ? r.report : undefined,
        log: typeof r.log === 'string' ? r.log : undefined,
        record: typeof r.record === 'string' ? r.record : path,
        done: typeof r.done === 'string' ? r.done : undefined,
        rearm: typeof r.rearm === 'string' ? r.rearm : undefined,
        started: typeof r.started === 'number' ? r.started : undefined,
        finished: typeof r.finished === 'number' ? r.finished : null,
      })
    } catch {
      /* a record being rewritten: the next poll reads it whole */
    }
  }
  return jobs
}

export function isJobRunning(job: Pick<AcpJob, 'status'>) {
  return job.status === 'running' || job.status === 'pending'
}

// File names `lsof -Fn` reports open, as base names (the task id is unique; /tmp and /private/tmp agree).
export function parseOpen(stdout: string): Set<string> {
  const open = new Set<string>()
  for (const line of stdout.split('\n')) if (line.startsWith('n')) open.add(baseName(line.slice(1).trim()))
  return open
}
