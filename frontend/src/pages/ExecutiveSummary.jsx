import { useEffect, useState } from 'react'
import { getSummary } from '../api/client'
import KPICard from '../components/KPICard'
import HorizontalBarChart from '../components/HorizontalBarChart'
import CategoryPieChart from '../components/CategoryPieChart'
import WeeklyHeatmap from '../components/WeeklyHeatmap'

export default function ExecutiveSummary() {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    getSummary()
      .then(r => setData(r.data))
      .catch(e => setError(e.response?.data?.error ?? 'Error al cargar datos'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="loading">Cargando Resumen Ejecutivo…</div>
  if (error)   return <div className="error-msg">⚠ {error}</div>
  if (!data)   return null

  // Preparar datos para barras
  const topProducts = (data.top_10_products ?? []).map(p => ({
    name:  p.category_name,
    value: p.total_units,
  }))

  const topClients = (data.top_10_clients ?? []).map(c => ({
    name:  `Cliente ${c.client_id}`,
    value: c.num_transactions,
  }))

  // sales_by_store es un array [{store_id, total_units, ...}]
  const salesByStore = (data.sales_by_store ?? []).map(s => ({
    name: `Tienda ${s.store_id}`,
    value: s.total_units,
  }))

  const peakDays = (data.peak_days ?? []).slice(0, 10).map(d => ({
    ...d,
    transactions: d.num_transactions ?? 0,
  }))

  return (
    <div>
      <h1 className="page-title">Resumen Ejecutivo</h1>

      {/* KPIs principales */}
      <div className="kpi-grid">
        <KPICard
          label="Total Unidades Vendidas"
          value={(data.total_units_sold ?? 0).toLocaleString()}
          colorIndex={0}
        />
        <KPICard
          label="Total Transacciones"
          value={(data.total_transactions ?? 0).toLocaleString()}
          colorIndex={1}
        />
        <KPICard
          label="Clientes Únicos"
          value={(data.total_clients ?? 0).toLocaleString()}
          colorIndex={2}
        />
        <KPICard
          label="Categorías"
          value={(data.total_categories ?? 0).toLocaleString()}
          colorIndex={3}
        />
        <KPICard
          label="Tiendas"
          value={(data.total_stores ?? 0).toLocaleString()}
          sub={`${data.date_range?.start ?? ''} → ${data.date_range?.end ?? ''}`}
          colorIndex={4}
        />
      </div>

      {/* Top productos + Top clientes */}
      <div className="grid-2">
        <HorizontalBarChart
          data={topProducts}
          nameKey="name"
          valueKey="value"
          title="Top 10 Categorías por Unidades Vendidas"
        />
        <HorizontalBarChart
          data={topClients}
          nameKey="name"
          valueKey="value"
          title="Top 10 Clientes por Transacciones"
        />
      </div>

      {/* Ventas por tienda + Pie de categorías */}
      <div className="grid-2">
        <HorizontalBarChart
          data={salesByStore}
          nameKey="name"
          valueKey="value"
          title="Unidades Vendidas por Tienda"
        />
        <CategoryPieChart
          data={data.categories_by_volume ?? []}
          nameKey="category_name"
          valueKey="total_units"
          title="Distribución por Categoría (Top 9 + Otros)"
        />
      </div>

      {/* Heatmap semanal */}
      {data.weekly_heatmap && (
        <div className="grid-1">
          <WeeklyHeatmap data={data.weekly_heatmap} title="Actividad Semanal (transacciones por mes × día de semana)" />
        </div>
      )}

      {/* Días pico */}
      {peakDays.length > 0 && (
        <div className="card" style={{ marginBottom: 24 }}>
          <div className="card-title">Días Pico (Top 10 por transacciones)</div>
          <table className="data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Fecha</th>
                <th>Transacciones</th>
              </tr>
            </thead>
            <tbody>
              {peakDays.map((d, i) => (
                <tr key={d.date}>
                  <td><span className="badge">{i + 1}</span></td>
                  <td>{d.date}</td>
                  <td>{(d.transactions).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
