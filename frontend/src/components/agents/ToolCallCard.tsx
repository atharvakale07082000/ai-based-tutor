import { Icon } from '@/components/ui/Icon'

interface ToolCallCardProps {
  name: string
  args: Record<string, unknown>
  result?: unknown
  latency_ms?: number
  isLoading?: boolean
}

function truncateJson(val: unknown, maxLen = 120): string {
  const str = JSON.stringify(val, null, 2)
  return str.length > maxLen ? str.slice(0, maxLen) + '…' : str
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

export function ToolCallCard({ name, args, result, latency_ms, isLoading }: ToolCallCardProps) {
  const argsStr = truncateJson(args)
  const resultStr = result !== undefined ? truncateJson(result) : null

  return (
    <div
      style={{
        background: 'var(--paper-2)',
        border: '1px solid var(--line-1)',
        borderRadius: 'var(--r-2)',
        overflow: 'hidden',
        fontSize: 12,
        fontFamily: 'var(--font-mono)',
      }}
    >
      {/* Header pill row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '5px 10px',
          background: 'var(--paper-3)',
          borderBottom: '1px solid var(--line-1)',
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

      {/* Args block */}
      <div style={{ padding: '6px 10px' }}>
        <div className="caps" style={{ fontSize: 9, color: 'var(--ink-3)', marginBottom: 3, letterSpacing: '0.06em' }}>args</div>
        <pre
          style={{
            margin: 0,
            fontSize: 11,
            color: 'var(--ink-2)',
            fontFamily: 'var(--font-mono)',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
            lineHeight: 1.5,
          }}
        >
          {argsStr}
        </pre>
      </div>

      {/* Result block */}
      {resultStr !== null && (
        <div
          style={{
            padding: '6px 10px',
            background: 'color-mix(in srgb, var(--pos) 8%, var(--paper-2))',
            borderTop: '1px solid color-mix(in srgb, var(--pos) 15%, transparent)',
          }}
        >
          <div className="caps" style={{ fontSize: 9, color: 'var(--pos)', marginBottom: 3, letterSpacing: '0.06em' }}>result</div>
          <pre
            style={{
              margin: 0,
              fontSize: 11,
              color: 'var(--ink-1)',
              fontFamily: 'var(--font-mono)',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
              lineHeight: 1.5,
            }}
          >
            {resultStr}
          </pre>
        </div>
      )}
    </div>
  )
}
