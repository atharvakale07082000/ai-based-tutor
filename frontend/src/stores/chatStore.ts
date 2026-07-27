import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/**
 * Client-side history for the Ask Atelier chat. There is no server-side thread
 * store, so each conversation ("chat") is kept here and persisted to
 * localStorage, letting the learner keep several chats and switch between them
 * from the history drawer.
 *
 * Every field added after the first release is optional so that threads written
 * by an older build rehydrate without crashing (see `migrate` below).
 */

export interface ChatAction {
  kind: string
  payload: Record<string, unknown>
}

/** How a turn came to replace an earlier one. Drives the honesty note in the UI. */
export type ChatRevision = 'regenerated' | 'edited'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  /** The agent's live reasoning ("how I'm thinking through this"), streamed in. */
  reasoning: string
  actions: ChatAction[]
  /** The learner pressed Stop — whatever streamed is kept, but it is a partial answer. */
  stopped?: boolean
  /** Learner-facing failure text for a turn that never completed. Enables Retry. */
  error?: string
  /** Set when this turn replaced an earlier one (regenerate / edit & resend). */
  revised?: ChatRevision
}

export type ChatStatus = 'running' | 'done' | 'error'

export interface ChatThread {
  id: string
  title: string
  messages: ChatMessage[]
  createdAt: number
  updatedAt: number
  status: ChatStatus
  /** True once the learner renamed the chat by hand — auto-titling stops touching it. */
  titlePinned?: boolean
}

const MAX_THREADS = 40
const MAX_TITLE = 44

export const DEFAULT_TITLE = 'New chat'

/**
 * Build a short, human title from the first user turn. Deliberately local and
 * instant — no LLM call — so the sidebar labels itself the moment a chat starts.
 */
export function deriveTitle(messages: ChatMessage[] | undefined): string {
  const firstUser = (messages ?? []).find((m) => m?.role === 'user' && m.content?.trim())
  const raw = firstUser?.content ?? ''
  const cleaned = raw
    .replace(/```[\s\S]*?```/g, ' ') // fenced code blocks carry no title signal
    .replace(/`([^`]*)`/g, '$1')
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1') // links/images → their label
    .replace(/^\s{0,3}#{1,6}\s+/gm, '') // heading markers
    .replace(/^\s{0,3}(?:[-*+]|\d+[.)])\s+/gm, '') // list markers
    .replace(/[*_~>]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  if (!cleaned) return DEFAULT_TITLE

  // Prefer the first sentence when it already reads like a label. (No lookbehind —
  // it is a parse-time syntax error on older Safari, which would kill the bundle.)
  // The trailing (?=\s|$) keeps "np.einsum" / "3.5" from reading as a sentence end.
  const sentence = cleaned.match(/^[^.?!]+[.?!](?=\s|$)/)?.[0] ?? cleaned
  const base = sentence.length >= 12 && sentence.length <= MAX_TITLE ? sentence : cleaned

  let title = base
  if (title.length > MAX_TITLE) {
    const cut = title.slice(0, MAX_TITLE)
    const lastSpace = cut.lastIndexOf(' ')
    title = (lastSpace > MAX_TITLE * 0.6 ? cut.slice(0, lastSpace) : cut).trimEnd() + '…'
  }
  title = title.replace(/[\s,;:]+…$/, '…').replace(/[.,;:\s]+$/, '')
  if (!title) return DEFAULT_TITLE
  return title.charAt(0).toUpperCase() + title.slice(1)
}

/** Trim a hand-typed name to something the sidebar can render on one line. */
export function normalizeTitle(input: string): string {
  const t = input.replace(/\s+/g, ' ').trim()
  if (!t) return ''
  return t.length > MAX_TITLE ? t.slice(0, MAX_TITLE).trimEnd() : t
}

// Persist only what the history UI needs — keep the reasoning narrative and answer,
// drop the transient streaming flag before writing to disk.
function slim(messages: ChatMessage[]): ChatMessage[] {
  return messages.map((m) => ({ ...m, streaming: false }))
}

interface ChatState {
  threads: ChatThread[]
  activeId: string | null
  /** Create a fresh empty chat and make it active. Returns its id. */
  newThread: () => string
  setActive: (id: string) => void
  /** Upsert the active chat's messages + status; retitles from the first user turn. */
  saveActive: (messages: ChatMessage[], status: ChatStatus) => void
  /** Hand-rename a chat. An empty name clears the pin and reverts to the auto title. */
  renameThread: (id: string, title: string) => void
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
          title: DEFAULT_TITLE,
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
                ? {
                    ...t,
                    messages: slim(messages),
                    // A hand-picked name always wins over the derived one.
                    title: t.titlePinned ? t.title : deriveTitle(messages),
                    updatedAt: now,
                    status,
                  }
                : t,
            )
            .sort((a, b) => b.updatedAt - a.updatedAt)
          return { threads }
        }),

      renameThread: (id, title) =>
        set((s) => {
          const next = normalizeTitle(title)
          return {
            threads: s.threads.map((t) =>
              t.id === id
                ? next
                  ? { ...t, title: next, titlePinned: true }
                  : { ...t, title: deriveTitle(t.messages), titlePinned: false }
                : t,
            ),
          }
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
      version: 1,
      partialize: (s) => ({ threads: s.threads, activeId: s.activeId }),
      // Threads persisted by earlier builds predate `titlePinned` / the message-level
      // stopped/error/revised flags. Normalize defensively so a stale or half-written
      // payload can never crash the page on boot.
      migrate: (persisted) => {
        const state = (persisted ?? {}) as Partial<{ threads: unknown; activeId: unknown }>
        const raw: unknown[] = Array.isArray(state.threads) ? state.threads : []
        const threads: ChatThread[] = raw
          .filter((t): t is Partial<ChatThread> => !!t && typeof t === 'object')
          .filter((t) => typeof t.id === 'string' && t.id.length > 0)
          .map((t) => {
            const messages = (Array.isArray(t.messages) ? t.messages : []).filter(
              (m): m is ChatMessage => !!m && typeof m === 'object' && typeof m.id === 'string',
            )
            return {
              id: t.id as string,
              title: typeof t.title === 'string' && t.title ? t.title : deriveTitle(messages),
              messages: messages.map((m) => ({
                ...m,
                content: typeof m.content === 'string' ? m.content : '',
                reasoning: typeof m.reasoning === 'string' ? m.reasoning : '',
                actions: Array.isArray(m.actions) ? m.actions : [],
                streaming: false,
              })),
              createdAt: typeof t.createdAt === 'number' ? t.createdAt : Date.now(),
              updatedAt: typeof t.updatedAt === 'number' ? t.updatedAt : Date.now(),
              status: t.status === 'running' || t.status === 'error' ? t.status : 'done',
              titlePinned: t.titlePinned === true,
            }
          })
        const activeId = typeof state.activeId === 'string' ? state.activeId : null
        return {
          threads,
          activeId: threads.some((t) => t.id === activeId) ? activeId : (threads[0]?.id ?? null),
        }
      },
    },
  ),
)
