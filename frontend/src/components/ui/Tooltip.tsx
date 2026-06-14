import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

interface TooltipProps {
  children: ReactNode
  label: ReactNode
  side?: 'top' | 'bottom'
  className?: string
}

export function Tooltip({ children, label, side = 'top', className }: TooltipProps) {
  return (
    <span className={cn('tt-wrap relative inline-flex', className)}>
      {children}
      <span
        className={cn(
          'tt pointer-events-none absolute left-1/2 z-[100] -translate-x-1/2 whitespace-nowrap rounded-[var(--r-1)] bg-ink-0 px-[7px] py-[3px] text-[11px] text-paper-0 opacity-0 transition-opacity duration-[var(--dur-fast)]',
          side === 'top' ? 'bottom-full mb-1.5' : 'top-full mt-1.5'
        )}
      >
        {label}
      </span>
    </span>
  )
}
