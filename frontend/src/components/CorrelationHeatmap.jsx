/**
 * CorrelationHeatmap — tabla de correlación entre 7 features de clientes.
 * Recibe { labels, feature_keys, correlation_matrix }
 * Colores: azul (-1) → blanco (0) → rojo (+1)
 */

function corrToColor(v) {
  if (v == null) return '#f8fafc'
  const t = (v + 1) / 2  // 0..1
  if (t >= 0.5) {
    // 0 → rojo
    const intensity = (t - 0.5) * 2
    const r = Math.round(255)
    const g = Math.round(255 - 180 * intensity)
    const b = Math.round(255 - 220 * intensity)
    return `rgb(${r},${g},${b})`
  } else {
    // azul → 0
    const intensity = (0.5 - t) * 2
    const r = Math.round(255 - 220 * intensity)
    const g = Math.round(255 - 180 * intensity)
    const b = Math.round(255)
    return `rgb(${r},${g},${b})`
  }
}

const LABEL_MAP = {
  purchase_frequency:      'Frec. Compra',
  total_units:             'Total Unid.',
  avg_basket_size:         'Cesta Prom.',
  avg_categories_per_txn:  'Cat./Transac.',
  category_diversity:      'Diversidad',
  num_stores_visited:      'Tiendas',
  active_days:             'Días Activo',
}

export default function CorrelationHeatmap({ data }) {
  if (!data?.correlation_matrix) return null
  const { labels, feature_keys, correlation_matrix } = data

  const shortLabels = feature_keys.map(k => LABEL_MAP[k] ?? k)

  return (
    <div className="card">
      <div className="card-title">Matriz de Correlación — Comportamiento de Clientes</div>
      <div style={{ fontSize: 12, color: '#64748b', marginBottom: 12 }}>
        n = {data.client_features_count?.toLocaleString() ?? '—'} clientes
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table className="corr-table">
          <thead>
            <tr>
              <th></th>
              {shortLabels.map(l => <th key={l}>{l}</th>)}
            </tr>
          </thead>
          <tbody>
            {correlation_matrix.map((row, ri) => (
              <tr key={ri}>
                <th style={{ textAlign: 'right', padding: '4px 8px', fontSize: 10, color: '#64748b' }}>
                  {shortLabels[ri]}
                </th>
                {row.map((val, ci) => (
                  <td key={ci}>
                    <div
                      className="corr-cell"
                      style={{ background: corrToColor(val) }}
                      title={`${shortLabels[ri]} × ${shortLabels[ci]}: ${val?.toFixed(3)}`}
                    >
                      {val?.toFixed(2)}
                    </div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 8 }}>
        Rojo = correlación positiva · Azul = correlación negativa · Blanco = sin correlación
      </div>
    </div>
  )
}
