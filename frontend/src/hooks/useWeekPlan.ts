import { useCallback, useEffect, useState } from 'react'
import { ApiError, coaching } from '../api'
import { errorMessage } from '../errors'
import { addDays, fromISODate, mondayOf, nextMonday, toISODate } from '../format'
import type { WeekPlan } from '../types'
import type { RequestStatus } from './requestStatus'

/**
 * Selected week, its stored plan, and the page-wide busy/error state.
 *
 * Example: `const { plan, shiftWeek } = useWeekPlan()`
 */
export function useWeekPlan() {
  const [weekStart, setWeekStart] = useState<string>(() => toISODate(nextMonday()))
  const [plan, setPlan] = useState<WeekPlan | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [notes, setNotes] = useState('')

  const loadPlan = useCallback(async (week: string) => {
    setLoading(true)
    setError(null)
    try {
      const p = await coaching.getWeek(week)
      setPlan(p)
      setNotes(p.notes)
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setPlan(null)
        setNotes('')
      } else {
        setError(errorMessage(err, 'Failed to load week'))
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadPlan(weekStart)
  }, [weekStart, loadPlan])

  function pickWeek(value: string) {
    if (!value) return
    setWeekStart(toISODate(mondayOf(fromISODate(value))))
  }

  function shiftWeek(offset: number) {
    setWeekStart(toISODate(addDays(fromISODate(weekStart), offset * 7)))
  }

  const status: RequestStatus = { busy, setBusy, error, setError }
  return { weekStart, pickWeek, shiftWeek, plan, setPlan, loading, notes, setNotes, status }
}
