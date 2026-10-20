import { useEffect, useState } from 'react'
import { profile } from '../api'
import type { HrZone } from '../types'

/**
 * The athlete's HR zones for "Zone N" hints; null when no profile/zones yet.
 *
 * Example: `const hrZones = useHrZones()`
 */
export function useHrZones(): HrZone[] | null {
  const [hrZones, setHrZones] = useState<HrZone[] | null>(null)
  useEffect(() => {
    profile
      .zones()
      .then((z) => setHrZones(z.hr_zones))
      // Hints are optional: a missing profile just hides the bpm range.
      .catch(() => setHrZones(null))
  }, [])
  return hrZones
}
