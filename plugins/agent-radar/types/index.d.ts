export type RadarKind = 'agent' | 'shell' | 'acp'

// The fields of an acp-dispatch job record (jobs/<name>.json) the radar keeps.
export type AcpJob = {
  name: string
  agent: string
  model?: string | null
  effort?: string | null
  status: string // running, done, no-report, blocked, partial, ...
  exit?: number | null
  report?: string
  log?: string
  record?: string
  done?: string
  rearm?: string
  started?: number // epoch seconds
  finished?: number | null
}

export type RadarAgent = {
  id: string
  description: string
  type: string
  status: 'running' | 'done' | 'failed'
  startedAt: number
  endedAt?: number
  tools: number
  last: string
  kind?: RadarKind // absent: a subagent (state written before the fork)
  command?: string // shell: the Bash command
  detail?: string // shell: the Bash description, else the start of the command
  out?: string // shell: the file Claude Code writes its output to
  seen?: boolean // shell: its output file has been seen open
  misses?: number // shell: consecutive polls that found its output file closed
  hidden?: boolean // shell: shown as an acp job instead
  lines?: string[] // shell output / acp log, last lines for the pane
  final?: boolean // acp: the last log lines were read after it ended
  job?: AcpJob // acp: its job record
}

declare module 'claude-code' {
  interface PluginState {
    'agent-radar': { agents: RadarAgent[]; selected: string | null; now: number }
  }
}
