interface ProfileInputProps {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  kind?: 'number' | 'decimal' | 'text' | 'mono'
  placeholder?: string
  error?: string
}

/**
 * Labelled profile input; `mono` is a text field for compared values (pace, time).
 *
 * Example: `<ProfileInput id="max_hr" label="Max HR (bpm)" value={v} onChange={set} />`
 */
export function ProfileInput({ id, label, value, onChange, kind = 'number', placeholder, error }: ProfileInputProps) {
  const numeric = kind === 'number' || kind === 'decimal'
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className={kind === 'mono' ? 'input mono' : 'input'}
        type={numeric ? 'number' : 'text'}
        min={numeric ? '0' : undefined}
        step={kind === 'decimal' ? 'any' : undefined}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      {error && <p className="field-error">{error}</p>}
    </div>
  )
}
