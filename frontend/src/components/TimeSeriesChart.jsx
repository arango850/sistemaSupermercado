import { useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'

const STORE_COLORS = {
  '102': '#2563eb',
  '103': '#10b981',
  '107': '#f59e0b',
  '110': '#ef4444',
}

export default function TimeSeriesChart({ data }) {
  const [period, setPeriod] = useState('daily')
  const [metric, setMetric] = useState('transactions')

  if (!data) return null

  // data[period] tiene claves num_transactions / total_units
  const periodData = data[period] ?? []

  // by_store_daily es formato largo [{date, store_id, num_transactions}]
  // Lo transformamos a formato ancho [{date, '102': n, '103': n, ...}]
  const byStore = period === 'daily'
    ? (() => {
        const raw = data.by_store_daily ?? []
        const map = {}
        raw.forEach(({ date, store_id, num_transactions }) => {
          if (!map[date]) map[date] = { date }
          map[date][String(store_id)] = num_transactions
        })
        return Object.values(map).sort((a, b) => a.date.localeCompare(b.date))
      })()
    : null

  return (
    <div className="card">
      <div className="card-title">Serie Temporal de Actividad</div>

      <div style={{ display: 'flex', gap: 24, marginBottom: 12, flexWrap: 'wrap' }}>
        <div className="tab-bar">
          {['daily', 'weekly', 'monthly'].map(p => (
            <button key={p} className={`tab-btn${period === p ? ' active' : ''}`} onClick={() => setPeriod(p)}>
              {{ daily: 'Diario', weekly: 'Semanal', monthly: 'Mensual' }[p]}
            </button>
          ))}
        </div>
        <div className="tab-bar">
          {['transactions', 'units'].map(m => (
            <button key={m} className={`tab-btn${metric === m ? ' active' : ''}`} onClick={() => setMetric(m)}>
              {{ transactions: 'Transacciones', units: 'Unidades' }[m]}
            </button>
          ))}
        </div>
      </div>

      {/* Gráfico global */}
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={periodData} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="date" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
          <YAxis tick={{ fontSize: 11 }} tickFormatter={v => v.toLocaleString()} width={70} />
          <Tooltip formatter={v => v.toLocaleString()} />
          <Legend />
          <Line
            type="monotone"
            dataKey={metric === 'transactions' ? 'num_transactions' : 'total_units'}
            stroke="#2563eb"
            dot={false}
            strokeWidth={2}
            name={{ transactions: 'Transacciones', units: 'Unidades' }[metric]}
          />
        </LineChart>
      </ResponsiveContainer>

      {/* Gráfico por tienda (solo diario) */}
      {byStore && period === 'daily' && (
        <>
          <div className="card-title" style={{ marginTop: 24 }}>Por Tienda (diario)</div>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={byStore} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={v => v.toLocaleString()} width={70} />
              <Tooltip formatter={v => v.toLocaleString()} />
              <Legend />
              {Object.entries(STORE_COLORS).map(([store, color]) => (
                <Line key={store} type="monotone" dataKey={store} stroke={color}
                  dot={false} strokeWidth={2} name={`Tienda ${store}`} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </>
      )}
    </div>
  )
}
