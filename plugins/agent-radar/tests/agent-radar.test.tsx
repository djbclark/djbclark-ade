import { describe, expect, mock, test } from 'claude-code/testing'

import { describe as label, elapsed, isShown, resetBandOrder } from '../hooks/register'
import { RECORDS_SH, TAILS_SH, agentOf, baseName, blocks, clean, isDispatchCommand, isOutputPath, isSafePath, jobMatches, logSummary, oneLine, outputPathOf, parseRecords, shellLabel, shouldScan, tailLines } from '../hooks/watch'

const BAND = { component: 'AbovePrompt', props: { hasSurvey: false, isWorking: true, maxRows: 10, bodyColumns: 120 } }
const PANE = { component: 'Pane', requestId: 'agent-radar', props: { title: 'Agent Radar', isFocused: true, bodyColumns: 100, placement: 'dock' } }

const OUT = '/private/tmp/c/p/s/tasks/bqumpaw3k.output'
const NOW = () => Date.now() / 1000

// Stands for the engine beneath the mod: lsof sees OUT open while `state.open` holds, the records script
// lists `state.records`, the tails script answers from `state.tails`.
function engine(on: any, files: Record<string, string> = {}, beneath?: unknown) {
  const clock = mock.clock(on, { now: 0 })
  const toasts: string[] = []
  const state = { messages: [{ role: 'user', text: 'Run the sweep', toolUses: [] }, { role: 'assistant', text: 'Sweep is at trial 12 of 40.', toolUses: [] }] as any[], n: 0, file: undefined as string | undefined, open: true, records: [] as any[], tails: {} as Record<string, string>, runs: [] as string[][] }
  resetBandOrder()
  on('env.get', (_$: any, e: any) => ({ value: e.name === 'HOME' ? '/home/me' : undefined }))
  on('fs.exists', (_$: any, e: any) => ({ value: e.path in files }))
  on('fs.read', (_$: any, e: any) => ({ value: files[e.path] ?? '' }))
  on('session.start', (_$: any, e: any) => ({ sessionId: 's', cwd: e.cwd }))
  on('session.id', () => ({ value: 's' }))
  on('command.register', () => ({ value: undefined }))
  on('tool.call', () => {
    const file = state.file ?? (state.n++ === 0 ? OUT : `/private/tmp/c/p/s/tasks/b${state.n}.output`)
    return { result: { backgroundTaskId: baseName(file) }, text: `Command running in background. You can read its output at ${file}` }
  })
  on('agent.spawn', () => ({ model: 'sonnet', agentId: 'a1' }))
  on('agent.list', () => ({ value: [] }))
  on('turn.complete', () => ({ text: '' }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.panes', () => ({ value: [] }))
  on('ui.toast', (_$: any, e: any) => (toasts.push(e.text), { value: undefined }))
  on('ui.render', ($: any, e: any) => beneath ?? $.ui.resolve(e).Text({ children: 'band below' }))
  on('session.messages', () => ({ value: state.messages }))
  on('process.run', (_$: any, e: any) => {
    const [cmd, flag, script] = e.argv as string[]
    state.runs.push(e.argv)
    if (cmd?.endsWith('lsof')) {
      const files = (e.argv as string[]).slice(3)
      return { value: { exitCode: state.open ? 0 : 1, stdout: state.open ? files.map(f => `p42\nn${f}\n`).join('') : '', stderr: '' } }
    }
    if (cmd === 'sh' && flag === '-c' && script?.includes('radar:records')) {
      return { value: { exitCode: 0, stdout: state.records.map(r => `\x01${r.record}\n${JSON.stringify(r)}\n`).join(''), stderr: '' } }
    }
    if (cmd === 'sh' && flag === '-c' && script?.includes('radar:tails')) {
      const files = (e.argv as string[]).slice(4)
      return { value: { exitCode: 0, stdout: files.map(f => `\x01${f}\n${state.tails[f] ?? ''}`).join(''), stderr: '' } }
    }
    return { value: { exitCode: 0, stdout: '', stderr: '' } }
  })
  return { clock, toasts, state }
}

const settle = () => new Promise(done => (globalThis as any).setTimeout(done, 20)) // a poll runs in the background
// A poll under load can take longer than settle: wait for what it should have done, up to 4 s.
async function eventually(check: () => unknown) {
  for (let i = 0; i < 160 && !(await check()); i++) await new Promise(done => (globalThis as any).setTimeout(done, 25))
}

// An acp-dispatch job record as the writer leaves it (the keys the radar reads).
function job(over: Record<string, unknown> = {}) {
  return {
    name: 'docs',
    agent: 'grok',
    model: 'grok-4.7',
    effort: 'high',
    owner: 's',
    started: NOW(),
    finished: null,
    status: 'running',
    exit: null,
    record: '/state/t/jobs/docs.json',
    report: '/state/t/docs-report.md',
    done: '/state/t/docs-report.md.done',
    log: '/state/t/docs.jsonl',
    rearm: "/b/acp-dispatch wait /state/t/jobs/docs.json && /b/acp-dispatch check /state/t/jobs/docs.json",
    ...over,
  }
}

describe('agent-radar', () => {
  test('helpers', () => {
    expect(elapsed({ startedAt: 0, endedAt: 252_000 })).toBe('4m 12s')
    expect(elapsed({ startedAt: 0, endedAt: 9_000 })).toBe('9s')
    expect(label({ tool: 'mcp__plugin_playwright_playwright__browser_click' })).toBe('browser: click')
    const done = (ago: number) => ({ id: 'x', description: 'd', type: 't', status: 'done' as const, startedAt: 0, endedAt: Date.now() - ago, tools: 0, last: '' })
    expect(isShown(done(5_000))).toBe(true)
    expect([done(600_000)].filter(a => isShown(a))).toEqual([]) // gone after 30 s
  })

  test('a spawned agent shows in the pane, opens to its messages, and toasts when done', async ($, on) => {
    const { toasts } = engine(on)
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' } as any)
    await $.agent.spawn({ prompt: 'run it', description: 'sweep runner' } as any)

    const band = await $.ui.mount({ plugin: 'agent-radar', surface: 'terminal', ...BAND } as any)
    expect(await band.find({ type: 'Text', text: / ● sweep runner/ })).toBeDefined()
    expect(await band.find({ type: 'Text', text: /band below/ })).toBeDefined()
    // the radar sits on top: what other mods draw stays below it
    const root: any = await band.drawn()
    expect(root.props.key).toBe('bands')
    expect(root.children.map((c: any) => c.props?.key)).toEqual(['band:agent-radar', undefined])

    const r = await $.command.run({ command: 'radar', args: '' } as any)
    expect(r.text).toBe('1 running, 0 finished')

    const ui = await $.ui.mount({ plugin: 'agent-radar', surface: 'terminal', ...PANE } as any)
    expect(await ui.find({ type: 'Text', text: /1 running · 0 finished/ })).toBeDefined()
    expect(await ui.find({ key: 'agent-a1' })).toBeDefined()

    await ui.press({ key: 'agent-a1' })
    expect(await ui.find({ type: 'Text', text: /Sweep is at trial 12 of 40/ })).toBeDefined()
    await ui.press({ key: 'back' })

    await $.turn.complete({ reason: 'answer', answer: 'done', durationMs: 1, agentId: 'a1' } as any)
    expect(toasts[0]).toMatch(/^✓ sweep runner done \(\d+s · 0 tools\)$/)
    expect(await ui.find({ type: 'Text', text: /0 running · 1 finished/ })).toBeDefined()
    expect(await band.find({ type: 'Text', text: / ✓ sweep runner/ })).toBeDefined() // still shown for 30 s
    await ui.unmount()
    await band.unmount()
  })

  test('follows the band order file', async ($, on) => {
    // another band mod drew its column beneath
    const beneath = {
      type: 'Box',
      props: { key: 'bands', flexDirection: 'column' },
      children: [{ type: 'Box', props: { key: 'band:where-am-i' }, children: [{ type: 'Text', children: ['here'] }] }],
    }
    engine(on, { '/home/me/.claude/claude-code-mods/bands.json': '{"order":["where-am-i","agent-radar"]}' }, beneath)
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' } as any)
    await $.agent.spawn({ prompt: 'run it', description: 'sweep runner' } as any)
    const band = await $.ui.mount({ plugin: 'agent-radar', surface: 'terminal', ...BAND } as any)
    const root: any = await band.drawn()
    expect(root.children.map((c: any) => c.props.key)).toEqual(['band:where-am-i', 'band:agent-radar'])
    await band.unmount()
  })

  test('fork helpers', () => {
    expect(agentOf("acp-run codex -C /x -p 'hello --model nope' --model gpt-6-astra")).toEqual({ agent: 'codex', model: 'gpt-6-astra' })
    expect(agentOf('cd /x && timeout 900 acp-dispatch grok --name docs --model=grok-4.7')).toEqual({ agent: 'grok', model: 'grok-4.7' })
    expect(agentOf('codex exec -c \'model="gpt-6-luna"\' "fix it"')).toEqual({ agent: 'codex', model: 'gpt-6-luna' })
    expect(agentOf('opencode run -m zai/glm hi')?.agent).toBe('opencode')
    expect(agentOf('cursor-agent -p hi')?.agent).toBe('cursor-agent')
    expect(agentOf('acp-dispatch footer --report r.md')).toBeUndefined()
    expect(agentOf('git commit -m "ask codex exec"')).toBeUndefined()
    expect(agentOf('gh run watch 123')).toBeUndefined()
    expect(shellLabel('acp-run codex -p x --model gpt-6-astra', 'Ask codex').label).toBe('codex gpt-6-astra')
    expect(shellLabel('gh run watch 123 --exit-status', 'Watch CI')).toEqual({ label: 'Watch CI', detail: 'gh run watch 123 --exit-status' })
    expect(shellLabel('sleep 600 && echo hi && echo a very long command line that goes on', undefined).label).toBe('sleep 600 && echo hi && echo a very long command l')
    expect(outputPathOf('You can read its output at /private/tmp/c/p/s/tasks/bqumpaw3k.output')).toBe(OUT)
    expect(outputPathOf('Output is being written to: /tmp/b1.output')).toBe('/tmp/b1.output')
    expect(outputPathOf('Output is being written to: /private/tmp/c/p/s/tasks/bor07nzv3.output. You will be notified')).toBe('/private/tmp/c/p/s/tasks/bor07nzv3.output')
    expect(outputPathOf('nothing here')).toBeUndefined()
    expect(outputPathOf('x', { backgroundOutputPath: '/remote/t.output' })).toBe('/remote/t.output')
    expect(jobMatches(job().rearm, job() as any)).toBe(true)
    expect(jobMatches('acp-dispatch codex --name docs --detach', job() as any)).toBe(true)
    expect(jobMatches('acp-dispatch codex --name other', job() as any)).toBe(false)
    expect(jobMatches('sleep 5', job() as any)).toBe(false)
    expect(isDispatchCommand('~/src/djbclark-ade/bin/acp-dispatch codex --name x')).toBe(true)
    expect(isDispatchCommand('ls ~/.local/state/bigteam')).toBe(true)
    expect(isDispatchCommand('gh run watch 1')).toBe(false)
    const acp = (status: string) => [{ kind: 'acp', status }]
    expect(shouldScan([], 0, 100_000)).toBe(false) // never dispatched: no scan
    expect(shouldScan([{ status: 'running' }], 0, 100_000)).toBe(false) // a subagent or shell is no reason
    expect(shouldScan([], 100_000, 130_000)).toBe(true) // within 60 s of a dispatch command
    expect(shouldScan([], 100_000, 161_000)).toBe(false) // 60 s passed, nothing running
    expect(shouldScan(acp('running'), 100_000, 400_000)).toBe(true) // a tracked job still runs
    expect(shouldScan(acp('done'), 100_000, 161_000)).toBe(false)
    expect(shouldScan([], 0, 100_000, true)).toBe(true) // the first /radar
    expect(tailLines('a\r\n\x1b[31mb\x1b[0m\n\n c \n', 2)).toEqual(['b', ' c'])
    const log = [
      '{"t": 1, "kind": "update", "data": {"sessionUpdate": "tool_call", "title": "read_file"}}',
      '{"t": 2, "kind": "update", "data": {"sessionUpdate": "agent_message_chunk", "content": {"text": "Writing the "}}}',
      '{"t": 3, "kind": "update", "data": {"sessionUpdate": "agent_message_chunk", "content": {"text": "report"}}}',
      'cut in half',
      '{"t": 4, "kind": "result", "data": {"exit": 0, "tool_calls": 3}}',
    ].join('\n')
    expect(logSummary(log)).toEqual(['> read_file', 'Writing the report', 'result: exit 0 · 3 tool calls'])
    const records = `\x01/a.json\n${JSON.stringify(job())}\n\x01/b.json\n${JSON.stringify(job({ name: 'x', owner: 'other' }))}\n\x01/c.json\n{not json`
    expect(parseRecords(records, 's').map(j => j.name)).toEqual(['docs'])
  })

  test('a background shell shows, then finishes after two lsof misses', async ($, on) => {
    const { clock, toasts, state } = engine(on)
    state.tails[OUT] = 'building\nrun 1 of 3\nrun 2 of 3\n'
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' } as any)
    await $.tool.call({ tool: 'Bash', command: 'gh run watch 123', description: 'Watch CI', run_in_background: true } as any)

    const band = await $.ui.mount({ plugin: 'agent-radar', surface: 'terminal', ...BAND } as any)
    expect(await band.find({ type: 'Text', text: / ● Watch CI/ })).toBeDefined()
    await clock.advance(5_000)
    await eventually(() => band.find({ type: 'Text', text: /sh .*· run 2 of 3/ }))
    expect(await band.find({ type: 'Text', text: /sh .*· run 2 of 3/ })).toBeDefined() // kind tag and the last output line
    expect(toasts).toEqual([])

    state.open = false
    await clock.advance(5_000) // one miss: still running
    await settle()
    expect(toasts).toEqual([])
    await clock.advance(5_000) // two in a row: over
    await eventually(() => toasts.length > 0)
    expect(toasts.length).toBe(1)
    expect(toasts[0]).toMatch(/^✓ Watch CI done \(\d+s\)$/)
    expect(await band.find({ type: 'Text', text: / ✓ Watch CI/ })).toBeDefined()
    const r = await $.command.run({ command: 'radar', args: '' } as any)
    expect(r.text).toBe('0 running, 1 finished')
    await band.unmount()
  })

  test('a command Claude Code moved to the background (Ctrl+B, a timeout) is a line too', async ($, on) => {
    engine(on)
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' } as any)
    await $.tool.call({ tool: 'Bash', command: 'ls' } as any) // no run_in_background; the result carries a task id
    const r = await $.command.run({ command: 'radar', args: '' } as any)
    expect(r.text).toBe('1 running, 0 finished')
  })

  test('a shell that runs another agent is labelled with it and its model; the pane shows its output', async ($, on) => {
    const { clock, state } = engine(on)
    state.tails[OUT] = 'thinking\nediting a.ts\n'
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' } as any)
    await $.tool.call({ tool: 'Bash', command: "acp-run codex -C /x -p 'fix it' --model gpt-6-astra", run_in_background: true } as any)
    await clock.advance(5_000)
    await settle()
    const band = await $.ui.mount({ plugin: 'agent-radar', surface: 'terminal', ...BAND } as any)
    expect(await band.find({ type: 'Text', text: / ● codex gpt-6-astra/ })).toBeDefined()
    await $.command.run({ command: 'radar', args: '' } as any)
    const ui = await $.ui.mount({ plugin: 'agent-radar', surface: 'terminal', ...PANE } as any)
    await ui.press({ key: 'agent-sh:bqumpaw3k.output' })
    await eventually(() => ui.find({ type: 'Text', text: /editing a\.ts/ }))
    expect(await ui.find({ type: 'Text', text: /\$ acp-run codex -C \/x/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /editing a\.ts/ })).toBeDefined()
    await ui.unmount()
    await band.unmount()
  })

  test('an acp-dispatch job of this session shows and toasts its status; another session\'s does not', async ($, on) => {
    const { clock, toasts, state } = engine(on)
    state.records = [job(), job({ name: 'theirs', owner: 'other', record: '/state/t/jobs/theirs.json' })]
    state.tails['/state/t/docs.jsonl'] = '{"t": 1, "kind": "update", "data": {"sessionUpdate": "tool_call", "title": "Read `a.md`"}}\n'
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' } as any)
    await $.tool.call({ tool: 'Bash', command: 'acp-dispatch grok --name docs --detach --no-wait' } as any) // starts the records scan
    await clock.advance(5_000)
    const band = await $.ui.mount({ plugin: 'agent-radar', surface: 'terminal', ...BAND } as any)
    await eventually(() => band.find({ type: 'Text', text: /acp .*· running · > Read `a\.md`/ }))
    expect(await band.find({ type: 'Text', text: / ● grok grok-4\.7 · docs/ })).toBeDefined()
    expect(await band.find({ type: 'Text', text: /acp .*· running · > Read `a\.md`/ })).toBeDefined()
    expect(await band.find({ type: 'Text', text: /theirs/ })).toBeUndefined()
    expect((await $.command.run({ command: 'radar', args: '' } as any)).text).toBe('1 running, 0 finished')

    const ui = await $.ui.mount({ plugin: 'agent-radar', surface: 'terminal', ...PANE } as any)
    await ui.press({ key: `agent-acp:docs:${Math.floor(state.records[0].started)}` })
    expect(await ui.find({ type: 'Text', text: /agent grok · model grok-4\.7 · effort high/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /report: \/state\/t\/docs-report\.md/ })).toBeDefined()

    state.records = [job({ status: 'no-report', exit: 3, finished: NOW() })]
    await clock.advance(5_000)
    await eventually(() => toasts.length > 0)
    expect(toasts).toEqual([expect.stringMatching(/^✗ grok grok-4\.7 · docs no-report \(\d+s\)$/)])
    expect(await band.find({ type: 'Text', text: / ✗ grok grok-4\.7 · docs/ })).toBeDefined()
    expect(await band.find({ type: 'Text', text: /no-report \(exit 3\)/ })).toBeDefined()
    await ui.unmount()
    await band.unmount()
  })

  test('the waiter of a job and a launcher with its --name are the one job line, not two', async ($, on) => {
    const { clock, toasts, state } = engine(on)
    state.records = [job()]
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' } as any)
    await $.tool.call({ tool: 'Bash', command: job().rearm, run_in_background: true } as any)
    await clock.advance(5_000)
    await eventually(async () => (await $.command.run({ command: 'radar', args: '' } as any)).text === '1 running, 0 finished')
    expect((await $.command.run({ command: 'radar', args: '' } as any)).text).toBe('1 running, 0 finished')
    // its output file closing is no toast: the job is the line
    state.open = false
    await clock.advance(5_000)
    await clock.advance(5_000)
    await settle()
    expect(toasts).toEqual([])
    // a run in the foreground of the launcher, tracked before its record exists, is hidden once the record shows
    state.records = []
    await $.tool.call({ tool: 'Bash', command: 'acp-dispatch codex --name later --detach', run_in_background: true } as any)
    state.records = [job(), job({ name: 'later', record: '/state/t/jobs/later.json', rearm: 'x' })]
    await clock.advance(5_000)
    await eventually(async () => (await $.command.run({ command: 'radar', args: '' } as any)).text === '2 running, 0 finished')
    expect((await $.command.run({ command: 'radar', args: '' } as any)).text).toBe('2 running, 0 finished')
  })

  test('a session that never runs acp-dispatch does no records scan; the first /radar scans once', async ($, on) => {
    const { clock, state } = engine(on)
    const scans = () => state.runs.filter(a => a[2]?.includes('radar:records')).length
    state.records = [job({ status: 'done', started: NOW() - 3700, finished: NOW() - 3600 })] // there, but nobody asked
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' } as any)
    await $.agent.spawn({ prompt: 'run it', description: 'sweep runner' } as any)
    await $.tool.call({ tool: 'Bash', command: 'gh run watch 123', run_in_background: true } as any)
    for (let i = 0; i < 4; i++) {
      await clock.advance(5_000)
      await settle()
    }
    await eventually(() => state.runs.some(a => a[0]?.endsWith('lsof'))) // the polls ran: for the shell
    expect(scans()).toBe(0)
    // /radar scans once, adopt-style: a job launched before this mod loaded shows
    const r = await $.command.run({ command: 'radar', args: '' } as any)
    expect(scans()).toBe(1)
    expect(r.text).toBe('2 running, 0 finished') // the subagent and the shell; the old job ended before this session
    await $.command.run({ command: 'radar', args: '' } as any)
    await clock.advance(5_000)
    await settle()
    expect(scans()).toBe(1) // the second /radar and the timer do not: no job runs, no dispatch command was seen
  })

  test('a Bash command that dispatches starts the records scan', async ($, on) => {
    const { clock, state } = engine(on)
    const scans = () => state.runs.filter(a => a[2]?.includes('radar:records')).length
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' } as any)
    await $.tool.call({ tool: 'Bash', command: 'git status' } as any)
    await clock.advance(5_000)
    await settle()
    expect(scans()).toBe(0)
    await $.tool.call({ tool: 'Bash', command: 'acp-dispatch codex --name later --detach --no-wait' } as any)
    await clock.advance(5_000)
    await eventually(() => scans() > 0)
    expect(scans()).toBeGreaterThan(0)
  })

  // ---------------------------------------------------------------- security: external data on its way to the terminal
  // (ported from the adversary review of hamzafer/claude-code-mods#129, and applied to the job paths too)

  const ESC = '\x1b'
  const HOSTILE = `A${ESC}[31mB${ESC}[0m${ESC}]52;c;ZXZpbA==\x07C${ESC}]0;title${ESC}\\D${ESC}Pq1;2${ESC}\\E\x9b31mF\x9d52;c;Zg\x9cG\x07\x00H‮I⁦J‏K؜L`

  test('clean drops escape sequences, control characters and bidi controls, and keeps tab and line breaks', () => {
    expect(clean(HOSTILE)).toBe('ABCDEFGHIJKL')
    expect(clean('a\tb\nc\r\nd')).toBe('a\tb\nc\r\nd')
    expect(clean(`${ESC}[2Jgone${ESC}[?25l${ESC}c${ESC}[`)).toBe('gone')
    expect(oneLine(`  two\n\n lines ${ESC}[1m\t bold  `)).toBe('two lines bold')
    expect(oneLine('x'.repeat(5000), 50)).toHaveLength(50)
    expect(oneLine(42 as any)).toBe('')
    expect(tailLines(`ok\n${HOSTILE}\n`)).toEqual(['ok', 'ABCDEFGHIJKL'])
  })

  test('a command is cut at 4096 characters before any regex runs', () => {
    const t0 = Date.now()
    expect(agentOf(`acp-run codex --model gpt-6-astra ${'x'.repeat(200_000)}`)).toEqual({ agent: 'codex', model: 'gpt-6-astra' }) // what comes early still counts
    expect(agentOf(`${'x '.repeat(3000)}; acp-run codex --model m`)).toBeUndefined() // past the cap: not looked at
    expect(isDispatchCommand(`${'x '.repeat(3000)}; acp-dispatch codex --name late`)).toBe(false)
    expect(isDispatchCommand('acp-dispatch codex --name early ' + 'x'.repeat(200_000))).toBe(true)
    const many = 'acp-dispatch '.repeat(60_000) // each occurrence would rescan to the end of the line
    expect(jobMatches(many, job() as any)).toBe(false)
    expect(agentOf(many)).toBeUndefined()
    expect(shellLabel(many, undefined).label).toHaveLength(50)
    expect(shellLabel('a'.repeat(100_000), `d${ESC}[31m\nesc‮`).detail).toHaveLength(200)
    expect(Date.now() - t0).toBeLessThan(2000)
  })

  test('a label and a detail are clean one-liners', () => {
    expect(shellLabel(`echo ${ESC}]52;c;ZXZpbA==\x07hi\n  there‮`, `Run${ESC}[31m it\nnow`)).toEqual({ label: 'Run it now', detail: 'echo hi there' })
    expect(shellLabel(`echo ${ESC}[31mhi${ESC}[0m`, undefined).label).toBe('echo hi')
  })

  test('an output path must be absolute, plain, free of `..` and end in .output', () => {
    expect(isOutputPath(OUT)).toBe(true)
    for (const bad of ['relative/b.output', '/tmp/../etc/passwd.output', '/tmp/a/../b.output', '/tmp/a b.output', '/tmp/a\nb.output', `/tmp/a${ESC}[31m.output`, '/tmp/a\x9bb.output', '/tmp/a‮b.output', '/tmp/a.txt', '', '/' + 'a'.repeat(2000) + '.output', 42, undefined]) {
      expect(isOutputPath(bad)).toBe(false)
      expect(outputPathOf('x', { backgroundOutputPath: bad })).toBeUndefined()
    }
    expect(outputPathOf('Output is being written to: /tmp/../etc/passwd.output')).toBeUndefined()
    expect(outputPathOf('You can read its output at /x/../tasks/b1.output')).toBeUndefined()
    expect(outputPathOf('Output is being written to: ../b1.output')).toBeUndefined()
    expect(outputPathOf(`written to: /tmp/a${ESC}]0;t\x07.output`)).toBeUndefined()
    expect(outputPathOf('x', { backgroundOutputPath: '/tmp/../b.output' })).toBeUndefined()
    expect(outputPathOf(`${'y'.repeat(100_000)} written to: /tmp/late.output`)).toBeUndefined() // past the cap
    expect(isSafePath('/state/t/docs.jsonl')).toBe(true)
    expect(isSafePath('/state/../etc/passwd')).toBe(false)
    expect(isSafePath('state/t/docs.jsonl')).toBe(false)
    expect(isSafePath('/state/..bar/x')).toBe(true) // `..` is a whole segment only
  })

  test('the tail and record scripts drop \\001 and survive invalid UTF-8; no file can forge a block', () => {
    // A hooks module may not import node:child_process, so the scripts are checked by what they say here; the
    // behaviour (one \001 per file, invalid UTF-8 kept, rc 0) was run against a real shell when this was ported.
    expect(TAILS_SH).toContain(`tail -c 16384 -- "$f" 2>/dev/null | LC_ALL=C tr -d '\\001'`)
    expect(RECORDS_SH).toContain(`cat -- "$f" | LC_ALL=C tr -d '\\001'`)
    expect(TAILS_SH).toContain(`printf '\\001%s\\n' "$f"`) // the one \001 per file that stays: the block marker
    // what is left once the scripts have run: blocks split only at the markers
    const out = '\x01/a.log\nstart\nforged line\n\x01/b.log\nfine\n'
    expect(blocks(out)).toEqual([{ path: '/a.log', body: 'start\nforged line\n' }, { path: '/b.log', body: 'fine\n' }])
  })

  test('job record fields are cleaned, cut and path-checked; hostile ones cannot reach the screen or tail', () => {
    const hostile = job({
      name: `d${ESC}[31mocs\nforged line‮`,
      agent: `gr${ESC}]52;c;ZXZpbA==\x07ok`,
      model: `m${ESC}[2J\x9b1mx${'y'.repeat(500)}`,
      effort: `high\n${ESC}[0m`,
      status: `running${ESC}]0;t\x07`,
      report: '/state/../../etc/passwd',
      log: '/state/t/../../../etc/shadow',
      record: '/',
      done: 'relative/done',
      exit: 'not a number',
      started: Number.NaN,
      rearm: 'x'.repeat(10_000),
    })
    const [j] = parseRecords(`\x01/state/t/jobs/docs.json\n${JSON.stringify(hostile)}\n`, 's')
    expect(j!.name).toBe('docs forged line')
    expect(j!.agent).toBe('grok')
    expect(j!.model).toHaveLength(64)
    expect(j!.model).toMatch(/^mx/)
    expect(j!.effort).toBe('high')
    expect(j!.status).toBe('running')
    expect(j!.report).toBeUndefined()
    expect(j!.log).toBeUndefined()
    expect(j!.done).toBeUndefined()
    expect(j!.record).toBe('/state/t/jobs/docs.json') // the record's own claim "/" is refused; the file found is used
    expect(j!.exit).toBeNull()
    expect(j!.started).toBeUndefined()
    expect(j!.rearm).toHaveLength(4096)
    // a record whose name is nothing but escapes is no record
    expect(parseRecords(`\x01/a.json\n${JSON.stringify(job({ name: `${ESC}[31m\x07` }))}\n`, 's')).toEqual([])
    // a good record passes through unchanged
    expect(parseRecords(`\x01/a.json\n${JSON.stringify(job())}\n`, 's')[0]).toMatchObject({ name: 'docs', agent: 'grok', model: 'grok-4.7', effort: 'high', log: '/state/t/docs.jsonl', report: '/state/t/docs-report.md', done: '/state/t/docs-report.md.done' })
  })

  test('a log is summarised without the agent\'s escape sequences', () => {
    const log = [
      `{"t": 1, "kind": "update", "data": {"sessionUpdate": "tool_call", "title": "Read \\u001b[31m\\u001b]52;c;Zg\\u0007a.md\\n‮x"}}`,
      `{"t": 2, "kind": "update", "data": {"sessionUpdate": "agent_message_chunk", "content": {"text": "all \\u001b[1mgood\\u001b[0m\\nnext\\u0007 line⁦"}}}`,
      `{"t": 3, "kind": "turn", "data": {"n": "1\\u001b[2J", "stop_reason": "end\\u202e_turn", "seconds": 3.2}}`,
      `{"t": 4, "kind": "result", "data": {"exit": "0\\u001b]0;x\\u0007", "tool_calls": "9\\u001b[2J"}}`,
    ].join('\n')
    const lines = logSummary(log)
    expect(lines).toEqual(['> Read a.md x', 'all good', 'next line', 'turn 1: end_turn after 3s', 'result: exit 0 · 9 tool calls'])
    for (const l of lines) expect(clean(l)).toBe(l)
  })

  test('a hostile command, description and output path never reach the band or the pane raw', async ($, on) => {
    const { clock, state } = engine(on)
    state.tails[OUT] = `building\n${ESC}]52;c;ZXZpbA==\x07${ESC}[31mred line‮\n`
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' } as any)
    const command = `echo ${ESC}]52;c;ZXZpbA==\x07${ESC}[2Jhi‮ there ${'z'.repeat(9000)}`
    await $.tool.call({ tool: 'Bash', command, description: `Run${ESC}[31m it‮\nnow`, run_in_background: true } as any)
    await clock.advance(5_000)
    await eventually(() => $.command.run({ command: 'radar', args: '' } as any).then(() => state.runs.some(a => a[2]?.includes('radar:tails'))))
    const band = await $.ui.mount({ plugin: 'agent-radar', surface: 'terminal', ...BAND } as any)
    await eventually(() => band.find({ type: 'Text', text: /red line/ }))
    expect(await band.find({ type: 'Text', text: / ● Run it now/ })).toBeDefined()
    expect(await band.find({ type: 'Text', text: /sh .*· red line/ })).toBeDefined()
    expect(await band.find({ type: 'Text', text: /[\x00-\x08\x0b-\x1f\x7f-\x9f‪-‮⁦-⁩]/ })).toBeUndefined()
    const ui = await $.ui.mount({ plugin: 'agent-radar', surface: 'terminal', ...PANE } as any)
    await ui.press({ key: 'agent-sh:bqumpaw3k.output' })
    expect(await ui.find({ type: 'Text', text: /^\$ echo hi there z+$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /[\x00-\x08\x0b-\x1f\x7f-\x9f‪-‮⁦-⁩]/ })).toBeUndefined()
    await ui.unmount()
    await band.unmount()

    // an output path with `..` in it is no line: nothing is tailed or asked of lsof for it
    const runs = state.runs.length
    state.file = '/private/tmp/c/../../../etc/passwd.output'
    await $.tool.call({ tool: 'Bash', command: 'sleep 9', run_in_background: true } as any)
    state.file = `/private/tmp/c/p/s/tasks/a${ESC}]0;t\x07.output`
    await $.tool.call({ tool: 'Bash', command: 'sleep 8', run_in_background: true } as any)
    await clock.advance(5_000)
    await settle()
    expect((await $.command.run({ command: 'radar', args: '' } as any)).text).toBe('1 running, 0 finished')
    expect(state.runs.slice(runs).flat().some(a => a.includes('passwd') || a.includes(ESC))).toBe(false)
  })

  test('a job record with a hostile log path is shown but its log is never tailed; its text is clean', async ($, on) => {
    const { clock, state } = engine(on)
    state.records = [job({ name: `docs${ESC}[31m`, model: `grok-4.7${ESC}]52;c;Zg\x07‮`, log: '/state/t/../../etc/shadow', report: '/state/../etc/passwd' })]
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' } as any)
    await $.tool.call({ tool: 'Bash', command: 'acp-dispatch grok --name docs --detach --no-wait' } as any)
    await clock.advance(5_000)
    const band = await $.ui.mount({ plugin: 'agent-radar', surface: 'terminal', ...BAND } as any)
    await eventually(() => band.find({ type: 'Text', text: / ● grok grok-4\.7 · docs/ }))
    expect(await band.find({ type: 'Text', text: / ● grok grok-4\.7 · docs/ })).toBeDefined()
    expect(await band.find({ type: 'Text', text: /[\x00-\x08\x0b-\x1f\x7f-\x9f‪-‮⁦-⁩]/ })).toBeUndefined()
    await clock.advance(5_000)
    await settle()
    expect(state.runs.flat().some(a => a.includes('shadow') || a.includes('passwd'))).toBe(false)
    const ui = await $.ui.mount({ plugin: 'agent-radar', surface: 'terminal', ...PANE } as any)
    await ui.press({ key: `agent-acp:docs:${Math.floor(state.records[0].started)}` })
    expect(await ui.find({ type: 'Text', text: /passwd/ })).toBeUndefined() // the report path was refused
    await ui.unmount()
    await band.unmount()
  })

  test('a subagent description, a tool call and a message are cleaned too', async ($, on) => {
    const { state } = engine(on)
    state.messages = [{ role: 'assistant', text: `done ${ESC}]52;c;Zg\x07${ESC}[31mfine‮`, toolUses: [] }]
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' } as any)
    await $.agent.spawn({ prompt: 'run it', description: `sweep${ESC}[31m runner\n‮` } as any)
    const band = await $.ui.mount({ plugin: 'agent-radar', surface: 'terminal', ...BAND } as any)
    expect(await band.find({ type: 'Text', text: / ● sweep runner/ })).toBeDefined()
    expect(label({ tool: 'Bash', command: `ls ${ESC}[31m${ESC}]52;c;Zg\x07x`, description: '' })).toBe('running ls x')
    expect(label({ tool: 'Edit', file_path: `/a/b${ESC}[2J/c‮.ts` })).toBe('editing b/c.ts')
    expect(label({ tool: `mcp__a${ESC}[31m__b` })).toBe('using a b')
    const ui = await $.ui.mount({ plugin: 'agent-radar', surface: 'terminal', ...PANE } as any)
    await $.command.run({ command: 'radar', args: '' } as any)
    await ui.press({ key: 'agent-a1' })
    expect(await ui.find({ type: 'Text', text: /^done fine$/ })).toBeDefined()
    await ui.unmount()
    await band.unmount()
  })
})
