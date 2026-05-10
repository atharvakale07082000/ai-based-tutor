import { create } from 'zustand'

interface CmdkState {
  open: boolean
  query: string
  setOpen: (open: boolean) => void
  setQuery: (query: string) => void
  toggle: () => void
}

export const useCmdkStore = create<CmdkState>()((set, get) => ({
  open: false,
  query: '',
  setOpen: (open) => set({ open, query: open ? get().query : '' }),
  setQuery: (query) => set({ query }),
  toggle: () => set((s) => ({ open: !s.open, query: s.open ? '' : s.query })),
}))
