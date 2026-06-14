import { forwardRef, type HTMLAttributes } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/cn'

const cardVariants = cva(
  'relative rounded-[var(--r-3)] border border-line-1 bg-paper-1 transition-[border-color,background-color,transform,box-shadow] duration-[var(--dur-base)] ease-[var(--ease-out)]',
  {
    variants: {
      padding: {
        none: 'p-0',
        sm: 'p-3',
        md: 'p-4',
        lg: 'p-6',
      },
      hover: {
        true: 'hover:border-line-2 hover:bg-paper-2 hover:-translate-y-0.5 hover:shadow-[var(--shadow-2)]',
        false: '',
      },
      raised: {
        true: 'shadow-[var(--shadow-2)]',
        false: '',
      },
    },
    defaultVariants: { padding: 'md', hover: false, raised: false },
  }
)

interface CardProps extends HTMLAttributes<HTMLDivElement>, VariantProps<typeof cardVariants> {
  accent?: boolean
}

export const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ padding, hover, raised, accent, className, children, ...props }, ref) => {
    return (
      <div ref={ref} className={cn(cardVariants({ padding, hover, raised }), className)} {...props}>
        {accent && (
          <div className="absolute left-3 right-3 top-0 h-0.5 rounded-b-sm bg-accent" />
        )}
        {children}
      </div>
    )
  }
)
Card.displayName = 'Card'

export function CardSkeleton() {
  return (
    <div className="rounded-[var(--r-3)] border border-line-1 bg-paper-1 p-4">
      <div className="skel mb-2 h-3 w-3/5" />
      <div className="skel mb-2 h-3 w-4/5" />
      <div className="skel h-3 w-2/5" />
    </div>
  )
}
