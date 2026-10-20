import { WEEKDAY_NAMES } from '../format'

interface WeekdayCheckboxesProps {
  selected: number[] // 0=Mon
  onToggle: (day: number) => void
}

/** Monday-to-Sunday checkbox row used for run-day selection. */
export function WeekdayCheckboxes({ selected, onToggle }: WeekdayCheckboxesProps) {
  return (
    <div className="checkbox-row">
      {WEEKDAY_NAMES.map((name, i) => (
        <label className="checkbox-label" key={name}>
          <input type="checkbox" checked={selected.includes(i)} onChange={() => onToggle(i)} />
          {name}
        </label>
      ))}
    </div>
  )
}
