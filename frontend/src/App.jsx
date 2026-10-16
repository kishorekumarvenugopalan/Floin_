import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import AppShell from './components/layout/AppShell'
import { LoadingState } from './components/common/ui'
import { SimulationProvider } from './context/SimulationContext'
import { AreaProvider } from './context/AreaContext'

const SimulationWorkspace = lazy(() => import('./pages/SimulationWorkspace'))
const SimulationHistory = lazy(() => import('./pages/SimulationHistory'))

export default function App() {
  return (
    <BrowserRouter>
      <SimulationProvider>
        <AreaProvider>
          <Suspense fallback={<div className="p-8"><LoadingState label="Loading…" /></div>}>
            <Routes>
              <Route element={<AppShell />}>
                <Route path="/simulation" element={<SimulationWorkspace />} />
                <Route path="/history" element={<SimulationHistory />} />
                <Route path="*" element={<Navigate to="/simulation" replace />} />
              </Route>
            </Routes>
          </Suspense>
        </AreaProvider>
      </SimulationProvider>
    </BrowserRouter>
  )
}
