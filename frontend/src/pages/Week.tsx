import { GarminMfaCard } from '../components/week/GarminMfaCard'
import { GeneratePanel } from '../components/week/GeneratePanel'
import { PushReportCard } from '../components/week/PushReportCard'
import { SyncReportCard } from '../components/week/SyncReportCard'
import { WeekBanners } from '../components/week/WeekBanners'
import { WeekControls } from '../components/week/WeekControls'
import { WeekDays } from '../components/week/WeekDays'
import { WeekHeaderActions } from '../components/week/WeekHeaderActions'
import { useDayGuards } from '../hooks/useDayGuards'
import { useGarminPush } from '../hooks/useGarminPush'
import { useGarminStatus } from '../hooks/useGarminStatus'
import { useGarminSync } from '../hooks/useGarminSync'
import { usePlanActions } from '../hooks/usePlanActions'
import { useRunDays } from '../hooks/useRunDays'
import { useWeekPlan } from '../hooks/useWeekPlan'

export function Week() {
  const week = useWeekPlan()
  const { weekStart, plan, setPlan, status } = week
  const { days, toggleDay } = useRunDays()
  const garminStatus = useGarminStatus(weekStart)
  const push = useGarminPush({ weekStart, setPlan, status })
  const sync = useGarminSync({ weekStart, garminConfigured: garminStatus?.configured, status })
  const guardByDate = useDayGuards(plan, weekStart)
  const actions = usePlanActions({ weekStart, notes: week.notes, days, setPlan, status })

  // Sync MFA takes precedence when both prompts are pending (matches prior behavior).
  const mfa = sync.syncNeedsMfa
    ? { code: sync.syncMfaCode, setCode: sync.setSyncMfaCode, submit: sync.submitSyncMfa }
    : { code: push.mfaCode, setCode: push.setMfaCode, submit: push.submitMfa }
  const cancelMfa = () => {
    push.cancelMfa()
    sync.cancelSyncMfa()
  }

  return (
    <>
      <div className="page-header">
        <h1>Week</h1>
        <WeekHeaderActions
          plan={plan}
          busy={status.busy}
          garminConfigured={garminStatus?.configured ?? false}
          onRegenerate={actions.generate}
          onApprove={actions.approve}
          onPush={push.executePush}
        />
      </div>

      <WeekControls weekStart={weekStart} plan={plan} onShiftWeek={week.shiftWeek} onPickWeek={week.pickWeek} />
      <WeekBanners error={status.error} garminStatus={garminStatus} stalenessText={sync.stalenessText} plan={plan} />

      {(push.needsMfa || sync.syncNeedsMfa) && (
        <GarminMfaCard
          code={mfa.code}
          busy={status.busy}
          onCodeChange={mfa.setCode}
          onSubmit={mfa.submit}
          onCancel={cancelMfa}
        />
      )}
      {sync.syncReport && <SyncReportCard report={sync.syncReport} />}
      {push.pushReport && <PushReportCard report={push.pushReport} />}

      <GeneratePanel
        hasPlan={plan !== null}
        busy={status.busy}
        notes={week.notes}
        days={days}
        onNotesChange={week.setNotes}
        onToggleDay={toggleDay}
        onGenerate={actions.generate}
        onSync={() => sync.executeSync()}
      />
      <WeekDays
        weekStart={weekStart}
        plan={plan}
        loading={week.loading}
        busy={status.busy}
        canGenerate={days.length > 0}
        guardByDate={guardByDate}
        onGenerate={actions.generate}
        onRegenerateDay={actions.regenerateDay}
        onRegenerateFromGuard={actions.regenerateFromGuard}
      />
    </>
  )
}
