import { useMemo, useState } from 'react'
import { Loader2, PlayCircle } from 'lucide-react'
import { useApi } from '../../hooks/useApi'
import { createSimulation, listDatasets } from '../../services/floinApi'
import { ErrorState, InfoTip } from '../common/ui'
import { fmt } from '../../utils/format'
import { GROUND_LABELS, imdCategory, stormName } from '../../utils/plain'

// Mirrors the backend SimulationRequest (floin_backend/app/schemas/simulation.py).
// There is no location or curve-number field: CN is derived from land cover and soil, and
// every run covers the whole model area. Ia ratio, minimum flood depth and depth class breaks
// are not shown in the form: new runs send the backend defaults below, and a run reopened from
// History keeps the values it was stored with.
export const DEFAULT_FORM = {
  scenario: 'custom', source: 'uniform', rainfall_mm: '200', rainfall_dataset: '', duration_hours: '24',
  antecedent_moisture: 'II', ia_ratio: '0.2', min_flood_depth_m: '0.1', breaks: '0.3, 1.0, 2.0',
}

/** Form values from a stored run's parameters (GET /simulations/{id}). */
export function formFromParameters(p) {
  if (!p) return DEFAULT_FORM
  return {
    scenario: p.scenario ?? DEFAULT_FORM.scenario,
    source: p.rainfall_dataset ? 'dataset' : 'uniform',
    rainfall_mm: p.rainfall_mm != null ? String(p.rainfall_mm) : DEFAULT_FORM.rainfall_mm,
    rainfall_dataset: p.rainfall_dataset || '',
    duration_hours: p.duration_hours != null ? String(p.duration_hours) : DEFAULT_FORM.duration_hours,
    antecedent_moisture: p.antecedent_moisture || 'II',
    ia_ratio: p.ia_ratio != null ? String(p.ia_ratio) : DEFAULT_FORM.ia_ratio,
    min_flood_depth_m: p.min_flood_depth_m != null ? String(p.min_flood_depth_m) : DEFAULT_FORM.min_flood_depth_m,
    breaks: p.depth_class_breaks_m ? p.depth_class_breaks_m.join(', ') : DEFAULT_FORM.breaks,
  }
}

const GROUND_HELP = {
  I: 'Dry ground soaks up more rain, so less water runs off.',
  II: 'Typical conditions.',
  III: 'Soaked ground cannot take in much more, so more water runs off.',
}

function validate(f) {
  const errors = {}
  const num = (v) => (v === '' || v === null ? NaN : Number(v))
  if (!f.scenario.trim()) errors.scenario = 'Give this simulation a name.'
  else if (f.scenario.length > 80) errors.scenario = 'At most 80 characters.'
  if (f.source === 'uniform') {
    const p = num(f.rainfall_mm)
    if (!Number.isFinite(p)) errors.rainfall_mm = 'Enter the amount of rain as a number.'
    else if (p <= 0 || p > 2000) errors.rainfall_mm = 'Enter more than 0 and at most 2000 mm.'
  } else if (!f.rainfall_dataset) errors.rainfall_dataset = 'Choose a past storm.'
  const d = num(f.duration_hours)
  if (!Number.isFinite(d)) errors.duration_hours = 'Enter the number of hours.'
  else if (d <= 0 || d > 240) errors.duration_hours = 'Enter more than 0 and at most 240 hours.'
  const ia = num(f.ia_ratio)
  if (!Number.isFinite(ia) || ia <= 0 || ia > 0.3) errors.ia_ratio = 'Above 0 and at most 0.3.'
  const md = num(f.min_flood_depth_m)
  if (!Number.isFinite(md) || md <= 0 || md > 1) errors.min_flood_depth_m = 'Above 0 and at most 1 m.'
  const breaks = f.breaks.split(',').map((s) => s.trim()).filter(Boolean).map(Number)
  if (!breaks.length || breaks.length > 6 || breaks.some((b) => !Number.isFinite(b))) errors.breaks = '1–6 numbers separated by commas.'
  else if (breaks.some((b, i) => i > 0 && b <= breaks[i - 1]) || breaks[0] <= md) errors.breaks = 'Must increase and start above the minimum depth.'
  return { errors, breaks }
}

