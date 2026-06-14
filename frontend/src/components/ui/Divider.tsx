import { cn } from '@/lib/cn'

interface DividerProps {
  vertical?: boolean
  label?: string
  mt?: number
  mb?: number
  className?: string
}

export function Divider({ vertical, label, mt = 0, mb = 0, className }: DividerProps) {
  if (vertical) {
    return <div className={cn('w-px self-stretch bg-line-1', className)} />
  }

  if (label) {
    return (
      <div className={cn('flex items-center gap-2.5', className)} style={{ marginTop: mt, marginBottom: mb }}>
        <div className="h-px flex-1 bg-line-1" />
        <span className="caps text-ink-3">{label}</span>
        <div className="h-px flex-1 bg-line-1" />
      </div>
    )
  }

  return <div className={cn('h-px bg-line-1', className)} style={{ marginTop: mt, marginBottom: mb }} />
}
