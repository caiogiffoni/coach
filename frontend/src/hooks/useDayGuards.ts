import { useEffect, useState } from 'react'
import { coaching } from '../api'
import { toISODate } from '../format'
import type { DayGuardResult, WeekPlan } from '../types'

/**
 * Daily-guard results keyed by ISO date, for planned days up to today.
 *
 * Example: `const guardByDate = useDayGuards(plan, weekStart)`
 */
export function useDayGuards(
  plan: WeekPlan | null,
  weekStart: string,
): Record<string, DayGuardResult> {
  const [guardByDate, setGuardByDate] = useState<Record<string, DayGuardResult>>({})

  // Fetch guard results for every day that has a planned workout.
  useEffect(() => {
    if (!plan) {
      setGuardByDate({})
      return
    }
    let cancelled = false
    const today = toISODate(new Date())
    Promise.all(
      plan.workouts.map(async (w) => {
        if (w.date > today) return null
        try {
          return await coaching.guard(weekStart, w.date)
        } catch {
          return null
        }
      }),
    ).then((results) => {
      if (cancelled) return
      const byDate: Record<string, DayGuardResult> = {}
      for (const r of results) {
        if (r) byDate[r.date] = r
      }
      setGuardByDate(byDate)
    })
    return () => {
      cancelled = true
    }
  }, [plan, weekStart])

  return guardByDate
}
