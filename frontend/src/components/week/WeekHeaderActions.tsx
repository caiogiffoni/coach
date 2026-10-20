import type { WeekPlan } from '../../types'

interface WeekHeaderActionsProps {
  plan: WeekPlan | null
  busy: boolean
  garminConfigured: boolean
  onRegenerate: () => void
  onApprove: () => void
  onPush: () => void
}

/** Status-dependent header buttons: regenerate/approve a draft, push an approved week. */
export function WeekHeaderActions({
  plan,
  busy,
  garminConfigured,
  onRegenerate,
  onApprove,
  onPush,
}: WeekHeaderActionsProps) {
  if (plan?.status === 'draft') {
    return (
      <div className="row">
        <button type="button" className="button button-secondary" onClick={onRegenerate} disabled={busy}>
          Regenerate
        </button>
        <button type="button" className="button button-primary" onClick={onApprove} disabled={busy}>
          Approve
        </button>
      </div>
    )
  }
  if (plan?.status !== 'approved') return null
  return (
    <button
      type="button"
      className="button button-primary"
      onClick={onPush}
      disabled={busy || !garminConfigured}
      title={garminConfigured ? 'Push this week to Garmin Connect' : 'Garmin credentials not configured'}
    >
      Push to Garmin
    </button>
  )
}
