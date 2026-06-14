import { forwardRef, type InputHTMLAttributes } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/cn'
import { Icon } from './Icon'

const wrapperVariants = cva(
  'flex items-center gap-1.5 rounded-[var(--r-2)] border bg-paper-1 px-2.5 transition-[border-color,box-shadow] duration-[var(--dur-fast)] ease-[var(--ease-out)] focus-within:shadow-[var(--ring-focus)]',
  {
    variants: {
      inputSize: {
        sm: 'h-[26px]',
        md: 'h-[30px]',
        lg: 'h-9',
      },
      error: {
        true: 'border-neg',
        false: 'border-line-2',
      },
    },
    defaultVariants: { inputSize: 'md', error: false },
  }
)

interface InputProps
  extends InputHTMLAttributes<HTMLInputElement>,
    Omit<VariantProps<typeof wrapperVariants>, 'error'> {
  icon?: string
  suffix?: string
  label?: string
  hint?: string
  error?: string
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ icon, suffix, label, hint, error, inputSize, className, ...props }, ref) => {
    return (
      <label className="flex flex-col gap-1">
        {label && <span className="caps text-ink-2">{label}</span>}
        <div className={wrapperVariants({ inputSize, error: !!error })}>
          {icon && <Icon name={icon} size={13} className="flex-shrink-0 text-ink-3" />}
          <input
            ref={ref}
            {...props}
            className={cn(
              'h-full flex-1 bg-transparent border-0 outline-none text-[13px] text-ink-0 font-[inherit]',
              className
            )}
          />
          {suffix && <span className="t-xs fg-3">{suffix}</span>}
        </div>
        {hint && !error && <span className="t-xs fg-3">{hint}</span>}
        {error && <span className="t-xs text-neg">{error}</span>}
      </label>
    )
  }
)
Input.displayName = 'Input'
