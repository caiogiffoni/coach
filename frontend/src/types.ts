// API response types mirroring the backend schemas (backend/app/*/router.py).

export interface AuthStatus {
  registration_open: boolean
}

export interface TokenResponse {
  token: string
}

export interface UserResponse {
  email: string
}

export type GoalMode = 'race' | 'health'
export type RaceDistance = '5K' | '10K' | 'HM' | 'MARATHON'

export interface Profile {
  max_hr: number | null
  resting_hr: number | null
  threshold_pace_sec_per_km: number | null
  threshold_hr: number | null
  recent_race_distance_km: number | null
  recent_race_time_sec: number | null
  current_weekly_volume_km: number | null
  injury_history: string[]
  goal_mode: GoalMode
  goal_race_distance: RaceDistance | null
  goal_race_date: string | null // ISO date
  preferred_days: number[] // weekday ints, 0=Mon..6=Sun
  seeded_at: string | null
}

export interface ProfileUpdate {
  max_hr?: number | null
  resting_hr?: number | null
  threshold_pace_sec_per_km?: number | null
  threshold_hr?: number | null
  recent_race_distance_km?: number | null
  recent_race_time_sec?: number | null
  current_weekly_volume_km?: number | null
  injury_history?: string[] | null
  goal_mode?: GoalMode | null
  goal_race_distance?: RaceDistance | null
  goal_race_date?: string | null
  preferred_days?: number[] | null
}

export interface HrZone {
  zone: string
  min_bpm: number
  max_bpm: number
}

export interface PaceZone {
  name: string
  min_sec_per_km: number
  max_sec_per_km: number
}

export interface ZonesResponse {
  hr_zones: HrZone[] | null
  hr_source: 'lthr' | 'karvonen' | null
  pace_zones: PaceZone[] | null
  threshold_pace_sec_per_km: number | null
  threshold_pace_source: 'profile' | 'race_estimate' | null
  weekly_ceiling_km: number | null
  intensity_budget_km: number | null
}

export type StepType =
  | 'warmup'
  | 'main'
  | 'interval'
  | 'recovery'
  | 'cooldown'
  | 'rest'

export type Zone = 'Z1' | 'Z2' | 'Z3' | 'Z4' | 'Z5'

export interface WorkoutStep {
  type: StepType | string
  duration_min: number
  target_zone: Zone | string | null
  target_pace_min: number | null // faster bound, sec/km
  target_pace_max: number | null // slower bound, sec/km
  target_hr_min: number | null // bpm
  target_hr_max: number | null // bpm
}

export type SlotType = 'aerobic' | 'quality' | 'recovery' | 'long'

export interface Workout {
  id: number
  date: string // ISO date
  name: string
  sport: string
  duration_min: number
  description: string
  steps: WorkoutStep[]
  slot_type: SlotType | string
  status: string
}

export type WeekStatus = 'draft' | 'approved' | 'pushed'
export type WeekSource = 'llm' | 'fallback'

export interface WeekPlan {
  id: number
  week_start: string // Monday, ISO date
  goal_mode: string
  notes: string
  source: WeekSource | string
  status: WeekStatus | string
  validation_errors: string[]
  created_at: string
  workouts: Workout[]
}

export interface WeekPlanSummary {
  week_start: string
  status: string
  source: string
}

export interface GenerateWeekRequest {
  week: string // any date in the target week
  days?: number[]
  notes?: string
  day_date?: string
}

export interface ImportReport {
  activities: number
  daily_wellness: number
  sleep: number
  hrv: number
  vo2max: number
  race_predictions: number
  training_load: number
  training_readiness: number
  training_history: number
  personal_records: number
  biometric_profile: number
}

export interface LoginResult {
  success: boolean
  needs_mfa: boolean
  message: string
}

export interface GarminStatus {
  configured: boolean
  logged_in: boolean
  message: string
}

export interface SkippedDate {
  date: string
  reason: string
}

export interface PushReport {
  pushed_dates: string[]
  skipped_dates: SkippedDate[]
  errors: string[]
}
