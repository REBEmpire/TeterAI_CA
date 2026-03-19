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
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-semibold uppercase ${bg} ${text}`}
    >
      {showDot && <span className={`w-1.5 h-1.5 rounded-full ${dot}`} />}
      {urgency}
    </span>
  )
}