export default function SimulationForm({ initial = DEFAULT_FORM, restoredFrom, onSubmitted, busy }) {
  const rainfallDatasets = useApi((signal) => listDatasets({ category: 'rainfall' }, { signal }), [])
  const [form, setForm] = useState(initial)
  const [touched, setTouched] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)

  const gridded = useMemo(
    () => (rainfallDatasets.data || []).filter((d) => d.stage === 'processed' && ['available', 'limited'].includes(d.status)),
    [rainfallDatasets.data],
  )
  const { errors, breaks } = validate(form)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const invalid = (k) => !!(touched && errors[k])
  const err = (k) => invalid(k) && <p className="mt-1 text-[11px] text-terracotta-ink" id={`${k}-error`}>{errors[k]}</p>

  async function onSubmit(e) {
    e.preventDefault()
    setTouched(true)
    if (Object.keys(errors).length || submitting || busy) return
    setSubmitting(true)
    setSubmitError(null)
    const body = {
      scenario: form.scenario.trim(),
      duration_hours: Number(form.duration_hours),
      antecedent_moisture: form.antecedent_moisture,
      ia_ratio: Number(form.ia_ratio),
      min_flood_depth_m: Number(form.min_flood_depth_m),
      depth_class_breaks_m: breaks,
      ...(form.source === 'uniform' ? { rainfall_mm: Number(form.rainfall_mm) } : { rainfall_dataset: form.rainfall_dataset }),
    }
    try {
      const accepted = await createSimulation(body)
      await onSubmitted?.(accepted.simulation_id)
    } catch (err2) {
      setSubmitError(err2)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-3">
      {restoredFrom && <p className="rounded-md bg-mangrove/10 px-2.5 py-1.5 text-[11px] text-mangrove">These are the settings of “{restoredFrom}”. Nothing runs until you press Run simulation.</p>}
      <Field label="Name this simulation" htmlFor="scenario" hint="Any name you like, so you can find it later in History.">
        <input id="scenario" value={form.scenario} onChange={set('scenario')} className={input}
               aria-invalid={invalid('scenario')} aria-describedby="scenario-error" />
        {err('scenario')}
      </Field>

      <div className="text-[11px] font-medium text-muted">How do you want to set the rain?</div>
      <div className="-mt-2 flex gap-1 rounded-md bg-paper-2 p-0.5 text-xs" role="radiogroup" aria-label="How to set the rain">
        {[['uniform', 'Enter an amount'], ['dataset', 'Use a past storm']].map(([k, label]) => (
          <button key={k} type="button" role="radio" aria-checked={form.source === k} onClick={() => setForm((f) => ({ ...f, source: k }))}
                  className={`flex-1 rounded px-2 py-1.5 font-medium ${form.source === k ? 'bg-paper text-mangrove shadow-sm' : 'text-muted hover:text-ink'}`}>{label}</button>
        ))}
      </div>

      <p className="-mt-1 text-[11px] leading-snug text-faint">
        {form.source === 'uniform'
          ? 'You choose how much rain falls. The same amount falls on every part of Chennai.'
          : 'Replays the rain of a real storm, with different amounts in different parts of the city.'}
      </p>

      <div className="grid grid-cols-2 gap-2.5">
        {form.source === 'uniform' ? (
          <Field label="Total rain (mm)" htmlFor="rainfall_mm"
                 hint="Millimetres of rain, as in weather reports. For example, 100 mm is the height the water would reach in a flat tray left out in the rain.">
            <input id="rainfall_mm" type="number" inputMode="decimal" min="0" step="any" value={form.rainfall_mm}
                   onChange={set('rainfall_mm')} className={input} aria-invalid={invalid('rainfall_mm')} aria-describedby="rainfall_mm-error" />
            {err('rainfall_mm')}
          </Field>
        ) : (
          <div className="col-span-2">
            <Field label="Past storm" htmlFor="rainfall_dataset" hint="Rain measured by satellite for a real storm. Each part of Chennai gets the amount that actually fell there.">
              <select id="rainfall_dataset" value={form.rainfall_dataset} onChange={set('rainfall_dataset')} className={input}
                      aria-invalid={invalid('rainfall_dataset')} aria-describedby="rainfall_dataset-error">
                <option value="">Choose a storm…</option>
                {gridded.map((d) => <option key={d.name} value={d.name}>{stormName(d)}</option>)}
              </select>
              {rainfallDatasets.error && <p className="mt-1 text-[11px] text-terracotta-ink">{rainfallDatasets.error.message}</p>}
              {err('rainfall_dataset')}
              {gridded.filter((d) => d.name === form.rainfall_dataset).map((d) => (
                <p key={d.name} className="mt-1 text-[11px] text-faint">Rain in this storm: {fmt(d.min_value, { digits: 0 })}–{fmt(d.max_value, { digits: 0 })} mm, depending on the area (satellite estimate).</p>
              ))}
            </Field>
          </div>
        )}
        <Field label="How long it rains (hours)" htmlFor="duration_hours"
               hint="Saved with the simulation. In this model the total amount of rain is what matters, so the duration does not change the flooding.">
          <input id="duration_hours" type="number" inputMode="decimal" min="0" step="any" value={form.duration_hours}
                 onChange={set('duration_hours')} className={input} aria-invalid={invalid('duration_hours')} aria-describedby="duration_hours-error" />
          {err('duration_hours')}
        </Field>
      </div>

      {form.source === 'uniform' && imdCategory(Number(form.rainfall_mm)) && (
        <p className="-mt-1 text-[11px] text-faint">
          If it fell within one day, the weather department (IMD) would call {fmt(Number(form.rainfall_mm))} mm <b className="font-medium text-muted">{imdCategory(Number(form.rainfall_mm))}</b>.
        </p>
      )}

      <Field label="How wet was the ground before the rain?" htmlFor="amc" hint="Wet ground cannot soak up much more water, so more of the rain runs off and floods.">
        <select id="amc" value={form.antecedent_moisture} onChange={set('antecedent_moisture')} className={input}>
          {['I', 'II', 'III'].map((k) => <option key={k} value={k}>{GROUND_LABELS[k]}</option>)}
        </select>
        <p className="mt-1 text-[11px] text-faint">{GROUND_HELP[form.antecedent_moisture]}</p>
      </Field>

      {submitError && <ErrorState error={submitError} title="The simulation could not be started" />}
      <button type="submit" disabled={submitting || busy}
              className="flex w-full items-center justify-center gap-2 rounded-md bg-mangrove px-4 py-2.5 text-sm font-semibold text-ivory transition-colors hover:bg-mangrove-2 disabled:cursor-not-allowed disabled:bg-mangrove/40">
        {submitting || busy ? <Loader2 size={16} className="animate-spin" /> : <PlayCircle size={16} />}
        {submitting ? 'Submitting…' : busy ? 'Simulation running…' : 'Run simulation'}
      </button>
      {touched && Object.keys(errors).length > 0 && <p className="text-center text-[11px] text-terracotta-ink">Please correct the fields marked in red.</p>}
      <p className="text-center text-[11px] text-faint">A simulation usually takes 2–5 minutes.</p>
    </form>
  )
}

const input = 'w-full rounded-md border border-line-strong bg-ivory px-2.5 py-1.5 text-sm text-ink placeholder:text-faint focus:border-mangrove focus:outline-none aria-[invalid=true]:border-terracotta'

function Field({ label, htmlFor, hint, children }) {
  return (
    <div className="min-w-0">
      <label htmlFor={htmlFor} className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-muted">
        {label} {hint && <InfoTip text={hint} />}
      </label>
      {children}
    </div>
  )
}
