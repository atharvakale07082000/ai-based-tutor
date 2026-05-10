import { forwardRef, type InputHTMLAttributes } from 'react'
import { Icon } from './Icon'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  icon?: string
  suffix?: string
  label?: string
  hint?: string
  error?: string
  inputSize?: 'sm' | 'md' | 'lg'
}

const heights = { sm: 26, md: 30, lg: 36 }

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ icon, suffix, label, hint, error, inputSize = 'md', className = '', style = {}, ...props }, ref) => {
    return (
      <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {label && <span className="caps" style={{ color: 'var(--ink-2)' }}>{label}</span>}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            height: heights[inputSize],
            padding: '0 10px',
            background: 'var(--paper-1)',
            border: `1px solid ${error ? 'var(--neg)' : 'var(--line-2)'}`,
            borderRadius: 'var(--r-2)',
            transition: 'border-color var(--dur-fast) var(--ease-out), box-shadow var(--dur-fast) var(--ease-out)',
          }}
          onFocusCapture={(e) => { e.currentTarget.style.boxShadow = 'var(--ring-focus)' }}
          onBlurCapture={(e) => { e.currentTarget.style.boxShadow = 'none' }}
        >
          {icon && <Icon name={icon} size={13} style={{ color: 'var(--ink-3)', flexShrink: 0 }} />}
          <input
            ref={ref}
            {...props}
            style={{
              flex: 1,
              height: '100%',
              background: 'transparent',
              border: 0,
              outline: 'none',
              fontSize: 13,
              color: 'var(--ink-0)',
              fontFamily: 'inherit',
              ...style,
            }}
          />
          {suffix && <span className="t-xs fg-3">{suffix}</span>}
        </div>
        {hint && !error && <span className="t-xs fg-3">{hint}</span>}
        {error && <span className="t-xs" style={{ color: 'var(--neg)' }}>{error}</span>}
      </label>
    )
  }
)
Input.displayName = 'Input'
