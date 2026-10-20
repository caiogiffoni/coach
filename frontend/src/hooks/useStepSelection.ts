import { useMemo, useState } from 'react'
import type { ItemDraft } from '../workoutBuilder'

/**
 * Checkbox selection of top-level steps for "Group into repeat". Uids that no
 * longer name a top-level step (deleted, or already grouped) drop out.
 *
 * Example: `const selection = useStepSelection(items); selection.toggle(uid)`
 */
export function useStepSelection(items: ItemDraft[]) {
  const [picked, setPicked] = useState<ReadonlySet<string>>(() => new Set())
  const selected = useMemo<ReadonlySet<string>>(
    () => new Set(items.filter((item) => item.kind === 'step' && picked.has(item.uid)).map((item) => item.uid)),
    [items, picked],
  )

  function toggle(uid: string) {
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(uid)) next.delete(uid)
      else next.add(uid)
      return next
    })
  }

  return { selected, toggle, clear: () => setPicked(new Set()) }
}

export type StepSelection = ReturnType<typeof useStepSelection>
