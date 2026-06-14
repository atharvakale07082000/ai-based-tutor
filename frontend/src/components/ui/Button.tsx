import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/cn'
import { Icon } from './Icon'

const buttonVariants = cva(
  'inline-flex items-center justify-center font-medium whitespace-nowrap flex-shrink-0 tracking-[-0.005em] rounded-[var(--r-2)] border font-[inherit] ' +
    'transition-[background-color,border-color,transform,box-shadow] duration-[var(--dur-fast)] ease-[var(--ease-out)] ' +
    'active:scale-[0.965] disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer',
  {
    variants: {
      variant: {
        primary: 'bg-ink-0 text-paper-0 border-ink-0 hover:bg-accent hover:border-accent',
        accent: 'bg-accent text-white border-accent hover:bg-accent-hover hover:border-accent-hover',
        secondary: 'bg-paper-1 text-ink-0 border-line-2 hover:bg-paper-2',
        ghost: 'bg-transparent text-ink-1 border-transparent hover:bg-paper-2',
        outline: 'bg-transparent text-ink-0 border-line-2 hover:bg-paper-1',
        danger: 'bg-neg-soft text-neg border-transparent hover:bg-neg-soft',
      },
      size: {
        xs: 'h-[22px] px-2 text-[11px] gap-1',
        sm: 'h-[26px] px-2.5 text-[12px] gap-[5px]',
        md: 'h-[30px] px-3 text-[13px] gap-1.5',
        lg: 'h-[38px] px-4 text-[14px] gap-2',
      },
      full: {
        true: 'w-full',
        false: 'w-auto',
      },
    },
    defaultVariants: { variant: 'secondary', size: 'md', full: false },
  }
)

const iconSizes: Record<NonNullable<VariantProps<typeof buttonVariants>['size']>, number> = {
  xs: 12,
  sm: 13,
  md: 14,
  lg: 15,
}

interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  icon?: string
  iconRight?: string
  loading?: boolean
  as?: 'button' | 'a'
  href?: string
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant, size = 'md', icon, iconRight, loading, disabled, full, className, children, ...props }, ref) => {
    const isDisabled = disabled || loading
    const iconSize = iconSizes[size ?? 'md']

    return (
      <button
        ref={ref}
        disabled={isDisabled}
        className={cn('group', buttonVariants({ variant, size, full }), className)}
        {...props}
      >
        {loading ? (
          <span className="inline-block h-3 w-3 animate-[spin_0.7s_linear_infinite] rounded-full border-[1.5px] border-current border-t-transparent" />
        ) : icon ? (
          <Icon name={icon} size={iconSize} />
        ) : null}
        {children}
        {iconRight && !loading && (
          <Icon
            name={iconRight}
            size={iconSize}
            className="transition-transform duration-[var(--dur-fast)] ease-[var(--ease-out)] group-hover:translate-x-[2.5px]"
          />
        )}
      </button>
    )
  }
)
Button.displayName = 'Button'
