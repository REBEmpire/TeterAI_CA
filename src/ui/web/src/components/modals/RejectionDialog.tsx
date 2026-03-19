import { useState } from 'react'
import type { RejectionReason } from '../../types'

const REJECTION_REASONS: { value: RejectionReason; label: string }[] = [
  { value: 'CitationError', label: 'Citation Error' },
  { value: 'ContentError', label: 'Content Error' },
  { value: 'ToneStyle', label: 'Tone / Style' },
  { value: 'MissingInfo', label: 'Missing Information' },
  { value: 'ScopeIssue', label: 'Scope Issue' },
  { value: 'Other', label: 'Other' },
]

interface Props {
  onConfirm: (reason: RejectionReason, notes: string) => void
  onCancel: () => void
  loading?: boolean
}

export function RejectionDialog({ onConfirm, onCancel, loading }: Props) {
  const [reason, setReason] = useState<RejectionReason>('ContentError')
  const [notes, setNotes] = useState('')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-md p-6">
        {/* Header with orange accent */}
        <div className="flex items-center gap-3 mb-5">
          <span className="w-1 h-6 bg-teter-orange rounded-sm" />
          <h2 className="text-teter-dark font-semibold text-lg">Reject Draft</h2>
        </div>

        <div className="flex flex-col gap-4">
          <div>
            <label className="label">Rejection Reason *</label>
            <select
              className="select"
              value={reason}
              onChange={(e) => setReason(e.target.value as RejectionReason)}
            >
              {REJECTION_REASONS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="label">Notes (optional)</label>
            <textarea
              className="input resize-none"
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Provide specific feedback for the agent to improve the draft…"
            />
          </div>
        </div>

        <div className="flex justify-end gap-3 mt-6">
          <button className="btn-outline" onClick={onCancel} disabled={loading}>
            Cancel
          </button>
          <button
            className="btn-danger"
            onClick={() => onConfirm(reason, notes)}
            disabled={loading}
          >
            {loading ? 'Rejecting…' : 'Reject and Send Back'}
          </button>
        </div>
      </div>
    </div>
  )
}
