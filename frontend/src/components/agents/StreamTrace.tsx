import { useState } from 'react'
import { ToolCallCard } from '@/components/agents/ToolCallCard'

export interface AgentStep {
  step: number
  thought?: string
  toolCall?: { name: string; args: Record<string, unknown> }
  toolResult?: { result: unknown; latency_ms: number }
}

interface StreamTraceProps {
  routing?: { agent: string; reason: string }
  steps: AgentStep[]
  streaming: boolean
}

function countTools(steps: AgentStep[]): number {
  return steps.filter((s) => s.toolCall).length
}

export function StreamTrace({ routing, steps, streaming }: StreamTraceProps) {
  // Expanded while streaming; collapsed once done
  const [expanded, setExpanded] = useState(true)

  // When streaming goes from true→false, collapse
  // We do this declaratively: collapsed state is the complement of expanded,
  // but auto-expand while streaming
  const isExpanded = streaming || expanded

  if (!routing && steps.length === 0) return null

  const toolCount = countTools(steps)

  return (
    <div style={{ marginBottom: 8 }}>
      {/* Routing chip */}
      {routing && (
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
            padding: '2px 8px',
            background: 'color-mix(in srgb, var(--accent) 10%, var(--paper-2))',
            border: '1px solid color-mix(in srgb, var(--accent) 20%, transparent)',
            borderRadius: 'var(--r-pill)',
            fontSize: 11,
            color: 'var(--accent)',
            fontFamily: 'var(--font-mono)',
            marginBottom: 8,
          }}
        >
          <span style={{ fontSize: 12 }}>→</span>
          <span style={{ fontWeight: 600 }}>{routing.agent}</span>
          <span style={{ color: 'var(--ink-3)', fontSize: 10 }}>·</span>
          <span style={{ color: 'var(--ink-2)', fontSize: 10 }}>{routing.reason}</span>
        </div>
      )}

      {/* Steps section */}
      {steps.length > 0 && (
        <div
          style={{
            border: '1px solid var(--line-1)',
            borderRadius: 'var(--r-2)',
            overflow: 'hidden',
            background: 'var(--paper-1)',
          }}
        >
          {/* Collapse/expand header */}
          <button
            onClick={() => !streaming && setExpanded((v) => !v)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              width: '100%',
              padding: '6px 10px',
              background: 'var(--paper-2)',
              border: 0,
              borderBottom: isExpanded ? '1px solid var(--line-1)' : 0,
              cursor: streaming ? 'default' : 'pointer',
              fontFamily: 'inherit',
              textAlign: 'left',
            }}
          >
            <span style={{ fontSize: 10, color: 'var(--ink-3)', transform: isExpanded ? 'rotate(90deg)' : 'none', display: 'inline-block', transition: 'transform 0.15s' }}>▶</span>
            <span className="t-xs fg-2" style={{ flex: 1, fontWeight: 500 }}>
              {steps.length} {steps.length === 1 ? 'step' : 'steps'}
              {toolCount > 0 && ` · ${toolCount} tool${toolCount > 1 ? 's' : ''} used`}
            </span>
            {streaming && (
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
            )}
          </button>

          {/* Step cards */}
          {isExpanded && (
            <div style={{ padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 8 }}>
              {steps.map((step) => (
                <div key={step.step}>
                  {/* Thought bubble */}
                  {step.thought && (
                    <div
                      style={{
                        padding: '5px 10px',
                        background: 'var(--paper-2)',
                        borderRadius: 'var(--r-2)',
                        marginBottom: step.toolCall ? 6 : 0,
                        border: '1px solid var(--line-1)',
                      }}
                    >
                      <span className="t-xs" style={{ color: 'var(--ink-3)', fontStyle: 'italic', lineHeight: 1.5, display: 'block' }}>
                        {step.thought}
                      </span>
                    </div>
                  )}

                  {/* Tool call card */}
                  {step.toolCall && (
                    <ToolCallCard
                      name={step.toolCall.name}
                      args={step.toolCall.args}
                      result={step.toolResult?.result}
                      latency_ms={step.toolResult?.latency_ms}
                      isLoading={!step.toolResult}
                    />
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
