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

export interface SyncReport {
  activities: number
  daily_wellness: number
  hrv: number
  training_readiness: number
  training_load: number
  skipped_datasets: string[]
  newest_date: string | null
  needs_mfa: boolean
}

export interface IngestionStatus {
  newest_date: string | null
}

export interface FileResult {
  filename: string
  status: 'ok' | 'error'
  detail: string | null
  counts: ImportReport | null
}

export interface UploadReport {
  files: FileResult[]
  totals: ImportReport
}

export interface DayGuardResult {
  date: string
  recommendation: 'proceed' | 'swap' | 'veto'
  reason: string
  current_slot_type: string
  suggested_slot_type: string | null
  data_age_days: number
  fatigue_reasons: string[]
}

// --- Workout library (builder) --------------------------------------------
// Mirrors the workout builder API contract (/api/workouts).

export type BuilderStepType = 'warmup' | 'run' | 'recover' | 'rest' | 'cooldown'

export type BuilderStepEnd =
  | { type: 'time'; seconds: number } // 1..86400
  | { type: 'distance'; meters: number } // 1..100000
  | { type: 'lap_button' }

export type HrZoneNumber = 1 | 2 | 3 | 4 | 5

export type BuilderStepTarget =
  | { type: 'none' }
  | { type: 'hr_zone'; zone: HrZoneNumber }
  | { type: 'hr_range'; min_bpm: number; max_bpm: number } // 30..230, min < max
  | { type: 'pace_range'; fast_sec_per_km: number; slow_sec_per_km: number } // 120..1200, fast < slow

export interface BuilderStep {
  kind: 'step'
  step_type: BuilderStepType
  end: BuilderStepEnd
  target: BuilderStepTarget
  notes: string // 0..200 chars
}

export interface RepeatBlock {
  kind: 'repeat'
  iterations: number // 2..50
  steps: BuilderStep[] // 1..20, no nested repeats
}

export type WorkoutItem = BuilderStep | RepeatBlock

export interface LibraryWorkoutInput {
  name: string
  description: string
  steps: WorkoutItem[]
}

export interface LibraryWorkoutPush {
  date: string // ISO date
  garmin_workout_id: string
  pushed_at: string
}

export interface LibraryWorkout {
  id: number
  name: string
  description: string
  steps: WorkoutItem[]
  estimated_duration_sec: number | null
  estimated_distance_m: number | null
  created_at: string
  updated_at: string
  pushes: LibraryWorkoutPush[] // newest first
}

export interface LibraryWorkoutSummary {
  id: number
  name: string
  description: string
  step_count: number // leaf steps, repeats expanded
  estimated_duration_sec: number | null
  estimated_distance_m: number | null
  updated_at: string
}
