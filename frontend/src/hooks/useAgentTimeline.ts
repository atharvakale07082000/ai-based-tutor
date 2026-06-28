import { useState, useCallback } from 'react'
import type { StepEvent } from '@/lib/api'

export type StepStatus = 'active' | 'done' | 'error'

export interface TimelineStep {
  id: string
  label: string
  status: StepStatus
}

/**
 * Folds streamed `step` events into an ordered timeline.
 *
 * - A new step id appends to the timeline (shows pending/active).
 * - A known step id updates its status in place (active → done turns it green).
 * - `reset()` clears the timeline before a new run.
 */
export function useAgentTimeline() {
  const [steps, setSteps] = useState<TimelineStep[]>([])

  const applyStep = useCallback((ev: Pick<StepEvent, 'id' | 'label' | 'status'>) => {
    setSteps((prev) => {
      const idx = prev.findIndex((s) => s.id === ev.id)
      if (idx === -1) {
        return [...prev, { id: ev.id, label: ev.label, status: ev.status }]
      }
      const next = [...prev]
      next[idx] = { ...next[idx], label: ev.label || next[idx].label, status: ev.status }
      return next
    })
  }, [])

  const reset = useCallback(() => setSteps([]), [])

  return { steps, applyStep, reset }
}
