import { confidenceColor } from '../../theme/teter'

interface Props {
  score: number  // 0.0 – 1.0
  showBar?: boolean
}

export function ConfidenceMeter({ score, showBar = true }: Props) {
  const pct = Math.round(score * 100)
  const colorClass = confidenceColor(score)

  const fillColor =
    score >= 0.8 ? '#2e7d32' : score >= 0.5 ? '#f9a825' : '#c62828'

  return (
    <div className="flex items-center gap-2">
      <span className={`text-sm font-bold ${colorClass}`}>{pct}%</span>
      {showBar && (
        <div className="flex-1 h-2 bg-teter-gray rounded-full overflow-hidden">
          <div
            className="h-full rounded-full animate-bar-fill"
            style={{
              '--bar-width': `${pct}%`,
              backgroundColor: fillColor,
            } as React.CSSProperties}
          />
        </div>
      )}
    </div>
  )
}
