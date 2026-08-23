export const meta = {
  name: 'graph-audit',
  description: 'Fan out a multi-dimension audit over a target path, verify each finding adversarially, synthesize a report',
  phases: [
    { title: 'Audit', detail: 'one agent per dimension' },
    { title: 'Verify', detail: 'one skeptic per finding' },
    { title: 'Synthesize', detail: 'prioritized report from confirmed findings' },
  ],
}

const target = (args && args.target) || '.'
const dimensions = (args && args.dimensions) || [
  { key: 'correctness', prompt: `Review ${target} for correctness bugs. Report concrete file/line findings, not style opinions.` },
  { key: 'security', prompt: `Review ${target} for security issues (injection, secrets, unsafe deserialization, auth gaps). Report concrete findings.` },
  { key: 'simplification', prompt: `Review ${target} for dead code, unneeded abstraction, and needless complexity. Report concrete findings.` },
]

const FINDINGS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          file: { type: 'string' },
          summary: { type: 'string' },
          severity: { type: 'string', enum: ['low', 'medium', 'high'] },
        },
        required: ['file', 'summary', 'severity'],
      },
    },
  },
  required: ['findings'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    real: { type: 'boolean' },
    reason: { type: 'string' },
  },
  required: ['real', 'reason'],
}

log(`Auditing ${target} across ${dimensions.length} dimensions: ${dimensions.map((d) => d.key).join(', ')}`)

const perDimension = await pipeline(
  dimensions,
  (d) =>
    agent(d.prompt, {
      label: `audit:${d.key}`,
      phase: 'Audit',
      schema: FINDINGS_SCHEMA,
      agentType: 'general-purpose',
    }),
  (review, d) =>
    parallel(
      (review ? review.findings : []).map((f, i) => () =>
        agent(
          `Try to refute this finding. Default to real:false if you are not confident it reproduces.\nFile: ${f.file}\nSeverity: ${f.severity}\nClaim: ${f.summary}`,
          { label: `verify:${d.key}:${i}:${f.file}`, phase: 'Verify', schema: VERDICT_SCHEMA },
        ).then((v) => ({ ...f, dimension: d.key, verdict: v })),
      ),
    ),
)

const confirmed = perDimension
  .flat()
  .filter((f) => f && f.verdict && f.verdict.real)

log(`${confirmed.length} findings survived verification`)

if (!confirmed.length) {
  return { target, findings: [], report: 'No findings survived adversarial verification.' }
}

phase('Synthesize')
const report = await agent(
  `Write a short prioritized audit report (most severe first) from these confirmed findings:\n${JSON.stringify(confirmed)}`,
  { phase: 'Synthesize' },
)

return { target, findings: confirmed, report }
