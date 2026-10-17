import { describe, expect, mock, test } from 'claude-code/testing'

import { describe as label, elapsed, isShown, resetBandOrder } from '../hooks/register'
import { agentOf, baseName, jobMatches, logSummary, outputPathOf, parseRecords, shellLabel, tailLines } from '../hooks/watch'

const BAND = { component: 'AbovePrompt', props: { hasSurvey: false, isWorking: true, maxRows: 10, bodyColumns: 120 } }
const PANE = { component: 'Pane', requestId: 'agent-radar', props: { title: 'Agent Radar', isFocused: true, bodyColumns: 100, placement: 'dock' } }

const OUT = '/private/tmp/c/p/s/tasks/bqumpaw3k.output'
const NOW = () => Date.now() / 1000

// Stands for the engine beneath the mod: lsof sees OUT open while `state.open` holds, the records script
// lists `state.records`, the tails script answers from `state.tails`.
function engine(on: any, files: Record<string, string> = {}, beneath?: unknown) {
  const clock = mock.clock(on, { now: 0 })
  const toasts: string[] = []
  const state = { n: 0, open: true, records: [] as any[], tails: {} as Record<string, string>, runs: [] as string[][] }
  resetBandOrder()
  on('env.get', (_$: any, e: any) => ({ value: e.name === 'HOME' ? '/home/me' : undefined }))
  on('fs.exists', (_$: any, e: any) => ({ value: e.path in files }))
  on('fs.read', (_$: any, e: any) => ({ value: files[e.path] ?? '' }))
  on('session.start', (_$: any, e: any) => ({ sessionId: 's', cwd: e.cwd }))
  on('session.id', () => ({ value: 's' }))
  on('command.register', () => ({ value: undefined }))
  on('tool.call', () => {
    const file = state.n++ === 0 ? OUT : `/private/tmp/c/p/s/tasks/b${state.n}.output`
    return { result: { backgroundTaskId: baseName(file) }, text: `Command running in background. You can read its output at ${file}` }
  })
  on('agent.spawn', () => ({ model: 'sonnet', agentId: 'a1' }))
  on('agent.list', () => ({ value: [] }))
  on('turn.complete', () => ({ text: '' }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.panes', () => ({ value: [] }))
  on('ui.toast', (_$: any, e: any) => (toasts.push(e.text), { value: undefined }))
  on('ui.render', ($: any, e: any) => beneath ?? $.ui.resolve(e).Text({ children: 'band below' }))
  on('session.messages', () => ({ value: [{ role: 'user', text: 'Run the sweep', toolUses: [] }, { role: 'assistant', text: 'Sweep is at trial 12 of 40.', toolUses: [] }] }))
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
})
