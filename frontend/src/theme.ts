import { useCallback, useState } from 'react'

// Theme: 'light' | 'dark', persisted to localStorage, prefers-color-scheme
// default. index.html applies the initial theme before first paint; this
// hook only manages toggling afterwards.

const THEME_KEY = 'theme'

function currentTheme(): 'light' | 'dark' {
  return document.documentElement.getAttribute('data-theme') === 'dark'
    ? 'dark'
    : 'light'
}

export function useTheme(): { theme: 'light' | 'dark'; toggleTheme: () => void } {
  const [theme, setTheme] = useState<'light' | 'dark'>(currentTheme)

  const toggleTheme = useCallback(() => {
    const next = currentTheme() === 'dark' ? 'light' : 'dark'
    if (next === 'dark') {
      document.documentElement.setAttribute('data-theme', 'dark')
    } else {
      document.documentElement.removeAttribute('data-theme')
    }
    localStorage.setItem(THEME_KEY, next)
    setTheme(next)
  }, [])

  return { theme, toggleTheme }
}
