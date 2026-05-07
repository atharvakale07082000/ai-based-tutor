import type { HTMLAttributes } from 'react'

type BadgeVariant = 'violet' | 'indigo' | 'emerald' | 'amber' | 'rose' | 'surface' | 'hf'

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant
  dot?: boolean
  glow?: boolean
}

const variantClasses: Record<BadgeVariant, string> = {
  violet: 'bg-violet/20 text-violet-light border border-violet/30',
  indigo: 'bg-indigo/20 text-indigo-light border border-indigo/30',
  emerald: 'bg-emerald/20 text-emerald border border-emerald/30',
  amber: 'bg-amber/20 text-amber border border-amber/30',
  rose: 'bg-rose/20 text-rose border border-rose/30',
  surface: 'bg-surface-2 text-paper/70 border border-surface-3',
  hf: 'bg-orange-500/20 text-orange-400 border border-orange-500/30',
}

export function Badge({ variant = 'violet', dot, glow, className = '', children, ...props }: BadgeProps) {
  return (
    <span
      className={`
        inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium
        ${variantClasses[variant]}
        ${glow ? 'agent-pill-active' : ''}
        ${className}
      `}
      {...props}
    >
      {dot && (
        <span className={`w-1.5 h-1.5 rounded-full ${variant === 'emerald' ? 'bg-emerald' : variant === 'rose' ? 'bg-rose' : variant === 'amber' ? 'bg-amber' : 'bg-violet-light'}`} />
      )}
      {children}
    </span>
  )
}

export function HFBadge({ className = '' }: { className?: string }) {
  return (
    <Badge variant="hf" className={className}>
      🤗 Hugging Face
    </Badge>
  )
}
