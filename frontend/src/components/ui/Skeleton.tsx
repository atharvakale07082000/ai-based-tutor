interface SkeletonProps {
  className?: string
  lines?: number
  circle?: boolean
}

export function Skeleton({ className = '', lines, circle }: SkeletonProps) {
  const base = `animate-pulse bg-surface-2 rounded-lg ${circle ? 'rounded-full' : ''}`

  if (lines) {
    return (
      <div className="space-y-2">
        {Array.from({ length: lines }).map((_, i) => (
          <div
            key={i}
            className={`${base} h-4 ${i === lines - 1 ? 'w-3/4' : 'w-full'}`}
          />
        ))}
      </div>
    )
  }

  return <div className={`${base} ${className}`} />
}

export function CardSkeleton() {
  return (
    <div className="bg-surface-1 border border-surface-2 rounded-2xl p-6 space-y-4">
      <Skeleton className="h-5 w-2/3" />
      <Skeleton lines={3} />
      <div className="flex gap-2">
        <Skeleton className="h-6 w-16" />
        <Skeleton className="h-6 w-20" />
      </div>
    </div>
  )
}

export function ChatBubbleSkeleton({ isUser = false }: { isUser?: boolean }) {
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-md space-y-2 ${isUser ? 'items-end' : 'items-start'} flex flex-col`}>
        <Skeleton className="h-4 w-64" />
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-4 w-56" />
      </div>
    </div>
  )
}
