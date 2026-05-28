// weekly_heatmap: { [month]: { [day_of_week]: count } }
// Days: 0=Mon … 6=Sun  /  Months: 1=Jan … 12=Jun

const DAY_LABELS   = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
const MONTH_LABELS = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                      'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

function lerp(a, b, t) {
  return Math.round(a + (b - a) * t)
}

function countToColor(count, max) {
  if (!count) return '#f8fafc'
  const t = count / max
  const r = lerp(219, 37,  t)
  const g = lerp(234, 99,  t)
  const b = lerp(254, 235, t)
  return `rgb(${r},${g},${b})`
}

export default function WeeklyHeatmap({ data, title }) {
  if (!data) return null

  // Transformar lista plana [{month, day_of_week, count}] a dict anidado {month: {day: count}}
  const nested = {}
  const rawList = Array.isArray(data) ? data : []
  rawList.forEach(({ month, day_of_week, count }) => {
    const m = month   // '2013-01'
    if (!nested[m]) nested[m] = {}
    nested[m][day_of_week] = count
  })

  const months = Object.keys(nested).sort()
  let maxVal = 0
  months.forEach(m => Object.values(nested[m]).forEach(v => { if (v > maxVal) maxVal = v }))

  return (
    <div className="card">
      {title && <div className="card-title">{title}</div>}
      <div style={{ overflowX: 'auto' }}>
        <table className="heatmap-table">
          <thead>
            <tr>
              <th>Mes</th>
              {DAY_LABELS.map(d => <th key={d}>{d}</th>)}
            </tr>
          </thead>
          <tbody>
            {months.map(m => (
              <tr key={m}>
                <td style={{ padding: '4px 10px', fontWeight: 600, color: '#64748b' }}>
                  {m}
                </td>
                {[0, 1, 2, 3, 4, 5, 6].map(day => {
                  const count = nested[m]?.[day] ?? 0
                  return (
                    <td key={day}>
                      <div
                        className="heatmap-cell"
                        style={{ background: countToColor(count, maxVal) }}
                        title={`${m} ${DAY_LABELS[day]}: ${count.toLocaleString()}`}
                      >
                        {count > 0 ? count.toLocaleString() : '—'}
                      </div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
