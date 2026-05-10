interface TabItem {
  value: string
  label: string
  icon?: string
  count?: number
}

interface TabsProps {
  tabs: TabItem[]
  value: string
  onChange: (v: string) => void
  variant?: 'underline' | 'segmented'
}

export function Tabs({ tabs, value, onChange, variant = 'underline' }: TabsProps) {
  if (variant === 'segmented') {
    return (
      <div style={{ display: 'inline-flex', padding: 2, gap: 2, background: 'var(--paper-2)', borderRadius: 'var(--r-2)', border: '1px solid var(--line-1)' }}>
        {tabs.map((t) => (
          <button
            key={t.value}
            onClick={() => onChange(t.value)}
            style={{
              padding: '3px 10px',
              fontSize: 12,
              fontWeight: 500,
              borderRadius: 'var(--r-1)',
              background: value === t.value ? 'var(--paper-0)' : 'transparent',
              color: value === t.value ? 'var(--ink-0)' : 'var(--ink-2)',
              boxShadow: value === t.value ? 'var(--shadow-1)' : 'none',
              transition: 'all var(--dur-fast) var(--ease-out)',
              cursor: 'pointer',
              border: 0,
              fontFamily: 'inherit',
              whiteSpace: 'nowrap',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', borderBottom: '1px solid var(--line-1)', gap: 0 }}>
      {tabs.map((t) => (
        <button
          key={t.value}
          onClick={() => onChange(t.value)}
          style={{
            padding: '8px 12px',
            fontSize: 13,
            fontWeight: 500,
            color: value === t.value ? 'var(--ink-0)' : 'var(--ink-2)',
            borderBottom: `2px solid ${value === t.value ? 'var(--ink-0)' : 'transparent'}`,
            marginBottom: -1,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            transition: 'color var(--dur-fast)',
            background: 'transparent',
            cursor: 'pointer',
            fontFamily: 'inherit',
            whiteSpace: 'nowrap',
          }}
        >
          {t.label}
          {t.count !== undefined && (
            <span style={{ fontSize: 11, color: 'var(--ink-3)' }}>{t.count}</span>
          )}
        </button>
      ))}
    </div>
  )
}
