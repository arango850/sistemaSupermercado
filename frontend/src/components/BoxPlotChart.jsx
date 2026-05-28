/**
 * BoxPlotChart — distribución del tamaño de cesta:
 *   - Histograma de frecuencias (basket_size_histogram)
 *   - Top 15 categorías por volumen de transacciones (category_basket_stats)
 */
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell,
} from 'recharts'

const PALETTE = [
  '#2563eb','#3b82f6','#60a5fa','#93c5fd','#bfdbfe',
  '#10b981','#34d399','#6ee7b7','#a7f3d0','#d1fae5',
  '#f59e0b','#fbbf24','#fcd34d','#fde68a','#fef3c7',
]

export default function BoxPlotChart({ data }) {
  if (!data?.basket_size_histogram) return null

  // Histograma de tamaño de cesta (solo primeras 30 entradas para no saturar)
  const histData = (data.basket_size_histogram ?? []).slice(0, 30)

  // Top 15 categorías por número de transacciones (count)
  const topCats = [...(data.category_basket_stats ?? [])]
    .sort((a, b) => b.count - a.count)
    .slice(0, 15)
    .map(c => ({ name: c.category_name, value: c.count }))

  return (
    <>
      {/* Histograma */}
      <div className="card" style={{ marginBottom: 24 }}>
        <div className="card-title">Distribución de Tamaño de Cesta (frecuencia por nº de ítems)</div>
        <div style={{ fontSize: 12, color: '#64748b', marginBottom: 12 }}>
          Mediana: 6 ítems · Q1: 3 · Q3: 12 · Máx: 128
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={histData} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis
              dataKey="basket_size"
              tick={{ fontSize: 11 }}
              label={{ value: 'Ítems en cesta', position: 'insideBottom', offset: -2, fontSize: 11 }}
            />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={v => (v / 1000).toFixed(0) + 'k'} width={50} />
            <Tooltip
              formatter={v => [v.toLocaleString(), 'Transacciones']}
              labelFormatter={l => `${l} ítems`}
            />
            <Bar dataKey="frequency" radius={[3, 3, 0, 0]}>
              {histData.map((_, i) => (
                <Cell key={i} fill={i < 6 ? '#2563eb' : i < 12 ? '#60a5fa' : '#bfdbfe'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Top categorías por volumen */}
      <div className="card">
        <div className="card-title">Top 15 Categorías por Número de Transacciones</div>
        <ResponsiveContainer width="100%" height={420}>
          <BarChart
            data={topCats}
            layout="vertical"
            margin={{ top: 4, right: 70, left: 8, bottom: 4 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={v => (v / 1000).toFixed(0) + 'k'} />
            <YAxis type="category" dataKey="name" width={155} tick={{ fontSize: 11 }} tickLine={false} />
            <Tooltip formatter={v => [v.toLocaleString(), 'Transacciones']} />
            <Bar dataKey="value" radius={[0, 4, 4, 0]}>
              {topCats.map((_, i) => (
                <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </>
  )
}

