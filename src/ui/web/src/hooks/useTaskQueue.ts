/**
 * Task queue hook — REST polling for desktop mode.
 *
 * Replaces the Firestore onSnapshot real-time listener with a 5-second
 * polling interval against the local FastAPI backend. This works in both
 * desktop and cloud modes since the REST API is always available.
 */
import { useEffect, useState, useCallback } from 'react'
import { listTasks } from '../api/client'
import type { TaskSummary, Urgency } from '../types'

const POLL_INTERVAL_MS = 5000

const URGENCY_ORDER: Record<Urgency, number> = { HIGH: 0, MEDIUM: 1, LOW: 2 }

function sortTasks(tasks: TaskSummary[]): TaskSummary[] {
  return [...tasks].sort((a, b) => {
    const urgDiff =
      (URGENCY_ORDER[a.urgency] ?? 9) - (URGENCY_ORDER[b.urgency] ?? 9)
    if (urgDiff !== 0) return urgDiff
    const aTime = a.created_at ? new Date(a.created_at).getTime() : 0
    const bTime = b.created_at ? new Date(b.created_at).getTime() : 0
    return aTime - bTime  // oldest first
  })
}

export function useTaskQueue(filters?: {
  project?: string
  docType?: string
  urgency?: string
}) {
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)

  const fetchTasks = useCallback(async () => {
    try {
      const data = await listTasks({
        project: filters?.project,
        doc_type: filters?.docType,
        urgency: filters?.urgency,
      })
      setTasks(sortTasks(data))
      setError(null)
    } catch (err) {
      setError(err as Error)
    } finally {
      setLoading(false)
    }
  }, [filters?.project, filters?.docType, filters?.urgency])

  useEffect(() => {
    setLoading(true)
    fetchTasks()
    const interval = setInterval(fetchTasks, POLL_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [fetchTasks])

  return { tasks, loading, error }
}
