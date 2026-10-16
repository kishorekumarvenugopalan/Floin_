import { Component, useMemo, useState } from 'react'
import { AlertTriangle, ArrowDown, ArrowUp, CheckCircle2, CircleDashed, Info, Inbox, RefreshCw, XCircle } from 'lucide-react'

export function Card({ title, subtitle, actions, children, className = '', bodyClass = 'p-4', eyebrow }) {
  return (
    <section className={`min-w-0 rounded-lg border border-line bg-paper shadow-[0_1px_0_rgba(36,41,35,0.04)] ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0">
            {eyebrow && <div className="mb-0.5 font-mono text-[10px] uppercase tracking-[0.14em] text-faint">{eyebrow}</div>}
            {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  )
}

export function SectionLabel({ children }) {
  return <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.14em] text-muted">{children}</div>
}

const TONES = { default: 'text-ink', water: 'text-teal-ink', warn: 'text-terracotta-ink', danger: 'text-terracotta-ink', ok: 'text-mangrove', violet: 'text-violet-ink' }

export function Metric({ label, value, unit, hint, tone = 'default', sub }) {
  return (
    <div className="min-w-0 rounded-lg border border-line bg-paper p-4">
      <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted">
        {label}
        {hint && <InfoTip text={hint} />}
      </div>
      <div className={`mt-2 font-serif text-[1.7rem] leading-none tabular-nums ${TONES[tone]}`}>
        {value}
        {unit && value !== '—' && <span className="ml-1 font-sans text-sm text-muted">{unit}</span>}
      </div>
      {sub && <div className="mt-1.5 text-xs text-muted">{sub}</div>}
    </div>
  )
}

export function Mono({ children, className = '' }) {
  return <span className={`font-mono text-[11px] ${className}`}>{children}</span>
}

const BADGE = {
  available: 'bg-teal/15 text-teal-ink ring-teal/40',
  completed: 'bg-teal/15 text-teal-ink ring-teal/40',
  ok: 'bg-teal/15 text-teal-ink ring-teal/40',
  ready: 'bg-teal/15 text-teal-ink ring-teal/40',
  limited: 'bg-lime/35 text-lime-ink ring-lime/60',
  partial: 'bg-lime/35 text-lime-ink ring-lime/60',
  running: 'bg-violet/15 text-violet-ink ring-violet/40',
  queued: 'bg-paper-2 text-muted ring-line-strong',
  checking: 'bg-paper-2 text-muted ring-line-strong',
  degraded: 'bg-lime/35 text-lime-ink ring-lime/60',
  rejected: 'bg-paper-2 text-muted ring-line-strong',
  unavailable: 'bg-paper-2 text-muted ring-line-strong',
  missing: 'bg-terracotta/12 text-terracotta-ink ring-terracotta/40',
  failed: 'bg-terracotta/12 text-terracotta-ink ring-terracotta/40',
  offline: 'bg-terracotta/12 text-terracotta-ink ring-terracotta/40',
}

export function StatusBadge({ status, label }) {
  const cls = BADGE[status] || 'bg-paper-2 text-muted ring-line-strong'
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${cls}`}>
      {status === 'running' && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-violet" />}
      {label || status}
    </span>
  )
}

/** A row stating whether a piece of data is available, with its source or the reason it is not. */
export function AvailabilityRow({ label, state, value, note }) {
  const Icon = state === 'ok' ? CheckCircle2 : state === 'unavailable' || state === 'error' ? XCircle : CircleDashed
  const colour = state === 'ok' ? 'text-teal-ink' : state === 'error' ? 'text-terracotta-ink' : state === 'partial' ? 'text-lime-ink' : 'text-faint'
  return (
    <div className="flex items-start gap-2 py-1.5">
      <Icon size={14} className={`mt-0.5 shrink-0 ${colour}`} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
          <span className="text-xs text-ink">{label}</span>
          {value != null && <span className="font-mono text-[11px] text-ink">{value}</span>}
        </div>
        {note && <p className="text-[11px] leading-snug text-muted">{note}</p>}
      </div>
      <span className="sr-only">{state}</span>
    </div>
  )
}

export function InfoTip({ text }) {
  return (
    <span className="group relative inline-flex normal-case tracking-normal">
      <button type="button" aria-label={text} className="text-faint hover:text-muted focus:text-muted">
        <Info size={12} />
      </button>
      <span role="tooltip"
            className="pointer-events-none absolute bottom-full left-1/2 z-[1500] mb-2 hidden w-64 -translate-x-1/2 rounded-md border border-line-strong bg-paper px-3 py-2 font-sans text-xs leading-relaxed text-ink shadow-lg group-focus-within:block group-hover:block">
        {text}
      </span>
    </span>
  )
}

export function Skeleton({ className = 'h-4 w-full' }) {
  return <div className={`skeleton ${className}`} aria-hidden="true" />
}

export function LoadingState({ label = 'Loading…', rows = 3 }) {
  return (
    <div role="status" aria-live="polite" className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className={`h-3.5 ${i % 2 ? 'w-2/3' : 'w-full'}`} />)}
      <p className="pt-1 text-xs text-muted">{label}</p>
    </div>
  )
}

