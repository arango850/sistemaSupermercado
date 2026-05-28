import { NavLink } from 'react-router-dom'
import { useState, useEffect, useRef } from 'react'
import { runAnalysis, getAnalysisStatus } from '../api/client'

export default function Navbar() {
  const [pipelineStatus, setPipelineStatus] = useState('idle')
  const intervalRef = useRef(null)

  const startPolling = () => {
    if (intervalRef.current) return
    intervalRef.current = setInterval(async () => {
      try {
        const { data } = await getAnalysisStatus()
        setPipelineStatus(data.status)
        if (data.status !== 'running') {
          clearInterval(intervalRef.current)
          intervalRef.current = null
        }
      } catch { /* silencioso */ }
    }, 3000)
  }

  const handleRun = async () => {
    try {
      await runAnalysis()
      setPipelineStatus('running')
      startPolling()
    } catch (err) {
      if (err.response?.status === 409) {
        setPipelineStatus('running')
        startPolling()
      }
    }
  }

  useEffect(() => () => { clearInterval(intervalRef.current) }, [])

  const btnLabel = {
    idle:      '⟳ Actualizar análisis',
    running:   '⏳ Analizando…',
    completed: '✓ Completado',
    error:     '✗ Error — reintentar',
  }[pipelineStatus] ?? '⟳ Actualizar análisis'

  return (
    <nav className="navbar">
      <NavLink to="/summary" className="navbar-brand">🛒 Supermercado Analytics</NavLink>
      <div className="navbar-links">
        <NavLink to="/summary" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
          Resumen Ejecutivo
        </NavLink>
        <NavLink to="/charts" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
          Visualizaciones Analíticas
        </NavLink>
        <NavLink to="/segments" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
          Segmentación
        </NavLink>
        <NavLink to="/recommendations" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
          Recomendaciones
        </NavLink>
      </div>
      <button
        className={`run-btn ${pipelineStatus}`}
        onClick={handleRun}
        disabled={pipelineStatus === 'running'}
      >
        {btnLabel}
      </button>
    </nav>
  )
}
