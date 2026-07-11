import { Icon } from '@/components/ui/Icon'

interface ToolCallCardProps {
  name: string
  latency_ms?: number
  isLoading?: boolean
}

function Spinner() {
  return (
    <span
      style={{
        display: 'inline-block',
        width: 10,
        height: 10,
        border: '1.5px solid var(--line-2)',
        borderTopColor: 'var(--accent)',
        borderRadius: '50%',
        animation: 'spin 0.7s linear infinite',
      }}
    />
  )
}

/**
 * Compact "a tool ran" chip. Intentionally shows only the tool name and its
 * timing/loading state — never the raw arguments or results, which can contain
 * internal ids and other data the learner shouldn't see. The agent's reasoning
 * is surfaced separately as the thought text in StreamTrace.
 */
export function ToolCallCard({ name, latency_ms, isLoading }: ToolCallCardProps) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '5px 10px',
        background: 'var(--paper-2)',
        border: '1px solid var(--line-1)',
        borderRadius: 'var(--r-2)',
        fontFamily: 'var(--font-mono)',
      }}
    >
      <Icon name="bolt" size={11} style={{ color: 'var(--accent)', flexShrink: 0 }} />
      <span
        className="mono"
        style={{
          fontSize: 11,
          color: 'var(--ink-0)',
          fontWeight: 600,
          flex: 1,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {name}
      </span>
      {isLoading ? (
        <Spinner />
      ) : latency_ms !== undefined ? (
        <span
          style={{
            fontSize: 10,
            color: 'var(--pos)',
            background: 'color-mix(in srgb, var(--pos) 10%, var(--paper-2))',
            border: '1px solid color-mix(in srgb, var(--pos) 20%, transparent)',
            borderRadius: 'var(--r-pill)',
            padding: '1px 6px',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {latency_ms}ms
        </span>
      ) : null}
    </div>
  )
}