export function ErrorState({ error, onRetry, title = 'Could not load data' }) {
  return (
    <div role="alert" className="rounded-md border border-terracotta/40 bg-terracotta/8 p-3 text-sm">
      <div className="flex items-center gap-2 font-semibold text-terracotta-ink"><AlertTriangle size={15} /> {title}</div>
      <p className="mt-1 text-xs text-ink/80">{error?.message || String(error)}</p>
      {error?.code && <p className="mt-1 font-mono text-[10px] text-muted">{error.code}{error.status ? ` · HTTP ${error.status}` : ''}</p>}
      {onRetry && (
        <button onClick={onRetry} className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-terracotta/40 px-2.5 py-1 text-xs text-terracotta-ink hover:bg-terracotta/10">
          <RefreshCw size={12} /> Retry
        </button>
      )}
    </div>
  )
}

export function EmptyState({ title, children, action, icon: Icon = Inbox }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-line-strong bg-paper/60 px-6 py-10 text-center">
      <Icon size={22} className="text-faint" aria-hidden="true" />
      <p className="text-base font-semibold text-ink">{title}</p>
      {children && <div className="max-w-md text-xs leading-relaxed text-muted">{children}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

export function Notice({ tone = 'info', children, title }) {
  const tones = {
    info: 'border-teal/40 bg-teal/8 text-ink',
    warn: 'border-terracotta/40 bg-terracotta/8 text-ink',
    note: 'border-line-strong bg-paper-2/60 text-ink',
  }
  return (
    <div className={`rounded-md border px-3.5 py-2.5 text-xs leading-relaxed ${tones[tone]}`}>
      {title && <div className="mb-0.5 font-semibold">{title}</div>}
      {children}
    </div>
  )
}

export function Button({ children, variant = 'primary', className = '', ...props }) {
  const variants = {
    primary: 'bg-mangrove text-ivory hover:bg-mangrove-2 disabled:bg-mangrove/40',
    secondary: 'border border-line-strong bg-paper text-ink hover:border-mangrove/50 hover:bg-paper-2 disabled:opacity-50',
    ghost: 'text-muted hover:bg-paper-2 hover:text-ink',
    lime: 'bg-lime text-ink hover:brightness-95',
  }
  return (
    <button className={`inline-flex items-center justify-center gap-2 rounded-md px-3.5 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed ${variants[variant]} ${className}`} {...props}>
      {children}
    </button>
  )
}

/** Sortable table. columns: [{key, label, render?, align?, sortValue?}] */
export function DataTable({ columns, rows, initialSort, emptyText = 'No rows', maxHeight = '28rem', rowKey, onRowClick, activeKey }) {
  const [sort, setSort] = useState(initialSort || { key: columns[0].key, dir: 'asc' })
  const sorted = useMemo(() => {
    const col = columns.find((c) => c.key === sort.key)
    const value = (r) => (col?.sortValue ? col.sortValue(r) : r[sort.key])
    return [...rows].sort((a, b) => {
      const va = value(a)
      const vb = value(b)
      if (va == null) return 1
      if (vb == null) return -1
      const cmp = typeof va === 'number' && typeof vb === 'number' ? va - vb : String(va).localeCompare(String(vb), undefined, { numeric: true })
      return sort.dir === 'asc' ? cmp : -cmp
    })
  }, [rows, sort, columns])

  if (!rows.length) return <p className="py-6 text-center text-sm text-muted">{emptyText}</p>
  return (
    <div className="scroll-thin overflow-auto rounded-md border border-line" style={{ maxHeight }}>
      <table className="w-full text-left text-sm">
        <thead className="sticky top-0 z-10 bg-paper-2 font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
          <tr>
            {columns.map((c) => {
              const active = sort.key === c.key
              return (
                <th key={c.key} scope="col" className={`whitespace-nowrap px-3 py-2 font-medium ${c.align === 'right' ? 'text-right' : ''}`}
                    aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                  <button type="button" className="inline-flex items-center gap-1 hover:text-ink"
                          onClick={() => setSort({ key: c.key, dir: active && sort.dir === 'desc' ? 'asc' : 'desc' })}>
                    {c.label}
                    {active && (sort.dir === 'asc' ? <ArrowUp size={11} /> : <ArrowDown size={11} />)}
                  </button>
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody className="divide-y divide-line bg-paper">
          {sorted.map((r, i) => {
            const key = rowKey ? rowKey(r) : i
            return (
              <tr key={key} onClick={onRowClick ? () => onRowClick(r) : undefined}
                  className={`${onRowClick ? 'cursor-pointer' : ''} ${activeKey != null && key === activeKey ? 'bg-lime/25' : 'hover:bg-paper-2/70'}`}>
                {columns.map((c) => (
                  <td key={c.key} className={`px-3 py-2 align-top ${c.align === 'right' ? 'text-right font-mono text-xs tabular-nums' : ''}`}>
                    {c.render ? c.render(r) : r[c.key] ?? '—'}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error) {
    return { error }
  }
  render() {
    if (this.state.error) {
      return (
        <div className="p-6">
          <ErrorState title={this.props.title || 'This section crashed'} error={this.state.error} onRetry={() => this.setState({ error: null })} />
        </div>
      )
    }
    return this.props.children
  }
}

export function PageHeader({ eyebrow, title, description, actions, children }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.16em] text-muted">{eyebrow}</div>}
        <h1 className="text-[2rem] leading-tight text-ink">{title}</h1>
        {description && <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-muted">{description}</p>}
        {children}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}
