import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Cell, ResponsiveContainer, LabelList,
} from 'recharts'

const PALETTE = [
  '#2563eb','#3b82f6','#60a5fa','#93c5fd','#bfdbfe',
  '#10b981','#34d399','#6ee7b7','#a7f3d0','#d1fae5',
]

export default function HorizontalBarChart({ data, nameKey = 'name', valueKey = 'value', title }) {
  if (!data?.length) return null
  return (
    <div className="card">
      {title && <div className="card-title">{title}</div>}
      <ResponsiveContainer width="100%" height={Math.max(260, data.length * 36)}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 60, left: 8, bottom: 4 }}
        >
          <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={v => v.toLocaleString()} />
          <YAxis
            type="category"
            dataKey={nameKey}
            width={140}
            tick={{ fontSize: 11 }}
            tickLine={false}
          />
          <Tooltip formatter={v => v.toLocaleString()} />
          <Bar dataKey={valueKey} radius={[0, 4, 4, 0]}>
            {data.map((_, i) => (
              <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
            ))}
            <LabelList dataKey={valueKey} position="right" style={{ fontSize: 11 }} formatter={v => v.toLocaleString()} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
