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
      // Emphasis rule — three filled variants exist because they are three different
      // decisions, not three shades of one: `primary` is the page's single main action
      // (ink), `signal` is the one amber "do this now" (ratings, key CTAs), `accent` is the
      // brand-terracotta CTA reserved for Ask-Atelier-style entry points. Everything else
      // is quieter: secondary > outline > ghost. `danger` is destructive only.
      variant: {
        primary: 'bg-ink-0 text-paper-0 border-ink-0 hover:bg-accent hover:border-accent',
        accent:
          'bg-[var(--accent-btn)] text-white border-[var(--accent-btn)] ' +
          'hover:bg-[var(--accent-btn-hover)] hover:border-[var(--accent-btn-hover)]',
        // Amber signal — the single "do this" action on a view (ratings, key CTAs).
        signal:
          'bg-[var(--signal-btn)] text-[var(--on-signal)] border-[var(--signal-btn)] ' +
          'hover:bg-[var(--signal-btn-hover)] hover:border-[var(--signal-btn-hover)]',
        // paper-2 fill (not paper-1) so the button stays visible on paper-1 cards in both themes.
        secondary: 'bg-paper-2 text-ink-0 border-line-2 hover:bg-paper-3',
        ghost: 'bg-transparent text-ink-1 border-transparent hover:bg-paper-2',
        outline: 'bg-transparent text-ink-0 border-line-2 hover:bg-paper-1',
        danger: 'bg-neg-soft text-neg border-transparent hover:bg-neg-soft',
      },
      size: {
        // 24px is the WCAG 2.1 AA (2.5.8) minimum target size; xs sat at 22px and failed it
        // everywhere it was used (message actions, Voice, round actions). Keep xs for dense
        // table/message rows only — 111 callsites reached past the md default for xs/sm, which
        // is why the interface read as uniformly tiny. Sizes track the 2026-08-23 type lift.
        xs: 'h-6 px-2 text-[12px] gap-1',
        sm: 'h-[28px] px-3 text-[13px] gap-[5px]',
        md: 'h-[34px] px-3.5 text-[14px] gap-1.5',
        lg: 'h-[40px] px-5 text-[15px] gap-2',
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
