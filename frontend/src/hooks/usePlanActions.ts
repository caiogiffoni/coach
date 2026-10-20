import { coaching } from '../api'
import { errorMessage } from '../errors'
import type { WeekPlan } from '../types'
import type { RequestStatus } from './requestStatus'

interface PlanActionsInput {
  weekStart: string
  notes: string
  days: number[]
  setPlan: (plan: WeekPlan) => void
  status: RequestStatus
}

/**
 * Generate / regenerate / approve actions for the selected week.
 *
 * Example: `const { generate } = usePlanActions({ weekStart, notes, days, setPlan, status })`
 */
export function usePlanActions({ weekStart, notes, days, setPlan, status }: PlanActionsInput) {
  async function run(action: () => Promise<WeekPlan>) {
    status.setBusy(true)
    status.setError(null)
    try {
      setPlan(await action())
    } catch (err) {
      status.setError(errorMessage(err, 'Request failed'))
    } finally {
      status.setBusy(false)
    }
  }

  const generate = () =>
    run(() =>
      coaching.generateWeek({
        week: weekStart,
        days: days.length > 0 ? days : undefined,
        notes: notes.trim() || undefined,
      }),
    )

  const regenerateDay = (date: string) =>
    run(() => coaching.generateWeek({ week: weekStart, day_date: date }))

  const regenerateFromGuard = (date: string, reason: string) =>
    run(() =>
      coaching.generateWeek({
        week: weekStart,
        day_date: date,
        notes: [notes.trim(), `Guard: ${reason}`].filter(Boolean).join(' — '),
      }),
    )

  const approve = () => run(() => coaching.approveWeek(weekStart))

  return { generate, regenerateDay, regenerateFromGuard, approve }
}
