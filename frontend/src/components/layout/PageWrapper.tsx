import { useLocation } from 'react-router-dom'
import { useAgentSocket } from '@/hooks/useAgentSocket'
import { useLearnerStore } from '@/stores/learnerStore'

interface PageWrapperProps {
  children: React.ReactNode
}

// Thin wrapper that wires up the socket and plays the page-enter transition — shell layout lives in App.tsx
export function PageWrapper({ children }: PageWrapperProps) {
  const learnerId = useLearnerStore((s) => s.id ?? undefined)
  const location = useLocation()
  useAgentSocket({ learnerId })
  return (
    <div key={location.pathname} className="page-enter" style={{ height: '100%' }}>
      {children}
    </div>
  )
}

// Keep legacy export for old imports
export const pageVariants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit:    { opacity: 0, y: -4 },
}
