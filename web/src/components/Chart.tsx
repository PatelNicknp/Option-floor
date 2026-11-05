import type { ChartPoint } from "../types"

const LINES: { key: keyof ChartPoint; label: string; color: string; width: number }[] = [
  { key: "ma200", label: "200 day", color: "#c0392b", width: 1.4 },
  { key: "ma150", label: "150 day", color: "#d6a312", width: 1.4 },
  { key: "ma50", label: "50 day", color: "#2a6fdb", width: 1.6 },
  { key: "ma20", label: "20 day", color: "#e07a2f", width: 1.6 },
  { key: "ma10", label: "10 day", color: "#1b7a49", width: 1.8 },
  { key: "c", label: "Price", color: "#221c16", width: 2.2 },
]

export function PriceChart({ points, label }: { points: ChartPoint[]; label: string }) {
  if (!points.length) return <p className="text-sm text-muted">No daily chart was saved for this idea.</p>
  const width = 640
  const height = 180
  const pad = 8
  const values = points.flatMap((point) => LINES.map((line) => point[line.key])).filter((value): value is number => typeof value === "number")
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const x = (index: number) => pad + (index / Math.max(1, points.length - 1)) * (width - pad * 2)
  const y = (value: number) => pad + (1 - (value - min) / span) * (height - pad * 2)

  return (
    <figure>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label} className="h-40 w-full">
        {LINES.map((line) => {
          let path = ""
          points.forEach((point, index) => {
            const value = point[line.key]
            if (typeof value !== "number") return
            path += `${path ? "L" : "M"}${x(index).toFixed(1)},${y(value).toFixed(1)} `
          })
          if (!path) return null
          return <path key={line.key} d={path.trim()} fill="none" stroke={line.color} strokeWidth={line.width} />
        })}
      </svg>
      <figcaption className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
        {LINES.map((line) => (
          <span key={line.key} className="inline-flex items-center gap-1">
            <span className="inline-block h-2 w-4 rounded-sm" style={{ background: line.color }} />
            {line.label}
          </span>
        ))}
      </figcaption>
    </figure>
  )
}

export function ChartLegend() {
  return (
    <ul className="grid gap-2 text-sm sm:grid-cols-2">
      <li><span className="mr-2 inline-block h-2 w-4 rounded-sm bg-[#1b7a49]" />10 day average, green</li>
      <li><span className="mr-2 inline-block h-2 w-4 rounded-sm bg-[#e07a2f]" />20 day average, orange</li>
      <li><span className="mr-2 inline-block h-2 w-4 rounded-sm bg-[#2a6fdb]" />50 day average, blue</li>
      <li><span className="mr-2 inline-block h-2 w-4 rounded-sm bg-[#d6a312]" />150 day average, yellow</li>
      <li><span className="mr-2 inline-block h-2 w-4 rounded-sm bg-[#c0392b]" />200 day average, red</li>
      <li><span className="mr-2 inline-block h-2 w-4 rounded-sm bg-ink" />Daily closing price</li>
    </ul>
  )
}
