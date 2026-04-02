import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listProjects } from '../api/client'
import type { ProjectSummary } from '../types'

export function CloseoutPicker() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    listProjects()
      .then((all) => {
        const closeoutProjects = all.filter((p) => p.phase === 'closeout' && p.active)
        setProjects(closeoutProjects)
        // Auto-navigate if only one closeout project
        if (closeoutProjects.length === 1) {
          navigate(`/projects/${closeoutProjects[0].project_id}/closeout`, { replace: true })
        }
      })
      .finally(() => setLoading(false))
  }, [navigate])

  if (loading) {
    return (
      <div className="max-w-wide mx-auto px-4 py-6">
        <div className="text-sm text-teter-gray-text">Loading projects...</div>
      </div>
    )
  }

  if (projects.length === 0) {
    return (
      <div className="max-w-wide mx-auto px-4 py-6">
        <div className="flex items-center gap-3 mb-6">
          <span className="w-1 h-8 bg-teter-orange rounded-sm" />
          <div>
            <h1 className="text-xl font-semibold text-teter-dark">Closeout Review</h1>
            <p className="text-sm text-teter-gray-text mt-0.5">No projects are currently in closeout phase.</p>
          </div>
        </div>
        <p className="text-sm text-teter-gray-text">
          To begin closeout, go to <button className="text-teter-orange hover:underline font-semibold" onClick={() => navigate('/admin')}>Admin</button> and transition a project to the Closeout phase.
        </p>
      </div>
    )
  }

  return (
    <div className="max-w-wide mx-auto px-4 py-6">
      <div className="flex items-center gap-3 mb-6">
        <span className="w-1 h-8 bg-teter-orange rounded-sm" />
        <div>
          <h1 className="text-xl font-semibold text-teter-dark">Closeout Review</h1>
          <p className="text-sm text-teter-gray-text mt-0.5">Select a project to review closeout status</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {projects.map((p) => (
          <button
            key={p.project_id}
            className="bg-white rounded border border-teter-gray-mid shadow-card p-5 text-left hover:border-teter-orange transition-colors group"
            onClick={() => navigate(`/projects/${p.project_id}/closeout`)}
          >
            <div className="text-xs font-semibold text-teter-orange mb-1">{p.project_number}</div>
            <div className="text-sm font-semibold text-teter-dark group-hover:text-teter-orange transition-colors">
              {p.name}
            </div>
            <div className="text-xs text-teter-gray-text mt-2 uppercase font-semibold">Closeout Phase</div>
          </button>
        ))}
      </div>
    </div>
  )
}
