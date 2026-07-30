// Fetch wrapper: baseURL /api (Vite dev proxy → :8000), attaches the Bearer
// token from localStorage, throws typed ApiError on 4xx/5xx, redirects to
// /login on 401.

import type {
  AuthStatus,
  DayGuardResult,
  GarminStatus,
  GenerateWeekRequest,
  ImportReport,
  IngestionStatus,
  LoginResult,
  Profile,
  ProfileUpdate,
  PushReport,
  SyncReport,
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

  let errorData: unknown = null
  if (!res.ok) {
    errorData = await res.json().catch(() => null)
  }

  if (res.status === 401 && getToken()) {
    // Garmin MFA challenges are returned as 401 with needs_mfa: do not bounce.
    const data = errorData as { needs_mfa?: boolean } | null
    if (data?.needs_mfa) {
      throw new ApiError(401, JSON.stringify(data))
    }
    // Expired/invalid session: drop the token and bounce to login.
    clearToken()
    window.location.assign('/login')
    throw new ApiError(401, 'Session expired')
  }

  if (!res.ok) {
    let message = `Request failed (${res.status})`
    const data = errorData as { detail?: string | Array<{ msg?: string }> } | null
    if (typeof data?.detail === 'string') {
      message = data.detail
    } else if (Array.isArray(data?.detail) && data.detail.length > 0) {
      // FastAPI 422 validation errors: [{loc, msg, ...}]
      message = data.detail.map((e) => e.msg ?? '').join('; ')
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

// --- Ingestion ------------------------------------------------------------------

export const ingestion = {
  status: () => request<IngestionStatus>('/ingestion/status'),
  import: (path: string) =>
    request<ImportReport>('/ingestion/import', { method: 'POST', body: { path } }),
  sync: (days = 14) =>
    request<SyncReport>('/ingestion/sync', { method: 'POST', body: { days } }),
}

// --- Coaching -----------------------------------------------------------------

export const coaching = {
  generateWeek: (body: GenerateWeekRequest) =>
    request<WeekPlan>('/coaching/weeks/generate', { method: 'POST', body }),
  listWeeks: () => request<WeekPlanSummary[]>('/coaching/weeks'),
  getWeek: (weekStart: string) => request<WeekPlan>(`/coaching/weeks/${weekStart}`),
  approveWeek: (weekStart: string) =>
    request<WeekPlan>(`/coaching/weeks/${weekStart}/approve`, { method: 'POST' }),
  guard: (weekStart: string, date: string, days?: number[]) => {
    const params = new URLSearchParams({ week_start: weekStart, date })
    if (days && days.length > 0) params.set('days', days.join(','))
    return request<DayGuardResult>(`/coaching/guard?${params.toString()}`)
  },
}

// --- Garmin -------------------------------------------------------------------

export const garmin = {
  status: () => request<GarminStatus>('/garmin/status'),
  login: (mfa_code?: string) =>
    request<LoginResult>('/garmin/login', {
      method: 'POST',
      body: { mfa_code: mfa_code ?? null },
    }),
  push: (week_start: string) =>
    request<PushReport>(`/garmin/push?week_start=${week_start}`, { method: 'POST' }),
}
