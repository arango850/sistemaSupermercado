import { useState, useEffect } from 'react'
import { getSegments } from '../api/client'
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, BarChart, Bar, Cell,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
} from 'recharts'

// Paleta de colores para segmentos
const SEG_COLORS = ['#2563eb', '#16a34a', '#dc2626', '#d97706', '#7c3aed', '#0891b2']

const FEATURE_LABELS = {
  purchase_frequency: 'Frec. Compra',
  total_units:        'Total Unid.',
  avg_basket_size:    'Tamaño Cesta',
  category_diversity: 'Diversidad Cat.',
  active_days:        'Días Activo',
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-componentes
// ─────────────────────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub }) {
  return (
    <div className="kpi-card">
      <div className="kpi-value">{value}</div>
      <div className="kpi-label">{label}</div>
      {sub && <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: 4 }}>{sub}</div>}
    </div>
  )
}

function SegmentCard({ seg }) {
  const color = SEG_COLORS[seg.segment_id % SEG_COLORS.length]
  return (
    <div className="chart-card" style={{ borderTop: `4px solid ${color}` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h3 style={{ margin: 0, color, fontSize: '1rem' }}>
            Segmento {seg.segment_id + 1}
          </h3>
          <p style={{ margin: '4px 0 0', fontWeight: 600, fontSize: '1.1rem' }}>{seg.label}</p>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: '1.6rem', fontWeight: 700, color }}>
            {seg.size.toLocaleString()}
          </div>
          <div style={{ fontSize: '0.8rem', color: '#64748b' }}>
            clientes ({seg.percentage}%)
          </div>
        </div>
      </div>

      {/* Tabla de centroide */}
      <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 16, fontSize: '0.82rem' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
            <th style={{ textAlign: 'left', padding: '4px 0', color: '#64748b' }}>Métrica</th>
            <th style={{ textAlign: 'right', padding: '4px 0', color: '#64748b' }}>Centroide</th>
            {seg.stats && (
              <th style={{ textAlign: 'right', padding: '4px 0', color: '#64748b' }}>Media real</th>
            )}
          </tr>
        </thead>
        <tbody>
          {Object.entries(seg.centroid).map(([key, val]) => (
            <tr key={key} style={{ borderBottom: '1px solid #f1f5f9' }}>
              <td style={{ padding: '3px 0' }}>{FEATURE_LABELS[key] || key}</td>
              <td style={{ textAlign: 'right', fontWeight: 500 }}>{val.toLocaleString()}</td>
              {seg.stats && (
                <td style={{ textAlign: 'right', color: '#64748b' }}>
                  {(seg.stats[key]?.mean ?? '—').toLocaleString()}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ElbowChart({ elbow }) {
  return (
    <div className="chart-card">
      <h2 className="chart-title">Método del Codo — Selección de k</h2>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        {/* Inercia */}
        <div style={{ flex: 1, minWidth: 260 }}>
          <p style={{ margin: '0 0 8px', fontWeight: 600, fontSize: '0.85rem', color: '#64748b' }}>
            Inercia (↓ mejor)
          </p>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={elbow} margin={{ top: 0, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="k" label={{ value: 'k', position: 'insideBottom', offset: -2 }} />
              <YAxis tickFormatter={v => (v / 1e6).toFixed(1) + 'M'} />
              <Tooltip formatter={v => v.toLocaleString()} />
              <Bar dataKey="inertia" fill="#2563eb" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        {/* Silhouette */}
        <div style={{ flex: 1, minWidth: 260 }}>
          <p style={{ margin: '0 0 8px', fontWeight: 600, fontSize: '0.85rem', color: '#64748b' }}>
            Silhouette Score (↑ mejor)
          </p>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={elbow} margin={{ top: 0, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="k" label={{ value: 'k', position: 'insideBottom', offset: -2 }} />
              <YAxis domain={[0, 1]} />
              <Tooltip formatter={v => v.toFixed(4)} />
              <Bar dataKey="silhouette" radius={[4, 4, 0, 0]}>
                {elbow.map((e, i) => (
                  <Cell key={i} fill={e.silhouette === Math.max(...elbow.map(x => x.silhouette))
                    ? '#16a34a' : '#94a3b8'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}

function ScatterSegments({ sample, segments }) {
  // Agrupar la muestra por segmento
  const grouped = {}
  for (const pt of sample) {
    const sid = pt.segment_id
    if (!grouped[sid]) grouped[sid] = []
    grouped[sid].push({ x: pt.purchase_frequency, y: pt.total_units })
  }

  const segLabels = Object.fromEntries(segments.map(s => [s.segment_id, s.label]))

  return (
    <div className="chart-card">
      <h2 className="chart-title">Scatter de Clientes — Frec. Compra vs Total Unidades</h2>
      <p style={{ margin: '0 0 12px', fontSize: '0.82rem', color: '#64748b' }}>
        Muestra de {sample.length} clientes coloreados por segmento
      </p>
      <ResponsiveContainer width="100%" height={380}>
        <ScatterChart margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis
            dataKey="x"
            name="Frec. Compra"
            label={{ value: 'Frecuencia de compra', position: 'insideBottom', offset: -5 }}
            type="number"
          />
          <YAxis
            dataKey="y"
            name="Total Unidades"
            label={{ value: 'Total unidades', angle: -90, position: 'insideLeft' }}
            type="number"
          />
          <Tooltip
            cursor={{ strokeDasharray: '3 3' }}
            content={({ payload }) => {
              if (!payload?.length) return null
              const { x, y } = payload[0].payload
              return (
                <div className="custom-tooltip">
                  <p>Frec. compra: <b>{x}</b></p>
                  <p>Total unidades: <b>{y}</b></p>
                </div>
              )
            }}
          />
          <Legend />
          {Object.entries(grouped).map(([sid, pts]) => (
            <Scatter
              key={sid}
              name={`Seg. ${parseInt(sid) + 1}: ${segLabels[parseInt(sid)] || ''}`}
              data={pts}
              fill={SEG_COLORS[parseInt(sid) % SEG_COLORS.length]}
              opacity={0.6}
            />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  )
}

function RadarSegments({ segments }) {
  // Normalizar centroid values para el radar (0–100)
  const featureKeys = ['purchase_frequency', 'total_units', 'avg_basket_size',
                       'category_diversity', 'active_days']
  const maxVals = {}
  for (const key of featureKeys) {
    maxVals[key] = Math.max(...segments.map(s => s.centroid[key] || 0)) || 1
  }

  const radarData = featureKeys.map(key => {
    const point = { feature: FEATURE_LABELS[key] || key }
    segments.forEach(seg => {
      point[`seg${seg.segment_id}`] = Math.round((seg.centroid[key] / maxVals[key]) * 100)
    })
    return point
  })

  return (
    <div className="chart-card">
      <h2 className="chart-title">Perfil de Segmentos — Comparativa Radar</h2>
      <ResponsiveContainer width="100%" height={360}>
        <RadarChart data={radarData}>
          <PolarGrid />
          <PolarAngleAxis dataKey="feature" tick={{ fontSize: 12 }} />
          <PolarRadiusAxis angle={30} domain={[0, 100]} tick={{ fontSize: 10 }} />
          {segments.map(seg => (
            <Radar
              key={seg.segment_id}
              name={`Seg. ${seg.segment_id + 1}: ${seg.label}`}
              dataKey={`seg${seg.segment_id}`}
              stroke={SEG_COLORS[seg.segment_id % SEG_COLORS.length]}
              fill={SEG_COLORS[seg.segment_id % SEG_COLORS.length]}
              fillOpacity={0.15}
            />
          ))}
          <Legend />
          <Tooltip formatter={v => `${v}%`} />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Página principal
// ─────────────────────────────────────────────────────────────────────────────

export default function Segments() {
  const [data, setData]     = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]   = useState(null)

  useEffect(() => {
    getSegments()
      .then(res => setData(res.data))
      .catch(() => setError('No hay datos de segmentación. Ejecuta el análisis primero.'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="page-loading">Cargando segmentación…</div>
  if (error)   return <div className="page-error">{error}</div>

  const { k, silhouette_score, total_clients, segments = [],
          elbow_data = [], client_sample = [] } = data

  return (
    <div className="page-container">
      <h1 className="page-title">Segmentación de Clientes</h1>
      <p className="page-subtitle">
        K-Means sobre {total_clients?.toLocaleString()} clientes ·{' '}
        features: frecuencia, unidades, tamaño de cesta, diversidad y días activos
      </p>

      {/* KPIs */}
      <div className="kpi-grid">
        <KpiCard label="Segmentos (k óptimo)" value={k} />
        <KpiCard
          label="Silhouette Score"
          value={silhouette_score?.toFixed(4)}
          sub="Rango 0–1 (>0.5 = buena cohesión)"
        />
        <KpiCard label="Total Clientes" value={total_clients?.toLocaleString()} />
        {segments.map(seg => (
          <KpiCard
            key={seg.segment_id}
            label={`Seg. ${seg.segment_id + 1}: ${seg.label}`}
            value={`${seg.percentage}%`}
            sub={`${seg.size?.toLocaleString()} clientes`}
          />
        ))}
      </div>

      {/* Tarjetas de perfil por segmento */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: 16,
          marginBottom: 24,
        }}
      >
        {segments.map(seg => <SegmentCard key={seg.segment_id} seg={seg} />)}
      </div>

      {/* Radar comparativo */}
      {segments.length > 0 && <RadarSegments segments={segments} />}

      {/* Elbow */}
      {elbow_data.length > 0 && <ElbowChart elbow={elbow_data} />}

      {/* Scatter */}
      {client_sample.length > 0 && (
        <ScatterSegments sample={client_sample} segments={segments} />
      )}
    </div>
  )
}
