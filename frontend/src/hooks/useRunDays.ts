import { useEffect, useState } from 'react'
import { profile } from '../api'

/**
 * Run-day selection (0 = Monday), seeded from the profile's preferred days.
 *
 * Example: `const { days, toggleDay } = useRunDays()`
 */
export function useRunDays() {
  const [days, setDays] = useState<number[]>([])

  // Initialize run-day checkboxes from the profile's preferred days.
  useEffect(() => {
    profile
      .get()
      .then((p) => setDays([...p.preferred_days].sort()))
      .catch(() => {})
  }, [])

  function toggleDay(day: number) {
    setDays((prev) =>
      prev.includes(day) ? prev.filter((d) => d !== day) : [...prev, day].sort(),
    )
  }

  return { days, toggleDay }
}
