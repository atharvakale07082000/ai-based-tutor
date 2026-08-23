import type { SelectHTMLAttributes } from 'react'

/**
 * The one styled dropdown.
 *
 * Three pages hand-rolled a bare `<select>`, which keeps the platform's own chrome — a grey
 * OS control with a native arrow sitting inside otherwise fully tokenised cards. `appearance:
 * none` plus a drawn chevron is what makes it match everything around it.
 *
 * `tone="code"` is for the dark editor toolbar, which sits on `--code-*` rather than `--paper-*`.
 */
export function Select({
  tone = 'default',
  size = 'sm',
  style,
  ...props
}: Omit<SelectHTMLAttributes<HTMLSelectElement>, 'size'> & {
  tone?: 'default' | 'code'
  size?: 'xs' | 'sm'
}) {
  const code = tone === 'code'
  const pad = size === 'xs' ? '3px 24px 3px 8px' : '5px 26px 5px 9px'

  // A chevron drawn in the current ink colour, inlined so no request is needed.
  const chevron = encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="10" height="6" viewBox="0 0 10 6"><path d="M1 1l4 4 4-4" fill="none" stroke="${
      code ? '#8FA6B8' : '#6E6553'
    }" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  )

  return (
    <select
      {...props}
      style={{
        appearance: 'none',
        WebkitAppearance: 'none',
        MozAppearance: 'none',
        fontFamily: code ? 'var(--font-mono)' : 'inherit',
        fontSize: code ? 12 : 'var(--t-sm)',
        letterSpacing: code ? '0.04em' : undefined,
        padding: pad,
        borderRadius: 'var(--r-1)',
        background: `url("data:image/svg+xml,${chevron}") no-repeat right 9px center, ${
          code ? 'var(--code-bg)' : 'var(--paper-2)'
        }`,
        color: code ? 'var(--code-ink)' : 'var(--ink-1)',
        border: `1px solid ${code ? 'var(--code-line)' : 'var(--line-1)'}`,
        cursor: 'pointer',
        lineHeight: 1.4,
        ...style,
      }}
    />
  )
}
