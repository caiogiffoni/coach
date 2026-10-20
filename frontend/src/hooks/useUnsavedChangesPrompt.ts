import { useEffect } from 'react'

/**
 * Ask the browser to confirm leaving the page while there are unsaved edits.
 * (BrowserRouter has no data-router blocker, so in-app links aren't blocked.)
 *
 * Example: `useUnsavedChangesPrompt(dirty)`
 */
export function useUnsavedChangesPrompt(dirty: boolean): void {
  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])
}
