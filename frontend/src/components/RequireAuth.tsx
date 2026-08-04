import type { ReactNode } from 'react'
import { Navigate } from 'react-router'
import { getToken } from '../api'
import { Nav } from './Nav'

/** Auth guard: redirects to /login without a token; renders nav + page. */
export function RequireAuth({ children }: { children: ReactNode }) {
  if (!getToken()) {
    return <Navigate to="/login" replace />
  }
  return (
    <>
      <Nav />
      <main className="container">{children}</main>
    </>
  )
}
