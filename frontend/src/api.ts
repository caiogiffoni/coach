// Fetch wrapper: baseURL /api (Vite dev proxy → :8000), attaches the Bearer
// token from localStorage, throws typed ApiError on 4xx/5xx, redirects to
// /login on 401.

import type {
  AuthStatus,
  GenerateWeekRequest,
  ImportReport,
  Profile,
  ProfileUpdate,
  TokenResponse,
  UserResponse,
  WeekPlan,
  WeekPlanSummary,
  ZonesResponse,
} from './types'

const TOKEN_KEY = 'token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'

  const res = await fetch(`/api${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  })

  if (res.status === 401 && getToken()) {
    // Expired/invalid session: drop the token and bounce to login.
    clearToken()
    window.location.assign('/login')
    throw new ApiError(401, 'Session expired')
  }

  if (!res.ok) {
    let message = `Request failed (${res.status})`
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') {
        message = data.detail
      } else if (Array.isArray(data.detail) && data.detail.length > 0) {
        // FastAPI 422 validation errors: [{loc, msg, ...}]
        message = data.detail.map((e: { msg?: string }) => e.msg ?? '').join('; ')
      }
    } catch {
      // non-JSON error body: keep the generic message
    }
    throw new ApiError(res.status, message)
  }

  return (await res.json()) as T
}

// --- Auth -------------------------------------------------------------------

export const auth = {
  status: () => request<AuthStatus>('/auth/status'),
  register: (email: string, password: string) =>
    request<TokenResponse>('/auth/register', {
      method: 'POST',
      body: { email, password },
    }),
  login: (email: string, password: string) =>
    request<TokenResponse>('/auth/login', {
      method: 'POST',
      body: { email, password },
    }),
  me: () => request<UserResponse>('/auth/me'),
}

// --- Profile ----------------------------------------------------------------

export const profile = {
  get: () => request<Profile>('/profile'),
  update: (body: ProfileUpdate) =>
    request<Profile>('/profile', { method: 'PUT', body }),
  seed: () => request<Profile>('/profile/seed', { method: 'POST' }),
  zones: () => request<ZonesResponse>('/profile/zones'),
}

// --- Coaching -----------------------------------------------------------------

export const coaching = {
  generateWeek: (body: GenerateWeekRequest) =>
    request<WeekPlan>('/coaching/weeks/generate', { method: 'POST', body }),
  listWeeks: () => request<WeekPlanSummary[]>('/coaching/weeks'),
  getWeek: (weekStart: string) => request<WeekPlan>(`/coaching/weeks/${weekStart}`),
  approveWeek: (weekStart: string) =>
    request<WeekPlan>(`/coaching/weeks/${weekStart}/approve`, { method: 'POST' }),
}

// --- Ingestion ------------------------------------------------------------------

export const ingestion = {
  import: (path: string) =>
    request<ImportReport>('/ingestion/import', { method: 'POST', body: { path } }),
}
