import { confidenceColor } from '../../theme/teter'

interface Props {
  score: number  // 0.0 – 1.0
  showBar?: boolean
}

export function ConfidenceMeter({ score, showBar = true }: Props) {
  const pct = Math.round(score * 100)
  const colorClass = confidenceColor(score)

  // Bar fill color (Tailwind can't interpolate values at runtime so use style)
  const fillColor =
    score >= 0.8 ? '#2e7d32' : score >= 0.5 ? '#f9a825' : '#c62828'

  return (
    <div className="flex items-center gap-2">
      <span className={`text-sm font-semibold ${colorClass}`}>{pct}%</span>
      {showBar && (
        <div className="flex-1 h-1.5 bg-teter-gray rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-300"
            style={{ width: `${pct}%`, backgroundColor: fillColor }}
          />
        </div>
      )}
    </div>
  )
}
