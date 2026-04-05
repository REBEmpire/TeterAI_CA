<<<<<<< SEARCH
import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '../../hooks/useAuth'
import { RoleGuard } from '../common/RoleGuard'

const DESKTOP_MODE = import.meta.env.VITE_DESKTOP_MODE === 'true'
=======
import { Link, useLocation } from 'react-router-dom'
import { useState, useEffect } from 'react'
import { useAuth } from '../../hooks/useAuth'
import { RoleGuard } from '../common/RoleGuard'
import { apiClient } from '../../api/client'
import { SystemHealth } from '../../types'

const DESKTOP_MODE = import.meta.env.VITE_DESKTOP_MODE === 'true'

function HealthIndicator() {
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!DESKTOP_MODE) return;
    const fetchHealth = () => {
      apiClient.getHealth()
        .then(setHealth)
        .catch(err => {
          console.error("Health check failed", err);
          setHealth({
            status: 'error',
            last_dispatch_at: null,
            pending_count: 0,
            error_count: 0,
            poll_interval_seconds: 60
          })
        });
    }
    fetchHealth()
    const int = setInterval(fetchHealth, 30000)
    return () => clearInterval(int)
  }, [])

  if (!DESKTOP_MODE || !health) return null;

  let colorClass = 'bg-green-500'
  if (health.status === 'degraded') colorClass = 'bg-yellow-500'
  if (health.status === 'error') colorClass = 'bg-red-500'

  return (
    <div className="relative ml-4 flex items-center">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center justify-center w-6 h-6 rounded-full hover:bg-white/10 transition-colors cursor-pointer"
        title="System Health"
      >
        <span className={`w-2.5 h-2.5 rounded-full ${colorClass} shadow-[0_0_8px_rgba(255,255,255,0.3)]`}></span>
      </button>

      {open && (
        <div className="absolute top-8 left-0 w-64 p-3 bg-[#2a2a2a] border border-white/10 rounded-lg shadow-xl z-50 text-sm">
          <div className="flex justify-between items-center mb-2 pb-2 border-b border-white/10">
            <span className="font-semibold text-white">System Status</span>
            <span className={`text-xs px-2 py-0.5 rounded-full text-white/90 ${colorClass}`}>
              {health.status.toUpperCase()}
            </span>
          </div>
          <div className="space-y-1.5 text-white/80">
            <div className="flex justify-between">
              <span>Last poll:</span>
              <span className="text-white">
                {health.last_dispatch_at ? new Date(health.last_dispatch_at).toLocaleTimeString() : 'Never'}
              </span>
            </div>
            <div className="flex justify-between">
              <span>Poll interval:</span>
              <span className="text-white">{health.poll_interval_seconds}s</span>
            </div>
            <div className="flex justify-between">
              <span>Pending tasks:</span>
              <span className="text-white">{health.pending_count}</span>
            </div>
            <div className="flex justify-between text-red-300">
              <span>Error tasks:</span>
              <span>{health.error_count}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
>>>>>>> REPLACE
<<<<<<< SEARCH
        {/* Brand mark */}
        <Link to="/dashboard" className="flex items-center gap-3 mr-6 group">
          <span className="w-[3px] h-9 bg-teter-orange rounded-sm transition-all duration-200 group-hover:h-10" />
          <span className="font-semibold text-base tracking-tight text-white leading-none">
            Teter<span className="text-teter-orange">AI</span>
            <span className="block text-[10px] font-normal text-white/45 tracking-widest uppercase mt-0.5">
              Construction Administration
            </span>
          </span>
        </Link>
=======
        {/* Brand mark */}
        <Link to="/dashboard" className="flex items-center gap-3 mr-2 group">
          <span className="w-[3px] h-9 bg-teter-orange rounded-sm transition-all duration-200 group-hover:h-10" />
          <span className="font-semibold text-base tracking-tight text-white leading-none">
            Teter<span className="text-teter-orange">AI</span>
            <span className="block text-[10px] font-normal text-white/45 tracking-widest uppercase mt-0.5">
              Construction Administration
            </span>
          </span>
        </Link>
        <HealthIndicator />
>>>>>>> REPLACE
