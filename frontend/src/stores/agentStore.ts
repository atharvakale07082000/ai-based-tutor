import { create } from 'zustand'

export interface AgentStatus {
  status: 'active' | 'processing' | 'idle' | 'error'
  lastPing: number
  latencyMs: number
}

export interface HFModelStatus {
  status: 'ok' | 'loading' | 'error'
  lastUsed: number | null
  latencyMs: number | null
}

interface AgentStoreState {
  agents: {
    curriculum: AgentStatus
    quiz: AgentStatus
    progress: AgentStatus
    doubt: AgentStatus
  }
  hfModels: Record<string, HFModelStatus>
  tokenUsage: Record<string, number>

  updateAgentStatus: (agent: keyof AgentStoreState['agents'], status: Partial<AgentStatus>) => void
  updateHFModel: (modelKey: string, status: Partial<HFModelStatus>) => void
  incrementTokenUsage: (modelKey: string, tokens: number) => void
  setHFModels: (models: Record<string, HFModelStatus>) => void
}

const defaultAgentStatus: AgentStatus = {
  status: 'active',
  lastPing: Date.now(),
  latencyMs: 0,
}

const defaultHFModels: Record<string, HFModelStatus> = {
  DOUBT_SOLVER: { status: 'ok', lastUsed: null, latencyMs: null },
  QUIZ_GENERATOR: { status: 'ok', lastUsed: null, latencyMs: null },
  TOPIC_CLASSIFIER: { status: 'ok', lastUsed: null, latencyMs: null },
  DIFFICULTY_SCORER: { status: 'ok', lastUsed: null, latencyMs: null },
  EMBEDDINGS: { status: 'ok', lastUsed: null, latencyMs: null },
  SPEECH_TO_TEXT: { status: 'ok', lastUsed: null, latencyMs: null },
  SENTIMENT: { status: 'ok', lastUsed: null, latencyMs: null },
  IMAGE_CAPTIONER: { status: 'ok', lastUsed: null, latencyMs: null },
}

export const useAgentStore = create<AgentStoreState>((set) => ({
  agents: {
    curriculum: { ...defaultAgentStatus },
    quiz: { ...defaultAgentStatus },
    progress: { ...defaultAgentStatus },
    doubt: { ...defaultAgentStatus },
  },
  hfModels: defaultHFModels,
  tokenUsage: {},

  updateAgentStatus: (agent, status) =>
    set((state) => ({
      agents: {
        ...state.agents,
        [agent]: { ...state.agents[agent], ...status, lastPing: Date.now() },
      },
    })),

  updateHFModel: (modelKey, status) =>
    set((state) => ({
      hfModels: {
        ...state.hfModels,
        [modelKey]: { ...state.hfModels[modelKey], ...status },
      },
    })),

  incrementTokenUsage: (modelKey, tokens) =>
    set((state) => ({
      tokenUsage: {
        ...state.tokenUsage,
        [modelKey]: (state.tokenUsage[modelKey] ?? 0) + tokens,
      },
    })),

  setHFModels: (models) =>
    set({ hfModels: models }),
}))
