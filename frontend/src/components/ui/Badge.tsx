import type { HTMLAttributes } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/cn'
import { Icon } from './Icon'

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-[var(--r-1)] font-medium tracking-normal whitespace-nowrap border',
  {
    variants: {
      tone: {
        neutral: 'bg-paper-2 text-ink-1 border-line-1',
        accent: 'bg-accent-soft text-accent border-accent-line',
        pos: 'bg-pos-soft text-pos border-transparent',
        warn: 'bg-warn-soft text-warn border-transparent',
        neg: 'bg-neg-soft text-neg border-transparent',
        info: 'bg-info-soft text-info border-transparent',
        outline: 'bg-transparent text-ink-2 border-line-2',
      },
      size: {
        xs: 'h-4 px-[5px] text-[10px]',
        sm: 'h-[18px] px-1.5 text-[11px]',
        md: 'h-[22px] px-2 text-[12px]',
      },
    },
    defaultVariants: { tone: 'neutral', size: 'sm' },
  }
)

interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {
  dot?: boolean
  icon?: string
  glow?: boolean
}

const iconSizes = { xs: 10, sm: 11, md: 12 } as const

export function Badge({ tone, size = 'sm', dot, icon, className, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ tone, size }), className)} {...props}>
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {icon && <Icon name={icon} size={iconSizes[size ?? 'sm']} />}
      {children}
    </span>
  )
}

// Legacy alias so old code importing HFBadge doesn't break
export function HFBadge({ className }: { className?: string }) {
  return (
    <Badge tone="info" className={className}>
      🤗 HuggingFace
    </Badge>
  )
}
