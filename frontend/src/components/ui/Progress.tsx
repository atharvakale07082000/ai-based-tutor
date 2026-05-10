type ProgressSize = 'xs' | 'sm' | 'md' | 'lg'
type ProgressTone = 'accent' | 'pos' | 'warn' | 'neg'

interface ProgressProps {
  value?: number
  max?: number
  size?: ProgressSize
  tone?: ProgressTone
  showLabel?: boolean
}

const heights = { xs: 2, sm: 4, md: 6, lg: 8 }
const colors: Record<ProgressTone, string> = {
  accent: 'var(--ink-0)',
  pos:    'var(--pos)',
  warn:   'var(--warn)',
  neg:    'var(--neg)',
}

export function Progress({ value = 0, max = 100, size = 'md', tone = 'accent', showLabel }: ProgressProps) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100))
  return (
    <div>
      <div style={{ height: heights[size], background: 'var(--paper-3)', borderRadius: 'var(--r-pill)', overflow: 'hidden' }}>
        <div
          style={{
            width: `${pct}%`,
            height: '100%',
            background: colors[tone],
            borderRadius: 'var(--r-pill)',
            transition: 'width var(--dur-slow) var(--ease-out)',
          }}
        />
      </div>
      {showLabel && (
        <div className="t-xs fg-3" style={{ marginTop: 4 }}>{Math.round(pct)}% complete</div>
      )}
    </div>
  )
}

interface ValueBarProps {
  value: number
  max?: number
  segments?: number
  height?: number
}

export function ValueBar({ value, max = 100, segments, height = 4 }: ValueBarProps) {
  if (segments !== undefined) {
    return (
      <div style={{ display: 'flex', gap: 2 }}>
        {Array.from({ length: segments }).map((_, i) => (
          <div
            key={i}
            style={{
              flex: 1,
              height,
              background: i < value ? 'var(--ink-0)' : 'var(--paper-3)',
              borderRadius: 1,
            }}
          />
        ))}
      </div>
    )
  }
  return <Progress value={value} max={max} />
}
