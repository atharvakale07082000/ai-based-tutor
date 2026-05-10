import type { HTMLAttributes } from 'react'
import { Icon } from './Icon'

type Tone = 'neutral' | 'accent' | 'pos' | 'warn' | 'neg' | 'info' | 'outline'
type BadgeSize = 'xs' | 'sm' | 'md'

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone
  size?: BadgeSize
  dot?: boolean
  icon?: string
  glow?: boolean
}

const tones: Record<Tone, React.CSSProperties> = {
  neutral: { background: 'var(--paper-2)', color: 'var(--ink-1)', border: '1px solid var(--line-1)' },
  accent:  { background: 'var(--accent-soft)', color: 'var(--accent)', border: '1px solid var(--accent-line)' },
  pos:     { background: 'var(--pos-soft)', color: 'var(--pos)', border: '1px solid transparent' },
  warn:    { background: 'var(--warn-soft)', color: 'var(--warn)', border: '1px solid transparent' },
  neg:     { background: 'var(--neg-soft)', color: 'var(--neg)', border: '1px solid transparent' },
  info:    { background: 'var(--info-soft)', color: 'var(--info)', border: '1px solid transparent' },
  outline: { background: 'transparent', color: 'var(--ink-2)', border: '1px solid var(--line-2)' },
}

const sizes = {
  xs: { height: 16, px: 5, fs: 10 },
  sm: { height: 18, px: 6, fs: 11 },
  md: { height: 22, px: 8, fs: 12 },
}

export function Badge({ tone = 'neutral', size = 'sm', dot, icon, className = '', children, ...props }: BadgeProps) {
  const t = tones[tone]
  const s = sizes[size]
  return (
    <span
      className={className}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        height: s.height,
        padding: `0 ${s.px}px`,
        ...t,
        borderRadius: 'var(--r-1)',
        fontSize: s.fs,
        fontWeight: 500,
        letterSpacing: 0,
        whiteSpace: 'nowrap',
      }}
      {...props}
    >
      {dot && <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'currentColor' }} />}
      {icon && <Icon name={icon} size={s.fs} />}
      {children}
    </span>
  )
}

// Legacy alias so old code importing HFBadge doesn't break
export function HFBadge({ className = '' }: { className?: string }) {
  return <Badge tone="info" className={className}>🤗 HuggingFace</Badge>
}
