import { useEffect, useState } from 'react'
import { getTimeSeries, getBoxplot, getHeatmap } from '../api/client'
import TimeSeriesChart from '../components/TimeSeriesChart'
import BoxPlotChart from '../components/BoxPlotChart'
import CorrelationHeatmap from '../components/CorrelationHeatmap'

export default function AnalyticalCharts() {
  const [tsData,      setTsData]      = useState(null)
  const [boxData,     setBoxData]     = useState(null)
  const [hmData,      setHmData]      = useState(null)
  const [loading,     setLoading]     = useState(true)
  const [error,       setError]       = useState(null)

  useEffect(() => {
    Promise.all([getTimeSeries(), getBoxplot(), getHeatmap()])
      .then(([ts, box, hm]) => {
        setTsData(ts.data)
        setBoxData(box.data)
        setHmData(hm.data)
      })
      .catch(e => setError(e.response?.data?.error ?? 'Error al cargar visualizaciones'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="loading">Cargando Visualizaciones Analíticas…</div>
  if (error)   return <div className="error-msg">⚠ {error}</div>

  return (
    <div>
      <h1 className="page-title">Visualizaciones Analíticas</h1>

      {/* Serie temporal */}
      <div className="grid-1">
        {tsData && <TimeSeriesChart data={tsData} />}
      </div>

      {/* Boxplot */}
      <div className="grid-1">
        {boxData && <BoxPlotChart data={boxData} />}
      </div>

      {/* Estadísticas resumen del boxplot */}
      {boxData?.basket_size_stats && (
        <div className="card" style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', gap: 48, flexWrap: 'wrap' }}>
            {/* Tamaño de cesta */}
            <div>
              <div className="card-title" style={{ marginBottom: 12 }}>Tamaño de Cesta por Transacción</div>
              <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
                {Object.entries(boxData.basket_size_stats)
                  .filter(([k]) => k !== 'label')
                  .map(([k, v]) => (
                    <div key={k}>
                      <div style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', fontWeight: 600 }}>{k}</div>
                      <div style={{ fontSize: 20, fontWeight: 700 }}>{typeof v === 'number' ? v.toFixed(2) : v}</div>
                    </div>
                  ))}
              </div>
            </div>
            {/* Total unidades por cliente */}
            {boxData?.client_total_stats && (
              <div>
                <div className="card-title" style={{ marginBottom: 12 }}>Total Unidades por Cliente</div>
                <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
                  {Object.entries(boxData.client_total_stats)
                    .filter(([k]) => k !== 'label')
                    .map(([k, v]) => (
                      <div key={k}>
                        <div style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', fontWeight: 600 }}>{k}</div>
                        <div style={{ fontSize: 20, fontWeight: 700 }}>{typeof v === 'number' ? v.toFixed(2) : v}</div>
                      </div>
                    ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Heatmap de correlaciones */}
      <div className="grid-1">
        {hmData && <CorrelationHeatmap data={hmData} />}
      </div>
    </div>
  )
}
