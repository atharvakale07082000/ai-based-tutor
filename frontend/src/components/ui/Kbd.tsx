import { cn } from '@/lib/cn'

interface KbdProps {
  keys: string[]
  className?: string
}

export function Kbd({ keys, className }: KbdProps) {
  return (
    <span className={cn('inline-flex gap-0.5', className)}>
      {keys.map((k, i) => (
        <kbd key={i} className="kbd">{k}</kbd>
      ))}
    </span>
  )
}
