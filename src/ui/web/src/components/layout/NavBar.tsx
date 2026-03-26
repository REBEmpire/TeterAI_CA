import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '../../hooks/useAuth'
import { RoleGuard } from '../common/RoleGuard'

const DESKTOP_MODE = import.meta.env.VITE_DESKTOP_MODE === 'true'

/**
 * Top navigation bar — styled to match Teter's #313131 dark header with
 * orange brand accents, mirroring teterae.com's design language.
 */
export function NavBar() {
  const { user, logout } = useAuth()
  const location = useLocation()

  const navLink = (to: string, label: string) => {
    const active = location.pathname.startsWith(to)
    return (
      <Link
        to={to}
        className={`px-4 py-2 text-sm font-semibold rounded transition-colors duration-150 ${
          active
            ? 'text-teter-orange bg-white/10'
            : 'text-white/80 hover:text-white hover:bg-white/10'
        }`}
      >
        {label}
      </Link>
    )
  }

  return (
    <header className="bg-teter-dark text-white sticky top-0 z-40 shadow-md">
      <div className="max-w-wide mx-auto px-4 flex items-center h-14 gap-2">
        {/* Brand mark */}
        <Link to="/dashboard" className="flex items-center gap-3 mr-6">
          {/* Orange accent bar mimicking Teter logo treatment */}
          <span className="w-1 h-8 bg-teter-orange rounded-sm" />
          <span className="font-semibold text-base tracking-wide text-white leading-none">
            Teter<span className="text-teter-orange">AI</span>
            <span className="block text-[10px] font-normal text-white/50 tracking-widest uppercase">
              Construction Administration
            </span>
          </span>
        </Link>

        {/* Nav links */}
        <nav className="flex items-center gap-1">
          {navLink('/dashboard', 'Action Dashboard')}
          {/* Upload nav item — visible in both desktop and cloud modes */}
          <Link
            to="/upload"
            className={`
              flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded
              transition-colors duration-150
              ${location.pathname.startsWith('/upload')
                ? 'text-teter-orange bg-white/10'
                : 'text-white/80 hover:text-white hover:bg-white/10'}
            `}
          >
            {/* Upload arrow icon (inline SVG) */}
            <svg
              className="h-4 w-4 shrink-0"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
              aria-hidden="true"
            >
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
            </svg>
            Upload
          </Link>
          {/* Knowledge Graph nav item */}
          <Link
            to="/knowledge-graph"
            className={`
              flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded
              transition-colors duration-150
              ${location.pathname.startsWith('/knowledge-graph')
                ? 'text-teter-orange bg-white/10'
                : 'text-white/80 hover:text-white hover:bg-white/10'}
            `}
          >
            {/* Network/graph inline SVG icon */}
            <svg
              className="h-4 w-4 shrink-0"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
              aria-hidden="true"
            >
              <circle cx="5"  cy="12" r="2" />
              <circle cx="19" cy="5"  r="2" />
              <circle cx="19" cy="19" r="2" />
              <circle cx="12" cy="12" r="2" />
              <line x1="7"  y1="12" x2="10" y2="12" />
              <line x1="14" y1="12" x2="17" y2="6.5" />
              <line x1="14" y1="12" x2="17" y2="17.5" />
            </svg>
            Knowledge Graph
          </Link>
          {DESKTOP_MODE && navLink('/settings', 'Settings')}
          {!DESKTOP_MODE && (
            <RoleGuard roles={['ADMIN']}>
              {navLink('/admin', 'Admin')}
            </RoleGuard>
          )}
        </nav>

        {/* Right side: user info + logout */}
        <div className="ml-auto flex items-center gap-3">
          {user && (
            <>
              <span className="text-sm text-white/70 hidden sm:block">
                {user.display_name}
              </span>
              <span className="text-xs px-2 py-0.5 rounded bg-teter-orange/20 text-teter-orange-light font-semibold uppercase">
                {user.role.replace('_', ' ')}
              </span>
              <button
                onClick={logout}
                className="text-sm text-white/60 hover:text-white transition-colors"
              >
                Logout
              </button>
            </>
          )}
        </div>
      </div>
    </header>
  )
}
