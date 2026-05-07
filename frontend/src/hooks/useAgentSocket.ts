import { useEffect, useCallback } from 'react'
import { connectSocket, disconnectSocket, WS_EVENTS } from '@/lib/socket'
import { useAgentStore } from '@/stores/agentStore'
import { useLearnerStore } from '@/stores/learnerStore'
import toast from 'react-hot-toast'

interface AgentStatusEvent {
  agent: 'curriculum' | 'quiz' | 'progress' | 'doubt'
  status: 'active' | 'processing' | 'idle' | 'error'
  latency_ms: number
}

interface CurriculumUpdateEvent {
  items: Array<{ domain: string; subtopic: string; priority: number }>
  version: number
}

interface QuizReadyEvent {
  quiz_id: string
  topic: string
}

interface ProgressUpdateEvent {
  topic: string
  new_elo: number
  old_elo: number
}

interface DoubtStreamEvent {
  token: string
  session_id: string
}

interface UseAgentSocketOptions {
  learnerId?: string
  onDoubtToken?: (token: string, sessionId: string) => void
  onQuizReady?: (quizId: string, topic: string) => void
}

export function useAgentSocket(options: UseAgentSocketOptions = {}) {
  const { learnerId, onDoubtToken, onQuizReady } = options
  const { updateAgentStatus } = useAgentStore()
  const { updateProficiency, setLearner } = useLearnerStore()

  useEffect(() => {
    const socket = connectSocket(learnerId)

    socket.on(WS_EVENTS.AGENT_STATUS, (data: AgentStatusEvent) => {
      updateAgentStatus(data.agent, {
        status: data.status,
        latencyMs: data.latency_ms,
        lastPing: Date.now(),
      })
    })

    socket.on(WS_EVENTS.CURRICULUM_UPDATE, (data: CurriculumUpdateEvent) => {
      setLearner({ curriculumVersion: data.version })
      toast.success('Your curriculum has been updated by the Planner agent!', { icon: '🗺️' })
    })

    socket.on(WS_EVENTS.QUIZ_READY, (data: QuizReadyEvent) => {
      onQuizReady?.(data.quiz_id, data.topic)
      toast.success(`Quiz ready: ${data.topic}`, { icon: '📝' })
    })

    socket.on(WS_EVENTS.PROGRESS_UPDATE, (data: ProgressUpdateEvent) => {
      updateProficiency(data.topic, data.new_elo)
    })

    socket.on(WS_EVENTS.DOUBT_STREAM, (data: DoubtStreamEvent) => {
      onDoubtToken?.(data.token, data.session_id)
    })

    return () => {
      socket.off(WS_EVENTS.AGENT_STATUS)
      socket.off(WS_EVENTS.CURRICULUM_UPDATE)
      socket.off(WS_EVENTS.QUIZ_READY)
      socket.off(WS_EVENTS.PROGRESS_UPDATE)
      socket.off(WS_EVENTS.DOUBT_STREAM)
    }
  }, [learnerId, onDoubtToken, onQuizReady, updateAgentStatus, updateProficiency, setLearner])

  const disconnect = useCallback(() => {
    disconnectSocket()
  }, [])

  return { disconnect }
}

export default useAgentSocket
