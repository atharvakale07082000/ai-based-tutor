import type { CSSProperties } from 'react'
import { Icon } from './Icon'
import type { TimelineStep } from '@/hooks/useAgentTimeline'

/**
 * Vertical live-progress timeline for agent flows.
 *
 * Each step renders a status node and label:
 *   - done   → green check
 *   - active → pulsing accent spinner
 *   - error  → red alert
 *   - (steps stream in dynamically; the connector line links them)
 */
export function AgentTimeline({
  steps,
  className,
  style,
}: {
  steps: TimelineStep[]
  className?: string
  style?: CSSProperties
}) {
  if (steps.length === 0) return null

  return (
    <div className={className} style={{ display: 'flex', flexDirection: 'column', gap: 0, ...style }}>
      {steps.map((step, i) => {
        const isLast = i === steps.length - 1
        return (
          <div key={step.id} style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
            {/* Node + connector column */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', alignSelf: 'stretch' }}>
              <StepNode status={step.status} />
              {!isLast && (
                <div
                  style={{
                    width: 2,
                    flex: 1,
                    minHeight: 14,
                    background: 'var(--line-2)',
                    marginTop: 2,
                    marginBottom: 2,
                  }}
                />
              )}
            </div>
            {/* Label */}
            <div style={{ paddingBottom: isLast ? 0 : 12, paddingTop: 1 }}>
              <span
                className="t-sm"
                style={{
                  color:
                    step.status === 'done'
                      ? 'var(--ink-1)'
                      : step.status === 'error'
                        ? 'var(--neg)'
                        : 'var(--ink-0)',
                  fontWeight: step.status === 'active' ? 500 : 400,
                }}
              >
                {step.label}
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function StepNode({ status }: { status: TimelineStep['status'] }) {
  if (status === 'done') {
    return (
      <span
        style={{
          width: 18,
          height: 18,
          borderRadius: '50%',
          background: 'var(--pos)',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        <Icon name="check" size={11} style={{ color: 'var(--paper-0)' }} />
      </span>
    )
  }
  if (status === 'error') {
    return (
      <span
        style={{
          width: 18,
          height: 18,
          borderRadius: '50%',
          background: 'var(--neg)',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        <Icon name="x" size={11} style={{ color: 'var(--paper-0)' }} />
      </span>
    )
  }
  // active
  return (
    <span
      style={{
        width: 18,
        height: 18,
        borderRadius: '50%',
        border: '2px solid var(--accent)',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
      }}
    >
      <Icon name="refresh" size={11} className="spin" style={{ color: 'var(--accent)' }} />
    </span>
  )
}
