import { useEffect, useState } from 'react'
import { garmin } from '../api'
import type { GarminStatus } from '../types'

/**
 * Garmin credential status, refetched whenever the selected week changes.
 *
 * Example: `const garminStatus = useGarminStatus(weekStart)`
 */
export function useGarminStatus(weekStart: string): GarminStatus | null {
  const [garminStatus, setGarminStatus] = useState<GarminStatus | null>(null)

  useEffect(() => {
    garmin
      .status()
      .then((s) => setGarminStatus(s))
      .catch(() => setGarminStatus(null))
  }, [weekStart])

  return garminStatus
}
