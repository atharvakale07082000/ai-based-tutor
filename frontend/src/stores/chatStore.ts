import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { AgentStep } from '@/components/agents/StreamTrace'
import type { TimelineStep } from '@/hooks/useAgentTimeline'

/**
 * Client-side history for the Ask Atelier chat. There is no server-side thread
 * store, so each conversation ("chat") is kept here and persisted to
 * localStorage, letting the learner keep several chats and switch between them
 * from the history drawer.
 */

export interface ChatAction {
  kind: string
  payload: Record<string, unknown>
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  routing?: { agent: string; reason: string }
  steps: AgentStep[]
  timeline: TimelineStep[]
  actions: ChatAction[]
}

export type ChatStatus = 'running' | 'done' | 'error'

export interface ChatThread {
  id: string
  title: string
  messages: ChatMessage[]
  createdAt: number
  updatedAt: number
  status: ChatStatus
}

const MAX_THREADS = 40

function deriveTitle(messages: ChatMessage[]): string {
  const firstUser = messages.find((m) => m.role === 'user' && m.content.trim())
  const t = firstUser?.content.trim() ?? ''
  if (!t) return 'New chat'
  return t.length > 48 ? t.slice(0, 48) + '…' : t
}

// Persist only what the history UI needs — drop tool args/results (which carry
// internal ids) and the transient streaming flag before writing to disk.
function slim(messages: ChatMessage[]): ChatMessage[] {
  return messages.map((m) => ({
    ...m,
    streaming: false,
    steps: m.steps.map((s: AgentStep) => ({
      step: s.step,
      thought: s.thought,
      toolCall: s.toolCall ? { name: s.toolCall.name, args: {} } : undefined,
      toolResult: s.toolResult ? { result: null, latency_ms: s.toolResult.latency_ms } : undefined,
    })),
  }))
}

interface ChatState {
  threads: ChatThread[]
  activeId: string | null
  /** Create a fresh empty chat and make it active. Returns its id. */
  newThread: () => string
  setActive: (id: string) => void
  /** Upsert the active chat's messages + status; retitles from the first user turn. */
  saveActive: (messages: ChatMessage[], status: ChatStatus) => void
  deleteThread: (id: string) => void
  clearAll: () => void
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      threads: [],
      activeId: null,

      newThread: () => {
        const id = crypto.randomUUID()
        const now = Date.now()
        const thread: ChatThread = {
          id,
          title: 'New chat',
          messages: [],
          createdAt: now,
          updatedAt: now,
          status: 'done',
        }
        set((s) => ({ threads: [thread, ...s.threads].slice(0, MAX_THREADS), activeId: id }))
        return id
      },

      setActive: (id) => set({ activeId: id }),

      saveActive: (messages, status) =>
        set((s) => {
          if (!s.activeId) return {}
          const now = Date.now()
          const threads = s.threads
            .map((t) =>
              t.id === s.activeId
                ? { ...t, messages: slim(messages), title: deriveTitle(messages), updatedAt: now, status }
                : t,
            )
            .sort((a, b) => b.updatedAt - a.updatedAt)
          return { threads }
        }),

      deleteThread: (id) =>
        set((s) => {
          const threads = s.threads.filter((t) => t.id !== id)
          const activeId = s.activeId === id ? (threads[0]?.id ?? null) : s.activeId
          return { threads, activeId }
        }),

      clearAll: () => set({ threads: [], activeId: null }),
    }),
    {
      name: 'atelier-chats',
      partialize: (s) => ({ threads: s.threads, activeId: s.activeId }),
    },
  ),
)
