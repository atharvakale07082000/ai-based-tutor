import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { Icon } from './Icon'

type Variant = 'primary' | 'secondary' | 'ghost' | 'outline' | 'accent' | 'danger'
type Size = 'xs' | 'sm' | 'md' | 'lg'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  icon?: string
  iconRight?: string
  loading?: boolean
  full?: boolean
  as?: 'button' | 'a'
  href?: string
}

interface VariantStyle {
  background: string
  color: string
  borderColor: string
  hover: string
  hoverBorder: string
}

const variantStyles: Record<Variant, VariantStyle> = {
  primary:   { background: 'var(--ink-0)', color: 'var(--paper-0)', borderColor: 'var(--ink-0)', hover: 'var(--accent)', hoverBorder: 'var(--accent)' },
  accent:    { background: 'var(--accent)', color: '#fff', borderColor: 'var(--accent)', hover: 'var(--accent-hover)', hoverBorder: 'var(--accent-hover)' },
  secondary: { background: 'var(--paper-1)', color: 'var(--ink-0)', borderColor: 'var(--line-2)', hover: 'var(--paper-2)', hoverBorder: 'var(--line-2)' },
  ghost:     { background: 'transparent', color: 'var(--ink-1)', borderColor: 'transparent', hover: 'var(--paper-2)', hoverBorder: 'transparent' },
  outline:   { background: 'transparent', color: 'var(--ink-0)', borderColor: 'var(--line-2)', hover: 'var(--paper-1)', hoverBorder: 'var(--line-2)' },
  danger:    { background: 'var(--neg-soft)', color: 'var(--neg)', borderColor: 'transparent', hover: 'var(--neg-soft)', hoverBorder: 'transparent' },
}

const sizeStyles: Record<Size, { height: number; px: number; fontSize: number; gap: number }> = {
  xs: { height: 22, px: 8,  fontSize: 11, gap: 4 },
  sm: { height: 26, px: 10, fontSize: 12, gap: 5 },
  md: { height: 30, px: 12, fontSize: 13, gap: 6 },
  lg: { height: 38, px: 16, fontSize: 14, gap: 8 },
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'secondary', size = 'md', icon, iconRight, loading, disabled, full, className = '', children, as: Tag = 'button', ...props }, ref) => {
    const v = variantStyles[variant]
    const s = sizeStyles[size]
    const isDisabled = disabled || loading

    return (
      <button
        ref={ref}
        disabled={isDisabled}
        className={className}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: s.gap,
          height: s.height,
          padding: `0 ${s.px}px`,
          fontSize: s.fontSize,
          fontWeight: 500,
          background: v.background,
          color: v.color,
          border: `1px solid ${v.borderColor}`,
          borderRadius: 'var(--r-2)',
          cursor: isDisabled ? 'not-allowed' : 'pointer',
          opacity: disabled ? 0.5 : 1,
          transition: 'background var(--dur-fast) var(--ease-out)',
          width: full ? '100%' : 'auto',
          letterSpacing: '-0.005em',
          whiteSpace: 'nowrap',
          flexShrink: 0,
          fontFamily: 'inherit',
        }}
        onMouseEnter={(e) => {
          if (isDisabled) return
          e.currentTarget.style.background = v.hover
          e.currentTarget.style.borderColor = v.hoverBorder
        }}
        onMouseLeave={(e) => {
          if (isDisabled) return
          e.currentTarget.style.background = v.background
          e.currentTarget.style.borderColor = v.borderColor
        }}
        {...props}
      >
        {loading ? (
          <span style={{ width: 12, height: 12, border: '1.5px solid currentColor', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.7s linear infinite', display: 'inline-block' }} />
        ) : icon ? <Icon name={icon} size={s.fontSize + 1} /> : null}
        {children}
        {iconRight && !loading && <Icon name={iconRight} size={s.fontSize + 1} />}
      </button>
    )
  }
)
Button.displayName = 'Button'
