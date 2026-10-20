import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, profile } from '../api'
import { errorMessage } from '../errors'
import { EMPTY_FORM, profileToForm, validateProfileForm } from '../profileForm'
import type { FieldErrors, FormState } from '../profileForm'
import type { ZonesResponse } from '../types'

/**
 * Athlete-profile form state, load/save/seed actions, and derived zones.
 *
 * Example: `const { form, setField, onSubmit } = useProfileForm()`
 */
export function useProfileForm() {
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [exists, setExists] = useState(false)
  const [zones, setZones] = useState<ZonesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})

  function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }))
    setSaved(false)
  }

  async function load() {
    setLoading(true)
    try {
      setForm(profileToForm(await profile.get()))
      setExists(true)
      setZones(await profile.zones())
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setExists(false)
        setZones(null)
      } else {
        setError(errorMessage(err, 'Failed to load profile'))
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function toggleDay(day: number) {
    setField(
      'preferred_days',
      form.preferred_days.includes(day)
        ? form.preferred_days.filter((d) => d !== day)
        : [...form.preferred_days, day].sort(),
    )
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    const { errors, body } = validateProfileForm(form)
    setFieldErrors(errors)
    if (!body) return
    setBusy(true)
    try {
      await profile.update(body)
      setExists(true)
      setSaved(true)
      setZones(await profile.zones())
    } catch (err) {
      setError(errorMessage(err, 'Save failed'))
    } finally {
      setBusy(false)
    }
  }

  async function onSeed() {
    setError(null)
    setBusy(true)
    try {
      await profile.seed()
      await load()
      setSaved(true)
    } catch (err) {
      setError(errorMessage(err, 'Seed failed'))
    } finally {
      setBusy(false)
    }
  }

  return { form, setField, toggleDay, fieldErrors, exists, zones, loading, busy, error, saved, onSubmit, onSeed }
}
