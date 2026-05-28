const COLORS = [
  '#2563eb','#10b981','#f59e0b','#ef4444','#8b5cf6',
  '#06b6d4','#ec4899','#84cc16','#f97316','#6366f1',
]

export default function KPICard({ label, value, sub, colorIndex = 0 }) {
  const color = COLORS[colorIndex % COLORS.length]
  return (
    <div className="kpi-card" style={{ borderTopColor: color }}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value" style={{ color }}>{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  )
}
