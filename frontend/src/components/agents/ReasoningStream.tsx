import { useState, type CSSProperties } from 'react'
import { Icon } from '@/components/ui/Icon'

export interface ReasoningSegment {
  id?: string
  text: string
  /** Pipeline flows carry a status; free-form chat reasoning leaves it undefined. */
  status?: 'active' | 'done' | 'error'
}

/**
 * Shows the agent's internal reasoning — how it's thinking through the task — as a
 * live "Thinking…" panel that collapses to a re-openable "Reasoning" toggle once the
 * work is done. This replaces the old mechanical agent-workflow trace (tool names,
 * args, latencies, step checklist), which was never meant for learners' eyes.
 *
 * Two shapes feed it:
 *   - chat: one free-form segment whose text streams in (no status).
 *   - generation flows: one segment per pipeline step, carrying a status.
 */
export function ReasoningStream({
  segments,
  active,
  className,
  style,
}: {
  segments: ReasoningSegment[]
  /** Whether reasoning is still streaming. Derived from segment status if omitted. */
  active?: boolean
  className?: string
  style?: CSSProperties
}) {
  const [userOpen, setUserOpen] = useState(false)
  const visible = segments.filter((s) => s.text.trim())
  if (visible.length === 0) return null

  const isActive = active ?? visible.some((s) => s.status === 'active')
  const isOpen = isActive || userOpen

  return (
    <div
      className={className}
      style={{
        border: '1px solid var(--line-1)',
        borderRadius: 'var(--r-2)',
        background: 'var(--paper-1)',
        overflow: 'hidden',
        marginBottom: 8,
        ...style,
      }}
    >
      {/* Header — "Thinking…" while live, a re-openable "Reasoning" toggle when done */}
      <button
        onClick={() => !isActive && setUserOpen((v) => !v)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 7,
          width: '100%',
          padding: '6px 10px',
          background: 'var(--paper-2)',
          border: 0,
          borderBottom: isOpen ? '1px solid var(--line-1)' : 0,
          cursor: isActive ? 'default' : 'pointer',
          fontFamily: 'inherit',
          textAlign: 'left',
        }}
      >
        <Icon
          name="sparkle"
          size={12}
          style={{ color: 'var(--accent)', flexShrink: 0, ...(isActive ? { animation: 'pulse-soft 1.4s ease-in-out infinite' } : {}) }}
        />
        <span className="t-xs fg-2" style={{ flex: 1, fontWeight: 500 }}>
          {isActive ? 'Thinking…' : 'Reasoning'}
        </span>
        {isActive ? (
          <span
            style={{
              width: 8,
              height: 8,
              border: '1.5px solid var(--line-2)',
              borderTopColor: 'var(--accent)',
              borderRadius: '50%',
              animation: 'spin 0.7s linear infinite',
            }}
          />
        ) : (
          <span
            style={{
              fontSize: 9,
              color: 'var(--ink-3)',
              transform: isOpen ? 'rotate(90deg)' : 'none',
              transition: 'transform 0.15s',
            }}
          >
            ▶
          </span>
        )}
      </button>

      {/* Body — reasoning lines */}
      {isOpen && (
        <div style={{ padding: '8px 11px', display: 'flex', flexDirection: 'column', gap: 6 }}>
          {visible.map((s, i) => {
            const isLastActive = isActive && i === visible.length - 1
            return (
              <div key={s.id ?? i} style={{ display: 'flex', gap: 7, alignItems: 'flex-start' }}>
                {s.status && (
                  <span style={{ flexShrink: 0, marginTop: 3 }}>
                    <StatusGlyph status={s.status} />
                  </span>
                )}
                <span
                  className="t-xs"
                  style={{
                    color: s.status === 'active' || isLastActive ? 'var(--ink-1)' : 'var(--ink-3)',
                    fontStyle: 'italic',
                    lineHeight: 1.55,
                  }}
                >
                  {s.text}
                  {isLastActive && !s.status && (
                    <span className="caret-blink" style={{ fontStyle: 'normal' }}>▌</span>
                  )}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function StatusGlyph({ status }: { status: NonNullable<ReasoningSegment['status']> }) {
  if (status === 'done') {
    return <Icon name="check" size={10} style={{ color: 'var(--pos)' }} />
  }
  if (status === 'error') {
    return <Icon name="x" size={10} style={{ color: 'var(--neg)' }} />
  }
  return (
    <span
      style={{
        display: 'inline-block',
        width: 8,
        height: 8,
        border: '1.5px solid var(--line-2)',
        borderTopColor: 'var(--accent)',
        borderRadius: '50%',
        animation: 'spin 0.7s linear infinite',
      }}
    />
  )
}
