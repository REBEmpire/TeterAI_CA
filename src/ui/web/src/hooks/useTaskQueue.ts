/**
 * Real-time Firestore listener for the reviewable task queue.
 *
 * Subscribes to all tasks with status IN [STAGED_FOR_REVIEW, ESCALATED_TO_HUMAN].
 * Updates the local state within < 2 s of Firestore writes.
 */
import { useEffect, useState } from 'react'
import {
  collection,
  onSnapshot,
  query,
  where,
  type Unsubscribe,
} from 'firebase/firestore'
import { db } from '../firebase'
import type { TaskSummary, Urgency } from '../types'

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

  useEffect(() => {
    if (!db) {
      setLoading(false)
      return
    }

    setLoading(true)
    let q = query(
      collection(db, 'tasks'),
      where('status', 'in', ['STAGED_FOR_REVIEW', 'ESCALATED_TO_HUMAN']),
    )

    if (filters?.project) {
      q = query(q, where('project_number', '==', filters.project))
    }
    if (filters?.docType) {
      q = query(q, where('document_type', '==', filters.docType))
    }
    if (filters?.urgency) {
      q = query(q, where('urgency', '==', filters.urgency))
    }

    const unsub: Unsubscribe = onSnapshot(
      q,
      (snapshot) => {
        const items: TaskSummary[] = snapshot.docs.map((doc) => ({
          task_id: doc.id,
          ...(doc.data() as Omit<TaskSummary, 'task_id'>),
        }))
        setTasks(sortTasks(items))
        setLoading(false)
        setError(null)
      },
      (err) => {
        setError(err)
        setLoading(false)
      },
    )

    return unsub
  }, [filters?.project, filters?.docType, filters?.urgency])

  return { tasks, loading, error }
}
