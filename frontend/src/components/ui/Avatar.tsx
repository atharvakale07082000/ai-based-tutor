const PALETTE = ['#A8553A', '#6B5B95', '#4F6F4A', '#4A6B7A', '#B5832C']

interface AvatarProps {
  name?: string
  src?: string
  size?: number
  status?: 'online' | 'busy' | 'away'
}

export function Avatar({ name = '?', src, size = 28, status }: AvatarProps) {
  const initials = name.split(' ').map((p) => p[0]).slice(0, 2).join('').toUpperCase()
  const hash = name.split('').reduce((a, c) => a + c.charCodeAt(0), 0)
  const color = PALETTE[hash % PALETTE.length]

  return (
    <div style={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
      <div
        style={{
          width: size,
          height: size,
          borderRadius: 'var(--r-pill)',
          background: src ? `url(${src}) center/cover` : color + '22',
          color,
          fontWeight: 600,
          fontSize: size * 0.4,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          border: '1px solid var(--line-1)',
          letterSpacing: 0,
        }}
      >
        {!src && initials}
      </div>
      {status && (
        <div
          style={{
            position: 'absolute',
            bottom: 0,
            right: 0,
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: status === 'online' ? 'var(--pos)' : status === 'busy' ? 'var(--warn)' : 'var(--ink-3)',
            border: '2px solid var(--paper-0)',
          }}
        />
      )}
    </div>
  )
}
