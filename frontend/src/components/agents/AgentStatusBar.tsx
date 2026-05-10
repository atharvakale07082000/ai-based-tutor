import { useAgentStore } from '@/stores/agentStore'
import { AgentPill } from '@/components/ui/AgentPill'

const AGENT_ACTIVITY: Record<string, { kind: 'curr' | 'quiz' | 'prog' | 'doubt'; label: string }> = {
  curriculum: { kind: 'curr',  label: 'Curriculum' },
  quiz:       { kind: 'quiz',  label: 'Quiz Gen' },
  progress:   { kind: 'prog',  label: 'Progress' },
  doubt:      { kind: 'doubt', label: 'Doubt-Solver' },
}

export function AgentStatusBar() {
  const agents = useAgentStore((s) => s.agents)

  const items = Object.entries(AGENT_ACTIVITY).map(([key, meta]) => {
    const agent = agents[key as keyof typeof agents]
    const status = agent?.status ?? 'idle'
    const state = status === 'active' ? 'active' : status === 'processing' ? 'thinking' : 'idle'
    const text =
      state === 'active' ? 'Working…' :
      state === 'thinking' ? 'Thinking…' :
      'Standby'
    return { ...meta, state, text, latency: agent?.latencyMs }
  })

  return (
    <div
      style={{
        padding: '5px 16px',
        background: 'var(--paper-1)',
        borderBottom: '1px solid var(--line-1)',
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        fontSize: 12,
        flexShrink: 0,
        overflowX: 'auto',
      }}
      className="scrollbar-hide"
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: 'var(--pos)',
            animation: 'pulse-soft 2s infinite',
          }}
        />
        <span className="caps" style={{ color: 'var(--ink-2)', whiteSpace: 'nowrap' }}>Live</span>
      </div>
      <div style={{ width: 1, height: 16, background: 'var(--line-1)', flexShrink: 0 }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, flex: 1, overflowX: 'auto' }} className="scrollbar-hide">
        {items.map((a) => (
          <div key={a.kind} style={{ display: 'flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap' }}>
            <AgentPill kind={a.kind} state={a.state as any} mini />
            <span className="t-xs fg-2">·</span>
            <span className="t-xs fg-1">{a.text}</span>
            {a.latency != null && a.latency > 0 && (
              <span className="t-xs mono" style={{ color: 'var(--ink-4)' }}>{a.latency}ms</span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
