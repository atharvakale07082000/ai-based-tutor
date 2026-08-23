import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/**
 * `system` is the default and stamps NO `data-theme` attribute, which is what lets the
 * `prefers-color-scheme` block in index.css decide. The store previously defaulted to
 * `'light'` and always stamped an attribute, so a full dark palette existed but every
 * dark-OS visitor got the cream theme until they found the toggle.
 */
type Theme = 'system' | 'light' | 'dark'
type Density = 'compact' | 'comfortable' | 'spacious'

interface ThemeState {
  theme: Theme
  density: Density
  setTheme: (t: Theme) => void
  toggleTheme: () => void
  setDensity: (d: Density) => void
}

/** What the viewer is actually seeing right now, resolving `system` against the OS. */
export function resolveTheme(theme: Theme): 'light' | 'dark' {
  if (theme !== 'system') return theme
  return typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light'
}

function applyTheme(theme: Theme, density: Density) {
  const root = document.documentElement
  if (theme === 'system') {
    root.removeAttribute('data-theme')
  } else {
    root.setAttribute('data-theme', theme)
  }
  if (density === 'comfortable') {
    root.removeAttribute('data-density')
  } else {
    root.setAttribute('data-density', density)
  }
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      theme: 'system',
      density: 'comfortable',
      setTheme: (theme) => {
        set({ theme })
        applyTheme(theme, get().density)
      },
      // Toggling from `system` picks the opposite of what the viewer currently sees, so the
      // first click always visibly changes something.
      toggleTheme: () => {
        const next = resolveTheme(get().theme) === 'dark' ? 'light' : 'dark'
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
