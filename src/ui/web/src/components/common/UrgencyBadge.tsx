import { urgencyClasses } from '../../theme/teter'
import type { Urgency } from '../../types'

interface Props {
  urgency: Urgency
  showDot?: boolean
}

export function UrgencyBadge({ urgency, showDot = true }: Props) {
  const { bg, text, dot } = urgencyClasses(urgency)
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold uppercase tracking-wide ${bg} ${text}`}
    >
      {showDot && (
        <span
          className={`w-2 h-2 rounded-full ${dot} ${urgency === 'HIGH' ? 'animate-urgency-pulse' : ''}`}
        />
      )}
      {urgency}
    </span>
  )
}
