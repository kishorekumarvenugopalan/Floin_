import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { History, Mountain } from 'lucide-react'
import { getHealth } from '../../services/floinApi'
import { usePolling } from '../../hooks/useApi'
import { API_BASE_URL } from '../../services/api'
import { ErrorBoundary } from '../common/ui'

const NAV = [
  { to: '/simulation', label: 'Simulation workspace', short: 'Workspace', icon: Mountain },
  { to: '/history', label: 'Simulation history', short: 'History', icon: History },
]

function BackendStatus() {
  const [state, setState] = useState({ status: 'checking' })
  usePolling(async (signal) => {
    try {
      const h = await getHealth({ signal })
      setState({ status: h.status })
    } catch (err) {
      if (!signal.aborted) setState({ status: 'offline', error: err })
    }
  }, 30000, true)
  const dot = { ok: 'bg-teal', degraded: 'bg-lime', offline: 'bg-terracotta', checking: 'bg-faint' }[state.status] || 'bg-lime'
  const label = { ok: 'Backend online', degraded: 'Backend degraded', offline: 'Backend offline', checking: 'Checking backend' }[state.status] || state.status
  return (
    <div className="flex shrink-0 items-center gap-2 text-[11px] text-muted" title={`${API_BASE_URL}${state.error ? ` · ${state.error.message}` : ''}`} role="status" aria-live="polite">
      <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden="true" />
      <span className="hidden sm:inline">{label}</span>
      <span className="sr-only sm:hidden">{label}</span>
    </div>
  )
}

export default function AppShell() {
  const location = useLocation()
  return (
    <div className="flex h-full flex-col">
      <header className="relative z-40 flex h-12 shrink-0 items-center gap-4 border-b border-line bg-ivory px-3 shadow-[0_1px_2px_rgba(60,64,67,0.15)] md:px-4">
        <div className="flex items-center gap-2">
          <svg viewBox="0 0 32 32" className="h-6 w-6" aria-hidden="true">
            <rect width="32" height="32" rx="7" fill="#E8F0FE" />
            <path d="M16 6c4.5 6 7.5 9.6 7.5 13.4a7.5 7.5 0 0 1-15 0C8.5 15.6 11.5 12 16 6z" fill="#1A73E8" />
          </svg>
          <div className="leading-none">
            <div className="text-sm font-bold tracking-wide text-ink">FLOIN</div>
            <div className="hidden text-[10px] text-faint md:block">Chennai flood simulation</div>
          </div>
        </div>
        <nav aria-label="Main" className="flex items-center gap-1">
          {NAV.map(({ to, label, short, icon: Icon }) => (
            <NavLink key={to} to={to}
                     className={({ isActive }) => `flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors ${
                       isActive ? 'bg-mangrove/15 text-mangrove' : 'text-muted hover:bg-paper-2 hover:text-ink'}`}>
              <Icon size={14} aria-hidden="true" />
              <span className="hidden sm:inline">{label}</span>
              <span className="sm:hidden">{short}</span>
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto"><BackendStatus /></div>
      </header>
      <main className="min-h-0 flex-1 overflow-hidden">
        <ErrorBoundary key={location.pathname}>
          <Outlet />
        </ErrorBoundary>
      </main>
    </div>
  )
}
