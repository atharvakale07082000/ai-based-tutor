import { useAgentSocket } from '@/hooks/useAgentSocket'
import { useLearnerStore } from '@/stores/learnerStore'

interface PageWrapperProps {
  children: React.ReactNode
}

// Thin wrapper that just wires up the socket — shell layout lives in App.tsx
export function PageWrapper({ children }: PageWrapperProps) {
  const learnerId = useLearnerStore((s) => s.id ?? undefined)
  useAgentSocket({ learnerId })
  return <>{children}</>
}

// Keep legacy export for old imports
export const pageVariants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit:    { opacity: 0, y: -4 },
}
