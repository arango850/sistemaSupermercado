import { useState, useEffect, useRef } from 'react'
import { getRecommendations, getRecommendationsByCategory } from '../api/client'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell,
} from 'recharts'

const LIFT_COLORS = (lift) => {
  if (lift >= 3)   return '#16a34a'
  if (lift >= 2)   return '#2563eb'
  if (lift >= 1.5) return '#d97706'
  return '#64748b'
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-componentes
// ─────────────────────────────────────────────────────────────────────────────

function MetaCards({ meta }) {
  const cards = [
    { label: 'Total reglas',          value: meta.total_rules?.toLocaleString() },
    { label: 'Transacciones analizadas', value: meta.n_transactions?.toLocaleString() },
    { label: 'Soporte mínimo',        value: `${(meta.min_support * 100).toFixed(0)}%` },
    { label: 'Confianza mínima',      value: `${(meta.min_confidence * 100).toFixed(0)}%` },
    { label: 'Lift mínimo',           value: meta.min_lift },
    { label: 'Categorías con reglas', value: meta.categories_with_rules?.length },
  ]
  return (
    <div className="kpi-grid">
      {cards.map(c => (
        <div className="kpi-card" key={c.label}>
          <div className="kpi-value">{c.value ?? '—'}</div>
          <div className="kpi-label">{c.label}</div>
        </div>
      ))}
    </div>
  )
}

function TopRulesChart({ rules }) {
  if (!rules?.length) return null
  const data = rules.slice(0, 15).map(r => ({
    name: `${r.antecedent} → ${r.consequent}`,
    lift: r.lift,
    confidence: r.confidence,
  }))
  return (
    <div className="chart-card">
      <h2 className="chart-title">Top 15 Reglas por Lift</h2>
      <p style={{ margin: '0 0 12px', fontSize: '0.82rem', color: '#64748b' }}>
        Lift = qué tan más probable es comprar B si ya compraste A, comparado con la probabilidad base de B
      </p>
      <ResponsiveContainer width="100%" height={360}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 0, right: 20, left: 230, bottom: 0 }}
        >
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" domain={[0, 'auto']} tickFormatter={v => v.toFixed(1)} />
          <YAxis type="category" dataKey="name" width={220} tick={{ fontSize: 10 }} />
          <Tooltip
            formatter={(val, name) => [
              val.toFixed(3),
              name === 'lift' ? 'Lift' : 'Confianza',
            ]}
          />
          <Bar dataKey="lift" radius={[0, 4, 4, 0]}>
            {data.map((d, i) => (
              <Cell key={i} fill={LIFT_COLORS(d.lift)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function RecommendationResults({ categoryName, recs }) {
  if (!recs?.length) {
    return (
      <div className="chart-card">
        <p style={{ color: '#64748b' }}>
          No se encontraron recomendaciones para <strong>{categoryName}</strong>.
          Prueba otra categoría o verifica que el análisis esté actualizado.
        </p>
      </div>
    )
  }

  const chartData = recs.map(r => ({
    name: r.recommendation,
    confianza: r.confidence,
    lift: r.lift,
  }))

  return (
    <div className="chart-card">
      <h2 className="chart-title">
        Si compraste <span style={{ color: '#2563eb' }}>{categoryName}</span>…
      </h2>
      <p style={{ margin: '0 0 16px', fontSize: '0.82rem', color: '#64748b' }}>
        Categorías frecuentemente compradas en la misma transacción, ordenadas por Lift
      </p>

      {/* Tabla */}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
          <thead>
            <tr style={{ borderBottom: '2px solid #e2e8f0', background: '#f8fafc' }}>
              <th style={{ textAlign: 'left', padding: '8px 12px' }}>#</th>
              <th style={{ textAlign: 'left', padding: '8px 12px' }}>Categoría recomendada</th>
              <th style={{ textAlign: 'right', padding: '8px 12px' }}>Confianza</th>
              <th style={{ textAlign: 'right', padding: '8px 12px' }}>Lift</th>
              <th style={{ textAlign: 'right', padding: '8px 12px' }}>Soporte</th>
            </tr>
          </thead>
          <tbody>
            {recs.map((r, i) => (
              <tr
                key={i}
                style={{ borderBottom: '1px solid #f1f5f9',
                         background: i % 2 === 0 ? '#fff' : '#f8fafc' }}
              >
                <td style={{ padding: '8px 12px', color: '#94a3b8' }}>{i + 1}</td>
                <td style={{ padding: '8px 12px', fontWeight: 500 }}>{r.recommendation}</td>
                <td style={{ padding: '8px 12px', textAlign: 'right' }}>
                  <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    <div
                      style={{
                        width: `${Math.round(r.confidence * 80)}px`,
                        height: 8,
                        background: '#2563eb',
                        borderRadius: 4,
                        opacity: 0.7,
                      }}
                    />
                    {(r.confidence * 100).toFixed(1)}%
                  </div>
                </td>
                <td style={{ padding: '8px 12px', textAlign: 'right' }}>
                  <span
                    style={{
                      background: LIFT_COLORS(r.lift) + '22',
                      color: LIFT_COLORS(r.lift),
                      fontWeight: 700,
                      padding: '2px 8px',
                      borderRadius: 4,
                    }}
                  >
                    {r.lift.toFixed(2)}×
                  </span>
                </td>
                <td style={{ padding: '8px 12px', textAlign: 'right', color: '#64748b' }}>
                  {(r.support * 100).toFixed(2)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mini chart */}
      <div style={{ marginTop: 20 }}>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart
            data={chartData}
            margin={{ top: 0, right: 10, left: 0, bottom: 70 }}
          >
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" angle={-35} textAnchor="end" tick={{ fontSize: 10 }} />
            <YAxis />
            <Tooltip
              formatter={(val, name) => [
                val.toFixed(3),
                name === 'confianza' ? 'Confianza' : 'Lift',
              ]}
            />
            <Bar dataKey="confianza" fill="#2563eb" radius={[4, 4, 0, 0]} name="Confianza" />
            <Bar dataKey="lift" fill="#16a34a" radius={[4, 4, 0, 0]} name="Lift" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function CategoryPopularityChart({ categorySupport }) {
  if (!categorySupport?.length) return null
  const data = categorySupport.slice(0, 20).map(c => ({
    name: c.category_name,
    support: c.support,
    count: c.count,
  }))
  return (
    <div className="chart-card">
      <h2 className="chart-title">Top 20 Categorías más Frecuentes</h2>
      <p style={{ margin: '0 0 12px', fontSize: '0.82rem', color: '#64748b' }}>
        Porcentaje de transacciones que incluyen cada categoría
      </p>
      <ResponsiveContainer width="100%" height={340}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 0, right: 40, left: 200, bottom: 0 }}
        >
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" tickFormatter={v => `${(v * 100).toFixed(0)}%`} />
          <YAxis type="category" dataKey="name" width={190} tick={{ fontSize: 10 }} />
          <Tooltip
            formatter={(val, name) => [
              `${(val * 100).toFixed(2)}%`,
              'Soporte',
            ]}
          />
          <Bar dataKey="support" fill="#2563eb" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Página principal
// ─────────────────────────────────────────────────────────────────────────────

export default function Recommendations() {
  const [meta, setMeta]         = useState(null)
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)

  // búsqueda
  const [query, setQuery]         = useState('')
  const [suggestions, setSuggs]   = useState([])
  const [showSuggs, setShowSuggs] = useState(false)
  const [selected, setSelected]   = useState(null)
  const [recs, setRecs]           = useState(null)
  const [searching, setSearching] = useState(false)
  const inputRef = useRef(null)

  useEffect(() => {
    getRecommendations()
      .then(res => setMeta(res.data))
      .catch(() => setError('No hay datos de recomendaciones. Ejecuta el análisis primero.'))
      .finally(() => setLoading(false))
  }, [])

  // Auto-completado
  useEffect(() => {
    if (!meta?.categories_with_rules || !query.trim()) {
      setSuggs([])
      return
    }
    const q = query.toLowerCase()
    const matches = meta.categories_with_rules
      .filter(c => c.toLowerCase().includes(q))
      .slice(0, 8)
    setSuggs(matches)
  }, [query, meta])

  const handleSearch = async (catName) => {
    if (!catName) return
    setSelected(catName)
    setQuery(catName)
    setShowSuggs(false)
    setSearching(true)
    try {
      const res = await getRecommendationsByCategory(catName)
      setRecs(res.data.recommendations)
    } catch {
      setRecs([])
    } finally {
      setSearching(false)
    }
  }

  if (loading) return <div className="page-loading">Cargando recomendaciones…</div>
  if (error)   return <div className="page-error">{error}</div>

  return (
    <div className="page-container">
      <h1 className="page-title">Recomendaciones de Productos</h1>
      <p className="page-subtitle">
        Reglas de asociación por co-ocurrencia de categorías en transacciones
      </p>

      {meta && <MetaCards meta={meta} />}

      {/* Buscador */}
      <div className="chart-card" style={{ marginBottom: 0 }}>
        <h2 className="chart-title">Buscar recomendaciones por categoría</h2>
        <p style={{ margin: '0 0 12px', fontSize: '0.82rem', color: '#64748b' }}>
          Escribe el nombre de una categoría para ver qué otras categorías se compran junto a ella
        </p>
        <div style={{ position: 'relative', maxWidth: 520 }}>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={e => { setQuery(e.target.value); setShowSuggs(true) }}
            onFocus={() => setShowSuggs(true)}
            onBlur={() => setTimeout(() => setShowSuggs(false), 200)}
            onKeyDown={e => {
              if (e.key === 'Enter' && query.trim()) handleSearch(query.trim())
            }}
            placeholder="Ej: PANES-TOSTADAS, LECHE LIQUIDA…"
            style={{
              width: '100%',
              padding: '10px 14px',
              fontSize: '0.95rem',
              border: '1.5px solid #cbd5e1',
              borderRadius: 8,
              outline: 'none',
              boxSizing: 'border-box',
            }}
          />
          {showSuggs && suggestions.length > 0 && (
            <ul
              style={{
                position: 'absolute',
                top: '100%',
                left: 0,
                right: 0,
                background: '#fff',
                border: '1px solid #e2e8f0',
                borderRadius: 8,
                boxShadow: '0 4px 16px rgba(0,0,0,0.1)',
                listStyle: 'none',
                margin: 0,
                padding: '4px 0',
                zIndex: 100,
              }}
            >
              {suggestions.map(s => (
                <li
                  key={s}
                  onMouseDown={() => handleSearch(s)}
                  style={{
                    padding: '8px 14px',
                    cursor: 'pointer',
                    fontSize: '0.88rem',
                    transition: 'background 0.1s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = '#f1f5f9')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                  {s}
                </li>
              ))}
            </ul>
          )}
        </div>
        <button
          onClick={() => handleSearch(query.trim())}
          disabled={!query.trim() || searching}
          style={{
            marginTop: 12,
            padding: '9px 20px',
            background: '#2563eb',
            color: '#fff',
            border: 'none',
            borderRadius: 8,
            cursor: 'pointer',
            fontSize: '0.9rem',
            opacity: (!query.trim() || searching) ? 0.5 : 1,
          }}
        >
          {searching ? 'Buscando…' : 'Buscar'}
        </button>
      </div>

      {/* Resultados */}
      {selected && !searching && recs !== null && (
        <RecommendationResults categoryName={selected} recs={recs} />
      )}
      {searching && (
        <div className="page-loading" style={{ padding: '20px 0' }}>Buscando…</div>
      )}

      {/* Top reglas globales */}
      {meta?.top_rules && <TopRulesChart rules={meta.top_rules} />}

      {/* Popularidad de categorías */}
      {meta?.category_support && (
        <CategoryPopularityChart categorySupport={meta.category_support} />
      )}
    </div>
  )
}
