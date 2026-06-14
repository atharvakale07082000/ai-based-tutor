import { cn } from '@/lib/cn'

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
  className?: string
}

export function AgentPill({ kind = 'curr', state = 'idle', label, mini, className }: AgentPillProps) {
  const color = COLORS[kind]
  const text = label ?? LABELS[kind]
  const pulsing = state === 'active' || state === 'thinking'

  if (mini) {
    return (
      <span className={cn('inline-flex items-center gap-1.5 text-[11px] text-ink-2', className)}>
        <span
          className={cn('h-1.5 w-1.5 rounded-full', pulsing && 'animate-[pulse-soft_2s_infinite]')}
          style={{ background: color }}
        />
        {text}
      </span>
    )
  }

  return (
    <span
      className={cn(
        'pill-i inline-flex items-center gap-1.5 rounded-[var(--r-pill)] border border-line-1 bg-paper-1 py-[3px] pl-1.5 pr-2 text-[11px] font-medium text-ink-1 transition-[transform,box-shadow] duration-[var(--dur-fast)] ease-[var(--ease-out)]',
        className
      )}
    >
      <span
        className={cn('h-[7px] w-[7px] rounded-full', pulsing && 'animate-[pulse-soft_2s_infinite]')}
        style={{ background: color, boxShadow: pulsing ? `0 0 0 3px ${color}22` : 'none' }}
      />
      {text}
    </span>
  )
}
