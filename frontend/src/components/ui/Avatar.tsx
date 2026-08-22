import { cn } from '@/lib/cn'

// Deterministic avatar hues, used as a 13% fill only.
//
// The initials themselves are NOT tinted: drawing a hue at full strength on a 13% wash of
// itself gave 4.1:1 in light and 3.1:1 in dark, both under AA, and the dark case was worse
// because these hues are picked for a cream ground. Painting the initials in the theme's own
// ink keeps them legible in both themes while the fill still carries the identity colour.
const PALETTE = ['#B4700E', '#A8553A', '#2F8C82', '#4A6B9A', '#8A5A6E']

interface AvatarProps {
  name?: string
  src?: string
  size?: number
  status?: 'online' | 'busy' | 'away'
  className?: string
}

export function Avatar({ name = '?', src, size = 28, status, className }: AvatarProps) {
  const initials = name.split(' ').map((p) => p[0]).slice(0, 2).join('').toUpperCase()
  const hash = name.split('').reduce((a, c) => a + c.charCodeAt(0), 0)
  const color = PALETTE[hash % PALETTE.length]

  return (
    <div className={cn('relative flex-shrink-0', className)} style={{ width: size, height: size }}>
      <div
        className="flex h-full w-full items-center justify-center rounded-[var(--r-pill)] border border-line-1 font-semibold"
        style={{
          background: src ? `url(${src}) center/cover` : color + '22',
          color: 'var(--ink-0)',
          fontSize: size * 0.4,
          letterSpacing: 0,
        }}
      >
        {!src && initials}
      </div>
      {status && (
        <div
          className="absolute bottom-0 right-0 h-2 w-2 rounded-full border-2 border-paper-0"
          style={{
            background: status === 'online' ? 'var(--pos)' : status === 'busy' ? 'var(--warn)' : 'var(--ink-3)',
          }}
        />
      )}
    </div>
  )
}
