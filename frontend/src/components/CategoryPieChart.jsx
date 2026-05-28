import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts'

const COLORS = [
  '#2563eb','#10b981','#f59e0b','#ef4444','#8b5cf6',
  '#06b6d4','#ec4899','#84cc16','#f97316','#64748b',
]

export default function CategoryPieChart({ data, nameKey = 'name', valueKey = 'total_units', title, maxSlices = 9 }) {
  if (!data?.length) return null

  // Top N + Otros
  const sorted = [...data].sort((a, b) => b[valueKey] - a[valueKey])
  const top    = sorted.slice(0, maxSlices)
  const rest   = sorted.slice(maxSlices)
  const pieData = rest.length
    ? [...top, { [nameKey]: 'Otros', [valueKey]: rest.reduce((s, d) => s + d[valueKey], 0) }]
    : top

  return (
    <div className="card">
      {title && <div className="card-title">{title}</div>}
      <ResponsiveContainer width="100%" height={320}>
        <PieChart>
          <Pie
            data={pieData}
            dataKey={valueKey}
            nameKey={nameKey}
            cx="50%"
            cy="45%"
            outerRadius={110}
            label={({ name, percent }) => `${name} (${(percent * 100).toFixed(1)}%)`}
            labelLine={false}
          >
            {pieData.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip formatter={v => v.toLocaleString()} />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}
