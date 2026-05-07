import { motion } from 'framer-motion'
import { TopBar } from './TopBar'
import { AgentStatusBar } from '@/components/agents/AgentStatusBar'
import { useAgentSocket } from '@/hooks/useAgentSocket'
import { useLearnerStore } from '@/stores/learnerStore'

interface PageWrapperProps {
  children: React.ReactNode
  showAgentBar?: boolean
  fullscreen?: boolean
}

const prefersReducedMotion =
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

export const pageVariants = {
  initial: prefersReducedMotion ? {} : { opacity: 0, y: 16 },
  animate: { opacity: 1, y: 0 },
  exit: prefersReducedMotion ? {} : { opacity: 0, y: -8 },
}

export function PageWrapper({ children, showAgentBar = true, fullscreen = false }: PageWrapperProps) {
  const learnerId = useLearnerStore((s) => s.id ?? undefined)
  useAgentSocket({ learnerId })

  return (
    <div className="min-h-screen bg-ink flex flex-col">
      {!fullscreen && <TopBar />}
      {!fullscreen && showAgentBar && <AgentStatusBar />}
      <motion.main
        variants={pageVariants}
        initial="initial"
        animate="animate"
        exit="exit"
        transition={{ duration: 0.28, ease: 'easeOut' }}
        className={fullscreen ? 'flex-1 flex flex-col' : 'flex-1 overflow-auto'}
      >
        {children}
      </motion.main>
    </div>
  )
}
