interface GarminMfaCardProps {
  code: string
  busy: boolean
  onCodeChange: (code: string) => void
  onSubmit: () => void
  onCancel: () => void
}

/** Prompt for the Garmin MFA code before retrying a push or sync. */
export function GarminMfaCard({ code, busy, onCodeChange, onSubmit, onCancel }: GarminMfaCardProps) {
  return (
    <section className="section">
      <div className="card">
        <h2 className="card-title">Garmin two-factor authentication</h2>
        <p className="field-hint" style={{ marginBottom: 12 }}>
          Enter the MFA code from your authenticator app to continue.
        </p>
        <div className="field">
          <label className="field-label" htmlFor="mfa-code">
            MFA code
          </label>
          <input
            id="mfa-code"
            className="input"
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            onChange={(e) => onCodeChange(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && onSubmit()}
          />
        </div>
        <div className="form-actions">
          <button type="button" className="button button-primary" onClick={onSubmit} disabled={busy || !code}>
            Verify and continue
          </button>
          <button type="button" className="button button-secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
        </div>
      </div>
    </section>
  )
}
