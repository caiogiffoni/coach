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
  LibraryWorkout,
  LibraryWorkoutInput,
  LibraryWorkoutPush,
  LibraryWorkoutSummary,
  LoginResult,
  Profile,
  ProfileUpdate,
  PushReport,
  SyncReport,
  TokenResponse,
  UploadReport,
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
  return handleResponse<T>(res)
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
  upload: async (files: FileList) => {
    const form = new FormData()
    for (let i = 0; i < files.length; i++) {
      form.append('files', files[i])
    }
    const headers: Record<string, string> = {}
    const token = getToken()
    if (token) headers['Authorization'] = `Bearer ${token}`

    const res = await fetch('/api/ingestion/upload', {
      method: 'POST',
      headers,
      body: form,
    })
    return handleResponse<UploadReport>(res)
  },
  sync: (days = 14) =>
    request<SyncReport>('/ingestion/sync', { method: 'POST', body: { days } }),
}

/** Garmin auth failures come back as 401 but must not end the app session. */
function garminAuthFailureMessage(errorData: unknown): string | null {
  const data = errorData as { needs_mfa?: boolean; detail?: unknown } | null
  if (data?.needs_mfa) return JSON.stringify(data)
  // backend/app/garmin/push.py _require_login raises 401 "MFA required: …" /
  // "Garmin login failed: …" for both the week and the library-workout push.
  const detail = data?.detail
  if (typeof detail === 'string' && /^(MFA required|Garmin login failed)/.test(detail)) return detail
  return null
}

function errorDetailMessage(status: number, errorData: unknown): string {
  const data = errorData as {
    detail?: string | Array<{ loc?: Array<string | number>; msg?: string }>
  } | null
  if (typeof data?.detail === 'string') return data.detail
  if (Array.isArray(data?.detail) && data.detail.length > 0) {
    // FastAPI 422 validation errors: [{loc, msg, ...}]; drop the "body" root.
    return data.detail
      .map((e) => {
        const where = (e.loc ?? []).filter((part) => part !== 'body').join('.')
        return where ? `${where}: ${e.msg ?? ''}` : (e.msg ?? '')
      })
      .join('; ')
  }
  return `Request failed (${status})`
}

async function handleResponse<T>(res: Response): Promise<T> {
  let errorData: unknown = null
  if (!res.ok) {
    errorData = await res.json().catch(() => null)
  }

  if (res.status === 401 && getToken()) {
    const garminMessage = garminAuthFailureMessage(errorData)
    if (garminMessage !== null) throw new ApiError(401, garminMessage)
    // Expired/invalid session: drop the token and bounce to login.
    clearToken()
    window.location.assign('/login')
    throw new ApiError(401, 'Session expired')
  }

  if (!res.ok) throw new ApiError(res.status, errorDetailMessage(res.status, errorData))
  // 204 No Content (e.g. DELETE) has no JSON body.
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
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

// --- Workout library ------------------------------------------------------------

export const workoutLibrary = {
  list: () => request<LibraryWorkoutSummary[]>('/workouts'),
  get: (id: number) => request<LibraryWorkout>(`/workouts/${id}`),
  create: (body: LibraryWorkoutInput) =>
    request<LibraryWorkout>('/workouts', { method: 'POST', body }),
  update: (id: number, body: LibraryWorkoutInput) =>
    request<LibraryWorkout>(`/workouts/${id}`, { method: 'PUT', body }),
  remove: (id: number) => request<void>(`/workouts/${id}`, { method: 'DELETE' }),
  duplicate: (id: number) =>
    request<LibraryWorkout>(`/workouts/${id}/duplicate`, { method: 'POST' }),
  push: (id: number, date: string) =>
    request<LibraryWorkoutPush>(`/workouts/${id}/push`, { method: 'POST', body: { date } }),
}
