import { create } from 'zustand'

const STORAGE_KEY = 'theme_color'
const DEFAULT_COLOR = '#4f46e5'

interface ThemeState {
  color: string
  setColor: (color: string) => void
}

function loadInitial(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) || DEFAULT_COLOR
  } catch {
    return DEFAULT_COLOR
  }
}

export const useThemeStore = create<ThemeState>((set) => ({
  color: loadInitial(),
  setColor: (color) => {
    try {
      localStorage.setItem(STORAGE_KEY, color)
    } catch {
      /* ignore */
    }
    set({ color })
  },
}))
