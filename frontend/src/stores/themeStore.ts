import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type Theme = 'light' | 'dark'
type Density = 'compact' | 'comfortable' | 'spacious'

interface ThemeState {
  theme: Theme
  density: Density
  setTheme: (t: Theme) => void
  toggleTheme: () => void
  setDensity: (d: Density) => void
}

function applyTheme(theme: Theme, density: Density) {
  const root = document.documentElement
  root.setAttribute('data-theme', theme)
  if (density === 'comfortable') {
    root.removeAttribute('data-density')
  } else {
    root.setAttribute('data-density', density)
  }
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      theme: 'light',
      density: 'comfortable',
      setTheme: (theme) => {
        set({ theme })
        applyTheme(theme, get().density)
      },
      toggleTheme: () => {
        const next = get().theme === 'light' ? 'dark' : 'light'
        set({ theme: next })
        applyTheme(next, get().density)
      },
      setDensity: (density) => {
        set({ density })
        applyTheme(get().theme, density)
      },
    }),
    {
      name: 'atelier-theme',
      onRehydrateStorage: () => (state) => {
        if (state) applyTheme(state.theme, state.density)
      },
    }
  )
)
