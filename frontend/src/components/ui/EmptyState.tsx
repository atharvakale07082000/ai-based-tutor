import { Icon } from './Icon'
import { Button } from './Button'

interface EmptyStateProps {
  icon: string
  title: string
  body?: string
  action?: { label: string; onClick: () => void }
  size?: 'sm' | 'md'
}

export function EmptyState({ icon, title, body, action, size = 'md' }: EmptyStateProps) {
  const pad = size === 'sm' ? '16px 12px' : '28px 16px'
  const iconSize = size === 'sm' ? 18 : 24

  return (
    <div style={{ padding: pad, display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 8 }}>
      <div style={{
        width: iconSize + 16,
        height: iconSize + 16,
        borderRadius: 'var(--r-2)',
        background: 'var(--paper-2)',
        display: 'grid',
        placeItems: 'center',
      }}>
        <Icon name={icon as any} size={iconSize} style={{ color: 'var(--ink-3)' }} />
      </div>
      <div>
        <div className="t-sm fg-1" style={{ fontWeight: 500 }}>{title}</div>
        {body && <div className="t-xs fg-3" style={{ marginTop: 2, maxWidth: 220, lineHeight: 1.5 }}>{body}</div>}
      </div>
      {action && (
        <Button size="sm" variant="secondary" onClick={action.onClick}>{action.label}</Button>
      )}
    </div>
  )
}
