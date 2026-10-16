import { useMemo, useState } from 'react'
import { Loader2, PlayCircle } from 'lucide-react'
import { useApi } from '../../hooks/useApi'
import { createSimulation, listDatasets } from '../../services/floinApi'
import { ErrorState, InfoTip } from '../common/ui'
import { fmt } from '../../utils/format'

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

const AMC_HELP = {
  I: 'Dry ground before the event: lower curve numbers, less runoff.',
  II: 'Average conditions (TR-55 table values).',
  III: 'Wet ground after recent heavy rain: higher curve numbers, more runoff.',
}

function validate(f) {
  const errors = {}
  const num = (v) => (v === '' || v === null ? NaN : Number(v))
  if (!f.scenario.trim()) errors.scenario = 'Give the run a name.'
  else if (f.scenario.length > 80) errors.scenario = 'At most 80 characters.'
  if (f.source === 'uniform') {
    const p = num(f.rainfall_mm)
    if (!Number.isFinite(p)) errors.rainfall_mm = 'Enter a number.'
    else if (p <= 0 || p > 2000) errors.rainfall_mm = 'Must be above 0 and at most 2000 mm.'
  } else if (!f.rainfall_dataset) errors.rainfall_dataset = 'Choose a rainfall dataset.'
  const d = num(f.duration_hours)
  if (!Number.isFinite(d)) errors.duration_hours = 'Enter a number.'
  else if (d <= 0 || d > 240) errors.duration_hours = 'Must be above 0 and at most 240 hours.'
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
      {restoredFrom && <p className="rounded-md bg-mangrove/10 px-2.5 py-1.5 text-[11px] text-mangrove">Inputs restored from {restoredFrom}. Nothing runs until you press Run simulation.</p>}
      <Field label="Run name" htmlFor="scenario">
        <input id="scenario" value={form.scenario} onChange={set('scenario')} className={input}
               aria-invalid={invalid('scenario')} aria-describedby="scenario-error" />
        {err('scenario')}
      </Field>

      <div className="flex gap-1 rounded-md bg-paper-2 p-0.5 text-xs" role="radiogroup" aria-label="Rainfall input">
        {[['uniform', 'Rainfall depth'], ['dataset', 'Rainfall grid']].map(([k, label]) => (
          <button key={k} type="button" role="radio" aria-checked={form.source === k} onClick={() => setForm((f) => ({ ...f, source: k }))}
                  className={`flex-1 rounded px-2 py-1.5 font-medium ${form.source === k ? 'bg-paper text-mangrove shadow-sm' : 'text-muted hover:text-ink'}`}>{label}</button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-2.5">
        {form.source === 'uniform' ? (
          <Field label="Rainfall (mm)" htmlFor="rainfall_mm" hint="Event total, applied evenly to every land cell of the model area.">
            <input id="rainfall_mm" type="number" inputMode="decimal" min="0" step="any" value={form.rainfall_mm}
                   onChange={set('rainfall_mm')} className={input} aria-invalid={invalid('rainfall_mm')} aria-describedby="rainfall_mm-error" />
            {err('rainfall_mm')}
          </Field>
        ) : (
          <Field label="Rainfall grid" htmlFor="rainfall_dataset" hint="Registered rainfall rasters on the 30 m model grid.">
            <select id="rainfall_dataset" value={form.rainfall_dataset} onChange={set('rainfall_dataset')} className={input}
                    aria-invalid={invalid('rainfall_dataset')} aria-describedby="rainfall_dataset-error">
              <option value="">Select…</option>
              {gridded.map((d) => <option key={d.name} value={d.name}>{d.title} ({fmt(d.min_value)}–{fmt(d.max_value)} mm)</option>)}
            </select>
            {rainfallDatasets.error && <p className="mt-1 text-[11px] text-terracotta-ink">{rainfallDatasets.error.message}</p>}
            {err('rainfall_dataset')}
          </Field>
        )}
        <Field label="Duration (h)" htmlFor="duration_hours"
               hint="Stored with the run and used for mean intensity. SCS-CN works on event totals, so duration does not change runoff depth.">
          <input id="duration_hours" type="number" inputMode="decimal" min="0" step="any" value={form.duration_hours}
                 onChange={set('duration_hours')} className={input} aria-invalid={invalid('duration_hours')} aria-describedby="duration_hours-error" />
          {err('duration_hours')}
        </Field>
      </div>

      <Field label="Antecedent moisture" htmlFor="amc" hint="Adjusts the TR-55 curve numbers for ground wetness before the event (Chow et al. 1988).">
        <select id="amc" value={form.antecedent_moisture} onChange={set('antecedent_moisture')} className={input}>
          <option value="I">I · dry</option>
          <option value="II">II · average</option>
          <option value="III">III · wet</option>
        </select>
        <p className="mt-1 text-[11px] text-faint">{AMC_HELP[form.antecedent_moisture]}</p>
      </Field>

      {submitError && <ErrorState error={submitError} title="The backend rejected the request" />}
      <button type="submit" disabled={submitting || busy}
              className="flex w-full items-center justify-center gap-2 rounded-md bg-mangrove px-4 py-2.5 text-sm font-semibold text-ivory transition-colors hover:bg-mangrove-2 disabled:cursor-not-allowed disabled:bg-mangrove/40">
        {submitting || busy ? <Loader2 size={16} className="animate-spin" /> : <PlayCircle size={16} />}
        {submitting ? 'Submitting…' : busy ? 'Simulation running…' : 'Run simulation'}
      </button>
      {touched && Object.keys(errors).length > 0 && <p className="text-center text-[11px] text-terracotta-ink">Fix the highlighted fields.</p>}
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
