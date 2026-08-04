import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { ApiError, auth, setToken } from '../api'

export function Login() {
  const navigate = useNavigate()
  const [registrationOpen, setRegistrationOpen] = useState<boolean | null>(null)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    auth
      .status()
      .then((s) => setRegistrationOpen(s.registration_open))
      .catch(() => setRegistrationOpen(false))
  }, [])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const { token } = registrationOpen
        ? await auth.register(email, password)
        : await auth.login(email, password)
      setToken(token)
      navigate('/week', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Request failed')
    } finally {
      setBusy(false)
    }
  }

  if (registrationOpen === null) {
    return (
      <div className="auth-layout">
        <p className="muted">Loading…</p>
      </div>
    )
  }

  return (
    <div className="auth-layout">
      <div className="card auth-card">
        <h1 className="card-title">
          {registrationOpen ? 'Create your account' : 'Sign in'}
        </h1>
        <form onSubmit={onSubmit}>
          <div className="field">
            <label className="field-label" htmlFor="email">
              Email
            </label>
            <input
              id="email"
              className="input"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              className="input"
              type="password"
              required
              minLength={registrationOpen ? 8 : undefined}
              autoComplete={registrationOpen ? 'new-password' : 'current-password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {registrationOpen && (
              <p className="field-hint">At least 8 characters.</p>
            )}
          </div>
          {error && (
            <div className="banner banner-danger" role="alert">
              {error}
            </div>
          )}
          <button
            type="submit"
            className="button button-primary"
            style={{ width: '100%' }}
            disabled={busy}
          >
            {registrationOpen ? 'Create account' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
