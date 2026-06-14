import { cn } from '@/lib/cn'

type ProgressSize = 'xs' | 'sm' | 'md' | 'lg'
type ProgressTone = 'accent' | 'pos' | 'warn' | 'neg'

interface ProgressProps {
  value?: number
  max?: number
  size?: ProgressSize
  tone?: ProgressTone
  showLabel?: boolean
  className?: string
}

const heights = { xs: 2, sm: 4, md: 6, lg: 8 }
const colors: Record<ProgressTone, string> = {
  accent: 'var(--ink-0)',
  pos:    'var(--pos)',
  warn:   'var(--warn)',
  neg:    'var(--neg)',
}

export function Progress({ value = 0, max = 100, size = 'md', tone = 'accent', showLabel, className }: ProgressProps) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100))
  return (
    <div className={className}>
      <div
        className="overflow-hidden rounded-[var(--r-pill)] bg-paper-3"
        style={{ height: heights[size] }}
      >
        <div
          className="h-full rounded-[var(--r-pill)] transition-[width] duration-[var(--dur-slow)] ease-[var(--ease-out)]"
          style={{ width: `${pct}%`, background: colors[tone] }}
        />
      </div>
      {showLabel && <div className="t-xs fg-3 mt-1">{Math.round(pct)}% complete</div>}
    </div>
  )
}

interface ValueBarProps {
  value: number
  max?: number
  /** Number of segments to render, or an array whose length determines the segment count. */
  segments?: number | unknown[]
  height?: number
  className?: string
}

export function ValueBar({ value, max = 100, segments, height = 4, className }: ValueBarProps) {
  if (segments !== undefined) {
    const count = Array.isArray(segments) ? segments.length : segments
    return (
      <div className={cn('flex gap-0.5', className)}>
        {Array.from({ length: count }).map((_, i) => (
          <div
            key={i}
            className="flex-1 rounded-[1px]"
            style={{ height, background: i < value ? 'var(--ink-0)' : 'var(--paper-3)' }}
          />
        ))}
      </div>
    )
  }
  return <Progress value={value} max={max} className={className} />
}
