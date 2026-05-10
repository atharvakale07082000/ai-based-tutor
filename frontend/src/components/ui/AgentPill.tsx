type AgentKind = 'curr' | 'quiz' | 'prog' | 'doubt'

const COLORS: Record<AgentKind, string> = {
  curr:  'var(--agent-curr)',
  quiz:  'var(--agent-quiz)',
  prog:  'var(--agent-prog)',
  doubt: 'var(--agent-doubt)',
}

const LABELS: Record<AgentKind, string> = {
  curr:  'Curriculum',
  quiz:  'Quiz Gen',
  prog:  'Progress',
  doubt: 'Doubt-Solver',
}

interface AgentPillProps {
  kind?: AgentKind
  state?: 'active' | 'idle' | 'thinking'
  label?: string
  mini?: boolean
}

export function AgentPill({ kind = 'curr', state = 'idle', label, mini }: AgentPillProps) {
  const color = COLORS[kind]
  const text = label ?? LABELS[kind]
  const pulsing = state === 'active' || state === 'thinking'

  if (mini) {
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--ink-2)' }}>
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: color,
            animation: pulsing ? 'pulse-soft 2s infinite' : 'none',
          }}
        />
        {text}
      </span>
    )
  }

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '3px 8px 3px 6px',
        borderRadius: 'var(--r-pill)',
        background: 'var(--paper-1)',
        border: '1px solid var(--line-1)',
        fontSize: 11,
        fontWeight: 500,
        color: 'var(--ink-1)',
      }}
    >
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: '50%',
          background: color,
          boxShadow: pulsing ? `0 0 0 3px ${color}22` : 'none',
          animation: pulsing ? 'pulse-soft 2s infinite' : 'none',
        }}
      />
      {text}
    </span>
  )
}
