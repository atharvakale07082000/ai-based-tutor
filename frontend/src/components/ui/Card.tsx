import { forwardRef, type HTMLAttributes } from 'react'

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  padding?: 'none' | 'sm' | 'md' | 'lg'
  hover?: boolean
  accent?: boolean
  raised?: boolean
}

const pads = { none: 0, sm: 12, md: 16, lg: 24 }

export const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ padding = 'md', hover, accent, raised, className = '', style = {}, children, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={className}
        style={{
          background: 'var(--paper-1)',
          border: '1px solid var(--line-1)',
          borderRadius: 'var(--r-3)',
          padding: pads[padding],
          boxShadow: raised ? 'var(--shadow-2)' : 'none',
          position: 'relative',
          transition: 'border-color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out)',
          ...style,
        }}
        onMouseEnter={hover ? (e) => {
          e.currentTarget.style.borderColor = 'var(--line-2)'
          e.currentTarget.style.background = 'var(--paper-2)'
        } : undefined}
        onMouseLeave={hover ? (e) => {
          e.currentTarget.style.borderColor = 'var(--line-1)'
          e.currentTarget.style.background = 'var(--paper-1)'
        } : undefined}
        {...props}
      >
        {accent && (
          <div style={{ position: 'absolute', top: 0, left: 12, right: 12, height: 2, background: 'var(--accent)', borderRadius: '0 0 2px 2px' }} />
        )}
        {children}
      </div>
    )
  }
)
Card.displayName = 'Card'

export function CardSkeleton() {
  return (
    <div style={{ background: 'var(--paper-1)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: 16 }}>
      <div className="skel" style={{ height: 12, width: '60%', marginBottom: 8 }} />
      <div className="skel" style={{ height: 12, width: '80%', marginBottom: 8 }} />
      <div className="skel" style={{ height: 12, width: '40%' }} />
    </div>
  )
}
