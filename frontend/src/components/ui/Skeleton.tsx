import type { HTMLAttributes } from 'react'

interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  w?: string | number
  h?: string | number
  r?: number
  lines?: number
  circle?: boolean
}

export function Skeleton({ w = '100%', h = 12, r = 5, className = '', style = {}, lines, circle, ...props }: SkeletonProps) {
  if (lines) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {Array.from({ length: lines }).map((_, i) => (
          <div key={i} className="skel" style={{ height: 12, width: i === lines - 1 ? '75%' : '100%', borderRadius: r }} />
        ))}
      </div>
    )
  }
  return (
    <div
      className={`skel ${className}`}
      style={{ width: w, height: h, borderRadius: circle ? '50%' : r, ...style }}
      {...props}
    />
  )
}

export function CardSkeleton() {
  return (
    <div style={{ background: 'var(--paper-1)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: 16 }}>
      <Skeleton h={12} w="60%" style={{ marginBottom: 8 }} />
      <Skeleton h={12} w="80%" style={{ marginBottom: 8 }} />
      <Skeleton h={12} w="40%" />
    </div>
  )
}

export function ChatBubbleSkeleton({ isUser = false }: { isUser?: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start' }}>
      <div style={{ maxWidth: 400 }}>
        <Skeleton h={12} w={260} style={{ marginBottom: 6 }} />
        <Skeleton h={12} w={200} style={{ marginBottom: 6 }} />
        <Skeleton h={12} w={220} />
      </div>
    </div>
  )
}
