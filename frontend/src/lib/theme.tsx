/**
 * Theme provider — dark / light con persistencia en localStorage.
 *
 * Estrategia:
 *  - El "dark" es el default (sin clase). El "light" se activa agregando
 *    `.light` al elemento <html>. Las CSS variables en index.css cambian
 *    automáticamente y, como tailwind.config las consume vía rgb(var(...)),
 *    todas las utilidades (`bg-surface`, `text-text-primary`, etc.) reflejan
 *    el cambio sin tocar componentes.
 *  - Para evitar FOUC, hay un <script> en index.html que aplica `.light`
 *    sincrónicamente antes de montar React.
 */
import {
  createContext, useContext, useEffect, useState, useCallback, type ReactNode,
} from 'react'

export type Theme = 'dark' | 'light'

interface ThemeCtx {
  theme: Theme
  setTheme: (t: Theme) => void
  toggleTheme: () => void
}

const ThemeContext = createContext<ThemeCtx>(null!)

const STORAGE_KEY = 'theme'

function readInitialTheme(): Theme {
  if (typeof document === 'undefined') return 'dark'
  return document.documentElement.classList.contains('light') ? 'light' : 'dark'
}

function applyTheme(theme: Theme) {
  const root = document.documentElement
  if (theme === 'light') root.classList.add('light')
  else                   root.classList.remove('light')
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(readInitialTheme)

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t)
    try { localStorage.setItem(STORAGE_KEY, t) } catch {}
    applyTheme(t)
  }, [])

  const toggleTheme = useCallback(() => {
    setTheme(theme === 'dark' ? 'light' : 'dark')
  }, [theme, setTheme])

  // Sincroniza si otra pestaña cambia el tema
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== STORAGE_KEY || !e.newValue) return
      const t = e.newValue as Theme
      if (t === 'dark' || t === 'light') {
        setThemeState(t)
        applyTheme(t)
      }
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  return useContext(ThemeContext)
}
