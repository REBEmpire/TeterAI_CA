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
